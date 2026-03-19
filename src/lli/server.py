"""
FastAPI server for the LLM Interceptor UI.

Serves the React frontend and provides API endpoints for session data.
"""

import json
import logging
import mimetypes
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lli.watch import WatchManager

# Get logger
logger = logging.getLogger("llm_interceptor.server")
SESSION_METADATA_FILE = "session_meta.json"
SESSION_ANNOTATIONS_FILE = "annotations.json"


def _ensure_static_mime_types():
    """Force correct MIME types for static assets (especially on Windows)."""
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")


class SessionSummary(BaseModel):
    """Summary information for a session."""

    id: str
    timestamp: datetime
    request_count: int
    total_latency_ms: float
    total_tokens: int
    duration_ms: int = 0
    failed_count: int = 0


class AnnotationData(BaseModel):
    """Annotation data for a session."""

    session_note: str = ""
    requests: dict[str, str] = {}  # key: sequenceId (e.g., "001"), value: note


class WatchStatus(BaseModel):
    """High-level watch-mode status for the UI."""

    output_dir: str
    has_sessions: bool
    active: bool
    session_id: str | None = None


class ServerState:
    """Shared state for the API server."""

    def __init__(self, watch_manager: WatchManager):
        self.watch_manager = watch_manager
        self._session_cache: dict[str, tuple[float, SessionSummary]] = {}


SESSION_ID_TIMESTAMP_RE = re.compile(r"^session_(\d{8}_\d{6})(?:_\d+)?$")
SPLIT_FILE_TIMESTAMP_RE = re.compile(
    r"^\d+_(?:request|response)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.json$"
)


def _parse_iso_datetime(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a naive (UTC) datetime."""
    if not isinstance(value, str) or not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.replace(tzinfo=None)
    except ValueError:
        return None


def _parse_session_timestamp(session_id: str) -> datetime | None:
    """Parse timestamps from session directory names, including collision suffixes."""
    match = SESSION_ID_TIMESTAMP_RE.match(session_id)
    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _parse_split_filename_timestamp(filename: str) -> datetime | None:
    """Parse timestamps embedded in split request/response filenames."""
    match = SPLIT_FILE_TIMESTAMP_RE.match(filename)
    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None


def _read_session_metadata_timestamp(session_dir: Path) -> datetime | None:
    """Read the persisted session start time, if available."""
    metadata_path = session_dir / SESSION_METADATA_FILE
    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read session metadata %s: %s", metadata_path, exc)
        return None

    if not isinstance(payload, dict):
        return None

    return _parse_iso_datetime(payload.get("started_at"))


def _is_session_dir(path: Path) -> bool:
    """Best-effort detection for captured session directories."""
    if not path.is_dir():
        return False

    if (path / SESSION_METADATA_FILE).exists() or (path / SESSION_ANNOTATIONS_FILE).exists():
        return True

    if _parse_session_timestamp(path.name) is not None:
        return True

    return any(path.glob("*.json"))


def _summarize_session_dir(session_dir: Path) -> SessionSummary:
    """
    Build a stable session summary from directory contents.

    We prefer persisted session metadata so renaming the folder does not affect
    displayed time. If metadata is unavailable, fall back to timestamps from the
    captured files, then filename timestamps, then legacy directory-name parsing,
    and finally stable filesystem metadata instead of `now()`.
    """
    request_count = 0
    total_latency_ms = 0.0
    total_tokens = 0
    failed_count = 0
    earliest_timestamp: datetime | None = _read_session_metadata_timestamp(session_dir)
    latest_timestamp: datetime | None = None
    oldest_file_timestamp: datetime | None = None
    oldest_record_file_mtime: datetime | None = None

    for file_path in sorted(session_dir.glob("*.json")):
        if file_path.name in {SESSION_ANNOTATIONS_FILE, SESSION_METADATA_FILE}:
            continue

        file_stat = file_path.stat()
        file_mtime = datetime.fromtimestamp(file_stat.st_mtime)
        if oldest_record_file_mtime is None or file_mtime < oldest_record_file_mtime:
            oldest_record_file_mtime = file_mtime

        filename_timestamp = _parse_split_filename_timestamp(file_path.name)
        if filename_timestamp is not None:
            if earliest_timestamp is None or filename_timestamp < earliest_timestamp:
                earliest_timestamp = filename_timestamp
            if oldest_file_timestamp is None or filename_timestamp < oldest_file_timestamp:
                oldest_file_timestamp = filename_timestamp
            if latest_timestamp is None or filename_timestamp > latest_timestamp:
                latest_timestamp = filename_timestamp

        try:
            with open(file_path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read session file %s: %s", file_path, exc)
            continue

        if not isinstance(payload, dict):
            continue

        record_type = payload.get("type")
        record_timestamp = _parse_iso_datetime(payload.get("timestamp"))
        if record_timestamp is not None:
            if earliest_timestamp is None or record_timestamp < earliest_timestamp:
                earliest_timestamp = record_timestamp
            if latest_timestamp is None or record_timestamp > latest_timestamp:
                latest_timestamp = record_timestamp

        if record_type == "request":
            request_count += 1
            usage = payload.get("usage")
            if isinstance(usage, dict):
                total_value = usage.get("total_tokens")
                if isinstance(total_value, int | float):
                    total_tokens += int(total_value)
        elif record_type == "response":
            status_code = payload.get("status_code")
            if isinstance(status_code, int | float) and int(status_code) >= 400:
                failed_count += 1
            elif status_code is None:
                failed_count += 1

            latency_ms = payload.get("latency_ms")
            if isinstance(latency_ms, int | float):
                total_latency_ms += float(latency_ms)

            body = payload.get("body")
            if isinstance(body, dict):
                usage = body.get("usage")
                if isinstance(usage, dict):
                    total_value = usage.get("total_tokens")
                    if isinstance(total_value, int | float):
                        total_tokens += int(total_value)

    parsed_timestamp = _parse_session_timestamp(session_dir.name)
    if earliest_timestamp is None:
        if oldest_file_timestamp is not None:
            earliest_timestamp = oldest_file_timestamp
            latest_timestamp = latest_timestamp or oldest_file_timestamp
        elif parsed_timestamp is not None:
            earliest_timestamp = parsed_timestamp
            latest_timestamp = latest_timestamp or parsed_timestamp
        elif oldest_record_file_mtime is not None:
            earliest_timestamp = oldest_record_file_mtime
            latest_timestamp = latest_timestamp or oldest_record_file_mtime
        else:
            fallback_timestamp = datetime.fromtimestamp(session_dir.stat().st_mtime)
            earliest_timestamp = fallback_timestamp
            latest_timestamp = latest_timestamp or fallback_timestamp

    duration_ms = 0
    if latest_timestamp is not None and earliest_timestamp is not None:
        duration_ms = max(
            int((latest_timestamp - earliest_timestamp).total_seconds() * 1000),
            0,
        )

    return SessionSummary(
        id=session_dir.name,
        timestamp=earliest_timestamp,
        request_count=request_count,
        total_latency_ms=total_latency_ms,
        total_tokens=total_tokens,
        duration_ms=duration_ms,
        failed_count=failed_count,
    )


def create_app(watch_manager: WatchManager) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="LLM Interceptor API")
    state = ServerState(watch_manager)

    # Enable CORS for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # For dev only, restrict in prod if needed
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API Endpoints

    @app.get("/api/status", response_model=WatchStatus)
    def get_status():
        """Get watch-mode status metadata for the UI."""
        traces_dir = state.watch_manager.output_dir
        has_sessions = False
        if traces_dir.exists():
            has_sessions = any(p.is_dir() for p in traces_dir.glob("session_*"))

        current_session = state.watch_manager.current_session
        return WatchStatus(
            output_dir=str(traces_dir),
            has_sessions=has_sessions,
            active=current_session is not None,
            session_id=current_session.session_id if current_session else None,
        )

    @app.get("/api/sessions", response_model=list[SessionSummary])
    def list_sessions():
        """List all captured sessions with mtime-based caching."""
        traces_dir = state.watch_manager.output_dir

        if not traces_dir.exists():
            return []

        session_dirs = [p for p in traces_dir.iterdir() if _is_session_dir(p)]
        sessions: list[SessionSummary] = []
        new_cache: dict[str, tuple[float, SessionSummary]] = {}

        for path in session_dirs:
            try:
                dir_mtime = path.stat().st_mtime
            except OSError:
                continue

            cached = state._session_cache.get(path.name)
            if cached is not None and cached[0] == dir_mtime:
                new_cache[path.name] = cached
                sessions.append(cached[1])
            else:
                summary = _summarize_session_dir(path)
                new_cache[path.name] = (dir_mtime, summary)
                sessions.append(summary)

        state._session_cache = new_cache
        sessions.sort(key=lambda session: (session.timestamp, session.id))
        return sessions

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        """Get full details for a specific session."""
        session_dir = state.watch_manager.output_dir / session_id

        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="Session not found")

        # Load all request/response pairs
        pairs = {}

        for file_path in sorted(session_dir.glob("*.json")):
            try:
                parts = file_path.stem.split("_")
                if len(parts) < 2:
                    continue

                seq_id = parts[0]
                msg_type = parts[1]  # request or response

                if seq_id not in pairs:
                    pairs[seq_id] = {"request": None, "response": None}

                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    pairs[seq_id][msg_type] = data

            except Exception as e:
                logger.error(f"Error reading {file_path}: {e}")

        # Convert to list
        result = []
        for seq_id in sorted(pairs.keys()):
            result.append(pairs[seq_id])

        return {"id": session_id, "pairs": result}

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        """Delete a captured session and all local files under it."""
        session_dir = state.watch_manager.output_dir / session_id

        if not session_dir.exists() or not session_dir.is_dir():
            raise HTTPException(status_code=404, detail="Session not found")

        try:
            shutil.rmtree(session_dir)
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete session") from e

        return {"ok": True}

    @app.get("/api/active")
    async def get_active_session():
        """Get data for the currently active recording session."""
        current_session = state.watch_manager.current_session

        if not current_session:
            return {"active": False, "session_id": None, "pairs": []}

        # If recording, we need to extract and merge from the global log on-the-fly
        # This is a bit complex, for now we'll return basic info
        # A full implementation would reuse StreamMerger logic here

        return {
            "active": True,
            "session_id": current_session.session_id,
            "pairs": [],  # TODO: Implement real-time merging
        }

    @app.get("/api/sessions/{session_id}/annotations", response_model=AnnotationData)
    def get_annotations(session_id: str):
        """Get annotations for a specific session."""
        session_dir = state.watch_manager.output_dir / session_id

        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="Session not found")

        annotations_file = session_dir / "annotations.json"

        if not annotations_file.exists():
            return AnnotationData()

        try:
            with open(annotations_file, encoding="utf-8") as f:
                data = json.load(f)
                return AnnotationData(**data)
        except Exception as e:
            logger.error(f"Error reading annotations for {session_id}: {e}")
            return AnnotationData()

    @app.put("/api/sessions/{session_id}/annotations", response_model=AnnotationData)
    def update_annotations(session_id: str, annotations: AnnotationData):
        """Update annotations for a specific session."""
        session_dir = state.watch_manager.output_dir / session_id

        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="Session not found")

        annotations_file = session_dir / "annotations.json"

        try:
            with open(annotations_file, "w", encoding="utf-8") as f:
                json.dump(annotations.model_dump(), f, ensure_ascii=False, indent=2)
            return annotations
        except Exception as e:
            logger.error(f"Error saving annotations for {session_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save annotations") from e

    # Ensure consistent MIME type mappings before serving static assets
    _ensure_static_mime_types()

    # Serve static files (React UI)
    # The static directory should be adjacent to this file in the package
    static_dir = Path(__file__).parent / "static"

    if static_dir.exists():
        # Mount assets specifically for explicit access (higher priority)
        if (static_dir / "assets").exists():
            app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        # Mount root for index.html and all assets
        # html=True allows serving index.html for the root path and subpaths (SPA support)
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        # Fallback for development/missing build
        @app.get("/")
        async def index():
            return {"message": "UI not built. Run 'npm run build' in ui/ directory."}

    return app


def run_server(watch_manager: WatchManager, host: str = "127.0.0.1", port: int = 8000):
    """Run the API server."""
    import uvicorn

    app = create_app(watch_manager)

    # Run uvicorn programmatically
    # In a real CLI tool, we might want to suppress some uvicorn logs
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)

    # Run in the current thread (should be called from a dedicated thread)
    server.run()

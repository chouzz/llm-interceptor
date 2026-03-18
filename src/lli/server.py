"""
FastAPI server for the LLM Interceptor UI.

Serves the React frontend and provides API endpoints for session data.
"""

import json
import logging
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lli.watch import WatchManager

# Get logger
logger = logging.getLogger("llm_interceptor.server")


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
    duration_ms: float
    total_tokens: int


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


def _parse_timestamp(value: object) -> datetime | None:
    """Parse ISO timestamps from session files into naive UTC datetimes."""
    if not isinstance(value, str) or not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_session_dir_timestamp(path: Path) -> datetime:
    """Best-effort timestamp from the session directory name."""
    try:
        return datetime.strptime(path.name.replace("session_", ""), "%Y%m%d_%H%M%S")
    except ValueError:
        return datetime.now()


def _summarize_session(path: Path) -> SessionSummary:
    """Build session summary stats from captured request/response files."""
    fallback_timestamp = _parse_session_dir_timestamp(path)
    request_timestamps: list[datetime] = []
    response_timestamps: list[datetime] = []
    request_count = 0
    total_latency_ms = 0.0

    for file_path in sorted(path.glob("*.json")):
        if file_path.name == "annotations.json":
            continue

        parts = file_path.stem.split("_")
        if len(parts) < 2:
            continue

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("Failed to read session file %s: %s", file_path, e)
            continue

        if not isinstance(data, dict):
            continue

        msg_type = parts[1]
        timestamp = _parse_timestamp(data.get("timestamp"))

        if msg_type == "request":
            request_count += 1
            if timestamp is not None:
                request_timestamps.append(timestamp)
        elif msg_type == "response":
            if timestamp is not None:
                response_timestamps.append(timestamp)

            latency_ms = data.get("latency_ms")
            if isinstance(latency_ms, int | float):
                total_latency_ms += float(latency_ms)

    started_at = min(request_timestamps) if request_timestamps else fallback_timestamp
    ended_candidates = response_timestamps or request_timestamps
    ended_at = max(ended_candidates) if ended_candidates else started_at
    duration_ms = max((ended_at - started_at).total_seconds() * 1000, 0.0)

    return SessionSummary(
        id=path.name,
        timestamp=started_at,
        request_count=request_count,
        total_latency_ms=total_latency_ms,
        duration_ms=duration_ms,
        total_tokens=0,
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
    async def get_status():
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
    async def list_sessions():
        """List all captured sessions."""
        sessions = []
        traces_dir = state.watch_manager.output_dir

        if not traces_dir.exists():
            return []

        # Scan for session directories
        # Sort by directory name (timestamp) ascending (oldest first)
        session_dirs = sorted(
            [p for p in traces_dir.glob("session_*") if p.is_dir()],
            key=lambda p: p.name,
            reverse=False,
        )

        for path in session_dirs:
            sessions.append(_summarize_session(path))

        return sessions

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
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
    async def delete_session(session_id: str):
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
    async def get_annotations(session_id: str):
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
    async def update_annotations(session_id: str, annotations: AnnotationData):
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

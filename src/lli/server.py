"""
FastAPI server for the LLM Interceptor UI.

Serves the React frontend and provides API endpoints for session data.
"""

import hashlib
import json
import logging
import mimetypes
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

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


class UsageMetrics(BaseModel):
    """Normalized usage metrics exposed to the UI."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


class ExchangeSummary(BaseModel):
    """Lightweight exchange metadata for the requests list."""

    id: str
    sequence_id: str
    timestamp: str
    request_method: str = "POST"
    request_url: str = ""
    status_code: int = 0
    latency_ms: float = 0.0
    model: str = "unknown-model"
    system_prompt_key: str = ""
    usage: UsageMetrics | None = None
    has_response: bool = False
    tool_names: list[str] = []


class SessionOverview(BaseModel):
    """Fast session payload used for the requests list."""

    id: str
    exchanges: list[ExchangeSummary]


class RequestResponsePair(BaseModel):
    """Full request/response payload for a single exchange."""

    request: dict[str, Any] | None
    response: dict[str, Any] | None


class ExchangeDetail(BaseModel):
    """Detailed request/response payload for a single exchange."""

    id: str
    sequence_id: str
    pair: RequestResponsePair


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
        self._session_cache: dict[str, SessionCacheEntry] = {}


@dataclass
class SessionPairCache:
    """Cached file paths and exchange summary for a single pair."""

    request_path: Path | None = None
    response_path: Path | None = None
    summary: ExchangeSummary | None = None


@dataclass
class SessionCacheEntry:
    """Cached data derived from a session directory."""

    dir_mtime: float
    summary: SessionSummary
    overview: SessionOverview
    pairs: dict[str, SessionPairCache]


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


def _is_openai_format(body: object) -> bool:
    """Best-effort detection for OpenAI-style request payloads."""
    if not isinstance(body, dict):
        return False

    tools = body.get("tools")
    if isinstance(tools, list) and any(
        isinstance(tool, dict) and tool.get("type") == "function" for tool in tools
    ):
        return True

    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") in {"tool", "developer"} or "tool_calls" in message:
                return True
        if "system" not in body and any(
            isinstance(message, dict) and message.get("role") == "system" for message in messages
        ):
            return True

    return False


def _stringify_content(value: object) -> str:
    """Convert provider-specific content blocks to a readable string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def _extract_system_prompt_key(body: object) -> str:
    """Extract a stable system prompt key without sending full raw payloads."""
    if not isinstance(body, dict):
        return ""

    if _is_openai_format(body):
        messages = body.get("messages")
        if not isinstance(messages, list):
            return ""
        parts: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") not in {"system", "developer"}:
                continue
            rendered = _stringify_content(message.get("content")).strip()
            if rendered:
                parts.append(rendered)
        raw_key = "\n".join(parts)
        return hashlib.sha1(raw_key.encode("utf-8")).hexdigest() if raw_key else ""

    system = body.get("system")
    raw_key = _stringify_content(system).strip()
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest() if raw_key else ""


def _extract_request_tool_names(body: object) -> list[str]:
    """Collect tool-use names embedded in request/response content."""
    if not isinstance(body, dict):
        return []

    names: list[str] = []
    if _is_openai_format(body):
        messages = body.get("messages")
        if not isinstance(messages, list):
            return names
        for message in messages:
            if not isinstance(message, dict):
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name)
        return names

    messages = body.get("messages")
    if not isinstance(messages, list):
        return names
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name)
    return names


def _extract_response_tool_names(body: object) -> list[str]:
    """Collect tool-use names emitted by the model response."""
    if not isinstance(body, dict):
        return []

    names: list[str] = []
    choices = body.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name)
        if names:
            return names

    content = body.get("content")
    if not isinstance(content, list):
        return names
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def _normalize_usage_metrics(raw_usage: object) -> UsageMetrics | None:
    """Normalize OpenAI/Anthropic usage payloads to a common shape."""
    if not isinstance(raw_usage, dict):
        return None

    def safe_number(value: object) -> int | None:
        if isinstance(value, int | float):
            return int(value)
        return None

    input_tokens = safe_number(raw_usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = safe_number(raw_usage.get("prompt_tokens"))

    output_tokens = safe_number(raw_usage.get("output_tokens"))
    if output_tokens is None:
        output_tokens = safe_number(raw_usage.get("completion_tokens"))

    total_tokens = safe_number(raw_usage.get("total_tokens"))

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None

    if input_tokens is None and total_tokens is not None and output_tokens is not None:
        input_tokens = max(total_tokens - output_tokens, 0)

    if output_tokens is None and total_tokens is not None and input_tokens is not None:
        output_tokens = max(total_tokens - input_tokens, 0)

    input_final = input_tokens if input_tokens is not None else total_tokens or 0
    output_final = output_tokens if output_tokens is not None else 0
    total_final = total_tokens if total_tokens is not None else input_final + output_final
    return UsageMetrics(
        input_tokens=input_final,
        output_tokens=output_final,
        total_tokens=total_final,
    )


def _empty_exchange_summary(sequence_id: str) -> ExchangeSummary:
    """Create a default exchange summary before payload enrichment."""
    fallback_id = f"seq-{sequence_id}"
    return ExchangeSummary(
        id=fallback_id,
        sequence_id=sequence_id,
        timestamp="",
        request_method="POST",
        request_url="",
        status_code=0,
        latency_ms=0.0,
        model="unknown-model",
        system_prompt_key="",
        usage=None,
        has_response=False,
        tool_names=[],
    )


def _parse_session_file(file_path: Path) -> tuple[str, str] | None:
    """Parse the sequence id and record kind from a split record filename."""
    if file_path.name in {SESSION_ANNOTATIONS_FILE, SESSION_METADATA_FILE}:
        return None
    parts = file_path.stem.split("_")
    if len(parts) < 2:
        return None
    sequence_id, record_type = parts[0], parts[1]
    if record_type not in {"request", "response"}:
        return None
    return sequence_id, record_type


def _build_session_cache_entry(session_dir: Path) -> SessionCacheEntry:
    """Build a cache entry containing the sidebar summary and request-list overview."""
    request_count = 0
    total_latency_ms = 0.0
    total_tokens = 0
    failed_count = 0
    earliest_timestamp: datetime | None = _read_session_metadata_timestamp(session_dir)
    latest_timestamp: datetime | None = None
    oldest_file_timestamp: datetime | None = None
    oldest_record_file_mtime: datetime | None = None
    pair_cache: dict[str, SessionPairCache] = {}

    started_at = perf_counter()

    def _numeric_key(file_path: Path) -> tuple[int, str]:
        """Extract a numeric key from a filename for natural sorting."""
        name = file_path.name
        match = re.match(r"^(\d+)", name)
        if match:
            return int(match.group(1)), name
        return 999999, name

    for file_path in sorted(session_dir.glob("*.json"), key=_numeric_key):
        request_usage = None
        parsed = _parse_session_file(file_path)
        if parsed is None:
            continue

        sequence_id, record_type = parsed
        pair_entry = pair_cache.setdefault(sequence_id, SessionPairCache())
        summary = pair_entry.summary or _empty_exchange_summary(sequence_id)

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

        record_timestamp = _parse_iso_datetime(payload.get("timestamp"))
        if record_timestamp is not None:
            if earliest_timestamp is None or record_timestamp < earliest_timestamp:
                earliest_timestamp = record_timestamp
            if latest_timestamp is None or record_timestamp > latest_timestamp:
                latest_timestamp = record_timestamp
            if not summary.timestamp:
                summary.timestamp = payload.get("timestamp", "")

        if record_type == "request":
            request_count += 1
            pair_entry.request_path = file_path

            request_id = payload.get("request_id")
            if isinstance(request_id, str) and request_id:
                summary.id = request_id

            summary.request_method = (
                payload.get("method")
                if isinstance(payload.get("method"), str) and payload.get("method")
                else summary.request_method
            )
            summary.request_url = (
                payload.get("url") if isinstance(payload.get("url"), str) else summary.request_url
            )

            body = payload.get("body")
            if isinstance(body, dict):
                model = body.get("model")
                if isinstance(model, str) and model:
                    summary.model = model

                system_prompt_key = _extract_system_prompt_key(body)
                if system_prompt_key:
                    summary.system_prompt_key = system_prompt_key

                for name in _extract_request_tool_names(body):
                    if name not in summary.tool_names:
                        summary.tool_names.append(name)

            request_usage = _normalize_usage_metrics(payload.get("usage"))
            if request_usage is not None:
                total_tokens += request_usage.total_tokens
                summary.usage = request_usage

        else:
            pair_entry.response_path = file_path
            summary.has_response = True

            status_code = payload.get("status_code")
            if isinstance(status_code, int | float):
                summary.status_code = int(status_code)
                if int(status_code) >= 400:
                    failed_count += 1
            elif status_code is None:
                failed_count += 1

            latency_ms = payload.get("latency_ms")
            if isinstance(latency_ms, int | float):
                summary.latency_ms = float(latency_ms)
                total_latency_ms += float(latency_ms)

            body = payload.get("body")
            if isinstance(body, dict):
                usage = _normalize_usage_metrics(body.get("usage"))
                if usage is not None:
                    # Response usage supersedes request usage to avoid double-counting
                    total_tokens -= (request_usage.total_tokens if request_usage is not None else 0)
                    total_tokens += usage.total_tokens
                    summary.usage = usage

                for name in _extract_response_tool_names(body):
                    if name not in summary.tool_names:
                        summary.tool_names.append(name)

        if not summary.timestamp:
            summary.timestamp = payload.get("timestamp", "")

        pair_entry.summary = summary

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

    summary = SessionSummary(
        id=session_dir.name,
        timestamp=earliest_timestamp,
        request_count=request_count,
        total_latency_ms=total_latency_ms,
        total_tokens=total_tokens,
        duration_ms=duration_ms,
        failed_count=failed_count,
    )
    overview = SessionOverview(
        id=session_dir.name,
        exchanges=[
            pair_entry.summary or _empty_exchange_summary(sequence_id)
            for sequence_id, pair_entry in sorted(
                pair_cache.items(),
                key=lambda x: (0, int(x[0])) if x[0].isdigit() else (1, x[0]),
            )
        ],
    )
    try:
        dir_mtime = session_dir.stat().st_mtime
    except OSError:
        dir_mtime = 0.0

    logger.debug(
        "Built session cache for %s in %.1fms (%d exchanges)",
        session_dir.name,
        (perf_counter() - started_at) * 1000,
        len(overview.exchanges),
    )
    return SessionCacheEntry(
        dir_mtime=dir_mtime,
        summary=summary,
        overview=overview,
        pairs=pair_cache,
    )


def _get_or_build_session_cache(state: ServerState, session_dir: Path) -> SessionCacheEntry:
    """Return a warm cache entry for a session directory."""
    try:
        dir_mtime = session_dir.stat().st_mtime
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    cached = state._session_cache.get(session_dir.name)
    if cached is not None and cached.dir_mtime == dir_mtime:
        return cached

    entry = _build_session_cache_entry(session_dir)
    state._session_cache[session_dir.name] = entry
    return entry


def _read_pair_details(pair_cache: SessionPairCache) -> RequestResponsePair:
    """Read the full request/response JSON for a single exchange."""
    request_data: dict[str, Any] | None = None
    response_data: dict[str, Any] | None = None

    if pair_cache.request_path is not None:
        with open(pair_cache.request_path, encoding="utf-8") as f:
            payload = json.load(f)
            if isinstance(payload, dict):
                request_data = payload

    if pair_cache.response_path is not None:
        with open(pair_cache.response_path, encoding="utf-8") as f:
            payload = json.load(f)
            if isinstance(payload, dict):
                response_data = payload

    return RequestResponsePair(request=request_data, response=response_data)


def _is_session_dir(path: Path) -> bool:
    """Best-effort detection for captured session directories."""
    if not path.is_dir():
        return False

    if (path / SESSION_METADATA_FILE).exists() or (path / SESSION_ANNOTATIONS_FILE).exists():
        return True

    if _parse_session_timestamp(path.name) is not None:
        return True

    return any(path.glob("*.json"))


def _validate_session_id(session_id: str) -> None:
    """Validate session_id to prevent path traversal attacks.

    Session IDs must match the expected format: session_YYYYMMDD_HHMMSS
    """
    if not _parse_session_timestamp(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")


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
        new_cache: dict[str, SessionCacheEntry] = {}

        for path in session_dirs:
            try:
                dir_mtime = path.stat().st_mtime
            except OSError:
                continue

            cached = state._session_cache.get(path.name)
            if cached is not None and cached.dir_mtime == dir_mtime:
                new_cache[path.name] = cached
                sessions.append(cached.summary)
            else:
                entry = _build_session_cache_entry(path)
                new_cache[path.name] = entry
                sessions.append(entry.summary)

        state._session_cache = new_cache
        sessions.sort(key=lambda session: (session.timestamp, session.id))
        return sessions

    @app.get("/api/sessions/{session_id}", response_model=SessionOverview)
    def get_session(session_id: str):
        """Get a fast overview for a specific session."""
        _validate_session_id(session_id)
        session_dir = state.watch_manager.output_dir / session_id

        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="Session not found")

        started_at = perf_counter()
        entry = _get_or_build_session_cache(state, session_dir)
        logger.debug(
            "Served session overview %s in %.1fms (%d exchanges)",
            session_id,
            (perf_counter() - started_at) * 1000,
            len(entry.overview.exchanges),
        )
        return entry.overview

    @app.get("/api/sessions/{session_id}/exchanges/{sequence_id}", response_model=ExchangeDetail)
    def get_exchange_detail(session_id: str, sequence_id: str):
        """Get the full request/response payload for a single exchange."""
        _validate_session_id(session_id)
        session_dir = state.watch_manager.output_dir / session_id

        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="Session not found")

        entry = _get_or_build_session_cache(state, session_dir)
        pair_cache = entry.pairs.get(sequence_id)
        if pair_cache is None:
            raise HTTPException(status_code=404, detail="Exchange not found")

        try:
            pair = _read_pair_details(pair_cache)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Error reading exchange %s/%s: %s", session_id, sequence_id, exc)
            raise HTTPException(status_code=500, detail="Failed to read exchange") from exc

        exchange_id = (
            pair_cache.summary.id if pair_cache.summary is not None else f"seq-{sequence_id}"
        )
        return ExchangeDetail(id=exchange_id, sequence_id=sequence_id, pair=pair)

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        """Delete a captured session and all local files under it."""
        _validate_session_id(session_id)
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
        _validate_session_id(session_id)
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
        _validate_session_id(session_id)
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

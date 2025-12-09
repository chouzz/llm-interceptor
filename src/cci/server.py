"""
FastAPI server for the Claude Code Inspector UI.

Serves the React frontend and provides API endpoints for session data.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cci.watch import WatchManager

# Get logger
logger = logging.getLogger("cci.server")


class SessionSummary(BaseModel):
    """Summary information for a session."""

    id: str
    timestamp: datetime
    request_count: int
    total_latency_ms: float
    total_tokens: int


class ServerState:
    """Shared state for the API server."""

    def __init__(self, watch_manager: WatchManager):
        self.watch_manager = watch_manager


def create_app(watch_manager: WatchManager) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Claude Code Inspector API")
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
            # Basic info from directory name
            try:
                # Format: session_YYYYMMDD_HHMMSS
                ts_str = path.name.replace("session_", "")
                timestamp = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            except ValueError:
                timestamp = datetime.now()

            # Count requests (rough estimate from file count / 2)
            file_count = len(list(path.glob("*.json")))
            req_count = file_count // 2

            sessions.append(
                SessionSummary(
                    id=path.name,
                    timestamp=timestamp,
                    request_count=req_count,
                    total_latency_ms=0,  # TODO: Calculate from summary file if available
                    total_tokens=0,  # TODO: Calculate from summary file if available
                )
            )

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

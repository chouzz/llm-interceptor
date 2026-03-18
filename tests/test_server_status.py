from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lli.server import create_app
from lli.watch import WatchManager


def test_api_status_reports_output_dir_and_no_sessions(tmp_path: Path) -> None:
    watch_manager = WatchManager(output_dir=tmp_path)
    watch_manager.initialize()
    try:
        app = create_app(watch_manager)
        client = TestClient(app)

        res = client.get("/api/status")
        assert res.status_code == 200
        payload = res.json()

        assert payload["output_dir"] == str(tmp_path)
        assert payload["has_sessions"] is False
        assert payload["active"] is False
        assert payload["session_id"] is None
    finally:
        watch_manager.shutdown()


def test_api_status_reports_active_recording(tmp_path: Path) -> None:
    watch_manager = WatchManager(output_dir=tmp_path)
    watch_manager.initialize()
    try:
        watch_manager.start_recording()
        app = create_app(watch_manager)
        client = TestClient(app)

        res = client.get("/api/status")
        assert res.status_code == 200
        payload = res.json()

        assert payload["output_dir"] == str(tmp_path)
        assert payload["active"] is True
        assert payload["session_id"] is not None
    finally:
        watch_manager.shutdown()


def test_api_status_reports_has_sessions_when_session_dir_exists(tmp_path: Path) -> None:
    watch_manager = WatchManager(output_dir=tmp_path)
    watch_manager.initialize()
    try:
        (tmp_path / "session_20260101_000000").mkdir(parents=True, exist_ok=True)
        app = create_app(watch_manager)
        client = TestClient(app)

        res = client.get("/api/status")
        assert res.status_code == 200
        payload = res.json()

        assert payload["has_sessions"] is True
        assert payload["active"] is False
    finally:
        watch_manager.shutdown()

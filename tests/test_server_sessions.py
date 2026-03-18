from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from lli.server import create_app
from lli.watch import WatchManager


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_api_sessions_include_duration_and_total_latency(tmp_path: Path) -> None:
    watch_manager = WatchManager(output_dir=tmp_path)
    watch_manager.initialize()
    try:
        session_dir = tmp_path / "session_20260101_120000"
        session_dir.mkdir(parents=True, exist_ok=True)

        _write_json(
            session_dir / "001_request_test.json",
            {
                "type": "request",
                "request_id": "req-1",
                "timestamp": "2026-01-01T12:00:00Z",
                "method": "POST",
                "url": "https://example.test/v1/chat/completions",
                "body": {},
            },
        )
        _write_json(
            session_dir / "001_response_test.json",
            {
                "type": "response",
                "request_id": "req-1",
                "timestamp": "2026-01-01T12:00:02Z",
                "status_code": 200,
                "latency_ms": 500,
                "body": {},
            },
        )
        _write_json(
            session_dir / "002_request_test.json",
            {
                "type": "request",
                "request_id": "req-2",
                "timestamp": "2026-01-01T12:00:05Z",
                "method": "POST",
                "url": "https://example.test/v1/chat/completions",
                "body": {},
            },
        )
        _write_json(
            session_dir / "002_response_test.json",
            {
                "type": "response",
                "request_id": "req-2",
                "timestamp": "2026-01-01T12:00:07Z",
                "status_code": 500,
                "latency_ms": 1000,
                "body": {"error": "boom"},
            },
        )
        _write_json(
            session_dir / "annotations.json",
            {
                "session_note": "ignored by request count",
                "requests": {},
            },
        )

        app = create_app(watch_manager)
        client = TestClient(app)

        res = client.get("/api/sessions")
        assert res.status_code == 200

        payload = res.json()
        assert len(payload) == 1
        assert payload[0]["id"] == "session_20260101_120000"
        assert payload[0]["request_count"] == 2
        assert payload[0]["total_latency_ms"] == 1500
        assert payload[0]["duration_ms"] == 7000
        assert payload[0]["timestamp"].startswith("2026-01-01T12:00:00")
    finally:
        watch_manager.shutdown()

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from lli.server import StaticTracesProvider, _is_openai_responses_request, create_app
from lli.watch import WatchManager


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_is_openai_responses_request_url_gating() -> None:
    """URL takes priority: embeddings bodies also carry a bare `input` field."""
    responses_body = {
        "model": "gpt-5-mini",
        "input": "Hello",
        "instructions": "You are helpful.",
    }
    embeddings_body = {"model": "text-embedding-3-small", "input": "The food was delicious"}

    assert _is_openai_responses_request(responses_body, "https://api.openai.com/v1/responses")
    assert _is_openai_responses_request(
        {"input": [{"type": "message", "role": "user", "content": "hi"}]},
        "https://api.openai.com/v1/responses",
    )
    # Embeddings URLs are never classified as Responses chat requests
    assert not _is_openai_responses_request(embeddings_body, "https://api.openai.com/v1/embeddings")
    assert not _is_openai_responses_request(
        embeddings_body, "https://api.openai.com/v1/chat/completions"
    )


def test_is_openai_responses_request_body_fallback_requires_signals() -> None:
    """Without a URL, a bare `input` payload (embeddings-like) is not enough."""
    assert _is_openai_responses_request(
        {"model": "gpt-5-mini", "input": "Hello", "instructions": "You are helpful."}
    )
    assert _is_openai_responses_request({"input": "Hello", "max_output_tokens": 1024})
    assert _is_openai_responses_request({"input": "Hello", "previous_response_id": "resp_1"})
    # Embeddings-like body has no Responses-specific fields
    assert not _is_openai_responses_request(
        {"model": "text-embedding-3-small", "input": "The food was delicious"}
    )
    # Chat completions style bodies are never Responses requests
    assert not _is_openai_responses_request(
        {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]}
    )


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


def test_api_sessions_keep_stable_timestamp_for_suffixed_session_ids(
    tmp_path: Path,
) -> None:
    watch_manager = WatchManager(output_dir=tmp_path)
    watch_manager.initialize()
    try:
        session_dir = tmp_path / "session_20260101_120000_2"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "annotations.json").write_text(
            json.dumps({"session_note": "", "requests": {}}),
            encoding="utf-8",
        )

        app = create_app(watch_manager)
        client = TestClient(app)

        first_res = client.get("/api/sessions")
        second_res = client.get("/api/sessions")

        assert first_res.status_code == 200
        assert second_res.status_code == 200

        first_payload = first_res.json()
        second_payload = second_res.json()

        assert len(first_payload) == 1
        assert first_payload[0]["id"] == "session_20260101_120000_2"
        assert first_payload[0]["timestamp"].startswith("2026-01-01T12:00:00")
        assert second_payload[0]["timestamp"] == first_payload[0]["timestamp"]
    finally:
        watch_manager.shutdown()


def test_api_sessions_keep_stable_timestamp_when_directory_is_renamed(
    tmp_path: Path,
) -> None:
    watch_manager = WatchManager(output_dir=tmp_path)
    watch_manager.initialize()
    try:
        session_dir = tmp_path / "renamed-by-user"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session_meta.json").write_text(
            json.dumps(
                {
                    "session_id": "session_20260101_120000",
                    "started_at": "2026-01-01T12:00:00",
                    "ended_at": "2026-01-01T12:05:00",
                }
            ),
            encoding="utf-8",
        )
        (session_dir / "annotations.json").write_text(
            json.dumps({"session_note": "note", "requests": {}}),
            encoding="utf-8",
        )

        app = create_app(watch_manager)
        client = TestClient(app)

        first_res = client.get("/api/sessions")
        second_res = client.get("/api/sessions")

        assert first_res.status_code == 200
        assert second_res.status_code == 200

        first_payload = first_res.json()
        second_payload = second_res.json()

        assert len(first_payload) == 1
        assert first_payload[0]["id"] == "renamed-by-user"
        assert first_payload[0]["timestamp"].startswith("2026-01-01T12:00:00")
        assert second_payload[0]["timestamp"] == first_payload[0]["timestamp"]
    finally:
        watch_manager.shutdown()


def test_api_sessions_detect_renamed_legacy_session_without_metadata(tmp_path: Path) -> None:
    watch_manager = WatchManager(output_dir=tmp_path)
    watch_manager.initialize()
    try:
        session_dir = tmp_path / "custom-folder-name"
        session_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            session_dir / "001_request_2026-01-01_12-00-00.json",
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
            session_dir / "001_response_2026-01-01_12-00-01.json",
            {
                "type": "response",
                "request_id": "req-1",
                "timestamp": "2026-01-01T12:00:01Z",
                "status_code": 200,
                "latency_ms": 321,
                "body": {},
            },
        )

        app = create_app(watch_manager)
        client = TestClient(app)

        res = client.get("/api/sessions")
        assert res.status_code == 200

        payload = res.json()
        assert len(payload) == 1
        assert payload[0]["id"] == "custom-folder-name"
        assert payload[0]["timestamp"].startswith("2026-01-01T12:00:00")
        assert payload[0]["request_count"] == 1
        assert payload[0]["total_latency_ms"] == 321
    finally:
        watch_manager.shutdown()


def test_api_sessions_support_openai_responses_payloads(tmp_path: Path) -> None:
    """Responses API exchanges expose model, prompt key, tools, and usage in the overview."""
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
                "url": "https://api.openai.com/v1/responses",
                "body": {
                    "model": "gpt-5-mini",
                    "instructions": "You are a helpful assistant.",
                    "input": "What is the weather in SF?",
                    "tools": [
                        {
                            "type": "function",
                            "name": "get_weather",
                            "parameters": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                            },
                        }
                    ],
                    "stream": True,
                },
            },
        )
        _write_json(
            session_dir / "001_response_test.json",
            {
                "type": "response",
                "request_id": "req-1",
                "timestamp": "2026-01-01T12:00:02Z",
                "status_code": 200,
                "latency_ms": 750,
                "body": {
                    "id": "resp_1",
                    "object": "response",
                    "status": "completed",
                    "model": "gpt-5-mini",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_1",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {"type": "output_text", "text": "Let me check.", "annotations": []}
                            ],
                        },
                        {
                            "type": "function_call",
                            "id": "fc_1",
                            "call_id": "call_1",
                            "name": "get_weather",
                            "arguments": '{"city": "SF"}',
                            "status": "completed",
                        },
                    ],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                    },
                },
            },
        )

        app = create_app(watch_manager)
        client = TestClient(app)

        res = client.get("/api/sessions/session_20260101_120000")
        assert res.status_code == 200

        payload = res.json()
        assert len(payload["exchanges"]) == 1

        exchange = payload["exchanges"][0]
        assert exchange["model"] == "gpt-5-mini"
        assert exchange["status_code"] == 200
        assert exchange["latency_ms"] == 750
        assert exchange["has_response"] is True
        # System prompt key is hashed from the instructions field
        assert exchange["system_prompt_key"]
        # Tool names are collected from both request tools and response function calls
        assert exchange["tool_names"] == ["get_weather"]
        # Usage is normalized from the Responses API usage payload
        assert exchange["usage"] == {
            "input_tokens": 20,
            "output_tokens": 10,
            "total_tokens": 30,
        }
    finally:
        watch_manager.shutdown()


def test_static_traces_provider_serves_sessions(tmp_path: Path) -> None:
    """The standalone provider (lli serve) lists sessions without a WatchManager."""
    session_dir = tmp_path / "session_20260101_120000_123456"
    session_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        session_dir / "001_request_test.json",
        {
            "type": "request",
            "request_id": "req-1",
            "timestamp": "2026-01-01T12:00:00Z",
            "method": "POST",
            "url": "https://api.anthropic.com/v1/messages",
            "body": {"model": "claude-sonnet-4-5", "messages": []},
        },
    )
    _write_json(
        session_dir / "001_response_test.json",
        {
            "type": "response",
            "request_id": "req-1",
            "timestamp": "2026-01-01T12:00:01Z",
            "status_code": 200,
            "latency_ms": 100,
            "body": {"content": [{"type": "text", "text": "hi"}]},
        },
    )
    # run_meta.json must be ignored by the session file parser
    _write_json(
        session_dir / "run_meta.json",
        {"command": ["claude", "-p", "hello"], "exit_code": 0},
    )

    provider = StaticTracesProvider(output_dir=tmp_path)
    app = create_app(provider)
    client = TestClient(app)

    res = client.get("/api/sessions")
    assert res.status_code == 200
    payload = res.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "session_20260101_120000_123456"
    assert payload[0]["request_count"] == 1

    # Status: sessions exist, but no active recording (no capture process)
    status = client.get("/api/status").json()
    assert status["has_sessions"] is True
    assert status["active"] is False

    # Exchange details still resolve
    detail = client.get("/api/sessions/session_20260101_120000_123456/exchanges/001")
    assert detail.status_code == 200
    assert detail.json()["pair"]["request"]["body"]["model"] == "claude-sonnet-4-5"

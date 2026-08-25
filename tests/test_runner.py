"""Tests for the run wrapper (lli run)."""

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

from lli.config import LLIConfig
from lli.runner import (
    RunResult,
    build_child_env,
    run_wrapped_command,
    wait_for_drain,
    write_run_metadata,
)
from lli.watch import WatchManager

SESSION_ID_RE = re.compile(r"^session_\d{8}_\d{6}_\d{6}$")


class TestBuildChildEnv:
    """Test child environment construction."""

    def test_proxy_vars_set(self) -> None:
        env = build_child_env(12345, cert_path=Path("/nonexistent"), base_env={})
        assert env["HTTP_PROXY"] == "http://127.0.0.1:12345"
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:12345"
        assert env["http_proxy"] == "http://127.0.0.1:12345"
        assert env["https_proxy"] == "http://127.0.0.1:12345"
        assert "localhost" in env["NO_PROXY"]

    def test_cert_vars_set_when_cert_exists(self, tmp_path: Path) -> None:
        cert = tmp_path / "ca.pem"
        cert.write_text("FAKE CERT", encoding="utf-8")
        env = build_child_env(1, cert_path=cert, base_env={})
        assert env["NODE_EXTRA_CA_CERTS"] == str(cert)
        assert env["SSL_CERT_FILE"] == str(cert)
        assert env["REQUESTS_CA_BUNDLE"] == str(cert)

    def test_cert_vars_absent_when_cert_missing(self, tmp_path: Path) -> None:
        env = build_child_env(1, cert_path=tmp_path / "missing.pem", base_env={})
        assert "NODE_EXTRA_CA_CERTS" not in env
        assert "SSL_CERT_FILE" not in env

    def test_existing_proxy_env_overridden(self) -> None:
        env = build_child_env(
            9999,
            cert_path=Path("/nonexistent"),
            base_env={"HTTPS_PROXY": "http://evil:1"},
        )
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:9999"


class TestWaitForDrain:
    """Test in-flight drain waiting."""

    @pytest.mark.asyncio
    async def test_returns_immediately_when_idle(self) -> None:
        assert await wait_for_drain(lambda: 0, timeout=1.0) is True

    @pytest.mark.asyncio
    async def test_drains_when_count_drops(self) -> None:
        counts = iter([2, 1, 0])
        assert await wait_for_drain(lambda: next(counts), timeout=2.0, poll_interval=0.01) is True

    @pytest.mark.asyncio
    async def test_times_out_when_never_drains(self) -> None:
        assert await wait_for_drain(lambda: 1, timeout=0.05, poll_interval=0.01) is False

    @pytest.mark.asyncio
    async def test_zero_timeout_checks_once(self) -> None:
        assert await wait_for_drain(lambda: 1, timeout=0) is False
        assert await wait_for_drain(lambda: 0, timeout=0) is True


class TestSessionIdFormat:
    """Test collision-proof session/log naming in WatchManager."""

    def test_session_id_contains_microseconds(self, tmp_path: Path) -> None:
        mgr = WatchManager(output_dir=tmp_path, port=0)
        mgr.initialize()
        try:
            session = mgr.start_recording()
            assert SESSION_ID_RE.match(session.session_id), session.session_id
        finally:
            mgr.shutdown()

    def test_global_log_name_contains_microseconds(self, tmp_path: Path) -> None:
        mgr = WatchManager(output_dir=tmp_path, port=0)
        name = mgr.global_log_path.name
        assert re.match(r"^all_captured_\d{8}_\d{6}_\d{6}\.jsonl$", name), name


class TestRunWrappedCommand:
    """Integration smoke tests (real proxy, no network traffic)."""

    def _run(self, tmp_path: Path, argv: list[str], label: str | None = None):
        return asyncio.run(
            run_wrapped_command(
                argv,
                config=LLIConfig(),
                label=label,
                output_root=tmp_path,
                drain_timeout=2.0,
            )
        )

    def test_successful_run_produces_session_and_metadata(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, [sys.executable, "-c", "pass"], label="smoke")

        assert result.exit_code == 0
        assert result.interrupted is False
        assert result.proxy_port > 0
        assert result.requests_captured == 0

        # Session lives directly in the traces root, alongside watch sessions
        assert result.session_dir.is_relative_to(tmp_path)
        assert result.session_dir.parent == tmp_path
        assert SESSION_ID_RE.match(result.session_id)

        # Metadata lives inside the session directory
        assert (result.session_dir / "session_meta.json").is_file()
        assert (result.session_dir / "run_meta.json").is_file()

        meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        assert meta["command"] == [sys.executable, "-c", "pass"]
        assert meta["label"] == "smoke"
        assert meta["exit_code"] == 0
        assert meta["session_id"] == result.session_id
        assert meta["requests_captured"] == 0
        assert meta["proxy_port"] == result.proxy_port
        assert meta["duration_seconds"] >= 0

    def test_exit_code_propagated(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, [sys.executable, "-c", "import sys; sys.exit(3)"])
        assert result.exit_code == 3

    def test_missing_command_exits_127(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, ["lli-definitely-not-a-command-xyz"])
        assert result.exit_code == 127
        # Session is still finalized for failed spawns
        assert result.session_dir.is_dir()

    def test_runs_are_isolated(self, tmp_path: Path) -> None:
        first = self._run(tmp_path, [sys.executable, "-c", "pass"])
        second = self._run(tmp_path, [sys.executable, "-c", "pass"])
        assert first.session_dir != second.session_dir
        assert first.session_id != second.session_id
        assert first.session_dir.is_relative_to(tmp_path)
        assert second.session_dir.is_relative_to(tmp_path)
        # Each run wrote its own metadata
        assert first.metadata_path.is_file()
        assert second.metadata_path.is_file()

    def test_concurrent_runs_do_not_collide(self, tmp_path: Path) -> None:
        """Two runs starting in the same second must not share sessions/logs."""

        async def _two_runs():
            return await asyncio.gather(
                run_wrapped_command(
                    [sys.executable, "-c", "pass"],
                    config=LLIConfig(),
                    output_root=tmp_path,
                    drain_timeout=2.0,
                ),
                run_wrapped_command(
                    [sys.executable, "-c", "pass"],
                    config=LLIConfig(),
                    output_root=tmp_path,
                    drain_timeout=2.0,
                ),
            )

        first, second = asyncio.run(_two_runs())

        # Distinct sessions, both directly under the shared root
        assert first.session_id != second.session_id
        assert first.session_dir != second.session_dir
        # Distinct global logs (one per run)
        logs = list(tmp_path.glob("all_captured_*.jsonl"))
        assert len(logs) == 2
        # Both metas intact
        for result in (first, second):
            meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
            assert meta["exit_code"] == 0


class TestWriteRunMetadata:
    """Test metadata serialization."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "session_20260101_120000_123456"
        session_dir.mkdir()
        result = RunResult(
            command=["claude", "-p", "hi"],
            label="demo",
            session_id="session_20260101_120000_123456",
            session_dir=session_dir,
            exit_code=0,
            started_at=datetime(2026, 1, 1, 12, 0, 0),
            ended_at=datetime(2026, 1, 1, 12, 0, 5),
            requests_captured=7,
            proxy_port=45678,
            drained=True,
        )
        path = write_run_metadata(result)
        assert path == session_dir / "run_meta.json"

        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["command"] == ["claude", "-p", "hi"]
        assert meta["label"] == "demo"
        assert meta["requests_captured"] == 7
        assert meta["duration_seconds"] == 5.0

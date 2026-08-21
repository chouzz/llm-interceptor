"""Tests for the run wrapper (lli run)."""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from lli.config import LLIConfig
from lli.runner import (
    _slugify,
    build_child_env,
    make_run_dir,
    run_wrapped_command,
    wait_for_drain,
    write_run_metadata,
)


class TestSlugify:
    """Test label slugification."""

    def test_basic(self) -> None:
        assert _slugify("codex-task") == "codex-task"

    def test_spaces_and_specials_replaced(self) -> None:
        assert _slugify("Fix The Bug! (v2)") == "Fix-The-Bug-v2"

    def test_long_labels_truncated(self) -> None:
        assert len(_slugify("a" * 100)) == 40

    def test_empty_becomes_empty(self) -> None:
        assert _slugify("!!!") == ""


class TestMakeRunDir:
    """Test run directory creation."""

    def test_basic_without_label(self, tmp_path: Path) -> None:
        run_dir = make_run_dir(tmp_path, None, now=datetime(2026, 1, 1, 12, 0, 0))
        assert run_dir.name == "run_20260101_120000"
        assert run_dir.is_dir()

    def test_with_label(self, tmp_path: Path) -> None:
        run_dir = make_run_dir(tmp_path, "codex", now=datetime(2026, 1, 1, 12, 0, 0))
        assert run_dir.name == "run_20260101_120000_codex"

    def test_collision_appends_suffix(self, tmp_path: Path) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        first = make_run_dir(tmp_path, None, now=now)
        second = make_run_dir(tmp_path, None, now=now)
        assert first != second
        assert second.name == "run_20260101_120000_2"
        third = make_run_dir(tmp_path, None, now=now)
        assert third.name == "run_20260101_120000_3"


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

        # Run directory structure
        assert result.run_dir.name.startswith("run_")
        assert result.run_dir.name.endswith("_smoke")
        assert (result.run_dir / "run_meta.json").is_file()
        assert result.session_dir is not None
        assert (result.session_dir / "session_meta.json").is_file()

        # Global log lives inside the run dir (self-contained run)
        assert result.run_dir.glob("all_captured_*.jsonl")

        # Metadata content
        meta = json.loads((result.run_dir / "run_meta.json").read_text(encoding="utf-8"))
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
        assert result.session_dir is not None

    def test_runs_are_isolated(self, tmp_path: Path) -> None:
        first = self._run(tmp_path, [sys.executable, "-c", "pass"])
        second = self._run(tmp_path, [sys.executable, "-c", "pass"])
        assert first.run_dir != second.run_dir
        assert first.session_dir != second.session_dir
        # Each session lives inside its own run directory
        assert first.session_dir is not None
        assert second.session_dir is not None
        assert first.session_dir.is_relative_to(first.run_dir)
        assert second.session_dir.is_relative_to(second.run_dir)
        assert not second.session_dir.is_relative_to(first.run_dir)


class TestWriteRunMetadata:
    """Test metadata serialization."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        from lli.runner import RunResult

        result = RunResult(
            command=["claude", "-p", "hi"],
            label="demo",
            run_dir=tmp_path,
            session_id="session_20260101_120000",
            session_dir=tmp_path / "session_20260101_120000",
            exit_code=0,
            started_at=datetime(2026, 1, 1, 12, 0, 0),
            ended_at=datetime(2026, 1, 1, 12, 0, 5),
            requests_captured=7,
            proxy_port=45678,
            drained=True,
        )
        path = write_run_metadata(result)
        assert path == tmp_path / "run_meta.json"

        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["command"] == ["claude", "-p", "hi"]
        assert meta["requests_captured"] == 7
        assert meta["duration_seconds"] == 5.0
        assert meta["session_dir"] == "session_20260101_120000"

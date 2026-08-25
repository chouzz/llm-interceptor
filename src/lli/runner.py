"""
Run wrapper for LLM Interceptor.

Executes an arbitrary command with an ephemeral capture proxy and produces
a fully-processed session (per-exchange request/response JSON files) with
no interactive keypresses. Designed for automated agent experiments:

    lli run -- claude -p "fix the flaky test"

Lifecycle:
    1. Start an ephemeral mitmproxy instance (OS-assigned port)
    2. Start a recording session in the shared traces directory
    3. Spawn the command with proxy + CA environment variables injected
    4. Wait for the command to exit, then drain in-flight responses
    5. Stop the session (triggers merge + split), write run metadata
       (run_meta.json inside the session directory), and shut down cleanly

Sessions land directly in the traces root alongside `lli watch` sessions;
microsecond session IDs keep concurrent runs collision-free.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lli import __version__
from lli.config import LLIConfig, get_cert_path, get_default_trace_dir
from lli.logger import get_logger
from lli.proxy import create_watch_master
from lli.watch import SessionContext, WatchManager, WatchState

RUN_METADATA_FILE = "run_meta.json"
DEFAULT_DRAIN_TIMEOUT = 15.0


@dataclass
class RunResult:
    """Outcome of a wrapped command run."""

    command: list[str]
    label: str | None
    session_id: str
    session_dir: Path
    exit_code: int
    started_at: datetime
    ended_at: datetime
    requests_captured: int
    proxy_port: int
    drained: bool
    interrupted: bool = False

    @property
    def duration_seconds(self) -> float:
        """Wall-clock duration of the wrapped command run."""
        return (self.ended_at - self.started_at).total_seconds()

    @property
    def metadata_path(self) -> Path:
        """Path to the run metadata file inside the session directory."""
        return self.session_dir / RUN_METADATA_FILE


def build_child_env(
    proxy_port: int,
    cert_path: Path | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """
    Build the environment for the wrapped command.

    Points HTTP(S)_PROXY at the capture proxy, bypasses localhost, and
    (when the mitmproxy CA exists) exports CA trust variables so that
    common runtimes (Node, Python requests/urllib, OpenSSL-based tools)
    accept the intercepted TLS certificates.
    """
    proxy_url = f"http://127.0.0.1:{proxy_port}"
    no_proxy = "localhost,127.0.0.1,::1"

    env = dict(base_env if base_env is not None else os.environ)
    env.update(
        {
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
            "http_proxy": proxy_url,
            "https_proxy": proxy_url,
            "NO_PROXY": no_proxy,
            "no_proxy": no_proxy,
        }
    )

    cert = Path(cert_path) if cert_path is not None else get_cert_path()
    if cert.exists():
        cert_str = str(cert)
        env["NODE_EXTRA_CA_CERTS"] = cert_str
        env["SSL_CERT_FILE"] = cert_str
        env["REQUESTS_CA_BUNDLE"] = cert_str

    return env


async def wait_for_listen_port(master: Any, timeout: float = 10.0) -> int:
    """Wait for the proxy server to bind and return the actual port."""
    proxyserver = master.addons.get("proxyserver")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while loop.time() < deadline:
        for instance in proxyserver.servers:
            addrs = getattr(instance, "listen_addrs", None) or ()
            if addrs:
                return int(addrs[0][1])
        await asyncio.sleep(0.05)

    raise RuntimeError(f"Capture proxy did not start listening within {timeout:.0f}s")


async def wait_for_drain(
    in_flight: Callable[[], int],
    timeout: float,
    poll_interval: float = 0.1,
) -> bool:
    """
    Wait until ``in_flight()`` reports zero, or the timeout expires.

    Returns:
        True if all in-flight requests completed, False on timeout.
    """
    loop = asyncio.get_running_loop()
    if timeout <= 0:
        return in_flight() == 0

    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if in_flight() == 0:
            return True
        await asyncio.sleep(poll_interval)

    return in_flight() == 0


async def _terminate_process(proc: asyncio.subprocess.Process) -> int:
    """Terminate a subprocess, escalating to kill if needed. Return exit code."""
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    return proc.returncode if proc.returncode is not None else 130


def write_run_metadata(result: RunResult) -> Path:
    """Write the run metadata JSON file into the session directory."""
    payload = {
        "lli_version": __version__,
        "command": result.command,
        "label": result.label,
        "started_at": result.started_at.isoformat(),
        "ended_at": result.ended_at.isoformat(),
        "duration_seconds": result.duration_seconds,
        "exit_code": result.exit_code,
        "interrupted": result.interrupted,
        "session_id": result.session_id,
        "requests_captured": result.requests_captured,
        "proxy_port": result.proxy_port,
    }
    path = result.metadata_path
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def run_wrapped_command(
    command: Sequence[str],
    *,
    config: LLIConfig | None = None,
    label: str | None = None,
    output_root: str | Path | None = None,
    drain_timeout: float = DEFAULT_DRAIN_TIMEOUT,
    base_env: Mapping[str, str] | None = None,
) -> RunResult:
    """
    Run ``command`` under an ephemeral capture proxy and finalize a session.

    The session is created directly in ``output_root`` (default: the shared
    traces directory), so it shows up in the web UI alongside watch-mode
    sessions as soon as it is processed.

    Args:
        command: Command and arguments to execute
        config: LLI configuration (proxy host/port are overridden)
        label: Optional label recorded in run_meta.json
        output_root: Traces root for session output (default: <traces>)
        drain_timeout: Seconds to wait for in-flight responses after exit
        base_env: Base environment for the child (default: os.environ)

    Returns:
        RunResult describing the completed run
    """
    if not command:
        raise ValueError("command must not be empty")

    logger = get_logger()

    config = config or LLIConfig()
    # Ephemeral, loopback-only proxy for this run
    config.proxy.host = "127.0.0.1"
    config.proxy.port = 0

    root = Path(output_root) if output_root is not None else get_default_trace_dir()
    started_at = datetime.now()

    logger.info(
        "lli run: %s → %s (label=%s)",
        " ".join(command),
        root,
        label or "<none>",
    )

    watch_manager = WatchManager(output_dir=root, port=0)
    watch_manager.initialize()

    session: SessionContext | None = None
    session_dir: Path | None = None
    exit_code = 127
    proxy_port = 0
    drained = False
    interrupted = False

    try:
        master, addon = create_watch_master(config, watch_manager)
        run_task = asyncio.create_task(master.run())

        proc: asyncio.subprocess.Process | None = None
        try:
            proxy_port = await wait_for_listen_port(master)
            logger.info("Capture proxy listening on 127.0.0.1:%d", proxy_port)

            session = watch_manager.start_recording()

            env = build_child_env(proxy_port, get_cert_path(), base_env)
            try:
                proc = await asyncio.create_subprocess_exec(*command, env=env)
                exit_code = await proc.wait()
            except (FileNotFoundError, PermissionError, NotADirectoryError) as e:
                logger.error("Failed to start command %r: %s", command[0], e)
                exit_code = 127

            drained = await wait_for_drain(addon.in_flight_count, drain_timeout)
            if not drained:
                logger.warning(
                    "Drain timeout after %.1fs (%d requests still in flight); "
                    "finalizing session with whatever was captured",
                    drain_timeout,
                    addon.in_flight_count(),
                )

            session = watch_manager.stop_recording()
            session_dir = watch_manager.process_session(session)
        except KeyboardInterrupt:
            interrupted = True
            exit_code = 130
            if proc is not None and proc.returncode is None:
                exit_code = await _terminate_process(proc)
            if watch_manager.state == WatchState.RECORDING:
                session = watch_manager.stop_recording()
                session_dir = watch_manager.process_session(session)
            logger.warning("Run interrupted; capture session finalized")
        finally:
            master.shutdown()
            try:
                await asyncio.wait_for(asyncio.shield(run_task), timeout=10)
            except Exception:
                logger.debug("Proxy shutdown did not complete cleanly")
            if not run_task.done():
                run_task.cancel()
    finally:
        watch_manager.shutdown()

    ended_at = datetime.now()
    assert session is not None and session_dir is not None

    result = RunResult(
        command=list(command),
        label=label,
        session_id=session.session_id,
        session_dir=session_dir,
        exit_code=exit_code,
        started_at=started_at,
        ended_at=ended_at,
        requests_captured=session.request_count,
        proxy_port=proxy_port,
        drained=drained,
        interrupted=interrupted,
    )
    write_run_metadata(result)

    logger.info(
        "lli run complete: exit=%d, session=%s (%d requests) → %s",
        result.exit_code,
        result.session_id,
        result.requests_captured,
        result.session_dir,
    )

    return result

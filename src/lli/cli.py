"""
Command-line interface for LLM Interceptor.

Provides the `lli` command with subcommands for watch,
merge, split, config, and stats.
"""

from __future__ import annotations

import asyncio
import re
import socket
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import click
from rich.panel import Panel
from rich.table import Table

from lli import __version__
from lli.config import get_cert_info, get_default_trace_dir, load_config
from lli.net import detect_primary_ipv4, reachable_host_for_listen_host

if TYPE_CHECKING:
    from lli.config import LLIConfig
    from lli.watch import WatchManager

from lli.logger import get_console, setup_logger
from lli.merger import merge_streams
from lli.splitter import split_records
from lli.storage import count_records

# Use the shared console from logger module for coordinated output
# This ensures proper coordination between Live displays and logging
console = get_console()


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True),
    help="Path to configuration file (TOML or YAML)",
)
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """
    LLM Interceptor (LLI) - MITM Proxy for LLM Traffic Analysis.

    Intercept, analyze, and log communications between AI coding tools/agents
    and their backend LLM APIs.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


@main.command()
@click.option(
    "--input",
    "-i",
    "input_file",
    type=click.Path(exists=True),
    required=True,
    help="Input JSONL file with raw streaming chunks",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    type=click.Path(),
    required=True,
    help="Output JSONL file for merged records",
)
def merge(input_file: str, output_file: str) -> None:
    """
    Merge streaming response chunks into complete records.

    Reads a JSONL file containing raw streaming chunks and produces
    a new file with complete request-response pairs.

    Example:

        lli merge --input raw_trace.jsonl --output merged.jsonl
    """
    setup_logger("INFO")

    console.print(f"[cyan]Merging:[/] {input_file} → {output_file}")

    try:
        stats = merge_streams(input_file, output_file)

        # Display results
        table = Table(title="Merge Statistics", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Requests", str(stats["total_requests"]))
        table.add_row("Streaming Requests", str(stats["streaming_requests"]))
        table.add_row("Non-Streaming Requests", str(stats["non_streaming_requests"]))
        table.add_row("Incomplete Requests", str(stats["incomplete_requests"]))
        table.add_row("Total Chunks Processed", str(stats["total_chunks_processed"]))

        console.print()
        console.print(table)
        console.print(f"\n[green]✓ Output saved to:[/] {output_file}")

    except FileNotFoundError:
        console.print(f"[red]Error:[/] Input file not found: {input_file}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


@main.command()
@click.option(
    "--input",
    "-i",
    "input_file",
    type=click.Path(exists=True),
    required=True,
    help="Input merged JSONL file",
)
@click.option(
    "--output-dir",
    "-o",
    "output_dir",
    type=click.Path(),
    default="./split_output",
    help="Output directory for split files (default: ./split_output)",
)
def split(input_file: str, output_dir: str) -> None:
    """
    Split merged JSONL into individual JSON files for analysis.

    Reads a merged JSONL file and produces individual JSON files
    for each request and response record.

    Output files are named: {index:03d}_{type}_{timestamp}.json
    Example files: 001_request_2025-11-26_14-12-47.json
                   001_response_2025-11-26_14-12-47.json

    Example:

        lli split --input merged.jsonl --output-dir ./analysis
    """
    setup_logger("INFO")

    console.print(f"[cyan]Splitting:[/] {input_file} → {output_dir}/")

    try:
        stats = split_records(input_file, output_dir)

        # Display results
        table = Table(title="Split Statistics", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Records", str(stats["total_records"]))
        table.add_row("Request Files", str(stats["request_files"]))
        table.add_row("Response Files", str(stats["response_files"]))
        table.add_row("Errors", str(stats["errors"]))

        console.print()
        console.print(table)
        console.print(f"\n[green]✓ Output saved to:[/] {output_dir}/")

    except FileNotFoundError:
        console.print(f"[red]Error:[/] Input file not found: {input_file}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        sys.exit(1)


@main.command()
@click.option(
    "--cert-help",
    is_flag=True,
    help="Show certificate installation instructions",
)
@click.option(
    "--proxy-help",
    is_flag=True,
    help="Show proxy configuration instructions",
)
@click.option(
    "--show",
    is_flag=True,
    help="Show current configuration",
)
@click.pass_context
def config(
    ctx: click.Context,
    cert_help: bool,
    proxy_help: bool,
    show: bool,
) -> None:
    """
    Display configuration and setup help.

    Examples:

        lli config --cert-help

        lli config --proxy-help

        lli config --show
    """
    if cert_help:
        _show_cert_help()
    elif proxy_help:
        _show_proxy_help()
    elif show:
        _show_config(ctx.obj.get("config_path"))
    else:
        # Show all help by default
        _show_cert_help()
        console.print()
        _show_proxy_help()


def _show_cert_help() -> None:
    """Display certificate installation instructions."""
    cert_info = get_cert_info()

    console.print("[bold cyan]Certificate Installation Guide[/]")
    console.print("=" * 50)
    console.print()

    console.print(f"[dim]Certificate path:[/] {cert_info['cert_path']}")
    exists_text = (
        "[green]Yes[/]" if cert_info["exists"] else "[yellow]No (will be generated on first run)[/]"
    )
    console.print(f"[dim]Certificate exists:[/] {exists_text}")
    console.print()

    console.print("[bold]macOS:[/]")
    console.print("  1. Run the proxy once to generate the certificate")
    console.print(f"  2. Open: {cert_info['cert_path']}")
    console.print("  3. Double-click to add to Keychain")
    console.print("  4. In Keychain Access, find 'mitmproxy'")
    console.print("  5. Double-click → Trust → 'Always Trust'")
    console.print()

    console.print("[bold]Linux:[/]")
    console.print("  # Ubuntu/Debian:")
    console.print(
        f"  sudo cp {cert_info['cert_path']} /usr/local/share/ca-certificates/mitmproxy.crt"
    )
    console.print("  sudo update-ca-certificates")
    console.print()
    console.print("  # Fedora/RHEL:")
    console.print(f"  sudo cp {cert_info['cert_path']} /etc/pki/ca-trust/source/anchors/")
    console.print("  sudo update-ca-trust")
    console.print()

    console.print("[bold]Windows:[/]")
    console.print(f"  1. Open: {cert_info['cert_path']}")
    console.print("  2. Click 'Install Certificate'")
    console.print("  3. Select 'Local Machine' → Next")
    console.print("  4. 'Place all certificates in the following store'")
    console.print("  5. Browse → 'Trusted Root Certification Authorities'")
    console.print("  6. Finish")


def _show_proxy_help() -> None:
    """Display proxy configuration instructions."""
    config = load_config()
    console.print("[bold cyan]Proxy Configuration Guide[/]")
    console.print("=" * 50)
    console.print()

    console.print("[bold]Environment Variables (Shell):[/]")
    console.print("  export HTTP_PROXY=http://127.0.0.1:9090")
    console.print("  export HTTPS_PROXY=http://127.0.0.1:9090")
    if config.proxy.no_proxy:
        console.print(f"  export NO_PROXY={','.join(config.proxy.no_proxy)}")
    console.print()

    console.print("[bold]Claude Code:[/]")
    console.print("  # Set in your shell before running claude:")
    console.print("  export HTTP_PROXY=http://127.0.0.1:9090")
    console.print("  export HTTPS_PROXY=http://127.0.0.1:9090")
    console.print("  claude")
    console.print()

    console.print("[bold]Cursor IDE:[/]")
    console.print("  # Add to your shell profile (.bashrc, .zshrc):")
    console.print("  export HTTP_PROXY=http://127.0.0.1:9090")
    console.print("  export HTTPS_PROXY=http://127.0.0.1:9090")
    console.print("  # Then restart Cursor from that terminal")
    console.print()

    console.print("[bold]curl:[/]")
    console.print("  curl -x http://127.0.0.1:9090 https://api.anthropic.com/v1/messages ...")
    console.print()

    console.print("[bold]Python requests:[/]")
    console.print("  import requests")
    console.print('  proxies = {"http": "http://127.0.0.1:9090", "https": "http://127.0.0.1:9090"}')
    console.print("  requests.post(url, proxies=proxies, verify=False)")
    console.print()
    console.print("[bold]LAN capture (listen on all interfaces):[/]")
    console.print("  lli watch --lan")
    console.print("  # It will print the detected LAN IP + port for you.")


def _show_config(config_path: str | None) -> None:
    """Display current configuration."""
    config = load_config(config_path)

    console.print("[bold cyan]Current Configuration[/]")
    console.print("=" * 50)
    console.print()

    # Proxy settings
    console.print("[bold]Proxy:[/]")
    console.print(f"  Host: {config.proxy.host}")
    console.print(f"  Port: {config.proxy.port}")
    if config.proxy.no_proxy:
        console.print(f"  No-proxy: {', '.join(config.proxy.no_proxy)}")
    else:
        console.print("  No-proxy: (not set)")
    if config.proxy.upstream_ca_cert:
        console.print(f"  Upstream CA cert: {config.proxy.upstream_ca_cert}")
    else:
        console.print("  Upstream CA cert: (not set)")
    console.print()

    # Filter settings
    console.print("[bold]URL Filters:[/]")
    console.print("  Include patterns:")
    for pattern in config.filter.include_patterns:
        console.print(f"    - {pattern}")
    if config.filter.exclude_patterns:
        console.print("  Exclude patterns:")
        for pattern in config.filter.exclude_patterns:
            console.print(f"    - {pattern}")
    console.print()

    # Storage settings
    console.print("[bold]Storage:[/]")
    console.print(f"  Output file: {config.storage.output_file}")
    console.print(f"  Pretty JSON: {config.storage.pretty_json}")
    console.print()

    # Masking settings
    console.print("[bold]Masking:[/]")
    console.print(f"  Mask auth headers: {config.masking.mask_auth_headers}")
    console.print(f"  Sensitive headers: {', '.join(config.masking.sensitive_headers)}")


@main.command()
@click.argument("file", type=click.Path(exists=True))
def stats(file: str) -> None:
    """
    Display statistics for a captured trace file.

    Example:

        lli stats my_trace.jsonl
    """
    setup_logger("INFO")

    counts = count_records(file)

    table = Table(title=f"Statistics for {file}")
    table.add_column("Record Type", style="cyan")
    table.add_column("Count", style="green", justify="right")

    total = 0
    for record_type, count in sorted(counts.items()):
        table.add_row(record_type, str(count))
        total += count

    table.add_row("─" * 20, "─" * 10)
    table.add_row("[bold]Total[/]", f"[bold]{total}[/]")

    console.print(table)


@main.command()
@click.option(
    "--port",
    "-p",
    type=int,
    default=9090,
    show_default=True,
    help="Proxy server port (default: 9090)",
)
@click.option(
    "--lan",
    is_flag=True,
    help="Listen on the LAN (bind proxy to 0.0.0.0) and print a reachable LAN IP.",
)
@click.option(
    "--output-dir",
    "--log-dir",
    "-o",
    "output_dir",
    type=click.Path(),
    help="Root output directory (default: ./traces or OS-specific logs dir)",
)
@click.option(
    "--include",
    "-i",
    multiple=True,
    help="Additional URL patterns to include (glob pattern, e.g. '*api.example.com*')",
)
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help=(
        "URL patterns to exclude (glob). Excluded URLs won't be captured and will also be "
        "bypassed via mitmproxy ignore_hosts (best-effort)."
    ),
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug mode with verbose logging",
)
@click.option(
    "--ui",
    is_flag=True,
    default=True,
    help="Launch the web UI (default: True)",
)
@click.option(
    "--ui-host",
    default="127.0.0.1",
    show_default=True,
    help="Host interface for the web UI (use 0.0.0.0 to expose on the network)",
)
@click.option(
    "--ui-port",
    default=48080,
    show_default=True,
    type=int,
    help="Port for the web UI",
)
@click.option(
    "--upstream-ca-cert",
    type=click.Path(exists=False),
    default=None,
    help="Path to PEM or CA bundle for trusting upstream (e.g. corporate proxy) certificates",
)
@click.pass_context
def watch(
    ctx: click.Context,
    port: int,
    lan: bool,
    output_dir: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    debug: bool,
    ui: bool,
    ui_host: str,
    ui_port: int,
    upstream_ca_cert: str | None,
) -> None:
    """
    Start watch mode for continuous session capture.

    Watch mode provides an interactive interface to capture multiple
    coding sessions. Press Enter to start/stop processing a session.
    While recording, press Esc to cancel the current session.

    State Machine:
      - IDLE: Traffic is captured but not assigned to a session
      - RECORDING: Traffic is captured with session ID injection
      - PROCESSING: Session data is extracted, merged, and split

    Examples:

        lli watch

        lli watch --port 9090 --output-dir ./my_traces

        lli watch --include "*my-custom-api.com*"

        lli watch --exclude "*example.com/health*" --exclude "*example.com/metrics*"

        lli watch --upstream-ca-cert /path/to/corporate-ca.pem

    Configure your target application to use this proxy (replace the port as needed):

        export HTTP_PROXY=http://127.0.0.1:9090

        export HTTPS_PROXY=http://127.0.0.1:9090

        export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem
    """
    from lli.watch import WatchManager

    # Load configuration
    config = load_config(ctx.obj.get("config_path"))

    # Apply CLI overrides only when explicitly provided
    port_source = ctx.get_parameter_source("port")
    if port_source == click.core.ParameterSource.DEFAULT:
        port = config.proxy.port
    else:
        config.proxy.port = port

    # Apply proxy host rules:
    # - With --lan: bind to all interfaces (0.0.0.0) and show LAN IP in help text.
    # - Without --lan: always default to loopback (127.0.0.1) as requested.
    if lan:
        config.proxy.host = "0.0.0.0"
    else:
        config.proxy.host = "127.0.0.1"

    # CLI override for upstream CA cert (explicit --upstream-ca-cert overrides config/env)
    if upstream_ca_cert is not None:
        config.proxy.upstream_ca_cert = upstream_ca_cert

    # Add custom glob patterns (user-provided via CLI)
    for pattern in include:
        config.filter.include_globs.append(pattern)

    # Exclude patterns provided via CLI:
    # - Always exclude from capture (filter.exclude_globs)
    # - Also bypass interception via mitmproxy ignore_hosts (proxy.no_proxy)
    #   so these requests don't get MITM'd.
    for pattern in exclude:
        config.filter.exclude_globs.append(pattern)
        config.proxy.no_proxy = config.proxy.no_proxy or []
        config.proxy.no_proxy.append(_glob_to_regex(pattern))

    if debug:
        config.logging.level = "DEBUG"

    # Determine output directory
    if output_dir is None:
        output_dir = str(get_default_trace_dir())

    # Setup logging
    setup_logger(config.logging.level, config.logging.log_file)

    # Check certificate
    cert_info = get_cert_info()
    if not cert_info["exists"]:
        console.print(
            "[yellow]⚠ mitmproxy CA certificate not found.[/]\n"
            "  Run 'lli config --cert-help' for installation instructions.\n"
            "  The certificate will be generated on first run.\n"
        )

    # Create watch manager
    watch_manager = WatchManager(output_dir=output_dir, port=port)

    # Launch UI server if requested
    if ui:
        from lli.server import run_server

        if _is_port_in_use(ui_host, ui_port):
            ui_url = f"http://{reachable_host_for_listen_host(ui_host)}:{ui_port}"
            console.print(
                Panel(
                    f"Port {ui_port} is already in use.\n"
                    f"Assuming the UI is running at [bold link={ui_url}]{ui_url}[/].\n"
                    "Use '--no-ui' to silence this message.",
                    title="[bold yellow]Web UI Already Running[/]",
                    border_style="yellow",
                )
            )
        else:
            server_thread = threading.Thread(
                target=run_server,
                args=(watch_manager,),
                kwargs={"host": ui_host, "port": ui_port},
                daemon=True,
            )
            server_thread.start()

            ui_url = f"http://{reachable_host_for_listen_host(ui_host)}:{ui_port}"
            console.print(
                Panel(
                    f"Analyze sessions at: [bold link={ui_url}]{ui_url}[/]",
                    title="[bold green]Web UI Available[/]",
                    border_style="green",
                )
            )

    # Display startup info
    _display_watch_banner(
        port,
        output_dir,
        watch_manager.global_log_path,
        config,
        lan=lan,
    )

    # Initialize watch manager
    watch_manager.initialize()

    # State for controlling the event loop
    stop_event = threading.Event()

    def run_proxy_in_thread() -> None:
        """Run the proxy in a separate thread."""
        from lli.proxy import run_watch_proxy

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_watch_proxy(config, watch_manager))
        except Exception as e:
            if not stop_event.is_set():
                console.print(f"[red]Proxy error:[/] {e}")
        finally:
            loop.close()

    # Start proxy in background thread
    proxy_thread = threading.Thread(target=run_proxy_in_thread, daemon=True)
    proxy_thread.start()

    try:
        # Main interactive loop
        _run_watch_loop(watch_manager, stop_event)
    except KeyboardInterrupt:
        console.print("\n[cyan]Watch mode stopped.[/]")
    finally:
        stop_event.set()
        watch_manager.shutdown()

        # Show summary
        output_path = Path(output_dir)
        if output_path.exists():
            session_dirs = [d for d in output_path.iterdir() if d.is_dir() and "session" in d.name]
            console.print(f"\n[green]Sessions captured:[/] {len(session_dirs)}")
            console.print(f"[green]Output directory:[/] {output_path.absolute()}")
            console.print(f"[green]Global log:[/] {watch_manager.global_log_path}")


@main.command()
@click.argument("command", nargs=-1, required=True)
@click.option(
    "--label",
    "-l",
    default=None,
    help="Label for the run directory (e.g. --label codex gives run_<ts>_codex)",
)
@click.option(
    "--output-dir",
    "-o",
    "output_root",
    type=click.Path(),
    default=None,
    help="Traces root for session output (default: same as lli watch)",
)
@click.option(
    "--include",
    "-i",
    multiple=True,
    help="Additional URL patterns to include (glob pattern, e.g. '*api.example.com*')",
)
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help="URL patterns to exclude (glob). Excluded URLs won't be captured and will also be "
    "bypassed via mitmproxy ignore_hosts (best-effort).",
)
@click.option(
    "--drain-timeout",
    type=float,
    default=15.0,
    show_default=True,
    help="Seconds to wait for in-flight responses after the command exits",
)
@click.option(
    "--upstream-ca-cert",
    type=click.Path(exists=False),
    default=None,
    help="Path to PEM or CA bundle for trusting upstream (e.g. corporate proxy) certificates",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug mode with verbose logging",
)
@click.pass_context
def run(
    ctx: click.Context,
    command: tuple[str, ...],
    label: str | None,
    output_root: str | None,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    drain_timeout: float,
    upstream_ca_cert: str | None,
    debug: bool,
) -> None:
    """
    Run a command with automatic LLM traffic capture (no keypresses needed).

    Starts an ephemeral capture proxy, spawns COMMAND with proxy and CA
    environment variables injected, and when the command exits: drains
    in-flight responses, processes the session (merge + split into
    per-exchange request/response JSON files), and writes run metadata.
    Exits with the command's exit code.

    The session lands directly in the traces directory alongside watch-mode
    sessions (microsecond IDs keep concurrent runs collision-free), so it
    appears in the web UI automatically:

        <output-dir>/session_<timestamp>_<usec>/
            session_meta.json
            run_meta.json     # command, label, exit code, duration, ...
            001_request_*.json / 001_response_*.json / ...

    Examples:

        lli run -- claude -p "fix the failing test"

        lli run --label codex -- codex exec "review src/"

        lli run --include "*my-llm.example.com*" -- curl -s https://api.example.com/health
    """
    from lli.runner import run_wrapped_command

    config = load_config(ctx.obj.get("config_path"))

    if upstream_ca_cert is not None:
        config.proxy.upstream_ca_cert = upstream_ca_cert

    for pattern in include:
        config.filter.include_globs.append(pattern)

    for pattern in exclude:
        config.filter.exclude_globs.append(pattern)
        config.proxy.no_proxy = config.proxy.no_proxy or []
        config.proxy.no_proxy.append(_glob_to_regex(pattern))

    if debug:
        config.logging.level = "DEBUG"

    setup_logger(config.logging.level, config.logging.log_file)

    cert_info = get_cert_info()
    if not cert_info["exists"]:
        console.print(
            "[yellow]⚠ mitmproxy CA certificate not found.[/]\n"
            "  It will be generated on first run; HTTPS interception may fail\n"
            "  for the wrapped command until it exists.\n"
        )

    console.print(f"[cyan]▶ lli run:[/] {' '.join(command)}")

    try:
        result = asyncio.run(
            run_wrapped_command(
                list(command),
                config=config,
                label=label,
                output_root=output_root,
                drain_timeout=drain_timeout,
            )
        )
    except Exception as e:
        console.print(f"[red]Run failed:[/] {e}")
        sys.exit(1)

    console.print()
    status = "interrupted" if result.interrupted else "finished"
    console.print(
        f"[green]✔[/] Session [cyan]{result.session_id}[/] {status} "
        f"(exit code {result.exit_code}, {result.requests_captured} requests captured)"
    )
    console.print(f"  Session: [cyan]{result.session_dir}[/]")
    console.print(f"  Metadata: [cyan]{result.metadata_path}[/]")

    sys.exit(result.exit_code)


@main.command()
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host interface to bind the web UI (use 0.0.0.0 to expose on the network)",
)
@click.option(
    "--port",
    "-p",
    default=48080,
    show_default=True,
    type=int,
    help="Port for the web UI",
)
@click.option(
    "--output-dir",
    "-o",
    "output_dir",
    type=click.Path(),
    default=None,
    help="Traces directory to serve (default: ./traces or OS-specific logs dir)",
)
def serve(
    host: str,
    port: int,
    output_dir: str | None,
) -> None:
    """
    Start the web UI as a standalone, long-running server.

    Serves all captured sessions (from `lli watch` and `lli run`) and picks
    up new ones automatically as they are processed. Keep this running in
    one terminal and capture from any other terminal.

    Examples:

        lli serve

        lli serve --port 48080 --output-dir ./traces
    """
    from lli.server import StaticTracesProvider, run_server

    setup_logger("INFO")

    if output_dir is None:
        output_dir = str(get_default_trace_dir())

    if _is_port_in_use(host, port):
        ui_url = f"http://{reachable_host_for_listen_host(host)}:{port}"
        console.print(
            f"[red]Error:[/] Port {port} is already in use.\n"
            f"  If a web UI is already running at {ui_url}, just reuse it;\n"
            "  otherwise pick another port with --port."
        )
        sys.exit(1)

    traces_dir = Path(output_dir)
    provider = StaticTracesProvider(output_dir=traces_dir)

    ui_url = f"http://{reachable_host_for_listen_host(host)}:{port}"
    console.print(
        Panel.fit(
            f"[bold cyan]LLI Web UI[/]\n[dim]Standalone session viewer[/]\n\n"
            f"Serving traces from: [cyan]{traces_dir.absolute()}[/]\n"
            f"Analyze sessions at: [bold link={ui_url}]{ui_url}[/]\n\n"
            f"[dim]New sessions from `lli watch` / `lli run` appear automatically "
            "(Ctrl+C to stop).[/]",
            border_style="cyan",
        )
    )

    try:
        run_server(provider, host=host, port=port)
    except KeyboardInterrupt:
        console.print("\n[cyan]Web UI stopped.[/]")


def _display_watch_banner(
    port: int,
    output_dir: str,
    global_log_path: Path,
    config: LLIConfig,
    lan: bool = False,
) -> None:
    """Display the watch mode startup banner."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]LLI Watch Mode[/]\n[dim]Continuous Capture Interface[/]",
            border_style="cyan",
        )
    )
    console.print()
    console.print(f"  [cyan]Proxy Port:[/]    {port}")
    console.print(f"  [cyan]Output Dir:[/]    {output_dir}")
    console.print(f"  [cyan]Global Log:[/]    {global_log_path}")
    if config.proxy.upstream_ca_cert:
        ca_path = Path(config.proxy.upstream_ca_cert)
        exists_hint = "[green]exists[/]" if ca_path.exists() else "[yellow]file not found[/]"
        console.print(f"  [cyan]Upstream CA:[/]   {config.proxy.upstream_ca_cert} ({exists_hint})")
    console.print()

    # Display filter rules
    _display_filter_rules(config)

    console.print("[dim]Configure your application:[/]")
    if lan:
        detected = detect_primary_ipv4() or "<your_lan_ip>"
        console.print(f"  export HTTP_PROXY=http://{detected}:{port}")
        console.print(f"  export HTTPS_PROXY=http://{detected}:{port}")
    else:
        console.print(f"  export HTTP_PROXY=http://127.0.0.1:{port}")
        console.print(f"  export HTTPS_PROXY=http://127.0.0.1:{port}")
    if config.proxy.no_proxy:
        console.print(f"  export NO_PROXY={','.join(config.proxy.no_proxy)}")
    console.print("  export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem")
    console.print()


def _display_filter_rules(config: LLIConfig) -> None:
    """Display the current URL filter rules."""
    console.print("[bold cyan]URL Filter Rules:[/]")

    # Built-in include patterns (regex)
    if config.filter.include_patterns:
        console.print("  [green]Include (built-in):[/]")
        for pattern in config.filter.include_patterns:
            # Extract domain name from regex pattern for display
            # e.g., ".*api\.anthropic\.com.*" -> "api.anthropic.com"
            display = pattern.replace(r".*", "").replace("\\.", ".")
            console.print(f"    [dim]•[/] {display}")

    # User-provided include globs
    if config.filter.include_globs:
        console.print("  [green]Include (custom glob):[/]")
        for pattern in config.filter.include_globs:
            console.print(f"    [bold green]•[/] {pattern}")

    # Exclude patterns
    if config.filter.exclude_patterns:
        console.print("  [red]Exclude (regex):[/]")
        for pattern in config.filter.exclude_patterns:
            display = pattern.replace(r".*", "").replace("\\.", ".")
            console.print(f"    [dim]•[/] {display}")

    if config.filter.exclude_globs:
        console.print("  [red]Exclude (custom glob):[/]")
        for pattern in config.filter.exclude_globs:
            console.print(f"    [bold red]•[/] {pattern}")

    console.print()


def _glob_to_regex(glob_pattern: str) -> str:
    """
    Convert a glob-ish URL/host pattern to a regex string.

    Used for mapping `--exclude` patterns to mitmproxy `ignore_hosts`, which expects regex.
    mitmproxy's `ignore_hosts` is evaluated against the request host in most setups,
    so we try to derive a host-oriented regex even if the user provides a full URL glob.
    """
    # Heuristic: prefer matching host portion if we can derive it.
    raw = glob_pattern.strip()
    candidate = raw

    # If it looks like a URL, parse it and use netloc.
    if "://" in raw:
        parsed = urlparse(raw.replace("*", "x").replace("?", "x"))
        if parsed.netloc:
            candidate = parsed.netloc
    else:
        # If it's a URL-ish glob without scheme, drop any path/query fragments.
        candidate = raw.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]

    # Escape regex meta, then replace glob wildcards.
    # Note: we do NOT anchor with ^/$ so substrings match.
    s = re.escape(candidate)
    s = s.replace(r"\*", ".*").replace(r"\?", ".")
    return s


def _run_watch_loop(watch_manager: WatchManager, stop_event: threading.Event) -> None:
    """Run the main watch mode interaction loop."""
    from lli.watch import WatchState

    def _recording_status_text(session_id: str) -> str:
        return (
            f"[bold red]◉[/] [red][REC][/] Session [bold]{session_id}[/] recording  "
            f"[dim]Press [Enter] to STOP & PROCESS, [Esc] to CANCEL[/]"
        )

    while not stop_event.is_set():
        state = watch_manager.state

        if state == WatchState.IDLE:
            # Display IDLE status with spinner pinned at bottom
            idle_status_text = (
                f"[bold green]●[/] [green][IDLE][/] Monitoring on :{watch_manager.port}  "
                f"[dim]Press [Enter] to START Session {watch_manager.next_session_id}[/]"
            )

            with console.status(idle_status_text, spinner="dots", spinner_style="green"):
                try:
                    input()
                except EOFError:
                    break

            if stop_event.is_set():
                break

            # Start recording
            try:
                session = watch_manager.start_recording()
                session_id = session.session_id

                console.print(
                    f"\n[bold green]▶[/] [green][START][/] Session [bold]{session_id}[/] "
                    f"recording (requests: {session.request_count})"
                )

                # Display RECORDING status once to avoid spinner refresh noise
                with console.status(
                    _recording_status_text(session_id),
                    spinner="point",
                    spinner_style="red",
                ):
                    try:
                        key = _wait_for_enter_or_escape()
                    except EOFError:
                        break

                if stop_event.is_set():
                    break

                if key == "escape":
                    cancelled = watch_manager.cancel_recording()
                    console.print(
                        f"\n[bold yellow]✖[/] [yellow][CANCEL][/]"
                        f" Session [bold]{session_id}[/] cancelled "
                        f"(requests: {cancelled.request_count})."
                    )
                    console.print()
                else:
                    # Stop recording and process
                    session = watch_manager.stop_recording()
                    console.print(
                        f"\n[bold yellow]⏳[/] [yellow][BUSY][/] Processing "
                        f"Session [bold]{session_id}[/] "
                        f"(requests: {session.request_count})..."
                    )

                    # Process the session
                    session_dir = watch_manager.process_session(session)
                    console.print(f"  [green]✔[/] Saved to [cyan]{session_dir}/[/]")
                    console.print()

            except RuntimeError as e:
                console.print(f"[red]Error:[/] {e}")

        elif state == WatchState.RECORDING:
            # This branch handles the case where we enter the loop already in RECORDING state
            # (e.g., after an error or unexpected state transition)
            session_id = (
                watch_manager.current_session.session_id if watch_manager.current_session else "?"
            )
            with console.status(
                _recording_status_text(session_id),
                spinner="point",
                spinner_style="red",
            ):
                try:
                    key = _wait_for_enter_or_escape()
                except EOFError:
                    break

            if stop_event.is_set():
                break

            try:
                if key == "escape":
                    cancelled = watch_manager.cancel_recording()
                    console.print(
                        f"\n[bold yellow]✖[/] [yellow][CANCEL][/]"
                        f" Session [bold]{cancelled.session_id}[/] cancelled "
                        f"(requests: {cancelled.request_count})."
                    )
                    console.print()
                else:
                    # Stop recording and process
                    session = watch_manager.stop_recording()
                    session_id = session.session_id
                    console.print(
                        f"\n[bold yellow]⏳[/] [yellow][BUSY][/] Processing "
                        f"Session [bold]{session_id}[/] "
                        f"(requests: {session.request_count})..."
                    )

                    # Process the session
                    session_dir = watch_manager.process_session(session)
                    console.print(f"  [green]✔[/] Saved to [cyan]{session_dir}/[/]")
                    console.print()
            except RuntimeError as e:
                console.print(f"[red]Error processing session:[/] {e}")

        elif state == WatchState.PROCESSING:
            # Wait for processing to complete (should not normally reach here)
            import time

            time.sleep(0.1)


def _wait_for_enter_or_escape(
    timeout: float | None = None,
) -> Literal["enter", "escape"] | None:
    """
    Wait for a single keypress: Enter or Escape.

    Falls back to line-buffered input when stdin is not a TTY (e.g. piped).
    """
    if not sys.stdin.isatty():
        if timeout is None:
            input()
            return "enter"
        return None

    if sys.platform.startswith("win"):
        # Windows: use msvcrt for unbuffered key input
        import msvcrt
        import time

        if timeout is None:
            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    return "enter"
                if ch == "\x1b":
                    return "escape"
        else:
            end_time = time.time() + timeout
            while time.time() < end_time:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        return "enter"
                    if ch == "\x1b":
                        return "escape"
                time.sleep(0.01)
            return None
    else:
        # POSIX: temporarily switch terminal to raw mode
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            if timeout is None:
                while True:
                    rlist, _, _ = select.select([fd], [], [])
                    if rlist:
                        ch = sys.stdin.read(1)
                        if ch in ("\r", "\n"):
                            return "enter"
                        if ch == "\x1b":
                            return "escape"
            else:
                rlist, _, _ = select.select([fd], [], [], timeout)
                if not rlist:
                    return None
                ch = sys.stdin.read(1)
                if ch in ("\r", "\n"):
                    return "enter"
                if ch == "\x1b":
                    return "escape"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return None


def _is_port_in_use(host: str, port: int) -> bool:
    """Return True if the given host:port combination is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


if __name__ == "__main__":
    main(obj={})

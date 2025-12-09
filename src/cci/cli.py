"""
Command-line interface for Claude-Code-Inspector.

Provides the `cci` command with subcommands for watch, merge, split, config, and stats.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cci import __version__
from cci.config import get_cert_info, load_config

if TYPE_CHECKING:
    from cci.config import CCIConfig
    from cci.watch import WatchManager
from cci.logger import setup_logger
from cci.merger import merge_streams
from cci.splitter import split_records
from cci.storage import count_records

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="cci")
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
    Claude-Code-Inspector (CCI) - MITM Proxy for LLM API Traffic Analysis.

    Intercept, analyze, and log communications between AI coding assistants
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

        cci merge --input raw_trace.jsonl --output merged.jsonl
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

        cci split --input merged.jsonl --output-dir ./analysis
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

        cci config --cert-help

        cci config --proxy-help

        cci config --show
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
        f"  sudo cp {cert_info['cert_path']} " "/usr/local/share/ca-certificates/mitmproxy.crt"
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
    console.print("[bold cyan]Proxy Configuration Guide[/]")
    console.print("=" * 50)
    console.print()

    console.print("[bold]Environment Variables (Shell):[/]")
    console.print("  export HTTP_PROXY=http://127.0.0.1:8080")
    console.print("  export HTTPS_PROXY=http://127.0.0.1:8080")
    console.print()

    console.print("[bold]Claude Code:[/]")
    console.print("  # Set in your shell before running claude:")
    console.print("  export HTTP_PROXY=http://127.0.0.1:8080")
    console.print("  export HTTPS_PROXY=http://127.0.0.1:8080")
    console.print("  claude")
    console.print()

    console.print("[bold]Cursor IDE:[/]")
    console.print("  # Add to your shell profile (.bashrc, .zshrc):")
    console.print("  export HTTP_PROXY=http://127.0.0.1:8080")
    console.print("  export HTTPS_PROXY=http://127.0.0.1:8080")
    console.print("  # Then restart Cursor from that terminal")
    console.print()

    console.print("[bold]curl:[/]")
    console.print("  curl -x http://127.0.0.1:8080 https://api.anthropic.com/v1/messages ...")
    console.print()

    console.print("[bold]Python requests:[/]")
    console.print("  import requests")
    console.print('  proxies = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}')
    console.print("  requests.post(url, proxies=proxies, verify=False)")


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

        cci stats my_trace.jsonl
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
    help="Proxy server port (default: 9090)",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(),
    default="./traces",
    help="Root output directory (default: ./traces)",
)
@click.option(
    "--include",
    "-i",
    multiple=True,
    help="Additional URL patterns to include (glob pattern, e.g. '*api.example.com*')",
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
@click.pass_context
def watch(
    ctx: click.Context,
    port: int,
    output_dir: str,
    include: tuple[str, ...],
    debug: bool,
    ui: bool,
) -> None:
    """
    Start watch mode for continuous session capture.

    Watch mode provides an interactive interface to capture multiple
    coding sessions. Press Enter to toggle between IDLE and RECORDING
    states.

    State Machine:
      - IDLE: Traffic is captured but not assigned to a session
      - RECORDING: Traffic is captured with session ID injection
      - PROCESSING: Session data is extracted, merged, and split

    Examples:

        cci watch

        cci watch --port 9090 --output-dir ./my_traces

        cci watch --include "*my-custom-api.com*"

    Configure your target application to use this proxy:

        export HTTP_PROXY=http://127.0.0.1:9090

        export HTTPS_PROXY=http://127.0.0.1:9090

        export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem
    """
    from cci.watch import WatchManager

    # Load configuration
    config = load_config(ctx.obj.get("config_path"))

    # Apply CLI overrides
    config.proxy.port = port

    # Add custom glob patterns (user-provided via CLI)
    for pattern in include:
        config.filter.include_globs.append(pattern)

    if debug:
        config.logging.level = "DEBUG"

    # Setup logging
    setup_logger(config.logging.level, config.logging.log_file)

    # Check certificate
    cert_info = get_cert_info()
    if not cert_info["exists"]:
        console.print(
            "[yellow]⚠ mitmproxy CA certificate not found.[/]\n"
            "  Run 'cci config --cert-help' for installation instructions.\n"
            "  The certificate will be generated on first run.\n"
        )

    # Create watch manager
    watch_manager = WatchManager(output_dir=output_dir, port=port)

    # Launch UI server if requested
    if ui:
        from cci.server import run_server

        ui_port = 8000  # TODO: Make configurable
        server_thread = threading.Thread(
            target=run_server, args=(watch_manager,), kwargs={"port": ui_port}, daemon=True
        )
        server_thread.start()

        ui_url = f"http://localhost:{ui_port}"
        console.print(
            Panel(
                f"Analyze sessions at: [bold link={ui_url}]{ui_url}[/]",
                title="[bold green]Web UI Available[/]",
                border_style="green",
            )
        )

    # Display startup info
    _display_watch_banner(port, output_dir, watch_manager.global_log_path, config)

    # Initialize watch manager
    watch_manager.initialize()

    # State for controlling the event loop
    stop_event = threading.Event()

    def run_proxy_in_thread() -> None:
        """Run the proxy in a separate thread."""
        from cci.proxy import run_watch_proxy

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


def _display_watch_banner(
    port: int,
    output_dir: str,
    global_log_path: Path,
    config: CCIConfig,
) -> None:
    """Display the watch mode startup banner."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]CCI Watch Mode[/]\n" "[dim]Continuous Capture Interface[/]",
            border_style="cyan",
        )
    )
    console.print()
    console.print(f"  [cyan]Proxy Port:[/]    {port}")
    console.print(f"  [cyan]Output Dir:[/]    {output_dir}")
    console.print(f"  [cyan]Global Log:[/]    {global_log_path}")
    console.print()

    # Display filter rules
    _display_filter_rules(config)

    console.print("[dim]Configure your application:[/]")
    console.print(f"  export HTTP_PROXY=http://127.0.0.1:{port}")
    console.print(f"  export HTTPS_PROXY=http://127.0.0.1:{port}")
    console.print("  export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem")
    console.print()


def _display_filter_rules(config: CCIConfig) -> None:
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


def _run_watch_loop(watch_manager: WatchManager, stop_event: threading.Event) -> None:
    """Run the main watch mode interaction loop."""
    from cci.watch import WatchState

    while not stop_event.is_set():
        state = watch_manager.state

        if state == WatchState.IDLE:
            # Display IDLE prompt
            console.print(
                f"[bold green]●[/] [green][IDLE][/] Monitoring on :{watch_manager.port}... "
                f"Logging to [cyan]{watch_manager.global_log_path.name}[/]"
            )
            console.print(
                f"  [dim]Press [Enter] to START Session {watch_manager.next_session_id}[/]"
            )

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
                    f"\n[bold red]◉[/] [red][REC][/] Session [bold]{session_id}[/] is recording..."
                )
                console.print("  [dim]Press [Enter] to STOP & PROCESS[/]")
            except RuntimeError as e:
                console.print(f"[red]Error starting recording:[/] {e}")

        elif state == WatchState.RECORDING:
            try:
                input()
            except EOFError:
                break

            if stop_event.is_set():
                break

            # Stop recording and process
            try:
                session = watch_manager.stop_recording()
                session_id = session.session_id
                console.print(
                    f"\n[bold yellow]⏳[/] [yellow][BUSY][/] Processing "
                    f"Session [bold]{session_id}[/]..."
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


if __name__ == "__main__":
    main(obj={})

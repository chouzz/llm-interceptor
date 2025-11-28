"""
Command-line interface for Claude-Code-Inspector.

Provides the `cci` command with subcommands for capture, merge, and config.
"""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from cci import __version__
from cci.config import get_cert_info, load_config
from cci.logger import log_startup_banner, setup_logger
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
    "--port",
    "-p",
    type=int,
    default=8080,
    help="Proxy server port (default: 8080)",
)
@click.option(
    "--host",
    "-h",
    type=str,
    default="127.0.0.1",
    help="Proxy server host (default: 127.0.0.1)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="cci_trace.jsonl",
    help="Output file path (default: cci_trace.jsonl)",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug mode with verbose logging",
)
@click.option(
    "--include",
    "-i",
    multiple=True,
    help="Additional URL patterns to include (regex)",
)
@click.option(
    "--exclude",
    "-e",
    multiple=True,
    help="URL patterns to exclude (regex)",
)
@click.pass_context
def capture(
    ctx: click.Context,
    port: int,
    host: str,
    output: str,
    debug: bool,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> None:
    """
    Start the proxy server and capture LLM API traffic.

    The proxy will intercept HTTP/HTTPS traffic and log requests to
    configured LLM APIs (Anthropic, OpenAI, Google, etc.).

    Examples:

        cci capture --port 8080 --output my_trace.jsonl

        cci capture --debug --include ".*my-custom-api\\.com.*"

    Configure your target application to use this proxy:

        export HTTP_PROXY=http://127.0.0.1:8080

        export HTTPS_PROXY=http://127.0.0.1:8080
    """
    # Load configuration
    config = load_config(ctx.obj.get("config_path"))

    # Apply CLI overrides
    config.proxy.port = port
    config.proxy.host = host
    config.storage.output_file = output

    if debug:
        config.logging.level = "DEBUG"

    # Add custom patterns
    for pattern in include:
        config.filter.include_patterns.append(pattern)
    for pattern in exclude:
        config.filter.exclude_patterns.append(pattern)

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

    # Display startup banner
    log_startup_banner(host, port)

    # Run the proxy
    try:
        from cci.proxy import run_proxy

        asyncio.run(run_proxy(config, output))
    except KeyboardInterrupt:
        console.print("\n[cyan]Capture stopped.[/]")
        # Show summary
        output_path = Path(output)
        if output_path.exists():
            counts = count_records(output_path)
            console.print(f"\n[green]Saved to:[/] {output}")
            console.print(f"[dim]Records:[/] {sum(counts.values())} total")
            for record_type, count in counts.items():
                console.print(f"  - {record_type}: {count}")
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        if debug:
            raise
        sys.exit(1)


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
        "[green]Yes[/]" if cert_info["exists"]
        else "[yellow]No (will be generated on first run)[/]"
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
        f"  sudo cp {cert_info['cert_path']} "
        "/usr/local/share/ca-certificates/mitmproxy.crt"
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
    console.print('  import requests')
    console.print('  proxies = {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}')
    console.print('  requests.post(url, proxies=proxies, verify=False)')


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


if __name__ == "__main__":
    main(obj={})


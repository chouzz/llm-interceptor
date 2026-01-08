"""
Logging configuration for LLM Interceptor.

Implements a tiered logging system with INFO, DEBUG, and ERROR levels.
Provides a shared Console instance for unified Rich output.
"""

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

# Create a single shared console for all Rich output
# Using force_terminal=True ensures consistent behavior
# Using stderr=True keeps logs separate from stdout
console = Console(stderr=True, force_terminal=True)

# Custom logger name (kept stable for backward compatibility in log routing)
LOGGER_NAME = "llm_interceptor"

# Module-level reference to the current RichHandler for dynamic updates
_rich_handler: RichHandler | None = None


def get_console() -> Console:
    """
    Get the shared Console instance.

    This console should be used for ALL Rich output (status, panels, tables, etc.)
    to ensure proper coordination with logging output and Live displays.

    Returns:
        The shared Console instance
    """
    return console


def setup_logger(
    level: str = "INFO",
    log_file: str | Path | None = None,
    log_format: str | None = None,
) -> logging.Logger:
    """
    Set up the LLI logger with the specified configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output
        log_format: Custom log format string

    Returns:
        Configured logger instance
    """
    global _rich_handler

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    # Clear existing handlers
    logger.handlers.clear()

    # Rich console handler for pretty terminal output
    # Using the shared console ensures coordination with Live displays
    _rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        show_level=False,
        rich_tracebacks=True,
        tracebacks_show_locals=level.upper() == "DEBUG",
        markup=True,
    )
    _rich_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addHandler(_rich_handler)

    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        formatter = logging.Formatter(
            log_format or "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """Get the LLI logger instance."""
    return logging.getLogger(LOGGER_NAME)


class LogContext:
    """Context manager for temporary log level changes."""

    def __init__(self, level: str):
        self.level = level
        self.original_level: int | None = None

    def __enter__(self) -> "LogContext":
        logger = get_logger()
        self.original_level = logger.level
        logger.setLevel(getattr(logging, self.level.upper(), logging.INFO))
        return self

    def __exit__(self, *args: object) -> None:
        if self.original_level is not None:
            get_logger().setLevel(self.original_level)


def log_request_summary(
    method: str,
    url: str,
    status: int | None = None,
    latency_ms: float | None = None,
    captured: bool = True,
) -> None:
    """Log a formatted request summary."""
    logger = get_logger()

    # Capture status indicator
    if captured:
        cap_str = "[bold green][CAPT][/bold green]"
    else:
        cap_str = "[bold magenta][SKIP][/bold magenta]"

    # Color coding based on status
    if status is None:
        status_str = "→"
    elif 200 <= status < 300:
        status_str = f"[green]{status}[/green]"
    elif 300 <= status < 400:
        status_str = f"[yellow]{status}[/yellow]"
    else:
        status_str = f"[red]{status}[/red]"

    latency_str = f" ({latency_ms:.0f}ms)" if latency_ms else ""

    logger.info(f"{cap_str} {method} {url} {status_str}{latency_str}")


def log_streaming_progress(request_id: str, chunk_count: int) -> None:
    """Log streaming response progress."""
    logger = get_logger()
    logger.debug("Request %s... received chunk #%d", request_id[:8], chunk_count)


def log_error(message: str, exc: Exception | None = None) -> None:
    """Log an error with optional exception details."""
    logger = get_logger()
    if exc:
        logger.error("%s: %s", message, exc, exc_info=logger.level <= logging.DEBUG)
    else:
        logger.error("%s", message)


def log_startup_banner(host: str, port: int) -> None:
    """Log the startup banner."""
    console.print()
    # fmt: off
    console.print("[bold cyan]╔══════════════════════════════════════════════════════════╗[/]")  # noqa: E501
    console.print("[bold cyan]║[/]  [bold white]LLM Interceptor (LLI)[/]                                 [bold cyan]║[/]")  # noqa: E501
    console.print("[bold cyan]║[/]  [dim]MITM Proxy for LLM Traffic Analysis[/]                   [bold cyan]║[/]")  # noqa: E501
    console.print("[bold cyan]╠══════════════════════════════════════════════════════════╣[/]")  # noqa: E501
    console.print(f"[bold cyan]║[/]  Proxy listening on: [bold green]{host}:{port}[/]                 [bold cyan]║[/]")  # noqa: E501
    console.print("[bold cyan]║[/]                                                          [bold cyan]║[/]")  # noqa: E501
    console.print("[bold cyan]║[/]  [dim]Configure your HTTP/HTTPS proxy to point here[/]         [bold cyan]║[/]")  # noqa: E501
    console.print("[bold cyan]║[/]  [dim]Press Ctrl+C to stop capturing[/]                        [bold cyan]║[/]")  # noqa: E501
    console.print("[bold cyan]╚══════════════════════════════════════════════════════════╝[/]")  # noqa: E501
    # fmt: on
    console.print()

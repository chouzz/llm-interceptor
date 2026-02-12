"""
Command-line interface for LLM Interceptor.

The canonical CLI entrypoint is `lli`.
"""

from __future__ import annotations

from lli.cli import main as _legacy_main


def main() -> None:
    # Delegate to the CLI package implementation.
    _legacy_main(obj={})


if __name__ == "__main__":
    main()

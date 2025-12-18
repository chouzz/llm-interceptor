"""
Command-line interface for LLM Interceptor.

The canonical CLI entrypoint is `lli`.
For backward compatibility, the legacy command `cci` is also provided.
"""

from __future__ import annotations

from cci.cli import main as _legacy_main


def main() -> None:
    # Delegate to the legacy Click app. We avoid rewriting the full CLI surface
    # area here, and rely on Click to use the invoked executable name (`lli`
    # vs `cci`) in help output.
    _legacy_main(obj={})


if __name__ == "__main__":
    main()

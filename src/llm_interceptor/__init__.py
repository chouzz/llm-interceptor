"""
LLM Interceptor (LLI)

Intercept and analyze LLM traffic from AI coding tools.

This project was formerly distributed as "claude-code-inspector". The legacy
import package `cci` and CLI command `cci` are kept for backward compatibility,
but new code should prefer `llm_interceptor` and the `lli` command.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def _get_version() -> str:
    # Prefer the installed distribution version. Fall back to the legacy module
    # constant when running from source without an installed wheel.
    try:
        return version("llm-interceptor")
    except PackageNotFoundError:
        try:
            from cci import __version__ as legacy_version  # type: ignore

            return legacy_version
        except Exception:
            return "0.0.0"


__version__ = _get_version()

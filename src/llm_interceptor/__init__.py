"""
LLM Interceptor (LLI)

Intercept and analyze LLM traffic from AI coding tools.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def _get_version() -> str:
    # Prefer the installed distribution version. Fall back to the source package
    # constant when running without an installed wheel.
    try:
        return version("llm-interceptor")
    except PackageNotFoundError:
        try:
            from lli import __version__

            return __version__
        except Exception:
            return "0.0.0"


__version__ = _get_version()

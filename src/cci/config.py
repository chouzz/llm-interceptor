"""
Configuration management for LLM Interceptor.

Supports loading from TOML/YAML files or environment variables.
"""

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class FilterConfig(BaseModel):
    """URL filtering configuration."""

    # Patterns to include (regex patterns, used internally for built-in providers)
    include_patterns: list[str] = Field(
        default_factory=lambda: [
            r".*api\.anthropic\.com.*",
            r".*api\.openai\.com.*",
            r".*generativelanguage\.googleapis\.com.*",
            r".*api\.together\.xyz.*",
            r".*api\.groq\.com.*",
            r".*api\.mistral\.ai.*",
            r".*api\.cohere\.ai.*",
            r".*api\.deepseek\.com.*",
        ]
    )
    # Patterns to exclude (regex patterns, takes precedence)
    exclude_patterns: list[str] = Field(default_factory=list)
    # Glob patterns to include (user-friendly, e.g. "*api.example.com*")
    include_globs: list[str] = Field(default_factory=list)
    # Glob patterns to exclude (user-friendly, takes precedence)
    exclude_globs: list[str] = Field(default_factory=list)


class MaskingConfig(BaseModel):
    """Sensitive data masking configuration."""

    # Mask Authorization headers
    mask_auth_headers: bool = True
    # Header names to mask
    sensitive_headers: list[str] = Field(
        default_factory=lambda: ["authorization", "x-api-key", "api-key"]
    )
    # Body fields to mask (dot notation for nested)
    sensitive_body_fields: list[str] = Field(default_factory=list)
    # Mask pattern for API keys
    mask_pattern: str = "***MASKED***"


class ProxyConfig(BaseModel):
    """Proxy server configuration."""

    host: str = "127.0.0.1"
    port: int = 8080
    # SSL verification mode
    ssl_insecure: bool = False


class StorageConfig(BaseModel):
    """Storage configuration."""

    # Default output file
    output_file: str = "lli_trace.jsonl"
    # Enable pretty JSON (for debugging, not recommended for production)
    pretty_json: bool = False
    # Max file size before rotation (0 = no rotation)
    max_file_size_mb: int = 0


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)-8s | %(message)s"
    # Log to file as well
    log_file: str | None = None


class CCIConfig(BaseModel):
    """Main configuration model for LLM Interceptor (legacy name kept for compatibility)."""

    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    masking: MaskingConfig = Field(default_factory=MaskingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config(config_path: str | Path | None = None) -> CCIConfig:
    """
    Load configuration from file or create default.

    Priority:
    1. Explicit config path
    2. ./lli.toml or ./lli.yaml (preferred)
    3. ./cci.toml or ./cci.yaml (legacy)
    4. ~/.config/lli/config.toml or config.yaml (preferred)
    5. ~/.config/cci/config.toml or config.yaml (legacy)
    6. Environment variables
    7. Defaults

    Args:
        config_path: Optional explicit path to config file

    Returns:
        CCIConfig instance
    """
    config_data: dict[str, Any] = {}

    # Search paths for config files
    search_paths: list[Path] = []

    if config_path:
        search_paths.append(Path(config_path))
    else:
        # Current directory
        search_paths.extend([Path("lli.toml"), Path("lli.yaml"), Path("lli.yml")])
        search_paths.extend([Path("cci.toml"), Path("cci.yaml"), Path("cci.yml")])
        # User config directory
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        search_paths.extend(
            [
                config_home / "lli" / "config.toml",
                config_home / "lli" / "config.yaml",
                config_home / "lli" / "config.yml",
                config_home / "cci" / "config.toml",
                config_home / "cci" / "config.yaml",
                config_home / "cci" / "config.yml",
            ]
        )

    # Try to load from file
    for path in search_paths:
        if path.exists():
            config_data = _load_file(path)
            break

    # Apply environment variable overrides
    config_data = _apply_env_overrides(config_data)

    return CCIConfig(**config_data)


def _load_file(path: Path) -> dict[str, Any]:
    """Load configuration from TOML or YAML file."""
    content = path.read_text(encoding="utf-8")

    if path.suffix == ".toml":
        return tomllib.loads(content)
    elif path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(content) or {}
    else:
        raise ValueError(f"Unsupported config file format: {path.suffix}")


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to config."""
    # Map environment variables to config paths
    env_mapping = {
        # Preferred (new) names
        "LLI_PROXY_HOST": ("proxy", "host"),
        "LLI_PROXY_PORT": ("proxy", "port"),
        "LLI_OUTPUT_FILE": ("storage", "output_file"),
        "LLI_LOG_LEVEL": ("logging", "level"),
        # Legacy names (kept for backward compatibility)
        "CCI_PROXY_HOST": ("proxy", "host"),
        "CCI_PROXY_PORT": ("proxy", "port"),
        "CCI_OUTPUT_FILE": ("storage", "output_file"),
        "CCI_LOG_LEVEL": ("logging", "level"),
    }

    for env_var, path in env_mapping.items():
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(config, path, value)

    # Handle include patterns from env (comma-separated)
    include_patterns = os.environ.get("LLI_INCLUDE_PATTERNS") or os.environ.get(
        "CCI_INCLUDE_PATTERNS"
    )
    if include_patterns:
        if "filter" not in config:
            config["filter"] = {}
        config["filter"]["include_patterns"] = include_patterns.split(",")

    return config


def _set_nested(d: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Set a nested dictionary value."""
    for key in path[:-1]:
        d = d.setdefault(key, {})

    # Type conversion for certain fields
    if path[-1] == "port":
        value = int(value)

    d[path[-1]] = value


def get_cert_path() -> Path:
    """Get the mitmproxy CA certificate path."""
    # mitmproxy stores certs in ~/.mitmproxy
    mitmproxy_dir = Path.home() / ".mitmproxy"
    return mitmproxy_dir / "mitmproxy-ca-cert.pem"


def get_cert_info() -> dict[str, Any]:
    """Get certificate installation information."""
    cert_path = get_cert_path()
    return {
        "cert_path": str(cert_path),
        "exists": cert_path.exists(),
        "mitmproxy_dir": str(cert_path.parent),
    }


def get_default_trace_dir() -> Path:
    """
    Get the default directory for trace logs.

    Priority:
    1. ./traces (if it exists)
    2. OS-specific standard directories:
       - Windows: %LOCALAPPDATA%\\llm-interceptor\traces
       - macOS: ~/Library/Logs/llm-interceptor
       - Linux: ~/.cache/llm-interceptor
    """
    # 1. Check if we are in the project root or current dir has traces/
    local_traces = Path.cwd() / "traces"
    if local_traces.is_dir():
        return local_traces

    # 2. OS-specific standard directories
    if sys.platform == "win32":
        # Windows: C:\Users\<User>\AppData\Local\llm-interceptor\traces
        app_data = os.environ.get("LOCALAPPDATA")
        if app_data:
            base = Path(app_data)
        else:
            base = Path.home() / "AppData" / "Local"
        return base / "llm-interceptor" / "traces"
    elif sys.platform == "darwin":
        # macOS: ~/Library/Logs/llm-interceptor
        return Path.home() / "Library" / "Logs" / "llm-interceptor"
    else:
        # Linux: ~/.cache/llm-interceptor
        cache_home = os.environ.get("XDG_CACHE_HOME")
        if cache_home:
            base = Path(cache_home)
        else:
            base = Path.home() / ".cache"
        return base / "llm-interceptor"

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-11-28

### Added

- **New `split` command** - Split JSONL trace files into individual JSON files for easier analysis
  - Output individual JSON files for each request and response
  - Support for extracting tool_calls from messages
- **Enhanced `merge` command**
  - Added tool_calls extraction support
  - Output separate request and response lines for better organization
- **JSONLWriter improvements**
  - Added file overwrite option for more flexible output handling

### Fixed

- Corrected SSE streaming response capture for more reliable data collection

### Changed

- Improved code formatting and readability throughout the codebase

---

## [1.0.0] - 2025-11-25

### Added

- Initial release of Claude-Code-Inspector (CCI)
- **Core Features**
  - MITM proxy server using mitmproxy for traffic interception
  - Support for both streaming (SSE) and non-streaming API responses
  - Automatic API key masking in captured logs
  - JSONL output format for easy analysis
  - Stream merger utility to consolidate streaming chunks

- **CLI Commands**
  - `cci capture` - Start proxy and capture LLM API traffic
  - `cci merge` - Merge streaming response chunks into complete records
  - `cci config` - Display configuration and setup help
  - `cci stats` - Show statistics for captured trace files

- **Supported LLM Providers**
  - Anthropic (api.anthropic.com)
  - OpenAI (api.openai.com)
  - Google (generativelanguage.googleapis.com)
  - Together (api.together.xyz)
  - Groq (api.groq.com)
  - Mistral (api.mistral.ai)
  - Cohere (api.cohere.ai)
  - DeepSeek (api.deepseek.com)
  - Custom providers via `--include` pattern

- **Configuration**
  - TOML/YAML configuration file support
  - Environment variable overrides
  - URL pattern filtering (include/exclude)
  - Sensitive header masking
  - Log rotation support

- **Documentation**
  - Comprehensive README with installation instructions
  - Certificate installation guide for macOS, Linux, and Windows
  - Node.js application configuration (NODE_EXTRA_CA_CERTS)
  - Troubleshooting guide

- **CI/CD**
  - GitHub Actions workflow for CI (test on Ubuntu, macOS, Windows)
  - GitHub Actions workflow for PyPI publishing
  - Support for Python 3.10, 3.11, 3.12

### Technical Details

- Built with Python 3.10+
- Uses mitmproxy for HTTPS interception
- Pydantic for data models and validation
- Click for CLI interface
- Rich for beautiful terminal output


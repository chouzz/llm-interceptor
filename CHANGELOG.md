# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.1] - 2026-01-06

### Added

- **Configurable UI host/port** - Allow configuring the UI host and port

### Fixed

- **React hooks usage** - Avoid hooks in sessions map to prevent runtime errors

## [2.2.0] - 2026-01-05

### Added

- **Copy buttons** - Added "Copy" functionality to System and Tools interfaces for easier content extraction
- **OS-specific trace directories** - Now uses standard system directories for trace logs (XDG on Linux, Library/Logs on macOS, LocalAppData on Windows)
- **Watch mode for development** - Added auto-rebuild watch mode for UI development

### Fixed

- **Session naming & UI title** - Improved session naming logic and fixed UI title display issues
- **Session leakage & collisions** - Fixed session ID collisions and potential session leakage in watch mode

## [2.1.0] - 2025-12-24

### Added

- **Watch mode cancellation** - Added ability to cancel recording with Ctrl+C
  - Properly handles cleanup when recording is interrupted
  - New test coverage for watch cancel functionality

### Changed

- **Annotation UI improvements**
  - Fixed session annotation: changed button to div for proper group-hover behavior
  - Moved annotation display/editor inside cards for better visual consistency
  - Added blur-to-save functionality for seamless annotation editing
  - Unified styling between sessions and requests panels
  - Added Tooltip for full annotation preview on hover
  - Made annotation cards clickable for editing
- **Icon placement** - Moved app icon from project root to ui/public/ directory

### Fixed

- **Group-hover functionality** - Fixed hover buttons not appearing in session cards
- **Annotation editing** - Clicking outside annotation editor now auto-saves

## [2.0.1] - 2025-12-22

### Changed

- **App icon update** - Updated `cci-icon.png` with transparent rounded corners
  - Replaced white background corners with transparent alpha channel
  - Updated icon to 512×512 PNG format for better visual integration
  - Icon now displays well on both dark and light backgrounds
- **UI screenshot** - Updated `cci-ui-screenshot.png` to reflect latest UI changes

## [2.0.0] - 2025-12-18

### Added

- **LLM Interceptor branding** - Complete rebranding from Claude Code Inspector to LLM Interceptor (LLI)
- **Performance optimizations** - Base performance improvements for better efficiency

### Changed

- **Project rename** - Renamed from `cci` to `lli` (LLM Interceptor) across all components
- **CLI command** - Primary command changed from `cci` to `lli`
- **Package name** - Updated package name to `llm-interceptor`
- **Log improvements** - Enhanced log output coloring and deduplication for better readability

---

## [1.4.0] - 2025-12-16

### Added

- **Annotation system** - Add annotation support for sessions and requests
- **UI enhancements**
  - Favicon and custom page title
  - Chat scroll buttons for easier navigation
  - JSON text wrapping toggle in raw view
  - Auto-select newest session on load
  - Sticky tool name header for better context awareness

### Fixed

- **Windows compatibility** - Fixed npm build command execution on Windows using `shell=True`
- **Port conflict detection** - Check if UI port is in use before starting server
- **Data normalization** - Normalize token usage and static file MIME types
- **UI fixes**
  - Fixed system instruction color display
  - Fixed sticky tool header flicker during scroll

### Changed

- **Code organization** - Refactored UI into modular components and hooks
- **CLI improvements** - Centralized Rich Console instance for unified output
- **Better feedback** - CLI now uses `console.status` for improved user feedback
- **OpenAI compatibility** - Normalize OpenAI system content to string format

---

## [1.3.0] - 2025-12-09

### Added

- **React Web UI** - Modern web interface for trace analysis
  - Beautiful dark/light theme with toggle support
  - Session list with timestamp-based sorting
  - Conversation view with system prompts, messages, and tool calls
  - Multiple view tabs: Chat, System, Tools, and Raw JSON
  - Automatic API format detection (Anthropic/OpenAI)
  - Real-time session updates via polling
- **FastAPI server** - Backend API for serving UI and session data
  - RESTful endpoints for sessions and session details
  - Static file serving for bundled React app
- **UI auto-launch** - `cci watch` now automatically starts the UI server (default: enabled)
- **Build script** - `build_ui.py` for building frontend assets

### Changed

- **GitHub Actions** - Updated CI/CD workflows to build frontend UI before packaging
- **Dependencies** - Added `fastapi`, `uvicorn`, `python-multipart`, `watchdog`

---

## [1.2.0] - 2025-12-09

### Added

- **New `watch` command** - Continuous session capture mode for real-time monitoring
  - Automatic session management with timestamped directories
  - Support for custom URL patterns via `--include` option
- **Streamlit app for AI Traffic Inspector** - Web-based UI for traffic analysis
- **Glob pattern support** - URL filtering now supports glob patterns for more flexible matching

### Changed

- **CLI refactoring** - Removed `capture` command and updated subcommands for cleaner interface

---

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

- Initial release (project formerly known as Claude-Code-Inspector / CCI)
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

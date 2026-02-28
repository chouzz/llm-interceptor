"""
mitmproxy addon for LLM Interceptor.

Handles traffic interception, data capture, and sensitive data masking.
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tls import TlsData
from mitmproxy.tools.dump import DumpMaster

from lli.config import LLIConfig
from lli.filters import URLFilter
from lli.logger import (
    get_logger,
    log_request_summary,
    log_streaming_progress,
    log_tls_handshake_failure,
)

if TYPE_CHECKING:
    from lli.watch import WatchManager


class WatchAddon:
    """
    mitmproxy addon for watch mode.

    Writes records through WatchManager for session-aware logging
    with automatic session ID injection.
    """

    def __init__(
        self,
        config: LLIConfig,
        watch_manager: WatchManager,
        url_filter: URLFilter,
    ):
        """
        Initialize the watch addon.

        Args:
            config: LLI configuration
            watch_manager: WatchManager instance for session management
            url_filter: URL filter for traffic selection
        """
        self.config = config
        self.watch_manager = watch_manager
        self.url_filter = url_filter
        self.masking_config = config.masking
        self._logger = get_logger()

        # Track in-flight requests
        self._request_times: dict[int, float] = {}
        self._request_ids: dict[int, str] = {}
        self._request_sessions: dict[int, str | None] = {}

    def request(self, flow: http.HTTPFlow) -> None:
        """Handle an outgoing request."""
        url = flow.request.pretty_url
        method = flow.request.method

        self._logger.debug("Intercepted request: %s %s", method, url)

        # Determine if we should capture this request
        should_capture = self.url_filter.should_capture(url)

        # Log summary for all requests
        log_request_summary(method, url, captured=should_capture)

        # Generate unique request ID and track timing for all requests
        request_id = str(uuid4())
        flow_id = id(flow)
        self._request_ids[flow_id] = request_id
        self._request_times[flow_id] = time.time()

        if not should_capture:
            self._logger.debug("URL not matched, skipping: %s", url)
            return

        # Capture current session ID for this request
        session_id = self.watch_manager.current_session_id
        self._request_sessions[flow_id] = session_id

        # Parse headers (with masking)
        headers = self._mask_headers(dict(flow.request.headers))

        # Parse body
        body = self._parse_body(flow.request.content, flow.request.headers.get("content-type"))

        # Mask sensitive body fields if configured
        if body and isinstance(body, dict):
            body = self._mask_body_fields(body)

        # Create request record
        record = {
            "type": "request",
            "id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "url": url,
            "headers": headers,
            "body": body,
        }

        self.watch_manager.write_record(record, session_id=session_id)
        self._logger.debug("Captured request %s to %s", request_id[:8], url)

    def response(self, flow: http.HTTPFlow) -> None:
        """Handle a response."""
        url = flow.request.pretty_url
        method = flow.request.method
        status_code = flow.response.status_code

        # Determine if we should capture this response
        should_capture = self.url_filter.should_capture(url)

        flow_id = id(flow)
        request_id = self._request_ids.get(flow_id, str(uuid4()))
        start_time = self._request_times.get(flow_id, time.time())
        latency_ms = (time.time() - start_time) * 1000

        # Log summary for all responses
        log_request_summary(
            method,
            url,
            status_code,
            latency_ms,
            captured=should_capture,
        )

        if not should_capture:
            # Cleanup and exit early if not capturing
            self._cleanup_flow(flow_id)
            return

        # Use the session ID from the request start
        session_id = self._request_sessions.get(flow_id)

        # Check if this is a streaming response
        content_type = flow.response.headers.get("content-type", "")
        is_streaming = "text/event-stream" in content_type

        self._logger.debug(
            "Response received: %s %s (streaming=%s, content-type=%s)",
            status_code,
            url,
            is_streaming,
            content_type,
        )

        if is_streaming:
            # For streaming SSE responses, parse the complete body into chunks
            sse_events = self._parse_sse_body(flow.response.content)

            # Write individual chunk records for each SSE event
            for chunk_index, event_content in enumerate(sse_events):
                chunk_record = {
                    "type": "response_chunk",
                    "request_id": request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status_code": status_code,
                    "chunk_index": chunk_index,
                    "content": event_content,
                }
                self.watch_manager.write_record(chunk_record, session_id=session_id)
                log_streaming_progress(request_id, chunk_index)

            # Write meta record with chunk count
            meta_record = {
                "type": "response_meta",
                "request_id": request_id,
                "total_latency_ms": latency_ms,
                "status_code": status_code,
                "total_chunks": len(sse_events),
            }
            self.watch_manager.write_record(meta_record, session_id=session_id)
        else:
            # Non-streaming response - capture complete body
            headers = self._mask_headers(dict(flow.response.headers))
            body = self._parse_body(
                flow.response.content, flow.response.headers.get("content-type")
            )

            record = {
                "type": "response",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status_code": status_code,
                "headers": headers,
                "body": body,
                "latency_ms": latency_ms,
            }
            self.watch_manager.write_record(record, session_id=session_id)

        # Cleanup
        self._cleanup_flow(flow_id)

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        """Handle response headers (called before body is received)."""
        url = flow.request.pretty_url
        if not self.url_filter.should_capture(url):
            return

        content_type = flow.response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            self._logger.debug("Detected streaming response for %s", url)

    def tls_failed_server(self, data: TlsData) -> None:
        """Log TLS handshake failures with server context."""
        server = data.conn
        address = getattr(server, "address", None)
        host = getattr(server, "sni", None) or (address[0] if address else None)
        port = address[1] if address else None
        if host and port:
            target = f"https://{host}:{port}"
        elif host:
            target = host
        else:
            target = "unknown"
        log_tls_handshake_failure(target, getattr(server, "error", None))

    def _parse_sse_body(self, content: bytes | None) -> list[Any]:
        """Parse a complete SSE response body into individual events."""
        if not content:
            return []

        events = []
        try:
            text = content.decode("utf-8")
            raw_events = text.split("\n\n")

            for raw_event in raw_events:
                raw_event = raw_event.strip()
                if not raw_event:
                    continue

                for line in raw_event.split("\n"):
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data == "[DONE]":
                            events.append({"done": True})
                        else:
                            try:
                                events.append(json.loads(data))
                            except json.JSONDecodeError:
                                events.append({"raw": data})
                    elif line.startswith("event:"):
                        event_type = line[6:].strip()
                        if events and isinstance(events[-1], dict):
                            events[-1]["_event_type"] = event_type

            return events

        except Exception as e:
            self._logger.debug("Failed to parse SSE body: %s", e)
            return [{"error": str(e), "raw": content[:500].hex() if content else ""}]

    def _parse_body(self, content: bytes | None, content_type: str | None) -> Any:
        """Parse request/response body based on content type."""
        if not content:
            return None

        try:
            if content_type and "json" in content_type:
                return json.loads(content.decode("utf-8"))

            try:
                text = content.decode("utf-8")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
            except UnicodeDecodeError:
                return f"<binary content: {len(content)} bytes>"

        except Exception as e:
            self._logger.debug("Failed to parse body: %s", e)
            return f"<parse error: {e}>"

    def _mask_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Mask sensitive headers."""
        if not self.masking_config.mask_auth_headers:
            return headers

        masked = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower in self.masking_config.sensitive_headers:
                masked[key] = self._mask_api_key(value)
            else:
                masked[key] = value

        return masked

    def _mask_api_key(self, value: str) -> str:
        """Mask an API key value."""
        patterns = [
            (r"(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]+", r"\1***"),
            (r"(Bearer\s+)[a-zA-Z0-9_-]+", r"\1***MASKED***"),
            (r"([a-zA-Z0-9]{8})[a-zA-Z0-9]{24,}", r"\1***"),
        ]

        masked = value
        for pattern, replacement in patterns:
            masked = re.sub(pattern, replacement, masked)

        if masked == value and len(value) > 16:
            return value[:8] + self.masking_config.mask_pattern

        return masked

    def _mask_body_fields(self, body: dict[str, Any]) -> dict[str, Any]:
        """Mask sensitive fields in the request/response body."""
        if not self.masking_config.sensitive_body_fields:
            return body

        masked = body.copy()
        for field_path in self.masking_config.sensitive_body_fields:
            parts = field_path.split(".")
            self._mask_nested_field(masked, parts)

        return masked

    def _mask_nested_field(self, obj: dict[str, Any], path: list[str]) -> None:
        """Recursively mask a nested field."""
        if not path:
            return

        key = path[0]
        if key not in obj:
            return

        if len(path) == 1:
            obj[key] = self.masking_config.mask_pattern
        elif isinstance(obj[key], dict):
            self._mask_nested_field(obj[key], path[1:])

    def _cleanup_flow(self, flow_id: int) -> None:
        """Clean up tracking data for a completed flow."""
        self._request_times.pop(flow_id, None)
        self._request_ids.pop(flow_id, None)
        self._request_sessions.pop(flow_id, None)


async def run_watch_proxy(
    config: LLIConfig,
    watch_manager: WatchManager,
) -> None:
    """
    Start the mitmproxy server in watch mode.

    Args:
        config: LLI configuration
        watch_manager: WatchManager instance for session management
    """
    logger = get_logger()
    logger.info("Starting watch proxy on %s:%d", config.proxy.host, config.proxy.port)

    mitmproxy_logger = logging.getLogger("mitmproxy")
    mitmproxy_logger.setLevel(logging.WARNING)
    mitmproxy_logger.propagate = False

    mitmproxy_console_logger = logging.getLogger("mitmproxy.console")
    mitmproxy_console_logger.setLevel(logging.WARNING)
    mitmproxy_console_logger.propagate = False

    url_filter = URLFilter(config.filter)

    # Create watch addon
    addon = WatchAddon(config, watch_manager, url_filter)

    # Configure mitmproxy options
    opts = Options(
        listen_host=config.proxy.host,
        listen_port=config.proxy.port,
        ssl_insecure=config.proxy.ssl_insecure,
    )
    if config.proxy.no_proxy:
        opts.update(ignore_hosts=config.proxy.no_proxy)

    # Create and run DumpMaster
    # Suppress mitmproxy's default console output by redirecting stdout temporarily
    null_stream = StringIO()

    # Redirect stdout during DumpMaster creation to suppress console output
    with redirect_stdout(null_stream):
        master = DumpMaster(opts)
        master.addons.add(addon)

    # Try to remove eventlog addon if it exists
    try:
        from mitmproxy.addons import eventstore

        for addon_name in list(master.addons.keys()):
            addon_instance = master.addons[addon_name]
            if isinstance(addon_instance, eventstore.EventStore):
                master.addons.remove(addon_name)
    except Exception:
        pass

    logger.info("Watch proxy initialized, monitoring traffic...")

    try:
        await master.run()
    except Exception as e:
        logger.error("Watch proxy error: %s", e)
        raise

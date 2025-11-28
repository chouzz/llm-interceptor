"""
mitmproxy addon for Claude-Code-Inspector.

Handles traffic interception, data capture, and sensitive data masking.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from cci.config import CCIConfig
from cci.filters import URLFilter
from cci.logger import get_logger, log_request_summary, log_streaming_progress
from cci.models import (
    NonStreamingResponseRecord,
    RequestRecord,
    ResponseChunkRecord,
    ResponseMetaRecord,
)
from cci.storage import JSONLWriter


class CCIAddon:
    """
    mitmproxy addon for capturing LLM API traffic.

    Handles:
    - Request/response interception
    - Streaming response handling (SSE)
    - Sensitive data masking
    - JSONL output
    """

    def __init__(
        self,
        config: CCIConfig,
        writer: JSONLWriter,
        url_filter: URLFilter,
    ):
        """
        Initialize the CCI addon.

        Args:
            config: CCI configuration
            writer: JSONL writer for output
            url_filter: URL filter for traffic selection
        """
        self.config = config
        self.writer = writer
        self.url_filter = url_filter
        self.masking_config = config.masking
        self._logger = get_logger()

        # Track in-flight requests
        self._request_times: dict[int, float] = {}
        self._request_ids: dict[int, str] = {}

    def request(self, flow: http.HTTPFlow) -> None:
        """
        Handle an outgoing request.

        Called when a client request is received by the proxy.
        """
        url = flow.request.pretty_url

        # Log all requests in debug mode
        self._logger.debug("Intercepted request: %s %s", flow.request.method, url)

        if not self.url_filter.should_capture(url):
            self._logger.debug("URL not matched, skipping: %s", url)
            return

        self._logger.info("Capturing request: %s %s", flow.request.method, url)

        # Generate unique request ID
        request_id = str(uuid4())
        flow_id = id(flow)
        self._request_ids[flow_id] = request_id
        self._request_times[flow_id] = time.time()

        # Parse headers (with masking)
        headers = self._mask_headers(dict(flow.request.headers))

        # Parse body
        body = self._parse_body(flow.request.content, flow.request.headers.get("content-type"))

        # Mask sensitive body fields if configured
        if body and isinstance(body, dict):
            body = self._mask_body_fields(body)

        # Create request record
        record = RequestRecord(
            id=request_id,
            timestamp=datetime.now(timezone.utc),
            method=flow.request.method,
            url=url,
            headers=headers,
            body=body,
        )

        self.writer.write_record(record)
        log_request_summary(flow.request.method, url)
        self._logger.debug("Captured request %s to %s", request_id[:8], url)

    def response(self, flow: http.HTTPFlow) -> None:
        """
        Handle a response.

        Called when a server response is received.
        For non-streaming responses, captures the complete body.
        """
        url = flow.request.pretty_url
        if not self.url_filter.should_capture(url):
            return

        flow_id = id(flow)
        request_id = self._request_ids.get(flow_id, str(uuid4()))
        start_time = self._request_times.get(flow_id, time.time())
        latency_ms = (time.time() - start_time) * 1000

        # Check if this is a streaming response
        content_type = flow.response.headers.get("content-type", "")
        is_streaming = "text/event-stream" in content_type

        self._logger.debug(
            "Response received: %s %s (streaming=%s, content-type=%s)",
            flow.response.status_code, url, is_streaming, content_type
        )

        if is_streaming:
            # For streaming SSE responses, parse the complete body into chunks
            sse_events = self._parse_sse_body(flow.response.content)

            # Write individual chunk records for each SSE event
            for chunk_index, event_content in enumerate(sse_events):
                chunk_record = ResponseChunkRecord(
                    request_id=request_id,
                    timestamp=datetime.now(timezone.utc),
                    status_code=flow.response.status_code,
                    chunk_index=chunk_index,
                    content=event_content,
                )
                self.writer.write_record(chunk_record)
                log_streaming_progress(request_id, chunk_index)

            # Write meta record with chunk count
            meta_record = ResponseMetaRecord(
                request_id=request_id,
                total_latency_ms=latency_ms,
                status_code=flow.response.status_code,
                total_chunks=len(sse_events),
            )
            self.writer.write_record(meta_record)
            self._logger.info(
                "Streaming response complete: %d events in %.0fms",
                len(sse_events), latency_ms
            )
        else:
            # Non-streaming response - capture complete body
            headers = self._mask_headers(dict(flow.response.headers))
            body = self._parse_body(
                flow.response.content, flow.response.headers.get("content-type")
            )

            record = NonStreamingResponseRecord(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc),
                status_code=flow.response.status_code,
                headers=headers,
                body=body,
                latency_ms=latency_ms,
            )
            self.writer.write_record(record)
            self._logger.info(
                "Response captured: %s %s -> %d (%.0fms)",
                flow.request.method, url, flow.response.status_code, latency_ms
            )

        log_request_summary(
            flow.request.method,
            url,
            flow.response.status_code,
            latency_ms,
        )

        # Cleanup
        self._cleanup_flow(flow_id)

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        """
        Handle response headers (called before body is received).

        Used to detect streaming responses and log info.
        """
        url = flow.request.pretty_url
        if not self.url_filter.should_capture(url):
            return

        content_type = flow.response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            self._logger.debug("Detected streaming response for %s", url)
            # Don't set stream=True, let mitmproxy buffer the complete response
            # This ensures we get the full SSE content in the response hook

    def _parse_sse_body(self, content: bytes | None) -> list[Any]:
        """
        Parse a complete SSE response body into individual events.

        SSE format: each event is "data: {...}\n\n"
        """
        if not content:
            return []

        events = []
        try:
            text = content.decode("utf-8")

            # Split by double newline to get individual events
            raw_events = text.split("\n\n")

            for raw_event in raw_events:
                raw_event = raw_event.strip()
                if not raw_event:
                    continue

                # Parse each line of the event
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
                        # Handle event type if present
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
            # Try JSON first
            if content_type and "json" in content_type:
                return json.loads(content.decode("utf-8"))

            # Try to decode as text
            try:
                text = content.decode("utf-8")
                # Try parsing as JSON anyway
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
            except UnicodeDecodeError:
                # Binary content - return base64 or indication
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
                # Mask API keys while preserving format hint
                masked[key] = self._mask_api_key(value)
            else:
                masked[key] = value

        return masked

    def _mask_api_key(self, value: str) -> str:
        """Mask an API key value."""
        # Common patterns: sk-xxx, Bearer sk-xxx, etc.
        patterns = [
            (r"(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]+", r"\1***"),
            (r"(Bearer\s+)[a-zA-Z0-9_-]+", r"\1***MASKED***"),
            (r"([a-zA-Z0-9]{8})[a-zA-Z0-9]{24,}", r"\1***"),
        ]

        masked = value
        for pattern, replacement in patterns:
            masked = re.sub(pattern, replacement, masked)

        # If no pattern matched and it looks like a key, mask most of it
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


async def run_proxy(
    config: CCIConfig,
    output_path: str,
) -> None:
    """
    Start the mitmproxy server with CCI addon.

    Args:
        config: CCI configuration
        output_path: Path for JSONL output
    """
    logger = get_logger()
    logger.info("Starting proxy on %s:%d", config.proxy.host, config.proxy.port)
    logger.info("Output file: %s", output_path)
    logger.info("URL patterns: %s", config.filter.include_patterns)

    # Create writer and filter
    writer = JSONLWriter(output_path)
    writer.open()

    url_filter = URLFilter(config.filter)

    # Create addon
    addon = CCIAddon(config, writer, url_filter)

    # Configure mitmproxy options
    opts = Options(
        listen_host=config.proxy.host,
        listen_port=config.proxy.port,
        ssl_insecure=config.proxy.ssl_insecure,
    )

    # Create and run DumpMaster
    master = DumpMaster(opts)
    master.addons.add(addon)

    logger.info("Proxy initialized, starting to capture traffic...")

    try:
        await master.run()
    except Exception as e:
        logger.error("Proxy error: %s", e)
        raise
    finally:
        writer.close()
        logger.info("Proxy stopped, output saved to %s", output_path)

"""
Stream merger utility for LLM Interceptor.

Aggregates streaming response chunks into complete request-response pairs.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from cci.logger import get_logger
from cci.models import ToolCall
from cci.storage import JSONLWriter, read_jsonl


class StreamMerger:
    """
    Merges streaming response chunks into complete records.

    Reads a JSONL file with interleaved request/response_chunk/response_meta
    records and produces a new file with separate request and response lines.
    """

    def __init__(self, input_path: str | Path, output_path: str | Path):
        """
        Initialize the stream merger.

        Args:
            input_path: Path to input JSONL file with raw chunks
            output_path: Path to output JSONL file for merged records
        """
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self._logger = get_logger()

    def merge(self) -> dict[str, int]:
        """
        Perform the merge operation.

        Output format is alternating request/response lines:
        - Line 1: request JSON
        - Line 2: response JSON (merged from chunks if streaming)
        - Line 3: next request JSON
        - Line 4: next response JSON
        - etc.

        Returns:
            Statistics about the merge operation
        """
        self._logger.info("Reading records from %s", self.input_path)
        records = read_jsonl(self.input_path)

        # Group records by request_id
        requests: dict[str, dict[str, Any]] = {}
        chunks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        metas: dict[str, dict[str, Any]] = {}
        non_streaming: dict[str, dict[str, Any]] = {}

        # Track order of requests
        request_order: list[str] = []

        for record in records:
            record_type = record.get("type", "")

            if record_type == "request":
                request_id = record["id"]
                requests[request_id] = record
                request_order.append(request_id)
            elif record_type == "response_chunk":
                request_id = record.get("request_id")
                if request_id:
                    chunks[request_id].append(record)
            elif record_type == "response_meta":
                request_id = record.get("request_id")
                if request_id:
                    metas[request_id] = record
            elif record_type == "response":
                # Non-streaming response
                request_id = record.get("request_id")
                if request_id:
                    non_streaming[request_id] = record

        self._logger.info(
            "Found %d requests, %d chunks, %d non-streaming responses",
            len(requests),
            sum(len(c) for c in chunks.values()),
            len(non_streaming),
        )

        # Process and write records
        stats = {
            "total_requests": len(requests),
            "streaming_requests": 0,
            "non_streaming_requests": 0,
            "incomplete_requests": 0,
            "total_chunks_processed": 0,
        }

        with JSONLWriter(self.output_path, append=False) as writer:
            for request_id in request_order:
                if request_id not in requests:
                    continue

                request = requests[request_id]

                # Check if this was a streaming or non-streaming request
                if request_id in chunks:
                    # Streaming request - write request then merged response
                    writer.write_record(request)

                    request_chunks = sorted(
                        chunks[request_id], key=lambda x: x.get("chunk_index", 0)
                    )
                    meta = metas.get(request_id, {})

                    # Detect API format and rebuild response
                    api_format = self._detect_api_format(request_chunks)
                    if api_format == "anthropic":
                        response = self._rebuild_anthropic_response(
                            request_id, request_chunks, meta
                        )
                    else:
                        response = self._rebuild_openai_response(request_id, request_chunks, meta)

                    writer.write_record(response)
                    stats["streaming_requests"] += 1
                    stats["total_chunks_processed"] += len(request_chunks)

                elif request_id in non_streaming:
                    # Non-streaming request - write request then response as-is
                    writer.write_record(request)
                    writer.write_record(non_streaming[request_id])
                    stats["non_streaming_requests"] += 1

                else:
                    # Request without response - only write request
                    writer.write_record(request)
                    self._logger.warning("Request %s... has no response", request_id[:8])
                    stats["incomplete_requests"] += 1

        self._logger.info(
            "Wrote %d request-response pairs to %s",
            stats["streaming_requests"] + stats["non_streaming_requests"],
            self.output_path,
        )

        return stats

    def _detect_api_format(self, chunks: list[dict[str, Any]]) -> str:
        """
        Detect whether chunks are from Anthropic or OpenAI API.

        Args:
            chunks: List of response chunk records

        Returns:
            "anthropic" or "openai"
        """
        for chunk in chunks:
            content = chunk.get("content", {})
            if not isinstance(content, dict):
                continue

            # Anthropic format indicators
            content_type = content.get("type", "")
            if content_type in (
                "message_start",
                "content_block_start",
                "content_block_delta",
                "content_block_stop",
                "message_delta",
                "message_stop",
                "ping",
            ):
                return "anthropic"

            # OpenAI format indicators
            if "choices" in content:
                return "openai"

        # Default to anthropic
        return "anthropic"

    def _rebuild_anthropic_response(
        self,
        request_id: str,
        chunks: list[dict[str, Any]],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Rebuild a complete Anthropic API response from streaming chunks.

        Args:
            request_id: The request ID
            chunks: List of response chunk records (sorted by chunk_index)
            meta: Response meta record

        Returns:
            Complete response record with rebuilt Anthropic response body
        """
        # Initialize response body structure
        body: dict[str, Any] = {
            "type": "message",
            "role": "assistant",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {},
        }

        # Track content blocks by index
        content_blocks: dict[int, dict[str, Any]] = {}
        content_block_deltas: dict[int, list[str]] = defaultdict(list)

        # Track status code and timestamp from first chunk
        status_code = meta.get("status_code", 200)
        timestamp = None
        headers: dict[str, str] = {}

        for chunk in chunks:
            content = chunk.get("content", {})
            if not isinstance(content, dict):
                continue

            # Get timestamp from first chunk
            if timestamp is None:
                timestamp = chunk.get("timestamp")
                status_code = chunk.get("status_code", status_code)
                headers = chunk.get("headers", {})

            content_type = content.get("type", "")

            if content_type == "message_start":
                # Extract message metadata
                message = content.get("message", {})
                body["id"] = message.get("id", "")
                body["model"] = message.get("model", "")
                body["role"] = message.get("role", "assistant")
                body["usage"] = message.get("usage", {})

            elif content_type == "content_block_start":
                # Start a new content block
                index = content.get("index", 0)
                block = content.get("content_block", {})
                block_type = block.get("type", "text")

                if block_type == "text":
                    content_blocks[index] = {
                        "type": "text",
                        "text": block.get("text", ""),
                    }
                elif block_type == "tool_use":
                    content_blocks[index] = {
                        "type": "tool_use",
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "input": {},
                    }
                elif block_type == "thinking":
                    content_blocks[index] = {
                        "type": "thinking",
                        "thinking": block.get("thinking", ""),
                    }
                else:
                    # Generic block
                    content_blocks[index] = dict(block)

            elif content_type == "content_block_delta":
                # Accumulate delta content
                index = content.get("index", 0)
                delta = content.get("delta", {})
                delta_type = delta.get("type", "")

                if delta_type == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        content_block_deltas[index].append(text)
                elif delta_type == "input_json_delta":
                    partial_json = delta.get("partial_json", "")
                    if partial_json:
                        content_block_deltas[index].append(partial_json)
                elif delta_type == "thinking_delta":
                    thinking = delta.get("thinking", "")
                    if thinking:
                        content_block_deltas[index].append(thinking)

            elif content_type == "message_delta":
                # Extract final message metadata
                delta = content.get("delta", {})
                if "stop_reason" in delta:
                    body["stop_reason"] = delta["stop_reason"]
                if "stop_sequence" in delta:
                    body["stop_sequence"] = delta["stop_sequence"]
                # Update usage with final values
                if "usage" in content:
                    body["usage"].update(content["usage"])

        # Merge deltas into content blocks
        for index, block in sorted(content_blocks.items()):
            delta_parts = content_block_deltas.get(index, [])
            merged_delta = "".join(delta_parts)

            if block.get("type") == "text":
                block["text"] = block.get("text", "") + merged_delta
            elif block.get("type") == "tool_use":
                # Parse accumulated JSON for tool input
                if merged_delta:
                    try:
                        block["input"] = json.loads(merged_delta)
                    except json.JSONDecodeError:
                        block["input"] = merged_delta
            elif block.get("type") == "thinking":
                block["thinking"] = block.get("thinking", "") + merged_delta

        # Build content array in order
        body["content"] = [block for _, block in sorted(content_blocks.items())]

        # Build response record
        response: dict[str, Any] = {
            "type": "response",
            "request_id": request_id,
            "status_code": status_code,
            "body": body,
            "latency_ms": meta.get("total_latency_ms", 0),
        }

        if timestamp:
            response["timestamp"] = timestamp
        if headers:
            response["headers"] = headers

        return response

    def _rebuild_openai_response(
        self,
        request_id: str,
        chunks: list[dict[str, Any]],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Rebuild a complete OpenAI API response from streaming chunks.

        Args:
            request_id: The request ID
            chunks: List of response chunk records (sorted by chunk_index)
            meta: Response meta record

        Returns:
            Complete response record with rebuilt OpenAI response body
        """
        # Initialize response body structure
        body: dict[str, Any] = {
            "object": "chat.completion",
            "choices": [],
            "usage": {},
        }

        # Track choices by index
        choices_content: dict[int, list[str]] = defaultdict(list)
        choices_tool_calls: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
        choices_tool_args: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
        choices_finish_reason: dict[int, str | None] = {}
        choices_role: dict[int, str] = {}

        # Track status code and timestamp
        status_code = meta.get("status_code", 200)
        timestamp = None
        headers: dict[str, str] = {}

        for chunk in chunks:
            content = chunk.get("content", {})
            if not isinstance(content, dict):
                continue

            # Get metadata from first chunk
            if timestamp is None:
                timestamp = chunk.get("timestamp")
                status_code = chunk.get("status_code", status_code)
                headers = chunk.get("headers", {})

            # Extract top-level metadata
            if "id" not in body and "id" in content:
                body["id"] = content["id"]
            if "model" not in body and "model" in content:
                body["model"] = content["model"]
            if "created" not in body and "created" in content:
                body["created"] = content["created"]
            if "system_fingerprint" in content:
                body["system_fingerprint"] = content["system_fingerprint"]

            # Process choices
            for choice in content.get("choices", []):
                index = choice.get("index", 0)
                delta = choice.get("delta", {})

                # Accumulate role
                if "role" in delta:
                    choices_role[index] = delta["role"]

                # Accumulate content
                if "content" in delta and delta["content"]:
                    choices_content[index].append(delta["content"])

                # Accumulate tool calls
                if "tool_calls" in delta:
                    for tc in delta["tool_calls"]:
                        tc_index = tc.get("index", 0)
                        if "id" in tc:
                            choices_tool_calls[index][tc_index] = {
                                "id": tc["id"],
                                "type": tc.get("type", "function"),
                                "function": {
                                    "name": tc.get("function", {}).get("name", ""),
                                    "arguments": "",
                                },
                            }
                        if "function" in tc and "arguments" in tc["function"]:
                            choices_tool_args[index][tc_index].append(tc["function"]["arguments"])

                # Track finish reason
                if "finish_reason" in choice and choice["finish_reason"]:
                    choices_finish_reason[index] = choice["finish_reason"]

            # Extract usage from final chunk
            if "usage" in content and content["usage"]:
                body["usage"] = content["usage"]

        # Build choices array
        all_indices = set(choices_content.keys()) | set(choices_tool_calls.keys())
        if not all_indices:
            all_indices = {0}

        for index in sorted(all_indices):
            message: dict[str, Any] = {
                "role": choices_role.get(index, "assistant"),
            }

            # Merge content
            content_parts = choices_content.get(index, [])
            if content_parts:
                message["content"] = "".join(content_parts)
            else:
                message["content"] = None

            # Merge tool calls
            tool_calls_data = choices_tool_calls.get(index, {})
            if tool_calls_data:
                tool_calls_list = []
                for tc_index, tc_data in sorted(tool_calls_data.items()):
                    # Merge arguments
                    args_parts = choices_tool_args.get(index, {}).get(tc_index, [])
                    tc_data["function"]["arguments"] = "".join(args_parts)
                    tool_calls_list.append(tc_data)
                message["tool_calls"] = tool_calls_list

            choice_record: dict[str, Any] = {
                "index": index,
                "message": message,
                "finish_reason": choices_finish_reason.get(index),
            }

            body["choices"].append(choice_record)

        # Build response record
        response: dict[str, Any] = {
            "type": "response",
            "request_id": request_id,
            "status_code": status_code,
            "body": body,
            "latency_ms": meta.get("total_latency_ms", 0),
        }

        if timestamp:
            response["timestamp"] = timestamp
        if headers:
            response["headers"] = headers

        return response

    def _extract_text_from_chunks(self, chunks: list[dict[str, Any]]) -> str:
        """Extract the complete response text from streaming chunks."""
        text_parts: list[str] = []

        for chunk in chunks:
            content = chunk.get("content", {})
            if isinstance(content, dict):
                # Handle different API formats

                # Anthropic format
                if "delta" in content:
                    delta = content["delta"]
                    if isinstance(delta, dict) and "text" in delta:
                        text_parts.append(delta["text"])

                # OpenAI format
                if "choices" in content:
                    for choice in content.get("choices", []):
                        delta = choice.get("delta", {})
                        if "content" in delta:
                            text_parts.append(delta["content"])

                # Raw text in content
                if "text" in content:
                    text_parts.append(content["text"])

                # Message content
                if "content_block" in content:
                    block = content["content_block"]
                    if isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])

            elif isinstance(content, str):
                text_parts.append(content)

        return "".join(text_parts)

    def _extract_tool_calls_from_chunks(self, chunks: list[dict[str, Any]]) -> list[ToolCall]:
        """Extract tool calls from streaming chunks.

        Tool calls in Anthropic streaming format come in three stages:
        1. content_block_start with type=tool_use: contains id, name, and empty input
        2. content_block_delta with input_json_delta: contains partial JSON fragments
        3. content_block_stop: marks the end of the tool call

        We need to aggregate all input_json_delta fragments by content block index.
        """
        # Track tool calls by their content block index
        tool_call_data: dict[int, dict[str, Any]] = {}
        tool_input_parts: dict[int, list[str]] = defaultdict(list)

        for chunk in chunks:
            content = chunk.get("content", {})
            if not isinstance(content, dict):
                continue

            content_type = content.get("type", "")
            index = content.get("index")

            # Start of a tool_use content block
            if content_type == "content_block_start":
                block = content.get("content_block", {})
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_call_data[index] = {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                    }

            # Delta containing input JSON fragments
            elif content_type == "content_block_delta":
                delta = content.get("delta", {})
                if isinstance(delta, dict) and delta.get("type") == "input_json_delta":
                    partial_json = delta.get("partial_json", "")
                    if partial_json and index is not None:
                        tool_input_parts[index].append(partial_json)

        # Build the final tool calls list
        tool_calls: list[ToolCall] = []
        for index, data in sorted(tool_call_data.items()):
            # Concatenate all JSON fragments for this tool call
            full_json_str = "".join(tool_input_parts.get(index, []))

            # Try to parse the JSON input
            tool_input = None
            if full_json_str:
                try:
                    tool_input = json.loads(full_json_str)
                except json.JSONDecodeError:
                    # If parsing fails, keep the raw string
                    tool_input = full_json_str

            tool_calls.append(
                ToolCall(
                    id=data["id"],
                    name=data["name"],
                    input=tool_input,
                )
            )

        return tool_calls

    def _extract_text_from_body(self, body: dict[str, Any]) -> str:
        """Extract text from a non-streaming response body."""
        # Anthropic format
        if "content" in body:
            content = body["content"]
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                return "".join(texts)
            elif isinstance(content, str):
                return content

        # OpenAI format
        if "choices" in body:
            texts = []
            for choice in body.get("choices", []):
                message = choice.get("message", {})
                if "content" in message:
                    texts.append(message["content"])
            return "".join(texts)

        # Fallback: JSON dump
        return json.dumps(body)

    def _extract_tool_calls_from_body(self, body: dict[str, Any]) -> list[ToolCall]:
        """Extract tool calls from a non-streaming response body.

        In Anthropic's non-streaming format, tool calls appear as content blocks
        with type="tool_use" in the content array.
        """
        tool_calls: list[ToolCall] = []

        # Anthropic format
        if "content" in body:
            content = body["content"]
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        tool_calls.append(
                            ToolCall(
                                id=item.get("id", ""),
                                name=item.get("name", ""),
                                input=item.get("input"),
                            )
                        )

        # OpenAI format
        if "choices" in body:
            for choice in body.get("choices", []):
                message = choice.get("message", {})
                if "tool_calls" in message:
                    for tc in message.get("tool_calls", []):
                        tool_calls.append(
                            ToolCall(
                                id=tc.get("id", ""),
                                name=tc.get("function", {}).get("name", ""),
                                input=tc.get("function", {}).get("arguments"),
                            )
                        )

        return tool_calls

    def _parse_timestamp(self, ts: Any) -> datetime:
        """Parse a timestamp from various formats."""
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            # Handle ISO format with Z suffix
            ts = ts.rstrip("Z")
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                pass
        return datetime.utcnow()


def merge_streams(input_path: str | Path, output_path: str | Path) -> dict[str, int]:
    """
    Convenience function to merge streaming chunks.

    Args:
        input_path: Path to input JSONL file
        output_path: Path to output JSONL file

    Returns:
        Statistics about the merge operation
    """
    merger = StreamMerger(input_path, output_path)
    return merger.merge()

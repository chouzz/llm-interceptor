"""Tests for stream merger functionality."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from cci.merger import StreamMerger
from cci.models import ToolCall


class TestExtractTextFromChunks:
    """Test text extraction from streaming chunks."""

    def test_anthropic_delta_format(self, tmp_path: Path) -> None:
        """Test extracting text from Anthropic delta format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"delta": {"text": "Hello"}}},
            {"content": {"delta": {"text": " "}}},
            {"content": {"delta": {"text": "World"}}},
        ]

        result = merger._extract_text_from_chunks(chunks)
        assert result == "Hello World"

    def test_anthropic_content_block_format(self, tmp_path: Path) -> None:
        """Test extracting text from Anthropic content_block format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"content_block": {"text": "Hello "}}},
            {"content": {"content_block": {"text": "from Anthropic"}}},
        ]

        result = merger._extract_text_from_chunks(chunks)
        assert result == "Hello from Anthropic"

    def test_openai_choices_delta_format(self, tmp_path: Path) -> None:
        """Test extracting text from OpenAI choices.delta format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"choices": [{"delta": {"content": "Hello"}}]}},
            {"content": {"choices": [{"delta": {"content": " "}}]}},
            {"content": {"choices": [{"delta": {"content": "World"}}]}},
        ]

        result = merger._extract_text_from_chunks(chunks)
        assert result == "Hello World"

    def test_openai_multiple_choices(self, tmp_path: Path) -> None:
        """Test extracting text from OpenAI with multiple choices."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "content": {
                    "choices": [
                        {"delta": {"content": "Choice1"}},
                        {"delta": {"content": "Choice2"}},
                    ]
                }
            },
        ]

        result = merger._extract_text_from_chunks(chunks)
        assert result == "Choice1Choice2"

    def test_raw_text_in_content(self, tmp_path: Path) -> None:
        """Test extracting raw text from content."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"text": "Raw text"}},
        ]

        result = merger._extract_text_from_chunks(chunks)
        assert result == "Raw text"

    def test_string_content(self, tmp_path: Path) -> None:
        """Test extracting text when content is a string."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": "Plain string content"},
        ]

        result = merger._extract_text_from_chunks(chunks)
        assert result == "Plain string content"

    def test_empty_chunks(self, tmp_path: Path) -> None:
        """Test handling empty chunks list."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        result = merger._extract_text_from_chunks([])
        assert result == ""

    def test_mixed_formats(self, tmp_path: Path) -> None:
        """Test handling mixed format chunks."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"delta": {"text": "Anthropic"}}},
            {"content": {"choices": [{"delta": {"content": "OpenAI"}}]}},
            {"content": {"text": "Raw"}},
        ]

        result = merger._extract_text_from_chunks(chunks)
        assert "Anthropic" in result
        assert "OpenAI" in result
        assert "Raw" in result


class TestExtractToolCallsFromChunks:
    """Test tool call extraction from streaming chunks."""

    def test_anthropic_tool_use_streaming(self, tmp_path: Path) -> None:
        """Test extracting tool calls from Anthropic streaming format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            # Start of tool_use block
            {
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool_123",
                        "name": "read_file",
                    },
                }
            },
            # Input JSON deltas
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"path"'},
                }
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": ': "/test.txt"}'},
                }
            },
        ]

        result = merger._extract_tool_calls_from_chunks(chunks)

        assert len(result) == 1
        assert result[0].id == "tool_123"
        assert result[0].name == "read_file"
        assert result[0].input == {"path": "/test.txt"}

    def test_anthropic_multiple_tool_calls(self, tmp_path: Path) -> None:
        """Test extracting multiple tool calls from Anthropic streaming format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            # First tool
            {
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "read_file",
                    },
                }
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"path": "a.txt"}'},
                }
            },
            # Second tool
            {
                "content": {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool_2",
                        "name": "write_file",
                    },
                }
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"path": "b.txt", "content": "hello"}',
                    },
                }
            },
        ]

        result = merger._extract_tool_calls_from_chunks(chunks)

        assert len(result) == 2
        assert result[0].id == "tool_1"
        assert result[0].name == "read_file"
        assert result[0].input == {"path": "a.txt"}
        assert result[1].id == "tool_2"
        assert result[1].name == "write_file"
        assert result[1].input == {"path": "b.txt", "content": "hello"}

    def test_anthropic_invalid_json_input(self, tmp_path: Path) -> None:
        """Test handling invalid JSON in tool input."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool_123",
                        "name": "test_tool",
                    },
                }
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": "invalid json"},
                }
            },
        ]

        result = merger._extract_tool_calls_from_chunks(chunks)

        assert len(result) == 1
        assert result[0].id == "tool_123"
        assert result[0].name == "test_tool"
        # Invalid JSON is stored as raw string
        assert result[0].input == "invalid json"

    def test_empty_tool_input(self, tmp_path: Path) -> None:
        """Test tool call with empty input."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool_123",
                        "name": "no_args_tool",
                    },
                }
            },
        ]

        result = merger._extract_tool_calls_from_chunks(chunks)

        assert len(result) == 1
        assert result[0].id == "tool_123"
        assert result[0].name == "no_args_tool"
        assert result[0].input is None

    def test_no_tool_calls(self, tmp_path: Path) -> None:
        """Test chunks without tool calls."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"delta": {"text": "Hello"}}},
            {"content": {"delta": {"text": " World"}}},
        ]

        result = merger._extract_tool_calls_from_chunks(chunks)
        assert result == []


class TestExtractTextFromBody:
    """Test text extraction from non-streaming response bodies."""

    def test_anthropic_content_list_format(self, tmp_path: Path) -> None:
        """Test extracting text from Anthropic content list format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "World"},
            ]
        }

        result = merger._extract_text_from_body(body)
        assert result == "Hello World"

    def test_anthropic_content_string_format(self, tmp_path: Path) -> None:
        """Test extracting text when content is a string."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {"content": "Direct string content"}

        result = merger._extract_text_from_body(body)
        assert result == "Direct string content"

    def test_openai_choices_message_format(self, tmp_path: Path) -> None:
        """Test extracting text from OpenAI choices format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {
            "choices": [
                {"message": {"content": "Hello from OpenAI"}},
            ]
        }

        result = merger._extract_text_from_body(body)
        assert result == "Hello from OpenAI"

    def test_openai_multiple_choices(self, tmp_path: Path) -> None:
        """Test extracting text from OpenAI with multiple choices."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {
            "choices": [
                {"message": {"content": "First choice"}},
                {"message": {"content": "Second choice"}},
            ]
        }

        result = merger._extract_text_from_body(body)
        assert result == "First choiceSecond choice"

    def test_fallback_to_json_dump(self, tmp_path: Path) -> None:
        """Test fallback to JSON dump for unknown formats."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {"unknown_field": "value"}

        result = merger._extract_text_from_body(body)
        assert "unknown_field" in result
        assert "value" in result


class TestExtractToolCallsFromBody:
    """Test tool call extraction from non-streaming response bodies."""

    def test_anthropic_tool_use_format(self, tmp_path: Path) -> None:
        """Test extracting tool calls from Anthropic content format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {
            "content": [
                {"type": "text", "text": "I'll read the file."},
                {
                    "type": "tool_use",
                    "id": "tool_abc",
                    "name": "read_file",
                    "input": {"path": "/test.txt"},
                },
            ]
        }

        result = merger._extract_tool_calls_from_body(body)

        assert len(result) == 1
        assert result[0].id == "tool_abc"
        assert result[0].name == "read_file"
        assert result[0].input == {"path": "/test.txt"}

    def test_anthropic_multiple_tool_calls(self, tmp_path: Path) -> None:
        """Test extracting multiple tool calls from Anthropic format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "read_file",
                    "input": {"path": "a.txt"},
                },
                {
                    "type": "tool_use",
                    "id": "tool_2",
                    "name": "write_file",
                    "input": {"path": "b.txt", "content": "data"},
                },
            ]
        }

        result = merger._extract_tool_calls_from_body(body)

        assert len(result) == 2
        assert result[0].name == "read_file"
        assert result[1].name == "write_file"

    def test_openai_tool_calls_format(self, tmp_path: Path) -> None:
        """Test extracting tool calls from OpenAI format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_xyz",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "Tokyo"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

        result = merger._extract_tool_calls_from_body(body)

        assert len(result) == 1
        assert result[0].id == "call_xyz"
        assert result[0].name == "get_weather"
        assert result[0].input == '{"location": "Tokyo"}'

    def test_openai_multiple_tool_calls(self, tmp_path: Path) -> None:
        """Test extracting multiple tool calls from OpenAI format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "func1", "arguments": "{}"},
                            },
                            {
                                "id": "call_2",
                                "function": {"name": "func2", "arguments": "{}"},
                            },
                        ],
                    }
                }
            ]
        }

        result = merger._extract_tool_calls_from_body(body)

        assert len(result) == 2
        assert result[0].name == "func1"
        assert result[1].name == "func2"

    def test_no_tool_calls(self, tmp_path: Path) -> None:
        """Test body without tool calls."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        body = {"content": [{"type": "text", "text": "Just text"}]}

        result = merger._extract_tool_calls_from_body(body)
        assert result == []


class TestStreamMergerIntegration:
    """Integration tests for the full merge workflow."""

    def test_merge_anthropic_streaming_request(self, tmp_path: Path) -> None:
        """Test merging a complete Anthropic streaming request."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_anthropic_123"
        timestamp = "2025-01-01T12:00:00Z"

        records = [
            # Request
            {
                "type": "request",
                "id": request_id,
                "timestamp": timestamp,
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "body": {"model": "claude-3-sonnet", "messages": []},
            },
            # Streaming chunks
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 0,
                "content": {"delta": {"text": "Hello "}},
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 1,
                "content": {"delta": {"text": "World!"}},
            },
            # Meta
            {
                "type": "response_meta",
                "request_id": request_id,
                "status_code": 200,
                "total_latency_ms": 500,
                "total_chunks": 2,
            },
        ]

        # Write input file
        with open(input_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        # Merge
        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["streaming_requests"] == 1
        assert stats["total_chunks_processed"] == 2

        # Verify output
        with open(output_file) as f:
            merged = json.loads(f.readline())

        assert merged["request_id"] == request_id
        assert merged["response_text"] == "Hello World!"
        assert merged["chunk_count"] == 2
        assert merged["total_latency_ms"] == 500

    def test_merge_openai_streaming_request(self, tmp_path: Path) -> None:
        """Test merging a complete OpenAI streaming request."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_openai_456"
        timestamp = "2025-01-01T12:00:00Z"

        records = [
            # Request
            {
                "type": "request",
                "id": request_id,
                "timestamp": timestamp,
                "method": "POST",
                "url": "https://api.openai.com/v1/chat/completions",
                "body": {"model": "gpt-4", "messages": [], "stream": True},
            },
            # Streaming chunks
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 0,
                "content": {"choices": [{"delta": {"content": "Hello "}}]},
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 1,
                "content": {"choices": [{"delta": {"content": "from GPT!"}}]},
            },
            # Meta
            {
                "type": "response_meta",
                "request_id": request_id,
                "status_code": 200,
                "total_latency_ms": 300,
                "total_chunks": 2,
            },
        ]

        # Write input file
        with open(input_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        # Merge
        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["streaming_requests"] == 1

        # Verify output
        with open(output_file) as f:
            merged = json.loads(f.readline())

        assert merged["response_text"] == "Hello from GPT!"

    def test_merge_anthropic_non_streaming_with_tool_calls(self, tmp_path: Path) -> None:
        """Test merging non-streaming Anthropic response with tool calls."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_non_stream_789"
        timestamp = "2025-01-01T12:00:00Z"

        records = [
            # Request
            {
                "type": "request",
                "id": request_id,
                "timestamp": timestamp,
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "body": {"model": "claude-3-sonnet", "messages": []},
            },
            # Non-streaming response
            {
                "type": "response",
                "request_id": request_id,
                "status_code": 200,
                "latency_ms": 250,
                "body": {
                    "content": [
                        {"type": "text", "text": "I'll help you."},
                        {
                            "type": "tool_use",
                            "id": "tool_999",
                            "name": "search",
                            "input": {"query": "test"},
                        },
                    ]
                },
            },
        ]

        # Write input file
        with open(input_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        # Merge
        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["non_streaming_requests"] == 1

        # Verify output
        with open(output_file) as f:
            merged = json.loads(f.readline())

        assert merged["response_text"] == "I'll help you."
        assert len(merged["tool_calls"]) == 1
        assert merged["tool_calls"][0]["name"] == "search"
        assert merged["chunk_count"] == 0

    def test_merge_openai_non_streaming_with_tool_calls(self, tmp_path: Path) -> None:
        """Test merging non-streaming OpenAI response with tool calls."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_openai_non_stream"
        timestamp = "2025-01-01T12:00:00Z"

        records = [
            # Request
            {
                "type": "request",
                "id": request_id,
                "timestamp": timestamp,
                "method": "POST",
                "url": "https://api.openai.com/v1/chat/completions",
                "body": {"model": "gpt-4", "messages": []},
            },
            # Non-streaming response
            {
                "type": "response",
                "request_id": request_id,
                "status_code": 200,
                "latency_ms": 200,
                "body": {
                    "choices": [
                        {
                            "message": {
                                "content": "Let me check.",
                                "tool_calls": [
                                    {
                                        "id": "call_abc",
                                        "function": {
                                            "name": "get_data",
                                            "arguments": '{"id": 123}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            },
        ]

        # Write input file
        with open(input_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        # Merge
        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["non_streaming_requests"] == 1

        # Verify output
        with open(output_file) as f:
            merged = json.loads(f.readline())

        assert merged["response_text"] == "Let me check."
        assert len(merged["tool_calls"]) == 1
        assert merged["tool_calls"][0]["name"] == "get_data"

    def test_merge_anthropic_streaming_with_tool_calls(self, tmp_path: Path) -> None:
        """Test merging Anthropic streaming response with tool calls."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_stream_tools"
        timestamp = "2025-01-01T12:00:00Z"

        records = [
            # Request
            {
                "type": "request",
                "id": request_id,
                "timestamp": timestamp,
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "body": {"model": "claude-3-sonnet", "messages": [], "stream": True},
            },
            # Text content block
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 0,
                "content": {"delta": {"text": "Reading file..."}},
            },
            # Tool use content block start
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 1,
                "content": {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool_stream_123",
                        "name": "read_file",
                    },
                },
            },
            # Tool input delta
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 2,
                "content": {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"path": "/etc/hosts"}',
                    },
                },
            },
            # Meta
            {
                "type": "response_meta",
                "request_id": request_id,
                "status_code": 200,
                "total_latency_ms": 400,
                "total_chunks": 3,
            },
        ]

        # Write input file
        with open(input_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        # Merge
        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["streaming_requests"] == 1
        assert stats["total_chunks_processed"] == 3

        # Verify output
        with open(output_file) as f:
            merged = json.loads(f.readline())

        assert merged["response_text"] == "Reading file..."
        assert len(merged["tool_calls"]) == 1
        assert merged["tool_calls"][0]["id"] == "tool_stream_123"
        assert merged["tool_calls"][0]["name"] == "read_file"
        assert merged["tool_calls"][0]["input"] == {"path": "/etc/hosts"}

    def test_merge_incomplete_request(self, tmp_path: Path) -> None:
        """Test handling request without response."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        records = [
            {
                "type": "request",
                "id": "orphan_request",
                "timestamp": "2025-01-01T12:00:00Z",
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
            },
        ]

        # Write input file
        with open(input_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        # Merge
        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["incomplete_requests"] == 1
        assert stats["streaming_requests"] == 0
        assert stats["non_streaming_requests"] == 0

    def test_merge_mixed_requests(self, tmp_path: Path) -> None:
        """Test merging file with mixed streaming and non-streaming requests."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        records = [
            # Streaming request
            {
                "type": "request",
                "id": "stream_req",
                "timestamp": "2025-01-01T12:00:00Z",
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
            },
            {
                "type": "response_chunk",
                "request_id": "stream_req",
                "status_code": 200,
                "chunk_index": 0,
                "content": {"delta": {"text": "Streamed"}},
            },
            {
                "type": "response_meta",
                "request_id": "stream_req",
                "status_code": 200,
                "total_latency_ms": 100,
            },
            # Non-streaming request
            {
                "type": "request",
                "id": "non_stream_req",
                "timestamp": "2025-01-01T12:01:00Z",
                "method": "POST",
                "url": "https://api.openai.com/v1/chat/completions",
            },
            {
                "type": "response",
                "request_id": "non_stream_req",
                "status_code": 200,
                "latency_ms": 150,
                "body": {"choices": [{"message": {"content": "Non-streamed"}}]},
            },
        ]

        # Write input file
        with open(input_file, "w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        # Merge
        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["streaming_requests"] == 1
        assert stats["non_streaming_requests"] == 1
        assert stats["total_requests"] == 2

        # Verify output
        with open(output_file) as f:
            lines = f.readlines()

        assert len(lines) == 2
        merged1 = json.loads(lines[0])
        merged2 = json.loads(lines[1])

        texts = {merged1["response_text"], merged2["response_text"]}
        assert "Streamed" in texts
        assert "Non-streamed" in texts


class TestParseTimestamp:
    """Test timestamp parsing."""

    def test_parse_iso_format(self, tmp_path: Path) -> None:
        """Test parsing ISO format timestamp."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        result = merger._parse_timestamp("2025-01-15T10:30:00")
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_iso_format_with_z(self, tmp_path: Path) -> None:
        """Test parsing ISO format timestamp with Z suffix."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        result = merger._parse_timestamp("2025-01-15T10:30:00Z")
        assert result.year == 2025
        assert result.hour == 10

    def test_parse_datetime_object(self, tmp_path: Path) -> None:
        """Test passing datetime object directly."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        dt = datetime(2025, 6, 15, 14, 30)
        result = merger._parse_timestamp(dt)
        assert result == dt

    def test_parse_invalid_fallback(self, tmp_path: Path) -> None:
        """Test fallback for invalid timestamp."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        result = merger._parse_timestamp("invalid")
        # Should return current time (approximately)
        assert isinstance(result, datetime)


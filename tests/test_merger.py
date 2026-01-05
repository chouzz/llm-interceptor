"""Tests for stream merger functionality."""

import json
from datetime import datetime
from pathlib import Path

from cci.merger import StreamMerger


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


class TestDetectApiFormat:
    """Test API format detection from chunks."""

    def test_detect_anthropic_message_start(self, tmp_path: Path) -> None:
        """Test detecting Anthropic format from message_start."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"type": "message_start", "message": {"id": "msg_123"}}},
        ]

        result = merger._detect_api_format(chunks)
        assert result == "anthropic"

    def test_detect_anthropic_content_block_start(self, tmp_path: Path) -> None:
        """Test detecting Anthropic format from content_block_start."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"type": "content_block_start", "index": 0}},
        ]

        result = merger._detect_api_format(chunks)
        assert result == "anthropic"

    def test_detect_anthropic_ping(self, tmp_path: Path) -> None:
        """Test detecting Anthropic format from ping."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"type": "ping"}},
        ]

        result = merger._detect_api_format(chunks)
        assert result == "anthropic"

    def test_detect_openai_choices(self, tmp_path: Path) -> None:
        """Test detecting OpenAI format from choices."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"choices": [{"delta": {"content": "Hello"}}]}},
        ]

        result = merger._detect_api_format(chunks)
        assert result == "openai"

    def test_detect_default_anthropic(self, tmp_path: Path) -> None:
        """Test default to anthropic for unknown format."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {"content": {"unknown": "data"}},
        ]

        result = merger._detect_api_format(chunks)
        assert result == "anthropic"


class TestRebuildAnthropicResponse:
    """Test rebuilding Anthropic API response from chunks."""

    def test_rebuild_basic_text_response(self, tmp_path: Path) -> None:
        """Test rebuilding a basic text response."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "status_code": 200,
                "timestamp": "2025-01-01T12:00:00Z",
                "content": {
                    "type": "message_start",
                    "message": {
                        "id": "msg_123",
                        "model": "claude-3-sonnet",
                        "role": "assistant",
                        "usage": {"input_tokens": 10, "output_tokens": 0},
                    },
                },
            },
            {
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello "},
                },
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "World!"},
                },
            },
            {
                "content": {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 5},
                },
            },
        ]

        result = merger._rebuild_anthropic_response("req_123", chunks, {})

        assert result["type"] == "response"
        assert result["request_id"] == "req_123"
        assert result["status_code"] == 200
        assert result["body"]["id"] == "msg_123"
        assert result["body"]["model"] == "claude-3-sonnet"
        assert result["body"]["role"] == "assistant"
        assert result["body"]["stop_reason"] == "end_turn"
        assert len(result["body"]["content"]) == 1
        assert result["body"]["content"][0]["type"] == "text"
        assert result["body"]["content"][0]["text"] == "Hello World!"

    def test_rebuild_response_with_tool_use(self, tmp_path: Path) -> None:
        """Test rebuilding response with tool use."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "status_code": 200,
                "content": {
                    "type": "message_start",
                    "message": {
                        "id": "msg_456",
                        "model": "claude-3-sonnet",
                        "role": "assistant",
                        "usage": {},
                    },
                },
            },
            {
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "I'll help."},
                },
            },
            {
                "content": {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool_abc",
                        "name": "read_file",
                    },
                },
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"path": "/test.txt"}',
                    },
                },
            },
            {
                "content": {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                },
            },
        ]

        result = merger._rebuild_anthropic_response("req_456", chunks, {})

        assert len(result["body"]["content"]) == 2
        assert result["body"]["content"][0]["type"] == "text"
        assert result["body"]["content"][0]["text"] == "I'll help."
        assert result["body"]["content"][1]["type"] == "tool_use"
        assert result["body"]["content"][1]["id"] == "tool_abc"
        assert result["body"]["content"][1]["name"] == "read_file"
        assert result["body"]["content"][1]["input"] == {"path": "/test.txt"}
        assert result["body"]["stop_reason"] == "tool_use"

    def test_rebuild_with_thinking_block(self, tmp_path: Path) -> None:
        """Test rebuilding response with thinking block."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "status_code": 200,
                "content": {
                    "type": "message_start",
                    "message": {
                        "id": "msg_789",
                        "model": "claude-3-sonnet",
                        "role": "assistant",
                        "usage": {},
                    },
                },
            },
            {
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": ""},
                },
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "Let me think..."},
                },
            },
            {
                "content": {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                },
            },
            {
                "content": {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": "Here's my answer."},
                },
            },
        ]

        result = merger._rebuild_anthropic_response("req_789", chunks, {})

        assert len(result["body"]["content"]) == 2
        assert result["body"]["content"][0]["type"] == "thinking"
        assert result["body"]["content"][0]["thinking"] == "Let me think..."
        assert result["body"]["content"][1]["type"] == "text"
        assert result["body"]["content"][1]["text"] == "Here's my answer."


class TestRebuildOpenAIResponse:
    """Test rebuilding OpenAI API response from chunks."""

    def test_rebuild_basic_text_response(self, tmp_path: Path) -> None:
        """Test rebuilding a basic OpenAI text response."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "status_code": 200,
                "timestamp": "2025-01-01T12:00:00Z",
                "content": {
                    "id": "chatcmpl-123",
                    "model": "gpt-4",
                    "created": 1704110400,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}}],
                },
            },
            {
                "content": {
                    "choices": [{"index": 0, "delta": {"content": "Hello "}}],
                },
            },
            {
                "content": {
                    "choices": [{"index": 0, "delta": {"content": "World!"}}],
                },
            },
            {
                "content": {
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            },
        ]

        result = merger._rebuild_openai_response("req_123", chunks, {})

        assert result["type"] == "response"
        assert result["request_id"] == "req_123"
        assert result["status_code"] == 200
        assert result["body"]["id"] == "chatcmpl-123"
        assert result["body"]["model"] == "gpt-4"
        assert result["body"]["created"] == 1704110400
        assert len(result["body"]["choices"]) == 1
        assert result["body"]["choices"][0]["message"]["role"] == "assistant"
        assert result["body"]["choices"][0]["message"]["content"] == "Hello World!"
        assert result["body"]["choices"][0]["finish_reason"] == "stop"
        assert result["body"]["usage"]["total_tokens"] == 15

    def test_rebuild_response_with_tool_calls(self, tmp_path: Path) -> None:
        """Test rebuilding OpenAI response with tool calls."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "status_code": 200,
                "content": {
                    "id": "chatcmpl-456",
                    "model": "gpt-4",
                    "choices": [{"index": 0, "delta": {"role": "assistant"}}],
                },
            },
            {
                "content": {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_abc",
                                        "type": "function",
                                        "function": {"name": "get_weather", "arguments": ""},
                                    }
                                ]
                            },
                        }
                    ],
                },
            },
            {
                "content": {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [{"index": 0, "function": {"arguments": '{"loc'}}]
                            },
                        }
                    ],
                },
            },
            {
                "content": {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": 'ation": "Tokyo"}'}}
                                ]
                            },
                        }
                    ],
                },
            },
            {
                "content": {
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                },
            },
        ]

        result = merger._rebuild_openai_response("req_456", chunks, {})

        assert len(result["body"]["choices"]) == 1
        message = result["body"]["choices"][0]["message"]
        assert "tool_calls" in message
        assert len(message["tool_calls"]) == 1
        assert message["tool_calls"][0]["id"] == "call_abc"
        assert message["tool_calls"][0]["function"]["name"] == "get_weather"
        assert message["tool_calls"][0]["function"]["arguments"] == '{"location": "Tokyo"}'
        assert result["body"]["choices"][0]["finish_reason"] == "tool_calls"

    def test_rebuild_with_multiple_choices(self, tmp_path: Path) -> None:
        """Test rebuilding OpenAI response with multiple choices."""
        merger = StreamMerger(tmp_path / "in.jsonl", tmp_path / "out.jsonl")

        chunks = [
            {
                "status_code": 200,
                "content": {
                    "id": "chatcmpl-789",
                    "model": "gpt-4",
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant"}},
                        {"index": 1, "delta": {"role": "assistant"}},
                    ],
                },
            },
            {
                "content": {
                    "choices": [
                        {"index": 0, "delta": {"content": "First"}},
                        {"index": 1, "delta": {"content": "Second"}},
                    ],
                },
            },
            {
                "content": {
                    "choices": [
                        {"index": 0, "finish_reason": "stop"},
                        {"index": 1, "finish_reason": "stop"},
                    ],
                },
            },
        ]

        result = merger._rebuild_openai_response("req_789", chunks, {})

        assert len(result["body"]["choices"]) == 2
        assert result["body"]["choices"][0]["message"]["content"] == "First"
        assert result["body"]["choices"][1]["message"]["content"] == "Second"


class TestStreamMergerIntegration:
    """Integration tests for the full merge workflow with new output format."""

    def test_merge_anthropic_streaming_outputs_request_response_lines(self, tmp_path: Path) -> None:
        """Test that merge outputs separate request and response lines."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_anthropic_123"
        timestamp = "2025-01-01T12:00:00Z"

        records = [
            {
                "type": "request",
                "id": request_id,
                "timestamp": timestamp,
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "body": {"model": "claude-3-sonnet", "messages": []},
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 0,
                "content": {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test",
                        "model": "claude-3-sonnet",
                        "role": "assistant",
                        "usage": {"input_tokens": 10},
                    },
                },
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 1,
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 2,
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello World!"},
                },
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 3,
                "content": {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 5},
                },
            },
            {
                "type": "response_meta",
                "request_id": request_id,
                "status_code": 200,
                "total_latency_ms": 500,
            },
        ]

        with open(input_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["streaming_requests"] == 1
        assert stats["total_chunks_processed"] == 4

        # Verify output has 2 lines: request and response
        with open(output_file, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 2

        # First line should be the original request
        request_line = json.loads(lines[0])
        assert request_line["type"] == "request"
        assert request_line["id"] == request_id

        # Second line should be the rebuilt response
        response_line = json.loads(lines[1])
        assert response_line["type"] == "response"
        assert response_line["request_id"] == request_id
        assert response_line["status_code"] == 200
        assert response_line["body"]["id"] == "msg_test"
        assert response_line["body"]["model"] == "claude-3-sonnet"
        assert response_line["body"]["content"][0]["text"] == "Hello World!"
        assert response_line["body"]["stop_reason"] == "end_turn"

    def test_merge_openai_streaming_outputs_request_response_lines(self, tmp_path: Path) -> None:
        """Test that merge outputs separate request and response lines for OpenAI."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_openai_456"

        records = [
            {
                "type": "request",
                "id": request_id,
                "timestamp": "2025-01-01T12:00:00Z",
                "method": "POST",
                "url": "https://api.openai.com/v1/chat/completions",
                "body": {"model": "gpt-4", "messages": [], "stream": True},
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 0,
                "content": {
                    "id": "chatcmpl-test",
                    "model": "gpt-4",
                    "choices": [{"index": 0, "delta": {"role": "assistant"}}],
                },
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 1,
                "content": {
                    "choices": [{"index": 0, "delta": {"content": "Hello from GPT!"}}],
                },
            },
            {
                "type": "response_chunk",
                "request_id": request_id,
                "status_code": 200,
                "chunk_index": 2,
                "content": {
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            },
            {
                "type": "response_meta",
                "request_id": request_id,
                "status_code": 200,
                "total_latency_ms": 300,
            },
        ]

        with open(input_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["streaming_requests"] == 1

        with open(output_file, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 2

        request_line = json.loads(lines[0])
        assert request_line["type"] == "request"
        assert request_line["id"] == request_id

        response_line = json.loads(lines[1])
        assert response_line["type"] == "response"
        assert response_line["body"]["id"] == "chatcmpl-test"
        assert response_line["body"]["choices"][0]["message"]["content"] == "Hello from GPT!"
        assert response_line["body"]["choices"][0]["finish_reason"] == "stop"

    def test_merge_non_streaming_preserves_original_response(self, tmp_path: Path) -> None:
        """Test that non-streaming responses are preserved as-is."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        request_id = "req_non_stream"
        original_response = {
            "type": "response",
            "request_id": request_id,
            "status_code": 200,
            "latency_ms": 250,
            "body": {
                "id": "msg_original",
                "content": [{"type": "text", "text": "Original response"}],
            },
        }

        records = [
            {
                "type": "request",
                "id": request_id,
                "timestamp": "2025-01-01T12:00:00Z",
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "body": {"model": "claude-3-sonnet", "messages": []},
            },
            original_response,
        ]

        with open(input_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["non_streaming_requests"] == 1

        with open(output_file, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 2

        request_line = json.loads(lines[0])
        assert request_line["type"] == "request"

        response_line = json.loads(lines[1])
        assert response_line == original_response

    def test_merge_mixed_requests_maintains_order(self, tmp_path: Path) -> None:
        """Test that mixed streaming/non-streaming requests maintain order."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        records = [
            # First: streaming request
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
                "content": {
                    "type": "message_start",
                    "message": {"id": "msg_1", "model": "claude", "role": "assistant"},
                },
            },
            {
                "type": "response_chunk",
                "request_id": "stream_req",
                "status_code": 200,
                "chunk_index": 1,
                "content": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            },
            {
                "type": "response_chunk",
                "request_id": "stream_req",
                "status_code": 200,
                "chunk_index": 2,
                "content": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Streamed"},
                },
            },
            {
                "type": "response_meta",
                "request_id": "stream_req",
                "status_code": 200,
                "total_latency_ms": 100,
            },
            # Second: non-streaming request
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

        with open(input_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["streaming_requests"] == 1
        assert stats["non_streaming_requests"] == 1
        assert stats["total_requests"] == 2

        with open(output_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Should have 4 lines: req1, resp1, req2, resp2
        assert len(lines) == 4

        # Verify order
        line0 = json.loads(lines[0])
        assert line0["type"] == "request"
        assert line0["id"] == "stream_req"

        line1 = json.loads(lines[1])
        assert line1["type"] == "response"
        assert line1["request_id"] == "stream_req"
        assert line1["body"]["content"][0]["text"] == "Streamed"

        line2 = json.loads(lines[2])
        assert line2["type"] == "request"
        assert line2["id"] == "non_stream_req"

        line3 = json.loads(lines[3])
        assert line3["type"] == "response"
        assert line3["request_id"] == "non_stream_req"

    def test_merge_incomplete_request_outputs_only_request(self, tmp_path: Path) -> None:
        """Test that incomplete requests only output the request line."""
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

        with open(input_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        merger = StreamMerger(input_file, output_file)
        stats = merger.merge()

        assert stats["incomplete_requests"] == 1

        with open(output_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Should only have the request line
        assert len(lines) == 1
        line = json.loads(lines[0])
        assert line["type"] == "request"
        assert line["id"] == "orphan_request"


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

"""
Data models for LLM Interceptor.

Defines the JSON schema for request, response chunk, and response meta records.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class RecordType(str, Enum):
    """Type of record in the JSONL output."""

    REQUEST = "request"
    RESPONSE_CHUNK = "response_chunk"
    RESPONSE_META = "response_meta"


class RequestRecord(BaseModel):
    """
    Type A: Request record.

    Captures the outgoing request to the LLM API.
    """

    type: RecordType = RecordType.REQUEST
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() + "Z"}


class ResponseChunkRecord(BaseModel):
    """
    Type B: Response chunk record (for streaming responses).

    Captures individual SSE chunks from streaming responses.
    """

    type: RecordType = RecordType.RESPONSE_CHUNK
    request_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status_code: int
    chunk_index: int
    content: Any = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() + "Z"}


class ResponseMetaRecord(BaseModel):
    """
    Type C: Response meta record.

    Captures metadata about the complete response.
    """

    type: RecordType = RecordType.RESPONSE_META
    request_id: str
    total_latency_ms: float
    status_code: int
    total_chunks: int | None = None
    error: str | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() + "Z"}


class NonStreamingResponseRecord(BaseModel):
    """
    Response record for non-streaming responses.

    Captures the complete response body at once.
    """

    type: str = "response"
    request_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    latency_ms: float

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() + "Z"}


class ToolCall(BaseModel):
    """
    Represents a tool call extracted from streaming response.
    """

    id: str
    name: str
    input: Any = None


class MergedRecord(BaseModel):
    """
    Merged record combining request and all response chunks.

    Used by the merge command to produce consolidated logs.
    """

    request_id: str
    timestamp: datetime
    method: str
    url: str
    request_body: Any = None
    response_status: int
    response_text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    total_latency_ms: float
    chunk_count: int = 0

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() + "Z"}

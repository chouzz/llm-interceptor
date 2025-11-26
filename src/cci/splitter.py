"""
Record splitter utility for Claude-Code-Inspector.

Splits merged JSONL files into individual text files for analysis.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cci.logger import get_logger
from cci.storage import read_jsonl


class RecordSplitter:
    """
    Splits merged JSONL records into individual text files.

    Reads a merged JSONL file and produces individual text files
    containing the request prompt and response for each record.
    """

    SEPARATOR = "=" * 80

    def __init__(self, input_path: str | Path, output_dir: str | Path):
        """
        Initialize the record splitter.

        Args:
            input_path: Path to input merged JSONL file
            output_dir: Directory to write individual files
        """
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self._logger = get_logger()

    def split(self) -> dict[str, int]:
        """
        Perform the split operation.

        Returns:
            Statistics about the split operation
        """
        self._logger.info("Reading records from %s", self.input_path)
        records = list(read_jsonl(self.input_path))

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

        stats = {
            "total_records": len(records),
            "files_created": 0,
            "errors": 0,
        }

        for index, record in enumerate(records, start=1):
            try:
                filename = self._generate_filename(index, record)
                content = self._format_record(record)

                output_path = self.output_dir / filename
                output_path.write_text(content, encoding="utf-8")

                stats["files_created"] += 1
                self._logger.debug("Created %s", filename)

            except Exception as e:
                self._logger.error("Error processing record %d: %s", index, e)
                stats["errors"] += 1

        self._logger.info(
            "Split complete: %d files created in %s",
            stats["files_created"],
            self.output_dir,
        )

        return stats

    def _generate_filename(self, index: int, record: dict[str, Any]) -> str:
        """
        Generate filename for a record.

        Format: {seq:03d}_{timestamp}.txt
        Example: 001_2025-11-26_14-12-47.txt
        """
        timestamp = record.get("timestamp", "")
        ts_str = self._format_timestamp_for_filename(timestamp)

        return f"{index:03d}_{ts_str}.txt"

    def _format_timestamp_for_filename(self, timestamp: Any) -> str:
        """Format timestamp for use in filename."""
        if isinstance(timestamp, str):
            # Parse ISO format timestamp
            ts = timestamp.rstrip("Z").replace("+00:00", "")
            try:
                dt = datetime.fromisoformat(ts)
                return dt.strftime("%Y-%m-%d_%H-%M-%S")
            except ValueError:
                pass

        if isinstance(timestamp, datetime):
            return timestamp.strftime("%Y-%m-%d_%H-%M-%S")

        # Fallback to current time
        return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    def _format_record(self, record: dict[str, Any]) -> str:
        """
        Format a record into readable text content.

        Returns:
            Formatted text with request and response sections
        """
        lines = []

        # Request section
        lines.append(self.SEPARATOR)
        lines.append("REQUEST")
        lines.append(self.SEPARATOR)
        lines.append("")

        request_content = self._extract_request_content(record.get("request_body"))
        lines.append(request_content)

        lines.append("")

        # Response section
        lines.append(self.SEPARATOR)
        lines.append("RESPONSE")
        lines.append(self.SEPARATOR)
        lines.append("")

        response_content = self._extract_response_content(record.get("response_text", ""))
        lines.append(response_content)

        # Tool calls section (if present)
        tool_calls = record.get("tool_calls", [])
        if tool_calls:
            lines.append("")
            lines.append(self.SEPARATOR)
            lines.append("TOOL CALLS")
            lines.append(self.SEPARATOR)
            lines.append("")

            tool_calls_content = self._format_tool_calls(tool_calls)
            lines.append(tool_calls_content)

        return "\n".join(lines)

    def _extract_request_content(self, request_body: Any) -> str:
        """
        Extract the full request body as formatted JSON.

        Outputs the complete request body including tools, system prompts, etc.
        """
        if request_body is None:
            return "[No request body]"

        if isinstance(request_body, str):
            return self._unescape_newlines(request_body)

        if isinstance(request_body, dict):
            # Output the full request body as pretty-printed JSON
            formatted = json.dumps(request_body, indent=2, ensure_ascii=False)
            return self._unescape_newlines(formatted)

        # Fallback for other types
        return self._unescape_newlines(str(request_body))

    def _extract_response_content(self, response_text: Any) -> str:
        """
        Extract readable content from response_text.

        Converts escaped newlines to actual newlines.
        """
        if response_text is None:
            return "[No response]"

        if isinstance(response_text, str):
            return self._unescape_newlines(response_text)

        # Handle dict or other types
        if isinstance(response_text, dict):
            return self._unescape_newlines(json.dumps(response_text, indent=2, ensure_ascii=False))

        return self._unescape_newlines(str(response_text))

    def _unescape_newlines(self, text: str) -> str:
        """
        Convert escaped newlines to actual newlines.

        Handles both \\n (JSON escaped) and \n (literal backslash-n).
        """
        # Replace literal \n with actual newline
        # This handles cases where the text contains "\\n" which represents a newline
        result = text.replace("\\n", "\n")
        # Also handle \t for tabs
        result = result.replace("\\t", "\t")
        return result

    def _format_tool_calls(self, tool_calls: list[dict[str, Any]]) -> str:
        """
        Format tool calls into readable text.

        Args:
            tool_calls: List of tool call dictionaries with id, name, and input

        Returns:
            Formatted text representation of tool calls
        """
        lines = []

        for i, tool_call in enumerate(tool_calls, start=1):
            tool_id = tool_call.get("id", "")
            tool_name = tool_call.get("name", "")
            tool_input = tool_call.get("input")

            lines.append(f"[{i}] {tool_name}")
            lines.append(f"    ID: {tool_id}")

            if tool_input:
                # Format input as pretty-printed JSON
                if isinstance(tool_input, dict):
                    input_str = json.dumps(tool_input, indent=4, ensure_ascii=False)
                    # Indent each line for nested display
                    indented_input = "\n".join(
                        "    " + line for line in input_str.split("\n")
                    )
                    lines.append(f"    Input:")
                    lines.append(indented_input)
                else:
                    lines.append(f"    Input: {tool_input}")

            lines.append("")  # Blank line between tool calls

        return "\n".join(lines)


def split_records(input_path: str | Path, output_dir: str | Path) -> dict[str, int]:
    """
    Convenience function to split merged records.

    Args:
        input_path: Path to input merged JSONL file
        output_dir: Directory to write individual files

    Returns:
        Statistics about the split operation
    """
    splitter = RecordSplitter(input_path, output_dir)
    return splitter.split()


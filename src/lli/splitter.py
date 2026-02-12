"""
Record splitter utility for LLM Interceptor.

Splits merged JSONL files into individual JSON files (request and response).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from lli.logger import get_logger
from lli.storage import read_jsonl


class RecordSplitter:
    """
    Splits merged JSONL records into individual JSON files.

    Reads a merged JSONL file and produces individual JSON files
    for each request and response record.

    Output files are named: {index:03d}_{type}_{timestamp}.json
    Example: 001_request_2025-11-26_14-12-47.json
             001_response_2025-11-26_14-12-47.json
    """

    def __init__(self, input_path: str | Path, output_dir: str | Path):
        """
        Initialize the record splitter.

        Args:
            input_path: Path to input merged JSONL file
            output_dir: Directory to write individual JSON files
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
            "request_files": 0,
            "response_files": 0,
            "errors": 0,
        }

        # Track pair index for naming
        pair_index = 0

        for record in records:
            record_type = record.get("type", "")

            try:
                if record_type == "request":
                    pair_index += 1
                    filename = self._generate_filename(pair_index, "request", record)
                    self._write_json_file(filename, record)
                    stats["request_files"] += 1
                    self._logger.debug("Created %s", filename)

                elif record_type == "response":
                    # Response uses the same pair_index as its corresponding request
                    filename = self._generate_filename(pair_index, "response", record)
                    self._write_json_file(filename, record)
                    stats["response_files"] += 1
                    self._logger.debug("Created %s", filename)

            except Exception as e:
                self._logger.error("Error processing record: %s", e)
                stats["errors"] += 1

        self._logger.info(
            "Split complete: %d request files, %d response files created in %s",
            stats["request_files"],
            stats["response_files"],
            self.output_dir,
        )

        return stats

    def _generate_filename(self, index: int, record_type: str, record: dict[str, Any]) -> str:
        """
        Generate filename for a record.

        Format: {index:03d}_{type}_{timestamp}.json
        Example: 001_request_2025-11-26_14-12-47.json
        """
        timestamp = record.get("timestamp", "")
        ts_str = self._format_timestamp_for_filename(timestamp)

        return f"{index:03d}_{record_type}_{ts_str}.json"

    def _format_timestamp_for_filename(self, timestamp: Any) -> str:
        """Format timestamp for use in filename."""
        if isinstance(timestamp, str):
            # Parse ISO format timestamp
            ts = timestamp.rstrip("Z").replace("+00:00", "")
            # Remove any trailing Z after timezone removal
            if ts.endswith("Z"):
                ts = ts[:-1]
            try:
                dt = datetime.fromisoformat(ts)
                return dt.strftime("%Y-%m-%d_%H-%M-%S")
            except ValueError:
                pass

        if isinstance(timestamp, datetime):
            return timestamp.strftime("%Y-%m-%d_%H-%M-%S")

        # Fallback to current time
        return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    def _write_json_file(self, filename: str, record: dict[str, Any]) -> None:
        """
        Write a record to a JSON file.

        Args:
            filename: Name of the file to create
            record: The record data to write
        """
        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)


def split_records(input_path: str | Path, output_dir: str | Path) -> dict[str, int]:
    """
    Convenience function to split merged records.

    Args:
        input_path: Path to input merged JSONL file
        output_dir: Directory to write individual JSON files

    Returns:
        Statistics about the split operation
    """
    splitter = RecordSplitter(input_path, output_dir)
    return splitter.split()

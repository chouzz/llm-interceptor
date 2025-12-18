"""
JSONL storage for LLM Interceptor.

Handles writing request/response records to JSONL files.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import BaseModel

from cci.logger import get_logger


class JSONLWriter:
    """
    Thread-safe JSONL file writer.

    Writes Pydantic models or dicts as JSON lines to a file.
    """

    def __init__(
        self,
        output_path: str | Path,
        pretty: bool = False,
        max_size_mb: int = 0,
        append: bool = True,
    ):
        """
        Initialize the JSONL writer.

        Args:
            output_path: Path to the output JSONL file
            pretty: If True, write pretty-printed JSON (one record per multiple lines)
            max_size_mb: Maximum file size in MB before rotation (0 = no rotation)
            append: If True, append to existing file; if False, overwrite
        """
        self.output_path = Path(output_path)
        self.pretty = pretty
        self.max_size_mb = max_size_mb
        self.append = append
        self._lock = threading.Lock()
        self._file: TextIO | None = None
        self._record_count = 0
        self._logger = get_logger()

        # Ensure parent directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> "JSONLWriter":
        """Open the file for writing."""
        mode = "a" if self.append else "w"
        self._file = open(self.output_path, mode, encoding="utf-8")
        return self

    def __exit__(self, *args: object) -> None:
        """Close the file."""
        if self._file:
            self._file.close()
            self._file = None

    def open(self) -> None:
        """Open the file for writing."""
        if self._file is None:
            mode = "a" if self.append else "w"
            self._file = open(self.output_path, mode, encoding="utf-8")

    def close(self) -> None:
        """Close the file."""
        if self._file:
            self._file.close()
            self._file = None

    def write_record(self, record: BaseModel | dict[str, Any]) -> None:
        """
        Write a record to the JSONL file.

        Args:
            record: A Pydantic model or dictionary to write
        """
        with self._lock:
            if self._file is None:
                raise RuntimeError("Writer not opened. Use 'with' context or call open()")

            # Check for file rotation
            if self.max_size_mb > 0:
                self._check_rotation()

            # Convert to dict if Pydantic model
            if isinstance(record, BaseModel):
                data = record.model_dump(mode="json")
            else:
                data = record

            # Convert datetime objects to ISO format
            data = self._serialize_datetimes(data)

            # Write as JSON line
            if self.pretty:
                json_str = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

            self._file.write(json_str + "\n")
            self._file.flush()
            self._record_count += 1

            self._logger.debug(f"Wrote record #{self._record_count} to {self.output_path}")

    def _serialize_datetimes(self, obj: Any) -> Any:
        """Recursively serialize datetime objects to ISO format strings."""
        if isinstance(obj, datetime):
            return obj.isoformat() + "Z" if obj.tzinfo is None else obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._serialize_datetimes(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_datetimes(item) for item in obj]
        return obj

    def _check_rotation(self) -> None:
        """Check if file rotation is needed and perform if necessary."""
        if self._file is None:
            return

        current_size = self.output_path.stat().st_size / (1024 * 1024)  # MB
        if current_size >= self.max_size_mb:
            self._rotate_file()

    def _rotate_file(self) -> None:
        """Rotate the current file by renaming it with a timestamp."""
        if self._file:
            self._file.close()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated_name = f"{self.output_path.stem}_{timestamp}{self.output_path.suffix}"
        rotated_path = self.output_path.parent / rotated_name
        self.output_path.rename(rotated_path)

        self._logger.info(f"Rotated log file to {rotated_path}")

        # Open new file
        self._file = open(self.output_path, "a", encoding="utf-8")

    @property
    def record_count(self) -> int:
        """Return the number of records written."""
        return self._record_count


def read_jsonl(file_path: str | Path) -> list[dict[str, Any]]:
    """
    Read all records from a JSONL file.

    Args:
        file_path: Path to the JSONL file

    Returns:
        List of dictionaries representing each record
    """
    records: list[dict[str, Any]] = []
    with open(file_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                get_logger().warning(f"Skipping invalid JSON at line {line_num}: {e}")
    return records


def count_records(file_path: str | Path) -> dict[str, int]:
    """
    Count records by type in a JSONL file.

    Args:
        file_path: Path to the JSONL file

    Returns:
        Dictionary with counts by record type
    """
    counts: dict[str, int] = {}
    for record in read_jsonl(file_path):
        record_type = record.get("type", "unknown")
        counts[record_type] = counts.get(record_type, 0) + 1
    return counts

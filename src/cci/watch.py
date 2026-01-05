"""
Watch mode for LLM Interceptor.

Provides continuous capture with session management:
- IDLE: Monitor traffic without session assignment
- RECORDING: Capture traffic with session ID injection
- PROCESSING: Extract, merge, and split session data
"""

import json
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from cci.config import get_default_trace_dir
from cci.logger import get_logger


class WatchState(Enum):
    """State machine states for watch mode."""

    IDLE = "IDLE"
    RECORDING = "RECORDING"
    PROCESSING = "PROCESSING"


@dataclass
class SessionContext:
    """
    Metadata for a recording session.

    Tracks the session ID, timestamps, and file offsets
    for extracting session data from the global log.
    """

    session_id: str
    start_time: datetime
    start_offset: int = 0
    end_offset: int = 0
    end_time: datetime | None = None

    @property
    def directory_name(self) -> str:
        """Generate directory name for this session."""
        return self.session_id


class GlobalLogger:
    """
    Thread-safe global log writer with offset tracking.

    Writes all captured traffic to a single JSONL file,
    providing methods to:
    - Write records with session ID injection
    - Track file position (byte offset)
    - Extract segments between two offsets
    """

    def __init__(self, filepath: str | Path):
        """
        Initialize the global logger.

        Args:
            filepath: Path to the global JSONL log file
        """
        self.filepath = Path(filepath)
        self._file: TextIO | None = None
        self._lock = threading.Lock()
        self._logger = get_logger()

        # Ensure parent directory exists
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def open(self) -> None:
        """Open the log file for appending."""
        if self._file is None:
            self._file = open(self.filepath, "a", encoding="utf-8")
            self._logger.debug("Opened global log: %s", self.filepath)

    def close(self) -> None:
        """Close the log file."""
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None
            self._logger.debug("Closed global log: %s", self.filepath)

    def __enter__(self) -> "GlobalLogger":
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.close()

    def write_record(self, data: dict[str, Any]) -> None:
        """
        Write a record to the global log.

        The record is immediately flushed to disk for durability.

        Args:
            data: Dictionary to write as JSON line
        """
        with self._lock:
            if self._file is None:
                raise RuntimeError("GlobalLogger not opened. Call open() first.")

            json_line = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            self._file.write(json_line + "\n")
            self._file.flush()

    def get_current_offset(self) -> int:
        """
        Get the current file position (byte offset).

        Returns:
            Current byte position at end of file
        """
        with self._lock:
            if self._file is None:
                raise RuntimeError("GlobalLogger not opened. Call open() first.")
            return self._file.tell()

    def extract_segment(
        self,
        start_offset: int,
        end_offset: int,
        dest_path: str | Path,
        filter_control_frames: bool = True,
    ) -> int:
        """
        Extract data between two offsets to a destination file.

        Uses file seek operations for efficient extraction without
        loading the entire log into memory.

        Args:
            start_offset: Starting byte position
            end_offset: Ending byte position
            dest_path: Path to write extracted data
            filter_control_frames: If True, skip control frames (_meta_type)

        Returns:
            Number of data records extracted
        """
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        record_count = 0

        with (
            open(self.filepath, encoding="utf-8") as src,
            open(dest_path, "w", encoding="utf-8") as dst,
        ):
            src.seek(start_offset)
            current_pos = start_offset

            while current_pos < end_offset:
                line = src.readline()
                if not line:
                    break

                current_pos = src.tell()

                # Skip empty lines
                line = line.strip()
                if not line:
                    continue

                # Filter control frames if requested
                if filter_control_frames and "_meta_type" in line:
                    continue

                # Write data line to destination
                dst.write(line + "\n")
                record_count += 1

        self._logger.info(
            "Extracted %d records from offset %d-%d to %s",
            record_count,
            start_offset,
            end_offset,
            dest_path,
        )

        return record_count


class WatchManager:
    """
    Main controller for watch mode operation.

    Manages the state machine and coordinates:
    - Session lifecycle (start/stop recording)
    - Global logger operations
    - Session data extraction and processing
    """

    def __init__(self, output_dir: str | Path | None = None, port: int = 9090):
        """
        Initialize the watch manager.

        Args:
            output_dir: Root directory for all output files (default: auto-detected)
            port: Proxy server port
        """
        self.output_dir = Path(output_dir) if output_dir else get_default_trace_dir()
        self.port = port
        self._logger = get_logger()

        # State management
        self._state = WatchState.IDLE
        self._state_lock = threading.Lock()
        self._current_session: SessionContext | None = None
        self._session_seq = 1

        # Global log setup
        self._global_log_name = f"all_captured_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._global_log_path = self.output_dir / self._global_log_name
        self._global_logger: GlobalLogger | None = None

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state(self) -> WatchState:
        """Current state of the watch manager."""
        with self._state_lock:
            return self._state

    @property
    def current_session(self) -> SessionContext | None:
        """Currently active session, or None if idle."""
        with self._state_lock:
            return self._current_session

    @property
    def current_session_id(self) -> str | None:
        """ID of current session, or None if idle."""
        session = self.current_session
        return session.session_id if session else None

    @property
    def global_log_path(self) -> Path:
        """Path to the global log file."""
        return self._global_log_path

    @property
    def next_session_id(self) -> int:
        """Next session sequence number."""
        return self._session_seq

    def initialize(self) -> None:
        """Initialize the global logger."""
        self._global_logger = GlobalLogger(self._global_log_path)
        self._global_logger.open()
        self._logger.info("Initialized watch mode, logging to %s", self._global_log_path)

    def shutdown(self) -> None:
        """Clean up resources."""
        if self._global_logger:
            self._global_logger.close()
            self._global_logger = None
        self._logger.info("Watch mode shutdown complete")

    def write_record(self, record: dict[str, Any], session_id: str | None = None) -> None:
        """
        Write a record to the global log with session ID injection.

        Args:
            record: Record data to write
            session_id: Optional session ID to override the current one.
                      Used for responses to requests that started in a previous session.
        """
        if not self._global_logger:
            raise RuntimeError("WatchManager not initialized. Call initialize() first.")

        # Inject session ID: use provided one, or current one, or None
        if session_id is None:
            session_id = self.current_session_id

        record_with_session = {"_session_id": session_id, **record}

        self._global_logger.write_record(record_with_session)

    def start_recording(self) -> SessionContext:
        """
        Start a new recording session.

        Transitions from IDLE to RECORDING state.

        Returns:
            The newly created SessionContext

        Raises:
            RuntimeError: If not in IDLE state
        """
        with self._state_lock:
            if self._state != WatchState.IDLE:
                raise RuntimeError(f"Cannot start recording from {self._state} state")

            if not self._global_logger:
                raise RuntimeError("WatchManager not initialized")

            # Generate session ID (timestamp-based for easy identification)
            # Ensure unique ID by bumping timestamp if directory already exists
            timestamp = datetime.now()
            session_id = f"session_{timestamp.strftime('%Y%m%d_%H%M%S')}"

            while (self.output_dir / session_id).exists():
                from datetime import timedelta

                timestamp += timedelta(seconds=1)
                session_id = f"session_{timestamp.strftime('%Y%m%d_%H%M%S')}"

            # Write start marker
            start_marker = {
                "_meta_type": "session_start",
                "session_id": session_id,
                "timestamp": timestamp.isoformat(),
            }
            self._global_logger.write_record(start_marker)

            # Record offset AFTER the start marker
            start_offset = self._global_logger.get_current_offset()

            # Create session context
            session = SessionContext(
                session_id=session_id, start_time=timestamp, start_offset=start_offset
            )

            self._current_session = session
            self._state = WatchState.RECORDING

            self._logger.info("Started recording session: %s", session_id)
            return session

    def stop_recording(self) -> SessionContext:
        """
        Stop the current recording session.

        Transitions from RECORDING to PROCESSING state.

        Returns:
            The completed SessionContext with end offset

        Raises:
            RuntimeError: If not in RECORDING state
        """
        with self._state_lock:
            if self._state != WatchState.RECORDING:
                raise RuntimeError(f"Cannot stop recording from {self._state} state")

            if not self._global_logger or not self._current_session:
                raise RuntimeError("Invalid state: no active session")

            session = self._current_session

            # Record end offset BEFORE the end marker
            session.end_offset = self._global_logger.get_current_offset()
            session.end_time = datetime.now()

            # Write end marker
            end_marker = {
                "_meta_type": "session_end",
                "session_id": session.session_id,
                "timestamp": session.end_time.isoformat(),
            }
            self._global_logger.write_record(end_marker)

            self._state = WatchState.PROCESSING

            self._logger.info(
                "Stopped recording session: %s (offset %d-%d)",
                session.session_id,
                session.start_offset,
                session.end_offset,
            )
            return session

    def cancel_recording(self) -> SessionContext:
        """
        Cancel the current recording session without processing.

        Transitions from RECORDING back to IDLE state, clears the current
        session, and advances the session counter.

        Note:
            Captured traffic remains in the global log, but no session directory
            is created and no merge/split processing is performed.

        Returns:
            The cancelled SessionContext with end offset/time set.

        Raises:
            RuntimeError: If not in RECORDING state
        """
        with self._state_lock:
            if self._state != WatchState.RECORDING:
                raise RuntimeError(f"Cannot cancel recording from {self._state} state")

            if not self._global_logger or not self._current_session:
                raise RuntimeError("Invalid state: no active session")

            session = self._current_session

            # Record end offset/time at moment of cancellation
            session.end_offset = self._global_logger.get_current_offset()
            session.end_time = datetime.now()

            # Write cancel marker
            cancel_marker = {
                "_meta_type": "session_cancelled",
                "session_id": session.session_id,
                "timestamp": session.end_time.isoformat(),
            }
            self._global_logger.write_record(cancel_marker)

            # Transition back to IDLE without processing
            self._current_session = None
            self._session_seq += 1
            self._state = WatchState.IDLE

            self._logger.info(
                "Cancelled recording session: %s (offset %d-%d)",
                session.session_id,
                session.start_offset,
                session.end_offset,
            )
            return session

    def process_session(self, session: SessionContext) -> Path:
        """
        Process a completed session.

        Extracts session data, runs merge and split operations.
        Split output files are placed directly in the session directory.
        Transitions from PROCESSING to IDLE state.

        Args:
            session: The session to process

        Returns:
            Path to the session output directory

        Raises:
            RuntimeError: If not in PROCESSING state
        """
        with self._state_lock:
            if self._state != WatchState.PROCESSING:
                raise RuntimeError(f"Cannot process session from {self._state} state")

        if not self._global_logger:
            raise RuntimeError("WatchManager not initialized")

        # Create session directory
        session_dir = self.output_dir / session.directory_name
        session_dir.mkdir(parents=True, exist_ok=True)

        # Use temporary files for intermediate processing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            raw_path = temp_path / "raw.jsonl"
            merged_path = temp_path / "merged.jsonl"

            # Extract raw data to temp file
            record_count = self._global_logger.extract_segment(
                session.start_offset, session.end_offset, raw_path, filter_control_frames=True
            )

            self._logger.info(
                "Extracted %d records for session %s", record_count, session.session_id
            )

            # Run merge and split if records exist
            if record_count > 0:
                from cci.merger import merge_streams

                try:
                    merge_stats = merge_streams(raw_path, merged_path, session_id=session.session_id)
                    self._logger.info(
                        "Merged %d requests (%d streaming, %d non-streaming)",
                        merge_stats["total_requests"],
                        merge_stats["streaming_requests"],
                        merge_stats["non_streaming_requests"],
                    )

                    # Run split - output directly to session directory
                    from cci.splitter import split_records

                    split_stats = split_records(merged_path, session_dir)
                    self._logger.info(
                        "Split into %d request files, %d response files",
                        split_stats["request_files"],
                        split_stats["response_files"],
                    )
                except Exception as e:
                    self._logger.error("Error processing session: %s", e)

        # Transition back to IDLE
        with self._state_lock:
            self._current_session = None
            self._session_seq += 1
            self._state = WatchState.IDLE

        self._logger.info("Session %s processing complete", session.session_id)
        return session_dir

    def get_session_dir(self, session: SessionContext) -> Path:
        """Get the output directory path for a session."""
        return self.output_dir / session.directory_name

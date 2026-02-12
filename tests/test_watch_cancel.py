import json

from lli.watch import WatchManager, WatchState


def test_cancel_recording_transitions_to_idle(tmp_path) -> None:
    mgr = WatchManager(output_dir=tmp_path, port=1234)
    mgr.initialize()
    try:
        session = mgr.start_recording()
        assert mgr.state == WatchState.RECORDING
        assert session.request_count == 0

        # Write at least one record during the session
        mgr.write_record({"type": "request", "id": "req_1"})
        assert session.request_count == 1

        cancelled = mgr.cancel_recording()
        assert cancelled.session_id == session.session_id
        assert cancelled.request_count == 1
        assert mgr.state == WatchState.IDLE
        assert mgr.current_session is None
        assert mgr.next_session_id == 2

        # Cancel marker should be present in global log
        log_text = mgr.global_log_path.read_text(encoding="utf-8")
        assert '"_meta_type":"session_cancelled"' in log_text

        # Ensure the log is valid JSONL (at least for the cancel marker line)
        cancel_lines = [
            ln for ln in log_text.splitlines() if '"_meta_type":"session_cancelled"' in ln
        ]
        assert len(cancel_lines) == 1
        json.loads(cancel_lines[0])
    finally:
        mgr.shutdown()

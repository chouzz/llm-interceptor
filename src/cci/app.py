import json
import os
import re
from pathlib import Path
from typing import Any

import streamlit as st

from cci.config import get_default_trace_dir

# ================= 1. Config & Utils =================

# Set page config first
st.set_page_config(layout="wide", page_title="LLM Interceptor", page_icon="🔍")

# Determine BASE_DIR using the standard logic
BASE_DIR = get_default_trace_dir()


def parse_file_info(filename: str) -> tuple[int | None, str | None, str | None]:
    """
    Extract metadata from filename: 001_request_2025-12-03...json
    Returns: (seq_id, type, timestamp)
    """
    # Pattern: ID_TYPE_TIMESTAMP.json
    # Example: 001_request_2025-12-03_15-20-05.json
    match = re.match(r"(\d+)_([a-z]+)_(.+)\.json", filename)
    if match:
        return int(match.group(1)), match.group(2), match.group(3)
    return None, None, None


def load_session_turns(session_path: Path) -> list[dict[str, Any]]:
    """
    Core logic: Load and pair Request/Response, calculate context features.
    Looks for 'split_output' subdirectory first, otherwise scans the session dir.
    """
    # Check for split_output subdirectory
    split_output_dir = session_path / "split_output"
    if split_output_dir.exists() and split_output_dir.is_dir():
        target_dir = split_output_dir
    else:
        target_dir = session_path

    if not target_dir.exists():
        return []

    files = sorted(os.listdir(target_dir))
    turns_map: dict[int, dict[str, Any]] = {}

    for f in files:
        if not f.endswith(".json"):
            continue

        seq_id, f_type, timestamp = parse_file_info(f)
        if seq_id is None:
            continue

        if seq_id not in turns_map:
            turns_map[seq_id] = {
                "seq_id": seq_id,
                "ts": timestamp,
                "req": None,
                "res": None,
                "req_file": None,
                "res_file": None,
            }

        # Read content
        file_path = target_dir / f
        try:
            with open(file_path, encoding="utf-8") as fp:
                content = json.load(fp)
        except Exception as e:
            content = {"error": f"JSON Decode Fail: {str(e)}"}

        if f_type == "request":
            turns_map[seq_id]["req"] = content
            turns_map[seq_id]["req_file"] = f
        elif f_type == "response":
            turns_map[seq_id]["res"] = content
            turns_map[seq_id]["res_file"] = f

    # Convert to list and sort
    sorted_turns = sorted(turns_map.values(), key=lambda x: x["seq_id"])

    # --- Context Analysis Logic ---
    last_ctx_len = 0
    last_sys_prompt = ""

    for i, turn in enumerate(sorted_turns):
        req = turn["req"] or {}
        msgs = req.get("messages", [])

        # 1. Extract current features
        current_ctx_len = len(msgs)

        # Extract System Prompt Fingerprint (first 50 chars)
        current_sys_prompt = "No System"
        if msgs and msgs[0].get("role") == "system":
            content = msgs[0].get("content", "")
            if isinstance(content, str):
                current_sys_prompt = content[:50]
            elif isinstance(content, list):
                # Handle list content for system prompt if applicable
                current_sys_prompt = "[Complex System Prompt]"
            else:
                current_sys_prompt = str(content)[:50]

        # 2. Detect Context Switch (Heuristics)
        is_switch = False
        switch_reason = ""

        if i > 0:  # Skip first
            if current_sys_prompt != last_sys_prompt:
                is_switch = True
                switch_reason = "System Prompt Changed"
            elif current_ctx_len < last_ctx_len:
                is_switch = True
                switch_reason = "Context Reset"

        turn["is_switch"] = is_switch
        turn["switch_reason"] = switch_reason
        turn["ctx_len"] = current_ctx_len
        turn["sys_preview"] = current_sys_prompt

        # Extract last user message for display
        last_user_msg = "No User Input"
        for m in reversed(msgs):
            if m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, list):
                    # Try to extract text from list if possible
                    text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                    if text_parts:
                        last_user_msg = " ".join(text_parts)
                    else:
                        last_user_msg = "[Complex/Image Input]"
                else:
                    last_user_msg = content
                break
        turn["last_user_msg"] = last_user_msg

        # Update state
        last_ctx_len = current_ctx_len
        last_sys_prompt = current_sys_prompt

    return sorted_turns


# ================= 2. UI Rendering =================


def main():
    # Sidebar Styling
    with st.sidebar:
        st.title("🔍 LLM Interceptor")
        st.markdown("---")

        if not BASE_DIR.exists():
            st.error(f"Traces directory not found: {BASE_DIR}")
            st.info("Please ensure you are running this from the project root.")
            return

        # Scan for session directories (directories containing 'split_output' or .json files)
        sessions = []
        for d in sorted(os.listdir(BASE_DIR)):
            path = BASE_DIR / d
            if path.is_dir():
                sessions.append(d)

        sessions = sorted(sessions, reverse=True)  # Newest first

        selected_session_name = st.selectbox("Select Session", sessions)

        st.markdown("### Filters")
        filter_hide_short = st.checkbox(
            "Hide Background Tasks",
            value=False,
            help="Hide tasks with history < 2 messages (often internal calls)",
        )

        search_query = st.text_input("Keyword Search", placeholder="Search content...")

    if not selected_session_name:
        st.info("👈 Please select a session from the sidebar.")
        return

    session_path = BASE_DIR / selected_session_name

    # Load Data
    with st.spinner(f"Loading session {selected_session_name}..."):
        turns = load_session_turns(session_path)

    # Metrics
    st.sidebar.markdown("---")
    st.sidebar.metric("Total API Calls", len(turns))

    if not turns:
        st.warning("No request/response pairs found in this session.")
        return

    # Header
    st.title(f"Session: {selected_session_name}")
    st.caption(f"Path: `{session_path}`")
    st.markdown("---")

    # Main Feed
    displayed_count = 0

    for turn in turns:
        # --- Filters ---
        if filter_hide_short and turn["ctx_len"] < 2:
            continue

        if search_query:
            # Simple case-insensitive search in user msg and response
            query = search_query.lower()
            req_match = query in str(turn["last_user_msg"]).lower()

            res_text = ""
            if turn["res"]:
                try:
                    if "choices" in turn["res"]:
                        res_text = turn["res"]["choices"][0]["message"]["content"]
                    elif "content" in turn["res"]:
                        # Handle Anthropic format
                        res_text = turn["res"]["content"][0]["text"]
                except Exception:
                    pass

            res_match = query in str(res_text).lower()

            if not (req_match or res_match):
                continue

        displayed_count += 1

        # --- Context Switch Separator ---
        if turn.get("is_switch"):
            switch_reason = turn["switch_reason"]
            st.markdown(
                f"""
            <div style="text-align: center; color: #f97316; margin: 30px 0 20px 0;
                        display: flex; align-items: center; justify-content: center; gap: 10px;">
                <span style="font-size: 1.2em;">⚡</span>
                <span style="font-weight: 600;">New Context Detected</span>
                <span style="background: #fff7ed; color: #c2410c;
                            padding: 2px 8px; border-radius: 12px;
                            font-size: 0.8em;">{switch_reason}</span>
            </div>
            <hr style="border: 0; border-top: 2px dashed #fdba74; margin-bottom: 30px;">
            """,
                unsafe_allow_html=True,
            )

        # --- Card Component ---
        req = turn["req"]
        res = turn["res"]
        model = req.get("model", "unknown") if req else "unknown"

        # Card Container with custom styling
        with st.container():
            # Meta Header
            cols = st.columns([4, 1])
            with cols[0]:
                st.caption(
                    f"**#{turn['seq_id']}** | 🕒 {turn['ts']} | 🤖 **{model}** | "
                    f"📚 History: `{turn['ctx_len']}` | 🎯 Intent: `{turn['sys_preview']}...`"
                )

            # Content Grid
            c1, c2 = st.columns([1, 1])

            # LEFT: Request
            with c1:
                st.markdown("**User Input**")
                st.info(turn["last_user_msg"], icon="👤")

                with st.popover("📄 Full Request JSON", use_container_width=True):
                    st.json(req)

            # RIGHT: Response
            with c2:
                st.markdown("**AI Response**")
                if res:
                    # Parse AI Content
                    ai_content = "No content"
                    try:
                        if "choices" in res:  # OpenAI format
                            ai_content = res["choices"][0]["message"]["content"]
                        elif "content" in res:  # Anthropic format
                            content_block = res["content"]
                            if isinstance(content_block, list) and len(content_block) > 0:
                                ai_content = content_block[0].get("text", "")
                            elif isinstance(content_block, str):
                                ai_content = content_block
                    except Exception as e:
                        ai_content = f"Error parsing content: {e}"

                    # Check for error in response
                    if "error" in res:
                        st.error(f"API Error: {res['error']}")
                    else:
                        st.markdown(ai_content)

                    with st.expander("🛠 Raw Response"):
                        st.json(res)
                else:
                    st.warning("⚠️ No Response Captured", icon="⚠️")

            st.divider()

    if displayed_count == 0:
        st.info("No messages match current filters.")


if __name__ == "__main__":
    main()

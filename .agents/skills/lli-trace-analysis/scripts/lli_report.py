#!/usr/bin/env python3
"""Summarize LLM Interceptor (lli) capture sessions.

Usage:
  python3 lli_report.py TRACES_DIR            summarize every session
  python3 lli_report.py SESSION_DIR           per-exchange detail for one session
  python3 lli_report.py PATH --format json    machine-readable output

Works on plain trace files only (standard library, no lli import needed).
Supports Anthropic Messages, OpenAI Chat Completions, and OpenAI Responses
capture formats.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REQ_RE = re.compile(r"^(\d{3})_request_.+\.json$")
RESP_RE = re.compile(r"^(\d{3})_response_.+\.json$")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: skipping {path.name}: {exc}", file=sys.stderr)
        return None


def detect_format(url: str, body: dict[str, Any]) -> str:
    if isinstance(body, dict):
        if "/responses" in url:
            return "openai_responses"
        if "input" in body and "messages" not in body:
            return "openai_responses"
        if "candidates" in body or "usageMetadata" in body or "contents" in body:
            return "gemini"
        tools = body.get("tools") or []
        if tools and isinstance(tools[0], dict):
            if "function" in tools[0]:
                return "openai_chat"
            if "input_schema" in tools[0]:
                return "anthropic"
        if "system" in body:
            return "anthropic"
        for message in body.get("messages") or []:
            if isinstance(message, dict) and message.get("role") in (
                "system",
                "developer",
                "tool",
            ):
                return "openai_chat"
    if "/chat/completions" in url:
        return "openai_chat"
    return "anthropic"


def normalize_usage(body: dict[str, Any], fmt: str) -> dict[str, int]:
    u = body.get("usage") or body.get("usageMetadata") or {}
    if not isinstance(u, dict):
        u = {}

    def pick(*keys: str) -> int | None:
        for key in keys:
            value = u.get(key)
            if isinstance(value, int):
                return value
        return None

    inp = pick("input_tokens", "prompt_tokens", "promptTokenCount")
    out = pick("output_tokens", "completion_tokens", "candidatesTokenCount")
    cache_read = pick("cache_read_input_tokens", "cachedContentTokenCount")
    details = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    if cache_read is None and isinstance(details, dict):
        cached = details.get("cached_tokens")
        if isinstance(cached, int):
            cache_read = cached
    cache_create = pick("cache_creation_input_tokens")
    cache_read = cache_read or 0
    cache_create = cache_create or 0
    inp = inp or 0
    out = out or 0
    if fmt == "anthropic":
        total = inp + out + cache_read + cache_create
        cache_subset = False
    else:
        total = inp + out
        cache_subset = True
    return {
        "input": inp,
        "output": out,
        "cache_read": cache_read,
        "cache_create": cache_create,
        "total": total,
        "cache_is_subset_of_input": cache_subset,
    }


def extract_tool_calls(body: dict[str, Any], fmt: str) -> list[str]:
    calls: list[str] = []
    if not isinstance(body, dict):
        return calls
    if fmt == "anthropic":
        for block in body.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append(str(block.get("name")))
    elif fmt == "openai_chat":
        for choice in body.get("choices") or []:
            message = choice.get("message") if isinstance(choice, dict) else None
            for call in (message or {}).get("tool_calls") or []:
                if isinstance(call, dict):
                    name = (call.get("function") or {}).get("name")
                    if name:
                        calls.append(str(name))
    elif fmt == "openai_responses":
        for item in body.get("output") or []:
            if isinstance(item, dict) and item.get("type") == "function_call":
                calls.append(str(item.get("name")))
    return calls


def terminal_reason(body: dict[str, Any], fmt: str) -> str | None:
    if not isinstance(body, dict):
        return None
    if fmt == "anthropic":
        return body.get("stop_reason")
    if fmt == "openai_chat":
        reasons = [c.get("finish_reason") for c in body.get("choices") or []]
        return next((r for r in reasons if r), None)
    if fmt == "openai_responses":
        return body.get("status")
    return None


def parse_session(session_dir: Path) -> dict[str, Any]:
    requests: dict[str, dict[str, Any]] = {}
    responses: dict[str, dict[str, Any]] = {}
    for entry in sorted(session_dir.iterdir()):
        req_match = REQ_RE.match(entry.name)
        resp_match = RESP_RE.match(entry.name)
        if req_match:
            data = load_json(entry)
            if data is not None:
                requests[req_match.group(1)] = data
        elif resp_match:
            data = load_json(entry)
            if data is not None:
                responses[resp_match.group(1)] = data

    run_meta = None
    meta_path = session_dir / "run_meta.json"
    if meta_path.exists():
        loaded = load_json(meta_path)
        if isinstance(loaded, dict):
            run_meta = loaded

    exchanges = []
    totals = {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_create": 0,
        "total": 0,
        "latency_ms": 0.0,
    }
    models: list[str] = []
    formats: dict[str, int] = {}
    failed = 0
    orphan = 0

    for seq in sorted(requests):
        req = requests[seq]
        resp = responses.get(seq)
        url = str(req.get("url") or "")
        body = req.get("body") if isinstance(req.get("body"), dict) else {}
        fmt = detect_format(url, body)
        model = body.get("model") or (resp or {}).get("body", {}).get("model")
        status = resp.get("status_code") if resp else None
        latency = resp.get("latency_ms") if resp else None
        resp_body = resp.get("body") if resp and isinstance(resp.get("body"), dict) else {}
        if not resp:
            orphan += 1
        elif isinstance(status, int) and status >= 400:
            failed += 1
        usage = normalize_usage(resp_body, fmt) if resp else None
        tools = extract_tool_calls(resp_body, fmt) if resp else []
        reason = terminal_reason(resp_body, fmt) if resp else None
        resp_model = resp_body.get("model")
        model_note = ""
        if resp_model and model and resp_model != model:
            model_note = f"response reports {resp_model}"
        if usage:
            for key in totals:
                if key == "latency_ms":
                    continue
                totals[key] += usage[key]
        if isinstance(latency, (int, float)):
            totals["latency_ms"] += float(latency)
        if model and model not in models:
            models.append(str(model))
        formats[fmt] = formats.get(fmt, 0) + 1
        exchanges.append(
            {
                "seq": seq,
                "format": fmt,
                "model": model,
                "model_note": model_note or None,
                "status_code": status,
                "latency_ms": latency,
                "usage": usage,
                "tool_calls": tools,
                "stop_reason": reason,
                "has_response": resp is not None,
            }
        )

    return {
        "session": session_dir.name,
        "kind": "run" if run_meta else "watch",
        "label": (run_meta or {}).get("label"),
        "command": (run_meta or {}).get("command"),
        "exit_code": (run_meta or {}).get("exit_code"),
        "duration_seconds": (run_meta or {}).get("duration_seconds"),
        "n_exchanges": len(exchanges),
        "n_failed": failed,
        "n_orphan": orphan,
        "models": models,
        "formats": formats,
        "totals": totals,
        "exchanges": exchanges,
    }


def find_session_dirs(root: Path) -> list[Path]:
    dirs = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and any(REQ_RE.match(f.name) for f in entry.iterdir()):
            dirs.append(entry)
    return dirs


def fmt_num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def render_markdown(sessions: list[dict[str, Any]], detailed: bool) -> str:
    lines: list[str] = []
    lines.append("# LLI trace report")
    lines.append("")
    lines.append("## Sessions")
    lines.append("")
    header = (
        "| Session | Kind | Label/Command | Exchanges | Failed | Orphan | Model(s) | "
        "Format(s) | In | Out | Cache R | Cache W | Total tok | Latency (ms) |"
    )
    lines.append(header)
    lines.append("|" + "---|" * 13)
    for s in sessions:
        ident = s["label"] or " ".join(map(str, s["command"] or [])) or "-"
        lines.append(
            "| {session} | {kind} | {ident} | {n} | {failed} | {orphan} | {models} | "
            "{formats} | {i} | {o} | {cr} | {cw} | {t} | {lat} |".format(
                session=s["session"],
                kind=s["kind"],
                ident=ident,
                n=s["n_exchanges"],
                failed=s["n_failed"],
                orphan=s["n_orphan"],
                models=", ".join(s["models"]) or "-",
                formats=", ".join(f"{k}x{v}" for k, v in s["formats"].items()),
                i=fmt_num(s["totals"]["input"]),
                o=fmt_num(s["totals"]["output"]),
                cr=fmt_num(s["totals"]["cache_read"]),
                cw=fmt_num(s["totals"]["cache_create"]),
                t=fmt_num(s["totals"]["total"]),
                lat=fmt_num(s["totals"]["latency_ms"]),
            )
        )
    lines.append("")
    lines.append(
        "Cache R = cache-read tokens, Cache W = cache-creation tokens. "
        "For Anthropic they are *added* into Total; for OpenAI formats "
        "cache-read is a subset of In (already included)."
    )
    run_lines = [
        "- `{}`: exit_code={}, duration={}s".format(
            s["session"], s["exit_code"], fmt_num(s["duration_seconds"])
        )
        for s in sessions
        if s["kind"] == "run"
    ]
    if run_lines:
        lines.append("")
        lines.append("Run session details:")
        lines.extend(run_lines)
    if detailed:
        for s in sessions:
            lines.append("")
            lines.append("## Session {} — exchanges".format(s["session"]))
            lines.append("")
            lines.append(
                "| Seq | Format | Model | Status | Stop | Latency (ms) | "
                "In | Out | Cache R | Cache W | Tool calls | Note |"
            )
            lines.append("|" + "---|" * 12)
            for e in s["exchanges"]:
                usage = e["usage"] or {}
                note = e["model_note"] or ("orphan request" if not e["has_response"] else "")
                lines.append(
                    "| {seq} | {fmt} | {model} | {status} | {stop} | {lat} | {i} | {o} | "
                    "{cr} | {cw} | {tools} | {note} |".format(
                        seq=e["seq"],
                        fmt=e["format"],
                        model=e["model"] or "-",
                        status=e["status_code"] if e["status_code"] is not None else "n/a",
                        stop=e["stop_reason"] or "-",
                        lat=fmt_num(e["latency_ms"]),
                        i=fmt_num(usage.get("input")),
                        o=fmt_num(usage.get("output")),
                        cr=fmt_num(usage.get("cache_read")),
                        cw=fmt_num(usage.get("cache_create")),
                        tools=", ".join(e["tool_calls"]) or "-",
                        note=note,
                    )
                )
    gemini = [s for s in sessions if "gemini" in s["formats"]]
    if gemini:
        lines.append("")
        lines.append(
            "WARNING: Gemini-format captures found. LLI does not rebuild Gemini "
            "streaming bodies; totals above may be incomplete — consult the raw "
            "all_captured_*.jsonl response_chunk records."
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize LLI (LLM Interceptor) trace sessions.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", help="traces root directory or a single session directory")
    parser.add_argument("--format", choices=["md", "json"], default="md")
    parser.add_argument(
        "--exchanges",
        action="store_true",
        help="include per-exchange tables when summarizing a traces root",
    )
    args = parser.parse_args()

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1

    if any(REQ_RE.match(f.name) for f in root.iterdir()):
        session_dirs = [root]
        detailed = True
    else:
        session_dirs = find_session_dirs(root)
        detailed = args.exchanges

    if not session_dirs:
        print(f"error: no LLI sessions found under {root}", file=sys.stderr)
        return 2

    sessions = [parse_session(d) for d in session_dirs]

    if args.format == "json":
        print(json.dumps(sessions, indent=2))
    else:
        sys.stdout.write(render_markdown(sessions, detailed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

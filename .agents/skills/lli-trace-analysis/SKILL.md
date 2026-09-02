---
name: lli-trace-analysis
description: Analyze LLM traffic captures and agent traces produced by LLM Interceptor (lli). Use this skill whenever the user mentions lli, LLI traces, traces/ directories with session_* subdirectories, all_captured_*.jsonl, run_meta.json, captured LLM API traffic, or wants token usage / latency / tool-call statistics for AI agent runs, wants to compare how different coding agents (Claude Code, Codex, OpenCode, Cursor) behaved on the same task, wants to extract prompts/responses/tool calls from captured sessions, or wants to record an agent run with `lli run` to inspect what the agent actually sent to its LLM. Covers Anthropic Messages, OpenAI Chat Completions, and OpenAI Responses API capture formats, plus lli installation and capture setup when lli is not yet installed.
license: MIT
compatibility: opencode
---

# LLI Trace Analysis

Analyze (and optionally capture) LLM API traffic recorded by [LLM Interceptor](https://github.com/chouzz/llm-interceptor) (lli) — a proxy that sits between AI coding agents (Claude Code, Codex, OpenCode, ...) and their LLM APIs and writes every request/response pair to disk as plain JSON.

## When to use this skill

- A `traces/` directory (or any dir) contains `session_*` folders, `NNN_request_*.json` / `NNN_response_*.json` pairs, `all_captured_*.jsonl`, `run_meta.json`, or `session_meta.json`
- The user asks about token usage, latency, tool calls, models, prompts, or errors in captured agent traffic
- The user wants to compare agents (e.g. "how many tokens did claude vs codex burn on this task?")
- The user wants to record a new experiment: `lli run -- claude -p "..."` and then analyze it

## Prerequisites (load lazily — do not require upfront)

1. **Analyzing existing traces → zero dependencies.** Traces are plain JSON files. Use the bundled `scripts/lli_report.py` (Python 3.9+, standard library only — it never imports the `lli` package). This works even when lli is not installed, e.g. when a colleague sent you a traces directory.
2. **Capturing new traffic → lli must be installed.** Check with `command -v lli`. If missing:
   ```bash
   uv tool install llm-interceptor   # or: pip install llm-interceptor
   ```
   - `lli run` (recommended for experiments) works out of the box: the mitmproxy CA at `~/.mitmproxy/mitmproxy-ca-cert.pem` is generated automatically on first proxy start, and CA trust is injected into the captured child process — **no system-wide certificate installation needed**.
   - Only `lli watch` (interactive continuous HTTPS capture) needs the CA installed system-wide; prefer `lli run` unless the user explicitly wants watch mode.

## Artifact layout

```
traces/                                       # default output dir (configurable via -o)
├── all_captured_YYYYMMDD_HHMMSS_ffffff.jsonl # raw global log (ground truth, replayable)
├── session_YYYYMMDD_HHMMSS_ffffff/           # one folder per capture session
│   ├── session_meta.json                     # {session_id, started_at, ended_at}
│   ├── run_meta.json                         # ONLY in `lli run` sessions:
│   │                                         #   {command, label, exit_code, duration_seconds, ...}
│   ├── 001_request_YYYY-MM-DD_HH-MM-SS.json
│   ├── 001_response_YYYY-MM-DD_HH-MM-SS.json # pairs share the NNN index
│   └── ...
```

- `run_meta.json` present ⇒ this session came from `lli run` (read it for the wrapped command, label, exit code). Its `label` is the natural key when comparing experiments.
- Request/response correlation: `request.id == response.request_id`, plus the shared `NNN` prefix. A request file with no response file is an **orphan request** (interrupted or in-flight when capture stopped).
- Sessions are found under `traces/` by default; if the user gives a custom path, trust it. To enumerate run sessions programmatically: `ls traces/session_*/run_meta.json`.

## Core workflow

### Step 1 — Get the overview with the bundled script

```bash
python3 <skill-dir>/scripts/lli_report.py traces/            # summarize every session
python3 <skill-dir>/scripts/lli_report.py traces/session_X/  # per-exchange detail for one session
python3 <skill-dir>/scripts/lli_report.py traces/ --format json   # machine-readable
```

It normalizes across all three API formats and reports: model (from the request), input/output/cache tokens, latency, tool-call names, stop reason, and failed/orphan requests. Prefer this over hand-written jq for anything aggregate — it encodes the canonical usage normalization from lli's own UI backend.

### Step 2 — Identify the API format before digging by hand

Same concepts, different JSON shapes per provider. Quick decision tree (request URL is the strongest signal):

- URL contains `/responses` **or** body has top-level `input` + `instructions`/`max_output_tokens` → **OpenAI Responses API**
- Body has `messages` AND a top-level `system` field → **Anthropic Messages**
- Body has `messages` with `role: "system"`/`"developer"` inside the array, or `tools[].function` wrappers → **OpenAI Chat Completions**
- Response body has `choices` → OpenAI Chat; `output` array + `status` → Responses; `content` array + `stop_reason` → Anthropic

### Step 3 — Extract precise fields

Read `references/provider-formats.md` for the full per-format JSON path tables (tokens, tool calls, system prompts, stop reasons, streaming internals) with ready-made jq snippets. **Do not load whole request JSON files into context** — a single capture can carry the agent's entire system prompt (tens of KB). Use jq/python one-liners to project only the fields you need, e.g.:

```bash
jq -c '{model: .body.model, tools: [.body.tools[]?.name]}' traces/session_X/001_request_*.json
```

### Step 4 (optional) — Capture new experiments

```bash
lli run --label my-experiment -- claude -p "fix the failing test"
lli run --label codex-a -- codex exec "review src/"
```

- `lli` exits with the child's exit code → composes with scripts/CI
- After the run, the session lands in `traces/session_*/` with `run_meta.json`; analyze it with Step 1
- Batch-compare agents on the same tasks by giving each run a distinct `--label`
- Byte-level truth (per-chunk streaming, truncation) lives in the raw log `all_captured_*.jsonl` — see the reference for its record types

## Pitfalls (bit regularly — read once)

1. **Tool-call arguments type differs**: Anthropic `tool_use.input` is an already-parsed object; OpenAI formats' `function.arguments` is a **JSON string** needing a second `json.loads`.
2. **Response model can differ from request model** (e.g. provider upgrade mid-request). Report the request's `body.model` as authoritative; note discrepancies.
3. **Streaming responses are reconstructions**: rebuilt bodies drop headers and `_session_id`; a truncated stream yields partial text. For per-chunk truth use `response_chunk` records in the raw JSONL — and ignore their `_event_type` field, it is off-by-one relative to the wire; use `content.type` instead.
4. **Masked ≠ safe**: `Authorization` / `x-api-key` headers are partially masked and may contain key fragments after punctuation. Never republish them.
5. **Usage fields differ per format** (`input_tokens` vs `prompt_tokens` vs nested `*_details`); never sum raw fields across formats — that's what `lli_report.py` normalizes.
6. **Non-LLI JSON**: the tool only captures known LLM API endpoints (Anthropic/OpenAI/Google/etc. + `--include` patterns). Other traffic is absent by design.

## Web UI alternative

If a human wants to browse sessions visually, `lli serve` (default http://127.0.0.1:48080) shows all sessions with search/filter. The UI reads the same files — mention it when the user seems to want interactive exploration rather than scripted analysis.

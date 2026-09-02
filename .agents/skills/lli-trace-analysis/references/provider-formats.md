# LLI Capture Formats Reference

Field-path reference for the three LLM API formats LLI captures, plus the raw
JSONL record formats. Read the section for the format you identified — not the
whole file.

**Terminology**: "format" = the wire API dialect of a captured exchange
(Anthropic Messages, OpenAI Chat Completions, OpenAI Responses). LLI preserves
each request/response `body` verbatim (non-streaming) or rebuilds it from SSE
chunks (streaming), so field paths match each provider's official API schema.

## Table of contents

- [Format identification](#format-identification)
- [Anthropic Messages format](#anthropic-messages-format)
- [OpenAI Chat Completions format](#openai-chat-completions-format)
- [OpenAI Responses format](#openai-responses-format)
- [Raw JSONL record formats](#raw-jsonl-record-formats)
- [Gotchas checklist](#gotchas-checklist)

---

## Format identification

The request URL is the strongest signal; fall back to body shape.

| Signal | Format |
|---|---|
| URL path contains `/responses` | OpenAI Responses |
| Request body: top-level `input`, `instructions`, and/or `max_output_tokens`, no `messages` | OpenAI Responses |
| Request body: `messages` + top-level `system` (string or blocks) | Anthropic Messages |
| Request body: `messages` with `{"role": "system"\|"developer"}` entries inside the array | OpenAI Chat Completions |
| Request `tools[]` shaped `{name, description, input_schema}` | Anthropic Messages |
| Request `tools[]` shaped `{type: "function", function: {...}}` (Chat) or flat `{type: "function", name, parameters}` (Responses) | OpenAI |
| Response body has `choices` | OpenAI Chat Completions |
| Response body has `output` array + `status` | OpenAI Responses |
| Response body has `content` array + `stop_reason` | Anthropic Messages |
| Response body has `candidates` / `usageMetadata` | **Gemini — not rebuilt by LLI's merger;** non-streaming bodies are verbatim, streaming rebuilds are lossy. Use the raw JSONL chunks (see below). |

Note: Anthropic-compatible proxy endpoints (e.g. `open.bigmodel.cn/api/anthropic/...`)
speak the Anthropic Messages format regardless of the host.

---

## Anthropic Messages format

Typical URL: `.../v1/messages`.

### Request `body`

| What | Path | Notes |
|---|---|---|
| Model | `body.model` | e.g. `claude-sonnet-4-...`, `glm-5.2` on compat proxies |
| Conversation | `body.messages[]` | `role` user/assistant; `content` is a string or block array |
| Content blocks | `body.messages[].content[]` | `type`: `text`, `tool_use` (assistant), `tool_result` (user), `thinking` |
| System prompt | `body.system` | string or `[{type: "text", text, cache_control}]` |
| Tools offered | `body.tools[].name` | definitions `{name, description, input_schema}` |
| Max tokens | `body.max_tokens` | |
| Extended thinking | `body.thinking` | config, e.g. `{type: "enabled", budget_tokens: ...}` |
| Streaming flag | `body.stream` | |

```bash
# system prompt text (both shapes)
jq -r 'if (.body.system|type)=="string" then .body.system
       else ([.body.system[]?.text]|join("\n")) end' NNN_request_*.json

# tool names offered
jq -c '[.body.tools[]?.name]' NNN_request_*.json
```

### Response `body`

| What | Path | Notes |
|---|---|---|
| Assistant text | `body.content[] \| select(.type=="text") \| .text` | |
| Thinking | `body.content[] \| select(.type=="thinking") \| .thinking` | |
| Tool calls | `body.content[] \| select(.type=="tool_use")` | `{id, name, input}` — **`input` is already a parsed object** |
| Stop reason | `body.stop_reason` | `end_turn`, `tool_use`, `max_tokens`, ... |
| Input tokens | `body.usage.input_tokens` | |
| Output tokens | `body.usage.output_tokens` | |
| Cache read | `body.usage.cache_read_input_tokens` | |
| Cache creation | `body.usage.cache_creation_input_tokens` | |
| Response model | `body.model` | **can differ from the request's** (e.g. request `glm-5.2` → response `glm-5.3`) |

```bash
jq -c '{model: .body.model, stop: .body.stop_reason,
        usage: .body.usage}' NNN_response_*.json

jq -c '.body.content[]? | select(.type=="tool_use") | {name, input}' NNN_response_*.json
```

Token math: `input_tokens` **excludes** cached tokens. Effective context ≈
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens`; total
billed work ≈ that plus `output_tokens`.

---

## OpenAI Chat Completions format

Typical URL: `.../v1/chat/completions`.

### Request `body`

| What | Path | Notes |
|---|---|---|
| Model | `body.model` | |
| Conversation | `body.messages[]` | roles: system, developer, user, assistant, tool |
| System prompt | `body.messages[] \| select(.role=="system"\|"developer") \| .content` | |
| Tools offered | `body.tools[].function.name` | wrappers `{type:"function", function:{name, description, parameters}}` |
| Tool call history | `body.messages[].tool_calls[]` | prior assistant turns: `{id, function:{name, arguments}}` |
| Tool results | `body.messages[] \| select(.role=="tool")` | `{tool_call_id, content}` |

```bash
jq -r '[.body.messages[]? | select(.role=="system" or .role=="developer") | .content] | join("\n\n")' NNN_request_*.json
```

### Response `body`

| What | Path | Notes |
|---|---|---|
| Message | `body.choices[N].message` | |
| Assistant text | `body.choices[N].message.content` | |
| Tool calls | `body.choices[N].message.tool_calls[M]` | `{id, function:{name, arguments}}` — **`arguments` is a JSON *string*** |
| Stop reason | `body.choices[N].finish_reason` | `stop`, `tool_calls`, `length`, ... |
| Input tokens | `body.usage.prompt_tokens` | |
| Output tokens | `body.usage.completion_tokens` | |
| Cached subset | `body.usage.prompt_tokens_details.cached_tokens` | subset **of** `prompt_tokens` (do not add) |
| Response id | `body.id` | `body.object == "chat.completion"` for non-streaming |

```bash
jq -c '{model: .body.model,
        finish: .body.choices[0].finish_reason,
        usage: .body.usage}' NNN_response_*.json

# tool calls with parsed arguments
jq -c '.body.choices[0].message.tool_calls[]? |
       {name: .function.name, args: (.function.arguments | fromjson?)}' NNN_response_*.json
```

Token math: `prompt_tokens` **already includes** cached tokens. Total = `prompt_tokens + completion_tokens`.

---

## OpenAI Responses format

Typical URL: `.../v1/responses`. Used by Codex-class agents.

### Request `body`

| What | Path | Notes |
|---|---|---|
| Model | `body.model` | |
| Prompt items | `body.input` | string or typed item array |
| Input message | `body.input[] \| select(.type=="message")` | `{role, content:[{type:"input_text"\|"output_text", text}]}` |
| Tool call history | `body.input[] \| select(.type=="function_call")` | `{call_id, name, arguments}` (arguments = JSON string) |
| Tool results | `body.input[] \| select(.type=="function_call_output")` | `{call_id, output}` |
| Reasoning items | `body.input[] \| select(.type=="reasoning")` | |
| System prompt | `body.instructions` | top-level string |
| Tools offered | `body.tools[].name` | **flat** shape: `{type:"function", name, parameters, description}` |
| Max tokens | `body.max_output_tokens` | |

```bash
jq -r '.body.instructions' NNN_request_*.json
jq -c '[.body.tools[]?.name]' NNN_request_*.json
```

### Response `body`

| What | Path | Notes |
|---|---|---|
| Output items | `body.output[]` | typed items, order preserved |
| Assistant text | `body.output[] \| select(.type=="message")` | `.content[] \| select(.type=="output_text") \| .text` |
| Reasoning | `body.output[] \| select(.type=="reasoning")` | `.summary[]` parts |
| Tool calls | `body.output[] \| select(.type=="function_call")` | `{id, call_id, name, arguments}` — **arguments = JSON string** |
| Status | `body.status` | `completed`, `in_progress`, `failed`, `incomplete` |
| Incomplete why | `body.incomplete_details` | e.g. `{"reason": "max_output_tokens"}` |
| Error | `body.error` | |
| Input tokens | `body.usage.input_tokens` | |
| Output tokens | `body.usage.output_tokens` | |
| Cached subset | `body.usage.input_tokens_details.cached_tokens` | subset **of** `input_tokens` (do not add) |

```bash
jq -c '{model: .body.model, status: .body.status, usage: .body.usage}' NNN_response_*.json
jq -c '.body.output[]? | select(.type=="function_call") |
       {name, args: (.arguments | fromjson?)}' NNN_response_*.json
```

---

## Raw JSONL record formats

`all_captured_*.jsonl` (traces root) and per-session `raw.jsonl` (older LLI
versions) contain one compact JSON object per line. Data records carry a
prepended `_session_id`. Control frames `{"_meta_type": "session_start"|
"session_end"|"session_cancelled", ...}` bracket sessions.

| `type` | When | Key fields |
|---|---|---|
| `request` | every captured request | `id`, `timestamp`, `method`, `url`, `headers` (masked), `body` |
| `response_chunk` | streaming only, one line per SSE event | `request_id`, `chunk_index`, `content` (parsed SSE payload; `[DONE]` → `{"done": true}`) |
| `response_meta` | end of a streaming response | `request_id`, `total_latency_ms`, `status_code`, `total_chunks`, `error?` |
| `response` | non-streaming only | `request_id`, `status_code`, `headers`, `body` (verbatim), `latency_ms` |

```bash
# replay one streaming response's text (Anthropic example) from the raw log
jq -r 'select(.type=="response_chunk" and .request_id=="<id>")
       | .content | select(.type=="content_block_delta")
       | .delta | select(.type=="text_delta") | .text' all_captured_*.jsonl

# correlate: list request ids + urls + latencies
jq -rc 'select(.type=="request") | {id, url}' all_captured_*.jsonl
jq -rc 'select(.type=="response_meta") | {request_id, total_latency_ms, status_code}' all_captured_*.jsonl
```

Chunk `content.type` values: Anthropic `message_start` / `content_block_start` /
`content_block_delta` / `content_block_stop` / `message_delta` (final
`stop_reason` + cumulative `usage`) / `message_stop` / `ping`; OpenAI Chat raw
chunks carry top-level `choices[].delta`; Responses events are named
`response.*` (e.g. `response.output_text.delta`,
`response.function_call_arguments.delta`, `response.completed`).

---

## Gotchas checklist

- [ ] **`_event_type` in raw chunks is off-by-one** (LLI attaches the next SSE
      `event:` line to the previous payload). Always branch on `content.type`.
- [ ] **Streaming response files are reconstructions**: no `headers`, no
      `_session_id`; truncated streams end mid-text with partial tool args.
      Non-streaming response files are verbatim.
- [ ] **Orphan requests** (request file, no response file) mean the capture
      stopped mid-flight or the request failed at the transport layer — check
      `response_meta.error` in the raw log.
- [ ] **Masking is partial**: masked auth headers can retain fragments after
      punctuation (`Bearer ***MASKED***.EWWCfjloPL1Xv...`). Treat as sensitive.
- [ ] **Don't sum tokens across formats** without normalization:
      Anthropic `input_tokens` excludes cache; OpenAI `prompt_tokens` /
      `input_tokens` include it. Use `scripts/lli_report.py` for aggregation.
- [ ] **Response `body.model` may differ from request** — report the request's.
- [ ] Non-JSON request bodies degrade to strings / `"<binary content: N bytes>"`
      / `"<parse error: ...>"` in `body`.

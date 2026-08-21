import type {
  ExchangeDetail,
  NormalizedExchange,
  NormalizedMessage,
  NormalizedTool,
  RawRequest,
  RawResponse,
  Session,
  SessionOverview,
  RequestResponsePair,
} from './types';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

/**
 * Detects if the request body follows OpenAI structure.
 */
const isOpenAIFormat = (body: unknown): boolean => {
  if (!isRecord(body)) return false;

  // Check for OpenAI specific tool format
  const tools = body.tools;
  if (
    Array.isArray(tools) &&
    tools.some((t) => isRecord(t) && t.type === 'function')
  ) {
    return true;
  }

  // Check for OpenAI specific message roles or properties
  const messages = body.messages;
  if (
    Array.isArray(messages) &&
    messages.some(
      (m) =>
        isRecord(m) &&
        (m.role === 'tool' || m.role === 'developer' || 'tool_calls' in m)
    )
  ) {
    return true;
  }

  // If system is strictly in messages and not at top level (Anthropic uses top level system usually)
  if (!('system' in body) && Array.isArray(messages) && messages.some((m) => isRecord(m) && m.role === 'system')) {
    return true;
  }

  return false;
};

const RESPONSES_URL_RE = /\/responses(?:\/|\?|#|$)/;

/**
 * Detects if the request body follows the OpenAI Responses API structure
 * (prompt carried in `input` instead of `messages`).
 *
 * When the request URL is available it takes priority: embeddings requests
 * also carry a top-level `input` without `messages` and must not be treated
 * as Responses chat payloads. Without a URL, fall back to body heuristics
 * that require Responses-specific fields beyond a bare `input`.
 */
const isOpenAIResponsesFormat = (body: unknown, url?: string): boolean => {
  if (typeof url === 'string' && url) {
    return RESPONSES_URL_RE.test(url);
  }
  if (!isRecord(body)) return false;
  if (!('input' in body) || 'messages' in body) return false;
  if (typeof body.input !== 'string' && !Array.isArray(body.input)) return false;
  return (
    typeof body.instructions === 'string' ||
    'previous_response_id' in body ||
    'max_output_tokens' in body
  );
};

/**
 * Normalizes provider-specific token usage stats into {input_tokens, output_tokens}.
 */
const normalizeUsageMetrics = (rawUsage: unknown) => {
  if (!isRecord(rawUsage)) return undefined;

  const safeNumber = (value: unknown): number | undefined =>
    typeof value === 'number' && Number.isFinite(value) ? value : undefined;

  const inputRaw = isRecord(rawUsage) ? rawUsage.input_tokens ?? rawUsage.prompt_tokens : undefined;
  const outputRaw = isRecord(rawUsage) ? rawUsage.output_tokens ?? rawUsage.completion_tokens : undefined;
  const totalRaw = isRecord(rawUsage) ? rawUsage.total_tokens : undefined;

  let input = safeNumber(inputRaw);
  let output = safeNumber(outputRaw);
  const total = safeNumber(totalRaw);

  if (input === undefined && output === undefined && total === undefined) {
    return undefined;
  }

  if (input === undefined && total !== undefined && output !== undefined) {
    input = Math.max(total - output, 0);
  }

  if (output === undefined && total !== undefined && input !== undefined) {
    output = Math.max(total - input, 0);
  }

  const inputFinal = input ?? total ?? 0;
  const outputFinal = output ?? 0;
  const totalFinal = total ?? (inputFinal + outputFinal);

  return {
    input_tokens: inputFinal,
    output_tokens: outputFinal,
    total_tokens: totalFinal,
  };
};

/**
 * Convert OpenAI system content (string/array/object) to readable string.
 */
const extractProviderTextContent = (content: unknown): string => {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === 'string') return block;
        if (isRecord(block)) {
          if (typeof block.text === 'string') return block.text;
          return JSON.stringify(block, null, 2);
        }
        return String(block);
      })
      .join('\n');
  }
  if (isRecord(content)) return JSON.stringify(content, null, 2);
  if (content === undefined || content === null) return '';
  return String(content);
};

/**
 * Normalizes an OpenAI-style request body into our standard format.
 */
const normalizeOpenAIRequest = (
  body: unknown
): { system: string | undefined; messages: NormalizedMessage[]; tools: NormalizedTool[]; model: string } => {
  const model = isRecord(body) ? asString(body.model, 'unknown-model') : 'unknown-model';

  const rawMessages = isRecord(body) && Array.isArray(body.messages) ? body.messages : [];

  // 1. Extract System Prompt (OpenAI puts it in messages)
  const systemMessages = rawMessages.filter(
    (m) => isRecord(m) && (m.role === 'system' || m.role === 'developer')
  );
  const system =
    systemMessages.length > 0
      ? systemMessages
          .map((m) => (isRecord(m) ? extractProviderTextContent(m.content) : ''))
          .filter(Boolean)
          .join('\n')
      : undefined;

  // 2. Normalize Tools
  const toolsSrc = isRecord(body) && Array.isArray(body.tools) ? body.tools : [];
  const tools: NormalizedTool[] = toolsSrc
    .map((t) => {
      if (!isRecord(t)) return null;
      // OpenAI Tool format: { type: 'function', function: { name, description, parameters } }
      if (t.type === 'function' && isRecord(t.function)) {
        const fn = t.function;
        const tool: NormalizedTool = {
          name: asString(fn.name, 'unknown'),
          input_schema: fn.parameters,
        };
        if (typeof fn.description === 'string') {
          tool.description = fn.description;
        }
        return tool;
      }
      return null;
    })
    .filter((t): t is NormalizedTool => t !== null);

  // 3. Normalize Messages (Convert OpenAI structure to "Normalized" Anthropic-like structure for UI)
  const messages: NormalizedMessage[] = rawMessages
    .filter((m) => !(isRecord(m) && (m.role === 'system' || m.role === 'developer')))
    .map((m) => {
      const role = isRecord(m) ? asString(m.role, 'user') : 'user';

      // Handle Assistant with Tool Calls
      if (role === 'assistant' && isRecord(m) && Array.isArray(m.tool_calls)) {
        const contentBlocks: Record<string, unknown>[] = [];
        if (m.content) {
          contentBlocks.push({ type: 'text', text: m.content });
        }
        m.tool_calls.forEach((tc) => {
          if (!isRecord(tc)) return;
          const fn = isRecord(tc.function) ? tc.function : null;
          const argsRaw = fn ? asString(fn.arguments, '{}') : '{}';

          let input: unknown = {};
          try {
            input = JSON.parse(argsRaw);
          } catch {
            input = { error: 'Failed to parse arguments', raw: argsRaw };
          }

          contentBlocks.push({
            type: 'tool_use',
            name: fn ? asString(fn.name, 'unknown') : 'unknown',
            input,
            id: tc.id,
          });
        });
        return { role: 'assistant', content: contentBlocks };
      }

      // Handle Tool Results (OpenAI 'tool' role -> Normalized 'user' role with tool_result block)
      if (role === 'tool' && isRecord(m)) {
        return {
          role: 'user',
          content: [
            {
              type: 'tool_result',
              tool_use_id: m.tool_call_id,
              content: m.content,
            },
          ],
        };
      }

      // Standard User/Assistant Text
      return {
        role: role as NormalizedMessage['role'],
        content: isRecord(m) ? m.content : m,
      };
    });

  return { system, messages, tools, model };
};

/**
 * Converts a Responses API function_call item into a normalized tool_use block.
 */
const normalizeResponsesFunctionCall = (item: Record<string, unknown>): Record<string, unknown> => {
  const argsRaw = asString(item.arguments, '');
  let input: unknown = {};
  if (argsRaw) {
    try {
      input = JSON.parse(argsRaw);
    } catch {
      input = { error: 'Failed to parse arguments', raw: argsRaw };
    }
  }
  return {
    type: 'tool_use',
    name: asString(item.name, 'unknown'),
    input,
    id: item.call_id !== undefined ? item.call_id : item.id,
  };
};

/**
 * Converts Responses API message content parts into UI content blocks.
 */
const normalizeResponsesContentParts = (content: unknown): unknown => {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return content;
  return content
    .map((part) => {
      if (typeof part === 'string') return { type: 'text', text: part };
      if (!isRecord(part)) return null;
      if (
        (part.type === 'input_text' || part.type === 'output_text' || part.type === 'summary_text') &&
        typeof part.text === 'string'
      ) {
        return { type: 'text', text: part.text };
      }
      if (typeof part.text === 'string') {
        return { type: 'text', text: part.text };
      }
      return part;
    })
    .filter((part) => part !== null);
};

/**
 * Normalizes an OpenAI Responses API request body into our standard format.
 */
const normalizeOpenAIResponsesRequest = (
  body: unknown
): { system: string | undefined; messages: NormalizedMessage[]; tools: NormalizedTool[]; model: string } => {
  const model = isRecord(body) ? asString(body.model, 'unknown-model') : 'unknown-model';

  // The Responses API carries the system prompt in `instructions`
  const instructions = isRecord(body) ? body.instructions : undefined;
  const system =
    typeof instructions === 'string' && instructions.trim() ? instructions : undefined;

  // Responses API tools are flat: { type: 'function', name, parameters, description }
  const toolsSrc = isRecord(body) && Array.isArray(body.tools) ? body.tools : [];
  const tools: NormalizedTool[] = toolsSrc
    .map((t) => {
      if (!isRecord(t)) return null;
      if (t.type === 'function' && typeof t.name === 'string') {
        const tool: NormalizedTool = {
          name: t.name,
          input_schema: t.parameters,
        };
        if (typeof t.description === 'string') {
          tool.description = t.description;
        }
        return tool;
      }
      return null;
    })
    .filter((t): t is NormalizedTool => t !== null);

  // Input is a string shorthand or a list of typed items
  const input = isRecord(body) ? body.input : undefined;
  let messages: NormalizedMessage[] = [];
  if (typeof input === 'string') {
    messages = [{ role: 'user', content: input }];
  } else if (Array.isArray(input)) {
    messages = input
      .filter((item): item is Record<string, unknown> => isRecord(item))
      .filter((item) => item.type !== 'reasoning')
      .map((item) => {
        const itemType = asString(item.type, '');

        // Prior assistant tool call
        if (itemType === 'function_call') {
          return {
            role: 'assistant' as const,
            content: [normalizeResponsesFunctionCall(item)],
          };
        }

        // Tool result
        if (itemType === 'function_call_output') {
          let output: unknown = item.output;
          if (typeof output === 'string') {
            try {
              output = JSON.parse(output);
            } catch {
              // keep raw string
            }
          }
          return {
            role: 'user' as const,
            content: [
              {
                type: 'tool_result',
                tool_use_id: item.call_id,
                content: output,
              },
            ],
          };
        }

        return {
          role: asString(item.role, 'user') as NormalizedMessage['role'],
          content: normalizeResponsesContentParts(item.content),
        };
      });
  }

  return { system, messages, tools, model };
};

/**
 * Normalizes an Anthropic-style request body into our standard format.
 */
const normalizeAnthropicRequest = (  body: unknown
): { system: unknown; messages: NormalizedMessage[]; tools: NormalizedTool[]; model: string } => {
  if (!isRecord(body)) return { system: undefined, messages: [], tools: [], model: 'unknown' };

  const model = asString(body.model, 'unknown-model');

  // System prompt can be a string or an array of content blocks in Anthropic.
  // Preserve arrays so the chat/system views can render each block separately.
  const system: unknown =
    typeof body.system === 'string' || Array.isArray(body.system) ? body.system : undefined;

  const messages: NormalizedMessage[] = Array.isArray(body.messages)
    ? body.messages
        .filter((message): message is Record<string, unknown> => isRecord(message))
        .map((message) => ({
          role: asString(message.role, 'user') as NormalizedMessage['role'],
          content: message.content,
        }))
    : [];

  const tools: NormalizedTool[] = Array.isArray(body.tools)
    ? body.tools
        .map((t) => {
          if (!isRecord(t)) return null;
          const tool: NormalizedTool = {
            name: asString(t.name, 'unknown'),
            input_schema: t.input_schema,
          };
          if (typeof t.description === 'string') {
            tool.description = t.description;
          }
          return tool;
        })
        .filter((t): t is NormalizedTool => t !== null)
    : [];

  return { system, messages, tools, model };
};

const normalizeExchangePair = (
  pair: RequestResponsePair,
  index: number,
  fallbackSessionId: string,
  sequenceId?: string
): NormalizedExchange | null => {
  if (!pair.request) return null;

  const rawRequest: RawRequest = {
    type: 'request',
    id: pair.request.request_id,
    timestamp: pair.request.timestamp,
    method: pair.request.method || 'POST',
    url: pair.request.url || '',
    headers: pair.request.headers || {},
    body: pair.request.body,
  };

  const rawResponse: RawResponse | null = pair.response
    ? {
        type: 'response',
        request_id: pair.response.request_id,
        timestamp: pair.response.timestamp,
        status_code: pair.response.status_code || 0,
        latency_ms: pair.response.latency_ms || 0,
        body: pair.response.body,
      }
    : null;

  let responseContent: unknown = rawResponse?.body;
  const usageData: unknown =
    isRecord(rawResponse?.body) && 'usage' in rawResponse.body ? rawResponse.body.usage : undefined;

  try {
    const responsesFormat = isOpenAIResponsesFormat(rawRequest.body, rawRequest.url);
    const openAIFormat = !responsesFormat && isOpenAIFormat(rawRequest.body);
    const normalized = responsesFormat
      ? normalizeOpenAIResponsesRequest(rawRequest.body)
      : openAIFormat
        ? normalizeOpenAIRequest(rawRequest.body)
        : normalizeAnthropicRequest(rawRequest.body);

    if (responsesFormat) {
      // Responses API: extract blocks from the output items array
      if (isRecord(rawResponse?.body) && Array.isArray(rawResponse.body.output)) {
        const blocks: Record<string, unknown>[] = [];
        rawResponse.body.output.forEach((item) => {
          if (!isRecord(item)) return;
          if (item.type === 'message') {
            const content = Array.isArray(item.content) ? item.content : [];
            content.forEach((part) => {
              if (!isRecord(part)) return;
              // Refusal parts carry the text in `refusal` instead of `text`
              if (part.type === 'refusal' && typeof part.refusal === 'string' && part.refusal) {
                blocks.push({ type: 'text', text: part.refusal });
                return;
              }
              if (typeof part.text === 'string' && part.text) {
                blocks.push({ type: 'text', text: part.text });
              }
            });
          } else if (item.type === 'function_call') {
            blocks.push(normalizeResponsesFunctionCall(item));
          } else if (item.type === 'reasoning') {
            const summary = Array.isArray(item.summary) ? item.summary : [];
            const text = summary
              .map((part) => (isRecord(part) && typeof part.text === 'string' ? part.text : ''))
              .join('\n')
              .trim();
            blocks.push({ type: 'thinking', thinking: text });
          }
        });
        if (blocks.length > 0) {
          responseContent = blocks;
        }
      }
    } else if (openAIFormat) {
      if (isRecord(rawResponse?.body) && Array.isArray(rawResponse.body.choices)) {
        const choice = rawResponse.body.choices[0];
        if (isRecord(choice) && isRecord(choice.message)) {
          const msg = choice.message;
          if (Array.isArray(msg.tool_calls)) {
            const blocks: Record<string, unknown>[] = [];
            if (msg.content) {
              blocks.push({ type: 'text', text: msg.content });
            }
            msg.tool_calls.forEach((tc) => {
              if (!isRecord(tc) || !isRecord(tc.function)) return;
              const argsRaw = asString(tc.function.arguments, '');
              let input: unknown = {};
              if (argsRaw) {
                try {
                  input = JSON.parse(argsRaw);
                } catch {
                  input = { error: 'Failed to parse arguments', raw: argsRaw };
                }
              }
              blocks.push({
                type: 'tool_use',
                name: asString(tc.function.name, 'unknown'),
                input,
                id: tc.id,
              });
            });
            responseContent = blocks;
          } else {
            responseContent = msg.content;
          }
        }
      }
    } else if (isRecord(rawResponse?.body)) {
      responseContent = 'content' in rawResponse.body ? (rawResponse.body as Record<string, unknown>).content : rawResponse.body;
    }

    const { system, messages, tools, model } = normalized;
    const systemPromptKey = extractProviderTextContent(system);

    return {
      id: rawRequest.id || `${fallbackSessionId}-${sequenceId || index + 1}`,
      sequenceId: sequenceId || String(index + 1).padStart(5, '0'),
      timestamp: rawRequest.timestamp || new Date().toISOString(),
      latencyMs: rawResponse?.latency_ms || 0,
      statusCode: rawResponse?.status_code || 0,
      model,
      systemPromptKey,
      toolNames: [],
      hasFullDetails: true,
      systemPrompt: system,
      messages,
      tools,
      responseContent,
      usage: normalizeUsageMetrics(usageData),
      rawRequest,
      rawResponse,
    };
  } catch (e) {
    console.error(`Error processing request ${index} in session ${fallbackSessionId}`, e);
    return null;
  }
};

export const normalizeSessionOverview = (overview: SessionOverview): Session => {
  const exchanges: NormalizedExchange[] = overview.exchanges.map((exchange) => ({
    id: exchange.id || `${overview.id}-${exchange.sequence_id}`,
    sequenceId: exchange.sequence_id,
    timestamp: exchange.timestamp || new Date().toISOString(),
    latencyMs: exchange.latency_ms || 0,
    statusCode: exchange.status_code || 0,
    model: exchange.model || 'unknown-model',
    systemPromptKey: exchange.system_prompt_key || '',
    toolNames: exchange.tool_names || [],
    hasFullDetails: false,
    systemPrompt: undefined,
    messages: [],
    tools: [],
    responseContent: null,
    usage: normalizeUsageMetrics(exchange.usage),
    rawRequest: {
      type: 'request',
      id: exchange.id || `${overview.id}-${exchange.sequence_id}`,
      timestamp: exchange.timestamp || new Date().toISOString(),
      method: exchange.request_method || 'POST',
      url: exchange.request_url || '',
      headers: {},
      body: null,
    },
    rawResponse: exchange.has_response
      ? {
          type: 'response',
          request_id: exchange.id,
          timestamp: exchange.timestamp || new Date().toISOString(),
          status_code: exchange.status_code || 0,
          latency_ms: exchange.latency_ms || 0,
          body: null,
        }
      : null,
  }));

  return {
    id: overview.id,
    name: overview.id,
    exchanges,
  };
};

export const normalizeExchangeDetail = (detail: ExchangeDetail, sessionId: string): NormalizedExchange | null => {
  const normalized = normalizeExchangePair(detail.pair, Number(detail.sequence_id) - 1, sessionId, detail.sequence_id);
  if (!normalized) return null;
  normalized.id = detail.id || normalized.id;
  return normalized;
};

export const mergeExchangeDetail = (
  session: Session,
  detailedExchange: NormalizedExchange
): Session => ({
  ...session,
  exchanges: session.exchanges.map((exchange) =>
    exchange.sequenceId === detailedExchange.sequenceId
      ? {
          ...exchange,
          ...detailedExchange,
          systemPromptKey: exchange.systemPromptKey || detailedExchange.systemPromptKey,
          toolNames: exchange.toolNames.length > 0 ? exchange.toolNames : detailedExchange.toolNames,
          hasFullDetails: true,
        }
      : exchange
  ),
});

export const formatTimestamp = (iso: string) => {
  if (!iso) return '--:--:--';
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
};

export const formatDuration = (ms: number) => {
  if (!Number.isFinite(ms) || ms <= 0) return '0s';

  const totalSeconds = Math.floor(ms / 1000);
  if (totalSeconds < 1) return '<1s';
  if (totalSeconds < 60) return `${totalSeconds}s`;

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
};

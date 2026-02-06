import type {
  NormalizedExchange,
  NormalizedMessage,
  NormalizedTool,
  RawRequest,
  RawResponse,
  Session,
  SessionDetails,
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

/**
 * Normalize provider-specific token usage stats into {input_tokens, output_tokens}.
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
const normalizeOpenAISystemContent = (content: unknown): string => {
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
          .map((m) => (isRecord(m) ? normalizeOpenAISystemContent(m.content) : ''))
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
 * Normalizes an Anthropic-style request body into our standard format.
 */
const normalizeAnthropicRequest = (
  body: unknown
): { system: string | undefined; messages: NormalizedMessage[]; tools: NormalizedTool[]; model: string } => {
  if (!isRecord(body)) return { system: undefined, messages: [], tools: [], model: 'unknown' };

  const model = asString(body.model, 'unknown-model');

  // System prompt can be a string or array of objects in Anthropic
  let system: string | undefined = undefined;
  if (typeof body.system === 'string') {
    system = body.system;
  } else if (Array.isArray(body.system)) {
    system = body.system
      .map((s) => (isRecord(s) ? asString(s.text) : ''))
      .filter(Boolean)
      .join('\n');
  }

  const messages: NormalizedMessage[] = Array.isArray(body.messages) ? (body.messages as NormalizedMessage[]) : [];

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

/**
 * Main parser function to process API session details
 */
export const normalizeSession = (details: SessionDetails): Session => {
  const exchanges: NormalizedExchange[] = [];

  details.pairs.forEach((pair, index) => {
    // Basic Request Validation
    if (!pair.request) return;

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

    // --- Normalization Logic ---
    let responseContent: unknown = rawResponse?.body;
    const usageData: unknown =
      isRecord(rawResponse?.body) && 'usage' in rawResponse.body ? rawResponse.body.usage : undefined;

    try {
      const normalized = isOpenAIFormat(rawRequest.body)
        ? normalizeOpenAIRequest(rawRequest.body)
        : normalizeAnthropicRequest(rawRequest.body);

      // Provider-specific response normalization
      if (isOpenAIFormat(rawRequest.body)) {
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
      } else {
        // Default: Anthropic Format
        if (isRecord(rawResponse?.body)) {
          responseContent = 'content' in rawResponse.body ? (rawResponse.body as Record<string, unknown>).content : rawResponse.body;
        }
      }

      const { system, messages, tools, model } = normalized;

      // Generate a 3-digit sequence ID based on index
      const sequenceId = String(index + 1).padStart(3, '0');

      const exchange: NormalizedExchange = {
        id: rawRequest.id || `local-${index}`,
        sequenceId,
        timestamp: rawRequest.timestamp || new Date().toISOString(),
        latencyMs: rawResponse?.latency_ms || 0,
        statusCode: rawResponse?.status_code || 0,
        model,
        systemPrompt: system,
        messages,
        tools,
        responseContent,
        usage: normalizeUsageMetrics(usageData),
        rawRequest,
        rawResponse,
      };

      exchanges.push(exchange);
    } catch (e) {
      console.error(`Error processing request ${index} in session ${details.id}`, e);
    }
  });

  return {
    id: details.id,
    name: details.id,
    exchanges: exchanges.sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    ),
  };
};

export const formatTimestamp = (iso: string) => {
  if (!iso) return '--:--:--';
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
};

import type { NormalizedExchange, NormalizedMessage, NormalizedTool, RawRequest, RawResponse, Session, SessionDetails } from "./types";

/**
 * Detects if the request body follows OpenAI structure.
 */
const isOpenAIFormat = (body: any): boolean => {
  if (!body) return false;
  // Check for OpenAI specific tool format
  if (body.tools && Array.isArray(body.tools) && body.tools.some((t: any) => t.type === 'function')) return true;
  // Check for OpenAI specific message roles or properties
  if (body.messages && Array.isArray(body.messages) && body.messages.some((m: any) => m.role === 'tool' || m.tool_calls || m.role === 'developer')) return true;
  // If system is strictly in messages and not at top level (Anthropic uses top level system usually)
  if (!body.system && body.messages && body.messages.some((m: any) => m.role === 'system')) return true;
  return false;
};

/**
 * Normalizes an OpenAI-style request body into our standard format.
 */
const normalizeOpenAIRequest = (body: any): { system: string | undefined, messages: NormalizedMessage[], tools: NormalizedTool[], model: string } => {
  const model = body.model || 'unknown-model';
  
  const rawMessages = Array.isArray(body.messages) ? body.messages : [];
  
  // 1. Extract System Prompt (OpenAI puts it in messages)
  const systemMessages = rawMessages.filter((m: any) => m.role === 'system' || m.role === 'developer');
  const system = systemMessages.length > 0 ? systemMessages.map((m: any) => m.content).join('\n') : undefined;

  // 2. Normalize Tools
  const tools: NormalizedTool[] = Array.isArray(body.tools) ? body.tools.map((t: any) => {
    // OpenAI Tool format: { type: 'function', function: { name, description, parameters } }
    if (t.type === 'function' && t.function) {
      return {
        name: t.function.name,
        description: t.function.description,
        input_schema: t.function.parameters
      };
    }
    return null;
  }).filter((t: any) => t !== null) : [];

  // 3. Normalize Messages (Convert OpenAI structure to "Normalized" Anthropic-like structure for UI)
  const messages: NormalizedMessage[] = rawMessages
    .filter((m: any) => m.role !== 'system' && m.role !== 'developer')
    .map((m: any) => {
      // Handle Assistant with Tool Calls
      if (m.role === 'assistant' && m.tool_calls) {
        const contentBlocks: any[] = [];
        if (m.content) {
          contentBlocks.push({ type: 'text', text: m.content });
        }
        m.tool_calls.forEach((tc: any) => {
          let input = {};
          try {
            input = JSON.parse(tc.function.arguments || '{}');
          } catch(e) {
            input = { error: "Failed to parse arguments", raw: tc.function.arguments };
          }
          
          contentBlocks.push({
            type: 'tool_use',
            name: tc.function.name,
            input: input,
            id: tc.id
          });
        });
        return { role: 'assistant', content: contentBlocks };
      }

      // Handle Tool Results (OpenAI 'tool' role -> Normalized 'user' role with tool_result block)
      if (m.role === 'tool') {
        return {
          role: 'user', 
          content: [{
            type: 'tool_result',
            tool_use_id: m.tool_call_id,
            content: m.content
          }]
        };
      }

      // Standard User/Assistant Text
      return {
        role: m.role,
        content: m.content
      };
    });

  return { system, messages, tools, model };
};

/**
 * Normalizes an Anthropic-style request body into our standard format.
 */
const normalizeAnthropicRequest = (body: any): { system: string | undefined, messages: NormalizedMessage[], tools: NormalizedTool[], model: string } => {
  if (!body) return { system: undefined, messages: [], tools: [], model: 'unknown' };

  const model = body.model || 'unknown-model';
  
  // System prompt can be a string or array of objects in Anthropic
  let system = undefined;
  if (typeof body.system === 'string') {
    system = body.system;
  } else if (Array.isArray(body.system)) {
    system = body.system.map((s: any) => s.text).join('\n');
  }

  const messages: NormalizedMessage[] = Array.isArray(body.messages) ? body.messages : [];
  
  const tools: NormalizedTool[] = Array.isArray(body.tools) ? body.tools.map((t: any) => ({
    name: t.name,
    description: t.description,
    input_schema: t.input_schema
  })) : [];

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

    // Use pair.request and pair.response directly
    // Ensure they match RawRequest/RawResponse structure (which they mostly do from the backend)
    const rawRequest: RawRequest = {
        type: 'request',
        id: pair.request.request_id,
        timestamp: pair.request.timestamp,
        method: pair.request.method || 'POST',
        url: pair.request.url || '',
        headers: pair.request.headers || {},
        body: pair.request.body
    };

    const rawResponse: RawResponse | null = pair.response ? {
        type: 'response',
        request_id: pair.response.request_id,
        timestamp: pair.response.timestamp,
        status_code: pair.response.status_code || 0,
        latency_ms: pair.response.latency_ms || 0,
        body: pair.response.body
    } : null;

    // --- Normalization Logic ---
    let normalized;
    let responseContent = rawResponse?.body;
    let usage = rawResponse?.body?.usage;

    try {
        if (isOpenAIFormat(rawRequest.body)) {
          // OpenAI Format
          normalized = normalizeOpenAIRequest(rawRequest.body);
          
          // Normalize OpenAI Response if available
          if (rawResponse?.body && rawResponse.body.choices) {
            const choice = rawResponse.body.choices[0];
            if (choice) {
               // If response has tool calls, normalize to content blocks for UI
               if (choice.message.tool_calls) {
                  const blocks: any[] = [];
                  if (choice.message.content) {
                    blocks.push({ type: 'text', text: choice.message.content });
                  }
                  choice.message.tool_calls.forEach((tc: any) => {
                      let input = {};
                      try { input = JSON.parse(tc.function.arguments); } catch(e) {}
                      blocks.push({
                          type: 'tool_use',
                          name: tc.function.name,
                          input: input,
                          id: tc.id
                      });
                  });
                  responseContent = blocks;
               } else {
                  responseContent = choice.message.content;
               }
            }
            usage = rawResponse.body.usage;
          }

        } else {
          // Default: Anthropic Format
          normalized = normalizeAnthropicRequest(rawRequest.body);
          if (rawResponse?.body) {
            // Anthropic content is usually at body.content or body itself if simple
            responseContent = rawResponse.body.content || rawResponse.body;
            usage = rawResponse.body.usage;
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
          usage,
          rawRequest,
          rawResponse
        };

        exchanges.push(exchange);
    } catch (e) {
        console.error(`Error processing request ${index} in session ${details.id}`, e);
    }
  });

  return {
    id: details.id,
    name: details.id,
    exchanges: exchanges.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
  };
};

export const formatTimestamp = (iso: string) => {
  if (!iso) return '--:--:--';
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch (e) {
    return iso;
  }
};

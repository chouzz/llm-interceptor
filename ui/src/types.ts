
// --- API Types (from Backend) ---

export interface SessionSummary {
  id: string;
  timestamp: string;
  request_count: number;
  total_latency_ms: number;
  total_tokens: number;
}

export interface AnnotationData {
  session_note: string;
  requests: Record<string, string>; // key: sequenceId (e.g., "001"), value: note
}

export interface LogRecord {
  type: "request" | "response";
  request_id: string;
  timestamp: string;
  status_code?: number;
  method?: string;
  url?: string;
  body: unknown;
  latency_ms?: number;
  headers?: Record<string, string>;
}

export interface RequestResponsePair {
  request: LogRecord | null;
  response: LogRecord | null;
}

export interface SessionDetails {
  id: string;
  pairs: RequestResponsePair[];
}


// --- UI Internal Types (Normalized) ---

// Raw JSON File Structures (Mapped from LogRecord)
export interface RawRequest {
  type: 'request';
  id: string;
  timestamp: string;
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

export interface RawResponse {
  type: 'response';
  request_id?: string;
  timestamp: string;
  status_code: number;
  latency_ms: number;
  body: unknown;
}

export interface NormalizedMessage {
  role: 'user' | 'assistant' | 'system';
  content: unknown; // Provider payloads vary; UI components will narrow as needed
}

export interface NormalizedTool {
  name: string;
  description?: string;
  input_schema?: unknown; // JSON Schema
}

export interface NormalizedExchange {
  id: string;
  sequenceId?: string; // e.g. "001"
  timestamp: string;
  latencyMs: number;
  statusCode: number;
  model: string;

  // Grouped Data
  systemPrompt?: string; // Extracted system prompt
  messages: NormalizedMessage[]; // The conversation context sent TO the model
  tools?: NormalizedTool[]; // Tools defined in the request

  responseContent: unknown; // The answer FROM the model (provider-dependent)
  usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  };

  // Original raw data for debugging
  rawRequest: RawRequest;
  rawResponse: RawResponse | null;
}

export interface Session {
  id: string;
  name: string; // usually the folder name
  exchanges: NormalizedExchange[];
}

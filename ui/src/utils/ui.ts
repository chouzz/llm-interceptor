// UI-focused helpers that should not depend on React.

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

// Debounce helper for auto-saving annotations (or other UI actions).
export function debounce<Args extends unknown[], R>(
  fn: (...args: Args) => R,
  delay: number
): (...args: Args) => void {
  let timeoutId: ReturnType<typeof setTimeout>;
  return (...args: Args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}

// Copy to clipboard helper
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    console.error('Failed to copy:', err);
    return false;
  }
}

// Extract text content from message content (handles various formats)
export function extractTextContent(content: unknown): string {
  if (typeof content === 'string') {
    return content;
  }
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (!isRecord(block)) return String(block);
        const type = block.type;

        if (type === 'text' && typeof block.text === 'string') return block.text;

        if (type === 'tool_use') {
          const name = typeof block.name === 'string' ? block.name : 'unknown';
          return `[Tool Call: ${name}]\n${JSON.stringify(block.input, null, 2)}`;
        }

        if (type === 'tool_result') {
          const toolUseId = typeof block.tool_use_id === 'string' ? block.tool_use_id : 'unknown';
          const resultContent =
            typeof block.content === 'string'
              ? block.content
              : JSON.stringify(block.content, null, 2);
          return `[Tool Result: ${toolUseId}]\n${resultContent}`;
        }

        if (type === 'thinking') {
          const thinking = typeof block.thinking === 'string' ? block.thinking.trim() : '';
          return thinking ? `[Thinking]\n${thinking}` : '[Thinking]\nNo thinking content captured';
        }

        return JSON.stringify(block, null, 2);
      })
      .join('\n\n');
  }
  if (typeof content === 'object' && content !== null) {
    return JSON.stringify(content, null, 2);
  }
  return String(content);
}

// Helper for deterministic-ish color generation (used for grouping system prompts)
export function stringToColor(str: string | undefined) {
  if (!str) return '#94a3b8'; // Default slate-400
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const c = (hash & 0x00ffffff).toString(16).toUpperCase();
  return '#' + '00000'.substring(0, 6 - c.length) + c;
}

export function safeJSONStringify(value: unknown, space = 2) {
  try {
    return JSON.stringify(value, null, space);
  } catch (error) {
    console.error('Failed to stringify JSON data', error);
    return '';
  }
}

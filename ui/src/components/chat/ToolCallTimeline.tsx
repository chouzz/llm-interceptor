import React, { useMemo } from 'react';
import { Activity, Terminal, Zap } from 'lucide-react';
import type { NormalizedMessage } from '../../types';

const TOOL_RESULT_PREVIEW_LIMIT = 160;

type ToolEvent = {
  kind: 'call' | 'result';
  name: string;
  id?: string;
  source: 'context' | 'response';
  summary?: string;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const getToolUseId = (block: Record<string, unknown>): string | undefined => {
  const id = block.id ?? block.tool_use_id ?? block.tool_call_id;
  return typeof id === 'string' ? id : undefined;
};

const summarizeResult = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value.trim();
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const formatId = (id?: string): string => {
  if (!id) return '';
  return id.length > 12 ? `${id.slice(0, 12)}…` : id;
};

const collectToolBlocks = (
  content: unknown,
  source: ToolEvent['source'],
  entries: Array<{ block: Record<string, unknown>; source: ToolEvent['source'] }>
) => {
  if (!Array.isArray(content)) return;
  content.forEach((block) => {
    if (!isRecord(block)) return;
    const type = typeof block.type === 'string' ? block.type : '';
    if (type === 'tool_use' || type === 'tool_result') {
      entries.push({ block, source });
    }
  });
};

const buildToolEvents = (messages: NormalizedMessage[], responseContent: unknown): ToolEvent[] => {
  const entries: Array<{ block: Record<string, unknown>; source: ToolEvent['source'] }> = [];

  messages.forEach((msg) => collectToolBlocks(msg.content, 'context', entries));
  collectToolBlocks(responseContent, 'response', entries);

  const idToName = new Map<string, string>();
  entries.forEach(({ block }) => {
    const type = typeof block.type === 'string' ? block.type : '';
    if (type === 'tool_use' && typeof block.name === 'string') {
      const id = getToolUseId(block);
      if (id) idToName.set(id, block.name);
    }
  });

  const events: ToolEvent[] = [];
  entries.forEach(({ block, source }) => {
    const type = typeof block.type === 'string' ? block.type : '';
    if (type === 'tool_use') {
      const id = getToolUseId(block);
      const name = typeof block.name === 'string' ? block.name : 'unknown';
      events.push({ kind: 'call', name, id, source });
      return;
    }
    if (type === 'tool_result') {
      const id = getToolUseId(block);
      const name = (id && idToName.get(id)) || 'unknown';
      const summaryRaw = summarizeResult(block.content);
      const summary =
        summaryRaw.length > TOOL_RESULT_PREVIEW_LIMIT
          ? `${summaryRaw.slice(0, TOOL_RESULT_PREVIEW_LIMIT)}…`
          : summaryRaw;
      events.push({ kind: 'result', name, id, source, summary });
    }
  });

  return events;
};

export const ToolCallTimeline: React.FC<{
  messages: NormalizedMessage[];
  responseContent: unknown;
}> = ({ messages, responseContent }) => {
  const events = useMemo(
    () => buildToolEvents(messages, responseContent),
    [messages, responseContent]
  );
  const callCount = useMemo(
    () => events.filter((event) => event.kind === 'call').length,
    [events]
  );

  return (
    <div className="border border-gray-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900/40 overflow-hidden shadow-sm">
      <div className="px-4 py-3 border-b border-gray-200 dark:border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-bold text-slate-700 dark:text-slate-200">
          <Activity size={14} className="text-blue-500" />
          Tool Call Timeline
        </div>
        <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400 bg-gray-100 dark:bg-slate-800 px-2 py-0.5 rounded-full border border-gray-200 dark:border-slate-700">
          {callCount} calls
        </span>
      </div>
      <div className="p-4">
        {events.length === 0 ? (
          <div className="p-6 text-center text-slate-500 dark:text-slate-400 border border-dashed border-gray-200 dark:border-slate-800 rounded-lg bg-gray-50 dark:bg-slate-900/30 text-sm">
            No tool calls detected in this exchange.
          </div>
        ) : (
          <div className="relative">
            <div className="absolute left-4 top-2 bottom-2 w-px bg-gray-200 dark:bg-slate-800"></div>
            <div className="space-y-4">
              {events.map((event, idx) => {
                const isCall = event.kind === 'call';
                const badgeStyles = isCall
                  ? 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800/60'
                  : 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60';
                const nodeStyles = isCall
                  ? 'bg-yellow-100 dark:bg-yellow-900/40 text-yellow-600 dark:text-yellow-400 border-yellow-200 dark:border-yellow-800/60'
                  : 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800/60';

                return (
                  <div key={`${event.kind}-${event.id ?? 'na'}-${idx}`} className="relative pl-10">
                    <div
                      className={`absolute left-1.5 top-0.5 w-6 h-6 rounded-full border flex items-center justify-center ${nodeStyles}`}
                    >
                      {isCall ? <Terminal size={12} /> : <Zap size={12} />}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] font-mono text-slate-500 dark:text-slate-400 bg-gray-100 dark:bg-slate-800 px-1.5 py-0.5 rounded border border-gray-200 dark:border-slate-700">
                        #{idx + 1}
                      </span>
                      <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                        {event.name}
                      </span>
                      <span
                        className={`text-[9px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded border ${badgeStyles}`}
                      >
                        {isCall ? 'tool call' : 'tool result'}
                      </span>
                      <span className="text-[9px] uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-900 px-1.5 py-0.5 rounded border border-gray-200 dark:border-slate-700">
                        {event.source}
                      </span>
                      {event.id && (
                        <span className="text-[9px] font-mono text-slate-400 dark:text-slate-500">
                          id: {formatId(event.id)}
                        </span>
                      )}
                    </div>
                    {event.summary && (
                      <div
                        className="mt-1 text-[10px] text-slate-500 dark:text-slate-400 font-mono truncate"
                        title={event.summary}
                      >
                        {event.summary}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

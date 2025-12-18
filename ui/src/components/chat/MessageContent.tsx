import React from 'react';
import { Zap } from 'lucide-react';
import { CopyButton } from '../common/CopyButton';
import { ToolCallBlock } from './ToolCallBlock';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

export const MessageContent: React.FC<{ content: unknown }> = React.memo(({ content }) => {
  // Handle String content
  if (typeof content === 'string') {
    return (
      <div className="whitespace-pre-wrap leading-relaxed break-words text-slate-700 dark:text-slate-100 font-medium">
        {content}
      </div>
    );
  }

  // Handle Array of Content Blocks (Anthropic/OpenAI standardized)
  if (Array.isArray(content)) {
    return (
      <div className="space-y-3">
        {content.map((block, idx) => {
          if (!isRecord(block)) {
            return (
              <div
                key={idx}
                className="text-xs text-gray-500 italic border border-gray-200 dark:border-gray-800 p-2 rounded"
              >
                [Unrecognized block]
              </div>
            );
          }

          const type = block.type;

          if (type === 'text' && typeof block.text === 'string') {
            return (
              <div
                key={idx}
                className="whitespace-pre-wrap leading-relaxed break-words text-slate-700 dark:text-slate-100 font-medium"
              >
                {block.text}
              </div>
            );
          }
          if (type === 'tool_use') {
            return <ToolCallBlock key={idx} content={block} />;
          }
          if (type === 'tool_result') {
            // Determine how to render the tool result content
            const renderedResult =
              typeof block.content === 'string' ? block.content : JSON.stringify(block.content, null, 2);
            const toolUseId = typeof block.tool_use_id === 'string' ? block.tool_use_id : 'unknown';

            return (
              <div
                key={idx}
                className="text-xs border-l-2 border-emerald-500 pl-3 py-2 my-2 bg-emerald-50 dark:bg-emerald-900/10 rounded-r overflow-hidden group/result"
              >
                <div className="font-bold text-emerald-600 dark:text-emerald-500 text-[10px] uppercase mb-1 flex items-center gap-2">
                  <Zap size={10} />
                  Tool Result ({toolUseId})
                  <CopyButton
                    content={renderedResult}
                    className="opacity-0 group-hover/result:opacity-100"
                  />
                </div>
                {/* Use whitespace-pre-wrap to handle newlines and break-words to wrap long lines */}
                <div className="font-mono text-emerald-800 dark:text-emerald-200/90 whitespace-pre-wrap break-words max-h-[500px] overflow-y-auto custom-scrollbar">
                  {renderedResult}
                </div>
              </div>
            );
          }
          return (
            <div
              key={idx}
              className="text-xs text-gray-500 italic border border-gray-200 dark:border-gray-800 p-2 rounded"
            >
              [Unknown Block Type: {String(block.type)}]
            </div>
          );
        })}
      </div>
    );
  }

  // Handle Plain Objects (e.g., pure JSON responses from models)
  if (typeof content === 'object' && content !== null) {
    return (
      <div className="font-mono text-xs text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-black/20 p-3 rounded border border-emerald-200 dark:border-emerald-900/30 overflow-x-auto">
        <pre className="whitespace-pre-wrap break-words custom-scrollbar">
          {JSON.stringify(content, null, 2)}
        </pre>
      </div>
    );
  }

  return <div className="text-red-500 dark:text-red-400">Unrenderable content type</div>;
});

import React from 'react';

export const TokenBadge: React.FC<{
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number };
}> = ({ usage }) => {
  if (!usage) return null;
  const inputTokens = typeof usage.input_tokens === 'number' ? usage.input_tokens : 0;
  const outputTokens =
    typeof usage.output_tokens === 'number' ? usage.output_tokens : 0;
  const totalTokens = typeof usage.total_tokens === 'number' ? usage.total_tokens : (inputTokens + outputTokens);
  return (
    <div className="flex gap-3 text-xs font-mono text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded border border-gray-200 dark:border-gray-700">
      <span className="flex items-center gap-1">
        <span className="text-blue-600 dark:text-blue-400">In:</span>{' '}
        {inputTokens.toLocaleString()}
      </span>
      <span className="flex items-center gap-1">
        <span className="text-purple-600 dark:text-purple-400">Out:</span>{' '}
        {outputTokens.toLocaleString()}
      </span>
      <span className="flex items-center gap-1 text-gray-400 border-l border-gray-300 dark:border-gray-600 pl-2">
        Total: {totalTokens.toLocaleString()}
      </span>
    </div>
  );
};

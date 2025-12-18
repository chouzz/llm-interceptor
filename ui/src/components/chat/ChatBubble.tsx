import React, { useMemo } from 'react';
import { Search, Terminal, Zap } from 'lucide-react';
import type { NormalizedMessage } from '../../types';
import { extractTextContent } from '../../utils/ui';
import { CopyButton } from '../common/CopyButton';
import { MessageContent } from './MessageContent';

export const ChatBubble: React.FC<{ message: NormalizedMessage }> = React.memo(({ message }) => {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const textContent = useMemo(() => extractTextContent(message.content), [message.content]);

  // Special styling for System messages
  if (isSystem) {
    return (
      <div className="flex w-full mb-8 justify-center">
        <div className="w-full rounded-lg border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-[#1a0505] text-xs font-mono overflow-hidden shadow-sm group/system">
          <div className="flex items-center justify-between px-4 py-2 bg-red-100 dark:bg-red-950/40 border-b border-red-200 dark:border-red-900/50">
            <div className="flex items-center gap-2 text-red-600 dark:text-red-400 font-bold uppercase tracking-wider text-[10px]">
              <Terminal size={12} />
              System Configuration
            </div>
            <CopyButton content={textContent} className="opacity-0 group-hover/system:opacity-100" />
          </div>
          <div className="p-4 overflow-x-auto max-h-[300px] custom-scrollbar text-red-900 dark:text-red-50 font-medium">
            <MessageContent content={message.content} />
          </div>
        </div>
      </div>
    );
  }

  // User and Assistant messages
  return (
    <div className={`flex w-full mb-6 ${isUser ? 'justify-end' : 'justify-start'} group/bubble`}>
      <div className={`flex max-w-[85%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-3`}>
        {/* Avatar */}
        <div
          className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-1 shadow-md ring-2 ring-opacity-20 ${
            isUser ? 'bg-blue-600 ring-blue-400' : 'bg-purple-600 ring-purple-400'
          }`}
        >
          {isUser ? <Search size={16} className="text-white" /> : <Zap size={16} className="text-white" />}
        </div>

        {/* Content Bubble */}
        <div
          className={`rounded-2xl p-4 shadow-sm text-sm border relative overflow-hidden ${
            isUser
              ? 'bg-blue-50 dark:bg-slate-800 border-blue-200 dark:border-slate-700 rounded-tr-sm text-slate-800 dark:text-slate-100'
              : 'bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-800 rounded-tl-sm text-slate-800 dark:text-slate-200'
          }`}
        >
          <div
            className={`text-[10px] uppercase tracking-wider font-bold opacity-60 mb-2 flex items-center gap-2 text-slate-500 dark:text-slate-400 ${
              isUser ? 'justify-end' : 'justify-start'
            }`}
          >
            {message.role}
            <CopyButton content={textContent} className="opacity-0 group-hover/bubble:opacity-100" />
          </div>
          <MessageContent content={message.content} />
        </div>
      </div>
    </div>
  );
});

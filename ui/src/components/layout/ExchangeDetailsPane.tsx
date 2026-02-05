import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Box,
  ChevronDown,
  FileJson,
  MessageSquare,
  Terminal,
  WrapText,
  Zap,
} from 'lucide-react';
import type { NormalizedExchange } from '../../types';
import { safeJSONStringify } from '../../utils/ui';
import { ChatBubble } from '../chat/ChatBubble';
import { ToolCallTimeline } from '../chat/ToolCallTimeline';
import { CopyButton } from '../common/CopyButton';
import { JSONViewer } from '../common/JSONViewer';
import { TokenBadge } from '../common/TokenBadge';
import { ToolsList } from '../tools/ToolsList';

const TABS = [
  { id: 'chat', icon: MessageSquare, label: 'Chat' },
  { id: 'system', icon: Terminal, label: 'System' },
  { id: 'tools', icon: Box, label: 'Tools' },
  { id: 'raw', icon: FileJson, label: 'JSON' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export const ExchangeDetailsPane: React.FC<{
  currentExchange: NormalizedExchange | null;
}> = ({ currentExchange }) => {
  const [activeTab, setActiveTab] = useState<TabId>('chat');
  const [chatScrollEdges, setChatScrollEdges] = useState({ atTop: true, atBottom: true });
  const [isJsonWrapped, setIsJsonWrapped] = useState(false);

  const chatScrollRef = useRef<HTMLDivElement>(null);

  // Sticky tool header state
  const [stickyToolInfo, setStickyToolInfo] = useState<{
    name: string | null;
    toggleFn: (() => void) | null;
    scrollFn: (() => void) | null;
  }>({ name: null, toggleFn: null, scrollFn: null });

  const handleStickyToolChange = useCallback(
    (toolName: string | null, toggleFn: (() => void) | null, scrollFn: (() => void) | null) => {
      setStickyToolInfo({ name: toolName, toggleFn, scrollFn });
    },
    []
  );

  const handleTabChange = (tabId: TabId) => {
    setActiveTab(tabId);
    if (tabId !== 'tools') {
      setStickyToolInfo({ name: null, toggleFn: null, scrollFn: null });
    }
    if (tabId !== 'chat') {
      setChatScrollEdges({ atTop: true, atBottom: true });
    }
  };

  const requestBodyText = useMemo(
    () => (currentExchange ? safeJSONStringify(currentExchange.rawRequest) : ''),
    [currentExchange?.rawRequest]
  );

  const responseBodyText = useMemo(
    () => (currentExchange?.rawResponse ? safeJSONStringify(currentExchange.rawResponse) : ''),
    [currentExchange?.rawResponse]
  );

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el || activeTab !== 'chat') return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      setChatScrollEdges({
        atTop: scrollTop <= 8,
        atBottom: scrollTop + clientHeight >= scrollHeight - 8,
      });
    };

    handleScroll();
    el.addEventListener('scroll', handleScroll);
    return () => el.removeEventListener('scroll', handleScroll);
  }, [activeTab, currentExchange]);

  const scrollChatTo = (position: 'top' | 'bottom') => {
    const el = chatScrollRef.current;
    if (!el) return;
    const top = position === 'top' ? 0 : el.scrollHeight;
    el.scrollTo({ top, behavior: 'smooth' });
  };

  return (
    <div className="flex-1 flex flex-col bg-white dark:bg-[#0f172a] relative">
      {currentExchange ? (
        <>
          {/* Header */}
          <header className="h-[57px] border-b border-gray-200 dark:border-slate-800 flex items-center justify-between px-6 bg-white/80 dark:bg-slate-900/50 backdrop-blur sticky top-0 z-20">
            <div className="flex flex-col justify-center h-full">
              <div className="flex items-center gap-3">
                <span className="text-xs font-bold text-slate-500 dark:text-slate-400 bg-gray-100 dark:bg-slate-800 px-2 py-0.5 rounded border border-gray-200 dark:border-slate-700 font-mono">
                  {currentExchange.model}
                </span>
                <TokenBadge usage={currentExchange.usage} />
              </div>
            </div>
            <div className="flex bg-gray-100 dark:bg-slate-800/80 p-1 rounded-lg border border-gray-200 dark:border-slate-700">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => handleTabChange(tab.id)}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                    activeTab === tab.id
                      ? 'bg-white dark:bg-slate-600 text-slate-900 dark:text-white shadow-sm ring-1 ring-black/5 dark:ring-white/10'
                      : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-gray-200/50 dark:hover:bg-slate-700/50'
                  }`}
                  type="button"
                >
                  <tab.icon size={14} />
                  {tab.label}
                </button>
              ))}
            </div>
          </header>

          {/* Content Area */}
          <div
            ref={chatScrollRef}
            className="flex-1 overflow-y-auto px-6 pb-6 scroll-smooth custom-scrollbar bg-white dark:bg-[#0f172a]"
          >
            {/* Chat View */}
            {activeTab === 'chat' && (
              <div className="max-w-4xl mx-auto">
                {/* Reconstruct conversation history (Context) */}
                <div className="mb-8">
                  <div className="text-[10px] font-bold text-slate-400 dark:text-slate-600 mb-6 flex items-center justify-center gap-2 uppercase tracking-[0.2em]">
                    <span className="w-12 h-[1px] bg-gray-200 dark:bg-slate-800"></span>
                    Context History
                    <span className="w-12 h-[1px] bg-gray-200 dark:bg-slate-800"></span>
                  </div>

                  {currentExchange.systemPrompt && (
                    <ChatBubble message={{ role: 'system', content: currentExchange.systemPrompt }} />
                  )}

                  {currentExchange.messages.length === 0 && !currentExchange.systemPrompt && (
                    <div className="text-sm text-slate-500 dark:text-slate-600 italic text-center py-8 bg-gray-50 dark:bg-slate-900/20 rounded-lg border border-dashed border-gray-200 dark:border-slate-800">
                      No prior context messages. This appears to be the start of a conversation.
                    </div>
                  )}

                  {currentExchange.messages.map((msg, i) => {
                    // Hide trailing assistant messages (pre-fills) to avoid duplication with the actual response
                    if (i === currentExchange.messages.length - 1 && msg.role === 'assistant') {
                      return null;
                    }
                    return <ChatBubble key={i} message={msg} />;
                  })}
                </div>

                {/* Tool Call Timeline */}
                <div className="mt-12 pt-8 border-t border-gray-200 dark:border-slate-800">
                  <ToolCallTimeline
                    messages={currentExchange.messages}
                    responseContent={currentExchange.responseContent}
                  />
                </div>

                {/* The Response */}
                <div className="mt-12 pt-8 border-t border-gray-200 dark:border-slate-800">
                  <div className="text-[10px] font-bold text-emerald-600 dark:text-emerald-500/70 mb-8 flex items-center justify-center gap-2 uppercase tracking-[0.2em]">
                    <span className="w-12 h-[1px] bg-emerald-100 dark:bg-emerald-900/30"></span>
                    <Zap size={12} />
                    Model Response
                    <span className="w-12 h-[1px] bg-emerald-100 dark:bg-emerald-900/30"></span>
                  </div>
                  {currentExchange.responseContent ? (
                    <ChatBubble message={{ role: 'assistant', content: currentExchange.responseContent }} />
                  ) : (
                    <div className="text-slate-500 italic p-6 border border-dashed border-gray-200 dark:border-slate-800 rounded-lg text-sm text-center bg-gray-50 dark:bg-slate-900/20">
                      Response data unavailable or failed to parse.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* System Prompt View */}
            {activeTab === 'system' && (
              <div className="max-w-4xl mx-auto">
                <div className="bg-white dark:bg-[#0d1117] border border-gray-200 dark:border-slate-800 rounded-lg overflow-hidden shadow-xl">
                  <div className="px-4 py-3 bg-gray-100 dark:bg-slate-900 border-b border-gray-200 dark:border-slate-800 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Terminal size={16} className="text-red-500 dark:text-red-400" />
                      <span className="text-sm font-bold text-slate-700 dark:text-slate-300">
                        System Instruction
                      </span>
                    </div>
                    {currentExchange.systemPrompt && (
                      <CopyButton
                        content={currentExchange.systemPrompt}
                        className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700"
                      />
                    )}
                  </div>
                  <div className="p-6 overflow-x-auto bg-gray-50 dark:bg-transparent">
                    {currentExchange.systemPrompt ? (
                      <pre className="text-sm font-mono text-slate-800 dark:text-slate-300 whitespace-pre-wrap leading-relaxed selection:bg-red-200 dark:selection:bg-red-900/30">
                        {currentExchange.systemPrompt}
                      </pre>
                    ) : (
                      <div className="text-gray-500 dark:text-slate-500 italic text-sm text-center py-8">
                        No system prompt found in this request.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Tools View */}
            {activeTab === 'tools' && (
              <>
                {/* Sticky bar: always rendered to avoid layout thrash/flicker while scrolling */}
                <div
                  className={`sticky top-0 z-10 -mx-6 bg-white dark:bg-[#0f172a] border-b shadow-sm ${
                    stickyToolInfo.name
                      ? 'border-orange-200 dark:border-orange-800/50'
                      : 'border-gray-200 dark:border-slate-800'
                  }`}
                >
                  <div className="px-6">
                    <div className="max-w-4xl mx-auto">
                      <div className="flex items-center justify-between h-12">
                        {stickyToolInfo.name ? (
                          <>
                            {/* Clickable area to scroll to tool */}
                            <div
                              className="flex items-center gap-3 cursor-pointer hover:opacity-80 transition-opacity flex-1"
                              onClick={() => stickyToolInfo.scrollFn?.()}
                              title="Click to scroll to this tool"
                            >
                              <div className="p-1.5 bg-orange-100 dark:bg-orange-950/50 rounded text-orange-600 dark:text-orange-400">
                                <Box size={14} />
                              </div>
                              <span className="font-mono font-bold text-sm text-orange-700 dark:text-orange-300">
                                {stickyToolInfo.name}
                              </span>
                            </div>
                            {/* Collapse button */}
                            <button
                              className="p-1.5 hover:bg-orange-100 dark:hover:bg-orange-900/30 rounded transition-colors"
                              onClick={() => stickyToolInfo.toggleFn?.()}
                              title="Collapse this tool"
                              type="button"
                            >
                              <ChevronDown size={16} className="text-orange-500 dark:text-orange-400" />
                            </button>
                          </>
                        ) : (
                          <>
                            <h3 className="text-base font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                              <Box size={18} className="text-orange-500 dark:text-orange-400" />
                              Available Tools
                            </h3>
                            <span className="text-xs bg-gray-100 dark:bg-slate-800 px-3 py-1 rounded-full text-slate-500 dark:text-slate-400 border border-gray-200 dark:border-slate-700">
                              {currentExchange.tools?.length || 0} definitions
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="max-w-4xl mx-auto pt-4">
                  {currentExchange.tools && currentExchange.tools.length > 0 ? (
                    <ToolsList
                      tools={currentExchange.tools}
                      scrollContainerRef={chatScrollRef}
                      onStickyToolChange={handleStickyToolChange}
                    />
                  ) : (
                    <div className="p-12 text-center text-slate-500 border border-dashed border-gray-200 dark:border-slate-800 rounded-xl bg-gray-50 dark:bg-slate-900/20">
                      <Box size={32} className="mx-auto mb-3 opacity-20" />
                      No tools defined in this request.
                    </div>
                  )}
                </div>
              </>
            )}

            {/* Raw JSON View */}
            {activeTab === 'raw' && (
              <div className="flex flex-col h-full">
                <div className="flex justify-end mb-4">
                  <button
                    onClick={() => setIsJsonWrapped((prev) => !prev)}
                    className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition"
                    type="button"
                  >
                    <WrapText size={14} />
                    {isJsonWrapped ? '关闭换行' : '自动换行'}
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-6 h-full">
                  <div className="flex flex-col h-full overflow-hidden">
                    <div className="text-xs font-bold text-slate-500 dark:text-slate-400 mb-3 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-blue-500"></div>
                        Request Body
                      </div>
                      {requestBodyText && (
                        <CopyButton
                          content={requestBodyText}
                          className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700"
                        />
                      )}
                    </div>
                    <div className="flex-1 overflow-hidden rounded-lg shadow-inner border border-gray-200 dark:border-transparent">
                      <JSONViewer data={currentExchange.rawRequest} wrap={isJsonWrapped} />
                    </div>
                  </div>
                  <div className="flex flex-col h-full overflow-hidden">
                    <div className="text-xs font-bold text-slate-500 dark:text-slate-400 mb-3 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-green-500"></div>
                        Response Body
                      </div>
                      {responseBodyText && (
                        <CopyButton
                          content={responseBodyText}
                          className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700"
                        />
                      )}
                    </div>
                    <div className="flex-1 overflow-hidden rounded-lg shadow-inner border border-gray-200 dark:border-transparent">
                      {currentExchange.rawResponse ? (
                        <JSONViewer data={currentExchange.rawResponse} wrap={isJsonWrapped} />
                      ) : (
                        <div className="h-full p-4 bg-gray-50 dark:bg-slate-900/30 border border-gray-200 dark:border-slate-800 rounded text-slate-500 text-xs font-mono flex items-center justify-center">
                          Response file missing or corrupt
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {activeTab === 'chat' && (
            <div className="absolute bottom-6 right-6 flex flex-col gap-3 z-30">
              <button
                onClick={() => scrollChatTo('top')}
                className={`p-3 rounded-full border border-gray-200 dark:border-slate-700 shadow-lg bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-200 transition hover:-translate-y-0.5 hover:bg-blue-50 dark:hover:bg-slate-800/80 ${
                  chatScrollEdges.atTop
                    ? 'opacity-40 cursor-not-allowed hover:translate-y-0 hover:bg-white dark:hover:bg-slate-900'
                    : ''
                }`}
                aria-label="Scroll to top"
                disabled={chatScrollEdges.atTop}
                type="button"
              >
                <ArrowUp size={16} />
              </button>
              <button
                onClick={() => scrollChatTo('bottom')}
                className={`p-3 rounded-full border border-gray-200 dark:border-slate-700 shadow-lg bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-200 transition hover:translate-y-0.5 hover:bg-blue-50 dark:hover:bg-slate-800/80 ${
                  chatScrollEdges.atBottom
                    ? 'opacity-40 cursor-not-allowed hover:translate-y-0 hover:bg-white dark:hover:bg-slate-900'
                    : ''
                }`}
                aria-label="Scroll to bottom"
                disabled={chatScrollEdges.atBottom}
                type="button"
              >
                <ArrowDown size={16} />
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-slate-400 dark:text-slate-600 flex-col gap-6 bg-white dark:bg-[#0f172a]">
          <div className="w-20 h-20 bg-gray-100 dark:bg-slate-800/50 rounded-full flex items-center justify-center animate-pulse">
            <Activity size={32} className="opacity-40" />
          </div>
          <p className="text-sm font-medium tracking-wide uppercase opacity-70">
            Select a request to inspect details
          </p>
        </div>
      )}
    </div>
  );
};

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Box,
  ChevronDown,
  FileJson,
  LineChart,
  MessageSquare,
  Terminal,
  WrapText,
  Zap,
} from 'lucide-react';
import type { NormalizedExchange } from '../../types';
import { safeJSONStringify } from '../../utils/ui';
import { ChatBubble } from '../chat/ChatBubble';
import { CopyButton } from '../common/CopyButton';
import { JSONViewer } from '../common/JSONViewer';
import { TokenBadge } from '../common/TokenBadge';
import { ToolsList } from '../tools/ToolsList';

const TABS = [
  { id: 'chat', icon: MessageSquare, label: 'Chat' },
  { id: 'system', icon: Terminal, label: 'System' },
  { id: 'tools', icon: Box, label: 'Tools' },
  { id: 'stats', icon: LineChart, label: 'Statistical' },
  { id: 'raw', icon: FileJson, label: 'JSON' },
] as const;

type TabId = (typeof TABS)[number]['id'];

const DEFAULT_VISIBLE_REQUESTS = 50;

const toSeconds = (milliseconds: number) => milliseconds / 1000;

export const ExchangeDetailsPane: React.FC<{
  currentExchange: NormalizedExchange | null;
  sessionExchanges: NormalizedExchange[];
}> = ({ currentExchange, sessionExchanges }) => {
  const [activeTab, setActiveTab] = useState<TabId>('chat');
  const [chatScrollEdges, setChatScrollEdges] = useState({ atTop: true, atBottom: true });
  const [isJsonWrapped, setIsJsonWrapped] = useState(false);
  const [brushStartIndex, setBrushStartIndex] = useState(0);
  const [brushEndIndex, setBrushEndIndex] = useState(DEFAULT_VISIBLE_REQUESTS - 1);

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

  const statsSummary = useMemo(() => {
    if (sessionExchanges.length === 0) {
      return { totalLatencySeconds: 0, averageLatencySeconds: 0, requestCount: 0 };
    }

    const totalLatencyMs = sessionExchanges.reduce((sum, exchange) => sum + exchange.latencyMs, 0);
    const requestCount = sessionExchanges.length;

    return {
      totalLatencySeconds: toSeconds(totalLatencyMs),
      averageLatencySeconds: toSeconds(totalLatencyMs / requestCount),
      requestCount,
    };
  }, [sessionExchanges]);

  const chartData = useMemo(
    () =>
      sessionExchanges.map((exchange, index) => ({
        id: exchange.id,
        requestIndex: index + 1,
        latencySeconds: toSeconds(exchange.latencyMs),
      })),
    [sessionExchanges]
  );

  const [brushDrag, setBrushDrag] = useState<{
    mode: 'move' | 'left' | 'right';
    startX: number;
    startStart: number;
    startEnd: number;
  } | null>(null);
  const brushTrackRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chartData.length === 0) {
      setBrushStartIndex(0);
      setBrushEndIndex(0);
      return;
    }

    setBrushStartIndex((prev) => Math.min(prev, chartData.length - 1));
    setBrushEndIndex((prev) => {
      const minEnd = Math.min(DEFAULT_VISIBLE_REQUESTS - 1, chartData.length - 1);
      if (prev < 0) return minEnd;
      return Math.min(prev, chartData.length - 1);
    });
  }, [chartData.length]);

  const selectedRange = useMemo(() => {
    if (chartData.length === 0) {
      return { start: 0, end: 0, count: 0 };
    }

    const start = Math.max(0, Math.min(brushStartIndex, chartData.length - 1));
    const end = Math.max(start, Math.min(brushEndIndex, chartData.length - 1));

    return {
      start,
      end,
      count: end - start + 1,
    };
  }, [brushStartIndex, brushEndIndex, chartData.length]);

  const visibleData = useMemo(
    () => chartData.slice(selectedRange.start, selectedRange.end + 1),
    [chartData, selectedRange]
  );

  const visibleMaxLatency = useMemo(
    () => Math.max(1, ...visibleData.map((item) => item.latencySeconds)),
    [visibleData]
  );

  const overviewMaxLatency = useMemo(
    () => Math.max(1, ...chartData.map((item) => item.latencySeconds)),
    [chartData]
  );

  const visibleAverageSeconds = useMemo(() => {
    if (visibleData.length === 0) {
      return 0;
    }

    const visibleTotal = visibleData.reduce((sum, item) => sum + item.latencySeconds, 0);
    return visibleTotal / visibleData.length;
  }, [visibleData]);

  useEffect(() => {
    if (!brushDrag || chartData.length <= 1) {
      return;
    }

    const handlePointerMove = (event: MouseEvent) => {
      const trackRect = brushTrackRef.current?.getBoundingClientRect();
      if (!trackRect || trackRect.width === 0) return;

      const total = chartData.length - 1;
      const delta = Math.round(((event.clientX - brushDrag.startX) / trackRect.width) * total);

      if (brushDrag.mode === 'move') {
        const windowSize = brushDrag.startEnd - brushDrag.startStart;
        const nextStart = Math.max(0, Math.min(brushDrag.startStart + delta, total - windowSize));
        const nextEnd = Math.min(total, nextStart + windowSize);
        setBrushStartIndex(nextStart);
        setBrushEndIndex(nextEnd);
        return;
      }

      if (brushDrag.mode === 'left') {
        const nextStart = Math.max(0, Math.min(brushDrag.startStart + delta, brushDrag.startEnd - 1));
        setBrushStartIndex(nextStart);
        return;
      }

      const nextEnd = Math.min(total, Math.max(brushDrag.startEnd + delta, brushDrag.startStart + 1));
      setBrushEndIndex(nextEnd);
    };

    const handlePointerUp = () => setBrushDrag(null);

    window.addEventListener('mousemove', handlePointerMove);
    window.addEventListener('mouseup', handlePointerUp);

    return () => {
      window.removeEventListener('mousemove', handlePointerMove);
      window.removeEventListener('mouseup', handlePointerUp);
    };
  }, [brushDrag, chartData.length]);

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


            {/* Statistical View */}
            {activeTab === 'stats' && (
              <div className="max-w-6xl mx-auto w-full">
                <div className="bg-white dark:bg-[#0d1117] border border-gray-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                      <LineChart size={16} className="text-indigo-500" />
                      Request Latency Trend
                    </h3>
                    {chartData.length > 0 && (
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        Showing #{selectedRange.start + 1} - #{selectedRange.end + 1} / {chartData.length}
                      </span>
                    )}
                  </div>

                  {chartData.length > 0 ? (
                    <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/30 p-3 space-y-4">
                      <div className="w-full h-[52vh] min-h-[320px] max-h-[640px]">
                        <svg viewBox="0 0 1000 420" className="w-full h-full" role="img" aria-label="Session request latency chart">
                          {Array.from({ length: 6 }).map((_, tickIndex) => {
                            const tickValue = Math.round((visibleMaxLatency * (5 - tickIndex)) / 5);
                            const y = 30 + tickIndex * ((360 - 30) / 5);

                            return (
                              <g key={`visible-y-tick-${tickValue}-${tickIndex}`}>
                                <line
                                  x1={60}
                                  y1={y}
                                  x2={970}
                                  y2={y}
                                  stroke="currentColor"
                                  className="text-gray-200 dark:text-slate-700"
                                  strokeDasharray="4 4"
                                />
                                <text x={50} y={y + 4} textAnchor="end" fontSize="11" className="fill-slate-500 dark:fill-slate-400">
                                  {tickValue}
                                </text>
                              </g>
                            );
                          })}

                          {visibleData.map((item, index) => {
                            const barWidth = Math.max(2, 860 / Math.max(visibleData.length, 1));
                            const barSpacing = 860 / Math.max(visibleData.length, 1);
                            const x = 70 + index * barSpacing;
                            const barHeight = Math.max(2, (item.latencySeconds / visibleMaxLatency) * 300);
                            const y = 360 - barHeight;
                            const isLabelTick = visibleData.length <= 12 || index % Math.ceil(visibleData.length / 8) === 0;

                            return (
                              <g key={item.id}>
                                <rect x={x} y={y} width={Math.max(1, barWidth - 2)} height={barHeight} rx={2} className="fill-indigo-500" />
                                <title>{`Request #${item.requestIndex}: ${item.latencySeconds.toFixed(1)} s`}</title>
                                {isLabelTick && (
                                  <text x={x + barWidth / 2} y={380} textAnchor="middle" fontSize="11" className="fill-slate-500 dark:fill-slate-400">
                                    {item.requestIndex}
                                  </text>
                                )}
                              </g>
                            );
                          })}

                          <text
                            x={28}
                            y={195}
                            textAnchor="middle"
                            transform="rotate(-90 28 195)"
                            className="fill-slate-500 dark:fill-slate-400"
                            fontSize="12"
                          >
                            Latency (s)
                          </text>
                          <text x={520} y={408} textAnchor="middle" className="fill-slate-500 dark:fill-slate-400" fontSize="12">
                            Request Index
                          </text>
                        </svg>
                      </div>

                      <div className="rounded-md border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900/40 p-3 space-y-2">
                        <p className="text-xs text-slate-500 dark:text-slate-400">Brush Bar (drag center to move, drag handles to resize)</p>
                        <svg viewBox="0 0 1000 90" className="w-full h-16">
                          {chartData.map((item, index) => {
                            const barSpacing = 920 / Math.max(chartData.length, 1);
                            const x = 60 + index * barSpacing;
                            const barHeight = Math.max(2, (item.latencySeconds / overviewMaxLatency) * 50);
                            const y = 70 - barHeight;
                            return <rect key={`overview-${item.id}`} x={x} y={y} width={Math.max(1, barSpacing - 1)} height={barHeight} className="fill-slate-400/70 dark:fill-slate-500/60" />;
                          })}
                        </svg>

                        <div
                          ref={brushTrackRef}
                          className="relative h-8 rounded bg-slate-200/70 dark:bg-slate-800"
                          onMouseDown={(event) => {
                            const track = brushTrackRef.current?.getBoundingClientRect();
                            if (!track || chartData.length <= 1) return;

                            const left = (selectedRange.start / (chartData.length - 1)) * track.width;
                            const right = (selectedRange.end / (chartData.length - 1)) * track.width;
                            const offsetX = event.clientX - track.left;
                            const edgeThreshold = 10;

                            const mode: 'move' | 'left' | 'right' =
                              Math.abs(offsetX - left) < edgeThreshold
                                ? 'left'
                                : Math.abs(offsetX - right) < edgeThreshold
                                  ? 'right'
                                  : 'move';

                            setBrushDrag({
                              mode,
                              startX: event.clientX,
                              startStart: selectedRange.start,
                              startEnd: selectedRange.end,
                            });
                          }}
                        >
                          <div
                            className="absolute top-0 h-full bg-indigo-500/35 border border-indigo-500 rounded cursor-grab"
                            style={{
                              left: `${(selectedRange.start / Math.max(chartData.length - 1, 1)) * 100}%`,
                              width: `${((selectedRange.end - selectedRange.start) / Math.max(chartData.length - 1, 1)) * 100}%`,
                            }}
                          >
                            <div className="absolute left-0 top-0 h-full w-2 bg-indigo-600 cursor-ew-resize" />
                            <div className="absolute right-0 top-0 h-full w-2 bg-indigo-600 cursor-ew-resize" />
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500 italic text-center py-8">No request data available for statistics.</div>
                  )}

                  <div className="grid grid-cols-4 gap-3 mt-5">
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Total Time</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{statsSummary.totalLatencySeconds.toFixed(1)} s</p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Average Time (All)</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{Math.round(statsSummary.averageLatencySeconds)} s</p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Average Time (Visible)</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{Math.round(visibleAverageSeconds)} s</p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Request Count</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{statsSummary.requestCount}</p>
                    </div>
                  </div>
                </div>
              </div>
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

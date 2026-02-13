import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Box,
  ChevronDown,
  FileJson,
  LineChart as LineChartIcon,
  MessageSquare,
  Terminal,
  Wrench,
  WrapText,
  Zap,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
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
  { id: 'stats', icon: LineChartIcon, label: 'Statistical' },
  { id: 'raw', icon: FileJson, label: 'JSON' },
] as const;

type TabId = (typeof TABS)[number]['id'];
const DEFAULT_BRUSH_VISIBLE_POINTS = 50;

const formatSecondsFromMs = (ms: number, maximumFractionDigits = 3) =>
  (ms / 1000).toLocaleString(undefined, { maximumFractionDigits });
const formatInteger = (value: number) => value.toLocaleString();
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;
const asToolName = (value: unknown) =>
  typeof value === 'string' && value.trim().length > 0 ? value : 'unknown';

export const ExchangeDetailsPane: React.FC<{
  currentExchange: NormalizedExchange | null;
  sessionExchanges: NormalizedExchange[];
}> = ({ currentExchange, sessionExchanges }) => {
  const [activeTab, setActiveTab] = useState<TabId>('chat');
  const [chatScrollEdges, setChatScrollEdges] = useState({ atTop: true, atBottom: true });
  const [isJsonWrapped, setIsJsonWrapped] = useState(false);

  const chatScrollRef = useRef<HTMLDivElement>(null);
  const [latencyBrushRange, setLatencyBrushRange] = useState<{
    startIndex: number;
    endIndex: number;
  } | null>(null);
  const [tokenBrushRange, setTokenBrushRange] = useState<{
    startIndex: number;
    endIndex: number;
  } | null>(null);
  const [toolBrushRange, setToolBrushRange] = useState<{
    startIndex: number;
    endIndex: number;
  } | null>(null);

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
      return { totalLatencyMs: 0, averageLatencyMs: 0, requestCount: 0 };
    }

    const totalLatencyMs = sessionExchanges.reduce((sum, exchange) => sum + exchange.latencyMs, 0);
    const requestCount = sessionExchanges.length;

    return {
      totalLatencyMs,
      averageLatencyMs: totalLatencyMs / requestCount,
      requestCount,
    };
  }, [sessionExchanges]);

  const latencyChartData = useMemo(
    () =>
      sessionExchanges.map((exchange, index) => ({
        id: exchange.id,
        requestIndex: index + 1,
        latencySec: exchange.latencyMs / 1000,
      })),
    [sessionExchanges]
  );

  const tokenChartData = useMemo(
    () =>
      sessionExchanges.map((exchange, index) => ({
        id: exchange.id,
        requestIndex: index + 1,
        totalTokens: exchange.usage?.total_tokens ?? 0,
        inputTokens: exchange.usage?.input_tokens ?? 0,
        outputTokens: exchange.usage?.output_tokens ?? 0,
      })),
    [sessionExchanges]
  );

  const tokenSummary = useMemo(() => {
    if (sessionExchanges.length === 0) {
      return {
        totalTokens: 0,
        averageTokens: 0,
        totalInputTokens: 0,
        totalOutputTokens: 0,
      };
    }

    const totals = sessionExchanges.reduce(
      (acc, exchange) => {
        acc.totalTokens += exchange.usage?.total_tokens ?? 0;
        acc.totalInputTokens += exchange.usage?.input_tokens ?? 0;
        acc.totalOutputTokens += exchange.usage?.output_tokens ?? 0;
        return acc;
      },
      { totalTokens: 0, totalInputTokens: 0, totalOutputTokens: 0 }
    );

    return {
      ...totals,
      averageTokens: totals.totalTokens / sessionExchanges.length,
    };
  }, [sessionExchanges]);

  const toolTimelineData = useMemo(() => {
    const rows: Array<{ requestIndex: number; toolName: string; eventIndex: number; toolIndex: number }> = [];
    const firstSeenToolIndexes = new Map<string, number>();

    const getToolIndex = (toolName: string) => {
      const existing = firstSeenToolIndexes.get(toolName);
      if (typeof existing === 'number') {
        return existing;
      }
      const next = firstSeenToolIndexes.size;
      firstSeenToolIndexes.set(toolName, next);
      return next;
    };

    const pushToolUseFromContent = (content: unknown, requestIndex: number) => {
      if (!Array.isArray(content)) return;
      content.forEach((block) => {
        if (!isRecord(block) || block.type !== 'tool_use') return;
        const toolName = asToolName(block.name);
        rows.push({
          requestIndex,
          toolName,
          eventIndex: rows.length + 1,
          toolIndex: getToolIndex(toolName),
        });
      });
    };

    sessionExchanges.forEach((exchange, idx) => {
      const requestIndex = idx + 1;
      exchange.messages.forEach((message) => pushToolUseFromContent(message.content, requestIndex));
      pushToolUseFromContent(exchange.responseContent, requestIndex);
    });

    return rows;
  }, [sessionExchanges]);

  const toolNamesInOrder = useMemo(
    () =>
      Array.from(
        toolTimelineData.reduce((map, row) => {
          if (!map.has(row.toolIndex)) {
            map.set(row.toolIndex, row.toolName);
          }
          return map;
        }, new Map<number, string>())
      )
        .sort((a, b) => a[0] - b[0])
        .map((entry) => entry[1]),
    [toolTimelineData]
  );

  const toolCallCounts = useMemo(
    () =>
      Array.from(
        toolTimelineData.reduce((acc, row) => {
          acc.set(row.toolName, (acc.get(row.toolName) ?? 0) + 1);
          return acc;
        }, new Map<string, number>())
      )
        .map(([toolName, count]) => ({ toolName, count }))
        .sort((a, b) => b.count - a.count || a.toolName.localeCompare(b.toolName)),
    [toolTimelineData]
  );

  const toolSummary = useMemo(() => {
    const totalToolCalls = toolTimelineData.length;
    const uniqueTools = toolCallCounts.length;
    return {
      totalToolCalls,
      uniqueTools,
      averageToolCallsPerRequest:
        sessionExchanges.length > 0 ? totalToolCalls / sessionExchanges.length : 0,
    };
  }, [toolCallCounts.length, toolTimelineData.length, sessionExchanges.length]);

  useEffect(() => {
    if (sessionExchanges.length === 0) {
      setLatencyBrushRange(null);
      setTokenBrushRange(null);
      setToolBrushRange(null);
      return;
    }

    const endIndex = sessionExchanges.length - 1;
    const startIndex = Math.max(0, sessionExchanges.length - DEFAULT_BRUSH_VISIBLE_POINTS);
    setLatencyBrushRange({ startIndex, endIndex });
    setTokenBrushRange({ startIndex, endIndex });
  }, [sessionExchanges]);

  useEffect(() => {
    if (toolTimelineData.length === 0) {
      setToolBrushRange(null);
      return;
    }

    const endIndex = toolTimelineData.length - 1;
    const startIndex = Math.max(0, toolTimelineData.length - DEFAULT_BRUSH_VISIBLE_POINTS);
    setToolBrushRange({ startIndex, endIndex });
  }, [toolTimelineData]);

  const handleLatencyBrushChange = useCallback(
    (range: { startIndex?: number; endIndex?: number }) => {
      if (typeof range.startIndex !== 'number' || typeof range.endIndex !== 'number') {
        return;
      }
      setLatencyBrushRange({ startIndex: range.startIndex, endIndex: range.endIndex });
    },
    []
  );

  const handleTokenBrushChange = useCallback(
    (range: { startIndex?: number; endIndex?: number }) => {
      if (typeof range.startIndex !== 'number' || typeof range.endIndex !== 'number') {
        return;
      }
      setTokenBrushRange({ startIndex: range.startIndex, endIndex: range.endIndex });
    },
    []
  );

  const handleToolBrushChange = useCallback(
    (range: { startIndex?: number; endIndex?: number }) => {
      if (typeof range.startIndex !== 'number' || typeof range.endIndex !== 'number') {
        return;
      }
      setToolBrushRange({ startIndex: range.startIndex, endIndex: range.endIndex });
    },
    []
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
              <div className="w-full">
                <div className="bg-white dark:bg-[#0d1117] border border-gray-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                      <LineChartIcon size={16} className="text-indigo-500" />
                      Request Latency Trend
                    </h3>
                    <span className="text-xs text-slate-500 dark:text-slate-400">Y: Latency (s) · X: Request #</span>
                  </div>

                  {latencyChartData.length > 0 ? (
                    <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/30 p-3 h-[420px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={latencyChartData} margin={{ top: 14, right: 22, left: 8, bottom: 12 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.3} />
                          <XAxis
                            dataKey="requestIndex"
                            tick={{ fontSize: 11, fill: '#64748b' }}
                            tickLine={false}
                            axisLine={{ stroke: '#94a3b8', strokeOpacity: 0.3 }}
                            minTickGap={20}
                          />
                          <YAxis
                            tick={{ fontSize: 11, fill: '#64748b' }}
                            tickLine={false}
                            axisLine={{ stroke: '#94a3b8', strokeOpacity: 0.3 }}
                            tickFormatter={(value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 3 })}
                            width={72}
                            label={{
                              value: 'Latency (s)',
                              angle: -90,
                              position: 'insideLeft',
                              offset: -4,
                              fill: '#64748b',
                              fontSize: 12,
                            }}
                          />
                          <Tooltip
                            formatter={(value) => [
                              `${Number(value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 3 })} s`,
                              'Latency',
                            ]}
                            labelFormatter={(label) => `Request #${String(label ?? '-')}`}
                          />
                          <Line
                            type="monotone"
                            dataKey="latencySec"
                            name="Latency"
                            stroke="#6366f1"
                            strokeWidth={2.5}
                            dot={false}
                            activeDot={{ r: 4 }}
                            isAnimationActive={false}
                          />
                          {latencyBrushRange && (
                            <Brush
                              dataKey="requestIndex"
                              height={30}
                              travellerWidth={10}
                              stroke="#6366f1"
                              startIndex={latencyBrushRange.startIndex}
                              endIndex={latencyBrushRange.endIndex}
                              onChange={handleLatencyBrushChange}
                            />
                          )}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500 italic text-center py-8">No request data available for statistics.</div>
                  )}

                  <div className="grid grid-cols-3 gap-3 mt-5">
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Total Time</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{formatSecondsFromMs(statsSummary.totalLatencyMs, 2)} s</p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Average Time</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{formatSecondsFromMs(statsSummary.averageLatencyMs, 3)} s</p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Request Count</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">{statsSummary.requestCount}</p>
                    </div>
                  </div>

                  <div className="mt-6">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                        <LineChartIcon size={16} className="text-violet-500" />
                        Request Token Usage
                      </h3>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        Y: Tokens · X: Request #
                      </span>
                    </div>

                    {tokenChartData.length > 0 ? (
                      <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/30 p-3 h-[320px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={tokenChartData}
                            margin={{ top: 14, right: 22, left: 8, bottom: 12 }}
                            barCategoryGap={0}
                            barGap={0}
                          >
                            <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.3} />
                            <XAxis
                              dataKey="requestIndex"
                              tick={{ fontSize: 11, fill: '#64748b' }}
                              tickLine={false}
                              axisLine={{ stroke: '#94a3b8', strokeOpacity: 0.3 }}
                              minTickGap={20}
                            />
                            <YAxis
                              tick={{ fontSize: 11, fill: '#64748b' }}
                              tickLine={false}
                              axisLine={{ stroke: '#94a3b8', strokeOpacity: 0.3 }}
                              tickFormatter={(value: number) => formatInteger(value)}
                              width={72}
                              label={{
                                value: 'Tokens',
                                angle: -90,
                                position: 'insideLeft',
                                offset: -4,
                                fill: '#64748b',
                                fontSize: 12,
                              }}
                            />
                            <Tooltip
                              formatter={(value) => [formatInteger(Number(value ?? 0)), 'Total Tokens']}
                              labelFormatter={(label) => `Request #${String(label ?? '-')}`}
                            />
                            <Bar
                              dataKey="totalTokens"
                              name="Total Tokens"
                              fill="#8b5cf6"
                              isAnimationActive={false}
                            />
                            {tokenBrushRange && (
                              <Brush
                                dataKey="requestIndex"
                                height={30}
                                travellerWidth={10}
                                stroke="#8b5cf6"
                                startIndex={tokenBrushRange.startIndex}
                                endIndex={tokenBrushRange.endIndex}
                                onChange={handleTokenBrushChange}
                              />
                            )}
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <div className="text-sm text-slate-500 italic text-center py-8">
                        No token data available for statistics.
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-4 gap-3 mt-5">
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Total Tokens</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {formatInteger(tokenSummary.totalTokens)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Average Tokens</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {formatInteger(Math.round(tokenSummary.averageTokens))}
                      </p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Input Tokens</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {formatInteger(tokenSummary.totalInputTokens)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Output Tokens</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {formatInteger(tokenSummary.totalOutputTokens)}
                      </p>
                    </div>
                  </div>

                  <div className="mt-6">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                        <Wrench size={16} className="text-orange-500" />
                        Tool Call Timeline
                      </h3>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        Y: Tool Name · X: Request #
                      </span>
                    </div>

                    {toolTimelineData.length > 0 ? (
                      <div className="rounded-lg border border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/30 p-3 h-[360px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <ComposedChart
                            data={toolTimelineData}
                            margin={{ top: 14, right: 22, left: 8, bottom: 12 }}
                          >
                            <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.3} />
                            <XAxis
                              dataKey="requestIndex"
                              tick={{ fontSize: 11, fill: '#64748b' }}
                              tickLine={false}
                              axisLine={{ stroke: '#94a3b8', strokeOpacity: 0.3 }}
                              minTickGap={20}
                            />
                            <YAxis
                              dataKey="toolIndex"
                              type="number"
                              domain={[0, Math.max(toolNamesInOrder.length - 1, 0)]}
                              ticks={toolNamesInOrder.map((_, idx) => idx)}
                              allowDecimals={false}
                              tick={{ fontSize: 11, fill: '#64748b' }}
                              tickLine={false}
                              axisLine={{ stroke: '#94a3b8', strokeOpacity: 0.3 }}
                              tickFormatter={(value: number) => toolNamesInOrder[value] ?? `tool-${value}`}
                              width={140}
                              label={{
                                value: 'Tool Name',
                                angle: -90,
                                position: 'insideLeft',
                                offset: -4,
                                fill: '#64748b',
                                fontSize: 12,
                              }}
                            />
                            <Tooltip
                              formatter={(_, __, payload) => {
                                if (!payload?.payload || !isRecord(payload.payload)) {
                                  return ['-', 'Tool'];
                                }
                                return [String(payload.payload.toolName ?? '-'), 'Tool'];
                              }}
                              labelFormatter={(_, payload) => {
                                if (!payload || payload.length === 0 || !isRecord(payload[0].payload)) {
                                  return 'Request #-';
                                }
                                return `Request #${String(payload[0].payload.requestIndex ?? '-')}`;
                              }}
                            />
                            <Line
                              type="monotone"
                              dataKey="toolIndex"
                              stroke="#f97316"
                              strokeWidth={1.25}
                              dot={false}
                              activeDot={false}
                              isAnimationActive={false}
                              connectNulls={false}
                            />
                            <Scatter
                              dataKey="toolIndex"
                              fill="#ea580c"
                              isAnimationActive={false}
                              legendType="none"
                              shape="circle"
                            />
                            {toolBrushRange && (
                              <Brush
                                dataKey="eventIndex"
                                height={30}
                                travellerWidth={10}
                                stroke="#f97316"
                                startIndex={toolBrushRange.startIndex}
                                endIndex={toolBrushRange.endIndex}
                                onChange={handleToolBrushChange}
                              />
                            )}
                          </ComposedChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <div className="text-sm text-slate-500 italic text-center py-8">
                        No tool call data available for statistics.
                      </div>
                    )}
                  </div>

                  <div className="grid grid-cols-3 gap-3 mt-5">
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Total Tool Calls</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {formatInteger(toolSummary.totalToolCalls)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Unique Tools</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {formatInteger(toolSummary.uniqueTools)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-gray-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900/40">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Avg Calls / Request</p>
                      <p className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                        {toolSummary.averageToolCallsPerRequest.toLocaleString(undefined, {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </p>
                    </div>
                  </div>

                  <div className="mt-5 rounded-lg border border-gray-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900/40">
                    <div className="px-4 py-3 border-b border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-900/70">
                      <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                        Tool Call Counts
                      </h4>
                    </div>
                    {toolCallCounts.length > 0 ? (
                      <div className="max-h-[260px] overflow-auto custom-scrollbar">
                        <table className="w-full text-sm">
                          <thead className="sticky top-0 bg-white dark:bg-slate-900/95">
                            <tr className="text-left border-b border-gray-200 dark:border-slate-700">
                              <th className="px-4 py-2 font-semibold text-slate-600 dark:text-slate-300">
                                Tool Name
                              </th>
                              <th className="px-4 py-2 font-semibold text-slate-600 dark:text-slate-300 text-right">
                                Calls
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {toolCallCounts.map((row) => (
                              <tr
                                key={row.toolName}
                                className="border-b border-gray-100 dark:border-slate-800 last:border-b-0"
                              >
                                <td className="px-4 py-2 font-mono text-slate-700 dark:text-slate-200">
                                  {row.toolName}
                                </td>
                                <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-200">
                                  {formatInteger(row.count)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="px-4 py-6 text-sm text-slate-500 italic text-center">
                        No tool calls were found in this session.
                      </div>
                    )}
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

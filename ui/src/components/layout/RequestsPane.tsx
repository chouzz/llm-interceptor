import React, { useState, useCallback, useMemo, memo } from 'react';
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Cpu,
  Filter,
  MessageCircle,
  Pencil,
  X,
} from 'lucide-react';
import type { AnnotationData, NormalizedExchange } from '../../types';
import { formatTimestamp } from '../../utils';
import { stringToColor } from '../../utils/ui';
import { Tooltip } from '../common/Tooltip';

export const RequestsPane: React.FC<{
  width: number;
  isCollapsed: boolean;
  setIsCollapsed: (v: boolean) => void;
  onStartResize: (e: React.MouseEvent) => void;

  currentSessionName?: string;
  filteredExchanges: NormalizedExchange[];
  selectedExchangeId: string | null;
  onSelectExchange: (exchangeId: string) => void;

  systemPromptFilter: string | null;
  setSystemPromptFilter: (v: string | null) => void;

  selectedSessionId: string | null;
  annotations: Record<string, AnnotationData>;
  onUpdateRequestNote: (sessionId: string, sequenceId: string, note: string) => void;
}> = ({
  width,
  isCollapsed,
  setIsCollapsed,
  onStartResize,
  currentSessionName,
  filteredExchanges,
  selectedExchangeId,
  onSelectExchange,
  systemPromptFilter,
  setSystemPromptFilter,
  selectedSessionId,
  annotations,
  onUpdateRequestNote,
}) => {
  const [editingRequestNote, setEditingRequestNote] = useState<string | null>(null);

  // Cache expensive color calculations
  const exchangeColors = useMemo(() => {
    const colors: Record<string, string> = {};
    filteredExchanges.forEach(exchange => {
      colors[exchange.id] = stringToColor(exchange.systemPrompt);
    });
    return colors;
  }, [filteredExchanges]);

  // Memoize callback functions to prevent unnecessary re-renders
  const handleToggleCollapse = useCallback(() => {
    setIsCollapsed(!isCollapsed);
  }, [isCollapsed, setIsCollapsed]);

  const handleClearFilter = useCallback(() => {
    setSystemPromptFilter(null);
  }, [setSystemPromptFilter]);

  // Memoize computed values
  const requestCount = useMemo(() => filteredExchanges.length, [filteredExchanges.length]);

  // Memoize the rendered request items
  const renderedRequests = useMemo(() => {
    return filteredExchanges.map((exchange) => {
      const systemHashColor = exchangeColors[exchange.id];
      const isSelected = selectedExchangeId === exchange.id;
      const seqId = exchange.sequenceId || exchange.id;
      const requestNote = selectedSessionId ? annotations[selectedSessionId]?.requests?.[seqId] || '' : '';
      const hasRequestNote = requestNote.length > 0;
      const isEditingRequest = editingRequestNote === seqId;

      return (
        <RequestItem
          key={exchange.id}
          exchange={exchange}
          isSelected={isSelected}
          isCollapsed={isCollapsed}
          systemHashColor={systemHashColor}
          requestNote={requestNote}
          hasRequestNote={hasRequestNote}
          isEditingRequest={isEditingRequest}
          onSelectExchange={onSelectExchange}
          onSetIsCollapsed={setIsCollapsed}
          onSetEditingRequestNote={setEditingRequestNote}
          onSetSystemPromptFilter={setSystemPromptFilter}
          onUpdateRequestNote={onUpdateRequestNote}
          selectedSessionId={selectedSessionId}
        />
      );
    });
  }, [
    filteredExchanges,
    selectedExchangeId,
    isCollapsed,
    editingRequestNote,
    selectedSessionId,
    annotations,
    onSelectExchange,
    setIsCollapsed,
    setSystemPromptFilter,
    onUpdateRequestNote,
    exchangeColors,
  ]);

  return (
    <div
      style={{ width: isCollapsed ? '48px' : width }}
      className="flex-shrink-0 border-r border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-[#0f172a] flex flex-col relative transition-all duration-300 ease-in-out"
    >
      {/* Requests Header */}
      <div
        className={`p-4 border-b border-gray-200 dark:border-slate-800 h-[57px] flex items-center bg-white dark:bg-[#0f172a] ${
          isCollapsed ? 'justify-center' : 'justify-between'
        }`}
      >
        {!isCollapsed && (
          <div className="flex flex-col overflow-hidden">
            <h2 className="font-bold text-xs tracking-wide text-slate-500 dark:text-slate-400 uppercase">
              Requests
            </h2>
            <div className="text-xs text-slate-600 dark:text-slate-300 truncate font-medium">
              {currentSessionName || 'Select a session'}
            </div>
          </div>
        )}
        <div className="flex items-center gap-2">
          {!isCollapsed && (
            <span className="text-[10px] bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 px-2 py-0.5 rounded-full border border-gray-200 dark:border-slate-700 shadow-sm">
              {requestCount}
            </span>
          )}
          <button
            onClick={handleToggleCollapse}
            className="p-1.5 hover:bg-gray-100 dark:hover:bg-slate-800 rounded text-slate-500 dark:text-slate-400 transition-colors"
            type="button"
          >
            {isCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>
      </div>

      {/* Filter Banner */}
      {!isCollapsed && systemPromptFilter && (
        <div className="bg-blue-100 dark:bg-blue-900/30 px-4 py-2 flex items-center justify-between text-xs text-blue-800 dark:text-blue-200 border-b border-blue-200 dark:border-blue-800">
          <span className="font-medium flex items-center gap-2">
            <Filter size={12} />
            Filtered by System Prompt
          </span>
          <button onClick={handleClearFilter} className="hover:text-blue-600" type="button">
            <X size={14} />
          </button>
        </div>
      )}

      <div className="overflow-y-auto flex-1 custom-scrollbar bg-white dark:bg-[#0f172a]">
        {renderedRequests}
      </div>

      {/* Resizer Handle */}
      {!isCollapsed && (
        <div
          className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-blue-500/50 transition-colors z-10 flex items-center justify-center group"
          onMouseDown={onStartResize}
        >
          <div className="w-[1px] h-full bg-gray-200 dark:bg-slate-800 group-hover:bg-blue-500"></div>
        </div>
      )}
    </div>
  );
};

export const MemoizedRequestsPane = memo(RequestsPane);

// Memoized individual request item component for performance
const RequestItem = React.memo<{
  exchange: NormalizedExchange;
  isSelected: boolean;
  isCollapsed: boolean;
  systemHashColor: string;
  requestNote: string;
  hasRequestNote: boolean;
  isEditingRequest: boolean;
  onSelectExchange: (exchangeId: string) => void;
  onSetIsCollapsed: (collapsed: boolean) => void;
  onSetEditingRequestNote: (seqId: string | null) => void;
  onSetSystemPromptFilter: (color: string) => void;
  onUpdateRequestNote: (sessionId: string, sequenceId: string, note: string) => void;
  selectedSessionId: string | null;
}>(({
  exchange,
  isSelected,
  isCollapsed,
  systemHashColor,
  requestNote,
  hasRequestNote,
  isEditingRequest,
  onSelectExchange,
  onSetIsCollapsed,
  onSetEditingRequestNote,
  onSetSystemPromptFilter,
  onUpdateRequestNote,
  selectedSessionId,
}) => {
  const seqId = exchange.sequenceId || exchange.id;

  const handleSelectExchange = useCallback(() => {
    onSelectExchange(exchange.id);
  }, [exchange.id, onSelectExchange]);

  const handleCollapsedSelect = useCallback(() => {
    onSelectExchange(exchange.id);
    onSetIsCollapsed(false);
  }, [exchange.id, onSelectExchange, onSetIsCollapsed]);

  const handleToggleEdit = useCallback(() => {
    onSetEditingRequestNote(isEditingRequest ? null : seqId);
  }, [isEditingRequest, seqId, onSetEditingRequestNote]);

  const handleFilterBySystemPrompt = useCallback(() => {
    onSetSystemPromptFilter(systemHashColor);
  }, [systemHashColor, onSetSystemPromptFilter]);

  const handleUpdateNote = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (selectedSessionId) {
      onUpdateRequestNote(selectedSessionId, seqId, e.target.value);
    }
  }, [selectedSessionId, seqId, onUpdateRequestNote]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      onSetEditingRequestNote(null);
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSetEditingRequestNote(null);
    }
  }, [onSetEditingRequestNote]);

  const handleSaveNote = useCallback(() => {
    onSetEditingRequestNote(null);
  }, [onSetEditingRequestNote]);

  const handleEditNote = useCallback(() => {
    onSetEditingRequestNote(seqId);
  }, [seqId, onSetEditingRequestNote]);

  if (isCollapsed) {
    return (
      <div
        onClick={handleCollapsedSelect}
        className={`h-12 flex items-center justify-center cursor-pointer border-b border-gray-100 dark:border-slate-800/50 relative ${
          isSelected ? 'bg-blue-50 dark:bg-slate-800' : ''
        }`}
      >
        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: systemHashColor }} />
        {hasRequestNote && (
          <div className="absolute top-1 right-1 w-1.5 h-1.5 bg-amber-500 rounded-full"></div>
        )}
      </div>
    );
  }

  return (
    <div>
      <div
        onClick={handleSelectExchange}
        className={`px-4 py-3 border-b border-gray-100 dark:border-slate-800/50 cursor-pointer transition-colors group relative ${
          isSelected ? 'bg-blue-50 dark:bg-slate-800/80 shadow-md z-10' : 'hover:bg-gray-50 dark:hover:bg-slate-800/30'
        }`}
      >
        {/* Colored indicator for System Prompt grouping */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1 transition-all"
          style={{ backgroundColor: systemHashColor, opacity: isSelected ? 1 : 0.6 }}
        ></div>

        {/* Action Buttons (appear on hover) */}
        <div className="absolute right-2 top-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity z-20">
          <button
            onClick={handleToggleEdit}
            className="p-1.5 bg-white dark:bg-slate-700 rounded shadow-sm hover:scale-110"
            title="Edit note"
            type="button"
          >
            <Pencil size={12} className="text-slate-500 dark:text-slate-300" />
          </button>
          <button
            onClick={handleFilterBySystemPrompt}
            className="p-1.5 bg-white dark:bg-slate-700 rounded shadow-sm hover:scale-110"
            title="Filter by this System Prompt"
            type="button"
          >
            <Filter size={12} className="text-slate-500 dark:text-slate-300" />
          </button>
        </div>

        <div className="flex items-center justify-between mb-1.5 pl-2">
          <div className="flex items-center gap-2">
            {exchange.sequenceId && (
              <span
                className="text-xs font-mono font-bold px-1.5 py-0.5 rounded border shadow-sm"
                style={{
                  borderColor: isSelected ? 'transparent' : `${systemHashColor}40`,
                  backgroundColor: isSelected ? systemHashColor : `${systemHashColor}15`,
                  color: isSelected ? '#ffffff' : systemHashColor,
                }}
              >
                {exchange.sequenceId}
              </span>
            )}
            <span
              className={`text-[10px] font-bold px-1.5 py-0.5 rounded shadow-sm border ${
                exchange.rawRequest.method === 'POST'
                  ? 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-400 border-green-200 dark:border-green-900/30'
                  : 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 border-blue-200 dark:border-blue-900/30'
              }`}
            >
              {exchange.rawRequest.method}
            </span>
            {hasRequestNote && <MessageCircle size={10} className="text-amber-500 flex-shrink-0" />}
          </div>
          <span
            className={`text-[10px] font-mono flex items-center gap-1 px-1 rounded ${
              isSelected
                ? 'text-slate-600 dark:text-slate-300'
                : 'text-slate-400 dark:text-slate-500 bg-gray-100 dark:bg-slate-900/50'
            }`}
          >
            <Clock size={10} />
            {formatTimestamp(exchange.timestamp)}
          </span>
        </div>
        <div
          className={`text-xs font-mono truncate mb-2 pl-2 transition-opacity ${
            isSelected
              ? 'text-slate-800 dark:text-white font-medium'
              : 'text-slate-600 dark:text-slate-400 opacity-80 group-hover:opacity-100'
          }`}
          title={exchange.rawRequest.url}
        >
          {exchange.rawRequest.url.split('/').pop()}
        </div>
        <div className="flex items-center justify-between text-[10px] text-slate-500 pl-2">
          <div className="flex items-center gap-1.5">
            <Cpu
              size={10}
              className={
                exchange.model.includes('sonnet')
                  ? 'text-purple-500 dark:text-purple-400'
                  : 'text-slate-400 dark:text-slate-600'
              }
            />
            <span className={`truncate max-w-[100px] ${isSelected ? 'dark:text-slate-300' : ''}`}>
              {exchange.model}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {exchange.latencyMs > 0 && (
              <span className={`${isSelected ? 'dark:text-slate-300' : 'text-slate-500 dark:text-slate-600'}`}>
                {(exchange.latencyMs / 1000).toFixed(2)}s
              </span>
            )}
            {exchange.rawResponse ? (
              <span
                className={`font-bold px-1 rounded ${
                  exchange.statusCode === 200
                    ? 'text-green-600 dark:text-green-500 bg-green-100 dark:bg-green-900/10'
                    : 'text-red-600 dark:text-red-500 bg-red-100 dark:bg-red-900/10'
                }`}
              >
                {exchange.statusCode}
              </span>
            ) : (
              <span className="text-yellow-600 dark:text-yellow-500 font-bold px-1 rounded bg-yellow-100 dark:bg-yellow-900/10">
                N/A
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Inline Note Editor for Request */}
      {isEditingRequest && selectedSessionId && (
        <div className="mx-2 my-1 border-b border-gray-100 dark:border-slate-800/50 pb-2">
          <div className="relative">
            <textarea
              autoFocus
              value={requestNote}
              onChange={handleUpdateNote}
              onKeyDown={handleKeyDown}
              placeholder="Add a note... (Enter to save, Shift+Enter for newline)"
              className="w-full text-xs p-2 pr-8 border border-amber-300 dark:border-amber-700 rounded-md bg-amber-50 dark:bg-amber-950/30 text-slate-700 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 resize-none focus:outline-none focus:ring-2 focus:ring-amber-400 dark:focus:ring-amber-600"
              rows={2}
            />
            <button
              onClick={handleSaveNote}
              className="absolute top-1.5 right-1.5 p-1 hover:bg-amber-200 dark:hover:bg-amber-800 rounded text-amber-600 dark:text-amber-400"
              title="Done (Enter)"
              type="button"
            >
              <Check size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Display Note (when not editing) */}
      {!isEditingRequest && hasRequestNote && (
        <Tooltip text={requestNote}>
          <div
            className="mx-2 my-1 px-2 py-1.5 text-[10px] text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/20 rounded border-l-2 border-amber-400 dark:border-amber-600 cursor-pointer hover:bg-amber-100 dark:hover:bg-amber-950/30 transition-colors border-b border-gray-100 dark:border-slate-800/50"
            onClick={handleEditNote}
            title="Click to edit"
          >
            <div className="line-clamp-2">{requestNote}</div>
          </div>
        </Tooltip>
      )}
    </div>
  );
});

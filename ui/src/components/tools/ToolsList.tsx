import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Box, ChevronDown, ChevronRight, Code } from 'lucide-react';
import type { NormalizedTool } from '../../types';
import { JSONViewer } from '../common/JSONViewer';

// Tools list with sticky header support
export const ToolsList: React.FC<{
  tools: NormalizedTool[];
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  onStickyToolChange?: (
    toolName: string | null,
    toggleFn: (() => void) | null,
    scrollFn: (() => void) | null
  ) => void;
}> = ({ tools, scrollContainerRef, onStickyToolChange }) => {
  const [stickyToolName, setStickyToolName] = useState<string | null>(null);
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());
  const toolsContainerRef = useRef<HTMLDivElement>(null);
  const toolRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const toggleTool = useCallback((toolName: string) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolName)) {
        next.delete(toolName);
      } else {
        next.add(toolName);
      }
      return next;
    });
  }, []);

  const scrollToTool = useCallback(
    (toolName: string) => {
      const toolEl = toolRefs.current.get(toolName);
      const scrollContainer = scrollContainerRef.current;
      if (!toolEl || !scrollContainer) return;

      // Calculate the scroll position to bring the tool header to the top
      const containerRect = scrollContainer.getBoundingClientRect();
      const toolRect = toolEl.getBoundingClientRect();
      const scrollTop = scrollContainer.scrollTop + toolRect.top - containerRect.top;

      scrollContainer.scrollTo({ top: scrollTop, behavior: 'smooth' });
    },
    [scrollContainerRef]
  );

  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    const toolsContainer = toolsContainerRef.current;
    if (!scrollContainer || !toolsContainer) return;

    let rafId: number | null = null;
    const options: AddEventListenerOptions = { passive: true };

    // Small buffer to avoid flicker around sub-pixel boundaries when the header crosses the top edge.
    const EDGE_EPSILON_PX = 1;

    const updateStickyTool = () => {
      const toolElements = toolsContainer.querySelectorAll<HTMLElement>('[data-tool-name]');

      // Sticky calculations must be done relative to the scroll container viewport, not the window.
      const containerRect = scrollContainer.getBoundingClientRect();
      const viewportTop = containerRect.top + EDGE_EPSILON_PX;

      let currentTool: string | null = null;

      toolElements.forEach((el) => {
        const toolName = el.getAttribute('data-tool-name');
        const toolHeader = el.querySelector<HTMLElement>('.tool-header');
        const toolContent = el.querySelector<HTMLElement>('.tool-content');

        if (!toolName) return;
        // Only show sticky header for expanded tools
        if (!expandedTools.has(toolName)) return;
        if (!toolHeader || !toolContent) return;

        const headerRect = toolHeader.getBoundingClientRect();
        const contentRect = toolContent.getBoundingClientRect();

        // More stable rule:
        // - header is above the scroll container top
        // - and the tool's content spans the top edge of the scroll container
        const headerIsAboveTop = headerRect.bottom <= viewportTop;
        const contentSpansTop = contentRect.top < viewportTop && contentRect.bottom > viewportTop;

        if (headerIsAboveTop && contentSpansTop) {
          currentTool = toolName;
        }
      });

      // Avoid unnecessary state updates (and layout churn) while scrolling.
      setStickyToolName((prev) => (Object.is(prev, currentTool) ? prev : currentTool));
    };

    const handleScroll = () => {
      if (rafId != null) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        updateStickyTool();
      });
    };

    scrollContainer.addEventListener('scroll', handleScroll, options);
    handleScroll(); // Initial check (via rAF)

    return () => {
      if (rafId != null) {
        window.cancelAnimationFrame(rafId);
      }
      scrollContainer.removeEventListener('scroll', handleScroll, options);
    };
  }, [expandedTools, scrollContainerRef, tools]);

  // Notify parent about sticky tool changes
  useEffect(() => {
    if (!onStickyToolChange) return;

    if (stickyToolName) {
      onStickyToolChange(
        stickyToolName,
        () => toggleTool(stickyToolName),
        () => scrollToTool(stickyToolName)
      );
    } else {
      onStickyToolChange(null, null, null);
    }
  }, [onStickyToolChange, scrollToTool, stickyToolName, toggleTool]);

  return (
    <div ref={toolsContainerRef} className="relative">
      <div className="grid gap-3">
        {tools.map((tool, i) => (
          <ToolDefinitionControlled
            key={i}
            tool={tool}
            expanded={expandedTools.has(tool.name)}
            onToggle={() => toggleTool(tool.name)}
            ref={(el) => {
              if (el) {
                toolRefs.current.set(tool.name, el);
              } else {
                toolRefs.current.delete(tool.name);
              }
            }}
          />
        ))}
      </div>
    </div>
  );
};

// Controlled version of ToolDefinition for use with ToolsList
const ToolDefinitionControlled = React.forwardRef<
  HTMLDivElement,
  { tool: NormalizedTool; expanded: boolean; onToggle: () => void }
>(({ tool, expanded, onToggle }, ref) => {
  return (
    <div
      ref={ref}
      data-tool-name={tool.name}
      className="border border-gray-200 dark:border-gray-800 rounded-lg bg-white dark:bg-slate-900 overflow-hidden transition-all hover:border-gray-300 dark:hover:border-gray-700 shadow-sm"
    >
      <div
        className="tool-header px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50 transition"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <div className="p-1.5 bg-orange-100 dark:bg-orange-950/50 rounded text-orange-600 dark:text-orange-400">
            <Box size={16} />
          </div>
          <span className="font-mono font-bold text-sm text-slate-700 dark:text-orange-100">
            {tool.name}
          </span>
        </div>
        {expanded ? (
          <ChevronDown size={16} className="text-gray-400 dark:text-gray-500" />
        ) : (
          <ChevronRight size={16} className="text-gray-400 dark:text-gray-500" />
        )}
      </div>
      {expanded && (
        <div className="tool-content p-4 border-t border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-black/20">
          {tool.description && (
            <div className="mb-4 text-sm text-slate-600 dark:text-gray-400 italic bg-white dark:bg-slate-900 p-3 rounded border-l-2 border-gray-300 dark:border-gray-700 whitespace-pre-wrap break-words">
              {tool.description}
            </div>
          )}
          <div className="text-[10px] font-bold text-gray-500 mb-2 uppercase tracking-wide flex items-center gap-2">
            <Code size={12} />
            Input Schema
          </div>
          <JSONViewer data={tool.input_schema} />
        </div>
      )}
    </div>
  );
});

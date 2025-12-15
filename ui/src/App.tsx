import React, { useState, useMemo, useEffect, useRef } from 'react';
import {
  FolderOpen,
  Activity,
  Clock,
  MessageSquare,
  Terminal,
  Code,
  Cpu,
  ChevronRight,
  ChevronDown,
  ChevronLeft,
  Search,
  FileJson,
  Zap,
  Box,
  Moon,
  Sun,
  Filter,
  X,
  RefreshCw,
  Pencil,
  MessageCircle,
  Check,
  Copy,
  ArrowUp,
  ArrowDown,
  WrapText
} from 'lucide-react';
import type { Session, NormalizedMessage, NormalizedTool, SessionSummary, AnnotationData } from './types';
import { normalizeSession, formatTimestamp } from './utils';

// Debounce helper for auto-saving annotations
function debounce<T extends (...args: any[]) => any>(fn: T, delay: number): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}

// Copy to clipboard helper
const copyToClipboard = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    console.error('Failed to copy:', err);
    return false;
  }
};

// Extract text content from message content (handles various formats)
const extractTextContent = (content: string | any[] | any): string => {
  if (typeof content === 'string') {
    return content;
  }
  if (Array.isArray(content)) {
    return content.map(block => {
      if (block.type === 'text') return block.text;
      if (block.type === 'tool_use') return `[Tool Call: ${block.name}]\n${JSON.stringify(block.input, null, 2)}`;
      if (block.type === 'tool_result') {
        const resultContent = typeof block.content === 'string' ? block.content : JSON.stringify(block.content, null, 2);
        return `[Tool Result: ${block.tool_use_id}]\n${resultContent}`;
      }
      return JSON.stringify(block, null, 2);
    }).join('\n\n');
  }
  if (typeof content === 'object' && content !== null) {
    return JSON.stringify(content, null, 2);
  }
  return String(content);
};

// Tooltip component for long text
const Tooltip: React.FC<{ text: string; children: React.ReactNode }> = ({ text, children }) => {
  const [show, setShow] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseEnter = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setPosition({ x: rect.left, y: rect.bottom + 4 });
    setShow(true);
  };

  return (
    <div
      ref={containerRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => setShow(false)}
      className="relative"
    >
      {children}
      {show && text && (
        <div
          className="fixed z-50 max-w-md p-2 text-xs bg-slate-900 dark:bg-slate-700 text-white rounded-md shadow-lg whitespace-pre-wrap break-words"
          style={{ left: position.x, top: position.y }}
        >
          {text}
        </div>
      )}
    </div>
  );
};

// Copy button component with feedback
const CopyButton: React.FC<{ content: string; className?: string }> = ({ content, className = "" }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const success = await copyToClipboard(content);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className={`p-1 rounded hover:bg-gray-200 dark:hover:bg-slate-700 transition-colors ${className}`}
      title={copied ? "Copied!" : "Copy to clipboard"}
    >
      {copied ? (
        <Check size={12} className="text-green-500" />
      ) : (
        <Copy size={12} className="text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300" />
      )}
    </button>
  );
};

// API Base URL - empty for relative path (production), or localhost for dev
const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';

// --- Helper for color generation ---
const stringToColor = (str: string | undefined) => {
  if (!str) return '#94a3b8'; // Default slate-400
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash);
  }
  const c = (hash & 0x00ffffff).toString(16).toUpperCase();
  return '#' + '00000'.substring(0, 6 - c.length) + c;
};

const safeJSONStringify = (value: any, space = 2) => {
  try {
    return JSON.stringify(value, null, space);
  } catch (error) {
    console.error('Failed to stringify JSON data', error);
    return '';
  }
};

// --- Sub-components ---

const JSONViewer: React.FC<{ data: any; wrap?: boolean }> = ({ data, wrap = false }) => (
  <pre className={`text-xs font-mono bg-gray-50 dark:bg-black/40 p-4 rounded overflow-auto max-h-[600px] text-green-700 dark:text-green-400 border border-gray-200 dark:border-gray-800 custom-scrollbar ${wrap ? 'whitespace-pre-wrap break-words' : 'whitespace-pre'}`}>
    {safeJSONStringify(data)}
  </pre>
);

const TokenBadge: React.FC<{ usage?: { input_tokens: number, output_tokens: number } }> = ({ usage }) => {
  if (!usage) return null;
  const inputTokens = typeof usage.input_tokens === 'number' ? usage.input_tokens : 0;
  const outputTokens = typeof usage.output_tokens === 'number' ? usage.output_tokens : 0;
  return (
    <div className="flex gap-3 text-xs font-mono text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded border border-gray-200 dark:border-gray-700">
      <span className="flex items-center gap-1"><span className="text-blue-600 dark:text-blue-400">In:</span> {inputTokens.toLocaleString()}</span>
      <span className="flex items-center gap-1"><span className="text-purple-600 dark:text-purple-400">Out:</span> {outputTokens.toLocaleString()}</span>
      <span className="flex items-center gap-1 text-gray-400 border-l border-gray-300 dark:border-gray-600 pl-2">Total: {(inputTokens + outputTokens).toLocaleString()}</span>
    </div>
  );
};

const ToolCallBlock: React.FC<{ content: any }> = ({ content }) => {
  // Default expanded to true as requested
  const [expanded, setExpanded] = useState(true);
  const toolCallText = `[Tool Call: ${content.name}]\n${JSON.stringify(content.input, null, 2)}`;

  return (
    <div className="my-2 border border-yellow-500/30 dark:border-yellow-600/50 bg-yellow-50 dark:bg-yellow-950/20 rounded-md overflow-hidden group/tool shadow-sm">
      <div
        className="px-3 py-2 bg-yellow-100/50 dark:bg-yellow-900/30 flex items-center gap-2 cursor-pointer hover:bg-yellow-200/50 dark:hover:bg-yellow-900/50 transition select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <Terminal size={14} className="text-yellow-600 dark:text-yellow-500" />
        <span className="text-xs font-bold text-yellow-700 dark:text-yellow-500 font-mono">Tool Call: {content.name}</span>
        <div className="flex-1" />
        <CopyButton content={toolCallText} className="opacity-0 group-hover/tool:opacity-100" />
        {expanded ? <ChevronDown size={14} className="text-yellow-600 dark:text-yellow-500" /> : <ChevronRight size={14} className="text-yellow-600 dark:text-yellow-500 opacity-50 group-hover/tool:opacity-100"/>}
      </div>
      {expanded && (
        <div className="p-3 bg-white dark:bg-black/20">
             <div className="text-[10px] uppercase text-gray-400 dark:text-gray-500 mb-1 font-semibold tracking-wider">Arguments</div>
            <pre className="text-xs font-mono text-yellow-800 dark:text-yellow-100/80 overflow-x-auto whitespace-pre-wrap break-all custom-scrollbar">
              {JSON.stringify(content.input, null, 2)}
            </pre>
        </div>
      )}
    </div>
  );
}

const MessageContent: React.FC<{ content: string | any[] | any }> = ({ content }) => {
  // Handle String content
  if (typeof content === 'string') {
    return <div className="whitespace-pre-wrap leading-relaxed break-words text-slate-700 dark:text-slate-100 font-medium">{content}</div>;
  }

  // Handle Array of Content Blocks (Anthropic/OpenAI standardized)
  if (Array.isArray(content)) {
    return (
      <div className="space-y-3">
        {content.map((block, idx) => {
          if (block.type === 'text') {
            return <div key={idx} className="whitespace-pre-wrap leading-relaxed break-words text-slate-700 dark:text-slate-100 font-medium">{block.text}</div>;
          }
          if (block.type === 'tool_use') {
            return <ToolCallBlock key={idx} content={block} />;
          }
          if (block.type === 'tool_result') {
             // Determine how to render the tool result content
             let renderedResult;
             if (typeof block.content === 'string') {
                renderedResult = block.content;
             } else {
                // Pretty print objects/arrays
                renderedResult = JSON.stringify(block.content, null, 2);
             }

             return (
               <div key={idx} className="text-xs border-l-2 border-emerald-500 pl-3 py-2 my-2 bg-emerald-50 dark:bg-emerald-900/10 rounded-r overflow-hidden group/result">
                 <div className="font-bold text-emerald-600 dark:text-emerald-500 text-[10px] uppercase mb-1 flex items-center gap-2">
                    <Zap size={10} />
                    Tool Result ({block.tool_use_id})
                    <CopyButton content={renderedResult} className="opacity-0 group-hover/result:opacity-100" />
                 </div>
                 {/* Use whitespace-pre-wrap to handle newlines and break-words to wrap long lines */}
                 <div className="font-mono text-emerald-800 dark:text-emerald-200/90 whitespace-pre-wrap break-words max-h-[500px] overflow-y-auto custom-scrollbar">
                   {renderedResult}
                 </div>
               </div>
             )
          }
          return <div key={idx} className="text-xs text-gray-500 italic border border-gray-200 dark:border-gray-800 p-2 rounded">[Unknown Block Type: {block.type}]</div>;
        })}
      </div>
    );
  }

  // Handle Plain Objects (e.g., pure JSON responses from models)
  if (typeof content === 'object' && content !== null) {
      return (
        <div className="font-mono text-xs text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-black/20 p-3 rounded border border-emerald-200 dark:border-emerald-900/30 overflow-x-auto">
             <pre className="whitespace-pre-wrap break-words custom-scrollbar">{JSON.stringify(content, null, 2)}</pre>
        </div>
      );
  }

  return <div className="text-red-500 dark:text-red-400">Unrenderable content type</div>;
};

const ChatBubble: React.FC<{ message: NormalizedMessage }> = ({ message }) => {
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
        <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-1 shadow-md ring-2 ring-opacity-20 ${
          isUser
            ? 'bg-blue-600 ring-blue-400'
            : 'bg-purple-600 ring-purple-400'
        }`}>
           {isUser ? <Search size={16} className="text-white"/> : <Zap size={16} className="text-white"/>}
        </div>

        {/* Content Bubble */}
        <div className={`rounded-2xl p-4 shadow-sm text-sm border relative overflow-hidden ${
          isUser
            ? 'bg-blue-50 dark:bg-slate-800 border-blue-200 dark:border-slate-700 rounded-tr-sm text-slate-800 dark:text-slate-100'
            : 'bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-800 rounded-tl-sm text-slate-800 dark:text-slate-200'
        }`}>
          <div className={`text-[10px] uppercase tracking-wider font-bold opacity-60 mb-2 flex items-center gap-2 text-slate-500 dark:text-slate-400 ${isUser ? 'justify-end' : 'justify-start'}`}>
            {message.role}
            <CopyButton content={textContent} className="opacity-0 group-hover/bubble:opacity-100" />
          </div>
          <MessageContent content={message.content} />
        </div>
      </div>
    </div>
  );
};

// Tools list with sticky header support
const ToolsList: React.FC<{ tools: NormalizedTool[]; scrollContainerRef: React.RefObject<HTMLDivElement | null> }> = ({ tools, scrollContainerRef }) => {
  const [stickyToolName, setStickyToolName] = useState<string | null>(null);
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());
  const toolsContainerRef = useRef<HTMLDivElement>(null);
  const toolRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const toggleTool = (toolName: string) => {
    setExpandedTools(prev => {
      const next = new Set(prev);
      if (next.has(toolName)) {
        next.delete(toolName);
      } else {
        next.add(toolName);
      }
      return next;
    });
  };

  const scrollToTool = (toolName: string) => {
    const toolEl = toolRefs.current.get(toolName);
    const scrollContainer = scrollContainerRef.current;
    if (!toolEl || !scrollContainer) return;

    // Calculate the scroll position to bring the tool header to the top
    const containerRect = scrollContainer.getBoundingClientRect();
    const toolRect = toolEl.getBoundingClientRect();
    const scrollTop = scrollContainer.scrollTop + toolRect.top - containerRect.top;

    scrollContainer.scrollTo({ top: scrollTop, behavior: 'smooth' });
  };

  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    const toolsContainer = toolsContainerRef.current;
    if (!scrollContainer || !toolsContainer) return;

    const handleScroll = () => {
      const toolElements = toolsContainer.querySelectorAll('[data-tool-name]');
      // The sticky header should appear when tool header is above the content area top
      // Content area starts at top of scrollContainer
      const containerRect = scrollContainer.getBoundingClientRect();
      const viewportTop = containerRect.top;

      let currentTool: string | null = null;

      toolElements.forEach((el) => {
        const toolName = el.getAttribute('data-tool-name');
        const toolHeader = el.querySelector('.tool-header');
        const toolContent = el.querySelector('.tool-content');

        if (!toolName) return;
        // Only show sticky header for expanded tools
        if (!expandedTools.has(toolName)) return;
        if (!toolHeader || !toolContent) return;

        const headerRect = toolHeader.getBoundingClientRect();
        const contentRect = toolContent.getBoundingClientRect();

        // Check if this tool's content is visible but its header is scrolled out of view
        const headerIsAboveViewport = headerRect.bottom < viewportTop;
        const contentIsVisible = contentRect.bottom > viewportTop && contentRect.top < window.innerHeight;

        if (headerIsAboveViewport && contentIsVisible) {
          currentTool = toolName;
        }
      });

      setStickyToolName(currentTool);
    };

    scrollContainer.addEventListener('scroll', handleScroll);
    handleScroll(); // Initial check

    return () => scrollContainer.removeEventListener('scroll', handleScroll);
  }, [scrollContainerRef, tools, expandedTools]);

  return (
    <div ref={toolsContainerRef} className="relative">
      {/* Sticky Tool Name Header - fixed position below main header */}
      {stickyToolName && (
        <div className="sticky top-0 z-10 -mx-6 -mt-6 mb-0 bg-white dark:bg-[#0f172a] border-b border-orange-200 dark:border-orange-800/50 shadow-sm">
          <div className="px-6 py-0">
            <div className="max-w-4xl mx-auto">
              <div className="flex items-center justify-between py-2.5">
                {/* Clickable area to scroll to tool */}
                <div
                  className="flex items-center gap-3 cursor-pointer hover:opacity-80 transition-opacity flex-1"
                  onClick={() => scrollToTool(stickyToolName)}
                  title="Click to scroll to this tool"
                >
                  <div className="p-1.5 bg-orange-100 dark:bg-orange-950/50 rounded text-orange-600 dark:text-orange-400">
                    <Box size={14} />
                  </div>
                  <span className="font-mono font-bold text-sm text-orange-700 dark:text-orange-300">{stickyToolName}</span>
                </div>
                {/* Collapse button */}
                <button
                  className="p-1.5 hover:bg-orange-100 dark:hover:bg-orange-900/30 rounded transition-colors"
                  onClick={() => toggleTool(stickyToolName)}
                  title="Collapse this tool"
                >
                  <ChevronDown size={16} className="text-orange-500 dark:text-orange-400" />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      <div className={`grid gap-3 ${stickyToolName ? 'mt-6' : ''}`}>
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
}

// Controlled version of ToolDefinition for use with ToolsList
const ToolDefinitionControlled = React.forwardRef<HTMLDivElement, { tool: NormalizedTool; expanded: boolean; onToggle: () => void }>(
  ({ tool, expanded, onToggle }, ref) => {
    return (
      <div ref={ref} data-tool-name={tool.name} className="border border-gray-200 dark:border-gray-800 rounded-lg bg-white dark:bg-slate-900 overflow-hidden transition-all hover:border-gray-300 dark:hover:border-gray-700 shadow-sm">
        <div
          className="tool-header px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50 transition"
          onClick={onToggle}
        >
          <div className="flex items-center gap-3">
            <div className="p-1.5 bg-orange-100 dark:bg-orange-950/50 rounded text-orange-600 dark:text-orange-400">
              <Box size={16} />
            </div>
            <span className="font-mono font-bold text-sm text-slate-700 dark:text-orange-100">{tool.name}</span>
          </div>
          {expanded ? <ChevronDown size={16} className="text-gray-400 dark:text-gray-500"/> : <ChevronRight size={16} className="text-gray-400 dark:text-gray-500"/>}
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
  }
);

const TABS = [
  { id: 'chat', icon: MessageSquare, label: 'Chat' },
  { id: 'system', icon: Terminal, label: 'System' },
  { id: 'tools', icon: Box, label: 'Tools' },
  { id: 'raw', icon: FileJson, label: 'JSON' }
] as const;

type TabId = typeof TABS[number]['id'];

// --- Main App Component ---

const App: React.FC = () => {
  // Data State
  const [sessionList, setSessionList] = useState<SessionSummary[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);

  // Selection State
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedExchangeId, setSelectedExchangeId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('chat');

  // Theme State (Default Light)
  const [isDarkMode, setIsDarkMode] = useState(false);

  // Filter State
  const [systemPromptFilter, setSystemPromptFilter] = useState<string | null>(null);

  // Layout State
  const [sessionsWidth, setSessionsWidth] = useState(280);
  const [requestsWidth, setRequestsWidth] = useState(320);
  const [isSessionsCollapsed, setIsSessionsCollapsed] = useState(false);
  const [isRequestsCollapsed, setIsRequestsCollapsed] = useState(false);

  // Resize Refs
  const containerRef = useRef<HTMLDivElement>(null);

  // Annotation State
  const [annotations, setAnnotations] = useState<Record<string, AnnotationData>>({});
  const [editingSessionNote, setEditingSessionNote] = useState<string | null>(null);
  const [editingRequestNote, setEditingRequestNote] = useState<string | null>(null);
  const [chatScrollEdges, setChatScrollEdges] = useState({ atTop: true, atBottom: true });
  const [isJsonWrapped, setIsJsonWrapped] = useState(false);

  // --- Annotation API ---

  const fetchAnnotations = async (sessionId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/annotations`);
      if (res.ok) {
        const data = await res.json();
        setAnnotations(prev => ({ ...prev, [sessionId]: data }));
        return data;
      }
    } catch (error) {
      console.error("Failed to fetch annotations", error);
    }
    return { session_note: "", requests: {} };
  };

  const saveAnnotations = async (sessionId: string, data: AnnotationData) => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/annotations`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (res.ok) {
        setAnnotations(prev => ({ ...prev, [sessionId]: data }));
      }
    } catch (error) {
      console.error("Failed to save annotations", error);
    }
  };

  // Debounced save function (memoized)
  const debouncedSaveAnnotations = useMemo(
    () => debounce((sessionId: string, data: AnnotationData) => {
      saveAnnotations(sessionId, data);
    }, 500),
    []
  );

  const updateSessionNote = (sessionId: string, note: string) => {
    const current = annotations[sessionId] || { session_note: "", requests: {} };
    const updated = { ...current, session_note: note };
    setAnnotations(prev => ({ ...prev, [sessionId]: updated }));
    debouncedSaveAnnotations(sessionId, updated);
  };

  const updateRequestNote = (sessionId: string, sequenceId: string, note: string) => {
    const current = annotations[sessionId] || { session_note: "", requests: {} };
    const updated = {
      ...current,
      requests: { ...current.requests, [sequenceId]: note }
    };
    setAnnotations(prev => ({ ...prev, [sessionId]: updated }));
    debouncedSaveAnnotations(sessionId, updated);
  };

  // --- Data Fetching ---

  const fetchSessionList = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessionList(data);
        return data;
      }
    } catch (error) {
      console.error("Failed to fetch sessions", error);
    }
    return [];
  };

  const fetchSessionDetails = async (sessionId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        // Normalize the API data to UI structure
        const session = normalizeSession(data);
        setCurrentSession(session);

        // Auto-select first exchange if none selected or if switching sessions
        if (session.exchanges.length > 0) {
            // If just loaded a new session, select the last exchange (most recent) or first?
            // Usually last is most relevant.
            setSelectedExchangeId(session.exchanges[session.exchanges.length - 1].id);
        }
      }
    } catch (error) {
      console.error("Failed to fetch session details", error);
    }
  };

  // Poll for session list updates
  useEffect(() => {
    const load = async () => {
      await fetchSessionList();
      setIsLoadingList(false);
    };

    load();
    const interval = setInterval(fetchSessionList, 2000);
    return () => clearInterval(interval);
  }, []);

  // When selectedSessionId changes, fetch details and annotations
  useEffect(() => {
    if (selectedSessionId) {
      fetchSessionDetails(selectedSessionId);
      // Fetch annotations if not already loaded
      if (!annotations[selectedSessionId]) {
        fetchAnnotations(selectedSessionId);
      }
    } else {
      setCurrentSession(null);
    }
  }, [selectedSessionId]);

  // Auto-select the newest session once the list loads, and handle removed sessions
  useEffect(() => {
    if (sessionList.length === 0) {
      if (selectedSessionId !== null) {
        setSelectedSessionId(null);
      }
      setSelectedExchangeId(null);
      return;
    }

    const hasSelection = selectedSessionId && sessionList.some(session => session.id === selectedSessionId);
    if (!hasSelection) {
      setSelectedSessionId(sessionList[0].id);
    }
  }, [sessionList, selectedSessionId]);

  // --- Resizing Logic ---

  const startResizingSessions = (e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = sessionsWidth;

    const onMouseMove = (moveEvent: MouseEvent) => {
      const newWidth = Math.max(200, Math.min(600, startWidth + (moveEvent.clientX - startX)));
      setSessionsWidth(newWidth);
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  const startResizingRequests = (e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = requestsWidth;

    const onMouseMove = (moveEvent: MouseEvent) => {
       const newWidth = Math.max(250, Math.min(600, startWidth + (moveEvent.clientX - startX)));
       setRequestsWidth(newWidth);
    };

    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  // --- Computed Data ---

  const filteredExchanges = useMemo(() => {
    if (!currentSession) return [];
    if (!systemPromptFilter) return currentSession.exchanges;
    return currentSession.exchanges.filter(ex => stringToColor(ex.systemPrompt) === systemPromptFilter);
  }, [currentSession, systemPromptFilter]);

  const chatScrollRef = useRef<HTMLDivElement>(null);

  const currentExchange = useMemo(() =>
    currentSession?.exchanges.find(e => e.id === selectedExchangeId),
  [currentSession, selectedExchangeId]);

  const requestBodyText = useMemo(
    () => (currentExchange ? safeJSONStringify(currentExchange.rawRequest) : ''),
    [currentExchange]
  );

  const responseBodyText = useMemo(
    () => (currentExchange?.rawResponse ? safeJSONStringify(currentExchange.rawResponse) : ''),
    [currentExchange]
  );

  const toggleTheme = () => {
    setIsDarkMode(!isDarkMode);
  };

  // Sync theme with HTML element for global styles (scrollbars etc)
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el || activeTab !== 'chat') {
      setChatScrollEdges({ atTop: true, atBottom: true });
      return;
    }

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      setChatScrollEdges({
        atTop: scrollTop <= 8,
        atBottom: scrollTop + clientHeight >= scrollHeight - 8
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

  // Wrapper for app content
  return (
    <div ref={containerRef} className={`${isDarkMode ? 'dark' : ''} h-screen w-full flex bg-gray-50 dark:bg-[#0f172a] text-slate-900 dark:text-slate-200 overflow-hidden font-sans selection:bg-blue-200 dark:selection:bg-blue-500/30 transition-colors duration-200`}>

      {/* Empty State / Loading */}
      {sessionList.length === 0 && (
        <div className="flex-1 flex flex-col items-center justify-center p-8 text-center relative overflow-hidden bg-gray-50 dark:bg-[#0f172a]">
          <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-20 pointer-events-none"></div>
          <button
             onClick={toggleTheme}
             className="absolute top-6 right-6 p-2 rounded-full bg-white dark:bg-slate-800 shadow-sm border border-gray-200 dark:border-slate-700 hover:scale-110 transition-transform text-slate-600 dark:text-slate-400"
          >
             {isDarkMode ? <Sun size={20} /> : <Moon size={20} />}
          </button>

          <div className="mb-8 p-6 rounded-3xl bg-white dark:bg-slate-800/30 border border-gray-200 dark:border-slate-700/50 shadow-2xl backdrop-blur-sm">
             <FolderOpen size={64} className="text-blue-500 dark:text-blue-400" />
          </div>
          <h1 className="text-5xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-blue-600 via-indigo-600 to-emerald-600 dark:from-blue-400 dark:via-indigo-400 dark:to-emerald-400">
            Claude Code Inspector
          </h1>

          {isLoadingList ? (
             <div className="mt-8 flex items-center gap-3 text-slate-500 dark:text-slate-400">
                <RefreshCw className="animate-spin" size={20} />
                <span>Scanning for sessions...</span>
             </div>
          ) : (
              <p className="max-w-md text-slate-600 dark:text-slate-400 mb-10 leading-relaxed text-lg">
                No sessions found in the traces directory. <br/>
                Run <code>cci watch</code> to capture new sessions.
              </p>
          )}
        </div>
      )}

      {/* Main Content */}
      {sessionList.length > 0 && (
        <>
          {/* Sidebar: Sessions */}
          <div
            style={{ width: isSessionsCollapsed ? '48px' : sessionsWidth }}
            className="flex-shrink-0 border-r border-gray-200 dark:border-slate-800 bg-white dark:bg-[#0b1120] flex flex-col relative transition-all duration-300 ease-in-out"
          >
            {/* Sessions Header */}
            <div className={`p-4 border-b border-gray-200 dark:border-slate-800 flex items-center ${isSessionsCollapsed ? 'justify-center flex-col gap-4' : 'justify-between'}`}>
               {!isSessionsCollapsed && (
                <div className="flex items-center gap-2">
                  <Activity size={18} className="text-blue-600 dark:text-blue-500" />
                  <h2 className="font-bold text-sm tracking-wide text-slate-700 dark:text-slate-200">SESSIONS</h2>
                </div>
               )}

              <div className={`flex ${isSessionsCollapsed ? 'flex-col gap-3' : 'gap-1'}`}>
                 <button onClick={() => setIsSessionsCollapsed(!isSessionsCollapsed)} className="p-1.5 hover:bg-gray-100 dark:hover:bg-slate-800 rounded text-slate-500 dark:text-slate-400 transition-colors" title={isSessionsCollapsed ? "Expand" : "Collapse"}>
                   {isSessionsCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
                 </button>
                 {!isSessionsCollapsed && (
                   <button onClick={toggleTheme} className="p-1.5 hover:bg-gray-100 dark:hover:bg-slate-800 rounded text-slate-500 dark:text-slate-400 transition-colors" title="Toggle Theme">
                      {isDarkMode ? <Sun size={14} /> : <Moon size={14} />}
                   </button>
                 )}
              </div>
            </div>

            {/* Sessions List */}
            <div className="overflow-y-auto flex-1 p-2 space-y-1 custom-scrollbar">
              {sessionList.map(session => {
                const sessionNote = annotations[session.id]?.session_note || "";
                const hasNote = sessionNote.length > 0;
                const isEditing = editingSessionNote === session.id;

                return (
                  <div key={session.id} className="relative">
                    <button
                      onClick={() => {
                        setSelectedSessionId(session.id);
                        if (isSessionsCollapsed) setIsSessionsCollapsed(false);
                      }}
                      className={`w-full text-left rounded-lg text-sm font-medium transition-all duration-200 group relative ${
                        isSessionsCollapsed ? 'p-2 flex justify-center' : 'px-3 py-3'
                      } ${
                        selectedSessionId === session.id
                          ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-200 shadow-inner ring-1 ring-blue-100 dark:ring-blue-900/30'
                          : 'text-slate-500 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800/50 hover:text-slate-800 dark:hover:text-slate-200'
                      }`}
                      title={session.id}
                    >
                      {selectedSessionId === session.id && !isSessionsCollapsed && (
                        <div className="absolute left-0 top-3 bottom-3 w-1 bg-blue-500 rounded-r-full"></div>
                      )}
                      {isSessionsCollapsed ? (
                        <div className="relative">
                          <FolderOpen size={20} className={selectedSessionId === session.id ? 'text-blue-600 dark:text-blue-400' : 'text-slate-400 dark:text-slate-600'} />
                          {hasNote && (
                            <div className="absolute -top-1 -right-1 w-2 h-2 bg-amber-500 rounded-full"></div>
                          )}
                        </div>
                      ) : (
                        <>
                          <div className="flex items-center gap-2.5 mb-1">
                            <FolderOpen size={16} className={selectedSessionId === session.id ? 'text-blue-600 dark:text-blue-400' : 'text-slate-400 dark:text-slate-600 group-hover:text-slate-500'} />
                            <span className="truncate flex-1 font-semibold">{session.id}</span>
                            {hasNote && (
                              <MessageCircle size={12} className="text-amber-500 flex-shrink-0" />
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditingSessionNote(isEditing ? null : session.id);
                              }}
                              className="p-1 hover:bg-gray-200 dark:hover:bg-slate-700 rounded opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                              title="Edit note"
                            >
                              <Pencil size={12} className="text-slate-400 dark:text-slate-500" />
                            </button>
                          </div>
                          <div className="pl-7 text-[10px] text-slate-400 dark:text-slate-500 flex justify-between items-center">
                            <span>{session.request_count} requests</span>
                            <span className="font-mono opacity-50">{formatTimestamp(session.timestamp)}</span>
                          </div>
                        </>
                      )}
                    </button>

                    {/* Inline Note Editor */}
                    {!isSessionsCollapsed && isEditing && (
                      <div className="mx-2 mt-1 mb-2">
                        <div className="relative">
                          <textarea
                            autoFocus
                            value={sessionNote}
                            onChange={(e) => updateSessionNote(session.id, e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Escape') {
                                setEditingSessionNote(null);
                              } else if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                setEditingSessionNote(null);
                              }
                              // Shift+Enter allows natural newline
                            }}
                            placeholder="Add a note... (Enter to save, Shift+Enter for newline)"
                            className="w-full text-xs p-2 pr-8 border border-amber-300 dark:border-amber-700 rounded-md bg-amber-50 dark:bg-amber-950/30 text-slate-700 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 resize-none focus:outline-none focus:ring-2 focus:ring-amber-400 dark:focus:ring-amber-600"
                            rows={2}
                          />
                          <button
                            onClick={() => setEditingSessionNote(null)}
                            className="absolute top-1.5 right-1.5 p-1 hover:bg-amber-200 dark:hover:bg-amber-800 rounded text-amber-600 dark:text-amber-400"
                            title="Done (Enter)"
                          >
                            <Check size={12} />
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Display Note (when not editing) */}
                    {!isSessionsCollapsed && !isEditing && hasNote && (
                      <Tooltip text={sessionNote}>
                        <div
                          className="mx-2 mt-1 mb-2 px-2 py-1.5 text-[10px] text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/20 rounded border-l-2 border-amber-400 dark:border-amber-600 cursor-pointer hover:bg-amber-100 dark:hover:bg-amber-950/30 transition-colors"
                          onClick={() => setEditingSessionNote(session.id)}
                          title="Click to edit"
                        >
                          <div className="line-clamp-2">{sessionNote}</div>
                        </div>
                      </Tooltip>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Resizer Handle */}
            {!isSessionsCollapsed && (
              <div
                className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-blue-500/50 transition-colors z-10 flex items-center justify-center group"
                onMouseDown={startResizingSessions}
              >
                  <div className="w-[1px] h-full bg-gray-200 dark:bg-slate-800 group-hover:bg-blue-500"></div>
              </div>
            )}
          </div>

          {/* Middle Pane: Exchange List */}
          <div
            style={{ width: isRequestsCollapsed ? '48px' : requestsWidth }}
            className="flex-shrink-0 border-r border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-[#0f172a] flex flex-col relative transition-all duration-300 ease-in-out"
          >
            {/* Requests Header */}
            <div className={`p-4 border-b border-gray-200 dark:border-slate-800 h-[57px] flex items-center bg-white dark:bg-[#0f172a] ${isRequestsCollapsed ? 'justify-center' : 'justify-between'}`}>
               {!isRequestsCollapsed && (
                 <div className="flex flex-col overflow-hidden">
                   <h2 className="font-bold text-xs tracking-wide text-slate-500 dark:text-slate-400 uppercase">Requests</h2>
                   <div className="text-xs text-slate-600 dark:text-slate-300 truncate font-medium">{currentSession?.name || "Select a session"}</div>
                 </div>
               )}
               <div className="flex items-center gap-2">
                 {!isRequestsCollapsed && (
                   <span className="text-[10px] bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400 px-2 py-0.5 rounded-full border border-gray-200 dark:border-slate-700 shadow-sm">
                     {filteredExchanges.length}
                   </span>
                 )}
                 <button onClick={() => setIsRequestsCollapsed(!isRequestsCollapsed)} className="p-1.5 hover:bg-gray-100 dark:hover:bg-slate-800 rounded text-slate-500 dark:text-slate-400 transition-colors">
                   {isRequestsCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
                 </button>
               </div>
            </div>

            {/* Filter Banner */}
            {!isRequestsCollapsed && systemPromptFilter && (
              <div className="bg-blue-100 dark:bg-blue-900/30 px-4 py-2 flex items-center justify-between text-xs text-blue-800 dark:text-blue-200 border-b border-blue-200 dark:border-blue-800">
                <span className="font-medium flex items-center gap-2">
                   <Filter size={12} />
                   Filtered by System Prompt
                </span>
                <button onClick={() => setSystemPromptFilter(null)} className="hover:text-blue-600">
                  <X size={14} />
                </button>
              </div>
            )}

            <div className="overflow-y-auto flex-1 custom-scrollbar bg-white dark:bg-[#0f172a]">
              {filteredExchanges.map((exchange) => {
                const systemHashColor = stringToColor(exchange.systemPrompt);
                const isSelected = selectedExchangeId === exchange.id;
                const seqId = exchange.sequenceId || exchange.id;
                const requestNote = selectedSessionId ? (annotations[selectedSessionId]?.requests?.[seqId] || "") : "";
                const hasRequestNote = requestNote.length > 0;
                const isEditingRequest = editingRequestNote === seqId;

                if (isRequestsCollapsed) {
                   return (
                     <div
                        key={exchange.id}
                        onClick={() => {
                          setSelectedExchangeId(exchange.id);
                          setIsRequestsCollapsed(false);
                        }}
                        className={`h-12 flex items-center justify-center cursor-pointer border-b border-gray-100 dark:border-slate-800/50 relative ${isSelected ? 'bg-blue-50 dark:bg-slate-800' : ''}`}
                     >
                       <div className="w-2 h-2 rounded-full" style={{ backgroundColor: systemHashColor }} />
                       {hasRequestNote && (
                         <div className="absolute top-1 right-1 w-1.5 h-1.5 bg-amber-500 rounded-full"></div>
                       )}
                     </div>
                   )
                }

                return (
                  <div key={exchange.id}>
                    <div
                      onClick={() => setSelectedExchangeId(exchange.id)}
                      className={`px-4 py-3 border-b border-gray-100 dark:border-slate-800/50 cursor-pointer transition-colors group relative ${
                        isSelected
                          ? 'bg-blue-50 dark:bg-slate-800/80 shadow-md z-10'
                          : 'hover:bg-gray-50 dark:hover:bg-slate-800/30'
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
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditingRequestNote(isEditingRequest ? null : seqId);
                            }}
                            className="p-1.5 bg-white dark:bg-slate-700 rounded shadow-sm hover:scale-110"
                            title="Edit note"
                         >
                            <Pencil size={12} className="text-slate-500 dark:text-slate-300" />
                         </button>
                         <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSystemPromptFilter(systemHashColor);
                            }}
                            className="p-1.5 bg-white dark:bg-slate-700 rounded shadow-sm hover:scale-110"
                            title="Filter by this System Prompt"
                         >
                            <Filter size={12} className="text-slate-500 dark:text-slate-300" />
                         </button>
                       </div>

                       <div className="flex items-center justify-between mb-1.5 pl-2">
                          <div className="flex items-center gap-2">
                            {exchange.sequenceId && (
                              <span
                                  className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded border shadow-sm`}
                                  style={{
                                      borderColor: isSelected ? 'transparent' : `${systemHashColor}40`, // 40 = 25% opacity hex
                                      backgroundColor: isSelected ? systemHashColor : `${systemHashColor}15`, // 15 = ~8% opacity
                                      color: isSelected ? '#ffffff' : systemHashColor
                                  }}
                              >
                                {exchange.sequenceId}
                              </span>
                            )}
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shadow-sm border ${
                              exchange.rawRequest.method === 'POST'
                                ? 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-400 border-green-200 dark:border-green-900/30'
                                : 'bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 border-blue-200 dark:border-blue-900/30'
                            }`}>
                              {exchange.rawRequest.method}
                            </span>
                            {hasRequestNote && (
                              <MessageCircle size={10} className="text-amber-500 flex-shrink-0" />
                            )}
                          </div>
                          <span className={`text-[10px] font-mono flex items-center gap-1 px-1 rounded ${
                              isSelected ? 'text-slate-600 dark:text-slate-300' : 'text-slate-400 dark:text-slate-500 bg-gray-100 dark:bg-slate-900/50'
                          }`}>
                            <Clock size={10} />
                            {formatTimestamp(exchange.timestamp)}
                          </span>
                       </div>
                       <div className={`text-xs font-mono truncate mb-2 pl-2 transition-opacity ${
                           isSelected ? 'text-slate-800 dark:text-white font-medium' : 'text-slate-600 dark:text-slate-400 opacity-80 group-hover:opacity-100'
                       }`} title={exchange.rawRequest.url}>
                         {exchange.rawRequest.url.split('/').pop()}
                       </div>
                       <div className="flex items-center justify-between text-[10px] text-slate-500 pl-2">
                         <div className="flex items-center gap-1.5">
                            <Cpu size={10} className={exchange.model.includes('sonnet') ? 'text-purple-500 dark:text-purple-400' : 'text-slate-400 dark:text-slate-600'}/>
                            <span className={`truncate max-w-[100px] ${isSelected ? 'dark:text-slate-300' : ''}`}>{exchange.model}</span>
                         </div>
                         <div className="flex items-center gap-1.5">
                            {exchange.latencyMs > 0 && <span className={`${isSelected ? 'dark:text-slate-300' : 'text-slate-500 dark:text-slate-600'}`}>{(exchange.latencyMs / 1000).toFixed(2)}s</span>}
                            {exchange.rawResponse ? (
                              <span className={`font-bold px-1 rounded ${exchange.statusCode === 200 ? 'text-green-600 dark:text-green-500 bg-green-100 dark:bg-green-900/10' : 'text-red-600 dark:text-red-500 bg-red-100 dark:bg-red-900/10'}`}>
                                {exchange.statusCode}
                              </span>
                            ) : (
                              <span className="text-yellow-600 dark:text-yellow-500 font-bold px-1 rounded bg-yellow-100 dark:bg-yellow-900/10">N/A</span>
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
                            onChange={(e) => updateRequestNote(selectedSessionId, seqId, e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Escape') {
                                setEditingRequestNote(null);
                              } else if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                setEditingRequestNote(null);
                              }
                              // Shift+Enter allows natural newline
                            }}
                            placeholder="Add a note... (Enter to save, Shift+Enter for newline)"
                            className="w-full text-xs p-2 pr-8 border border-amber-300 dark:border-amber-700 rounded-md bg-amber-50 dark:bg-amber-950/30 text-slate-700 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 resize-none focus:outline-none focus:ring-2 focus:ring-amber-400 dark:focus:ring-amber-600"
                            rows={2}
                          />
                          <button
                            onClick={() => setEditingRequestNote(null)}
                            className="absolute top-1.5 right-1.5 p-1 hover:bg-amber-200 dark:hover:bg-amber-800 rounded text-amber-600 dark:text-amber-400"
                            title="Done (Enter)"
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
                          onClick={() => setEditingRequestNote(seqId)}
                          title="Click to edit"
                        >
                          <div className="line-clamp-2">{requestNote}</div>
                        </div>
                      </Tooltip>
                    )}
                  </div>
                )
              })}
            </div>

             {/* Resizer Handle */}
            {!isRequestsCollapsed && (
              <div
                className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-blue-500/50 transition-colors z-10 flex items-center justify-center group"
                onMouseDown={startResizingRequests}
              >
                  <div className="w-[1px] h-full bg-gray-200 dark:bg-slate-800 group-hover:bg-blue-500"></div>
              </div>
            )}
          </div>

          {/* Right Pane: Details */}
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
                    {TABS.map(tab => (
                      <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                          activeTab === tab.id
                            ? 'bg-white dark:bg-slate-600 text-slate-900 dark:text-white shadow-sm ring-1 ring-black/5 dark:ring-white/10'
                            : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-gray-200/50 dark:hover:bg-slate-700/50'
                        }`}
                      >
                        <tab.icon size={14} />
                        {tab.label}
                      </button>
                    ))}
                  </div>
                </header>

                {/* Content Area */}
                <div ref={chatScrollRef} className="flex-1 overflow-y-auto p-6 scroll-smooth custom-scrollbar bg-white dark:bg-[#0f172a]">

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
                           <Zap size={12}/>
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
                          <div className="px-4 py-3 bg-gray-100 dark:bg-slate-900 border-b border-gray-200 dark:border-slate-800 flex items-center gap-2">
                            <Terminal size={16} className="text-red-500 dark:text-red-400"/>
                            <span className="text-sm font-bold text-slate-700 dark:text-slate-300">System Instruction</span>
                          </div>
                          <div className="p-6 overflow-x-auto bg-gray-50 dark:bg-transparent">
                            {currentExchange.systemPrompt ? (
                              <pre className="text-sm font-mono text-slate-800 dark:text-slate-300 whitespace-pre-wrap leading-relaxed selection:bg-red-200 dark:selection:bg-red-900/30">
                                {currentExchange.systemPrompt}
                              </pre>
                            ) : (
                              <div className="text-gray-500 dark:text-slate-500 italic text-sm text-center py-8">No system prompt found in this request.</div>
                            )}
                          </div>
                       </div>
                    </div>
                  )}

                  {/* Tools View */}
                  {activeTab === 'tools' && (
                    <div className="max-w-4xl mx-auto">
                       <div className="mb-6 flex items-center justify-between">
                         <h3 className="text-base font-bold text-slate-700 dark:text-slate-200 flex items-center gap-2">
                            <Box size={18} className="text-orange-500 dark:text-orange-400"/>
                            Available Tools
                         </h3>
                         <span className="text-xs bg-gray-100 dark:bg-slate-800 px-3 py-1 rounded-full text-slate-500 dark:text-slate-400 border border-gray-200 dark:border-slate-700">
                           {currentExchange.tools?.length || 0} definitions
                         </span>
                       </div>
                       {currentExchange.tools && currentExchange.tools.length > 0 ? (
                          <ToolsList tools={currentExchange.tools} scrollContainerRef={chatScrollRef} />
                       ) : (
                         <div className="p-12 text-center text-slate-500 border border-dashed border-gray-200 dark:border-slate-800 rounded-xl bg-gray-50 dark:bg-slate-900/20">
                           <Box size={32} className="mx-auto mb-3 opacity-20"/>
                           No tools defined in this request.
                         </div>
                       )}
                    </div>
                  )}

                  {/* Raw JSON View */}
                  {activeTab === 'raw' && (
                    <div className="flex flex-col h-full">
                      <div className="flex justify-end mb-4">
                        <button
                          onClick={() => setIsJsonWrapped(prev => !prev)}
                          className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition"
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
                              <CopyButton content={requestBodyText} className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700" />
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
                              <CopyButton content={responseBodyText} className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700" />
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
                        chatScrollEdges.atTop ? 'opacity-40 cursor-not-allowed hover:translate-y-0 hover:bg-white dark:hover:bg-slate-900' : ''
                      }`}
                      aria-label="Scroll to top"
                      disabled={chatScrollEdges.atTop}
                    >
                      <ArrowUp size={16} />
                    </button>
                    <button
                      onClick={() => scrollChatTo('bottom')}
                      className={`p-3 rounded-full border border-gray-200 dark:border-slate-700 shadow-lg bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-200 transition hover:translate-y-0.5 hover:bg-blue-50 dark:hover:bg-slate-800/80 ${
                        chatScrollEdges.atBottom ? 'opacity-40 cursor-not-allowed hover:translate-y-0 hover:bg-white dark:hover:bg-slate-900' : ''
                      }`}
                      aria-label="Scroll to bottom"
                      disabled={chatScrollEdges.atBottom}
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
                 <p className="text-sm font-medium tracking-wide uppercase opacity-70">Select a request to inspect details</p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default App;

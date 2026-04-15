import { useCallback, useEffect, useRef, useState } from 'react';
import type { Session, SessionSummary, WatchStatus } from '../types';
import { mergeExchangeDetail, normalizeExchangeDetail, normalizeSessionOverview } from '../utils';

export function useSessions(options: { apiBase: string; pollMs?: number; isNewestFirst?: boolean }) {
  const { apiBase, pollMs = 2000, isNewestFirst = false } = options;

  // Data State
  const [sessionList, setSessionList] = useState<SessionSummary[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [loadingExchangeSequenceId, setLoadingExchangeSequenceId] = useState<string | null>(null);
  const [watchStatus, setWatchStatus] = useState<WatchStatus | null>(null);

  // Selection State
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedExchangeId, setSelectedExchangeId] = useState<string | null>(null);
  const sessionRequestRef = useRef(0);
  const exchangeRequestRef = useRef(0);
  const sessionAbortRef = useRef<AbortController | null>(null);
  const exchangeAbortRef = useRef<AbortController | null>(null);

  const fetchWatchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/status`);
      if (res.ok) {
        const data = (await res.json()) as WatchStatus;
        setWatchStatus(data);
        return data;
      }
    } catch (error) {
      console.error('Failed to fetch watch status', error);
    }
    return null;
  }, [apiBase]);

  const fetchSessionList = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessionList(data);
        return data as SessionSummary[];
      }
    } catch (error) {
      console.error('Failed to fetch sessions', error);
    }
    return [] as SessionSummary[];
  }, [apiBase]);

  const fetchSessionDetails = useCallback(async (sessionId: string) => {
    sessionAbortRef.current?.abort();
    const requestId = sessionRequestRef.current + 1;
    sessionRequestRef.current = requestId;
    const controller = new AbortController();
    sessionAbortRef.current = controller;
    setIsLoadingSession(true);
    setLoadingExchangeSequenceId(null);

    const fetchStartedAt = performance.now();
    try {
      const res = await fetch(`${apiBase}/api/sessions/${sessionId}`, { signal: controller.signal });
      if (res.ok) {
        const responseReceivedAt = performance.now();
        const data = await res.json();
        const jsonParsedAt = performance.now();
        const session = normalizeSessionOverview(data);
        const normalizedAt = performance.now();

        if (requestId !== sessionRequestRef.current) {
          return;
        }

        setCurrentSession(session);
        setSelectedExchangeId(session.exchanges.length > 0 ? session.exchanges[session.exchanges.length - 1].id : null);

        if (import.meta.env.DEV) {
          requestAnimationFrame(() => {
            console.debug('[session-load]', {
              sessionId,
              exchangeCount: session.exchanges.length,
              fetchMs: Math.round(responseReceivedAt - fetchStartedAt),
              parseMs: Math.round(jsonParsedAt - responseReceivedAt),
              normalizeMs: Math.round(normalizedAt - jsonParsedAt),
              totalMs: Math.round(normalizedAt - fetchStartedAt),
            });
          });
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return;
      }
      console.error('Failed to fetch session details', error);
    } finally {
      if (requestId === sessionRequestRef.current) {
        setIsLoadingSession(false);
      }
    }
  }, [apiBase]);

  const fetchExchangeDetails = useCallback(async (sessionId: string, exchangeId: string, sequenceId: string) => {
    exchangeAbortRef.current?.abort();
    const requestId = exchangeRequestRef.current + 1;
    exchangeRequestRef.current = requestId;
    const controller = new AbortController();
    exchangeAbortRef.current = controller;
    setLoadingExchangeSequenceId(sequenceId);

    const startedAt = performance.now();
    try {
      const res = await fetch(`${apiBase}/api/sessions/${sessionId}/exchanges/${sequenceId}`, {
        signal: controller.signal,
      });
      if (!res.ok) {
        return;
      }

      const responseReceivedAt = performance.now();
      const data = await res.json();
      const jsonParsedAt = performance.now();
      const detailedExchange = normalizeExchangeDetail(data, sessionId);
      const normalizedAt = performance.now();

      if (!detailedExchange || requestId !== exchangeRequestRef.current) {
        return;
      }

      setCurrentSession((prev) => {
        if (!prev || prev.id !== sessionId) return prev;
        return mergeExchangeDetail(prev, {
          ...detailedExchange,
          id: exchangeId || detailedExchange.id,
        });
      });

      if (import.meta.env.DEV) {
        console.debug('[exchange-load]', {
          sessionId,
          sequenceId,
          fetchMs: Math.round(responseReceivedAt - startedAt),
          parseMs: Math.round(jsonParsedAt - responseReceivedAt),
          normalizeMs: Math.round(normalizedAt - jsonParsedAt),
          totalMs: Math.round(normalizedAt - startedAt),
        });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return;
      }
      console.error('Failed to fetch exchange details', error);
    } finally {
      if (requestId === exchangeRequestRef.current) {
        setLoadingExchangeSequenceId((current) => (current === sequenceId ? null : current));
      }
    }
  }, [apiBase]);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`${apiBase}/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (!res.ok) {
        return false;
      }

      setSessionList((prev) => prev.filter((session) => session.id !== sessionId));

      const isDeletingSelectedSession = selectedSessionId === sessionId;
      setSelectedSessionId((prevSelected) => (prevSelected === sessionId ? null : prevSelected));
      if (isDeletingSelectedSession) {
        setSelectedExchangeId(null);
      }
      setCurrentSession((prev) => (prev?.id === sessionId ? null : prev));
      return true;
    } catch (error) {
      console.error('Failed to delete session', error);
      return false;
    }
  }, [apiBase, selectedSessionId]);

  // Poll for session list updates
  useEffect(() => {
    const load = async () => {
      await Promise.all([fetchSessionList(), fetchWatchStatus()]);
      setIsLoadingList(false);
    };

    load();
    const interval = setInterval(() => {
      void fetchSessionList();
      void fetchWatchStatus();
    }, pollMs);
    return () => clearInterval(interval);
  }, [fetchSessionList, fetchWatchStatus, pollMs]);

  // When selectedSessionId changes, fetch details
  useEffect(() => {
    if (selectedSessionId) {
      setCurrentSession(null);
      setSelectedExchangeId(null);
      fetchSessionDetails(selectedSessionId);
    } else {
      sessionAbortRef.current?.abort();
      exchangeAbortRef.current?.abort();
      setCurrentSession(null);
      setSelectedExchangeId(null);
      setIsLoadingSession(false);
      setLoadingExchangeSequenceId(null);
    }
  }, [fetchSessionDetails, selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId || !selectedExchangeId || !currentSession) return;

    const selectedExchange = currentSession.exchanges.find((exchange) => exchange.id === selectedExchangeId);
    if (!selectedExchange || selectedExchange.hasFullDetails || !selectedExchange.sequenceId) {
      return;
    }

    fetchExchangeDetails(selectedSessionId, selectedExchange.id, selectedExchange.sequenceId);
  }, [currentSession, fetchExchangeDetails, selectedExchangeId, selectedSessionId]);

  // Auto-select a session once the list loads, and handle removed sessions.
  // Selection follows UI sort preference when no current valid selection exists.
  useEffect(() => {
    if (sessionList.length === 0) {
      if (selectedSessionId !== null) {
        setSelectedSessionId(null);
      }
      setSelectedExchangeId(null);
      return;
    }

    const hasSelection =
      selectedSessionId && sessionList.some((session) => session.id === selectedSessionId);
    if (!hasSelection) {
      const fallbackIndex = isNewestFirst ? sessionList.length - 1 : 0;
      setSelectedSessionId(sessionList[fallbackIndex].id);
    }
  }, [isNewestFirst, sessionList, selectedSessionId]);

  useEffect(() => {
    return () => {
      sessionAbortRef.current?.abort();
      exchangeAbortRef.current?.abort();
    };
  }, []);

  return {
    sessionList,
    currentSession,
    isLoadingList,
    isLoadingSession,
    loadingExchangeSequenceId,
    watchStatus,
    selectedSessionId,
    setSelectedSessionId,
    selectedExchangeId,
    setSelectedExchangeId,
    refreshSessionList: fetchSessionList,
    fetchSessionDetails,
    fetchExchangeDetails,
    deleteSession,
  };
}

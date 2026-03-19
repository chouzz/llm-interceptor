import { useCallback, useEffect, useState } from 'react';
import type { Session, SessionSummary, WatchStatus } from '../types';
import { normalizeSession } from '../utils';

export function useSessions(options: { apiBase: string; pollMs?: number; isNewestFirst?: boolean }) {
  const { apiBase, pollMs = 2000, isNewestFirst = false } = options;

  // Data State
  const [sessionList, setSessionList] = useState<SessionSummary[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [watchStatus, setWatchStatus] = useState<WatchStatus | null>(null);

  // Selection State
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedExchangeId, setSelectedExchangeId] = useState<string | null>(null);

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
    try {
      const res = await fetch(`${apiBase}/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        // Normalize the API data to UI structure
        const session = normalizeSession(data);
        setCurrentSession(session);

        // Auto-select last exchange (most recent)
        if (session.exchanges.length > 0) {
          setSelectedExchangeId(session.exchanges[session.exchanges.length - 1].id);
        }
      }
    } catch (error) {
      console.error('Failed to fetch session details', error);
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
      fetchSessionDetails(selectedSessionId);
    } else {
      setCurrentSession(null);
    }
  }, [fetchSessionDetails, selectedSessionId]);

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

  return {
    sessionList,
    currentSession,
    isLoadingList,
    watchStatus,
    selectedSessionId,
    setSelectedSessionId,
    selectedExchangeId,
    setSelectedExchangeId,
    refreshSessionList: fetchSessionList,
    fetchSessionDetails,
    deleteSession,
  };
}

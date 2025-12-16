import React, { useEffect, useMemo, useState } from 'react';
import { EmptyState } from './components/layout/EmptyState';
import { ExchangeDetailsPane } from './components/layout/ExchangeDetailsPane';
import { RequestsPane } from './components/layout/RequestsPane';
import { SessionsSidebar } from './components/layout/SessionsSidebar';
import { useAnnotations } from './hooks/useAnnotations';
import { useResizablePanels } from './hooks/useResizablePanels';
import { useSessions } from './hooks/useSessions';
import { useTheme } from './hooks/useTheme';
import { stringToColor } from './utils/ui';

// API Base URL - empty for relative path (production), or localhost for dev
const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';

const App: React.FC = () => {
  const { isDarkMode, toggleTheme } = useTheme();
  const [systemPromptFilter, setSystemPromptFilter] = useState<string | null>(null);

  const {
    sessionsWidth,
    requestsWidth,
    isSessionsCollapsed,
    setIsSessionsCollapsed,
    isRequestsCollapsed,
    setIsRequestsCollapsed,
    startResizingSessions,
    startResizingRequests,
  } = useResizablePanels();

  const {
    sessionList,
    currentSession,
    isLoadingList,
    selectedSessionId,
    setSelectedSessionId,
    selectedExchangeId,
    setSelectedExchangeId,
  } = useSessions({ apiBase: API_BASE, pollMs: 2000 });

  const { annotations, ensureLoaded, fetchAllAnnotations, updateSessionNote, updateRequestNote } = useAnnotations({
    apiBase: API_BASE,
  });

  // Preload annotations for all sessions when session list changes
  useEffect(() => {
    if (sessionList.length === 0) return;
    
    // Find sessions that haven't been loaded yet
    const unloadedSessionIds = sessionList
      .map((s) => s.id)
      .filter((id) => !(id in annotations));
    
    if (unloadedSessionIds.length > 0) {
      void fetchAllAnnotations(unloadedSessionIds);
    }
  }, [sessionList, annotations, fetchAllAnnotations]);

  // Ensure annotations are loaded when session changes (fallback)
  useEffect(() => {
    if (!selectedSessionId) return;
    if (annotations[selectedSessionId]) return;
    void ensureLoaded(selectedSessionId);
  }, [annotations, ensureLoaded, selectedSessionId]);

  const filteredExchanges = useMemo(() => {
    if (!currentSession) return [];
    if (!systemPromptFilter) return currentSession.exchanges;
    return currentSession.exchanges.filter((ex) => stringToColor(ex.systemPrompt) === systemPromptFilter);
  }, [currentSession, systemPromptFilter]);

  const currentExchange = useMemo(
    () => currentSession?.exchanges.find((e) => e.id === selectedExchangeId) ?? null,
    [currentSession, selectedExchangeId]
  );

  return (
    <div
      className={`${
        isDarkMode ? 'dark' : ''
      } h-screen w-full flex bg-gray-50 dark:bg-[#0f172a] text-slate-900 dark:text-slate-200 overflow-hidden font-sans selection:bg-blue-200 dark:selection:bg-blue-500/30 transition-colors duration-200`}
    >
      {sessionList.length === 0 ? (
        <EmptyState isDarkMode={isDarkMode} isLoadingList={isLoadingList} onToggleTheme={toggleTheme} />
      ) : (
        <>
          <SessionsSidebar
            width={sessionsWidth}
            isCollapsed={isSessionsCollapsed}
            setIsCollapsed={setIsSessionsCollapsed}
            onStartResize={startResizingSessions}
            sessionList={sessionList}
            selectedSessionId={selectedSessionId}
            onSelectSession={setSelectedSessionId}
            isDarkMode={isDarkMode}
            onToggleTheme={toggleTheme}
            annotations={annotations}
            onUpdateSessionNote={updateSessionNote}
          />

          <RequestsPane
            width={requestsWidth}
            isCollapsed={isRequestsCollapsed}
            setIsCollapsed={setIsRequestsCollapsed}
            onStartResize={startResizingRequests}
            currentSessionName={currentSession?.name}
            filteredExchanges={filteredExchanges}
            selectedExchangeId={selectedExchangeId}
            onSelectExchange={setSelectedExchangeId}
            systemPromptFilter={systemPromptFilter}
            setSystemPromptFilter={setSystemPromptFilter}
            selectedSessionId={selectedSessionId}
            annotations={annotations}
            onUpdateRequestNote={updateRequestNote}
          />

          <ExchangeDetailsPane currentExchange={currentExchange} />
        </>
      )}
    </div>
  );
};

export default App;

import { useCallback, useMemo, useState } from 'react';
import type { AnnotationData } from '../types';
import { debounce } from '../utils/ui';

export function useAnnotations(options: { apiBase: string }) {
  const { apiBase } = options;

  const [annotations, setAnnotations] = useState<Record<string, AnnotationData>>({});

  const fetchAnnotations = async (sessionId: string) => {
    try {
      const res = await fetch(`${apiBase}/api/sessions/${sessionId}/annotations`);
      if (res.ok) {
        const data = (await res.json()) as AnnotationData;
        setAnnotations((prev) => ({ ...prev, [sessionId]: data }));
        return data;
      }
    } catch (error) {
      console.error('Failed to fetch annotations', error);
    }
    return { session_note: '', requests: {} } satisfies AnnotationData;
  };

  // Batch fetch annotations for multiple sessions
  const fetchAllAnnotations = useCallback(
    async (sessionIds: string[]) => {
      const results: Record<string, AnnotationData> = {};
      
      // Fetch all annotations in parallel
      const fetchPromises = sessionIds.map(async (sessionId) => {
        try {
          const res = await fetch(`${apiBase}/api/sessions/${sessionId}/annotations`);
          if (res.ok) {
            const data = (await res.json()) as AnnotationData;
            results[sessionId] = data;
          } else {
            results[sessionId] = { session_note: '', requests: {} };
          }
        } catch (error) {
          console.error(`Failed to fetch annotations for ${sessionId}`, error);
          results[sessionId] = { session_note: '', requests: {} };
        }
      });

      await Promise.all(fetchPromises);
      
      // Update state with all fetched annotations
      setAnnotations((prev) => ({ ...prev, ...results }));
      return results;
    },
    [apiBase]
  );

  const saveAnnotations = async (sessionId: string, data: AnnotationData) => {
    try {
      const res = await fetch(`${apiBase}/api/sessions/${sessionId}/annotations`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (res.ok) {
        setAnnotations((prev) => ({ ...prev, [sessionId]: data }));
      }
    } catch (error) {
      console.error('Failed to save annotations', error);
    }
  };

  // Debounced save function (memoized)
  const debouncedSaveAnnotations = useMemo(
    () =>
      debounce((sessionId: string, data: AnnotationData) => {
        saveAnnotations(sessionId, data);
      }, 500),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [apiBase]
  );

  const ensureLoaded = async (sessionId: string) => {
    if (annotations[sessionId]) return annotations[sessionId];
    return await fetchAnnotations(sessionId);
  };

  const updateSessionNote = (sessionId: string, note: string) => {
    const current = annotations[sessionId] || { session_note: '', requests: {} };
    const updated = { ...current, session_note: note };
    setAnnotations((prev) => ({ ...prev, [sessionId]: updated }));
    debouncedSaveAnnotations(sessionId, updated);
  };

  const updateRequestNote = (sessionId: string, sequenceId: string, note: string) => {
    const current = annotations[sessionId] || { session_note: '', requests: {} };
    const updated = {
      ...current,
      requests: { ...current.requests, [sequenceId]: note },
    };
    setAnnotations((prev) => ({ ...prev, [sessionId]: updated }));
    debouncedSaveAnnotations(sessionId, updated);
  };

  return {
    annotations,
    setAnnotations,
    ensureLoaded,
    fetchAnnotations,
    fetchAllAnnotations,
    updateSessionNote,
    updateRequestNote,
  };
}

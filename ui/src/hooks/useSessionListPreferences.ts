import { useEffect, useState } from 'react';

const SORT_ORDER_STORAGE_KEY = 'lli.sessions.sortNewestFirst';

function readInitialSortPreference(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }

  try {
    return window.localStorage.getItem(SORT_ORDER_STORAGE_KEY) === 'true';
  } catch (error) {
    console.error('Failed to read session sort preference', error);
    return false;
  }
}

export function useSessionListPreferences() {
  const [isNewestFirst, setIsNewestFirst] = useState<boolean>(readInitialSortPreference);

  useEffect(() => {
    try {
      window.localStorage.setItem(SORT_ORDER_STORAGE_KEY, String(isNewestFirst));
    } catch (error) {
      console.error('Failed to persist session sort preference', error);
    }
  }, [isNewestFirst]);

  const toggleSortOrder = () => {
    setIsNewestFirst((prev) => !prev);
  };

  return {
    isNewestFirst,
    setIsNewestFirst,
    toggleSortOrder,
  };
}

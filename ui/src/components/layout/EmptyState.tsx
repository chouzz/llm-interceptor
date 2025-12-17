import React from 'react';
import { FolderOpen, Moon, RefreshCw, Sun } from 'lucide-react';

export const EmptyState: React.FC<{
  isDarkMode: boolean;
  isLoadingList: boolean;
  onToggleTheme: () => void;
}> = ({ isDarkMode, isLoadingList, onToggleTheme }) => {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center relative overflow-hidden bg-gray-50 dark:bg-[#0f172a]">
      <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-20 pointer-events-none"></div>
      <button
        onClick={onToggleTheme}
        className="absolute top-6 right-6 p-2 rounded-full bg-white dark:bg-slate-800 shadow-sm border border-gray-200 dark:border-slate-700 hover:scale-110 transition-transform text-slate-600 dark:text-slate-400"
        type="button"
      >
        {isDarkMode ? <Sun size={20} /> : <Moon size={20} />}
      </button>

      <div className="mb-8 p-6 rounded-3xl bg-white dark:bg-slate-800/30 border border-gray-200 dark:border-slate-700/50 shadow-2xl backdrop-blur-sm">
        <FolderOpen size={64} className="text-blue-500 dark:text-blue-400" />
      </div>
      <h1 className="text-5xl font-bold mb-4 text-transparent bg-clip-text bg-gradient-to-r from-blue-600 via-indigo-600 to-emerald-600 dark:from-blue-400 dark:via-indigo-400 dark:to-emerald-400">
        LLM Interceptor
      </h1>

      {isLoadingList ? (
        <div className="mt-8 flex items-center gap-3 text-slate-500 dark:text-slate-400">
          <RefreshCw className="animate-spin" size={20} />
          <span>Scanning for sessions...</span>
        </div>
      ) : (
        <p className="max-w-md text-slate-600 dark:text-slate-400 mb-10 leading-relaxed text-lg">
          No sessions found in the traces directory. <br />
          Run <code>lli watch</code> to capture new sessions.
        </p>
      )}
    </div>
  );
};

import React from 'react';
import { FolderOpen, Moon, RefreshCw, Sun } from 'lucide-react';

export const EmptyState: React.FC<{
  isDarkMode: boolean;
  isLoadingList: boolean;
  onToggleTheme: () => void;
  outputDir: string | null;
  isRecording: boolean;
  recordingSessionId: string | null;
}> = ({ isDarkMode, isLoadingList, onToggleTheme, outputDir, isRecording, recordingSessionId }) => {
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
        <div className="max-w-2xl text-slate-600 dark:text-slate-400 mb-10 leading-relaxed text-lg">
          <p className="mb-4">
            {isRecording ? (
              <>
                No completed sessions yet. A recording is currently in progress
                {recordingSessionId ? (
                  <>
                    {' '}
                    (<code>{recordingSessionId}</code>)
                  </>
                ) : null}
                .
              </>
            ) : (
              <>No sessions yet.</>
            )}
          </p>

          {outputDir ? (
            <p className="mb-4">
              Output dir: <code className="break-all">{outputDir}</code>
            </p>
          ) : null}

          <div className="text-left inline-block rounded-2xl bg-white/80 dark:bg-slate-800/30 border border-gray-200 dark:border-slate-700/50 px-5 py-4 shadow-sm backdrop-blur-sm">
            <div className="font-semibold text-slate-800 dark:text-slate-200 mb-2">How to capture</div>
            <ol className="list-decimal pl-5 space-y-1">
              <li>
                In the terminal running <code>lli watch</code>, press <code>Enter</code> to start capturing.
              </li>
              <li>Start your conversation in your tool/app (with proxy env vars configured).</li>
              <li>
                Press <code>Enter</code> again to stop and process the session.
              </li>
            </ol>
          </div>
        </div>
      )}
    </div>
  );
};

import React from 'react';
import { Activity, ShieldCheck, Database, FileText, Cpu, AlertTriangle, Layers, Lock, Sparkles } from 'lucide-react';

interface HeaderProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  globalTrials: number;
  highwaterMark: number;
  experimentCount: number;
  onOpenPreregistration?: () => void;
  activePreregCount?: number;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  globalTrials,
  highwaterMark,
  experimentCount,
  onOpenPreregistration,
  activePreregCount = 3,
}) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-teal-500/10 border border-teal-500/30 flex items-center justify-center text-teal-400">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold tracking-tight text-white text-base sm:text-lg">
                  Institutional Quant Research Engine
                </span>
                <span className="px-2 py-0.5 text-xs font-mono rounded bg-teal-500/10 text-teal-400 border border-teal-500/20">
                  V2.1.5 Full-Stack
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Point-in-Time • Leakage-Safe • Walk-Forward Walk • Empirical Placebo Gates
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Preregistration Gate Launcher */}
            {onOpenPreregistration && (
              <button
                onClick={onOpenPreregistration}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-teal-500/15 border border-teal-500/30 text-teal-300 hover:bg-teal-500/25 transition text-xs font-semibold"
              >
                <Lock className="w-3.5 h-3.5 text-amber-400" />
                <span className="hidden sm:inline">Preregistration Protocol</span>
                <span className="px-1.5 py-0.2 rounded bg-teal-900/50 text-[10px] font-mono text-teal-200 border border-teal-700/50">
                  {activePreregCount} Locked
                </span>
              </button>
            )}

            {/* Trial Counter Guard */}
            <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800/80 border border-slate-700/60 font-mono text-xs">
              <span className="text-slate-400">Trials Counter:</span>
              <span className="text-amber-400 font-semibold">{globalTrials}</span>
              <span className="text-slate-500">/</span>
              <span className="text-slate-400" title="Highwater Mark protection">HW: {highwaterMark}</span>
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" title="Highwater invariant protected" />
            </div>

            {/* Experiment count badge */}
            <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800 text-slate-300 text-xs font-mono border border-slate-700">
              <span>{experimentCount} Runs Loaded</span>
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex space-x-1 sm:space-x-4 border-t border-slate-800/60 pt-2 pb-2 overflow-x-auto text-xs sm:text-sm">
          <button
            id="tab-leaderboard"
            onClick={() => setActiveTab('leaderboard')}
            className={`flex items-center gap-2 px-3 py-2 rounded-md font-medium transition-colors whitespace-nowrap ${
              activeTab === 'leaderboard'
                ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Activity className="w-4 h-4" />
            Experiment Leaderboard
          </button>

          <button
            id="tab-simulator"
            onClick={() => setActiveTab('simulator')}
            className={`flex items-center gap-2 px-3 py-2 rounded-md font-medium transition-colors whitespace-nowrap ${
              activeTab === 'simulator'
                ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Cpu className="w-4 h-4" />
            Walk-Forward Simulator
          </button>

          <button
            id="tab-paper-trading"
            onClick={() => setActiveTab('paper-trading')}
            className={`flex items-center gap-2 px-3 py-2 rounded-md font-medium transition-colors whitespace-nowrap ${
              activeTab === 'paper-trading'
                ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <Layers className="w-4 h-4" />
            Paper Trading &amp; Execution
          </button>

          <button
            id="tab-pit-audit"
            onClick={() => setActiveTab('pit-audit')}
            className={`flex items-center gap-2 px-3 py-2 rounded-md font-medium transition-colors whitespace-nowrap ${
              activeTab === 'pit-audit'
                ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
            PIT & Leakage Audits
          </button>

          <button
            id="tab-institutional-audits"
            onClick={() => setActiveTab('institutional-audits')}
            className={`flex items-center gap-2 px-3 py-2 rounded-md font-medium transition-colors whitespace-nowrap ${
              activeTab === 'institutional-audits'
                ? 'bg-teal-500/15 text-teal-300 border border-teal-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            <FileText className="w-4 h-4" />
            Institutional Audit Archive
          </button>
        </div>
      </div>
    </header>
  );
};

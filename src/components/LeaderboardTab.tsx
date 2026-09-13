import React, { useState } from 'react';
import { Search, Filter, Layers, ArrowUpRight, CheckCircle, XCircle, ShieldAlert, Sparkles, Download } from 'lucide-react';
import { ExperimentRecord } from '../types';

interface LeaderboardTabProps {
  experiments: ExperimentRecord[];
  onSelectExperiment: (exp: ExperimentRecord) => void;
}

export const LeaderboardTab: React.FC<LeaderboardTabProps> = ({ experiments, onSelectExperiment }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'REAL_DATA' | 'SYNTHETIC_OFFLINE' | 'CANDIDATES'>('ALL');

  const filteredExperiments = experiments.filter((exp) => {
    const matchesSearch =
      exp.experiment_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      exp.strategy.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (exp.model_name && exp.model_name.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (exp.hypothesis_name && exp.hypothesis_name.toLowerCase().includes(searchQuery.toLowerCase())) ||
      exp.target.toLowerCase().includes(searchQuery.toLowerCase()) ||
      exp.universe.some(s => s.toLowerCase().includes(searchQuery.toLowerCase()));

    if (!matchesSearch) return false;

    if (statusFilter === 'REAL_DATA') return exp.evidence_status === 'REAL_DATA';
    if (statusFilter === 'SYNTHETIC_OFFLINE') return exp.evidence_status === 'SYNTHETIC_OFFLINE';
    if (statusFilter === 'CANDIDATES') return exp.promotion_state !== 'RESEARCH_ONLY';
    return true;
  });

  const totalRuns = experiments.length;
  const realRuns = experiments.filter(e => e.evidence_status === 'REAL_DATA').length;
  const positiveNetSharpeRuns = experiments.filter(e => e.net_metrics.full_oos_sharpe > 0).length;
  const maxNetSharpe = Math.max(...experiments.map(e => e.net_metrics.full_oos_sharpe));

  const exportAllRegistryJson = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(experiments, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `experiment_registry.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="space-y-6">
      {/* Top metrics bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
          <div className="text-xs text-slate-400 font-mono uppercase">Logged Experiments</div>
          <div className="text-2xl font-mono font-bold text-white mt-1">{totalRuns}</div>
          <div className="text-xs text-slate-500 mt-1">{realRuns} on Real Market Data</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
          <div className="text-xs text-slate-400 font-mono uppercase">Positive Net Sharpe</div>
          <div className="text-2xl font-mono font-bold text-emerald-400 mt-1">
            {positiveNetSharpeRuns} <span className="text-xs text-slate-400 font-normal">({((positiveNetSharpeRuns / totalRuns) * 100).toFixed(0)}%)</span>
          </div>
          <div className="text-xs text-slate-500 mt-1">Survives transaction costs</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
          <div className="text-xs text-slate-400 font-mono uppercase">Peak Net OOS Sharpe</div>
          <div className="text-2xl font-mono font-bold text-teal-400 mt-1">
            +{maxNetSharpe.toFixed(3)}
          </div>
          <div className="text-xs text-slate-500 mt-1">Full walk-forward OOS</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
          <div className="text-xs text-slate-400 font-mono uppercase">Gate Audit Policy</div>
          <div className="text-xl font-mono font-bold text-amber-400 mt-1">
            Default Rejection
          </div>
          <div className="text-xs text-slate-500 mt-1">11 Mandatory Evidence Gates</div>
        </div>
      </div>

      {/* Controls & Filters Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-slate-900/60 p-3 rounded-xl border border-slate-800">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
          <input
            id="search-experiments"
            type="text"
            placeholder="Search experiments by ID, strategy, asset (e.g. SPY)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs sm:text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-teal-500 transition"
          />
        </div>

        <div className="flex items-center gap-2 overflow-x-auto text-xs">
          <button
            onClick={() => setStatusFilter('ALL')}
            className={`px-3 py-2 rounded-lg font-medium transition whitespace-nowrap ${
              statusFilter === 'ALL' ? 'bg-slate-800 text-white border border-slate-700' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            All ({experiments.length})
          </button>
          <button
            onClick={() => setStatusFilter('REAL_DATA')}
            className={`px-3 py-2 rounded-lg font-medium transition whitespace-nowrap ${
              statusFilter === 'REAL_DATA' ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Real Data ({realRuns})
          </button>
          <button
            onClick={() => setStatusFilter('SYNTHETIC_OFFLINE')}
            className={`px-3 py-2 rounded-lg font-medium transition whitespace-nowrap ${
              statusFilter === 'SYNTHETIC_OFFLINE' ? 'bg-amber-950/60 text-amber-300 border border-amber-800' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Synthetic ({totalRuns - realRuns})
          </button>

          <button
            onClick={exportAllRegistryJson}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition whitespace-nowrap border border-slate-700"
            title="Download full registry JSON"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Registry</span>
          </button>
        </div>
      </div>

      {/* Main Leaderboard Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="bg-slate-950/90 text-slate-400 uppercase font-mono border-b border-slate-800">
              <tr>
                <th className="px-4 py-3">Experiment ID</th>
                <th className="px-3 py-3">Evidence Mode</th>
                <th className="px-3 py-3">Strategy / Target</th>
                <th className="px-3 py-3 text-right">Gross SR</th>
                <th className="px-3 py-3 text-right">Net OOS SR</th>
                <th className="px-3 py-3 text-right">Net Return</th>
                <th className="px-3 py-3 text-right">Max DD</th>
                <th className="px-3 py-3 text-right">Cost Drag</th>
                <th className="px-3 py-3 text-right">Placebo</th>
                <th className="px-3 py-3 text-center">Promotion Gate</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 font-mono">
              {filteredExperiments.map((exp) => {
                const isReal = exp.evidence_status === 'REAL_DATA';
                const isPositiveNet = exp.net_metrics.full_oos_sharpe > 0;

                return (
                  <tr
                    key={exp.experiment_id}
                    className="hover:bg-slate-800/50 transition cursor-pointer"
                    onClick={() => onSelectExperiment(exp)}
                  >
                    <td className="px-4 py-3">
                      <div className="font-semibold text-white hover:text-teal-400 transition flex items-center gap-1.5">
                        <span>{exp.experiment_id}</span>
                        <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {exp.timestamp_utc} • {exp.trials} trials
                      </div>
                    </td>

                    <td className="px-3 py-3 whitespace-nowrap">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                        isReal
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                          : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                      }`}>
                        {isReal ? 'REAL SPY/QQQ' : 'SYNTHETIC 7-ASSET'}
                      </span>
                    </td>

                    <td className="px-3 py-3">
                      <div className="text-slate-200 font-sans font-medium">
                        {exp.hypothesis_name || exp.model_name || exp.strategy}
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono">
                        Target: <strong className="text-teal-400">{exp.target}</strong> ({exp.universe.join(', ')})
                      </div>
                    </td>

                    <td className="px-3 py-3 text-right text-slate-400">
                      {exp.gross_metrics.full_oos_sharpe.toFixed(2)}
                    </td>

                    <td className={`px-3 py-3 text-right font-bold ${isPositiveNet ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isPositiveNet ? '+' : ''}{exp.net_metrics.full_oos_sharpe.toFixed(2)}
                    </td>

                    <td className={`px-3 py-3 text-right font-semibold ${exp.net_metrics.full_oos_return > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {(exp.net_metrics.full_oos_return * 100).toFixed(1)}%
                    </td>

                    <td className="px-3 py-3 text-right text-rose-400">
                      {(exp.oos_metrics.full_oos_max_dd * 100).toFixed(1)}%
                    </td>

                    <td className="px-3 py-3 text-right text-amber-400">
                      -{(exp.net_metrics.cost_drag * 100).toFixed(1)}%
                    </td>

                    <td className="px-3 py-3 text-right text-teal-300">
                      {(exp.placebo_statistics.percentile * 100).toFixed(0)}%
                    </td>

                    <td className="px-3 py-3 text-center whitespace-nowrap">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                        exp.promotion_state === 'ROBUST_OOS' || exp.promotion_state === 'CANDIDATE'
                          ? 'bg-teal-500/20 text-teal-300 border-teal-500/30'
                          : 'bg-rose-500/15 text-rose-300 border-rose-500/20'
                      }`}>
                        {exp.promotion_state}
                      </span>
                      {exp.failed_gates.length > 0 && (
                        <div className="text-[9px] text-slate-500 mt-0.5">
                          {exp.failed_gates.length} failed gates
                        </div>
                      )}
                    </td>

                    <td className="px-4 py-3 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => onSelectExperiment(exp)}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-teal-300 text-xs font-sans font-medium border border-slate-700 transition"
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

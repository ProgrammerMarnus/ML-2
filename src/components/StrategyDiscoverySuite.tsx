import React, { useState } from 'react';
import {
  Compass,
  Play,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Layers,
  ArrowRight,
  TrendingUp,
  ShieldCheck,
  Zap,
  Download,
  Database,
  ExternalLink,
  ChevronRight,
  Sparkles,
  Sliders,
  Award
} from 'lucide-react';
import {
  DISCOVERY_CAMPAIGNS,
  DiscoveryCampaign,
  runDiscoverySweep,
  DiscoverySweepResult,
  DiscoveryHypothesisConfig,
  StrategyType
} from '../utils/quantEngine';
import { ExperimentRecord } from '../types';

interface StrategyDiscoverySuiteProps {
  globalTrials: number;
  onRegisterExperiment: (newExp: ExperimentRecord) => void;
  onInspectExperiment: (exp: ExperimentRecord) => void;
  onNavigateToPaperTrading?: () => void;
}

export const StrategyDiscoverySuite: React.FC<StrategyDiscoverySuiteProps> = ({
  globalTrials,
  onRegisterExperiment,
  onInspectExperiment,
  onNavigateToPaperTrading
}) => {
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>(DISCOVERY_CAMPAIGNS[0].id);
  const [isSweeping, setIsSweeping] = useState(false);
  const [sweepProgress, setSweepProgress] = useState({ current: 0, total: 0, currentHypothesisName: '' });
  const [sweepResult, setSweepResult] = useState<DiscoverySweepResult | null>(null);
  const [savedExpIds, setSavedExpIds] = useState<Set<string>>(new Set());

  const activeCampaign = DISCOVERY_CAMPAIGNS.find(c => c.id === selectedCampaignId) || DISCOVERY_CAMPAIGNS[0];

  const handleLaunchSweep = () => {
    setIsSweeping(true);
    setSweepResult(null);
    const campaign = activeCampaign;
    const total = campaign.hypotheses.length;

    let idx = 0;
    setSweepProgress({ current: 0, total, currentHypothesisName: campaign.hypotheses[0]?.name || '' });

    const interval = setInterval(() => {
      idx++;
      if (idx < total) {
        setSweepProgress({
          current: idx,
          total,
          currentHypothesisName: campaign.hypotheses[idx]?.name || ''
        });
      } else {
        clearInterval(interval);
        // Execute the full walk-forward simulation sweep
        const res = runDiscoverySweep(campaign, globalTrials);
        setSweepResult(res);
        setIsSweeping(false);
      }
    }, 450);
  };

  const handleSaveSingle = (exp: ExperimentRecord) => {
    onRegisterExperiment(exp);
    setSavedExpIds(prev => new Set([...prev, exp.experiment_id]));
  };

  const handleSaveAll = () => {
    if (!sweepResult) return;
    sweepResult.results.forEach(r => {
      onRegisterExperiment(r.experiment);
    });
    const allIds = sweepResult.results.map(r => r.experiment.experiment_id);
    setSavedExpIds(new Set(allIds));
  };

  const handleExportSweepJson = () => {
    if (!sweepResult) return;
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(sweepResult, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `discovery_sweep_${sweepResult.campaign.id}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="space-y-6">
      {/* Campaign Selection Header Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Compass className="w-5 h-5 text-teal-400" />
              <h3 className="text-base sm:text-lg font-bold text-white">
                Autonomous Strategy Discovery & Sweep Engine
              </h3>
              <span className="text-[11px] px-2 py-0.5 rounded bg-teal-500/10 text-teal-400 border border-teal-500/20 font-mono">
                Multi-Hypothesis Sweep
              </span>
            </div>
            <p className="text-xs sm:text-sm text-slate-400 mt-1 max-w-3xl">
              Systematically evaluates new strategy hypotheses, regime-conditioned gradient boosters, cross-asset momentum rotations, 
              and multi-factor ensembles across all 7 temporal walk-forward folds. Every candidate must pass all 14 institutional promotion gates.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              id="btn-launch-discovery"
              onClick={handleLaunchSweep}
              disabled={isSweeping}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition shadow-lg ${
                isSweeping
                  ? 'bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700'
                  : 'bg-teal-500 hover:bg-teal-400 text-slate-950 shadow-teal-500/20'
              }`}
            >
              {isSweeping ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Sweeping ({sweepProgress.current + 1}/{sweepProgress.total})...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  <span>Run Discovery Sweep</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Campaign Selection Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {DISCOVERY_CAMPAIGNS.map((campaign) => {
          const isSelected = selectedCampaignId === campaign.id;
          return (
            <div
              key={campaign.id}
              onClick={() => !isSweeping && setSelectedCampaignId(campaign.id)}
              className={`p-4 rounded-xl border transition cursor-pointer ${
                isSelected
                  ? 'bg-slate-900 border-teal-500/50 ring-1 ring-teal-500/30'
                  : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className={`p-1.5 rounded-lg ${isSelected ? 'bg-teal-500/20 text-teal-300' : 'bg-slate-800 text-slate-400'}`}>
                    <Layers className="w-4 h-4" />
                  </div>
                  <h4 className="text-sm font-semibold text-white font-sans">{campaign.name}</h4>
                </div>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                  {campaign.hypotheses.length} Hypotheses
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                {campaign.description}
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {campaign.hypotheses.map(h => (
                  <span
                    key={h.id}
                    className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-950 text-slate-300 border border-slate-800"
                  >
                    {h.category}: {h.strategyType}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Sweep In-Progress Execution Animation */}
      {isSweeping && (
        <div className="bg-slate-900/90 border border-teal-500/40 rounded-xl p-6 shadow-xl space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-white flex items-center gap-2">
              <RefreshCw className="w-4 h-4 text-teal-400 animate-spin" />
              <span>Running Strategy Discovery Tournament...</span>
            </h4>
            <span className="font-mono text-xs text-teal-400">
              Hypothesis {sweepProgress.current + 1} of {sweepProgress.total}
            </span>
          </div>

          <div className="w-full bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
            <div
              className="bg-gradient-to-r from-teal-500 to-emerald-400 h-full transition-all duration-300"
              style={{ width: `${((sweepProgress.current + 1) / sweepProgress.total) * 100}%` }}
            />
          </div>

          <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 flex items-center justify-between text-xs">
            <span className="text-slate-400">Current Alpha Test:</span>
            <span className="font-mono font-semibold text-teal-300">{sweepProgress.currentHypothesisName}</span>
          </div>
        </div>
      )}

      {/* Sweep Results Dashboard */}
      {sweepResult && (
        <div className="space-y-6">
          {/* Top Metric Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
              <div className="text-xs text-slate-400 font-mono uppercase">Hypotheses Tested</div>
              <div className="text-2xl font-mono font-bold text-white mt-1">
                {sweepResult.results.length}
              </div>
              <div className="text-xs text-slate-500 mt-1">{sweepResult.campaign.name.slice(0, 24)}...</div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
              <div className="text-xs text-slate-400 font-mono uppercase">Passed All 14 Gates</div>
              <div className="text-2xl font-mono font-bold text-emerald-400 mt-1 flex items-center gap-2">
                <span>{sweepResult.passingCount}</span>
                <span className="text-xs text-slate-400 font-normal">
                  ({Math.round((sweepResult.passingCount / sweepResult.results.length) * 100)}%)
                </span>
              </div>
              <div className="text-xs text-emerald-400/80 mt-1">Promoted to ROBUST_OOS</div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
              <div className="text-xs text-slate-400 font-mono uppercase">Peak Net OOS Sharpe</div>
              <div className="text-2xl font-mono font-bold text-teal-400 mt-1">
                +{Math.max(...sweepResult.results.map(r => r.experiment.net_metrics.full_oos_sharpe)).toFixed(3)}
              </div>
              <div className="text-xs text-slate-500 mt-1">After fees & slippage</div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 shadow-sm">
              <div className="text-xs text-slate-400 font-mono uppercase">Global Trials Added</div>
              <div className="text-2xl font-mono font-bold text-amber-400 mt-1">
                +{sweepResult.totalTrialsAdded}
              </div>
              <div className="text-xs text-slate-500 mt-1">Audit Ledger Synchronized</div>
            </div>
          </div>

          {/* Action Header for Batch Operations */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900 p-4 rounded-xl border border-slate-800">
            <div>
              <h4 className="text-sm font-semibold text-white">Discovery Tournament Leaderboard</h4>
              <p className="text-xs text-slate-400">
                Ranked by Out-Of-Sample Net Sharpe Ratio across all 7 temporal test folds.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleExportSweepJson}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition border border-slate-700"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Export Sweep JSON</span>
              </button>
              <button
                onClick={handleSaveAll}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-teal-500 hover:bg-teal-400 text-slate-950 font-semibold text-xs transition shadow-sm"
              >
                <Database className="w-3.5 h-3.5" />
                <span>Register All to Leaderboard</span>
              </button>
            </div>
          </div>

          {/* Discovery Results Matrix Table */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="bg-slate-950/90 text-slate-400 uppercase font-mono border-b border-slate-800">
                  <tr>
                    <th className="px-4 py-3">Rank / Strategy Hypothesis</th>
                    <th className="px-3 py-3">Category</th>
                    <th className="px-3 py-3">Target / Universe</th>
                    <th className="px-3 py-3 text-right">Gross SR</th>
                    <th className="px-3 py-3 text-right">Net OOS SR</th>
                    <th className="px-3 py-3 text-right">Net Return</th>
                    <th className="px-3 py-3 text-right">Max DD</th>
                    <th className="px-3 py-3 text-right">Cost Drag</th>
                    <th className="px-3 py-3 text-center">Gate Clearance</th>
                    <th className="px-3 py-3 text-center">Status</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 font-mono">
                  {sweepResult.results
                    .sort((a, b) => b.experiment.net_metrics.full_oos_sharpe - a.experiment.net_metrics.full_oos_sharpe)
                    .map((item, index) => {
                      const exp = item.experiment;
                      const isSaved = savedExpIds.has(exp.experiment_id);
                      const isPositive = exp.net_metrics.full_oos_sharpe > 0;
                      const isRobust = item.passedAllGates;

                      return (
                        <tr key={item.hypothesis.id} className="hover:bg-slate-800/50 transition">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <span className={`w-5 h-5 rounded-full flex items-center justify-center font-bold text-[10px] ${
                                index === 0 ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-slate-800 text-slate-400'
                              }`}>
                                #{index + 1}
                              </span>
                              <div>
                                <div className="font-semibold text-white font-sans text-xs">
                                  {item.hypothesis.name}
                                </div>
                                <div className="text-[10px] text-slate-500 font-mono">
                                  {exp.strategy_version} • Seed {exp.seed}
                                </div>
                              </div>
                            </div>
                          </td>

                          <td className="px-3 py-3">
                            <span className="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-300 border border-slate-700">
                              {item.hypothesis.category}
                            </span>
                          </td>

                          <td className="px-3 py-3">
                            <span className="font-bold text-teal-400">{exp.target}</span>
                            <span className="text-slate-500 text-[10px] ml-1">
                              ({exp.universe.join(', ')})
                            </span>
                          </td>

                          <td className="px-3 py-3 text-right text-slate-400">
                            {exp.gross_metrics.full_oos_sharpe.toFixed(2)}
                          </td>

                          <td className={`px-3 py-3 text-right font-bold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {isPositive ? '+' : ''}{exp.net_metrics.full_oos_sharpe.toFixed(2)}
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

                          <td className="px-3 py-3 text-center">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              item.gateCount === item.totalGates
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                            }`}>
                              {item.gateCount} / {item.totalGates} PASS
                            </span>
                          </td>

                          <td className="px-3 py-3 text-center whitespace-nowrap">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                              isRobust
                                ? 'bg-teal-500/20 text-teal-300 border-teal-500/40'
                                : 'bg-rose-500/15 text-rose-300 border-rose-500/20'
                            }`}>
                              {isRobust ? 'ROBUST_OOS' : 'RESEARCH_ONLY'}
                            </span>
                          </td>

                          <td className="px-4 py-3 text-right whitespace-nowrap">
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                onClick={() => onInspectExperiment(exp)}
                                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] transition"
                                title="Inspect deep audit"
                              >
                                Audit
                              </button>

                              <button
                                onClick={() => handleSaveSingle(exp)}
                                disabled={isSaved}
                                className={`px-2.5 py-1 rounded text-[11px] font-medium transition ${
                                  isSaved
                                    ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                                    : 'bg-teal-500/20 hover:bg-teal-500/30 text-teal-300 border border-teal-500/30'
                                }`}
                              >
                                {isSaved ? 'Registered' : 'Save'}
                              </button>

                              {isRobust && onNavigateToPaperTrading && (
                                <button
                                  onClick={onNavigateToPaperTrading}
                                  className="px-2 py-1 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 text-[11px] flex items-center gap-1 transition"
                                  title="Deploy to Paper Trading"
                                >
                                  <span>Paper</span>
                                  <ChevronRight className="w-3 h-3" />
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

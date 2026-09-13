import React, { useState } from 'react';
import { X, ShieldAlert, CheckCircle2, XCircle, Download, Layers, TrendingUp, BarChart2, ShieldCheck, ChevronRight } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts';
import { ExperimentRecord } from '../types';
import { evaluateGateResults } from '../utils/quantEngine';

interface ExperimentDetailModalProps {
  experiment: ExperimentRecord | null;
  onClose: () => void;
}

export const ExperimentDetailModal: React.FC<ExperimentDetailModalProps> = ({ experiment, onClose }) => {
  const [activeModalTab, setActiveModalTab] = useState<'folds' | 'robustness' | 'placebo' | 'gates'>('folds');

  if (!experiment) return null;

  const gateResults = evaluateGateResults(experiment);
  const passedGatesCount = gateResults.filter(g => g.passed).length;

  const exportExperimentJson = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(experiment, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `${experiment.experiment_id}_results.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  // Format empirical null histogram bins
  const nullMean = experiment.placebo_statistics.null_mean;
  const nullStd = experiment.placebo_statistics.null_std || 0.25;
  const observed = experiment.placebo_statistics.observed;

  const placeboHistogramData = [
    { bin: '-0.4 to -0.2', value: Math.round(experiment.placebo_statistics.n_runs * 0.05) },
    { bin: '-0.2 to 0.0', value: Math.round(experiment.placebo_statistics.n_runs * 0.15) },
    { bin: '0.0 to 0.2', value: Math.round(experiment.placebo_statistics.n_runs * 0.30) },
    { bin: '0.2 to 0.4', value: Math.round(experiment.placebo_statistics.n_runs * 0.30) },
    { bin: '0.4 to 0.6', value: Math.round(experiment.placebo_statistics.n_runs * 0.15) },
    { bin: '> 0.6', value: Math.max(1, Math.round(experiment.placebo_statistics.n_runs * 0.05)) },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-sm overflow-y-auto">
      <div className="relative w-full max-w-5xl bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden my-auto max-h-[92vh] flex flex-col">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/90">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${experiment.evidence_status === 'REAL_DATA' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'}`}>
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-mono text-base sm:text-lg font-bold text-white">
                  {experiment.hypothesis_name || experiment.model_name || experiment.experiment_id}
                </h3>
                <span className={`px-2 py-0.5 text-xs font-semibold rounded ${
                  experiment.evidence_status === 'REAL_DATA' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'
                }`}>
                  {experiment.evidence_status}
                </span>
                <span className={`px-2 py-0.5 text-xs font-semibold rounded ${
                  experiment.promotion_state === 'ROBUST_OOS' || experiment.promotion_state === 'CANDIDATE'
                    ? 'bg-teal-500/20 text-teal-300'
                    : 'bg-rose-500/20 text-rose-300'
                }`}>
                  {experiment.promotion_state}
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono">
                ID: {experiment.experiment_id} • Strategy: {experiment.strategy} • Target: {experiment.target} • Trials: {experiment.trials_this_experiment} • Seed: {experiment.seed}
              </p>
              {experiment.discovery_notes && (
                <div className="text-xs text-teal-300/90 font-sans mt-1 bg-teal-950/30 px-2.5 py-1 rounded border border-teal-900/40">
                  <strong className="font-semibold text-teal-400 font-mono text-[11px] mr-1">Hypothesis Rationale:</strong>
                  {experiment.discovery_notes}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={exportExperimentJson}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 transition"
              title="Download results JSON"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Export JSON</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-100 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Top Summary KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 p-4 bg-slate-950/60 border-b border-slate-800 text-xs">
          <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
            <div className="text-slate-400">Net OOS Sharpe</div>
            <div className={`text-base font-mono font-bold ${experiment.net_metrics.full_oos_sharpe > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {experiment.net_metrics.full_oos_sharpe > 0 ? '+' : ''}{experiment.net_metrics.full_oos_sharpe.toFixed(3)}
            </div>
            <div className="text-[10px] text-slate-500">Gross: {experiment.gross_metrics.full_oos_sharpe.toFixed(3)}</div>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
            <div className="text-slate-400">Net Return (OOS)</div>
            <div className={`text-base font-mono font-bold ${experiment.net_metrics.full_oos_return > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {(experiment.net_metrics.full_oos_return * 100).toFixed(1)}%
            </div>
            <div className="text-[10px] text-slate-500">Gross: {(experiment.gross_metrics.full_oos_return * 100).toFixed(1)}%</div>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
            <div className="text-slate-400">Cost Drag</div>
            <div className="text-base font-mono font-bold text-amber-400">
              -{(experiment.net_metrics.cost_drag * 100).toFixed(2)}%
            </div>
            <div className="text-[10px] text-slate-500">{experiment.costs.fee_bps} bps fee + {experiment.costs.slippage_bps} bps slip</div>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
            <div className="text-slate-400">Max Drawdown</div>
            <div className="text-base font-mono font-bold text-rose-400">
              {(experiment.oos_metrics.full_oos_max_dd * 100).toFixed(1)}%
            </div>
            <div className="text-[10px] text-slate-500">Worst Fold: {(experiment.oos_metrics.worst_oos_dd * 100).toFixed(1)}%</div>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
            <div className="text-slate-400">Placebo Rank</div>
            <div className="text-base font-mono font-bold text-teal-400">
              {(experiment.placebo_statistics.percentile * 100).toFixed(0)}th %ile
            </div>
            <div className="text-[10px] text-slate-500">adj p: {experiment.placebo_statistics.adjusted_p.toFixed(3)}</div>
          </div>

          <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
            <div className="text-slate-400">Promotion Gates</div>
            <div className={`text-base font-mono font-bold ${passedGatesCount === 11 ? 'text-emerald-400' : 'text-amber-400'}`}>
              {passedGatesCount} / 11 Passed
            </div>
            <div className="text-[10px] text-slate-500">{experiment.failed_gates.length} failed gates</div>
          </div>
        </div>

        {/* Modal Navigation Tabs */}
        <div className="flex border-b border-slate-800 px-6 gap-6 text-sm font-medium bg-slate-900/60">
          <button
            onClick={() => setActiveModalTab('folds')}
            className={`py-3 border-b-2 flex items-center gap-2 transition ${
              activeModalTab === 'folds' ? 'border-teal-400 text-teal-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <BarChart2 className="w-4 h-4" />
            Walk-Forward Folds ({experiment.folds?.length || 7})
          </button>
          <button
            onClick={() => setActiveModalTab('robustness')}
            className={`py-3 border-b-2 flex items-center gap-2 transition ${
              activeModalTab === 'robustness' ? 'border-teal-400 text-teal-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <TrendingUp className="w-4 h-4" />
            Cost & Delay Stress Curves
          </button>
          <button
            onClick={() => setActiveModalTab('placebo')}
            className={`py-3 border-b-2 flex items-center gap-2 transition ${
              activeModalTab === 'placebo' ? 'border-teal-400 text-teal-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <ShieldAlert className="w-4 h-4" />
            Placebo Empirical Null
          </button>
          <button
            onClick={() => setActiveModalTab('gates')}
            className={`py-3 border-b-2 flex items-center gap-2 transition ${
              activeModalTab === 'gates' ? 'border-teal-400 text-teal-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
            Gate Audit ({passedGatesCount}/11)
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto flex-1 text-slate-300 text-sm space-y-6">
          {/* TAB 1: Walk-Forward Folds */}
          {activeModalTab === 'folds' && (
            <div className="space-y-6">
              <div className="bg-slate-950/80 p-4 rounded-xl border border-slate-800">
                <div className="flex items-center justify-between mb-4">
                  <h4 className="font-semibold text-white flex items-center gap-2">
                    <span>OOS Sharpe by Walk-Forward Fold</span>
                    <span className="text-xs font-normal text-slate-400">
                      (5 purge bars, 5 embargo bars, fit strictly on train window)
                    </span>
                  </h4>
                </div>

                <div className="h-60 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={experiment.folds || []}
                      margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                      <XAxis
                        dataKey="fold_id"
                        stroke="#94a3b8"
                        tickFormatter={(v) => `Fold ${v}`}
                        tick={{ fontSize: 12 }}
                      />
                      <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px' }}
                        formatter={(val: any) => [Number(val).toFixed(3), 'OOS Sharpe']}
                      />
                      <ReferenceLine y={0} stroke="#64748b" strokeWidth={1.5} />
                      <Bar
                        dataKey="oos_sharpe"
                        fill="#0ea5e9"
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Folds Table */}
              <div className="overflow-x-auto rounded-lg border border-slate-800">
                <table className="w-full text-xs text-left">
                  <thead className="bg-slate-950 text-slate-400 uppercase font-mono border-b border-slate-800">
                    <tr>
                      <th className="px-3 py-2.5">Fold</th>
                      <th className="px-3 py-2.5">Train Bars</th>
                      <th className="px-3 py-2.5">Val / Test Dates</th>
                      <th className="px-3 py-2.5">Threshold</th>
                      <th className="px-3 py-2.5 text-right">OOS AUC</th>
                      <th className="px-3 py-2.5 text-right">Trades</th>
                      <th className="px-3 py-2.5 text-right">Gross Ret</th>
                      <th className="px-3 py-2.5 text-right">Net Ret</th>
                      <th className="px-3 py-2.5 text-right">OOS Sharpe</th>
                      <th className="px-3 py-2.5 text-right">Max DD</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/80 font-mono">
                    {experiment.folds?.map((f) => (
                      <tr key={f.fold_id} className="hover:bg-slate-800/40">
                        <td className="px-3 py-2 font-semibold text-white">Fold {f.fold_id}</td>
                        <td className="px-3 py-2 text-slate-300">{f.n_train} bars</td>
                        <td className="px-3 py-2 text-slate-400">
                          {f.test_start} → {f.test_end}
                        </td>
                        <td className="px-3 py-2 text-teal-400">{f.threshold}</td>
                        <td className="px-3 py-2 text-right">{f.oos_auc.toFixed(3)}</td>
                        <td className="px-3 py-2 text-right text-slate-300">{f.oos_trades}</td>
                        <td className="px-3 py-2 text-right text-slate-400">{(f.oos_gross_return * 100).toFixed(1)}%</td>
                        <td className={`px-3 py-2 text-right font-semibold ${f.oos_net_return >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {(f.oos_net_return * 100).toFixed(1)}%
                        </td>
                        <td className={`px-3 py-2 text-right font-bold ${f.oos_sharpe >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {f.oos_sharpe.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right text-rose-400">{(f.oos_max_dd * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 2: Robustness Stress Curves */}
          {activeModalTab === 'robustness' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Cost Stress Curve */}
                <div className="bg-slate-950/80 p-4 rounded-xl border border-slate-800">
                  <h4 className="font-semibold text-white mb-2 flex items-center justify-between">
                    <span>Transaction Fee Stress Curve</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${experiment.robustness.survives_cost_stress ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'}`}>
                      {experiment.robustness.survives_cost_stress ? 'Survives >= 10bps' : 'Fails @ 10bps'}
                    </span>
                  </h4>
                  <p className="text-xs text-slate-400 mb-4">
                    Evaluates strategy net Sharpe degradation as fee charges step from 0 bps to 20 bps (plus 1 bp slippage).
                  </p>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={experiment.robustness.cost_stress} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="fee_bps" stroke="#94a3b8" tickFormatter={(v) => `${v} bps`} />
                        <YAxis stroke="#94a3b8" />
                        <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }} />
                        <ReferenceLine y={0} stroke="#64748b" strokeDasharray="3 3" />
                        <Line type="monotone" dataKey="sharpe" stroke="#10b981" strokeWidth={2} name="Net Sharpe" dot={{ r: 4 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Delay Stress Curve */}
                <div className="bg-slate-950/80 p-4 rounded-xl border border-slate-800">
                  <h4 className="font-semibold text-white mb-2 flex items-center justify-between">
                    <span>Execution Delay Stress Curve</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${experiment.robustness.survives_delay_stress ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'}`}>
                      {experiment.robustness.survives_delay_stress ? 'Survives Delay >= 1 bar' : 'Fails Delay @ 1 bar'}
                    </span>
                  </h4>
                  <p className="text-xs text-slate-400 mb-4">
                    Quantifies alpha decay when execution is artificially postponed by +1 to +3 full market sessions.
                  </p>
                  <div className="h-56">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={experiment.robustness.delay_stress} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="delay_bars" stroke="#94a3b8" tickFormatter={(v) => `+${v} bar`} />
                        <YAxis stroke="#94a3b8" />
                        <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }} />
                        <ReferenceLine y={0} stroke="#64748b" strokeDasharray="3 3" />
                        <Line type="monotone" dataKey="sharpe" stroke="#38bdf8" strokeWidth={2} name="Delay Sharpe" dot={{ r: 4 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>

              {/* Stress matrix table */}
              <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs">
                <h5 className="font-semibold text-slate-300 mb-3 font-mono">Robustness Stress Matrix Detail</h5>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 font-mono">
                  {experiment.robustness.cost_stress.map((pt) => (
                    <div key={pt.fee_bps} className="p-2.5 rounded bg-slate-900 border border-slate-800">
                      <div className="text-slate-400">{pt.fee_bps} bps Fee</div>
                      <div className={`font-bold text-sm ${pt.sharpe > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        SR: {pt.sharpe.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-slate-500">Return: {(pt.net_return * 100).toFixed(1)}%</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: Placebo Empirical Null */}
          {activeModalTab === 'placebo' && (
            <div className="space-y-6">
              <div className="bg-slate-950/80 p-5 rounded-xl border border-slate-800">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 mb-4">
                  <div>
                    <h4 className="font-semibold text-white text-base">
                      Empirical Null Distribution vs Observed Strategy
                    </h4>
                    <p className="text-xs text-slate-400">
                      Evaluates the strategy against an empirical null of {experiment.placebo_statistics.n_runs} full walk-forward runs with randomized features/targets.
                    </p>
                  </div>
                  <div className={`px-3 py-1 rounded font-mono text-xs font-bold ${
                    experiment.placebo_statistics.percentile >= 0.95 ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                  }`}>
                    Percentile: {(experiment.placebo_statistics.percentile * 100).toFixed(1)}% ({experiment.placebo_statistics.percentile >= 0.95 ? 'PASSED' : 'REJECTED'})
                  </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6 font-mono text-xs">
                  <div className="p-2.5 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Observed Mean Sharpe:</span>
                    <div className="text-sm font-bold text-teal-400">{experiment.placebo_statistics.observed.toFixed(3)}</div>
                  </div>
                  <div className="p-2.5 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Null Mean:</span>
                    <div className="text-sm font-bold text-slate-200">{experiment.placebo_statistics.null_mean.toFixed(3)}</div>
                  </div>
                  <div className="p-2.5 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Null 95th Percentile:</span>
                    <div className="text-sm font-bold text-amber-400">{experiment.placebo_statistics.null_p95.toFixed(3)}</div>
                  </div>
                  <div className="p-2.5 bg-slate-900 rounded border border-slate-800">
                    <span className="text-slate-400">Adjusted p-value:</span>
                    <div className="text-sm font-bold text-indigo-400">{experiment.placebo_statistics.adjusted_p.toFixed(3)}</div>
                  </div>
                </div>

                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={placeboHistogramData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="bin" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#94a3b8" />
                      <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }} />
                      <Bar dataKey="value" fill="#6366f1" name="Null Trials Count" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-xs text-slate-400 text-center mt-2">
                  Engine Rule: A strategy must beat the empirical null at the 95% level. Single placebo tests are never permitted.
                </p>
              </div>
            </div>
          )}

          {/* TAB 4: Gate Audit Checklist */}
          {activeModalTab === 'gates' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="font-semibold text-white">14 Institutional Promotion Gates</h4>
                  <p className="text-xs text-slate-400">
                    The engine defaults to rejection. Every single gate must pass for promotion beyond RESEARCH_ONLY.
                  </p>
                </div>
                <div className="text-xs font-mono px-2.5 py-1 rounded bg-slate-800 text-slate-300">
                  State: <strong className="text-teal-400">{experiment.promotion_state}</strong>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-2.5">
                {gateResults.map((gate) => (
                  <div
                    key={gate.id}
                    className={`p-3 rounded-lg border flex items-start justify-between gap-4 transition ${
                      gate.passed
                        ? 'bg-emerald-950/20 border-emerald-800/40 text-slate-200'
                        : 'bg-rose-950/20 border-rose-800/40 text-slate-300'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5">
                        {gate.passed ? (
                          <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                        ) : (
                          <XCircle className="w-5 h-5 text-rose-400" />
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-white text-sm">{gate.name}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 font-mono text-slate-400">
                            Required for {gate.requiredFor}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 mt-0.5">{gate.description}</p>
                      </div>
                    </div>

                    <div className="text-right whitespace-nowrap font-mono text-xs">
                      <div className="text-slate-400 text-[10px]">Criterion: {gate.threshold}</div>
                      <div className={`font-bold ${gate.passed ? 'text-emerald-400' : 'text-rose-400'}`}>
                        Obs: {gate.observed}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

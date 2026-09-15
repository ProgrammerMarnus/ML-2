import React, { useState } from 'react';
import { ShieldCheck, Lock, CheckCircle2, AlertCircle, FileText, Sparkles, Hash, ArrowRight, X } from 'lucide-react';
import { PreregistrationRecord } from '../types';
import { apiService } from '../utils/apiService';

interface PreregistrationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectHypothesis?: (prereg: PreregistrationRecord) => void;
  existingPreregistrations: PreregistrationRecord[];
  onRefreshPreregistrations: () => void;
}

export const PreregistrationModal: React.FC<PreregistrationModalProps> = ({
  isOpen,
  onClose,
  onSelectHypothesis,
  existingPreregistrations,
  onRefreshPreregistrations,
}) => {
  const [activeTab, setActiveTab] = useState<'browse' | 'new'>('browse');

  // Form fields for new preregistration
  const defaultNextId = () => {
    const maxNum = existingPreregistrations.reduce((max, p) => {
      const m = p.hypothesis_id?.match(/H-0*(\d+)/);
      const val = m ? parseInt(m[1], 10) : 0;
      return Math.max(max, val);
    }, 0);
    const nextVal = maxNum > 0 ? maxNum + 1 : 9;
    return `H-00${nextVal}`;
  };

  const [hypothesisId, setHypothesisId] = useState(defaultNextId());
  const [title, setTitle] = useState('');
  const [economicMechanism, setEconomicMechanism] = useState('');
  const [targetAsset, setTargetAsset] = useState('SPY');
  const [universe, setUniverse] = useState<string[]>(['SPY', 'QQQ']);
  const [modelType, setModelType] = useState('regularized_directional_logistic');
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([
    'momentum_63',
    'realized_vol_20',
    'volatility_ratio_10_60',
    'cross_asset_rel_strength',
  ]);
  const [minNetSharpe, setMinNetSharpe] = useState('0.50');
  const [maxDrawdown, setMaxDrawdown] = useState('0.10');
  const [placeboPValue, setPlaceboPValue] = useState('0.01');
  const [researcherName, setResearcherName] = useState('Quant Research Lead');

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [createdRecord, setCreatedRecord] = useState<PreregistrationRecord | null>(null);

  if (!isOpen) return null;

  const availableFeatures = [
    'momentum_63',
    'momentum_252',
    'trend_50',
    'mean_reversion_20',
    'realized_vol_20',
    'parkinson_vol_20',
    'volatility_ratio_10_60',
    'volume_zscore_20',
    'cross_asset_rel_strength',
    'regime_drawdown',
    'regime_high_vol',
  ];

  const toggleFeature = (feat: string) => {
    setSelectedFeatures((prev) =>
      prev.includes(feat) ? prev.filter((f) => f !== feat) : [...prev, feat]
    );
  };

  const toggleUniverseAsset = (asset: string) => {
    setUniverse((prev) =>
      prev.includes(asset) ? prev.filter((a) => a !== asset) : [...prev, asset]
    );
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !economicMechanism.trim()) {
      setErrorMsg('Please specify both the hypothesis title and economic rationale.');
      return;
    }
    if (universe.length === 0) {
      setErrorMsg('Please select at least one asset in the universe.');
      return;
    }
    if (selectedFeatures.length === 0) {
      setErrorMsg('Please select at least one candidate feature.');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      const res = await apiService.createPreregistration({
        hypothesis_id: hypothesisId,
        title,
        economic_mechanism: economicMechanism,
        universe,
        target: targetAsset,
        timeframe: '1d',
        features: selectedFeatures,
        model_type: modelType,
        parameter_grid: { C: [0.01, 0.1, 1.0], penalty: ['l1', 'l2'] },
        gates: {
          min_net_sharpe: parseFloat(minNetSharpe) || 0.5,
          max_drawdown: parseFloat(maxDrawdown) || 0.1,
          placebo_p_threshold: parseFloat(placeboPValue) || 0.01,
        },
        sign_off_researcher: researcherName,
      });

      setCreatedRecord(res.record);
      onRefreshPreregistrations();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to preregister hypothesis');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/90">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-teal-500/10 text-teal-400 border border-teal-500/20">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <span>Institutional Preregistration Protocol</span>
                <span className="text-xs font-mono font-normal px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  Anti-p-Hacking Gate
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Enforces pre-commitment to economic mechanisms, universes, feature sets, and gate thresholds before backtesting.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab switcher */}
        <div className="flex border-b border-slate-800 px-6 bg-slate-900/60 text-xs font-medium">
          <button
            onClick={() => {
              setActiveTab('browse');
              setCreatedRecord(null);
            }}
            className={`py-3 px-4 border-b-2 transition flex items-center gap-2 ${
              activeTab === 'browse'
                ? 'border-teal-400 text-teal-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Lock className="w-3.5 h-3.5" />
            <span>Active Preregistered Hypotheses ({existingPreregistrations.length})</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('new');
              setCreatedRecord(null);
            }}
            className={`py-3 px-4 border-b-2 transition flex items-center gap-2 ${
              activeTab === 'new'
                ? 'border-teal-400 text-teal-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span>Lock New Preregistration</span>
          </button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {activeTab === 'browse' && (
            <div className="space-y-4">
              <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4 text-xs text-slate-400">
                <p>
                  Preregistered hypotheses are stamped with immutable SHA-256 configuration hashes in{' '}
                  <code className="text-teal-300 font-mono">data/research_ledgers/preregistrations.jsonl</code>.
                  Selecting an active hypothesis directly binds the Walk-Forward Simulator to its exact preregistered feature matrix and evaluation gates.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-4">
                {existingPreregistrations.map((prereg) => (
                  <div
                    key={prereg.preregistration_id}
                    className="bg-slate-800/60 border border-slate-700/60 hover:border-teal-500/50 rounded-xl p-4 transition space-y-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="px-2.5 py-1 rounded bg-teal-500/10 text-teal-400 font-mono font-bold text-xs border border-teal-500/20">
                          {prereg.hypothesis_id}
                        </span>
                        <h4 className="text-sm font-semibold text-white">{prereg.title}</h4>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-700">
                          Hash: {prereg.config_hash.slice(0, 8)}...
                        </span>
                        <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${
                          prereg.status === 'PREREGISTERED_CONFIRMED'
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                            : prereg.status === 'REJECTED'
                            ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                            : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                        }`}>
                          {prereg.status}
                        </span>
                      </div>
                    </div>

                    <p className="text-xs text-slate-300 leading-relaxed bg-slate-950/40 p-2.5 rounded-lg border border-slate-900 font-sans">
                      <span className="font-semibold text-slate-400">Economic Theory: </span>
                      {prereg.economic_mechanism}
                    </p>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                      <div className="bg-slate-900/70 p-2 rounded border border-slate-800">
                        <span className="text-slate-500 block text-[10px]">Universe</span>
                        <span className="text-white">{prereg.universe.join(', ')}</span>
                      </div>
                      <div className="bg-slate-900/70 p-2 rounded border border-slate-800">
                        <span className="text-slate-500 block text-[10px]">Model Type</span>
                        <span className="text-teal-300 truncate block">{prereg.model_type}</span>
                      </div>
                      <div className="bg-slate-900/70 p-2 rounded border border-slate-800">
                        <span className="text-slate-500 block text-[10px]">Min Net Sharpe</span>
                        <span className="text-amber-400">≥ {prereg.gates?.min_net_sharpe}</span>
                      </div>
                      <div className="bg-slate-900/70 p-2 rounded border border-slate-800">
                        <span className="text-slate-500 block text-[10px]">Max Drawdown</span>
                        <span className="text-rose-400">≤ {((prereg.gates?.max_drawdown || 0.1) * 100).toFixed(0)}%</span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-1">
                      <div className="flex flex-wrap gap-1">
                        {prereg.features.slice(0, 4).map((f) => (
                          <span key={f} className="text-[10px] px-2 py-0.5 rounded bg-slate-900 text-slate-400 font-mono">
                            {f}
                          </span>
                        ))}
                        {prereg.features.length > 4 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-900 text-slate-500 font-mono">
                            +{prereg.features.length - 4} more
                          </span>
                        )}
                      </div>

                      {onSelectHypothesis && (
                        <button
                          onClick={() => {
                            onSelectHypothesis(prereg);
                            onClose();
                          }}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-teal-500 hover:bg-teal-400 text-slate-950 font-bold text-xs transition"
                        >
                          <span>Load Into Simulator</span>
                          <ArrowRight className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'new' && (
            <form onSubmit={handleCreate} className="space-y-4">
              {createdRecord ? (
                <div className="bg-emerald-950/40 border border-emerald-500/40 rounded-xl p-5 space-y-3">
                  <div className="flex items-center gap-2 text-emerald-400 font-semibold text-sm">
                    <CheckCircle2 className="w-5 h-5" />
                    <span>Preregistration Successfully Locked and Stamped!</span>
                  </div>
                  <p className="text-xs text-slate-300">
                    Your hypothesis has been immutably recorded in the institutional research ledger.
                  </p>
                  <div className="p-3 bg-slate-950 rounded-lg font-mono text-xs text-slate-300 space-y-1">
                    <div><span className="text-slate-500">ID:</span> {createdRecord.preregistration_id}</div>
                    <div><span className="text-slate-500">Config SHA-256:</span> {createdRecord.config_hash}</div>
                    <div><span className="text-slate-500">Timestamp:</span> {createdRecord.timestamp_utc}</div>
                  </div>
                  <div className="pt-2 flex gap-3">
                    {onSelectHypothesis && (
                      <button
                        type="button"
                        onClick={() => {
                          onSelectHypothesis(createdRecord);
                          onClose();
                        }}
                        className="px-4 py-2 rounded-lg bg-teal-500 text-slate-950 font-bold text-xs hover:bg-teal-400 transition flex items-center gap-2"
                      >
                        <span>Launch Simulator With This Hypothesis</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setCreatedRecord(null)}
                      className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs hover:bg-slate-700 transition"
                    >
                      Create Another
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {errorMsg && (
                    <div className="flex items-center gap-2 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs">
                      <AlertCircle className="w-4 h-4 shrink-0" />
                      <span>{errorMsg}</span>
                    </div>
                  )}

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">Hypothesis Code</label>
                      <input
                        type="text"
                        value={hypothesisId}
                        onChange={(e) => setHypothesisId(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-teal-500"
                        placeholder="H-004"
                        required
                      />
                    </div>
                    <div className="sm:col-span-2">
                      <label className="block text-xs font-semibold text-slate-300 mb-1">Hypothesis Title</label>
                      <input
                        type="text"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-teal-500"
                        placeholder="e.g. Cross-Asset Volatility Skew Momentum"
                        required
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">
                      Economic Mechanism & Market Inefficiency (Who loses on the other side?)
                    </label>
                    <textarea
                      rows={3}
                      value={economicMechanism}
                      onChange={(e) => setEconomicMechanism(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-white focus:outline-none focus:border-teal-500 leading-relaxed"
                      placeholder="Specify the behavioral constraint, structural friction, or risk premium driving returns..."
                      required
                    />
                  </div>

                  {/* Universe and Target Asset */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">Target Asset</label>
                      <select
                        value={targetAsset}
                        onChange={(e) => setTargetAsset(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-teal-500"
                      >
                        <option value="SPY">SPY (S&P 500 ETF)</option>
                        <option value="QQQ">QQQ (Nasdaq 100 ETF)</option>
                        <option value="IWM">IWM (Russell 2000 ETF)</option>
                        <option value="TLT">TLT (20+ Year Treasury Bond ETF)</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">Model Architecture</label>
                      <select
                        value={modelType}
                        onChange={(e) => setModelType(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-teal-500"
                      >
                        <option value="regularized_directional_logistic">Regularized Directional Logistic (L1/L2)</option>
                        <option value="regime_conditioned_gb">Regime-Conditioned Gradient Boosting</option>
                        <option value="walk_forward_baseline">Baseline Single-Asset Walk-Forward</option>
                      </select>
                    </div>
                  </div>

                  {/* Universe Selector */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Asset Universe</label>
                    <div className="flex flex-wrap gap-2">
                      {['SPY', 'QQQ', 'IWM', 'TLT', 'DIA', 'VXX'].map((asset) => (
                        <button
                          type="button"
                          key={asset}
                          onClick={() => toggleUniverseAsset(asset)}
                          className={`px-3 py-1 rounded-md text-xs font-mono transition ${
                            universe.includes(asset)
                              ? 'bg-teal-500/20 text-teal-300 border border-teal-500/40'
                              : 'bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'
                          }`}
                        >
                          {asset}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Feature Space */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">
                      Preregistered Feature Set ({selectedFeatures.length} selected)
                    </label>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 max-h-36 overflow-y-auto p-2 bg-slate-950 border border-slate-800 rounded-lg text-xs">
                      {availableFeatures.map((feat) => (
                        <label
                          key={feat}
                          className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white"
                        >
                          <input
                            type="checkbox"
                            checked={selectedFeatures.includes(feat)}
                            onChange={() => toggleFeature(feat)}
                            className="rounded border-slate-700 text-teal-500 focus:ring-teal-400"
                          />
                          <span className="font-mono text-[11px] truncate">{feat}</span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Gate Thresholds */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">Min Net Sharpe Gate</label>
                      <input
                        type="number"
                        step="0.05"
                        value={minNetSharpe}
                        onChange={(e) => setMinNetSharpe(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-teal-500"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">Max Drawdown Gate</label>
                      <input
                        type="number"
                        step="0.01"
                        value={maxDrawdown}
                        onChange={(e) => setMaxDrawdown(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-teal-500"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">Placebo Separation p-val</label>
                      <input
                        type="number"
                        step="0.005"
                        value={placeboPValue}
                        onChange={(e) => setPlaceboPValue(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-teal-500"
                      />
                    </div>
                  </div>

                  {/* Researcher sign-off */}
                  <div className="pt-2">
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Authorizing Researcher Sign-Off</label>
                    <input
                      type="text"
                      value={researcherName}
                      onChange={(e) => setResearcherName(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-teal-500"
                      placeholder="Name / Quantitative Committee Member"
                      required
                    />
                  </div>

                  <div className="pt-4 flex justify-end gap-3 border-t border-slate-800">
                    <button
                      type="button"
                      onClick={onClose}
                      className="px-4 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs hover:bg-slate-700 transition"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className="px-5 py-2 rounded-lg bg-teal-500 hover:bg-teal-400 text-slate-950 font-bold text-xs transition flex items-center gap-2 shadow-lg disabled:opacity-50"
                    >
                      <Lock className="w-4 h-4" />
                      <span>{isSubmitting ? 'Locking Hash...' : 'Sign & Lock Preregistration'}</span>
                    </button>
                  </div>
                </>
              )}
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

import React, { useState, useEffect } from 'react';
import { Play, CheckCircle2, AlertCircle, RefreshCw, Layers, ShieldCheck, ArrowRight, Save, Download, Compass, Sparkles, Sliders, Lock, ShieldAlert, Zap, X } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, AreaChart, Area } from 'recharts';
import { runWalkForwardSimulation, SimulationParams, evaluateGateResults } from '../utils/quantEngine';
import { ExperimentRecord, PreregistrationRecord } from '../types';
import { StrategyDiscoverySuite } from './StrategyDiscoverySuite';
import { PreflightLeakageScanner } from './PreflightLeakageScanner';
import { PlaceboNullVisualizer } from './PlaceboNullVisualizer';
import { SafeguardsPanel } from './SafeguardsPanel';

interface SimulatorTabProps {
  globalTrials: number;
  highwaterMark?: number;
  onRegisterExperiment: (newExp: ExperimentRecord) => void;
  onInspectExperiment: (exp: ExperimentRecord) => void;
  onNavigateToPaperTrading?: () => void;
  onOpenPreregistration?: () => void;
  selectedPrereg?: PreregistrationRecord | null;
  onClearSelectedPrereg?: () => void;
}

export const SimulatorTab: React.FC<SimulatorTabProps> = ({
  globalTrials,
  highwaterMark = 63,
  onRegisterExperiment,
  onInspectExperiment,
  onNavigateToPaperTrading,
  onOpenPreregistration,
  selectedPrereg,
  onClearSelectedPrereg,
}) => {
  const [subTab, setSubTab] = useState<'discovery' | 'single' | 'preflight' | 'placebo' | 'safeguards'>('discovery');
  const [params, setParams] = useState<SimulationParams>({
    strategyType: 'regime_conditioned_gb',
    hypothesis_name: 'Macro Volatility Tilt (GB)',
    discovery_notes: 'Conditioned on volatility regime switches; scales down beta in turbulent regimes, captures trend in normal regimes.',
    universe: ['SPY', 'QQQ', 'TLT'],
    target: 'SPY',
    fee_bps: 5.0,
    slippage_bps: 1.0,
    signal_delay: 0,
    n_placebo_runs: 20,
    seed: 88
  });

  // When a preregistration is selected, synchronize simulation params to its contract
  useEffect(() => {
    if (selectedPrereg) {
      setSubTab('single');
      setParams((prev) => ({
        ...prev,
        hypothesis_name: `${selectedPrereg.hypothesis_id}: ${selectedPrereg.title}`,
        discovery_notes: selectedPrereg.economic_mechanism,
        universe: selectedPrereg.universe,
        target: selectedPrereg.target,
        strategyType: (selectedPrereg.model_type as any) || prev.strategyType,
      }));
    }
  }, [selectedPrereg]);

  const [isRunning, setIsRunning] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [activeSimulationResult, setActiveSimulationResult] = useState<ExperimentRecord | null>(null);
  const [isSaved, setIsSaved] = useState(false);

  const pipelineStages = [
    "LockedTestProtocol Invariant Check & PIT Data Loading",
    "6-Dimensional Anti-Leakage Perturbation Test (Delta = 0.000)",
    "Fitting 7 Walk-Forward Folds (5 Purge & 5 Embargo Bars)",
    "Robustness Stress Testing (Transaction Fees & Execution Delays)",
    "Generating Placebo Empirical Null Distribution",
    "Running Stationary Block Bootstrap (500 Samples)",
    "Evaluating 11 Institutional Promotion Gates"
  ];

  const handleRunSimulation = () => {
    setIsRunning(true);
    setCurrentStep(0);
    setActiveSimulationResult(null);
    setIsSaved(false);

    // Progressive pipeline animation
    let step = 0;
    const interval = setInterval(() => {
      step++;
      setCurrentStep(step);
      if (step >= pipelineStages.length) {
        clearInterval(interval);
        const result = runWalkForwardSimulation(params, globalTrials);
        setActiveSimulationResult(result);
        setIsRunning(false);
      }
    }, 280);
  };

  const handleSaveToLeaderboard = () => {
    if (!activeSimulationResult) return;
    onRegisterExperiment(activeSimulationResult);
    setIsSaved(true);
  };

  const toggleUniverseAsset = (asset: string) => {
    if (params.universe.includes(asset)) {
      if (params.universe.length > 1) {
        setParams({ ...params, universe: params.universe.filter(a => a !== asset) });
      }
    } else {
      setParams({ ...params, universe: [...params.universe, asset] });
    }
  };

  return (
    <div className="space-y-6">
      {/* Mode Switcher: Discovery Suite vs Single Interactive Trial vs Quant Integrity Diagnostics */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/80 p-2 rounded-xl border border-slate-800">
        <div className="flex flex-wrap items-center gap-2">
          <button
            id="tab-discovery-suite"
            onClick={() => setSubTab('discovery')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              subTab === 'discovery'
                ? 'bg-teal-500 text-slate-950 shadow-md shadow-teal-500/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Compass className="w-3.5 h-3.5" />
            <span>Autonomous Discovery</span>
          </button>

          <button
            id="tab-single-trial"
            onClick={() => setSubTab('single')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              subTab === 'single'
                ? 'bg-teal-500 text-slate-950 shadow-md shadow-teal-500/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Walk-Forward (7 Folds)</span>
          </button>

          <button
            id="tab-preflight-scan"
            onClick={() => setSubTab('preflight')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              subTab === 'preflight'
                ? 'bg-teal-500 text-slate-950 shadow-md shadow-teal-500/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>Pre-Flight Leakage Scanner</span>
          </button>

          <button
            id="tab-placebo-null"
            onClick={() => setSubTab('placebo')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              subTab === 'placebo'
                ? 'bg-teal-500 text-slate-950 shadow-md shadow-teal-500/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span>Placebo &amp; Hansen SPA</span>
          </button>

          <button
            id="tab-safeguards"
            onClick={() => setSubTab('safeguards')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              subTab === 'safeguards'
                ? 'bg-teal-500 text-slate-950 shadow-md shadow-teal-500/20'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
            <span>Circuit Breakers</span>
          </button>
        </div>

        <div className="flex items-center gap-3">
          {onOpenPreregistration && (
            <button
              onClick={onOpenPreregistration}
              className="flex items-center gap-1.5 px-3 py-1 rounded bg-teal-500/10 border border-teal-500/30 text-teal-300 hover:bg-teal-500/20 text-xs font-mono transition"
            >
              <Lock className="w-3 h-3 text-amber-400" />
              <span>Preregistration Gate</span>
            </button>
          )}

          <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-slate-400 pr-2">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>V2.1.5 Invariant Enforced</span>
          </div>
        </div>
      </div>

      {/* Preregistration Binding Notification if active */}
      {selectedPrereg && subTab === 'single' && (
        <div className="p-3.5 rounded-xl bg-teal-950/40 border border-teal-500/40 text-xs flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-lg bg-teal-500/20 text-teal-300">
              <Lock className="w-4 h-4" />
            </div>
            <div>
              <div className="text-white font-semibold flex items-center gap-2">
                <span>Simulation Bound to Preregistered Hypothesis:</span>
                <span className="font-mono text-teal-300">{selectedPrereg.hypothesis_id} - {selectedPrereg.title}</span>
              </div>
              <p className="text-slate-400 text-[11px]">
                Config Fingerprint: <code className="font-mono text-teal-200">{selectedPrereg.config_hash}</code> • Target: {selectedPrereg.target} • Universe: {selectedPrereg.universe.join(', ')}
              </p>
            </div>
          </div>
          {onClearSelectedPrereg && (
            <button
              onClick={onClearSelectedPrereg}
              className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition"
              title="Unlock Custom Parameters"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      )}

      {subTab === 'discovery' && (
        <StrategyDiscoverySuite
          globalTrials={globalTrials}
          onRegisterExperiment={onRegisterExperiment}
          onInspectExperiment={onInspectExperiment}
          onNavigateToPaperTrading={onNavigateToPaperTrading}
        />
      )}

      {subTab === 'preflight' && (
        <PreflightLeakageScanner />
      )}

      {subTab === 'placebo' && (
        <PlaceboNullVisualizer
          observedSharpe={activeSimulationResult ? activeSimulationResult.net_metrics.full_oos_sharpe : 0.424}
          strategyName={activeSimulationResult ? activeSimulationResult.strategy : 'Walk-Forward Gradient Boosting (Baseline)'}
        />
      )}

      {subTab === 'safeguards' && (
        <SafeguardsPanel highwaterMark={highwaterMark} />
      )}

      {subTab === 'single' && (
        <div className="space-y-6">
          {/* Introduction banner */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <h3 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                  <span>Walk-Forward Research Simulator</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-teal-500/10 text-teal-400 border border-teal-500/20 font-mono">
                    Pipeline Invariant Active
                  </span>
                </h3>
                <p className="text-xs sm:text-sm text-slate-400 mt-1 max-w-3xl">
                  Execute a fully audited walk-forward trial across 7 temporal folds with 5-bar purges and embargos. 
                  The engine automatically calculates gross vs. net alpha, applies cost and execution delay stress testing, 
                  constructs empirical placebo nulls, and runs the 14-gate institutional promotion barrier.
                </p>
              </div>

              <div className="flex items-center gap-3">
                <button
                  id="btn-run-simulation"
                  onClick={handleRunSimulation}
                  disabled={isRunning}
                  className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition shadow-lg ${
                    isRunning
                      ? 'bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700'
                      : 'bg-teal-500 hover:bg-teal-400 text-slate-950 shadow-teal-500/20'
                  }`}
                >
                  {isRunning ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Executing Pipeline ({currentStep + 1}/7)...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 fill-current" />
                      <span>Run Walk-Forward Trial</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Simulator Parameters Panel */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Column 1: Model & Universe */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
              <h4 className="text-xs font-mono uppercase text-slate-400 font-semibold tracking-wider">
                1. Strategy & Target Universe
              </h4>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Model Architecture
                </label>
                <select
                  value={params.strategyType}
                  onChange={(e) => {
                    const st = e.target.value as any;
                    let hypName = params.hypothesis_name;
                    let discNotes = params.discovery_notes;
                    let universe = params.universe;
                    if (st === 'h001_spillover') {
                      hypName = 'H-001 Information Diffusion Spillover';
                      discNotes = 'SPY/QQQ ratio z-score conditional asset selection with 9-feature panel. Tested on untouched 2021-2026 data. Full-strategy placebo p=0.667.';
                      universe = ['SPY', 'QQQ', '^VIX'];
                    } else if (st === 'h002_liquidity') {
                      hypName = 'H-002-R1 Small-Cap Liquidity Provision';
                      discNotes = 'Amended cross-sectional dollar-neutral long/short on 285 small/mid-caps. Amihud illiquidity + signed volume proxy. High turnover (72x) drag.';
                      universe = ['285-Stock Small/Mid-Cap Universe'];
                    } else if (st === 'h003_volatility') {
                      hypName = 'H-003-R1 Volatility Shock Allocation';
                      discNotes = 'Daily volatility shock allocation across 17 ETFs and VIX spot. Inverse realized volatility weighting with crisis drawdown stand-down.';
                      universe = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'VNQ', 'GLD', 'TLT', 'IEF', 'LQD', 'HYG', 'DBC', 'XLE', 'XLF', 'XLK', 'XLV', 'XLI', '^VIX'];
                    } else if (st === 'h004_macro_yield_curve') {
                      hypName = 'H-004 Macro Yield Curve & Credit Spread Momentum';
                      discNotes = 'Credit risk appetite & 10Y-2Y slope leading indicator. Monthly rebalance, 1.95x annual turnover, $850M capacity. Robust to 1-2 bar delay.';
                      universe = ['TLT', 'IEF', 'HYG', 'LQD', 'SPY'];
                    } else if (st === 'h007_quality_minus_junk' || st === 'h005_quality_minus_junk') {
                      hypName = 'H-007 Quality-Minus-Junk Low-Turnover Core';
                      discNotes = 'Systematic long high-profitability low-debt vs short speculative junk. Quarterly rebalancing, 2.2x turnover, $450M capacity.';
                      universe = ['Top 100 Liquid US Equities'];
                    } else if (st === 'h008_microstructure_ofi' || st === 'h006_microstructure_ofi') {
                      hypName = 'H-008 Microstructure OFI Liquidity Provision';
                      discNotes = 'Intraday order flow imbalance (OFI) passive limit replenishment filtered by VPIN toxicity guard. High intraday turnover stress test.';
                      universe = ['SPY', 'QQQ'];
                    } else if (st === 'regime_conditioned_gb') {
                      hypName = 'Macro Volatility Tilt (GB)';
                      discNotes = 'Conditioned on volatility regime switches; scales down beta in turbulent regimes, captures trend in normal regimes.';
                    } else if (st === 'cross_asset_momentum') {
                      hypName = 'Cross-Asset Dual Momentum Flight-to-Safety';
                      discNotes = 'Dual-momentum rotation between risk assets (SPY, QQQ) and flight-to-safety assets (TLT, GLD).';
                    } else if (st === 'multi_factor_ensemble') {
                      hypName = 'Multi-Factor Forest Ensemble';
                      discNotes = 'Blends 4 independent orthogonal factor families (Momentum, Trend, Realized Vol, Volume Z-Score) with equal weighting.';
                    } else if (st === 'volume_mean_reversion') {
                      hypName = 'Volume-Confirmed Fast Mean Reversion';
                      discNotes = 'Exploits short-term intraday overextensions filtered by 2-sigma volume spikes. High turnover stress test.';
                    }
                    setParams({ ...params, strategyType: st, hypothesis_name: hypName, discovery_notes: discNotes, universe });
                  }}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:border-teal-500 focus:outline-none"
                >
                  <optgroup label="Phase 2 Next-Gen Institutional Hypotheses">
                    <option value="h004_macro_yield_curve">H-004: Macro Yield Curve & Credit Momentum (1.95x Turnover, $850M Cap)</option>
                    <option value="h007_quality_minus_junk">H-007: Quality-Minus-Junk Low-Turnover Core (2.2x Turnover, $450M Cap)</option>
                    <option value="h008_microstructure_ofi">H-008: Microstructure OFI Liquidity Provision (Intraday Queue Depth)</option>
                  </optgroup>
                  <optgroup label="Institutional Research Hypotheses (Canonical)">
                    <option value="h001_spillover">H-001: Cross-Asset Spillover (SPY/QQQ Diffusion)</option>
                    <option value="h002_liquidity">H-002-R1: Liquidity Reversal (285 Small-Cap Stocks)</option>
                    <option value="h003_volatility">H-003-R1: Volatility Risk Premium (17 ETFs + VIX)</option>
                  </optgroup>
                  <optgroup label="Exploratory Research Architectures">
                    <option value="regime_conditioned_gb">Regime-Conditioned Volatility Tilt (GB) — High Sharpe</option>
                    <option value="cross_asset_momentum">Cross-Asset Dual Momentum (SPY/QQQ/GLD/TLT)</option>
                    <option value="multi_factor_ensemble">Multi-Factor Forest Ensemble (4 Factor Families)</option>
                    <option value="volume_mean_reversion">Volume-Confirmed Fast Mean Reversion (Turnover Stress)</option>
                    <option value="gradient_boosting">Walk-Forward Gradient Boosting (Standard)</option>
                    <option value="high_threshold_gb">High-Threshold GB (Conservative 0.70 threshold)</option>
                    <option value="logistic_regression">Logistic Regression (Linear Baseline)</option>
                    <option value="baseline">Baseline Moving Average Cross</option>
                  </optgroup>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Hypothesis Formulation
                </label>
                <input
                  type="text"
                  value={params.hypothesis_name || ''}
                  onChange={(e) => setParams({ ...params, hypothesis_name: e.target.value })}
                  placeholder="e.g. Volatility-Regime Conditioned Beta Decay"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:border-teal-500 focus:outline-none placeholder-slate-600"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Discovery Rationale / Notes
                </label>
                <textarea
                  rows={2}
                  value={params.discovery_notes || ''}
                  onChange={(e) => setParams({ ...params, discovery_notes: e.target.value })}
                  placeholder="Theoretical alpha intuition, economic mechanism, factor rationale..."
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:border-teal-500 focus:outline-none placeholder-slate-600 resize-none"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Target Asset
                </label>
                <div className="flex gap-2">
                  {['SPY', 'QQQ', 'AAPL', 'MSFT'].map((tgt) => (
                    <button
                      key={tgt}
                      onClick={() => setParams({ ...params, target: tgt })}
                      className={`flex-1 py-1.5 text-xs font-mono rounded-lg border transition ${
                        params.target === tgt
                          ? 'bg-teal-500/20 text-teal-300 border-teal-500/40 font-bold'
                          : 'bg-slate-950 text-slate-400 border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      {tgt}
                    </button>
                  ))}
                </div>
              </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Features Universe Pool
            </label>
            <div className="flex flex-wrap gap-1.5">
              {['SPY', 'QQQ', 'AAPL', 'MSFT', 'GLD', 'TLT'].map((sym) => {
                const isSelected = params.universe.includes(sym);
                return (
                  <button
                    key={sym}
                    onClick={() => toggleUniverseAsset(sym)}
                    className={`px-2.5 py-1 text-xs font-mono rounded-md border transition ${
                      isSelected
                        ? 'bg-slate-800 text-teal-300 border-teal-500/30'
                        : 'bg-slate-950 text-slate-500 border-slate-800 hover:text-slate-300'
                    }`}
                  >
                    {sym}
                  </button>
                );
              })}
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              Cross-asset relative strength features are computed across selected pool.
            </p>
          </div>
        </div>

        {/* Column 2: Transaction Costs & Execution Delays */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <h4 className="text-xs font-mono uppercase text-slate-400 font-semibold tracking-wider">
            2. Friction & Execution Delays
          </h4>

          <div>
            <div className="flex justify-between text-xs mb-1.5">
              <span className="text-slate-300">Transaction Fee</span>
              <span className="font-mono text-teal-400 font-bold">{params.fee_bps} bps / trade</span>
            </div>
            <input
              type="range"
              min="0"
              max="20"
              step="0.5"
              value={params.fee_bps}
              onChange={(e) => setParams({ ...params, fee_bps: parseFloat(e.target.value) })}
              className="w-full accent-teal-400 cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>0 bps (Free)</span>
              <span>5 bps (Baseline)</span>
              <span>20 bps (High)</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between text-xs mb-1.5">
              <span className="text-slate-300">Slippage</span>
              <span className="font-mono text-teal-400 font-bold">{params.slippage_bps} bps</span>
            </div>
            <input
              type="range"
              min="0"
              max="5"
              step="0.5"
              value={params.slippage_bps}
              onChange={(e) => setParams({ ...params, slippage_bps: parseFloat(e.target.value) })}
              className="w-full accent-teal-400 cursor-pointer"
            />
          </div>

          <div>
            <div className="flex justify-between text-xs mb-1.5">
              <span className="text-slate-300">Execution Delay</span>
              <span className="font-mono text-amber-400 font-bold">
                {params.signal_delay === 0 ? 'Next Open (t+1 09:30)' : `+${params.signal_delay} bar(s)`}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-1.5">
              {[0, 1, 2, 3].map((delay) => (
                <button
                  key={delay}
                  onClick={() => setParams({ ...params, signal_delay: delay })}
                  className={`py-1.5 text-xs font-mono rounded border transition ${
                    params.signal_delay === delay
                      ? 'bg-amber-500/20 text-amber-300 border-amber-500/40 font-bold'
                      : 'bg-slate-950 text-slate-400 border-slate-800'
                  }`}
                >
                  +{delay}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              Engine rule: Delays tests realism; signals generated at close of bar t trade at t+1 open.
            </p>
          </div>
        </div>

        {/* Column 3: Statistical Rigor & Seeds */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <h4 className="text-xs font-mono uppercase text-slate-400 font-semibold tracking-wider">
            3. Empirical Null & Replicates
          </h4>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Placebo Null Pipeline Repeats
            </label>
            <div className="grid grid-cols-3 gap-2">
              {[20, 50, 100].map((runs) => (
                <button
                  key={runs}
                  onClick={() => setParams({ ...params, n_placebo_runs: runs })}
                  className={`py-1.5 text-xs font-mono rounded border transition ${
                    params.n_placebo_runs === runs
                      ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40 font-bold'
                      : 'bg-slate-950 text-slate-400 border-slate-800'
                  }`}
                >
                  {runs} runs
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              Minimum 20 repetitions mandatory to prevent single-shuffle statistical hazard.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Random State Seed
            </label>
            <input
              type="number"
              value={params.seed}
              onChange={(e) => setParams({ ...params, seed: parseInt(e.target.value) || 42 })}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-white focus:border-teal-500 focus:outline-none"
            />
          </div>

          <div className="pt-1">
            <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-[11px] text-slate-400 space-y-1">
              <div>• 7 Walk-Forward Folds: 2018 - 2025</div>
              <div>• 5 Purge Bars + 5 Embargo Bars</div>
              <div>• Stationary Block Bootstrap: 500 reps</div>
            </div>
          </div>
        </div>
      </div>

      {/* Running Pipeline Progress Indicator */}
      {isRunning && (
        <div className="bg-slate-900/90 border border-teal-500/40 rounded-xl p-6 shadow-xl space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold text-white flex items-center gap-2">
              <RefreshCw className="w-4 h-4 text-teal-400 animate-spin" />
              <span>Executing Walk-Forward Research Pipeline...</span>
            </h4>
            <span className="font-mono text-xs text-teal-400">
              Stage {Math.min(currentStep + 1, pipelineStages.length)} of {pipelineStages.length}
            </span>
          </div>

          <div className="w-full bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
            <div
              className="bg-teal-500 h-full transition-all duration-300"
              style={{ width: `${((currentStep + 1) / pipelineStages.length) * 100}%` }}
            />
          </div>

          <div className="space-y-1.5">
            {pipelineStages.map((stg, idx) => (
              <div
                key={idx}
                className={`flex items-center gap-2 text-xs font-mono transition ${
                  idx < currentStep
                    ? 'text-emerald-400'
                    : idx === currentStep
                    ? 'text-teal-300 font-bold'
                    : 'text-slate-600'
                }`}
              >
                {idx < currentStep ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                ) : idx === currentStep ? (
                  <RefreshCw className="w-3.5 h-3.5 text-teal-400 animate-spin" />
                ) : (
                  <span className="w-3.5 h-3.5 inline-block text-center text-slate-600">•</span>
                )}
                <span>{stg}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Simulation Result Presentation */}
      {activeSimulationResult && !isRunning && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl space-y-6">
          {/* Header & Status */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
            <div>
              <div className="flex items-center gap-3">
                <h4 className="font-mono text-lg font-bold text-white">
                  Trial Complete: {activeSimulationResult.experiment_id}
                </h4>
                <span className={`px-2.5 py-0.5 rounded text-xs font-semibold border ${
                  activeSimulationResult.promotion_state === 'ROBUST_OOS' || activeSimulationResult.promotion_state === 'CANDIDATE'
                    ? 'bg-teal-500/20 text-teal-300 border-teal-500/30'
                    : 'bg-rose-500/20 text-rose-300 border-rose-500/30'
                }`}>
                  State: {activeSimulationResult.promotion_state}
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono mt-1">
                Strategy: {activeSimulationResult.strategy} • Seed: {activeSimulationResult.seed} • Universe: {activeSimulationResult.universe.join(', ')}
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={handleSaveToLeaderboard}
                disabled={isSaved}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition border ${
                  isSaved
                    ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/60 cursor-default'
                    : 'bg-teal-500 hover:bg-teal-400 text-slate-950 border-transparent shadow'
                }`}
              >
                <Save className="w-3.5 h-3.5" />
                <span>{isSaved ? 'Registered to Leaderboard' : 'Register to Leaderboard'}</span>
              </button>

              <button
                onClick={() => onInspectExperiment(activeSimulationResult)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition"
              >
                <span>Full Audit View</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Key KPI Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 font-mono text-xs">
            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
              <span className="text-slate-400">Gross Sharpe</span>
              <div className="text-base font-bold text-slate-200">
                {activeSimulationResult.gross_metrics.full_oos_sharpe.toFixed(3)}
              </div>
              <span className="text-[10px] text-slate-500">Return: {(activeSimulationResult.gross_metrics.full_oos_return * 100).toFixed(1)}%</span>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
              <span className="text-slate-400">Net OOS Sharpe</span>
              <div className={`text-base font-bold ${activeSimulationResult.net_metrics.full_oos_sharpe > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {activeSimulationResult.net_metrics.full_oos_sharpe > 0 ? '+' : ''}{activeSimulationResult.net_metrics.full_oos_sharpe.toFixed(3)}
              </div>
              <span className="text-[10px] text-slate-500">Return: {(activeSimulationResult.net_metrics.full_oos_return * 100).toFixed(1)}%</span>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
              <span className="text-slate-400">Cost Drag</span>
              <div className="text-base font-bold text-amber-400">
                -{(activeSimulationResult.net_metrics.cost_drag * 100).toFixed(2)}%
              </div>
              <span className="text-[10px] text-slate-500">{activeSimulationResult.costs.fee_bps} bps fee drag</span>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
              <span className="text-slate-400">Max Drawdown</span>
              <div className="text-base font-bold text-rose-400">
                {(activeSimulationResult.oos_metrics.full_oos_max_dd * 100).toFixed(1)}%
              </div>
              <span className="text-[10px] text-slate-500">7-year OOS test</span>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
              <span className="text-slate-400">Placebo Percentile</span>
              <div className={`text-base font-bold ${activeSimulationResult.placebo_statistics.percentile >= 0.95 ? 'text-emerald-400' : 'text-amber-400'}`}>
                {(activeSimulationResult.placebo_statistics.percentile * 100).toFixed(1)}%
              </div>
              <span className="text-[10px] text-slate-500">p={activeSimulationResult.placebo_statistics.adjusted_p.toFixed(3)}</span>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800">
              <span className="text-slate-400">Positive Folds</span>
              <div className="text-base font-bold text-teal-400">
                {activeSimulationResult.oos_metrics.positive_folds} / 7
              </div>
              <span className="text-[10px] text-slate-500">Single fold share: {(activeSimulationResult.oos_metrics.single_fold_share * 100).toFixed(0)}%</span>
            </div>
          </div>

          {/* Visual Charts: Fold Breakdown, Cost Curve, and Cumulative Fold Equity */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
              <h5 className="font-semibold text-white text-xs mb-3 font-mono">
                Walk-Forward Fold OOS Sharpe
              </h5>
              <div className="h-44">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={activeSimulationResult.folds} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="fold_id" stroke="#94a3b8" tickFormatter={(v) => `F${v}`} />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }} />
                    <ReferenceLine y={0} stroke="#64748b" />
                    <Bar dataKey="oos_sharpe" fill="#0d9488" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
              <h5 className="font-semibold text-white text-xs mb-3 font-mono">
                Fee Stress Curve (Net Sharpe vs BPS)
              </h5>
              <div className="h-44">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={activeSimulationResult.robustness.cost_stress} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="fee_bps" stroke="#94a3b8" tickFormatter={(v) => `${v}bp`} />
                    <YAxis stroke="#94a3b8" />
                    <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }} />
                    <ReferenceLine y={0} stroke="#64748b" />
                    <Line type="monotone" dataKey="sharpe" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Fold-by-Fold Cumulative OOS Equity Progression */}
            <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
              <h5 className="font-semibold text-white text-xs mb-3 font-mono flex items-center justify-between">
                <span>Cumulative Walk-Forward Equity</span>
                <span className="text-[10px] text-teal-400 font-normal">Base 100</span>
              </h5>
              <div className="h-44">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart
                    data={(() => {
                      let eq = 100;
                      return (activeSimulationResult.folds || []).map((f) => {
                        eq = eq * (1 + (f.oos_net_return ?? 0));
                        return {
                          fold: `F${f.fold_id}`,
                          equity: parseFloat(eq.toFixed(2)),
                        };
                      });
                    })()}
                    margin={{ top: 5, right: 5, left: -20, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="fold" stroke="#94a3b8" />
                    <YAxis stroke="#94a3b8" domain={['auto', 'auto']} />
                    <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155' }} />
                    <Area type="monotone" dataKey="equity" stroke="#38bdf8" fill="#0284c7" fillOpacity={0.25} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Promotion Gates Status */}
          <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
            <h5 className="font-semibold text-slate-300 text-xs mb-3 font-mono flex items-center justify-between">
              <span>Promotion Gate Audit Results</span>
              <span>
                {evaluateGateResults(activeSimulationResult).filter(g => g.passed).length} / {evaluateGateResults(activeSimulationResult).length} Gates Passed
              </span>
            </h5>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {evaluateGateResults(activeSimulationResult).map((gate) => (
                <div
                  key={gate.id}
                  className={`p-2.5 rounded border text-xs flex items-center justify-between ${
                    gate.passed
                      ? 'bg-emerald-950/20 border-emerald-800/40 text-slate-300'
                      : 'bg-rose-950/20 border-rose-800/40 text-slate-400'
                  }`}
                >
                  <div className="flex items-center gap-2 truncate pr-2">
                    {gate.passed ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                    )}
                    <span className="truncate">{gate.name}</span>
                  </div>
                  <span className={`font-mono text-[11px] font-bold shrink-0 ${gate.passed ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {gate.passed ? 'PASS' : 'FAIL'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
        </div>
      )}
    </div>
  );
};

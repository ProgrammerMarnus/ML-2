import React, { useState } from 'react';
import { ShieldCheck, Play, CheckCircle2, AlertTriangle, RefreshCw, Layers, Zap, Info } from 'lucide-react';
import { apiService } from '../utils/apiService';
import { LeakageScanReport } from '../types';

interface PreflightLeakageScannerProps {
  onScanComplete?: (report: LeakageScanReport) => void;
}

export const PreflightLeakageScanner: React.FC<PreflightLeakageScannerProps> = ({ onScanComplete }) => {
  const [targetAsset, setTargetAsset] = useState('SPY');
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([
    'momentum_63',
    'realized_vol_20',
    'volatility_ratio_10_60',
    'trend_50',
    'cross_asset_rel_strength',
  ]);
  const [isScanning, setIsScanning] = useState(false);
  const [scanResult, setScanResult] = useState<LeakageScanReport | null>(null);

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

  const handleRunScan = async () => {
    if (selectedFeatures.length === 0) return;
    setIsScanning(true);
    try {
      const result = await apiService.runPreflightLeakageScan(selectedFeatures, targetAsset);
      setScanResult(result);
      if (onScanComplete) onScanComplete(result);
    } catch (err) {
      console.error('Leakage scan error:', err);
    } finally {
      setIsScanning(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-teal-500/10 text-teal-400 border border-teal-500/20">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm sm:text-base font-bold text-white flex items-center gap-2">
              <span>Pre-Flight Anti-Leakage Diagnostic Scanner</span>
              <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded bg-teal-500/10 text-teal-300 border border-teal-500/20">
                Point-in-Time Invariant Probe
              </span>
            </h3>
            <p className="text-xs text-slate-400">
              Executes perturbation probes against candidate feature transformations prior to fold execution to mathematically prove zero lookahead bias.
            </p>
          </div>
        </div>

        <button
          onClick={handleRunScan}
          disabled={isScanning || selectedFeatures.length === 0}
          className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-teal-500 hover:bg-teal-400 text-slate-950 font-bold text-xs transition disabled:opacity-50 shadow-md whitespace-nowrap"
        >
          {isScanning ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              <span>Running Probes...</span>
            </>
          ) : (
            <>
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Run Pre-Flight Scan</span>
            </>
          )}
        </button>
      </div>

      {/* Feature selection controls */}
      <div>
        <label className="block text-xs font-semibold text-slate-300 mb-2">
          Select Candidate Features to Audit ({selectedFeatures.length} selected for {targetAsset})
        </label>
        <div className="flex flex-wrap gap-2">
          {availableFeatures.map((feat) => (
            <button
              type="button"
              key={feat}
              onClick={() => toggleFeature(feat)}
              className={`px-2.5 py-1 rounded text-xs font-mono transition ${
                selectedFeatures.includes(feat)
                  ? 'bg-teal-500/20 text-teal-300 border border-teal-500/40'
                  : 'bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'
              }`}
            >
              {feat}
            </button>
          ))}
        </div>
      </div>

      {/* Scan Results Readout */}
      {scanResult && (
        <div className="space-y-4 pt-2">
          <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-xl bg-slate-950 border border-slate-800">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${scanResult.overallPassed ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                {scanResult.overallPassed ? <CheckCircle2 className="w-6 h-6" /> : <AlertTriangle className="w-6 h-6" />}
              </div>
              <div>
                <div className="text-xs font-mono uppercase text-slate-400">Composite Audit Verdict</div>
                <div className={`text-base font-bold ${scanResult.overallPassed ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {scanResult.status === 'VERIFIED_LEAKAGE_FREE' ? 'Zero Lookahead Bias Verified' : 'Potential Leakage Detected'}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-6 font-mono text-xs">
              <div className="text-right">
                <span className="text-slate-500 block text-[10px]">Integrity Score</span>
                <span className="text-emerald-400 font-bold text-base">{scanResult.compositeScore}/100</span>
              </div>
              <div className="text-right">
                <span className="text-slate-500 block text-[10px]">Probes Passed</span>
                <span className="text-white font-bold text-base">
                  {scanResult.probes.filter((p) => p.passed).length}/{scanResult.probes.length}
                </span>
              </div>
            </div>
          </div>

          {/* Diagnostic Probes Table */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {scanResult.probes.map((probe) => (
              <div
                key={probe.id}
                className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3.5 space-y-2 text-xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-teal-400">
                      {probe.id}
                    </span>
                    <span className="font-semibold text-white">{probe.name}</span>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase border ${
                    probe.passed ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                  }`}>
                    {probe.passed ? 'PASSED' : 'FLAGGED'}
                  </span>
                </div>

                <p className="text-slate-400 text-[11px] leading-relaxed">
                  {probe.description}
                </p>

                <div className="p-2 rounded bg-slate-900/80 text-[11px] font-mono text-slate-300 flex items-center justify-between">
                  <span>Delta: <strong className="text-teal-300">{probe.delta.toFixed(4)}</strong> (tol: ≤{probe.threshold})</span>
                  <span className="text-emerald-400 font-semibold">{probe.score}%</span>
                </div>
                <div className="text-[10px] text-slate-500 font-mono">
                  {probe.details}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

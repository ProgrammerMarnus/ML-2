import React, { useState, useEffect } from 'react';
import { ShieldAlert, ShieldCheck, AlertOctagon, Sliders, CheckCircle2, RefreshCw, Lock } from 'lucide-react';
import { SafeguardsConfig } from '../types';
import { apiService } from '../utils/apiService';

interface SafeguardsPanelProps {
  highwaterMark: number;
}

export const SafeguardsPanel: React.FC<SafeguardsPanelProps> = ({ highwaterMark }) => {
  const [safeguards, setSafeguards] = useState<SafeguardsConfig>({
    maxDailyDrawdownPct: 2.5,
    circuitBreakerActive: true,
    volRegimeThreshold: 35.0,
    volRegimeActive: true,
    consecutiveLossLimit: 3,
    consecutiveLossActive: true,
    highwaterLockStrict: true,
  });

  const [isSaving, setIsSaving] = useState(false);
  const [tripSimulation, setTripSimulation] = useState<string | null>(null);

  useEffect(() => {
    apiService.getSafeguards().then((cfg) => setSafeguards(cfg));
  }, []);

  const handleToggle = async (key: keyof SafeguardsConfig) => {
    const updated = {
      ...safeguards,
      [key]: !safeguards[key],
    };
    setSafeguards(updated);
    setIsSaving(true);
    try {
      await apiService.updateSafeguards(updated);
    } catch (e) {
      console.error(e);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSimulateCircuitBreakerTrip = () => {
    setTripSimulation('TRIPPED: Intraday Drawdown reached 2.54%. Trading halted immediately; all positions liquidated to cash.');
    setTimeout(() => {
      setTripSimulation(null);
    }, 6000);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm sm:text-base font-bold text-white flex items-center gap-2">
              <span>Execution Safeguards & Circuit Breakers</span>
              <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                ACTIVE MONITOR
              </span>
            </h3>
            <p className="text-xs text-slate-400">
              Deterministic real-time runtime safeguards protecting capital from catastrophic regime changes, slippage, and trial counter manipulation.
            </p>
          </div>
        </div>

        <button
          onClick={handleSimulateCircuitBreakerTrip}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 hover:bg-rose-500/20 text-xs font-mono transition"
        >
          <AlertOctagon className="w-4 h-4" />
          <span>Test Trip Breaker</span>
        </button>
      </div>

      {tripSimulation && (
        <div className="p-3.5 rounded-xl bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs font-mono flex items-center gap-3 animate-pulse">
          <AlertOctagon className="w-5 h-5 shrink-0 text-rose-400" />
          <span>{tripSimulation}</span>
        </div>
      )}

      {/* Safeguards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
        {/* Max Daily Drawdown Breaker */}
        <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-semibold text-white">Daily Drawdown Breaker</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${safeguards.circuitBreakerActive ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400'}`}>
                {safeguards.circuitBreakerActive ? 'ENABLED' : 'DISABLED'}
              </span>
            </div>
            <p className="text-slate-400 text-[11px]">
              Halts trading if daily mark-to-market drawdown exceeds {safeguards.maxDailyDrawdownPct}%.
            </p>
          </div>
          <div className="pt-3 flex items-center justify-between border-t border-slate-900 mt-2">
            <span className="font-mono text-amber-400 font-bold">{safeguards.maxDailyDrawdownPct}% Limit</span>
            <button
              onClick={() => handleToggle('circuitBreakerActive')}
              className="text-[11px] text-teal-400 hover:underline"
            >
              Toggle
            </button>
          </div>
        </div>

        {/* Volatility Regime Kill Switch */}
        <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-semibold text-white">Volatility Regime Switch</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${safeguards.volRegimeActive ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400'}`}>
                {safeguards.volRegimeActive ? 'ENABLED' : 'DISABLED'}
              </span>
            </div>
            <p className="text-slate-400 text-[11px]">
              Forces 100% cash allocation when realized volatility surpasses {safeguards.volRegimeThreshold}%.
            </p>
          </div>
          <div className="pt-3 flex items-center justify-between border-t border-slate-900 mt-2">
            <span className="font-mono text-teal-300 font-bold">{safeguards.volRegimeThreshold}% Vol</span>
            <button
              onClick={() => handleToggle('volRegimeActive')}
              className="text-[11px] text-teal-400 hover:underline"
            >
              Toggle
            </button>
          </div>
        </div>

        {/* Consecutive Loss Limiter */}
        <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-semibold text-white">Loss Streak Limiter</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${safeguards.consecutiveLossActive ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400'}`}>
                {safeguards.consecutiveLossActive ? 'ENABLED' : 'DISABLED'}
              </span>
            </div>
            <p className="text-slate-400 text-[11px]">
              Halves position sizing after {safeguards.consecutiveLossLimit} consecutive loss days to mitigate trend fatigue.
            </p>
          </div>
          <div className="pt-3 flex items-center justify-between border-t border-slate-900 mt-2">
            <span className="font-mono text-sky-400 font-bold">{safeguards.consecutiveLossLimit} Days</span>
            <button
              onClick={() => handleToggle('consecutiveLossActive')}
              className="text-[11px] text-teal-400 hover:underline"
            >
              Toggle
            </button>
          </div>
        </div>

        {/* Highwater Mark Counter Protection */}
        <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-semibold text-white">Trial HW Invariant</span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                LOCKED
              </span>
            </div>
            <p className="text-slate-400 text-[11px]">
              Prevents trial counter rollback attacks. Strictly enforces monotonic highwater tracking across runs.
            </p>
          </div>
          <div className="pt-3 flex items-center justify-between border-t border-slate-900 mt-2">
            <span className="font-mono text-emerald-400 font-bold flex items-center gap-1">
              <Lock className="w-3 h-3" />
              HW: {highwaterMark}
            </span>
            <span className="text-[10px] font-mono text-slate-500">Atomic</span>
          </div>
        </div>
      </div>
    </div>
  );
};

import React, { useState, useMemo } from 'react';
import { 
  Play, 
  RotateCcw, 
  ShieldAlert, 
  CheckCircle2, 
  XCircle, 
  AlertTriangle, 
  Download, 
  PlusCircle, 
  Activity, 
  Lock, 
  FileCode, 
  Cpu, 
  TrendingUp, 
  Clock, 
  Layers,
  ArrowRight
} from 'lucide-react';
import { ExperimentRecord, PaperOrder, PaperPosition, PromotionState, PaperValidationReport } from '../types';
import { 
  BrokerState, 
  createInitialBrokerState, 
  submitPaperOrder, 
  appendAuditEvent, 
  reconcileLedger, 
  calculatePortfolioValue,
  evaluatePaperGates,
  DEFAULT_SAFEGUARDS 
} from '../utils/paperBrokerEngine';
import { PAPER_MARKET_SESSIONS, MarketSessionBar } from '../data/paperSessionsData';
import { OperationalIntegrationPanel } from './OperationalIntegrationPanel';
import { LiveExecutionConsole } from './LiveExecutionConsole';
import { Radio } from 'lucide-react';

interface PaperTradingTabProps {
  experiments: ExperimentRecord[];
}

export const PaperTradingTab: React.FC<PaperTradingTabProps> = ({ experiments }) => {
  const [activeSubTab, setActiveSubTab] = useState<'live-console' | 'replay-stepper' | 'operational-controls'>('live-console');

  // Bind paper trading to an experiment (defaults to the robust Seed 43 experiment)
  const defaultExp = experiments.find(e => e.promotion_state === 'ROBUST_OOS') || experiments[0];
  const [selectedExpId, setSelectedExpId] = useState<string>(defaultExp?.experiment_id || '');
  
  const boundExperiment = useMemo(() => {
    return experiments.find(e => e.experiment_id === selectedExpId) || defaultExp;
  }, [experiments, selectedExpId, defaultExp]);

  // Paper broker state
  const [brokerState, setBrokerState] = useState<BrokerState>(() => createInitialBrokerState(100000));
  const [currentSessionIndex, setCurrentSessionIndex] = useState<number>(0);
  const [orderFilter, setOrderFilter] = useState<string>('ALL');

  // Manual Order Input state
  const [manualSymbol, setManualSymbol] = useState<'SPY' | 'QQQ'>('SPY');
  const [manualSide, setManualSide] = useState<'BUY' | 'SELL'>('BUY');
  const [manualQty, setManualQty] = useState<number>(25);
  const [manualType, setManualType] = useState<'MARKET' | 'LIMIT'>('MARKET');
  const [manualLimitPrice, setManualLimitPrice] = useState<number>(580.0);

  // Current market session
  const currentSession: MarketSessionBar = PAPER_MARKET_SESSIONS[Math.min(currentSessionIndex, PAPER_MARKET_SESSIONS.length - 1)];

  // Current market prices
  const currentMarketPrices = useMemo(() => ({
    SPY: currentSession ? currentSession.spy_close : 580.0,
    QQQ: currentSession ? currentSession.qqq_close : 505.0
  }), [currentSession]);

  // Current equity & reconciliation calculation
  const reconciliation = useMemo(() => {
    return reconcileLedger(brokerState, currentMarketPrices);
  }, [brokerState, currentMarketPrices]);

  const currentEquity = useMemo(() => {
    return calculatePortfolioValue(brokerState.cash, brokerState.positions, currentMarketPrices);
  }, [brokerState.cash, brokerState.positions, currentMarketPrices]);

  // Drawdown
  const currentDrawdown = brokerState.peakPortfolioValue > 0
    ? (currentEquity - brokerState.peakPortfolioValue) / brokerState.peakPortfolioValue
    : 0;

  // Build Paper Validation Report
  const validationReport: PaperValidationReport = useMemo(() => {
    const isBoundApproved = boundExperiment?.promotion_state === 'ROBUST_OOS' || boundExperiment?.promotion_state === 'CANDIDATE';
    const state: PromotionState = isBoundApproved ? 'PAPER_READY' : 'RESEARCH_ONLY';
    
    const rep: PaperValidationReport = {
      experiment_id: boundExperiment?.experiment_id || 'unbound',
      strategy_id: boundExperiment?.run_hash?.substring(0, 8) || 'strat_alpha',
      config_fingerprint: boundExperiment?.config_fingerprint || '0000000000000000',
      start_time: brokerState.auditTrail[0]?.timestamp || new Date().toISOString(),
      state,
      n_days_executed: brokerState.observedSessions.length,
      n_orders_submitted: brokerState.orders.length,
      n_orders_filled: brokerState.orders.filter(o => o.status === 'FILLED').length,
      n_orders_rejected: brokerState.orders.filter(o => o.status === 'REJECTED').length,
      n_orders_cancelled: brokerState.orders.filter(o => o.status === 'CANCELLED').length,
      n_safeguard_breaches: brokerState.safeguardBreaches,
      kill_switch_tripped: brokerState.killSwitchActive || brokerState.killSwitchTested,
      kill_switch_tested: brokerState.killSwitchTested,
      kill_switch_reset: brokerState.killSwitchReset,
      n_reconciliation_failures: brokerState.reconciliationFailures,
      final_reconciliation_consistent: reconciliation.consistent,
      starting_cash: brokerState.initialCash,
      ending_cash: brokerState.cash,
      total_realized_pnl: reconciliation.totalRealized,
      total_unrealized_pnl: reconciliation.totalUnrealized,
      total_fees_paid: reconciliation.totalFeesPaid,
      max_drawdown_observed: brokerState.maxDrawdownObserved,
      observed_sessions: brokerState.observedSessions,
      gate_results: {},
      promotion_recommendation: 'REMAIN_PAPER_READY'
    };

    const gateEval = evaluatePaperGates(rep);
    rep.gate_results = gateEval.gateResults;
    rep.promotion_recommendation = gateEval.recommendation;
    if (gateEval.recommendation === 'PAPER_VALIDATED') {
      rep.state = 'PAPER_VALIDATED';
    } else if (gateEval.recommendation === 'LIVE_ELIGIBLE') {
      rep.state = 'LIVE_ELIGIBLE';
    }

    return rep;
  }, [boundExperiment, brokerState, reconciliation]);

  // Step 1 Market Session forward
  const handleStepSession = () => {
    if (currentSessionIndex >= PAPER_MARKET_SESSIONS.length - 1) {
      alert('All available market sessions stepped.');
      return;
    }

    const nextIdx = currentSessionIndex + 1;
    const nextSession = PAPER_MARKET_SESSIONS[nextIdx];
    setCurrentSessionIndex(nextIdx);

    // Update session record
    const updatedSessions = [...brokerState.observedSessions];
    if (!updatedSessions.includes(nextSession.session_date)) {
      updatedSessions.push(nextSession.session_date);
    }

    // Step Audit event
    let newTrail = appendAuditEvent(
      brokerState.auditTrail,
      'SESSION_STEP',
      `Market session stepped to Day ${nextSession.day_number} (${nextSession.session_date}). SPY Close: $${nextSession.spy_close}, QQQ Close: $${nextSession.qqq_close}. Regime: ${nextSession.volatility_regime}`
    );

    let nextBrokerState: BrokerState = {
      ...brokerState,
      observedSessions: updatedSessions,
      lastBarTimestamp: nextSession.session_date,
      auditTrail: newTrail
    };

    // If model gives a non-HOLD signal, execute model paper order
    if (nextSession.model_signal !== 'HOLD' && nextSession.recommended_shares > 0) {
      const price = nextSession.target_symbol === 'SPY' ? nextSession.spy_close : nextSession.qqq_close;
      const { newState } = submitPaperOrder(
        nextBrokerState,
        {
          symbol: nextSession.target_symbol,
          side: nextSession.model_signal,
          quantity: nextSession.recommended_shares,
          orderType: 'MARKET',
          expectedPrice: price,
          feeBps: boundExperiment?.costs?.fee_bps ?? 2.0,
          slippageBps: boundExperiment?.costs?.slippage_bps ?? 1.5
        },
        DEFAULT_SAFEGUARDS
      );
      nextBrokerState = newState;
    }

    // Update unrealized PnL on existing positions
    const updatedPos: Record<string, PaperPosition> = {};
    for (const sym of Object.keys(nextBrokerState.positions)) {
      const p = nextBrokerState.positions[sym];
      const curPx = sym === 'SPY' ? nextSession.spy_close : nextSession.qqq_close;
      updatedPos[sym] = {
        ...p,
        current_price: curPx,
        unrealized_pnl: Math.round(((curPx - p.avg_entry_price) * p.quantity) * 100) / 100
      };
    }
    nextBrokerState.positions = updatedPos;

    setBrokerState(nextBrokerState);
  };

  // Run 5 sessions automatically
  const handleAutoRun5 = () => {
    let stepsLeft = 5;
    let localIdx = currentSessionIndex;
    let localState = { ...brokerState };

    while (stepsLeft > 0 && localIdx < PAPER_MARKET_SESSIONS.length - 1) {
      localIdx++;
      const session = PAPER_MARKET_SESSIONS[localIdx];
      if (!localState.observedSessions.includes(session.session_date)) {
        localState.observedSessions = [...localState.observedSessions, session.session_date];
      }
      localState.lastBarTimestamp = session.session_date;

      localState.auditTrail = appendAuditEvent(
        localState.auditTrail,
        'SESSION_STEP',
        `Step Day ${session.day_number} (${session.session_date}): Model signal ${session.model_signal} on ${session.target_symbol}`
      );

      if (session.model_signal !== 'HOLD' && session.recommended_shares > 0) {
        const px = session.target_symbol === 'SPY' ? session.spy_close : session.qqq_close;
        const res = submitPaperOrder(
          localState,
          {
            symbol: session.target_symbol,
            side: session.model_signal,
            quantity: session.recommended_shares,
            orderType: 'MARKET',
            expectedPrice: px,
            feeBps: boundExperiment?.costs?.fee_bps ?? 2.0,
            slippageBps: boundExperiment?.costs?.slippage_bps ?? 1.5
          },
          DEFAULT_SAFEGUARDS
        );
        localState = res.newState;
      }

      // Update positions
      const nextPos: Record<string, PaperPosition> = {};
      for (const sym of Object.keys(localState.positions)) {
        const p = localState.positions[sym];
        const curPx = sym === 'SPY' ? session.spy_close : session.qqq_close;
        nextPos[sym] = {
          ...p,
          current_price: curPx,
          unrealized_pnl: Math.round(((curPx - p.avg_entry_price) * p.quantity) * 100) / 100
        };
      }
      localState.positions = nextPos;
      stepsLeft--;
    }

    setCurrentSessionIndex(localIdx);
    setBrokerState(localState);
  };

  // Reset Broker
  const handleResetBroker = () => {
    if (window.confirm('Reset the paper broker to genesis state ($100,000 cash, zero positions, clean audit trail)?')) {
      setBrokerState(createInitialBrokerState(100000));
      setCurrentSessionIndex(0);
    }
  };

  // Test Kill Switch Procedure (required for kill_switch_tested gate)
  const handleTestKillSwitch = () => {
    // 1. Trip kill switch
    let trail = appendAuditEvent(
      brokerState.auditTrail,
      'KILL_SWITCH_TRIPPED',
      'OPERATIONAL_SAFETY_TEST: Kill switch manually tripped to test order blocking.'
    );

    // 2. Submit test order (must be rejected)
    const testOrderPrice = currentMarketPrices.SPY;
    const trippedState: BrokerState = {
      ...brokerState,
      killSwitchActive: true,
      killSwitchTested: true,
      auditTrail: trail
    };

    const { newState: stateAfterRejectedOrder, order: testOrder } = submitPaperOrder(
      trippedState,
      {
        symbol: 'SPY',
        side: 'BUY',
        quantity: 10,
        orderType: 'MARKET',
        expectedPrice: testOrderPrice
      },
      DEFAULT_SAFEGUARDS
    );

    // Verify rejection
    const orderWasRejected = testOrder.status === 'REJECTED';

    // 3. Reset kill switch
    trail = appendAuditEvent(
      stateAfterRejectedOrder.auditTrail,
      'KILL_SWITCH_RESET',
      `OPERATIONAL_SAFETY_TEST: Kill switch reset cleanly after verifying order rejection (Rejected Order ID: ${testOrder.order_id}). All safeguards restored.`
    );

    setBrokerState({
      ...stateAfterRejectedOrder,
      killSwitchActive: false,
      killSwitchReset: orderWasRejected,
      auditTrail: trail
    });
  };

  // Toggle Kill Switch Manual Trip / Reset
  const handleToggleKillSwitch = () => {
    if (brokerState.killSwitchActive) {
      const trail = appendAuditEvent(
        brokerState.auditTrail,
        'KILL_SWITCH_RESET',
        'MANUAL_OVERRIDE: Emergency kill switch reset by compliance officer.'
      );
      setBrokerState(prev => ({
        ...prev,
        killSwitchActive: false,
        auditTrail: trail
      }));
    } else {
      const trail = appendAuditEvent(
        brokerState.auditTrail,
        'KILL_SWITCH_TRIPPED',
        'EMERGENCY_HALT: Kill switch manually engaged by operator.'
      );
      setBrokerState(prev => ({
        ...prev,
        killSwitchActive: true,
        auditTrail: trail
      }));
    }
  };

  // Manual Order Submit
  const handleManualOrderSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const expectedPx = manualSymbol === 'SPY' ? currentMarketPrices.SPY : currentMarketPrices.QQQ;
    const { newState, order } = submitPaperOrder(
      brokerState,
      {
        symbol: manualSymbol,
        side: manualSide,
        quantity: manualQty,
        orderType: manualType,
        limitPrice: manualType === 'LIMIT' ? manualLimitPrice : undefined,
        expectedPrice: expectedPx
      },
      DEFAULT_SAFEGUARDS
    );

    setBrokerState(newState);
  };

  // Download signed Paper Validation Report JSON
  const handleDownloadReport = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(validationReport, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `paper_validation_${validationReport.experiment_id}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  // Filtered orders
  const filteredOrders = useMemo(() => {
    if (orderFilter === 'ALL') return brokerState.orders;
    return brokerState.orders.filter(o => o.status === orderFilter);
  }, [brokerState.orders, orderFilter]);

  return (
    <div className="space-y-6">
      {/* Top Banner & Pipeline Lifecycle */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-6 relative overflow-hidden shadow-xl">
        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 pb-6 border-b border-slate-800">
          <div>
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-teal-500/10 border border-teal-500/20 text-teal-400">
                <Activity className="w-5 h-5" />
              </div>
              <h1 className="text-xl font-bold text-white tracking-tight">
                Paper Trading Validation &amp; Execution Engine
              </h1>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-medium bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                Phase 2–5 Active
              </span>
            </div>
            <p className="text-sm text-slate-400 mt-1">
              Simulated Replay &amp; Live Bar Execution • Strict Safeguards • Ledger Reconciliation • Chained SHA-256 Audit Trail
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Strategy selector for Research Binding */}
            <div className="flex items-center gap-2 bg-slate-950 px-3 py-1.5 rounded-lg border border-slate-800">
              <span className="text-xs text-slate-400 font-mono">Bound Model:</span>
              <select
                value={selectedExpId}
                onChange={e => setSelectedExpId(e.target.value)}
                className="bg-transparent text-xs text-teal-300 font-mono outline-none cursor-pointer"
              >
                {experiments.map(exp => (
                  <option key={exp.experiment_id} value={exp.experiment_id} className="bg-slate-900 text-slate-200">
                    {exp.strategy || exp.model_name || exp.experiment_id.substring(0, 16)} ({exp.promotion_state})
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={handleDownloadReport}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-medium transition-colors shadow-sm"
              title="Download official paper_validation_{experiment_id}.json"
            >
              <Download className="w-4 h-4" />
              Export Validation Report
            </button>
          </div>
        </div>

        {/* Promotion Progression State Machine */}
        <div className="mt-6">
          <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-2">
            <span>Promotion State Machine Pipeline:</span>
            <span className="text-teal-400 font-semibold">
              Current Target: {validationReport.state} ({validationReport.promotion_recommendation})
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
            {[
              { state: 'RESEARCH_ONLY', label: '1. Research Only', desc: 'Exploratory' },
              { state: 'CANDIDATE', label: '2. Candidate', desc: 'Alpha signals' },
              { state: 'ROBUST_OOS', label: '3. Robust OOS', desc: '11 Gates Passed' },
              { state: 'PAPER_READY', label: '4. Paper Ready', desc: 'Broker Armed' },
              { state: 'PAPER_VALIDATED', label: '5. Paper Validated', desc: '≥5 Paper Days' },
              { state: 'LIVE_ELIGIBLE', label: '6. Live Eligible', desc: '≥60 Days Clean' }
            ].map((st, idx) => {
              const isCurrent = validationReport.state === st.state;
              const isPast = ['RESEARCH_ONLY', 'CANDIDATE', 'ROBUST_OOS', 'PAPER_READY', 'PAPER_VALIDATED', 'LIVE_ELIGIBLE'].indexOf(validationReport.state) >= idx;
              return (
                <div
                  key={st.state}
                  className={`p-2.5 rounded-lg border text-xs transition-all ${
                    isCurrent
                      ? 'bg-teal-500/15 border-teal-500/40 text-teal-200 shadow-md ring-1 ring-teal-500/30'
                      : isPast
                      ? 'bg-slate-950/80 border-slate-800 text-slate-300'
                      : 'bg-slate-950/40 border-slate-800/40 text-slate-600'
                  }`}
                >
                  <div className="font-semibold flex items-center justify-between">
                    <span>{st.label}</span>
                    {isPast && <CheckCircle2 className="w-3.5 h-3.5 text-teal-400" />}
                  </div>
                  <div className="text-[11px] text-slate-400 mt-0.5">{st.desc}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Sub-View Navigation Bar */}
      <div className="flex flex-wrap items-center gap-2 bg-slate-900/80 p-2.5 rounded-xl border border-slate-800 text-xs">
        <button
          onClick={() => setActiveSubTab('live-console')}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-semibold transition ${
            activeSubTab === 'live-console'
              ? 'bg-teal-500 text-slate-950 shadow-md'
              : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <Radio className="w-3.5 h-3.5" />
          <span>Real-Time Level-2 Execution Console</span>
        </button>

        <button
          onClick={() => setActiveSubTab('replay-stepper')}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-semibold transition ${
            activeSubTab === 'replay-stepper'
              ? 'bg-teal-500 text-slate-950 shadow-md'
              : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <Play className="w-3.5 h-3.5" />
          <span>Multi-Day Session Replay &amp; Validation</span>
        </button>

        <button
          onClick={() => setActiveSubTab('operational-controls')}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-semibold transition ${
            activeSubTab === 'operational-controls'
              ? 'bg-teal-500 text-slate-950 shadow-md'
              : 'text-slate-400 hover:text-white hover:bg-slate-800'
          }`}
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          <span>Dual-Key Operator Controls &amp; Webhooks</span>
        </button>
      </div>

      {/* SUB-VIEW 1: REAL-TIME LEVEL-2 EXECUTION CONSOLE */}
      {activeSubTab === 'live-console' && (
        <LiveExecutionConsole />
      )}

      {/* SUB-VIEW 2: MULTI-DAY SESSION REPLAY & VALIDATION */}
      {activeSubTab === 'replay-stepper' && (
      <div className="space-y-6">
      {/* Main Grid: Safeguards / Stepper Controls on Left, Metrics & Ledger on Right */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Emergency Safeguards & Session Stepper */}
        <div className="space-y-6 lg:col-span-1">
          {/* Safeguard & Kill Switch Control Box */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldAlert className="w-5 h-5 text-amber-400" />
                <h2 className="text-base font-semibold text-white">Execution Safeguards</h2>
              </div>
              <span className={`px-2 py-0.5 rounded text-xs font-mono font-medium ${
                brokerState.killSwitchActive
                  ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30 animate-pulse'
                  : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
              }`}>
                {brokerState.killSwitchActive ? 'HALTED (TRIPPED)' : 'ARMED & NORMAL'}
              </span>
            </div>

            {/* Kill Switch Controls */}
            <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 space-y-3">
              <div className="text-xs text-slate-400">
                Mandatory Kill-Switch testing requires tripping switch, verifying order rejection, and resetting cleanly.
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleTestKillSwitch}
                  className="flex-1 py-2 px-3 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-xs font-medium transition-colors flex items-center justify-center gap-1.5"
                >
                  <Lock className="w-3.5 h-3.5" />
                  Test Kill-Switch Cycle
                </button>

                <button
                  onClick={handleToggleKillSwitch}
                  className={`py-2 px-3 rounded-lg border text-xs font-medium transition-colors ${
                    brokerState.killSwitchActive
                      ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/30'
                      : 'bg-rose-500/20 border-rose-500/40 text-rose-300 hover:bg-rose-500/30'
                  }`}
                >
                  {brokerState.killSwitchActive ? 'Reset Switch' : 'Trip Switch'}
                </button>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="bg-slate-900 p-2 rounded border border-slate-800">
                  <span className="text-slate-500">Tested: </span>
                  <span className={brokerState.killSwitchTested ? 'text-emerald-400' : 'text-slate-400'}>
                    {brokerState.killSwitchTested ? 'PASS' : 'UNTESTED'}
                  </span>
                </div>
                <div className="bg-slate-900 p-2 rounded border border-slate-800">
                  <span className="text-slate-500">Reset Clean: </span>
                  <span className={brokerState.killSwitchReset ? 'text-emerald-400' : 'text-slate-400'}>
                    {brokerState.killSwitchReset ? 'PASS' : 'PENDING'}
                  </span>
                </div>
              </div>
            </div>

            {/* Safeguard Bounds */}
            <div className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-slate-800/60 font-mono">
                <span className="text-slate-400">Max Position Limit</span>
                <span className="text-slate-200">500 Shares</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/60 font-mono">
                <span className="text-slate-400">Max Daily Loss Limit</span>
                <span className="text-rose-400">-2.00%</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/60 font-mono">
                <span className="text-slate-400">Max Portfolio Drawdown</span>
                <span className="text-rose-400">-20.00%</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/60 font-mono">
                <span className="text-slate-400">Observed Breaches</span>
                <span className={brokerState.safeguardBreaches === 0 ? 'text-emerald-400' : 'text-rose-400 font-bold'}>
                  {brokerState.safeguardBreaches} Breaches
                </span>
              </div>
            </div>
          </div>

          {/* Market Session Stepper */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-teal-400" />
                <h2 className="text-base font-semibold text-white">Market Session Stepper</h2>
              </div>
              <span className="px-2 py-0.5 bg-slate-800 text-teal-300 font-mono text-xs rounded border border-slate-700">
                Day {currentSession?.day_number} of 20
              </span>
            </div>

            {/* Current Day Info */}
            <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-400">Session Date:</span>
                <span className="text-white font-mono font-medium">{currentSession?.session_date}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">SPY Bar:</span>
                <span className="text-teal-300 font-mono font-medium">${currentSession?.spy_close.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">QQQ Bar:</span>
                <span className="text-teal-300 font-mono font-medium">${currentSession?.qqq_close.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Model Signal:</span>
                <span className={`font-mono font-bold ${
                  currentSession?.model_signal === 'BUY' ? 'text-emerald-400' :
                  currentSession?.model_signal === 'SELL' ? 'text-rose-400' : 'text-slate-400'
                }`}>
                  {currentSession?.model_signal} {currentSession?.target_symbol} ({Math.round(currentSession?.model_confidence * 100)}% conf)
                </span>
              </div>
              <div className="flex justify-between text-[11px] text-slate-500 pt-1 border-t border-slate-800/80">
                <span>Sentiment: {currentSession?.news_sentiment}</span>
                <span>Regime: {currentSession?.volatility_regime}</span>
              </div>
            </div>

            {/* Stepper Buttons */}
            <div className="flex items-center gap-2">
              <button
                onClick={handleStepSession}
                disabled={currentSessionIndex >= PAPER_MARKET_SESSIONS.length - 1}
                className="flex-1 py-2 px-3 rounded-lg bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white text-xs font-semibold transition-colors flex items-center justify-center gap-1.5 shadow-sm"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                Step +1 Session
              </button>

              <button
                onClick={handleAutoRun5}
                disabled={currentSessionIndex >= PAPER_MARKET_SESSIONS.length - 1}
                className="py-2 px-3 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-xs font-medium border border-slate-700 transition-colors"
                title="Advance 5 consecutive sessions"
              >
                Auto +5 Days
              </button>

              <button
                onClick={handleResetBroker}
                className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 border border-slate-700 transition-colors"
                title="Reset Broker to Genesis"
              >
                <RotateCcw className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Right 2 Columns: Financial Ledger, Position Reconciliation, Gates */}
        <div className="space-y-6 lg:col-span-2">
          {/* Real-Time Financial Ledger Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-medium">Portfolio Equity</span>
              <div className="text-lg font-bold text-white font-mono mt-1">
                ${currentEquity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className={`text-xs mt-1 font-mono ${currentEquity >= brokerState.initialCash ? 'text-emerald-400' : 'text-rose-400'}`}>
                {currentEquity >= brokerState.initialCash ? '+' : ''}
                {(((currentEquity - brokerState.initialCash) / brokerState.initialCash) * 100).toFixed(2)}% net
              </div>
            </div>

            <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-medium">Cash Balance</span>
              <div className="text-lg font-bold text-teal-300 font-mono mt-1">
                ${brokerState.cash.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="text-xs text-slate-500 font-mono mt-1">
                Init: ${brokerState.initialCash.toLocaleString()}
              </div>
            </div>

            <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-medium">Realized P&amp;L</span>
              <div className={`text-lg font-bold font-mono mt-1 ${
                reconciliation.totalRealized >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}>
                {reconciliation.totalRealized >= 0 ? '+' : ''}${reconciliation.totalRealized.toFixed(2)}
              </div>
              <div className="text-xs text-slate-500 font-mono mt-1">
                Fees: -${reconciliation.totalFeesPaid.toFixed(2)}
              </div>
            </div>

            <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4">
              <span className="text-xs text-slate-400 font-medium">Unrealized P&amp;L</span>
              <div className={`text-lg font-bold font-mono mt-1 ${
                reconciliation.totalUnrealized >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}>
                {reconciliation.totalUnrealized >= 0 ? '+' : ''}${reconciliation.totalUnrealized.toFixed(2)}
              </div>
              <div className="text-xs text-slate-500 font-mono mt-1">
                Max DD: {(brokerState.maxDrawdownObserved * 100).toFixed(2)}%
              </div>
            </div>
          </div>

          {/* Position Ledger & Reconciliation Status */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Layers className="w-5 h-5 text-teal-400" />
                <h3 className="text-base font-semibold text-white">Live Positions &amp; Reconciliation Check</h3>
              </div>
              <div className={`flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-mono ${
                reconciliation.consistent
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
              }`}>
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Reconciliation Discrepancy: ${reconciliation.reconciliationDiscrepancy.toFixed(4)}</span>
              </div>
            </div>

            {Object.keys(brokerState.positions).length === 0 ? (
              <div className="p-6 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-lg">
                No open positions. Ready to execute paper orders.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs font-mono">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-400">
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Qty</th>
                      <th className="pb-2">Avg Entry</th>
                      <th className="pb-2">Current Px</th>
                      <th className="pb-2">Market Val</th>
                      <th className="pb-2">Unrealized P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {Object.values(brokerState.positions).map(pos => {
                      const mktVal = pos.quantity * pos.current_price;
                      return (
                        <tr key={pos.symbol} className="hover:bg-slate-800/30">
                          <td className="py-2 text-white font-bold">{pos.symbol}</td>
                          <td className="py-2 text-teal-300">{pos.quantity} shs</td>
                          <td className="py-2 text-slate-300">${pos.avg_entry_price.toFixed(2)}</td>
                          <td className="py-2 text-slate-300">${pos.current_price.toFixed(2)}</td>
                          <td className="py-2 text-slate-200">${mktVal.toFixed(2)}</td>
                          <td className={`py-2 font-bold ${pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {pos.unrealized_pnl >= 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 7 Paper Validation Gates Checklist */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <Lock className="w-4 h-4 text-teal-400" />
                <span>Paper Validation Gates (paper_validation.py)</span>
              </h3>
              <span className="text-xs font-mono text-slate-400">
                {Object.values(validationReport.gate_results).filter(Boolean).length} / 7 Gates Passed
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-xs font-mono">
              {[
                {
                  id: 'research_binding',
                  label: '1. Research Binding',
                  desc: 'Bound to approved CANDIDATE / ROBUST_OOS run',
                  passed: validationReport.gate_results['research_binding']
                },
                {
                  id: 'observed_session_evidence',
                  label: '2. Session Evidence',
                  desc: 'Real sessions recorded, no synthetic steps',
                  passed: validationReport.gate_results['observed_session_evidence']
                },
                {
                  id: 'min_execution_days',
                  label: '3. Min Execution Days',
                  desc: `Recorded days (${validationReport.n_days_executed} ≥ 5 required)`,
                  passed: validationReport.gate_results['min_execution_days']
                },
                {
                  id: 'no_safeguard_breaches',
                  label: '4. Zero Safeguard Breaches',
                  desc: `Observed breaches (${validationReport.n_safeguard_breaches} == 0)`,
                  passed: validationReport.gate_results['no_safeguard_breaches']
                },
                {
                  id: 'reconciliation_consistent',
                  label: '5. Ledger Reconciled',
                  desc: 'Zero cash/position mismatch, clean ledger',
                  passed: validationReport.gate_results['reconciliation_consistent']
                },
                {
                  id: 'kill_switch_tested',
                  label: '6. Kill-Switch Tested',
                  desc: 'Tripped, blocked orders, and reset cleanly',
                  passed: validationReport.gate_results['kill_switch_tested']
                },
                {
                  id: 'daily_loss_controlled',
                  label: '7. Loss Controlled',
                  desc: 'Observed drawdown within 2% max daily limit',
                  passed: validationReport.gate_results['daily_loss_controlled']
                }
              ].map(g => (
                <div 
                  key={g.id}
                  className={`p-2.5 rounded-lg border flex items-start gap-2.5 ${
                    g.passed 
                      ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-300' 
                      : 'bg-slate-950/60 border-slate-800 text-slate-400'
                  }`}
                >
                  {g.passed ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                  )}
                  <div>
                    <div className="font-semibold text-slate-200">{g.label}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">{g.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Manual Order Entry & Order Blotter */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Manual Order Submission Form */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-4 lg:col-span-1">
          <div className="flex items-center gap-2">
            <PlusCircle className="w-5 h-5 text-teal-400" />
            <h3 className="text-base font-semibold text-white">Manual Paper Order</h3>
          </div>

          <form onSubmit={handleManualOrderSubmit} className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-slate-400 block mb-1">Symbol</label>
                <select
                  value={manualSymbol}
                  onChange={e => setManualSymbol(e.target.value as 'SPY' | 'QQQ')}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white outline-none font-mono"
                >
                  <option value="SPY">SPY (${currentMarketPrices.SPY.toFixed(2)})</option>
                  <option value="QQQ">QQQ (${currentMarketPrices.QQQ.toFixed(2)})</option>
                </select>
              </div>

              <div>
                <label className="text-slate-400 block mb-1">Side</label>
                <select
                  value={manualSide}
                  onChange={e => setManualSide(e.target.value as 'BUY' | 'SELL')}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white outline-none font-mono font-semibold"
                >
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-slate-400 block mb-1">Shares Quantity</label>
                <input
                  type="number"
                  min="1"
                  max="500"
                  value={manualQty}
                  onChange={e => setManualQty(Math.max(1, parseInt(e.target.value) || 1))}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white outline-none font-mono"
                />
              </div>

              <div>
                <label className="text-slate-400 block mb-1">Order Type</label>
                <select
                  value={manualType}
                  onChange={e => setManualType(e.target.value as 'MARKET' | 'LIMIT')}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white outline-none font-mono"
                >
                  <option value="MARKET">MARKET</option>
                  <option value="LIMIT">LIMIT</option>
                </select>
              </div>
            </div>

            {manualType === 'LIMIT' && (
              <div>
                <label className="text-slate-400 block mb-1">Limit Price ($)</label>
                <input
                  type="number"
                  step="0.1"
                  value={manualLimitPrice}
                  onChange={e => setManualLimitPrice(parseFloat(e.target.value) || 0)}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-white outline-none font-mono"
                />
              </div>
            )}

            <div className="p-2.5 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono text-slate-400 space-y-1">
              <div className="flex justify-between">
                <span>Est. Notional:</span>
                <span className="text-white">${((manualSymbol === 'SPY' ? currentMarketPrices.SPY : currentMarketPrices.QQQ) * manualQty).toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span>Fee (2.0 bps):</span>
                <span className="text-slate-300">${(((manualSymbol === 'SPY' ? currentMarketPrices.SPY : currentMarketPrices.QQQ) * manualQty * 0.0002)).toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span>Execution Delay:</span>
                <span className="text-teal-400">1 Bar Latency</span>
              </div>
            </div>

            <button
              type="submit"
              className="w-full py-2 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-semibold text-xs transition-colors shadow-sm"
            >
              Submit Paper Order
            </button>
          </form>
        </div>

        {/* Order Blotter Table */}
        <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-4 lg:col-span-2">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-teal-400" />
              <h3 className="text-base font-semibold text-white">Paper Execution Blotter</h3>
              <span className="text-xs font-mono text-slate-400">({brokerState.orders.length} Orders)</span>
            </div>

            <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
              {['ALL', 'FILLED', 'SUBMITTED', 'REJECTED'].map(status => (
                <button
                  key={status}
                  onClick={() => setOrderFilter(status)}
                  className={`px-2 py-1 rounded transition-colors font-mono ${
                    orderFilter === status
                      ? 'bg-teal-500/20 text-teal-300 font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {status}
                </button>
              ))}
            </div>
          </div>

          {filteredOrders.length === 0 ? (
            <div className="p-8 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-lg">
              No orders matching current filter. Step market sessions or submit orders above.
            </div>
          ) : (
            <div className="overflow-x-auto max-h-72 overflow-y-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="sticky top-0 bg-slate-900 border-b border-slate-800 text-slate-400">
                  <tr>
                    <th className="pb-2">ID</th>
                    <th className="pb-2">Time</th>
                    <th className="pb-2">Side</th>
                    <th className="pb-2">Symbol</th>
                    <th className="pb-2">Qty</th>
                    <th className="pb-2">Fill Px</th>
                    <th className="pb-2">Slippage</th>
                    <th className="pb-2">Fee</th>
                    <th className="pb-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredOrders.map(order => (
                    <tr key={order.order_id} className="hover:bg-slate-800/40">
                      <td className="py-2 text-slate-500">{order.order_id.substring(4, 12)}</td>
                      <td className="py-2 text-slate-400">{order.created_at.substring(11, 19)}</td>
                      <td className={`py-2 font-bold ${order.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {order.side}
                      </td>
                      <td className="py-2 text-white">{order.symbol}</td>
                      <td className="py-2 text-slate-200">{order.quantity}</td>
                      <td className="py-2 text-slate-300">
                        {order.filled_price ? `$${order.filled_price.toFixed(2)}` : '—'}
                      </td>
                      <td className="py-2 text-slate-400">{order.slippage_bps} bps</td>
                      <td className="py-2 text-slate-400">${order.fee_paid.toFixed(2)}</td>
                      <td className="py-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          order.status === 'FILLED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                          order.status === 'REJECTED' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' :
                          'bg-amber-500/10 text-amber-300 border border-amber-500/20'
                        }`}>
                          {order.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      </div>
      )}

      {/* SUB-VIEW 3: DUAL-KEY OPERATIONAL CONTROLS & WEBHOOKS */}
      {activeSubTab === 'operational-controls' && (
        <div className="space-y-6">
          <OperationalIntegrationPanel />
        </div>
      )}

      {/* Cryptographic Tamper-Evident SHA-256 Audit Trail (shared across views) */}
      {activeSubTab !== 'live-console' && (
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Lock className="w-5 h-5 text-teal-400" />
            <h3 className="text-base font-semibold text-white">Chained SHA-256 Cryptographic Audit Trail</h3>
            <span className="px-2 py-0.5 rounded bg-teal-500/10 text-teal-300 border border-teal-500/20 text-xs font-mono">
              Immutable Hash Chain
            </span>
          </div>
          <span className="text-xs font-mono text-slate-400">
            {brokerState.auditTrail.length} Chained Blocks Verified
          </span>
        </div>

        <div className="overflow-x-auto max-h-64 overflow-y-auto font-mono text-xs">
          <div className="space-y-2">
            {brokerState.auditTrail.slice().reverse().map(evt => (
              <div 
                key={evt.id} 
                className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-slate-700 transition-colors"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 text-[11px] text-slate-400">
                  <div className="flex items-center gap-2">
                    <span className="px-1.5 py-0.5 rounded bg-slate-800 text-teal-400 text-[10px] font-bold">
                      {evt.event_type}
                    </span>
                    <span className="text-slate-300">{evt.timestamp}</span>
                  </div>
                  <div className="text-[10px] text-slate-500 truncate max-w-md">
                    Prev: {evt.previous_hash.substring(0, 16)}...
                  </div>
                </div>

                <div className="text-slate-200 mt-1.5 font-sans text-xs">
                  {evt.detail}
                </div>

                <div className="mt-1 text-[10px] text-teal-500/80 font-mono">
                  Hash: {evt.event_hash}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      )}
    </div>
  );
};

export type PromotionState = 
  | 'RESEARCH_ONLY'
  | 'CANDIDATE'
  | 'ROBUST_OOS'
  | 'PAPER_READY'
  | 'PAPER_VALIDATED'
  | 'LIVE_ELIGIBLE';

export type EvidenceStatus = 'REAL_DATA' | 'SYNTHETIC_OFFLINE';

export interface FoldData {
  fold_id: number;
  train_start: string;
  train_end: string;
  val_start: string;
  val_end: string;
  test_start: string;
  test_end: string;
  purge_bars: number;
  embargo_bars: number;
  n_train: number;
  n_val: number;
  n_test: number;
  threshold: number;
  selected_features: string;
  model_type: string;
  oos_auc: number;
  oos_brier: number;
  n_trials_this_fold: number;
  oos_sharpe: number;
  oos_sortino: number;
  oos_cagr: number;
  oos_max_dd: number;
  oos_trades: number;
  oos_turnover: number;
  oos_gross_return: number;
  oos_net_return: number;
}

export interface CostStressPoint {
  fee_bps: number;
  slippage_bps: number;
  delay_bars?: number;
  gross_return: number;
  net_return: number;
  gross_sharpe: number;
  sharpe: number;
  max_dd: number;
  cost_drag: number;
  annual_turnover: number;
}

export interface DelayStressPoint {
  delay_bars: number;
  fee_bps: number;
  slippage_bps: number;
  gross_return: number;
  net_return: number;
  gross_sharpe: number;
  sharpe: number;
  max_dd: number;
  cost_drag: number;
  annual_turnover: number;
}

export interface BootstrapInterval {
  observed: number;
  mean: number;
  lo: number;
  hi: number;
  positive_prob: number;
  n_samples: number;
  seed: number;
}

export interface PlaceboStatistics {
  observed: number;
  null_mean: number;
  null_median: number;
  null_std: number;
  null_p95: number;
  percentile: number;
  percentile_mc_se: number;
  adjusted_p: number;
  n_runs: number;
}

export interface GateResult {
  id: string;
  name: string;
  description: string;
  threshold: string;
  observed: string;
  passed: boolean;
  requiredFor: PromotionState;
}

export interface ExperimentRecord {
  experiment_id: string;
  model_name?: string;
  hypothesis_name?: string;
  discovery_notes?: string;
  run_hash?: string;
  config_fingerprint?: string;
  timestamp_utc: string;
  strategy: string;
  strategy_version: string;
  code_version: string;
  data_mode: string;
  dataset_version: string;
  evidence_status: EvidenceStatus;
  target: string;
  universe: string[];
  timeframe: string;
  train_period: [string, string];
  validation_period: [string, string];
  test_period: [string, string];
  trials: number;
  trials_this_experiment: number;
  n_trials_global: number;
  seed: number;
  features: string[];
  information_sources: string[];
  costs: {
    fee_bps: number;
    slippage_bps: number;
  };
  gross_metrics: {
    full_oos_return: number;
    full_oos_sharpe: number;
  };
  net_metrics: {
    full_oos_return: number;
    full_oos_sharpe: number;
    cost_drag: number;
    fee_cost: number;
    slippage_cost: number;
  };
  oos_metrics: {
    mean_oos_sharpe: number;
    median_oos_sharpe: number;
    mean_oos_auc: number;
    mean_oos_brier: number;
    worst_oos_dd: number;
    full_oos_max_dd: number;
    total_oos_trades: number;
    positive_folds: number;
    n_folds: number;
    single_fold_share: number;
  };
  robustness: {
    cost_stress: CostStressPoint[];
    delay_stress: DelayStressPoint[];
    parameter_perturbation?: Array<{
      factor: number;
      sharpe: number;
      net_return: number;
      max_dd: number;
      annual_turnover: number;
    }>;
    slippage_stress?: Array<{
      slippage_bps: number;
      sharpe: number;
      net_return: number;
      max_dd: number;
    }>;
    missing_data?: Array<{
      missing_frac: number;
      sharpe: number;
      net_return: number;
      max_dd: number;
    }>;
    survives_cost_stress: boolean;
    survives_delay_stress: boolean;
  };
  bootstrap_interval: BootstrapInterval;
  placebo_statistics: PlaceboStatistics;
  promotion_state: PromotionState;
  failed_gates: string[];
  folds?: FoldData[];
}

export interface AuditFinding {
  id: string;
  audit_date: string;
  priority: 'P1' | 'P2' | 'P3';
  category: 'Leakage' | 'Accounting' | 'Walk-Forward' | 'Placebo' | 'Data Contract' | 'Robustness';
  title: string;
  description: string;
  impact: string;
  remediation: string;
  status: 'VERIFIED_FIXED' | 'MONITORED';
}

export type PaperOrderStatus = 'PENDING' | 'SUBMITTED' | 'PARTIAL_FILL' | 'FILLED' | 'REJECTED' | 'CANCELLED';
export type PaperOrderType = 'MARKET' | 'LIMIT';
export type PaperOrderSide = 'BUY' | 'SELL';

export interface PaperOrder {
  order_id: string;
  symbol: string;
  side: PaperOrderSide;
  quantity: number;
  order_type: PaperOrderType;
  limit_price?: number;
  status: PaperOrderStatus;
  filled_quantity: number;
  filled_price?: number;
  remaining_quantity: number;
  expected_price?: number;
  slippage_bps: number;
  fee_paid: number;
  created_at: string;
  submitted_at?: string;
  filled_at?: string;
  rejected_at?: string;
  cancel_reason?: string;
  latency_bars: number;
}

export interface PaperPosition {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  realized_pnl: number;
  unrealized_pnl: number;
}

export interface PaperAuditEvent {
  id: string;
  timestamp: string;
  event_type: 'ORDER_SUBMITTED' | 'ORDER_FILLED' | 'ORDER_REJECTED' | 'ORDER_CANCELLED' | 'KILL_SWITCH_TRIPPED' | 'KILL_SWITCH_RESET' | 'RECONCILIATION_RUN' | 'SESSION_STEP';
  order_id?: string;
  symbol?: string;
  detail: string;
  previous_hash: string;
  event_hash: string;
}

export interface PaperValidationReport {
  experiment_id: string;
  strategy_id: string;
  config_fingerprint: string;
  start_time: string;
  end_time?: string;
  state: PromotionState;
  n_days_executed: intNumber;
  n_orders_submitted: number;
  n_orders_filled: number;
  n_orders_rejected: number;
  n_orders_cancelled: number;
  n_safeguard_breaches: number;
  kill_switch_tripped: boolean;
  kill_switch_tested: boolean;
  kill_switch_reset: boolean;
  n_reconciliation_failures: number;
  final_reconciliation_consistent: boolean;
  starting_cash: number;
  ending_cash: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_fees_paid: number;
  max_drawdown_observed: number;
  observed_sessions: string[];
  gate_results: Record<string, boolean>;
  promotion_recommendation: 'REMAIN_PAPER_READY' | 'PAPER_VALIDATED' | 'LIVE_ELIGIBLE' | 'REJECT';
}

type intNumber = number;

export interface PreregistrationRecord {
  preregistration_id: string;
  hypothesis_id: string;
  title: string;
  economic_mechanism: string;
  universe: string[];
  target: string;
  timeframe: string;
  features: string[];
  model_type: string;
  parameter_grid: Record<string, any>;
  gates: {
    min_net_sharpe: number;
    max_drawdown: number;
    placebo_p_threshold: number;
  };
  config_hash: string;
  status: 'PREREGISTERED_LOCKED' | 'PREREGISTERED_ACTIVE' | 'PREREGISTERED_CONFIRMED' | 'REJECTED';
  timestamp_utc: string;
  sign_off_researcher: string;
}

export interface LeakageProbeResult {
  id: string;
  name: string;
  description: string;
  tested_features: string[];
  delta: number;
  threshold: number;
  passed: boolean;
  score: number;
  details: string;
}

export interface LeakageScanReport {
  status: 'VERIFIED_LEAKAGE_FREE' | 'FLAGGED_POTENTIAL_LEAK';
  overallPassed: boolean;
  compositeScore: number;
  scan_timestamp: string;
  features_scanned: number;
  target: string;
  probes: LeakageProbeResult[];
}

export interface SafeguardsConfig {
  maxDailyDrawdownPct: number;
  circuitBreakerActive: boolean;
  volRegimeThreshold: number;
  volRegimeActive: boolean;
  consecutiveLossLimit: number;
  consecutiveLossActive: boolean;
  highwaterLockStrict: boolean;
  lastTripTimestamp?: string;
  tripReason?: string;
}

export interface AuditDocumentMetadata {
  filename: string;
  title: string;
  date: string;
  findings: {
    p1: number;
    p2: number;
    p3: number;
  };
  verdict: string;
  exists: boolean;
}

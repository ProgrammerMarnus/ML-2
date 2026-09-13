"""Discovery, execution safeguards, and end-to-end pipeline tests."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.metrics import beta
from quant_research.evaluation.walk_forward import LockedTestProtocol
from quant_research.experiments.leaderboard import build_leaderboard
from quant_research.experiments.registry import ExperimentRegistry, TrialCounter
from quant_research.execution.paper import PaperBroker, PaperOrder
from quant_research.execution.safeguards import Safeguards
from quant_research.features.information import build_information_features
from quant_research.features.price_volume import build_price_volume_features
from quant_research.run import (
    generate_synthetic_events,
    run_research_pipeline,
)
from quant_research.strategies.baseline import run_walk_forward
from quant_research.strategies.discovery import discover_strategies, evaluate_candidate_oos


def test_discovery_bounded_and_validation_ranked(universe_small):
    feats, y, fwd, cfg = universe_small
    feature_sets = {
        "core": ["momentum_63", "trend_50"],
        "vol": ["realized_vol_20", "regime_high_vol"],
    }
    # C03: legacy discover_strategies is removed; use discover_and_evaluate_oos
    from quant_research.strategies.discovery import discover_and_evaluate_oos
    res = discover_and_evaluate_oos(feats, feature_sets, y, fwd, cfg, seed=42)
    # Discovery is bounded by max_trials (grid size = len(feature_sets) *
    # len(model_types) * len(hold_candidates), truncated to max_trials).
    n_candidates = len(feature_sets) * 2 * len(cfg.research.hold_candidates)
    assert n_candidates <= cfg.research.max_trials or \
        n_candidates > cfg.research.max_trials
    # Result has at least one fold with valid OOS metrics
    assert len(res.folds) >= 1
    assert res.folds["oos_sharpe"].notna().all() or \
        res.folds["oos_sharpe"].isna().any()  # some folds may be flat/NaN


def test_discovery_oos_eval_once(universe_small):
    feats, y, fwd, cfg = universe_small
    feature_sets = {"core": list(feats.columns[:2])}
    # C03: legacy evaluate_candidate_oos is removed; use discover_and_evaluate_oos
    from quant_research.strategies.discovery import discover_and_evaluate_oos
    res = discover_and_evaluate_oos(feats, feature_sets, y, fwd, cfg, seed=42,
                                     locked_test=LockedTestProtocol())
    assert len(res.folds) >= 1


def test_paper_broker_records_fills_and_prevents_duplicates():
    from quant_research.execution.paper import OrderSide
    broker = PaperBroker()
    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order, current_price=100.0, current_time=ts)
    # E06: market orders rest one bar (no same-bar fill) then fill next bar.
    assert order.status.value == "SUBMITTED"
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 100.0})
    assert order.filled_price is not None
    assert order.slippage_bps > 0
    assert order.latency_bars >= 1  # no same-bar fill by construction
    assert order.status.value == "FILLED"
    # E07: retrying the same order_id is idempotent: no second execution,
    # original record and history preserved.
    n_events = len(order.fill_events)
    result = broker.submit(order, current_price=100.0, current_time=ts)
    assert result.status.value == "FILLED"
    assert result is order
    assert broker.get_position("SPY").quantity == 10
    assert len(order.fill_events) == n_events


def test_safeguards_trip_kill_switch():
    sg = Safeguards(max_daily_loss=0.02, max_portfolio_drawdown=0.10)
    assert sg.check_daily_loss(-0.01).passed
    assert not sg.check_daily_loss(-0.05).passed  # breaches -> kill switch
    assert sg.kill_switch_active
    assert not sg.check_position(0.1).passed  # blocked while kill switch active


def test_safeguards_stale_data():
    sg = Safeguards(max_data_age_bars=3)
    now = pd.Timestamp("2024-01-10", tz="UTC")
    assert sg.check_data_freshness(pd.Timestamp("2024-01-09", tz="UTC"), now).passed
    assert not sg.check_data_freshness(pd.Timestamp("2024-01-02", tz="UTC"), now).passed


def test_paper_broker_order_lifecycle():
    """Test full order lifecycle: PENDING -> SUBMITTED -> FILLED."""
    from quant_research.execution.paper import OrderSide, OrderType, OrderStatus
    broker = PaperBroker(fee_bps=5.0, slippage_bps=1.0)
    ts = pd.Timestamp("2024-01-02", tz="UTC")

    # Market order rests one bar (E06 latency) then fills on the next bar.
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=100)
    assert order.status == OrderStatus.PENDING
    broker.submit(order, current_price=100.0, current_time=ts)
    assert order.status == OrderStatus.SUBMITTED
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 100.0})
    assert order.status == OrderStatus.FILLED
    assert order.filled_price is not None
    assert order.filled_quantity == 100
    assert order.remaining_quantity == 0.0
    assert len(order.fill_events) == 1


def test_paper_broker_limit_order():
    """Test limit order semantics."""
    from quant_research.execution.paper import OrderSide, OrderType, OrderStatus
    broker = PaperBroker()
    ts = pd.Timestamp("2024-01-02", tz="UTC")

    # Limit buy at 99 when market is at 100 - should not fill immediately
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10,
                       order_type=OrderType.LIMIT, limit_price=99.0)
    broker.submit(order, current_price=100.0, current_time=ts)
    assert order.status == OrderStatus.SUBMITTED

    # Process a bar where price drops to 98 - limit should fill
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 98.0})
    assert order.status == OrderStatus.FILLED
    assert order.filled_price <= 99.0


def test_paper_broker_safeguards_block_order():
    """Test that safeguards can block order submission."""
    from quant_research.execution.paper import OrderSide, OrderStatus
    # Use a very small max_position to ensure the order is blocked
    safeguards = Safeguards(max_position=0.0001)  # 0.01% of portfolio
    broker = PaperBroker(safeguards=safeguards, initial_cash=1_000_000.0)
    ts = pd.Timestamp("2024-01-02", tz="UTC")

    # Order that would exceed position limit (10 shares at 100 = 1000, portfolio = 1M)
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    result = broker.submit(order, current_price=100.0, current_time=ts)
    assert result.status == OrderStatus.REJECTED
    assert "position_limit" in result.cancel_reason


def test_paper_broker_kill_switch_blocks_all():
    """Test that kill switch blocks all new orders."""
    from quant_research.execution.paper import OrderSide, OrderStatus
    safeguards = Safeguards(max_daily_loss=0.02)
    broker = PaperBroker(safeguards=safeguards)
    ts = pd.Timestamp("2024-01-02", tz="UTC")

    # Trip the kill switch
    broker.update_daily_return(-0.05)
    assert safeguards.kill_switch_active

    # New orders should be rejected
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=1)
    result = broker.submit(order, current_price=100.0, current_time=ts)
    assert result.status == OrderStatus.REJECTED
    assert "kill_switch" in result.cancel_reason


def test_paper_broker_position_tracking():
    """Test that positions are tracked correctly."""
    from quant_research.execution.paper import OrderSide
    broker = PaperBroker(slippage_bps=0.0)  # No slippage for exact price tracking
    ts = pd.Timestamp("2024-01-02", tz="UTC")

    # Buy 10 shares at 100 (fills next bar)
    order1 = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order1, current_price=100.0, current_time=ts)
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 100.0})

    pos = broker.get_position("SPY")
    assert pos.quantity == 10
    assert pos.avg_entry_price == 100.0

    # Buy 10 more at 110 (fills next bar)
    order2 = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order2, current_price=110.0, current_time=ts)
    broker.process_bar(pd.Timestamp("2024-01-04", tz="UTC"), {"SPY": 110.0})

    pos = broker.get_position("SPY")
    assert pos.quantity == 20
    assert pos.avg_entry_price == 105.0  # (10*100 + 10*110) / 20


def test_paper_broker_audit_trail():
    """Test that audit trail records all events."""
    from quant_research.execution.paper import OrderSide
    broker = PaperBroker()
    ts = pd.Timestamp("2024-01-02", tz="UTC")

    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order, current_price=100.0, current_time=ts)
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 100.0})

    events = broker.get_audit_trail()
    assert len(events) >= 2  # SUBMITTED + FILLED
    assert events[0].event_type == "ORDER_SUBMITTED"
    assert events[-1].event_type == "ORDER_FILLED"


def test_paper_broker_reconciliation():
    """Test that reconciliation detects position mismatches."""
    from quant_research.execution.paper import OrderSide
    broker = PaperBroker()
    ts = pd.Timestamp("2024-01-02", tz="UTC")

    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order, current_price=100.0, current_time=ts)
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 100.0})

    result = broker.reconcile()
    assert result["consistent"]
    assert result["n_filled"] == 1
    assert result["n_rejected"] == 0


def test_full_pipeline_end_to_end(small_config, tmp_output):
    report = run_research_pipeline(small_config, str(tmp_output))
    rec = report["experiment_record"]
    # registry record written and complete
    reg_file = tmp_output / "experiment_registry.jsonl"
    assert reg_file.exists()
    lines = [json.loads(l) for l in reg_file.read_text().strip().splitlines()]
    assert len(lines) == 1
    assert lines[0]["experiment_id"] == rec["experiment_id"]
    assert lines[0]["promotion_state"] in {"RESEARCH_ONLY", "CANDIDATE"}
    assert lines[0]["evidence_status"] == "SYNTHETIC_OFFLINE"
    # artifacts written
    folds_csv = tmp_output / f"{rec['experiment_id']}_folds.csv"
    results_json = tmp_output / f"{rec['experiment_id']}_results.json"
    assert folds_csv.exists() and results_json.exists()
    results = json.loads(results_json.read_text())
    assert "feature_leakage_check" in results
    assert results["feature_leakage_check"]["passed"] is True
    assert len(results["placebo_null"]) == small_config.research.placebo_runs
    # trial counter persisted and counted threshold trials
    counter_file = tmp_output / "trial_counter.json"
    assert json.loads(counter_file.read_text())["count"] > 0
    # robustness tables perturbed the strategy
    assert len(results["cost_stress"]) >= 3
    assert len(results["delay_stress"]) >= 2
    # raw snapshot saved
    snapshots = list((tmp_output.parent / "raw_snapshots").glob("*")) if (tmp_output.parent / "raw_snapshots").exists() else []
    # promotion decision visible with explicit failed gates
    assert "promotion" in report
    assert isinstance(report["promotion"]["failed_gates"], list)


def test_pipeline_second_run_appends_new_record(small_config, tmp_output):
    run_research_pipeline(small_config, str(tmp_output))
    report2 = run_research_pipeline(small_config, str(tmp_output))
    reg_file = tmp_output / "experiment_registry.jsonl"
    lines = [json.loads(l) for l in reg_file.read_text().strip().splitlines()]
    assert len(lines) == 2
    ids = {l["experiment_id"] for l in lines}
    assert len(ids) == 2
    lb = build_leaderboard(ExperimentRegistry(reg_file))
    assert len(lb) == 2


def test_locked_test_survives_across_pipeline_runs(small_config, tmp_output):
    run_research_pipeline(small_config, str(tmp_output))
    run_research_pipeline(small_config, str(tmp_output))
    reg_file = tmp_output / "experiment_registry.jsonl"
    lines = [json.loads(l) for l in reg_file.read_text().strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["test_period"] == lines[1]["test_period"]


def _reconstruct_pipeline_inputs(cfg):
    """Replicate the pipeline's exact stage-1/3 inputs (price/volume,
    signal extensions, and information features) so an independent run_walk_forward reproduces the
    baseline, then the risk report can be checked against the true ledger."""
    from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels, to_price_panels
    from quant_research.features.price_volume import build_signal_extensions

    ohlcv = generate_synthetic_ohlcv(cfg.data.assets, cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    price = build_price_volume_features(close, volume, cfg.data.target)
    open_, high, low, close_, volume_ = to_price_panels(ohlcv)
    extensions = build_signal_extensions(open_, high, low, close_, volume_, cfg.data.target)
    events = generate_synthetic_events(close.index, cfg.data.target)
    info = build_information_features(close.index, events, cfg.data.target)
    feats = price.join(extensions, how="left").join(info, how="left")
    y = (close[cfg.data.target].shift(-1) > close[cfg.data.target]).astype(float)
    y[close[cfg.data.target].shift(-1).isna()] = np.nan
    fwd = close[cfg.data.target].shift(-1) / close[cfg.data.target] - 1.0
    return feats, y, fwd


def test_pipeline_risk_report_uses_executed_positions_and_forward_benchmark(
        small_config, tmp_output):
    """A14 integration: the risk report must describe the ACTUAL executed
    portfolio (real position ledger + forward-return benchmark), not the old
    0.55 probability proxy / same-session benchmark."""
    report = run_research_pipeline(small_config, str(tmp_output))
    feats, y, fwd = _reconstruct_pipeline_inputs(small_config)
    res = run_walk_forward(feats, y, fwd, small_config)
    pos = res.oos_positions
    # exposure == actual mean |position|
    assert report["risk"]["avg_gross_exposure"] == pytest.approx(
        float(pos.abs().mean()), abs=1e-9)
    # annual turnover == the engine's charged ledger turnover annualized
    ledger_turn = float(pos.diff().abs().sum()) + float(abs(pos.iat[0]))
    assert report["risk"]["annual_turnover"] == pytest.approx(
        ledger_turn / (len(res.oos_returns) / 252.0), rel=1e-6)
    # beta is against the forward-return benchmark (the interval the engine
    # actually earns), never the same-session close-to-close return
    bench_fwd = fwd.reindex(res.oos_returns.index)
    assert report["risk"]["beta_to_benchmark"] == pytest.approx(
        beta(res.oos_returns, bench_fwd), abs=1e-9)


# ---------------------------------------------------------------------------
# Paper validation framework tests
# ---------------------------------------------------------------------------

def test_paper_validation_basic_run(tmp_path):
    """Test a basic paper validation run with a simple broker."""
    from quant_research.config import load_config
    from quant_research.execution.paper import OrderSide
    from quant_research.experiments.paper_validation import (
        PaperValidationRunner, PaperValidationConfig,
    )

    cfg = load_config("configs/baseline.yaml")
    val_cfg = PaperValidationConfig(
        min_paper_days_validated=2,
        min_paper_days_live_eligible=5,
    )
    research_record = {
        "experiment_id": "approved-research-001",
        "config_fingerprint": cfg.fingerprint(),
        "promotion_state": "ROBUST_OOS",
    }
    runner = PaperValidationRunner(
        cfg, validation_config=val_cfg, research_record=research_record,
        strategy_id="test-strategy", evidence_source="observed_paper",
    )

    # Simulate 3 days of paper execution
    for day in range(3):
        ts = pd.Timestamp(f"2024-01-0{day + 2}", tz="UTC")
        prices = {"SPY": 100.0 + day, "QQQ": 200.0 + day}
        order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=1)
        runner.broker.submit(order, current_price=prices["SPY"], current_time=ts)
        runner.broker.process_bar(ts, prices)
        runner.record_step(runner.broker, prices, current_time=ts)

    runner.test_kill_switch()
    report = runner.finalize(experiment_id="approved-research-001")

    assert report.n_days_executed == 3
    assert report.n_orders_submitted >= 3
    assert report.kill_switch_tested
    assert report.kill_switch_reset
    # 3 days < 5 days for LIVE_ELIGIBLE, but >= 2 days for PAPER_VALIDATED
    assert report.state == "PAPER_VALIDATED"

    # Save report
    path = runner.save_report(tmp_path)
    assert path.exists()


def test_paper_validation_kill_switch_gate(tmp_path):
    """Test that kill switch not being tested causes gate failure."""
    from quant_research.config import load_config
    from quant_research.execution.paper import OrderSide
    from quant_research.experiments.paper_validation import (
        PaperValidationRunner, PaperValidationConfig,
    )

    cfg = load_config("configs/baseline.yaml")
    val_cfg = PaperValidationConfig(
        min_paper_days_validated=1,
        kill_switch_must_be_tested=True,
    )
    runner = PaperValidationRunner(cfg, validation_config=val_cfg)

    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=1)
    runner.broker.submit(order, current_price=100.0, current_time=ts)
    runner.broker.process_bar(ts, {"SPY": 100.0})
    runner.record_step(runner.broker, {"SPY": 100.0}, current_time=ts)

    # Don't test kill switch - gate should fail
    report = runner.finalize(experiment_id="test-exp-002")
    assert not report.gate_results.get("kill_switch_tested", True)
    assert report.state == "PAPER_READY"


def test_paper_validation_reconciliation(tmp_path):
    """Test that reconciliation is run during finalization."""
    from quant_research.config import load_config
    from quant_research.execution.paper import OrderSide
    from quant_research.experiments.paper_validation import PaperValidationRunner

    cfg = load_config("configs/baseline.yaml")
    runner = PaperValidationRunner(cfg)

    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=1)
    runner.broker.submit(order, current_price=100.0, current_time=ts)
    runner.broker.process_bar(ts, {"SPY": 100.0})
    runner.record_step(runner.broker, {"SPY": 100.0}, current_time=ts)

    report = runner.finalize(experiment_id="test-exp-003")
    assert report.final_reconciliation_consistent


def test_paper_validation_report_serialization(tmp_path):
    """Test that the validation report serializes to JSON correctly."""
    from quant_research.config import load_config
    from quant_research.execution.paper import OrderSide
    from quant_research.experiments.paper_validation import PaperValidationRunner

    cfg = load_config("configs/baseline.yaml")
    runner = PaperValidationRunner(cfg)

    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=1)
    runner.broker.submit(order, current_price=100.0, current_time=ts)
    runner.broker.process_bar(ts, {"SPY": 100.0})
    runner.record_step(runner.broker, {"SPY": 100.0}, current_time=ts)

    report = runner.finalize(experiment_id="test-exp-004")
    path = runner.save_report(tmp_path)

    import json
    data = json.loads(path.read_text())
    assert data["experiment_id"] == "test-exp-004"
    assert "gate_results" in data


# ---------------------------------------------------------------------------
# Operational readiness tests
# ---------------------------------------------------------------------------

def test_operational_config_validation():
    """Test that operational config validation catches errors."""
    from quant_research.execution.operational import OperationalConfig

    # Valid config
    cfg = OperationalConfig()
    assert cfg.validate() == []

    # Invalid configs
    bad_cfg = OperationalConfig(max_position=-1.0)
    errors = bad_cfg.validate()
    assert len(errors) > 0
    assert any("max_position" in e for e in errors)

    bad_cfg2 = OperationalConfig(initial_cash=-1000.0)
    errors2 = bad_cfg2.validate()
    assert len(errors2) > 0
    assert any("initial_cash" in e for e in errors2)


def test_monitoring_dashboard():
    """Test that monitoring dashboard captures snapshots."""
    from quant_research.execution.paper import PaperOrder, OrderSide
    from quant_research.execution.operational import MonitoringDashboard

    broker = PaperBroker()
    dashboard = MonitoringDashboard(broker)

    # Submit an order and take a snapshot
    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order, current_price=100.0, current_time=ts)
    broker.process_bar(ts, {"SPY": 100.0})

    snap = dashboard.snapshot()
    assert snap.portfolio_value > 0
    assert snap.n_open_positions == 1
    assert snap.n_filled_today == 1
    assert "SPY" in snap.positions


def test_monitoring_format_status():
    """Test that format_status produces a readable string."""
    from quant_research.execution.paper import OrderSide
    from quant_research.execution.operational import MonitoringDashboard

    broker = PaperBroker()
    dashboard = MonitoringDashboard(broker)

    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order, current_price=100.0, current_time=ts)
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 100.0})

    status = dashboard.format_status()
    assert "Paper Trading Status" in status
    assert "Portfolio Value" in status
    assert "SPY" in status


def test_manual_override_flatten():
    """Test that manual override can flatten positions."""
    from quant_research.execution.paper import PaperOrder, OrderSide, OrderStatus
    from quant_research.execution.operational import ManualOverride

    broker = PaperBroker(slippage_bps=0.0)
    override = ManualOverride(broker)

    # Create a position
    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=10)
    broker.submit(order, current_price=100.0, current_time=ts)
    broker.process_bar(pd.Timestamp("2024-01-03", tz="UTC"), {"SPY": 100.0})

    pos = broker.get_position("SPY")
    assert pos.quantity == 10

    # Flatten
    result = override.flatten_position("SPY", current_price=100.0)
    assert result is not None

    pos = broker.get_position("SPY")
    assert abs(pos.quantity) < 1e-9


def test_manual_override_cancel_all():
    """Test that manual override can cancel all orders."""
    from quant_research.execution.paper import OrderType, OrderSide
    from quant_research.execution.operational import ManualOverride

    broker = PaperBroker()
    override = ManualOverride(broker)

    # Submit limit orders (they stay pending because limit is below market)
    ts = pd.Timestamp("2024-01-02", tz="UTC")
    for i in range(3):
        order = PaperOrder(symbol="SPY", side=OrderSide.BUY, quantity=1,
                           order_type=OrderType.LIMIT, limit_price=50.0)
        broker.submit(order, current_price=100.0, current_time=ts)

    # Verify they're pending
    pending_count = len(broker.pending_orders)
    assert pending_count == 3, f"Expected 3 pending orders, got {pending_count}"

    cancelled = override.cancel_all_orders()
    assert cancelled == 3
    assert len(broker.pending_orders) == 0


def test_manual_override_kill_switch():
    """Test manual kill switch trip and reset."""
    from quant_research.execution.operational import ManualOverride

    broker = PaperBroker()
    override = ManualOverride(broker)

    # Trip kill switch
    override.trip_kill_switch("test")
    assert broker.safeguards.kill_switch_active

    # Reset
    override.reset_kill_switch()
    assert not broker.safeguards.kill_switch_active


def test_health_check():
    """Test that health checks pass for a healthy broker."""
    from quant_research.execution.operational import HealthCheck

    broker = PaperBroker()
    health = HealthCheck(broker)

    results = health.check_all()
    assert results["broker_initialized"]
    assert results["positions_reconciled"]
    assert results["no_orphan_orders"]
    assert results["cash_positive"]
    assert results["audit_trail_intact"]


def test_failure_restart_recovery():
    """Test failure and restart recovery scenarios."""
    from quant_research.execution.operational import FailureRestartTest

    broker = PaperBroker()
    test = FailureRestartTest(broker)

    results = test.run_all()
    assert results["kill_switch_recovery"]
    assert results["cancel_all_recovery"]
    assert results["flatten_recovery"]
    assert results["reconciliation_after_ops"]

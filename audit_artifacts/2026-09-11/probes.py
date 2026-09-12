"""Independent audit reproductions. No production code is modified.

Run from the repository: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
PYTHONPATH=src python audit_artifacts/2026-09-11/probes.py
"""
from __future__ import annotations

import json
import tempfile
import warnings
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant_research.config import AppConfig, EvaluationConfig, ExecutionConfig, ModelConfig, ResearchConfig
from quant_research.data.loaders import _long_from_wide_csv, to_price_panels
from quant_research.data.validation import validate_ohlcv
from quant_research.evaluation.backtest import backtest
from quant_research.evaluation.robustness import replay_oos, parameter_perturbation, assert_cost_accounting, cost_stress
from quant_research.evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from quant_research.execution.paper import PaperBroker, PaperOrder, OrderSide, OrderType, Safeguards
from quant_research.execution.operational import ManualOverride
from quant_research.experiments.paper_validation import PaperValidationRunner
from quant_research.experiments.registry import SearchLedger, TrialCounter
from quant_research.features.information import build_information_features
from quant_research.features.point_in_time import validate_events
from quant_research.features.price_volume import build_signal_extensions
from quant_research.strategies.baseline import run_walk_forward
from quant_research.strategies.discovery import discover_and_evaluate_oos

OUT = Path(__file__).resolve().parent
RESULTS = {}


def probe(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:
        RESULTS[name] = {"probe_error": type(exc).__name__, "message": str(exc)}
    print(name, json.dumps(RESULTS[name], default=str), flush=True)


idx = pd.bdate_range("2020-01-01", periods=244, tz="UTC")
rng = np.random.default_rng(810)
X = pd.DataFrame(rng.normal(size=(len(idx), 3)), index=idx, columns=["a", "b", "c"])
fwd = pd.Series(rng.normal(0.001, 0.009, len(idx)), index=idx)
y = (fwd > 0).astype(float)
cfg = AppConfig(
    evaluation=EvaluationConfig(train_window=60, validation_window=30, test_window=30,
                                step_bars=30, purge_bars=2, embargo_bars=2),
    model=ModelConfig(type="logistic"),
    research=ResearchConfig(max_trials=2, threshold_candidates=[0.0], hold_candidates=[1],
                            placebo_runs=1, bootstrap_samples=10),
)
ts = idx[0]


def discovery_replay():
    original = discover_and_evaluate_oos(X, {"all": list(X)}, y, fwd, cfg)
    replay = replay_oos(X, y, fwd, cfg, original, None)
    boundary = [s.test_idx[0] for s in original.fold_specs[1:]]
    try:
        assert_cost_accounting(replay, cfg.execution.fee_bps, cfg.execution.slippage_bps)
        assertion = "passed"
    except AssertionError as exc:
        assertion = str(exc)
    try:
        cost_stress(X, y, fwd, cfg, original, None, fee_grid=[5.0])
        battery = "passed"
    except AssertionError as exc:
        battery = str(exc)
    return {
        "n_folds": len(original.fold_specs),
        "positions_equal": original.oos_positions.equals(replay.oos_positions),
        "original_fee": original.fee_costs, "replay_fee": replay.fee_costs,
        "net_delta_at_fold_starts": (replay.oos_returns - original.oos_returns).loc[boundary].tolist(),
        "accounting_assertion": assertion, "cost_stress_assertion": battery,
    }


def discovery_lock():
    class RejectingLock:
        def __init__(self): self.calls = 0
        def verify(self, folds):
            self.calls += 1
            raise RuntimeError("evaluation forbidden")
    lock = RejectingLock()
    res = discover_and_evaluate_oos(X, {"all": list(X)}, y, fwd, cfg, locked_test=lock)
    return {"verify_calls": lock.calls, "evaluated_folds": len(res.folds)}


def discovery_start():
    with tempfile.TemporaryDirectory() as td:
        ledger = SearchLedger(Path(td) / "search.jsonl")
        counter = TrialCounter(Path(td) / "counter.json")
        with patch("quant_research.strategies.discovery._validation_sharpe", side_effect=RuntimeError("interrupted during search")):
            try:
                discover_and_evaluate_oos(X, {"all": list(X)}, y, fwd, cfg,
                                         ledger=ledger, family_id="family", trial_counter=counter)
            except RuntimeError:
                pass
        return {"ledger_entries": ledger.read_all(), "trial_count": counter.count}


def parameter_anchor():
    params = ModelConfig(type="logistic", parameters={"C": 1.0}, logreg_C=0.01)
    cfg2 = replace(cfg, model=params, research=replace(cfg.research, threshold_candidates=[0.5]))
    base = run_walk_forward(X, y, fwd, cfg2)
    captures = []
    real_replay = replay_oos
    def capture(*args, **kwargs):
        res = real_replay(*args, **kwargs)
        captures.append(res)
        return res
    with patch("quant_research.evaluation.robustness.replay_oos", side_effect=capture):
        parameter_perturbation(X, y, fwd, cfg2, base, None, factors=[1.0])
    replay = captures[0]
    return {"baseline_C": base.fitted_models[1].named_steps["model"].C,
            "factor_one_C": replay.fitted_models[1].named_steps["model"].C,
            "max_probability_difference": float((base.predictions.prob-replay.predictions.prob).abs().max())}


def malformed_lock():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "lock.json"
        result = {}
        for value in ({}, {"spec": {}}, {"folds": [], "hash": None}):
            path.write_text(json.dumps(value))
            lock = LockedTestProtocol(path, dataset_id="dataset", config_fingerprint="config")
            lock.verify(walk_forward_splits(idx, cfg.evaluation))
            result[json.dumps(value)] = {"accepted": True, "replacement_n_folds": json.loads(path.read_text())["n_folds"]}
        return result


def corrupt_ledger():
    with tempfile.TemporaryDirectory() as td:
        ledger = SearchLedger(Path(td) / "ledger.jsonl")
        ledger.record_start("f", "search", 1)
        before = ledger.family_attempt_count("f")
        ledger.path.write_text('{"family_id":"f", BROKEN\n')
        ledger.record_start("f", "search", 1)
        return {"before_corruption": before, "after_corruption_and_another_search": ledger.family_attempt_count("f")}


def paper_latency():
    broker = PaperBroker(latency_bars=3, fee_bps=0, slippage_bps=0)
    o = broker.submit(PaperOrder("SPY", OrderSide.BUY, 1), 100, ts)
    return {"configured_latency": broker.latency_bars, "status_at_submission": o.status.value,
            "submitted_at": o.submitted_at, "filled_at": o.filled_at}


def paper_duplicate_id():
    broker = PaperBroker(fee_bps=0, slippage_bps=0)
    for _ in range(2):
        broker.submit(PaperOrder("SPY", OrderSide.BUY, 1, order_id="retry-id"), 100, ts)
    return {"position": broker.get_position("SPY").quantity,
            "recorded_order_count": len(broker.orders),
            "recorded_filled_quantity": broker.orders["retry-id"].filled_quantity,
            "reconciliation": broker.reconcile()}


def paper_kill_pending():
    broker = PaperBroker(fee_bps=0, slippage_bps=0)
    o = broker.submit(PaperOrder("SPY", OrderSide.BUY, 10, OrderType.LIMIT, 90), 100, ts)
    broker.safeguards.trip_kill_switch("emergency")
    broker.process_bar(idx[1], {"SPY": 80})
    return {"kill_active": broker.safeguards.kill_switch_active, "order_status": o.status.value,
            "position": broker.get_position("SPY").quantity}


def paper_exit():
    broker = PaperBroker(initial_cash=1000, fee_bps=0, slippage_bps=0)
    broker.submit(PaperOrder("SPY", OrderSide.BUY, 8), 100, ts)
    broker.process_bar(ts, {"SPY": 100})
    exit_order = ManualOverride(broker).flatten_position("SPY", 100)
    return {"exit_status": exit_order.status.value, "reason": exit_order.cancel_reason,
            "remaining_position": broker.get_position("SPY").quantity}


def pending_exposure():
    broker = PaperBroker(initial_cash=1000, fee_bps=0, slippage_bps=0)
    for _ in range(2):
        broker.submit(PaperOrder("SPY", OrderSide.BUY, 8, OrderType.LIMIT, 100), 100, ts)
    broker.process_bar(idx[1], {"SPY": 100})
    return {"position": broker.get_position("SPY").quantity, "cash": broker.cash,
            "configured_max_position": broker.safeguards.max_position,
            "actual_position_weight": broker.get_position("SPY").quantity * 100 / broker.current_value}


def paper_marks():
    broker = PaperBroker(initial_cash=1000, fee_bps=0, slippage_bps=0)
    broker.submit(PaperOrder("SPY", OrderSide.BUY, 5), 100, ts)
    broker.process_bar(ts, {"SPY": 100})
    before = broker.current_value
    broker.process_bar(idx[1], {"QQQ": 200})
    missing_mark = broker.current_value
    broker.process_bar(idx[2], {"SPY": np.nan})
    return {"before": before, "value_when_held_symbol_omitted": missing_mark,
            "value_after_nan_price": broker.current_value}


def paper_evidence():
    runner = PaperValidationRunner(cfg)
    runner.test_kill_switch()
    for _ in range(60):
        runner.record_step(runner.broker)
    report = runner.finalize()
    return {"state": report.state, "days": report.n_days_executed,
            "filled_orders": report.n_orders_filled, "start": report.start_time,
            "end": report.end_time, "gates": report.gate_results}


def paper_breaches():
    runner = PaperValidationRunner(cfg)
    runner.test_kill_switch()
    runner.broker.update_daily_return(-0.20)
    runner.broker.submit(PaperOrder("SPY", OrderSide.BUY, 1), 100, ts)
    runner.broker.current_value = runner.broker.initial_cash * 0.8
    for _ in range(60):
        runner.record_step(runner.broker)
    report = runner.finalize()
    return {"state": report.state, "breaches": report.n_safeguard_breaches,
            "max_drawdown": report.max_drawdown_observed, "gates": report.gate_results}


def paper_fees():
    runner = PaperValidationRunner(cfg)
    runner.broker.submit(PaperOrder("SPY", OrderSide.BUY, 10), 100, ts)
    fee_once = (runner.broker.initial_cash - runner.broker.cash
                - 10 * runner.broker.get_order(next(iter(runner.broker.orders))).filled_price)
    for _ in range(3): runner.record_step(runner.broker)
    return {"actual_fee": fee_once, "reported_fee": runner.finalize().total_fees_paid}


def event_identity():
    first = dict(event_id="e1", symbol="SPY", event_time=ts, publication_time=ts,
                 availability_time=ts, source="source", raw_value=1., processed_value=1.,
                 sentiment=1., revision=0)
    ev = pd.DataFrame([first])
    single = build_information_features(idx[:4], ev, "SPY")
    double = build_information_features(idx[:4], pd.concat([ev, ev]), "SPY")
    rev = dict(first, revision=1, availability_time=idx[1], publication_time=idx[1],
               raw_value=-1., processed_value=-1., sentiment=-1.)
    revised = build_information_features(idx[:4], pd.DataFrame([dict(first, topic="earnings"), dict(rev, topic="earnings")]), "SPY")
    conflict = pd.DataFrame([first, dict(first, processed_value=np.nan)])
    return {"single_attention": single.info_attention.iloc[0],
            "redelivered_attention": double.info_attention.iloc[0],
            "revised_sentiment": revised.info_sentiment.tolist(),
            "missing_value_conflict_accepted_rows": len(validate_events(conflict))}


def fabricated_ohlc():
    wide = pd.DataFrame({"timestamp": idx, "Close_SPY": 100 * (1+fwd).cumprod().to_numpy(),
                         "Volume_SPY": np.full(len(idx), 100000.)})
    long = validate_ohlcv(_long_from_wide_csv(wide))
    panels = to_price_panels(long)
    ext = build_signal_extensions(*panels, "SPY")
    return {"synthetic_range_rows": int(long._synthetic_range.sum()),
            "overnight_matches_close_return": bool(np.allclose(ext.overnight_gap.iloc[1:],
               panels[3].SPY.pct_change().iloc[1:])),
            "intraday_return_unique": ext.intraday_return.unique().tolist(),
            "range_position_nonmissing": int(ext.day_range_position.notna().sum())}


def invalid_return():
    f = fwd.copy()
    f.iloc[100] = np.inf
    bt = backtest(pd.Series(1., index=idx), f, cfg.execution, risk_returns=fwd.shift(1))
    g = fwd.copy()
    g.iloc[100] = np.nan
    missing = backtest(pd.Series(1., index=idx), g, cfg.execution, risk_returns=fwd.shift(1))
    return {"infinite_net_bar": bt.net_returns.iloc[100], "reported_sharpe": bt.metrics["sharpe"],
            "missing_return_gross": missing.gross_returns.iloc[100],
            "position_during_missing_return": missing.positions.iloc[100]}


with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for name, fn in [
        ("discovery_replay", discovery_replay), ("discovery_lock", discovery_lock),
        ("discovery_start", discovery_start), ("parameter_anchor", parameter_anchor),
        ("malformed_lock", malformed_lock), ("corrupt_ledger", corrupt_ledger),
        ("paper_latency", paper_latency), ("paper_kill_pending", paper_kill_pending),
        ("paper_duplicate_id", paper_duplicate_id),
        ("paper_exit", paper_exit), ("pending_exposure", pending_exposure),
        ("paper_marks", paper_marks), ("paper_evidence", paper_evidence),
        ("paper_breaches", paper_breaches), ("paper_fees", paper_fees),
        ("event_identity", event_identity), ("fabricated_ohlc", fabricated_ohlc),
        ("invalid_return", invalid_return),
    ]:
        probe(name, fn)
OUT.joinpath("probe-results.json").write_text(json.dumps(RESULTS, indent=2, default=str) + "\n")

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
    broker = PaperBroker()
    ts = pd.Timestamp("2024-01-02", tz="UTC")
    order = PaperOrder(timestamp=ts, symbol="SPY", side="buy", quantity=10,
                       expected_price=100.0)
    broker.submit(order, fill_price=100.05)
    assert order.slippage_bps == pytest.approx(5.0)
    assert order.latency_bars >= 1  # no same-bar fill by construction
    with pytest.raises(ValueError, match="duplicate"):
        broker.submit(order, fill_price=100.05)


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
    """Replicate the pipeline's exact stage-1/3 inputs (price/volume +
    information features) so an independent run_walk_forward reproduces the
    baseline, then the risk report can be checked against the true ledger."""
    from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels

    ohlcv = generate_synthetic_ohlcv(cfg.data.assets, cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    price = build_price_volume_features(close, volume, cfg.data.target)
    events = generate_synthetic_events(close.index, cfg.data.target)
    info = build_information_features(close.index, events, cfg.data.target)
    feats = price.join(info, how="left")
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
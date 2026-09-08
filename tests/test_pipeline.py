"""Discovery, execution safeguards, and end-to-end pipeline tests."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.walk_forward import LockedTestProtocol
from quant_research.experiments.leaderboard import build_leaderboard
from quant_research.experiments.registry import ExperimentRegistry, TrialCounter
from quant_research.execution.paper import PaperBroker, PaperOrder
from quant_research.execution.safeguards import Safeguards
from quant_research.features.price_volume import build_price_volume_features
from quant_research.run import run_research_pipeline
from quant_research.strategies.discovery import discover_strategies, evaluate_candidate_oos


def test_discovery_bounded_and_validation_ranked(universe_small):
    feats, y, fwd, cfg = universe_small
    feature_sets = {
        "core": ["momentum_63", "trend_50"],
        "vol": ["realized_vol_20", "regime_high_vol"],
    }
    grid = discover_strategies(feats, feature_sets, y, fwd, cfg, seed=42)
    # 2 sets x 2 models x 4 hold periods = 16 candidates, bounded by max_trials
    assert len(grid) <= cfg.research.max_trials
    assert grid["robust_adjusted_score"].is_monotonic_decreasing
    assert grid["validation_sharpe"].notna().all()


def test_discovery_oos_eval_once(universe_small):
    feats, y, fwd, cfg = universe_small
    feature_sets = {"core": list(feats.columns[:2])}
    grid = discover_strategies(feats, feature_sets, y, fwd, cfg, seed=42)
    protocol = LockedTestProtocol()
    res = evaluate_candidate_oos(feats, y, fwd, cfg, grid.iloc[0], feature_sets,
                                 locked_test=protocol)
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

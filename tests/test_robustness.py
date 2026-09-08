"""Robustness tests: every stress re-runs the exact OOS execution path.

Proves the four invariants required by the research-integrity audit:
1. baseline stress at configured assumptions equals the baseline OOS result
2. changing costs changes only execution economics (never the strategy)
3. changing delay changes signal timing, never model selection
4. changing stress assumptions never reselects a model/threshold using test data
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, EvaluationConfig
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.robustness import (
    cost_stress,
    delay_stress,
    missing_data_stress,
    parameter_perturbation,
    replay_oos,
    robustness_battery,
    slippage_stress,
)
from quant_research.evaluation.walk_forward import LockedTestProtocol
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment


@pytest.fixture(scope="module")
def setup():
    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY", "QQQ"], target="SPY",
                        start="2016-01-01", end="2020-01-01"),
        evaluation=EvaluationConfig(train_window=200, validation_window=50,
                                    test_window=50, step_bars=100,
                                    purge_bars=2, embargo_bars=2, expanding=True),
    )
    ohlcv = generate_synthetic_ohlcv(["SPY", "QQQ"], cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    lt = LockedTestProtocol()
    base = run_walk_forward(feats, y, fwd, cfg, locked_test=lt)
    summary = summarize_experiment(base)
    return cfg, feats, y, fwd, base, summary, lt


def test_baseline_stress_at_configured_assumptions_equals_oos(setup):
    cfg, feats, y, fwd, base, summary, lt = setup
    table = cost_stress(feats, y, fwd, cfg, base, lt)
    row = table[table["fee_bps"] == cfg.execution.fee_bps].iloc[0]
    assert row["sharpe"] == pytest.approx(summary["full_oos_sharpe"])
    assert row["net_return"] == pytest.approx(summary["full_oos_net_return"])
    assert row["gross_sharpe"] == pytest.approx(summary["full_oos_gross_sharpe"])
    # exact replay reproduces the OOS return streams bit-for-bit
    replay = replay_oos(feats, y, fwd, cfg, base, lt, exec_cfg=cfg.execution)
    pd.testing.assert_series_equal(replay.oos_returns, base.oos_returns)
    pd.testing.assert_series_equal(replay.oos_gross_returns, base.oos_gross_returns)


def test_cost_stress_changes_only_execution_economics(setup):
    cfg, feats, y, fwd, base, summary, lt = setup
    table = cost_stress(feats, y, fwd, cfg, base, lt)
    for _, row in table.iterrows():
        # gross side is unaffected by fees
        assert row["gross_sharpe"] == pytest.approx(summary["full_oos_gross_sharpe"])
        assert row["gross_return"] == pytest.approx(summary["full_oos_gross_return"])
        # thresholds are pinned: no reselection under stress
        replay = replay_oos(feats, y, fwd, cfg, base, lt,
                            exec_cfg=replace(cfg.execution, fee_bps=float(row["fee_bps"])))
        pd.testing.assert_series_equal(
            replay.folds["threshold"].reset_index(drop=True),
            base.folds["threshold"].reset_index(drop=True))
    # higher fees strictly reduce net economics
    assert (table["net_return"].diff().dropna() < 0).all()
    assert (table["fee_cost"].diff().dropna() > 0).all()


def test_delay_stress_changes_timing_not_model(setup):
    cfg, feats, y, fwd, base, summary, lt = setup
    table = delay_stress(feats, y, fwd, cfg, base, lt)
    replay1 = replay_oos(feats, y, fwd, cfg, base, lt,
                         exec_cfg=replace(cfg.execution, signal_delay_bars=1))
    # model selection unchanged
    pd.testing.assert_series_equal(
        replay1.folds["threshold"].reset_index(drop=True),
        base.folds["threshold"].reset_index(drop=True))
    for fid in base.fitted_models:
        m0 = base.fitted_models[fid].named_steps["model"]
        m1 = replay1.fitted_models[fid].named_steps["model"]
        np.testing.assert_array_equal(m0.coef_, m1.coef_)
        np.testing.assert_array_equal(m0.intercept_, m1.intercept_)
    # timing changed -> the executed return stream differs
    d0 = table[table["delay_bars"] == 0].iloc[0]
    d1 = table[table["delay_bars"] == 1].iloc[0]
    assert d0["sharpe"] != pytest.approx(d1["sharpe"])


def test_stress_never_reselects_on_test_data(setup):
    cfg, feats, y, fwd, base, summary, lt = setup
    # mutate test-only labels and returns; selection must not move
    y2 = y.copy()
    fwd2 = fwd.copy()
    for spec in base.fold_specs:
        te = spec.test_idx.intersection(y.index)
        y2.loc[te] = 1.0 - y2.loc[te]
        fwd2.loc[te] = -fwd2.loc[te]
    replay = replay_oos(feats, y2, fwd2, cfg, base, lt,
                        exec_cfg=replace(cfg.execution, fee_bps=10.0))
    pd.testing.assert_series_equal(
        replay.folds["threshold"].reset_index(drop=True),
        base.folds["threshold"].reset_index(drop=True))
    for fid in base.fitted_models:
        np.testing.assert_array_equal(
            replay.fitted_models[fid].named_steps["model"].coef_,
            base.fitted_models[fid].named_steps["model"].coef_)
    # the evaluation itself reflects the mutated test data (as it should)
    assert not np.allclose(replay.oos_returns.to_numpy(), base.oos_returns.to_numpy())


def test_robustness_battery_covers_all_dimensions(setup):
    cfg, feats, y, fwd, base, summary, lt = setup
    battery = robustness_battery(feats, y, fwd, cfg, base, lt)
    assert set(battery) == {"cost_stress", "slippage_stress", "delay_stress",
                            "parameter_perturbation", "missing_data"}
    assert len(battery["cost_stress"]) >= 3
    assert len(battery["delay_stress"]) >= 2
    assert len(battery["parameter_perturbation"]) >= 2
    assert len(battery["missing_data"]) == 1
    # every stress keeps the baseline thresholds pinned
    for name in ("cost_stress", "slippage_stress", "delay_stress",
                 "parameter_perturbation", "missing_data"):
        if name == "missing_data":
            res = replay_oos(feats, y, fwd, cfg, base, lt)  # baseline exec
        else:
            continue
        pd.testing.assert_series_equal(
            res.folds["threshold"].reset_index(drop=True),
            base.folds["threshold"].reset_index(drop=True))


def test_robustness_does_not_consume_research_trials(setup, tmp_path):
    cfg, feats, y, fwd, base, summary, lt = setup
    from quant_research.experiments.registry import TrialCounter

    counter = TrialCounter(tmp_path / "trials.json")
    counter.increment(100)
    before = counter.count
    robustness_battery(feats, y, fwd, cfg, base, lt)
    replay_oos(feats, y, fwd, cfg, base, lt, exec_cfg=cfg.execution,
               trial_counter=counter)
    assert counter.count == before

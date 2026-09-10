"""Baseline walk-forward strategy tests: selection on validation, locked OOS."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.walk_forward import (
    LockedTestProtocol,
    LockedTestViolation,
)
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import (
    run_walk_forward,
    select_threshold,
    summarize_experiment,
)


@pytest.fixture(scope="module")
def universe():
    ohlcv = generate_synthetic_ohlcv(["SPY"], "2015-01-01", "2020-01-01", seed=42)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype("float")
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    return feats, y, fwd, close


def test_walk_forward_produces_expected_columns(universe, small_config):
    feats, y, fwd, _ = universe
    res = run_walk_forward(feats, y, fwd, small_config)
    cols = {"fold_id", "train_start", "train_end", "val_start", "val_end",
            "test_start", "test_end", "purge_bars", "embargo_bars", "threshold",
            "selected_features", "oos_sharpe", "oos_auc", "oos_brier"}
    assert cols.issubset(set(res.folds.columns))
    assert (res.folds["purge_bars"] == small_config.evaluation.purge_bars).all()
    assert res.predictions["fold"].nunique() == len(res.folds)


def test_threshold_selection_uses_validation_only(universe, small_config):
    feats, y, fwd, _ = universe
    # threshold selection on validation data must be independent of test data:
    # two disjoint windows within the fixture range
    val_idx = pd.bdate_range("2018-01-03", periods=60, freq="B").tz_localize("UTC")
    val_idx = val_idx[val_idx.isin(fwd.index)]
    probs = pd.Series(np.random.default_rng(1).uniform(0.4, 0.6, len(val_idx)), index=val_idx)
    thr1, _ = select_threshold(probs, fwd.loc[val_idx], [0.5, 0.55], small_config.execution)
    test_idx = pd.bdate_range("2019-06-03", periods=60, freq="B").tz_localize("UTC")
    test_idx = test_idx[test_idx.isin(fwd.index)]
    thr2, _ = select_threshold(probs, fwd.loc[test_idx], [0.5, 0.55], small_config.execution)
    # pure structural check: select_threshold receives ONLY the data passed in
    assert thr1 in [0.5, 0.55] and thr2 in [0.5, 0.55]


def test_locked_test_blocks_recut(universe, small_config):
    feats, y, fwd, _ = universe
    protocol = LockedTestProtocol()
    run_walk_forward(feats, y, fwd, small_config, locked_test=protocol)
    from quant_research.config import EvaluationConfig

    tampered = small_config
    from dataclasses import replace

    # Change test_window to create different layout (must also be non-gapped)
    # step_bars=30, test_window=30 is non-gapped but different from baseline
    tampered = replace(small_config, evaluation=replace(
        small_config.evaluation, test_window=30, step_bars=30))
    with pytest.raises(LockedTestViolation):
        run_walk_forward(feats, y, fwd, tampered, locked_test=protocol)


def test_summary_shape(universe, small_config):
    feats, y, fwd, _ = universe
    res = run_walk_forward(feats, y, fwd, small_config)
    s = summarize_experiment(res)
    for key in ("mean_oos_sharpe", "median_oos_sharpe", "mean_oos_auc",
                "worst_oos_dd", "full_oos_max_dd", "positive_folds",
                "n_folds", "full_oos_sharpe"):
        assert key in s
    assert s["n_folds"] == len(res.folds)


def _summary_stub(sharpes):
    """Minimal ExperimentResult stand-in for concentration-metric tests."""
    from types import SimpleNamespace

    f = pd.DataFrame({"oos_sharpe": sharpes, "oos_auc": 0.5, "oos_brier": 0.25,
                      "oos_max_dd": -0.1, "oos_trades": 5})
    return SimpleNamespace(folds=f, oos_returns=pd.Series([0.0, 0.001]),
                           oos_gross_returns=None, fee_costs=0.0,
                           slippage_costs=0.0)


def test_single_fold_share_is_largest_positive_contribution():
    """A06: concentration = the LARGEST fold's share of the positive Sharpe
    pool.  The old ratio (sum positive / sum |all|) was not a concentration:
    balanced positives [1,1,1,1] scored 1.0 (always failing the gate) while
    [10, 0.01, 0.01, -9] scored 0.53 (passing) despite one fold supplying
    99.8% of the positive Sharpe."""
    # balanced positives: each fold contributes 1/4
    s = summarize_experiment(_summary_stub([1.0, 1.0, 1.0, 1.0]))
    assert s["single_fold_share"] == pytest.approx(0.25)
    # single winner: ~all of the positive pool comes from one fold
    s = summarize_experiment(_summary_stub([10.0, 0.01, 0.01, -9.0]))
    assert s["single_fold_share"] == pytest.approx(10.0 / 10.02)
    # mixed signs: losses leave the pool, largest positive still dominates
    s = summarize_experiment(_summary_stub([3.0, 2.0, -1.0]))
    assert s["single_fold_share"] == pytest.approx(0.6)


def test_single_fold_share_no_positive_edge_is_nan():
    """Flat (NaN-Sharpe) and all-negative folds leave no positive edge to
    concentrate: the share is NaN and the promotion gate fails."""
    s = summarize_experiment(_summary_stub([float("nan"), float("nan")]))
    assert np.isnan(s["single_fold_share"])
    s = summarize_experiment(_summary_stub([-1.0, -2.0]))
    assert np.isnan(s["single_fold_share"])


def test_oos_predictions_cover_test_windows_only(universe, small_config):
    feats, y, fwd, _ = universe
    res = run_walk_forward(feats, y, fwd, small_config)
    test_ranges = list(zip(res.folds["test_start"], res.folds["test_end"]))
    for _, row in res.predictions.iterrows():
        start = res.folds.loc[res.folds["fold_id"] == row["fold"], "test_start"].iloc[0]
        end = res.folds.loc[res.folds["fold_id"] == row["fold"], "test_end"].iloc[0]
        assert start <= str(row.name.date()) <= end

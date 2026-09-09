"""Placebo design tests.

Placebo runs must reuse the same walk-forward folds, trial accounting,
preprocessing, selection procedure and execution model - randomizing only the
intended information.  Target-permutation and block-permutation variants are
first-class alongside feature shuffling, and placebo must never touch the
research trial counter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, EvaluationConfig
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.placebo import (
    PLACEBO_MODES,
    placebo_statistics,
    run_placebo_null,
)
from quant_research.evaluation.walk_forward import LockedTestProtocol
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment


@pytest.fixture(scope="module")
def setup():
    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2016-01-01", end="2020-01-01"),
        evaluation=EvaluationConfig(train_window=200, validation_window=50,
                                    test_window=50, step_bars=100,
                                    purge_bars=2, embargo_bars=2, expanding=True),
    )
    ohlcv = generate_synthetic_ohlcv(["SPY"], cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    return cfg, feats, y, fwd


def _pipeline(cfg, lt):
    def run(X, yy, ff):
        return summarize_experiment(run_walk_forward(X, yy, ff, cfg, locked_test=lt))
    return run


def test_all_placebo_modes_run_with_same_folds(setup):
    cfg, feats, y, fwd = setup
    lt = LockedTestProtocol()
    base = run_walk_forward(feats, y, fwd, cfg, locked_test=lt)
    for mode in PLACEBO_MODES:
        null = run_placebo_null(feats, y, fwd, _pipeline(cfg, lt),
                                n_runs=3, seed=42, mode=mode)
        assert len(null) == 3
        assert null["mean_oos_sharpe"].notna().all()
        assert (null["mode"] == mode).all()
    # the locked test protocol is still frozen to the identical folds
    lt.verify(base.fold_specs)


def test_placebo_does_not_touch_research_trials(setup, tmp_path):
    cfg, feats, y, fwd = setup
    from quant_research.experiments.registry import TrialCounter

    counter = TrialCounter(tmp_path / "trials.json")
    counter.increment(50)
    lt = LockedTestProtocol()
    run_walk_forward(feats, y, fwd, cfg, locked_test=lt, trial_counter=counter)
    after_baseline = counter.count
    assert after_baseline > 50
    # the placebo pipeline runs without a trial counter -> no increments
    run_placebo_null(feats, y, fwd, _pipeline(cfg, lt), n_runs=2, seed=42,
                     mode="shuffle_features")
    run_placebo_null(feats, y, fwd, _pipeline(cfg, lt), n_runs=2, seed=42,
                     mode="permute_target")
    run_placebo_null(feats, y, fwd, _pipeline(cfg, lt), n_runs=2, seed=42,
                     mode="block_permute")
    assert counter.count == after_baseline


def test_placebo_permute_target_passes_permuted_inputs(setup):
    """The pipeline must consume the permuted targets, not the originals."""
    cfg, feats, y, fwd = setup
    seen = {}

    def capture_run(X, yy, ff):
        seen["yy"] = yy.copy()
        seen["ff"] = ff.copy()
        return {"mean_oos_sharpe": 0.0, "median_oos_sharpe": 0.0}

    run_placebo_null(feats, y, fwd, capture_run, n_runs=1, seed=3,
                     mode="permute_target")
    # same index as the original (same folds are constructible)...
    assert seen["yy"].index.equals(y.index)
    assert seen["ff"].index.equals(fwd.index)
    # ...but the actual values are a permutation of the originals, not the
    # identity ordering (the pass-through pipeline receives the permuted info)
    assert sorted(seen["yy"].dropna().tolist()) == sorted(y.dropna().tolist())
    assert not pd.Series(seen["yy"].fillna(-999)).equals(y.fillna(-999))
    assert not pd.Series(seen["ff"].fillna(-999)).equals(fwd.fillna(-999))


def test_block_permute_assigns_values_to_original_chronology(setup):
    """A03: the block permutation must randomize the DATED targets -- values
    move, the chronological index never does.  The old code kept each value's
    original timestamp, so the pipeline's .loc lookup silently restored the
    original date-to-target pairing while the risk history was scrambled."""
    cfg, feats, y, fwd = setup
    seen = {}

    def capture_run(X, yy, ff):
        seen["yy"] = yy.copy()
        seen["ff"] = ff.copy()
        return {"mean_oos_sharpe": 0.0, "median_oos_sharpe": 0.0}

    run_placebo_null(feats, y, fwd, capture_run, n_runs=1, seed=3,
                     mode="block_permute", block_len=21)
    y_r, f_r = seen["yy"], seen["ff"]
    # chronology preserved: original index, monotonic increasing (risk history
    # derived as shift(1) stays valid)
    assert y_r.index.equals(y.index)
    assert y_r.index.is_monotonic_increasing
    assert f_r.index.equals(fwd.index)
    assert f_r.index.is_monotonic_increasing
    # the VALUES actually move: dated targets are genuinely randomized
    assert not pd.Series(y_r.fillna(-999)).equals(y.fillna(-999))
    assert not pd.Series(f_r.fillna(-999)).equals(fwd.fillna(-999))
    # label/return pairing is preserved: y and fwd were permuted with the SAME
    # index positions, so the (label, return) pair at each bar is an original
    # pair (sign relation survives), and missingness travels with the pair
    live = y_r.notna() & f_r.notna()
    assert ((f_r[live] > 0).astype(float) == y_r[live]).all()
    assert y_r.isna().sum() == y.isna().sum()
    assert (y_r.isna() == f_r.isna()).all()


def test_placebo_statistics_full_report():
    null = pd.DataFrame({"mean_oos_sharpe": np.linspace(-1, 1, 21)})
    s = placebo_statistics(0.0, null)
    for k in ("percentile", "adjusted_p", "percentile_mc_se", "null_mean",
              "null_median", "null_std", "null_p95", "n_runs", "observed"):
        assert k in s
    assert s["null_median"] == pytest.approx(0.0)
    assert s["null_mean"] == pytest.approx(0.0)
    assert s["n_runs"] == 21
    # Monte Carlo uncertainty of the empirical percentile (binomial SE, A12);
    # percentile here is 10/21 (nulls strictly below 0.0)
    p_emp = 10.0 / 21.0
    assert s["percentile"] == pytest.approx(p_emp)
    assert s["percentile_mc_se"] == pytest.approx(
        float(np.sqrt(p_emp * (1 - p_emp) / 21)))

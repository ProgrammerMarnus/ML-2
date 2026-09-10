"""Selection-isolation tests.

For every fold: TRAIN does model/imputer/scaler fitting; VALIDATION does
threshold/feature/parameter selection; TEST does evaluation only.

Explicitly mutating the test labels/returns must never change the selected
threshold, the selected features, or the fitted model parameters.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, EvaluationConfig
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import run_walk_forward


@pytest.fixture(scope="module")
def setup():
    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY", "QQQ"], target="SPY",
                        start="2016-01-01", end="2020-01-01"),
        # B09: Use step_bars <= test_window to avoid gapped windows
        evaluation=EvaluationConfig(train_window=200, validation_window=50,
                                    test_window=100, step_bars=100,
                                    purge_bars=2, embargo_bars=2, expanding=True),
    )
    ohlcv = generate_synthetic_ohlcv(["SPY", "QQQ"], cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    return cfg, feats, y, fwd


def _model_coefs(res):
    out = {}
    for fid in sorted(res.fitted_models):
        m = res.fitted_models[fid].named_steps["model"]
        out[fid] = (m.coef_.copy(), m.intercept_.copy())
    return out


def test_mutating_test_labels_does_not_change_selection(setup):
    """Mutating ONE fold's test labels must never change THAT fold's selection.

    With expanding windows a LATER fold's training data legitimately includes
    an earlier fold's test period, so mutating all test windows at once would
    change later folds through their (correct) train data -- that is standard
    walk-forward behavior, not leakage.  Therefore:
      (a) mutating the LAST fold's test labels leaves every fold identical;
      (b) mutating fold k's test labels leaves fold k's own threshold,
          selected features, and fitted model parameters untouched.
    """
    cfg, feats, y, fwd = setup
    base = run_walk_forward(feats, y, fwd, cfg)
    ref = _model_coefs(base)

    # (a) last fold: no later folds exist -> complete invariance
    y2 = y.copy()
    last = base.fold_specs[-1]
    y2.loc[last.test_idx.intersection(y.index)] = 1.0 - y2.loc[
        last.test_idx.intersection(y.index)]
    res2 = run_walk_forward(feats, y2, fwd, cfg)
    pd.testing.assert_series_equal(
        res2.folds["threshold"].reset_index(drop=True),
        base.folds["threshold"].reset_index(drop=True))
    pd.testing.assert_series_equal(
        res2.folds["selected_features"].reset_index(drop=True),
        base.folds["selected_features"].reset_index(drop=True))
    got = _model_coefs(res2)
    for fid in ref:
        np.testing.assert_array_equal(got[fid][0], ref[fid][0])
        np.testing.assert_array_equal(got[fid][1], ref[fid][1])

    # (b) per-fold: fold k's own selection is untouched by its own test labels
    for spec in base.fold_specs:
        yk = y.copy()
        mask = spec.test_idx.intersection(y.index)
        yk.loc[mask] = 1.0 - yk.loc[mask]
        resk = run_walk_forward(feats, yk, fwd, cfg)
        assert len(resk.folds) == len(resk.fold_specs)  # positional alignment
        assert resk.folds["threshold"].iloc[spec.fold_id - 1] == \
            base.folds["threshold"].iloc[spec.fold_id - 1]
        assert resk.folds["selected_features"].iloc[spec.fold_id - 1] == \
            base.folds["selected_features"].iloc[spec.fold_id - 1]
        mk = resk.fitted_models[spec.fold_id].named_steps["model"]
        mb = base.fitted_models[spec.fold_id].named_steps["model"]
        np.testing.assert_array_equal(mk.coef_, mb.coef_)
        np.testing.assert_array_equal(mk.intercept_, mb.intercept_)


def test_mutating_test_returns_does_not_change_selection(setup):
    """Mutating the LAST fold's test returns must change nothing at all:
    no later fold exists, and no fold's selection consumes its own test data.
    """
    cfg, feats, y, fwd = setup
    base = run_walk_forward(feats, y, fwd, cfg)
    fwd2 = fwd.copy()
    last = base.fold_specs[-1]
    fwd2.loc[last.test_idx.intersection(fwd.index)] = \
        -fwd2.loc[last.test_idx.intersection(fwd.index)]
    res2 = run_walk_forward(feats, y, fwd2, cfg)
    pd.testing.assert_series_equal(
        res2.folds["threshold"].reset_index(drop=True),
        base.folds["threshold"].reset_index(drop=True))
    pd.testing.assert_series_equal(
        res2.folds["selected_features"].reset_index(drop=True),
        base.folds["selected_features"].reset_index(drop=True))
    ref = _model_coefs(base)
    got = _model_coefs(res2)
    for fid in ref:
        np.testing.assert_array_equal(got[fid][0], ref[fid][0])
        np.testing.assert_array_equal(got[fid][1], ref[fid][1])


def test_thresholds_come_from_validation_candidates(setup):
    cfg, feats, y, fwd = setup
    base = run_walk_forward(feats, y, fwd, cfg)
    assert (base.folds["threshold"].isin(cfg.research.threshold_candidates)).all()
    # no fold may see its test bars during threshold selection by construction
    for _, row in base.folds.iterrows():
        assert row["threshold"] in cfg.research.threshold_candidates

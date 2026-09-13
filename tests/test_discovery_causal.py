"""A02 regression tests: nested discovery selection is causal.

The deep audit found that the globally ranked discovery winner was applied
retrospectively to earlier OOS folds even though later validation windows
overlap earlier test periods (247 of the first 252 test bars sat inside the
second validation window).  The fix nests candidate selection within each
outer fold: fold k's candidate is chosen using only data strictly before
fold k's test start, then evaluated on fold k's test only.

These tests pin the causal property with independent timing expectations:
perturbing any period AFTER a fold's decision time cannot change that fold's
chosen candidate or its test predictions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ResearchConfig
from quant_research.evaluation.robustness import replay_oos
from quant_research.evaluation.walk_forward import LockedTestViolation
from quant_research.strategies.discovery import discover_and_evaluate_oos

FLIP = 300  # regime boundary bar


def _regime_stream(n=900, seed=11):
    """Deterministic two-regime stream: 'early_signal' equals the forward
    direction before bar FLIP and is uninformative afterwards; 'late_signal' is
    uninformative before FLIP and equals the direction afterwards.  Nested
    selection therefore picks the informative candidate per regime, while a
    single global winner cannot."""
    idx = pd.bdate_range("2016-01-01", periods=n, freq="B").tz_localize("UTC")
    rng = np.random.default_rng(seed)
    pattern = np.tile([0.002, -0.002], n // 2 + 1)[:n]
    pattern[-1] = 0.002
    fwd = pd.Series(pattern, index=idx)
    y = (fwd > 0).astype(float)
    pos = np.arange(n)
    x1 = np.where(pos < FLIP, y.to_numpy(), 0.5) + rng.normal(0.0, 0.01, n)
    x2 = np.where(pos < FLIP, 0.5, y.to_numpy()) + rng.normal(0.0, 0.01, n)
    X = pd.DataFrame({
        "early_signal": x1,
        "late_signal": x2,
        "noise": rng.normal(0.0, 1.0, n),
    }, index=idx)
    return X, y, fwd


def _discovery_cfg(idx):
    return AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start=str(idx[0].date()), end=str(idx[-1].date())),
        # B09: Use step_bars <= test_window to avoid gapped windows
        evaluation=EvaluationConfig(train_window=250, validation_window=60,
                                    test_window=100, step_bars=100,
                                    purge_bars=2, embargo_bars=2,
                                    expanding=False),
        research=ResearchConfig(threshold_candidates=[0.5], hold_candidates=[1],
                                max_trials=8, placebo_runs=1, bootstrap_samples=20),
    )


def _feature_sets():
    return {"early": ["early_signal", "noise"], "late": ["late_signal", "noise"]}


def test_nested_discovery_selection_differs_across_regimes():
    """Per-fold selection: the chosen candidate follows the regime, which a
    single global winner cannot do."""
    X, y, fwd = _regime_stream()
    cfg = _discovery_cfg(X.index)
    res = discover_and_evaluate_oos(X, _feature_sets(), y, fwd, cfg)
    assert len(res.folds) >= 3
    # distinct winners across folds (regime-dependent selection)
    assert res.folds["candidate_id"].nunique() > 1
    # every fold's decision artifacts are recorded and reproducible
    assert res.folds["threshold"].notna().all()
    assert res.predictions["fold"].nunique() == len(res.folds)


def test_nested_discovery_later_period_cannot_change_earlier_folds():
    """The exact audit requirement: perturbing ANY period at/after a fold's
    decision time cannot change that fold's chosen candidate or its test
    predictions.  Perturbing from the FIRST test start onward leaves fold 1's
    selection artifacts and predictions bit-identical (its own metrics may
    move -- the perturbed returns are its scored P&L, and the causal vol
    scaling reacts to realized returns)."""
    X, y, fwd = _regime_stream()
    cfg = _discovery_cfg(X.index)
    base = discover_and_evaluate_oos(X, _feature_sets(), y, fwd, cfg)

    first_test = base.fold_specs[0].test_idx[0]
    fwd2 = fwd.copy()
    fwd2.loc[fwd2.index >= first_test] = -fwd2.loc[fwd2.index >= first_test]
    pert = discover_and_evaluate_oos(X, _feature_sets(), y, fwd2, cfg)

    # fold 1: decision made before the perturbation period
    fid1 = base.fold_specs[0].fold_id
    b1 = base.folds[base.folds["fold_id"] == fid1].iloc[0]
    p1 = pert.folds[pert.folds["fold_id"] == fid1].iloc[0]
    assert int(b1["candidate_id"]) == int(p1["candidate_id"])
    assert b1["model_type"] == p1["model_type"]
    assert b1["selected_features"] == p1["selected_features"]
    assert b1["threshold"] == pytest.approx(p1["threshold"])
    te1 = base.fold_specs[0].test_idx
    np.testing.assert_array_equal(
        base.predictions.loc[te1, "prob"].to_numpy(),
        pert.predictions.loc[te1, "prob"].to_numpy())
    # ...while the scored P&L on the perturbed interval legitimately changes
    assert not np.allclose(base.oos_returns.loc[te1].to_numpy(),
                           pert.oos_returns.loc[te1].to_numpy())


def test_nested_discovery_mid_folds_unaffected_by_later_perturbation():
    """Perturbing from fold 2's test start onward must leave folds 1 AND 2
    (whose decisions precede that point) untouched."""
    X, y, fwd = _regime_stream()
    cfg = _discovery_cfg(X.index)
    base = discover_and_evaluate_oos(X, _feature_sets(), y, fwd, cfg)

    cut = base.fold_specs[1].test_idx[0]
    fwd2 = fwd.copy()
    fwd2.loc[fwd2.index >= cut] = -fwd2.loc[fwd2.index >= cut]
    pert = discover_and_evaluate_oos(X, _feature_sets(), y, fwd2, cfg)

    for k in (0, 1):
        fid = base.fold_specs[k].fold_id
        b = base.folds[base.folds["fold_id"] == fid].iloc[0]
        p = pert.folds[pert.folds["fold_id"] == fid].iloc[0]
        assert int(b["candidate_id"]) == int(p["candidate_id"])
        te = base.fold_specs[k].test_idx
        np.testing.assert_array_equal(
            base.predictions.loc[te, "prob"].to_numpy(),
            pert.predictions.loc[te, "prob"].to_numpy())


def test_nested_discovery_costs_reconcile_on_merged_ledger():
    """The per-fold chosen strategies run on ONE continuous ledger: boundary
    transitions are charged exactly once and fold turnover slices sum to the
    continuous total (A05 contract inherited by the A02 path)."""
    X, y, fwd = _regime_stream()
    cfg = _discovery_cfg(X.index)
    res = discover_and_evaluate_oos(X, _feature_sets(), y, fwd, cfg)
    pos = res.oos_positions
    ledger_turn = float(pos.diff().abs().sum()) + float(abs(pos.iat[0]))
    assert res.folds["oos_turnover"].sum() == pytest.approx(ledger_turn, abs=1e-9)
    assert res.fee_costs == pytest.approx(
        ledger_turn * cfg.execution.fee_bps / 1e4)
    assert res.slippage_costs == pytest.approx(
        ledger_turn * cfg.execution.slippage_bps / 1e4)


def test_nested_discovery_no_override_replay_is_cost_identical():
    """A discovery replay must preserve the merged boundary-cost ledger.

    This is the E08 acceptance criterion: a replay which changes nothing must
    reproduce positions, gross/net returns, and fees rather than reintroduce
    fold-local turnover accounting.
    """
    X, y, fwd = _regime_stream()
    cfg = _discovery_cfg(X.index)
    base = discover_and_evaluate_oos(X, _feature_sets(), y, fwd, cfg)
    replay = replay_oos(X, y, fwd, cfg, base, locked_test=None)

    pd.testing.assert_series_equal(replay.oos_positions, base.oos_positions)
    pd.testing.assert_series_equal(replay.oos_gross_returns,
                                  base.oos_gross_returns)
    pd.testing.assert_series_equal(replay.oos_returns, base.oos_returns)
    assert replay.fee_costs == pytest.approx(base.fee_costs, abs=1e-12)
    assert replay.slippage_costs == pytest.approx(base.slippage_costs,
                                                   abs=1e-12)
    assert replay.folds["oos_turnover"].sum() == pytest.approx(
        base.folds["oos_turnover"].sum(), abs=1e-12)


def test_nested_discovery_rejects_a_bad_lock_before_candidate_fits(monkeypatch):
    """A rejected locked layout must not consume a discovery candidate fit.

    This guards the actual E09 failure mode: verifying the lock after the
    global candidate-validation loop still exposed the supposedly protected
    test geometry to a costly search before eventually raising.
    """
    X, y, fwd = _regime_stream()
    cfg = _discovery_cfg(X.index)

    class RejectingLock:
        def __init__(self):
            self.calls = 0

        def verify(self, folds):
            self.calls += 1
            raise LockedTestViolation("test lock intentionally rejects layout")

    lock = RejectingLock()

    def candidate_fit_must_not_run(*args, **kwargs):
        raise AssertionError("candidate validation ran before locked-test verification")

    monkeypatch.setattr(
        "quant_research.strategies.discovery._validation_sharpe",
        candidate_fit_must_not_run,
    )
    with pytest.raises(LockedTestViolation, match="intentionally rejects"):
        discover_and_evaluate_oos(X, _feature_sets(), y, fwd, cfg,
                                  locked_test=lock)
    assert lock.calls == 1

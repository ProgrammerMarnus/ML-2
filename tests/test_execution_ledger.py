"""A04/A05/A09 regression tests: the engine executes ONE delayed close-to-close
contract, reconciles every fold to a continuous position/transaction ledger,
and preserves the candidate's immutable hold period through exact replay.

These tests use hand-calculated expectations, never golden outputs from the
previous implementation.  Before the fix, the following were all broken:

- A04: ``backtest`` scored the signal against the same-session close-to-close
  return instead of the documented forward interval ``close[t+1]/close[t]-1``.
- A05: each fold re-ran the backtest, so execution state (signal shift, hold,
  position) reset at fold boundaries, and each fold's first bar re-charged
  |position| as if it were a fresh entry (double-charged transitions and lost
  boundary exposure).
- A09: exact replay dropped the candidate's ``hold_bars`` (silently reverted to
  a one-bar hold).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import (AppConfig, DataConfig, EvaluationConfig,
                                   ExecutionConfig, ResearchConfig)
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.backtest import (EXECUTION_CONTRACT,
                                                INHERENT_MARKET_EXECUTION_LAG,
                                                _vol_target_scale, backtest)
from quant_research.evaluation.robustness import replay_oos
from quant_research.evaluation.walk_forward import LockedTestProtocol
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import run_walk_forward


def test_contract_is_delayed_close_to_close():
    """A04: gross[t] == position[t] * fwd[t] with fwd[t] = close[t+1]/close[t]-1,
    never the same-session return.  A hand-built overnight gap distinguishes
    the two contracts exactly one bar apart."""
    assert EXECUTION_CONTRACT == "delayed_close_to_close"
    idx = pd.bdate_range("2024-01-01", periods=30, freq="B").tz_localize("UTC")
    close = pd.Series(100.0 * (1.001 ** np.arange(30)), index=idx)
    # overnight +10% gap: close[25] = close[24] * 1.10
    close.iloc[25:] = close.iloc[25:] * 1.10
    fwd = close.shift(-1) / close - 1.0   # the interval the engine executes
    sess = close / close.shift(1) - 1.0   # same-session return (never used)
    sig = pd.Series(1.0, index=idx)                        # always long
    cfg = ExecutionConfig(target_vol=1.0, fee_bps=0.0, slippage_bps=0.0)
    bt_fwd = backtest(sig, fwd, cfg, risk_returns=sess)
    bt_sess = backtest(sig, sess, cfg, risk_returns=sess)
    # executed interval is the forward close-to-close return, bar-for-bar
    np.testing.assert_allclose(
        bt_fwd.gross_returns.to_numpy(),
        (bt_fwd.positions * fwd.fillna(0.0)).to_numpy(), rtol=0, atol=1e-12)
    # positions are warm after the vol window (scale clamps at 1 for small vol)
    assert bt_fwd.positions.iloc[24] == pytest.approx(1.0)
    # the +10% gap shows up at bar 24 under the forward contract...
    assert bt_fwd.gross_returns.iloc[24] == pytest.approx(1.10 * 1.001 - 1.0)
    # ...and only gains one day of drift under the same-session contract, so
    # the two contracts are economically different exactly one bar apart.
    assert bt_sess.gross_returns.iloc[24] == pytest.approx(0.001)
    assert bt_fwd.gross_returns.iloc[24] != pytest.approx(
        bt_sess.gross_returns.iloc[24])


def _noisy_perfect_classifier_stream(n=900, seed=11):
    """Deterministic alternating-forward-return stream with a nearly-noiseless
    feature (x ~= class label): mixed long/flat signals across the OOS path
    while the fold topology stays fully deterministic."""
    idx = pd.bdate_range("2016-01-01", periods=n, freq="B").tz_localize("UTC")
    rng = np.random.default_rng(seed)
    pattern = np.tile([0.002, -0.002], n // 2 + 1)[:n]
    pattern[-1] = 0.002   # keep the last label/return finite
    fwd = pd.Series(pattern, index=idx)
    y = (fwd > 0).astype(float)
    x = pd.DataFrame({
        "sig": y.to_numpy() + rng.normal(0.0, 0.01, n),
        "lag": np.roll(y.to_numpy(), 1) + rng.normal(0.0, 0.01, n),
    }, index=idx)
    return x, y, fwd


def _walk_cfg(idx, *, train, step):
    return AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start=str(idx[0].date()), end=str(idx[-1].date())),
        evaluation=EvaluationConfig(train_window=train, validation_window=50,
                                    test_window=50, step_bars=step,
                                    purge_bars=2, embargo_bars=2, expanding=True),
        research=ResearchConfig(threshold_candidates=[0.5], hold_candidates=[1],
                                placebo_runs=1, bootstrap_samples=20),
    )


def test_walk_forward_continuous_ledger_reconciles_fold_slices():
    """A05: the whole OOS path is ONE continuous position ledger; each fold row
    is a slice of that ledger.  The sum of per-fold turnover MUST equal the
    turnover of the continuous position path exactly (and fees/slippage scale
    with that single total).  Under the old per-fold backtest, each fold's
    first bar re-charged |position| as a fresh entry, so fold turnover summed
    to MORE than the continuous ledger total."""
    x, y, fwd = _noisy_perfect_classifier_stream()
    cfg = _walk_cfg(x.index, train=300, step=50)
    res = run_walk_forward(x, y, fwd, cfg)
    assert len(res.folds) >= 2
    pos = res.oos_positions
    pos_turn = float(pos.diff().abs().sum()) + float(abs(pos.iat[0]))
    fold_sum = float(res.folds["oos_turnover"].sum())
    assert fold_sum == pytest.approx(pos_turn, abs=1e-9)  # exact ledger slice
    # one continuous ledger: gross == position * forward return bar-for-bar
    np.testing.assert_allclose(
        res.oos_gross_returns.to_numpy(),
        (pos * fwd.loc[pos.index].fillna(0.0)).to_numpy(),
        rtol=0, atol=1e-12)
    # costs scale exactly with the SAME continuous turnover
    assert res.fee_costs == pytest.approx(
        pos_turn * cfg.execution.fee_bps / 1e4)
    assert res.slippage_costs == pytest.approx(
        pos_turn * cfg.execution.slippage_bps / 1e4)
    assert res.fee_costs + res.slippage_costs == pytest.approx(
        float((res.oos_gross_returns - res.oos_returns).sum()), abs=1e-9)
    # hand-derived identity: recompute positions from per-fold directions
    # shifted by the inherent market lag times the causal vol scale.  With no
    # per-fold restart, the engine's ledger must match this exactly.  This also
    # proves execution state (signal shift) carries across fold boundaries.
    thr_by_fold = dict(zip(res.folds["fold_id"], res.folds["threshold"]))
    thr_v = res.predictions["fold"].map(thr_by_fold).to_numpy()
    dir_full = pd.Series(
        np.where(res.predictions["prob"].to_numpy() > thr_v, 1.0, 0.0),
        index=res.predictions.index,
    )
    lag = INHERENT_MARKET_EXECUTION_LAG + int(cfg.execution.signal_delay_bars)
    scale = _vol_target_scale(fwd.shift(1), cfg.execution)
    scale = scale.reindex(dir_full.index).fillna(0.0)
    expected = (dir_full.shift(lag).fillna(0.0) * scale)
    expected = expected.clip(-cfg.execution.max_position,
                             cfg.execution.max_position).fillna(0.0)
    np.testing.assert_allclose(
        pos.to_numpy(), expected.to_numpy(), rtol=0, atol=1e-9,
        err_msg="OOS positions do not match the single continuous execution contract")
    for i in range(len(res.fold_specs) - 1):
        te2 = res.fold_specs[i + 1].test_idx
        assert te2[0] > res.fold_specs[i].test_idx[-1]   # adjacent, no overlap


def test_replay_oos_preserves_baseline_hold_bars():
    """A09: exact replay must re-run the candidate's immutable OOS spec,
    including the previously chosen ``hold_bars``.  A no-override replay must
    reproduce the baseline positions/gross bit-for-bit (a silent fallback to a
    one-bar hold changed 53 of 160 OOS positions in the audit demo)."""
    ohlcv = generate_synthetic_ohlcv(["SPY"], "2015-01-01", "2020-01-01", seed=42)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    cfg = _walk_cfg(feats.index, train=200, step=100)
    base = run_walk_forward(feats, y, fwd, cfg, hold_bars=5)
    assert base.hold_bars == 5
    rep = replay_oos(feats, y, fwd, cfg, base, LockedTestProtocol())
    assert rep.hold_bars == base.hold_bars == 5
    pd.testing.assert_series_equal(rep.oos_positions, base.oos_positions)
    pd.testing.assert_series_equal(rep.oos_gross_returns, base.oos_gross_returns)
    assert rep.fee_costs == pytest.approx(base.fee_costs)
    assert rep.slippage_costs == pytest.approx(base.slippage_costs)

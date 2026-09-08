"""V2.1.2 execution/delay audit: exact delay semantics on a deterministic toy
return series.

Proves, at the backtest level, that changing ``signal_delay_bars`` from 0 to d
changes ONLY signal execution timing:

    delayed_positions[t] == baseline_positions[t - d]

subject only to (a) the documented inherent execution lag (position for
session t uses the signal through t-1) and (b) the vol-target warmup (the
scale is anchored at t and undefined for the first VOL_LOOKBACK bars).
Session returns are NEVER realigned: every variant is evaluated against the
identical realized return series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import ExecutionConfig
from quant_research.evaluation.backtest import VOL_LOOKBACK, backtest

N = 260


def _toy_returns(n: int = N) -> pd.Series:
    """Deterministic, non-degenerate session returns (fixed pattern)."""
    pattern = np.array([0.01, -0.008, 0.004, 0.002, -0.012, 0.006, -0.003, 0.009,
                        -0.005, 0.001] * (n // 10 + 1))[:n]
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.Series(pattern, index=idx)


def _toy_signal(returns: pd.Series) -> pd.Series:
    """Deterministic binary signal derived causally from past returns only:
    long when yesterday's return was positive."""
    sig = (returns.shift(1) > 0).astype(float)
    sig.iloc[0] = 0.0
    return sig


def _flat_scale_cfg() -> ExecutionConfig:
    """Vol-target scale pinned at max_position (constant over the whole
    window), isolating pure signal-timing effects."""
    return ExecutionConfig(fee_bps=5.0, slippage_bps=1.0, signal_delay_bars=0,
                           target_vol=10.0, max_position=1.0)


@pytest.mark.parametrize("d", [1, 2, 3])
def test_positions_shift_exactly_by_d(d):
    """delayed_positions[t] == baseline_positions[t-d] (exact, toy series)."""
    rets = _toy_returns()
    sig = _toy_signal(rets)
    base = backtest(sig, rets, _flat_scale_cfg(), threshold=0.5)
    delayed = backtest(
        sig, rets,
        ExecutionConfig(fee_bps=5.0, slippage_bps=1.0, signal_delay_bars=d,
                        target_vol=10.0, max_position=1.0),
        threshold=0.5)
    pb = base.positions.to_numpy()
    pd_ = delayed.positions.to_numpy()
    # shift invariant once BOTH the signal shift and the vol-scale warmup have
    # passed: scale[t] == scale[t-d] == const only for t >= VOL_LOOKBACK + d
    start = VOL_LOOKBACK + d
    np.testing.assert_array_equal(pd_[start:], pb[start - d:len(pd_) - d])
    # documented signal warmup: the first INHERENT_LAG + d bars are flat
    assert (pd_[:1 + d] == 0.0).all()


def test_realized_returns_never_realigned():
    """Delaying the signal must not touch the return series: gross[t] is
    always position[t] * r[t] on the SAME r for every delay."""
    rets = _toy_returns()
    sig = _toy_signal(rets)
    gross = {}
    for d in (0, 1, 2):
        cfg = ExecutionConfig(fee_bps=0.0, slippage_bps=0.0, signal_delay_bars=d,
                              target_vol=10.0, max_position=1.0)
        bt = backtest(sig, rets, cfg, threshold=0.5)
        # exact identity: gross == position * realized session return
        np.testing.assert_allclose(
            bt.gross_returns.to_numpy(),
            (bt.positions * rets).to_numpy(), rtol=0, atol=1e-15)
        gross[d] = bt.gross_returns
    # the return observations themselves are identical across variants
    pd.testing.assert_index_equal(gross[0].index, gross[2].index)
    assert gross[0].index.equals(rets.index)


def test_delay_changes_only_timing_not_costs_per_turnover():
    """For fixed positions, fees/slippage scale exactly with turnover and
    gross is cost-invariant; net = gross - costs bar-for-bar."""
    rets = _toy_returns()
    sig = _toy_signal(rets)
    cfg0 = ExecutionConfig(fee_bps=0.0, slippage_bps=0.0, target_vol=10.0,
                           max_position=1.0)
    base = backtest(sig, rets, cfg0, threshold=0.5)
    for fee, slip in ((5.0, 1.0), (10.0, 2.5)):
        cfg = ExecutionConfig(fee_bps=fee, slippage_bps=slip, target_vol=10.0,
                              max_position=1.0)
        bt = backtest(sig, rets, cfg, threshold=0.5)
        # gross return invariant to costs (identical positions)
        np.testing.assert_array_equal(
            bt.gross_returns.to_numpy(), base.gross_returns.to_numpy())
        np.testing.assert_array_equal(
            bt.positions.to_numpy(), base.positions.to_numpy())
        turn = bt.turnover
        np.testing.assert_allclose(
            bt.metrics["fee_cost"], float(turn.sum()) * fee / 1e4,
            rtol=0, atol=1e-12)
        np.testing.assert_allclose(
            bt.metrics["slippage_cost"], float(turn.sum()) * slip / 1e4,
            rtol=0, atol=1e-12)
        np.testing.assert_allclose(
            bt.net_returns.to_numpy(),
            (bt.gross_returns - bt.costs).to_numpy(), rtol=0, atol=1e-15)


def test_delayed_signal_trades_older_information():
    """Semantics check: with delay d, position[t] follows the signal from
    bar t-1-d (inherent 1-bar lag + configured delay)."""
    rets = _toy_returns()
    sig = _toy_signal(rets)
    d = 2
    cfg = ExecutionConfig(fee_bps=0.0, slippage_bps=0.0, signal_delay_bars=d,
                          target_vol=10.0, max_position=1.0)
    bt = backtest(sig, rets, cfg, threshold=0.5)
    expected_dir = sig.shift(1 + d).fillna(0.0)  # signal through t-1-d
    # positions == expected direction wherever the vol scale is active (all
    # bars after VOL_LOOKBACK; scale is constant 1.0 for the toy series)
    active = slice(VOL_LOOKBACK + d, len(rets))
    np.testing.assert_array_equal(
        (bt.positions.to_numpy()[active] != 0).astype(float),
        expected_dir.to_numpy()[active])


def test_identity_predictions_threshold_folds_across_delays():
    """Delay stress consumes identical model inputs: same signal array, same
    thresholding, same index.  (Selection immutability across the battery is
    proven in test_robustness.py; here we pin the backtest-level contract.)"""
    rets = _toy_returns()
    sig = _toy_signal(rets)
    outs = []
    for d in (0, 1, 2, 3):
        cfg = ExecutionConfig(fee_bps=5.0, slippage_bps=1.0, signal_delay_bars=d,
                              target_vol=10.0, max_position=1.0)
        bt = backtest(sig, rets, cfg, threshold=0.5)
        outs.append(bt)
    # identical realized-return timeline
    for bt in outs[1:]:
        assert bt.net_returns.index.equals(outs[0].net_returns.index)
    # thresholding is a pure function of (signal, threshold): the raw binary
    # direction before shift is identical for all delays
    raw = (sig > 0.5).astype(float)
    for d, bt in enumerate(outs):
        start = VOL_LOOKBACK + d
        np.testing.assert_array_equal(
            (bt.positions.to_numpy()[start:] != 0).astype(float),
            raw.shift(1 + d).fillna(0.0).to_numpy()[start:])

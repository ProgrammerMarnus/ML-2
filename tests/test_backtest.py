"""Backtest correctness tests: no same-bar fill, fees, slippage, delay, bounds."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import ExecutionConfig
from quant_research.evaluation.backtest import backtest


@pytest.fixture()
def setup():
    idx = pd.bdate_range("2020-01-01", periods=300, freq="B").tz_localize("UTC")
    rng = np.random.default_rng(3)
    rets = pd.Series(rng.normal(0.0005, 0.01, len(idx)), index=idx)
    sig = pd.Series(rng.uniform(0.3, 0.7, len(idx)), index=idx)
    return idx, sig, rets


def test_no_same_bar_fill_leaky_signal_earns_nothing(setup):
    """A signal encoding the CURRENT session's return must not earn it:
    position for session t comes from the signal at t-1, so the leak is
    shifted out of reach and realized Sharpe must be near zero (vs huge)."""
    idx, _, rets = setup
    leaky_signal = rets * 100  # knows today's return
    leaky_signal = (leaky_signal - leaky_signal.min()) / (leaky_signal.max() - leaky_signal.min())
    cfg = ExecutionConfig(fee_bps=0.0, slippage_bps=0.0)
    bt = backtest(leaky_signal, rets, cfg)
    # position[t] uses signal[t-1]; correlation of pos with same-bar rets must be ~0
    corr = np.corrcoef(bt.positions.iloc[1:], rets.iloc[1:])[0, 1]
    assert abs(corr) < 0.2
    # whereas the KNOWING trader benchmark (pos = sign(today)) would have corr 1


def test_shifted_signal_cannot_create_hidden_lookahead(setup):
    """delay=1 must equal a pure one-bar forward shift of the delay=0
    positions (with constant returns the vol-target scale is constant,
    so positions shift exactly)."""
    idx, sig, rets = setup
    flat_rets = pd.Series(0.0005, index=idx)  # constant -> constant scale
    cfg0 = ExecutionConfig(fee_bps=0.0, slippage_bps=0.0, signal_delay_bars=0)
    cfg1 = ExecutionConfig(fee_bps=0.0, slippage_bps=0.0, signal_delay_bars=1)
    bt0 = backtest(sig, flat_rets, cfg0)
    bt1 = backtest(sig, flat_rets, cfg1)
    np.testing.assert_allclose(bt1.positions.to_numpy()[1:], bt0.positions.to_numpy()[:-1])


def test_fees_reduce_returns(setup):
    idx, sig, rets = setup
    clean = ExecutionConfig(fee_bps=0.0, slippage_bps=0.0)
    costly = ExecutionConfig(fee_bps=10.0, slippage_bps=0.0)
    bt_clean = backtest(sig, rets, clean, threshold=0.5)
    bt_cost = backtest(sig, rets, costly, threshold=0.5)
    assert bt_cost.metrics["total_return"] < bt_clean.metrics["total_return"]
    assert bt_cost.metrics["fee_cost"] > 0
    assert bt_cost.metrics["slippage_cost"] == 0


def test_slippage_charged_on_turnover(setup):
    idx, sig, rets = setup
    cfg = ExecutionConfig(fee_bps=0.0, slippage_bps=5.0)
    bt = backtest(sig, rets, cfg, threshold=0.5)
    expected = bt.turnover.sum() * 5.0 / 10000.0
    assert np.isclose(bt.metrics["slippage_cost"], expected)


def test_delay_stress_changes_result(setup):
    idx, sig, rets = setup
    cfg0 = ExecutionConfig(signal_delay_bars=0)
    cfg2 = ExecutionConfig(signal_delay_bars=2)
    bt0 = backtest(sig, rets, cfg0, threshold=0.5)
    bt2 = backtest(sig, rets, cfg2, threshold=0.5)
    assert not np.allclose(bt0.positions.to_numpy(), bt2.positions.to_numpy())


def test_position_bounded(setup):
    idx, sig, rets = setup
    cfg = ExecutionConfig(max_position=0.5)
    bt = backtest(sig, rets, cfg, threshold=0.4)
    assert bt.positions.abs().max() <= 0.5 + 1e-12


def test_turnover_and_trades_consistent(setup):
    idx, sig, rets = setup
    cfg = ExecutionConfig(fee_bps=1.0)
    bt = backtest(sig, rets, cfg, threshold=0.5)
    n_changes = int((bt.positions.diff().abs() > 1e-12).sum())
    assert bt.metrics["trade_count"] >= n_changes - 1  # includes initial position
    assert bt.metrics["total_turnover"] == pytest.approx(bt.turnover.sum())


def test_gross_net_and_cost_drag(setup):
    idx, sig, rets = setup
    cfg = ExecutionConfig(fee_bps=5.0, slippage_bps=1.0)
    bt = backtest(sig, rets, cfg, threshold=0.5)
    assert (bt.net_returns <= bt.gross_returns + 1e-12).all()
    assert bt.metrics["cost_drag"] > 0


def test_hold_bars_reduces_turnover(setup):
    idx, sig, rets = setup
    cfg = ExecutionConfig(fee_bps=1.0)
    bt1 = backtest(sig, rets, cfg, threshold=0.5, hold_bars=1)
    bt5 = backtest(sig, rets, cfg, threshold=0.5, hold_bars=5)
    assert bt5.metrics["total_turnover"] <= bt1.metrics["total_turnover"]

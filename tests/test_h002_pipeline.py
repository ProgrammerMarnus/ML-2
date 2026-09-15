"""H-002 real-data pipeline unit tests.

Covers the three components that turn the liquidity-reversal features into a
tradeable cross-sectional book:

  * ``_build_h002_composite_signal`` - cross-sectional z-score composite.
  * ``construct_h002_portfolio``     - decile legs, preregistered direction,
    position/sector caps, dollar neutrality and gross-leverage target.
  * ``portfolio_returns``            - delayed execution, turnover and costs.

Offline tests on synthetic panels: they exercise the mechanics, not market
evidence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.features.liquidity_reversal import compute_liquidity_features
from quant_research.h002_pipeline import (
    _build_h002_composite_signal,
    _cross_sectional_zscore,
)
from quant_research.portfolio.h002_portfolio import construct_h002_portfolio
from quant_research.portfolio.h002_returns import portfolio_returns


def _synthetic_features(n_days: int = 300, n_tickers: int = 40, seed: int = 7):
    """Daily OHLCV panels plus per-ticker liquidity feature frames."""
    idx = pd.bdate_range("2018-01-01", periods=n_days, freq="B", tz="UTC")
    rng = np.random.default_rng(seed)
    tickers = [f"S{i:02d}" for i in range(n_tickers)]
    close, volume, frames = {}, {}, {}
    for sym in tickers:
        c = pd.Series(100 * np.cumprod(1 + rng.normal(0.0, 0.012, n_days)), index=idx)
        v = pd.Series(1e6 * (1 + np.abs(rng.normal(0, 0.4, n_days))), index=idx)
        close[sym] = c
        volume[sym] = v
        frames[sym] = compute_liquidity_features(c * 1.01, c * 0.99, c, v)
    return idx, tickers, pd.DataFrame(close), pd.DataFrame(volume), frames


@pytest.fixture()
def panels():
    return _synthetic_features()


def _ramp_signal(n_names: int = 100, name: str = "S", width: int = 3) -> pd.DataFrame:
    """Single bar whose signals ascend 0..n-1, so ranks are unambiguous."""
    idx = pd.bdate_range("2020-01-01", periods=1, tz="UTC")
    names = [f"{name}{i:0{width}d}" for i in range(n_names)]
    return pd.DataFrame([np.arange(n_names, dtype=float)], index=idx, columns=names)


# ---------------------------------------------------------------------------
# Composite signal
# ---------------------------------------------------------------------------

def test_cross_sectional_zscore_is_standardised_per_row():
    panel = pd.DataFrame(
        np.arange(12, dtype=float).reshape(3, 4),
        index=pd.bdate_range("2020-01-01", periods=3, tz="UTC"),
    )
    z = _cross_sectional_zscore(panel)
    assert np.allclose(z.mean(axis=1), 0.0)
    assert np.allclose(z.std(axis=1), 1.0)


def test_composite_signal_shape_matches_panel(panels):
    idx, tickers, close, volume, frames = panels
    sig = _build_h002_composite_signal(frames, volume, tickers, close.index)
    assert sig.shape == (len(idx), len(tickers))
    assert list(sig.columns) == tickers
    assert sig.index.equals(close.index)


def test_composite_signal_is_cross_sectionally_centered(panels):
    idx, tickers, close, volume, frames = panels
    sig = _build_h002_composite_signal(frames, volume, tickers, close.index)
    row = sig.iloc[-1].dropna()
    assert len(row) == len(tickers)
    assert abs(float(row.mean())) < 1e-9


def test_composite_signal_ignores_unknown_symbols(panels):
    """A ticker without a feature frame must not appear in the composite."""
    idx, tickers, close, volume, frames = panels
    partial = {k: v for k, v in frames.items() if k != tickers[0]}
    sig = _build_h002_composite_signal(partial, volume, tickers, close.index)
    assert sig[tickers[0]].isna().all()


# ---------------------------------------------------------------------------
# Portfolio construction
# ---------------------------------------------------------------------------

#: Sector caps effectively disabled, for tests that isolate a single rule.
_NO_SECTOR_CAP = dict(max_sector_net_exposure=10.0, max_sector_gross_exposure=10.0)


def test_decile_legs_are_ten_percent_not_whole_universe():
    """A decile of 100 names is 10 long / 10 short, not 100 / 100."""
    signal = _ramp_signal(100)
    w = construct_h002_portfolio(signal, {}, min_members_per_day=20,
                                 **_NO_SECTOR_CAP)
    row = w.iloc[0]
    assert (row > 0).sum() == 10
    assert (row < 0).sum() == 10


def test_preregistered_direction_longs_low_signal():
    """H-002: high buying pressure reverses, so long low signal / short high."""
    signal = _ramp_signal(100)
    w = construct_h002_portfolio(signal, {}, min_members_per_day=20,
                                 long_low_signal=True, **_NO_SECTOR_CAP)
    row = w.iloc[0]
    assert row["S000"] > 0
    assert row["S099"] < 0


def test_inverted_direction_longs_high_signal():
    signal = _ramp_signal(100)
    w = construct_h002_portfolio(signal, {}, min_members_per_day=20,
                                 long_low_signal=False, **_NO_SECTOR_CAP)
    row = w.iloc[0]
    assert row["S099"] > 0
    assert row["S000"] < 0


def test_flat_when_cross_section_too_small():
    signal = _ramp_signal(10)
    w = construct_h002_portfolio(signal, {}, min_members_per_day=20)
    assert (w.iloc[0] == 0).all()


def test_dollar_neutral_after_caps():
    signal = _ramp_signal(100)
    w = construct_h002_portfolio(signal, {}, min_members_per_day=20,
                                 **_NO_SECTOR_CAP)
    row = w.iloc[0]
    assert abs(float(row[row > 0].sum() + row[row < 0].sum())) < 1e-12


def test_max_stock_weight_is_respected():
    signal = _ramp_signal(25)
    w = construct_h002_portfolio(signal, {}, min_members_per_day=20,
                                 max_stock_weight=0.02, **_NO_SECTOR_CAP)
    assert float(w.iloc[0].abs().max()) <= 0.02 + 1e-12


def test_gross_leverage_is_not_exceeded():
    """Realized gross exposure never exceeds the requested target."""
    signal = _ramp_signal(400, width=4)
    sectors = {n: f"SEC{i % 10}" for i, n in enumerate(signal.columns)}
    w = construct_h002_portfolio(signal, sectors, min_members_per_day=20,
                                 gross_leverage=1.0)
    assert float(w.iloc[0].abs().sum()) <= 1.0 + 1e-9


def test_gross_leverage_target_is_reachable_when_caps_do_not_bind():
    """With a generous position cap and spread sectors the book reaches 1.0x."""
    signal = _ramp_signal(400, width=4)
    sectors = {n: f"SEC{i % 10}" for i, n in enumerate(signal.columns)}
    w = construct_h002_portfolio(signal, sectors, min_members_per_day=20,
                                 max_stock_weight=10.0,
                                 max_sector_gross_exposure=10.0,
                                 max_sector_net_exposure=10.0,
                                 gross_leverage=1.0)
    row = w.iloc[0]
    assert float(row.abs().sum()) == pytest.approx(1.0, abs=1e-9)
    assert float(row[row > 0].sum()) == pytest.approx(0.5, abs=1e-9)
    assert float(row[row < 0].sum()) == pytest.approx(-0.5, abs=1e-9)


def test_sector_net_exposure_is_capped():
    """Sector imbalance is scaled to the 10% net cap (H-002 prereg 6.1)."""
    signal = _ramp_signal(100)
    # The 10 lowest signals (long leg) are Tech and the 10 highest (short leg)
    # are Energy, so both sectors start with a +-0.2 net before the cap.
    sectors = {n: ("Tech" if i < 50 else "Energy") for i, n in enumerate(signal.columns)}
    w = construct_h002_portfolio(signal, sectors, min_members_per_day=20,
                                 max_stock_weight=0.02,
                                 max_sector_net_exposure=0.10,
                                 max_sector_gross_exposure=10.0)
    net: dict = {}
    for ticker, weight in w.iloc[0].items():
        net[sectors[ticker]] = net.get(sectors[ticker], 0.0) + float(weight)
    assert all(abs(v) <= 0.10 + 1e-12 for v in net.values())


def test_sector_gross_exposure_is_capped():
    """Sector gross exposure is scaled to the 20% gross cap (H-002 prereg 6.1)."""
    signal = _ramp_signal(100)
    sectors = {n: "Tech" for n in signal.columns}
    w = construct_h002_portfolio(signal, sectors, min_members_per_day=20,
                                 max_stock_weight=0.02,
                                 max_sector_gross_exposure=0.20,
                                 max_sector_net_exposure=10.0)
    gross = float(w.iloc[0].abs().sum())
    assert gross <= 0.20 + 1e-12


# ---------------------------------------------------------------------------
# Portfolio returns, execution delay, turnover and costs
# ---------------------------------------------------------------------------

def test_returns_use_delayed_execution():
    """A weight set at close t earns t->t+1, never the t return itself."""
    idx = pd.bdate_range("2020-01-01", periods=3, tz="UTC")
    close = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=idx)
    weights = pd.DataFrame({"A": [1.0, 1.0, 0.0]}, index=idx)
    out = portfolio_returns(weights, close, fee_bps=0.0, slippage_bps=0.0)
    assert out["gross_returns"].iloc[0] == 0.0
    assert out["gross_returns"].iloc[1] == pytest.approx(0.10, abs=1e-12)
    assert out["gross_returns"].iloc[2] == 0.0


def test_costs_are_proportional_to_turnover():
    idx = pd.bdate_range("2020-01-01", periods=4, tz="UTC")
    close = pd.DataFrame({"A": [100.0, 100.0, 100.0, 100.0]}, index=idx)
    weights = pd.DataFrame({"A": [1.0, -1.0, -1.0, 1.0]}, index=idx)
    out = portfolio_returns(weights, close, fee_bps=10.0, slippage_bps=0.0)
    # Execution is lagged one bar, so entry (turnover 1.0) lands on bar 1 and
    # the +1 -> -1 flip (turnover 2.0) on bar 2.
    assert out["turnover"].iloc[0] == pytest.approx(0.0)
    assert out["turnover"].iloc[1] == pytest.approx(1.0)
    assert out["turnover"].iloc[2] == pytest.approx(2.0)
    assert out["turnover"].iloc[3] == pytest.approx(0.0)
    assert out["costs"].iloc[2] == pytest.approx(2.0 * 10.0 / 10000.0)


def test_net_equals_gross_minus_costs():
    idx, tickers, close, volume, frames = _synthetic_features(n_days=150, n_tickers=30)
    sig = _build_h002_composite_signal(frames, volume, tickers, close.index)
    w = construct_h002_portfolio(sig, {}, min_members_per_day=20)
    out = portfolio_returns(w, close, fee_bps=5.0, slippage_bps=2.0)
    diff = out["gross_returns"] - out["net_returns"]
    assert np.allclose(diff.values, out["costs"].values)


def test_zero_cost_when_flat():
    idx = pd.bdate_range("2020-01-01", periods=4, tz="UTC")
    close = pd.DataFrame({"A": [100.0, 101.0, 102.0, 103.0]}, index=idx)
    weights = pd.DataFrame({"A": [0.0, 0.0, 0.0, 0.0]}, index=idx)
    out = portfolio_returns(weights, close, fee_bps=5.0, slippage_bps=1.0)
    assert float(out["costs"].sum()) == 0.0
    assert float(out["gross_returns"].abs().sum()) == 0.0


def test_empty_weights_produce_zero_returns():
    idx = pd.bdate_range("2020-01-01", periods=5, tz="UTC")
    close = pd.DataFrame({"A": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)
    weights = pd.DataFrame({"A": np.zeros(5)}, index=idx)
    out = portfolio_returns(weights, close, fee_bps=5.0, slippage_bps=1.0)
    assert (out["net_returns"].abs() < 1e-15).all()


"""Portfolio construction and risk engine tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import ExecutionConfig
from quant_research.portfolio.construction import (
    apply_drawdown_control,
    apply_position_limits,
    apply_turnover_control,
    construct_portfolio,
    vol_target_weights,
)
from quant_research.portfolio.risk import (
    concentration_hhi,
    historical_cvar,
    historical_var,
    risk_report,
)


@pytest.fixture()
def signal_and_close(close_panel):
    signal = pd.Series(1.0, index=close_panel.index)
    return signal, close_panel


def test_vol_target_weights_causal_and_bounded(close_panel):
    rets = close_panel["SPY"] / close_panel["SPY"].shift(1) - 1
    vol = rets.rolling(20).std() * np.sqrt(252)
    w = vol_target_weights(pd.Series(1.0, index=vol.index), vol, 0.10, 1.0)
    assert w.abs().max() <= 1.0 + 1e-12
    # uses only t-1 vol: no NaN-shift leakage
    assert w.iloc[20] == w.iloc[20]


def test_position_limits_enforced():
    idx = pd.bdate_range("2020-01-01", periods=5, freq="B").tz_localize("UTC")
    w = pd.DataFrame({"A": [0.9] * 5, "B": [0.8] * 5}, index=idx)
    capped = apply_position_limits(w, max_asset_weight=0.4, max_gross_leverage=0.7)
    assert capped.abs().max().max() <= 0.4 + 1e-12
    assert (capped.abs().sum(axis=1) <= 0.7 + 1e-9).all()


def test_turnover_control_limits_daily_change():
    idx = pd.bdate_range("2020-01-01", periods=5, freq="B").tz_localize("UTC")
    w = pd.DataFrame({"A": [0.0, 1.0, 0.0, 1.0, 0.0]}, index=idx)
    controlled = apply_turnover_control(w, max_daily_turnover=0.2)
    deltas = controlled.diff().abs().sum(axis=1).dropna()
    assert (deltas <= 0.2 + 1e-9).all()


def test_drawdown_control_de_risks():
    rets = pd.Series([0.01] * 10 + [-0.03] * 20 + [0.01] * 10)
    w = pd.Series(1.0, index=rets.index)
    controlled = apply_drawdown_control(rets, w, dd_trigger=-0.10, dd_release=-0.04)
    assert controlled.iloc[:12].max() == 1.0  # before trigger
    assert (controlled.iloc[14:24] < 1.0).all()  # de-risked after drawdown


def test_construct_portfolio_traceable(signal_and_close):
    signal, close = signal_and_close
    out = construct_portfolio(signal, close, "SPY", ExecutionConfig())
    assert "assumptions" in out["trace"]
    assert out["trace"]["vol_target"] == 0.10
    assert out["weights"].abs().max() <= 1.0 + 1e-12


def test_var_cvar_and_risk_report(close_panel):
    rets = close_panel["SPY"] / close_panel["SPY"].shift(1) - 1
    rets = rets.dropna()
    var95 = historical_var(rets)
    cvar95 = historical_cvar(rets)
    assert cvar95 >= var95 >= 0
    report = risk_report(rets, weights=pd.Series(1.0, index=rets.index), benchmark=rets)
    for key in ("annualized_vol", "max_drawdown", "var_95_daily", "cvar_95_daily",
                "concentration_hhi", "annual_turnover", "beta_to_benchmark"):
        assert key in report
    # a single time-series is NOT a cross-sectional weight vector: HHI is None
    assert report["concentration_hhi"] is None
    # exposure/activity metrics are still reported from the time series
    assert report["avg_gross_exposure"] == pytest.approx(1.0)
    # a real weight MATRIX produces a proper cross-sectional HHI
    m = pd.DataFrame({c: np.ones(len(rets)) for c in ("A", "B")}, index=rets.index)
    m2 = risk_report(rets, weight_matrix=m)
    assert m2["concentration_hhi"] == pytest.approx(0.5)


def test_concentration_hhi():
    assert concentration_hhi(pd.Series([0.5, 0.5])) == pytest.approx(0.5)
    assert concentration_hhi(pd.Series([1.0])) == pytest.approx(1.0)


def test_risk_report_turnover_uses_engine_ledger_convention():
    """A14: ``annual_turnover`` must come from the ACTUAL position ledger with
    the engine's charged-turnover convention (first bar charges |position|), so
    a constant-hold series (all 1.0) has turnover 1.0 total, not 0."""
    idx = pd.bdate_range("2024-01-01", periods=5, freq="B").tz_localize("UTC")
    rets = pd.Series([0.0] * 5, index=idx)
    w = pd.Series([1.0] * 5, index=idx)
    r = risk_report(rets, weights=w)
    assert r["avg_gross_exposure"] == pytest.approx(1.0)
    assert r["annual_turnover"] == pytest.approx(1.0 / (5 / 252.0))


def test_drawdown_control_de_risks_after_initial_loss():
    """A15: the drawdown controller's high-water mark starts at initial capital,
    so a 20% first-bar loss de-risks the NEXT bar (causal one-bar shift), it
    does not leave the controller at full exposure."""
    rets = pd.Series([-0.20, 0.0, 0.0, 0.0])
    w = pd.Series(1.0, index=rets.index)
    controlled = apply_drawdown_control(rets, w, dd_trigger=-0.10,
                                        dd_release=-0.04, de_risked_weight=0.5)
    assert controlled.iloc[0] == pytest.approx(1.0)   # no prior obs at bar 0
    assert (controlled.iloc[1:] < 1.0).all()          # de-risked from bar 1 on

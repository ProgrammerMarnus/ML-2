"""Metrics correctness tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.evaluation.metrics import (
    annualized_volatility,
    beta,
    cagr,
    calmar_ratio,
    compute_metrics,
    hit_rate,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    tail_loss,
)


def test_sharpe_known_values():
    r = pd.Series([0.001] * 100)  # constant positive return
    expected = 0.001 / r.std(ddof=1) * np.sqrt(252)
    assert sharpe_ratio(r) == pytest.approx(expected, rel=1e-9)
    assert sharpe_ratio(pd.Series([0.0] * 10)) != sharpe_ratio(r)  # sd=0 handled


def test_max_drawdown_simple():
    r = pd.Series([0.10, -0.10, -0.10, 0.05])
    equity = (1 + r).cumprod()
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity.to_numpy()]))[1:]
    expected = float((equity.to_numpy() / peak - 1).min())
    assert max_drawdown(r) == pytest.approx(expected)


def test_max_drawdown_includes_initial_capital():
    """A15: a drawdown that starts before ANY peak must be counted.  The
    high-water mark begins at initial capital 1.0, not at the first
    post-return equity value."""
    r = pd.Series([-0.20, 0.0, 0.0])
    assert max_drawdown(r) == pytest.approx(-0.20)
    # a first-bar loss followed by recovery is still a -10% drawdown
    assert max_drawdown(pd.Series([-0.10, 0.10])) == pytest.approx(-0.10)


def test_cagr_reasonable():
    r = pd.Series([0.001] * 252)
    assert 0.2 < cagr(r) < 0.4


def test_calmar_uses_abs_drawdown():
    r = pd.Series([0.02, -0.05, 0.02, 0.02])
    assert calmar_ratio(r) == pytest.approx(cagr(r) / abs(max_drawdown(r)))


def test_sortino_uses_downside_only():
    up = pd.Series([0.01] * 50)
    assert np.isnan(sortino_ratio(up))  # no downside -> undefined, not faked


def test_sortino_uses_full_sample_downside_deviation():
    """A22: the denominator is the all-observation zero-target downside
    deviation, not the dispersion of the losses alone.  Audit reproduction:
    [0.03, -0.01, 0.03, -0.01] must give 22.449944 (the old loss-only std
    returned NaN because equal losses have zero dispersion)."""
    r = pd.Series([0.03, -0.01, 0.03, -0.01])
    mean = r.mean()
    dd = float(np.sqrt(np.mean(np.minimum(r.to_numpy(), 0.0) ** 2)))
    assert sortino_ratio(r) == pytest.approx(mean / dd * np.sqrt(252))
    assert sortino_ratio(r) == pytest.approx(22.449944, rel=1e-6)


def test_sortino_edge_cases():
    # repeated equal losses: defined (old code returned NaN)
    assert sortino_ratio(pd.Series([0.01, -0.01, 0.01, -0.01])) == pytest.approx(0.0)
    # a single loss: computed from the full-sample downside deviation
    r1 = pd.Series([0.02, -0.01])
    dd1 = float(np.sqrt(0.01 ** 2 / 2))
    assert sortino_ratio(r1) == pytest.approx(0.005 / dd1 * np.sqrt(252))
    # no losses -> undefined, not faked
    assert np.isnan(sortino_ratio(pd.Series([0.01] * 50)))
    # all losses -> defined and negative
    assert sortino_ratio(pd.Series([-0.01, -0.01])) == pytest.approx(-np.sqrt(252))


def test_hit_rate_excludes_flat():
    r = pd.Series([0.01, -0.01, 0.0, 0.02])
    assert hit_rate(r) == pytest.approx(2 / 3)


def test_tail_loss_is_mean_of_worst_tail():
    r = pd.Series([-0.10, -0.05, 0.0, 0.01, 0.02] * 10)
    q = r.quantile(0.05)
    assert tail_loss(r) == pytest.approx(r[r <= q].mean())


def test_beta_against_benchmark():
    idx = pd.bdate_range("2020-01-01", periods=200, freq="B").tz_localize("UTC")
    rng = np.random.default_rng(2)
    bench = pd.Series(rng.normal(0.0004, 0.01, len(idx)), index=idx)
    strat = 1.5 * bench + pd.Series(rng.normal(0, 0.002, len(idx)), index=idx)
    assert beta(strat, bench) == pytest.approx(1.5, abs=0.15)


def test_compute_metrics_distinguishes_gross_net():
    idx = pd.date_range("2020-01-01", periods=100, freq="D", tz="UTC")
    gross = pd.Series(0.001, index=idx)
    net = pd.Series(0.0007, index=idx)
    m = compute_metrics(net, gross_returns=gross)
    assert m["gross_return"] > m["net_return"]
    assert m["cost_drag"] == pytest.approx(m["gross_return"] - m["net_return"])


def test_compute_metrics_includes_position_stats():
    idx = pd.date_range("2020-01-01", periods=100, freq="D", tz="UTC")
    rets = pd.Series(0.001, index=idx)
    pos = pd.Series(1.0, index=idx)
    pos.iloc[::10] = 0.0
    m = compute_metrics(rets, positions=pos)
    assert m["turnover_annual"] > 0
    assert 0 <= m["avg_exposure"] <= 1

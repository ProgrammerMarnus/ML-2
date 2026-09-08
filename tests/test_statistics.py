"""Statistics tests: bootstrap/placebo determinism, multiple-testing, PBO."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.evaluation.bootstrap import bootstrap_sharpe
from quant_research.evaluation.multiple_testing import (
    benjamini_hochberg,
    bonferroni,
    deflated_sharpe_pvalue,
    expected_max_sharpe,
    holm,
)
from quant_research.evaluation.overfitting import (
    probability_of_backtest_overfitting,
    robustness_score,
)
from quant_research.evaluation.placebo import placebo_statistics, run_placebo_null


@pytest.fixture()
def returns():
    idx = pd.bdate_range("2020-01-01", periods=500, freq="B").tz_localize("UTC")
    rng = np.random.default_rng(5)
    return pd.Series(rng.normal(0.0006, 0.01, len(idx)), index=idx)


def test_bootstrap_deterministic(returns):
    b1 = bootstrap_sharpe(returns, n_samples=200, seed=42)
    b2 = bootstrap_sharpe(returns, n_samples=200, seed=42)
    assert b1 == b2
    b3 = bootstrap_sharpe(returns, n_samples=200, seed=43)
    assert b1["mean"] != b3["mean"]


def test_bootstrap_interval_brackets_observed(returns):
    b = bootstrap_sharpe(returns, n_samples=300, seed=42)
    assert b["lo"] <= b["observed"] <= b["hi"]
    assert 0 <= b["positive_prob"] <= 1


def test_bonferroni_bounds_family():
    adj = bonferroni([0.01, 0.04, 0.5])
    assert adj[0] == pytest.approx(0.03)
    assert adj[1] == pytest.approx(0.12)
    assert all(a <= 1.0 for a in adj)
    assert all(a >= p for a, p in zip(adj, [0.01, 0.04, 0.5]))


def test_benjamini_hochberg_monotone_and_sorted():
    p = [0.001, 0.008, 0.039, 0.041, 0.2]
    adj = benjamini_hochberg(p)
    assert all(a >= q for a, q in zip(adj, p))
    assert adj == sorted(adj)


def test_holm_never_smaller_than_input():
    p = [0.01, 0.02, 0.03]
    adj = holm(p)
    assert all(a >= q for a, q in zip(adj, p))


def test_expected_max_sharpe_grows_with_trials():
    e10 = expected_max_sharpe(10, 1000)
    e100 = expected_max_sharpe(100, 1000)
    assert e100 > e10 > 0


def test_deflated_sharpe_significant_strategy():
    # a large observed Sharpe over long history remains significant
    p = deflated_sharpe_pvalue(2.0, n_trials=100, n_obs=2000)
    assert p < 0.05
    # a marginal Sharpe after many trials does not
    p2 = deflated_sharpe_pvalue(0.3, n_trials=1000, n_obs=500)
    assert p2 > 0.05


def _stub_pipeline(mean):
    def pipeline(X, y, fwd):
        return {"mean_oos_sharpe": mean, "median_oos_sharpe": mean}
    return pipeline


def test_placebo_null_deterministic():
    idx = pd.bdate_range("2020-01-01", periods=300, freq="B").tz_localize("UTC")
    rng = np.random.default_rng(9)
    X = pd.DataFrame(rng.normal(size=(len(idx), 3)), index=idx)
    y = pd.Series(rng.integers(0, 2, len(idx)), index=idx).astype(float)
    fwd = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx)
    n1 = run_placebo_null(X, y, fwd, _stub_pipeline(0.1), n_runs=4, seed=42)
    n2 = run_placebo_null(X, y, fwd, _stub_pipeline(0.1), n_runs=4, seed=42)
    pd.testing.assert_frame_equal(n1, n2)


def test_placebo_statistics_percentile_and_adjusted_p():
    null = pd.DataFrame({"mean_oos_sharpe": np.linspace(0.0, 1.0, 21)})
    stats_ = placebo_statistics(0.5, null)
    assert stats_["percentile"] == pytest.approx(10 / 21)
    assert stats_["adjusted_p"] == pytest.approx((1 + 11) / 22)
    better = placebo_statistics(2.0, null)
    assert better["adjusted_p"] == pytest.approx(1 / 22)


def test_placebo_rejects_invalid_mode():
    with pytest.raises(ValueError, match="mode"):
        run_placebo_null(None, None, None, _stub_pipeline(0), n_runs=2, mode="bogus")


def test_pbo_detects_overfit_variants():
    rng = np.random.default_rng(1)
    # 20 variants: variant 0 great IS, terrible OOS (classic overfit)
    is_perf = rng.normal(0, 0.1, (20, 8))
    is_perf[0] += 1.0  # best in every fold
    matrix = pd.DataFrame(is_perf)
    matrix.iloc[0] = -0.5  # but worst OOS
    res = probability_of_backtest_overfitting(matrix)
    assert res["pbo"] > 0.5


def test_robustness_score_components():
    good = robustness_score(True, True, 1.0, 0.9, 0.99, 0.1)
    bad = robustness_score(False, False, 0.0, 0.1, 0.05, 0.9)
    assert good["robustness_score"] > bad["robustness_score"]
    assert 0 <= bad["robustness_score"] <= 1

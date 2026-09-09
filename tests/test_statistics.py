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


def test_expected_max_sharpe_units_are_period_not_annualized():
    """A17: the output is in PERIOD (daily) units, not annualized.  Audit
    anchor: (50 trials, 1000 obs) -> 0.072019 daily == 1.143267 annualized."""
    em = expected_max_sharpe(50, 1000)
    assert em == pytest.approx(0.072019, abs=1e-3)
    assert em * np.sqrt(252) == pytest.approx(1.143267, abs=5e-3)


def test_expected_max_sharpe_accepts_cross_trial_variance():
    """A17: the null benchmark must accept the cross-trial Sharpe-variance
    estimate instead of assuming V = 1/(n-1).  E[max SR] scales with sqrt(V)."""
    base = expected_max_sharpe(50, 1000)
    doubled = expected_max_sharpe(50, 1000, sharpe_variance=4.0 / 999)
    assert doubled == pytest.approx(2.0 * base, rel=1e-12)


def test_deflated_sharpe_significant_strategy():
    # a large observed Sharpe over long history remains significant
    p = deflated_sharpe_pvalue(2.0, n_trials=100, n_obs=2000)
    assert p < 0.05
    # a marginal Sharpe after many trials does not
    p2 = deflated_sharpe_pvalue(0.3, n_trials=1000, n_obs=500)
    assert p2 > 0.05


def test_deflated_sharpe_published_denominator_audit_case():
    """A17: the PSR denominator is the published probabilistic-Sharpe term
    sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) (Bailey & Lopez de Prado 2014,
    eq. 2) -- it scales with the ESTIMATED Sharpe, not fixed 1/3 and 1/24
    constants.  Audit reproduction: annual SR 1.5, 1,000 observations, 50
    trials, skew -3, kurtosis 10 -> p = 0.266938 with the published
    denominator (the old fixed-constant denominator gave ~0.3195)."""
    from scipy import stats as sps

    sr = 1.5 / np.sqrt(252)  # per-period Sharpe
    v = 1.0 / 999  # benchmark variance held at the module's assumption
    sr0 = expected_max_sharpe(50, 1000, sharpe_variance=v)
    denom = np.sqrt(1.0 - (-3.0) * sr + (10.0 - 1) / 4.0 * sr ** 2)
    expected = float(1.0 - sps.norm.cdf(np.sqrt(999) * (sr - sr0) / denom))
    p = deflated_sharpe_pvalue(1.5, n_trials=50, n_obs=1000, skew=-3.0,
                               kurtosis=10.0, sharpe_variance=v)
    assert p == pytest.approx(expected, rel=1e-12)
    assert abs(p - 0.266938) < 0.01  # audit anchor
    assert p < 0.30  # the old wrong denominator produced ~0.3195


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


def test_pbo_two_variant_audit_case_flags_all_splits():
    """A16: with 2 variants and 8 folds the old fold-count threshold (4) made
    flagging impossible -- max variant rank 1 < 4 -- so the audit's opposite-
    variant construction returned PBO = 0.0 while the direct rank calculation
    returns 1.0.  The rank is now taken against the STRATEGY distribution."""
    # opposite variants (v1 = -v0) with zero total sum and no zero-sum
    # 4-subsets: in EVERY split the IS winner is the OOS loser -> PBO = 1.0
    # (rows = strategy variants, columns = folds)
    m = pd.DataFrame([[3.0, 3.0, 3.0, -4.0, -4.0, 1.0, -1.0, -1.0],
                      [-3.0, -3.0, -3.0, 4.0, 4.0, -1.0, 1.0, 1.0]])
    res = probability_of_backtest_overfitting(m, max_combinations=70)
    assert res["pbo"] == pytest.approx(1.0)
    assert res["n_splits"] == 70


def test_pbo_balanced_variants_never_flag():
    # the IS winner is also the OOS winner in every split -> PBO = 0
    m = pd.DataFrame([[3.0] * 8, [4.0] * 8])
    res = probability_of_backtest_overfitting(m, max_combinations=70)
    assert res["pbo"] == pytest.approx(0.0)


def test_pbo_many_strategies_few_folds_bounded():
    """A16: with 20 variants and only 2 OOS folds the old fold-count
    threshold (1) flagged nearly every split of a pure-noise family,
    inflating PBO toward 1.  The variant-axis relative rank keeps the null
    family's PBO bounded in [0, 1] and finite."""
    rng = np.random.default_rng(1)
    m = pd.DataFrame(rng.normal(0, 0.1, (20, 4)))
    res = probability_of_backtest_overfitting(m, max_combinations=6)
    assert np.isfinite(res["pbo"])
    assert 0.0 <= res["pbo"] <= 1.0
    assert res["n_splits"] == 6


def test_pbo_rejects_non_finite_observations():
    """A16: PBO requires a finite Sharpe observation for every variant/fold;
    silent NaN handling would bias the rank statistic."""
    m = pd.DataFrame([[1.0, np.nan, 1.0, 1.0],
                      [0.0, 0.0, 0.0, 0.0]])  # rows = variants, cols = folds
    with pytest.raises(ValueError, match="non-finite"):
        probability_of_backtest_overfitting(m)


def test_robustness_score_components():
    good = robustness_score(True, True, 1.0, 0.9, 0.99, 0.1)
    bad = robustness_score(False, False, 0.0, 0.1, 0.05, 0.9)
    assert good["robustness_score"] > bad["robustness_score"]
    assert 0 <= bad["robustness_score"] <= 1

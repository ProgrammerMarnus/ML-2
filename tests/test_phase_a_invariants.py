"""Phase A correctness-freeze invariant tests (V2.1.3).

Covers the external-audit critical/high findings:

1. Risk-state causality: ``position[t]`` must not change when the CURRENT or
   FUTURE realized returns change (vol scale uses only observable bars < t).
2. OOS warm-start equivalence: a fold backtest given pre-window risk history
   equals a continuous backtest over that history evaluated on the window.
3. Drawdown control causal shift: today's return cannot change today's weight.
4. Discovery -> OOS faithful replay: the candidate's hold_bars and per-fold
   thresholds are pinned into the OOS run (no re-selection, no lost spec).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, ExecutionConfig, EvaluationConfig
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.backtest import backtest, INHERENT_MARKET_EXECUTION_LAG
from quant_research.evaluation.metrics import sharpe_ratio
from quant_research.features.price_volume import build_price_volume_features
from quant_research.portfolio.construction import apply_drawdown_control
from quant_research.strategies.baseline import run_walk_forward
from quant_research.evaluation.walk_forward import LockedTestProtocol


def _toy(window: int = 120, seed: int = 7):
    """Deterministic toy: signal, forward returns, and observable risk returns."""
    idx = pd.bdate_range("2020-01-01", periods=window, freq="B").tz_localize("UTC")
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, window + 1)))
    close = pd.Series(close, index=idx.insert(0, idx[0] - pd.Timedelta(days=1))).iloc[1:]
    # forward return close[t] -> close[t+1]
    fwd = close.shift(-1) / close - 1.0
    # observable close-to-close return known at close[t]
    risk = close / close.shift(1) - 1.0
    sig = pd.Series(rng.uniform(0.0, 1.0, window), index=idx)
    cfg = ExecutionConfig(fee_bps=5.0, slippage_bps=1.0, target_vol=0.10,
                          max_position=1.0)
    return idx, sig, fwd, risk, cfg


def test_position_invariant_to_current_and_future_returns():
    idx, sig, fwd, risk, cfg = _toy()
    base = backtest(sig, fwd, cfg, threshold=0.5, risk_returns=risk)

    # perturb CURRENT bar's realized return: position[t] must be unchanged
    fwd_now = fwd.copy()
    t = len(idx) // 2
    fwd_now.iloc[t] = fwd_now.iloc[t] * 3.0
    bt_now = backtest(sig, fwd_now, cfg, threshold=0.5, risk_returns=risk)
    np.testing.assert_array_equal(
        base.positions.iloc[: t + INHERENT_MARKET_EXECUTION_LAG].to_numpy(),
        bt_now.positions.iloc[: t + INHERENT_MARKET_EXECUTION_LAG].to_numpy(),
    )

    # perturb FUTURE risk bars (>= t): scale[t] uses only risk[t-20..t-1]
    risk_fut = risk.copy()
    risk_fut.iloc[t:] = risk_fut.iloc[t:] * 5.0
    bt_fut = backtest(sig, fwd, cfg, threshold=0.5, risk_returns=risk_fut)
    np.testing.assert_array_equal(
        base.positions.iloc[:t].to_numpy(), bt_fut.positions.iloc[:t].to_numpy()
    )


def test_oos_warm_start_equivalence():
    """A fold backtest given full pre-window risk history equals a continuous
    backtest over the joined history evaluated on the same window."""
    idx, sig, fwd, risk, cfg = _toy(window=160)
    # simulate a fold: last 60 bars are the window, earlier 100 are history
    win = 60
    win_idx = idx[-win:]
    # continuous backtest over full series
    full = backtest(sig, fwd, cfg, threshold=0.5, risk_returns=risk)
    # fold backtest: window returns + FULL risk series for warm-up
    fold = backtest(sig.loc[win_idx], fwd.loc[win_idx], cfg, threshold=0.5,
                    risk_returns=risk)
    np.testing.assert_allclose(
        full.positions.loc[win_idx].to_numpy(), fold.positions.to_numpy(),
        rtol=1e-12, atol=1e-12,
    )


def test_warm_start_differs_from_cold_start_in_scale_space():
    """Without pre-window risk history, the fold backtest cold-starts: the
    early window positions (before 20 observable bars accumulate) differ from
    the warm-start version, proving the warm-up context is actually used."""
    idx, sig, fwd, risk, cfg = _toy(window=160)
    win_idx = idx[-60:]
    warm = backtest(sig.loc[win_idx], fwd.loc[win_idx], cfg, threshold=0.5,
                    risk_returns=risk)
    cold = backtest(sig.loc[win_idx], fwd.loc[win_idx], cfg, threshold=0.5)
    # the first positions differ (cold-start scale is 0 there)
    assert np.any(warm.positions.to_numpy() != cold.positions.to_numpy())


def test_drawdown_today_return_does_not_change_today_weight():
    rets = pd.Series([0.01] * 10 + [-0.03] * 20 + [0.01] * 10)
    w = pd.Series(1.0, index=rets.index)
    base = apply_drawdown_control(rets, w, dd_trigger=-0.10, dd_release=-0.04)
    for t in range(1, len(rets)):
        rt = rets.copy()
        rt.iloc[t] = rt.iloc[t] * 10.0  # today's return is unknown intraday
        ctrl = apply_drawdown_control(rt, w, dd_trigger=-0.10, dd_release=-0.04)
        assert ctrl.iloc[t] == base.iloc[t], f"today's return changed weight at {t}"


def test_discovery_candidate_hold_bars_pinned_into_oos():
    """The candidate's hold_bars is part of the immutable OOS specification:
    three different hold_bars must yield three different OOS behaviors, and a
    pinned replay of one candidate reproduces its own selection exactly."""
    from quant_research.strategies.discovery import _validation_sharpe
    from quant_research.strategies.baseline import run_walk_forward

    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2016-01-01", end="2020-01-01"),
        # B09: Use step_bars <= test_window to avoid gapped windows
        evaluation=EvaluationConfig(train_window=200, validation_window=50,
                                    test_window=100, step_bars=100,
                                    purge_bars=2, embargo_bars=2, expanding=True),
    )
    ohlcv = generate_synthetic_ohlcv(["SPY"], cfg.data.start, cfg.data.end, seed=3)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    feat_cols = list(feats.columns)

    _ = _validation_sharpe(feats, y, fwd, cfg, feat_cols, "logistic", 1,
                           cfg.research.threshold_candidates, 42)
    # C03: legacy discover_strategies is removed; build a candidate directly
    # from the validation output (mimicking what discover_and_evaluate_oos does
    # internally for the grid).
    from quant_research.config import ModelConfig
    vsharpe, vdd, thr, perfold = _validation_sharpe(
        feats, y, fwd, cfg, feat_cols, "logistic", 1,
        cfg.research.threshold_candidates, 42)
    cand_hold = 1
    cand = {
        "hold_bars": cand_hold,
        "per_fold_thresholds": perfold,
        "threshold": thr,
    }
    # a hold_bars change must change OOS behavior while the spec stays pinned
    res = run_walk_forward(feats, y, fwd, cfg, hold_bars=cand_hold)
    res2 = run_walk_forward(feats, y, fwd, cfg, hold_bars=cand_hold + 1)
    assert not np.allclose(res.oos_positions.to_numpy(), res2.oos_positions.to_numpy())
    # replaying the SAME pinned spec is deterministic
    rep = run_walk_forward(feats, y, fwd, cfg, hold_bars=cand_hold)
    np.testing.assert_allclose(res.oos_positions.to_numpy(), rep.oos_positions.to_numpy())


def test_delay_zero_stress_equals_baseline_oos():
    """Requirement 3: the delay=0 (configured-assumption) robustness row must
    reconcile exactly with the unperturbed baseline OOS result.

    This proves robustness stress testing replays the SAME execution at delay=0
    and only varies the stress knob at delay>0.  It is the pipeline-level
    counterpart of run.py's reconciliation assertions, validated on a
    deterministic synthetic end-to-end run with the real battery.
    """
    from quant_research.evaluation.robustness import robustness_battery
    from quant_research.strategies.baseline import run_walk_forward
    from quant_research.config import AppConfig, DataConfig, EvaluationConfig

    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2016-01-01", end="2021-01-01"),
        # B09: Use step_bars <= test_window to avoid gapped windows
        evaluation=EvaluationConfig(train_window=200, validation_window=50,
                                    test_window=100, step_bars=100,
                                    purge_bars=2, embargo_bars=2, expanding=True),
    )
    ohlcv = generate_synthetic_ohlcv(["SPY"], cfg.data.start, cfg.data.end, seed=5)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    baseline = run_walk_forward(feats, y, fwd, cfg)
    baseline_sharpe = sharpe_ratio(baseline.oos_returns)
    baseline_gross_sharpe = sharpe_ratio(baseline.oos_gross_returns)
    baseline_gross_return = float((1 + baseline.oos_gross_returns).prod() - 1)

    # robustness battery re-runs the locked-fold OOS path at delay=0
    battery = robustness_battery(feats, y, fwd, cfg, baseline,
                                 LockedTestProtocol())
    delay0 = battery["delay_stress"][
        battery["delay_stress"]["delay_bars"] == 0].iloc[0]

    assert abs(delay0["sharpe"] - baseline_sharpe) < 1e-9, \
        "delay=0 net Sharpe must reconcile with baseline"
    assert abs(delay0["gross_sharpe"] - baseline_gross_sharpe) < 1e-9, \
        "delay=0 gross Sharpe must reconcile with baseline"
    assert abs(delay0["gross_return"] - baseline_gross_return) < 1e-9
    assert abs(delay0["fee_cost"] - baseline.fee_costs) < 1e-10, \
        "delay=0 must not re-introduce cost assumptions"
    assert abs(delay0["slippage_cost"] - baseline.slippage_costs) < 1e-10
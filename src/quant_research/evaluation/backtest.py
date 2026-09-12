"""Causal backtester with ONE explicit execution contract.

The engine executes *delayed close-to-close* and nothing else.  Concretely,
with ``fwd[t] = close[t+1] / close[t] - 1`` a demonstrably-measurable return
interval, and ``dir[t]`` = thresholded decision from data through close t:

    execution_lag            = INHERENT_MARKET_EXECUTION_LAG + signal_delay_bars
    position[t]              = direction(signal[t - execution_lag]) * vol_target_scale[t]
    gross[t]                 = position[t] * fwd[t]        (earned close[t] -> close[t+1])

So a signal computed from data through close t is NEVER traded in session t
(no same-bar fill) and earns the interval ``close[t+lag] -> close[t+lag+1]``.
This is the documented execution contract of the engine and of every score it
produces:

- ``fwd[k]`` is the forward/next-close return ``close[k+1]/close[k]-1``; it is
  NOT the same-session close-to-close return.  Labels (``y[k]``) predict its
  sign and are therefore aligned to the same interval.
- Open prices are never used; intraday/overnight execution detail is not
  modeled.  For a next-open fill contract this backtester would have to take
  open-adjacent prices as input -- it does not, by design.
- ``signal_delay_bars`` (config) adds further latency on top of the inherent
  one-bar lag, modeling slower data/decision arrival.  Delaying the signal
  shifts ONLY the direction series; the realized return series is never
  reindexed and the vol-target scale stays anchored at t.
- vol_target_scale uses only trailing observable returns through t-1, so it
  is REAL-TIME observable at t and is therefore NOT shifted with the delay.
- Costs (fee + slippage, bps) are charged on |position change| (turnover),
  derived from one continuous position ledger.  Any position change between
  two adjacent bars -- including across a walk-forward fold boundary -- is
  charged exactly once, and no position silently appears or disappears.

Delay-shift invariant (verified in tests/test_delay_invariants.py):

    positions_with_delay_d[t] == positions_with_delay_0[t - d]

holds exactly whenever the vol-target scale is constant over the compared
window (the toy tests force this); with time-varying scale the DIRECTION
series shifts exactly by d while the scale stays anchored at t (documented
convention, not a realignment of the return series -- the return series is
never shifted or reindexed by the delay).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..config import ExecutionConfig
from .metrics import compute_metrics

VOL_LOOKBACK = 20
INHERENT_MARKET_EXECUTION_LAG = 1
EXECUTION_CONTRACT = "delayed_close_to_close"


@dataclass
class BacktestResult:
    net_returns: pd.Series
    gross_returns: pd.Series
    positions: pd.Series
    turnover: pd.Series
    costs: pd.Series
    metrics: dict


def _vol_target_scale(returns: pd.Series, cfg: ExecutionConfig) -> pd.Series:
    """Causal vol targeting: trailing std through t-1 only.

    ``returns[k]`` MUST be a return known at close[k] (an observable
    close-to-close return).  The rolling window is then shifted by one so that
    ``scale[t]`` uses ``returns[t-20 .. t-1]`` -- all known at the decision
    time for position[t].  Passing forward returns here would peek at window
    ``t-1 -> t`` (not realised until close[t]) and must never happen.
    """
    vol = returns.rolling(VOL_LOOKBACK, min_periods=VOL_LOOKBACK).std().shift(1) * np.sqrt(252.0)
    scale = (cfg.target_vol / vol.replace(0.0, np.nan)).clip(upper=cfg.max_position)
    return scale


def backtest(
    signal: pd.Series,
    fwd_returns: pd.Series,
    cfg: ExecutionConfig,
    threshold: float | None = None,
    hold_bars: int = 1,
    risk_returns: pd.Series | None = None,
) -> BacktestResult:
    """Simulate the strategy under the DELAYED CLOSE-TO-CLOSE contract.

    Parameters
    ----------
    signal : probabilities/positions indexed by bar t (data through t close).
    fwd_returns : realized forward return of the contract interval,
        ``fwd[t] = close[t+1]/close[t] - 1`` (NOT the same-session
        close-to-close return).  ``gross[t] == position[t] * fwd[t]``.
    threshold : probability threshold; long when signal > threshold, else flat.
    hold_bars : minimum holding period between position changes.
    risk_returns : (optional) observable close-to-close return series for risk
        scaling, ``risk[k] = close[k]/close[k-1] - 1`` known at close k,
        aligned to a FULL index that includes the evaluation window AND enough
        pre-window history for the rolling vol window to warm up.  When
        omitted it defaults to ``fwd_returns`` (backward compatible for
        toy/unit tests); the production walk-forward always passes an
        explicitly observable series so the first evaluation bars are not an
        artificial cold start.

    Position causality: ``position[t]`` depends only on ``signal[t-lag]`` and
    ``scale[t]`` where ``scale[t]`` uses ``risk_returns[t-20 .. t-1]``.  It is
    therefore invariant to ``fwd_returns[t]`` and to ``risk_returns[t:]``.
    """
    if cfg.signal_delay_bars < 0:
        raise ValueError("signal_delay_bars cannot be negative")
    idx = fwd_returns.index
    if not idx.is_unique:
        raise ValueError("fwd_returns index must be unique (no overlapping bars)")
    # E21: missing/non-finite realized returns are rejected at the public
    # boundary.  The engine must never silently zero an infinite print (a
    # fabricated or broken feed) into an infinite/net-zero P&L bar, nor
    # silently flatten exposure through a NaN bar without telling the caller.
    vals = pd.to_numeric(fwd_returns, errors="coerce").to_numpy(dtype=float)
    bad = ~np.isfinite(vals)
    if bool(bad.any()):
        bad_pos = np.flatnonzero(bad).tolist()
        kinds = sorted({("inf" if np.isinf(vals[i]) else "nan") for i in bad_pos})
        raise ValueError(
            f"fwd_returns has non-finite values ({'/'.join(kinds)}) at "
            f"position(s) {bad_pos[:8]} of {len(vals)}; clean the return feed "
            f"before backtesting")
    sig = signal.reindex(idx).astype("float64")

    # execution_lag = inherent market execution lag + configured signal delay.
    # Delaying the signal shifts ONLY the direction series; the return series
    # is never realigned and the vol-target scale stays anchored at t.
    lag = INHERENT_MARKET_EXECUTION_LAG + int(cfg.signal_delay_bars)
    if threshold is None:
        raw = sig
    else:
        raw = pd.Series(np.where(sig > threshold, 1.0, 0.0), index=idx)

    # apply holding period: position changes require `hold_bars` sessions apart
    shifted = raw.shift(lag)
    if hold_bars > 1:
        desired = shifted.fillna(0.0).to_numpy()
        current = 0.0
        bars_since_change = hold_bars
        staged_vals = np.empty(len(desired))
        for i, v in enumerate(desired):
            bars_since_change += 1
            if v != current and bars_since_change >= hold_bars:
                current = v
                bars_since_change = 0
            staged_vals[i] = current
        staged = pd.Series(staged_vals, index=idx)
    else:
        staged = shifted

    # Vol-target scale is computed from the OBSERVABLE risk-return series (full
    # history passed in) so the window has warm-up context; it is then aligned
    # to the evaluation index and the scale at t uses only bars t-20..t-1.
    if risk_returns is not None:
        scale_full = _vol_target_scale(risk_returns, cfg)
        scale = scale_full.reindex(idx).fillna(0.0)
    else:
        scale = _vol_target_scale(fwd_returns, cfg).reindex(idx).fillna(0.0)
    position = (staged * scale).clip(-cfg.max_position, cfg.max_position).fillna(0.0)

    gross = position * fwd_returns.fillna(0.0)
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(position.iloc[0])
    total_cost_bps = cfg.fee_bps + cfg.slippage_bps
    costs = turnover * total_cost_bps / 10000.0
    fee_costs = turnover * cfg.fee_bps / 10000.0
    slip_costs = turnover * cfg.slippage_bps / 10000.0
    net = gross - costs

    metrics = compute_metrics(net, gross_returns=gross, positions=position)
    metrics["trade_count"] = int((turnover > 1e-9).sum())
    metrics["total_turnover"] = float(turnover.sum())
    metrics["fee_cost"] = float(fee_costs.sum())
    metrics["slippage_cost"] = float(slip_costs.sum())
    metrics["total_cost"] = float(costs.sum())
    return BacktestResult(
        net_returns=net,
        gross_returns=gross,
        positions=position,
        turnover=turnover,
        costs=costs,
        metrics=metrics,
    )

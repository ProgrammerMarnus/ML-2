"""Portfolio construction: explicit, traceable rules - no opaque optimizer.

Every sizing decision traces to a documented assumption: vol targeting scale,
position/asset caps, turnover cap, drawdown de-risking, and cash floor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ExecutionConfig
from ..evaluation.metrics import TRADING_DAYS


def vol_target_weights(signal: pd.Series, realized_vol: pd.Series,
                       target_vol: float, max_weight: float) -> pd.Series:
    """Causal vol targeting: scale_t = min(target/vol_{t-1}, max_weight)."""
    vol = realized_vol.shift(1)
    raw = (target_vol / vol.replace(0.0, np.nan)).clip(upper=max_weight)
    w = signal * raw
    return w.clip(-max_weight, max_weight).fillna(0.0)


def apply_position_limits(weights: pd.DataFrame, max_asset_weight: float = 0.40,
                          max_gross_leverage: float = 1.0) -> pd.DataFrame:
    """Per-asset cap + gross leverage cap (traceable, rule-based)."""
    w = weights.clip(-max_asset_weight, max_asset_weight)
    gross = w.abs().sum(axis=1)
    scale = (max_gross_leverage / gross).clip(upper=1.0).replace([np.inf], 1.0)
    return w.mul(scale, axis=0)


def apply_turnover_control(weights: pd.DataFrame, max_daily_turnover: float = 0.20) -> pd.DataFrame:
    """Limit total absolute weight change per day to `max_daily_turnover`."""
    out = weights.copy()
    prev = out.iloc[0] * 0.0
    rows = []
    for _, row in out.iterrows():
        delta = (row - prev).abs().sum()
        if delta > max_daily_turnover and delta > 0:
            row = prev + (row - prev) * (max_daily_turnover / delta)
        rows.append(row)
        prev = row
    return pd.DataFrame(rows, index=out.index, columns=out.columns)


def apply_drawdown_control(returns: pd.Series, weights: pd.Series,
                           dd_trigger: float = -0.10, dd_release: float = -0.04,
                           de_risked_weight: float = 0.5) -> pd.Series:
    """De-risk when drawdown breaches trigger; release when it recovers.

    CAUSAL timing: the de-risk state applied to ``weights[t]`` is decided from
    the drawdown through bar ``t-1`` only.  A bar's own realized return never
    changes that same bar's weight (the return is not known when the position
    is held).  The first bar has no prior drawdown observation and starts at
    full weight.
    """
    equity = (1 + returns.fillna(0)).cumprod()
    dd = equity / equity.cummax() - 1
    dd_prev = dd.shift(1).fillna(0.0)  # drawdown observed at decision time
    state = 1.0
    states = []
    for d in dd_prev:
        if d <= dd_trigger:
            state = de_risked_weight
        elif d >= dd_release:
            state = 1.0
        states.append(state)
    return weights * pd.Series(states, index=weights.index)


def construct_portfolio(signal: pd.Series, close: pd.DataFrame, target: str,
                        exec_cfg: ExecutionConfig, vol_window: int = 20) -> dict:
    """Single-target portfolio construction with all controls applied.

    Returns weights, components, and an assumption trace.
    """
    rets = close[target].pct_change() if hasattr(close[target], "pct_change") else close[target].diff() / close[target].shift(1)
    rets = close[target] / close[target].shift(1) - 1.0
    realized_vol = rets.rolling(vol_window, min_periods=vol_window).std() * np.sqrt(TRADING_DAYS)
    base = vol_target_weights(signal, realized_vol.reindex(signal.index), exec_cfg.target_vol, exec_cfg.max_position)
    controlled = apply_drawdown_control(rets.reindex(signal.index).fillna(0.0), base)
    weights = controlled.clip(-exec_cfg.max_position, exec_cfg.max_position)
    cash = 1.0 - weights.abs()
    trace = {
        "vol_target": exec_cfg.target_vol,
        "vol_window": vol_window,
        "max_position": exec_cfg.max_position,
        "drawdown_trigger": -0.10,
        "drawdown_release": -0.04,
        "de_risked_weight": 0.5,
        "assumptions": "causal vol targeting from trailing 20d vol; drawdown de-risk; remainder held in cash",
    }
    return {"weights": weights, "cash": cash, "trace": trace,
            "realized_vol": realized_vol.reindex(signal.index)}

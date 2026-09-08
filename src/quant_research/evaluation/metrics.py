"""Standardized performance metrics.

Gross -> costs -> slippage -> net is always distinguished.  A result is never
called "net" unless actual configured costs/slippage were applied.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252.0


def _clean(returns: pd.Series) -> pd.Series:
    r = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    return r


def annualized_volatility(returns: pd.Series) -> float:
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))


def sharpe_ratio(returns: pd.Series) -> float:
    r = _clean(returns)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS))


def sortino_ratio(returns: pd.Series) -> float:
    r = _clean(returns)
    downside = r[r < 0]
    if len(r) < 2 or downside.std(ddof=1) == 0 or len(downside) == 0:
        return float("nan")
    return float(r.mean() / downside.std(ddof=1) * np.sqrt(TRADING_DAYS))


def max_drawdown(returns: pd.Series) -> float:
    r = _clean(returns)
    if len(r) == 0:
        return float("nan")
    # High-water mark starts from INITIAL capital (1.0), so a loss before the
    # first peak is counted: returns [-0.20, 0, 0] must report -0.20, not 0.
    equity = (1.0 + r).cumprod()
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity.to_numpy()]))[1:]
    dd = equity / pd.Series(peak, index=equity.index) - 1.0
    return float(dd.min())


def cagr(returns: pd.Series) -> float:
    r = _clean(returns)
    if len(r) == 0:
        return float("nan")
    equity = float((1.0 + r).prod())
    if equity <= 0:
        return -1.0
    years = len(r) / TRADING_DAYS
    return float(equity ** (1.0 / years) - 1.0)


def calmar_ratio(returns: pd.Series) -> float:
    mdd = max_drawdown(returns)
    if not np.isfinite(mdd) or mdd == 0:
        return float("nan")
    return float(cagr(returns) / abs(mdd))


def hit_rate(returns: pd.Series) -> float:
    r = _clean(returns)
    active = r[r != 0]
    if len(active) == 0:
        return float("nan")
    return float((active > 0).mean())


def tail_loss(returns: pd.Series, q: float = 0.05) -> float:
    """Conditional value at risk (mean of worst q-quantile returns)."""
    r = _clean(returns)
    if len(r) == 0:
        return float("nan")
    cutoff = r.quantile(q)
    tail = r[r <= cutoff]
    return float(tail.mean()) if len(tail) else float("nan")


def beta(returns: pd.Series, benchmark: pd.Series) -> float:
    r = _clean(returns)
    b = _clean(benchmark)
    common = r.index.intersection(b.index)
    if len(common) < 2:
        return float("nan")
    x = b.loc[common]
    y = r.loc[common]
    var = x.var(ddof=1)
    if var == 0:
        return float("nan")
    return float(np.cov(y, x, ddof=1)[0, 1] / var)


def compute_metrics(
    net_returns: pd.Series,
    gross_returns: pd.Series | None = None,
    positions: pd.Series | None = None,
    benchmark: pd.Series | None = None,
) -> dict:
    """Full metric block for one strategy return stream."""
    net = _clean(net_returns)
    m = {
        "sharpe": sharpe_ratio(net),
        "sortino": sortino_ratio(net),
        "cagr": cagr(net),
        "calmar": calmar_ratio(net),
        "max_dd": max_drawdown(net),
        "ann_vol": annualized_volatility(net),
        "hit_rate": hit_rate(net),
        "tail_loss_5pct": tail_loss(net),
        "total_return": float((1.0 + net).prod() - 1.0) if len(net) else float("nan"),
    }
    if benchmark is not None:
        m["beta"] = beta(net, benchmark)
    if positions is not None:
        pos = _clean(positions)
        if len(pos) > 1:
            turnover = pos.diff().abs()
            m["turnover_annual"] = float(turnover.sum() / max(len(pos) / TRADING_DAYS, 1e-9))
            m["avg_exposure"] = float(pos.abs().mean())
    if gross_returns is not None:
        gross = _clean(gross_returns)
        net_ret = float((1.0 + net).prod() - 1.0)
        gross_ret = float((1.0 + gross).prod() - 1.0)
        m["gross_return"] = gross_ret
        m["net_return"] = net_ret
        m["cost_drag"] = gross_ret - net_ret
    return m

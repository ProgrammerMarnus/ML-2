"""H-002 portfolio return computation.

Computes portfolio returns, turnover, and costs from a weight matrix and
close price panel.  Uses the delayed close-to-close execution contract:
signal at close t earns the return from close t to close t+1.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def portfolio_returns(
    weights: pd.DataFrame,
    close_panel: pd.DataFrame,
    fee_bps: float = 5.0,
    slippage_bps: float = 1.0,
) -> Dict:
    """Compute portfolio returns, turnover, and costs from a weight matrix.

    Parameters
    ----------
    weights : pd.DataFrame
        Rows = timestamps, columns = tickers, weights at decision time (close t).
    close_panel : pd.DataFrame
        Rows = timestamps, columns = tickers, adjusted close prices.
    fee_bps, slippage_bps : float
        Cost parameters in basis points.

    Returns
    -------
    Dict with:
        gross_returns : pd.Series - gross portfolio return per day
        net_returns : pd.Series - net portfolio return per day (after costs)
        turnover : pd.Series - daily turnover (sum of |weight change|)
        costs : pd.Series - daily total costs
        weight_matrix : pd.DataFrame - the executed weight matrix (lagged)
    """
    # Lag weights by 1 day (delayed execution)
    exec_weights = weights.shift(1).fillna(0.0)

    # Align to common index and columns
    common_idx = weights.index.intersection(close_panel.index)
    common_cols = weights.columns.intersection(close_panel.columns)
    w = exec_weights.loc[common_idx, common_cols]
    cp = close_panel.loc[common_idx, common_cols]

    # Forward returns: close[t+1]/close[t] - 1
    fwd_ret = cp.shift(-1) / cp - 1.0

    # Portfolio gross return
    gross = (w * fwd_ret).sum(axis=1)

    # Turnover: sum of |weight change| per day
    turnover = w.diff().abs().sum(axis=1)
    turnover.iloc[0] = w.iloc[0].abs().sum()  # entry on first day

    fee_costs = turnover * fee_bps / 10000.0
    slippage_costs = turnover * slippage_bps / 10000.0
    costs = fee_costs + slippage_costs

    net = gross - costs

    return {
        "gross_returns": gross.fillna(0.0),
        "net_returns": net.fillna(0.0),
        "turnover": turnover,
        "costs": costs,
        "fee_costs": fee_costs,
        "slippage_costs": slippage_costs,
        "weight_matrix": w,
    }

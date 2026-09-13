"""Independent performance-metric cross-checks for regression tests.

Fincore never generates promotion metrics. It is an optional oracle that can
catch accidental semantic drift in the engine's transparent implementation.
"""

from __future__ import annotations

import math

import pandas as pd

from .metrics import annualized_volatility, beta, max_drawdown, sharpe_ratio


def compare_with_fincore(returns: pd.Series, benchmark: pd.Series | None = None,
                         atol: float = 1e-10) -> dict:
    """Return comparison details or raise when Fincore disagrees with engine metrics."""
    try:
        from fincore import empyrical as oracle
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("metric-oracle support requires the [metric-oracle] extra (fincore)") from exc
    local = {
        "sharpe": sharpe_ratio(returns),
        "annual_volatility": annualized_volatility(returns),
        "max_drawdown": max_drawdown(returns),
    }
    external = {
        "sharpe": float(oracle.sharpe_ratio(returns, annualization=252)),
        "annual_volatility": float(oracle.annual_volatility(returns, annualization=252)),
        "max_drawdown": float(oracle.max_drawdown(returns)),
    }
    if benchmark is not None:
        local["beta"] = beta(returns, benchmark)
        external["beta"] = float(oracle.beta(returns, benchmark))
    mismatches = {
        key: {"engine": local[key], "fincore": external[key]}
        for key in local
        if not (math.isnan(local[key]) and math.isnan(external[key]))
        and not math.isclose(local[key], external[key], abs_tol=atol, rel_tol=atol)
    }
    if mismatches:
        raise AssertionError(f"metric-oracle mismatch: {mismatches}")
    return {"engine": local, "fincore": external, "atol": atol}

"""H-003-R1 weekly multi-asset portfolio construction.

The original H-003 preregistration called for a VIX-futures curve and a true
equal-risk-contribution allocator.  H-003-R1 is a separate amended family that
uses only repository-sourceable adjusted ETF closes and VIX spot.  It uses a
deterministic inverse-volatility risk budget; this module must never be cited
as an implementation of the original H-003 contract.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


H003_R1_PORTFOLIO_PARAMS = {
    "rebalance_weekday": 2,  # Wednesday
    "vol_lookback": 60,
    "target_vol": 0.10,
    "gross_leverage": 0.50,
    "max_asset_weight": 0.15,
    "max_class_gross": 0.40,
    "max_equity_net": 0.20,
    "min_assets": 12,
    "vix_stand_down": 80.0,
}


def _cap_and_normalize(
    weights: pd.Series,
    asset_classes: Mapping[str, str],
    gross_leverage: float,
    max_asset_weight: float,
    max_class_gross: float,
    max_equity_net: float,
) -> pd.Series:
    """Apply hard portfolio limits without re-grossing after a cap binds."""
    w = weights.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)
    gross = float(w.abs().sum())
    if gross <= 0:
        return w * 0.0
    w *= gross_leverage / gross
    w = w.clip(-max_asset_weight, max_asset_weight)

    classes = pd.Series({s: asset_classes.get(s, "unknown") for s in w.index})
    for class_name in sorted(classes.unique()):
        members = classes.index[classes.eq(class_name)]
        class_gross = float(w.loc[members].abs().sum())
        if class_gross > max_class_gross:
            w.loc[members] *= max_class_gross / class_gross

    equity = classes.index[classes.eq("equity")]
    equity_net = float(w.loc[equity].sum()) if len(equity) else 0.0
    if abs(equity_net) > max_equity_net:
        # Scaling the whole equity sleeve preserves its relative risk budget and
        # direction while guaranteeing the hard net-equity limit.
        w.loc[equity] *= max_equity_net / abs(equity_net)
    return w


def construct_h003_portfolio(
    signal: pd.DataFrame,
    close: pd.DataFrame,
    asset_classes: Mapping[str, str],
    vix: pd.Series | None = None,
    *,
    rebalance_weekday: int = 2,
    vol_lookback: int = 60,
    target_vol: float = 0.10,
    gross_leverage: float = 0.50,
    max_asset_weight: float = 0.15,
    max_class_gross: float = 0.40,
    max_equity_net: float = 0.20,
    min_assets: int = 12,
    vix_stand_down: float = 80.0,
) -> pd.DataFrame:
    """Construct Wednesday-rebalanced signed inverse-volatility weights.

    Signal and volatility observed at close ``t`` form target weights at close
    ``t``.  Return accounting applies the mandatory one-session execution lag.
    Missing Wednesdays (exchange holidays) are deliberately not substituted by
    another weekday: the previous book is held until the next valid Wednesday.
    """
    if signal.index.tz is None or close.index.tz is None:
        raise ValueError("H-003 signal and close indexes must be timezone-aware")
    common_idx = signal.index.intersection(close.index).sort_values()
    common_cols = signal.columns.intersection(close.columns)
    sig = signal.loc[common_idx, common_cols]
    cp = close.loc[common_idx, common_cols]
    returns = cp.pct_change(fill_method=None)
    trailing_vol = returns.rolling(vol_lookback, min_periods=vol_lookback).std() * np.sqrt(252.0)
    trailing_cov = returns.rolling(vol_lookback, min_periods=vol_lookback).cov()

    targets = pd.DataFrame(np.nan, index=common_idx, columns=common_cols, dtype=float)
    for ts in common_idx[common_idx.weekday == rebalance_weekday]:
        row = sig.loc[ts].replace([np.inf, -np.inf], np.nan).dropna()
        vols = trailing_vol.loc[ts].reindex(row.index).replace(0.0, np.nan).dropna()
        row = row.reindex(vols.index).dropna()
        if len(row) < min_assets:
            targets.loc[ts] = 0.0
            continue
        if vix is not None:
            vix_value = vix.reindex(common_idx).loc[ts]
            if pd.notna(vix_value) and float(vix_value) > vix_stand_down:
                targets.loc[ts] = 0.0
                continue

        # The amended signal is an expected-return direction.  Magnitude is
        # intentionally ignored so no post-hoc score scaling can tune exposure.
        direction = np.sign(row).replace(0.0, np.nan).dropna()
        inv_vol = 1.0 / vols.reindex(direction.index)
        raw = direction * inv_vol
        w = _cap_and_normalize(
            raw, asset_classes, gross_leverage, max_asset_weight,
            max_class_gross, max_equity_net,
        )

        # Ex-ante volatility is computed from the trailing covariance available
        # at t.  Scale down only; never lever above the frozen 0.5 gross cap.
        try:
            cov_t = trailing_cov.loc[ts].loc[w.index, w.index]
            variance = float(w.to_numpy() @ cov_t.to_numpy() @ w.to_numpy())
            predicted_vol = np.sqrt(max(variance, 0.0) * 252.0)
        except (KeyError, ValueError):
            predicted_vol = float("nan")
        if np.isfinite(predicted_vol) and predicted_vol > target_vol:
            w *= target_vol / predicted_vol
        targets.loc[ts] = w.reindex(common_cols).fillna(0.0)

    # Prior to the first valid Wednesday the strategy is flat.  Thereafter the
    # target book is held, including across non-Wednesday missing-signal days.
    return targets.ffill().fillna(0.0)


def validate_h003_limits(
    weights: pd.DataFrame,
    asset_classes: Mapping[str, str],
    *,
    max_asset_weight: float = 0.15,
    max_class_gross: float = 0.40,
    max_equity_net: float = 0.20,
    gross_leverage: float = 0.50,
    atol: float = 1e-10,
) -> dict:
    """Return auditable hard-limit checks for a target-weight matrix."""
    classes = pd.Series({s: asset_classes.get(s, "unknown") for s in weights.columns})
    class_gross = {
        name: weights.loc[:, classes.index[classes.eq(name)]].abs().sum(axis=1)
        for name in sorted(classes.unique())
    }
    equity = classes.index[classes.eq("equity")]
    equity_net = weights.loc[:, equity].sum(axis=1) if len(equity) else pd.Series(0.0, index=weights.index)
    return {
        "max_abs_weight": float(weights.abs().max().max()),
        "max_gross": float(weights.abs().sum(axis=1).max()),
        "max_class_gross": float(max((v.max() for v in class_gross.values()), default=0.0)),
        "max_abs_equity_net": float(equity_net.abs().max()),
        "passed": bool(
            weights.abs().max().max() <= max_asset_weight + atol
            and weights.abs().sum(axis=1).max() <= gross_leverage + atol
            and max((v.max() for v in class_gross.values()), default=0.0) <= max_class_gross + atol
            and equity_net.abs().max() <= max_equity_net + atol
        ),
    }

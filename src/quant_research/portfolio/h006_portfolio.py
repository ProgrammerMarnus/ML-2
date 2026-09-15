"""H-006 weekly cross-sectional factor mean-reversion portfolio.

The constructor implements the frozen H-006 rules directly: Wednesday-close
decisions, signal-magnitude/inverse-volatility sizing, hard asset/class/gross/
net caps, a 10% portfolio volatility ceiling, the VIX>75 gross reduction, and
the predeclared turnover scaling rule. Return attribution is handled by the
shared portfolio return ledger, which applies the mandatory one-session lag.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


H006_PORTFOLIO_PARAMS = {
    "rebalance_weekday": 2,  # Wednesday
    "vol_lookback": 60,
    "position_target_vol": 0.08,
    "portfolio_target_vol": 0.10,
    "gross_leverage_cap": 1.0,
    "net_exposure_cap": 0.40,
    "max_asset_weight": 0.12,
    "min_assets": 12,
    "vix_threshold": 75.0,
    "vix_gross_cap": 0.30,
    "max_missing_20": 5,
    "turnover_annual_cap": 8.0,
    "turnover_scale": 0.70,
}

H006_CLASS_GROSS_CAPS = {
    "us_equity": 0.50,
    "international_equity": 0.30,
    "fixed_income": 0.40,
    "commodity": 0.20,
}


def _apply_hard_limits(
    weights: pd.Series,
    asset_classes: Mapping[str, str],
    class_gross_caps: Mapping[str, float],
    *,
    gross_leverage_cap: float,
    net_exposure_cap: float,
    max_asset_weight: float,
) -> pd.Series:
    """Apply conservative caps without re-grossing after any cap binds."""
    w = weights.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)
    w = w.clip(-max_asset_weight, max_asset_weight)

    for class_name, class_cap in class_gross_caps.items():
        members = [s for s in w.index if asset_classes.get(s) == class_name]
        if not members:
            continue
        class_gross = float(w.loc[members].abs().sum())
        if class_gross > class_cap:
            w.loc[members] *= class_cap / class_gross

    gross = float(w.abs().sum())
    if gross > gross_leverage_cap:
        w *= gross_leverage_cap / gross

    net = float(w.sum())
    if abs(net) > net_exposure_cap:
        # Scaling the entire book is conservative and preserves every relative
        # signal/risk allocation while guaranteeing the hard total-net cap.
        w *= net_exposure_cap / abs(net)
    return w


def construct_h006_portfolio(
    signal: pd.DataFrame,
    close: pd.DataFrame,
    asset_classes: Mapping[str, str],
    vix: pd.Series,
    *,
    class_gross_caps: Mapping[str, float] = H006_CLASS_GROSS_CAPS,
    rebalance_weekday: int = 2,
    vol_lookback: int = 60,
    position_target_vol: float = 0.08,
    portfolio_target_vol: float = 0.10,
    gross_leverage_cap: float = 1.0,
    net_exposure_cap: float = 0.40,
    max_asset_weight: float = 0.12,
    min_assets: int = 12,
    vix_threshold: float = 75.0,
    vix_gross_cap: float = 0.30,
    max_missing_20: int = 5,
    turnover_annual_cap: float = 8.0,
    turnover_scale: float = 0.70,
) -> pd.DataFrame:
    """Construct the frozen H-006 Wednesday-close target-weight matrix."""
    if signal.index.tz is None or close.index.tz is None or vix.index.tz is None:
        raise ValueError("H-006 signal, close, and VIX indexes must be timezone-aware")
    common_idx = signal.index.intersection(close.index).sort_values()
    common_cols = signal.columns.intersection(close.columns)
    sig = signal.loc[common_idx, common_cols]
    cp = close.loc[common_idx, common_cols]
    vix_aligned = vix.reindex(common_idx)

    returns = cp.pct_change(fill_method=None)
    trailing_vol = returns.rolling(
        vol_lookback, min_periods=vol_lookback
    ).std() * np.sqrt(252.0)
    trailing_cov = returns.rolling(
        vol_lookback, min_periods=vol_lookback
    ).cov()
    missing_20 = cp.isna().rolling(20, min_periods=1).sum()

    targets = pd.DataFrame(np.nan, index=common_idx, columns=common_cols, dtype=float)
    previous = pd.Series(0.0, index=common_cols, dtype=float)
    for ts in common_idx[common_idx.weekday == rebalance_weekday]:
        row = sig.loc[ts].replace([np.inf, -np.inf], np.nan)
        eligible = row.notna() & trailing_vol.loc[ts].notna()
        eligible &= missing_20.loc[ts].le(max_missing_20)
        valid = row.index[eligible]
        if len(valid) < min_assets:
            targets.loc[ts] = 0.0
            previous = targets.loc[ts].copy()
            continue

        vols = trailing_vol.loc[ts, valid].replace(0.0, np.nan).dropna()
        scores = row.reindex(vols.index).dropna()
        raw = scores * (position_target_vol / vols.reindex(scores.index))
        w = _apply_hard_limits(
            raw, asset_classes, class_gross_caps,
            gross_leverage_cap=gross_leverage_cap,
            net_exposure_cap=net_exposure_cap,
            max_asset_weight=max_asset_weight,
        )

        try:
            cov_t = trailing_cov.loc[ts].loc[w.index, w.index]
            variance = float(w.to_numpy() @ cov_t.to_numpy() @ w.to_numpy())
            predicted_vol = np.sqrt(max(variance, 0.0) * 252.0)
        except (KeyError, ValueError):
            predicted_vol = float("nan")
        if np.isfinite(predicted_vol) and predicted_vol > portfolio_target_vol:
            w *= portfolio_target_vol / predicted_vol

        vix_value = vix_aligned.loc[ts]
        if pd.notna(vix_value) and float(vix_value) > vix_threshold:
            gross = float(w.abs().sum())
            if gross > vix_gross_cap:
                w *= vix_gross_cap / gross

        proposed = w.reindex(common_cols).fillna(0.0)
        annual_one_way = 0.5 * float((proposed - previous).abs().sum()) * 52.0
        if annual_one_way > turnover_annual_cap:
            proposed *= turnover_scale
        targets.loc[ts] = proposed
        previous = proposed.copy()

    return targets.ffill().fillna(0.0)


def validate_h006_limits(
    weights: pd.DataFrame,
    asset_classes: Mapping[str, str],
    class_gross_caps: Mapping[str, float] = H006_CLASS_GROSS_CAPS,
    *,
    max_asset_weight: float = 0.12,
    gross_leverage_cap: float = 1.0,
    net_exposure_cap: float = 0.40,
    atol: float = 1e-10,
) -> dict:
    """Return auditable hard-limit checks for an H-006 weight matrix."""
    per_class = {}
    for class_name, cap in class_gross_caps.items():
        members = [s for s in weights.columns if asset_classes.get(s) == class_name]
        gross = (
            weights.loc[:, members].abs().sum(axis=1)
            if members else pd.Series(0.0, index=weights.index)
        )
        per_class[class_name] = {
            "observed_max": float(gross.max()), "cap": float(cap),
            "passed": bool(gross.max() <= cap + atol),
        }
    max_abs = float(weights.abs().max().max())
    max_gross = float(weights.abs().sum(axis=1).max())
    max_abs_net = float(weights.sum(axis=1).abs().max())
    return {
        "max_abs_weight": max_abs,
        "max_gross": max_gross,
        "max_abs_net": max_abs_net,
        "class_gross": per_class,
        "passed": bool(
            max_abs <= max_asset_weight + atol
            and max_gross <= gross_leverage_cap + atol
            and max_abs_net <= net_exposure_cap + atol
            and all(item["passed"] for item in per_class.values())
        ),
    }

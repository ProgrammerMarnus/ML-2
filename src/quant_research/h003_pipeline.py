"""H-003-R1 amended multi-asset volatility-shock research pipeline.

H-003-R1 is deliberately a new family.  It substitutes a five-term,
daily-OHLCV signal and VIX spot stand-down rule for the original H-003 VIX
futures M1-M3 contract.  Results from this module are never evidence for the
original preregistration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from .config import AppConfig
from .data.schemas import DataValidationError
from .evaluation.metrics import max_drawdown, sharpe_ratio, sortino_ratio
from .evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from .features.registry import registry_hash
from .portfolio.h002_returns import portfolio_returns
from .portfolio.h003_portfolio import (
    H003_R1_PORTFOLIO_PARAMS,
    construct_h003_portfolio,
    validate_h003_limits,
)
from .strategies.baseline import ExperimentResult, summarize_experiment


H003_R1_INVESTABLES = (
    "SPY", "QQQ", "IWM", "EFA", "EEM",
    "TLT", "IEF", "SHY", "LQD", "HYG",
    "UUP", "FXE", "FXY", "FXB",
    "GLD", "DBC", "USO",
)
H003_R1_ASSET_CLASSES = {
    **{s: "equity" for s in ("SPY", "QQQ", "IWM", "EFA", "EEM")},
    **{s: "fixed_income" for s in ("TLT", "IEF", "SHY", "LQD", "HYG")},
    **{s: "currency" for s in ("UUP", "FXE", "FXY", "FXB")},
    **{s: "commodity" for s in ("GLD", "DBC", "USO")},
}
H003_R1_FEATURES = (
    "h003r1_vshock_1d",
    "h003r1_vshock_5d",
    "h003r1_vol_mean_rev",
    "h003r1_skewness_20d",
    "h003r1_correlation_spike",
)


def _cross_sectional_zscore(panel: pd.DataFrame) -> pd.DataFrame:
    mean = panel.mean(axis=1)
    std = panel.std(axis=1).replace(0.0, np.nan)
    return panel.sub(mean, axis=0).div(std, axis=0)


def build_h003_features(close: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Build the five frozen H-003-R1 feature panels from trailing data only."""
    returns = close.pct_change(fill_method=None)
    rv20 = np.sqrt(returns.pow(2).rolling(20, min_periods=20).mean() * 252.0)
    # Reference window excludes the most recent 20 sessions, matching the
    # economic intent of comparing a current shock with an earlier-year norm.
    reference = rv20.shift(21)
    reference_mean = reference.rolling(232, min_periods=232).mean()
    reference_std = reference.rolling(232, min_periods=232).std().replace(0.0, np.nan)
    vshock = ((rv20 - reference_mean) / reference_std).clip(lower=0.0)

    # Per-asset average correlation to the rest of the universe.  Unlike a
    # single market-wide average, this remains cross-sectionally informative.
    average_corr = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    for symbol in close.columns:
        peers = [p for p in close.columns if p != symbol]
        pairwise = pd.concat(
            [returns[symbol].rolling(20, min_periods=20).corr(returns[p]) for p in peers],
            axis=1,
        )
        average_corr[symbol] = pairwise.mean(axis=1, skipna=True)
    corr_reference = average_corr.shift(1).rolling(252, min_periods=252).mean()

    return {
        "h003r1_vshock_1d": vshock.shift(1),
        "h003r1_vshock_5d": vshock.shift(1).rolling(5, min_periods=5).mean(),
        "h003r1_vol_mean_rev": rv20.div(reference_mean.replace(0.0, np.nan)),
        "h003r1_skewness_20d": returns.rolling(20, min_periods=20).skew(),
        "h003r1_correlation_spike": average_corr - corr_reference,
    }


def build_h003_signal(feature_panels: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Equal-weight the five frozen, sign-aligned cross-sectional terms."""
    missing = sorted(set(H003_R1_FEATURES) - set(feature_panels))
    if missing:
        raise DataValidationError(f"H-003-R1 feature panels missing: {missing}")
    signed = [
        -_cross_sectional_zscore(feature_panels["h003r1_vshock_1d"]),
        -_cross_sectional_zscore(feature_panels["h003r1_vshock_5d"]),
        -_cross_sectional_zscore(feature_panels["h003r1_vol_mean_rev"]),
        _cross_sectional_zscore(feature_panels["h003r1_skewness_20d"]),
        -_cross_sectional_zscore(feature_panels["h003r1_correlation_spike"]),
    ]
    stacked = pd.concat([term.stack() for term in signed], axis=1)
    # Require all five terms.  This prevents a changing feature definition in
    # early history or on partially missing observations.
    return stacked.mean(axis=1, skipna=False).unstack().reindex(
        index=signed[0].index, columns=signed[0].columns,
    )


def h003_feature_leakage_report(ohlcv: pd.DataFrame, seed: int = 17) -> Dict:
    """Perturb future prices and prove unchanged-history signals are identical."""
    close_all = ohlcv.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    investable = [s for s in H003_R1_INVESTABLES if s in close_all.columns]
    close = close_all[investable]
    if len(close) < 600 or len(investable) < 12:
        return {"passed": False, "checked_rows": 0,
                "detail": "insufficient panel for H-003-R1 leakage audit"}
    split = len(close) // 2
    before = build_h003_signal(build_h003_features(close))
    perturbed = close.copy()
    rng = np.random.default_rng(seed)
    future = perturbed.index[split:]
    shocks = rng.normal(0.0, 0.02, (len(future), len(investable)))
    perturbed.loc[future, investable] *= np.exp(np.cumsum(shocks, axis=0))
    after = build_h003_signal(build_h003_features(perturbed))
    delta = (before.iloc[:split] - after.iloc[:split]).abs().to_numpy(dtype=float)
    finite = delta[np.isfinite(delta)]
    max_delta = float(finite.max()) if finite.size else 0.0
    return {
        "passed": bool(max_delta < 1e-12),
        "checked_rows": int(split),
        "max_abs_delta_history": max_delta,
        "symbols_checked": investable,
        "detail": "H-003-R1 signals on unchanged history are identical under future-price perturbation",
    }


def _flatten_features(feature_panels: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for name in H003_R1_FEATURES:
        frame = feature_panels[name].copy()
        frame.columns = [f"{symbol}_{name}" for symbol in frame.columns]
        frames.append(frame)
    return pd.concat(frames, axis=1).sort_index()


def estimate_capacity_millions(
    executed_weights: pd.DataFrame,
    close: pd.DataFrame,
    volume: pd.DataFrame,
    participation: float = 0.01,
) -> float:
    """Conservative 5th-percentile AUM capacity from rebalance trade sizes."""
    dollar_volume = close * volume
    adv20 = dollar_volume.rolling(20, min_periods=20).mean()
    trades = executed_weights.diff().abs()
    mask = trades > 1e-12
    capacity = participation * adv20.div(trades.where(mask))
    values = capacity.where(mask).stack().replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.quantile(0.05) / 1_000_000.0) if len(values) else float("nan")


def run_h003_pipeline(
    cfg: AppConfig,
    ohlcv: pd.DataFrame,
    out: Path,
    dataset_version: str,
) -> Dict:
    """Execute H-003-R1 signal, allocation, and locked OOS fold accounting."""
    close_all = ohlcv.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    volume_all = ohlcv.pivot(index="timestamp", columns="symbol", values="volume").sort_index()
    missing = sorted(set(H003_R1_INVESTABLES) - set(close_all.columns))
    if missing:
        raise DataValidationError(f"H-003-R1 missing investable ETFs: {missing}")
    if "^VIX" not in close_all.columns:
        raise DataValidationError("H-003-R1 requires VIX spot (^VIX) for its stand-down/crisis contract")

    close = close_all.loc[:, H003_R1_INVESTABLES]
    volume = volume_all.loc[:, H003_R1_INVESTABLES]
    vix = close_all["^VIX"].reindex(close.index)
    feature_panels = build_h003_features(close)
    signal = build_h003_signal(feature_panels)
    features = _flatten_features(feature_panels)
    weights = construct_h003_portfolio(
        signal, close, H003_R1_ASSET_CLASSES, vix,
        **H003_R1_PORTFOLIO_PARAMS,
    )
    limit_report = validate_h003_limits(weights, H003_R1_ASSET_CLASSES)
    if not limit_report["passed"]:
        raise DataValidationError(f"H-003-R1 portfolio limits failed: {limit_report}")
    returns = portfolio_returns(
        weights, close,
        fee_bps=cfg.execution.fee_bps,
        slippage_bps=cfg.execution.slippage_bps,
    )

    eligible = signal.notna().sum(axis=1) >= H003_R1_PORTFOLIO_PARAMS["min_assets"]
    anchor = close.index[eligible]
    folds = walk_forward_splits(anchor, cfg.evaluation)
    locked_test = LockedTestProtocol(
        out / "test_lock.json", dataset_id=dataset_version,
        config_fingerprint=str(cfg.evaluation),
    )
    locked_test.verify(folds)

    fold_rows = []
    oos_net, oos_gross = [], []
    for spec in folds:
        idx = spec.test_idx
        net = returns["net_returns"].reindex(idx).fillna(0.0)
        gross = returns["gross_returns"].reindex(idx).fillna(0.0)
        turnover = returns["turnover"].reindex(idx).fillna(0.0)
        row = spec.summary()
        row.update({
            "threshold": float("nan"),
            "selected_features": ",".join(H003_R1_FEATURES),
            "model_type": "h003_r1_inverse_vol_portfolio",
            "oos_auc": float("nan"), "oos_brier": float("nan"),
            "n_trials_this_fold": 0,
            "oos_sharpe": sharpe_ratio(net),
            "oos_sortino": sortino_ratio(net),
            "oos_cagr": float("nan"),
            "oos_max_dd": max_drawdown(net),
            "oos_trades": int((turnover > 1e-12).sum()),
            "oos_turnover": float(turnover.sum()),
            "oos_gross_return": float((1.0 + gross).prod() - 1.0),
            "oos_net_return": float((1.0 + net).prod() - 1.0),
        })
        fold_rows.append(row)
        oos_net.append(net)
        oos_gross.append(gross)
    folds_df = pd.DataFrame(fold_rows)
    net_oos = pd.concat(oos_net).sort_index()
    gross_oos = pd.concat(oos_gross).sort_index()
    executed = returns["weight_matrix"].reindex(net_oos.index).fillna(0.0)

    baseline = ExperimentResult(
        folds=folds_df,
        predictions=pd.DataFrame(index=net_oos.index),
        oos_returns=net_oos,
        oos_gross_returns=gross_oos,
        oos_positions=executed.abs().sum(axis=1),
        fold_specs=folds,
        fitted_models={}, thresholds={},
        fee_costs=float(returns["fee_costs"].reindex(net_oos.index).sum()),
        slippage_costs=float(returns["slippage_costs"].reindex(net_oos.index).sum()),
        hold_bars=5,
        execution_contract="h003_r1_multi_asset_portfolio",
        feature_subset=list(features.columns),
        risk_returns=close["SPY"].pct_change(fill_method=None).shift(-1),
        model_cfg=None,
        boundary_policy="continuous",
        per_fold_hold_bars={}, per_fold_feature_subsets={},
        anchor_index=anchor,
    )
    summary = summarize_experiment(baseline)
    return {
        "baseline": baseline,
        "baseline_summary": summary,
        "folds": folds_df,
        "close": close,
        "volume": volume,
        "vix": vix,
        "features": features,
        "feature_panels": feature_panels,
        "h003_signal_panel": signal,
        "h003_weights": weights,
        "h003_executed_weights": returns["weight_matrix"],
        "h003_portfolio_returns": returns,
        "h003_limit_report": limit_report,
        "feature_version": registry_hash(list(H003_R1_FEATURES)),
        "feature_names": list(H003_R1_FEATURES),
        "traded_universe": list(H003_R1_INVESTABLES),
        "capacity_millions": estimate_capacity_millions(
            returns["weight_matrix"], close, volume,
        ),
        "feature_leakage_check": h003_feature_leakage_report(ohlcv),
        "price_feats": pd.DataFrame(), "info_cols": [],
        "events": None, "y": pd.Series(dtype=float),
        "fwd": baseline.risk_returns,
        "asset_forward_returns": None, "selected_asset": None,
        "pit_events_validated": False,
        "pit_events_note": "H-003-R1 daily market-data portfolio; no event inputs",
        "asset_execution_contract": {
            "strategy": "H-003-R1 weekly signed inverse-volatility portfolio",
            "signal_terms": list(H003_R1_FEATURES),
            "decision_time": "Wednesday close",
            "execution_lag_sessions": 1,
        },
    }

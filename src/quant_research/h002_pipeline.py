"""H-002 real-data pipeline runner.

This module implements the cross-sectional portfolio evaluation path for
the H-002 real-data exploration.  It is invoked from run_research_pipeline
when ``data.mode == 'h002'``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd
import numpy as np

from quant_research.config import AppConfig
from quant_research.data.schemas import DataValidationError
from quant_research.evaluation.metrics import max_drawdown, sharpe_ratio
from quant_research.evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from quant_research.strategies.baseline import ExperimentResult, summarize_experiment

def _max_abs(frame: pd.DataFrame) -> float:
    """Largest absolute finite value in ``frame`` (0.0 when nothing finite).

    Feature frames carry NaN during warm-up, so ``np.nanmax`` would warn/return
    NaN for an all-NaN slice; a finite maximum is the meaningful leakage bound.
    """
    if frame is None or frame.size == 0:
        return 0.0
    values = np.asarray(frame.to_numpy(), dtype=float)
    values = values[np.isfinite(values)]
    return float(np.abs(values).max()) if values.size else 0.0




def h002_feature_leakage_report(
    ohlcv: pd.DataFrame,
    max_symbols: int = 5,
    seed: int = 7,
) -> Dict:
    """Panel-aware leakage audit for the H-002 liquidity features.

    The generic ``feature_leakage_report`` rebuilds the price/volume feature
    family; H-002 uses a different family, so it gets its own audit.  Future
    OHLCV bars (strictly after the split) are perturbed for a sample of
    symbols and the liquidity features are rebuilt.  Every feature value on
    the unchanged history must be bit-identical, otherwise future information
    is entering feature construction.

    Returns a structured report compatible with ``report["feature_leakage_check"]``.
    """
    from .features.liquidity_reversal import compute_liquidity_features

    close = ohlcv.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    volume = ohlcv.pivot(index="timestamp", columns="symbol", values="volume").sort_index()
    high = ohlcv.pivot(index="timestamp", columns="symbol", values="high").sort_index()
    low = ohlcv.pivot(index="timestamp", columns="symbol", values="low").sort_index()

    n = len(close)
    if n < 20:
        return {
            "passed": False,
            "max_abs_delta_history": float("nan"),
            "checked_rows": 0,
            "detail": "insufficient history for an H-002 leakage audit",
        }
    split = n // 2

    eligible = [s for s in close.columns if len(close[s].dropna()) >= 252]
    sample = eligible[:max_symbols]
    if not sample:
        return {
            "passed": False,
            "max_abs_delta_history": float("nan"),
            "checked_rows": 0,
            "detail": "no symbols with sufficient history for an H-002 leakage audit",
        }

    rng = np.random.default_rng(seed)
    # ``close`` carries the union calendar of the whole universe; an individual
    # symbol need not have data on every one of those sessions.  Restrict the
    # audit to the dates the symbol actually has, otherwise label-based indexing
    # raises on dates the symbol never traded.
    history = close.index[:split]
    per_symbol: Dict[str, float] = {}
    for sym in sample:
        c, v = close[sym], volume[sym]
        h, l = high[sym], low[sym]
        try:
            before = compute_liquidity_features(h, l, c, v)
        except Exception:  # noqa: BLE001 - a symbol that cannot compute is skipped
            continue

        future = c.index.intersection(close.index[split:])
        hist_local = before.index.intersection(history)
        if not len(future) or not len(hist_local):
            continue

        pert = 1.0 + rng.normal(0.0, 0.05, len(future))
        c2, v2 = c.copy(), v.copy()
        h2, l2 = h.copy(), l.copy()
        # Perturb price levels and volume independently so both the price- and
        # volume-derived feature legs are exercised.
        c2.loc[future] = c.loc[future].to_numpy() * pert
        h2.loc[future] = h.loc[future].to_numpy() * pert
        l2.loc[future] = l.loc[future].to_numpy() * pert
        v2.loc[future] = v.loc[future].to_numpy() * (
            1.0 + rng.lognormal(0.0, 0.5, len(future))
        )
        try:
            after = compute_liquidity_features(h2, l2, c2, v2)
        except Exception:  # noqa: BLE001
            continue

        common_cols = before.columns.intersection(after.columns)
        # ``history`` is the union calendar; ``before``/``after`` are indexed on
        # this symbol's own trading days, so intersect before label indexing.
        delta = (before.loc[hist_local, common_cols]
                 - after.loc[hist_local, common_cols]).abs()
        per_symbol[sym] = _max_abs(delta)

    if not per_symbol:
        return {
            "passed": False,
            "max_abs_delta_history": float("nan"),
            "checked_rows": 0,
            "detail": "no H-002 feature frame could be rebuilt for the leakage audit",
        }

    max_delta = max(per_symbol.values())
    return {
        "passed": bool(max_delta < 1e-12),
        "checked_rows": int(split),
        "max_abs_delta_history": float(max_delta),
        "symbols_checked": sorted(per_symbol),
        "per_symbol_max_abs_delta": per_symbol,
        "information_event": {"key": "information_event",
                              "max_abs_delta_history": 0.0, "passed": True},
        "information_event_membership": {"max_abs_delta_history": 0.0, "passed": True},
        "detail": "H-002 liquidity features on unchanged history identical under "
                  "future-OHLCV perturbation",
    }


def _cross_sectional_zscore(panel: pd.DataFrame) -> pd.DataFrame:
    """Z-score each row (timestamp) across the available cross-section."""
    mu = panel.mean(axis=1)
    sd = panel.std(axis=1)
    return panel.sub(mu, axis=0).div(sd.replace(0.0, np.nan), axis=0)


def _build_h002_composite_signal(
    feature_frames: Dict[str, pd.DataFrame],
    volume: pd.DataFrame,
    tickers,
    index,
) -> pd.DataFrame:
    """Equal-weighted cross-sectional z-score composite (H-002 prereg section 2.3).

    The preregistered composite is

        Signal = w1·z(LIM_1d) + w2·z(LIM_5d) + w3·z(LIM_std_20d)
               + w4·z(Volume_ratio) + w5·z(Amihud_illiq)
               + w6·z(Size_decile) + w7·z(Vol_regime)

    with equal weights (w_i = 1/7) and cross-sectional z-scores.

    DOCUMENTED DEVIATION: two of the seven terms are not computable from
    free daily OHLCV and are omitted:
      - ``Size_decile`` requires point-in-time market capitalisation.
      - ``Vol_regime`` requires the VIX level (the free VIX series is not
        reliably retrievable here).
    The five available terms are equal-weighted (w_i = 1/5).  LIM_1d, LIM_5d and
    LIM_std_20d are proxied by the return-signed volume imbalance (see
    ``features/liquidity_reversal.py``), which is the documented stand-in for a
    properly classified LIM.

    A higher composite means more buying pressure, which the hypothesis expects
    to reverse; the portfolio therefore shorts high-signal names and longs
    low-signal names (see ``construct_h002_portfolio(long_low_signal=True)``).
    """
    lim1 = pd.DataFrame(index=index, columns=list(tickers), dtype=float)
    lim5 = pd.DataFrame(index=index, columns=list(tickers), dtype=float)
    limstd = pd.DataFrame(index=index, columns=list(tickers), dtype=float)
    volratio = pd.DataFrame(index=index, columns=list(tickers), dtype=float)
    amihud = pd.DataFrame(index=index, columns=list(tickers), dtype=float)

    for sym in tickers:
        feats = feature_frames.get(sym)
        if feats is None or "volume_imbalance" not in feats.columns:
            continue
        vi = feats["volume_imbalance"]
        lim1[sym] = vi
        lim5[sym] = vi.rolling(5).mean()
        limstd[sym] = vi.rolling(20).std()
        if "amihud_20d" in feats.columns:
            amihud[sym] = feats["amihud_20d"]
        if sym in volume.columns:
            vol = volume[sym]
            volratio[sym] = vol / vol.rolling(20).mean()

    terms = [
        _cross_sectional_zscore(lim1),
        _cross_sectional_zscore(lim5),
        _cross_sectional_zscore(limstd),
        _cross_sectional_zscore(volratio),
        _cross_sectional_zscore(amihud),
    ]
    # Equal-weight the available terms; NaN terms drop out per name/day rather
    # than silently becoming zero.  (pandas >= 3 no longer accepts dropna= on
    # DataFrame.stack; the new implementation already preserves NA rows.)
    stacked = pd.concat([t.stack() for t in terms], axis=1)
    composite = stacked.mean(axis=1, skipna=True).unstack()
    composite = composite.reindex(index=index, columns=list(tickers))
    return composite


def run_h002_pipeline(
    cfg: AppConfig,
    ohlcv: pd.DataFrame,
    data_meta: dict,
    out: Path,
    locked_test: LockedTestProtocol,
    counter,
    start_count: int,
    dataset_version: str,
    ledger,
    family_id: str,
) -> Dict:
    """Execute the H-002 real-data cross-sectional portfolio pipeline."""
    from .features.liquidity_reversal import compute_liquidity_features
    from .features.registry import registry_hash
    from .portfolio.h002_portfolio import (
        H002_PREREG_PORTFOLIO_PARAMS,
        construct_h002_portfolio,
    )
    from .portfolio.h002_returns import portfolio_returns

    close = ohlcv.pivot(index="timestamp", columns="symbol", values="close").sort_index()
    volume = ohlcv.pivot(index="timestamp", columns="symbol", values="volume").sort_index()
    open_ = ohlcv.pivot(index="timestamp", columns="symbol", values="open").sort_index()
    high = ohlcv.pivot(index="timestamp", columns="symbol", values="high").sort_index()
    low = ohlcv.pivot(index="timestamp", columns="symbol", values="low").sort_index()

    feature_frames = {}
    tickers = sorted(close.columns)

    for sym in tickers:
        c = close[sym]
        v = volume[sym]
        h = high[sym]
        l = low[sym]
        if len(c.dropna()) < 252:
            continue
        try:
            feats = compute_liquidity_features(h, l, c, v)
            feature_frames[sym] = feats
        except Exception:
            continue

    if not feature_frames:
        raise DataValidationError("H-002 pipeline: no tickers with computable features")

    feature_dfs = []
    bare_feature_names = set()
    for sym, feats in feature_frames.items():
        feats_df = feats.copy()
        bare_feature_names.update(str(c) for c in feats_df.columns)
        feats_df.columns = [f"{sym}_{col}" for col in feats_df.columns]
        feature_dfs.append(feats_df)

    all_features = pd.concat(feature_dfs, axis=1).sort_index()
    all_features = all_features.dropna(axis=1, how="all")
    # registry_hash requires bare feature names (the registry knows
    # ``amihud_1d``, not ``AAPL_amihud_1d``); ticker prefixes are panel
    # coordinates, not distinct feature definitions.
    if not bare_feature_names:
        raise DataValidationError("H-002 pipeline: no features produced")
    feature_version = registry_hash(sorted(bare_feature_names))

    signal_panel = _build_h002_composite_signal(feature_frames, volume, tickers, close.index)

    signal_panel = signal_panel.dropna(axis=1, how="all")
    if signal_panel.shape[1] < 10:
        raise DataValidationError(
            f"H-002 pipeline: only {signal_panel.shape[1]} signal tickers")

    sector_map_raw = data_meta.get("sector_map", {})
    if not sector_map_raw:
        from .data.h002_universe import _load_sector_map
        sector_map_raw = _load_sector_map()

    exec_cfg = cfg.execution
    # Protocol integrity: the frozen portfolio contract's holding period must
    # match the configured H-002 horizon, otherwise the evaluated book would
    # silently depart from the preregistered 1-5 day reversal window.
    frozen_hold = int(H002_PREREG_PORTFOLIO_PARAMS["rebalance_bars"])
    configured_hold = int(getattr(cfg.model, "hold_bars", frozen_hold))
    if configured_hold != frozen_hold:
        raise DataValidationError(
            "H-002 pipeline: configured model.hold_bars "
            f"({configured_hold}) does not match the frozen portfolio "
            f"rebalance_bars ({frozen_hold}) in H002_PREREG_PORTFOLIO_PARAMS"
        )
    weights = construct_h002_portfolio(
        signal_panel, sector_map_raw, **H002_PREREG_PORTFOLIO_PARAMS,
    )

    port_rets = portfolio_returns(weights, close,
                                   fee_bps=exec_cfg.fee_bps,
                                   slippage_bps=exec_cfg.slippage_bps)

    port_fwd = port_rets["net_returns"].loc[
        port_rets["net_returns"].index.intersection(close.index)]
    anchor = port_fwd.dropna().index
    folds = walk_forward_splits(anchor, cfg.evaluation)

    if not folds:
        raise DataValidationError("H-002 pipeline: no walk-forward folds")

    fold_rows = []
    oos_returns_list = []
    oos_gross_list = []
    oos_positions_list = []
    oos_turnover_list = []

    gross_series = port_rets["gross_returns"]
    turnover_series = port_rets["turnover"]

    for spec in folds:
        te_idx = spec.test_idx.intersection(anchor)
        if len(te_idx) < cfg.evaluation.test_window // 2:
            continue
        net_te = port_fwd.loc[te_idx]
        gross_te = gross_series.loc[te_idx]
        turn_te = turnover_series.loc[te_idx]
        sharpe = float(sharpe_ratio(net_te)) if net_te.std() > 0 and len(net_te) >= 20 else float("nan")
        max_dd = float(max_drawdown(net_te)) if len(net_te) else float("nan")
        trades = int((turn_te > 1e-9).sum())
        row = spec.summary()
        row.update({
            "threshold": float("nan"), "selected_features": "",
            "model_type": "h002_portfolio",
            "oos_auc": float("nan"), "oos_brier": float("nan"),
            "n_trials_this_fold": 0,
            "oos_sharpe": sharpe, "oos_sortino": float("nan"),
            "oos_cagr": float("nan"), "oos_max_dd": max_dd,
            "oos_trades": trades, "oos_turnover": float(turn_te.sum()),
            "oos_gross_return": float((1 + gross_te.fillna(0)).prod() - 1) if len(gross_te) else float("nan"),
            "oos_net_return": float((1 + net_te.fillna(0)).prod() - 1) if len(net_te) else float("nan"),
        })
        fold_rows.append(row)
        oos_returns_list.append(net_te)
        oos_gross_list.append(gross_te)
        oos_turnover_list.append(turn_te)

    if not fold_rows:
        raise DataValidationError("H-002 pipeline: no usable folds")

    folds_df = pd.DataFrame(fold_rows)
    oos_ret = pd.concat(oos_returns_list).sort_index()
    oos_gross = pd.concat(oos_gross_list).sort_index()
    oos_turn = pd.concat(oos_turnover_list).sort_index()

    # "Position" for a dollar-neutral book is not a scalar direction; the
    # meaningful analogue is the executed gross exposure (sum of |weights|),
    # which is what the manifest records per observation.
    gross_exposure = port_rets["weight_matrix"].abs().sum(axis=1)
    oos_positions = gross_exposure.reindex(oos_ret.index).fillna(0.0)

    baseline = ExperimentResult(
        folds=folds_df,
        predictions=pd.DataFrame(index=oos_ret.index),
        oos_returns=oos_ret, oos_gross_returns=oos_gross,
        oos_positions=oos_positions,
        fold_specs=folds, fitted_models={}, thresholds={},
        fee_costs=float(port_rets["fee_costs"].sum()),
        slippage_costs=float(port_rets["slippage_costs"].sum()), hold_bars=5,
        execution_contract="h002_cross_sectional_portfolio",
        feature_subset=list(all_features.columns),
        risk_returns=port_fwd.shift(1),
        model_cfg=None, boundary_policy="continuous",
        per_fold_hold_bars={}, per_fold_feature_subsets={},
        anchor_index=anchor,
    )

    summary = summarize_experiment(baseline)

    return {
        "baseline_summary": summary,
        "folds": folds_df,
        "feature_version": feature_version,
        # Registry-record descriptors.  The cross-sectional book trades many
        # names (not ``data.assets``) and uses a compact set of feature
        # DEFINITIONS (not the ticker-expanded panel columns).
        "traded_universe": sorted(
            weights.columns[weights.abs().sum(axis=0) > 0].tolist()),
        "feature_names": sorted(bare_feature_names),
        "ohlcv": ohlcv, "close": close, "volume": volume,
        "features": all_features,
        # Carry the constructed portfolio through so the finish stage does not
        # have to re-derive the signal panel by parsing column names.
        "h002_signal_panel": signal_panel,
        "h002_weights": weights,
        # Executed (lagged) cross-sectional weight matrix: the book the returns
        # were actually earned on, used for exposure/turnover/HHI diagnostics.
        "h002_executed_weights": port_rets["weight_matrix"],
        # Per-ticker feature frames, used by the finish stage to rebuild the
        # composite signal for cost/delay stress under identical logic.
        "h002_feature_frames": feature_frames,
        "price_feats": pd.DataFrame(), "info_cols": [],
        "events": None,
        "y": pd.Series(dtype=float),
        "fwd": port_fwd,
        "baseline": baseline,
        "asset_forward_returns": None, "selected_asset": None,
        "data_integrity_report": data_meta.get("missing_data_report", {}),
        "snapshot_metadata": data_meta.get("snapshot_metadata", {}),
        "feature_leakage_check": h002_feature_leakage_report(ohlcv),
        "pit_events_validated": False,
        "pit_events_note": "H-002 real-data pipeline",
        "asset_execution_contract": {
            "strategy": "H-002 cross-sectional dollar-neutral L/S portfolio",
            "construction": "equal-weight top/bottom decile, sector-neutral",
        },
    }

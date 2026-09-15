"""Portfolio-native cross-sectional evaluator for H-006.

H-006 is a fixed-rule, 17-ETF weekly strategy.  It has no fitted model or
threshold search, so train/validation windows define chronological boundaries
only.  This module keeps its panel construction and robustness paths isolated
from the scalar classifier engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

import numpy as np
import pandas as pd

from .config import AppConfig
from .data.schemas import DataValidationError
from .evaluation.bootstrap import bootstrap_sharpe
from .evaluation.metrics import max_drawdown, sharpe_ratio, sortino_ratio
from .evaluation.placebo import placebo_statistics
from .evaluation.walk_forward import LockedTestProtocol, walk_forward_splits
from .experiments.promotion import stress_survival
from .features.factor_mean_reversion import compute_factor_mean_reversion_features
from .features.registry import registry_hash
from .portfolio.h002_returns import portfolio_returns
from .portfolio.h006_portfolio import (
    H006_PORTFOLIO_PARAMS,
    construct_h006_portfolio,
    validate_h006_limits,
)
from .strategies.baseline import ExperimentResult, summarize_experiment


H006_INVESTABLES = (
    "SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "VEA", "VWO",
    "TLT", "IEF", "SHY", "LQD", "HYG", "GLD", "DBC", "USO", "VNQ",
)
H006_ASSET_CLASSES = {
    **{s: "us_equity" for s in ("SPY", "QQQ", "IWM", "DIA", "VNQ")},
    **{s: "international_equity" for s in ("EFA", "EEM", "VEA", "VWO")},
    **{s: "fixed_income" for s in ("TLT", "IEF", "SHY", "LQD", "HYG")},
    **{s: "commodity" for s in ("GLD", "DBC", "USO")},
}
H006_BETA_BENCHMARK = {
    **{s: "SPY" for s in H006_INVESTABLES if H006_ASSET_CLASSES[s] in {
        "us_equity", "international_equity"
    }},
    **{s: "LQD" for s in H006_INVESTABLES if H006_ASSET_CLASSES[s] == "fixed_income"},
    **{s: "GLD" for s in H006_INVESTABLES if H006_ASSET_CLASSES[s] == "commodity"},
}
H006_FEATURES = (
    "h006_beta_zscore",
    "h006_momentum_deviation",
    "h006_volatility_percentile",
    "h006_correlation_extreme",
    "h006_drawdown_recovery",
)


def _cross_sectional_zscore(panel: pd.DataFrame) -> pd.DataFrame:
    mean = panel.mean(axis=1)
    std = panel.std(axis=1).replace(0.0, np.nan)
    return panel.sub(mean, axis=0).div(std, axis=0)


def build_h006_feature_panels(
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """Build all five per-asset H-006 features with frozen benchmarks."""
    missing = sorted(set(H006_INVESTABLES) - set(close.columns))
    if missing:
        raise DataValidationError(f"H-006 missing investable ETFs: {missing}")
    panels = {
        name: pd.DataFrame(index=close.index, columns=H006_INVESTABLES, dtype=float)
        for name in H006_FEATURES
    }
    for symbol in H006_INVESTABLES:
        benchmark = H006_BETA_BENCHMARK[symbol]
        features = compute_factor_mean_reversion_features(
            close=close[symbol], high=high[symbol], low=low[symbol],
            volume=volume[symbol], benchmark_close=close[benchmark],
            correlation_benchmark_close=close["SPY"],
        ).reindex(close.index)
        # A benchmark's exposure to itself is identically one (and its
        # correlation with itself is identically one). Rolling floating-point
        # arithmetic can leave tiny non-zero standard deviations and turn that
        # numerical noise into large z-scores. The frozen all-five-terms rule
        # treats these undefined standardized self-exposures as missing.
        if symbol == benchmark:
            features["h006_beta_zscore"] = np.nan
        if symbol == "SPY":
            features["h006_correlation_extreme"] = np.nan
        for name in H006_FEATURES:
            panels[name][symbol] = features[name]
    return panels


def build_h006_signal(feature_panels: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Cross-sectionally standardize and equal-weight the five signed terms."""
    missing = sorted(set(H006_FEATURES) - set(feature_panels))
    if missing:
        raise DataValidationError(f"H-006 feature panels missing: {missing}")
    signed = [
        -_cross_sectional_zscore(feature_panels["h006_beta_zscore"]),
        -_cross_sectional_zscore(feature_panels["h006_momentum_deviation"]),
        -_cross_sectional_zscore(feature_panels["h006_volatility_percentile"]),
        -_cross_sectional_zscore(feature_panels["h006_correlation_extreme"]),
        _cross_sectional_zscore(feature_panels["h006_drawdown_recovery"]),
    ]
    stacked = pd.concat(
        [term.stack(future_stack=True) for term in signed], axis=1
    )
    # All five terms are mandatory for a name/date. A missing component never
    # silently changes the equal-weight definition.
    return stacked.mean(axis=1, skipna=False).unstack().reindex(
        index=signed[0].index, columns=H006_INVESTABLES,
    )


def _flatten_features(feature_panels: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for name in H006_FEATURES:
        frame = feature_panels[name].copy()
        frame.columns = [f"{symbol}_{name}" for symbol in frame.columns]
        frames.append(frame)
    return pd.concat(frames, axis=1).sort_index()


def h006_feature_leakage_report(ohlcv: pd.DataFrame, seed: int = 23) -> Dict:
    """Prove that future OHLCV changes cannot alter historical H-006 signals."""
    panels = {
        field: ohlcv.pivot(index="timestamp", columns="symbol", values=field).sort_index()
        for field in ("close", "high", "low", "volume")
    }
    if len(panels["close"]) < 700:
        return {"passed": False, "checked_rows": 0,
                "detail": "insufficient panel for H-006 leakage audit"}
    split = len(panels["close"]) // 2
    before = build_h006_signal(build_h006_feature_panels(**panels))
    changed = {name: frame.copy() for name, frame in panels.items()}
    rng = np.random.default_rng(seed)
    future = panels["close"].index[split:]
    shocks = rng.normal(0.0, 0.02, (len(future), len(H006_INVESTABLES)))
    multipliers = np.exp(np.cumsum(shocks, axis=0))
    for field in ("close", "high", "low"):
        changed[field].loc[future, H006_INVESTABLES] *= multipliers
    changed["volume"].loc[future, H006_INVESTABLES] *= rng.lognormal(
        0.0, 0.4, (len(future), len(H006_INVESTABLES))
    )
    after = build_h006_signal(build_h006_feature_panels(**changed))
    delta = (before.iloc[:split] - after.iloc[:split]).abs().to_numpy(dtype=float)
    finite = delta[np.isfinite(delta)]
    max_delta = float(finite.max()) if finite.size else 0.0
    return {
        "passed": bool(max_delta < 1e-12),
        "checked_rows": int(split),
        "max_abs_delta_history": max_delta,
        "symbols_checked": list(H006_INVESTABLES),
        "detail": "H-006 signals on unchanged history are identical under future-OHLCV perturbation",
    }


def estimate_capacity_millions(
    executed_weights: pd.DataFrame,
    close: pd.DataFrame,
    volume: pd.DataFrame,
    participation: float = 0.01,
) -> float:
    """Conservative fifth-percentile AUM capacity at one-percent ADV."""
    adv20 = (close * volume).rolling(20, min_periods=20).mean()
    trades = executed_weights.diff().abs()
    mask = trades > 1e-12
    capacity = participation * adv20.div(trades.where(mask))
    values = capacity.where(mask).stack().replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.quantile(0.05) / 1_000_000.0) if len(values) else float("nan")


def _assert_frozen_execution_config(cfg: AppConfig) -> None:
    expected = {
        "hold_bars": 5,
        "rebalance_day": "wednesday",
        "target_vol": 0.10,
        "max_position": 0.12,
        "gross_leverage_cap": 1.0,
        "net_exposure_cap": 0.40,
    }
    actual = {
        "hold_bars": cfg.model.hold_bars,
        "rebalance_day": cfg.model.rebalance_day,
        "target_vol": cfg.execution.target_vol,
        "max_position": cfg.execution.max_position,
        "gross_leverage_cap": cfg.execution.gross_leverage_cap,
        "net_exposure_cap": cfg.execution.net_exposure_cap,
    }
    if actual != expected:
        raise DataValidationError(
            f"H-006 execution config differs from frozen contract: {actual} != {expected}"
        )


def run_h006_pipeline(
    cfg: AppConfig,
    ohlcv: pd.DataFrame,
    out: Path,
    dataset_version: str,
) -> Dict:
    """Build the H-006 strategy and its locked, continuous OOS evidence."""
    _assert_frozen_execution_config(cfg)
    if cfg.research.threshold_candidates:
        raise DataValidationError("H-006 has no threshold search")
    if cfg.research.protocol_path:
        from .experiments.protocol import ResearchProtocol
        declared = set(ResearchProtocol.load(cfg.research.protocol_path).feature_names)
        if declared != set(H006_FEATURES):
            raise DataValidationError(
                "H-006 protocol feature contract does not match the five frozen terms"
            )

    pivot = lambda field: ohlcv.pivot(  # noqa: E731 - compact fixed panel loader
        index="timestamp", columns="symbol", values=field
    ).sort_index()
    close_all, high_all, low_all, volume_all = (
        pivot("close"), pivot("high"), pivot("low"), pivot("volume")
    )
    missing = sorted(set(H006_INVESTABLES) - set(close_all.columns))
    if missing:
        raise DataValidationError(f"H-006 missing investable ETFs: {missing}")
    if "^VIX" not in close_all.columns:
        raise DataValidationError(
            "H-006 requires ^VIX to enforce its frozen VIX>75 gross-reduction rule"
        )

    close = close_all.loc[:, H006_INVESTABLES]
    high = high_all.loc[:, H006_INVESTABLES]
    low = low_all.loc[:, H006_INVESTABLES]
    volume = volume_all.loc[:, H006_INVESTABLES]
    vix = close_all["^VIX"].reindex(close.index)
    feature_panels = build_h006_feature_panels(close, high, low, volume)
    signal = build_h006_signal(feature_panels)
    features = _flatten_features(feature_panels)
    weights = construct_h006_portfolio(
        signal, close, H006_ASSET_CLASSES, vix, **H006_PORTFOLIO_PARAMS,
    )
    limits = validate_h006_limits(weights, H006_ASSET_CLASSES)
    if not limits["passed"]:
        raise DataValidationError(f"H-006 portfolio limits failed: {limits}")

    result = portfolio_returns(
        weights, close, fee_bps=cfg.execution.fee_bps,
        slippage_bps=cfg.execution.slippage_bps,
    )
    rf_fwd = close["SHY"].shift(-1) / close["SHY"] - 1.0
    excess_net = result["net_returns"] - rf_fwd.fillna(0.0)
    excess_gross = result["gross_returns"] - rf_fwd.fillna(0.0)

    # Fold geometry is anchored on the declared observations, never on signal
    # availability or realized outcomes. Warm-up rows may be flat, but cannot
    # move test membership.
    anchor = close.index
    folds = walk_forward_splits(anchor, cfg.evaluation)
    lock = LockedTestProtocol(
        out / "test_lock.json", dataset_id=dataset_version,
        config_fingerprint=str(cfg.evaluation),
    )
    lock.verify(folds)

    fold_rows, oos_net, oos_gross = [], [], []
    for spec in folds:
        idx = spec.test_idx
        net = excess_net.reindex(idx).fillna(0.0)
        gross = excess_gross.reindex(idx).fillna(0.0)
        turnover = result["turnover"].reindex(idx).fillna(0.0)
        row = spec.summary()
        row.update({
            "threshold": float("nan"),
            "selected_features": ",".join(H006_FEATURES),
            "model_type": "h006_fixed_rule_cross_sectional",
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
    executed_oos = result["weight_matrix"].reindex(net_oos.index).fillna(0.0)
    baseline = ExperimentResult(
        folds=folds_df,
        predictions=pd.DataFrame(index=net_oos.index),
        oos_returns=net_oos,
        oos_gross_returns=gross_oos,
        oos_positions=executed_oos.abs().sum(axis=1),
        fold_specs=folds, fitted_models={}, thresholds={},
        fee_costs=float(result["fee_costs"].reindex(net_oos.index).sum()),
        slippage_costs=float(result["slippage_costs"].reindex(net_oos.index).sum()),
        hold_bars=5,
        execution_contract="h006_cross_sectional_portfolio",
        feature_subset=list(features.columns),
        risk_returns=(close["SPY"].shift(-1) / close["SPY"] - 1.0),
        model_cfg=None, boundary_policy="continuous",
        per_fold_hold_bars={}, per_fold_feature_subsets={}, anchor_index=anchor,
    )
    return {
        "baseline": baseline,
        "baseline_summary": summarize_experiment(baseline),
        "folds": folds_df,
        "close": close, "high": high, "low": low, "volume": volume,
        "vix": vix, "risk_free_forward_returns": rf_fwd,
        "features": features, "feature_panels": feature_panels,
        "h006_signal_panel": signal,
        "h006_weights": weights,
        "h006_executed_weights": result["weight_matrix"],
        "h006_portfolio_returns": result,
        "h006_limit_report": limits,
        "feature_version": registry_hash(list(H006_FEATURES)),
        "feature_names": list(H006_FEATURES),
        "traded_universe": list(H006_INVESTABLES),
        "capacity_millions": estimate_capacity_millions(
            result["weight_matrix"], close, volume,
        ),
        "feature_leakage_check": h006_feature_leakage_report(ohlcv),
        "price_feats": pd.DataFrame(), "info_cols": [], "events": None,
        "y": pd.Series(dtype=float), "fwd": baseline.risk_returns,
        "asset_forward_returns": None, "selected_asset": None,
        "pit_events_validated": False,
        "pit_events_note": "H-006 daily-market-data portfolio; no event inputs",
        "asset_execution_contract": {
            "strategy": "H-006 weekly factor mean-reversion portfolio",
            "decision_time": "Wednesday close",
            "execution_lag_sessions": 1,
            "risk_free_proxy": "SHY",
        },
    }


def finish_h006_pipeline(
    cfg: AppConfig,
    out: Path,
    report: Dict,
    dataset_version: str,
    integrity_ok: bool,
    register_and_decide: Callable,
) -> Dict:
    """Build portfolio-native stresses and register the H-006 decision."""
    baseline = report["baseline"]
    summary = report["baseline_summary"]
    close, volume = report["close"], report["volume"]
    high, low, vix = report["high"], report["low"], report["vix"]
    signal, weights = report["h006_signal_panel"], report["h006_weights"]
    rf_fwd = report["risk_free_forward_returns"].fillna(0.0)
    oos_idx = baseline.oos_returns.index
    base_fee, base_slip = float(cfg.execution.fee_bps), float(cfg.execution.slippage_bps)

    def evaluate(targets, fee_bps=base_fee, slippage_bps=base_slip):
        priced = portfolio_returns(
            targets, close, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )
        net = (priced["net_returns"] - rf_fwd).reindex(oos_idx).fillna(0.0)
        gross = (priced["gross_returns"] - rf_fwd).reindex(oos_idx).fillna(0.0)
        turn = priced["turnover"].reindex(oos_idx).fillna(0.0)
        return priced, net, gross, turn

    cost_rows = []
    for fee, slip in (
        (base_fee, base_slip),
        (float(cfg.promotion.cost_stress_fee_bps),
         float(cfg.promotion.cost_stress_slippage_bps)),
    ):
        _, net, gross, turn = evaluate(weights, fee, slip)
        cost_rows.append({
            "fee_bps": fee, "slippage_bps": slip,
            "sharpe": sharpe_ratio(net), "gross_sharpe": sharpe_ratio(gross),
            "net_return": float((1.0 + net).prod() - 1.0),
            "gross_return": float((1.0 + gross).prod() - 1.0),
            "max_dd": max_drawdown(net),
            "annual_turnover": float(turn.sum() / max(len(turn) / 252.0, 1e-9)),
        })
    cost_stress = pd.DataFrame(cost_rows).drop_duplicates(
        subset=["fee_bps", "slippage_bps"]
    )

    delay_rows = []
    for delay in sorted({0, int(cfg.promotion.delay_stress_bars)}):
        _, net, _, turn = evaluate(weights.shift(delay) if delay else weights)
        delay_rows.append({
            "delay_bars": delay, "sharpe": sharpe_ratio(net),
            "net_return": float((1.0 + net).prod() - 1.0),
            "max_dd": max_drawdown(net),
            "annual_turnover": float(turn.sum() / max(len(turn) / 252.0, 1e-9)),
        })
    delay_stress = pd.DataFrame(delay_rows)

    stressed_slip = base_slip * float(cfg.promotion.slippage_stress_multiplier)
    _, slip_net, slip_gross, slip_turn = evaluate(weights, base_fee, stressed_slip)
    slippage_stress = pd.DataFrame([{
        "multiplier": float(cfg.promotion.slippage_stress_multiplier),
        "fee_bps": base_fee, "slippage_bps": stressed_slip,
        "sharpe": sharpe_ratio(slip_net), "gross_sharpe": sharpe_ratio(slip_gross),
        "net_return": float((1.0 + slip_net).prod() - 1.0),
        "max_dd": max_drawdown(slip_net),
        "annual_turnover": float(slip_turn.sum() / max(len(slip_turn) / 252.0, 1e-9)),
    }])

    perturb_rows = []
    pct = float(cfg.promotion.parameter_robustness_pct)
    for factor in (1.0 - pct, 1.0 + pct):
        params = dict(H006_PORTFOLIO_PARAMS)
        params["position_target_vol"] *= factor
        params["portfolio_target_vol"] *= factor
        perturbed_weights = construct_h006_portfolio(
            signal, close, H006_ASSET_CLASSES, vix, **params,
        )
        _, net, _, turn = evaluate(perturbed_weights)
        perturb_rows.append({
            "factor": factor, "sharpe": sharpe_ratio(net),
            "net_return": float((1.0 + net).prod() - 1.0),
            "max_dd": max_drawdown(net),
            "annual_turnover": float(turn.sum() / max(len(turn) / 252.0, 1e-9)),
        })
    parameter_perturbation = pd.DataFrame(perturb_rows)

    rng = np.random.default_rng(cfg.model.random_seed + 6006)
    masked_close = close.mask(
        rng.random(close.shape) < float(cfg.promotion.missing_data_pct)
    )
    masked_features = build_h006_feature_panels(masked_close, high, low, volume)
    masked_signal = build_h006_signal(masked_features)
    missing_weights = construct_h006_portfolio(
        masked_signal, masked_close, H006_ASSET_CLASSES, vix,
        **H006_PORTFOLIO_PARAMS,
    )
    _, missing_net, _, missing_turn = evaluate(missing_weights)
    missing_data_stress = pd.DataFrame([{
        "missing_frac": float(cfg.promotion.missing_data_pct),
        "seed": cfg.model.random_seed + 6006,
        "sharpe": sharpe_ratio(missing_net),
        "net_return": float((1.0 + missing_net).prod() - 1.0),
        "max_dd": max_drawdown(missing_net),
        "annual_turnover": float(
            missing_turn.sum() / max(len(missing_turn) / 252.0, 1e-9)
        ),
    }])

    valid_idx = signal.index[signal.notna().sum(axis=1) >= H006_PORTFOLIO_PARAMS["min_assets"]]
    rng = np.random.default_rng(cfg.model.random_seed)
    null_rows = []
    for run_id in range(cfg.research.placebo_runs):
        permuted = signal.copy()
        order = rng.permutation(len(valid_idx))
        permuted.loc[valid_idx] = signal.loc[valid_idx].iloc[order].to_numpy()
        placebo_weights = construct_h006_portfolio(
            permuted, close, H006_ASSET_CLASSES, vix, **H006_PORTFOLIO_PARAMS,
        )
        _, null_net, _, _ = evaluate(placebo_weights)
        null_rows.append({"run": run_id, "oos_sharpe": sharpe_ratio(null_net)})
    placebo_null = pd.DataFrame(null_rows)
    placebo = placebo_statistics(
        summary["full_oos_net_sharpe"], placebo_null, metric="oos_sharpe",
    )
    boot = bootstrap_sharpe(
        baseline.oos_returns, seed=cfg.model.random_seed, research=cfg.research,
    )

    robustness = {
        "cost_stress": cost_stress.to_dict("records"),
        "slippage_stress": slippage_stress.to_dict("records"),
        "delay_stress": delay_stress.to_dict("records"),
        "parameter_perturbation": parameter_perturbation.to_dict("records"),
        "missing_data": missing_data_stress.to_dict("records"),
    }
    robustness.update(stress_survival(robustness, cfg.promotion))

    executed = report["h006_executed_weights"].reindex(oos_idx).fillna(0.0)
    benchmark = (
        close["SPY"].shift(-1) / close["SPY"] - 1.0 - rf_fwd
    ).reindex(oos_idx)
    from .portfolio.risk import risk_report
    risk = risk_report(
        baseline.oos_returns, weight_matrix=executed, benchmark=benchmark,
    )
    annual_turnover = float(
        report["h006_portfolio_returns"]["turnover"].reindex(oos_idx).fillna(0.0).sum()
        / max(len(oos_idx) / 252.0, 1e-9)
    )
    capacity = float(report["capacity_millions"])
    cost_exact = cost_stress[
        cost_stress["fee_bps"].ge(cfg.promotion.cost_stress_fee_bps)
        & cost_stress["slippage_bps"].ge(cfg.promotion.cost_stress_slippage_bps)
    ]["sharpe"]
    delay_exact = delay_stress[
        delay_stress["delay_bars"].eq(cfg.promotion.delay_stress_bars)
    ]["sharpe"]
    additional = [
        {"name": "h006_cost_stress_exact", "passed": bool(len(cost_exact) and (cost_exact > 0).all()),
         "detail": f"Sharpe at >=10bps fee + >=5bps slippage={cost_exact.tolist()} > 0"},
        {"name": "h006_delay_stress_at_least_0_5", "passed": bool(len(delay_exact) and (delay_exact > 0.5).all()),
         "detail": f"one-session-delay Sharpe={delay_exact.tolist()} > 0.5"},
        {"name": "h006_slippage_stress_at_least_0_5", "passed": bool(slippage_stress['sharpe'].iloc[0] > 0.5),
         "detail": f"2x-slippage Sharpe={slippage_stress['sharpe'].iloc[0]:.6g} > 0.5"},
        {"name": "h006_parameter_robustness", "passed": bool((parameter_perturbation['sharpe'] > 0.5).all()),
         "detail": f"+/-20% volatility-target Sharpes={parameter_perturbation['sharpe'].tolist()} > 0.5"},
        {"name": "h006_missing_data_robustness", "passed": bool(missing_data_stress['sharpe'].iloc[0] > 0.5),
         "detail": f"5% input-gap Sharpe={missing_data_stress['sharpe'].iloc[0]:.6g} > 0.5"},
        {"name": "h006_capacity_sufficient", "passed": bool(np.isfinite(capacity) and capacity >= cfg.promotion.min_capacity_aum / 1_000_000.0),
         "detail": f"capacity=${capacity:.6g}m >= ${cfg.promotion.min_capacity_aum / 1_000_000.0:.6g}m"},
        {"name": "h006_trial_budget", "passed": bool(report['trial_counter'].count <= cfg.research.max_trials),
         "detail": f"trial count={report['trial_counter'].count} <= {cfg.research.max_trials}"},
    ]

    report.update({
        "robustness": robustness,
        "cost_stress": cost_stress,
        "slippage_stress": slippage_stress,
        "delay_stress": delay_stress,
        "parameter_perturbation": parameter_perturbation,
        "missing_data_stress": missing_data_stress,
        "ablation": pd.DataFrame(),
        "placebo_null": placebo_null,
        "placebo_permute_target": pd.DataFrame(),
        "placebo_block_permute": pd.DataFrame(),
        "placebo_statistics": placebo,
        "placebo_mode_statistics": {"shuffle_signal_rows": placebo},
        "bootstrap": boot,
        "risk": risk,
        "h006_gate_metrics": {
            "sortino": sortino_ratio(baseline.oos_returns),
            "annual_turnover": annual_turnover,
            "capacity_millions": capacity,
            "slippage_2x_sharpe": float(slippage_stress["sharpe"].iloc[0]),
            "parameter_sharpes": parameter_perturbation["sharpe"].tolist(),
            "missing_data_sharpe": float(missing_data_stress["sharpe"].iloc[0]),
        },
        "additional_gate_checks": additional,
    })
    return register_and_decide(
        cfg, out, report, baseline, summary, robustness, boot, placebo,
        report["trial_counter"], int(report["start_count"]), dataset_version,
        report["feature_version"], [], integrity_ok, report["features"], None, None,
    )

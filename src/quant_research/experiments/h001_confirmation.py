"""One locked, asset-specific final confirmation for corrected H-001."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_config
from ..data.loaders import load_market_data, to_panels, to_price_panels
from ..data.snapshots import save_snapshot
from ..data.validation import validate_ohlcv
from ..evaluation.backtest import backtest_selected_asset
from ..evaluation.bootstrap import bootstrap_sharpe
from ..evaluation.metrics import sharpe_ratio
from ..evaluation.placebo import placebo_statistics
from ..features.assembly import build_feature_panel, h001_selected_legs
from ..strategies.baseline import build_model
from .protocol import ResearchProtocol


def _inputs(close: pd.DataFrame, features: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    assets = pd.DataFrame({
        "SPY": close["SPY"].shift(-1) / close["SPY"] - 1.0,
        "QQQ": close["QQQ"].shift(-1) / close["QQQ"] - 1.0,
    })
    legs = h001_selected_legs(features)
    fwd = pd.Series(np.nan, index=features.index, dtype="float64")
    for symbol in assets.columns:
        fwd.loc[legs.eq(symbol)] = assets.loc[legs.eq(symbol), symbol]
    return assets, legs, fwd


def run_confirmation(config_path: str, output: str, train_end: str, confirmation_start: str) -> dict:
    cfg = load_config(config_path)
    protocol = ResearchProtocol.load(cfg.research.protocol_path or "")
    protocol.assert_matches_config(cfg.fingerprint(), cfg.research.max_trials)
    if protocol.target != "conditional_SPY_or_QQQ_lagging_leg":
        raise ValueError("H-001 confirmation protocol must declare the conditional SPY/QQQ target")
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    ohlcv, data_meta = load_market_data(cfg.data)
    validate_ohlcv(ohlcv)
    snapshot = save_snapshot(ohlcv, cfg.data.raw_snapshot_dir, name="h001_confirmation")
    close, volume = to_panels(ohlcv)
    open_, high, low = to_price_panels(ohlcv)[:3]
    features = build_feature_panel(close, volume, "SPY", cfg.features,
                                   open_=open_, high=high, low=low)
    if sorted(features.columns) != sorted(protocol.feature_names):
        raise ValueError("frozen protocol does not match H-001 feature panel")
    assets, legs, fwd = _inputs(close, features)
    train_mask = features.index < pd.Timestamp(train_end, tz="UTC")
    test_mask = features.index >= pd.Timestamp(confirmation_start, tz="UTC")
    train_idx = features.index[train_mask & fwd.notna()]
    test_idx = features.index[test_mask & fwd.notna()]
    if len(train_idx) < 252 or len(test_idx) < 252:
        raise ValueError("confirmation requires at least one year of usable train and test observations")
    y = (fwd > 0).astype(float)
    model = build_model(cfg.model)
    model.fit(features.loc[train_idx], y.loc[train_idx].astype(int))
    probabilities = pd.Series(model.predict_proba(features.loc[test_idx])[:, 1], index=test_idx)
    threshold = float(cfg.research.threshold_candidates[0])
    risk = assets.mean(axis=1).shift(1)
    baseline = backtest_selected_asset(probabilities, assets.loc[test_idx], legs.loc[test_idx],
                                      cfg.execution, threshold=threshold,
                                      hold_bars=cfg.model.hold_bars or 1,
                                      risk_returns=risk)
    costs, delays = [], []
    for fee in (0.0, 5.0, 10.0, 20.0):
        bt = backtest_selected_asset(probabilities, assets.loc[test_idx], legs.loc[test_idx],
                                     replace(cfg.execution, fee_bps=fee), threshold=threshold,
                                     hold_bars=cfg.model.hold_bars or 1, risk_returns=risk)
        costs.append({"fee_bps": fee, "sharpe": bt.metrics["sharpe"]})
    for delay in (0, 1, 2, 3):
        bt = backtest_selected_asset(probabilities, assets.loc[test_idx], legs.loc[test_idx],
                                     replace(cfg.execution, signal_delay_bars=delay), threshold=threshold,
                                     hold_bars=cfg.model.hold_bars or 1, risk_returns=risk)
        delays.append({"delay_bars": delay, "sharpe": bt.metrics["sharpe"]})
    rng = np.random.default_rng(cfg.model.random_seed)
    nulls = []
    for _ in range(cfg.research.placebo_runs):
        permutation = rng.permutation(len(test_idx))
        permuted = features.loc[test_idx].iloc[permutation].copy()
        permuted.index = test_idx
        # The selected leg is itself a deterministic H-001 signal. Derive it
        # from the permuted rows; holding it fixed would merely retest the same
        # SPY/QQQ allocation and cannot be a valid null for the full strategy.
        permuted_legs = h001_selected_legs(permuted)
        p = pd.Series(model.predict_proba(permuted)[:, 1], index=test_idx)
        nulls.append(float(backtest_selected_asset(
            p, assets.loc[test_idx], permuted_legs, cfg.execution, threshold=threshold,
            hold_bars=cfg.model.hold_bars or 1, risk_returns=risk,
        ).metrics["sharpe"]))
    observed = float(baseline.metrics["sharpe"])
    placebo = placebo_statistics(
        observed, pd.DataFrame({"mean_oos_sharpe": nulls})
    )
    bootstrap = bootstrap_sharpe(baseline.net_returns, seed=cfg.model.random_seed, research=cfg.research)
    gates = {
        "net_sharpe_positive": observed > 0,
        "drawdown_within_limit": baseline.metrics["max_dd"] >= cfg.promotion.max_oos_dd,
        "cost_stress_survives": next(row["sharpe"] for row in costs if row["fee_bps"] == 10.0) > 0,
        "delay_stress_survives": next(row["sharpe"] for row in delays if row["delay_bars"] == 1) > 0,
        "bootstrap_positive_prob": bootstrap["positive_prob"] >= cfg.promotion.min_bootstrap_positive_prob,
        "placebo_separates": placebo["percentile"] >= cfg.promotion.min_placebo_percentile
                              and placebo["adjusted_p"] <= cfg.promotion.max_placebo_adjusted_p,
    }
    report = {
        "status": "CONFIRMED_CANDIDATE" if all(gates.values()) else "CONFIRMATION_FAILED",
        "protocol": {"path": str(Path(cfg.research.protocol_path).resolve()), "digest": protocol.digest},
        "data": {"metadata": data_meta, "snapshot": snapshot},
        "train_end": train_end, "confirmation_start": confirmation_start,
        "n_train": len(train_idx), "n_confirmation": len(test_idx),
        "features": list(features.columns), "threshold": threshold,
        "net_metrics": baseline.metrics, "bootstrap": bootstrap, "placebo": placebo,
        "cost_stress": costs, "delay_stress": delays, "gates": gates,
        "executed_legs": legs.loc[test_idx].value_counts().to_dict(),
    }
    (out / "confirmation_results.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run locked H-001 final confirmation")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--train-end", default="2021-01-01")
    parser.add_argument("--confirmation-start", default="2021-01-01")
    args = parser.parse_args(argv)
    print(json.dumps(run_confirmation(args.config, args.output, args.train_end, args.confirmation_start), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

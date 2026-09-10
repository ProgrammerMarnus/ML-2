"""Research-run orchestrator and CLI.

`python -m quant_research.run --config configs/baseline.yaml`

One coherent pipeline: data -> PIT validation -> features -> walk-forward ->
robustness -> ablation -> placebo -> portfolio/risk -> registry record ->
promotion decision.  Every artifact is written under the output directory.

Integrity rules enforced here:
- robustness stresses re-run the EXACT fold-level OOS trading specification
  (same folds/features/params/thresholds/preprocessing/execution), changing
  only the stressed variable, and never reselect a threshold on test data
- the registry record stores ONE canonical ``robustness`` object whose
  survival flags are exactly what the promotion gates consume
- net/gross accounting is separated end-to-end (gross returns, fees,
  slippage, net returns, Sharpe)
- placebo runs reuse the same walk-forward folds/selection/execution and only
  randomize the intended information; they never touch the research trial count
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import CODE_VERSION
from .config import AppConfig, load_config
from .data.loaders import load_market_data, to_panels
from .data.snapshots import create_run_manifest, get_git_info, save_manifest, save_snapshot
from .data.validation import missing_data_report, validate_ohlcv
from .evaluation.bootstrap import bootstrap_sharpe
from .evaluation.placebo import PLACEBO_MODES, placebo_statistics, run_placebo_null
from .evaluation.robustness import (
    parameter_perturbation,
    regime_analysis,
    robustness_battery,
)
from .evaluation.walk_forward import LockedTestProtocol
from .experiments.leaderboard import build_leaderboard
from .experiments.promotion import evaluate_gates, promotion_decision, stress_survival
from .experiments.registry import ExperimentRegistry, TrialCounter, SearchLedger
from .features.information import build_information_features
from .features.leakage import feature_leakage_report
from .features.price_volume import build_price_volume_features
from .features.point_in_time import validate_events
from .features.registry import registry_hash
from .portfolio.risk import risk_report
from .strategies.baseline import run_walk_forward, summarize_experiment

SYNTHETIC_EVENT_NOTE = "synthetic events for offline exercise of the PIT layer; NOT market evidence"


def generate_synthetic_events(bars_index: pd.DatetimeIndex, symbol: str, seed: int = 7) -> pd.DataFrame:
    """Deterministic synthetic events for offline runs (clearly labelled).

    Availability is deliberately set to event_time + 1 day for a third of the
    events to exercise after-close/next-session semantics.
    """
    rng = np.random.default_rng(seed)
    bars_index = pd.DatetimeIndex(bars_index)
    n = max(len(bars_index) // 20, 10)
    pick = rng.choice(len(bars_index) - 1, size=n, replace=False)
    rows = []
    for i, p in enumerate(pick):
        et = bars_index[p]
        av = et + pd.Timedelta(days=1) if i % 3 == 0 else et
        rows.append({
            "event_id": f"synth-{symbol}-{i}",
            "symbol": symbol,
            "event_time": et,
            "publication_time": et,
            "availability_time": av,
            "source": f"synthetic_source_{i % 3}",
            "raw_value": float(rng.normal()),
            "processed_value": float(rng.normal(0, 0.5)),
            "topic": f"topic_{i % 4}",
            "sentiment": float(rng.normal(0, 0.4)),
            "novelty": float(rng.uniform(0, 1)),
            "revision": 0,
        })
    return pd.DataFrame(rows)


def run_research_pipeline(cfg: AppConfig, output_dir: Optional[str] = None) -> Dict:
    """Execute the full research pipeline; returns the experiment record."""
    out = Path(output_dir or cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: Dict = {"config_fingerprint": cfg.fingerprint()}

    # --- 1. data -------------------------------------------------------------
    ohlcv, data_meta = load_market_data(cfg.data)
    validate_ohlcv(ohlcv)
    missing = missing_data_report(ohlcv)  # exchange-calendar aware
    integrity_ok = bool(
        (missing["n_missing_sessions"] == 0).all()
        and (missing["n_observed_closures"] == 0).all()
    )
    report["data_integrity_report"] = missing
    snapshot_meta = save_snapshot(ohlcv, cfg.data.raw_snapshot_dir, name=f"{cfg.data.mode}_ohlcv")
    dataset_version = snapshot_meta["dataset_hash"]
    close, volume = to_panels(ohlcv)
    report["data_meta"] = data_meta
    report["snapshot_metadata"] = snapshot_meta
    report["ohlcv"] = ohlcv

    # --- 2. point-in-time validation ------------------------------------------
    events = None
    if cfg.data.mode == "synthetic":
        events = generate_synthetic_events(close.index, cfg.data.target)
        events = validate_events(events)  # raises on PIT violations
        report["pit_events_validated"] = True
        report["pit_events_note"] = SYNTHETIC_EVENT_NOTE
    report["events"] = events

    # --- 3. features -----------------------------------------------------------
    price_feats = build_price_volume_features(close, volume, cfg.data.target)
    if events is not None:
        info_feats = build_information_features(close.index, events, cfg.data.target)
        features = price_feats.join(info_feats, how="left")
        info_cols = list(info_feats.columns)
    else:
        features = price_feats
        info_cols = []
    leakage = feature_leakage_report(close, volume, cfg.data.target, info_events=events)
    report["feature_leakage_check"] = leakage
    integrity_ok = integrity_ok and leakage["passed"]

    y = (close[cfg.data.target].shift(-1) > close[cfg.data.target]).astype("float")
    y[close[cfg.data.target].shift(-1).isna()] = np.nan
    fwd = close[cfg.data.target].shift(-1) / close[cfg.data.target] - 1.0
    feature_version = registry_hash(list(features.columns))

        # --- 4. walk-forward baseline (locked test) ---------------------------------
    eval_fp = cfg.evaluation.fingerprint() if hasattr(cfg.evaluation, "fingerprint") else str(cfg.evaluation)
    locked_test = LockedTestProtocol(Path(out) / "test_lock.json",
                                     dataset_id=dataset_version,
                                     config_fingerprint=eval_fp)
    counter = TrialCounter(Path(out) / "trial_counter.json")
    start_count = counter.count  # for trials_this_experiment (per-run delta)

    # B11/C05: durable, output-location-independent search ledger keyed by the
    # research family (dataset + evaluation policy), so repeated research on the
    # same OOS family is visible across artifact directories.  The ledger lives in
    # a shared project location (not under ``out``) so separate output directories
    # still share the same family history.
    # B18/D12: Make shared-ledger location injectable for test isolation.
    # Default remains repo-root/data/research_ledgers for production runs.
    ledger_dir_env = os.environ.get("ML2_LEDGER_DIR")
    if ledger_dir_env:
        shared_ledger_dir = Path(ledger_dir_env)
    else:
        # Derive repo root from this module's location
        _module_root = Path(__file__).parent.parent
        shared_ledger_dir = _module_root / "data" / "research_ledgers"
    shared_ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = SearchLedger(shared_ledger_dir / "search_ledger.jsonl")
    eval_fp = cfg.evaluation.fingerprint() if hasattr(cfg.evaluation, "fingerprint") else str(cfg.evaluation)
    family_id = SearchLedger.family_id(dataset_version, eval_fp)
    n_threshold_trials = len(getattr(cfg.research, "threshold_candidates", [0.5]))
    start_entry = ledger.record_start(family_id, "baseline_threshold_search", n_threshold_trials,
                                      dataset_version, eval_fp, {"stage": "walk_forward_baseline"})
    attempt_id = start_entry.get("attempt_id", "")

    baseline = run_walk_forward(features, y, fwd, cfg, locked_test=locked_test,
                                trial_counter=counter)
    summary = summarize_experiment(baseline)

    ledger.record_outcome(family_id, "baseline_threshold_search", n_threshold_trials,
                          "completed", {"n_folds": len(baseline.folds),
                                        "full_oos_net_sharpe": summary.get("full_oos_net_sharpe")},
                          attempt_id=attempt_id)
    report["folds"] = baseline.folds
    report["baseline_summary"] = summary
    report["search_family_id"] = family_id
    return _finish_pipeline(cfg, out, report, close, volume, price_feats, features,
                            info_cols, y, fwd, baseline, summary, locked_test,
                            counter, start_count, dataset_version, feature_version,
                            integrity_ok, ledger, family_id)


def _finish_pipeline(cfg, out, report, close, volume, price_feats, features, info_cols,
                     y, fwd, baseline, summary, locked_test, counter, start_count,
                     dataset_version, feature_version, integrity_ok,
                     ledger=None, family_id=None) -> Dict:
    """Pipeline stages 5-8: robustness, statistics, ablation, placebo."""

    # --- 5. robustness on the exact OOS execution path ------------------------
    battery = robustness_battery(features, y, fwd, cfg, baseline, locked_test)

    # Pipeline-level reconciliation (fails loudly on ANY discrepancy):
    # - the delay_stress row at the configured delay uses the CONFIGURED cost
    #   assumptions, so its full economics (net/gross Sharpe, fee, slippage) must
    #   equal the baseline OOS execution exactly (C04: the anchor is the configured
    #   delay, not necessarily delay=0);
    # - every delay=0 row of the cost/slippage frames shares the identical
    #   execution path only when the baseline itself has zero configured delay, so
    #   the gross economics must equal the baseline gross only in that case.
    frame_ds = battery["delay_stress"]
    configured_delay = cfg.execution.signal_delay_bars
    # Anchor row: the stress row at the configured delay (may be delay=0 or
    # another value).  When the configured delay is not in the stress grid, the
    # grid's closest value is used as a diagnostic, not a reconciliation anchor.
    anchor = frame_ds[frame_ds["delay_bars"] == configured_delay]
    if anchor.empty:
        # Configured delay not in grid — use the first row as a diagnostic,
        # but do not assert exact reconciliation (the anchor is outside the grid).
        anchor_row = frame_ds.iloc[0]
        anchor_present = False
    else:
        anchor_row = anchor.iloc[0]
        anchor_present = True
    if anchor_present:
        if abs(float(anchor_row["sharpe"]) - summary["full_oos_net_sharpe"]) > 1e-9:
            raise AssertionError(
                f"delay_stress configured-delay row net Sharpe {anchor_row['sharpe']!r} "
                f"does not reconcile with baseline {summary['full_oos_net_sharpe']!r}")
        if abs(float(anchor_row["gross_sharpe"]) - summary["full_oos_gross_sharpe"]) > 1e-9:
            raise AssertionError(
                "delay_stress configured-delay row gross Sharpe does not reconcile "
                "with baseline")
        if abs(float(anchor_row["fee_cost"]) - baseline.fee_costs) > 1e-10 or \
                abs(float(anchor_row["slippage_cost"]) - baseline.slippage_costs) > 1e-10:
            raise AssertionError(
                "delay_stress configured-delay row does not reconcile with baseline "
                "fee/slippage costs")
    # Delay=0 reconciliation is only valid when the baseline has zero configured
    # delay (the delay=0 row then IS the configured-delay anchor).
    if configured_delay == 0:
        zero = frame_ds[frame_ds["delay_bars"] == 0]
        if zero.empty:
            raise AssertionError("delay_stress is missing its delay=0 anchor row")
        row = zero.iloc[0]
        if abs(float(row["sharpe"]) - summary["full_oos_net_sharpe"]) > 1e-9:
            raise AssertionError(
                f"delay_stress delay=0 net Sharpe {row['sharpe']!r} does not reconcile "
                f"with baseline {summary['full_oos_net_sharpe']!r}")
        if abs(float(row["gross_sharpe"]) - summary["full_oos_gross_sharpe"]) > 1e-9:
            raise AssertionError(
                "delay_stress delay=0 gross Sharpe does not reconcile with baseline")
        if abs(float(row["fee_cost"]) - baseline.fee_costs) > 1e-10 or \
                abs(float(row["slippage_cost"]) - baseline.slippage_costs) > 1e-10:
            raise AssertionError(
                "delay_stress delay=0 row does not reconcile with baseline "
                "fee/slippage costs")
    cfg_fee, cfg_slip = cfg.execution.fee_bps, cfg.execution.slippage_bps
    # C04: cost/slippage stress reconciliation uses the configured-delay anchor,
    # not necessarily delay=0.  When configured_delay > 0 the delay=0 rows have
    # different execution timing, so their gross economics differ from the baseline.
    anchor_delay = configured_delay
    for name in ("cost_stress", "slippage_stress"):
        frame = battery[name]
        if frame.empty:
            raise AssertionError(f"{name} battery is empty")
        anchor_rows = frame[frame["delay_bars"] == anchor_delay]
        if anchor_rows.empty:
            continue  # anchor outside grid; nothing to reconcile
        for _, r in anchor_rows.iterrows():
            if abs(float(r["gross_sharpe"]) - summary["full_oos_gross_sharpe"]) > 1e-9:
                raise AssertionError(
                    f"{name} configured-delay gross Sharpe {r['gross_sharpe']!r} does not "
                    f"reconcile with baseline (costs must not change gross)")
            if (abs(float(r["fee_bps"]) - cfg_fee) < 1e-12
                    and abs(float(r["slippage_bps"]) - cfg_slip) < 1e-12):
                if abs(float(r["sharpe"]) - summary["full_oos_net_sharpe"]) > 1e-9:
                    raise AssertionError(
                        f"{name} configured-delay row at configured assumptions does not "
                        f"reconcile with baseline net Sharpe")
                if abs(float(r["fee_cost"]) - baseline.fee_costs) > 1e-10 or \
                        abs(float(r["slippage_cost"]) - baseline.slippage_costs) > 1e-10:
                    raise AssertionError(
                        f"{name} configured-delay row at configured assumptions does not "
                        f"reconcile with baseline fee/slippage costs")

    report["cost_stress"] = battery["cost_stress"]
    report["slippage_stress"] = battery["slippage_stress"]
    report["delay_stress"] = battery["delay_stress"]
    report["parameter_perturbation"] = battery["parameter_perturbation"]
    report["missing_data_stress"] = battery["missing_data"]
    signal = baseline.predictions["prob"]
    regime_flags = pd.DataFrame({
        "high_vol": price_feats["regime_high_vol"].reindex(signal.index),
        "drawdown_deep": (price_feats["regime_drawdown"] < -0.05)
            .astype(float).reindex(signal.index),
    })
    report["regime"] = regime_analysis(baseline.oos_returns, regime_flags)

    # canonical robustness object (single source of truth for record + gates)
    robustness = {
        "cost_stress": battery["cost_stress"].to_dict("records"),
        "slippage_stress": battery["slippage_stress"].to_dict("records"),
        "delay_stress": battery["delay_stress"].to_dict("records"),
        "parameter_perturbation": battery["parameter_perturbation"].to_dict("records"),
        "missing_data": battery["missing_data"].to_dict("records"),
    }
    robustness.update(stress_survival(robustness, cfg.promotion))
    report["robustness"] = robustness

    # --- 6. bootstrap, ablation, empirical null ---------------------------------
    boot = bootstrap_sharpe(baseline.oos_returns, seed=cfg.model.random_seed,
                            research=cfg.research)
    report["bootstrap"] = boot

    def _summarize(feats: pd.DataFrame) -> dict:
        return summarize_experiment(run_walk_forward(feats, y, fwd, cfg,
                                                     locked_test=locked_test))

    def _run_pipeline(X, yy, ff):
        """Full pass-through pipeline for placebo: uses the permuted inputs."""
        return summarize_experiment(run_walk_forward(X, yy, ff, cfg,
                                                     locked_test=locked_test))

    price_only = _summarize(price_feats)
    metric_keys = ("mean_oos_sharpe", "median_oos_sharpe", "mean_oos_auc", "mean_oos_brier")
    ablation = [{"source": "price_volume", **{k: price_only[k] for k in metric_keys}}]
    if info_cols:
        ablation.append({
            "source": "price_plus_information",
            **{k: summary[k] for k in metric_keys},
            "delta_sharpe_vs_price_only": summary["mean_oos_sharpe"] - price_only["mean_oos_sharpe"],
        })
    report["ablation"] = pd.DataFrame(ablation)

    nulls = {}
    for mode in PLACEBO_MODES:
        nulls[mode] = run_placebo_null(
            features, y, fwd, _run_pipeline, n_runs=cfg.research.placebo_runs,
            seed=cfg.model.random_seed, mode=mode,
        )
    report["placebo_null"] = nulls["shuffle_features"]
    report["placebo_permute_target"] = nulls["permute_target"]
    report["placebo_block_permute"] = nulls["block_permute"]
    placebo = placebo_statistics(summary["mean_oos_sharpe"], nulls["shuffle_features"])
    report["placebo_statistics"] = placebo
    report["placebo_mode_statistics"] = {
        mode: placebo_statistics(summary["mean_oos_sharpe"], null)
        for mode, null in nulls.items()
    }

    # --- 7. portfolio / risk ------------------------------------------------------
    # Risk diagnostics describe the ACTUAL executed portfolio: the continuous
    # OOS position ledger (real per-fold thresholds, execution lag, vol sizing
    # -- not a 0.55 probability proxy) and the forward-return benchmark
    # aligned to the interval the strategy actually earns (A14).
    oos_idx = baseline.oos_returns.index
    risk = risk_report(
        baseline.oos_returns,
        weights=baseline.oos_positions.reindex(oos_idx),
        benchmark=fwd.reindex(oos_idx),
    )
    report["risk"] = risk
    return _register_and_decide(cfg, out, report, baseline, summary, robustness, boot,
                                placebo, counter, start_count, dataset_version,
                                feature_version, info_cols, integrity_ok, features,
                                ledger, family_id)


def _register_and_decide(cfg, out, report, baseline, summary, robustness, boot,
                         placebo, counter, start_count, dataset_version, feature_version,
                         info_cols, integrity_ok, features, ledger, family_id) -> Dict:
    """Stage 8: registry record + promotion decision + artifact export."""
    annual_turnover = float(baseline.folds["oos_turnover"].sum()
                            / max(len(baseline.oos_returns) / 252.0, 1e-9))
    checks = evaluate_gates(
        {**summary, "annual_turnover": annual_turnover},
        robustness, boot, placebo, integrity_ok,
        report["feature_leakage_check"]["passed"], counter.count, cfg.promotion,
        n_family_searches=(ledger.family_attempt_count(family_id) if ledger else 0),
    )
    decision = promotion_decision(checks)
    folds = baseline.folds
    record = {
        "strategy": "walk_forward_baseline",
        "data_mode": cfg.data.mode,
        "features": sorted(features.columns),
        "universe": cfg.data.assets,
        "target": cfg.data.target,
        "timeframe": cfg.data.frequency,
        "train_period": [str(folds["train_start"].min()), str(folds["train_end"].max())],
        "validation_period": [str(folds["val_start"].min()), str(folds["val_end"].max())],
                "test_period": [str(folds["test_start"].min()), str(folds["test_end"].max())],
        "trials": int(counter.count),
        "n_trials_global": int(counter.count),
        "trials_this_experiment": int(counter.count - start_count),
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "strategy_version": "baseline-2.1.3",
        "code_version": CODE_VERSION,
        "seed": cfg.model.random_seed,
        "config_fingerprint": cfg.fingerprint(),
        "gross_metrics": {
            "full_oos_sharpe": summary["full_oos_gross_sharpe"],
            "full_oos_return": summary["full_oos_gross_return"],
        },
        "net_metrics": {
            "full_oos_sharpe": summary["full_oos_net_sharpe"],
            "full_oos_return": summary["full_oos_net_return"],
            "fee_cost": summary["fee_cost"],
            "slippage_cost": summary["slippage_cost"],
            "cost_drag": summary["cost_drag"],
        },
        "costs": {"fee_bps": cfg.execution.fee_bps, "slippage_bps": cfg.execution.slippage_bps},
        "slippage": {"applied_bps": cfg.execution.slippage_bps},
        "oos_metrics": summary,
        "bootstrap_interval": boot,
        "robustness": robustness,
        "placebo_statistics": placebo,
        "information_sources": ["price_volume"] + (["information"] if info_cols else []),
        "promotion_state": decision["state"],
        "failed_gates": decision["failed_gates"],
        # B11: research-family identity + durable search-ledger locator, so the
        # same OOS family can be recognized across artifact directories and the
        # full search history audited.
        "search_family_id": family_id,
        "search_ledger": str(ledger.path) if ledger else None,
        "search_correction_method": cfg.promotion.selection_correction,
        "evidence_status": "SYNTHETIC_OFFLINE" if cfg.data.mode == "synthetic" else "REAL_DATA",
    }
    registry = ExperimentRegistry(Path(out) / "experiment_registry.jsonl")
    stored = registry.record(record)
    report["experiment_record"] = stored
    report["promotion"] = decision
    report["leaderboard"] = build_leaderboard(registry)

    # B16: Create and save complete reproducibility manifest
    git_rev, git_dirty = get_git_info()
    env_info = {
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": __import__("sklearn").__version__,
    }
    try:
        import scipy
        env_info["scipy"] = scipy.__version__
    except ImportError:
        pass

    manifest = create_run_manifest(
        cfg=cfg,
        ohlcv=report["ohlcv"],
        snapshot_meta=report["snapshot_metadata"],
        features=features,
        events=report.get("events"),
        baseline=baseline,
        robustness=robustness,
        placebo=placebo,
        bootstrap=boot,
        summary=summary,
        experiment_record=stored,
        git_revision=git_rev,
        git_dirty=git_dirty,
        environment=env_info,
        output_dir=out,
    )
    manifest_path = save_manifest(manifest, out, experiment_id=stored["experiment_id"])
    # C15: the manifest locator points to the immutable experiment-specific file.
    report["manifest_path"] = str(manifest_path)

    _write_artifacts(out, report)
    return report


def _write_artifacts(out: Path, report: Dict) -> None:
    exp = report["experiment_record"]
    stamp = exp["experiment_id"]
    report["folds"].to_csv(out / f"{stamp}_folds.csv", index=False)
    frame_keys = ("cost_stress", "slippage_stress", "delay_stress",
                  "parameter_perturbation", "missing_data_stress", "regime",
                  "ablation", "placebo_null", "placebo_permute_target",
                  "placebo_block_permute", "data_integrity_report")
    skip = {"folds", "leaderboard"} | set(frame_keys)
    serializable = {k: v for k, v in report.items() if k not in skip}
    for k in frame_keys:
        if k in report:
            serializable[k] = report[k].to_dict("records")
    serializable["leaderboard"] = report["leaderboard"].to_dict("records")

    def _default(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, pd.Timestamp):
            return o.isoformat()
        return str(o)

    (out / f"{stamp}_results.json").write_text(
        json.dumps(serializable, indent=2, default=_default), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Institutional Quant Research Engine V2.1")
    parser.add_argument("--config", default=None, help="YAML config path")
    parser.add_argument("--output", default=None, help="output directory override")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    report = run_research_pipeline(cfg, args.output)
    exp = report["experiment_record"]
    print(f"experiment_id: {exp['experiment_id']}")
    print(f"evidence_status: {exp['evidence_status']}")
    print(f"promotion_state: {exp['promotion_state']}")
    if exp["failed_gates"]:
        print("failed gates:", ", ".join(exp["failed_gates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

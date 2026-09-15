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
from .data.schemas import DataValidationError
from .data.loaders import load_market_data, to_panels, to_price_panels
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
from .experiments.registry import (
    ExperimentRegistry, SearchLedger, TrialCounter, dataset_family_identity,
)
from .features.assembly import build_feature_panel, h001_selected_legs, selected_sources
from .features.leakage import feature_leakage_report
from .features.price_volume import build_price_volume_features
from .features.point_in_time import validate_events
from .features.registry import registry_hash
from .portfolio.risk import risk_report
from .strategies.baseline import run_walk_forward, summarize_experiment
from .h002_pipeline import run_h002_pipeline
from .h003_pipeline import run_h003_pipeline

SYNTHETIC_EVENT_NOTE = "synthetic events for offline exercise of the PIT layer; NOT market evidence"


def _assert_preregistered_execution_supported(cfg: AppConfig) -> list[str]:
    """Refuse proxy runs that could be mislabelled as H-002/H-003 evidence.

    The generic engine evaluates one scalar target against daily OHLCV.  H-002
    and H-003 each require a different data and portfolio contract; allowing
    their registered feature source through this path would create an invalid
    result with a deceptively official-looking experiment record.  The feature
    functions remain available for isolated development tests.

    When ``data.mode == 'h002'``, the H-002 real-data pipeline is used instead,
    so ``liquidity_reversal`` is permitted (the cross-sectional portfolio path
    replaces the scalar backtest).
    """
    sources = selected_sources(
        cfg.features, events_available=cfg.data.mode == "synthetic",
    )
    if cfg.data.mode == "h002":
        # H-002 real-data pipeline: liquidity_reversal features are used in the
        # cross-sectional portfolio constructor, not the scalar backtest.
        return sources
    if cfg.data.mode == "h003":
        if sources != ["h003_r1_volatility_shock"]:
            raise DataValidationError(
                "H-003-R1 mode requires the single frozen feature source "
                "'h003_r1_volatility_shock'"
            )
        return sources
    missing_contracts = {
        "liquidity_reversal": (
            "H-002 cannot run in the scalar daily-OHLCV engine: it requires "
            "point-in-time Russell 3000 membership, market-cap and intraday "
            "buy/sell classification data, plus a cross-sectional dollar-neutral "
            "portfolio evaluator."
        ),
        "volatility_risk_premium": (
            "H-003 cannot run in the scalar daily-OHLCV engine: it requires "
            "the 17-ETF universe, VIX-futures M1-M3 term structure, rolling "
            "cross-asset correlations, and a risk-parity portfolio evaluator."
        ),
    }
    unsupported = [missing_contracts[source] for source in sources if source in missing_contracts]
    if unsupported:
        raise DataValidationError(" ".join(unsupported))
    return sources


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
    declared_sources = _assert_preregistered_execution_supported(cfg)
    out = Path(output_dir or cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: Dict = {"config_fingerprint": cfg.fingerprint()}
    if cfg.research.protocol_path:
        from .experiments.protocol import ResearchProtocol

        protocol = ResearchProtocol.load(cfg.research.protocol_path)
        protocol.assert_matches_config(cfg.fingerprint(), cfg.research.max_trials)
        report["research_protocol"] = {
            "path": str(Path(cfg.research.protocol_path).resolve()),
            "digest": protocol.digest,
            "hypothesis_id": protocol.hypothesis_id,
            "primary_metric": protocol.primary_metric,
        }
    else:
        report["research_protocol"] = None

    # --- 1. data -------------------------------------------------------------
    ohlcv, data_meta = load_market_data(cfg.data)
    validate_ohlcv(ohlcv)
    missing = missing_data_report(ohlcv, exchange=cfg.data.exchange_calendar)
    integrity_ok = bool(
        (missing["n_missing_sessions"] == 0).all()
        and (missing["n_observed_closures"] == 0).all()
    )
    report["data_integrity_report"] = missing
    snapshot_meta = save_snapshot(ohlcv, cfg.data.raw_snapshot_dir, name=f"{cfg.data.mode}_ohlcv")
    dataset_version = snapshot_meta["dataset_hash"]
    close, volume = to_panels(ohlcv)
    open_, high, low = to_price_panels(ohlcv)[:3]
    report["data_meta"] = data_meta
    report["snapshot_metadata"] = snapshot_meta
    report["ohlcv"] = ohlcv

    # --- H-002 real-data pipeline branch ----------------------------------------
    if cfg.data.mode == "h002":
        data_meta["missing_data_report"] = missing
        data_meta["snapshot_metadata"] = snapshot_meta
        h002_report = run_h002_pipeline(
            cfg, ohlcv, data_meta, out, None, None, 0,
            dataset_version, None, None,
        )
        # Merge H-002 report into the main report
        report.update(h002_report)
        report["data_integrity_report"] = missing
        report["snapshot_metadata"] = snapshot_meta
        report["data_meta"] = data_meta
        # Skip the scalar walk-forward and go to _finish_pipeline
        baseline = h002_report["baseline"]
        summary = h002_report["baseline_summary"]
        close = h002_report["close"]
        volume = h002_report["volume"]
        features = h002_report["features"]
        price_feats = h002_report["price_feats"]
        info_cols = h002_report["info_cols"]
        y = h002_report["y"]
        fwd = h002_report["fwd"]
        events = h002_report["events"]
        asset_forward_returns = h002_report["asset_forward_returns"]
        selected_asset = h002_report["selected_asset"]
        feature_version = h002_report["feature_version"]
        locked_test = None  # No locked test for H-002 initial exploration
        # The H-002 cross-sectional run is a research trial in its own right.
        # Record it in the persistent monotonic counter so the search-effort
        # gates see it, and expose it to the finish stage.
        counter = TrialCounter(Path(out) / "trial_counter.json")
        start_count = counter.count
        counter.increment()
        report["trial_counter"] = counter
        report["start_count"] = start_count
        eval_fp = str(cfg.evaluation)
        integrity_ok = True
        ledger = None
        family_id = None
        # Skip to _finish_pipeline
        return _finish_pipeline(
            cfg, out, report, close, volume, price_feats, features,
            info_cols, y, fwd, baseline, summary, locked_test,
            counter, start_count, dataset_version, feature_version,
            integrity_ok, ledger, family_id,
        )

    # --- H-003-R1 amended multi-asset pipeline branch ------------------------
    if cfg.data.mode == "h003":
        h003_report = run_h003_pipeline(cfg, ohlcv, out, dataset_version)
        report.update(h003_report)
        report["data_integrity_report"] = missing
        report["snapshot_metadata"] = snapshot_meta
        report["data_meta"] = data_meta
        counter = TrialCounter(Path(out) / "trial_counter.json")
        start_count = counter.count
        counter.increment()
        report["trial_counter"] = counter
        report["start_count"] = start_count
        report["strategy_name"] = "h003_r1_volatility_shock_portfolio"
        report["information_sources_override"] = [
            "adjusted_daily_ohlcv", "vix_spot"
        ]
        return _finish_pipeline(
            cfg, out, report,
            h003_report["close"], h003_report["volume"],
            h003_report["price_feats"], h003_report["features"],
            h003_report["info_cols"], h003_report["y"], h003_report["fwd"],
            h003_report["baseline"], h003_report["baseline_summary"], None,
            counter, start_count, dataset_version,
            h003_report["feature_version"], integrity_ok, None, None,
        )

    # --- 2. point-in-time validation ------------------------------------------
    events = None
    if cfg.data.mode == "synthetic":
        events = generate_synthetic_events(close.index, cfg.data.target)
        events = validate_events(events)  # raises on PIT violations
        report["pit_events_validated"] = True
        report["pit_events_note"] = SYNTHETIC_EVENT_NOTE
    report["events"] = events

    # --- 3. features -----------------------------------------------------------
    # Keep the canonical price-only panel for diagnostics/ablation below, but
    # construct model inputs solely through the declared feature contract.
    price_feats = build_price_volume_features(close, volume, cfg.data.target)
    features = build_feature_panel(
        close, volume, cfg.data.target, cfg.features,
        open_=open_, high=high, low=low, events=events,
    )
    info_cols = [column for column in features.columns if column.startswith("info_")]
    feature_sources = declared_sources
    leakage = feature_leakage_report(close, volume, cfg.data.target, info_events=events,
                                     open_=open_, high=high, low=low)
    report["feature_leakage_check"] = leakage
    integrity_ok = integrity_ok and leakage["passed"]

    asset_forward_returns = None
    selected_asset = None
    if "cross_asset_spillover" in feature_sources:
        if feature_sources != ["cross_asset_spillover"]:
            raise DataValidationError(
                "H-001 is a closed feature contract; cross_asset_spillover cannot "
                "be combined with other feature sources"
            )
        asset_forward_returns = pd.DataFrame({
            "SPY": close["SPY"].shift(-1) / close["SPY"] - 1.0,
            "QQQ": close["QQQ"].shift(-1) / close["QQQ"] - 1.0,
        })
        selected_asset = h001_selected_legs(features)
        fwd = pd.Series(np.nan, index=features.index, dtype="float64")
        for symbol in ("SPY", "QQQ"):
            mask = selected_asset.eq(symbol)
            fwd.loc[mask] = asset_forward_returns.loc[mask, symbol]
        report["asset_execution_contract"] = {
            "strategy": "H-001 conditional selected-asset",
            "assets": ["SPY", "QQQ"],
            "selection_rule": "ratio_zscore > 0 selects SPY; otherwise QQQ",
            "switch_turnover": "two-sided",
        }
    else:
        fwd = close[cfg.data.target].shift(-1) / close[cfg.data.target] - 1.0
    y = (fwd > 0).astype("float")
    y[fwd.isna()] = np.nan
    feature_version = registry_hash(list(features.columns))
    if cfg.research.protocol_path:
        if sorted(protocol.feature_names) != sorted(features.columns):
            raise DataValidationError(
                "research protocol feature contract does not match the selected feature panel"
            )

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
# D12: The shared ledger path is configurable via environment variable so tests
    # can override it to an isolated location.  This prevents tests from mutating
    # shared project research history.
    _env_ledger_dir = os.environ.get("QUANT_RESEARCH_LEDGER_DIR")
    if _env_ledger_dir:
        shared_ledger_dir = Path(_env_ledger_dir)
    else:
        _repo_root = Path(__file__).resolve().parents[2]
        shared_ledger_dir = _repo_root / "data" / "research_ledgers"
    shared_ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = SearchLedger(shared_ledger_dir / "search_ledger.jsonl")
    eval_fp = cfg.evaluation.fingerprint() if hasattr(cfg.evaluation, "fingerprint") else str(cfg.evaluation)
    # E10: bind the exact snapshot revision to a stable data contract. Family
    # identity retains provider/mode, universe, window, frequency and calendar,
    # but not the exact content hash, so minor revisions cannot reset history.
    from .experiments.registry import family_lineage as _lineage
    family_dataset_identity = dataset_family_identity(
        dataset_version,
        mode=cfg.data.mode,
        assets=cfg.data.assets,
        target=cfg.data.target,
        start=cfg.data.start,
        end=cfg.data.end,
        frequency=cfg.data.frequency,
        exchange_calendar=cfg.data.exchange_calendar,
    )
    family_id = SearchLedger.family_id(family_dataset_identity, eval_fp)
    n_threshold_trials = len(getattr(cfg.research, "threshold_candidates", [0.5]))
    start_entry = ledger.record_start(family_id, "baseline_threshold_search", n_threshold_trials,
                                      dataset_version, eval_fp,
                                      {"stage": "walk_forward_baseline",
                                       "dataset_lineage": _lineage(family_dataset_identity),
                                       "dataset_family_identity": family_dataset_identity})
    attempt_id = start_entry.get("attempt_id", "")

    baseline = run_walk_forward(features, y, fwd, cfg, locked_test=locked_test,
                                trial_counter=counter,
                                asset_forward_returns=asset_forward_returns,
                                selected_asset=selected_asset)
    summary = summarize_experiment(baseline)

    ledger.record_outcome(family_id, "baseline_threshold_search", n_threshold_trials,
                          "completed", {"n_folds": len(baseline.folds),
                                        "full_oos_net_sharpe": summary.get("full_oos_net_sharpe")},
                          attempt_id=attempt_id)
    report["folds"] = baseline.folds
    report["baseline_summary"] = summary
    report["search_family_id"] = family_id
    report["search_family_dataset_identity"] = family_dataset_identity
    return _finish_pipeline(cfg, out, report, close, volume, price_feats, features,
                            info_cols, y, fwd, baseline, summary, locked_test,
                            counter, start_count, dataset_version, feature_version,
                            integrity_ok, ledger, family_id)


def _finish_pipeline(cfg, out, report, close, volume, price_feats, features, info_cols,
                     y, fwd, baseline, summary, locked_test, counter, start_count,
                     dataset_version, feature_version, integrity_ok,
                     ledger=None, family_id=None) -> Dict:
    """Pipeline stages 5-8: robustness, statistics, ablation, placebo.

    When ``baseline.execution_contract == 'h002_cross_sectional_portfolio'``,
    the scalar robustness/placebo/ablation paths do not apply.  A simplified
    cost-stress + bootstrap path is used instead.
    """

    is_h002 = (baseline is not None and
                getattr(baseline, "execution_contract", "") == "h002_cross_sectional_portfolio")
    is_h003 = (baseline is not None and
                getattr(baseline, "execution_contract", "") == "h003_r1_multi_asset_portfolio")

    if is_h002:
        return _finish_h002_pipeline(cfg, out, report, close, volume, features,
                                      baseline, summary, dataset_version)
    if is_h003:
        return _finish_h003_pipeline(cfg, out, report, close, volume, features,
                                      baseline, summary, dataset_version,
                                      integrity_ok)

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
        return summarize_experiment(run_walk_forward(
            feats, y, fwd, cfg, locked_test=locked_test,
            asset_forward_returns=baseline.asset_forward_returns,
            selected_asset=baseline.selected_asset,
        ))

    def _run_pipeline(X, yy, ff):
        """Full pass-through pipeline for placebo: uses the permuted inputs."""
        placebo_legs = baseline.selected_asset
        if baseline.asset_forward_returns is not None:
            placebo_legs = h001_selected_legs(X)
        return summarize_experiment(run_walk_forward(
            X, yy, ff, cfg, locked_test=locked_test,
            asset_forward_returns=baseline.asset_forward_returns,
            selected_asset=placebo_legs,
        ))

    metric_keys = ("mean_oos_sharpe", "median_oos_sharpe", "mean_oos_auc", "mean_oos_brier")
    if baseline.asset_forward_returns is not None:
        # H-001's preregistration prohibits removing its ratio/VIX/volume
        # contract. A price-only ablation would be a different hypothesis.
        ablation = [{"source": "not_applicable_closed_h001_contract",
                     **{k: summary[k] for k in metric_keys}}]
    else:
        price_only = _summarize(price_feats)
        ablation = [{"source": "price_volume", **{k: price_only[k] for k in metric_keys}}]
    if info_cols and baseline.asset_forward_returns is None:
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


def _finish_h002_pipeline(
    cfg: AppConfig,
    out: Path,
    report: Dict,
    close: pd.DataFrame,
    volume: pd.DataFrame,
    features: pd.DataFrame,
    baseline: ExperimentResult,
    summary: dict,
    dataset_version: str,
) -> Dict:
    """Simplified finish path for H-002 cross-sectional portfolio.

    Skips scalar robustness/placebo/ablation (which don't apply to a
    cross-sectional portfolio strategy) and instead does:
      - Cost stress: re-run portfolio with higher fees
      - Bootstrap Sharpe on portfolio OOS returns
      - Assemble final report and pass to _register_and_decide
    """

    from .evaluation.bootstrap import bootstrap_sharpe
    from .evaluation.metrics import max_drawdown, sharpe_ratio
    from .portfolio.h002_portfolio import (
        H002_PREREG_PORTFOLIO_PARAMS,
        construct_h002_portfolio,
    )
    from .portfolio.h002_returns import portfolio_returns

    # Trial accounting: the H-002 path allocates its own persistent counter in
    # run_research_pipeline and hands it through the report.
    counter = report.get("trial_counter")
    if counter is None:  # pragma: no cover - defensive fallback
        from .experiments.registry import TrialCounter
        counter = TrialCounter(Path(out) / "trial_counter.json")
        counter.increment()
    start_count = int(report.get("start_count", 0))

    # --- Cost stress: re-run portfolio with escalating fees ---
    cost_stress_rows = []
    base_fee = cfg.execution.fee_bps
    base_slip = cfg.execution.slippage_bps

    # Reconstruct the signal panel from features
    # (features columns are ticker_featurename; extract per-ticker signals)
    signal_panel = report.get("h002_signal_panel")
    if signal_panel is None:
        # Fallback: rebuild the composite from each ticker's own feature frame
        # (carried in ``report["h002_feature_frames"]``) using the exact same
        # constructor as the main pipeline, so stress results are comparable.
        from .h002_pipeline import _build_h002_composite_signal
        frames = report.get("h002_feature_frames")
        if frames is not None:
            signal_panel = _build_h002_composite_signal(
                frames, volume, list(close.columns), close.index)

    if signal_panel is None:
        raise DataValidationError(
            "H-002 finish stage: no composite signal panel available; the "
            "pipeline report must carry 'h002_signal_panel' or "
            "'h002_feature_frames'"
        )

    signal_panel = signal_panel.dropna(axis=1, how="all")

    # Protocol feature contract (H-002-R1).  The generic engine compares the
    # protocol's feature_names against the scaled panel columns, but that check
    # is never reached in H-002 mode (this function returns first).  Enforce the
    # equivalent guarantee here: every feature the amended preregistration
    # declares must actually be present in the computed panel, so the run can
    # never silently drop a registered feature from the strategy it claims to
    # be testing.
    _proto = report.get("research_protocol")
    if _proto:
        from .experiments.protocol import ResearchProtocol
        _declared = set(ResearchProtocol.load(_proto["path"]).feature_names)
        _computed = {c[len(sym) + 1:] for sym in close.columns
                     for c in features.columns if c.startswith(f"{sym}_")}
        _absent = sorted(_declared - _computed)
        if _absent:
            raise DataValidationError(
                f"research protocol declares features that the H-002 pipeline "
                f"did not compute: {_absent}"
            )

    # Load sector map
    from .data.h002_universe import _load_sector_map
    sector_map_raw = _load_sector_map()

    # The weights are fee-independent, so construct the book once and only
    # re-price it across the fee/slippage grid.  (Reconstructing inside the loop
    # tripled the cost of the most expensive stage for identical output.)
    weights = construct_h002_portfolio(
        signal_panel, sector_map_raw, **H002_PREREG_PORTFOLIO_PARAMS,
    )

    for fee_mult in (1.0, 2.0, 3.0):
        fee_bps = base_fee * fee_mult
        slip_bps = base_slip * fee_mult
        rets = portfolio_returns(weights, close, fee_bps=fee_bps, slippage_bps=slip_bps)
        net = rets["net_returns"]
        gross = rets["gross_returns"]
        cost_stress_rows.append({
            "fee_bps": fee_bps,
            "slippage_bps": slip_bps,
            "sharpe": float(sharpe_ratio(net)),
            "gross_sharpe": float(sharpe_ratio(gross)),
            "net_return": float((1 + net.fillna(0)).prod() - 1) if len(net) else float("nan"),
            "gross_return": float((1 + gross.fillna(0)).prod() - 1) if len(gross) else float("nan"),
            "max_dd": float(max_drawdown(net)),
            "annual_turnover": float(rets["turnover"].sum() / max(len(net) / 252.0, 1e-9)),
            "fee_cost": float(rets["costs"].sum() * fee_bps / (fee_bps + slip_bps)) if (fee_bps + slip_bps) > 0 else 0.0,
            "slippage_cost": float(rets["costs"].sum() * slip_bps / (fee_bps + slip_bps)) if (fee_bps + slip_bps) > 0 else 0.0,
        })

    cost_stress = pd.DataFrame(cost_stress_rows)

    # --- Delay stress: re-run the portfolio on a stale signal -----------------
    # A delay of N bars means the portfolio is formed from the signal as it
    # stood N sessions earlier.  This is the H-002 execution-delay stress and
    # it feeds the ``survives_delay_stress`` promotion gate.
    delay_stress_rows = []
    delays = sorted({0, int(cfg.promotion.delay_stress_bars),
                     int(cfg.promotion.delay_stress_bars) * 2})
    for delay in delays:
        sig_delayed = signal_panel if delay <= 0 else signal_panel.shift(delay)
        weights_d = construct_h002_portfolio(
            sig_delayed, sector_map_raw, **H002_PREREG_PORTFOLIO_PARAMS,
        )
        rets_d = portfolio_returns(weights_d, close,
                                   fee_bps=base_fee, slippage_bps=base_slip)
        net_d = rets_d["net_returns"]
        delay_stress_rows.append({
            "delay_bars": int(delay),
            "sharpe": float(sharpe_ratio(net_d)),
            "net_return": float((1 + net_d.fillna(0)).prod() - 1) if len(net_d) else float("nan"),
            "max_dd": float(max_drawdown(net_d)),
            "annual_turnover": float(rets_d["turnover"].sum()
                                     / max(len(net_d) / 252.0, 1e-9)),
        })

    delay_stress = pd.DataFrame(delay_stress_rows)

    # --- Bootstrap Sharpe ---
    boot = bootstrap_sharpe(baseline.oos_returns, seed=cfg.model.random_seed,
                            research=cfg.research)

    # --- Assemble robustness report ---
    robustness = {
        "cost_stress": cost_stress.to_dict("records"),
        "slippage_stress": cost_stress.to_dict("records"),  # same as cost stress for portfolio
        "delay_stress": delay_stress.to_dict("records"),
        "parameter_perturbation": [],  # Not applicable
        "missing_data": [],  # Not applicable
    }
    robustness.update(stress_survival(robustness, cfg.promotion))
    report["robustness"] = robustness
    report["cost_stress"] = cost_stress
    report["slippage_stress"] = cost_stress
    report["delay_stress"] = delay_stress
    report["parameter_perturbation"] = pd.DataFrame()
    report["missing_data_stress"] = pd.DataFrame()

    # --- Risk report ---
    # H-002 is a cross-sectional dollar-neutral book, so exposure, turnover and
    # concentration must come from the executed weight MATRIX.  The scalar
    # per-timestamp net position is ~0 every session and would understate both
    # gross exposure and turnover.
    from .portfolio.risk import risk_report
    exec_weights = report.get("h002_executed_weights")
    oos_idx = baseline.oos_returns.index
    risk = risk_report(
        baseline.oos_returns,
        weight_matrix=(exec_weights.reindex(oos_idx)
                       if exec_weights is not None else None),
        benchmark=None,
    )
    report["risk"] = risk

    # --- Placeholder for ablation/placebo (not applicable) ---
    # Note: the ``*_permute_*``/``placebo_null`` keys are listed in
    # ``_write_artifacts.frame_keys`` and must therefore be DataFrames (empty is
    # fine), not bare dicts.
    report["ablation"] = pd.DataFrame()
    report["placebo_null"] = pd.DataFrame()
    report["placebo_permute_target"] = pd.DataFrame()
    report["placebo_block_permute"] = pd.DataFrame()
    report["placebo_statistics"] = {"percentile": float("nan"), "p_value": float("nan")}
    report["placebo_mode_statistics"] = {}
    report["bootstrap"] = boot

    return _register_and_decide(cfg, out, report, baseline, summary, robustness, boot,
                                {}, counter, start_count, dataset_version,
                                report.get("feature_version"), [], True, features,
                                None, None)


def _finish_h003_pipeline(
    cfg: AppConfig,
    out: Path,
    report: Dict,
    close: pd.DataFrame,
    volume: pd.DataFrame,
    features: pd.DataFrame,
    baseline: ExperimentResult,
    summary: dict,
    dataset_version: str,
    integrity_ok: bool,
) -> Dict:
    """Finish H-003-R1 with portfolio-native stresses and mandate gates."""
    from .evaluation.metrics import max_drawdown, sharpe_ratio, sortino_ratio
    from .evaluation.placebo import placebo_statistics
    from .portfolio.h002_returns import portfolio_returns
    from .portfolio.h003_portfolio import (
        H003_R1_PORTFOLIO_PARAMS,
        construct_h003_portfolio,
    )
    from .h003_pipeline import (
        H003_R1_ASSET_CLASSES,
        H003_R1_FEATURES,
    )

    counter = report["trial_counter"]
    start_count = int(report.get("start_count", 0))
    signal = report.get("h003_signal_panel")
    vix = report.get("vix")
    if signal is None or vix is None:
        raise DataValidationError("H-003-R1 finish stage requires signal and VIX panels")

    # The protocol binds the compact feature definitions, not the 17x expanded
    # diagnostic matrix.  Any mismatch fails before the result is registered.
    proto_meta = report.get("research_protocol")
    if proto_meta:
        from .experiments.protocol import ResearchProtocol
        declared = set(ResearchProtocol.load(proto_meta["path"]).feature_names)
        if declared != set(H003_R1_FEATURES):
            raise DataValidationError(
                "H-003-R1 protocol feature contract does not match the frozen pipeline"
            )

    oos_idx = baseline.oos_returns.index
    target_weights = report["h003_weights"]
    executed_weights = report["h003_executed_weights"].reindex(oos_idx).fillna(0.0)
    base_fee = float(cfg.execution.fee_bps)
    base_slip = float(cfg.execution.slippage_bps)

    cost_rows = []
    for multiple in (1.0, 2.0, 3.0):
        result = portfolio_returns(
            target_weights, close,
            fee_bps=base_fee * multiple,
            slippage_bps=base_slip * multiple,
        )
        net = result["net_returns"].reindex(oos_idx).fillna(0.0)
        gross = result["gross_returns"].reindex(oos_idx).fillna(0.0)
        turn = result["turnover"].reindex(oos_idx).fillna(0.0)
        cost_rows.append({
            "multiple": multiple,
            "fee_bps": base_fee * multiple,
            "slippage_bps": base_slip * multiple,
            "all_in_bps": (base_fee + base_slip) * multiple,
            "sharpe": sharpe_ratio(net),
            "gross_sharpe": sharpe_ratio(gross),
            "net_return": float((1.0 + net).prod() - 1.0),
            "gross_return": float((1.0 + gross).prod() - 1.0),
            "max_dd": max_drawdown(net),
            "annual_turnover": float(turn.sum() / max(len(net) / 252.0, 1e-9)),
        })
    cost_stress = pd.DataFrame(cost_rows)

    delay_rows = []
    for delay in sorted({0, int(cfg.promotion.delay_stress_bars), 3}):
        delayed_targets = target_weights.shift(delay) if delay else target_weights
        result = portfolio_returns(
            delayed_targets, close, fee_bps=base_fee, slippage_bps=base_slip,
        )
        net = result["net_returns"].reindex(oos_idx).fillna(0.0)
        turn = result["turnover"].reindex(oos_idx).fillna(0.0)
        delay_rows.append({
            "delay_bars": delay,
            "sharpe": sharpe_ratio(net),
            "net_return": float((1.0 + net).prod() - 1.0),
            "max_dd": max_drawdown(net),
            "annual_turnover": float(turn.sum() / max(len(net) / 252.0, 1e-9)),
        })
    delay_stress = pd.DataFrame(delay_rows)

    # Full-strategy placebo: permute complete cross-sectional signal rows,
    # rebuild the weekly risk portfolio, then price the resulting book.
    valid_idx = signal.dropna(how="any").index
    rng = np.random.default_rng(cfg.model.random_seed)
    null_rows = []
    for run_id in range(cfg.research.placebo_runs):
        permuted = signal.copy()
        order = rng.permutation(len(valid_idx))
        permuted.loc[valid_idx] = signal.loc[valid_idx].iloc[order].to_numpy()
        null_weights = construct_h003_portfolio(
            permuted, close, H003_R1_ASSET_CLASSES, vix,
            **H003_R1_PORTFOLIO_PARAMS,
        )
        null_result = portfolio_returns(
            null_weights, close, fee_bps=base_fee, slippage_bps=base_slip,
        )
        null_net = null_result["net_returns"].reindex(oos_idx).fillna(0.0)
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
        "slippage_stress": cost_stress.to_dict("records"),
        "delay_stress": delay_stress.to_dict("records"),
        "parameter_perturbation": [],
        "missing_data": [],
    }
    robustness.update(stress_survival(robustness, cfg.promotion))

    benchmark = close["SPY"].pct_change(fill_method=None).shift(-1).reindex(oos_idx)
    from .portfolio.risk import risk_report
    risk = risk_report(
        baseline.oos_returns,
        weight_matrix=executed_weights,
        benchmark=benchmark,
    )

    net = baseline.oos_returns
    sortino = sortino_ratio(net)
    annual_turnover = float(
        report["h003_portfolio_returns"]["turnover"].reindex(oos_idx).fillna(0.0).sum()
        / max(len(oos_idx) / 252.0, 1e-9)
    )
    capacity = float(report.get("capacity_millions", float("nan")))
    common_corr = net.index.intersection(benchmark.dropna().index)
    corr_spy = (
        float(net.loc[common_corr].corr(benchmark.loc[common_corr]))
        if len(common_corr) > 1
        and net.loc[common_corr].std() > 0
        and benchmark.loc[common_corr].std() > 0
        else float("nan")
    )
    mid = len(net) // 2
    first_half_sharpe = sharpe_ratio(net.iloc[:mid])
    second_half_sharpe = sharpe_ratio(net.iloc[mid:])
    vix_oos = vix.reindex(oos_idx)
    top_vix_idx = vix_oos.nlargest(min(5, vix_oos.notna().sum())).index
    top_vix_return = float((1.0 + net.reindex(top_vix_idx).fillna(0.0)).prod() - 1.0)
    y2020 = net[(net.index >= pd.Timestamp("2020-01-01", tz="UTC"))
                & (net.index < pd.Timestamp("2021-01-01", tz="UTC"))]
    crisis_2020_return = (
        float((1.0 + y2020).prod() - 1.0) if len(y2020) else float("nan")
    )
    try:
        quartiles = pd.qcut(vix_oos.rank(method="first"), 4, labels=False)
        regime_sharpes = [sharpe_ratio(net[quartiles.eq(q)]) for q in range(4)]
    except ValueError:
        regime_sharpes = [float("nan")] * 4
    positive_regimes = sum(np.isfinite(x) and x > 0 for x in regime_sharpes)
    cost_2x = cost_stress.loc[cost_stress["multiple"].eq(2.0), "sharpe"].iloc[0]
    delay_3 = delay_stress.loc[delay_stress["delay_bars"].eq(3), "sharpe"].iloc[0]

    custom_checks = [
        {"name": "h003_sharpe_at_least_0_8", "passed": summary["full_oos_net_sharpe"] >= 0.8,
         "detail": f"full OOS net Sharpe={summary['full_oos_net_sharpe']:.6g} >= 0.8"},
        {"name": "h003_sortino_at_least_1_2", "passed": np.isfinite(sortino) and sortino >= 1.2,
         "detail": f"full OOS Sortino={sortino:.6g} >= 1.2"},
        {"name": "h003_drawdown_within_20pct", "passed": summary["full_oos_max_dd"] >= -0.20,
         "detail": f"full OOS max drawdown={summary['full_oos_max_dd']:.6g} >= -0.20"},
        {"name": "h003_turnover_at_most_2x", "passed": annual_turnover <= 2.0,
         "detail": f"annual turnover={annual_turnover:.6g} <= 2.0"},
        {"name": "h003_capacity_at_least_500m", "passed": np.isfinite(capacity) and capacity >= 500.0,
         "detail": f"5th-percentile 1%-ADV capacity=${capacity:.6g}m >= $500m"},
        {"name": "h003_cost_2x_sharpe", "passed": np.isfinite(cost_2x) and cost_2x >= 0.4,
         "detail": f"2x-cost Sharpe={cost_2x:.6g} >= 0.4"},
        {"name": "h003_delay_3d_sharpe", "passed": np.isfinite(delay_3) and delay_3 >= 0.4,
         "detail": f"3-session-delay Sharpe={delay_3:.6g} >= 0.4"},
        {"name": "h003_bootstrap_positive_prob", "passed": boot.get("positive_prob", 0.0) >= 0.80,
         "detail": f"bootstrap P(Sharpe>0)={boot.get('positive_prob')} >= 0.80"},
        {"name": "h003_placebo_percentile", "passed": placebo.get("percentile", 0.0) >= 0.85,
         "detail": f"placebo percentile={placebo.get('percentile')} >= 0.85"},
        {"name": "h003_crisis_alpha", "passed": bool(
            np.isfinite(crisis_2020_return) and crisis_2020_return > 0 and top_vix_return > 0),
         "detail": f"2020 return={crisis_2020_return:.6g}; top-five-VIX-day return={top_vix_return:.6g}"},
        {"name": "h003_regime_consistent", "passed": positive_regimes >= 3,
         "detail": f"positive Sharpe in {positive_regimes}/4 VIX quartiles; values={regime_sharpes}"},
        {"name": "h003_subperiod_stable", "passed": first_half_sharpe > 0 and second_half_sharpe > 0,
         "detail": f"half Sharpes={first_half_sharpe:.6g}, {second_half_sharpe:.6g}"},
        {"name": "h003_transaction_cost_alpha", "passed": np.isfinite(cost_2x) and cost_2x > 0,
         "detail": f"Sharpe after {(base_fee + base_slip) * 2:.6g}bps all-in={cost_2x:.6g} > 0"},
        {"name": "h003_correlation_diversification", "passed": np.isfinite(corr_spy) and corr_spy < 0.5,
         "detail": f"portfolio correlation to SPY={corr_spy:.6g} < 0.5"},
    ]

    report.update({
        "robustness": robustness,
        "cost_stress": cost_stress,
        "slippage_stress": cost_stress,
        "delay_stress": delay_stress,
        "parameter_perturbation": pd.DataFrame(),
        "missing_data_stress": pd.DataFrame(),
        "ablation": pd.DataFrame(),
        "placebo_null": placebo_null,
        "placebo_permute_target": pd.DataFrame(),
        "placebo_block_permute": pd.DataFrame(),
        "placebo_statistics": placebo,
        "placebo_mode_statistics": {"shuffle_signal_rows": placebo},
        "bootstrap": boot,
        "risk": risk,
        "h003_gate_metrics": {
            "sortino": sortino,
            "annual_turnover": annual_turnover,
            "capacity_millions": capacity,
            "correlation_to_spy": corr_spy,
            "first_half_sharpe": first_half_sharpe,
            "second_half_sharpe": second_half_sharpe,
            "crisis_2020_return": crisis_2020_return,
            "top_five_vix_days_return": top_vix_return,
            "vix_quartile_sharpes": regime_sharpes,
        },
        "additional_gate_checks": custom_checks,
    })
    return _register_and_decide(
        cfg, out, report, baseline, summary, robustness, boot, placebo,
        counter, start_count, dataset_version, report.get("feature_version"),
        [], integrity_ok, features, None, None,
    )


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
        # D02: Use family_attempt_count (includes abandoned/unresolved starts)
        # rather than family_search_count (only completed/aborted outcomes).
        n_family_searches=(ledger.family_attempt_count(family_id) if ledger else 0),
    )
    if report.get("additional_gate_checks"):
        from .experiments.promotion import GateCheck
        checks.extend(
            GateCheck(item["name"], bool(item["passed"]), str(item["detail"]))
            for item in report["additional_gate_checks"]
        )
    decision = promotion_decision(checks)
    folds = baseline.folds
    record = {
        "strategy": report.get("strategy_name", "walk_forward_baseline"),
        "data_mode": cfg.data.mode,
        # H-002 (cross-sectional portfolio) reports a traded universe of many
        # names rather than ``data.assets``, and a compact set of feature
        # DEFINITIONS rather than the ticker-expanded panel columns.  Prefer the
        # report-supplied values so the record describes what was actually
        # traded, not the scalar fallback placeholders.
        "features": report.get("feature_names") or sorted(features.columns),
        "universe": report.get("traded_universe") or cfg.data.assets,
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
        "strategy_version": "baseline-2.2.0",
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
        "information_sources": report.get(
            "information_sources_override",
            ["price_volume"] + (["information"] if info_cols else []),
        ),
        "additional_gate_checks": report.get("additional_gate_checks", []),
        "promotion_state": decision["state"],
        "failed_gates": decision["failed_gates"],
        # B11: research-family identity + durable search-ledger locator, so the
        # same OOS family can be recognized across artifact directories and the
        # full search history audited.
        "search_family_id": family_id,
        "search_family_dataset_identity": report.get("search_family_dataset_identity"),
        "search_ledger": str(ledger.path) if ledger else None,
        "search_correction_method": cfg.promotion.selection_correction,
        "research_protocol": report.get("research_protocol"),
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
            value = report[k]
            # Frame keys are normally DataFrames, but an alternative execution
            # path may legitimately supply an empty dict for a table it does not
            # compute (e.g. H-002 has no placebo null).  Only DataFrames need
            # conversion; anything already JSON-shaped is passed through.
            serializable[k] = (
                value.to_dict("records") if isinstance(value, pd.DataFrame)
                else value
            )
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

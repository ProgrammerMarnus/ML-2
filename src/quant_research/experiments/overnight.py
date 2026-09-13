"""Time-bounded development search with one untouched confirmation window.

Candidates are ranked using *only* their train/validation windows. After the
time budget ends, the best development candidate is frozen into an immutable
protocol and evaluated once on the final, previously unread test window. This
is intentionally different from repeatedly running every parameter variation
over the same OOS history, which would turn the test set into a tuning input.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import AppConfig, ModelConfig, load_config
from ..data.loaders import load_market_data, to_panels, to_price_panels
from ..data.schemas import DataValidationError
from ..data.snapshots import save_snapshot
from ..data.validation import validate_ohlcv
from ..evaluation.backtest import backtest
from ..evaluation.metrics import sharpe_ratio
from ..evaluation.walk_forward import FoldSpec, walk_forward_splits
from ..features.information import build_information_features
from ..features.point_in_time import validate_events
from ..features.price_volume import build_price_volume_features, build_signal_extensions
from ..features.registry import registry_hash
from ..run import generate_synthetic_events
from ..strategies.baseline import build_model, select_threshold
from .automation import CreatedExperiment, StrategyTemplate, create_experiment_plan
from .protocol import ResearchProtocol


_LOGISTIC_GRID = tuple(itertools.product(
    (0.05, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
    (1, 3, 5, 10, 15, 20),
))
_BOOSTING_GRID = tuple(itertools.product(
    (0.01, 0.02, 0.03, 0.05, 0.08, 0.12),
    (50, 100, 150, 200),
    (1, 2, 3),
    (3, 5, 10),
))
_EXTENDED_LOGISTIC_GRID = tuple(itertools.product(
    (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48),
    (1, 2, 3, 5, 8, 13, 20, 30),
))
_EXTENDED_BOOSTING_GRID = tuple(itertools.product(
    (0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.06, 0.08, 0.10, 0.15),
    (50, 75, 100, 150, 200),
    (1, 2, 3, 4),
    (1, 2, 3, 5, 8, 13, 20, 30),
))


def catalogue_size() -> int:
    return (len(_LOGISTIC_GRID) + len(_BOOSTING_GRID)
            + len(_EXTENDED_LOGISTIC_GRID) + len(_EXTENDED_BOOSTING_GRID))


def strategy_template_for(candidate_index: int) -> StrategyTemplate:
    """Return a deterministic preregisterable candidate from the large catalog."""
    if candidate_index < 0:
        raise DataValidationError("candidate index cannot be negative")
    if candidate_index < len(_LOGISTIC_GRID):
        c, hold = _LOGISTIC_GRID[candidate_index]
        return StrategyTemplate(
            strategy_id=f"logistic_c{c:g}_hold{hold}_v{candidate_index:03d}",
            mechanism=("Persistent price and point-in-time information states "
                       "may contain next-session directional information under "
                       "predeclared regularization and turnover constraints."),
            model=ModelConfig(type="logistic", random_seed=42, logreg_C=c,
                              hold_bars=hold),
        )
    boost_index = candidate_index - len(_LOGISTIC_GRID)
    if boost_index < len(_BOOSTING_GRID):
        learning_rate, n_estimators, max_depth, hold = _BOOSTING_GRID[boost_index]
        return StrategyTemplate(
            strategy_id=(f"boost_lr{learning_rate:g}_n{n_estimators}_d{max_depth}"
                         f"_hold{hold}_v{candidate_index:03d}"),
            mechanism=("Trend, volatility, liquidity, and point-in-time "
                       "information may interact nonlinearly under a "
                       "predeclared shallow-tree capacity constraint."),
            model=ModelConfig(
                type="gradient_boosting", random_seed=42,
                gb_learning_rate=learning_rate, gb_n_estimators=n_estimators,
                hold_bars=hold, parameters={"max_depth": max_depth},
            ),
        )
    extended_logistic_index = boost_index - len(_BOOSTING_GRID)
    if extended_logistic_index < len(_EXTENDED_LOGISTIC_GRID):
        c, hold = _EXTENDED_LOGISTIC_GRID[extended_logistic_index]
        return StrategyTemplate(
            strategy_id=f"logistic_extended_c{c:g}_hold{hold}_v{candidate_index:04d}",
            mechanism=("Persistent price and point-in-time information states "
                       "may contain next-session directional information under "
                       "predeclared regularization and turnover constraints."),
            model=ModelConfig(type="logistic", random_seed=42, logreg_C=c,
                              hold_bars=hold),
        )
    extended_boost_index = extended_logistic_index - len(_EXTENDED_LOGISTIC_GRID)
    if extended_boost_index < len(_EXTENDED_BOOSTING_GRID):
        learning_rate, n_estimators, max_depth, hold = _EXTENDED_BOOSTING_GRID[extended_boost_index]
        return StrategyTemplate(
            strategy_id=(f"boost_extended_lr{learning_rate:g}_n{n_estimators}_d{max_depth}"
                         f"_hold{hold}_v{candidate_index:04d}"),
            mechanism=("Trend, volatility, liquidity, and point-in-time "
                       "information may interact nonlinearly under a "
                       "predeclared shallow-tree capacity constraint."),
            model=ModelConfig(
                type="gradient_boosting", random_seed=42,
                gb_learning_rate=learning_rate, gb_n_estimators=n_estimators,
                hold_bars=hold, parameters={"max_depth": max_depth},
            ),
        )
    raise DataValidationError(
        f"strategy catalogue exhausted after {catalogue_size()} candidates; "
        "review the evidence before adding a new preregistered family"
    )


def _campaign_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = root / f"campaign_{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = root / f"campaign_{stamp}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def _configured_cutoff(base_config: AppConfig, *, allow_synthetic: bool,
                       as_of: str | None) -> AppConfig:
    if base_config.data.mode == "synthetic" and not allow_synthetic:
        raise DataValidationError(
            "overnight campaigns require real data; use configs/real_spy.yaml. "
            "Pass --allow-synthetic only for offline smoke testing."
        )
    cutoff = as_of or datetime.now(timezone.utc).date().isoformat()
    try:
        cutoff_date = datetime.fromisoformat(cutoff).date()
        start_date = datetime.fromisoformat(base_config.data.start).date()
    except ValueError as exc:
        raise DataValidationError("as_of and data.start must be ISO dates") from exc
    if cutoff_date < start_date:
        raise DataValidationError("as_of cannot be before data.start")
    if base_config.data.mode == "synthetic":
        return base_config
    return replace(base_config, data=replace(base_config.data, end=cutoff))


def _next_candidate_index(root: Path) -> int:
    return sum(
        1 for path in root.glob("campaign_*/candidate_*/experiment_plan.json")
        if path.is_file()
    )


def _prepare_candidate(base_config: AppConfig, campaign_dir: Path,
                       candidate_index: int) -> list[CreatedExperiment]:
    template = strategy_template_for(candidate_index)
    candidate_dir = campaign_dir / f"candidate_{candidate_index:03d}_{template.strategy_id}"
    return create_experiment_plan(
        base_config, candidate_dir, templates=(template,), max_experiments=1,
    )


def prepare_overnight_campaign(
    base_config: AppConfig,
    output_root: str | Path,
    *,
    allow_synthetic: bool = False,
    as_of: str | None = None,
) -> tuple[Path, list[CreatedExperiment]]:
    """Create one next-candidate campaign without executing it."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    config = _configured_cutoff(base_config, allow_synthetic=allow_synthetic,
                                as_of=as_of)
    campaign_dir = _campaign_dir(root)
    return campaign_dir, _prepare_candidate(config, campaign_dir,
                                             _next_candidate_index(root))


def _json_ready(value):
    """Convert numpy/pandas scalar values for stable, readable artifacts."""
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _json_safe(value):
    """Make artifacts strict JSON: undefined metrics are null, never NaN."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json_once(path: Path, document: dict) -> None:
    if path.exists():
        raise DataValidationError(f"refusing to overwrite immutable artifact {path}")
    path.write_text(json.dumps(_json_safe(document), indent=2, allow_nan=False,
                               default=_json_ready) + "\n",
                    encoding="utf-8")


def _catalogue_manifest(campaign_dir: Path) -> None:
    """Freeze the candidate universe before any market data is read."""
    candidates = []
    for index in range(catalogue_size()):
        template = strategy_template_for(index)
        candidates.append({
            "candidate_index": index,
            "strategy_id": template.strategy_id,
            "model": {
                "type": template.model.type,
                "logreg_C": template.model.logreg_C,
                "gb_learning_rate": template.model.gb_learning_rate,
                "gb_n_estimators": template.model.gb_n_estimators,
                "hold_bars": template.model.hold_bars,
                "parameters": template.model.parameters,
            },
        })
    _write_json_once(campaign_dir / "catalogue_manifest.json", {
        "automation": "development_then_single_confirmation_v1",
        "catalogue_size": catalogue_size(),
        "selection_rule": (
            "rank by aggregate validation net Sharpe only; deterministic "
            "candidate-index tie break; final test window is never read here"
        ),
        "candidates": candidates,
    })


def _research_context(cfg: AppConfig, campaign_dir: Path) -> dict:
    """Load a snapshot and construct the causal feature panel once per campaign."""
    ohlcv, data_meta = load_market_data(cfg.data)
    validate_ohlcv(ohlcv)
    snapshot = save_snapshot(ohlcv, cfg.data.raw_snapshot_dir,
                             name=f"{cfg.data.mode}_overnight")
    close, volume = to_panels(ohlcv)
    open_, high, low = to_price_panels(ohlcv)[:3]
    price_features = build_price_volume_features(close, volume, cfg.data.target)
    extensions = build_signal_extensions(open_, high, low, close, volume, cfg.data.target)
    features = price_features.join(extensions, how="left")
    if cfg.data.mode == "synthetic":
        events = validate_events(generate_synthetic_events(close.index, cfg.data.target))
        features = features.join(
            build_information_features(close.index, events, cfg.data.target), how="left"
        )
    anchor = features.dropna(how="all").index
    folds = walk_forward_splits(anchor, cfg.evaluation)
    if len(folds) < 2:
        raise DataValidationError(
            "development/confirmation campaigns require at least two complete "
            "walk-forward folds (one development validation fold plus one final test)"
        )
    target_close = close[cfg.data.target]
    y = (target_close.shift(-1) > target_close).astype("float")
    y[target_close.shift(-1).isna()] = np.nan
    fwd = target_close.shift(-1) / target_close - 1.0
    context = {
        "data_meta": data_meta,
        "dataset_hash": snapshot["dataset_hash"],
        "snapshot": snapshot,
        "features": features.loc[anchor],
        "feature_version": registry_hash(list(features.columns)),
        "y": y.loc[anchor],
        "fwd": fwd.loc[anchor],
        "risk_returns": fwd.loc[anchor].shift(1),
        "development_folds": folds,
        "confirmation_fold": folds[-1],
    }
    _write_json_once(campaign_dir / "dataset_manifest.json", {
        "dataset_hash": snapshot["dataset_hash"],
        "snapshot": snapshot,
        "data_meta": data_meta,
        "feature_version": context["feature_version"],
        "n_features": len(features.columns),
        "development_fold_ids": [fold.fold_id for fold in folds],
        "confirmation_fold": folds[-1].summary(),
    })
    return context


def _development_indices(spec: FoldSpec, context: dict) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Return usable train/validation rows without accessing the test window."""
    y = context["y"]
    fwd = context["fwd"]
    train = spec.train_idx[(y.loc[spec.train_idx].notna()) & (fwd.loc[spec.train_idx].notna())]
    val = spec.val_idx[(y.loc[spec.val_idx].notna()) & (fwd.loc[spec.val_idx].notna())]
    if len(train) == 0 or len(val) == 0:
        raise DataValidationError(f"fold {spec.fold_id} has no usable train or validation rows")
    return train, val


def _confirmation_indices(spec: FoldSpec, context: dict) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex, pd.DatetimeIndex]:
    """Availability filtering for the one final, now-authorized test read."""
    train, val = _development_indices(spec, context)
    fwd = context["fwd"]
    test = spec.test_idx[fwd.loc[spec.test_idx].notna()]
    if len(train) == 0 or len(val) == 0 or len(test) == 0:
        raise DataValidationError(f"fold {spec.fold_id} has no usable train, validation, or test rows")
    return train, val, test


def _score_on_validation(template: StrategyTemplate, context: dict) -> dict:
    """Score a strategy exclusively on validation windows; no test index is read."""
    features, y, fwd = context["features"], context["y"], context["fwd"]
    validation_returns: list[pd.Series] = []
    per_fold: list[dict] = []
    # The final fold's validation period remains development data.  Its test
    # period is deliberately absent from this function.
    for spec in context["development_folds"]:
        train, val = _development_indices(spec, context)
        model = build_model(template.model)
        model.fit(features.loc[train], y.loc[train].astype(int))
        probabilities = pd.Series(model.predict_proba(features.loc[val])[:, 1], index=val)
        threshold, _ = select_threshold(
            probabilities, fwd.loc[val], context["threshold_candidates"],
            context["execution"], hold_bars=template.model.hold_bars or 1,
            risk_returns=context["risk_returns"],
        )
        result = backtest(probabilities, fwd.loc[val], context["execution"],
                          threshold=threshold, hold_bars=template.model.hold_bars or 1,
                          risk_returns=context["risk_returns"])
        validation_returns.append(result.net_returns)
        per_fold.append({
            "fold_id": spec.fold_id,
            "threshold": threshold,
            "net_sharpe": result.metrics["sharpe"],
            "net_return": result.metrics["net_return"],
            "trades": result.metrics["trade_count"],
        })
    aggregate = pd.concat(validation_returns).sort_index()
    return {
        "strategy_id": template.strategy_id,
        "validation_net_sharpe": sharpe_ratio(aggregate),
        "validation_net_return": float((1.0 + aggregate).prod() - 1.0),
        "validation_observations": len(aggregate),
        "validation_folds": per_fold,
    }


def _confirmation_ledger_path() -> Path:
    """Return the output-independent ledger for consumed confirmation slices."""
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "research_ledgers" / "confirmation_ledger.jsonl"


def _confirmation_already_used(root: Path, dataset_id: str, fold: FoldSpec) -> bool:
    """Prevent a second campaign from quietly retesting the exact same OOS slice."""
    key = (str(fold.test_idx.min()), str(fold.test_idx.max()))
    ledger = _confirmation_ledger_path()
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                prior = json.loads(line)
            except json.JSONDecodeError:
                continue
            if prior.get("dataset_hash") == dataset_id and tuple(prior.get("test_window", ())) == key:
                return True
    for result_path in root.glob("campaign_*/confirmation_results.json"):
        try:
            prior = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if prior.get("dataset_hash") == dataset_id and tuple(prior.get("test_window", ())) == key:
            return True
    return False


def _claim_confirmation_slice(dataset_id: str, fold: FoldSpec, campaign_dir: Path) -> Path:
    """Append the final test claim before its first read (conservative by design)."""
    ledger = _confirmation_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "dataset_hash": dataset_id,
        "test_window": [str(fold.test_idx.min()), str(fold.test_idx.max())],
        "campaign_dir": str(campaign_dir),
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, allow_nan=False) + "\n")
    return ledger


def _freeze_selected_protocol(base_config: AppConfig, campaign_dir: Path,
                              template: StrategyTemplate, context: dict,
                              n_candidates: int) -> AppConfig:
    """Freeze the selected hypothesis after development and before its test read."""
    confirmation = context["confirmation_fold"]
    protocol_path = campaign_dir / "protocols" / f"{template.strategy_id}.json"
    # Account for the complete validation search rather than pretending that
    # only the chosen model's threshold trials occurred.
    declared_trials = max(
        base_config.research.max_trials,
        n_candidates * len(context["development_folds"]) * len(context["threshold_candidates"]),
    )
    candidate = replace(
        base_config,
        model=template.model,
        research=replace(base_config.research, max_trials=declared_trials,
                         protocol_path=str(protocol_path)),
        output_dir=str(campaign_dir / "confirmation"),
    )
    protocol = ResearchProtocol.create(
        hypothesis_id=template.strategy_id,
        economic_mechanism=template.mechanism,
        feature_names=list(context["features"].columns),
        target=candidate.data.target,
        primary_metric="confirmation_net_sharpe",
        development_data=(f"dataset:{context['dataset_hash']}; train/validation folds "
                          f"through {confirmation.val_idx.max().date()}; "
                          f"{n_candidates} candidates"),
        evaluation_data=(f"dataset:{context['dataset_hash']}; locked final test "
                         f"{confirmation.test_idx.min().date()}..{confirmation.test_idx.max().date()}"),
        max_trials=declared_trials,
        config_fingerprint=candidate.fingerprint(),
    )
    protocol.freeze(protocol_path)
    config_path = campaign_dir / "configs" / f"{template.strategy_id}.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(candidate.to_dict(), sort_keys=False), encoding="utf-8")
    return candidate


def _confirm_selected(template: StrategyTemplate, candidate: AppConfig, context: dict) -> dict:
    """Evaluate the frozen winner once on the final test window."""
    spec = context["confirmation_fold"]
    train, val, test = _confirmation_indices(spec, context)
    features, y, fwd = context["features"], context["y"], context["fwd"]
    model = build_model(template.model)
    model.fit(features.loc[train], y.loc[train].astype(int))
    val_probabilities = pd.Series(model.predict_proba(features.loc[val])[:, 1], index=val)
    threshold, threshold_table = select_threshold(
        val_probabilities, fwd.loc[val], context["threshold_candidates"], candidate.execution,
        hold_bars=template.model.hold_bars or 1, risk_returns=context["risk_returns"],
    )
    test_probabilities = pd.Series(model.predict_proba(features.loc[test])[:, 1], index=test)
    baseline = backtest(test_probabilities, fwd.loc[test], candidate.execution,
                        threshold=threshold, hold_bars=template.model.hold_bars or 1,
                        risk_returns=context["risk_returns"])
    cost_cfg = replace(candidate.execution,
                       fee_bps=max(candidate.execution.fee_bps, candidate.promotion.cost_stress_fee_bps))
    delay_cfg = replace(candidate.execution,
                        signal_delay_bars=max(candidate.execution.signal_delay_bars,
                                              candidate.promotion.delay_stress_bars))
    cost = backtest(test_probabilities, fwd.loc[test], cost_cfg, threshold=threshold,
                    hold_bars=template.model.hold_bars or 1, risk_returns=context["risk_returns"])
    delayed = backtest(test_probabilities, fwd.loc[test], delay_cfg, threshold=threshold,
                       hold_bars=template.model.hold_bars or 1, risk_returns=context["risk_returns"])
    return {
        "strategy_id": template.strategy_id,
        "dataset_hash": context["dataset_hash"],
        "evidence_status": "REAL_DATA" if candidate.data.mode != "synthetic" else "SYNTHETIC_OFFLINE",
        "promotion_state": "RESEARCH_ONLY",
        "reason": ("A single untouched confirmation window is useful evidence, but it "
                   "is not sufficient for automatic promotion."),
        "test_window": [str(spec.test_idx.min()), str(spec.test_idx.max())],
        "fold": spec.summary(),
        "threshold_selected_on_validation": threshold,
        "threshold_table": threshold_table.to_dict(orient="records"),
        "confirmation_metrics": baseline.metrics,
        "cost_stress_metrics": cost.metrics,
        "delay_stress_metrics": delayed.metrics,
    }


def run_overnight_campaign(
    base_config: AppConfig,
    output_root: str | Path,
    *,
    max_hours: float = 6.0,
    allow_synthetic: bool = False,
    as_of: str | None = None,
    max_candidates: int | None = None,
) -> tuple[Path, list[dict]]:
    """Rank development candidates, then read the final test window once.

    The duration controls how many validation-only candidates can be assessed.
    Once it expires, the best valid candidate is locked and tested exactly once
    on the final fold. A test already used for the same raw dataset is never
    silently reused by another campaign.
    """
    if not 0 < max_hours <= 24:
        raise DataValidationError("max_hours must be greater than 0 and at most 24")
    if max_candidates is not None and max_candidates < 1:
        raise DataValidationError("max_candidates must be positive when supplied")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    config = _configured_cutoff(base_config, allow_synthetic=allow_synthetic,
                                as_of=as_of)
    campaign_dir = _campaign_dir(root)
    _catalogue_manifest(campaign_dir)
    started = time.monotonic()
    deadline = started + max_hours * 3600.0
    context = _research_context(config, campaign_dir)
    context["execution"] = config.execution
    context["threshold_candidates"] = config.research.threshold_candidates
    outcomes: list[dict] = []
    failures: list[dict] = []

    # No call inside this loop receives a test index. Candidate ranking cannot
    # see the confirmation returns, labels, probabilities, or metrics.
    for candidate_index in range(catalogue_size()):
        if time.monotonic() >= deadline:
            break
        # This non-CLI cap exists for deterministic automated tests. Production
        # use is governed only by max_hours, as documented and requested.
        if max_candidates is not None and len(outcomes) + len(failures) >= max_candidates:
            break
        try:
            outcome = _score_on_validation(strategy_template_for(candidate_index), context)
        except (DataValidationError, ValueError) as exc:
            failures.append({"candidate_index": candidate_index, "error": str(exc)})
            continue
        outcome["candidate_index"] = candidate_index
        outcomes.append(outcome)

    elapsed = time.monotonic() - started
    development = {
        "campaign_dir": str(campaign_dir),
        "configured_max_hours": max_hours,
        "development_elapsed_seconds": elapsed,
        "n_candidates_scored": len(outcomes),
        "n_candidates_failed": len(failures),
        "catalogue_size": catalogue_size(),
        "ranking_metric": "aggregate_validation_net_sharpe",
        "test_window_read_during_development": False,
        "outcomes": sorted(outcomes, key=lambda row: row["candidate_index"]),
        "failures": failures,
    }
    _write_json_once(campaign_dir / "development_results.json", development)

    finite = [row for row in outcomes if np.isfinite(row["validation_net_sharpe"])]
    confirmation = None
    if finite and not _confirmation_already_used(root, context["dataset_hash"],
                                                  context["confirmation_fold"]):
        winner = max(finite, key=lambda row: (row["validation_net_sharpe"], -row["candidate_index"]))
        template = strategy_template_for(winner["candidate_index"])
        frozen = _freeze_selected_protocol(config, campaign_dir, template, context, len(outcomes))
        confirmation_ledger = _claim_confirmation_slice(
            context["dataset_hash"], context["confirmation_fold"], campaign_dir
        )
        confirmation = _confirm_selected(template, frozen, context)
        confirmation["development_selection"] = winner
        confirmation["confirmation_ledger"] = str(confirmation_ledger)
        _write_json_once(campaign_dir / "confirmation_results.json", confirmation)
    elif finite:
        confirmation = {
            "promotion_state": "RESEARCH_ONLY",
            "reason": "confirmation skipped: this exact dataset/test window was already used",
            "dataset_hash": context["dataset_hash"],
            "test_window": [str(context["confirmation_fold"].test_idx.min()),
                            str(context["confirmation_fold"].test_idx.max())],
        }
    else:
        confirmation = {
            "promotion_state": "RESEARCH_ONLY",
            "reason": "confirmation skipped: no candidate produced a finite validation Sharpe",
        }

    summary = {
        "campaign_dir": str(campaign_dir),
        "configured_max_hours": max_hours,
        "elapsed_seconds_before_confirmation": elapsed,
        "n_candidates_scored_on_validation": len(outcomes),
        "catalogue_size": catalogue_size(),
        "confirmation": confirmation,
    }
    _write_json_once(campaign_dir / "campaign_summary.json", summary)
    return campaign_dir, [summary]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run validation-only search, then one locked final confirmation."
    )
    parser.add_argument("--config", required=True, help="real-data base YAML config")
    parser.add_argument("--output", required=True, help="campaign artifact root")
    parser.add_argument("--max-hours", type=float, default=6.0,
                        help="time budget for new candidate starts (default: 6)")
    parser.add_argument("--allow-synthetic", action="store_true",
                        help="permit synthetic-data smoke campaigns; never market evidence")
    parser.add_argument("--as-of", default=None,
                        help="data cutoff, YYYY-MM-DD (defaults to today in UTC)")
    args = parser.parse_args(argv)
    campaign_dir, outcomes = run_overnight_campaign(
        load_config(args.config), args.output, max_hours=args.max_hours,
        allow_synthetic=args.allow_synthetic, as_of=args.as_of,
    )
    print(f"campaign: {campaign_dir}")
    summary = outcomes[0]
    print(f"candidates scored on validation: {summary['n_candidates_scored_on_validation']}")
    print(json.dumps(summary["confirmation"], sort_keys=True, default=_json_ready))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

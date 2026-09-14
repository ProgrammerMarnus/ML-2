"""Bounded, protocol-first experiment creation and testing.

This module deliberately automates the administrative and reproducibility work
around research; it does not fabricate a trading claim or bypass promotion.
Every generated candidate has an immutable research protocol, an independently
fingerprinted configuration, and its own artifact directory.  Executed runs
remain subject to the ordinary walk-forward, robustness, placebo, trial-count,
and promotion gates.

Usage
-----
``python -m quant_research.experiments.automation --config configs/baseline.yaml
--output artifacts/automation --run``
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import yaml

from ..config import AppConfig, ModelConfig, load_config
from ..data.schemas import DataValidationError
from ..run import run_research_pipeline
from .protocol import ResearchProtocol


@dataclass(frozen=True)
class StrategyTemplate:
    """A bounded, predeclared executable strategy variation."""

    strategy_id: str
    mechanism: str
    model: ModelConfig


# These are deliberately few and deterministic.  Expanding the catalog is a
# research decision: add a documented template and account for the extra search
# rather than silently sampling unlimited parameter combinations.
DEFAULT_TEMPLATES: tuple[StrategyTemplate, ...] = (
    StrategyTemplate(
        strategy_id="regularized_directional_logistic_short_hold",
        mechanism=("Persistent price and information states may carry modest "
                   "next-session directional information under regularization."),
        model=ModelConfig(type="logistic", random_seed=42, logreg_C=0.25,
                          hold_bars=3),
    ),
    StrategyTemplate(
        strategy_id="regularized_directional_logistic_medium_hold",
        mechanism=("Persistent price and information states may carry modest "
                   "next-session directional information under regularization."),
        model=ModelConfig(type="logistic", random_seed=42, logreg_C=1.0,
                          hold_bars=5),
    ),
    StrategyTemplate(
        strategy_id="regularized_directional_logistic_long_hold",
        mechanism=("Persistent price and information states may carry modest "
                   "next-session directional information under stronger signal "
                   "persistence and lower turnover."),
        model=ModelConfig(type="logistic", random_seed=42, logreg_C=4.0,
                          hold_bars=10),
    ),
    StrategyTemplate(
        strategy_id="shallow_nonlinear_gradient_boosting_short_hold",
        mechanism=("Interactions between trend, volatility, liquidity, and "
                   "point-in-time information may be nonlinear but stable when "
                   "model capacity is constrained."),
        model=ModelConfig(type="gradient_boosting", random_seed=42,
                          gb_learning_rate=0.03, gb_n_estimators=50,
                          hold_bars=5),
    ),
    StrategyTemplate(
        strategy_id="shallow_nonlinear_gradient_boosting_medium_hold",
        mechanism=("Interactions between trend, volatility, liquidity, and "
                   "point-in-time information may be nonlinear but stable when "
                   "model capacity is constrained."),
        model=ModelConfig(type="gradient_boosting", random_seed=42,
                          gb_learning_rate=0.05, gb_n_estimators=100,
                          hold_bars=10),
    ),
    StrategyTemplate(
        strategy_id="shallow_nonlinear_gradient_boosting_long_hold",
        mechanism=("Interactions between trend, volatility, liquidity, and "
                   "point-in-time information may be nonlinear but stable when "
                   "model capacity is constrained and turnover is reduced."),
        model=ModelConfig(type="gradient_boosting", random_seed=42,
                          gb_learning_rate=0.08, gb_n_estimators=200,
                          hold_bars=20),
    ),
)


@dataclass(frozen=True)
class CreatedExperiment:
    """Immutable files and executable configuration for one candidate."""

    strategy_id: str
    protocol_path: Path
    config_path: Path
    output_dir: Path
    config: AppConfig


def _protocol_features(config: AppConfig) -> list[str]:
    """Return the exact registered feature contract selected by the config."""
    from ..features.assembly import planned_feature_names

    return planned_feature_names(
        config.features,
        events_available=config.data.mode == "synthetic",
        assets=config.data.assets,
    )


def create_experiment_plan(
    base_config: AppConfig,
    output_dir: str | Path,
    *,
    templates: Iterable[StrategyTemplate] = DEFAULT_TEMPLATES,
    max_experiments: int = 2,
) -> list[CreatedExperiment]:
    """Create immutable protocols and YAML configs without executing them.

    The bound is intentionally small (1--10) and each plan entry consumes a
    separately named output directory.  Existing protocol/config names are
    never overwritten; regenerate a plan under a new output directory to begin
    a distinct research family.
    """
    if not 1 <= max_experiments <= 10:
        raise DataValidationError("max_experiments must be between 1 and 10")
    root = Path(output_dir)
    protocols = root / "protocols"
    configs = root / "configs"
    runs = root / "runs"
    protocols.mkdir(parents=True, exist_ok=True)
    configs.mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)

    chosen = list(templates)[:max_experiments]
    if not chosen:
        raise DataValidationError("at least one strategy template is required")
    ids = [template.strategy_id for template in chosen]
    if len(ids) != len(set(ids)):
        raise DataValidationError("strategy template ids must be unique")

    created: list[CreatedExperiment] = []
    for template in chosen:
        protocol_path = protocols / f"{template.strategy_id}.json"
        config_path = configs / f"{template.strategy_id}.yaml"
        run_dir = runs / template.strategy_id
        if config_path.exists():
            raise DataValidationError(
                f"generated config already exists at {config_path}; plans are immutable"
            )
        candidate = replace(
            base_config,
            model=template.model,
            research=replace(base_config.research, protocol_path=str(protocol_path)),
            output_dir=str(run_dir),
        )
        protocol = ResearchProtocol.create(
            hypothesis_id=template.strategy_id,
            economic_mechanism=template.mechanism,
            feature_names=_protocol_features(candidate),
            target=candidate.data.target,
            primary_metric="full_oos_net_sharpe",
            development_data=(f"{candidate.data.mode}:{candidate.data.start}.."
                              f"{candidate.data.end}:train_validation"),
            evaluation_data=(f"{candidate.data.mode}:{candidate.data.start}.."
                             f"{candidate.data.end}:locked_oos"),
            max_trials=candidate.research.max_trials,
            config_fingerprint=candidate.fingerprint(),
        )
        protocol.freeze(protocol_path)
        config_path.write_text(
            yaml.safe_dump(candidate.to_dict(), sort_keys=False), encoding="utf-8"
        )
        created.append(CreatedExperiment(template.strategy_id, protocol_path,
                                         config_path, run_dir, candidate))

    plan_path = root / "experiment_plan.json"
    if plan_path.exists():
        raise DataValidationError(f"experiment plan already exists at {plan_path}")
    plan_path.write_text(json.dumps({
        "automation": "bounded_protocol_first_v1",
        "experiments": [{
            "strategy_id": item.strategy_id,
            "protocol_path": str(item.protocol_path),
            "config_path": str(item.config_path),
            "output_dir": str(item.output_dir),
            "config_fingerprint": item.config.fingerprint(),
        } for item in created],
    }, indent=2) + "\n", encoding="utf-8")
    return created


def test_created_experiments(created: Iterable[CreatedExperiment]) -> list[dict]:
    """Execute a precreated plan and return compact auditable outcomes."""
    outcomes = []
    for item in created:
        report = run_research_pipeline(item.config, str(item.output_dir))
        record = report["experiment_record"]
        outcomes.append({
            "strategy_id": item.strategy_id,
            "experiment_id": record["experiment_id"],
            "evidence_status": record["evidence_status"],
            "promotion_state": record["promotion_state"],
            "failed_gates": record["failed_gates"],
            "results_path": str(item.output_dir / f"{record['experiment_id']}_results.json"),
        })
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create bounded, preregistered strategy experiments; optionally execute them."
    )
    parser.add_argument("--config", required=True, help="base YAML configuration")
    parser.add_argument("--output", required=True, help="new automation output directory")
    parser.add_argument("--max-experiments", type=int, default=2)
    parser.add_argument("--run", action="store_true",
                        help="execute generated experiments after creating their immutable plan")
    args = parser.parse_args(argv)

    created = create_experiment_plan(load_config(args.config), args.output,
                                     max_experiments=args.max_experiments)
    print(f"created {len(created)} preregistered experiment(s)")
    for item in created:
        print(f"- {item.strategy_id}: {item.config_path}")
    if args.run:
        for outcome in test_created_experiments(created):
            print(json.dumps(outcome, sort_keys=True))
    else:
        print("plan only; rerun with --run to execute the immutable candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

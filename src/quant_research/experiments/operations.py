"""Safe operational helpers for the overnight research campaign.

These commands deliberately do not download market data, generate features,
fit models, or read any OOS returns.  They prepare and inspect campaign work
without consuming a research or confirmation window.

Usage
-----
``python -m quant_research.experiments.operations preflight --config
configs/real_spy.yaml --output artifacts/overnight``

``python -m quant_research.experiments.operations status --output
artifacts/overnight``
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from ..config import AppConfig, load_config
from ..data.schemas import DataValidationError
from .overnight import _configured_cutoff, _confirmation_ledger_path, catalogue_size


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def preflight_campaign(
    base_config: AppConfig,
    output_root: str | Path,
    *,
    max_hours: float = 6.0,
    allow_synthetic: bool = False,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Validate local prerequisites without accessing market data or OOS data."""
    if not 0 < max_hours <= 24:
        raise DataValidationError("max_hours must be greater than 0 and at most 24")
    config = _configured_cutoff(base_config, allow_synthetic=allow_synthetic,
                                as_of=as_of)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    snapshot_dir = Path(config.data.raw_snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    requirements: list[dict[str, Any]] = []
    if config.data.mode == "yfinance":
        requirements.append({
            "name": "yfinance",
            "available": importlib.util.find_spec("yfinance") is not None,
            "install": ".venv/bin/python -m pip install -e '.[market,dev]'",
        })
    failures = [item["name"] for item in requirements if not item["available"]]
    ledger = _confirmation_ledger_path()
    consumed = len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.exists() else 0
    return {
        "ready": not failures,
        "mode": config.data.mode,
        "configured_data_end": config.data.end,
        "max_hours": max_hours,
        "output_root": str(output.resolve()),
        "snapshot_dir": str(snapshot_dir.resolve()),
        "catalogue_size": catalogue_size(),
        "confirmation_slices_recorded": consumed,
        "requirements": requirements,
        "failures": failures,
        "guarantees": [
            "No market-data download was attempted.",
            "No features, models, validation scores, or OOS test returns were read.",
            "No strategy or confirmation window was consumed.",
        ],
    }


def campaign_status(output_root: str | Path, campaign: str | Path | None = None) -> dict[str, Any]:
    """Read the latest campaign's compact state without modifying artifacts."""
    root = Path(output_root)
    if campaign is None:
        choices = sorted(path for path in root.glob("campaign_*") if path.is_dir())
        if not choices:
            raise DataValidationError(f"no campaign directories found under {root}")
        directory = choices[-1]
    else:
        directory = Path(campaign)
        if not directory.is_absolute():
            directory = root / directory
    if not directory.is_dir():
        raise DataValidationError(f"campaign directory does not exist: {directory}")
    summary = _read_json(directory / "campaign_summary.json")
    development = _read_json(directory / "development_results.json")
    confirmation = _read_json(directory / "confirmation_results.json")
    if summary is not None:
        state = "completed"
    elif development is not None:
        state = "awaiting_confirmation_or_finalization"
    elif (directory / "catalogue_manifest.json").exists():
        state = "started"
    else:
        state = "unknown"
    selected = confirmation.get("strategy_id") if confirmation else None
    if selected is None and summary:
        selected = (summary.get("confirmation") or {}).get("strategy_id")
    return {
        "campaign_dir": str(directory.resolve()),
        "state": state,
        "candidates_scored_on_validation": (
            summary.get("n_candidates_scored_on_validation") if summary else
            development.get("n_candidates_scored") if development else None
        ),
        "selected_strategy": selected,
        "confirmation_state": (
            confirmation.get("promotion_state") if confirmation else
            (summary.get("confirmation") or {}).get("promotion_state") if summary else None
        ),
        "confirmation_reason": (
            confirmation.get("reason") if confirmation else
            (summary.get("confirmation") or {}).get("reason") if summary else None
        ),
        "artifact_paths": {
            "summary": str(directory / "campaign_summary.json"),
            "development": str(directory / "development_results.json"),
            "confirmation": str(directory / "confirmation_results.json"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or inspect overnight research campaigns.")
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight", help="validate local prerequisites without data access")
    preflight.add_argument("--config", required=True)
    preflight.add_argument("--output", required=True)
    preflight.add_argument("--max-hours", type=float, default=6.0)
    preflight.add_argument("--allow-synthetic", action="store_true")
    preflight.add_argument("--as-of", default=None)
    status = commands.add_parser("status", help="read campaign artifacts without modifying them")
    status.add_argument("--output", required=True)
    status.add_argument("--campaign", default=None,
                        help="campaign directory name; defaults to the latest one")
    args = parser.parse_args(argv)
    if args.command == "preflight":
        report = preflight_campaign(load_config(args.config), args.output,
                                    max_hours=args.max_hours,
                                    allow_synthetic=args.allow_synthetic,
                                    as_of=args.as_of)
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 2
    print(json.dumps(campaign_status(args.output, args.campaign), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

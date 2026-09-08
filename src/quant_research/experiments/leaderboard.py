"""Research leaderboard built from the immutable registry.

Answers: what was tested?  when?  with what dataset?  how many trials?  what
was the untouched OOS performance?  did it survive costs/delay?  how did it
compare with the empirical null?  why was it promoted or rejected?
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .registry import ExperimentRegistry

LEADERBOARD_COLUMNS = [
    "experiment_id",
    "timestamp_utc",
    "strategy",
    "data_mode",
    "target",
    "universe",
    "trials",
    "n_trials_global",
    "search_class",
    "mean_oos_sharpe",
    "median_oos_sharpe",
    "mean_oos_auc",
    "worst_oos_dd",
    "bootstrap_lo",
    "bootstrap_hi",
    "survives_cost_stress",
    "survives_delay_stress",
    "placebo_percentile",
    "robustness_score",
    "dataset_version",
    "feature_version",
    "promotion_state",
    "failed_gates",
]


def _search_class(trials: int) -> str:
    """Interpret significance in light of search size."""
    if trials <= 1:
        return "one_shot_hypothesis_test"
    if trials <= 48:
        return "bounded_small_search"
    return "large_scale_search"


def build_leaderboard(registry: ExperimentRegistry) -> pd.DataFrame:
    rows = []
    for rec in registry.read_all():
        net = rec.get("net_metrics", {}) or {}
        oos = rec.get("oos_metrics", {}) or {}
        boot = rec.get("bootstrap_interval", {}) or {}
        placebo = rec.get("placebo_statistics", {}) or {}
        rob = rec.get("robustness", {}) or {}  # canonical robustness object
        surv_cost = bool(rob.get("survives_cost_stress", False))
        surv_delay = bool(rob.get("survives_delay_stress", False))
        rows.append({
            "experiment_id": rec["experiment_id"],
            "timestamp_utc": rec["timestamp_utc"],
            "strategy": rec.get("strategy"),
            "data_mode": rec.get("data_mode"),
            "target": rec.get("target"),
            "universe": rec.get("universe"),
            "trials": rec.get("trials"),
            "n_trials_global": rec.get("n_trials_global"),
            "search_class": _search_class(int(rec.get("trials", 0) or 0)),
            "mean_oos_sharpe": oos.get("mean_oos_sharpe"),
            "median_oos_sharpe": oos.get("median_oos_sharpe"),
            "mean_oos_auc": oos.get("mean_oos_auc"),
            "worst_oos_dd": oos.get("worst_oos_dd"),
            "bootstrap_lo": boot.get("lo"),
            "bootstrap_hi": boot.get("hi"),
            "survives_cost_stress": surv_cost,
            "survives_delay_stress": surv_delay,
            "placebo_percentile": placebo.get("percentile"),
            "robustness_score": float(surv_cost and surv_delay),
            "dataset_version": rec.get("dataset_version"),
            "feature_version": rec.get("feature_version"),
            "promotion_state": rec.get("promotion_state"),
            "failed_gates": ";".join(rec.get("failed_gates", []) or []),
        })
    return pd.DataFrame(rows, columns=LEADERBOARD_COLUMNS)

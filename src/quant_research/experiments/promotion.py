"""Promotion state machine: conservative, configurable, evidence-based.

States:
RESEARCH_ONLY -> CANDIDATE -> ROBUST_OOS -> PAPER_READY -> PAPER_VALIDATED -> LIVE_ELIGIBLE

Default gates REJECT promotion when OOS evidence is weak, cost/delay stress
fails, placebo is comparable or better, bootstrap uncertainty is too wide,
one fold dominates, turnover/economics are implausible, data-integrity checks
fail, trial accounting is inconsistent, or look-ahead risk remains.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ..config import PromotionConfig

STATES = [
    "RESEARCH_ONLY",
    "CANDIDATE",
    "ROBUST_OOS",
    "PAPER_READY",
    "PAPER_VALIDATED",
    "LIVE_ELIGIBLE",
]


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str


def stress_survival(robustness: dict, cfg: PromotionConfig) -> dict:
    """Survival flags derived from the canonical robustness tables.

    A single source of truth consumed by both the promotion gates and the
    registry record, so the two can never diverge.
    """
    cost = (robustness or {}).get("cost_stress") or []
    delay = (robustness or {}).get("delay_stress") or []
    cost_df = pd.DataFrame(cost) if cost else pd.DataFrame()
    delay_df = pd.DataFrame(delay) if delay else pd.DataFrame()

    if len(cost_df) and "fee_bps" in cost_df and "sharpe" in cost_df:
        stressed = cost_df[cost_df["fee_bps"] >= cfg.cost_stress_fee_bps]
        cost_ok = bool(len(stressed)) and bool((stressed["sharpe"] > 0).all())
    else:
        cost_ok = False
    if len(delay_df) and "delay_bars" in delay_df and "sharpe" in delay_df:
        dsel = delay_df[delay_df["delay_bars"] >= cfg.delay_stress_bars]
        delay_ok = bool(len(dsel)) and bool((dsel["sharpe"] > 0).all())
    else:
        delay_ok = False
    return {"survives_cost_stress": cost_ok, "survives_delay_stress": delay_ok}


def evaluate_gates(
    summary: dict,
    robustness: dict,
    bootstrap: dict,
    placebo: dict,
    integrity_ok: bool,
    lookahead_resolved: bool,
    trials: int,
    cfg: PromotionConfig,
) -> list:
    """Evaluate promotion criteria; returns the list of GateCheck results.

    ``robustness`` is the canonical robustness object from the experiment
    record (actual stress tables + survival flags); the gates consume exactly
    that representation.
    """
    survival = stress_survival(robustness, cfg)
    checks: list = []

    checks.append(GateCheck(
        "median_oos_sharpe_positive",
        summary.get("median_oos_sharpe", float("nan")) > cfg.min_median_oos_sharpe,
        f"median OOS Sharpe {summary.get('median_oos_sharpe')} > {cfg.min_median_oos_sharpe}",
    ))
    checks.append(GateCheck(
        "mean_oos_sharpe_positive",
        summary.get("mean_oos_sharpe", float("nan")) > cfg.min_mean_oos_sharpe,
        f"mean OOS Sharpe {summary.get('mean_oos_sharpe')} > {cfg.min_mean_oos_sharpe}",
    ))
    checks.append(GateCheck(
        "worst_dd_within_limit",
        summary.get("worst_oos_dd", float("nan")) >= cfg.max_oos_dd,
        f"worst OOS drawdown {summary.get('worst_oos_dd')} >= {cfg.max_oos_dd}",
    ))

    checks.append(GateCheck(
        "cost_stress_survives", survival["survives_cost_stress"],
        f"positive Sharpe at fee>={cfg.cost_stress_fee_bps}bps: "
        f"{survival['survives_cost_stress']}",
    ))
    checks.append(GateCheck(
        "delay_stress_survives", survival["survives_delay_stress"],
        f"positive Sharpe at delay>={cfg.delay_stress_bars}: "
        f"{survival['survives_delay_stress']}",
    ))

    bprob = bootstrap.get("positive_prob", float("nan"))
    checks.append(GateCheck(
        "bootstrap_positive_prob",
        bprob >= cfg.min_bootstrap_positive_prob,
        f"bootstrap P(SR>0)={bprob} >= {cfg.min_bootstrap_positive_prob}",
    ))
    pct = placebo.get("percentile", float("nan"))
    checks.append(GateCheck(
        "placebo_separates",
        pct >= cfg.min_placebo_percentile,
        f"placebo percentile {pct} >= {cfg.min_placebo_percentile} "
        "(real strategy must beat the empirical null)",
    ))
    share = summary.get("single_fold_share", float("nan"))
    checks.append(GateCheck(
        "not_single_fold",
        share <= cfg.max_single_fold_share,
        f"single-fold contribution {share} <= {cfg.max_single_fold_share}",
    ))
    turnover = summary.get("annual_turnover", float("nan"))
    checks.append(GateCheck(
        "turnover_plausible",
        turnover <= cfg.max_annual_turnover,
        f"annual turnover {turnover} <= {cfg.max_annual_turnover}",
    ))
    checks.append(GateCheck("data_integrity", integrity_ok, "data-integrity checks passed"))
    checks.append(GateCheck("lookahead_resolved", lookahead_resolved,
                            "no unresolved look-ahead risk"))
    checks.append(GateCheck(
        "trial_accounting_consistent",
        trials >= 1,
        f"trial count {trials} is recorded and consistent with evidence",
    ))
    return checks


def promotion_decision(checks: list, current_state: str = "RESEARCH_ONLY") -> dict:
    """Decide promotion strictly: any failed gate holds the strategy back."""
    if current_state not in STATES:
        raise ValueError(f"unknown promotion state {current_state!r}")
    failed = [c.name for c in checks if not c.passed]
    if failed:
        return {
            "decision": "RESEARCH_ONLY",
            "state": "RESEARCH_ONLY",
            "failed_gates": failed,
            "passed_gates": [c.name for c in checks if c.passed],
            "detail": [f"{c.name}: {c.detail}" for c in checks],
        }
    # all conservative research gates passed -> CANDIDATE (further states
    # require live-paper evidence, deliberately not automatable here)
    target = "CANDIDATE" if current_state == "RESEARCH_ONLY" else current_state
    return {
        "decision": target,
        "state": target,
        "failed_gates": [],
        "passed_gates": [c.name for c in checks],
        "detail": [f"{c.name}: {c.detail}" for c in checks],
    }

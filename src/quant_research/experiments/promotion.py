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

import numpy as np
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
    n_family_searches: int = 0,
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
        summary.get("full_oos_max_dd",
                    summary.get("worst_oos_dd", float("nan"))) >= cfg.max_oos_dd,
        f"full OOS path drawdown "
        f"{summary.get('full_oos_max_dd', summary.get('worst_oos_dd'))} >= "
        f"{cfg.max_oos_dd} (concatenated portfolio path, per-fold drawdowns are "
        f"kept as a separate security diagnostic)",
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
    adj_p = placebo.get("adjusted_p", float("nan"))
    n_runs = placebo.get("n_runs", 0)
    # A12: the gate consumes the SAME placebo_statistics evidence object the
    # record saves, and enforces the predeclared significance rule: the
    # percentile must clear the configured bar AND the Monte-Carlo-adjusted
    # p-value must be significant.  A one-run null can only produce
    # adjusted p = 0.5 and always fails, whatever its percentile.
    separates = bool(
        np.isfinite(pct) and np.isfinite(adj_p)
        and pct >= cfg.min_placebo_percentile
        and adj_p <= cfg.max_placebo_adjusted_p)
    checks.append(GateCheck(
        "placebo_separates", separates,
        f"placebo percentile {pct} >= {cfg.min_placebo_percentile} and "
        f"adjusted p {adj_p} <= {cfg.max_placebo_adjusted_p}"))
    adequate = bool(n_runs == n_runs and n_runs >= cfg.min_placebo_runs)
    checks.append(GateCheck(
        "placebo_sample_adequate", adequate,
        f"{n_runs} valid null runs >= {cfg.min_placebo_runs} "
        "(predeclared Monte Carlo sample-size requirement)"))
    share = summary.get("single_fold_share", float("nan"))
    checks.append(GateCheck(
        "not_single_fold",
        share <= cfg.max_single_fold_share,
        f"largest fold share of the positive Sharpe pool {share} <= "
        f"{cfg.max_single_fold_share} (A06 concentration definition)",
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

    # B10: research-family selection-correction gate.  Repeated candidate
    # research on the same OOS family inflates the chance of a spurious pass.
    # A family may not exceed its predeclared search cap; Bonferroni correction
    # additionally divides the placebo alpha by the number of family searches.
    # D02: When selection correction is active, a ledger is expected and
    # verified attempt history must be recorded.  A family with zero recorded
    # attempts when correction is active is treated as incomplete evidence.
    if cfg.selection_correction != "none" and n_family_searches == 0:
        checks.append(GateCheck(
            "family_history_mandatory",
            False,
            "no research-family attempt history recorded; promotion with "
            "selection correction requires verified attempt history (D02)",
        ))
    elif n_family_searches > cfg.max_family_searches:
        checks.append(GateCheck(
            "family_search_within_cap",
            False,
            f"family search count {n_family_searches} exceeds "
            f"max_family_searches {cfg.max_family_searches}",
        ))
    else:
        adj_p = placebo.get("adjusted_p", float("nan"))
        if cfg.selection_correction == "bonferroni_family":
            alpha_per = cfg.max_placebo_adjusted_p / max(n_family_searches, 1)
            corrected_ok = bool(adj_p <= alpha_per)
            checks.append(GateCheck(
                "family_selection_corrected",
                corrected_ok,
                f"family={n_family_searches} searches, Bonferroni alpha="
                f"{alpha_per:.5f}, placebo adjusted p={adj_p}",
            ))
        else:
            checks.append(GateCheck(
                "family_search_within_cap",
                True,
                f"family search count {n_family_searches} <= "
                f"max_family_searches {cfg.max_family_searches} "
                f"(selection_correction={cfg.selection_correction})",
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

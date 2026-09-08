"""Backtest-overfitting diagnostics (PBO/CSCV) and robustness scoring."""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def probability_of_backtest_overfitting(
    fold_sharpes: pd.DataFrame,
    n_splits: int = 16,
    max_combinations: int = 70,
) -> dict:
    """PBO via Combinatorially Symmetric Cross-Validation (simplified CSCV).

    ``fold_sharpes``: rows = strategy variants, columns = fold IDs with OOS
    Sharpe per fold.  For each even split of folds into IS/OOS halves, the
    variant ranked best in-sample is checked out-of-sample: PBO is the
    probability that the IS-best variant ranks in the worse OOS half.
    """
    matrix = fold_sharpes.to_numpy(dtype="float64")
    n_variants, n_folds = matrix.shape
    if n_folds < 4 or n_variants < 2:
        return {"pbo": float("nan"), "n_splits": 0}
    fold_ids = np.arange(n_folds)
    half = n_folds // 2
    combos = list(combinations(fold_ids, half))
    if len(combos) > max_combinations:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(combos), size=max_combinations, replace=False)
        combos = [combos[i] for i in sorted(idx)]
    below = 0
    used = 0
    for is_folds in combos:
        is_folds = list(is_folds)
        oos_folds = [f for f in fold_ids if f not in is_folds]
        if not oos_folds:
            continue
        is_perf = matrix[:, is_folds].mean(axis=1)
        oos_perf = matrix[:, oos_folds].mean(axis=1)
        best_is = int(np.argmax(is_perf))
        oos_rank = int((oos_perf > oos_perf[best_is]).sum())  # 0 = best OOS
        if oos_rank >= len(oos_folds) // 2:
            below += 1
        used += 1
    return {"pbo": float(below / used) if used else float("nan"), "n_splits": used}


def robustness_score(
    cost_stress_survives: bool,
    delay_stress_survives: bool,
    perturbation_stability: float,
    bootstrap_positive_prob: float,
    placebo_percentile: float,
    single_fold_share: float,
) -> dict:
    """Aggregate structured diagnostics into one conservative score in [0,1].

    Each component is explicit; failures subtract.  Nothing is hidden.
    """
    components = {
        "cost_stress": 0.25 if cost_stress_survives else -0.25,
        "delay_stress": 0.25 if delay_stress_survives else -0.25,
        "perturbation_stability": 0.20 * float(np.clip(perturbation_stability, 0, 1)),
        "bootstrap": 0.15 * float(np.clip(bootstrap_positive_prob, 0, 1)),
        "placebo": 0.15 * float(np.clip(placebo_percentile, 0, 1)),
        "fold_concentration": -0.20 * float(np.clip(single_fold_share, 0, 1)),
    }
    total = float(np.clip(0.5 + sum(components.values()), 0.0, 1.0))
    return {"robustness_score": total, "components": components}

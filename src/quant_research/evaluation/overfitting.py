"""Backtest-overfitting diagnostics (PBO/CSCV) and robustness scoring."""

from __future__ import annotations

from itertools import combinations
from math import comb

import numpy as np
import pandas as pd


def _unrank_combination(n: int, k: int, index: int) -> list:
    """The ``index``-th k-combination of range(n) in lexicographic order.

    Lets PBO sample combination indices WITHOUT materializing the full
    combinatorial list (C(30, 15) is 155 million -- the old code allocated
    every combination just to keep `max_combinations` of them).
    """
    out = []
    lo = 0
    remaining = k
    while remaining > 0:
        for c in range(lo, n - remaining + 1):
            cnt = comb(n - c - 1, remaining - 1)
            if index < cnt:
                out.append(c)
                lo = c + 1
                remaining -= 1
                break
            index -= cnt
    return out


def probability_of_backtest_overfitting(
    fold_sharpes: pd.DataFrame,
    n_splits: int = 16,
    max_combinations: int = 70,
) -> dict:
    """PBO via Combinatorially Symmetric Cross-Validation (simplified CSCV).

    ``fold_sharpes``: rows = strategy variants, columns = fold IDs with OOS
    Sharpe per fold.  For each even split of folds into IS/OOS halves, the
    variant ranked best in-sample is checked out-of-sample: its OOS rank is
    taken against the STRATEGY distribution (0 = best variant, n_variants-1 =
    worst), and the split counts as overfitting when the relative OOS rank is
    at least 0.5 -- i.e. the IS-best variant lands in the worse half of the
    variants.  Ties count in the strategy's favor (only strictly better
    variants raise the rank).  PBO is the fraction of overfitting splits.

    Combinations are generated lazily and, when the full combinatorial count
    exceeds ``max_combinations``, a fixed-seed random sample of that many is
    evaluated -- the full list is never materialized.
    """
    matrix = fold_sharpes.to_numpy(dtype="float64")
    if not np.isfinite(matrix).all():
        raise ValueError(
            "fold_sharpes contains non-finite values; PBO requires a finite "
            "Sharpe observation for every variant/fold")
    n_variants, n_folds = matrix.shape
    if n_folds < 4 or n_variants < 2:
        return {"pbo": float("nan"), "n_splits": 0}
    fold_ids = np.arange(n_folds)
    half = n_folds // 2
    total = comb(n_folds, half)
    rng = np.random.default_rng(42)
    if total <= max_combinations:
        indices = range(total)
    else:
        indices = np.sort(rng.choice(total, size=max_combinations, replace=False))
    below = 0
    used = 0
    for idx in indices:
        is_folds = list(_unrank_combination(n_folds, half, int(idx)))
        oos_folds = [f for f in fold_ids if f not in is_folds]
        if not oos_folds:
            continue
        is_perf = matrix[:, is_folds].mean(axis=1)
        oos_perf = matrix[:, oos_folds].mean(axis=1)
        best_is = int(np.argmax(is_perf))
        # rank of the IS-best variant WITHIN the strategy (variant) OOS
        # distribution: 0 = best variant OOS, n_variants-1 = worst.
        oos_rank = int((oos_perf > oos_perf[best_is]).sum())
        relative = oos_rank / (n_variants - 1)
        if relative >= 0.5:
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

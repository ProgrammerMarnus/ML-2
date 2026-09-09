"""Empirical-null placebo framework.

Answers: how unusual is the observed OOS performance under a reasonable
no-signal null?  The null is an EMPIRICAL DISTRIBUTION built from many full
walk-forward pipeline repetitions with randomized inputs, not one arbitrary
placebo run.  Modes:

- ``shuffle_features``: each feature column row-shuffled independently
  (destroys time alignment, preserves marginals)
- ``permute_target``: labels permuted jointly with forward returns
- ``block_permute``: contiguous blocks of the target stream permuted
  (preserves short-range autocorrelation of returns)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import AppConfig
from .multiple_testing import benjamini_hochberg

PLACEBO_MODES = ("shuffle_features", "permute_target", "block_permute")


def _block_permute(values: np.ndarray, block_len: int, rng: np.random.Generator) -> np.ndarray:
    n = len(values)
    n_blocks = int(np.ceil(n / block_len))
    order = rng.permutation(n_blocks)
    out = np.concatenate(
        [values[b * block_len:min((b + 1) * block_len, n)] for b in order]
    )
    return out[:n]


def run_placebo_null(
    features: pd.DataFrame,
    y: pd.Series,
    fwd: pd.Series,
    run_pipeline,
    n_runs: int,
    seed: int = 42,
    mode: str = "shuffle_features",
    block_len: int = 21,
) -> pd.DataFrame:
    """Build the empirical null distribution.

    ``run_pipeline(features, y, fwd) -> dict(mean_oos_sharpe=..., median_oos_sharpe=...)``
    must be the full walk-forward pipeline (same folds/protocol as the real
    strategy).  Returns a DataFrame with one row per placebo repetition.
    """
    if mode not in PLACEBO_MODES:
        raise ValueError(f"mode must be one of {PLACEBO_MODES}")
    rng_master = np.random.default_rng(seed)
    rows = []
    for run in range(n_runs):
        run_seed = int(rng_master.integers(0, 2**31 - 1))
        rng = np.random.default_rng(run_seed)
        if mode == "shuffle_features":
            X = features.copy()
            for col in X.columns:
                X[col] = rng.permutation(X[col].to_numpy())
            y_r, f_r = y, fwd
        elif mode == "permute_target":
            X = features
            idx = rng.permutation(len(y))
            y_r = y.iloc[idx].reset_index(drop=True)
            y_r.index = y.index
            f_r = fwd.iloc[idx]
            f_r.index = fwd.index
        else:  # block_permute
            X = features
            idx = _block_permute(np.arange(len(y)), block_len, rng)
            # A03: the permuted VALUES must be assigned to the ORIGINAL
            # chronological index.  The previous code kept each permuted
            # value's original timestamp (y.iloc[idx] carries the source
            # position's index), so the pipeline's chronological .loc lookup
            # silently restored the original date-to-target pairing while the
            # risk history (a shift over a non-chronological index) was
            # scrambled.  Here values move; dates never do.
            y_r = pd.Series(y.to_numpy()[idx], index=y.index, name=y.name)
            f_r = pd.Series(fwd.to_numpy()[idx], index=fwd.index, name=fwd.name)
        if not y_r.index.is_monotonic_increasing or not f_r.index.is_monotonic_increasing:
            raise ValueError(
                f"placebo mode {mode!r} produced a non-chronological index; "
                "risk returns must be derived on a sorted timeline")
        res = run_pipeline(X, y_r, f_r)
        rows.append(
            {
                "placebo_run": run,
                "seed": run_seed,
                "mode": mode,
                "mean_oos_sharpe": res.get("mean_oos_sharpe", float("nan")),
                "median_oos_sharpe": res.get("median_oos_sharpe", float("nan")),
            }
        )
    return pd.DataFrame(rows)


def placebo_statistics(observed_sharpe: float, null: pd.DataFrame, metric: str = "mean_oos_sharpe") -> dict:
    """Percentile of the observed strategy within the empirical null.

    Reports the empirical null mean/median/std, p95, the observed percentile,
    the conservative adjusted p-value ``(1 + #{null >= observed}) / (1 + n)``
    and the number of null runs used.
    """
    null_vals = null[metric].to_numpy(dtype="float64")
    null_vals = null_vals[np.isfinite(null_vals)]
    if len(null_vals) == 0 or not np.isfinite(observed_sharpe):
        return {"percentile": float("nan"), "adjusted_p": float("nan"),
                "percentile_mc_se": float("nan"),
                "null_mean": float("nan"), "null_median": float("nan"),
                "null_std": float("nan"), "null_p95": float("nan"),
                "n_runs": len(null_vals), "observed": observed_sharpe}
    percentile = float((null_vals < observed_sharpe).mean())
    adjusted_p = float((1.0 + (null_vals >= observed_sharpe).sum()) / (1.0 + len(null_vals)))
    # Monte Carlo uncertainty of the empirical percentile (binomial SE)
    mc_se = float(np.sqrt(percentile * (1.0 - percentile) / len(null_vals)))
    return {
        "percentile": percentile,
        "adjusted_p": adjusted_p,
        "percentile_mc_se": mc_se,
        "null_mean": float(null_vals.mean()),
        "null_median": float(np.median(null_vals)),
        "null_std": float(null_vals.std(ddof=1)),
        "null_p95": float(np.percentile(null_vals, 95)),
        "n_runs": int(len(null_vals)),
        "observed": float(observed_sharpe),
    }


def family_adjusted_pvalues(placebo_pvalues: list[float]) -> list[float]:
    """BH-adjust p-values across a family of strategies/tests."""
    return benjamini_hochberg(placebo_pvalues)

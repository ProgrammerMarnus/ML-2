"""Deterministic bootstrap confidence intervals.

Stationary block bootstrap over daily returns; fully seed-deterministic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ResearchConfig
from .metrics import TRADING_DAYS, sharpe_ratio


def bootstrap_sharpe(
    returns: pd.Series,
    n_samples: int | None = None,
    seed: int = 42,
    block_len: int = 20,
    research: ResearchConfig | None = None,
) -> dict:
    """Bootstrap the annualized Sharpe ratio of `returns`.

    Returns structured dict: mean, lo (2.5%), hi (97.5%), positive_prob,
    n_samples, seed.  Deterministic for a given (returns, seed).
    """
    r = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    n = len(r)
    if research is not None:
        n_samples = research.bootstrap_samples if n_samples is None else n_samples
    n_samples = int(n_samples or 500)
    if n < block_len * 2:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "positive_prob": float("nan"), "n_samples": n_samples, "seed": seed}
    vals = r.to_numpy()
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_len))
    starts_pool = np.arange(n - block_len + 1)
    sharpes = np.empty(n_samples)
    for b in range(n_samples):
        starts = rng.choice(starts_pool, size=n_blocks, replace=True)
        sample = np.concatenate([vals[s:s + block_len] for s in starts])[:n]
        mu = sample.mean()
        sd = sample.std(ddof=1)
        sharpes[b] = (mu / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else np.nan
    sharpes = sharpes[np.isfinite(sharpes)]
    if len(sharpes) == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "positive_prob": float("nan"), "n_samples": n_samples, "seed": seed}
    return {
        "mean": float(sharpes.mean()),
        "lo": float(np.percentile(sharpes, 2.5)),
        "hi": float(np.percentile(sharpes, 97.5)),
        "positive_prob": float((sharpes > 0).mean()),
        "n_samples": n_samples,
        "seed": seed,
        "observed": float(sharpe_ratio(r)),
    }

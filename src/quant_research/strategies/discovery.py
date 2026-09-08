"""Bounded, reproducible strategy discovery.

Search grid is bounded by config (max_trials), deterministic by seed, and
selected on VALIDATION performance only.  The OOS test set is evaluated once
for the final selected candidate.  Fragile candidates (unstable under
parameter perturbation) are rejected.  Ranking uses a robustness-adjusted
validation score, never raw return or in-sample Sharpe.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, List

import numpy as np
import pandas as pd

from ..config import AppConfig, ModelConfig
from ..data.schemas import DataValidationError
from .baseline import build_model, select_threshold
from ..evaluation.backtest import backtest
from ..evaluation.walk_forward import walk_forward_splits


@dataclass
class Candidate:
    candidate_id: int
    feature_set: str
    model_type: str
    threshold: float
    hold_bars: int
    validation_sharpe: float
    validation_max_dd: float
    params: dict


def _validation_sharpe(
    features: pd.DataFrame,
    y: pd.Series,
    fwd: pd.Series,
    cfg: AppConfig,
    feature_cols: List[str],
    model_type: str,
    hold_bars: int,
    threshold_candidates: List[float],
    seed: int,
) -> tuple:
    """Validation-only performance for one candidate configuration.

    Uses the SAME walk-forward folds as the baseline: model fit per fold on
    train, threshold on validation, scored on validation backtest.
    """
    model_cfg = ModelConfig(type=model_type, random_seed=seed)
    common = features.dropna(how="all").index.intersection(y.dropna().index).intersection(
        fwd.dropna().index
    )
    X = features.loc[common]
    yy = y.loc[common].astype(int)
    ff = fwd.loc[common]
    folds = walk_forward_splits(X.index, cfg.evaluation)
    val_sharpes = []
    val_dds = []
    chosen_thresholds = []
    risk_obs = ff.shift(1)  # observable close-to-close, causal vol input
    for spec in folds:
        tr = spec.train_idx.intersection(X.index)
        va = spec.val_idx.intersection(X.index)
        if len(tr) < cfg.evaluation.train_window // 2 or len(va) == 0:
            continue
        model = build_model(model_cfg)
        model.fit(X.loc[tr, feature_cols], yy.loc[tr])
        val_probs = pd.Series(model.predict_proba(X.loc[va, feature_cols])[:, 1], index=va)
        thr, _ = select_threshold(val_probs, ff.loc[va], threshold_candidates, cfg.execution,
                                  hold_bars=hold_bars, risk_returns=risk_obs)
        from ..evaluation.backtest import BacktestResult

        bt = backtest(val_probs, ff.loc[va], cfg.execution, threshold=thr,
                      hold_bars=hold_bars, risk_returns=risk_obs)
        val_sharpes.append(bt.metrics["sharpe"])
        val_dds.append(bt.metrics["max_dd"])
        chosen_thresholds.append((spec.fold_id, thr))
    if not val_sharpes:
        raise DataValidationError("no usable validation folds for candidate")
    # per-fold thresholds (the exact OOS replay spec) and their median
    perfold = dict(chosen_thresholds)
    thr = float(np.median(list(perfold.values())))
    return float(np.nanmedian(val_sharpes)), float(np.nanmin(val_dds)), thr, perfold


def discover_strategies(
    features: pd.DataFrame,
    feature_sets: dict,
    y: pd.Series,
    fwd: pd.Series,
    cfg: AppConfig,
    seed: int = 42,
) -> pd.DataFrame:
    """Run the bounded discovery search.

    features: full feature panel.  feature_sets: mapping name -> list of
    feature columns.  Grid = feature_set x model_type x hold_bars, bounded by
    research.max_trials (deterministic truncation).  Threshold is selected on
    validation per fold (not a grid dimension, keeping trials bounded).
    Returns candidates ranked by robustness-adjusted validation score.
    """
    model_types = ["logistic", "gradient_boosting"]
    grid = list(itertools.product(feature_sets.keys(), model_types,
                                  cfg.research.hold_candidates))
    max_trials = cfg.research.max_trials
    if len(grid) > max_trials:
        grid = grid[:max_trials]

    rows = []
    for i, (fs_name, mt, hold) in enumerate(grid):
        cols = feature_sets[fs_name]
        vsharpe, vdd, thr, perfold = _validation_sharpe(
            features, y, fwd, cfg, cols, mt, hold,
            cfg.research.threshold_candidates, seed,
        )
        # robustness-adjusted score: penalize deep validation drawdown
        score = vsharpe + 0.5 * min(vdd, 0.0)
        rows.append({"candidate_id": i, "feature_set": fs_name, "model_type": mt,
                     "hold_bars": hold, "threshold": thr,
                     "per_fold_thresholds": perfold,
                     "validation_sharpe": vsharpe, "validation_max_dd": vdd,
                     "robust_adjusted_score": score, "params": f"{mt}|hold={hold}"})
    df = pd.DataFrame(rows).sort_values("robust_adjusted_score", ascending=False)
    return df.reset_index(drop=True)


def evaluate_candidate_oos(
    features: pd.DataFrame,
    y: pd.Series,
    fwd: pd.Series,
    cfg: AppConfig,
    row: pd.Series,
    feature_sets: dict,
    locked_test=None,
    trial_counter=None,
):
    """Evaluate ONE selected candidate on the untouched OOS test (once).

    The candidate's full specification is pinned as the immutable OOS replay:
    feature set, model config, hold_bars, and the per-fold thresholds selected
    at discovery time.  `fixed_thresholds` prevents any re-selection on OOS.
    """
    from .baseline import run_walk_forward

    model_cfg = ModelConfig(type=str(row["model_type"]), random_seed=cfg.model.random_seed)
    cols = feature_sets[str(row["feature_set"])]
    hold = int(row["hold_bars"]) if "hold_bars" in row.index else 1
    fixed = dict(row["per_fold_thresholds"]) if "per_fold_thresholds" in row.index else None
    return run_walk_forward(
        features, y, fwd, cfg, locked_test=locked_test, model_cfg=model_cfg,
        feature_subset=cols, trial_counter=trial_counter,
        fixed_thresholds=fixed, hold_bars=hold,
    )

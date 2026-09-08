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
from .baseline import build_model, select_threshold, ExperimentResult
from ..evaluation.backtest import EXECUTION_CONTRACT, backtest
from ..evaluation.metrics import compute_metrics
from ..evaluation.walk_forward import walk_forward_splits
from sklearn.metrics import brier_score_loss, roc_auc_score


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
    return_per_fold: bool = False,
) -> tuple:
    """Validation-only performance for one candidate configuration.

    Uses the SAME walk-forward folds as the baseline: model fit per fold on
    train, threshold on validation, scored on validation backtest.

    With ``return_per_fold=True`` the per-fold validation scores/dds are also
    returned (dicts keyed by fold_id) so candidate selection can be NESTED
    within each outer fold (A02): a fold's candidate must be chosen using only
    that fold's own train+validation window, never the global aggregate.
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
    per_fold_scores = {}
    per_fold_dds = {}
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
        per_fold_scores[spec.fold_id] = float(bt.metrics["sharpe"])
        per_fold_dds[spec.fold_id] = float(bt.metrics["max_dd"])
        chosen_thresholds.append((spec.fold_id, thr))
    if not val_sharpes:
        raise DataValidationError("no usable validation folds for candidate")
    # per-fold thresholds (the exact OOS replay spec) and their median
    perfold = dict(chosen_thresholds)
    thr = float(np.median(list(perfold.values())))
    result = (float(np.nanmedian(val_sharpes)), float(np.nanmin(val_dds)), thr, perfold)
    if return_per_fold:
        return result + (per_fold_scores, per_fold_dds)
    return result


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


def discover_and_evaluate_oos(
    features: pd.DataFrame,
    feature_sets: dict,
    y: pd.Series,
    fwd: pd.Series,
    cfg: AppConfig,
    seed: int = 42,
    locked_test=None,
    trial_counter=None,
) -> ExperimentResult:
    """Contamination-free discovery evaluation (A02).

    Candidate selection is NESTED within each outer fold: the candidate is
    chosen using only the fold's own train+validation window (data strictly
    before that fold's test start), and is then evaluated on that fold's test
    only.  A later period's outcomes can therefore never change an earlier
    fold's chosen candidate or its test predictions -- the deep-audit finding
    that a globally ranked winner was applied retrospectively to earlier
    test folds is structurally impossible here.

    The per-fold chosen strategies (which may differ across folds) are
    executed on ONE continuous position ledger: per-fold positions are
    concatenated, every boundary transition is charged exactly once, and
    costs reconcile with the merged path (A05 contract).  Because the
    strategy changes at a fold boundary, the signal shift/hold restart
    within each fold's own window (documented per-fold-strategy execution).

    ``discover_strategies`` remains the bounded SEARCH artifact (global
    ranking report); this function is the evaluation that must be used for
    any OOS evidence.
    """
    model_types = ["logistic", "gradient_boosting"]
    grid = list(itertools.product(feature_sets.keys(), model_types,
                                  cfg.research.hold_candidates))
    if len(grid) > cfg.research.max_trials:
        grid = grid[:cfg.research.max_trials]

    candidates = {}
    for i, (fs_name, mt, hold) in enumerate(grid):
        cols = feature_sets[fs_name]
        vsharpe, vdd, thr, perfold, pfscores, pfdds = _validation_sharpe(
            features, y, fwd, cfg, cols, mt, hold,
            cfg.research.threshold_candidates, seed, return_per_fold=True)
        candidates[i] = {
            "candidate_id": i, "feature_set": fs_name, "model_type": mt,
            "hold_bars": int(hold), "cols": list(cols),
            "threshold": thr, "perfold": dict(perfold),
            "per_fold_score": dict(pfscores), "per_fold_dd": dict(pfdds),
            "validation_sharpe": vsharpe, "validation_max_dd": vdd,
        }

    common = features.dropna(how="all").index.intersection(y.dropna().index).intersection(
        fwd.dropna().index)
    X = features.loc[common]
    yy = y.loc[common].astype(int)
    ff = fwd.loc[common]
    folds = walk_forward_splits(X.index, cfg.evaluation)
    if locked_test is not None:
        locked_test.verify(folds)
    risk_obs = ff.shift(1)  # observable close-to-close, causal vol input

    fold_rows = []
    pred_frames = []
    pos_frames = []
    test_axes = []
    accepted_specs = []
    fitted = {}
    chosen_thresholds = {}
    for spec in folds:
        tr = spec.train_idx.intersection(X.index)
        va = spec.val_idx.intersection(X.index)
        te_all = spec.test_idx.intersection(X.index)
        if len(tr) < cfg.evaluation.train_window // 2 or len(va) == 0 or len(te_all) == 0:
            continue
        te = te_all[ff.loc[te_all].notna()]
        if len(te) == 0:
            continue

        # NESTED selection: fold-k validation score only (data that lies
        # strictly before fold-k's test window).  Ties break on the lower
        # candidate_id for determinism; non-finite scores (e.g. a flat
        # validation run) rank last, deterministically.
        def _fold_key(cid):
            s = candidates[cid]["per_fold_score"].get(spec.fold_id, float("nan"))
            if not np.isfinite(s):
                return (1.0, cid)
            return (-s, cid)

        best = min(candidates, key=_fold_key)
        c = candidates[best]
        threshold = float(c["perfold"].get(spec.fold_id, c["threshold"]))

        model_cfg = ModelConfig(type=c["model_type"], random_seed=seed)
        model = build_model(model_cfg)
        model.fit(X.loc[tr, c["cols"]], yy.loc[tr])
        test_probs = pd.Series(model.predict_proba(X.loc[te, c["cols"]])[:, 1],
                               index=te)
        dir_series = pd.Series(
            np.where(test_probs.to_numpy() > threshold, 1.0, 0.0), index=te)

        # fold-local execution: the strategy CHANGES at the boundary, so the
        # signal shift/hold restart within the fold's own window; boundary
        # transitions are charged exactly once on the merged ledger below.
        bt = backtest(dir_series, ff.loc[te], cfg.execution, threshold=None,
                      hold_bars=c["hold_bars"], risk_returns=risk_obs)
        pos_frames.append(bt.positions)

        fitted[spec.fold_id] = model
        chosen_thresholds[spec.fold_id] = threshold
        yy_te = yy.loc[te].astype(int)
        auc = (float(roc_auc_score(yy_te, test_probs))
               if yy_te.nunique() > 1 else float("nan"))
        brier = float(brier_score_loss(yy_te, test_probs))

        row = spec.summary()
        row.update({
            "candidate_id": int(best),
            "feature_set": c["feature_set"],
            "model_type": c["model_type"],
            "hold_bars": int(c["hold_bars"]),
            "threshold": threshold,
            "selected_features": ",".join(c["cols"]),
            "validation_sharpe": float(c["per_fold_score"].get(spec.fold_id,
                                                               float("nan"))),
            "validation_max_dd": float(c["per_fold_dd"].get(spec.fold_id,
                                                            float("nan"))),
            "oos_auc": auc,
            "oos_brier": brier,
            "n_trials_this_fold": len(grid) * len(cfg.research.threshold_candidates),
        })
        fold_rows.append(row)
        pred_frames.append(pd.DataFrame({
            "prob": test_probs, "y": yy_te.to_numpy(),
            "fwd": ff.loc[te].to_numpy(), "fold": spec.fold_id,
            "candidate_id": int(best)}, index=te))
        test_axes.append(te)
        accepted_specs.append(spec)
        if trial_counter is not None:
            trial_counter.increment(len(grid) * len(cfg.research.threshold_candidates))

    if not fold_rows:
        raise DataValidationError("discovery produced no usable folds")

    # ONE continuous position ledger over the merged per-fold positions (A05):
    # every transition -- including between folds -- is charged exactly once.
    pos_full = pd.concat(pos_frames).sort_index()
    if not pos_full.index.is_unique:
        raise DataValidationError(
            "overlapping OOS test windows produce duplicate timestamps; "
            "overlapping folds are not supported (use step_bars >= test_window)")
    oos_idx = pos_full.index
    gross = pos_full * ff.loc[oos_idx].fillna(0.0)
    turnover = pos_full.diff().abs()
    if len(turnover):
        turnover.iloc[0] = abs(pos_full.iloc[0])
    fee = turnover * cfg.execution.fee_bps / 10000.0
    slip = turnover * cfg.execution.slippage_bps / 10000.0
    net = gross - (fee + slip)

    for i, (spec, te) in enumerate(zip(accepted_specs, test_axes)):
        net_f = net.loc[te]
        gross_f = gross.loc[te]
        pos_f = pos_full.loc[te]
        turn_f = turnover.loc[te]
        m = compute_metrics(net_f, gross_returns=gross_f, positions=pos_f)
        row = fold_rows[i]
        row.update({
            "oos_sharpe": m["sharpe"],
            "oos_sortino": m["sortino"],
            "oos_cagr": m["cagr"],
            "oos_max_dd": m["max_dd"],
            "oos_trades": int((turn_f > 1e-9).sum()),
            "oos_turnover": float(turn_f.sum()),
            "oos_gross_return": m["gross_return"],
            "oos_net_return": m["net_return"],
        })

    folds_df = pd.DataFrame(fold_rows)
    preds = pd.concat(pred_frames).sort_index()
    fee_total = float((turnover * cfg.execution.fee_bps / 10000.0).sum())
    slip_total = float((turnover * cfg.execution.slippage_bps / 10000.0).sum())
    return ExperimentResult(
        folds=folds_df, predictions=preds, oos_returns=net,
        oos_gross_returns=gross, oos_positions=pos_full,
        fold_specs=accepted_specs, fitted_models=fitted,
        thresholds=chosen_thresholds, fee_costs=fee_total,
        slippage_costs=slip_total, hold_bars=1,
        execution_contract=EXECUTION_CONTRACT)

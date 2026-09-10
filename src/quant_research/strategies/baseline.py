"""Baseline walk-forward strategy.

Model fitting, imputation and scaling are strictly fold-local (train only).
Threshold selection uses VALIDATION data only.  Test data flows into
evaluation metrics and nothing else.

The engine supports *exact execution replay* for robustness work: given the
same fold specification, the same per-fold thresholds (``fixed_thresholds``),
and the same fitted models (``fitted_models``), a re-run reproduces the
identical OOS trading specification with only an execution-parameter override
changing.  Stress re-runs therefore never reconstruct an approximate strategy
from raw probabilities and never reselect a threshold on test data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..config import AppConfig, ExecutionConfig, ModelConfig
from ..data.schemas import DataValidationError
from ..evaluation.backtest import EXECUTION_CONTRACT, backtest
from ..evaluation.metrics import compute_metrics, max_drawdown, sharpe_ratio
from ..evaluation.walk_forward import FoldSpec, LockedTestProtocol, walk_forward_splits


@dataclass
class ExperimentResult:
    folds: pd.DataFrame
    predictions: pd.DataFrame
    oos_returns: pd.Series
    fold_specs: List[FoldSpec]
    oos_gross_returns: pd.Series = None  # type: ignore[assignment]
    oos_positions: pd.Series = None  # type: ignore[assignment]
    fitted_models: Dict[int, Pipeline] = field(default_factory=dict)
    thresholds: Dict[int, float] = field(default_factory=dict)
    fee_costs: float = 0.0
    slippage_costs: float = 0.0
    # Executable part of the strategy specification, persisted so replays
    # reproduce the EXACT OOS trading rule (the hold period is part of the
    # candidate's immutable spec -- A09).
    hold_bars: int = 1
    execution_contract: str = EXECUTION_CONTRACT
    # B06: persist the full executable spec so a no-override replay reproduces
    # the identical ledger: the feature columns used for fitting, the risk
    # input identity, per-fold holds/feature subsets, the fold-boundary
    # execution policy, and the (frozen) row anchor.
    feature_subset: Optional[List[str]] = None
    risk_returns: Optional[pd.Series] = None
    model_cfg: Optional[ModelConfig] = None
    boundary_policy: str = "continuous"  # continuous | fold_restart
    per_fold_hold_bars: Dict[int, int] = field(default_factory=dict)
    per_fold_feature_subsets: Dict[int, List[str]] = field(default_factory=dict)
    anchor_index: Optional[pd.Index] = None


def build_model(model_cfg: ModelConfig) -> Pipeline:
    """Fold-local preprocessing pipeline: imputer + scaler + classifier.

    Uses the explicit configuration fields (logreg_C, gb_learning_rate,
    gb_n_estimators, hold_bars) when present, falling back to the ``parameters``
    dict for backward compatibility.  The explicit fields take precedence so that
    two runs with the same ``parameters`` dict but different explicit fields
    execute different strategies (C08).
    """
    # Start from the explicit parameters dict (the canonical source), then
    # overlay explicit fields so they always win.
    params: dict = dict(model_cfg.parameters)
    if model_cfg.type == "logistic":
        C = float(model_cfg.logreg_C) if model_cfg.logreg_C is not None else float(params.get("C", 1.0))
        max_iter = int(params.get("max_iter", 1000))
        clf = LogisticRegression(
            C=C,
            max_iter=max_iter,
            random_state=model_cfg.random_seed,
        )
    elif model_cfg.type == "gradient_boosting":
        lr = float(model_cfg.gb_learning_rate) if model_cfg.gb_learning_rate is not None else float(params.get("learning_rate", 0.05))
        n_est = int(model_cfg.gb_n_estimators) if model_cfg.gb_n_estimators is not None else int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 2))
        clf = GradientBoostingClassifier(
            n_estimators=n_est,
            max_depth=max_depth,
            learning_rate=lr,
            random_state=model_cfg.random_seed,
        )
    else:  # pragma: no cover - ModelConfig validates
        raise DataValidationError(f"unknown model type {model_cfg.type!r}")
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", clf),
        ]
    )


def select_threshold(
    probs: pd.Series,
    fwd_returns: pd.Series,
    candidates: List[float],
    exec_cfg: ExecutionConfig,
    hold_bars: int = 1,
    risk_returns: Optional[pd.Series] = None,
) -> tuple:
    """Choose the trading threshold on VALIDATION data only.

    Ranked by validation net Sharpe with max drawdown as tiebreaker; the
    middle candidate is used when no candidate trades.  Threshold choice uses
    the SAME observable risk-return series as production (so the ranking is
    not biased by a peeking vol scale).
    """
    rows = []
    for t in candidates:
        bt = backtest(probs, fwd_returns, exec_cfg, threshold=float(t),
                      hold_bars=hold_bars, risk_returns=risk_returns)
        rows.append({"threshold": float(t), "sharpe": bt.metrics["sharpe"],
                     "max_dd": bt.metrics["max_dd"], "trades": bt.metrics["trade_count"]})
    table = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    tradable = table.dropna(subset=["sharpe"])
    tradable = tradable[tradable["trades"] > 0]
    if tradable.empty:
        mid = candidates[len(candidates) // 2]
        return float(mid), table
    best = tradable.sort_values(["sharpe", "max_dd"], ascending=[False, False]).iloc[0]
    return float(best["threshold"]), table


def run_walk_forward(
    features: pd.DataFrame,
    y: pd.Series,
    fwd_returns: pd.Series,
    cfg: AppConfig,
    locked_test: Optional[LockedTestProtocol] = None,
    model_cfg: Optional[ModelConfig] = None,
    threshold_candidates: Optional[List[float]] = None,
    feature_subset: Optional[List[str]] = None,
    trial_counter=None,
    exec_cfg: Optional[ExecutionConfig] = None,
    fixed_thresholds: Optional[Dict[int, float]] = None,
    fitted_models: Optional[Dict[int, Pipeline]] = None,
    risk_returns: Optional[pd.Series] = None,
    hold_bars: Optional[int] = None,
    # B06/B15: full-spec attributes so a no-override replay reproduces the
    # identical ledger.
    boundary_policy: str = "continuous",
    per_fold_hold_bars: Optional[Dict[int, int]] = None,
    per_fold_feature_subsets: Optional[Dict[int, List[str]]] = None,
    anchor_index: Optional[pd.Index] = None,
) -> ExperimentResult:
    """Run the baseline walk-forward experiment under the engine's execution
    contract (``backtest.EXECUTION_CONTRACT``).

    Returns fold-level records, OOS predictions, and the concatenated OOS net
    and gross return streams.  The whole OOS path is executed as ONE
    continuous backtest: per-fold executable directions are concatenated
    chronologically and shifted/staged/scaled/costed on a single position
    ledger.  Execution state (signal shift, holding period, position)
    therefore carries across fold boundaries, and every transition -- including
    between adjacent folds -- is charged exactly once (fold rows are slices of
    that ledger).  If `locked_test` is provided, the fold layout is verified
    against the frozen specification before any model is fitted.

    ``risk_returns`` is the OBSERVABLE close-to-close return series (``[k]``
    known at close[k]) used for vol targeting.  It is aligned to the full
    feature anchor so each fold's risk scale has pre-window history (no
    artificial cold-start per fold).  When omitted it defaults to the
    previous-bar close-to-close return of ``fwd_returns`` (i.e.
    ``fwd_returns.shift(1)``), which is observable and causal.

    ``hold_bars`` is the minimum holding period, threaded into the backtest
    exactly as chosen at discovery time (a candidate's hold rule is part of
    the immutable OOS specification).

    Replay knobs (used by robustness; each keeps the exact OOS trading
    specification and changes ONLY the given variable):

    - ``exec_cfg``: execution override (fees/slippage/delay).  Model fitting
      and threshold selection are unaffected.
    - ``fixed_thresholds``: per-fold thresholds selected previously, reused
      verbatim (no threshold selection => no new validation candidates =>
      the global trial counter is not touched).
    - ``fitted_models``: per-fold model pipelines fitted previously, reused
      verbatim (identical predictions/preprocessing).
    """
    model_cfg = model_cfg or cfg.model
    candidates = threshold_candidates or cfg.research.threshold_candidates
    exec_cfg = exec_cfg or cfg.execution

    # C08: Resolve hold_bars from the model configuration when not explicitly
    # passed.  The explicit ``hold_bars`` argument beats the config (used by
    # replay paths that pin a specific hold), but the default sentinel of None
    # means "use cfg.model.hold_bars, falling back to 1".
    if hold_bars is None:
        hold_bars = model_cfg.hold_bars if model_cfg.hold_bars is not None else 1

    # Observable risk-return series aligned to the full anchor (warm-up):
    # risk_obs[k] = close[k]/close[k-1]-1, known at close[k].  fwd[k] is the
    # close[k]->close[k+1] return, so risk_obs == fwd.shift(1).
    risk_obs = (risk_returns if risk_returns is not None
                else fwd_returns.shift(1))

    # B15: Fold geometry is anchored either to an explicitly frozen index
    # (missing-data stress preserves the baseline timeline) or to the FEATURE
    # index only (never to the labels or forward-return availability), so the
    # walk-forward layout is identical under label/return permutation (placebo)
    # and any execution stress.  Rows with missing labels/returns are dropped
    # per split, not by re-cutting the folds: the locked test protocol stays
    # valid across every replay.
    if anchor_index is not None:
        anchor = pd.Index(anchor_index)
        missing_anchor = [i for i in anchor if i not in features.index]
        if missing_anchor:
            raise DataValidationError(
                f"anchor_index contains {len(missing_anchor)} timestamps absent "
                f"from the feature panel; the baseline timeline cannot be replayed"
            )
    else:
        anchor = features.dropna(how="all").index
    X = features.loc[anchor]
    subset = feature_subset or list(X.columns)
    yy = y.loc[anchor]
    ff = fwd_returns.loc[anchor]

    folds = walk_forward_splits(anchor, cfg.evaluation)
    if locked_test is not None:
        locked_test.verify(folds)

    fold_rows = []
    pred_frames = []
    test_axes = []
    dir_frames = []
    accepted_specs = []
    oos_returns = []
    oos_gross = []
    oos_positions = []
    fitted: Dict[int, Pipeline] = {}
    chosen_thresholds: Dict[int, float] = {}
    fee_total = 0.0
    slip_total = 0.0
    for spec in folds:
        tr_all = spec.train_idx.intersection(anchor)
        va_all = spec.val_idx.intersection(anchor)
        te_all = spec.test_idx.intersection(anchor)
        if len(tr_all) < cfg.evaluation.train_window // 2 or len(va_all) == 0 or len(te_all) == 0:
            continue
        # per-split availability filter: drop rows without a usable label/return
        tr = tr_all[(yy.loc[tr_all].notna()) & (ff.loc[tr_all].notna())]
        va = va_all[(yy.loc[va_all].notna()) & (ff.loc[va_all].notna())]
        te = te_all[ff.loc[te_all].notna()]  # returns drive the backtest
        # C12: The reusable walk-forward/backtest APIs must not silently carry
        # position state across interior missing or non-finite forward returns.
        # Missing/infinite returns inside an evaluated window are a data-integrity
        # problem, not a normal warm-up artifact (terminal NaN at the very end of
        # the series is excluded by the fold geometry, which guarantees
        # test_start + test_window <= n).  Reject rather than drop-and-carry.
        te_fwd = ff.loc[te_all]
        bad_mask = ~np.isfinite(te_fwd.to_numpy())
        n_bad = int(bad_mask.sum())
        if n_bad > 0:
            bad_pos = np.flatnonzero(bad_mask)
            # Terminal NaN at the very last evaluated bar is acceptable: it is
            # the last bar of the whole series (no next close exists) and the
            # fold geometry guarantees test_start + test_window <= n only when
            # the full test window has a next-close for every bar -- so a NaN at
            # the last te_all position means the anchor contained one extra trailing
            # bar beyond the guaranteed test window (e.g. the last bar was kept in
            # the anchor because some feature column had a value).  Treat that as
            # acceptable, but reject any interior missing/non-finite returns.
            if not (len(bad_pos) == 1 and bad_pos[0] == len(te_all) - 1):
                raise DataValidationError(
                    f"forward returns on test window {spec.fold_id} contain "
                    f"{n_bad} missing/non-finite value(s) at position(s) "
                    f"{list(bad_pos + 1)} of {len(te_all)} (not solely the terminal "
                    f"bar); interior gaps are not supported by the continuous-position "
                    f"execution model — validate or impute realized returns before "
                    f"walk-forward evaluation")
        if len(tr) == 0 or len(va) == 0 or len(te) == 0:
            continue

        # B06: per-fold feature subset (nested discovery selects per fold).
        fold_subset = (per_fold_feature_subsets or {}).get(spec.fold_id, subset)

        if fitted_models is not None and spec.fold_id in fitted_models:
            model = fitted_models[spec.fold_id]  # exact reuse (identical predictions)
        else:
            model = build_model(model_cfg)
            model.fit(X.loc[tr, fold_subset], yy.loc[tr].astype(int))  # train-only fit
        fitted[spec.fold_id] = model

        if fixed_thresholds is not None and spec.fold_id in fixed_thresholds:
            threshold = float(fixed_thresholds[spec.fold_id])  # pinned; no reselection
            table = None
        else:
            val_probs = pd.Series(model.predict_proba(X.loc[va, subset])[:, 1], index=va)
            threshold, table = select_threshold(
                val_probs, ff.loc[va], candidates, exec_cfg,
                hold_bars=hold_bars, risk_returns=risk_obs,
            )
            if trial_counter is not None:
                trial_counter.increment(len(candidates))
        chosen_thresholds[spec.fold_id] = threshold

        test_probs = pd.Series(model.predict_proba(X.loc[te, fold_subset])[:, 1], index=te)
        # Per-fold threshold applied here to build the executable DIRECTION series.
        # Shift/hold/vol-scale/turnover/costs are applied ONCE over the continuous
        # OOS path (below): execution state carries across fold boundaries and
        # every transition -- including between adjacent folds -- is charged once.

        dir_series = pd.Series(
            np.where(test_probs.to_numpy() > threshold, 1.0, 0.0), index=te)
        yy_te = yy.loc[te].astype(int)
        auc = (float(roc_auc_score(yy_te, test_probs))
               if yy_te.nunique() > 1 else float("nan"))
        brier = float(brier_score_loss(yy_te, test_probs))

        row = spec.summary()
        row.update(
            {
                "threshold": threshold,
                "selected_features": ",".join(fold_subset),
                "model_type": model_cfg.type,
                "oos_auc": auc,
                "oos_brier": brier,
                "n_trials_this_fold": 0 if table is None else len(candidates),
            }
        )
        fold_rows.append(row)
        pred_frames.append(
            pd.DataFrame({"prob": test_probs, "y": yy_te.to_numpy(),
                          "fwd": ff.loc[te].to_numpy(), "fold": spec.fold_id}, index=te)
        )
        test_axes.append(te)
        dir_frames.append(dir_series)
        accepted_specs.append(spec)

    if not fold_rows:
        raise DataValidationError("walk-forward produced no usable folds")

    # B06: per-fold hold bars.  The default continuous policy applies a single
    # hold over the concatenated OOS path; fold_restart (used by nested
    # discovery) executes each fold's backtest independently so the hold state
    # restarts at each fold boundary.
    if per_fold_hold_bars:
        effective_hold = {spec.fold_id: per_fold_hold_bars.get(spec.fold_id, hold_bars)
                          for spec in accepted_specs}
    else:
        effective_hold = {spec.fold_id: hold_bars for spec in accepted_specs}

    if boundary_policy == "fold_restart":
        # B06: fold-local execution — each fold's backtest is independent so the
        # signal shift/hold restart within the fold's own window; boundary
        # transitions are charged exactly once on the merged ledger below.
        pos_frames = []
        for idx_s, (spec, te) in enumerate(zip(accepted_specs, test_axes)):
            if len(te) == 0:
                continue
            hold = effective_hold[spec.fold_id]
            bt_local = backtest(dir_frames[idx_s], ff.loc[te], exec_cfg,
                                threshold=None, hold_bars=hold, risk_returns=risk_obs)
            pos_frames.append(bt_local.positions)
        pos_full = pd.concat(pos_frames).sort_index()
        if not pos_full.index.is_unique:
            raise DataValidationError(
                "overlapping OOS test windows produce duplicate timestamps; "
                "overlapping folds are not supported until a prediction-combination "
                "policy is defined (use step_bars >= test_window)")
        oos_idx = pos_full.index
        gross_full = pos_full * ff.loc[oos_idx].fillna(0.0)
        turnover_full = pos_full.diff().abs()
        if len(turnover_full):
            turnover_full.iloc[0] = abs(pos_full.iloc[0])
        net_full = gross_full - (turnover_full * (exec_cfg.fee_bps + exec_cfg.slippage_bps) / 10000.0)
        fee_total = float(turnover_full.sum()) * exec_cfg.fee_bps / 10000.0
        slip_total = float(turnover_full.sum()) * exec_cfg.slippage_bps / 10000.0
        bt = None  # per-fold; metrics computed per slice below
    else:
        # Execute the whole OOS path as ONE continuous backtest over the merged
        # test timeline (see ``backtest.EXECUTION_CONTRACT``): per-fold directions
        # are concatenated chronologically then shifted/staged/scaled/costed as a
        # single path.  Each fold below is a slice of that ledger, so execution
        # state (signal shift, holding period, position) carries across fold
        # boundaries, every transition -- including between adjacent folds -- is
        # charged exactly once, and ``folds.oos_turnover`` reconciles exactly to
        # the continuous position path.
        dir_full = pd.concat(dir_frames).sort_index()
        if not dir_full.index.is_unique:
            raise DataValidationError(
                "overlapping OOS test windows produce duplicate timestamps; "
                "overlapping folds are not supported until a prediction-combination "
                "policy is defined (use step_bars >= test_window)")
        oos_idx = dir_full.index
        bt = backtest(dir_full, ff.loc[oos_idx], exec_cfg, threshold=None,
                      hold_bars=hold_bars, risk_returns=risk_obs)

    oos_returns = []
    oos_gross = []
    oos_positions = []
    fee_total = fee_total if boundary_policy == "fold_restart" else 0.0
    slip_total = slip_total if boundary_policy == "fold_restart" else 0.0
    for i, (spec, te) in enumerate(zip(accepted_specs, test_axes)):
        if len(te) == 0:
            continue
        if bt is not None:
            net_f = bt.net_returns.loc[te]
            gross_f = bt.gross_returns.loc[te]
            pos_f = bt.positions.loc[te]
            turn_f = bt.turnover.loc[te]
            fee_total += float(turn_f.sum()) * exec_cfg.fee_bps / 10000.0
            slip_total += float(turn_f.sum()) * exec_cfg.slippage_bps / 10000.0
        else:
            pos_f = pos_full.loc[te]
            gross_f = pos_f * ff.loc[te].fillna(0.0)
            net_f = net_full.loc[te]
            turn_f = turnover.loc[te]
            if te[0] == oos_idx[0]:
                turn_f.iloc[0] = abs(pos_f.iloc[0])
        m = compute_metrics(net_f, gross_returns=gross_f, positions=pos_f)
        row = fold_rows[i]
        row.update(
            {
                "oos_sharpe": m["sharpe"],
                "oos_sortino": m["sortino"],
                "oos_cagr": m["cagr"],
                "oos_max_dd": m["max_dd"],
                "oos_trades": int((turn_f > 1e-9).sum()),
                "oos_turnover": float(turn_f.sum()),
                "oos_gross_return": m["gross_return"],
                "oos_net_return": m["net_return"],
            }
        )
        oos_returns.append(net_f)
        oos_gross.append(gross_f)
        oos_positions.append(pos_f)

    folds_df = pd.DataFrame(fold_rows)
    preds = pd.concat(pred_frames).sort_index()
    # B06: store the full executable spec so a no-override replay reproduces the
    # identical ledger.
    oos_ret = (pd.concat(oos_returns).sort_index() if oos_returns
               else (bt.net_returns if bt is not None else net_full))
    oos_gross_ret = (pd.concat(oos_gross).sort_index() if oos_gross
                     else (bt.gross_returns if bt is not None else gross_full))
    oos_pos = (pd.concat(oos_positions).sort_index() if oos_positions
               else (bt.positions if bt is not None else pos_full))
    return ExperimentResult(folds=folds_df, predictions=preds, oos_returns=oos_ret,
                            oos_gross_returns=oos_gross_ret, oos_positions=oos_pos,
                            fold_specs=accepted_specs,
                            fitted_models=fitted, thresholds=chosen_thresholds,
                            fee_costs=fee_total, slippage_costs=slip_total,
                            hold_bars=hold_bars, execution_contract=EXECUTION_CONTRACT,
                            feature_subset=subset, risk_returns=risk_obs,
                            model_cfg=model_cfg, boundary_policy=boundary_policy,
                            per_fold_hold_bars=effective_hold,
                            per_fold_feature_subsets=per_fold_feature_subsets or {},
                            anchor_index=anchor)


def summarize_experiment(result: ExperimentResult) -> dict:
    f = result.folds
    # A06: fold concentration is the LARGEST fold's share of the total
    # positive Sharpe pool.  The old ratio (sum of positive Sharpes / sum of
    # |all| Sharpes) measured no concentration at all: [1, 1, 1, 1] scored
    # 1.0 (failing the gate) while [10, 0.01, 0.01, -9] scored 0.53 (passing)
    # despite one fold supplying 99.8% of the positive Sharpe.  Flat/NaN folds
    # (zero-trading) contribute zero; a pool with no positive edge is NaN
    # (the gate then fails conservatively).
    sharpe = pd.to_numeric(f["oos_sharpe"], errors="coerce")
    positive = sharpe.clip(lower=0.0).fillna(0.0)
    pool = float(positive.sum())
    single_fold_share = float(positive.max() / pool) if pool > 0 else float("nan")
    net = result.oos_returns
    gross = result.oos_gross_returns if result.oos_gross_returns is not None else net
    net_tot = float((1.0 + net.fillna(0)).prod() - 1.0) if len(net) else float("nan")
    gross_tot = float((1.0 + gross.fillna(0)).prod() - 1.0) if len(gross) else float("nan")
    return {
        "mean_oos_sharpe": float(f["oos_sharpe"].mean()),
        "median_oos_sharpe": float(f["oos_sharpe"].median()),
        "mean_oos_auc": float(f["oos_auc"].mean()),
        "mean_oos_brier": float(f["oos_brier"].mean()),
        "worst_oos_dd": float(f["oos_max_dd"].min()),
        # Full concatenated OOS path drawdown (actual portfolio path, initial
        # capital included).  Promotion gates use THIS; per-fold worst_oos_dd
        # is retained as a stability diagnostic (A15).
        "full_oos_max_dd": float(max_drawdown(net)) if len(net) else float("nan"),
        "total_oos_trades": int(f["oos_trades"].sum()),
        "positive_folds": int((f["oos_sharpe"] > 0).sum()),
        "n_folds": int(len(f)),
        "single_fold_share": single_fold_share,
        "full_oos_sharpe": float(sharpe_ratio(net)),
        "full_oos_net_sharpe": float(sharpe_ratio(net)),
        "full_oos_gross_sharpe": float(sharpe_ratio(gross)),
        "full_oos_net_return": float(net_tot),
        "full_oos_gross_return": float(gross_tot),
        "fee_cost": float(result.fee_costs),
        "slippage_cost": float(result.slippage_costs),
        "cost_drag": float(gross_tot - net_tot),  # compounded drag, consistent with metrics.cost_drag
    }

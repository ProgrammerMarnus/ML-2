"""E08: exact replay of a nested-discovery (fold_restart) OOS ledger."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from ..data.schemas import DataValidationError
from ..evaluation.backtest import EXECUTION_CONTRACT, backtest as _backtest
from ..evaluation.metrics import compute_metrics as _metrics
from .baseline import ExperimentResult


def _finite_mask(yy, ff, idx):
    yv = pd.to_numeric(yy.loc[idx], errors="coerce").to_numpy(dtype=float)
    fv = pd.to_numeric(ff.loc[idx], errors="coerce").to_numpy(dtype=float)
    good = np.isfinite(yv) & np.isfinite(fv)
    return idx[np.flatnonzero(good)]


def replay_discovery_oos(features, y, fwd, cfg, baseline, exec_cfg=None,
                         trial_counter=None, model_cfg=None):
    """Reuse fitted models verbatim; re-execute fold-local backtests; merge.

    Only execution costs (``exec_cfg``) may change.  Thresholds, features,
    holds and fitted models are never reselected.  ``trial_counter`` is never
    advanced.
    """
    from ..config import ExecutionConfig

    exec_cfg = exec_cfg or cfg.execution
    if not isinstance(exec_cfg, ExecutionConfig):
        exec_cfg = ExecutionConfig(**dict(exec_cfg))
    # E14: when the caller overrides the model (parameter stress), refit each
    # fold's estimator with the perturbed config; otherwise reuse fitted.
    _override_cfg = model_cfg
    common = features.dropna(how="all").index
    X = features.loc[common]
    yy = y.loc[common]
    ff = fwd.loc[common]
    risk_obs = baseline.risk_returns
    if risk_obs is None:
        risk_obs = ff.shift(1)
    fitted = baseline.fitted_models or {}
    thresholds = {int(k): float(v) for k, v in (baseline.thresholds or {}).items()}
    holds = {int(k): int(v) for k, v in (baseline.per_fold_hold_bars or {}).items()}
    subsets = {int(k): list(v) for k, v in (baseline.per_fold_feature_subsets or {}).items()}
    pos_frames = []
    fold_rows = []
    pred_frames = []
    test_axes = []
    accepted_specs = list(baseline.fold_specs)
    for spec in accepted_specs:
        te_all = spec.test_idx.intersection(X.index)
        cols = subsets.get(int(spec.fold_id), list(baseline.feature_subset or X.columns))
        model = fitted.get(int(spec.fold_id))
        if _override_cfg is not None:
            # E14 stress: refit this fold's training window with the perturbed
            # config (same fold-local imputer+scaler protocol as discovery).
            from ..evaluation.walk_forward import walk_forward_splits as _splits
            from .baseline import build_model as _build

            _folds = _splits(X.index, cfg.evaluation)
            _fspec = next(s for s in _folds if int(s.fold_id) == int(spec.fold_id))
            _tr = _finite_mask(yy, ff, _fspec.train_idx)
            if len(_tr) == 0:
                raise DataValidationError(
                    f"discovery replay has no usable training for fold {spec.fold_id}")
            model = _build(_override_cfg)
            model.fit(X.loc[_tr, cols].to_numpy(), yy.loc[_tr].astype(int).to_numpy())
        if model is None or len(te_all) == 0:
            raise DataValidationError(
                f"discovery replay missing model/window for fold {spec.fold_id}")
        te = te_all[ff.loc[te_all].notna()]
        if len(te) == 0:
            raise DataValidationError(
                f"discovery replay has no scorable bars for fold {spec.fold_id}")
        test_probs = pd.Series(model.predict_proba(X.loc[te, cols])[:, 1], index=te)
        threshold = float(thresholds[int(spec.fold_id)])
        dir_series = pd.Series(
            np.where(test_probs.to_numpy() > threshold, 1.0, 0.0), index=te)
        bt = _backtest(dir_series, ff.loc[te], exec_cfg, threshold=None,
                       hold_bars=int(holds.get(int(spec.fold_id), int(baseline.hold_bars))),
                       risk_returns=risk_obs)
        pos_frames.append(bt.positions)
        yy_te = yy.loc[te].astype(int)
        auc = (float(roc_auc_score(yy_te, test_probs))
               if yy_te.nunique() > 1 else float("nan"))
        brier = float(brier_score_loss(yy_te, test_probs))
        base_row = baseline.folds.loc[
            baseline.folds["fold_id"] == spec.fold_id].iloc[0].to_dict()
        base_row.update({"oos_auc": auc, "oos_brier": brier})
        fold_rows.append(base_row)
        pred_frames.append(pd.DataFrame({
            "prob": test_probs, "y": yy_te.to_numpy(),
            "fwd": ff.loc[te].to_numpy(), "fold": spec.fold_id}, index=te))
        test_axes.append(te)
    pos_full = pd.concat(pos_frames).sort_index()
    oos_idx = pos_full.index
    gross = pos_full * ff.loc[oos_idx].fillna(0.0)
    turnover = pos_full.diff().abs()
    if len(turnover):
        turnover.iloc[0] = abs(pos_full.iloc[0])
    fee = turnover * exec_cfg.fee_bps / 10000.0
    slip = turnover * exec_cfg.slippage_bps / 10000.0
    net = gross - (fee + slip)
    for i, (spec, te) in enumerate(zip(accepted_specs, test_axes)):
        net_f = net.loc[te]
        gross_f = gross.loc[te]
        pos_f = pos_full.loc[te]
        turn_f = turnover.loc[te]
        m = _metrics(net_f, gross_returns=gross_f, positions=pos_f)
        row = fold_rows[i]
        row.update({
            "oos_sharpe": m["sharpe"], "oos_sortino": m["sortino"],
            "oos_cagr": m["cagr"], "oos_max_dd": m["max_dd"],
            "oos_trades": int((turn_f > 1e-9).sum()),
            "oos_turnover": float(turn_f.sum()),
            "oos_gross_return": m["gross_return"],
            "oos_net_return": m["net_return"],
        })
    folds_df = pd.DataFrame(fold_rows)
    preds = pd.concat(pred_frames).sort_index()
    fee_total = float((turnover * exec_cfg.fee_bps / 10000.0).sum())
    slip_total = float((turnover * exec_cfg.slippage_bps / 10000.0).sum())
    return ExperimentResult(
        folds=folds_df, predictions=preds, oos_returns=net,
        oos_gross_returns=gross, oos_positions=pos_full,
        fold_specs=accepted_specs, fitted_models=dict(fitted),
        thresholds=dict(thresholds), fee_costs=fee_total,
        slippage_costs=slip_total, hold_bars=int(baseline.hold_bars),
        execution_contract=EXECUTION_CONTRACT,
        feature_subset=list(baseline.feature_subset or X.columns),
        risk_returns=risk_obs, model_cfg=baseline.model_cfg,
        boundary_policy="fold_restart",
        per_fold_hold_bars=dict(holds),
        per_fold_feature_subsets={int(k): list(v) for k, v in subsets.items()},
        anchor_index=baseline.anchor_index)

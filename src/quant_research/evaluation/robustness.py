"""Robustness battery: structured stress tests on the exact OOS execution path.

Every stress re-runs the EXACT fold-level OOS trading specification generated
by the walk-forward engine and never reconstructs an approximate strategy from
raw probabilities:

- same fold boundaries (verified against the locked test protocol)
- same selected features and model parameters
- same per-fold threshold (pinned from the baseline run, never reselected)
- same preprocessing (fold-local imputer/scaler; fitted models reused verbatim)
- same signal timestamps and execution convention (inherent 1-bar lag + delay)
- same position sizing (vol targeting) and turnover calculation

Only the robustness variable being stressed may change.  Stressing therefore
never reselects a model/threshold using test data.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from ..config import AppConfig, ModelConfig
from ..evaluation.backtest import VOL_LOOKBACK
from ..evaluation.metrics import max_drawdown, sharpe_ratio
from ..strategies.baseline import ExperimentResult, run_walk_forward

COST_FEE_GRID = (0.0, 2.5, 5.0, 10.0, 20.0)
SLIPPAGE_GRID = (0.0, 1.0, 2.0, 5.0, 10.0)
DELAY_GRID = (0, 1, 2, 3)
PARAM_FACTORS = (0.5, 0.8, 1.25, 2.0)
MISSING_FRAC = 0.10
MISSING_SEED = 42


def fixed_thresholds_from(baseline: ExperimentResult) -> dict:
    """Per-fold thresholds selected by the baseline walk-forward engine."""
    return {
        int(r["fold_id"]): float(r["threshold"])
        for _, r in baseline.folds.iterrows()
    }


def replay_oos(
    features: pd.DataFrame,
    y: pd.Series,
    fwd: pd.Series,
    cfg: AppConfig,
    baseline: ExperimentResult,
    locked_test,
    exec_cfg=None,
    model_cfg: ModelConfig | None = None,
    feature_subset=None,
    reuse_models: bool = True,
    trial_counter=None,
) -> ExperimentResult:
    """Re-run the exact baseline OOS trading specification with one override.

    Thresholds are pinned to the baseline selection; fitted models are reused
    (identical predictions) unless the model itself must change (parameter
    perturbation) or the features are perturbed (missing-data stress).
    ``trial_counter`` is deliberately NOT advanced: no new validation
    candidates are evaluated, so robustness runs never consume research trials.

    The candidate's immutable OOS specification -- including the holding
    period, which is part of the strategy -- is replayed verbatim from the
    baseline result (``baseline.hold_bars``) so a no-override replay can never
    silently fall back to a one-bar hold (A09).
    """
    model_cfg = model_cfg or cfg.model
    fitted = baseline.fitted_models if reuse_models else None
    return run_walk_forward(
        features, y, fwd, cfg,
        locked_test=locked_test,
        exec_cfg=exec_cfg,
        model_cfg=model_cfg,
        feature_subset=feature_subset or list(features.columns),
        fixed_thresholds=fixed_thresholds_from(baseline),
        fitted_models=fitted,
        trial_counter=trial_counter,
        hold_bars=int(baseline.hold_bars),
    )


def _summarize_result(res: ExperimentResult, **extra) -> dict:
    net = res.oos_returns
    gross = res.oos_gross_returns if res.oos_gross_returns is not None else net
    row = {
        "sharpe": float(sharpe_ratio(net)),
        "gross_sharpe": float(sharpe_ratio(gross)),
        "net_return": float((1.0 + net.fillna(0)).prod() - 1.0) if len(net) else float("nan"),
        "gross_return": float((1.0 + gross.fillna(0)).prod() - 1.0) if len(gross) else float("nan"),
        "max_dd": float(max_drawdown(net)),
        "annual_turnover": float(
            res.folds["oos_turnover"].sum() / max(len(net) / 252.0, 1e-9)
        ),
        "fee_cost": float(res.fee_costs),
        "slippage_cost": float(res.slippage_costs),
        "cost_drag": float(
            (1.0 + gross.fillna(0)).prod() - (1.0 + net.fillna(0)).prod()
        ) if len(net) else float("nan"),
    }
    row.update(extra)
    return row


def _assert_selection_identical(baseline: ExperimentResult,
                                res: ExperimentResult) -> None:
    """Fail loudly unless ALL selection artifacts match the baseline exactly.

    A robustness replay must never reselect anything: fold boundaries, pinned
    thresholds, selected features, fitted model parameters, and predictions
    must be bit-identical to the baseline OOS run.
    """
    if len(baseline.fold_specs) != len(res.fold_specs):
        raise AssertionError("replay changed the number of folds")
    for s0, s1 in zip(baseline.fold_specs, res.fold_specs):
        if (not s0.train_idx.equals(s1.train_idx)
                or not s0.val_idx.equals(s1.val_idx)
                or not s0.test_idx.equals(s1.test_idx)):
            raise AssertionError("replay changed fold boundaries")
    b = baseline.folds.reset_index(drop=True)
    r = res.folds.reset_index(drop=True)
    if not (b["threshold"].to_numpy() == r["threshold"].to_numpy()).all():
        raise AssertionError("replay reselected thresholds (must be pinned)")
    if not (b["selected_features"].to_numpy() == r["selected_features"].to_numpy()).all():
        raise AssertionError("replay reselected features (must be pinned)")
    for fid, m0 in baseline.fitted_models.items():
        m1 = res.fitted_models.get(fid)
        if m1 is None:
            raise AssertionError(f"replay lost fitted model for fold {fid}")
        c0, c1 = m0.named_steps["model"], m1.named_steps["model"]
        if not (np.array_equal(c0.coef_, c1.coef_)
                and np.array_equal(c0.intercept_, c1.intercept_)):
            raise AssertionError(f"replay refitted model parameters for fold {fid}")
    p0 = baseline.predictions["prob"].sort_index()
    p1 = res.predictions["prob"].sort_index()
    if len(p0) != len(p1) or not np.array_equal(p0.to_numpy(), p1.to_numpy()):
        raise AssertionError("replay predictions differ (models must be reused exactly)")


def assert_cost_accounting(res: ExperimentResult, fee_bps: float,
                           slippage_bps: float) -> None:
    """Exact cost accounting invariants for one OOS replay.

    The whole OOS path is ONE continuous position ledger (``res.oos_positions``):

    - fees scale exactly with total turnover
    - slippage scales exactly with total turnover
    - gross returns are untouched by costs; net = gross - costs bar-for-bar,
      where the per-bar cost is |position change| * (fee+slip) bps -- checked
      exactly over the full continuous path.  There is no per-fold position
      reset: a transition between adjacent folds appears at the first bar of
      the later fold and is charged exactly once.


    - fold-turnover slices reconcile exactly to the continuous ledger total,
      proving fold rows are faithful slices of the one executed path.



    """
    p = res.oos_positions
    if p is None:
        raise AssertionError("oos_positions missing; cannot verify costs")
    p = p.sort_index()
    turn_bar = p.diff().abs()
    if len(turn_bar):
        turn_bar.iat[0] = abs(p.iat[0])
    turnover = float(turn_bar.sum())
    np.testing.assert_allclose(
        res.fee_costs, turnover * fee_bps / 1e4, rtol=0, atol=1e-10,
        err_msg="fee costs do not scale exactly with turnover")
    np.testing.assert_allclose(
        res.slippage_costs, turnover * slippage_bps / 1e4, rtol=0, atol=1e-10,
        err_msg="slippage costs do not scale exactly with turnover")
    net = res.oos_returns.sort_index()
    gross = res.oos_gross_returns.sort_index()
    # aggregate reconciliation: total cost drag == fee + slippage totals
    np.testing.assert_allclose(
        float((gross.fillna(0) - net.fillna(0)).sum()),
        float(res.fee_costs + res.slippage_costs),
        rtol=0, atol=1e-9,
        err_msg="total gross - net does not reconcile with total costs")
    # exact per-bar reconciliation against |d(position)| over the CONTINUOUS path#
    total_bps = (fee_bps + slippage_bps) / 1e4
    np.testing.assert_allclose(
        (gross.fillna(0) - net.fillna(0)).to_numpy(),
        (turn_bar * total_bps).to_numpy(),
        rtol=0, atol=1e-12,
        err_msg="per-bar gross - net does not reconcile with turnover-scaled costs")
    # fold slices must coverthe continuous ledger exactly once#
    fold_turn = float(res.folds["oos_turnover"].sum())
    np.testing.assert_allclose(
        fold_turn, turnover, rtol=0, atol=1e-9,
        err_msg="fold turnover slices do not reconcile with the continuous ledger")



def assert_replay_matches_baseline(baseline: ExperimentResult,
                                   res: ExperimentResult,
                                   delay_bars: int = 0) -> None:
    """Fail loudly unless a robustness replay aligns with the baseline path.


    The engine executes ONE continuous OOS path (both baseline and replay share
    the identical position ledger).




    - delay_bars == 0: the replay must be the baseline execution exactly --
      identical selection artifacts (see _assert_selection_identical), identical
      positions, identical gross returns and turnover; only fee/slippage bps may
      change the net economics.



    - delay_bars == d: selection artifacts and realized return observations are
      identical, and the position SUPPORT of the full path must shift exactly by d:
      ``support_d[t] == support_0[t-d]`` for t at least ``VOL_LOOKBACK + d``
      bars into the path.  The warmup is whole-path, not per-fold: only the
      first ``1 + d`` bars (the very start of the OOS path) are flat in the
      delayed run -- once the signal shift has passed, baselined and delayed
      supports are identical shifted copies because the same continuous ledger is
      re-executed (the per-fold re-warm assumption no longer exists).


    """
    _assert_selection_identical(baseline, res)
    idx0 = baseline.oos_returns.sort_index().index
    idx1 = res.oos_returns.sort_index().index
    if len(idx0) != len(idx1) or not (idx0 == idx1).all():
        raise AssertionError("replay changed the realized OOS return timeline")
    p0 = baseline.oos_positions
    p1 = res.oos_positions
    if p0 is None or p1 is None:
        raise AssertionError("oos_positions missing; cannot verify alignment")
    w0 = (p0 != 0)
    w1 = (p1 != 0)
    if delay_bars == 0:
        if not np.array_equal(w0, w1):
            raise AssertionError("delay=0 replay positions differ from baseline positions")
    else:
        d = int(delay_bars)
        start = VOL_LOOKBACK + d  # beyond signal + vol-scale warmup
        if len(w1) > start:
            # full-path shift invariant: support_d[t] == support_0[t-d]
            if not np.array_equal(w1[start:], w0[start - d:len(w1) - d]):
                raise AssertionError(
                    f"delayed positions are not the baseline positions "
                    f"shifted by {d} bars over the continuous OOS path")
        if not (w1[:min(1 + d, len(w1))] == 0).all():
            raise AssertionError(
                f"delay={d}: warmup bars at the start of the OOS path are not flat")
    if delay_bars == 0:
        g0 = baseline.oos_gross_returns.sort_index()
        g1 = res.oos_gross_returns.sort_index()
        if not np.array_equal(g0.to_numpy(), g1.to_numpy()):
            raise AssertionError("delay=0 replay gross returns differ from baseline")
        t0 = float(baseline.folds["oos_turnover"].sum())
        t1 = float(res.folds["oos_turnover"].sum())
        np.testing.assert_allclose(t0, t1, rtol=0, atol=1e-12,
                                   err_msg="delay=0 replay turnover differs")


def cost_stress(
    features,
    y,
    fwd,
    cfg: AppConfig,
    baseline: ExperimentResult,
    locked_test,
    fee_grid=COST_FEE_GRID,
) -> pd.DataFrame:
    """Stress ONLY fees; everything else reproduces the baseline OOS run."""
    rows = []
    for fee in fee_grid:
        exec_cfg = replace(cfg.execution, fee_bps=fee)
        res = replay_oos(features, y, fwd, cfg, baseline, locked_test, exec_cfg=exec_cfg)
        assert_replay_matches_baseline(baseline, res, delay_bars=0)
        assert_cost_accounting(res, fee, exec_cfg.slippage_bps)
        rows.append(_summarize_result(
            res, fee_bps=fee, slippage_bps=exec_cfg.slippage_bps,
            delay_bars=exec_cfg.signal_delay_bars))
    return pd.DataFrame(rows)


def slippage_stress(
    features,
    y,
    fwd,
    cfg: AppConfig,
    baseline: ExperimentResult,
    locked_test,
    slip_grid=SLIPPAGE_GRID,
) -> pd.DataFrame:
    """Stress ONLY slippage; everything else reproduces the baseline OOS run."""
    rows = []
    for slip in slip_grid:
        exec_cfg = replace(cfg.execution, slippage_bps=slip)
        res = replay_oos(features, y, fwd, cfg, baseline, locked_test, exec_cfg=exec_cfg)
        assert_replay_matches_baseline(baseline, res, delay_bars=0)
        assert_cost_accounting(res, exec_cfg.fee_bps, slip)
        rows.append(_summarize_result(
            res, fee_bps=exec_cfg.fee_bps, slippage_bps=slip,
            delay_bars=exec_cfg.signal_delay_bars))
    return pd.DataFrame(rows)


def delay_stress(
    features,
    y,
    fwd,
    cfg: AppConfig,
    baseline: ExperimentResult,
    locked_test,
    delays=DELAY_GRID,
) -> pd.DataFrame:
    """Stress ONLY signal delay; changes timing, never model selection."""
    rows = []
    for d in delays:
        exec_cfg = replace(cfg.execution, signal_delay_bars=d)
        res = replay_oos(features, y, fwd, cfg, baseline, locked_test, exec_cfg=exec_cfg)
        assert_replay_matches_baseline(baseline, res, delay_bars=d)
        assert_cost_accounting(res, exec_cfg.fee_bps, exec_cfg.slippage_bps)
        rows.append(_summarize_result(
            res, fee_bps=exec_cfg.fee_bps, slippage_bps=exec_cfg.slippage_bps,
            delay_bars=d))
    return pd.DataFrame(rows)


def parameter_perturbation(
    features,
    y,
    fwd,
    cfg: AppConfig,
    baseline: ExperimentResult,
    locked_test,
    factors=PARAM_FACTORS,
) -> pd.DataFrame:
    """Stress model parameters (regularization factor on C).

    The model is refitted per fold (new params), but thresholds remain the
    baseline's validation-selected ones and the fold/feature/execution spec is
    unchanged.  ``params["C"]`` is scaled by ``factor`` (logistic models); a
    factor of 1.0 reproduces the baseline.
    """
    rows = []
    base = cfg.model
    for f in factors:
        params = dict(base.parameters)
        params["C"] = float(params.get("C", 1.0)) * f
        model_cfg = ModelConfig(type=base.type, random_seed=base.random_seed,
                                parameters=params)
        res = replay_oos(features, y, fwd, cfg, baseline, locked_test,
                         model_cfg=model_cfg, reuse_models=False)
        rows.append(_summarize_result(res, c_factor=float(f),
                                      model_type=model_cfg.type))
    return pd.DataFrame(rows)


def missing_data_stress(
    features,
    y,
    fwd,
    cfg: AppConfig,
    baseline: ExperimentResult,
    locked_test,
    frac: float = MISSING_FRAC,
    seed: int = MISSING_SEED,
) -> pd.DataFrame:
    """Stress missing feature cells: mask a random fraction and re-run.

    The fold-local imputer re-fits and handles the masked cells exactly as it
    would for warm-up/real missing data; thresholds remain the baseline's
    validation-selected ones; execution is unchanged.
    """
    rng = np.random.default_rng(seed)
    X = features.copy()
    mask = rng.random(X.shape) < frac
    Xm = X.mask(pd.DataFrame(mask, index=X.index, columns=X.columns))
    res = replay_oos(Xm, y, fwd, cfg, baseline, locked_test, reuse_models=False)
    row = _summarize_result(res, missing_frac=float(frac), seed=int(seed))
    return pd.DataFrame([row])


def robustness_battery(
    features,
    y,
    fwd,
    cfg: AppConfig,
    baseline: ExperimentResult,
    locked_test,
) -> dict:
    """Run the full robustness battery on the exact OOS execution path."""
    return {
        "cost_stress": cost_stress(features, y, fwd, cfg, baseline, locked_test),
        "slippage_stress": slippage_stress(features, y, fwd, cfg, baseline, locked_test),
        "delay_stress": delay_stress(features, y, fwd, cfg, baseline, locked_test),
        "parameter_perturbation": parameter_perturbation(
            features, y, fwd, cfg, baseline, locked_test),
        "missing_data": missing_data_stress(features, y, fwd, cfg, baseline, locked_test),
    }


def regime_analysis(net_returns: pd.Series, regime_flags: pd.DataFrame) -> pd.DataFrame:
    """Segment net returns by precomputed regime flags (causal regime series)."""
    from .metrics import sharpe_ratio as _sr, max_drawdown as _mdd

    rows = []
    for col in regime_flags.columns:
        flag = regime_flags[col].reindex(net_returns.index)
        for level in sorted(flag.dropna().unique()):
            seg = net_returns[flag == level]
            rows.append({
                "regime": col, "level": level, "n": int(len(seg)),
                "sharpe": float(_sr(seg)), "max_dd": float(_mdd(seg)),
                "total_return": float((1 + seg.fillna(0)).prod() - 1),
            })
    rows.append({"regime": "all", "level": None, "n": int(len(net_returns)),
                 "sharpe": float(_sr(net_returns)), "max_dd": float(_mdd(net_returns)),
                 "total_return": float((1 + net_returns.fillna(0)).prod() - 1)})
    return pd.DataFrame(rows)

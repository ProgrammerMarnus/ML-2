"""Net/gross accounting invariant tests.

The registry record's ``net_metrics.full_oos_sharpe`` must equal the Sharpe
recomputed directly from the returned net OOS return series; the gross side
and costs must reconcile the same way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ResearchConfig
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.metrics import sharpe_ratio
from quant_research.features.information import build_information_features
from quant_research.features.price_volume import build_price_volume_features
from quant_research.run import generate_synthetic_events, run_research_pipeline
from quant_research.strategies.baseline import run_walk_forward, summarize_experiment


def _simple_cfg(placebo_runs=2, bootstrap_samples=50):
    return AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2016-01-01", end="2020-01-01"),
        evaluation=EvaluationConfig(train_window=200, validation_window=50,
                                    test_window=50, step_bars=100,
                                    purge_bars=2, embargo_bars=2, expanding=True),
        research=ResearchConfig(placebo_runs=placebo_runs,
                                bootstrap_samples=bootstrap_samples),
    )


def _simple_data(cfg):
    """Reconstruct the pipeline's exact inputs (price/volume + information features).

    In synthetic mode the pipeline joins information features built from
    ``generate_synthetic_events`` (see ``run_research_pipeline`` stage 3);
    the invariant test must use the identical feature matrix.
    """
    ohlcv = generate_synthetic_ohlcv(["SPY"], cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    price_feats = build_price_volume_features(close, volume, cfg.data.target)
    events = generate_synthetic_events(close.index, cfg.data.target)
    info_feats = build_information_features(close.index, events, cfg.data.target)
    feats = price_feats.join(info_feats, how="left")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    return feats, y, fwd


def test_sharpe_recomputed_from_return_series():
    cfg = _simple_cfg()
    feats, y, fwd = _simple_data(cfg)
    res = run_walk_forward(feats, y, fwd, cfg)
    s = summarize_experiment(res)
    assert s["full_oos_sharpe"] == pytest.approx(sharpe_ratio(res.oos_returns))
    assert s["full_oos_net_sharpe"] == pytest.approx(sharpe_ratio(res.oos_returns))
    assert s["full_oos_gross_sharpe"] == pytest.approx(sharpe_ratio(res.oos_gross_returns))


def test_net_never_exceeds_gross_and_costs_reconcile():
    cfg = _simple_cfg()
    feats, y, fwd = _simple_data(cfg)
    res = run_walk_forward(feats, y, fwd, cfg)
    s = summarize_experiment(res)
    assert (res.oos_returns <= res.oos_gross_returns + 1e-12).all()
    assert s["fee_cost"] > 0
    assert s["slippage_cost"] > 0
    # compounded drag equals the gross/net total-return gap
    assert s["cost_drag"] == pytest.approx(
        s["full_oos_gross_return"] - s["full_oos_net_return"])


def test_registry_record_accounting_invariant(tmp_path):
    cfg = _simple_cfg()
    report = run_research_pipeline(cfg, str(tmp_path))
    rec = report["experiment_record"]
    feats, y, fwd = _simple_data(cfg)
    res = run_walk_forward(feats, y, fwd, cfg)
    # the recorded net Sharpe must equal Sharpe(recomputed net OOS series)
    assert rec["net_metrics"]["full_oos_sharpe"] == pytest.approx(
        sharpe_ratio(res.oos_returns))
    assert rec["gross_metrics"]["full_oos_sharpe"] == pytest.approx(
        sharpe_ratio(res.oos_gross_returns))
    assert rec["net_metrics"]["fee_cost"] == pytest.approx(res.fee_costs)
    assert rec["net_metrics"]["slippage_cost"] == pytest.approx(res.slippage_costs)
    # gross and net are genuinely different (costs are real, not placeholders)
    assert rec["gross_metrics"]["full_oos_sharpe"] != pytest.approx(
        rec["net_metrics"]["full_oos_sharpe"])
    assert rec["net_metrics"]["cost_drag"] > 0

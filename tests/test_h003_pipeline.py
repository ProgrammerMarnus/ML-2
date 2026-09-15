"""Behavioral tests for the amended H-003-R1 portfolio path."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_research.config import (
    AppConfig,
    DataConfig,
    EvaluationConfig,
    FeatureConfig,
    ResearchConfig,
)
from quant_research.data.loaders import generate_synthetic_ohlcv
from quant_research.h003_pipeline import (
    H003_R1_ASSET_CLASSES,
    H003_R1_FEATURES,
    H003_R1_INVESTABLES,
    build_h003_features,
    build_h003_signal,
    h003_feature_leakage_report,
    run_h003_pipeline,
)
from quant_research.portfolio.h003_portfolio import (
    H003_R1_PORTFOLIO_PARAMS,
    construct_h003_portfolio,
    validate_h003_limits,
)
from quant_research.portfolio.h002_returns import portfolio_returns


def _price_panel(n: int = 900) -> pd.DataFrame:
    idx = pd.bdate_range("2010-01-04", periods=n, tz="UTC")
    rng = np.random.default_rng(31)
    returns = rng.normal(0.0002, 0.01, (n, len(H003_R1_INVESTABLES)))
    return pd.DataFrame(
        100.0 * np.exp(np.cumsum(returns, axis=0)),
        index=idx,
        columns=H003_R1_INVESTABLES,
    )


def test_h003_features_are_frozen_five_term_contract():
    features = build_h003_features(_price_panel())
    assert tuple(features) == H003_R1_FEATURES
    assert all(frame.shape[1] == 17 for frame in features.values())
    signal = build_h003_signal(features)
    assert signal.notna().sum().sum() > 0


def test_h003_features_do_not_change_when_only_future_changes():
    close = _price_panel()
    split = 650
    before = build_h003_signal(build_h003_features(close))
    changed = close.copy()
    changed.iloc[split:] *= np.linspace(1.0, 2.0, len(changed) - split)[:, None]
    after = build_h003_signal(build_h003_features(changed))
    pd.testing.assert_frame_equal(before.iloc[:split], after.iloc[:split])


def test_h003_portfolio_rebalances_only_on_wednesday_and_respects_limits():
    close = _price_panel(180)
    columns = list(close.columns)
    signal = pd.DataFrame(
        np.tile(np.linspace(-1.0, 1.0, len(columns)), (len(close), 1)),
        index=close.index,
        columns=columns,
    )
    vix = pd.Series(20.0, index=close.index)
    weights = construct_h003_portfolio(
        signal, close, H003_R1_ASSET_CLASSES, vix,
        **H003_R1_PORTFOLIO_PARAMS,
    )
    changes = weights.diff().abs().sum(axis=1)
    changed_days = changes.index[changes > 1e-12]
    assert len(changed_days) > 0
    assert set(changed_days.weekday) == {2}
    assert validate_h003_limits(weights, H003_R1_ASSET_CLASSES)["passed"]


def test_h003_vix_stand_down_flattens_target_book():
    close = _price_panel(180)
    signal = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    # Preserve cross-sectional directions so the book would otherwise trade.
    signal.iloc[:, ::2] = -1.0
    vix = pd.Series(20.0, index=close.index)
    wednesdays = close.index[close.index.weekday == 2]
    vix.loc[wednesdays[-1]] = 81.0
    weights = construct_h003_portfolio(
        signal, close, H003_R1_ASSET_CLASSES, vix,
        **H003_R1_PORTFOLIO_PARAMS,
    )
    assert weights.loc[wednesdays[-1]].abs().sum() == 0.0


def test_portfolio_return_cost_attribution_reconciles():
    close = _price_panel(90)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    weights.loc[:, "SPY"] = 0.25
    result = portfolio_returns(weights, close, fee_bps=5.0, slippage_bps=2.0)
    pd.testing.assert_series_equal(
        result["costs"], result["fee_costs"] + result["slippage_costs"],
        check_names=False,
    )
    assert np.isclose(result["slippage_costs"].sum() / result["fee_costs"].sum(), 2 / 5)


def test_h003_leakage_report_uses_multi_asset_signal():
    assets = list(H003_R1_INVESTABLES) + ["^VIX"]
    ohlcv = generate_synthetic_ohlcv(assets, "2010-01-01", "2014-01-01")
    report = h003_feature_leakage_report(ohlcv)
    assert report["passed"] is True
    assert report["max_abs_delta_history"] == 0.0


def test_h003_pipeline_builds_locked_multi_asset_oos_result(tmp_path):
    assets = list(H003_R1_INVESTABLES) + ["^VIX"]
    ohlcv = generate_synthetic_ohlcv(assets, "2008-01-01", "2016-01-01")
    cfg = AppConfig(
        data=DataConfig(
            mode="h003", assets=assets, target="SPY",
            start="2008-01-01", end="2016-01-01",
        ),
        evaluation=EvaluationConfig(
            train_window=252, validation_window=63, test_window=126,
            step_bars=126, purge_bars=5, embargo_bars=5,
        ),
        features=FeatureConfig(include_sources=["h003_r1_volatility_shock"]),
    )
    report = run_h003_pipeline(cfg, ohlcv, tmp_path, "synthetic-h003-test")
    assert report["baseline"].execution_contract == "h003_r1_multi_asset_portfolio"
    assert len(report["folds"]) >= 1
    assert report["h003_limit_report"]["passed"] is True
    assert (tmp_path / "test_lock.json").exists()
    assert report["feature_leakage_check"]["passed"] is True


def test_h003_full_runner_records_portfolio_native_evidence(tmp_path, monkeypatch):
    from quant_research import run as run_module

    assets = list(H003_R1_INVESTABLES) + ["^VIX"]
    ohlcv = generate_synthetic_ohlcv(assets, "2008-01-01", "2016-01-01")
    cfg = AppConfig(
        data=DataConfig(
            mode="h003", assets=assets, target="SPY",
            start="2008-01-01", end="2016-01-01",
            raw_snapshot_dir=str(tmp_path / "snapshots"),
        ),
        evaluation=EvaluationConfig(
            train_window=252, validation_window=63, test_window=126,
            step_bars=126, purge_bars=5, embargo_bars=5,
        ),
        features=FeatureConfig(include_sources=["h003_r1_volatility_shock"]),
        research=ResearchConfig(
            max_trials=10, bootstrap_samples=20, placebo_runs=3,
            threshold_candidates=[0.5], hold_candidates=[5],
        ),
    )
    monkeypatch.setattr(
        run_module, "load_market_data",
        lambda _cfg: (ohlcv, {"mode": "synthetic test fixture"}),
    )
    report = run_module.run_research_pipeline(cfg, str(tmp_path / "run"))
    record = report["experiment_record"]
    assert record["strategy"] == "h003_r1_volatility_shock_portfolio"
    assert record["promotion_state"] == "RESEARCH_ONLY"
    assert record["evidence_status"] == "REAL_DATA"  # determined by configured mode
    assert len(report["placebo_null"]) == 3
    assert len(record["additional_gate_checks"]) == 14
    assert (tmp_path / "run" / "experiment_registry.jsonl").exists()

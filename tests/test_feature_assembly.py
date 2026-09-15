"""Regression coverage for declared hypothesis feature selection."""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from quant_research.config import (
    AppConfig, DataConfig, EvaluationConfig, FeatureConfig, ModelConfig,
    ResearchConfig,
)
from quant_research.data.schemas import DataValidationError
from quant_research.features.assembly import (
    build_feature_panel, h001_selected_legs, planned_feature_names,
)
from quant_research.features.registry import registry


def _ohlc(close_panel, volume_panel):
    open_ = close_panel * 0.999
    high = close_panel * 1.01
    low = close_panel * 0.99
    return open_, high, low, volume_panel


def test_cross_asset_source_reaches_the_model_panel(close_panel, volume_panel):
    close = close_panel.copy()
    close["^VIX"] = 20.0 + (close["SPY"] / close["SPY"].iloc[0] - 1.0) * 4.0
    volume = volume_panel.copy()
    volume["^VIX"] = volume["SPY"]
    open_, high, low, volume = _ohlc(close, volume)
    features = build_feature_panel(
        close, volume, "SPY",
        FeatureConfig(include_sources=["cross_asset_spillover"]),
        open_=open_, high=high, low=low,
    )
    expected = {spec.feature_name for spec in registry()
                if spec.source == "cross_asset_spillover"}
    assert set(features.columns) == expected
    assert "ratio_zscore_lag1" in features
    assert "momentum_63" not in features


def test_liquidity_and_price_sources_are_merged_exactly_once(close_panel, volume_panel):
    open_, high, low, volume = _ohlc(close_panel, volume_panel)
    features = build_feature_panel(
        close_panel, volume, "SPY",
        FeatureConfig(include_sources=["liquidity_reversal", "price_volume"]),
        open_=open_, high=high, low=low,
    )
    sources = {"liquidity_reversal", "price_volume"}
    expected = {spec.feature_name for spec in registry()
                if spec.source in sources and spec.feature_name != "parkinson_vol_20_lag1"}
    assert set(features.columns) == expected
    assert not features.columns.duplicated().any()
    assert "liquidity_innovation" in features
    assert "momentum_63" in features


def test_cross_asset_source_requires_its_declared_inputs(close_panel, volume_panel):
    open_, high, low, volume = _ohlc(close_panel[["SPY"]], volume_panel[["SPY"]])
    with pytest.raises(DataValidationError, match="SPY and QQQ"):
        build_feature_panel(
            close_panel[["SPY"]], volume, "SPY",
            FeatureConfig(include_sources=["cross_asset_spillover"]),
            open_=open_, high=high, low=low,
        )


def test_cross_asset_source_requires_the_preregistered_vix_input(close_panel, volume_panel):
    open_, high, low, volume = _ohlc(close_panel, volume_panel)
    with pytest.raises(DataValidationError, match="VIX"):
        build_feature_panel(
            close_panel, volume, "SPY",
            FeatureConfig(include_sources=["cross_asset_spillover"]),
            open_=open_, high=high, low=low,
        )


def test_cross_asset_features_match_the_locked_ratio_formulas(close_panel, volume_panel):
    from quant_research.features.cross_asset_spillover import compute_spillover_features

    vix = pd.Series(20.0 + pd.RangeIndex(len(close_panel)) / 100.0, index=close_panel.index)
    features = compute_spillover_features(
        close_panel["SPY"], close_panel["QQQ"], volume_panel["SPY"],
        volume_panel["QQQ"], vix,
    )
    ratio = close_panel["QQQ"] / close_panel["SPY"]
    expected_zscore = (ratio - ratio.rolling(20).mean()) / ratio.rolling(20).std()
    pd.testing.assert_series_equal(features["ratio_price"], ratio, check_names=False)
    pd.testing.assert_series_equal(features["ratio_zscore"], expected_zscore, check_names=False)
    pd.testing.assert_series_equal(
        features["ratio_zscore_lag3"], expected_zscore.shift(3), check_names=False,
    )


def test_volatility_contract_omits_unavailable_implied_vol_columns(close_panel, volume_panel):
    open_, high, low, volume = _ohlc(close_panel, volume_panel)
    config = FeatureConfig(include_sources=["volatility_risk_premium"])
    features = build_feature_panel(
        close_panel, volume, "SPY", config, open_=open_, high=high, low=low,
    )
    planned = planned_feature_names(config, events_available=False, assets=["SPY", "QQQ"])
    assert sorted(features.columns) == planned
    assert "vrp_vix" not in features


def test_h001_walk_forward_retains_executed_asset_legs(close_panel, volume_panel):
    from quant_research.strategies.baseline import run_walk_forward

    close = close_panel.copy()
    close["^VIX"] = 20.0 + pd.RangeIndex(len(close)) / 100.0
    volume = volume_panel.copy()
    volume["^VIX"] = volume["SPY"]
    open_, high, low, volume = _ohlc(close, volume)
    features = build_feature_panel(
        close, volume, "SPY", FeatureConfig(include_sources=["cross_asset_spillover"]),
        open_=open_, high=high, low=low,
    )
    asset_fwd = pd.DataFrame({
        "SPY": close["SPY"].shift(-1) / close["SPY"] - 1.0,
        "QQQ": close["QQQ"].shift(-1) / close["QQQ"] - 1.0,
    })
    selected = pd.Series(
        np.where(features["ratio_zscore"] > 0.0, "SPY", "QQQ"), index=features.index,
    ).where(features["ratio_zscore"].notna())
    fwd = pd.Series(np.nan, index=features.index)
    for symbol in ("SPY", "QQQ"):
        fwd.loc[selected.eq(symbol)] = asset_fwd.loc[selected.eq(symbol), symbol]
    y = (fwd > 0).astype(float).where(fwd.notna())
    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY", "QQQ", "^VIX"], target="SPY"),
        evaluation=EvaluationConfig(train_window=160, validation_window=60,
                                    test_window=60, step_bars=60),
        model=ModelConfig(type="logistic", logreg_C=1.0, hold_bars=3),
        features=FeatureConfig(include_sources=["cross_asset_spillover"]),
        research=ResearchConfig(threshold_candidates=[0.5], placebo_runs=1,
                                bootstrap_samples=10),
    )
    result = run_walk_forward(
        features, y, fwd, cfg, asset_forward_returns=asset_fwd,
        selected_asset=selected,
    )
    assert result.oos_legs is not None
    assert result.oos_turnover is not None
    assert set(result.oos_legs.dropna()).issubset({"SPY", "QQQ"})
    assert result.oos_turnover.index.equals(result.oos_returns.index)


def test_h001_feature_placebo_recomputes_the_conditional_leg():
    """A feature permutation must invalidate H-001's ratio-selected leg too."""
    idx = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    features = pd.DataFrame({"ratio_zscore": [-1.0, -0.5, 0.5, 1.0]}, index=idx)
    permuted = features.iloc[[2, 3, 0, 1]].copy()
    permuted.index = idx
    assert h001_selected_legs(features).tolist() == ["QQQ", "QQQ", "SPY", "SPY"]
    assert h001_selected_legs(permuted).tolist() == ["SPY", "SPY", "QQQ", "QQQ"]


@pytest.mark.parametrize(
    ("source", "required_contract"),
    [
        ("liquidity_reversal", "Russell 3000"),
        ("volatility_risk_premium", "VIX-futures M1-M3"),
    ],
)
def test_preregistered_h002_h003_cannot_run_as_scalar_ohlcv_proxies(
    source, required_contract,
):
    from quant_research.run import run_research_pipeline

    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY"),
        features=FeatureConfig(include_sources=[source]),
    )
    with pytest.raises(DataValidationError, match=required_contract):
        run_research_pipeline(cfg)
def test_overnight_intraday_source_reaches_the_model_panel(close_panel, volume_panel):
    """H-005's registered overnight/intraday decomposition must be buildable."""
    close = close_panel.copy()
    close["VIX"] = 20.0 + pd.RangeIndex(len(close)) / 100.0
    volume = volume_panel.copy()
    volume["VIX"] = volume["SPY"]
    open_, high, low, volume = _ohlc(close, volume)
    config = FeatureConfig(include_sources=["overnight_intraday"])
    features = build_feature_panel(
        close, volume, "SPY", config, open_=open_, high=high, low=low,
    )
    planned = planned_feature_names(config, events_available=False, assets=["SPY", "VIX"])
    assert sorted(features.columns) == planned
    assert "overnight_ret_20d_lag1" in features
    assert "intraday_ret_5d_lag1" in features
    assert "vix_regime" in features
    assert features["overnight_ret_1d"].notna().any()
    assert features["intraday_ret_1d"].notna().any()


def test_overnight_contract_omits_the_regime_column_without_vix(close_panel, volume_panel):
    """Without a VIX series the regime feature is absent from plan and panel."""
    open_, high, low, volume = _ohlc(close_panel, volume_panel)
    config = FeatureConfig(include_sources=["overnight_intraday"])
    features = build_feature_panel(
        close_panel, volume, "SPY", config, open_=open_, high=high, low=low,
    )
    planned = planned_feature_names(config, events_available=False, assets=["SPY"])
    assert sorted(features.columns) == planned
    assert "vix_regime" not in features
    assert "overnight_vol_ratio" in features


def test_overnight_source_accepts_the_real_data_vix_symbol(close_panel, volume_panel):
    """The preregistered regime feature must survive the provider's ``^VIX`` name.

    Real yfinance panels carry the index as ``^VIX``; a config declaring that
    symbol previously dropped ``vix_regime`` from both the plan and the panel,
    silently running a 12-feature contract against a 13-feature preregistration.
    """
    close = close_panel.copy()
    close["^VIX"] = 20.0 + pd.RangeIndex(len(close)) / 100.0
    volume = volume_panel.copy()
    volume["^VIX"] = volume["SPY"]
    open_, high, low, volume = _ohlc(close, volume)
    config = FeatureConfig(include_sources=["overnight_intraday"])
    features = build_feature_panel(
        close, volume, "SPY", config, open_=open_, high=high, low=low,
    )
    planned = planned_feature_names(config, events_available=False, assets=["SPY", "^VIX"])
    assert sorted(features.columns) == planned
    assert "vix_regime" in features
    assert features["vix_regime"].notna().any()
    assert features["overnight_ret_1d"].notna().any()


def test_overnight_vix_indicator_must_be_unambiguous(close_panel, volume_panel):
    """Two VIX columns would let a run use a different series than it declared."""
    close = close_panel.copy()
    close["VIX"] = 20.0
    close["^VIX"] = 21.0
    volume = volume_panel.copy()
    volume["VIX"] = volume["SPY"]
    volume["^VIX"] = volume["SPY"]
    open_, high, low, volume = _ohlc(close, volume)
    with pytest.raises(DataValidationError, match="ambiguous"):
        build_feature_panel(
            close, volume, "SPY",
            FeatureConfig(include_sources=["overnight_intraday"]),
            open_=open_, high=high, low=low,
        )

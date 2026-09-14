"""Configuration layer tests."""

from __future__ import annotations

import pytest

from quant_research.config import (
    AppConfig,
    ConfigError,
    DataConfig,
    EvaluationConfig,
    FeatureConfig,
    load_config,
)


def test_default_config_is_deterministic():
    c1, c2 = AppConfig(), AppConfig()
    assert c1.fingerprint() == c2.fingerprint()
    assert c1.fingerprint() != AppConfig(
        evaluation=EvaluationConfig(train_window=1000)
    ).fingerprint()


def test_config_yaml_roundtrip(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(
        """
data:
  mode: synthetic
  assets: [SPY]
  target: SPY
evaluation:
  train_window: 300
execution:
  fee_bps: 7.5
features:
  include_sources: [liquidity_reversal, price_volume]
  exclude_features: [trend_50]
"""
    )
    cfg = load_config(str(p))
    assert cfg.evaluation.train_window == 300
    assert cfg.execution.fee_bps == 7.5
    assert cfg.model.random_seed == 42
    assert cfg.features.include_sources == ["liquidity_reversal", "price_volume"]
    assert cfg.features.exclude_features == ["trend_50"]


def test_invalid_data_mode_rejected():
    with pytest.raises(ConfigError):
        DataConfig(mode="excel", assets=["SPY"], target="SPY")


def test_target_must_be_in_assets():
    with pytest.raises(ConfigError):
        DataConfig(mode="synthetic", assets=["SPY"], target="QQQ")


def test_csv_mode_requires_path():
    with pytest.raises(ConfigError):
        DataConfig(mode="csv", assets=["SPY"], target="SPY")


def test_negative_fees_rejected():
    with pytest.raises(ConfigError):
        AppConfig(execution=__import__(
            "quant_research.config", fromlist=["ExecutionConfig"]
        ).ExecutionConfig(fee_bps=-1))


def test_short_windows_rejected():
    with pytest.raises(ConfigError):
        EvaluationConfig(train_window=0)


def test_to_dict_roundtrip():
    cfg = AppConfig()
    again = AppConfig.from_dict(cfg.to_dict())
    assert again.fingerprint() == cfg.fingerprint()


def test_feature_source_duplicates_are_rejected():
    with pytest.raises(ConfigError, match="duplicates"):
        FeatureConfig(include_sources=["price_volume", "price_volume"])

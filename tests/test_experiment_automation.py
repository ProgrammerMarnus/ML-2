"""Tests for bounded protocol-first experiment automation."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, FeatureConfig, ResearchConfig
from quant_research.data.schemas import DataValidationError
from quant_research.experiments.automation import create_experiment_plan
from quant_research.experiments.overnight import (catalogue_size,
                                                   _score_on_validation,
                                                   prepare_overnight_campaign,
                                                   strategy_template_for)
from quant_research.experiments.operations import campaign_status, preflight_campaign
from quant_research.evaluation.walk_forward import FoldSpec
from quant_research.experiments.protocol import ResearchProtocol


def _config() -> AppConfig:
    return AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY"),
        research=ResearchConfig(placebo_runs=1, bootstrap_samples=10),
    )


def test_automation_creates_bound_protocols_and_configs(tmp_path):
    created = create_experiment_plan(_config(), tmp_path, max_experiments=1)
    assert len(created) == 1
    item = created[0]
    assert item.protocol_path.exists()
    assert item.config_path.exists()
    protocol = ResearchProtocol.load(item.protocol_path)
    assert protocol.config_fingerprint == item.config.fingerprint()
    assert protocol.hypothesis_id == item.strategy_id
    plan = json.loads((tmp_path / "experiment_plan.json").read_text())
    assert plan["experiments"][0]["strategy_id"] == item.strategy_id


def test_automation_refuses_to_overwrite_a_plan(tmp_path):
    create_experiment_plan(_config(), tmp_path, max_experiments=1)
    with pytest.raises(DataValidationError, match="already exists"):
        create_experiment_plan(_config(), tmp_path, max_experiments=1)


def test_automation_protocol_uses_the_configured_feature_sources(tmp_path):
    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY", "QQQ", "^VIX"], target="SPY"),
        features=FeatureConfig(include_sources=["cross_asset_spillover"]),
        research=ResearchConfig(placebo_runs=1, bootstrap_samples=10),
    )
    item = create_experiment_plan(cfg, tmp_path, max_experiments=1)[0]
    protocol = ResearchProtocol.load(item.protocol_path)
    assert protocol.feature_names == [
        "qqq_volume_zscore", "ratio_ma20", "ratio_price", "ratio_std20",
        "ratio_zscore", "ratio_zscore_lag1", "ratio_zscore_lag3",
        "spy_volume_zscore", "vol_regime",
    ]


def test_overnight_campaign_refuses_synthetic_data_without_opt_in(tmp_path):
    with pytest.raises(DataValidationError, match="require real data"):
        prepare_overnight_campaign(_config(), tmp_path)


def test_overnight_campaign_creates_the_next_catalog_candidate(tmp_path):
    campaign_dir, created = prepare_overnight_campaign(
        _config(), tmp_path, allow_synthetic=True,
    )
    assert campaign_dir.name.startswith("campaign_")
    assert len(created) == 1
    assert created[0].strategy_id == strategy_template_for(0).strategy_id
    assert (campaign_dir / "candidate_000_logistic_c0.05_hold1_v000" / "experiment_plan.json").exists()


def test_overnight_catalogue_continues_beyond_the_initial_six():
    assert catalogue_size() == 1960
    assert strategy_template_for(6).strategy_id != strategy_template_for(0).strategy_id
    assert strategy_template_for(catalogue_size() - 1).strategy_id.startswith("boost_extended_")


def test_development_scoring_never_reads_the_reserved_test_window():
    """A missing test slice must not affect a validation-only candidate score."""
    index = pd.date_range("2020-01-01", periods=14, freq="D", tz="UTC")
    test_index = pd.date_range("2030-01-01", periods=4, freq="D", tz="UTC")
    features = pd.DataFrame({"signal": np.linspace(-1.0, 1.0, len(index))}, index=index)
    context = {
        "features": features,
        "y": pd.Series(([0, 1] * 7), index=index, dtype=float),
        "fwd": pd.Series(np.linspace(-0.01, 0.01, len(index)), index=index),
        "risk_returns": pd.Series(np.linspace(-0.01, 0.01, len(index)), index=index),
        "execution": _config().execution,
        "threshold_candidates": [0.5],
        "development_folds": [FoldSpec(
            fold_id=1,
            train_idx=index[:8],
            val_idx=index[8:14],
            test_idx=test_index,
            purge_bars=0,
            embargo_bars=0,
        )],
    }
    result = _score_on_validation(strategy_template_for(0), context)
    assert result["validation_observations"] == 6


def test_preflight_neither_runs_data_nor_consumes_a_confirmation_window(tmp_path):
    report = preflight_campaign(_config(), tmp_path / "out", max_hours=6,
                                allow_synthetic=True)
    assert report["ready"]
    assert report["catalogue_size"] == catalogue_size()
    assert "No market-data download was attempted." in report["guarantees"]


def test_campaign_status_reads_completed_artifacts_without_changing_them(tmp_path):
    campaign = tmp_path / "out" / "campaign_20260101T000000Z"
    campaign.mkdir(parents=True)
    (campaign / "campaign_summary.json").write_text(json.dumps({
        "n_candidates_scored_on_validation": 12,
        "confirmation": {"strategy_id": "candidate", "promotion_state": "RESEARCH_ONLY"},
    }))
    report = campaign_status(tmp_path / "out")
    assert report["state"] == "completed"
    assert report["selected_strategy"] == "candidate"
    assert report["candidates_scored_on_validation"] == 12

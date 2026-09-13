from __future__ import annotations

import pytest

from quant_research.data.schemas import DataValidationError
from quant_research.experiments.protocol import ResearchProtocol


def test_protocol_is_immutable_and_binds_the_run_contract(tmp_path):
    protocol = ResearchProtocol.create(
        hypothesis_id="market-state-v1",
        economic_mechanism="Price/volume state changes persist into the next session.",
        feature_names=["momentum_63", "realized_vol_20"],
        target="SPY",
        primary_metric="mean_oos_sharpe",
        development_data="US ETFs through 2017-12-31",
        evaluation_data="US ETFs from 2018-01-01 onward",
        max_trials=12,
        config_fingerprint="abc123",
    )
    path = protocol.freeze(tmp_path / "market-state-v1.json")

    loaded = ResearchProtocol.load(path)
    assert loaded == protocol
    loaded.assert_matches_config("abc123", 12)
    with pytest.raises(DataValidationError, match="immutable"):
        protocol.freeze(path)
    with pytest.raises(DataValidationError, match="exceeds"):
        loaded.assert_matches_config("abc123", 13)


def test_protocol_rejects_overlapping_data_descriptions():
    with pytest.raises(DataValidationError, match="must differ"):
        ResearchProtocol.create(
            hypothesis_id="bad",
            economic_mechanism="test",
            feature_names=["x"],
            target="SPY",
            primary_metric="sharpe",
            development_data="same data",
            evaluation_data="same data",
            max_trials=1,
            config_fingerprint="abc",
        )

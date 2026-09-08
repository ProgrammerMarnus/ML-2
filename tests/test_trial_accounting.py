"""Trial-counter audit tests.

- each validation candidate increments the correct counter
- placebo runs do not accidentally alter the research trial count
- robustness tests do not alter the research trial count (no new validation candidates)
- rerunning the same experiment creates a new experiment ID without resetting the
  high-water mark
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant_research.config import AppConfig, DataConfig, EvaluationConfig, ResearchConfig
from quant_research.data.loaders import generate_synthetic_ohlcv, to_panels
from quant_research.evaluation.robustness import replay_oos
from quant_research.evaluation.walk_forward import LockedTestProtocol
from quant_research.experiments.registry import TrialCounter
from quant_research.features.price_volume import build_price_volume_features
from quant_research.strategies.baseline import run_walk_forward


@pytest.fixture(scope="module")
def setup():
    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2016-01-01", end="2020-01-01"),
        evaluation=EvaluationConfig(train_window=200, validation_window=50,
                                    test_window=50, step_bars=100,
                                    purge_bars=2, embargo_bars=2, expanding=True),
    )
    ohlcv = generate_synthetic_ohlcv(["SPY"], cfg.data.start, cfg.data.end, seed=42)
    close, volume = to_panels(ohlcv)
    feats = build_price_volume_features(close, volume, "SPY")
    y = (close["SPY"].shift(-1) > close["SPY"]).astype(float)
    y[close["SPY"].shift(-1).isna()] = np.nan
    fwd = close["SPY"].shift(-1) / close["SPY"] - 1.0
    return cfg, feats, y, fwd


def test_validation_candidates_increment_correct_counter(setup, tmp_path):
    cfg, feats, y, fwd = setup
    counter = TrialCounter(tmp_path / "trials.json")
    res = run_walk_forward(feats, y, fwd, cfg, trial_counter=counter)
    expected = len(res.folds) * len(cfg.research.threshold_candidates)
    assert counter.count == expected


def test_rerun_same_experiment_new_id_without_resetting_highwater(tmp_path):
    from quant_research.run import run_research_pipeline

    cfg = AppConfig(
        data=DataConfig(mode="synthetic", assets=["SPY"], target="SPY",
                        start="2020-01-01", end="2022-01-01"),
        evaluation=EvaluationConfig(train_window=120, validation_window=40,
                                    test_window=40, step_bars=40,
                                    purge_bars=2, embargo_bars=2, expanding=True),
        research=ResearchConfig(placebo_runs=1, bootstrap_samples=20),
    )
    r1 = run_research_pipeline(cfg, str(tmp_path))
    c1 = json.loads((tmp_path / "trial_counter.json").read_text())["count"]
    hw1 = json.loads((tmp_path / "trial_counter.json.highwater").read_text())["count"]
    r2 = run_research_pipeline(cfg, str(tmp_path))
    c2 = json.loads((tmp_path / "trial_counter.json").read_text())["count"]
    hw2 = json.loads((tmp_path / "trial_counter.json.highwater").read_text())["count"]
    assert r1["experiment_record"]["experiment_id"] != r2["experiment_record"]["experiment_id"]
    assert c2 > c1  # second run funds a fresh walk-forward seek...
    assert hw2 >= hw1  # high-water mark is monotonic, never reset


def test_robustness_replay_does_not_increment(setup, tmp_path):
    cfg, feats, y, fwd = setup
    lt = LockedTestProtocol()
    base = run_walk_forward(feats, y, fwd, cfg, locked_test=lt)
    counter = TrialCounter(tmp_path / "trials.json")
    counter.increment(100)
    before = counter.count
    replay_oos(feats, y, fwd, cfg, base, lt, exec_cfg=cfg.execution,
               trial_counter=counter)
    assert counter.count == before


def test_lowering_counter_fails(tmp_path):
    p = tmp_path / "trials.json"
    counter = TrialCounter(p)
    counter.increment(10)
    p.write_text(json.dumps({"count": 0}))  # manual tamper
    from quant_research.data.schemas import DataValidationError

    with pytest.raises(DataValidationError, match="never be reset"):
        TrialCounter(p)

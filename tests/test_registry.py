"""Registry, trial accounting, and leaderboard tests."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from quant_research.data.schemas import DataValidationError
from quant_research.experiments.leaderboard import _search_class, build_leaderboard
from quant_research.experiments.registry import ExperimentRegistry, TrialCounter
from helpers import valid_record


def test_record_appends_and_assigns_ids(tmp_path):
    reg = ExperimentRegistry(tmp_path / "reg.jsonl")
    r1 = reg.record(valid_record())
    r2 = reg.record(valid_record())
    assert r1["experiment_id"] != r2["experiment_id"]
    assert len(reg.read_all()) == 2


def test_records_are_immutable_never_overwritten(tmp_path):
    reg = ExperimentRegistry(tmp_path / "reg.jsonl")
    r1 = reg.record(valid_record())
    before = (tmp_path / "reg.jsonl").read_text()
    reg.record(valid_record())  # new record appended; r1 untouched
    after = (tmp_path / "reg.jsonl").read_text()
    assert after.startswith(before)
    assert json.loads(after.splitlines()[0]) == r1


def test_missing_required_fields_rejected(tmp_path):
    reg = ExperimentRegistry(tmp_path / "reg.jsonl")
    with pytest.raises(DataValidationError, match="missing fields"):
        reg.record({"strategy": "incomplete"})


def test_trial_counter_monotonic_and_persistent(tmp_path):
    p = tmp_path / "trials.json"
    c1 = TrialCounter(p)
    assert c1.count == 0
    c1.increment(5)
    c1.increment(3)
    assert c1.count == 8
    c2 = TrialCounter(p)  # reload from disk
    assert c2.count == 8


def test_trial_counter_refuses_reset(tmp_path):
    p = tmp_path / "trials.json"
    c1 = TrialCounter(p)
    c1.increment(10)
    p.write_text(json.dumps({"count": 0}))  # simulate accidental reset
    with pytest.raises(DataValidationError, match="never be reset"):
        TrialCounter(p)


def test_trial_counter_refuses_negative_increment(tmp_path):
    c = TrialCounter(tmp_path / "trials.json")
    c.increment(5)
    with pytest.raises(DataValidationError, match="only increase"):
        c.increment(-3)


def test_leaderboard_answers_standard_questions(tmp_path):
    reg = ExperimentRegistry(tmp_path / "reg.jsonl")
    reg.record(valid_record())
    lb = build_leaderboard(reg)
    assert len(lb) == 1
    row = lb.iloc[0]
    assert row["strategy"] == "test_strategy"
    assert row["trials"] == 3
    assert row["search_class"] == "bounded_small_search"
    assert row["dataset_version"] == "abc123"
    assert row["mean_oos_sharpe"] == 0.4
    assert row["bootstrap_lo"] == -0.2
    assert row["promotion_state"] == "RESEARCH_ONLY"


def test_search_classification():
    assert _search_class(1) == "one_shot_hypothesis_test"
    assert _search_class(20) == "bounded_small_search"
    assert _search_class(500) == "large_scale_search"

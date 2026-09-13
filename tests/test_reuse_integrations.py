from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_research.data.schemas import DataValidationError
from quant_research.data.calendar import library_version
from quant_research.data.validation import expected_sessions
from quant_research.features.finbert import FinBERTSpec, scores_from_logits
from quant_research.portfolio.skfolio_adapter import SkfolioSpec, optimize_training_weights


def test_exchange_calendar_recognizes_juneteenth_and_early_close_session():
    sessions = expected_sessions(
        pd.Timestamp("2024-06-17", tz="UTC"),
        pd.Timestamp("2024-06-21", tz="UTC"),
    )
    days = {stamp.date().isoformat() for stamp in sessions}
    assert days == {"2024-06-17", "2024-06-18", "2024-06-20", "2024-06-21"}
    assert library_version() != "unknown"


def test_finbert_scores_use_model_label_identity_not_class_position():
    scores = scores_from_logits(
        np.array([[0.0, 4.0, -1.0]]),
        {0: "neutral", 1: "positive", 2: "negative"},
    )
    assert scores[0]["sentiment"] > 0
    assert scores[0]["confidence"] > 0.9


def test_finbert_requires_immutable_model_revision():
    with pytest.raises(DataValidationError, match="commit SHA"):
        FinBERTSpec(revision="main")


def test_skfolio_rejects_infeasible_constraints_before_dependency_load():
    rets = pd.DataFrame({"a": [0.01, 0.02, -0.01], "b": [0.0, 0.01, -0.02]})
    with pytest.raises(DataValidationError, match="cannot satisfy"):
        optimize_training_weights(rets, SkfolioSpec(max_weight=0.4))

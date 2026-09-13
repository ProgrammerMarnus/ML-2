"""Reproducible FinBERT scoring for point-in-time news events.

This module never downloads or consumes a headline feed itself.  A caller must
first provide a validated event frame with authoritative publication and
availability timestamps.  That keeps a model's semantic score separate from
the much harder question of when a datum became tradable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from ..data.schemas import DataValidationError
from .point_in_time import validate_events


_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class FinBERTSpec:
    """An immutable model identity; tags such as ``main`` are forbidden."""

    model_id: str = "ProsusAI/finbert"
    revision: str = ""
    text_column: str = "raw_value"
    batch_size: int = 16

    def __post_init__(self) -> None:
        if not self.model_id or not self.model_id.strip():
            raise DataValidationError("FinBERT model_id must be non-empty")
        if not _COMMIT.fullmatch(self.revision):
            raise DataValidationError(
                "FinBERT revision must be a 40-character immutable Hugging Face commit SHA; "
                "branches and tags are not reproducible"
            )
        if not self.text_column or not self.text_column.strip():
            raise DataValidationError("FinBERT text_column must be non-empty")
        if not isinstance(self.batch_size, int) or isinstance(self.batch_size, bool) or self.batch_size < 1:
            raise DataValidationError("FinBERT batch_size must be a positive integer")


def text_sha256(value: object) -> str:
    """Stable digest retained in event provenance without duplicating text."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def scores_from_logits(logits: np.ndarray, id2label: Mapping[object, str]) -> list[dict]:
    """Convert classifier logits to FinBERT-compatible PIT feature values.

    Label names are read from the pinned model config instead of assuming a
    class order.  A model lacking positive/negative labels is rejected rather
    than silently producing an inverted sentiment feature.
    """
    arr = np.asarray(logits, dtype=float)
    if arr.ndim != 2 or arr.shape[0] == 0 or not np.isfinite(arr).all():
        raise DataValidationError("FinBERT logits must be a non-empty finite 2-D array")
    labels = {int(k): str(v).lower() for k, v in id2label.items()}
    if set(range(arr.shape[1])) - set(labels):
        raise DataValidationError("FinBERT model config lacks labels for one or more output classes")
    positive = [i for i, label in labels.items() if "positive" in label]
    negative = [i for i, label in labels.items() if "negative" in label]
    if len(positive) != 1 or len(negative) != 1:
        raise DataValidationError("FinBERT model must expose exactly one positive and one negative label")
    shifted = arr - arr.max(axis=1, keepdims=True)
    probs = np.exp(shifted)
    probs /= probs.sum(axis=1, keepdims=True)
    result = []
    for row in probs:
        by_label = {labels[i]: float(row[i]) for i in range(arr.shape[1])}
        result.append({
            "sentiment": float(row[positive[0]] - row[negative[0]]),
            "confidence": float(row.max()),
            "label_probabilities": by_label,
        })
    return result


def score_events(events: pd.DataFrame, spec: FinBERTSpec) -> pd.DataFrame:
    """Score event text locally and return a validated, provenance-rich frame.

    ``availability_time`` is deliberately preserved; inference time must never
    make historical information available earlier.  The model is loaded with
    ``local_files_only=True`` so a research run cannot silently pull a moving
    revision from the network.  Fetch the exact revision into a controlled
    cache before running this function.
    """
    validated = validate_events(events)
    if spec.text_column not in validated.columns:
        raise DataValidationError(f"FinBERT text column {spec.text_column!r} is missing")
    text = validated[spec.text_column]
    if text.isna().any() or (text.astype(str).str.strip() == "").any():
        raise DataValidationError("FinBERT input contains missing or empty text")
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise DataValidationError(
            "FinBERT support requires the [nlp] extra (transformers and torch)"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(
        spec.model_id, revision=spec.revision, local_files_only=True
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        spec.model_id, revision=spec.revision, local_files_only=True
    )
    model.eval()
    logits = []
    values = text.astype(str).tolist()
    with torch.no_grad():
        for start in range(0, len(values), spec.batch_size):
            encoded = tokenizer(
                values[start:start + spec.batch_size], padding=True, truncation=True,
                max_length=512, return_tensors="pt",
            )
            logits.append(model(**encoded).logits.detach().cpu().numpy())
    scores = scores_from_logits(np.vstack(logits), model.config.id2label)

    out = validated.copy()
    out["sentiment"] = [score["sentiment"] for score in scores]
    out["confidence"] = [score["confidence"] for score in scores]
    out["finbert_model_id"] = spec.model_id
    out["finbert_revision"] = spec.revision
    out["raw_text_sha256"] = [text_sha256(value) for value in values]
    out["processed_value"] = [
        json.dumps({
            "model_id": spec.model_id,
            "revision": spec.revision,
            "text_sha256": digest,
            "label_probabilities": score["label_probabilities"],
        }, sort_keys=True, separators=(",", ":"))
        for digest, score in zip(out["raw_text_sha256"], scores, strict=True)
    ]
    return validate_events(out)

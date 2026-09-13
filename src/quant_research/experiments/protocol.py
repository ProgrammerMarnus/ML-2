"""Immutable preregistration records for future research hypotheses.

The protocol is intentionally separate from a run configuration.  A strategy
can be configured many ways; a protocol records why the experiment is being
run and the data/evaluation boundary agreed before results are inspected.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..data.schemas import DataValidationError


@dataclass(frozen=True)
class ResearchProtocol:
    """A frozen, content-addressed hypothesis and evaluation contract."""

    hypothesis_id: str
    economic_mechanism: str
    feature_names: List[str]
    target: str
    primary_metric: str
    development_data: str
    evaluation_data: str
    max_trials: int
    config_fingerprint: str
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        hypothesis_id: str,
        economic_mechanism: str,
        feature_names: List[str],
        target: str,
        primary_metric: str,
        development_data: str,
        evaluation_data: str,
        max_trials: int,
        config_fingerprint: str,
    ) -> "ResearchProtocol":
        return cls(
            hypothesis_id=hypothesis_id,
            economic_mechanism=economic_mechanism,
            feature_names=list(feature_names),
            target=target,
            primary_metric=primary_metric,
            development_data=development_data,
            evaluation_data=evaluation_data,
            max_trials=max_trials,
            config_fingerprint=config_fingerprint,
            created_at=datetime.now(timezone.utc).isoformat(),
        ).validated()

    def validated(self) -> "ResearchProtocol":
        required = {
            "hypothesis_id": self.hypothesis_id,
            "economic_mechanism": self.economic_mechanism,
            "target": self.target,
            "primary_metric": self.primary_metric,
            "development_data": self.development_data,
            "evaluation_data": self.evaluation_data,
            "config_fingerprint": self.config_fingerprint,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise DataValidationError(f"research protocol missing required fields: {missing}")
        if not self.feature_names:
            raise DataValidationError("research protocol must declare at least one feature")
        if self.max_trials < 1:
            raise DataValidationError("research protocol max_trials must be positive")
        if self.development_data == self.evaluation_data:
            raise DataValidationError(
                "research protocol development_data and evaluation_data must differ"
            )
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def freeze(self, path: str | Path) -> Path:
        """Write once; refuses an overwrite, including an identical protocol."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise DataValidationError(
                f"research protocol already exists at {target}; protocols are immutable"
            )
        document = {"protocol_digest": self.digest, **self.to_dict()}
        target.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "ResearchProtocol":
        source = Path(path)
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataValidationError(f"cannot read research protocol {source}: {exc}") from exc
        expected = document.pop("protocol_digest", None)
        protocol = cls(**document).validated()
        if expected != protocol.digest:
            raise DataValidationError(f"research protocol digest mismatch: {source}")
        return protocol

    def assert_matches_config(self, config_fingerprint: str, max_trials: int) -> None:
        if self.config_fingerprint != config_fingerprint:
            raise DataValidationError(
                "research protocol config fingerprint does not match the run configuration"
            )
        if max_trials > self.max_trials:
            raise DataValidationError(
                f"run max_trials {max_trials} exceeds protocol limit {self.max_trials}"
            )

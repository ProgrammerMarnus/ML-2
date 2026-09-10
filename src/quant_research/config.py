"""Typed configuration layer.

Single source of truth for every research run.  The full configuration is
hashable (canonical JSON -> sha256) and becomes part of every experiment
fingerprint.  No secrets belong in this file or in YAML configs; credentials
are read from environment variables only.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class ConfigError(ValueError):
    """Raised for invalid or inconsistent configuration."""


@dataclass(frozen=True)
class DataConfig:
    mode: str = "synthetic"  # synthetic | csv | yfinance
    assets: List[str] = field(default_factory=lambda: ["SPY"])
    target: str = "SPY"
    start: str = "2012-01-01"
    end: str = "2026-01-01"
    frequency: str = "1d"
    csv_path: Optional[str] = None
    raw_snapshot_dir: str = "data/raw_snapshots"

    def __post_init__(self) -> None:
        if self.mode not in {"synthetic", "csv", "yfinance"}:
            raise ConfigError(f"data.mode must be synthetic|csv|yfinance, got {self.mode!r}")
        if self.mode == "csv" and not self.csv_path:
            raise ConfigError("data.csv_path is required when data.mode='csv'")
        if self.target not in self.assets:
            raise ConfigError(f"target {self.target!r} must be in assets")
        if self.frequency != "1d":
            raise ConfigError("only frequency '1d' is supported (documented limitation)")


@dataclass(frozen=True)
class EvaluationConfig:
    train_window: int = 1260
    validation_window: int = 252
    test_window: int = 252
    step_bars: int = 252
    purge_bars: int = 5
    embargo_bars: int = 5
    expanding: bool = True

    def __post_init__(self) -> None:
        if min(self.train_window, self.validation_window, self.test_window) <= 0:
            raise ConfigError("train/validation/test windows must be positive")
        if self.step_bars <= 0:
            raise ConfigError("step_bars must be positive")
        if self.purge_bars < 0 or self.embargo_bars < 0:
            raise ConfigError("purge/embargo bars cannot be negative")
        # B09: Reject gapped OOS windows (step_bars > test_window) until explicit
        # gap policy is implemented. Gapped windows cause position state to carry
        # across unscored returns, silently omitting returns or requiring explicit
        # liquidation/re-entry costs that are not currently modeled.
        if self.step_bars > self.test_window:
            raise ConfigError(
                f"step_bars ({self.step_bars}) > test_window ({self.test_window}) "
                f"creates gapped OOS windows; gap policy is not implemented. "
                f"Use step_bars <= test_window for continuous coverage or "
                f"step_bars == test_window for non-overlapping windows."
            )


@dataclass(frozen=True)
class ExecutionConfig:
    fee_bps: float = 5.0
    slippage_bps: float = 1.0
    signal_delay_bars: int = 0
    target_vol: float = 0.10
    max_position: float = 1.0

    def __post_init__(self) -> None:
        import math
        # Phase 4: strict finite-value + integer-type validation. Fail fast
        # before expensive research on NaN/inf costs, non-integral delays,
        # or degenerate volatility targets.
        for _name in ("fee_bps", "slippage_bps", "target_vol", "max_position"):
            _v = getattr(self, _name)
            if isinstance(_v, bool) or not isinstance(_v, (int, float)):
                raise ConfigError(f"execution.{_name} must be a real number, got {_v!r}")
            if not math.isfinite(float(_v)):
                raise ConfigError(f"execution.{_name} must be finite, got {_v!r}")
        if isinstance(self.signal_delay_bars, bool) or not isinstance(
            self.signal_delay_bars, int
        ):
            raise ConfigError(
                "execution.signal_delay_bars must be an integer, "
                f"got {self.signal_delay_bars!r}"
            )
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ConfigError("fees/slippage cannot be negative")
        if self.signal_delay_bars < 0:
            raise ConfigError("signal_delay_bars cannot be negative")
        if not self.target_vol > 0:
            raise ConfigError(
                "execution.target_vol must be positive for vol targeting; 0.0 is "
                "deprecated (implies no risk targeting / flat sizing) and negative "
                "values invert long-signal direction; use a positive value for "
                "long-signal sizing, or set target_vol=0.0 only when the strategy "
                "explicitly trades cash")
        if not 0 < self.max_position <= 1:
            raise ConfigError("max_position must be in (0, 1]")


@dataclass(frozen=True)
class ModelConfig:
    type: str = "logistic"
    random_seed: int = 42
    parameters: Dict[str, Any] = field(default_factory=lambda: {"C": 1.0, "max_iter": 1000})
    # Optional explicit hyperparameters.  `None` means "unset": build_model falls
    # back to the ``parameters`` bag (which keeps existing call sites and YAML
    # configs working).  An explicitly set field (non-None) is authoritative and
    # overrides the ``parameters`` entry with the same meaning (C08/C09).
    logreg_C: Optional[float] = None
    gb_learning_rate: Optional[float] = None
    gb_n_estimators: Optional[int] = None
    hold_bars: Optional[int] = None

    def __post_init__(self) -> None:
        import math

        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise ConfigError(f"model.random_seed must be an integer, got {self.random_seed!r}")
        if self.hold_bars is not None:
            if isinstance(self.hold_bars, bool) or not isinstance(self.hold_bars, int):
                raise ConfigError(f"model.hold_bars must be an integer, got {self.hold_bars!r}")
            if self.hold_bars < 1:
                raise ConfigError("model.hold_bars must be >= 1")
        for _name in ("logreg_C", "gb_learning_rate"):
            _v = getattr(self, _name)
            if _v is None:
                continue  # unset -> resolved from parameters by build_model
            if isinstance(_v, bool) or not isinstance(_v, (int, float)):
                raise ConfigError(f"model.{_name} must be a real number, got {_v!r}")
            if not math.isfinite(float(_v)):
                raise ConfigError(f"model.{_name} must be finite, got {_v!r}")
        if self.gb_n_estimators is not None:
            if isinstance(self.gb_n_estimators, bool) or not isinstance(self.gb_n_estimators, int):
                raise ConfigError(
                    f"model.gb_n_estimators must be an integer, got {self.gb_n_estimators!r}"
                )
            if self.gb_n_estimators < 1:
                raise ConfigError("model.gb_n_estimators must be >= 1")
        if self.logreg_C is not None and self.logreg_C <= 0:
            raise ConfigError("model.logreg_C must be positive")
        if self.gb_learning_rate is not None and not 0 < self.gb_learning_rate <= 1:
            raise ConfigError("model.gb_learning_rate must be in (0, 1]")
        if self.type not in {"logistic", "gradient_boosting"}:
            raise ConfigError(f"model.type must be logistic|gradient_boosting, got {self.type!r}")
        if self.random_seed < 0:
            raise ConfigError("random_seed must be a non-negative integer")


@dataclass(frozen=True)
class ResearchConfig:
    max_trials: int = 48
    bootstrap_samples: int = 500
    placebo_runs: int = 20
    threshold_candidates: List[float] = field(
        default_factory=lambda: [0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.62, 0.64, 0.66]
    )
    hold_candidates: List[int] = field(default_factory=lambda: [1, 2, 3, 5])

    def __post_init__(self) -> None:
        if self.max_trials <= 0:
            raise ConfigError("research.max_trials must be positive")
        if self.bootstrap_samples <= 0 or self.placebo_runs <= 0:
            raise ConfigError("bootstrap_samples/placebo_runs must be positive")


@dataclass(frozen=True)
class PromotionConfig:
    min_median_oos_sharpe: float = 0.0
    min_mean_oos_sharpe: float = 0.0
    max_oos_dd: float = -0.50
    cost_stress_fee_bps: float = 10.0
    delay_stress_bars: int = 1
    min_bootstrap_positive_prob: float = 0.60
    min_placebo_percentile: float = 0.95
    max_single_fold_share: float = 0.60
    max_annual_turnover: float = 60.0
    # A12: predeclared null-evidence requirements.  The placebo gate accepts
    # only an adequately sampled empirical null (min valid repetitions) and a
    # conservative Monte-Carlo-adjusted p-value (with 20 runs, percentile
    # 0.95 gives adjusted p = 2/21 ~= 0.095 <= 0.10; a single-run null gives
    # p = 0.5 and must always fail).
    min_placebo_runs: int = 20
    max_placebo_adjusted_p: float = 0.10
    # B10: predeclared research-family selection-correction policy.  Repeated
    # candidate research on the same OOS family inflates the chance of a
    # spuriously strong result; this declares HOW that is handled:
    #   - "none"        : no correction (default); promotion still requires the
    #                     placebo + Monte Carlo gate and is recommended only for
    #                     a single predeclared evaluation per family.
    #   - "bonferroni_family" : family-wide Bonferroni correction of the placebo
    #                     adjusted-p by the number of searches on the family.
    # A correction other than "none" requires the search ledger (B11).
    selection_correction: str = "none"
    max_family_searches: int = 1  # recommended cap; informative when correction="none"

    def __post_init__(self) -> None:
        if self.min_placebo_runs < 1:
            raise ConfigError("promotion.min_placebo_runs must be >= 1")
        if not 0 < self.max_placebo_adjusted_p < 1:
            raise ConfigError(
                "promotion.max_placebo_adjusted_p must be in (0, 1)")
        if self.selection_correction not in ("none", "bonferroni_family"):
            raise ConfigError(
                "promotion.selection_correction must be 'none' | 'bonferroni_family'")
        if self.max_family_searches < 1:
            raise ConfigError("promotion.max_family_searches must be >= 1")


@dataclass(frozen=True)
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    research: ResearchConfig = field(default_factory=ResearchConfig)
    promotion: PromotionConfig = field(default_factory=PromotionConfig)
    output_dir: str = "artifacts"

    @classmethod
    def from_yaml(cls, path: str | os.PathLike) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AppConfig":
        return cls(
            data=DataConfig(**raw.get("data", {})),
            evaluation=EvaluationConfig(**raw.get("evaluation", {})),
            execution=ExecutionConfig(**raw.get("execution", {})),
            model=ModelConfig(**raw.get("model", {})),
            research=ResearchConfig(**raw.get("research", {})),
            promotion=PromotionConfig(**raw.get("promotion", {})),
            output_dir=raw.get("output_dir", "artifacts"),
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "data": asdict(self.data),
            "evaluation": asdict(self.evaluation),
            "execution": asdict(self.execution),
            "model": asdict(self.model),
            "research": asdict(self.research),
            "promotion": asdict(self.promotion),
            "output_dir": self.output_dir,
        }
        return out

    def fingerprint(self) -> str:
        """Stable sha256 of the canonical configuration (first 16 hex chars)."""
        raw = json.dumps(self.to_dict(), sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]


def load_config(path: Optional[str] = None) -> AppConfig:
    """Load config from an explicit path or the QUANT_RESEARCH_CONFIG env var."""
    resolved = path or os.environ.get("QUANT_RESEARCH_CONFIG")
    if resolved:
        return AppConfig.from_yaml(resolved)
    return AppConfig()

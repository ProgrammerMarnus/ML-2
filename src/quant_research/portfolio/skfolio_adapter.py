"""Opt-in, constrained multi-asset allocation through skfolio.

This adapter is separate from the existing single-target sizing path. It accepts
training returns only and leaves fold selection and execution to this engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ..data.schemas import DataValidationError


@dataclass(frozen=True)
class SkfolioSpec:
    """Predeclared optimizer constraints for one walk-forward training fold."""

    objective: Literal["min_cvar", "max_sharpe"] = "min_cvar"
    min_weight: float = 0.0
    max_weight: float = 0.20
    budget: float = 1.0
    cvar_beta: float = 0.95
    max_turnover: float | None = None
    transaction_cost: float = 0.0

    def __post_init__(self) -> None:
        if self.objective not in {"min_cvar", "max_sharpe"}:
            raise DataValidationError("skfolio objective must be 'min_cvar' or 'max_sharpe'")
        if not np.isfinite([self.min_weight, self.max_weight, self.budget, self.cvar_beta, self.transaction_cost]).all():
            raise DataValidationError("skfolio constraints must be finite")
        if self.min_weight > self.max_weight:
            raise DataValidationError("skfolio min_weight cannot exceed max_weight")
        if not 0 < self.cvar_beta < 1:
            raise DataValidationError("skfolio cvar_beta must be in (0, 1)")
        if self.transaction_cost < 0:
            raise DataValidationError("skfolio transaction_cost cannot be negative")
        if self.max_turnover is not None and (
            not np.isfinite(self.max_turnover) or self.max_turnover < 0
        ):
            raise DataValidationError("skfolio max_turnover must be non-negative and finite")


def optimize_training_weights(
    training_returns: pd.DataFrame,
    spec: SkfolioSpec,
    previous_weights: pd.Series | None = None,
) -> dict:
    """Fit a constrained allocator on one training-only return matrix."""
    if not isinstance(training_returns, pd.DataFrame) or training_returns.shape[1] < 2:
        raise DataValidationError("skfolio allocation requires returns for at least two assets")
    if training_returns.empty or training_returns.columns.has_duplicates:
        raise DataValidationError("skfolio training return columns must be unique and non-empty")
    values = training_returns.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise DataValidationError("skfolio training returns contain missing/non-finite values")
    if len(training_returns) < 3:
        raise DataValidationError("skfolio allocation requires at least three training observations")
    if spec.max_weight * training_returns.shape[1] + 1e-12 < spec.budget:
        raise DataValidationError("skfolio max_weight constraints cannot satisfy the requested budget")
    if previous_weights is not None:
        previous_weights = previous_weights.reindex(training_returns.columns)
        if previous_weights.isna().any() or not np.isfinite(previous_weights.to_numpy(dtype=float)).all():
            raise DataValidationError("previous allocation must cover every asset with finite weights")
    try:
        from skfolio import RiskMeasure
        from skfolio.optimization import MeanRisk, ObjectiveFunction
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise DataValidationError("portfolio optimization requires the [portfolio] extra (skfolio)") from exc

    kwargs = {
        "risk_measure": RiskMeasure.CVAR,
        "min_weights": spec.min_weight,
        "max_weights": spec.max_weight,
        "budget": spec.budget,
        "cvar_beta": spec.cvar_beta,
        "transaction_costs": spec.transaction_cost,
    }
    if previous_weights is not None:
        kwargs["previous_weights"] = previous_weights.to_numpy(dtype=float)
    if spec.max_turnover is not None:
        kwargs["max_turnover"] = spec.max_turnover
    kwargs["objective_function"] = (
        ObjectiveFunction.MAXIMIZE_RATIO if spec.objective == "max_sharpe"
        else ObjectiveFunction.MINIMIZE_RISK
    )
    estimator = MeanRisk(**kwargs).fit(training_returns)
    weights = pd.Series(estimator.weights_, index=training_returns.columns, name="weight", dtype=float)
    if not np.isfinite(weights.to_numpy()).all():
        raise DataValidationError("skfolio returned non-finite weights")
    if not np.isclose(weights.sum(), spec.budget, rtol=0, atol=1e-7):
        raise DataValidationError("skfolio returned weights that violate the requested budget")
    return {
        "weights": weights,
        "spec": asdict(spec),
        "assets": list(training_returns.columns),
        "n_training_observations": int(len(training_returns)),
        "implementation": "skfolio.MeanRisk",
    }

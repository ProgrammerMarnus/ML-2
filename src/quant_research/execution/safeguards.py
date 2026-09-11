"""Trading safeguards: explicit, testable pre-trade checks.

This module re-exports SafeguardResult and Safeguards from the paper-execution
layer (paper.py) so existing imports continue to work.  The canonical
implementation lives in paper.py alongside the broker that enforces them.
"""

from __future__ import annotations

from quant_research.execution.paper import SafeguardResult, Safeguards

__all__ = ["SafeguardResult", "Safeguards"]

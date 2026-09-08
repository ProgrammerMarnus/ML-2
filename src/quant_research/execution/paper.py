"""Paper-trading interface.

Strict research/execution separation: this module can ONLY simulate paper
orders against validated market data.  It cannot place live orders; a real
broker adapter is intentionally out of scope and gated by future work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


@dataclass
class PaperOrder:
    timestamp: pd.Timestamp
    symbol: str
    side: str  # buy | sell
    quantity: float
    expected_price: float
    filled_price: Optional[float] = None
    slippage_bps: Optional[float] = None
    latency_bars: int = 1  # signal at t, fill at t+1 at the earliest


@dataclass
class PaperBroker:
    """Simulated paper broker: records expected vs simulated fills."""

    fee_bps: float = 5.0
    slippage_bps: float = 1.0
    orders: List[PaperOrder] = field(default_factory=list)

    def submit(self, order: PaperOrder, fill_price: float) -> PaperOrder:
        if order.filled_price is not None:
            raise ValueError("order already filled (duplicate-order protection)")
        order.filled_price = float(fill_price)
        order.slippage_bps = abs(fill_price - order.expected_price) / order.expected_price * 1e4
        self.orders.append(order)
        return order

    def expected_cost_bps(self) -> float:
        return self.fee_bps + self.slippage_bps

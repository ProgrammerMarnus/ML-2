"""Paper-trading engine with full order lifecycle and safeguards.

Strict research/execution separation: this module can ONLY simulate paper
orders against validated market data.  It cannot place live orders; a real
broker adapter is intentionally out of scope and gated by future work.

Order lifecycle:
  PENDING -> SUBMITTED -> PARTIAL_FILL -> FILLED
                                  -> REJECTED
                                  -> CANCELLED
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class PaperOrder:
    """A single paper-trade order with full lifecycle tracking."""
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: Optional[float] = None
    remaining_quantity: float = 0.0
    created_at: Optional[pd.Timestamp] = None
    submitted_at: Optional[pd.Timestamp] = None
    filled_at: Optional[pd.Timestamp] = None
    rejected_at: Optional[pd.Timestamp] = None
    cancel_reason: Optional[str] = None
    expected_price: Optional[float] = None
    slippage_bps: float = 0.0
    latency_bars: int = 1
    fill_events: List[Dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.remaining_quantity == 0.0 and self.quantity > 0:
            self.remaining_quantity = self.quantity


@dataclass
class Position:
    """Track a single symbol position state."""
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    def update_unrealized(self, current_price: float) -> None:
        if self.quantity != 0:
            self.unrealized_pnl = (current_price - self.avg_entry_price) * self.quantity
        else:
            self.unrealized_pnl = 0.0


@dataclass
class AuditEvent:
    """Immutable audit trail entry."""
    timestamp: pd.Timestamp
    event_type: str
    order_id: str
    symbol: str
    detail: str
    data: Dict = field(default_factory=dict)


@dataclass
class SafeguardResult:
    name: str
    passed: bool
    detail: str


class Safeguards:
    """Position/loss limits, stale-data detection, kill switch."""

    def __init__(
        self,
        max_position: float = 1.0,
        max_daily_loss: float = 0.05,
        max_portfolio_drawdown: float = 0.20,
        max_data_age_bars: int = 3,
    ) -> None:
        self.max_position = max_position
        self.max_daily_loss = max_daily_loss
        self.max_portfolio_drawdown = max_portfolio_drawdown
        self.max_data_age_bars = max_data_age_bars
        self.kill_switch_active = False
        self._kill_reason: Optional[str] = None

    def check_position(self, intended: float) -> SafeguardResult:
        ok = abs(intended) <= self.max_position and not self.kill_switch_active
        return SafeguardResult("position_limit", ok,
            f"|position| {abs(intended):.4f} <= {self.max_position}, kill_switch={self.kill_switch_active}")

    def check_daily_loss(self, daily_return: float) -> SafeguardResult:
        ok = daily_return > -self.max_daily_loss
        if not ok:
            self.kill_switch_active = True
            self._kill_reason = f"daily loss {daily_return:.4f} exceeded limit {self.max_daily_loss}"
        return SafeguardResult("daily_loss", ok, f"daily return {daily_return:.4f}")

    def check_drawdown(self, current_drawdown: float) -> SafeguardResult:
        ok = current_drawdown >= -self.max_portfolio_drawdown
        if not ok:
            self.kill_switch_active = True
            self._kill_reason = f"drawdown {current_drawdown:.4f} exceeded limit {self.max_portfolio_drawdown}"
        return SafeguardResult("portfolio_drawdown", ok, f"drawdown {current_drawdown:.4f}")

    def check_data_freshness(self, last_bar_ts: pd.Timestamp, now: pd.Timestamp,
                              bar_freq_days: int = 1) -> SafeguardResult:
        age_bars = int((now - last_bar_ts) / pd.Timedelta(days=bar_freq_days))
        ok = age_bars <= self.max_data_age_bars
        return SafeguardResult("data_freshness", ok, f"data age {age_bars} bars")

    def check_kill_switch(self) -> SafeguardResult:
        return SafeguardResult("kill_switch", not self.kill_switch_active,
            "kill_switch=ACTIVE" if self.kill_switch_active else "kill_switch=inactive")

    def trip_kill_switch(self, reason: str) -> None:
        self.kill_switch_active = True
        self._kill_reason = reason

    def reset_kill_switch(self) -> None:
        self.kill_switch_active = False
        self._kill_reason = None


class PaperBroker:
    """Simulated paper broker with full order lifecycle, safeguards, and accounting."""

    def __init__(
        self,
        fee_bps: float = 5.0,
        slippage_bps: float = 1.0,
        initial_cash: float = 1_000_000.0,
        safeguards: Optional[Safeguards] = None,
        latency_bars: int = 1,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.latency_bars = latency_bars
        self.safeguards = safeguards or Safeguards()
        self.orders: Dict[str, PaperOrder] = {}
        self.pending_orders: List[str] = []
        self.positions: Dict[str, Position] = {}
        self.peak_value = initial_cash
        self.current_value = initial_cash
        self.daily_return = 0.0
        self.audit_trail: List[AuditEvent] = []
        self._current_bar: Optional[pd.Timestamp] = None
        self._bar_counter: int = 0

    def submit(self, order: PaperOrder, current_price: float,
               current_time: pd.Timestamp) -> PaperOrder:
        """Submit an order for execution."""
        order.created_at = current_time
        self._current_bar = current_time

        validation_error = self._validate_order(order, current_price)
        if validation_error:
            return self._reject(order, current_time, validation_error)

        safeguard_failures = self._run_safeguards(order, current_price, current_time)
        if safeguard_failures:
            reasons = "; ".join(f"{s.name}: {s.detail}" for s in safeguard_failures)
            return self._reject(order, current_time, f"Safeguard(s) tripped: {reasons}")

        order.status = OrderStatus.SUBMITTED
        order.submitted_at = current_time
        order.expected_price = current_price
        self.orders[order.order_id] = order
        self.pending_orders.append(order.order_id)
        self._audit(current_time, "ORDER_SUBMITTED", order.order_id,
                    order.symbol, f"{order.side.value} {order.quantity} {order.symbol} @ {order.order_type.value}",
                    {"price": current_price})

        if order.order_type == OrderType.MARKET:
            self._try_fill_market(order, current_price, current_time)
        return order

    def _reject(self, order: PaperOrder, ts: pd.Timestamp, reason: str) -> PaperOrder:
        order.status = OrderStatus.REJECTED
        order.rejected_at = ts
        order.cancel_reason = reason
        self.orders[order.order_id] = order
        self._audit(ts, "ORDER_REJECTED", order.order_id, order.symbol, reason)
        return order

    def _validate_order(self, order: PaperOrder, current_price: float) -> Optional[str]:
        if order.quantity <= 0:
            return f"invalid quantity: {order.quantity}"
        if order.side not in (OrderSide.BUY, OrderSide.SELL):
            return f"invalid side: {order.side}"
        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None or order.limit_price <= 0:
                return f"invalid limit_price: {order.limit_price}"
        if not np.isfinite(current_price) or current_price <= 0:
            return f"invalid market price: {current_price}"
        return None

    def _run_safeguards(self, order: PaperOrder, current_price: float,
                         current_time: pd.Timestamp) -> List[SafeguardResult]:
        failures: List[SafeguardResult] = []
        ks = self.safeguards.check_kill_switch()
        if not ks.passed:
            failures.append(ks)
            return failures

        current_pos = self.positions.get(order.symbol, Position(order.symbol))
        order_value = order.remaining_quantity * current_price
        portfolio_value = max(self.current_value, 1.0)
        new_position_value = abs(current_pos.quantity * current_price) + order_value
        position_weight = new_position_value / portfolio_value
        pos_check = self.safeguards.check_position(position_weight)
        if not pos_check.passed:
            failures.append(pos_check)

        dl_check = self.safeguards.check_daily_loss(self.daily_return)
        if not dl_check.passed:
            failures.append(dl_check)

        dd = self._current_drawdown()
        dd_check = self.safeguards.check_drawdown(dd)
        if not dd_check.passed:
            failures.append(dd_check)
        return failures

    def _try_fill_market(self, order: PaperOrder, current_price: float,
                          current_time: pd.Timestamp) -> None:
        slippage_factor = self.slippage_bps / 10000.0
        if order.side == OrderSide.BUY:
            fill_price = current_price * (1.0 + slippage_factor)
        else:
            fill_price = current_price * (1.0 - slippage_factor)
        order.slippage_bps = self.slippage_bps
        order.latency_bars = self.latency_bars
        self._execute_fill(order, fill_price, order.remaining_quantity, current_time)

    def _try_fill_limit(self, order: PaperOrder, current_price: float,
                         current_time: pd.Timestamp) -> None:
        if order.limit_price is None:
            return
        should_fill = False
        if order.side == OrderSide.BUY and current_price <= order.limit_price:
            should_fill = True
            fill_price = min(current_price, order.limit_price)
        elif order.side == OrderSide.SELL and current_price >= order.limit_price:
            should_fill = True
            fill_price = max(current_price, order.limit_price)
        if should_fill:
            order.slippage_bps = abs(fill_price - current_price) / current_price * 1e4
            order.latency_bars = self.latency_bars
            self._execute_fill(order, fill_price, order.remaining_quantity, current_time)

    def _execute_fill(self, order: PaperOrder, fill_price: float,
                       fill_qty: float, fill_time: pd.Timestamp) -> None:
        order.filled_quantity += fill_qty
        order.remaining_quantity -= fill_qty
        order.filled_price = fill_price
        order.filled_at = fill_time
        if order.remaining_quantity <= 1e-12:
            order.status = OrderStatus.FILLED
            if order.order_id in self.pending_orders:
                self.pending_orders.remove(order.order_id)
        else:
            order.status = OrderStatus.PARTIAL_FILL

        order.fill_events.append({"time": fill_time, "price": fill_price,
            "quantity": fill_qty, "slippage_bps": order.slippage_bps})
        self._update_position(order.symbol, order.side, fill_qty, fill_price)
        cost = fill_qty * fill_price
        fee = cost * self.fee_bps / 10000.0
        if order.side == OrderSide.BUY:
            self.cash -= (cost + fee)
        else:
            self.cash += (cost - fee)
        self._audit(fill_time, "ORDER_FILLED", order.order_id, order.symbol,
                    f"filled {fill_qty} @ {fill_price:.4f} (fee={fee:.2f})")

    def _update_position(self, symbol: str, side: OrderSide, quantity: float,
                          price: float) -> None:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol)
        pos = self.positions[symbol]
        if side == OrderSide.BUY:
            if pos.quantity >= 0:
                total_cost = pos.avg_entry_price * pos.quantity + price * quantity
                pos.quantity += quantity
                pos.avg_entry_price = total_cost / pos.quantity if pos.quantity > 0 else 0.0
            else:
                close_qty = min(quantity, abs(pos.quantity))
                pnl = (pos.avg_entry_price - price) * close_qty
                pos.realized_pnl += pnl
                pos.quantity += quantity
                if pos.quantity > 0:
                    pos.avg_entry_price = price
        else:
            if pos.quantity <= 0:
                total_cost = pos.avg_entry_price * abs(pos.quantity) + price * quantity
                pos.quantity -= quantity
                pos.avg_entry_price = total_cost / abs(pos.quantity) if pos.quantity < 0 else 0.0
            else:
                close_qty = min(quantity, pos.quantity)
                pnl = (price - pos.avg_entry_price) * close_qty
                pos.realized_pnl += pnl
                pos.quantity -= quantity
                if pos.quantity < 0:
                    pos.avg_entry_price = price

    def cancel_order(self, order_id: str, reason: str = "user_request") -> bool:
        if order_id not in self.orders:
            return False
        order = self.orders[order_id]
        if order.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILL):
            return False
        order.status = OrderStatus.CANCELLED
        order.cancel_reason = reason
        if order_id in self.pending_orders:
            self.pending_orders.remove(order_id)
        self._audit(pd.Timestamp.now(), "ORDER_CANCELLED", order_id, order.symbol,
                    f"cancelled: {reason}")
        return True

    def cancel_all(self, symbol: Optional[str] = None, reason: str = "cancel_all") -> int:
        cancelled = 0
        for order_id in list(self.pending_orders):
            order = self.orders[order_id]
            if symbol is None or order.symbol == symbol:
                if self.cancel_order(order_id, reason):
                    cancelled += 1
        return cancelled

    def process_bar(self, timestamp: pd.Timestamp, prices: Dict[str, float]) -> List[PaperOrder]:
        self._current_bar = timestamp
        self._bar_counter += 1
        filled_orders: List[PaperOrder] = []
        for symbol, pos in self.positions.items():
            if symbol in prices:
                pos.update_unrealized(prices[symbol])
        for order_id in list(self.pending_orders):
            order = self.orders[order_id]
            if order.order_type == OrderType.LIMIT and order.symbol in prices:
                self._try_fill_limit(order, prices[order.symbol], timestamp)
                if order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL):
                    filled_orders.append(order)
        self._update_portfolio_value(prices)
        return filled_orders

    def _update_portfolio_value(self, prices: Dict[str, float]) -> None:
        position_value = sum(pos.quantity * prices[symbol]
            for symbol, pos in self.positions.items() if symbol in prices)
        self.current_value = self.cash + position_value
        if self.current_value > self.peak_value:
            self.peak_value = self.current_value

    def _current_drawdown(self) -> float:
        if self.peak_value <= 0:
            return 0.0
        return (self.current_value - self.peak_value) / self.peak_value

    def update_daily_return(self, daily_return: float) -> None:
        self.daily_return = daily_return
        self.safeguards.check_daily_loss(daily_return)

    @property
    def total_realized_pnl(self) -> float:
        return sum(pos.realized_pnl for pos in self.positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    def get_position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol))

    def get_order(self, order_id: str) -> Optional[PaperOrder]:
        return self.orders.get(order_id)

    def get_audit_trail(self) -> List[AuditEvent]:
        return list(self.audit_trail)

    def expected_cost_bps(self) -> float:
        return self.fee_bps + self.slippage_bps

    def _audit(self, timestamp: pd.Timestamp, event_type: str, order_id: str,
               symbol: str, detail: str, data: Optional[Dict] = None) -> None:
        self.audit_trail.append(AuditEvent(timestamp=timestamp, event_type=event_type,
            order_id=order_id, symbol=symbol, detail=detail, data=data or {}))

    def reconcile(self) -> Dict:
        """Reconcile positions against filled orders."""
        computed_positions: Dict[str, float] = {}
        for order in self.orders.values():
            if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL):
                continue
            if order.symbol not in computed_positions:
                computed_positions[order.symbol] = 0.0
            if order.side == OrderSide.BUY:
                computed_positions[order.symbol] += order.filled_quantity
            else:
                computed_positions[order.symbol] -= order.filled_quantity
        discrepancies = {}
        for symbol, expected_qty in computed_positions.items():
            actual_qty = self.positions.get(symbol, Position(symbol)).quantity
            if abs(expected_qty - actual_qty) > 1e-9:
                discrepancies[symbol] = {"expected": expected_qty, "actual": actual_qty}
        for symbol, pos in self.positions.items():
            if symbol not in computed_positions and abs(pos.quantity) > 1e-9:
                discrepancies[symbol] = {"expected": 0.0, "actual": pos.quantity}
        return {"consistent": len(discrepancies) == 0, "discrepancies": discrepancies,
                "n_orders": len(self.orders),
                "n_filled": sum(1 for o in self.orders.values() if o.status == OrderStatus.FILLED),
                "n_rejected": sum(1 for o in self.orders.values() if o.status == OrderStatus.REJECTED),
                "n_cancelled": sum(1 for o in self.orders.values() if o.status == OrderStatus.CANCELLED),
                "n_pending": len(self.pending_orders)}

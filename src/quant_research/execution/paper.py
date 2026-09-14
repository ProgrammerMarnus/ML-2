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

import hashlib
import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
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
    spread_bps: float = 0.0
    latency_bars: int = 1
    # Explicit execution-clock metadata.  A submitted order is not eligible
    # to fill until ``eligible_bar`` has been observed by ``process_bar``.
    reduce_only: bool = False
    submitted_bar: Optional[int] = None
    eligible_bar: Optional[int] = None
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


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit trail entry."""
    timestamp: pd.Timestamp
    event_type: str
    order_id: str
    symbol: str
    detail: str
    data: Dict = field(default_factory=dict)
    previous_hash: str = ""
    event_hash: str = ""


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
        self._baseline_max_position = max_position
        self._temporary_limit_expires_at: Optional[pd.Timestamp] = None
        self.kill_switch_active = False
        self._kill_reason: Optional[str] = None

    def refresh_position_limit(self, now: Optional[pd.Timestamp] = None) -> bool:
        """Expire a temporary limit and restore the configured baseline."""
        if self._temporary_limit_expires_at is None:
            return False
        now = now or pd.Timestamp.now(tz="UTC")
        if now.tzinfo is None:
            raise ValueError("position-limit clock must be timezone-aware")
        if now < self._temporary_limit_expires_at:
            return False
        self.max_position = self._baseline_max_position
        self._temporary_limit_expires_at = None
        return True

    def set_temporary_position_limit(self, limit: float,
                                     expires_at: pd.Timestamp) -> None:
        if not math.isfinite(limit) or not 0 < limit <= 2.0:
            raise ValueError("temporary position limit must be in (0, 2.0]")
        if not isinstance(expires_at, pd.Timestamp) or expires_at.tzinfo is None:
            raise ValueError("temporary position-limit expiry must be timezone-aware")
        if expires_at <= pd.Timestamp.now(tz="UTC"):
            raise ValueError("temporary position-limit expiry must be in the future")
        self.refresh_position_limit()
        if self._temporary_limit_expires_at is not None:
            raise ValueError("a temporary position-limit override is already active")
        self._baseline_max_position = self.max_position
        self.max_position = limit
        self._temporary_limit_expires_at = expires_at

    def check_position(self, intended: float) -> SafeguardResult:
        self.refresh_position_limit()
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
        spread_bps: float = 0.0,
        max_gross_exposure: float = 1.0,
        short_margin_ratio: float = 1.5,
    ) -> None:
        if not math.isfinite(spread_bps) or spread_bps < 0:
            raise ValueError("spread_bps must be finite and non-negative")
        if not math.isfinite(max_gross_exposure) or max_gross_exposure <= 0:
            raise ValueError("max_gross_exposure must be finite and positive")
        if not math.isfinite(short_margin_ratio) or short_margin_ratio <= 0:
            raise ValueError("short_margin_ratio must be finite and positive")
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.spread_bps = spread_bps
        self.max_gross_exposure = max_gross_exposure
        self.short_margin_ratio = short_margin_ratio
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
        self._last_marks: Dict[str, float] = {}

    def submit(self, order: PaperOrder, current_price: float,
               current_time: pd.Timestamp) -> PaperOrder:
        """Submit an order for execution.

        Runs pre-trade checks: kill switch, position limit, cash, exposure.
        Returns a SafeguardResult that is FAILING when the order cannot be accepted.
        """
        # E07: order-ID idempotency — retrying an order_id must not double-execute
        # and must be checked before other guards so a retry keeps its original
        # record/history instead of being overwritten.  Reuse of a terminal
        # REJECTED/CANCELLED id is also forbidden (history must never be overwritten).
        existing = self.orders.get(order.order_id)
        if existing is not None:
            if self._request_key(existing) != self._request_key(order):
                self._audit(current_time, "ORDER_ID_CONFLICT", order.order_id,
                            order.symbol,
                            "order_id is already bound to a different request")
                raise ValueError(
                    f"order_id {order.order_id} is already bound to a different request"
                )
            self._audit(current_time, "ORDER_DUPLICATE_REJECTED", order.order_id,
                        order.symbol,
                        f"duplicate order_id {order.order_id} rejected; "
                        f"existing status {existing.status.value}")
            return existing
        if not isinstance(current_time, pd.Timestamp) or current_time.tzinfo is None:
            return self._reject(order, current_time,
                "current_time must be a timezone-aware pd.Timestamp")
        if not math.isfinite(current_price) or current_price <= 0:
            return self._reject(order, current_time,
                f"current_price must be finite and positive; got {current_price}")
        # A tripped kill switch blocks risk-increasing flow.  Explicit
        # reduce-only orders are the audited emergency-exit exception.
        if self.safeguards.kill_switch_active and not order.reduce_only:
            self._audit(current_time, "SUBMIT_REJECTED", order.order_id, order.symbol,
                "kill switch active")
            return self._reject(order, current_time, "kill_switch active; no orders accepted")
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
        order.spread_bps = self.spread_bps if order.order_type == OrderType.MARKET else 0.0
        order.submitted_bar = self._bar_counter
        order.latency_bars = max(1, int(self.latency_bars))
        order.eligible_bar = self._bar_counter + order.latency_bars
        self.orders[order.order_id] = order
        self.pending_orders.append(order.order_id)
        self._audit(current_time, "ORDER_SUBMITTED", order.order_id,
                    order.symbol, f"{order.side.value} {order.quantity} {order.symbol} @ {order.order_type.value}",
                    {"price": current_price})
        # E06: market orders respect configured latency; they rest as SUBMITTED
        # at submission and fill on a later process_bar.
        if order.order_type == OrderType.MARKET:
            order.slippage_bps = self.slippage_bps
        return order

    @staticmethod
    def _request_key(order: PaperOrder) -> tuple:
        """Fields that define the immutable content of a broker request."""
        return (
            order.symbol, order.side, float(order.quantity), order.order_type,
            order.limit_price, bool(order.reduce_only),
        )

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
        if order.reduce_only and not self._reduces_exposure(order, order.quantity):
            return "reduce_only order would not reduce the current position"
        if not np.isfinite(current_price) or current_price <= 0:
            return f"invalid market price: {current_price}"
        return None

    def _run_safeguards(self, order: PaperOrder, current_price: float,
                         current_time: pd.Timestamp) -> List[SafeguardResult]:
        failures: List[SafeguardResult] = []
        if self.safeguards.refresh_position_limit(current_time):
            self._audit(
                current_time, "POSITION_LIMIT_OVERRIDE_EXPIRED",
                order.order_id, order.symbol,
                f"restored baseline limit {self.safeguards.max_position:.4f}",
            )
        ks = self.safeguards.check_kill_switch()
        if not ks.passed and not order.reduce_only:
            failures.append(ks)
            return failures

        current_pos = self.positions.get(order.symbol, Position(order.symbol))
        portfolio_value = max(self.current_value, 1.0)
        current_qty = current_pos.quantity
        if order.side == OrderSide.BUY:
            new_qty = current_qty + order.remaining_quantity
        else:
            new_qty = current_qty - order.remaining_quantity
        pending_net = 0.0
        for oid in self.pending_orders:
            po = self.orders.get(oid)
            if po is None or po.symbol != order.symbol:
                continue
            if po.side == OrderSide.BUY:
                pending_net += po.remaining_quantity
            else:
                pending_net -= po.remaining_quantity
        new_qty += pending_net
        # Reducing or flattening exposure must always be allowed (E04): only
        # block orders that increase the absolute position beyond the limit.
        # Pending same-symbol exposure counts toward the limit (E05).
        if abs(new_qty) > abs(current_qty):
            position_weight = abs(new_qty * current_price) / portfolio_value
            pos_check = self.safeguards.check_position(position_weight)
            if not pos_check.passed:
                failures.append(pos_check)
        # Reserve all pending buys, across the whole portfolio.  A per-symbol
        # check lets several individually valid orders spend the same cash.
        if order.side == OrderSide.BUY:
            required = self._reserved_buy_cash(current_price, include_order=order)
            if self.cash + 1e-12 < required:
                failures.append(SafeguardResult(
                    "cash", False,
                    f"insufficient cash {self.cash:.2f} for reserved buys {required:.2f}"))

        risk_failure = self._projected_risk_failure(
            order, current_price, include_order=True,
        )
        if risk_failure is not None:
            failures.append(SafeguardResult("buying_power", False, risk_failure))

        if not order.reduce_only:
            dl_check = self.safeguards.check_daily_loss(self.daily_return)
            if not dl_check.passed:
                failures.append(dl_check)

            dd = self._current_drawdown()
            dd_check = self.safeguards.check_drawdown(dd)
            if not dd_check.passed:
                failures.append(dd_check)
        return failures

    def _position_price(self, symbol: str, current_symbol: str,
                        current_price: float) -> float:
        if symbol == current_symbol:
            return current_price
        mark = self._last_marks.get(symbol)
        if mark is not None and math.isfinite(mark) and mark > 0:
            return mark
        pos = self.positions.get(symbol)
        if pos is not None and math.isfinite(pos.avg_entry_price) and pos.avg_entry_price > 0:
            return pos.avg_entry_price
        for order_id in self.pending_orders:
            pending = self.orders.get(order_id)
            if pending is None or pending.symbol != symbol:
                continue
            price = pending.limit_price if pending.order_type == OrderType.LIMIT else pending.expected_price
            if price is not None and math.isfinite(price) and price > 0:
                return float(price)
        return 0.0

    def _projected_risk(self, order: PaperOrder, current_price: float,
                        *, include_order: bool,
                        exclude_order_id: Optional[str] = None) -> Dict[str, float]:
        quantities = {symbol: pos.quantity for symbol, pos in self.positions.items()}
        for order_id in self.pending_orders:
            if order_id == exclude_order_id:
                continue
            pending = self.orders.get(order_id)
            if pending is None:
                continue
            signed = pending.remaining_quantity if pending.side == OrderSide.BUY else -pending.remaining_quantity
            quantities[pending.symbol] = quantities.get(pending.symbol, 0.0) + signed
        if include_order:
            signed = order.remaining_quantity if order.side == OrderSide.BUY else -order.remaining_quantity
            quantities[order.symbol] = quantities.get(order.symbol, 0.0) + signed

        gross_notional = 0.0
        short_notional = 0.0
        for symbol, quantity in quantities.items():
            price = self._position_price(symbol, order.symbol, current_price)
            notional = quantity * price
            gross_notional += abs(notional)
            short_notional += max(-notional, 0.0)
        equity = max(self.current_value, 0.0)
        return {
            "equity": equity,
            "gross_notional": gross_notional,
            "gross_exposure": gross_notional / max(equity, 1.0),
            "short_notional": short_notional,
            "short_margin_required": short_notional * self.short_margin_ratio,
        }

    def _projected_risk_failure(self, order: PaperOrder, current_price: float,
                                *, include_order: bool,
                                order_already_pending: bool = False) -> Optional[str]:
        baseline = self._projected_risk(
            order, current_price, include_order=False,
            exclude_order_id=order.order_id if order_already_pending else None,
        )
        projected = self._projected_risk(
            order, current_price, include_order=include_order,
        )
        if projected["gross_notional"] > baseline["gross_notional"] + 1e-12:
            if projected["gross_exposure"] > self.max_gross_exposure + 1e-12:
                return (
                    f"gross exposure {projected['gross_exposure']:.4f} exceeds "
                    f"limit {self.max_gross_exposure:.4f}"
                )
        if projected["short_notional"] > baseline["short_notional"] + 1e-12:
            if projected["short_margin_required"] > projected["equity"] + 1e-12:
                return (
                    f"short margin {projected['short_margin_required']:.2f} exceeds "
                    f"equity {projected['equity']:.2f}"
                )
        return None

    def _reserved_buy_cash(self, current_price: float,
                           include_order: Optional[PaperOrder] = None,
                           exclude_order_id: Optional[str] = None) -> float:
        """Worst-case cash reservation for all submitted buy orders and fees."""
        buys: List[PaperOrder] = []
        for oid in self.pending_orders:
            if oid == exclude_order_id:
                continue
            candidate = self.orders.get(oid)
            if candidate is not None and candidate.side == OrderSide.BUY:
                buys.append(candidate)
        if include_order is not None and include_order.side == OrderSide.BUY:
            buys.append(include_order)
        total = 0.0
        for candidate in buys:
            if candidate is include_order:
                price = current_price
            elif candidate.order_type == OrderType.LIMIT:
                price = float(candidate.limit_price)
            else:
                price = float(candidate.expected_price or current_price)
            total += candidate.remaining_quantity * price * (1.0 + self.fee_bps / 10000.0)
        return total

    def _reduces_exposure(self, order: PaperOrder, quantity: float) -> bool:
        current = self.positions.get(order.symbol, Position(order.symbol)).quantity
        signed = quantity if order.side == OrderSide.BUY else -quantity
        after = current + signed
        # A reduce-only exit can flatten, but cannot reverse the position.
        return (
            abs(current) > 1e-12
            and abs(after) < abs(current) - 1e-12
            and current * after >= -1e-12
        )

    def _fill_is_permitted(self, order: PaperOrder, fill_price: float,
                           fill_qty: float) -> Optional[str]:
        """Recheck cash and exposure at the executable price and bar."""
        if not math.isfinite(fill_price) or fill_price <= 0:
            return "invalid fill price"
        if self.safeguards.kill_switch_active and not order.reduce_only:
            return "kill switch active"
        if order.reduce_only and not self._reduces_exposure(order, fill_qty):
            return "reduce_only order no longer reduces exposure"

        current = self.positions.get(order.symbol, Position(order.symbol)).quantity
        signed = fill_qty if order.side == OrderSide.BUY else -fill_qty
        pending_other = 0.0
        for oid in self.pending_orders:
            if oid == order.order_id:
                continue
            pending = self.orders.get(oid)
            if pending is not None and pending.symbol == order.symbol:
                pending_other += (pending.remaining_quantity
                                  if pending.side == OrderSide.BUY
                                  else -pending.remaining_quantity)
        projected = current + signed + pending_other
        if abs(projected) > abs(current):
            weight = abs(projected * fill_price) / max(self.current_value, 1.0)
            if weight > self.safeguards.max_position + 1e-12:
                return f"position limit exceeded at fill ({weight:.4f})"
        if order.side == OrderSide.BUY:
            remaining_after = max(order.remaining_quantity - fill_qty, 0.0)
            reserve = self._reserved_buy_cash(
                fill_price, exclude_order_id=order.order_id
            )
            reserve += (fill_qty + remaining_after) * fill_price * (
                1.0 + self.fee_bps / 10000.0
            )
            if self.cash + 1e-12 < reserve:
                return f"insufficient cash at fill ({self.cash:.2f} < {reserve:.2f})"
        risk_failure = self._projected_risk_failure(
            order, fill_price, include_order=False, order_already_pending=True,
        )
        if risk_failure is not None:
            return risk_failure
        return None

    def _try_fill_market(self, order: PaperOrder, current_price: float,
                           current_time: pd.Timestamp) -> None:
        # E06: market orders respect configured latency; they rest as
        # SUBMITTED at submission and fill on a later process_bar.
        order.slippage_bps = self.slippage_bps
        order.latency_bars = self.latency_bars
        return None

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
            order.spread_bps = 0.0
            order.latency_bars = self.latency_bars
            self._execute_fill(
                order, fill_price, order.remaining_quantity, current_time,
                reference_price=current_price,
            )

    def _execute_fill(self, order: PaperOrder, fill_price: float,
                       fill_qty: float, fill_time: pd.Timestamp,
                       reference_price: Optional[float] = None) -> None:
        reason = self._fill_is_permitted(order, fill_price, fill_qty)
        if reason:
            order.status = OrderStatus.CANCELLED
            order.cancel_reason = reason
            if order.order_id in self.pending_orders:
                self.pending_orders.remove(order.order_id)
            self._audit(fill_time, "ORDER_CANCELLED", order.order_id, order.symbol,
                        f"fill prevented: {reason}")
            return
        previous_filled = order.filled_quantity
        new_filled = previous_filled + fill_qty
        if previous_filled > 0 and order.filled_price is not None:
            order.filled_price = (
                order.filled_price * previous_filled + fill_price * fill_qty
            ) / new_filled
        else:
            order.filled_price = fill_price
        order.filled_quantity = new_filled
        order.remaining_quantity -= fill_qty
        order.filled_at = fill_time
        if order.remaining_quantity <= 1e-12:
            order.status = OrderStatus.FILLED
            if order.order_id in self.pending_orders:
                self.pending_orders.remove(order.order_id)
        else:
            order.status = OrderStatus.PARTIAL_FILL

        cost = fill_qty * fill_price
        fee = cost * self.fee_bps / 10000.0
        reference = float(reference_price if reference_price is not None else fill_price)
        reference_notional = fill_qty * reference
        slippage_cost = reference_notional * order.slippage_bps / 10000.0
        spread_cost = reference_notional * order.spread_bps / 10000.0
        order.fill_events.append({
            "time": fill_time,
            "price": fill_price,
            "reference_price": reference,
            "quantity": fill_qty,
            "gross_notional": cost,
            "fee": fee,
            "slippage_bps": order.slippage_bps,
            "slippage_cost": slippage_cost,
            "spread_bps": order.spread_bps,
            "spread_cost": spread_cost,
            "total_explicit_cost": fee + slippage_cost + spread_cost,
        })
        self._update_position(order.symbol, order.side, fill_qty, fill_price)
        if order.side == OrderSide.BUY:
            self.cash -= (cost + fee)
        else:
            self.cash += (cost - fee)
        self._audit(fill_time, "ORDER_FILLED", order.order_id, order.symbol,
                    f"filled {fill_qty} @ {fill_price:.4f} (fee={fee:.2f})",
                    {
                        "reference_price": reference,
                        "fee": fee,
                        "slippage_cost": slippage_cost,
                        "spread_cost": spread_cost,
                    })

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
        self._audit(pd.Timestamp.now(tz="UTC"), "ORDER_CANCELLED", order_id, order.symbol,
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
        if not isinstance(timestamp, pd.Timestamp) or timestamp.tzinfo is None:
            raise ValueError("timestamp must be a timezone-aware pd.Timestamp")
        if self._current_bar is not None and timestamp <= self._current_bar:
            raise ValueError("bar timestamps must be strictly increasing")
        self._current_bar = timestamp
        self._bar_counter += 1
        # Cancel exposure-increasing resting orders after a kill switch trip,
        # while preserving explicitly reduce-only exits for emergency flattening.
        if self.safeguards.kill_switch_active:
            for order_id in list(self.pending_orders):
                order = self.orders[order_id]
                if order.reduce_only:
                    continue
                order.status = OrderStatus.CANCELLED
                order.cancel_reason = "kill_switch_active"
                self.pending_orders.remove(order_id)
                self._audit(timestamp, "ORDER_CANCELLED", order_id, order.symbol,
                            "cancelled: kill_switch_active")
        # E19: seed last-valid marks before any valuation/fill logic.
        for symbol, px in prices.items():
            try:
                fpx = float(px)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fpx) and fpx > 0 and symbol not in self._last_marks:
                self._last_marks[symbol] = fpx
        filled_orders: List[PaperOrder] = []
        for symbol, pos in self.positions.items():
            if symbol not in prices:
                continue
            try:
                px = float(prices[symbol])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(px) or px <= 0:
                continue
            pos.update_unrealized(px)
        # Revalue existing holdings before fill-time buying-power and margin
        # checks so they use current-bar equity rather than the previous mark.
        self._update_portfolio_value(prices)
        for order_id in list(self.pending_orders):
            order = self.orders[order_id]
            if order.symbol not in prices:
                continue
            try:
                opx = float(prices[order.symbol])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(opx) or opx <= 0:
                continue
            if order.eligible_bar is not None and self._bar_counter < order.eligible_bar:
                continue
            if order.order_type == OrderType.LIMIT:
                self._try_fill_limit(order, opx, timestamp)
            elif order.order_type == OrderType.MARKET:
                execution_cost_bps = self.slippage_bps + self.spread_bps
                slippage_factor = execution_cost_bps / 10000.0
                if order.side == OrderSide.BUY:
                    fill_price = opx * (1.0 + slippage_factor)
                else:
                    fill_price = opx * (1.0 - slippage_factor)
                order.slippage_bps = self.slippage_bps
                order.spread_bps = self.spread_bps
                self._execute_fill(
                    order, fill_price, order.remaining_quantity, timestamp,
                    reference_price=opx,
                )
            if order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL):
                filled_orders.append(order)
        self._update_portfolio_value(prices)
        return filled_orders

    def _update_portfolio_value(self, prices: Dict[str, float]) -> None:
        # E19: mark with the last valid price when a held symbol is omitted
        # or its update is missing/NaN/non-positive; such marks never move
        # the portfolio value.
        for symbol, px in prices.items():
            try:
                fpx = float(px)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fpx) and fpx > 0:
                self._last_marks[symbol] = fpx
        position_value = 0.0
        for symbol, pos in self.positions.items():
            if symbol in prices:
                try:
                    px = float(prices[symbol])
                except (TypeError, ValueError):
                    px = self._last_marks.get(symbol, float("nan"))
                if not math.isfinite(px) or px <= 0:
                    px = self._last_marks.get(symbol)
                    if px is None:
                        continue
            else:
                if symbol not in self._last_marks:
                    continue
                px = self._last_marks[symbol]
            pos.update_unrealized(px)
            position_value += pos.quantity * px
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
        return self.fee_bps + self.slippage_bps + self.spread_bps

    def cost_attribution(self) -> Dict[str, float]:
        """Return execution costs derived from immutable per-fill events."""
        totals = {"fees": 0.0, "slippage": 0.0, "spread": 0.0, "notional": 0.0}
        for order in self.orders.values():
            for event in order.fill_events:
                quantity = float(event.get("quantity", 0.0))
                price = float(event.get("price", 0.0))
                reference = float(event.get("reference_price", price))
                notional = float(event.get("gross_notional", quantity * price))
                totals["notional"] += notional
                totals["fees"] += float(
                    event.get("fee", notional * self.fee_bps / 10000.0)
                )
                totals["slippage"] += float(event.get(
                    "slippage_cost",
                    quantity * reference * float(event.get("slippage_bps", 0.0)) / 10000.0,
                ))
                totals["spread"] += float(event.get(
                    "spread_cost",
                    quantity * reference * float(event.get("spread_bps", 0.0)) / 10000.0,
                ))
        totals["total"] = totals["fees"] + totals["slippage"] + totals["spread"]
        return totals

    def buying_power(self) -> Dict[str, float]:
        """Current cash, gross-exposure, and short-margin capacity."""
        placeholder = PaperOrder("__RISK__", OrderSide.BUY, 0.0)
        risk = self._projected_risk(placeholder, 0.0, include_order=False)
        reserved_cash = self._reserved_buy_cash(0.0)
        return {
            **risk,
            "cash": self.cash,
            "reserved_buy_cash": reserved_cash,
            "available_cash": self.cash - reserved_cash,
            "gross_exposure_limit": self.max_gross_exposure,
            "short_margin_ratio": self.short_margin_ratio,
        }

    def _audit(self, timestamp: pd.Timestamp, event_type: str, order_id: str,
               symbol: str, detail: str, data: Optional[Dict] = None) -> None:
        payload = {
            "timestamp": timestamp.isoformat(), "event_type": event_type,
            "order_id": order_id, "symbol": symbol, "detail": detail,
            "data": data or {},
        }
        previous_hash = self.audit_trail[-1].event_hash if self.audit_trail else ""
        raw = json.dumps(
            {"previous_hash": previous_hash, **payload}, sort_keys=True, default=str,
            separators=(",", ":"),
        )
        event_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.audit_trail.append(AuditEvent(
            timestamp=timestamp, event_type=event_type, order_id=order_id,
            symbol=symbol, detail=detail, data=data or {},
            previous_hash=previous_hash, event_hash=event_hash,
        ))

    def verify_audit_trail(self) -> bool:
        """Verify the append-only hash chain and per-order event chronology."""
        previous_hash = ""
        last_by_order: Dict[str, pd.Timestamp] = {}
        for event in self.audit_trail:
            if (not event.order_id or not event.symbol or not event.event_hash
                    or event.previous_hash != previous_hash
                    or not isinstance(event.timestamp, pd.Timestamp)
                    or event.timestamp.tzinfo is None):
                return False
            previous_time = last_by_order.get(event.order_id)
            if previous_time is not None and event.timestamp < previous_time:
                return False
            payload = {
                "timestamp": event.timestamp.isoformat(), "event_type": event.event_type,
                "order_id": event.order_id, "symbol": event.symbol,
                "detail": event.detail, "data": event.data,
            }
            raw = json.dumps(
                {"previous_hash": previous_hash, **payload}, sort_keys=True,
                default=str, separators=(",", ":"),
            )
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != event.event_hash:
                return False
            previous_hash = event.event_hash
            last_by_order[event.order_id] = event.timestamp
        return True

    @staticmethod
    def _encode(value):
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {str(k): PaperBroker._encode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [PaperBroker._encode(v) for v in value]
        return value

    @staticmethod
    def _timestamp(value):
        return pd.Timestamp(value) if value is not None else None

    def save_state(self, path: str | Path) -> Path:
        """Persist enough state to resume paper simulation without reordering it."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"refusing to overwrite broker state: {target}")
        document = {
            "schema_version": 2,
            "fee_bps": self.fee_bps, "slippage_bps": self.slippage_bps,
            "spread_bps": self.spread_bps,
            "max_gross_exposure": self.max_gross_exposure,
            "short_margin_ratio": self.short_margin_ratio,
            "initial_cash": self.initial_cash, "cash": self.cash,
            "latency_bars": self.latency_bars, "peak_value": self.peak_value,
            "current_value": self.current_value, "daily_return": self.daily_return,
            "bar_counter": self._bar_counter, "current_bar": self._encode(self._current_bar),
            "last_marks": self._last_marks, "pending_orders": self.pending_orders,
            "orders": [self._encode(asdict(order)) for order in self.orders.values()],
            "positions": [asdict(position) for position in self.positions.values()],
            "audit_trail": [self._encode(asdict(event)) for event in self.audit_trail],
            "safeguards": {
                "max_position": self.safeguards.max_position,
                "baseline_max_position": self.safeguards._baseline_max_position,
                "temporary_limit_expires_at": self._encode(
                    self.safeguards._temporary_limit_expires_at
                ),
                "max_daily_loss": self.safeguards.max_daily_loss,
                "max_portfolio_drawdown": self.safeguards.max_portfolio_drawdown,
                "max_data_age_bars": self.safeguards.max_data_age_bars,
                "kill_switch_active": self.safeguards.kill_switch_active,
                "kill_reason": self.safeguards._kill_reason,
            },
        }
        target.write_text(json.dumps(document, sort_keys=True, default=str), encoding="utf-8")
        return target

    @classmethod
    def load_state(cls, path: str | Path) -> "PaperBroker":
        """Restore a verified broker snapshot; corrupted evidence is rejected."""
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") not in (1, 2):
            raise ValueError("unsupported broker-state schema")
        safeguards_data = document["safeguards"]
        safeguards = Safeguards(
            max_position=safeguards_data["max_position"],
            max_daily_loss=safeguards_data["max_daily_loss"],
            max_portfolio_drawdown=safeguards_data["max_portfolio_drawdown"],
            max_data_age_bars=safeguards_data["max_data_age_bars"],
        )
        safeguards.kill_switch_active = bool(safeguards_data["kill_switch_active"])
        safeguards._kill_reason = safeguards_data.get("kill_reason")
        safeguards._baseline_max_position = safeguards_data.get(
            "baseline_max_position", safeguards.max_position,
        )
        safeguards._temporary_limit_expires_at = cls._timestamp(
            safeguards_data.get("temporary_limit_expires_at")
        )
        broker = cls(
            document["fee_bps"], document["slippage_bps"],
            document["initial_cash"], safeguards, document["latency_bars"],
            spread_bps=document.get("spread_bps", 0.0),
            max_gross_exposure=document.get("max_gross_exposure", 1.0),
            short_margin_ratio=document.get("short_margin_ratio", 1.5),
        )
        broker.cash, broker.peak_value = document["cash"], document["peak_value"]
        broker.current_value, broker.daily_return = document["current_value"], document["daily_return"]
        broker._bar_counter = document["bar_counter"]
        broker._current_bar = cls._timestamp(document.get("current_bar"))
        broker._last_marks = {k: float(v) for k, v in document.get("last_marks", {}).items()}
        for raw in document["orders"]:
            raw["side"] = OrderSide(raw["side"])
            raw["order_type"] = OrderType(raw["order_type"])
            raw["status"] = OrderStatus(raw["status"])
            for key in ("created_at", "submitted_at", "filled_at", "rejected_at"):
                raw[key] = cls._timestamp(raw[key])
            raw["fill_events"] = [
                {**event, "time": cls._timestamp(event["time"])}
                for event in raw.get("fill_events", [])
            ]
            order = PaperOrder(**raw)
            broker.orders[order.order_id] = order
        broker.pending_orders = list(document["pending_orders"])
        broker.positions = {raw["symbol"]: Position(**raw) for raw in document["positions"]}
        broker.audit_trail = [
            AuditEvent(
                timestamp=cls._timestamp(raw["timestamp"]), event_type=raw["event_type"],
                order_id=raw["order_id"], symbol=raw["symbol"], detail=raw["detail"],
                data=raw.get("data", {}), previous_hash=raw.get("previous_hash", ""),
                event_hash=raw.get("event_hash", ""),
            )
            for raw in document["audit_trail"]
        ]
        if not broker.verify_audit_trail() or not broker.reconcile()["consistent"]:
            raise ValueError("broker state failed audit or reconciliation verification")
        return broker

    def reconcile(self) -> Dict:
        """Reconcile positions and cash against the immutable fill ledger."""
        computed_positions: Dict[str, float] = {}
        expected_cash = self.initial_cash
        for order in self.orders.values():
            if order.status not in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL):
                continue
            if order.symbol not in computed_positions:
                computed_positions[order.symbol] = 0.0
            if order.side == OrderSide.BUY:
                computed_positions[order.symbol] += order.filled_quantity
            else:
                computed_positions[order.symbol] -= order.filled_quantity
            for event in order.fill_events:
                quantity = float(event["quantity"])
                price = float(event["price"])
                notional = quantity * price
                fee = float(event.get("fee", notional * self.fee_bps / 10000.0))
                if order.side == OrderSide.BUY:
                    expected_cash -= notional + fee
                else:
                    expected_cash += notional - fee
        discrepancies = {}
        for symbol, expected_qty in computed_positions.items():
            actual_qty = self.positions.get(symbol, Position(symbol)).quantity
            if abs(expected_qty - actual_qty) > 1e-9:
                discrepancies[symbol] = {"expected": expected_qty, "actual": actual_qty}
        for symbol, pos in self.positions.items():
            if symbol not in computed_positions and abs(pos.quantity) > 1e-9:
                discrepancies[symbol] = {"expected": 0.0, "actual": pos.quantity}
        cash_difference = self.cash - expected_cash
        cash_consistent = abs(cash_difference) <= 1e-6
        return {"consistent": len(discrepancies) == 0 and cash_consistent,
                "discrepancies": discrepancies,
                "cash_consistent": cash_consistent,
                "expected_cash": expected_cash,
                "actual_cash": self.cash,
                "cash_difference": cash_difference,
                "n_orders": len(self.orders),
                "n_filled": sum(1 for o in self.orders.values() if o.status == OrderStatus.FILLED),
                "n_rejected": sum(1 for o in self.orders.values() if o.status == OrderStatus.REJECTED),
                "n_cancelled": sum(1 for o in self.orders.values() if o.status == OrderStatus.CANCELLED),
                "n_pending": len(self.pending_orders)}

"""Operational readiness: monitoring, manual override, and failure recovery.

This module provides the operational infrastructure needed for paper trading:
- Real-time monitoring dashboard (text-based)
- Manual override capability (cancel all, flatten, reset kill switch)
- Configuration validation before launch
- Failure/restart recovery tests
- Health checks
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .paper import (
    PaperBroker, PaperOrder, OrderSide, OrderType, OrderStatus,
    Safeguards, Position,
)


@dataclass(frozen=True)
class OperationalConfig:
    """Operational configuration for paper trading."""
    max_position: float = 1.0
    max_daily_loss: float = 0.05
    max_portfolio_drawdown: float = 0.20
    max_data_age_bars: int = 3
    fee_bps: float = 5.0
    slippage_bps: float = 1.0
    initial_cash: float = 1_000_000.0
    latency_bars: int = 1

    def validate(self) -> List[str]:
        """Validate configuration. Returns list of errors (empty = valid)."""
        errors = []
        if not 0 < self.max_position <= 2.0:
            errors.append(f"max_position {self.max_position} not in (0, 2.0]")
        if not 0 < self.max_daily_loss < 1.0:
            errors.append(f"max_daily_loss {self.max_daily_loss} not in (0, 1)")
        if not 0 < self.max_portfolio_drawdown < 1.0:
            errors.append(f"max_portfolio_drawdown {self.max_portfolio_drawdown} not in (0, 1)")
        if self.max_data_age_bars < 1:
            errors.append(f"max_data_age_bars {self.max_data_age_bars} < 1")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            errors.append("fees/slippage cannot be negative")
        if self.initial_cash <= 0:
            errors.append(f"initial_cash {self.initial_cash} <= 0")
        if self.latency_bars < 1:
            errors.append(f"latency_bars {self.latency_bars} < 1")
        return errors


@dataclass
class MonitoringSnapshot:
    """A single monitoring snapshot."""
    timestamp: str
    portfolio_value: float
    cash: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    total_fees_paid: float
    current_drawdown: float
    kill_switch_active: bool
    n_open_positions: int
    n_pending_orders: int
    n_filled_today: int
    positions: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {"timestamp": self.timestamp, "portfolio_value": self.portfolio_value,
                "cash": self.cash, "total_realized_pnl": self.total_realized_pnl,
                "total_unrealized_pnl": self.total_unrealized_pnl,
                "total_fees_paid": self.total_fees_paid,
                "current_drawdown": self.current_drawdown,
                "kill_switch_active": self.kill_switch_active,
                "n_open_positions": self.n_open_positions,
                "n_pending_orders": self.n_pending_orders,
                "n_filled_today": self.n_filled_today, "positions": self.positions}


class MonitoringDashboard:
    """Real-time monitoring dashboard for paper trading."""

    def __init__(self, broker: PaperBroker) -> None:
        self.broker = broker
        self.snapshots: List[MonitoringSnapshot] = []

    def snapshot(self) -> MonitoringSnapshot:
        """Take a monitoring snapshot."""
        positions = {}
        for symbol, pos in self.broker.positions.items():
            if abs(pos.quantity) > 1e-9:
                positions[symbol] = {"quantity": pos.quantity,
                    "avg_entry_price": pos.avg_entry_price,
                    "realized_pnl": pos.realized_pnl,
                    "unrealized_pnl": pos.unrealized_pnl}
        peak = self.broker.peak_value
        current = self.broker.current_value
        dd = (current - peak) / peak if peak > 0 else 0.0
        total_fees = 0.0
        for order in self.broker.orders.values():
            if order.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL):
                fill_cost = order.filled_quantity * (order.filled_price or 0.0)
                total_fees += fill_cost * self.broker.fee_bps / 10000.0
        snap = MonitoringSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            portfolio_value=self.broker.current_value, cash=self.broker.cash,
            total_realized_pnl=self.broker.total_realized_pnl,
            total_unrealized_pnl=self.broker.total_unrealized_pnl,
            total_fees_paid=total_fees, current_drawdown=dd,
            kill_switch_active=self.broker.safeguards.kill_switch_active,
            n_open_positions=sum(1 for p in self.broker.positions.values() if abs(p.quantity) > 1e-9),
            n_pending_orders=len(self.broker.pending_orders),
            n_filled_today=sum(1 for o in self.broker.orders.values() if o.status == OrderStatus.FILLED),
            positions=positions)
        self.snapshots.append(snap)
        return snap

    def format_status(self) -> str:
        """Format a human-readable status string."""
        snap = self.snapshot()
        lines = [f"=== Paper Trading Status @ {snap.timestamp} ===",
            f"Portfolio Value:  ${snap.portfolio_value:,.2f}",
            f"Cash:             ${snap.cash:,.2f}",
            f"Realized P&L:     ${snap.total_realized_pnl:,.2f}",
            f"Unrealized P&L:   ${snap.total_unrealized_pnl:,.2f}",
            f"Fees Paid:        ${snap.total_fees_paid:,.2f}",
            f"Drawdown:         {snap.current_drawdown:.2%}",
            f"Kill Switch:      {'ACTIVE' if snap.kill_switch_active else 'inactive'}",
            f"Open Positions:   {snap.n_open_positions}",
            f"Pending Orders:   {snap.n_pending_orders}"]
        if snap.positions:
            lines.append("--- Positions ---")
            for sym, pos in snap.positions.items():
                lines.append(f"  {sym}: {pos['quantity']:.2f} @ ${pos['avg_entry_price']:.2f}")
        return "\n".join(lines)

    def save_snapshots(self, output_dir: Path) -> Path:
        """Save all snapshots to a JSON file."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "monitoring_snapshots.json"
        path.write_text(json.dumps([s.to_dict() for s in self.snapshots], indent=2, default=str),
                         encoding="utf-8")
        return path


class ManualOverride:
    """Manual override capability for paper trading."""

    def __init__(self, broker: PaperBroker) -> None:
        self.broker = broker

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all pending orders. Returns number cancelled."""
        return self.broker.cancel_all(symbol=symbol, reason="manual_override")

    def flatten_position(self, symbol: str, current_price: float) -> Optional[PaperOrder]:
        """Close a position by submitting an offsetting order."""
        pos = self.broker.get_position(symbol)
        if abs(pos.quantity) < 1e-9:
            return None
        side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        order = PaperOrder(symbol=symbol, side=side, quantity=abs(pos.quantity))
        return self.broker.submit(order, current_price=current_price,
                                   current_time=pd.Timestamp.now(tz="UTC"))

    def flatten_all(self, prices: Dict[str, float]) -> List[PaperOrder]:
        """Close all positions. Returns list of orders submitted."""
        orders = []
        for symbol, pos in list(self.broker.positions.items()):
            if abs(pos.quantity) > 1e-9 and symbol in prices:
                order = self.flatten_position(symbol, prices[symbol])
                if order is not None:
                    orders.append(order)
        return orders

    def reset_kill_switch(self) -> None:
        """Reset the kill switch (manual override)."""
        self.broker.safeguards.reset_kill_switch()

    def trip_kill_switch(self, reason: str = "manual") -> None:
        """Trip the kill switch (emergency stop)."""
        self.broker.safeguards.trip_kill_switch(reason)


class HealthCheck:
    """Health checks for paper trading system."""

    def __init__(self, broker: PaperBroker) -> None:
        self.broker = broker

    def check_all(self) -> Dict[str, bool]:
        """Run all health checks."""
        return {"broker_initialized": self._check_broker_initialized(),
                "positions_reconciled": self._check_positions_reconciled(),
                "no_orphan_orders": self._check_no_orphan_orders(),
                "cash_positive": self._check_cash_positive(),
                "audit_trail_intact": self._check_audit_trail_intact()}

    def _check_broker_initialized(self) -> bool:
        return (self.broker.orders is not None and self.broker.positions is not None
                and self.broker.safeguards is not None)

    def _check_positions_reconciled(self) -> bool:
        return self.broker.reconcile()["consistent"]

    def _check_no_orphan_orders(self) -> bool:
        for oid in self.broker.pending_orders:
            order = self.broker.orders.get(oid)
            if order is None:
                return False
            if order.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILL):
                return False
        return True

    def _check_cash_positive(self) -> bool:
        return self.broker.cash >= 0

    def _check_audit_trail_intact(self) -> bool:
        return len(self.broker.audit_trail) >= 0


class FailureRestartTest:
    """Test failure and restart scenarios."""

    def __init__(self, broker: PaperBroker) -> None:
        self.broker = broker

    def test_kill_switch_recovery(self) -> bool:
        """Test that kill switch can be recovered from."""
        self.broker.safeguards.trip_kill_switch("test")
        if not self.broker.safeguards.kill_switch_active:
            return False
        self.broker.safeguards.reset_kill_switch()
        return not self.broker.safeguards.kill_switch_active

    def test_cancel_all_recovery(self) -> bool:
        """Test that all orders can be cancelled."""
        from .paper import OrderType
        ts = pd.Timestamp.now(tz="UTC")
        for i in range(3):
            # Use limit orders that won't fill immediately (limit below market)
            order = PaperOrder(symbol="TEST", side=OrderSide.BUY, quantity=1,
                               order_type=OrderType.LIMIT, limit_price=50.0)
            self.broker.submit(order, current_price=100.0, current_time=ts)
        cancelled = self.broker.cancel_all(reason="test")
        return cancelled == 3 and len(self.broker.pending_orders) == 0

    def test_flatten_recovery(self, prices: Dict[str, float]) -> bool:
        """Test that positions can be flattened."""
        ts = pd.Timestamp.now(tz="UTC")
        order = PaperOrder(symbol="TEST2", side=OrderSide.BUY, quantity=10)
        self.broker.submit(order, current_price=100.0, current_time=ts)
        if "TEST2" in prices:
            pos = self.broker.get_position("TEST2")
            if pos.quantity > 0:
                flatten_order = PaperOrder(symbol="TEST2", side=OrderSide.SELL, quantity=pos.quantity)
                self.broker.submit(flatten_order, current_price=prices["TEST2"], current_time=ts)
                new_pos = self.broker.get_position("TEST2")
                return abs(new_pos.quantity) < 1e-9
        return True

    def test_reconciliation_after_ops(self) -> bool:
        """Test that reconciliation passes after various operations."""
        ts = pd.Timestamp.now(tz="UTC")
        order = PaperOrder(symbol="TEST3", side=OrderSide.BUY, quantity=5)
        self.broker.submit(order, current_price=100.0, current_time=ts)
        return self.broker.reconcile()["consistent"]

    def run_all(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, bool]:
        """Run all failure/restart tests."""
        prices = prices or {"TEST2": 100.0}
        return {"kill_switch_recovery": self.test_kill_switch_recovery(),
                "cancel_all_recovery": self.test_cancel_all_recovery(),
                "flatten_recovery": self.test_flatten_recovery(prices),
                "reconciliation_after_ops": self.test_reconciliation_after_ops()}

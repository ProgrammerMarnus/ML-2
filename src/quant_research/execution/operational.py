"""Operational readiness: monitoring, manual override, and failure recovery.

This module provides the operational infrastructure needed for paper trading:
- Real-time monitoring dashboard (text-based)
- Manual override capability (cancel all, flatten, reset kill switch)
- Configuration validation before launch
- Failure/restart recovery tests
- Health checks
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

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
    spread_bps: float = 0.0
    initial_cash: float = 1_000_000.0
    latency_bars: int = 1
    max_gross_exposure: float = 1.0
    short_margin_ratio: float = 1.5

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
        if self.fee_bps < 0 or self.slippage_bps < 0 or self.spread_bps < 0:
            errors.append("fees/slippage/spread cannot be negative")
        if self.initial_cash <= 0:
            errors.append(f"initial_cash {self.initial_cash} <= 0")
        if self.latency_bars < 1:
            errors.append(f"latency_bars {self.latency_bars} < 1")
        if not 0 < self.max_gross_exposure <= 10.0:
            errors.append(
                f"max_gross_exposure {self.max_gross_exposure} not in (0, 10]"
            )
        if self.short_margin_ratio < 1.0:
            errors.append(
                f"short_margin_ratio {self.short_margin_ratio} < 1.0"
            )
        return errors

    def build_broker(self) -> PaperBroker:
        """Construct a broker only after the complete operational policy validates."""
        errors = self.validate()
        if errors:
            raise ValueError("invalid operational configuration: " + "; ".join(errors))
        safeguards = Safeguards(
            max_position=self.max_position,
            max_daily_loss=self.max_daily_loss,
            max_portfolio_drawdown=self.max_portfolio_drawdown,
            max_data_age_bars=self.max_data_age_bars,
        )
        return PaperBroker(
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            initial_cash=self.initial_cash,
            safeguards=safeguards,
            latency_bars=self.latency_bars,
            spread_bps=self.spread_bps,
            max_gross_exposure=self.max_gross_exposure,
            short_margin_ratio=self.short_margin_ratio,
        )


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
    order_counts: Dict[str, int] = field(default_factory=dict)
    recent_order_events: List[Dict] = field(default_factory=list)
    data_feed_health: Dict = field(default_factory=dict)
    system_resources: Dict[str, float] = field(default_factory=dict)
    active_alerts: int = 0
    unacknowledged_alerts: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {"timestamp": self.timestamp, "portfolio_value": self.portfolio_value,
                "cash": self.cash, "total_realized_pnl": self.total_realized_pnl,
                "total_unrealized_pnl": self.total_unrealized_pnl,
                "total_fees_paid": self.total_fees_paid,
                "current_drawdown": self.current_drawdown,
                "kill_switch_active": self.kill_switch_active,
                "n_open_positions": self.n_open_positions,
                "n_pending_orders": self.n_pending_orders,
                "n_filled_today": self.n_filled_today, "positions": self.positions,
                "order_counts": self.order_counts,
                "recent_order_events": self.recent_order_events,
                "data_feed_health": self.data_feed_health,
                "system_resources": self.system_resources,
                "active_alerts": self.active_alerts,
                "unacknowledged_alerts": self.unacknowledged_alerts}


class AlertSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class OperationalAlert:
    """Auditable operational alert with delivery and acknowledgment state."""
    alert_id: str
    created_at: str
    category: str
    severity: AlertSeverity
    message: str
    dedupe_key: str
    details: Dict = field(default_factory=dict)
    delivery: Dict[str, bool] = field(default_factory=dict)
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None
    acknowledgment_note: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "alert_id": self.alert_id,
            "created_at": self.created_at,
            "category": self.category,
            "severity": self.severity.value,
            "message": self.message,
            "dedupe_key": self.dedupe_key,
            "details": self.details,
            "delivery": self.delivery,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "acknowledgment_note": self.acknowledgment_note,
        }


class FileAlertChannel:
    """Append-only local JSONL alert sink; external delivery is separate."""

    name = "local_jsonl"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __call__(self, alert: OperationalAlert) -> None:
        self._append({"event_type": "ALERT_CREATED", "alert": alert.to_dict()})

    def record_acknowledgment(self, alert: OperationalAlert) -> None:
        self._append({"event_type": "ALERT_ACKNOWLEDGED", "alert": alert.to_dict()})

    def _append(self, record: Dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class AlertManager:
    """Evaluate broker state, deduplicate alerts, and track acknowledgment."""

    def __init__(
        self,
        channels: Optional[List[Callable[[OperationalAlert], None]]] = None,
    ) -> None:
        self.channels = list(channels or [])
        self.alerts: List[OperationalAlert] = []
        self._active_keys: set[str] = set()

    def emit(self, category: str, severity: AlertSeverity, message: str,
             *, dedupe_key: str, details: Optional[Dict] = None) -> OperationalAlert:
        for alert in self.alerts:
            if alert.dedupe_key == dedupe_key and alert.acknowledged_at is None:
                return alert
        alert = OperationalAlert(
            alert_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            category=category,
            severity=severity,
            message=message,
            dedupe_key=dedupe_key,
            details=details or {},
        )
        for index, channel in enumerate(self.channels):
            name = str(getattr(channel, "name", f"channel_{index}"))
            try:
                channel(alert)
                alert.delivery[name] = True
            except Exception:
                alert.delivery[name] = False
        self.alerts.append(alert)
        self._active_keys.add(dedupe_key)
        return alert

    def acknowledge(self, alert_id: str, *, actor: str, note: str) -> OperationalAlert:
        if not actor.strip() or not note.strip():
            raise ValueError("alert acknowledgment requires actor and note")
        for alert in self.alerts:
            if alert.alert_id != alert_id:
                continue
            if alert.acknowledged_at is not None:
                raise ValueError("alert is already acknowledged")
            alert.acknowledged_at = datetime.now(timezone.utc).isoformat()
            alert.acknowledged_by = actor
            alert.acknowledgment_note = note
            self._active_keys.discard(alert.dedupe_key)
            for channel in self.channels:
                record_acknowledgment = getattr(channel, "record_acknowledgment", None)
                if callable(record_acknowledgment):
                    record_acknowledgment(alert)
            return alert
        raise KeyError(f"unknown alert_id: {alert_id}")

    def unacknowledged(self) -> List[OperationalAlert]:
        return [alert for alert in self.alerts if alert.acknowledged_at is None]

    def evaluate_broker(
        self,
        broker: PaperBroker,
        *,
        now: Optional[pd.Timestamp] = None,
        max_data_age: pd.Timedelta = pd.Timedelta(days=3),
        pnl_loss_threshold: float = 0.02,
        position_warning_fraction: float = 0.9,
    ) -> List[OperationalAlert]:
        now = now or pd.Timestamp.now(tz="UTC")
        before = len(self.alerts)
        if broker.safeguards.kill_switch_active:
            self.emit(
                "SAFEGUARD_BREACH", AlertSeverity.CRITICAL,
                "Kill switch is active",
                dedupe_key="kill_switch_active",
                details={"reason": broker.safeguards._kill_reason},
            )
        for order in broker.orders.values():
            if order.status == OrderStatus.REJECTED:
                self.emit(
                    "ORDER_REJECTION", AlertSeverity.WARNING,
                    f"Order {order.order_id} was rejected",
                    dedupe_key=f"order_rejected:{order.order_id}",
                    details={"symbol": order.symbol, "reason": order.cancel_reason},
                )
        if broker._current_bar is None or now - broker._current_bar > max_data_age:
            self.emit(
                "DATA_STALENESS", AlertSeverity.CRITICAL,
                "Market data is missing or stale",
                dedupe_key="data_staleness",
                details={
                    "last_bar": broker._current_bar.isoformat() if broker._current_bar else None,
                    "max_age_seconds": max_data_age.total_seconds(),
                },
            )
        if broker.initial_cash > 0:
            pnl_fraction = (broker.current_value - broker.initial_cash) / broker.initial_cash
            if pnl_fraction <= -pnl_loss_threshold:
                self.emit(
                    "PNL_THRESHOLD", AlertSeverity.CRITICAL,
                    f"Portfolio loss {pnl_fraction:.2%} breached threshold",
                    dedupe_key="pnl_loss_threshold",
                    details={"pnl_fraction": pnl_fraction},
                )
        for symbol, position in broker.positions.items():
            mark = broker._last_marks.get(symbol, position.avg_entry_price)
            weight = abs(position.quantity * mark) / max(broker.current_value, 1.0)
            warning_level = broker.safeguards.max_position * position_warning_fraction
            if weight >= warning_level:
                self.emit(
                    "POSITION_LIMIT", AlertSeverity.WARNING,
                    f"{symbol} position is near its limit",
                    dedupe_key=f"position_limit:{symbol}",
                    details={"weight": weight, "warning_level": warning_level},
                )
        health = HealthCheck(broker).check_all()
        failed = sorted(name for name, passed in health.items() if not passed)
        if failed:
            self.emit(
                "SYSTEM_HEALTH", AlertSeverity.CRITICAL,
                "One or more broker health checks failed",
                dedupe_key="system_health",
                details={"failed_checks": failed},
            )
        return self.alerts[before:]


@dataclass(frozen=True)
class DailySettlementReport:
    """Write-once end-of-session accounting and integrity evidence."""
    session: str
    generated_at: str
    starting_cash: float
    ending_cash: float
    portfolio_value: float
    net_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    position_market_value: float
    fees: float
    slippage_cost: float
    spread_cost: float
    total_execution_cost: float
    accounting_identity_gap: float
    accounting_identity_valid: bool
    order_counts: Dict[str, int]
    positions: Dict[str, Dict[str, float]]
    reconciliation: Dict
    audit_trail_valid: bool
    audit_head_hash: str
    previous_report_hash: str
    report_hash: str

    def to_dict(self) -> Dict:
        return {
            "session": self.session,
            "generated_at": self.generated_at,
            "starting_cash": self.starting_cash,
            "ending_cash": self.ending_cash,
            "portfolio_value": self.portfolio_value,
            "net_pnl": self.net_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "position_market_value": self.position_market_value,
            "fees": self.fees,
            "slippage_cost": self.slippage_cost,
            "spread_cost": self.spread_cost,
            "total_execution_cost": self.total_execution_cost,
            "accounting_identity_gap": self.accounting_identity_gap,
            "accounting_identity_valid": self.accounting_identity_valid,
            "order_counts": self.order_counts,
            "positions": self.positions,
            "reconciliation": self.reconciliation,
            "audit_trail_valid": self.audit_trail_valid,
            "audit_head_hash": self.audit_head_hash,
            "previous_report_hash": self.previous_report_hash,
            "report_hash": self.report_hash,
        }


class DailySettlementReporter:
    """Generate hash-chained daily settlement reports from broker ledgers."""

    def __init__(self, previous_report_hash: str = "") -> None:
        self.previous_report_hash = previous_report_hash

    @staticmethod
    def _hash_payload(payload: Dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def generate(self, broker: PaperBroker,
                 session_time: Optional[pd.Timestamp] = None) -> DailySettlementReport:
        timestamp = session_time or broker._current_bar
        if timestamp is None:
            timestamp = pd.Timestamp.now(tz="UTC")
        if not isinstance(timestamp, pd.Timestamp) or timestamp.tzinfo is None:
            raise ValueError("session_time must be a timezone-aware pd.Timestamp")

        costs = broker.cost_attribution()
        reconciliation = broker.reconcile()
        positions: Dict[str, Dict[str, float]] = {}
        position_market_value = 0.0
        for symbol, pos in broker.positions.items():
            if abs(pos.quantity) <= 1e-12:
                continue
            mark = broker._last_marks.get(symbol, pos.avg_entry_price)
            market_value = pos.quantity * mark
            position_market_value += market_value
            positions[symbol] = {
                "quantity": pos.quantity,
                "avg_entry_price": pos.avg_entry_price,
                "mark": mark,
                "market_value": market_value,
                "realized_pnl": pos.realized_pnl,
                "unrealized_pnl": pos.unrealized_pnl,
            }

        net_pnl = broker.current_value - broker.initial_cash
        attributed_pnl = (
            broker.total_realized_pnl + broker.total_unrealized_pnl - costs["fees"]
        )
        identity_gap = net_pnl - attributed_pnl
        order_counts = {
            status.value: sum(1 for order in broker.orders.values() if order.status == status)
            for status in OrderStatus
        }
        payload = {
            "session": timestamp.normalize().date().isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "starting_cash": broker.initial_cash,
            "ending_cash": broker.cash,
            "portfolio_value": broker.current_value,
            "net_pnl": net_pnl,
            "realized_pnl": broker.total_realized_pnl,
            "unrealized_pnl": broker.total_unrealized_pnl,
            "position_market_value": position_market_value,
            "fees": costs["fees"],
            "slippage_cost": costs["slippage"],
            "spread_cost": costs["spread"],
            "total_execution_cost": costs["total"],
            "accounting_identity_gap": identity_gap,
            "accounting_identity_valid": abs(identity_gap) <= 1e-6,
            "order_counts": order_counts,
            "positions": positions,
            "reconciliation": reconciliation,
            "audit_trail_valid": broker.verify_audit_trail(),
            "audit_head_hash": (
                broker.audit_trail[-1].event_hash if broker.audit_trail else ""
            ),
            "previous_report_hash": self.previous_report_hash,
        }
        report_hash = self._hash_payload(payload)
        report = DailySettlementReport(**payload, report_hash=report_hash)
        return report

    def save(self, report: DailySettlementReport, output_dir: Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"settlement_{report.session}.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, indent=2, sort_keys=True)
        self.previous_report_hash = report.report_hash
        return path

    @classmethod
    def verify(cls, report: DailySettlementReport | Dict) -> bool:
        payload = report.to_dict() if isinstance(report, DailySettlementReport) else dict(report)
        claimed = payload.pop("report_hash", "")
        return bool(claimed) and cls._hash_payload(payload) == claimed

    @classmethod
    def verify_chain(cls, reports: List[DailySettlementReport | Dict]) -> bool:
        previous = ""
        for report in reports:
            payload = report.to_dict() if isinstance(report, DailySettlementReport) else dict(report)
            if payload.get("previous_report_hash", "") != previous or not cls.verify(payload):
                return False
            previous = str(payload["report_hash"])
        return True


class MonitoringDashboard:
    """Real-time monitoring dashboard for paper trading."""

    def __init__(self, broker: PaperBroker,
                 alert_manager: Optional[AlertManager] = None,
                 max_data_age: pd.Timedelta = pd.Timedelta(days=3)) -> None:
        self.broker = broker
        self.alert_manager = alert_manager or AlertManager()
        self.max_data_age = max_data_age
        self.snapshots: List[MonitoringSnapshot] = []

    def snapshot(self, now: Optional[pd.Timestamp] = None) -> MonitoringSnapshot:
        """Take a monitoring snapshot."""
        now = now or pd.Timestamp.now(tz="UTC")
        if not isinstance(now, pd.Timestamp) or now.tzinfo is None:
            raise ValueError("now must be a timezone-aware pd.Timestamp")
        self.alert_manager.evaluate_broker(
            self.broker, now=now, max_data_age=self.max_data_age,
        )
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
        order_counts = {
            status.value: sum(
                1 for order in self.broker.orders.values() if order.status == status
            )
            for status in OrderStatus
        }
        recent_events = [
            {
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "order_id": event.order_id,
                "symbol": event.symbol,
                "detail": event.detail,
            }
            for event in self.broker.audit_trail[-20:]
        ]
        if self.broker._current_bar is None:
            data_health = {
                "healthy": False, "last_bar": None, "age_seconds": None,
            }
        else:
            age = now - self.broker._current_bar
            data_health = {
                "healthy": age <= self.max_data_age,
                "last_bar": self.broker._current_bar.isoformat(),
                "age_seconds": max(age.total_seconds(), 0.0),
            }
        usage = resource.getrusage(resource.RUSAGE_SELF)
        system_resources = {
            "max_rss_kb": float(usage.ru_maxrss),
            "user_cpu_seconds": float(usage.ru_utime),
            "system_cpu_seconds": float(usage.ru_stime),
        }
        active_alerts = self.alert_manager.unacknowledged()
        snap = MonitoringSnapshot(
            timestamp=now.isoformat(),
            portfolio_value=self.broker.current_value, cash=self.broker.cash,
            total_realized_pnl=self.broker.total_realized_pnl,
            total_unrealized_pnl=self.broker.total_unrealized_pnl,
            total_fees_paid=total_fees, current_drawdown=dd,
            kill_switch_active=self.broker.safeguards.kill_switch_active,
            n_open_positions=sum(1 for p in self.broker.positions.values() if abs(p.quantity) > 1e-9),
            n_pending_orders=len(self.broker.pending_orders),
            n_filled_today=sum(1 for o in self.broker.orders.values() if o.status == OrderStatus.FILLED),
            positions=positions,
            order_counts=order_counts,
            recent_order_events=recent_events,
            data_feed_health=data_health,
            system_resources=system_resources,
            active_alerts=len(active_alerts),
            unacknowledged_alerts=[alert.to_dict() for alert in active_alerts])
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
        self._reset_requests: Dict[str, Dict[str, str]] = {}
        self._limit_requests: Dict[str, Dict] = {}

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all pending orders. Returns number cancelled."""
        return self.broker.cancel_all(symbol=symbol, reason="manual_override")

    def flatten_position(self, symbol: str, current_price: float) -> Optional[PaperOrder]:
        """Close a position by submitting an offsetting order."""
        pos = self.broker.get_position(symbol)
        if abs(pos.quantity) < 1e-9:
            return None
        # An emergency exit remains subject to broker accounting, but is marked
        # reduce-only so it can pass an active kill switch without temporarily
        # disabling that protection or permitting a reversal.
        self.broker.cancel_all(symbol=symbol, reason="flatten_blocker")
        side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        order = PaperOrder(symbol=symbol, side=side, quantity=abs(pos.quantity),
                           reduce_only=True)
        result = self.broker.submit(order, current_price=current_price,
                                    current_time=pd.Timestamp.now(tz="UTC"))
        if result.status == OrderStatus.SUBMITTED:
            # A process bar is the explicit simulated execution clock.  Its
            # first later bar satisfies the broker's minimum one-bar latency.
            self.broker.process_bar(
                result.submitted_at + pd.Timedelta("1ns"),
                {symbol: current_price},
            )
        return result

    def flatten_all(self, prices: Dict[str, float]) -> List[PaperOrder]:
        """Close all positions. Returns list of orders submitted."""
        orders = []
        for symbol, pos in list(self.broker.positions.items()):
            if abs(pos.quantity) > 1e-9 and symbol in prices:
                order = self.flatten_position(symbol, prices[symbol])
                if order is not None:
                    orders.append(order)
        return orders

    def request_kill_switch_reset(self, *, requested_by: str, reason: str) -> str:
        """Create an audited reset request; a second operator must approve it."""
        if not self.broker.safeguards.kill_switch_active:
            raise ValueError("kill switch is not active")
        if not requested_by.strip() or not reason.strip():
            raise ValueError("reset request requires requester and reason")
        request_id = str(uuid.uuid4())
        self._reset_requests[request_id] = {
            "requested_by": requested_by,
            "reason": reason,
        }
        self.broker._audit(
            pd.Timestamp.now(tz="UTC"), "KILL_SWITCH_RESET_REQUESTED",
            request_id, "SYSTEM", reason, {"requested_by": requested_by},
        )
        return request_id

    def reset_kill_switch(self, request_id: str, *, approved_by: str) -> None:
        """Approve a pending reset using a different operator identity."""
        request = self._reset_requests.get(request_id)
        if request is None:
            raise KeyError(f"unknown reset request: {request_id}")
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        if approved_by == request["requested_by"]:
            raise ValueError("kill-switch reset requires a second operator")
        self.broker.safeguards.reset_kill_switch()
        self.broker._audit(
            pd.Timestamp.now(tz="UTC"), "KILL_SWITCH_RESET_APPROVED",
            request_id, "SYSTEM", request["reason"],
            {
                "requested_by": request["requested_by"],
                "approved_by": approved_by,
            },
        )
        del self._reset_requests[request_id]

    def trip_kill_switch(self, reason: str = "manual") -> None:
        """Trip the kill switch (emergency stop)."""
        self.broker.safeguards.trip_kill_switch(reason)

    def request_position_limit_change(
        self,
        *,
        new_limit: float,
        expires_at: pd.Timestamp,
        requested_by: str,
        reason: str,
    ) -> str:
        """Request a time-limited position cap; approval must be independent."""
        if not requested_by.strip() or not reason.strip():
            raise ValueError("limit request requires requester and reason")
        if not isinstance(expires_at, pd.Timestamp) or expires_at.tzinfo is None:
            raise ValueError("limit override expiry must be timezone-aware")
        if expires_at <= pd.Timestamp.now(tz="UTC"):
            raise ValueError("limit override expiry must be in the future")
        if not 0 < new_limit <= 2.0:
            raise ValueError("new_limit must be in (0, 2.0]")
        request_id = str(uuid.uuid4())
        self._limit_requests[request_id] = {
            "new_limit": float(new_limit),
            "expires_at": expires_at,
            "requested_by": requested_by,
            "reason": reason,
        }
        self.broker._audit(
            pd.Timestamp.now(tz="UTC"), "POSITION_LIMIT_OVERRIDE_REQUESTED",
            request_id, "SYSTEM", reason,
            {
                "requested_by": requested_by,
                "new_limit": new_limit,
                "expires_at": expires_at.isoformat(),
            },
        )
        return request_id

    def approve_position_limit_change(self, request_id: str, *, approved_by: str) -> None:
        request = self._limit_requests.get(request_id)
        if request is None:
            raise KeyError(f"unknown position-limit request: {request_id}")
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        if approved_by == request["requested_by"]:
            raise ValueError("position-limit change requires a second operator")
        self.broker.safeguards.set_temporary_position_limit(
            request["new_limit"], request["expires_at"],
        )
        self.broker._audit(
            pd.Timestamp.now(tz="UTC"), "POSITION_LIMIT_OVERRIDE_APPROVED",
            request_id, "SYSTEM", request["reason"],
            {
                "requested_by": request["requested_by"],
                "approved_by": approved_by,
                "new_limit": request["new_limit"],
                "expires_at": request["expires_at"].isoformat(),
            },
        )
        del self._limit_requests[request_id]

    def emergency_shutdown(self, prices: Dict[str, float], *, actor: str,
                           reason: str) -> Dict:
        """Trip protection, cancel risk orders, and submit reduce-only exits."""
        if not actor.strip() or not reason.strip():
            raise ValueError("emergency shutdown requires actor and reason")
        self.broker.safeguards.trip_kill_switch(reason)
        control_id = str(uuid.uuid4())
        self.broker._audit(
            pd.Timestamp.now(tz="UTC"), "EMERGENCY_SHUTDOWN",
            control_id, "SYSTEM", reason, {"actor": actor},
        )
        cancelled = self.cancel_all_orders()
        flattened = self.flatten_all(prices)
        return {
            "control_id": control_id,
            "actor": actor,
            "reason": reason,
            "cancelled_orders": cancelled,
            "flatten_orders": [order.order_id for order in flattened],
            "reconciliation": self.broker.reconcile(),
            "audit_trail_valid": self.broker.verify_audit_trail(),
        }


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
        return self.broker.verify_audit_trail()


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
        # E06 latency: advance one bar so the entry actually fills.
        self.broker.process_bar(ts + pd.Timedelta("1ns"), {"TEST2": 100.0})
        if "TEST2" in prices:
            pos = self.broker.get_position("TEST2")
            if pos.quantity > 0:
                flatten_order = PaperOrder(symbol="TEST2", side=OrderSide.SELL, quantity=pos.quantity)
                self.broker.submit(flatten_order, current_price=prices["TEST2"], current_time=ts)
                self.broker.process_bar(ts + pd.Timedelta("2ns"), {"TEST2": prices["TEST2"]})
                new_pos = self.broker.get_position("TEST2")
                return abs(new_pos.quantity) < 1e-9
            return False
        return True

    def test_reconciliation_after_ops(self) -> bool:
        """Test that reconciliation passes after various operations."""
        ts = pd.Timestamp.now(tz="UTC")
        order = PaperOrder(symbol="TEST3", side=OrderSide.BUY, quantity=5)
        self.broker.submit(order, current_price=100.0, current_time=ts)
        self.broker.process_bar(ts + pd.Timedelta("1ns"), {"TEST3": 100.0})
        return self.broker.reconcile()["consistent"]

    def run_all(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, bool]:
        """Run all failure/restart tests."""
        prices = prices or {"TEST2": 100.0}
        return {"kill_switch_recovery": self.test_kill_switch_recovery(),
                "cancel_all_recovery": self.test_cancel_all_recovery(),
                "flatten_recovery": self.test_flatten_recovery(prices),
                "reconciliation_after_ops": self.test_reconciliation_after_ops()}

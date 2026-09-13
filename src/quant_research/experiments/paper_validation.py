"""Paper-validation framework: execute strategy against live/delayed data.

The promotion state machine defines:
    RESEARCH_ONLY -> CANDIDATE -> ROBUST_OOS -> PAPER_READY -> PAPER_VALIDATED -> LIVE_ELIGIBLE

States through ROBUST_OOS are automated by the research pipeline.  PAPER_READY and
beyond require live evidence that this platform cannot fabricate.  This module
provides the infrastructure to collect and validate that evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from ..config import AppConfig
from ..execution.paper import (
    PaperBroker, PaperOrder, OrderSide, OrderStatus, Safeguards,
)


@dataclass(frozen=True)
class PaperValidationConfig:
    """Criteria for promoting PAPER_READY -> PAPER_VALIDATED -> LIVE_ELIGIBLE."""
    min_paper_days_validated: int = 5
    min_paper_days_live_eligible: int = 60
    max_safeguard_breaches: int = 0
    max_reconciliation_failures: int = 0
    max_daily_loss_before_kill: float = 0.02
    kill_switch_must_be_tested: bool = True
    require_observed_sessions: bool = True
    require_research_binding: bool = True


@dataclass
class PaperValidationReport:
    """Evidence collected during a paper-validation run."""
    experiment_id: str
    config_fingerprint: str
    start_time: str
    strategy_id: str = ""
    evidence_source: str = "simulated_replay"
    observed_sessions: List[str] = field(default_factory=list)
    end_time: Optional[str] = None
    state: str = "PAPER_READY"
    n_days_executed: int = 0
    n_orders_submitted: int = 0
    n_orders_filled: int = 0
    n_orders_rejected: int = 0
    n_orders_cancelled: int = 0
    n_safeguard_breaches: int = 0
    kill_switch_tripped: bool = False
    kill_switch_tested: bool = False
    kill_switch_reset: bool = False
    n_reconciliation_failures: int = 0
    final_reconciliation_consistent: bool = False
    starting_cash: float = 0.0
    ending_cash: float = 0.0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_fees_paid: float = 0.0
    max_drawdown_observed: float = 0.0
    open_positions: Dict[str, float] = field(default_factory=dict)
    gate_results: Dict[str, bool] = field(default_factory=dict)
    promotion_recommendation: str = "REJECT"

    def to_dict(self) -> Dict:
        return {k: v for k, v in self.__dict__.items()}


class PaperValidationRunner:
    """Execute a strategy against live/delayed market data and collect evidence."""

    def __init__(
        self,
        cfg: AppConfig,
        validation_config: Optional[PaperValidationConfig] = None,
        broker: Optional[PaperBroker] = None,
        research_record: Optional[Dict] = None,
        strategy_id: str = "",
        evidence_source: str = "simulated_replay",
    ) -> None:
        self.cfg = cfg
        self.val_cfg = validation_config or PaperValidationConfig()
        self.broker = broker or PaperBroker(
            fee_bps=cfg.execution.fee_bps,
            slippage_bps=cfg.execution.slippage_bps,
            safeguards=Safeguards(
                max_position=cfg.execution.max_position,
                max_daily_loss=0.05,
                max_portfolio_drawdown=0.20,
            ),
        )
        self.report = PaperValidationReport(
            experiment_id=str((research_record or {}).get("experiment_id", "")),
            config_fingerprint=cfg.fingerprint(),
            start_time=datetime.now(timezone.utc).isoformat(),
            strategy_id=strategy_id,
            evidence_source=evidence_source,
            starting_cash=self.broker.initial_cash,
        )
        self._research_binding_verified = self._validate_research_record(research_record)
        self._prev_order_count = 0
        self._prev_filled_count = 0
        self._peak_value = self.broker.initial_cash
        self._max_drawdown = 0.0
        self._fees_paid = 0.0
        self._last_step_time: Optional[pd.Timestamp] = None
        self._breach_sessions: set[str] = set()
        self._reconciliation_failure_sessions: set[str] = set()

    def _validate_research_record(self, research_record: Optional[Dict]) -> bool:
        """Bind paper evidence to a compatible approved research result."""
        if not research_record:
            return False
        approved_states = {"CANDIDATE", "ROBUST_OOS", "PAPER_READY"}
        return bool(
            research_record.get("experiment_id")
            and research_record.get("config_fingerprint") == self.cfg.fingerprint()
            and research_record.get("promotion_state") in approved_states
        )

    def record_step(self, broker: PaperBroker, bar_data: Optional[Dict[str, float]] = None,
                     current_time: Optional[pd.Timestamp] = None) -> None:
        """Record one live-executed bar of paper execution.

        A step advances only for a unique UTC session backed by the broker's
        current processed bar.  Repeating a function call, a timestamp, or a
        same-day bar cannot manufacture paper-validation duration.
        """
        # E02: every step observes real breach state; breaches accumulate and
        # are never cleared by this probe.
        self._sync_ledger_counts(broker)
        if current_time is None or not isinstance(current_time, pd.Timestamp):
            return
        if current_time.tzinfo is None or not isinstance(bar_data, dict) or not bar_data:
            return
        if broker._current_bar != current_time:
            return
        if self._last_step_time is not None and current_time <= self._last_step_time:
            return
        session = current_time.normalize().isoformat()
        if session in self.report.observed_sessions:
            return
        self._last_step_time = current_time
        if broker.safeguards.kill_switch_active and not self.report.kill_switch_tripped:
            self.report.kill_switch_tripped = True
        if not broker.reconcile()["consistent"] and session not in self._reconciliation_failure_sessions:
            self.report.n_reconciliation_failures += 1
            self._reconciliation_failure_sessions.add(session)
        self.report.final_reconciliation_consistent = broker.reconcile()["consistent"]
        drawdown = (broker.current_value - self._peak_value) / self._peak_value if self._peak_value > 0 else 0.0
        if drawdown < -self.val_cfg.max_daily_loss_before_kill and session not in self._breach_sessions:
            self.report.n_safeguard_breaches += 1
            self._breach_sessions.add(session)
        if broker.safeguards.kill_switch_active and session not in self._breach_sessions:
            self.report.n_safeguard_breaches += 1
            self._breach_sessions.add(session)
        self._fees_paid = self._live_cumulative_fees(broker)
        self._track_drawdown(broker)
        self.report.observed_sessions.append(session)
        self.report.n_days_executed += 1

    def _sync_ledger_counts(self, broker: PaperBroker) -> None:
        self.report.n_orders_submitted = len(broker.orders)
        self.report.n_orders_filled = sum(1 for o in broker.orders.values() if o.status == OrderStatus.FILLED)
        self.report.n_orders_rejected = sum(1 for o in broker.orders.values() if o.status == OrderStatus.REJECTED)
        self.report.n_orders_cancelled = sum(1 for o in broker.orders.values() if o.status == OrderStatus.CANCELLED)
        self._prev_order_count = len(broker.orders)

    def _track_drawdown(self, broker: PaperBroker) -> None:
        if broker.current_value > self._peak_value:
            self._peak_value = broker.current_value
        if self._peak_value > 0:
            dd = (broker.current_value - self._peak_value) / self._peak_value
            self._max_drawdown = min(self._max_drawdown, dd)

    def _live_cumulative_fees(self, broker: PaperBroker) -> float:
        total = 0.0
        for o in broker.orders.values():
            if o.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILL):
                total += (o.filled_quantity * (o.filled_price or 0.0) * broker.fee_bps / 10000.0)
        return total

    def test_kill_switch(self) -> None:
        """Test the kill switch: trip it and reset it."""
        self.broker.safeguards.trip_kill_switch("test_kill_switch")
        self.report.kill_switch_tripped = True
        self.report.kill_switch_tested = True
        test_order = PaperOrder(symbol="TEST", side=OrderSide.BUY, quantity=1)
        result = self.broker.submit(test_order, current_price=100.0,
                                     current_time=pd.Timestamp.now(tz="UTC"))
        blocks_orders = result.status == OrderStatus.REJECTED
        self.broker.safeguards.reset_kill_switch()
        self.report.kill_switch_reset = True
        self.report.gate_results["kill_switch_blocks_orders"] = blocks_orders
        self.report.gate_results["kill_switch_resets_cleanly"] = (
            not self.broker.safeguards.kill_switch_active)

    def run_reconciliation(self) -> bool:
        """Run position reconciliation. Returns True if consistent."""
        result = self.broker.reconcile()
        if not result["consistent"]:
            self.report.n_reconciliation_failures += 1
        self.report.final_reconciliation_consistent = result["consistent"]
        return result["consistent"]

    def finalize(self, experiment_id: str = "") -> PaperValidationReport:
        """Finalize the validation report and compute gate results.

        Gates are derived from OBSERVED execution evidence, not default field
        values.  A report whose n_days_executed is zero because no real fills were
        recorded cannot pass min_execution_days; a report whose kill_switch_tested
        is False because test_kill_switch was never called cannot pass the
        kill-switch gate.  Default-true gates that discard actual test outcomes
        are not permitted.
        """
        self.report.end_time = datetime.now(timezone.utc).isoformat()
        if experiment_id:
            if self.report.experiment_id and experiment_id != self.report.experiment_id:
                raise ValueError("paper report experiment_id differs from its bound research record")
            self.report.experiment_id = experiment_id
        self.run_reconciliation()
        self.report.ending_cash = self.broker.cash
        self.report.total_realized_pnl = self.broker.total_realized_pnl
        self.report.total_unrealized_pnl = self.broker.total_unrealized_pnl
        self.report.total_fees_paid = self._fees_paid
        self.report.max_drawdown_observed = self._max_drawdown
        self.report.open_positions = {
            symbol: pos.quantity
            for symbol, pos in self.broker.positions.items()
            if abs(pos.quantity) > 1e-9
        }
        vc = self.val_cfg
        gates: Dict[str, bool] = {}
        gates["research_binding"] = (
            self._research_binding_verified or not vc.require_research_binding
        )
        gates["observed_session_evidence"] = (
            self.report.evidence_source == "observed_paper"
            or not vc.require_observed_sessions
        )
        # E01/E02: min_execution_days requires actual recorded sessions.
        gates["min_execution_days"] = self.report.n_days_executed >= vc.min_paper_days_validated
        # E02: no_safeguard_breaches reflects observed breaches accumulated during
        # record_step, not a default-zero field.
        gates["no_safeguard_breaches"] = self.report.n_safeguard_breaches <= vc.max_safeguard_breaches
        gates["reconciliation_consistent"] = (
            self.report.final_reconciliation_consistent
            and self.report.n_reconciliation_failures <= vc.max_reconciliation_failures
        )
        # E02: kill_switch_tested requires that test_kill_switch was actually
        # called AND that it both blocked orders AND reset cleanly.  A default-True
        # gate that passes without the test having been run is not permitted.
        if vc.kill_switch_must_be_tested:
            gates["kill_switch_tested"] = (
                self.report.kill_switch_tested
                and self.report.kill_switch_reset
                and self.report.gate_results.get("kill_switch_blocks_orders", False)
            )
        gates["daily_loss_controlled"] = (
            self.report.max_drawdown_observed >= -vc.max_daily_loss_before_kill
        )
        self.report.gate_results = gates
        all_passed = all(gates.values())
        if all_passed and self.report.n_days_executed >= vc.min_paper_days_live_eligible:
            self.report.promotion_recommendation = "LIVE_ELIGIBLE"
            self.report.state = "LIVE_ELIGIBLE"
        elif all_passed and self.report.n_days_executed >= vc.min_paper_days_validated:
            self.report.promotion_recommendation = "PAPER_VALIDATED"
            self.report.state = "PAPER_VALIDATED"
        else:
            self.report.promotion_recommendation = "REMAIN_PAPER_READY"
            self.report.state = "PAPER_READY"
        return self.report

    def save_report(self, output_dir: Path) -> Path:
        """Save the validation report to disk."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"paper_validation_{self.report.experiment_id}.json"
        path.write_text(json.dumps(self.report.to_dict(), indent=2, default=str),
                         encoding="utf-8")
        return path

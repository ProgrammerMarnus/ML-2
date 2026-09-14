"""Regression coverage for paper-execution and validation safety controls."""

from __future__ import annotations

import pandas as pd
import pytest

from quant_research.config import load_config
from quant_research.execution.paper import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperBroker,
    PaperOrder,
    Safeguards,
)
from quant_research.experiments.paper_validation import (
    PaperValidationConfig,
    PaperValidationRunner,
)


def _ts(day: int) -> pd.Timestamp:
    return pd.Timestamp(f"2024-01-{day:02d}", tz="UTC")


def test_market_order_waits_for_every_configured_latency_bar():
    broker = PaperBroker(initial_cash=10_000, fee_bps=0.0, slippage_bps=0.0,
                         latency_bars=3)
    order = PaperOrder("SPY", OrderSide.BUY, 1)
    broker.submit(order, 100.0, _ts(2))

    broker.process_bar(_ts(3), {"SPY": 100.0})
    assert order.status == OrderStatus.SUBMITTED
    broker.process_bar(_ts(4), {"SPY": 100.0})
    assert order.status == OrderStatus.SUBMITTED
    broker.process_bar(_ts(5), {"SPY": 100.0})
    assert order.status == OrderStatus.FILLED
    assert order.filled_at == _ts(5)


def test_pending_buys_reserve_cash_across_symbols():
    broker = PaperBroker(initial_cash=1_000, fee_bps=0.0, slippage_bps=0.0)
    first = PaperOrder("SPY", OrderSide.BUY, 8, OrderType.LIMIT, limit_price=100.0)
    second = PaperOrder("QQQ", OrderSide.BUY, 8, OrderType.LIMIT, limit_price=100.0)

    assert broker.submit(first, 100.0, _ts(2)).status == OrderStatus.SUBMITTED
    assert broker.submit(second, 100.0, _ts(2)).status == OrderStatus.REJECTED
    assert len(broker.pending_orders) == 1


def test_fill_rechecks_cash_at_the_executable_price():
    broker = PaperBroker(initial_cash=1_000, fee_bps=0.0, slippage_bps=0.0)
    order = PaperOrder("SPY", OrderSide.BUY, 10)
    assert broker.submit(order, 99.0, _ts(2)).status == OrderStatus.SUBMITTED

    broker.process_bar(_ts(3), {"SPY": 110.0})
    assert order.status == OrderStatus.CANCELLED
    assert broker.cash == 1_000
    assert broker.get_position("SPY").quantity == 0


def test_kill_switch_allows_only_reduce_only_exit_orders():
    broker = PaperBroker(initial_cash=10_000, fee_bps=0.0, slippage_bps=0.0)
    entry = PaperOrder("SPY", OrderSide.BUY, 5)
    broker.submit(entry, 100.0, _ts(2))
    broker.process_bar(_ts(3), {"SPY": 100.0})
    assert broker.get_position("SPY").quantity == 5

    broker.safeguards.trip_kill_switch("test")
    blocked = PaperOrder("SPY", OrderSide.BUY, 1)
    assert broker.submit(blocked, 100.0, _ts(4)).status == OrderStatus.REJECTED

    exit_order = PaperOrder("SPY", OrderSide.SELL, 5, reduce_only=True)
    assert broker.submit(exit_order, 100.0, _ts(4)).status == OrderStatus.SUBMITTED
    broker.process_bar(_ts(5), {"SPY": 100.0})
    assert exit_order.status == OrderStatus.FILLED
    assert broker.get_position("SPY").quantity == 0
    assert broker.safeguards.kill_switch_active


def test_conflicting_retry_cannot_reuse_an_existing_order_id():
    broker = PaperBroker(fee_bps=0.0, slippage_bps=0.0)
    original = PaperOrder("SPY", OrderSide.BUY, 1, order_id="fixed-id")
    broker.submit(original, 100.0, _ts(2))

    with pytest.raises(ValueError, match="different request"):
        broker.submit(PaperOrder("SPY", OrderSide.BUY, 2, order_id="fixed-id"),
                      100.0, _ts(2))

    assert broker.get_order("fixed-id") is original


def test_validation_counts_unique_processed_sessions_and_requires_research_binding():
    cfg = load_config("configs/baseline.yaml")
    validation = PaperValidationConfig(
        min_paper_days_validated=1,
        min_paper_days_live_eligible=2,
        kill_switch_must_be_tested=False,
    )
    runner = PaperValidationRunner(
        cfg, validation_config=validation, evidence_source="observed_paper"
    )
    stamp = _ts(2)
    runner.broker.process_bar(stamp, {"SPY": 100.0})
    runner.record_step(runner.broker, {"SPY": 100.0}, current_time=stamp)
    runner.record_step(runner.broker, {"SPY": 100.0}, current_time=stamp)

    report = runner.finalize()
    assert report.n_days_executed == 1
    assert report.observed_sessions == [stamp.normalize().isoformat()]
    assert not report.gate_results["research_binding"]
    assert report.state == "PAPER_READY"


def test_validation_counts_only_official_exchange_sessions():
    cfg = load_config("configs/baseline.yaml")
    validation = PaperValidationConfig(
        min_paper_days_validated=1,
        kill_switch_must_be_tested=False,
        require_observed_sessions=False,
        require_research_binding=False,
    )
    runner = PaperValidationRunner(cfg, validation_config=validation)
    # 2024-01-01 is an XNYS holiday and 2024-01-06 is a Saturday.
    for stamp in (
        pd.Timestamp("2024-01-01", tz="UTC"),
        pd.Timestamp("2024-01-06", tz="UTC"),
        pd.Timestamp("2024-01-08", tz="UTC"),
    ):
        runner.broker.process_bar(stamp, {"SPY": 100.0})
        runner.record_step(runner.broker, {"SPY": 100.0}, current_time=stamp)

    report = runner.finalize()
    assert report.n_days_executed == 1
    assert report.observed_sessions == ["2024-01-08T00:00:00+00:00"]
    assert report.gate_results["min_execution_days"]


def test_breach_during_submission_is_durable_validation_failure():
    cfg = load_config("configs/baseline.yaml")
    validation = PaperValidationConfig(
        min_paper_days_validated=1,
        max_safeguard_breaches=0,
        kill_switch_must_be_tested=False,
        require_observed_sessions=False,
        require_research_binding=False,
    )
    runner = PaperValidationRunner(cfg, validation_config=validation)
    # Set the live observation without pre-tripping: submit() must discover
    # the loss, trip the switch, and reject the order atomically.
    runner.broker.daily_return = -0.10
    order = PaperOrder("SPY", OrderSide.BUY, 1)
    assert runner.broker.submit(order, 100.0, _ts(2)).status == OrderStatus.REJECTED
    assert runner.broker.safeguards.kill_switch_active
    runner.broker.process_bar(_ts(3), {"SPY": 100.0})
    runner.record_step(runner.broker, {"SPY": 100.0}, current_time=_ts(3))

    report = runner.finalize()
    assert report.n_safeguard_breaches == 1
    assert not report.gate_results["no_safeguard_breaches"]
    assert report.state == "PAPER_READY"


def test_kill_switch_cancels_resting_risk_order_before_fill():
    broker = PaperBroker(initial_cash=10_000, fee_bps=0.0, slippage_bps=0.0)
    order = PaperOrder(
        "SPY", OrderSide.BUY, 5, OrderType.LIMIT, limit_price=99.0,
    )
    assert broker.submit(order, 100.0, _ts(2)).status == OrderStatus.SUBMITTED
    broker.safeguards.trip_kill_switch("intrabar breach")

    filled = broker.process_bar(_ts(3), {"SPY": 98.0})
    assert filled == []
    assert order.status == OrderStatus.CANCELLED
    assert order.cancel_reason == "kill_switch_active"
    assert broker.pending_orders == []
    assert broker.get_position("SPY").quantity == 0
    assert any(
        event.event_type == "ORDER_CANCELLED"
        and event.order_id == order.order_id
        and "kill_switch_active" in event.detail
        for event in broker.audit_trail
    )


def test_reduce_only_liquidation_bypasses_an_existing_position_breach():
    safeguards = Safeguards(max_position=0.05)
    broker = PaperBroker(
        initial_cash=10_000, fee_bps=0.0, slippage_bps=0.0,
        safeguards=safeguards,
    )
    entry = PaperOrder("SPY", OrderSide.BUY, 5)
    assert broker.submit(entry, 100.0, _ts(2)).status == OrderStatus.SUBMITTED
    broker.process_bar(_ts(3), {"SPY": 100.0})
    # The mark doubles after entry, putting the existing position above its
    # weight limit. The safety system must still permit flattening.
    broker.process_bar(_ts(4), {"SPY": 200.0})
    exit_order = PaperOrder("SPY", OrderSide.SELL, 5, reduce_only=True)
    assert broker.submit(exit_order, 200.0, _ts(4)).status == OrderStatus.SUBMITTED
    broker.process_bar(_ts(5), {"SPY": 200.0})
    assert exit_order.status == OrderStatus.FILLED
    assert broker.get_position("SPY").quantity == 0


def test_simultaneous_pending_orders_cannot_bypass_position_limit():
    safeguards = Safeguards(max_position=0.10)
    broker = PaperBroker(
        initial_cash=1_000, fee_bps=0.0, slippage_bps=0.0,
        safeguards=safeguards,
    )
    first = PaperOrder("SPY", OrderSide.BUY, 0.6, OrderType.LIMIT, limit_price=100.0)
    second = PaperOrder("SPY", OrderSide.BUY, 0.6, OrderType.LIMIT, limit_price=100.0)
    assert broker.submit(first, 100.0, _ts(2)).status == OrderStatus.SUBMITTED
    assert broker.submit(second, 100.0, _ts(2)).status == OrderStatus.REJECTED
    assert len(broker.pending_orders) == 1
    assert "position_limit" in (second.cancel_reason or "")


def test_identical_order_id_retry_executes_exactly_once():
    broker = PaperBroker(initial_cash=10_000, fee_bps=0.0, slippage_bps=0.0)
    original = PaperOrder("SPY", OrderSide.BUY, 5, order_id="idempotent-order")
    retry = PaperOrder("SPY", OrderSide.BUY, 5, order_id="idempotent-order")
    assert broker.submit(original, 100.0, _ts(2)) is original
    assert broker.submit(retry, 100.0, _ts(2)) is original
    assert broker.pending_orders == ["idempotent-order"]

    broker.process_bar(_ts(3), {"SPY": 100.0})
    assert broker.get_position("SPY").quantity == 5
    assert broker.cash == pytest.approx(9_500.0)
    assert len(original.fill_events) == 1
    assert sum(
        event.event_type == "ORDER_FILLED" and event.order_id == original.order_id
        for event in broker.audit_trail
    ) == 1


def test_broker_state_restores_pending_order_and_verifies_audit_chain(tmp_path):
    broker = PaperBroker(initial_cash=10_000, fee_bps=0.0, slippage_bps=0.0,
                         latency_bars=2)
    order = PaperOrder("SPY", OrderSide.BUY, 1)
    broker.submit(order, 100.0, _ts(2))
    broker.process_bar(_ts(3), {"SPY": 100.0})
    assert order.status == OrderStatus.SUBMITTED

    path = broker.save_state(tmp_path / "broker-state.json")
    resumed = PaperBroker.load_state(path)
    resumed.process_bar(_ts(4), {"SPY": 100.0})
    assert resumed.get_order(order.order_id).status == OrderStatus.FILLED
    assert resumed.reconcile()["consistent"]
    assert resumed.verify_audit_trail()


def test_broker_state_rejects_a_tampered_audit_trail(tmp_path):
    broker = PaperBroker(fee_bps=0.0, slippage_bps=0.0)
    broker.submit(PaperOrder("SPY", OrderSide.BUY, 1), 100.0, _ts(2))
    path = broker.save_state(tmp_path / "broker-state.json")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("ORDER_SUBMITTED", "ORDER_MUTATED", 1), encoding="utf-8")

    with pytest.raises(ValueError, match="audit"):
        PaperBroker.load_state(path)


def test_cancelled_order_state_survives_verified_restart(tmp_path):
    broker = PaperBroker(initial_cash=10_000, fee_bps=0.0, slippage_bps=0.0)
    order = PaperOrder(
        "SPY", OrderSide.BUY, 1, OrderType.LIMIT, limit_price=90.0,
    )
    broker.submit(order, 100.0, _ts(2))
    assert broker.cancel_order(order.order_id, reason="recovery-test")

    resumed = PaperBroker.load_state(broker.save_state(tmp_path / "cancelled-state.json"))
    restored = resumed.get_order(order.order_id)
    assert restored is not None
    assert restored.status == OrderStatus.CANCELLED
    assert restored.cancel_reason == "recovery-test"
    assert resumed.pending_orders == []
    assert resumed.verify_audit_trail()


def test_end_to_end_kill_cancel_flatten_restart_reconciles(tmp_path):
    broker = PaperBroker(initial_cash=100_000, fee_bps=1.0, slippage_bps=1.0)
    entry = PaperOrder("SPY", OrderSide.BUY, 10)
    broker.submit(entry, 100.0, _ts(2))
    broker.process_bar(_ts(3), {"SPY": 100.0})
    resting = PaperOrder(
        "QQQ", OrderSide.BUY, 5, OrderType.LIMIT, limit_price=190.0,
    )
    broker.submit(resting, 200.0, _ts(3))
    broker.safeguards.trip_kill_switch("e2e-emergency")
    broker.process_bar(_ts(4), {"SPY": 99.0, "QQQ": 180.0})
    assert resting.status == OrderStatus.CANCELLED

    flatten = PaperOrder("SPY", OrderSide.SELL, 10, reduce_only=True)
    broker.submit(flatten, 99.0, _ts(4))
    broker.process_bar(_ts(5), {"SPY": 99.0})
    assert flatten.status == OrderStatus.FILLED
    assert broker.get_position("SPY").quantity == 0

    resumed = PaperBroker.load_state(broker.save_state(tmp_path / "e2e-state.json"))
    assert resumed.safeguards.kill_switch_active
    assert resumed.reconcile()["consistent"]
    assert resumed.verify_audit_trail()


def test_batch_order_load_preserves_execution_ledger():
    broker = PaperBroker(
        initial_cash=10_000_000, fee_bps=0.0, slippage_bps=0.0,
    )
    orders = [
        PaperOrder(f"SYM{i:03d}", OrderSide.BUY, 1, order_id=f"load-{i:03d}")
        for i in range(250)
    ]
    prices = {order.symbol: 100.0 + (i % 10) for i, order in enumerate(orders)}
    for order in orders:
        assert broker.submit(order, prices[order.symbol], _ts(2)).status == OrderStatus.SUBMITTED
    filled = broker.process_bar(_ts(3), prices)

    assert len(filled) == 250
    assert broker.pending_orders == []
    assert all(order.status == OrderStatus.FILLED for order in orders)
    assert broker.reconcile()["consistent"]
    assert broker.verify_audit_trail()

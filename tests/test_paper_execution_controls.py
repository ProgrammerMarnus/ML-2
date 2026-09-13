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

# Current Project Status

**As of:** 2026-09-15
**Overall state:** `RESEARCH_ONLY` — no viable strategy and no live-broker
adapter.

This is the canonical status page. Dated audits, trial logs, closure reports,
and archived artifacts preserve what was known when they were written; their
historical metrics and findings are not current readiness claims.

## Strategy research

- `pv-2.2.0` is closed and failed.
- H-001 was implemented with its corrected nine-feature, selected-SPY/QQQ
  contract and run on real data. Its 2010–2020 candidate label was superseded
  because that run's feature placebo kept the selected leg fixed.
- The frozen 2021–2026 H-001 confirmation used the corrected full-strategy
  placebo and failed: net Sharpe 0.7873, placebo percentile 0.35, adjusted
  p-value 0.667. H-001 is rejected.
- H-002 was formally revised into the new family **H-002-R1** (its original
  contract was unobtainable), frozen, and executed once on real 2010–2023 daily
  data across 285 names. It is **rejected**: gross Sharpe −0.342 (no edge before
  costs), 0 of 10 positive OOS folds, net Sharpe −2.656, annual turnover 72×
  against a 6× cap. Trial budget retired; the 2010–2023 window is spent.
- The original H-002 remains unexecuted and blocked on point-in-time Russell 3000
  membership, market-cap, classified intraday trade, VIX, cross-sectional
  portfolio, and capacity contracts. The amendment did not discharge this.
- H-003 is blocked before trial execution because VIX-futures M1–M3,
  17-ETF correlation, weekly risk-parity, and crisis/diversification contracts
  are absent.
- H-003 was formally amended into the separate **H-003-R1** daily-data family,
  protocol-frozen, and executed once on 2008–2023 data across 17 ETFs plus VIX
  spot. It is **rejected**: gross Sharpe 0.375, net Sharpe −0.074, 2 of 5
  positive OOS folds, 7.42× annual turnover against a 2× cap, $6.76m capacity
  against $500m, and 10 of 14 mandate gates failed. Budget retired.
- The runtime rejects original H-002/H-003 scalar daily-OHLCV proxy runs. The
  explicit `h002` and `h003` modes route only to their separately frozen R1
  portfolio contracts; neither is evidence for the original hypothesis.

## Engineering and validation

- All ten P1 findings E01–E10 from the 2026-09-11 audit are fixed and covered
  by behavioral regressions.
- The latest complete suite run collected 399 tests and exited successfully
  with no failure or teardown error. It includes the new execution-accounting
  and operational-control regressions.
- PaperBroker hardening 4.1 is complete: lifecycle, latency, cash/exposure
  reservations, idempotency, reduce-only emergency exits, kill-switch pending
  cancellation, verified persistence, reconciliation, audit-chain validation,
  an end-to-end emergency flow, and a 250-order batch test are covered.
- The paper-validation framework enforces unique exchange sessions,
  research-record/evidence-source binding, breach and reconciliation gates,
  and structured reports. No observed paper sessions have been accepted.
- Local execution accounting now includes per-fill fee/slippage/spread
  attribution, portfolio gross-exposure and short-margin checks, cash-inclusive
  reconciliation, and write-once hash-chained daily settlement reports.
- Local operational controls include order/data/resource monitoring, deduplicated
  alerts with acknowledgment evidence, a two-person kill-switch reset, and an
  audited emergency shutdown. Temporary position-cap changes require independent
  approval, expire automatically, and restore the baseline limit. External
  alert delivery, authenticated operator identity/roles, real feeds, named
  operators, and observed-paper evidence remain open.
- This local evidence does not establish an external CI result.
- A least-privilege GitHub Actions workflow is configured to run the full suite
  on Python 3.13 and retain JUnit evidence. It has not yet produced a hosted run
  for this working tree.

## Remaining blockers

1. Produce a genuinely new preregistered research family or obtain the exact
   external contracts for original H-002/H-003. Both R1 amendments were
   executed and rejected; neither original hypothesis has been tested.
2. Produce a strategy that achieves every `ROBUST_OOS` gate on untouched
   evidence.
3. Complete remaining paper/order-flow accounting and operational work in the
   live-readiness checklist.
4. Select and implement a real broker adapter; none exists today.
5. Accumulate the required observed paper sessions only after a strategy is
   research-qualified.

See `LIVE_TRADING_READINESS_CHECKLIST.txt` for the detailed work queue,
`PHASE1_DATA_CONTRACT_GAP_MATRIX.md` for research blockers, and
`TEST_SUITE_REMEDIATION_REPORT.md` for test evidence.

# Current Project Status

**As of:** 2026-09-14  
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
- H-002 is blocked before trial execution because point-in-time Russell 3000
  membership, market-cap, classified intraday trade, VIX, cross-sectional
  portfolio, and capacity contracts are absent.
- H-003 is blocked before trial execution because VIX-futures M1–M3,
  17-ETF correlation, weekly risk-parity, and crisis/diversification contracts
  are absent.
- The runtime rejects H-002/H-003 scalar daily-OHLCV proxy runs so they cannot
  be recorded as preregistered evidence.

## Engineering and validation

- All ten P1 findings E01–E10 from the 2026-09-11 audit are fixed and covered
  by behavioral regressions.
- The latest complete suite run collected 360 tests and exited successfully
  with no failure or teardown error. Three subsequent PaperBroker tests also
  pass; the repository now collects 363 tests.
- PaperBroker hardening 4.1 is complete: lifecycle, latency, cash/exposure
  reservations, idempotency, reduce-only emergency exits, kill-switch pending
  cancellation, verified persistence, reconciliation, audit-chain validation,
  an end-to-end emergency flow, and a 250-order batch test are covered.
- This local evidence does not establish an external CI result.

## Remaining blockers

1. Obtain and approve the exact point-in-time data/evaluation contract for
   H-002 or H-003, or preregister a new research family.
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

# Current Project Status

**As of:** 2026-09-15 (late evening) — after both protocol-bound H-005 engine
executions reached `CANDIDATE` and exhausted the 10/10 selection budget.
**Overall state:** `RESEARCH_ONLY` for promotion purposes — **H-005 is the first
family with engine-protocol evidence passing every one of its frozen gates
(`CANDIDATE`)**; it is not yet `ROBUST_OOS` because its evaluated window is not
untouched (see the H-005 row below). No live-broker adapter exists.

This is the canonical status page. Dated audits, trial logs, closure reports,
and archived artifacts preserve what was known when they were written; their
historical metrics and findings are not current readiness claims.

## Repository state

- Single branch: local `main` contains the H-005 engine work beginning at
  `af7cdb0` plus this second-execution evidence and is ahead of `origin/main`.
  GitHub PRs #1–#5 are all merged, and every working/backup branch (local and
  remote) has been deleted.
- The AI Studio Build app (front-end + Express backend) was exported to ZIP and
  imported onto `main`; see [docs/DASHBOARD.md](docs/DASHBOARD.md). The export
  was verified file-by-file to be a snapshot of the pre-merge `origin/main`
  plus app-side work only, so no engine code was clobbered.

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

### Newly preregistered families (not yet validly executed)

The preregistration ledger `data/research_ledgers/preregistrations.jsonl`
(authoritative; served by the dashboard at `/api/preregistrations`) now also
contains five newer families:

| Family | Title (per frozen ledger) | State |
|---|---|---|
| H-005 | Overnight-Intraday Return Decomposition | **`CANDIDATE`** — both protocol-bound engine executions passed all 14 frozen gates. Execution 1: `20260915T160008Z_283db198b22dc6aa`, net Sharpe 0.997, placebo percentile 1.0, adjusted p 0.0476. Execution 2: `20260915T171435Z_8ab87aaf928a91ec`, net Sharpe 1.116, placebo percentile 0.95, adjusted p 0.0952. Both have bootstrap P(SR>0) 0.994 and clean cost/delay, leakage, and integrity gates. Not `ROBUST_OOS`: both reused the already-inspected 2010–2021 window; mean AUC remained near random (0.505/0.501). The cumulative 10/10 fold-level selection budget is spent. See `H005_TRIAL_SUMMARY.md`. |
| H-006 | Factor Exposure Mean Reversion | 5 features registered, config frozen. **Execution blocked**: the scalar walk-forward evaluates one target series, while H-006 needs a cross-sectional (multi-asset panel, weekly ranking/rebalance) evaluator. See `H006_FINAL_STATUS_REPORT.md` — note its engine path reference and feature counts are stale; the blocker itself is accurate. |
| H-004 | Macro Yield Curve & Credit Spread Momentum | Ledger-only preregistration: no hypothesis document, feature module, config, or engine path yet. Requires macro (yield-curve/credit-spread) data. |
| H-007 | Cross-Sectional Quality-Minus-Junk Low-Turnover Core | Ledger-only preregistration; needs fundamentals data plus the cross-sectional evaluator. |
| H-008 | Microstructure Order Flow Imbalance & Intraday Liquidity Replenishment | Ledger-only preregistration; needs intraday order-flow/microstructure data that the repository does not have. |

Note: some AI Studio-generated documents call H-004 "Sector Rotation with
Volatility Regime Filtering"; the frozen ledger title above is authoritative.

## Engineering and validation

- All ten P1 findings E01–E10 from the 2026-09-11 audit are fixed and covered
  by behavioral regressions.
- The latest complete suite run (`pytest -o addopts= -q -p no:cacheprovider`,
  2026-09-15 evening, 20:04 wall time) collected **410 tests** and passed all of
  them — exit 0 with no failures, skips, or teardown errors. (The older "451
  collected" figure is not reproducible from this tree; 410 is the verified
  count.) New coverage includes the H-005 feature-panel wiring contract
  (VIX-present via both `VIX` and `^VIX` symbols, and VIX-absent) and the
  H-006 feature tests.
- The feature registry holds **95 specs across 8 sources** (price_volume 21,
  volatility_risk_premium 21, liquidity_reversal 13, overnight_intraday 13,
  cross_asset_spillover 9, information 8, h003_r1_volatility_shock 5,
  factor_mean_reversion 5). `registry_hash` now serialises specs without empty
  optional metadata, so audited pre-existing pins (e.g. `momentum_63`) are
  byte-stable while H-006 tags its specs with `hypothesis`.
- Tracked `__pycache__/*.pyc` bytecode was removed from the index (84 files):
  it was CPython 3.12 output, is regenerated locally, and had caused every
  binary merge conflict. `.gitignore` was rewritten — the blanket
  `*.csv/*.json/*.parquet` rules are gone (replaced by scoped `artifacts/`,
  `artifacts_*/`, `data_cache/`, `logs/` rules) so new research files are no
  longer silently ignored; already-tracked artifacts remain tracked.
- The full-stack dashboard (Express backend `server.ts` + eight new React
  panels) runs locally via `npm run server`; see
  [docs/DASHBOARD.md](docs/DASHBOARD.md). It reads the repository's real
  ledgers but creates no promotion evidence.
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

1. H-005 has no trial budget left and still lacks untouched evidence. Do not
   rerun it. Any confirmation on 2022–2026 must be authorized and frozen as a
   separate confirmation family/protocol before data are read; until then it
   remains `CANDIDATE`, not `ROBUST_OOS`.
2. Implement the cross-sectional (panel + weekly portfolio) evaluator; it
   unblocks H-006 and is prerequisite for H-007-style strategies.
3. Implement or formally close the ledger-only preregistrations H-004, H-007,
   and H-008 (H-008 needs intraday order-flow data; H-004 needs macro
   yield-curve/credit-spread data; H-007 needs fundamentals).
4. Commit the remaining untracked H-002 input (`data/universe_russell3000.csv`)
   — `src/quant_research/data/h002_sectors.json` was committed in `66e5c04`,
   but `h002_universe.py` requires both.
5. Reconcile the authoritative preregistration ledger: H-005 and H-006 have
   frozen contracts/protocols but are absent from
   `data/research_ledgers/preregistrations.jsonl` (`/api/preregistrations`).
   Append them or correct the docs that claim they are present.
6. Complete remaining paper/order-flow accounting and operational work in the
   live-readiness checklist; select and implement a real broker adapter;
   accumulate observed paper sessions only after a strategy is
   research-qualified.

See `LIVE_TRADING_READINESS_CHECKLIST.txt` for the detailed work queue,
`PHASE1_DATA_CONTRACT_GAP_MATRIX.md` for research blockers,
[docs/DASHBOARD.md](docs/DASHBOARD.md) for the full-stack dashboard, and
`TEST_SUITE_REMEDIATION_REPORT.md` for test evidence.

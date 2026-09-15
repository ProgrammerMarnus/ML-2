# Phase 1 Data and Evaluation Contract Gap Matrix

**Status:** H-001 is rejected after confirmation. H-002 has been formally revised
into a new family (H-002-R1), executed once on real data, and **rejected**;
the original H-002 contract remains unexecuted. H-003 has likewise been amended
into H-003-R1, executed once, and rejected; original H-003 remains unexecuted.
H-005 is a budget-spent candidate; H-006's panel path is implemented and the
family is rejected after valid Trial 1. The remaining
H-004/H-007/H-008 are ledger-only preregistrations.

| Hypothesis | Preregistered requirement | Present repository capability | Required before a new protocol can be approved |
|---|---|---|---|
| H-002 Liquidity Reversal | Point-in-time monthly Russell 3000 membership; daily adjusted OHLCV; market capitalisation; intraday buys/sells classified at the midpoint; VIX; daily cross-sectional, equal-weight dollar-neutral long/short portfolio | Single-target daily OHLCV panel. The feature module uses return-signed volume as a proxy; no membership, market-cap, classified-trade, sector, or cross-sectional portfolio path exists. | Licensed or otherwise approved PIT data source and retention policy; normalized membership, market-cap, intraday-trade and VIX schemas; Lee-Ready-or-equivalent classification specification; universe filters; sector-neutral, dollar-neutral portfolio and capacity evaluator; locked 2010–2023 fold schedule with 126-session gaps. |
| H-002-R1 Liquidity Reversal (amended) | **RESOLVED — no longer blocked.** Contract restricted to repository-sourceable data: static universe snapshot, yfinance daily OHLCV, proxy LIM, 5-of-7 composite terms, contiguous 252-session folds. Frozen in `artifacts/h002_r1/h002_r1_protocol.json`. | Implemented: `configs/h002_real_universe.yaml`, `h002_pipeline.py`, `portfolio/h002_portfolio.py`, `portfolio/h002_returns.py`. | **None. Executed and REJECTED** (0/10 positive folds; gross Sharpe −0.342; net −2.656). Trial budget retired, window spent. See `HYPOTHESIS_H002_R1_LIQUIDITY_REVERSAL_AMENDED.md`. |
| H-003 Volatility Risk Premium | Daily OHLCV for 17 named ETFs; VIX futures M1–M3 term structure; 20-day pairwise correlations; weekly risk-parity allocation with 0.5 leverage; 2008–2023 folds separated by one year | Scalar target daily OHLCV panel. The feature module can compute realised-volatility proxies and optional VIX/VXN spot features, but has no VIX-futures curve, correlation panel, risk-parity allocator, weekly portfolio ledger, or crisis/correlation gates. | Approved VIX-futures continuous-contract methodology and data source; normalized 17-ETF/VIX-futures data contract; correlation and risk-parity implementation; weekly rebalance and 0.5x leverage evaluator; explicit crisis-alpha and diversification gates; locked 2008–2023 fold schedule with 252-session gaps. |
| H-003-R1 Daily Volatility-Shock Allocation (amended) | **RESOLVED — no longer blocked.** Frozen five-term daily-data signal over 17 ETFs; VIX spot stand-down; Wednesday signed inverse-vol portfolio; 0.5 gross/10% vol caps; contiguous 504-session OOS folds; portfolio-native cost, delay, placebo, crisis, capacity, and diversification gates. | Implemented in `h003_pipeline.py`, `portfolio/h003_portfolio.py`, and `configs/h003_r1_daily_volatility.yaml`; immutable protocol `artifacts/h003_r1/h003_r1_protocol.json`. | **None. Executed and REJECTED:** net OOS Sharpe −0.074, 2/5 positive folds, turnover 7.42x, capacity $6.76m, 10/14 mandate gates failed. Trial budget retired. See `H003_R1_RESULTS.md`. |
| H-005 Overnight-Intraday Return Decomposition | Daily OHLCV **including opens** for SPY/QQQ/IWM/EFA/EEM/TLT/GLD plus ^VIX, 2010–2021; 13 overnight/intraday features; 7-fold expanding walk-forward (1260/252/252, purge/embargo 5). | **EXECUTED TWICE (CANDIDATE).** `features/overnight_intraday.py`, engine feature-panel branch (accepts `^VIX`), `configs/h005_overnight_intraday_trial*.yaml`, frozen protocols `artifacts/h005_trial{1,2}/h005_protocol.json`. Experiments `20260915T160008Z_283db198b22dc6aa` and `20260915T171435Z_8ab87aaf928a91ec` each passed all 14 frozen gates. | **No implementation gap for the inspected window, but 10/10 selections are spent without untouched evidence. Any 2022–2026 confirmation needs a separately authorized and frozen family/protocol; H-005 remains below `ROBUST_OOS`.** |
| H-006 Factor Exposure Mean Reversion | 17-ETF cross-sectional weekly mean-reversion portfolio: 5 immutable features, Wednesday rebalance, gross ≤ 1.0, net ±40%. | **Implemented and executed:** `h006_pipeline.py`, `portfolio/h006_portfolio.py`, frozen snapshot replay, five complete locked OOS folds, and portfolio-native robustness/placebo/risk gates. | **None. Executed and REJECTED:** net Sharpe -0.073, 2/5 positive folds, turnover 15.21x, capacity $19.99m, 13 gates failed. Remaining budget retired. |
| H-004 Macro Yield Curve & Credit Spread Momentum | Macro yield-curve and credit-spread momentum data (per frozen ledger entry). | Ledger-only: no hypothesis document, feature module, config, or engine path. | Decide the macro data source and contract, or close the preregistration. |
| H-007 Cross-Sectional Quality-Minus-Junk Low-Turnover Core | Cross-sectional quality/fundamentals factor with low-turnover core allocation. | Ledger-only; reusable panel infrastructure exists, but there is no fundamentals input or H-007 contract implementation. | Decide the fundamentals data source, or close the preregistration. |
| H-008 Microstructure Order Flow Imbalance | Intraday order-flow imbalance and liquidity-replenishment microstructure data. | Ledger-only; no intraday data or engine path. | Decide the order-flow data source and contract, or close the preregistration. |

## Enforcement

`run_research_pipeline` rejects `liquidity_reversal` and
`volatility_risk_premium` feature sources on the default scalar path. This
prevents the proxy YAML files from creating experiment records that could be
mistaken for preregistered H-002/H-003 evidence. The feature modules remain
usable in isolated tests; the refusal applies only to research execution.

The refusal has explicit portfolio routes: `data.mode == "h002"` for H-002-R1,
`data.mode == "h003"` for H-003-R1, and `data.mode == "h006"` for H-006. Each uses its own
portfolio evaluator and frozen protocol/config binding. Neither route relaxes
the refusal for the original hypothesis feature source on the scalar engine.

## Decision status

H-002-R1 and H-003-R1 are **closed** by amendment, single baseline execution,
and rejection. Original H-002 and H-003 remain untested and blocked on their
respective external data contracts.

Revising a hypothesis into a new family does **not** discharge the original
contract. Original H-002 remains untested; if its mechanism is to be evaluated,
it still requires licensed PIT membership, market-cap, and midpoint-classified
trade data.

# Phase 1 Data and Evaluation Contract Gap Matrix

**Status:** H-001 is rejected after confirmation. H-002 and H-003 are blocked
before any trial can consume research budget.

| Hypothesis | Preregistered requirement | Present repository capability | Required before a new protocol can be approved |
|---|---|---|---|
| H-002 Liquidity Reversal | Point-in-time monthly Russell 3000 membership; daily adjusted OHLCV; market capitalisation; intraday buys/sells classified at the midpoint; VIX; daily cross-sectional, equal-weight dollar-neutral long/short portfolio | Single-target daily OHLCV panel. The feature module uses return-signed volume as a proxy; no membership, market-cap, classified-trade, sector, or cross-sectional portfolio path exists. | Licensed or otherwise approved PIT data source and retention policy; normalized membership, market-cap, intraday-trade and VIX schemas; Lee-Ready-or-equivalent classification specification; universe filters; sector-neutral, dollar-neutral portfolio and capacity evaluator; locked 2010–2023 fold schedule with 126-session gaps. |
| H-003 Volatility Risk Premium | Daily OHLCV for 17 named ETFs; VIX futures M1–M3 term structure; 20-day pairwise correlations; weekly risk-parity allocation with 0.5 leverage; 2008–2023 folds separated by one year | Scalar target daily OHLCV panel. The feature module can compute realised-volatility proxies and optional VIX/VXN spot features, but has no VIX-futures curve, correlation panel, risk-parity allocator, weekly portfolio ledger, or crisis/correlation gates. | Approved VIX-futures continuous-contract methodology and data source; normalized 17-ETF/VIX-futures data contract; correlation and risk-parity implementation; weekly rebalance and 0.5x leverage evaluator; explicit crisis-alpha and diversification gates; locked 2008–2023 fold schedule with 252-session gaps. |

## Enforcement

`run_research_pipeline` now rejects `liquidity_reversal` and
`volatility_risk_premium` feature sources. This prevents the existing proxy
YAML files from creating experiment records that could be mistaken for
preregistered H-002/H-003 evidence. The feature modules remain usable in
isolated tests; the refusal applies only to research execution.

## Decision required

Select an approved data source and implementation path for one hypothesis, or
formally retire/revise that hypothesis into a new research family. Either
choice requires a new immutable protocol and review before any real-data test
window is unlocked.

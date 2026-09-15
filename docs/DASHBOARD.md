# Research Dashboard (AI Studio full-stack app)

**Imported:** 2026-09-15 from the AI Studio Build app
(`2e4b70e4-2015-4d50-b515-c4cfe530f5d5`) via ZIP export. The export was
verified to be a snapshot of the pre-merge `origin/main` plus app-side work
only, so no Python engine code was changed by the import.

## Running it

```bash
npm install          # once; adds express, tsx, react-markdown on top of the UI deps
npm run server       # full-stack: API + UI with Vite middleware on http://0.0.0.0:3000
npm run server:prod  # NODE_ENV=production: serves the built dist/ instead
npm run dev          # UI only (API calls fall back to canned offline data)
```

`server.ts` (Express 5) is the backend; in development it embeds Vite's
middleware so the API and the React UI share port 3000. In production it
serves `dist/`.

## What the backend exposes

| Area | Endpoints |
|---|---|
| Health | `GET /api/health` |
| Trial accounting | `GET /api/trial-counter` — scans the repository's real `artifacts/**/trial_counter.json` ledgers and reports the live count, high-water mark, and invariant flag |
| Registries | `GET /api/registry` (search + confirmation ledger), `GET /api/audits`, `GET /api/audits/:filename` |
| Preregistrations | `GET /api/preregistrations`, `POST /api/preregistration` — backed by `data/research_ledgers/preregistrations.jsonl` |
| Leakage | `POST /api/preflight-leakage-scan` |
| Safeguards | `GET /api/safeguards`, `POST /api/safeguards` (runtime state in `data/research_ledgers/safeguards.json`) |
| Alerts | `POST /api/alerts/dispatch`, `GET /api/alerts/history` |
| Operators | `GET /api/operators/actions`, `POST /api/operators/sign-off` |
| Broker gateway | `GET /api/broker/gateway-status` |
| Market (simulated) | `GET /api/market/stream`, `GET /api/market/snapshot`, `POST /api/market/order`, `GET /api/market/orders`, `POST /api/market/orders/flatten` |
| Risk daemon | `GET /api/risk/daemon-status`, `POST /api/risk/trip-breaker` |
| Compliance | `GET /api/compliance/verify-checksums`, `GET /api/compliance/regulatory-checklist` |

**Important:** the broker, market, and operator endpoints are dashboard
simulations backed by in-memory state and the local ledgers. They are **not**
live-broker connectivity and cannot create `PAPER_READY`/`LIVE_ELIGIBLE`
evidence. The overall promotion state remains `RESEARCH_ONLY`.

## Front-end

`src/App.tsx` mounts the existing tabs plus eight panels added by the import:
`InstitutionalTearSheetGenerator`, `LiveExecutionConsole`,
`OperationalIntegrationPanel`, `PlaceboNullVisualizer`,
`PreflightLeakageScanner`, `PreregistrationModal`,
`RegulatoryComplianceHub`, and `SafeguardsPanel`. All API access goes through
`src/utils/apiService.ts`, which degrades to offline fallback data when the
backend is unreachable (clearly logged in the console).

## Import provenance and conventions

- The export tree was a snapshot of `origin/main` (`0baaad3`) plus app-side
  work; every Python/test/ledger file in it was byte-identical to
  `origin/main`, so the engine, tests, and PR #4/#5 content were untouched.
- Deliberately **not** imported: the export's `index.html` (it references
  `/index.tsx` and `/index.css`, which exist neither in the export nor here —
  this repo's entry point is `src/main.tsx`), its `tsconfig.json` (drops
  `strict`), its `.gitignore`, `bun.lock`, and `.env.local` (placeholder key;
  gitignored).
- `package.json` keeps this repo's dependency set and adds only what the new
  code needs: `express@^5`, `@types/express`, `@types/node`, `tsx`, and
  `react-markdown@^10.1.0`.

## AI Studio round-trip procedure

AI Studio's *Save to GitHub* is broken upstream (it can only create its own
new repository and currently fails with permission errors). The reliable
round-trip is: **Build → Apps → app → "Download App" (ZIP) → extract → diff
against this repository → port the deltas**:

```bash
diff -rq --exclude=node_modules --exclude=.git --exclude=__pycache__ \
  /home/marnus/VS-Code/ML-2 ~/Downloads/<extracted-app> | grep -v artifacts
```

Review each `differ`/`Only in` line before copying anything; the engine
(`src/quant_research/**`) should normally stay authoritative on the Git side.
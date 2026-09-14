# Paper Operations Runbook

**Version:** 1.0  
**Reviewed:** 2026-09-14  
**Scope:** Local paper simulator and future observed-paper integration only  
**Current authorization:** `RESEARCH_ONLY`; no live orders

This runbook defines the minimum operating sequence around `PaperBroker`. It
does not authorize paper-market or live execution. Named operators, alert
destinations, provider credentials, and escalation contacts must be approved
before an observed-paper session starts.

## Roles

- **Primary operator:** runs checks, monitors the session, and records events.
- **Approving operator:** independently approves kill-switch resets and limit
  changes; must not be the requester.
- **Research owner:** confirms the bound experiment remains research-qualified.
- **Incident owner:** coordinates response and decides whether a session may
  resume.

Names and reachable contact details are deployment-specific and remain open.
The local controls compare and audit supplied operator identifiers; they do not
authenticate those identities against an external identity provider. External
authentication and role assignment are required before observed paper use.

## Pre-session checklist

1. Confirm the strategy record, configuration fingerprint, and evidence source
   match the approved paper-validation record.
2. Run `OperationalConfig.validate()` and stop on any error.
3. Load broker state through `PaperBroker.load_state()`; stop if audit-chain or
   reconciliation verification fails.
4. Confirm the kill switch is inactive and there is no unapproved reset.
5. Reconcile cash, positions, pending orders, and the previous settlement hash.
6. Confirm the primary and redundant market feeds are connected, current, and
   using the expected exchange calendar. This step cannot pass with the current
   repository alone because no real feed is integrated.
7. Confirm alert delivery and operator acknowledgment using the approved
   external channels. The repository currently supplies local JSONL and
   pluggable channel interfaces only.
8. Record the session start and operator identities.

## Intraday monitoring

- Review position, cash, gross exposure, margin, P&L, drawdown, pending-order,
  data-age, system-resource, and alert snapshots.
- Acknowledge each alert with an operator identity and investigation note.
- Stop risk-increasing flow on stale data, reconciliation failure, corrupt
  audit evidence, breached limits, unexpected orders/fills, or feed divergence.
- Never reset the kill switch without a request and independent second-operator
  approval.
- Temporary position-cap changes require an independent approver and a UTC
  expiry; expiration automatically restores the configured baseline.
- Do not change strategy parameters or research gates during a session.

## Emergency shutdown

1. Call the audited emergency-shutdown control with operator and reason.
2. Verify the kill switch is active.
3. Verify risk-increasing pending orders were cancelled.
4. Submit only reduce-only exits using current validated marks.
5. Reconcile fills, positions, and cash; do not conceal residual positions.
6. Preserve broker state, alerts, audit trail, and settlement evidence.
7. Escalate to the incident owner. Resumption requires root-cause review and an
   independently approved reset.

## Post-session reconciliation

1. Process the final validated marks and stop accepting new orders.
2. Run cash-and-position reconciliation and audit-chain verification.
3. Generate the write-once daily settlement report.
4. Verify P&L identity, fee/slippage/spread attribution, report digest, and the
   previous-report hash.
5. Compare against provider/broker statements when an external adapter exists.
6. Record unresolved discrepancies as critical alerts and keep the next session
   blocked.

## Incident response

| Severity | Examples | Immediate action | Resume authority |
|---|---|---|---|
| Critical | Reconciliation failure, corrupt state, unknown fill, stale feed, limit breach | Kill, cancel risk orders, flatten if marks are valid, preserve evidence | Incident owner plus independent operator |
| Warning | Rejection spike, position near limit, delivery-channel failure | Stop affected flow, investigate, acknowledge | Primary operator after documented resolution |
| Informational | Expected session transition or completed settlement | Record and monitor | Primary operator |

No incident may be resolved by deleting or rewriting broker state, alert logs,
settlement reports, or research evidence.

## Escalation matrix to complete before observed paper

| Role | Primary | Backup | Contact channel | Status |
|---|---|---|---|---|
| Primary operator | Unassigned | Unassigned | Unconfigured | Open |
| Approving operator | Unassigned | Unassigned | Unconfigured | Open |
| Research owner | Unassigned | Unassigned | Unconfigured | Open |
| Incident owner | Unassigned | Unassigned | Unconfigured | Open |
| Broker/data provider | Not selected | Not selected | Unconfigured | Open |

## Training acceptance

Each primary and backup operator must demonstrate, in a non-live environment:

- configuration and startup validation;
- alert acknowledgment and evidence retention;
- cancel-all and reduce-only flattening;
- two-person kill-switch reset;
- restart from verified persisted state;
- settlement generation and hash-chain verification;
- response to stale data, reconciliation failure, and unexpected fills.

Training is not complete until identities, dates, scenario results, and reviewer
sign-off are attached to an observed-paper readiness record.

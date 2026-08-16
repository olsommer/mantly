# Production alert runbooks

Status: **Operator runbook**

Use UTC timestamps and stable request/ticket/run/delivery/provider identifiers.
Do not paste customer message bodies, credentials, or unredacted provider
responses into incident notes.

For suspected tenant isolation, unauthorized access/action, secret exposure,
malware/RCE, destructive/financial duplicate, or data loss, declare a security
incident and follow `docs/security/incident-response.md` immediately.

## 1. API unavailable or not ready

### Trigger

- `/api/health` fails or cannot connect;
- `/api/ready` returns 503 beyond threshold;
- sustained critical 5xx or latency.

### Immediate actions

1. Confirm scope: one route, one instance, or complete service.
2. Record deploy commit/image, restart time, request/correlation IDs, and first
   observed failure.
3. Check the detailed component state from the protected operator path.
4. Inspect redacted application, Caddy, PocketBase, host disk/memory, and recent
   deployment/migration events.
5. Stop automatic actions/outbound delivery when readiness failure could produce
   partial or duplicate effects.
6. Roll back only to a previously verified image when the current deployment
   caused the failure.

### Diagnose

- `application.startup` failed: inspect bootstrap, migration, license, secret, and
  provider configuration.
- `migration.projects` failed: keep readiness degraded; do not manually alter
  production schema without backup and reviewed procedure.
- PocketBase unavailable: inspect internal network, credentials, volume, disk,
  SQLite locking/integrity, and container health.
- Scheduler component failed/stale: use the relevant queue/sync runbook below.
- High latency without failures: inspect resource saturation, provider latency,
  large uploads/context, queue contention, and storage size.

### Recovery

- verify `/api/ready` and a synthetic authenticated read;
- verify tenant isolation and one safe synthetic ticket path;
- reconcile actions/deliveries that were in claimed or unknown state;
- record customer impact and communicate according to contract;
- create follow-up work for the root cause and detection gap.

## 2. Inbound channel stale or failing

### Trigger

- `support.sync` failed or stale;
- channel cursor/last-success exceeds two expected intervals;
- webhook signature/authentication failures spike;
- oldest unprocessed event exceeds target.

### Immediate actions

1. Identify tenant/project/channel and last successful cursor/event.
2. Pause only the affected channel automation if duplicate/reordered processing is possible.
3. Verify provider availability, credential validity/scopes, webhook signature
   secret, callback URL, rate limits, and network/DNS.
4. Inspect deduplication/replay records before manually replaying events.
5. Tell the operational owner to monitor the source mailbox/channel directly.

### Recovery

- restore or rotate credentials through the approved procedure;
- resume from the durable cursor/checkpoint, not an guessed timestamp;
- process a bounded batch and verify created/updated/skipped/duplicate counts;
- ensure no duplicate ticket or side effect was produced;
- clear the alert only after at least two successful intervals or provider events.

## 3. Outbound queue stuck, failing, or unknown

### Trigger

- `support.delivery` failed/stale;
- oldest queued item exceeds threshold;
- failure/blocked rate exceeds threshold;
- delivery remains claimed too long;
- provider outcome is unknown;
- duplicate-send/fencing conflict.

### Immediate actions

1. Pause automatic outbound delivery for the affected scope when duplicate or
   wrong-recipient risk exists.
2. Identify queue item, ticket, immutable content/version, claim/fencing state,
   idempotency key, attempts, and provider request ID.
3. Determine provider-side truth: not attempted, failed before acceptance,
   accepted/sent, delivered, duplicated, or unknown.
4. Do **not** reset and replay an unknown outcome blindly.
5. Route customer handling manually where the SLA requires a response.

### Recovery

- retry only a provably safe item;
- reconcile sent/delivered status from provider evidence;
- move exhausted/unknown items to explicit manual recovery/dead-letter state;
- compensate or contact the customer for a duplicate/incorrect response;
- verify queue age, claim expiry, retry count, and two successful scheduler runs;
- declare an incident for unauthorized, cross-tenant, or duplicate irreversible action.

## 4. Model/provider failure or cost anomaly

### Trigger

- model/provider error rate or latency exceeds threshold;
- rate limit/quota exhaustion;
- token/cost spike;
- invalid schema/safety/policy output spike;
- all configured providers unavailable.

### Immediate actions

1. Identify tenant, runbook/version, provider/model, error category, token/cost,
   and request correlation without copying prompt/content.
2. Disable automatic paths that depend on unreliable output; preserve manual or
   deterministic fallback.
3. Check provider status, account/quota, credentials, region, model deprecation,
   timeout/retry configuration, and recent prompt/context changes.
4. Enforce per-tenant budgets and stop recursive/retry cost amplification.
5. If switching provider/model, confirm the customer-approved data and region
   boundary before sending content.

### Recovery

- validate deterministic fixture/evaluation cases;
- run a small assisted-only batch;
- review safety/quality sampling before restoring autonomy;
- document cost cause and update budget/alert thresholds;
- treat suspected provider data exposure or credential compromise as an incident.

## 5. Tool/action execution failure or unknown side effect

### Trigger

- repeated action failure;
- unknown provider result;
- partial success;
- approval/permission/schema failure;
- duplicate side effect blocked or completed.

### Immediate actions

1. Pause the affected runbook/tool.
2. Preserve ticket, runbook/version, action ID, inputs reference, approval,
   idempotency/claim/fence, provider request/response reference, and before-state.
3. Query provider-side truth using a read-only operation.
4. Do not rerun the whole ticket.
5. Contact the customer operational owner for financial, destructive,
   customer-visible, or irreversible state.

### Recovery

- retry only when idempotency and previous outcome prove safety;
- use documented compensation/reversal where supported;
- route the ticket to manual recovery;
- add a regression test for the exact partial/unknown path;
- republish/re-enable the runbook only after review and approval.

## 6. Scheduler heartbeat stale

### Trigger

An enabled `support.sync`, `support.delivery`, `support.crm_sync`, or `support.sla`
heartbeat exceeds its stale-after threshold.

### Immediate actions

1. Check whether the API process restarted or the scheduler was intentionally disabled.
2. Verify configured interval/project scope and whether the in-process thread exists.
3. Check last success/failure, duration, counts, and redacted error.
4. Check blocking provider calls, unhandled deadlock/resource exhaustion, and host clock.
5. If the job can create side effects, do not start a second copy until lease/claim
   safety is understood.

### Recovery

- restart one supported API instance when the thread died;
- fix provider/configuration failure;
- verify durable cursor/queue state and bounded catch-up;
- ensure at least two successful intervals;
- open a scaling/reliability issue when correctness depends on an in-process
  thread or manual restart.

## 7. Disk/storage pressure or SQLite integrity risk

### Trigger

- free disk below warning/critical threshold;
- database/attachment growth anomaly;
- SQLite lock, I/O, corruption, or integrity error;
- backup cannot stage due to space.

### Immediate actions

1. Stop nonessential ingestion/extraction and automatic side effects before disk exhaustion.
2. Identify database, attachment, log, temporary, backup staging, and Docker growth.
3. Do not delete database, attachment, audit, or backup files ad hoc.
4. Preserve a consistent encrypted backup when storage health allows.
5. Declare an incident for corruption/data loss.

### Recovery

- expand storage or safely remove approved expired logs/backups/temp artifacts;
- run integrity and restore verification in isolation;
- restore from the latest verified backup when required;
- reconcile events after the restore point and replay valid deletions;
- update capacity triggers and retention automation.

## 8. Backup stale or failed

### Trigger

- newest successful encrypted backup older than 24 hours;
- two consecutive backup failures;
- component hash/encryption/off-host transfer failure.

### Immediate actions

1. Check the backup job log, destination access, age recipient, disk space,
   Docker mounts, and whether services restarted after failure.
2. Confirm no partial/unencrypted bundle was uploaded.
3. Run one controlled retry only after fixing the cause.
4. Escalate before 36 hours or the contractual RPO boundary.

### Recovery

- create and transfer a fresh encrypted bundle;
- verify checksum and inventory/expiry;
- schedule an immediate restore drill if integrity or completeness was uncertain;
- declare an incident if no backup inside the accepted RPO can be restored.

## 9. Restore drill overdue or failed

### Trigger

- no passed drill before pilot;
- quarterly drill overdue;
- restore hash, SQLite, service, collection, fixture, attachment, or deletion replay fails;
- actual RTO exceeds target.

### Immediate actions

1. Keep the restored target isolated.
2. Preserve bundle, manifest, hashes, logs, verification JSON, commit/image, and
   operator timeline.
3. Do not overwrite the same target repeatedly without diagnosis.
4. Test an earlier verified backup only after recording the failure.
5. Block new customer rollout and material migration until recovery is credible.

### Recovery

- fix backup completeness, restore tooling, configuration inventory, schema, or
  deletion replay;
- rerun the full drill with independent verification;
- update RPO/RTO or architecture honestly when the target cannot be met.

## 10. Critical quality or safety outcome

### Trigger

Any critical pilot review result, tenant disclosure, unauthorized action,
duplicate irreversible side effect, fabricated material policy/fact delivered,
or missing trace for a material autonomous decision.

### Immediate actions

1. Pause the affected runbook and equivalent action path.
2. Protect the customer and correct/reverse the outcome where possible.
3. Declare a security incident when confidentiality, authorization, integrity, or
   destructive/financial action is involved.
4. Preserve complete decision/action/delivery evidence.
5. Expand review to the same runbook/version and failure pattern.

### Recovery

- identify deterministic root cause and contributing conditions;
- add regression/evaluation cases;
- strengthen policy, permission, retrieval, approval, or idempotency controls;
- re-review and republish a new runbook version;
- restore autonomy gradually after explicit customer/engineering/security approval;
- report the event in pilot evidence and do not reclassify it away.

## 11. Closure record

For every warning requiring intervention or any critical alert, record:

- alert and incident ID;
- start/detection/containment/recovery times;
- affected tenant/project/runbook/provider;
- customer impact and communications;
- request/ticket/run/action/delivery identifiers;
- root cause and contributing factors;
- remediation and regression evidence;
- monitoring/runbook change;
- approvers and residual risk.

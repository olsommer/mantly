# Production observability

Status: **Required for production-like customer processing**

Owner: On-call operations owner with engineering component owners

Mantly must make customer-impacting failures visible before an operator discovers
them through a complaint. Telemetry is operational evidence, not a copy of
customer support content.

## 1. Objectives

The observability system must answer:

- Is the API live and ready to receive production traffic?
- Is PocketBase/storage available and within the supported capacity boundary?
- Are inbound messages being ingested without replay, duplicate, or cursor lag?
- Are runbooks, model calls, and external actions succeeding within policy?
- Is outbound delivery moving, retrying safely, or stuck?
- Are scheduled jobs running at the configured cadence?
- Are customer-visible latency, error, cost, and automation quality within the
  pilot target?
- Is the newest backup inside the RPO and has a restore drill passed?
- Can one ticket be followed from source message to final delivery and recovery?

## 2. Runtime endpoints

| Endpoint | Access | Purpose |
| --- | --- | --- |
| `GET /api/health` | Public/load balancer | Liveness plus a compact readiness flag; returns HTTP 200 while the process can answer. |
| `GET /api/ready` | Deployment platform/operator | HTTP 200 when startup and enabled component heartbeats are healthy; HTTP 503 when degraded. |
| `GET /api/internal/observability` | Protected by `X-Observability-Token` | Redacted component states, request counts, error rate, normalized route counts, durations, and recent slow requests. Disabled with HTTP 404 when `OBSERVABILITY_TOKEN` is unset. |

The detailed endpoint must never be exposed through an unprotected public
dashboard. The observability token is a production secret and must be rotated
after suspected exposure.

## 3. Request correlation

Every request receives:

- `X-Request-ID`: one request/attempt;
- `X-Correlation-ID`: a wider operation, ticket, delivery, or provider flow.

Safe caller-supplied identifiers are preserved; unsafe characters and excessive
length are removed. Responses echo both identifiers. Structured logs include the
active context automatically.

For asynchronous work, carry stable identifiers in durable records:

- tenant/project ID;
- ticket/message ID;
- runbook/version;
- AI run/action execution ID;
- outbound/delivery-run ID;
- provider request/event ID;
- idempotency and claim/fencing identifiers where safe to expose internally.

Do not use message subject/body, customer email, or attachment filename as a
correlation identifier.

## 4. Structured and redacted logs

Production default:

```env
LOG_FORMAT=json
LOG_LEVEL=INFO
LOG_REDACT_EMAILS=true
OBSERVABILITY_SLOW_REQUEST_MS=2000
OBSERVABILITY_TOKEN=<unique-secret>
```

Use `LOG_FORMAT=text` only for local interactive operation.

The formatter recursively redacts fields whose names resemble passwords, tokens,
credentials, API keys, cookies, authorization headers, private keys, JWTs, SMTP
passwords, or webhook secrets. It also removes bearer tokens and common inline
key/value secrets and redacts email local parts by default.

Never log by default:

- message or attachment bodies;
- complete prompts/model responses;
- access/reset/license keys;
- provider credentials or request authorization;
- customer exports or incident evidence;
- payment details;
- full external tool responses.

Log identifiers, categories, provider/request IDs, counts, durations, sizes,
status transitions, and redacted error classes. Debug content logging requires an
incident-specific approval, restricted destination, short expiry, and deletion.

## 5. Component heartbeat contract

Each enabled recurring or critical component exposes:

- enabled/disabled state and reason;
- `running`, `ok`, `idle`, `deferred`, `failed`, or equivalent status;
- start, last success, and last failure timestamps;
- last duration;
- consecutive and total failures;
- stale-after threshold;
- privacy-safe result counts/details;
- redacted latest error.

Current in-process components include:

- `application.startup`;
- `migration.projects`;
- `support.sync`;
- `support.delivery`;
- `support.delivery.record`;
- `support.crm_sync`;
- `support.sla`.

An enabled scheduler is stale after roughly three configured intervals (with a
minimum grace window). A failed or stale enabled component makes `/api/ready`
degraded. Disabled schedulers do not.

When an external cron/worker replaces an in-process scheduler, it must publish an
equivalent durable heartbeat. Do not report a job healthy only because the API
process is running.

## 6. Required signals

### API and storage

- request rate, duration, 4xx/5xx counts, normalized routes;
- process restart/startup failure;
- readiness failure and duration;
- PocketBase request latency/error/timeout;
- SQLite/storage size, free disk, integrity/locking errors;
- migration/bootstrap result;
- attachment processing size/error/queue.

### Inbound channels

- last successful sync/webhook time per project/channel;
- cursor age and oldest unprocessed event;
- events/messages received, created, updated, skipped, duplicated, replay blocked;
- signature/authentication failures;
- provider rate limit or credential failure;
- attachment extraction/quarantine failures.

### Runbooks, AI, and tools

- matched/no-match/blocked/failed counts by runbook version;
- model/provider/model identity, latency, token usage, variable cost, timeout,
  rate limit, invalid output, policy/safety block;
- action attempts, approvals, success, failure, unknown result, duplicate blocked,
  compensation/manual recovery;
- unsafe/materially incorrect review outcomes and pause state;
- runbook publication/evaluation failures.

### Outbound delivery

- queue depth and oldest queued age;
- claimed items and claim age;
- sent/delivered/failed/blocked/deferred counts;
- retry attempts and exhaustion;
- provider unknown outcomes;
- duplicate send prevention/fencing conflicts;
- dead-letter/manual reconciliation age.

### Business/pilot quality

- eligible volume and exclusions;
- verified autonomous, assisted, manual, and failed automation;
- match precision/coverage;
- first-response/resolution distributions;
- cost per ticket and provider spend;
- customer correction/manual recovery;
- KPI target pass/fail.

### Recovery and security

- newest successful encrypted backup age and expiry;
- backup failure and component hash/integrity result;
- last successful restore drill and actual RPO/RTO;
- authentication/authorization anomalies;
- rate-limit and secret/configuration scan failures;
- incident/runbook pause and unresolved high/critical risk.

## 7. Alert thresholds

Start with these pilot thresholds and tune only from measured load. A customer
contract can require stricter values.

| Signal | Warning | Critical |
| --- | --- | --- |
| API readiness | degraded for 2 minutes | degraded for 5 minutes or all requests unavailable |
| API 5xx rate | >2% for 10 minutes with at least 20 requests | >5% for 5 minutes or a critical route repeatedly fails |
| p95 request latency | >2 seconds for 15 minutes | >5 seconds for 10 minutes |
| Inbound sync heartbeat | >2 expected intervals stale | >3 intervals stale or oldest event exceeds customer response target |
| Outbound queue age | oldest >5 minutes | oldest >15 minutes or customer SLA threshold |
| Delivery failures | >2% over 15 minutes | duplicate/unknown irreversible result or >10% over 10 minutes |
| Model/provider errors | >5% over 15 minutes | >20% over 5 minutes or all providers unavailable |
| Tool/action failure | repeated same tool failure | unauthorized, duplicate, financial/destructive unknown result |
| Scheduler heartbeat | >2 intervals stale | >3 intervals stale |
| Disk | <20% or <10 GiB free | <10% or <5 GiB free |
| Backup freshness | >24 hours | >36 hours or two consecutive failures |
| Restore drill | due within 14 days | overdue or latest drill failed |
| Critical quality/security outcome | n/a | any critical outcome immediately |

Avoid alerts based only on one low-volume event unless it represents tenant
isolation, unauthorized action, secret exposure, duplicate irreversible side
effect, data loss, or another critical boundary.

## 8. Dashboards

Minimum production views:

1. **Service overview:** liveness/readiness, request rate/errors/latency,
   PocketBase/storage, deploy commit/image, active incidents.
2. **Support flow:** inbound lag, eligible ticket volume, runbook/no-match,
   action/approval, outbound queue/delivery, SLA breaches.
3. **Provider health and cost:** model/channel/tool provider latency, error, rate
   limit, tokens/cost, circuit-breaker state.
4. **Safety and quality:** match precision, unsafe/major/critical outcomes,
   customer corrections, manual recovery, paused runbooks.
5. **Recovery/security:** backup age, restore drill, auth anomalies, secret/
   dependency/config scans, unresolved accepted risks.

Dashboards must support tenant/project/runbook filtering without exposing another
tenant's content to tenant users.

## 9. Alert ownership and runbooks

Every alert has:

- severity and customer impact;
- primary and backup owner;
- diagnostic links/query;
- immediate containment/disable action;
- customer communication trigger;
- linked procedure in `alert-runbooks.md` or the security incident runbook;
- resolution and post-incident criteria.

An alert that no one can act on is removed or redesigned. A missing critical
signal remains a production-readiness issue.

## 10. Data retention and provider boundary

Apply `docs/security/data-retention.md` to logs, metrics, traces, and incident
evidence. If an external observability/model tracing provider is enabled, record
it in the deployment provider inventory with region, support access, content
capture, retention, deletion, and incident terms.

Content/model tracing is disabled by default. The ordinary detailed endpoint and
logs are designed to operate without message bodies or secrets.

## 11. Pre-pilot acceptance

- [ ] JSON logging and email/secret redaction tests pass.
- [ ] Request/correlation headers are visible through a complete synthetic ticket flow.
- [ ] `/api/health` and `/api/ready` are wired to the deployment platform.
- [ ] Detailed observability endpoint is disabled publicly and works with the secret token from the operator network.
- [ ] Every enabled scheduler exposes heartbeat and last success/failure.
- [ ] Inbound lag, outbound queue age, provider failure, backup age, and critical safety outcomes have alerts.
- [ ] Highest-severity alerts link to tested runbooks.
- [ ] Dashboard permissions and tenant filters are reviewed.
- [ ] Logs and traces contain no synthetic secrets/message bodies in the test exercise.
- [ ] On-call contact, escalation, and customer communication paths are current.

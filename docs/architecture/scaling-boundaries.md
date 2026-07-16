# Scaling boundaries and evolution triggers

Status: **Current production architecture contract**

Owner: Architecture and operations owners

This document states what the current release supports, what is only a controlled
pilot admission limit, and what must change before broader production use. It
does not infer capacity from feature completeness or a successful health check.

## 1. Supported topology

The current release supports exactly:

- one FastAPI application process/replica;
- one PocketBase process using its SQLite store;
- one writable PocketBase data volume;
- one writable `/app/data` volume;
- zero or one in-process instance of each configured support scheduler;
- one controlled deployment region/host failure domain;
- externally managed TLS, DNS, provider accounts, and encrypted off-host backup.

Runtime variables:

```env
MANTLY_API_REPLICAS=1
MANTLY_STORAGE_MODE=pocketbase-sqlite
MANTLY_WORKER_MODE=in-process
MANTLY_LOCAL_APPLICATION_DATA=true
MANTLY_INSTANCE_ID=<stable-instance-name>
```

`backend/sitecustomize.py` validates this topology before the Python process
runs. Multiple replicas or an unimplemented storage/worker mode stop startup.
This is deliberate: silently accepting an unsupported topology could create
multiple SQLite writers, duplicate schedulers, duplicate external actions, or
inconsistent local files.

The current topology is recoverable through encrypted backup and restore. It is
not highly available and does not provide point-in-time recovery, automatic
failover, or zero-data-loss guarantees.

## 2. Background-process inventory

| Process | Current implementation | Durable state | Multi-instance status |
| --- | --- | --- | --- |
| Channel/email sync | Optional thread in API process | Provider cursor, events/messages in PocketBase | **Single instance only** until external worker and lease/fencing are proven |
| Outbound delivery | Optional thread in API process | Queue, attempts, delivery runs, claim/fence records | Claims are tested, but scheduler duplication is not an approved deployment topology |
| CRM/external sync | Optional thread in API process | Connector/sync records | **Single instance only** |
| SLA escalation | Optional thread in API process | Ticket/SLA/events | **Single instance only** |
| Model/runbook execution | Request/task path and durable run/action records | AI runs, action executions, audit | Concurrency must remain bounded; no distributed queue contract yet |
| Backup | Host operator job | Encrypted off-host bundle | One backup writer; services stopped for consistent SQLite snapshot |
| Retention/deletion | Operator/customer procedure | Primary/derived/provider and deletion replay evidence | No distributed deletion coordinator yet |

No correctness decision may depend only on in-memory thread state. Durable
records remain the source of truth, but this does not by itself make the current
scheduler topology horizontally safe.

## 3. Conservative pilot admission envelope

These are **admission controls**, not measured maximum capacity claims. They keep
the first design-partner environment below likely bottlenecks until the exact
release, host, providers, workflow, attachment mix, and model configuration pass
the load plan.

| Dimension | Default pilot cap before measured approval |
| --- | ---: |
| Design partners per environment | 1 |
| Email workflow/mailbox | 1 selected workflow |
| Published V1 runbooks | 3 |
| Interactive support/admin users | 10 concurrent |
| Eligible pilot tickets | 200 minimum; expected daily volume recorded before go-live |
| Sustained inbound events | 1 per second |
| Short inbound burst | 5 per second for 60 seconds |
| Concurrent model/runbook executions | 5 |
| Scheduler batch size | 25 unless a tested route requires less |
| Single attachment | 20 MiB unless the configured extraction path proves a lower safe limit |
| Total active attachment/knowledge data | 10 GiB |
| Oldest outbound queue item | warning at 5 minutes; critical at 15 minutes or customer SLA |
| API p95 | warning above 2 seconds under accepted scenario |
| API 5xx | warning above 2% with sufficient sample; critical above 5% |
| Disk headroom | warning below 20%; critical below 10% |

A deployment may approve higher or lower values only after recording:

- host/container/storage specification;
- release commit and image digests;
- production-like fixture and data sizes;
- provider/model/tool configuration;
- scenario, duration, concurrency, target rate, and results;
- resource graphs and queue/heartbeat behavior;
- failure/recovery behavior;
- operator and architecture approval;
- new alert and admission thresholds.

## 4. Required load-test scenarios

`../../scripts/load_test.py` sends weighted synthetic HTTP scenarios and produces
JSON containing throughput, error rate, status/error counts, and min/median/
p90/p95/p99/max latency by route and overall. Sensitive headers are read from
environment variables and are never written to the scenario or output.

The example scenario checks liveness/readiness only. A production approval must
extend it with deterministic synthetic routes or fixture-driven workflows for:

1. authenticated Inbox list/read/update;
2. ticket/message creation or replay-safe inbound ingestion;
3. runbook matching and a no-match path;
4. knowledge lookup at representative corpus size;
5. model execution using a deterministic test adapter and, separately, an
   approved provider latency/cost exercise;
6. read-only tool lookup and a safely fenced synthetic action;
7. outbound queue claim/delivery through a test adapter;
8. attachment upload/extraction at representative sizes;
9. scheduler catch-up after a controlled outage;
10. backup during expected low-traffic operations and restore timing in isolation.

Run at least:

- **steady state:** expected peak rate for 30 minutes;
- **burst:** 5x expected peak for 5 minutes with bounded queueing;
- **soak:** expected average rate for 4 hours;
- **degraded provider:** injected model/channel/tool latency, rate limit, and
  failure;
- **restart/catch-up:** restart the one API process and prove no lost/duplicate
  work;
- **storage growth:** representative database, attachment, and knowledge size;
- **recovery:** verify RPO/RTO with the same release and data scale.

Example:

```bash
cd backend
uv run python ../scripts/load_test.py \
  --base-url https://isolated-load.example.test \
  --scenario ../docs/architecture/load-test.scenario.example.json \
  --duration 1800 \
  --concurrency 10 \
  --rate 5 \
  --header-env Authorization=LOAD_TEST_AUTHORIZATION \
  --output ../evidence/load-test.json \
  --fail-on-threshold
```

Use synthetic tenants, disconnected real outbound providers, and an isolated
capacity environment. Do not load-test a customer production mailbox without
written authorization.

## 5. Capacity approval criteria

An approved operating point requires:

- all scenario thresholds pass on at least three runs;
- no duplicate ticket, message, action, or delivery;
- no unknown financial/destructive/customer-visible side effect;
- no tenant cross-read/write;
- no missing audit/run/delivery evidence;
- queues recover to normal age after burst/degradation;
- schedulers remain healthy and do not overlap incorrectly;
- CPU, memory, disk I/O, free disk, SQLite locks, provider quota, and connection
  use remain below agreed warning levels;
- p95/p99, 5xx, provider error, action failure, and cost remain within targets;
- backup and restore complete inside RPO/RTO at tested data size;
- no unredacted customer content/secret appears in load evidence;
- the approved cap is at most 70% of the first consistently observed bottleneck,
  leaving operational headroom.

A single successful run is not a capacity certification.

## 6. Evolution triggers

### External durable job queue and workers

Trigger when any applies:

- scheduler catch-up threatens interactive API latency;
- jobs regularly exceed one process lifetime or require independent scaling;
- queue age breaches target despite adequate provider capacity;
- one worker failure can lose or delay work beyond the RTO/SLA;
- multiple API replicas are commercially required;
- action/delivery throughput requires partitioned concurrency;
- deployment requires rolling updates without pausing all background work.

Required before adoption:

- durable job/outbox contract;
- tenant/project routing and quotas;
- lease/visibility timeout plus fencing token;
- idempotency and unknown-outcome handling;
- retry/dead-letter/manual recovery;
- heartbeat, queue age, attempts, and result telemetry;
- graceful shutdown and deployment-drain behavior;
- deterministic integration/failure tests.

### Postgres or supported transactional database

Trigger when any applies:

- multiple concurrent application writers are required;
- SQLite lock/write latency appears in accepted load;
- database size/backup downtime threatens RTO/RPO;
- customer requires point-in-time recovery, managed replication, or stronger HA;
- schema migration duration or risk exceeds the single-node maintenance window;
- tenant volume requires stronger query/index/partition controls.

Required migration contract:

- canonical schema and authorization semantics independent of PocketBase UI;
- dual-read/write or controlled downtime plan;
- IDs, timestamps, ordering, audit, file references, and idempotency preserved;
- representative existing-data migration and rollback;
- row/tenant isolation tests;
- backup/PITR/restore and deletion replay;
- performance comparison and cutover reconciliation.

### Object storage

Trigger when any applies:

- attachments/knowledge exceed the tested local-volume cap;
- API replicas or workers need shared file access;
- backup time/size is dominated by files;
- customer requires lifecycle, immutability, regional bucket, or object audit;
- local disk headroom becomes an operational risk.

Required controls:

- tenant-scoped opaque object keys;
- authorized signed download/upload paths;
- encryption, region, lifecycle, deletion, and legal-hold behavior;
- checksum, content type, size, malware/quarantine metadata;
- orphan cleanup and database/object transaction reconciliation;
- provider inventory and customer contract update;
- migration and rollback with complete file/hash verification.

### Stateless API replicas

Trigger only after external workers, shared object storage, and a supported
transactional data layer are complete. Required:

- no correctness dependency on local/in-memory state;
- distributed session/rate-limit/idempotency semantics;
- scheduler disabled in API replicas;
- rolling deployment and connection drain;
- shared observability and per-instance identity;
- multi-replica tenant/action/delivery integration and chaos tests.

### High availability and regional resilience

Trigger when the customer agreement cannot tolerate the single-host RTO or
scheduled backup downtime. Required design must state:

- failure domains and recovery region;
- database and object replication consistency;
- secret/configuration and provider failover;
- DNS/traffic switch and split-brain prevention;
- background-job ownership during failover;
- data residency/transfer implications;
- actual tested failover and failback RTO/RPO.

## 7. Stable contracts during evolution

Preserve:

- globally unique tenant/project/ticket/message/run/action/delivery IDs;
- UTC timestamps and deterministic ordering fields;
- immutable published runbook/version references;
- idempotency keys and provider request IDs;
- append-oriented audit/evaluation semantics;
- explicit action/delivery state machines;
- attachment hashes and authorized parent relations;
- retention/deletion and restore replay evidence;
- customer export format versions;
- correlation IDs and privacy-safe operational metrics.

Do not expose storage-specific record behavior as a permanent public API without a
compatibility boundary.

## 8. Decision and evidence process

Every increase or architecture transition records:

- measured problem and customer requirement;
- current operating point and bottleneck;
- alternatives and why the selected change is proportionate;
- data migration, rollback, security/privacy, and contract impact;
- benchmark/failure/recovery evidence;
- updated threat model, observability, runbooks, provider inventory, backup, and
  deployment docs;
- owner, milestones, and explicit enablement gate.

Premature replacement of PocketBase is not the goal. Honest operating limits and
safe evolution are.

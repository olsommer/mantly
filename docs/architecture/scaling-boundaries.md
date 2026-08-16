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
runs. It rejects a **declared** replica count above one and unimplemented
storage/worker modes. That declaration is not proof of the actual replica count:
every process could claim `MANTLY_API_REPLICAS=1`.

Deployment acceptance therefore requires an external observation:

```bash
python scripts/runtime_topology_inventory.py \
  --compose-file docker-compose.yml \
  --project-name "$COMPOSE_PROJECT_NAME" \
  --output evidence/runtime-topology.json
```

The inventory queries `docker compose ps --all` and `docker inspect`, requires
exactly one running `app`, `caddy`, and `pocketbase`, verifies app/PocketBase
health, and verifies each required writable durable mount. It records image and
container identities without copying environment variables, secrets, or host
paths. A self-declared environment value or application health response cannot
replace this evidence. Re-run it after every deploy, rollback, scale command, or
volume change.

Silently accepting an unsupported topology could create multiple SQLite
writers, duplicate schedulers, duplicate external actions, or inconsistent
local files.

The current topology is recoverable through encrypted backup and restore. It is
not highly available and does not provide point-in-time recovery, automatic
failover, or zero-data-loss guarantees.

## 2. Background-process inventory

“Process lock” below means a Python lock protects only one process. It provides
no cross-replica exclusion.

| Executor / loop | Trigger and default | Durable ownership or recovery | Multi-instance classification |
| --- | --- | --- | --- |
| Channel/email sync scheduler | API daemon thread; `SUPPORT_SYNC_INTERVAL_SECONDS`, default off | Provider cursor plus sync/event/message records; process lock only | **Single instance only.** No distributed lease/fence for the scheduler. |
| Outbound delivery scheduler | API daemon thread; `SUPPORT_DELIVERY_INTERVAL_SECONDS`, default off | Durable queue, attempt, claim token, claim expiry, fence/idempotency and delivery-run records | Delivery claims reduce duplicate sends, but unknown provider outcomes and scheduler ownership still make the supported topology **single instance only**. |
| CRM/external sync scheduler | API daemon thread; `SUPPORT_CRM_SYNC_INTERVAL_SECONDS`, default off | Connector cursor and sync records; process lock only | **Single instance only.** |
| SLA escalation scheduler | API daemon thread; `SUPPORT_SLA_INTERVAL_SECONDS`, default off | Ticket/SLA/event records; process lock only | **Single instance only.** |
| Abandoned-processing expiry scheduler | API daemon thread; `SUPPORT_PROCESSING_EXPIRY_INTERVAL_SECONDS`, default 60 seconds | Durable ticket/message processing timestamps; process lock only | **Single instance only.** Recovery sweep can overlap across replicas. |
| Admin channel-test recovery scheduler | API daemon thread; `SUPPORT_CHANNEL_TEST_JOB_INTERVAL_SECONDS`, default 5 seconds | Durable webhook-job status, claim token and claim expiry; process lock plus record claims | Claims fence a job attempt, but this release approves only **one scheduler instance**. |
| Per-job channel-test worker | Request-triggered daemon thread | Same durable webhook-job claim and expiry; the active-job set is process-local | **Single API instance only.** Recovery may repeat computation; provider-event completion must hold the current claim. |
| Evaluation run worker | Request-triggered daemon thread in `api/admin/evals.py` | Eval run/results; startup marks orphaned running work failed | **Single instance only.** No durable worker lease, resume, or distributed concurrency limit. |
| Learning-proposal evaluation worker | Request-triggered daemon thread in `api/admin/learning_proposals.py` | Proposal plus eval run/results; orphan recovery | **Single instance only.** No distributed worker lease. |
| Non-critical I/O worker | Lazy API daemon thread in `core/background.py` | In-memory queue only | **Never use for critical work or side effects.** Work can be lost on restart and no cross-instance ownership exists. |
| Model/runbook/grounding execution | Request threads with process-local concurrency semaphores | Durable run/action/audit records; some provider calls can finish after request timeout | **Single instance envelope only.** Multiple replicas multiply concurrency and do not create a durable queue. |
| On-prem license refresh | API daemon thread every 12 hours when licensed mode is configured | Signed local cache and remote validation result | The read/check is independently repeatable, but it does not make the rest of the API multi-instance safe. |
| Discord gateway worker | Optional separate long-running process per configured bot/channel | Discord session/sequence in memory; forwarded events rely on downstream deduplication | **Exactly one per bot/channel.** Multiple gateway sessions can forward the same event. Not part of the standard three-service topology. |
| Support bridge API sidecar | Optional separately deployed bridge process | Core API/PocketBase contains authoritative event state | Not part of the standard topology. Scale only after duplicate webhook/event tests and an approved inventory extension. |
| Backup/restore job | Host operator or CI job | Encrypted bundle, manifest, checksum and restore evidence | **Exactly one.** Application and PocketBase stop for the consistent SQLite snapshot. |
| Retention/deletion/export procedure | Operator/customer procedure | Primary, derived, provider and replay evidence | **Exactly one coordinator.** No distributed deletion coordinator exists. |

No correctness decision may depend only on in-memory thread state. Durable
records remain the source of truth, but this does not by itself make the current
scheduler topology horizontally safe. The runtime guard now inventories both
default-off and default-on schedulers; `MANTLY_WORKER_MODE=disabled` is rejected
unless every scheduler interval, including processing-expiry and channel-test
recovery, is explicitly zero.

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
JSON containing successful throughput, attempted throughput, full wall-clock
run time, error/status counts, and min/median/p90/p95/p99/max latency by route
and overall. Sensitive headers are read from environment variables and are never
written to the scenario or output.

The harness bounds duration, rate, concurrency, request count, body size, and
in-flight futures. It does not “catch up” with an unbounded burst when the target
falls behind. Throughput uses successful requests divided by the complete
schedule-and-drain wall time. Redirects and environment proxies are disabled.
The target must match an explicit host/port allowlist; link-local addresses are
always blocked and private targets require an explicit isolated-environment
flag. Every scenario must include non-vacuous error, latency, throughput,
minimum-sample, and per-target-sample thresholds.

The committed example scenario checks liveness/readiness only and is marked
`kind: smoke`. It cannot support a capacity decision. A production capacity
scenario must use `kind: capacity` and add deterministic synthetic routes or
fixture-driven workflows for:

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

Every scenario target declares one or more `workloads`. A `kind: capacity`
scenario is rejected unless it covers `inbox-read`, `inbound-ingestion`,
`runbook-match`, `knowledge-lookup`, `model-execution`, `tool-lookup`,
`outbound-delivery`, and `attachment-processing`. Restart/catch-up,
storage-growth, and recovery remain separate evidence exercises because an HTTP
request generator cannot prove them.

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
  --release-id <immutable-commit-or-image-set> \
  --environment-id isolated-pilot-capacity \
  --run-kind steady \
  --base-url https://isolated-load.example.test \
  --allowed-host isolated-load.example.test:443 \
  --scenario ../evidence/pilot-critical.capacity.json \
  --duration 1800 \
  --concurrency 10 \
  --rate 5 \
  --max-requests 10000 \
  --header-env Authorization=LOAD_TEST_AUTHORIZATION \
  --output ../evidence/load-test.json \
  --fail-on-threshold
```

Use synthetic tenants, disconnected real outbound providers, and an isolated
capacity environment. Do not load-test a customer production mailbox without
written authorization. Add `--allow-private-target` only when the allowlisted
host belongs to that isolated environment.

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

Operational acceptance is machine-gated:

```bash
python scripts/validate_capacity_evidence.py \
  --manifest evidence/capacity-acceptance.json \
  --output evidence/capacity-decision.json
```

The manifest format is illustrated by
`capacity-acceptance.manifest.example.json`. The gate requires:

- one externally observed, supported topology inventory;
- three distinct 30-minute steady runs;
- one 5-minute burst run;
- one 4-hour soak run;
- one 5-minute degraded-provider run;
- the same immutable release, environment, and capacity-scenario digest across
  those runs;
- passing, non-vacuous thresholds in every run;
- passed restart/catch-up, storage-growth, and recovery exercises;
- CPU, memory, disk I/O/free space, SQLite locks, queue age, provider-error, and
  cost evidence;
- a complete numeric operating envelope with at least 30% headroom;
- explicit architecture and operations approvals.

Until this gate passes for the exact deployment artifact, Mantly has no approved
measured capacity baseline. The conservative pilot caps in section 3 remain
provisional admission limits, not proof that the system sustains them.

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

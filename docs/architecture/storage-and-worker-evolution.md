# Storage and worker evolution plan

Status: **Approved direction, not implemented runtime capability**

This plan defines how Mantly can leave the current single-node boundary without
changing customer-visible support semantics or risking duplicate actions.
Implementation begins only when a trigger in `scaling-boundaries.md` is met.

## 1. Target shape

```text
public edge
  -> stateless API replicas
       -> transactional database (Postgres)
       -> object storage
       -> durable job/outbox table or queue
            -> channel ingestion workers
            -> runbook/model workers
            -> action workers
            -> outbound delivery workers
            -> CRM/SLA/retention workers

shared operations:
  -> metrics/logs/traces
  -> encrypted database/object backups and PITR
  -> deployment/lease/queue control plane
```

The model/provider and external tools remain replaceable tenant-approved
adapters. The database, queue, and object store are infrastructure contracts, not
places for provider-specific policy.

## 2. Non-negotiable semantics

Before extracting work from the API process, define state machines for:

- inbound event/message deduplication;
- ticket/runbook execution;
- human approval;
- external action attempt and unknown outcome;
- outbound message claim, send, delivery, retry, and dead letter;
- connector cursor/checkpoint;
- retention/deletion and provider cleanup;
- backup/restore and deletion replay.

Every side-effecting job carries:

- tenant/project scope;
- immutable input/reference version;
- job type and schema version;
- logical operation/idempotency key;
- attempt number;
- lease/visibility expiry;
- fencing token or monotonically increasing claim version;
- correlation ID;
- result/error category;
- provider request ID where available;
- created, available, claimed, completed, and dead-letter timestamps.

A worker may repeat computation. It may not repeat an external side effect unless
the provider and Mantly state prove the retry is safe.

## 3. Stage 0 — Current release

- one API process;
- PocketBase/SQLite;
- local application data;
- optional in-process schedulers;
- controlled downtime for consistent backup;
- deployment guard rejects other topology.

Use the pilot admission limits and capacity evidence. Do not begin Stage 1 solely
because a queue is fashionable.

## 4. Stage 1 — Durable outbox and external worker

Goal: move one low-risk background path, normally outbound delivery or channel
sync, out of the API process without changing storage.

Steps:

1. Define a durable job/outbox record in the current database.
2. Commit business state and job intent atomically where possible; otherwise use
   a reconciliation scanner and prove crash windows.
3. Add one external worker process with bounded concurrency.
4. Implement atomic claim, lease, fencing, heartbeat, retry, dead letter, and
   graceful shutdown.
5. Keep one API replica and current storage.
6. Run dual observation without two executors: compare the new scanner's planned
   work to current scheduler output before cutover.
7. Disable the corresponding in-process scheduler.
8. Load-test restart, lease expiry, duplicate event, provider timeout, unknown
   outcome, and worker deployment drain.

Exit evidence:

- no duplicate side effect under crash/restart tests;
- queue age and worker heartbeat alerts;
- manual recovery/dead-letter workflow;
- deployment and rollback procedure;
- backup/export/deletion include jobs and attempts.

## 5. Stage 2 — Canonical Postgres data layer

Goal: support stronger transactional behavior, managed backup/PITR, and future
multiple writers.

Do not make the API depend directly on two unrelated storage implementations.
Create a repository/data-access boundary with explicit methods for tenant-scoped
records, transitions, claims, and queries.

Migration steps:

1. Freeze and version the canonical schema and state transitions.
2. Map every PocketBase collection, relation, file reference, auth identity, and
   authorization rule.
3. Build one-way migration and reconciliation tools using synthetic and redacted
   representative datasets.
4. Prove IDs, timestamps, ordering, decimals, JSON, enums, runbook versions,
   idempotency keys, audit history, and deletion markers.
5. Choose controlled downtime or dual-write. Dual-write is accepted only with a
   durable reconciliation contract and rollback.
6. Migrate authentication deliberately: keep PocketBase identity as an external
   service temporarily or move it with explicit password/session/reset behavior.
7. Run tenant-isolation, migration, rollback, load, PITR, restore, export, and
   delete-after-restore tests.
8. Cut over one controlled environment and monitor reconciliation before broader
   use.

Exit evidence:

- zero unexplained count/hash mismatches;
- all critical state transitions transactional;
- documented rollback point;
- tested backup/PITR and deletion replay;
- performance headroom at approved operating point.

## 6. Stage 3 — Object storage

Goal: separate binary lifecycle from the API host and database.

Object contract:

- opaque tenant-scoped key, never user-controlled filesystem path;
- database record with object version, hash, size, media type, status, parent,
  retention/deletion state, and provenance;
- upload to quarantine/staging, validate/scan, then atomically publish the
  authorized reference;
- short-lived signed access or authenticated proxy;
- no public bucket/listing;
- region/encryption/lifecycle/incident terms in provider inventory;
- orphan and missing-object reconciliation;
- deletion/legal hold and backup strategy.

Migration:

1. Copy existing files and verify size/hash.
2. Keep source read-only during validation.
3. Switch reads by recorded object version.
4. Switch writes.
5. Verify export, retrieval, deletion, restore, and authorization.
6. Remove local copies only after expiry and rollback approval.

## 7. Stage 4 — Stateless API replicas

Prerequisites:

- all schedulers moved to workers;
- no required local application data;
- shared transactional database and object storage;
- distributed rate limiting/session/idempotency where required;
- per-instance identity and shared telemetry;
- health/readiness distinguish API from workers/providers;
- rolling deployment and drain tested.

Enable two replicas first. Test:

- concurrent create/update/approval;
- repeated webhook/event;
- simultaneous action/delivery claim;
- worker/API restart during every transition;
- stale instance/lease fencing;
- tenant authorization across replicas;
- rolling schema compatibility;
- load-balancer retry behavior.

Do not run in-process background jobs in API replicas.

## 8. Stage 5 — Availability and regional resilience

Only after a contractual need:

- define primary/standby or multi-region consistency;
- choose database/object replication and failover ownership;
- prevent two regions executing the same job/action;
- handle provider/channel callbacks and DNS during failover;
- replicate or recreate configuration/secrets without broadening access;
- assess data-location/transfer impact;
- test failover and failback, not only component restart.

## 9. Rollback principles

- Back up and verify before migration.
- Use immutable release artifacts and versioned schemas/jobs/exports.
- Never roll back application code past a destructive schema change without a
  tested compatibility path.
- Stop side effects before resolving unknown mixed-state execution.
- Reconcile counts, hashes, transitions, queue jobs, and provider outcomes.
- Preserve audit evidence of migration and rollback.
- Do not use customer production as the first migration test.

## 10. Ownership

Each stage requires named owners for architecture, data migration, workers,
security/privacy, operations, customer communication, and rollback. The decision
record must link the measured trigger, test evidence, deployment limits, and
updated customer documentation.

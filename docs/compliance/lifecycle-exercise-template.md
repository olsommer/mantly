# Synthetic export, deletion, and restore exercise

Status: **Pre-pilot evidence template**

This exercise proves the configured release can isolate, export, delete, and keep
deleted data inaccessible after an older backup is restored. Use synthetic data
only. Store detailed logs in the approved evidence location.

## Identification

| Field | Value |
| --- | --- |
| Exercise ID | `lifecycle-YYYYmmdd-NNN` |
| Date/time UTC | TBD |
| Release commit/image digest | TBD |
| Schema/migration version | TBD |
| Environment | isolated staging/local |
| Operator | TBD |
| Independent verifier | TBD |
| Provider inventory version | TBD |
| Backup object used for replay test | TBD |

## Fixture

Create tenant A and tenant B with unique sentinel prefixes that cannot be
confused. Each tenant must include:

- two users with different roles;
- one project;
- the three V1 runbooks and published versions;
- one knowledge source, file, extracted/indexed item;
- one customer/contact/account;
- one ticket with inbound/outbound messages, note, attachment, watcher, event;
- one AI run, action execution, approval, and delivery attempt;
- one evaluation/pilot metric record;
- one application-data file under `/app/data`;
- one provider/connector reference without a real credential.

Create one contact in tenant A for restricted deletion.

## Baseline assertions

- [ ] Tenant A can access only tenant A fixture records.
- [ ] Tenant B can access only tenant B fixture records.
- [ ] Admin/global test identity can enumerate expected fixture counts.
- [ ] Retrieval returns only same-tenant knowledge/message results.
- [ ] No real outbound provider is connected.
- [ ] Backup is created before deletion and passes integrity checks.

Record counts and sentinel IDs without copying complete content.

## Export tenant A

- [ ] Request/approval record completed.
- [ ] Export cutoff and deployed version recorded.
- [ ] Manifest contains schema version, counts, hashes, and exclusions.
- [ ] JSON/JSONL and attachment paths validate.
- [ ] Tenant A source/export counts reconcile.
- [ ] Tenant B sentinel scan returns zero matches.
- [ ] Secret scan finds no credential/session/private-key fields.
- [ ] Export archive is encrypted for the synthetic recipient.
- [ ] Independent verifier recalculates checksums and samples relations.

Evidence references:

- Export manifest:
- Count comparison:
- Sentinel scan:
- Secret scan:
- Independent verification:

## Restricted deletion in tenant A

Delete the selected contact's direct content and derived/indexed data while
preserving unrelated tenant A records as required by the fixture design.

- [ ] Customer/contact profile handled as planned.
- [ ] Message/attachment/note fields handled as planned.
- [ ] Retrieval/index/cache no longer returns deleted content.
- [ ] Provider-copy task completed or recorded not applicable.
- [ ] Minimized deletion receipt created.
- [ ] Tenant A unrelated records remain correct.
- [ ] Tenant B remains unchanged.

## Full tenant A termination

- [ ] Tenant A users/sessions disabled.
- [ ] Channels, schedulers, automations, tools, and outbound delivery paused.
- [ ] Queued/claimed/unknown actions and deliveries reconciled.
- [ ] Tenant A credentials/provider references revoked or removed.
- [ ] Primary records deleted in dependency-safe order.
- [ ] PocketBase files and application-data paths removed.
- [ ] Retrieval/index/cache results removed.
- [ ] Dashboards/alerts/support access removed.
- [ ] Backup deletion-replay/tombstone record created.
- [ ] Tenant A login and authorized API reads fail.
- [ ] Tenant B fixture remains complete and usable.

## Restore and deletion replay

Restore the pre-deletion backup into a separate isolated environment.

- [ ] Backup manifest, hashes, and SQLite integrity pass.
- [ ] Restored environment has no real outbound provider credentials.
- [ ] Before replay, tenant A fixture is detected only as expected from the old snapshot.
- [ ] Restricted-deletion and tenant-termination records are replayed.
- [ ] Tenant A is inaccessible/deleted after replay.
- [ ] Retrieval cannot return tenant A sentinel content.
- [ ] No tenant A scheduler/action/delivery item can execute.
- [ ] Tenant B remains complete and isolated.
- [ ] Restore verifier and lifecycle assertions pass.

## Results

| Check | Expected | Actual | Pass |
| --- | --- | --- | --- |
| Export completeness | all scoped A records/files | TBD | yes/no |
| Cross-tenant leakage | zero B records in A export | TBD | yes/no |
| Secret leakage | zero prohibited credentials | TBD | yes/no |
| Restricted deletion | selected subject inaccessible | TBD | yes/no |
| Tenant A termination | no active/accessed A data | TBD | yes/no |
| Tenant B integrity | unchanged | TBD | yes/no |
| Restore integrity | hashes/SQLite/services pass | TBD | yes/no |
| Deletion replay | A remains deleted after old restore | TBD | yes/no |

## Deviations and incidents

Describe any mismatch, manual database repair, cross-tenant result, provider
unknown state, reappearing data, or missing evidence. A cross-tenant export or
deletion is a security incident, not a test-only inconvenience.

## Follow-up issues

| Issue | Severity | Owner | Due date | Pilot blocker |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | YYYY-MM-DD | yes/no |

## Decision

- [ ] Passed; lifecycle readiness accepted for the tested release/configuration.
- [ ] Conditionally accepted with a time-bounded risk acceptance.
- [ ] Failed; real customer processing remains blocked.

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Operator | TBD | approve/reject | YYYY-MM-DD |
| Independent verifier | TBD | approve/reject | YYYY-MM-DD |
| Engineering owner | TBD | approve/reject | YYYY-MM-DD |
| Privacy/security owner | TBD | approve/reject | YYYY-MM-DD |

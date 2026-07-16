# Restore drill evidence

Copy this template for every restore drill. Store customer-sensitive evidence in
the approved restricted location and keep only redacted identifiers in the
repository.

## Identification

| Field | Value |
| --- | --- |
| Drill ID | `restore-YYYYmmdd-NNN` |
| Date/time (UTC) | YYYY-MM-DDTHH:MM:SSZ |
| Environment | isolated local / staging / replacement host |
| Backup object ID | TBD |
| Backup creation time | TBD |
| Backup age at restore | TBD |
| Source commit/image digest | TBD |
| Target commit/image digest | TBD |
| Operator | TBD |
| Independent verifier | TBD |

## Objectives

| Objective | Target | Actual | Pass |
| --- | ---: | ---: | --- |
| RPO | 24 hours | TBD | yes/no |
| RTO | 4 hours | TBD | yes/no |
| Bundle integrity | all hashes valid | TBD | yes/no |
| SQLite integrity | all databases `ok` | TBD | yes/no |
| Required data classes | complete | TBD | yes/no |

## Procedure evidence

- Backup command/job reference:
- Encrypted bundle checksum:
- Restore command/job reference:
- `restore-verification.json` reference:
- Service health evidence:
- PocketBase collection verification:
- Application fixture verification:
- Attachment/knowledge verification:
- Deletion replay verification:
- Delivery/action safety mode during drill:

## Data verification

| Data class | Fixture/evidence ID | Expected | Observed | Pass |
| --- | --- | --- | --- | --- |
| Tenant/project | TBD | present and isolated | TBD | yes/no |
| Users/roles | TBD | correct | TBD | yes/no |
| Runbooks/versions | TBD | correct | TBD | yes/no |
| Tickets/messages | TBD | complete | TBD | yes/no |
| Attachments | TBD | readable and authorized | TBD | yes/no |
| Knowledge/index | TBD | source and retrieval available | TBD | yes/no |
| Action executions | TBD | history complete | TBD | yes/no |
| Outbound delivery | TBD | state and claims complete; no real send | TBD | yes/no |
| Audit/evaluations | TBD | reconstructable | TBD | yes/no |
| Deleted fixture | TBD | remains deleted after replay | TBD | yes/no |

## Deviations and repairs

Describe missing data, manual repair, unexpected configuration, delayed service
startup, stale credentials, or verification gaps. “None” must be explicit.

## Security observations

- Was the bundle encrypted and separately access controlled?
- Were secrets supplied separately rather than restored from the bundle?
- Were logs/evidence free of customer content and credentials?
- Was the target isolated from real outbound providers?
- Did any deleted data reappear before deletion replay?

## Follow-up work

| Issue | Severity | Owner | Due date | Blocking next pilot/release? |
| --- | --- | --- | --- | --- |
| TBD | TBD | TBD | YYYY-MM-DD | yes/no |

## Decision

- [ ] Restore accepted for production-readiness evidence.
- [ ] Restore conditionally accepted with documented risk acceptance.
- [ ] Restore failed; customer pilot/release remains blocked.

Approvals:

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Operator | TBD | approve/reject | YYYY-MM-DD |
| Independent verifier | TBD | approve/reject | YYYY-MM-DD |
| Engineering owner | TBD | approve/reject | YYYY-MM-DD |
| Security/privacy owner, if required | TBD | approve/reject | YYYY-MM-DD |

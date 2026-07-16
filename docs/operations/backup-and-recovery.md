# Backup and disaster recovery

Status: **Required for a production-like pilot**

Owner: Deployment operator with an independent restore verifier

This runbook covers the current single-node Docker Compose deployment. It backs
up both persistent Mantly state volumes, verifies archive integrity, and restores
into a clean or replacement environment. It does not claim point-in-time
recovery or high availability.

## 1. Recovery objectives

The current pilot objectives are:

| Objective | Target | Meaning |
| --- | ---: | --- |
| Recovery Point Objective (RPO) | 24 hours | At most 24 hours of successfully committed data may be lost after a complete host failure. |
| Recovery Time Objective (RTO) | 4 hours | A replacement single-node deployment should be restored and verified within four hours of incident declaration. |
| Backup frequency | Daily | Run after the lowest expected traffic period and after material schema/configuration changes. |
| Backup retention | 30 rolling days | Customer or legal requirements may shorten or extend this with explicit approval. |
| Restore drill | Before pilot, then quarterly | A backup is not considered valid until restored and verified. |

These are internal operating targets unless a signed customer agreement states
otherwise. A stricter customer requirement requires a different architecture or
explicit acceptance before go-live.

## 2. Protected state

The current Compose deployment stores durable state in:

- PocketBase data mounted at `/pb/pb_data`:
  - SQLite database;
  - PocketBase-managed files;
  - migration/runtime metadata;
- application data mounted at `/app/data`:
  - uploaded/derived content stored by the backend;
  - local execution artifacts and other application-managed state.

The backup script discovers the actual Docker volume names from container mounts;
it does not assume the Compose project prefix or legacy volume name.

The following are **not** embedded as plaintext in the backup bundle:

- JWT, SMTP, Stripe, provider, connector, webhook, PocketBase superuser, license,
  or backup-encryption secrets;
- deployment `.env` files;
- DNS/provider console configuration.

Maintain a separately protected infrastructure configuration record that lists
which secret references and provider accounts are required for recovery. Backup
encryption keys must be stored outside the backup location.

Caddy TLS data is not part of the required application backup because
certificates can be reissued. Back it up separately only when the deployment
operator has a documented reason.

## 3. Backup format

`scripts/backup.sh` creates one timestamped bundle containing:

```text
manifest.json
pocketbase-data.tar.gz
application-data.tar.gz
```

The manifest records:

- format version;
- UTC creation time;
- source host and repository commit when available;
- Compose project and discovered volume names;
- component size and SHA-256 digest;
- whether services were stopped for consistency;
- backup reason/operator metadata supplied through environment variables.

The component archives are created while `app` and `pocketbase` are stopped.
This controlled downtime is intentional: the current SQLite architecture does
not provide an application-level point-in-time snapshot contract.

The outer bundle must be encrypted with `age` by default. Unencrypted output is
allowed only with `ALLOW_UNENCRYPTED_BACKUP=true` for an isolated local drill.
Never upload an unencrypted production backup to shared or remote storage.

## 4. Prerequisites

- Docker and Docker Compose v2;
- the Compose project has been created and the `pocketbase` and `app` services
  exist;
- `python3`, `tar`, and `sha256sum` on the host;
- `age` for production backup encryption/decryption;
- enough free disk space for at least twice the current durable volume size;
- access to a destination that is separate from the production host;
- `BACKUP_AGE_RECIPIENT` set to the approved age public recipient.

Example:

```bash
export BACKUP_AGE_RECIPIENT='age1...'
export BACKUP_REASON='daily-production'
export BACKUP_OPERATOR='on-call@example.com'
./scripts/backup.sh /secure/staging-directory
```

The script outputs an `.age` bundle and a separate SHA-256 file. Transfer both to
the protected backup store, then remove the local staging copy according to the
host policy.

## 5. Backup procedure

1. Confirm no incident response or maintenance operation is changing the same
   data.
2. Confirm the last backup completed and the destination has sufficient space.
3. Run `scripts/backup.sh`.
4. The script:
   - identifies the running/created service containers and durable volume mounts;
   - stops `app` and `pocketbase`;
   - archives both volumes read-only;
   - generates and verifies component SHA-256 hashes;
   - creates the outer bundle;
   - encrypts the bundle unless explicitly in an unencrypted local drill;
   - restarts the previously running services through a trap even after failure;
   - waits for the stack to return to service where possible.
5. Copy the encrypted bundle and checksum to separate backup storage.
6. Record the backup object identifier, size, creation time, expiry, and job
   result in operations evidence.
7. Alert when the newest successful backup is older than the RPO.

## 6. Restore safety

Restore is destructive to the target PocketBase and application data volumes.
`scripts/restore.sh` requires:

```bash
export RESTORE_CONFIRM='ERASE_AND_RESTORE_MANTLY'
```

Use a replacement or isolated environment for drills. Never test a restore by
overwriting the only production copy.

Required inputs:

```bash
export BACKUP_AGE_IDENTITY_FILE=/secure/path/backup-identity.txt
./scripts/restore.sh /secure/mantly-backup-YYYYmmddTHHMMSSZ.tar.gz.age
```

For an unencrypted local drill only:

```bash
export ALLOW_UNENCRYPTED_BACKUP=true
export RESTORE_CONFIRM='ERASE_AND_RESTORE_MANTLY'
./scripts/restore.sh ./mantly-backup-...tar.gz
```

## 7. Restore procedure

1. Provision a clean host or isolated Compose project from the exact intended
   release commit/image.
2. Configure required secrets and domains from the protected infrastructure
   record; do not extract secrets from the backup.
3. Create the target service containers/volumes with `docker compose create`.
4. Run `scripts/restore.sh` with the explicit destructive confirmation.
5. The script:
   - decrypts and extracts the bundle in a temporary restricted directory;
   - validates format, component presence, size, and SHA-256 digests;
   - stops target services;
   - clears only the discovered target durable volumes;
   - restores PocketBase and application data;
   - runs SQLite integrity checks against each restored `.db` file;
   - starts PocketBase and the application;
   - waits for health endpoints;
   - runs `scripts/verify-restore.py` for application/PocketBase checks;
   - leaves temporary data only when requested for investigation.
6. Supply `PB_ADMIN_EMAIL` and `PB_ADMIN_PASSWORD` to deeper verification when
   available.
7. Validate customer/tenant-specific evidence manually or through the pilot
   fixture.
8. Reconcile messages, actions, delivery attempts, and deletion requests created
   after the backup timestamp before customer traffic resumes.
9. Rotate credentials when the recovery is caused by compromise.
10. Record elapsed time, data loss window, verification evidence, and any manual
    repair.

## 8. Restore verification

A restore is successful only when all applicable checks pass.

### Automated checks

- bundle and component hashes match;
- every restored SQLite database returns `PRAGMA integrity_check = ok`;
- PocketBase health endpoint succeeds;
- FastAPI `/api/health` succeeds;
- PocketBase superuser authentication succeeds when credentials are provided;
- required collections are reachable;
- backend support package/schema gate succeeds where configured;
- no required durable volume is empty unexpectedly.

### Application verification

Using a synthetic or authorized test tenant, verify:

- authentication and role/tenant boundaries;
- users, tenant/project configuration, and published runbooks;
- representative ticket, messages, notes, attachments, timeline, and audit events;
- knowledge source and retrieval access;
- outbound message/delivery state and claim history;
- action executions and approval history;
- tenant settings and provider/connector configuration references;
- metrics/evaluation records needed for the pilot;
- deleted fixture data remains deleted after replaying post-backup deletion
  records.

Do not send a real outbound customer message during a restore drill. Use a
blocked/test delivery adapter or disconnect external credentials.

## 9. Restore drill record

Create an evidence record for every drill:

| Field | Required value |
| --- | --- |
| Drill ID/date | UTC timestamp |
| Backup object and creation time | Identifier and age |
| Source commit/image | Commit SHA and image digest |
| Target environment | Isolated project/host |
| Operators/verifier | At least one operator and one verifier |
| Start/healthy time | RTO measurement |
| Estimated data-loss window | RPO measurement |
| Automated verification | Pass/fail with logs |
| Application fixture verification | Pass/fail with evidence refs |
| Missing/corrupt data | Details or none |
| Manual repair | Details or none |
| Security/deletion observations | Details or none |
| Follow-up issues | Owners and deadlines |

The first real customer pilot may not start until at least one complete restore
drill has passed using a representative synthetic dataset.

## 10. Retention and deletion

- Store encrypted bundles with explicit creation and expiry timestamps.
- Delete expired objects and redundant local staging copies automatically.
- Restrict backup read/decrypt access separately from production operator access.
- Review access logs for backup storage.
- Apply `docs/security/data-retention.md` to data that remains only in backups.
- When restoring an older snapshot, replay valid deletion/tombstone records before
  returning the environment to service.
- A legal hold must be scoped and documented; it must not silently disable normal
  expiry for every tenant.

## 11. Failure handling

If backup fails:

- the trap restarts services that were running before the attempt;
- preserve the failure log without customer content;
- do not upload a partial bundle;
- alert the operator and retry only after understanding whether disk, Docker,
  volume, encryption, or integrity failed;
- escalate before the RPO is breached.

If restore fails:

- keep the target isolated;
- preserve extraction and verification evidence;
- do not repeatedly overwrite the same target without understanding the failure;
- try an earlier verified backup only after recording the failed object;
- declare an incident when no backup within the accepted RPO can be restored.

## 12. Architecture boundary

This procedure provides recoverability for one controlled node. It does not
provide:

- continuous availability;
- automatic failover;
- point-in-time recovery;
- geographically redundant writes;
- zero-data-loss guarantees;
- safe horizontal SQLite writes.

Those requirements trigger the storage/worker evolution described in
`docs/architecture/scaling-boundaries.md` once merged.

# On-premises backup and recovery addendum

This addendum replaces copy-only SQLite backup instructions for customer-managed
Mantly deployments. Follow the full [backup and disaster-recovery
runbook](operations/backup-and-recovery.md).

## Customer responsibility boundary

The customer operating an on-premises instance is responsible for:

- installing and scheduling the backup tooling;
- providing an approved `age` encryption recipient and separately protected
  identity;
- transferring encrypted bundles and checksums off the Mantly host;
- enforcing retention and backup-store access controls;
- monitoring backup freshness against the agreed RPO;
- performing and recording restore drills;
- maintaining the external secret/configuration inventory required to rebuild the
  deployment;
- replaying valid deletion requests after an older snapshot is restored;
- contacting Mantly before migrating a machine-bound licensed instance when the
  license model requires a reset.

Mantly's repository tooling provides consistent bundle creation, destructive
restore safeguards, hash/SQLite verification, and application health/collection
checks. It does not provide managed off-site storage or automatic failover.

## Package requirements

The customer deployment package or operator checkout must contain:

```text
scripts/backup.sh
scripts/restore.sh
scripts/verify-restore.py
docs/operations/backup-and-recovery.md
docs/operations/restore-drill-template.md
```

Install `age`, Docker Compose v2, Python 3, `tar`, and `sha256sum` on the host.

## Create an encrypted backup

```bash
export BACKUP_AGE_RECIPIENT='age1...'
export BACKUP_REASON='daily-production'
export BACKUP_OPERATOR='customer-operator@example.com'
./scripts/backup.sh /secure/local-staging
```

The script temporarily stops the `app` and `pocketbase` writers, discovers the
actual Docker mounts for `/app/data` and `/pb/pb_data`, archives both, creates a
manifest with component hashes and sizes, encrypts the bundle, and returns the
previous service state.

Transfer both files off-host:

```text
mantly-backup-<timestamp>.tar.gz.age
mantly-backup-<timestamp>.tar.gz.age.sha256
```

Delete the local staging copy after successful protected transfer according to
the customer's operations policy.

## Restore into an isolated environment

Do not test a restore by overwriting the only production instance. Provision an
isolated Compose project or replacement host, configure its secrets separately,
and disconnect real outbound providers.

```bash
export BACKUP_AGE_IDENTITY_FILE=/secure/backup-identity.txt
export RESTORE_CONFIRM='ERASE_AND_RESTORE_MANTLY'
export RESTORE_API_URL=https://restored.example.com
export RESTORE_PB_URL=https://restored.example.com/pb
export PB_ADMIN_EMAIL=<restored-superuser-email>
export PB_ADMIN_PASSWORD=<restored-superuser-password>
./scripts/restore.sh /secure/mantly-backup-<timestamp>.tar.gz.age
```

The restore is intentionally destructive to the target durable volumes. It
validates the outer checksum, decrypts the bundle, verifies the manifest and
component hashes/sizes, restores both volumes, runs SQLite integrity checks,
starts the services, and runs the deployment verifier.

## Required customer verification

In addition to automated health and collection checks, verify with synthetic or
contract-authorized records:

- authentication, roles, tenant/project isolation;
- published runbooks and versions;
- tickets, messages, notes, timelines, and attachments;
- knowledge sources and retrieval;
- action execution and approval history;
- outbound queue/delivery state without sending a real message;
- audit/evaluation evidence;
- deletion replay for data removed after the backup timestamp.

Record the result with
[`operations/restore-drill-template.md`](operations/restore-drill-template.md).
The initial production-like pilot requires one passed restore drill; repeat at
least quarterly under the current operating target.

## Current limitation

This procedure targets the current single-node PocketBase/SQLite architecture.
It does not provide point-in-time recovery, continuous availability, automatic
failover, or safe multi-writer scaling. Customers requiring stricter RPO/RTO or
high availability need an explicitly supported architecture and agreement.

# Canonical naming and legacy-volume migration

Status: **Required when upgrading an existing deployment that used legacy Isarai identifiers**

Mantly package, image, test, cache, and Compose identifiers are normalized in
this release. Existing Docker volumes are never renamed in place or deleted
automatically because that could make a deployment appear empty.

## Canonical identifiers

| Kind | Canonical value |
| --- | --- |
| Python package/project | `mantly-backend` |
| Admin package | `@mantly/admin` |
| Outlook add-in package | `@mantly/outlook-addin` |
| Landing package | `@mantly/landing` |
| Application image | `mantly` or the configured Mantly registry path |
| PocketBase image | `mantly-pocketbase` |
| Test image | `mantly-test` |
| PocketBase Compose volume key | `mantly_pb_data` |
| Application Compose volume key | `mantly_app_data` |

The GitHub organization, commercial registry, customer-specific image prefix, and
external provider account names can differ. They must not be confused with the
product/runtime identifiers above.

## New deployments

No migration is required. Deploy the canonical Compose file and create a verified
encrypted backup after the first successful production-readiness check.

## Existing deployments

### 1. Prepare

1. Record the running commit/image digest and Compose project name.
2. Create and verify an encrypted backup using `scripts/backup.sh`.
3. Schedule downtime; the current SQLite deployment must not write during copy.
4. Confirm free disk can hold both old and new volumes.
5. Identify actual old volume names:

```bash
docker volume ls | grep -E 'isarai_(pb|app)_data|mantly_(pb|app)_data'
```

The default names are project-prefixed, for example:

```text
mantly_isarai_pb_data
mantly_isarai_app_data
```

A different historic Compose project can use another prefix. Supply explicit
`LEGACY_PB_VOLUME` and `LEGACY_APP_VOLUME` when necessary.

### 2. Copy and verify

```bash
export COMPOSE_PROJECT_NAME=mantly
export MANTLY_VOLUME_MIGRATION_CONFIRM=COPY_LEGACY_VOLUMES_TO_MANTLY
./scripts/migrate-compose-volumes.sh
```

Optional explicit names:

```bash
export LEGACY_PB_VOLUME=oldproject_isarai_pb_data
export LEGACY_APP_VOLUME=oldproject_isarai_app_data
export MANTLY_PB_VOLUME=mantly_mantly_pb_data
export MANTLY_APP_VOLUME=mantly_mantly_app_data
export MANTLY_VOLUME_MIGRATION_CONFIRM=COPY_LEGACY_VOLUMES_TO_MANTLY
./scripts/migrate-compose-volumes.sh
```

The script:

- stops `app` and `pocketbase` writers;
- requires an explicit destructive-operation acknowledgment;
- refuses a missing source or non-empty target;
- copies files read-only from legacy volumes;
- compares object counts and all regular-file SHA-256 hashes;
- retains legacy volumes for rollback;
- does not restart services automatically.

### 3. Start and validate canonical volumes

Deploy the canonical Compose file, then:

```bash
docker compose up -d
curl --fail --show-error https://<api-domain>/api/health
curl --fail --show-error https://<api-domain>/api/ready
```

Verify:

- PocketBase superuser and application authentication;
- tenant/project isolation;
- representative users, runbooks, tickets, messages, notes, attachments,
  knowledge, actions, outbound/delivery and audit history;
- scheduler heartbeat and queue state;
- one blocked/test ticket-to-delivery path;
- backup creation and restore verification from the canonical volumes.

### 4. Rollback

If validation fails:

1. stop `app` and `pocketbase`;
2. preserve logs and migration evidence;
3. restore the previous Compose/release artifact that references the legacy
   volumes;
4. start and verify the previous release;
5. investigate before copying again.

Do not allow writes to both old and new volumes and then alternate between them.
That creates divergent histories that a filename/hash comparison cannot reconcile.

### 5. Retire legacy volumes

Keep legacy volumes until:

- the agreed rollback window has expired;
- a canonical-volume encrypted backup has passed a restore drill;
- application/data verification and customer acceptance are recorded;
- no rollback or incident investigation requires the old copy.

Then delete only the explicitly approved legacy volume names:

```bash
docker volume rm oldproject_isarai_pb_data oldproject_isarai_app_data
```

The deletion is irreversible. Keep the encrypted verified backup according to the
retention policy.

## Repository naming gate

`scripts/check_branding.py` verifies package/lock metadata, canonical Compose
volume keys, and forbidden legacy identifiers. The legacy values are allowed only
in this migration runbook and the migration script because operators need the
exact historic names to migrate safely.

## External compatibility

Do not rename customer-visible domain names, Microsoft add-in IDs, API routes,
database collection names, provider object IDs, or license keys merely for brand
consistency. Those identifiers require their own compatibility and migration
analysis. This cleanup targets package/build/deployment names whose legacy value
is not a customer data contract.

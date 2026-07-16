# Deploy Mantly — SaaS

Production deployment guide for the hosted SaaS version on Hetzner or another Linux VPS with Docker.

This document describes the current controlled single-node architecture. It does not claim high availability, horizontal SQLite writes, point-in-time recovery, or zero-downtime failover. The supported capacity and evolution triggers are documented separately in the scaling-boundaries decision package.

## Prerequisites

- Linux VPS with Docker and Docker Compose v2
- DNS for `mantly.io`, `app.mantly.io`, `addin.mantly.io`, and `api.mantly.io`
- A supported model-provider API key
- A production secret store or protected environment configuration
- [`age`](https://age-encryption.org/) on the host for encrypted backups
- An off-host backup destination with access controls separate from the production server

## 1. Clone and configure

```bash
git clone <repo-url> mantly
cd mantly
cp .env.example .env
```

Edit `.env` with your values:

```env
# Required
JWT_SECRET=<generate: python3 -c "import secrets; print(secrets.token_hex(32))">
PB_ADMIN_EMAIL=admin@mantly.io
PB_ADMIN_PASSWORD=<strong-unique-password>

# Public SaaS domains
DOMAIN=api.mantly.io
PUBLIC_URL=https://api.mantly.io
CORS_ORIGINS=https://app.mantly.io,https://addin.mantly.io
PB_CORS_ORIGINS=https://app.mantly.io,https://addin.mantly.io
APP_BASE_URL=https://app.mantly.io
ADDIN_BASE_URL=https://addin.mantly.io
ASSET_BASE_URL=https://api.mantly.io

# Frontend build URLs
VITE_API_URL=https://api.mantly.io
VITE_PB_URL=https://api.mantly.io/pb
VITE_ADDIN_URL=https://addin.mantly.io
VITE_ADDIN_BASE_PATH=/
ENABLE_DEMO_MODE=false
SAAS_SIGNUP_ENABLED=true

# SaaS mode
VITE_IS_SAAS=true

# Add-in ID — fixed UUID for the Microsoft Store listing
ADDIN_ID=a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Managed model provider
MANTLY_MANAGED_LLM_PROVIDER=gemini
MANTLY_MANAGED_LLM_MODEL=<approved-model>
MANTLY_MANAGED_LLM_API_KEY=<provider-key>
```

Production rules:

- never commit `.env` or provider credentials;
- use unique secrets per environment;
- keep demo/mock flags disabled;
- restrict CORS to the actual admin/add-in origins;
- document provider region, retention, and subprocessor treatment before customer processing;
- record the deployed commit and image digest.

## 2. Start the stack

```bash
docker compose up -d --build
```

This starts the API stack:

| Service | Role | Port |
| --- | --- | --- |
| **caddy** | Reverse proxy for `api.mantly.io` | 80/443 public when mapped by the deployment platform |
| **pocketbase** | Authentication and data storage (SQLite) | 8090 internal |
| **app** | FastAPI backend | 8080 internal |

Caddy terminates TLS in a direct Docker deployment. When Coolify terminates TLS, keep `DOMAIN=:80` and expose only the Coolify-managed route.

## 3. Architecture overview

```text
Internet
  │
  ▼
Caddy (:443, api.mantly.io)
  ├── /pb/*    → PocketBase (:8090)   — auth and data
  └── /*       → FastAPI app (:8080)  — API and manifest assets
```

The admin SPA is hosted at `app.mantly.io`, the Outlook add-in SPA at `addin.mantly.io`, and the landing page at `mantly.io`.
Both SPAs call `https://api.mantly.io`; PocketBase is exposed as `https://api.mantly.io/pb` through the reverse proxy.
The SaaS API image is backend-only and does not bundle admin/add-in/landing assets.

The current deployment is one application instance and one PocketBase/SQLite instance. Do not run multiple API replicas with in-process schedulers until the distributed worker/lease boundary has been implemented and verified.

## Coolify deployment

Use four Coolify application resources in the same project/environment:

| Resource | Build pack | Domain | Dockerfile / compose |
| --- | --- | --- | --- |
| `mantly-api` | Docker Compose | `https://api.mantly.io` | `/docker-compose.yml`, service domain `caddy`, API image `/Dockerfile.api` |
| `mantly-admin` | Dockerfile | `https://app.mantly.io` | `/deploy/admin.Dockerfile` |
| `mantly-addin` | Dockerfile | `https://addin.mantly.io` | `/deploy/addin.Dockerfile` |
| `mantly-landing` | Dockerfile | `https://mantly.io` | `/deploy/landing.Dockerfile` |

Set these env vars on `mantly-api`:

```env
DOMAIN=:80
PUBLIC_URL=https://api.mantly.io
MANIFEST_BASE_URL=https://api.mantly.io
APP_BASE_URL=https://app.mantly.io
ADDIN_BASE_URL=https://addin.mantly.io
ASSET_BASE_URL=https://api.mantly.io
CORS_ORIGINS=https://app.mantly.io,https://addin.mantly.io
PB_CORS_ORIGINS=https://app.mantly.io,https://addin.mantly.io
VITE_API_URL=https://api.mantly.io
VITE_PB_URL=https://api.mantly.io/pb
VITE_ADDIN_URL=https://addin.mantly.io
VITE_ADDIN_BASE_PATH=/
VITE_IS_SAAS=true
ENABLE_DEMO_MODE=false
SAAS_SIGNUP_ENABLED=true

# Optional approved LangSmith tracing. Treat prompt/response tracing as customer data.
LANGSMITH_TRACING=false
LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=mantly.io
```

Set these env vars on `mantly-admin`:

```env
VITE_API_URL=https://api.mantly.io
VITE_PB_URL=https://api.mantly.io/pb
VITE_ADDIN_URL=https://addin.mantly.io
VITE_IS_SAAS=true
VITE_REQUIRE_AUTH=true
VITE_ENABLE_ADMIN_PREVIEW=true
VITE_ENABLE_DEMO_MODE=false
```

Set these env vars on `mantly-addin`:

```env
VITE_API_URL=https://api.mantly.io
VITE_PB_URL=https://api.mantly.io/pb
VITE_REQUIRE_AUTH=true
VITE_ENABLE_MOCK_MODE=false
VITE_ENABLE_DEMO_MODE=false
VITE_ADDIN_BASE_PATH=/
```

Point DNS for all four names to the Coolify server:

```text
mantly.io        A  <coolify-server-ip>
api.mantly.io    A  <coolify-server-ip>
app.mantly.io    A  <coolify-server-ip>
addin.mantly.io  A  <coolify-server-ip>
```

## 4. Verify deployment

```bash
curl --fail --show-error https://api.mantly.io/api/health
curl --fail --show-error https://api.mantly.io/pb/api/health
```

Also verify:

- authenticated admin login and password lifecycle;
- cross-tenant access denial;
- demo endpoints unavailable;
- one synthetic inbound ticket and safe outbound test delivery;
- scheduler/worker health and last-success timestamps once observability is enabled;
- a current encrypted backup and a passed restore drill.

## 5. PocketBase admin setup

1. Open `https://api.mantly.io/pb/_/`.
2. Log in with `PB_ADMIN_EMAIL` / `PB_ADMIN_PASSWORD`.
3. Configure SMTP for email verification and password reset under **Settings → Mail settings**.
4. Restrict superuser access to authorized operators and rotate the credentials after suspected exposure.

Do not use the PocketBase superuser credential in tenant-facing client code.

## 6. Microsoft Store submission

The store-ready manifest is at `addin/manifest.store.xml` with `https://addin.mantly.io` for the taskpane and `https://api.mantly.io` for icon assets.

To submit:

1. Open Microsoft Partner Center.
2. Create an Office Add-in submission.
3. Upload `addin/manifest.store.xml`.
4. Provide approved screenshots, descriptions, privacy information, and icon assets.
5. Submit for certification.

Once approved, tenants install the add-in from Microsoft 365 rather than downloading a repository manifest.

## 7. Self-service signup

With `VITE_IS_SAAS=true`, the admin SPA at `https://app.mantly.io/` can expose signup when the release explicitly enables it. New accounts create a tenant and initial administrator.

For the first design-partner pilot, founder-led provisioning is preferred. Broad self-service onboarding remains outside the active V1 validation contract until the pilot is repeatable and the abuse, billing, retention, and support boundaries are proven.

## 8. Managing on-premises licenses

The SaaS instance can act as the license server for customer-managed deployments. Licenses are stored in the PocketBase `licenses` collection.

Create a license through the protected admin API only after authentication/authorization and commercial approval. Never expose license-management endpoints without the platform-admin boundary.

Example payload:

```bash
curl -X POST https://api.mantly.io/api/admin/licenses \
  -H "Authorization: Bearer <platform-admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"tenant_name":"Customer XYZ","max_users":10,"expires_at":"2026-12-31T00:00:00Z"}'
```

Do not put full license keys in tickets, logs, or screenshots. Use a short prefix for support correlation.

## 9. Updating

Before updating:

1. confirm the target commit/image passed required CI and security checks;
2. create a fresh encrypted backup;
3. record current image digests and rollback command;
4. review schema and release notes;
5. schedule downtime when the change affects the single-node database or restore boundary.

```bash
cd mantly
git pull --ff-only
docker compose up -d --build
```

After updating, run health checks, authentication, schema/package gates, and a synthetic ticket lifecycle. Roll back to a previously verified artifact rather than rebuilding an old commit with a changed dependency graph.

## 10. Backups and recovery

The old approach of copying only `data.db` is insufficient: it can race SQLite writes and omits PocketBase files plus `/app/data` state. Use the versioned recovery tools and runbook:

- [Backup and disaster recovery](operations/backup-and-recovery.md)
- [Restore drill evidence template](operations/restore-drill-template.md)
- `scripts/backup.sh`
- `scripts/restore.sh`
- `scripts/verify-restore.py`

Create an encrypted backup:

```bash
export BACKUP_AGE_RECIPIENT='age1...'
export BACKUP_REASON='pre-deploy'
export BACKUP_OPERATOR='operator@example.com'
./scripts/backup.sh /secure/staging
```

The script stops `app` and `pocketbase` for a consistent single-node snapshot, archives both durable mounts, records component SHA-256 hashes in a manifest, encrypts the bundle with `age`, and restores the prior service state.

Restore only into a clean or isolated target unless responding to a declared incident:

```bash
export BACKUP_AGE_IDENTITY_FILE=/secure/backup-identity.txt
export RESTORE_CONFIRM='ERASE_AND_RESTORE_MANTLY'
export RESTORE_API_URL=https://api-restored.example.com
export RESTORE_PB_URL=https://api-restored.example.com/pb
export PB_ADMIN_EMAIL=<restored-superuser-email>
export PB_ADMIN_PASSWORD=<restored-superuser-password>
./scripts/restore.sh /secure/mantly-backup-<timestamp>.tar.gz.age
```

Production readiness requires:

- daily encrypted off-host backups;
- newest successful backup within the 24-hour RPO;
- 30-day rolling retention unless the customer contract states otherwise;
- at least one passed restore drill before the first real customer pilot and quarterly thereafter;
- deletion replay after restoring a snapshot older than a valid deletion request;
- backup encryption keys stored separately from backup objects.

A file that has never been restored and verified is not accepted as a backup.

## 11. Operations and incident readiness

Before production-like customer processing, complete:

- `SECURITY.md` reporting path;
- `security/threat-model.md` review for configured providers/connectors;
- `security/incident-response.md` with real contacts and credential-rotation procedures;
- `security/data-retention.md` with customer-specific periods;
- a restore drill and incident tabletop;
- production monitoring/alerting once the observability PR is merged.

## Troubleshooting

| Symptom | Likely cause / action |
| --- | --- |
| `502 Bad Gateway` | App or PocketBase not ready; inspect `docker compose ps` and redacted service logs |
| CORS error | `CORS_ORIGINS` and `PB_CORS_ORIGINS` must contain only the actual admin/add-in origins |
| Signup returns 404 | Signup is disabled or the frontend was built without SaaS signup support |
| PocketBase 401 | Superuser credentials/configuration mismatch; do not log the password |
| TLS certificate not issued | DNS or ports 80/443 are incorrect, or the deployment platform owns TLS termination |
| Backup script cannot discover a mount | The service/container or expected `/pb/pb_data` / `/app/data` mount is missing |
| Restore hash/integrity failure | Keep target isolated, preserve evidence, and try an earlier verified backup only after investigation |
| Restored service starts but data is incomplete | Do not resume traffic; run the full restore verification and reconcile post-backup events/deletions |

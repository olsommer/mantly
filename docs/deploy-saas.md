# Deploy Mantly — SaaS

Production deployment guide for the hosted SaaS version on Hetzner (or any VPS with Docker).

## Prerequisites

- Linux VPS with Docker and Docker Compose v2
- DNS for `mantly.io`, `app.mantly.io`, `addin.mantly.io`, and `api.mantly.io`
- A Google API key for Gemini

## 1. Clone and configure

```bash
git clone <repo-url> mantly
cd mantly
cp .env.example .env
```

Edit `.env` with your values:

```env
# Required
GOOGLE_API_KEY=<your-google-api-key>
JWT_SECRET=<generate: python3 -c "import secrets; print(secrets.token_hex(32))">
PB_ADMIN_EMAIL=admin@mantly.io
PB_ADMIN_PASSWORD=<strong-password>

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
```

## 2. Start the stack

```bash
docker compose up -d --build
```

This starts the API stack:

| Service      | Role                               | Port  |
|--------------|------------------------------------|-------|
| **caddy**    | Reverse proxy for `api.mantly.io`  | 80/443 (public) |
| **pocketbase** | Auth + data storage (SQLite)    | 8090 (internal) |
| **app**      | FastAPI backend                    | 8080 (internal) |

Caddy automatically provisions a Let's Encrypt TLS certificate for `api.mantly.io`.

## 3. Architecture overview

```
Internet
  │
  ▼
Caddy (:443, api.mantly.io)
  ├── /pb/*    → PocketBase (:8090)   — auth, user management
  └── /*       → FastAPI app (:8080)   — API + manifest assets
```

The admin SPA is hosted at `app.mantly.io`, the Outlook add-in SPA at `addin.mantly.io`, and the landing page at `mantly.io`.
Both SPAs call `https://api.mantly.io`; PocketBase is exposed as `https://api.mantly.io/pb`.
The SaaS API image is backend-only and does not bundle admin/add-in/landing assets.

## Coolify deployment

For the hosted SaaS setup, use four Coolify application resources in the same project/environment:

| Resource | Build pack | Domain | Dockerfile / compose |
|----------|------------|--------|----------------------|
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

# Optional LangSmith tracing for Inbox reply-composer / LangChain runs
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

Point DNS for all four names to the Coolify server. In the current production layout this means:

```text
mantly.io        A  <coolify-server-ip>
api.mantly.io    A  <coolify-server-ip>
app.mantly.io    A  <coolify-server-ip>
addin.mantly.io  A  <coolify-server-ip>
```

## 4. Verify deployment

```bash
# Health check
curl https://api.mantly.io/api/health

# PocketBase is reachable through Caddy
curl https://api.mantly.io/pb/api/health
```

## 5. PocketBase admin setup

1. Open `https://api.mantly.io/pb/_/` in a browser
2. Log in with `PB_ADMIN_EMAIL` / `PB_ADMIN_PASSWORD`
3. Configure SMTP for email verification and password reset:
   - Go to **Settings > Mail settings**
   - Enter your SMTP server details

## 6. Microsoft Store submission

The store-ready manifest is at `addin/manifest.store.xml` with `https://addin.mantly.io` for the taskpane and `https://api.mantly.io` for icon assets.

To submit:
1. Go to [Partner Center](https://partner.microsoft.com/dashboard/office/overview)
2. Create a new Office Add-in submission
3. Upload `addin/manifest.store.xml`
4. Provide screenshots, descriptions, and icon assets
5. Submit for certification

Once approved, tenants install the add-in from the Microsoft 365 App Store — no manifest download required.

## 7. Self-service signup

With `VITE_IS_SAAS=true`, the admin SPA at `https://app.mantly.io/` shows a signup form. New users can:

1. Enter company name, email, and password
2. A tenant and admin user are created automatically
3. They are immediately logged in with a JWT

## 8. Managing on-prem licenses

The SaaS instance acts as the license server for on-prem customers. Licenses are stored in the PocketBase `licenses` collection.

### Create a license (API)

```bash
curl -X POST https://api.mantly.io/api/admin/licenses \
  -H "Content-Type: application/json" \
  -d '{"tenant_name": "Law Firm XYZ", "max_users": 10, "expires_at": "2026-12-31T00:00:00Z"}'
```

This returns a 40-character hex license key to give to the customer.

### List licenses

```bash
curl https://api.mantly.io/api/admin/licenses
```

### Revoke a license

```bash
curl -X DELETE https://api.mantly.io/api/admin/licenses/<license-id>
```

You can also manage licenses directly in the PocketBase admin UI at `/pb/_/`.

## 9. Updating

```bash
cd mantly
git pull
docker compose up -d --build
```

Caddy preserves TLS certificates across restarts. PocketBase data is persisted in a Docker volume.

## 10. Backups

PocketBase stores all data in a single SQLite database inside the configured Docker volume. Back it up regularly:

```bash
# Copy the PB data directory from the volume
docker compose exec pocketbase cp /pb/pb_data/data.db /pb/pb_data/backup.db
docker cp "$(docker compose ps -q pocketbase)":/pb/pb_data/backup.db ./backup-$(date +%Y%m%d).db
```

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| `502 Bad Gateway` | App container not ready yet — wait for healthcheck or check `docker compose logs app` |
| `CORS error` in browser | `CORS_ORIGINS` and `PB_CORS_ORIGINS` must include `https://app.mantly.io` and `https://addin.mantly.io` |
| Signup returns 404 | `VITE_IS_SAAS` not set to `true` — rebuild the app image |
| PocketBase 401 | `PB_ADMIN_EMAIL` / `PB_ADMIN_PASSWORD` mismatch — check `.env` |
| TLS certificate not issued | DNS not pointing to server, or port 80/443 blocked by firewall |

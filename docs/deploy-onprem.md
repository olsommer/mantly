# Deploy Mantly — Commercial On-Premises

This guide covers Mantly's separately licensed commercial distribution. It
ships as pre-built Docker images with compiled Python and validates a commercial
license against the Mantly SaaS server. Contract terms govern that distribution.

For the AGPL-3.0 Community edition, build from source using
[`docker-compose.community.yml`](https://github.com/olsommer/mantly/blob/main/docker-compose.community.yml)
and follow the
[Community deployment guide](https://github.com/olsommer/mantly/blob/main/docs/deploy-community.md).
Community self-hosting uses no Mantly license key or license-server check.

## Prerequisites

- Linux server with Docker and Docker Compose v2
- A domain name with DNS pointing to the server (e.g. `mail.yourfirm.com`)
- A Google API key for Gemini (the customer provides their own)
- A license key from Mantly (contact support@mantly.io)
- Outbound HTTPS access to `ghcr.io` (image pulls) and `api.mantly.io` (license validation)

## 1. Get the deployment package

Mantly provides a `.tar.gz` package containing:

```
docker-compose.yml    # Pre-configured to pull images from ghcr.io
.env.example          # Configuration template
Caddyfile             # Reverse proxy config (automatic HTTPS)
support-launch-gate.sh # Deploy-time support launch proof gate
support-schema-gate.sh # Standalone PocketBase support schema gate
support-channel-lifecycle-smoke.sh # Focused per-channel proof runner
support-channel-activation-plan.sh # Channel setup handoff export
release-manifest.json # Image tag, support scripts, package-gate, and launch-proof handoff metadata
README.md             # This file
```

Extract the package:

```bash
tar xzf mantly-1.0.0.tar.gz
cd mantly-1.0.0
```

## 2. Authenticate with the container registry

```bash
# Mantly provides a read-only access token for pulling images
echo "<token-provided-by-mantly>" | docker login ghcr.io -u mantly-customer --password-stdin
```

## 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required — generate a random secret
JWT_SECRET=<generate: python3 -c "import secrets; print(secrets.token_hex(32))">

# PocketBase admin credentials
PB_ADMIN_EMAIL=admin@yourfirm.com
PB_ADMIN_PASSWORD=<strong-password>

# Your domain
DOMAIN=mail.yourfirm.com
PUBLIC_URL=https://mail.yourfirm.com

# License (provided by Mantly)
LICENSE_KEY=<your-40-char-hex-license-key>
LICENSE_SERVER_URL=https://api.mantly.io

# Unique add-in ID — generate once and keep forever
# python3 -c "import uuid; print(uuid.uuid4())"
ADDIN_ID=<your-generated-uuid>

# Optional managed LLM fallback. Tenants can also configure BYOK in Admin.
MANTLY_MANAGED_LLM_PROVIDER=gemini
MANTLY_MANAGED_LLM_MODEL=gemini-3-flash-preview
MANTLY_MANAGED_LLM_API_KEY=<optional-managed-key>

# Optional support launch gate values.
SUPPORT_PROJECT_ID=<project-id-after-first-login>
ADMIN_AUTH_TOKEN=<admin-jwt-for-launch-gate>

# Container registry. Package defaults to ghcr.io/isarlabs unless Mantly
# provided a customer-specific registry.
REGISTRY=ghcr.io/isarlabs
```

## 4. Start the stack

```bash
docker compose up -d
```

Docker pulls the images automatically on first run. Services started:

| Service        | Role                            | Port            |
|----------------|---------------------------------|-----------------|
| **caddy**      | Reverse proxy, automatic HTTPS  | 80/443 (public) |
| **pocketbase** | Auth + data storage (SQLite)    | 8090 (internal) |
| **app**        | FastAPI backend + SPAs          | 8080 (internal) |

## 5. Verify deployment

```bash
# Health check (includes license status)
curl https://mail.yourfirm.com/api/health

# Expected: {"status": "ok", "license": {"required": true, "valid": true, ...}}
```

For support-workspace launch readiness, gate deploys on the machine-readable launch proof:

```bash
# Optional standalone schema repair/check
./support-schema-gate.sh

# First proof run after install or channel changes
./support-launch-gate.sh --run

# Steady-state gate for deploy scripts
./support-launch-gate.sh

# Local handoff artifact written by the wrapper
ls -l support-launch-proof.json

# Provider setup handoff for ops/customer onboarding
./support-channel-activation-plan.sh
ls -l support-channel-activation-plan.json
```

`support-launch-gate.sh` reads `.env` and runs
`python -m automail.support.launch_gate --schema-gate --bundle-file
/app/data/support-launch-proof.json` inside the running `app` container. It
bootstraps/checks PocketBase support schema first, then fetches or runs launch
proof, and writes the portable launch-proof bundle into the persisted `app_data`
volume by default, then copies it to `./support-launch-proof.json` on the host
when the file exists. It defaults to `http://localhost:8080` inside that
container; set `MANTLY_BASE_URL` only if you need to test through the public
reverse proxy. `--run` calls the admin launch-proof runner first, then
evaluates the returned proof; the plain command only reads current readiness.
Set `SUPPORT_SKIP_SCHEMA_GATE=true` only for an intentional app-only proof, or
`SUPPORT_SCHEMA_GATE_NO_BOOTSTRAP=true` for a read-only schema preflight. Set
`SUPPORT_LAUNCH_GATE_BUNDLE_FILE` to override the bundle path inside the
container, or to an empty value to skip writing the default bundle. Set
`SUPPORT_LAUNCH_GATE_BUNDLE_OUT` to change the local copy path, or
`SUPPORT_LAUNCH_GATE_COPY_BUNDLE=false` to leave the bundle only in the app
container volume. The copied bundle includes `activationPlan` from the channel
activation-plan API when it can be fetched, and `activationPlanError` when that
handoff fetch fails.

For live Slack, Discord, Telegram, and Teams proof, set smoke targets in each
channel config before running `--run`. Request payload values still override
these, but deploy-time launch proof uses config defaults:

```json
{
  "smokeChannelId": "C0123456789",
  "smokeThreadId": "",
  "smokeThreadTs": "",
  "smokeProviderMessageId": "",
  "smokeToAddress": "",
  "smokeConversationId": "",
  "smokeReplyToId": "",
  "smokeServiceUrl": ""
}
```

Use `smokeChatId` for Telegram when the bot target is a chat id. Use
`smokeThreadTs` for Slack thread replies, `smokeThreadId` for Discord threads,
and `smokeConversationId`/`smokeReplyToId`/`smokeServiceUrl` for Teams Bot
Framework replies. Native provider launch proof is blocked until these config
values point at real provider targets; synthetic sample ids can still exercise
local adapter code, but they do not count as launch-ready provider evidence.

`support-schema-gate.sh` is still useful as a standalone repair/read-only
check. It runs `python -m automail.support.schema_gate` inside the app
container, executes the same idempotent schema bootstrap as app startup, then
verifies required support collections, fields, and migration files. Use
`./support-schema-gate.sh --no-bootstrap` when you only want a read-only schema
check without launch proof.

Release builders also run `python -m automail.support.package_gate` before
cutting the customer archive or pushing on-prem images. That static package
gate verifies the support workspace source spine, migrations, admin routes,
deploy wrappers, and customer docs are present before a release is produced.
`scripts/release-onprem.sh` builds and pushes the images, then runs
`scripts/package-customer.sh` so the customer archive and `release-manifest.json`
use the same registry and image tag. The manifest also records the static
`supportPackageGate` readiness result and check count used to cut the archive,
plus `supportChannelActivationPlan` metadata for the Admin Channels handoff
download. After first login, run `./support-channel-activation-plan.sh` or open
Admin Channels and download `support-channel-activation-plan-<project-id>.json`;
if secrets are missing, the wrapper also writes
`support-channel-activation-secrets.env` as the blank provider setup template.
The same handoff can be fetched manually without a browser:

```bash
curl -H "Authorization: Bearer $ADMIN_AUTH_TOKEN" \
  "$PUBLIC_URL/api/admin/projects/$SUPPORT_PROJECT_ID/channels/activation-plan" \
  > support-channel-activation-plan.json
```
Override `SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT`,
`SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT`, or
`SUPPORT_CHANNEL_ACTIVATION_WRITE_SECRETS=false` when the default local
handoff filenames are not appropriate.
Set `REGISTRY=...` before release when publishing to a customer-specific
registry. Set `SKIP_CUSTOMER_PACKAGE=true` only when intentionally publishing
images without a customer handoff archive.

For a focused channel proof, run the packaged lifecycle smoke runner against a
specific channel. It calls the same Admin Channels lifecycle-smoke endpoint as
launch proof from inside the app container, defaults to HTTP transport, and
exits `0` only when the provider endpoint creates a ticket, an
approval-required reply is approved, and delivery is sent:

```bash
SUPPORT_PROJECT_ID=<project-id> \
ADMIN_AUTH_TOKEN=<admin-api-token> \
./support-channel-lifecycle-smoke.sh \
  --channel-key slack-main \
  --transport http
```

Exit codes:

| Code | Meaning |
|------|---------|
| `0`  | Schema and required channel launch proof are ready. Email requires successful inbound sync plus outbound delivery proof; web chat requires a ticket-linked visitor session; external providers require HTTP inbound smoke, outbound smoke, and HTTP lifecycle smoke proof. |
| `1`  | Config, auth, network, or API error |
| `2`  | Launch proof is blocked by schema drift, missing smoke, failed delivery, or another blocker |

## 6. Optional Channel Bridges

Slack, Telegram, WhatsApp, Messenger, SMS/Twilio, generic webhooks, web chat,
and email terminate directly on the main `app` service. Teams and Discord
usually need a small public bridge because their runtime event surfaces are
bot/activity or Gateway driven. The same bridge can also front any HTTP-capable
adapter when the provider cannot reach the private app service directly.

Run the forwarding bridge when an external adapter should forward provider
events into the core app:

```bash
docker compose --profile support-bridge up -d support-bridge
```

Required bridge values:

```env
SUPPORT_BRIDGE_PROJECT_ID=<project-id>
SUPPORT_BRIDGE_TOKEN_ENV=SUPPORT_TEAMS_WEBHOOK_TOKEN # optional override
SUPPORT_TEAMS_WEBHOOK_TOKEN=<shared-forward-token>
SUPPORT_DISCORD_WEBHOOK_TOKEN=<shared-forward-token>
```

Without `SUPPORT_BRIDGE_TOKEN_ENV`, the bridge uses provider defaults:
`SUPPORT_SLACK_WEBHOOK_TOKEN`, `SUPPORT_TEAMS_WEBHOOK_TOKEN`,
`SUPPORT_DISCORD_WEBHOOK_TOKEN`, `SUPPORT_TELEGRAM_WEBHOOK_TOKEN`,
`SUPPORT_WHATSAPP_WEBHOOK_TOKEN`, `SUPPORT_MESSENGER_WEBHOOK_TOKEN`,
`SUPPORT_TWILIO_WEBHOOK_TOKEN`, or `SUPPORT_CHANNEL_WEBHOOK_TOKEN`.

The bridge exposes `/bridge/teams/{channel_key}`,
`/bridge/discord/{channel_key}`, and `/bridge/{provider}/{channel_key}` for
`slack`, `telegram`, `whatsapp`, `messenger`, `sms`, `twilio`, and
`channel-webhooks` on `SUPPORT_BRIDGE_PORT` (default `8095`). WhatsApp and
Messenger also support Meta webhook verification through
`GET /bridge/{provider}/{channel_key}?hub.mode=...&hub.verify_token=...&hub.challenge=...`,
which proxies the challenge to the core app so provider setup works when the
core app is private. Admin Channels includes this as `metaBridgeConfig` in the
copyable install package for WhatsApp and Messenger channels.
Set `SUPPORT_BRIDGE_INBOUND_TOKEN` to require `X-Support-Bridge-Token` from the
provider-facing adapter. Set `SUPPORT_BRIDGE_SIGNATURE_SECRET` when channel
config uses timestamp-bound HMAC proof instead of token forwarding.

Run the built-in Discord Gateway worker when this deployment should listen to
Discord directly:

```bash
docker compose --profile discord-gateway up -d discord-gateway
```

Required Gateway values:

```env
SUPPORT_BRIDGE_PROJECT_ID=<project-id>
SUPPORT_BRIDGE_DISCORD_CHANNEL_KEY=discord-main
SUPPORT_DISCORD_BOT_TOKEN=<discord-bot-token>
SUPPORT_DISCORD_WEBHOOK_TOKEN=<core-forward-token>
```

Discord message content is a privileged intent. Enable/approve Message Content
in the Discord developer portal before relying on ticket text ingestion.

## 7. License validation

On startup the app validates the license key against `LICENSE_SERVER_URL`. It then re-validates every 12 hours in the background.

- **Grace period**: If the license server becomes unreachable, the app continues operating for 48 hours using a cached validation. After that, API requests return `503 Service Unavailable`.
- **Health/static exemptions**: `/api/health`, `/addin/*`, and `/assets/*` are never blocked.
- **Cache file**: Stored at `/app/data/license_cache.json` inside the container. The `/app/data` volume persists across restarts.
- **Instance binding**: On first validation, the license is bound to a machine fingerprint. It cannot be reused on a different server.

## 8. Install the Outlook add-in

### Option A: Side-load via Microsoft 365 Admin Centre (recommended)

1. Log into the admin SPA at `https://mail.yourfirm.com/`
2. Go to **Settings** and click **Download Manifest**
3. The downloaded `manifest.xml` has your domain and add-in ID baked in
4. Go to [admin.microsoft.com](https://admin.microsoft.com) > **Settings** > **Integrated apps**
5. Click **Upload custom apps** and upload the manifest
6. Assign to the relevant users or groups
7. The add-in appears in Outlook as "Mantly"

### Option B: Individual side-load (for testing)

1. In Outlook (web), click the **Get Add-ins** button
2. Choose **My add-ins** > **Upload a custom add-in**
3. Upload the downloaded manifest file

## 9. Create users

1. Open `https://mail.yourfirm.com/` and log in with the PB admin credentials
2. Go to **User Management** to add users
3. New users receive a temporary password and must change it on first login

## 10. PocketBase admin

The PocketBase admin UI is available at `https://mail.yourfirm.com/pb/_/`. Use this for:

- Configuring SMTP (Settings > Mail settings) for email verification
- Viewing raw data records
- Managing collections

## 11. Updating

When Mantly provides a new version:

```bash
# Pull the latest images and restart
docker compose pull
docker compose up -d
```

Or pin a specific version in `.env`:

```env
VERSION=1.1.0
```

Data is persisted in Docker volumes (`pb_data`, `app_data`). Updates do not lose data.

## 12. Backups

```bash
# Back up PocketBase data
docker cp "$(docker compose ps -q pocketbase)":/pb/pb_data/data.db \
  ./backup-$(date +%Y%m%d).db
```

Store backups off-server. PocketBase's `data.db` contains tenant data, users, chats, projects, evals, feedback, monitor runs, and billing/license state.

## 13. Network requirements

| Direction | Destination         | Port | Purpose                          |
|-----------|---------------------|------|----------------------------------|
| Outbound  | `ghcr.io`           | 443  | Pull Docker images               |
| Inbound   | Your server         | 80, 443 | HTTP/HTTPS from users         |
| Inbound   | Your server         | 8095 | Optional channel bridge |
| Outbound  | `api.mantly.io`     | 443  | License validation (every 12h)   |
| Outbound  | Google APIs         | 443  | Gemini AI model calls            |
| Outbound  | Let's Encrypt       | 80   | TLS certificate issuance (ACME)  |

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| `503 License validation failed` | License expired, revoked, or server unreachable for >48h. Contact support@mantly.io |
| `503` after server migration | License is bound to the previous machine. Contact Mantly for a key reset |
| `502 Bad Gateway` | App container not ready — check `docker compose logs app` |
| Add-in not visible in Outlook | Manifest not uploaded in admin centre, or wrong `ADDIN_ID` |
| TLS certificate not issued | DNS not pointing to server, or ports 80/443 blocked |
| PocketBase 401 | `PB_ADMIN_EMAIL` / `PB_ADMIN_PASSWORD` mismatch |

## Support

- Email: support@mantly.io
- License issues: provide your license key prefix (first 8 characters)

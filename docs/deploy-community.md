# Self-host Mantly Community

Mantly Community is the source-based, AGPL-3.0 edition. This deployment builds
the application from the checked-out source and does not configure a Mantly
license key, license server, Stripe, or managed SaaS tenancy.

Mantly Community is currently a preview release. Pin a reviewed `v0.1.x` tag,
commit, or container digest; do not automate production deployments from a
moving `main` branch.

## Prerequisites

- Linux, macOS, or Windows with Docker and Docker Compose v2.
- A source checkout of `https://github.com/olsommer/mantly`.
- For public HTTPS: a hostname pointing to the host and inbound ports 80/443.
- An LLM provider API key or compatible gateway for AI processing.

## 1. Configure

Create a private environment file:

```sh
cp .env.community.example .env.community
```

Generate independent secrets and a stable Outlook add-in identifier:

```sh
openssl rand -hex 32
openssl rand -base64 36
uuidgen | tr '[:upper:]' '[:lower:]'
```

Edit `.env.community` and replace every placeholder. At minimum set:

- `PB_ADMIN_EMAIL` and `PB_ADMIN_PASSWORD` for PocketBase administration.
- `JWT_SECRET` for Mantly session tokens.
- `SETUP_ADMIN_EMAIL` and `SETUP_ADMIN_PASSWORD` for the first Mantly owner.
- `ADDIN_ID` to the generated UUID; retain it across upgrades.
- `COMPANY_NAME`.
- `MANTLY_SOURCE_URL` to the exact corresponding source for the deployed build
  if you distribute or operate a modified version.

For local HTTP, keep the defaults:

```env
DOMAIN=:80
PUBLIC_URL=http://localhost:8080
MANTLY_HTTP_PORT=8080
MANTLY_HTTPS_PORT=8443
```

For a public deployment, configure DNS first, then use:

```env
DOMAIN=support.example.com
PUBLIC_URL=https://support.example.com
MANTLY_HTTP_PORT=80
MANTLY_HTTPS_PORT=443
```

Caddy obtains and renews the TLS certificate. Do not expose PocketBase port
8090 or application port 8080 directly; both remain on the Compose network.

## 2. Validate and start

Resolve the Compose model before creating containers:

```sh
docker compose --env-file .env.community \
  -f docker-compose.community.yml config --quiet
```

Build from the current source checkout and start the stack:

```sh
docker compose --env-file .env.community \
  -f docker-compose.community.yml up -d --build
```

The stack contains:

| Service | Purpose | Public exposure |
| --- | --- | --- |
| `caddy` | HTTP/HTTPS reverse proxy | Configured host ports |
| `pocketbase` | Authentication and application data | `/pb/*` through Caddy |
| `app` | FastAPI, Admin SPA, and Outlook add-in | All remaining paths |

## 3. Verify

For the local defaults:

```sh
curl --fail http://localhost:8080/api/health
docker compose --env-file .env.community \
  -f docker-compose.community.yml ps
```

A healthy response reports `status: healthy` and PocketBase `status: ok`.
Community mode omits the commercial `license` status object because no license
middleware is configured.

Review logs without printing `.env.community`:

```sh
docker compose --env-file .env.community \
  -f docker-compose.community.yml logs --tail=200 app pocketbase caddy
```

## 4. First login

The first boot creates one tenant, one default project, and the root user named
by `SETUP_ADMIN_EMAIL`.

Open `PUBLIC_URL`, enter `SETUP_ADMIN_EMAIL`, and sign in directly with
`SETUP_ADMIN_PASSWORD`. Password login is enabled automatically for the
bootstrap user.

Mantly immediately requires a password change. Use `SETUP_ADMIN_PASSWORD` as
the current password and choose a new, unique password for normal use. The
bootstrap values are ignored after the first tenant exists, but Compose still
expects them to remain defined for container configuration.

After login, configure the LLM provider in Mantly Settings. Community supports
customer-provided provider keys and compatible custom gateways. The optional
`MANTLY_MANAGED_LLM_*` environment values provide an instance-wide fallback;
they are not required for license validation.

## No license phone-home

`docker-compose.community.yml` deliberately sets `IS_SAAS=false`,
`MANTLY_DEPLOYMENT_MODE=self_hosted`, and `MANTLY_EDITION=community`, while
defining no `LICENSE_KEY` or `LICENSE_SERVER_URL`. Therefore Mantly's commercial
license client and blocking middleware remain disabled.

Normal product integrations can still make outbound requests when configured,
including LLM providers, email servers, support channels, CRM systems, and
Caddy's certificate authority. Operators remain responsible for reviewing and
controlling those destinations.

## Back up and restore

PocketBase data and application attachments live in named Docker volumes. Stop
writes before taking a filesystem-level copy:

```sh
mkdir -p backups
docker compose --env-file .env.community \
  -f docker-compose.community.yml stop app pocketbase
docker compose --env-file .env.community \
  -f docker-compose.community.yml cp pocketbase:/pb/pb_data ./backups/pb_data
docker compose --env-file .env.community \
  -f docker-compose.community.yml cp app:/app/data ./backups/app_data
docker compose --env-file .env.community \
  -f docker-compose.community.yml start pocketbase app
```

Test restoration on a separate instance. Store backups encrypted and outside
the deployment host.

## Update

Back up first, fetch the reviewed release or commit, then rebuild:

```sh
git fetch --tags origin
git checkout <reviewed-tag-or-commit>
docker compose --env-file .env.community \
  -f docker-compose.community.yml up -d --build
```

Never remove the named volumes during an update. Review release notes and
migrations before moving between versions.

## Source and AGPL obligations

The corresponding source is this repository. Preserve license and copyright
notices when redistributing Mantly. Section 13 of the AGPL requires operators of
a modified network-accessible version to offer the corresponding source to
users interacting with that version. The Admin sidebar exposes
`MANTLY_SOURCE_URL` so users can reach that offer. Obtain legal advice for a
specific distribution or modification model.

The separately licensed pre-built commercial distribution has a different
installation path; see [Commercial on-premises deployment](deploy-onprem.md).

## Stop or remove

Stop containers while retaining data:

```sh
docker compose --env-file .env.community \
  -f docker-compose.community.yml down
```

Do not add `--volumes` unless permanent deletion of all Community instance data
is intended and verified backups exist.

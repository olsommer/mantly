# Mantly

**Customer support that runs itself.**

Mantly is an agentic omnichannel customer-support platform. It turns messages
into tickets, activates company-defined runbooks, performs permitted actions,
involves humans where configured, and replies through the originating channel.

> **Status:** Active development. The [product vision](docs/product-vision.md)
> describes intended direction, not production-readiness claims. Current
> implementation detail lives in the
> [support-system RFC](docs/pylon-pivot-rfc.md).

## Product

| Pillar | Purpose |
| --- | --- |
| **Inbox** | Omnichannel ticket inbox and system of record. |
| **Runbook Agent** | Matches executable runbooks and handles configured actions and responses. |
| **Knowledge Agent** | Helps humans investigate tickets using permitted company knowledge. |

```text
channel -> ticket -> runbook or human handling -> actions + response -> channel
```

Mantly prioritizes higher full-automation rates, lower cost per resolution,
faster support, and consistent answer quality. It should not become a generic
workflow builder or a legacy helpdesk with an AI sidebar.

## Repository

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI API, agent runtime, support domain, migrations, and tests |
| `admin/` | React/Vite support workspace and Inbox |
| `addin/` | React/Vite Outlook add-in |
| `landing/` | React/Vite marketing site |
| `pocketbase/` | PocketBase image and startup logic |
| `demo/` | Demo fixtures, actions, pipelines, and sample data |
| `deploy/` | Customer deployment assets |
| `docs/` | Product, implementation, and deployment documentation |
| `scripts/` | Quality, release, packaging, and smoke-test tooling |

## Local development

Requirements:

- Python 3.12 or newer and [`uv`](https://docs.astral.sh/uv/).
- Node.js 22 and npm.
- Docker for the local PocketBase container.

### PocketBase

Build and start the repository's PocketBase image:

```sh
export PB_ADMIN_EMAIL='admin@example.test'
export PB_ADMIN_PASSWORD='replace-this-local-password'

docker build -f pocketbase/Dockerfile -t mantly-pocketbase .
docker run --rm --name mantly-pocketbase \
  -p 8090:8090 \
  -e PB_ADMIN_EMAIL \
  -e PB_ADMIN_PASSWORD \
  -v mantly-pocketbase-data:/pb/pb_data \
  mantly-pocketbase
```

PocketBase runs at `http://localhost:8090`.

### API

In another terminal, copy the configuration template and set
`PB_ADMIN_EMAIL`/`PB_ADMIN_PASSWORD` to the PocketBase values above:

```sh
cd backend
cp config.env.example config.env
uv sync
uv run python -m automail.main
```

The API runs at `http://localhost:8080`.

### Admin

In another terminal:

```sh
cd admin
npm ci
npm run dev
```

The admin app runs at `http://localhost:5174`.

Optional frontend development:

| App | Command | Default URL |
| --- | --- | --- |
| Outlook add-in | `cd addin && npm ci && npm run dev` | `http://localhost:5173/addin/` |
| Landing page | `cd landing && npm ci && npm run dev` | `http://localhost:5175` |

## Quality checks

Run repository lint, type, and frontend build checks, then backend tests:

```sh
./scripts/check-quality.sh
(cd backend && uv run pytest)
```

## Documentation

- [Product vision](docs/product-vision.md)
- [Current support-system RFC](docs/pylon-pivot-rfc.md)
- [Founder-led pilot runbook](PILOT_RUNBOOK.md)
- [SaaS deployment](docs/deploy-saas.md)
- [Enterprise on-premises deployment](docs/deploy-onprem.md)

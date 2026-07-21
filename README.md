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
| **Inbox** | Omnichannel ticket system of record and one final response composer. |
| **Runbook Agent** | Matches one or more concern-scoped runbooks and returns structured action results. |
| **Knowledge Agent** | Helps humans investigate tickets using permitted company knowledge. |

```text
channel -> ticket -> concern runbooks -> actions + structured results
        -> Inbox response composer -> one response -> channel
```

Mantly prioritizes higher full-automation rates, lower cost per resolution,
faster support, and consistent answer quality. It should not become a generic
workflow builder or a legacy helpdesk with an AI sidebar.

## Editions and licensing

Unless a file carries an explicit different notice, this repository is Mantly
Community and is licensed under `AGPL-3.0-only`; see [LICENSE](LICENSE).

- **Mantly Community** is the source-based self-hosted edition. It requires no
  Mantly license key and performs no commercial license-server check. Start with
  the [Community deployment guide](docs/deploy-community.md).
- **Mantly Cloud** is the hosted service operated by Mantly.
- **Commercial deployments** may add managed delivery, support, or separately
  licensed terms for Business and Enterprise customers. The commercial
  pre-built-image path is documented separately and does not change the rights
  granted for Community source.

Mantly Cloud and independently developed commercial components may use separate
terms. External Community contributions are not relicensed without separate,
explicit contributor permission. Third-party components remain under their
respective licenses. See the [edition matrix](docs/editions.md) and
[trademark policy](TRADEMARKS.md).

## Repository

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI API, agent runtime, support domain, migrations, and tests |
| `admin/` | React/Vite support workspace and Inbox |
| `addin/` | React/Vite Outlook add-in |
| `landing/` | React/Vite marketing site |
| `pocketbase/` | PocketBase image and startup logic |
| `demo/` | Demo fixtures, actions, pipelines, and sample data |
| `e2e/` | Reusable test personas, synthetic knowledge, tool facts, and lifecycle expectations |
| `deploy/` | Community proxy config and commercial customer deployment assets |
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

Run the enforced backend lint/tests and frontend lint/build checks:

```sh
./scripts/check-quality.sh
```

Strict Pyright currently has a legacy baseline and is opt-in while that backlog
is reduced:

```sh
MANTLY_STRICT_PYRIGHT=1 ./scripts/check-quality.sh
```

## Documentation

- [Product vision](docs/product-vision.md)
- [Current support-system RFC](docs/pylon-pivot-rfc.md)
- [Founder-led pilot runbook](PILOT_RUNBOOK.md)
- [Community self-hosted deployment](docs/deploy-community.md)
- [Editions and deployment modes](docs/editions.md)
- [SaaS deployment](docs/deploy-saas.md)
- [Commercial on-premises deployment](docs/deploy-onprem.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Trademark policy](TRADEMARKS.md)

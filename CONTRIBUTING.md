# Contributing to Mantly

Thanks for improving Mantly. Contributions should keep the Community edition
useful as a real self-hosted support system, not a limited product demo.

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). Report
security problems privately as described in [SECURITY.md](SECURITY.md).

## Before opening a pull request

1. Open or reference an issue for substantial behavior or architecture changes.
2. Keep the change focused. Do not mix unrelated formatting or generated files.
3. Never commit credentials, customer data, local databases, or `.env` files.
4. Add or update tests and documentation for changed behavior.
5. Explain user impact, migration risk, and verification in the pull request.

## Local checks

For application changes, run the repository quality gates:

```sh
./scripts/check-quality.sh
```

The strict Pyright pass is temporarily opt-in while the existing type backlog
is reduced. Run it with `MANTLY_STRICT_PYRIGHT=1 ./scripts/check-quality.sh` when
working on typing and avoid increasing the reported baseline.

For Community deployment changes, also validate the resolved Compose model:

```sh
docker compose --env-file .env.community.example \
  -f docker-compose.community.yml config --quiet
```

See [README.md](README.md) for local development setup and
[docs/deploy-community.md](docs/deploy-community.md) for the self-host path.

## Licensing contributions

Unless a file states otherwise, contributions are submitted under
`AGPL-3.0-only`, the same license as the Community source. Only submit work you
have the right to license. Mantly does not currently require a contributor
license agreement.

Mantly Cloud and independently developed commercial components may use separate
terms. External contributions are not relicensed into proprietary software
without the contributor's separate, explicit permission. The Community license
continues to apply to Community source received under it.

Project and product names remain subject to the [trademark policy](TRADEMARKS.md),
independently of the source-code license.

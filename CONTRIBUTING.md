# Contributing to Mantly

Thanks for improving Mantly. Contributions should keep the Community edition
useful as a real self-hosted support system, not a limited product demo.

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). Report
security problems privately as described in [SECURITY.md](SECURITY.md).

## Before opening a pull request

1. Open or reference an issue for substantial behavior or architecture changes.
2. Keep the change focused. Do not mix unrelated formatting or generated files.
3. Never commit credentials, customer data, local databases, production exports,
   model weights, or `.env` files.
4. Add or update tests and documentation for changed behavior and failure paths.
5. Explain user impact, migration risk, and verification in the pull request.
6. Identify third-party code, generated material, assets, data, fonts, media,
   prompts, or documentation plus their provenance and license terms.

Only submit work you created or have the authority to license. Do not submit
code copied from another project, generated from confidential or restricted
sources, or material under terms incompatible with `AGPL-3.0-only`.

## Development requirements

- Preserve tenant isolation, permissions, idempotency, audit evidence, recovery,
  and safe manual fallback.
- Use synthetic fixtures and redacted evidence.
- Update security, privacy, operations, provider, and license evidence when a
  data, tool, provider, distribution, or runtime boundary changes.
- Keep commits and pull requests explicit about generated material and
  third-party sources.
- Add authorization, replay, unsafe-input, and failure tests when changing a
  trust boundary.

## Local checks

For application changes, run the complete repository quality gate:

```sh
./scripts/check-quality.sh
```

Strict Pyright is part of this gate. Do not introduce a new type-error baseline.

For Community deployment changes, also validate the resolved Compose model:

```sh
docker compose --env-file .env.community.example \
  -f docker-compose.community.yml config --quiet
```

See [README.md](README.md) for local development setup and
[docs/deploy-community.md](docs/deploy-community.md) for the self-host path.

## Licensing contributions

Unless a file states otherwise, contributions are submitted under
`AGPL-3.0-only`, the same license as the Community source. By submitting work,
you confirm that you created it or have the right to submit it under those terms
and that you disclosed any third-party or generated material.

Mantly does not currently require a Contributor License Agreement. Mantly Cloud
and independently developed commercial components may use separate terms.
External contributions are not relicensed into proprietary software without the
contributor's separate, explicit permission. The Community license continues to
apply to Community source received under it.

Project and product names remain subject to the [trademark policy](TRADEMARKS.md),
independently of the source-code license.

## Review and acceptance

Maintainers may reject or require replacement of a contribution when rights,
provenance, security, quality, or product scope are unclear. Acceptance does not
override third-party rights or the repository license.

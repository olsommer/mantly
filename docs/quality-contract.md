# Repository quality contract

Status: **Merge gate**

The same core checks run in GitHub Actions and through
`scripts/check-quality.sh`. A pull request is not production-ready merely because
one focused test passes.

## Required checks

### Backend

- Locked dependency installation with `uv sync --frozen`.
- Ruff across `automail` and all tests.
- Strict Pyright across the production package.
- Full pytest discovery and execution under `backend/tests`.
- Branch coverage of at least 60% across `automail`.
- Support package readiness gate.
- Clean PocketBase bootstrap and second-run idempotency.
- Tenant-isolation and delivery claim/fencing integration tests.

### Frontends

For `admin`, `addin`, and `landing`:

- locked `npm ci` installation;
- ESLint with zero warnings;
- TypeScript and production Vite build.

### Production lifecycle

- real PocketBase, FastAPI, admin, and add-in auth lifecycle in Chromium;
- first-user provisioning and forced password change;
- deletion prevents subsequent authentication;
- production combined image, SaaS API image, and PocketBase image build.

### Security and repository policy

- secret scan;
- Python and Node production dependency audit;
- container/configuration scan;
- required security, scope, pilot, and merge-order assets;
- machine-readable pilot metric schema validation.

## Local usage

Full core contract without browser E2E:

```bash
./scripts/check-quality.sh
```

Include the auth lifecycle E2E:

```bash
SKIP_E2E=false ./scripts/check-quality.sh
```

Reuse already installed dependencies:

```bash
SKIP_INSTALL=true ./scripts/check-quality.sh
```

Skipping installation or E2E is a local iteration convenience. It does not
remove the corresponding pull-request requirement.

## Coverage policy

The 60% repository threshold is a minimum floor, not a target. New or changed
security-critical code should have focused tests for its decision and failure
paths even when total coverage is already above the threshold.

Critical paths include:

- tenant and project authorization;
- authentication and password lifecycle;
- runbook publication and permission enforcement;
- prompt-injection and phishing controls;
- external action schema, approval, idempotency, retry, and partial failure;
- inbound event deduplication;
- outbound claim, fencing, retry, and delivery state;
- backup/restore verification;
- retention and deletion;
- logging and telemetry redaction.

Generated code, demo-only fixtures, or unreachable branches must not be added to
inflate the denominator or hide untested production behavior.

## Test isolation

Ordinary pull-request checks must not depend on paid provider credentials or
mutable external services. Model, channel, payment, and connector behavior should
use deterministic fixtures, local test services, or explicit integration jobs.

A live-provider test must:

- be opt-in;
- identify cost and data exposure;
- use a non-production account;
- never be the only verification of a safety or correctness property.

## Flaky tests

Do not solve flakiness by adding broad retries. A retry may be used only when the
asserted property genuinely includes transient behavior and the test still fails
on a deterministic defect.

A quarantined check requires:

- an issue;
- owner;
- reason;
- expiry date;
- alternate detection or risk acceptance.

## Merge and release rules

- All required checks must pass on the exact head approved for merge.
- A later PR in the production-hardening stack is not merged before its
  predecessors.
- A red security or tenant-isolation check is not bypassed for schedule pressure.
- A dependency finding may be temporarily accepted only through the documented
  risk-acceptance process.
- Production deployment records the merged commit/image digest and successful
  workflow run.
- Release rollback must use an already verified artifact rather than rebuilding
  an old commit with a changed dependency environment.

## Known boundary

The auth lifecycle E2E is a real multi-service browser journey. The complete
Inbox ticket-to-delivery journey continues to be covered by the backend support
suite and PocketBase delivery integration until a deterministic browser fixture
for ticket ingestion and outbound delivery is added. A future change must not
claim broader UI E2E coverage without an executable test.

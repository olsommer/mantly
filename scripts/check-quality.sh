#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/mantly-uv-cache}"
export AUTOMAIL_BACKGROUND_IO="${AUTOMAIL_BACKGROUND_IO:-disabled}"
export GOOGLE_API_KEY="${GOOGLE_API_KEY:-dummy-local-quality-key}"
export REQUIRE_AUTH="${REQUIRE_AUTH:-false}"

SKIP_INSTALL="${SKIP_INSTALL:-false}"
SKIP_E2E="${SKIP_E2E:-true}"

run() {
  echo
  echo "== $1 =="
  shift
  "$@"
}

if [[ "$SKIP_INSTALL" != "true" ]]; then
  run "Backend locked dependency sync" bash -lc "cd '$ROOT/backend' && uv sync --frozen"
  for app in admin addin landing; do
    run "$app locked dependency install" bash -lc "cd '$ROOT/$app' && npm ci"
  done
fi

run "Backend Ruff" bash -lc "cd '$ROOT/backend' && uv run ruff check automail tests"
run "Backend strict Pyright" bash -lc "cd '$ROOT/backend' && uv run pyright"
run "Backend full tests and coverage" bash -lc \
  "cd '$ROOT/backend' && uv run pytest tests --cov=automail --cov-branch --cov-report=term-missing:skip-covered --cov-fail-under=60 -ra"
run "Support package readiness" bash -lc \
  "cd '$ROOT/backend' && uv run python -m automail.support.package_gate --root .."

for app in admin addin landing; do
  run "$app lint" bash -lc "cd '$ROOT/$app' && npm run lint"
  run "$app production build" bash -lc "cd '$ROOT/$app' && npm run build"
done

run "Pilot metric schema" python -m json.tool "$ROOT/docs/pilot-metrics-schema.json"

required_files=(
  README.md
  PILOT_RUNBOOK.md
  SECURITY.md
  docs/v1-scope.md
  docs/pilot-success-criteria.md
  docs/pilot-metrics-schema.json
  docs/merge-order.md
  docs/security/threat-model.md
  docs/security/incident-response.md
  docs/security/data-retention.md
)

for path in "${required_files[@]}"; do
  if [[ ! -s "$ROOT/$path" ]]; then
    echo "Required production-readiness asset is missing or empty: $path" >&2
    exit 1
  fi
done

if grep -R --line-number --exclude-dir=.git --exclude='merge-order.md' 'isarai-test' "$ROOT"; then
  echo "Legacy isarai-test image name is forbidden." >&2
  exit 1
fi

if [[ "$SKIP_E2E" != "true" ]]; then
  run "Auth lifecycle E2E" bash -lc \
    "cd '$ROOT/addin' && npx playwright install chromium && npm run test:e2e:auth"
else
  echo
  echo "== Auth lifecycle E2E skipped (set SKIP_E2E=false to run) =="
fi

echo
echo "All configured quality checks passed."

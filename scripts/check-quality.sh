#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/mantly-uv-cache}"
export AUTOMAIL_BACKGROUND_IO="${AUTOMAIL_BACKGROUND_IO:-disabled}"
export GOOGLE_API_KEY="${GOOGLE_API_KEY:-dummy-local-quality-key}"
export REQUIRE_AUTH="${REQUIRE_AUTH:-false}"

SKIP_INSTALL="${SKIP_INSTALL:-false}"
SKIP_E2E="${SKIP_E2E:-false}"
SKIP_INTEGRATION="${SKIP_INTEGRATION:-false}"
SKIP_IMAGES="${SKIP_IMAGES:-false}"
SKIP_SECURITY="${SKIP_SECURITY:-false}"

run() {
  echo
  echo "== $1 =="
  shift
  "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command is unavailable: $1" >&2
    exit 1
  fi
}

install_dependencies() {
  require_command uv
  require_command npm
  run "Backend locked dependency sync" bash -lc "cd '$ROOT/backend' && uv sync --frozen"
  for app in admin addin landing; do
    run "$app locked dependency install" bash -lc "cd '$ROOT/$app' && npm ci"
  done
}

backend_lint() {
  require_command uv
  run "Backend Ruff" bash -lc "cd '$ROOT/backend' && uv run ruff check automail tests ../e2e"
  run "Backend strict Pyright" bash -lc "cd '$ROOT/backend' && uv run pyright"
}

backend_tests() {
  require_command uv
  run "Backend full test discovery" bash -lc "cd '$ROOT/backend' && uv run pytest tests --collect-only -q"
  run "Backend full tests and repository coverage" bash -lc \
    "cd '$ROOT/backend' && uv run pytest tests --cov=automail --cov-branch --cov-report=term-missing:skip-covered --cov-report=xml:coverage.xml --cov-report=json:coverage.json --cov-fail-under=60 -ra"
  run "Critical runtime coverage" python "$ROOT/scripts/check_critical_coverage.py" "$ROOT/backend/coverage.json"
  run "Support package readiness" bash -lc \
    "cd '$ROOT/backend' && uv run python -m automail.support.package_gate --root .."
}

frontend_quality() {
  require_command npm
  app="${1:-}"
  case "$app" in
    admin|addin|landing)
      run "$app lint" bash -lc "cd '$ROOT/$app' && npm run lint"
      run "$app TypeScript and production build" bash -lc "cd '$ROOT/$app' && npm run build"
      ;;
    all|"")
      for frontend in admin addin landing; do
        frontend_quality "$frontend"
      done
      ;;
    *)
      echo "Unknown frontend: $app" >&2
      exit 2
      ;;
  esac
}

repository_contract() {
  run "Pilot metric JSON syntax" python -m json.tool "$ROOT/docs/pilot-metrics-schema.json"
  run "Canonical Mantly naming" python "$ROOT/scripts/check_branding.py"
  run "Naming migration script syntax" bash -n "$ROOT/scripts/migrate-compose-volumes.sh"
  if [[ -f "$ROOT/scripts/validate-pilot-metrics.py" ]]; then
    run "Pilot metric schema contract" python "$ROOT/scripts/validate-pilot-metrics.py"
  fi

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
    docs/security/credential-rotation-and-break-glass.md
    docs/security/npm-audit-exceptions.json
    docs/security/dependency-exceptions.md
  )
  for path in "${required_files[@]}"; do
    if [[ ! -s "$ROOT/$path" ]]; then
      echo "Required production-readiness asset is missing or empty: $path" >&2
      exit 1
    fi
  done
}

pocketbase_integration() {
  require_command docker
  require_command curl
  require_command uv
  pb_port="${QUALITY_PB_PORT:-18090}"
  pb_name="${QUALITY_PB_CONTAINER:-mantly-pocketbase-quality-$$}"
  pb_image="${QUALITY_PB_IMAGE:-mantly-pocketbase-quality}"
  pb_email="${QUALITY_PB_EMAIL:-integration@example.com}"
  pb_password="${QUALITY_PB_PASSWORD:-integration-password-123456}"
  pb_url="http://127.0.0.1:${pb_port}"

  cleanup_pocketbase() {
    docker rm -f "$pb_name" >/dev/null 2>&1 || true
  }
  trap cleanup_pocketbase EXIT
  cleanup_pocketbase

  run "PocketBase image build" docker build -f "$ROOT/pocketbase/Dockerfile" -t "$pb_image" "$ROOT"
  run "PocketBase start" docker run -d --name "$pb_name" \
    -p "${pb_port}:8090" \
    -e "PB_ADMIN_EMAIL=$pb_email" \
    -e "PB_ADMIN_PASSWORD=$pb_password" \
    "$pb_image"

  ready=false
  for _attempt in $(seq 1 60); do
    if curl -fsS -X POST "$pb_url/api/collections/_superusers/auth-with-password" \
      -H 'Content-Type: application/json' \
      --data "{\"identity\":\"$pb_email\",\"password\":\"$pb_password\"}" >/dev/null; then
      ready=true
      break
    fi
    sleep 1
  done
  if [[ "$ready" != "true" ]]; then
    docker logs "$pb_name"
    echo "PocketBase did not become ready" >&2
    exit 1
  fi

  run "PocketBase clean bootstrap and idempotency" bash -lc \
    "cd '$ROOT/backend' && PB_URL='$pb_url' PB_ADMIN_EMAIL='$pb_email' PB_ADMIN_PASSWORD='$pb_password' uv run python -c 'from automail.db.pocketbase.bootstrap_app_schema import ensure_app_collections_schema; ensure_app_collections_schema(); ensure_app_collections_schema()'"
  run "PocketBase representative existing snapshot migration" bash -lc \
    "cd '$ROOT/backend' && PB_EXISTING_SNAPSHOT_TEST_URL='$pb_url' PB_EXISTING_SNAPSHOT_TEST_EMAIL='$pb_email' PB_EXISTING_SNAPSHOT_TEST_PASSWORD='$pb_password' uv run pytest tests/test_pb_existing_snapshot_integration.py -v"
  run "PocketBase bootstrap and tenant isolation tests" bash -lc \
    "cd '$ROOT/backend' && PB_URL='$pb_url' PB_ADMIN_EMAIL='$pb_email' PB_ADMIN_PASSWORD='$pb_password' uv run pytest tests/test_pb_bootstrap.py tests/test_tenant_isolation.py -v"
  run "PocketBase delivery claim and fencing" bash -lc \
    "cd '$ROOT/backend' && PB_DELIVERY_HOOK_TEST_URL='$pb_url' PB_DELIVERY_HOOK_TEST_EMAIL='$pb_email' PB_DELIVERY_HOOK_TEST_PASSWORD='$pb_password' uv run pytest tests/test_support_delivery_hook_integration.py -v"

  cleanup_pocketbase
  trap - EXIT
}

browser_e2e() {
  require_command npx
  run "Playwright Chromium install" bash -lc "cd '$ROOT/addin' && npx playwright install chromium"
  run "Auth and Admin Inbox lifecycle E2E" bash -lc "cd '$ROOT/addin' && npm run test:e2e:auth"
}

production_images() {
  require_command docker
  require_command curl
  run "Combined production image" docker build -t mantly-quality "$ROOT"
  run "SaaS API image" docker build -f "$ROOT/Dockerfile.api" -t mantly-api-quality "$ROOT"
  run "Caddy production image" docker build -f "$ROOT/caddy/Dockerfile" -t mantly-caddy-quality "$ROOT"
  run "PocketBase production image" docker build -f "$ROOT/pocketbase/Dockerfile" -t mantly-pocketbase-quality "$ROOT"
  run "Admin production image" docker build -f "$ROOT/deploy/admin.Dockerfile" -t mantly-admin-quality "$ROOT"
  run "Add-in production image" docker build -f "$ROOT/deploy/addin.Dockerfile" -t mantly-addin-quality "$ROOT"
  run "Landing production image" docker build -f "$ROOT/deploy/landing.Dockerfile" -t mantly-landing-quality "$ROOT"
  run "Production image non-root runtime and upgrade smoke" bash "$ROOT/scripts/smoke-production-images.sh"
}

security_policy() {
  repository_contract
  grep -q "tenant isolation" "$ROOT/docs/security/threat-model.md"
  grep -q "Required permission" "$ROOT/docs/security/threat-model.md"
  grep -q "5.12 Backup/recovery" "$ROOT/docs/security/threat-model.md"
  grep -q "duplicate side effects" "$ROOT/docs/security/incident-response.md"
  grep -q "Maximum planned overlap: 24 hours" "$ROOT/docs/security/credential-rotation-and-break-glass.md"
  grep -q "Access lifetime: maximum 60 minutes" "$ROOT/docs/security/credential-rotation-and-break-glass.md"
  grep -q "Backups" "$ROOT/docs/security/data-retention.md"
}

security_secret_scan() {
  require_command docker
  run "Repository secret scan" docker run --rm \
    -v "$ROOT:/repo" \
    ghcr.io/gitleaks/gitleaks:v8.28.0 \
    detect --source=/repo --redact --no-banner --verbose
}

security_python_audit() {
  require_command uv
  requirements_file="${TMPDIR:-/tmp}/mantly-production-requirements-$$.txt"
  trap 'rm -f "$requirements_file"' EXIT
  run "Export locked Python production dependencies" bash -lc \
    "cd '$ROOT/backend' && uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file '$requirements_file'"
  run "Audit Python production dependencies" uvx --python 3.12 --from pip-audit==2.9.0 \
    pip-audit --requirement "$requirements_file" --progress-spinner off --strict
  rm -f "$requirements_file"
  trap - EXIT
}

security_node_audit() {
  require_command npm
  require_command node
  app="${1:-all}"
  if [[ "$app" == "all" ]]; then
    for frontend in admin addin landing; do
      security_node_audit "$frontend"
    done
    return
  fi
  case "$app" in
    admin|addin|landing)
      run "$app production dependency audit" \
        node "$ROOT/scripts/check-node-audit.mjs" "$ROOT/$app"
      ;;
    *)
      echo "Unknown frontend audit target: $app" >&2
      exit 2
      ;;
  esac
}

security_config_scan() {
  require_command docker
  run "Container and repository configuration scan" docker run --rm \
    -v "$ROOT:/repo" \
    aquasec/trivy:0.58.2 \
    config --severity HIGH,CRITICAL --exit-code 1 --quiet /repo
}

security_all() {
  security_secret_scan
  security_python_audit
  security_node_audit all
  security_config_scan
  security_policy
}

all_checks() {
  if [[ "$SKIP_INSTALL" != "true" ]]; then
    install_dependencies
  fi
  backend_lint
  backend_tests
  frontend_quality all
  repository_contract
  if [[ "$SKIP_INTEGRATION" != "true" ]]; then
    pocketbase_integration
  else
    echo "PocketBase integration explicitly skipped (SKIP_INTEGRATION=true)."
  fi
  if [[ "$SKIP_E2E" != "true" ]]; then
    browser_e2e
  else
    echo "Browser E2E explicitly skipped (SKIP_E2E=true)."
  fi
  if [[ "$SKIP_IMAGES" != "true" ]]; then
    production_images
  else
    echo "Production image builds explicitly skipped (SKIP_IMAGES=true)."
  fi
  if [[ "$SKIP_SECURITY" != "true" ]]; then
    security_all
  else
    echo "Security scans explicitly skipped (SKIP_SECURITY=true)."
  fi
}

phase="${1:-all}"
case "$phase" in
  all) all_checks ;;
  install) install_dependencies ;;
  backend-lint) backend_lint ;;
  backend-tests) backend_tests ;;
  frontend) frontend_quality "${2:-all}" ;;
  repository) repository_contract ;;
  pocketbase) pocketbase_integration ;;
  e2e) browser_e2e ;;
  images) production_images ;;
  security) security_all ;;
  security-secret) security_secret_scan ;;
  security-python) security_python_audit ;;
  security-node) security_node_audit "${2:-all}" ;;
  security-config) security_config_scan ;;
  security-policy) security_policy ;;
  *)
    echo "Unknown quality phase: $phase" >&2
    exit 2
    ;;
esac

echo
echo "Quality phase '$phase' passed."

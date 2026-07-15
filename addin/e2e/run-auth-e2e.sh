#!/bin/sh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADDIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ADDIN_DIR/.." && pwd)"

PB_URL="${E2E_PB_URL:-http://127.0.0.1:8091}"
API_URL="${E2E_API_URL:-http://127.0.0.1:8180}"
ADDIN_URL="${E2E_ADDIN_URL:-http://127.0.0.1:4173}"
ADMIN_URL="${E2E_ADMIN_URL:-http://127.0.0.1:4174}"
PB_ADMIN_EMAIL="${E2E_PB_ADMIN_EMAIL:-admin@mantly.local}"
PB_ADMIN_PASSWORD="${E2E_PB_ADMIN_PASSWORD:-adminpass123}"
PB_CONTAINER_NAME="${E2E_PB_CONTAINER:-mantly-pocketbase-auth-e2e}"
PB_IMAGE_NAME="${E2E_PB_IMAGE:-mantly-pocketbase-auth-e2e}"
PB_VOLUME_NAME="${E2E_PB_VOLUME:-mantly-pocketbase-auth-e2e-data}"

BACKEND_LOG="/tmp/mantly-auth-e2e-backend.log"
ADDIN_LOG="/tmp/mantly-auth-e2e-addin.log"
ADMIN_LOG="/tmp/mantly-auth-e2e-admin.log"

cleanup() {
  if [ -n "${ADMIN_PID:-}" ]; then kill "$ADMIN_PID" >/dev/null 2>&1 || true; fi
  if [ -n "${ADDIN_PID:-}" ]; then kill "$ADDIN_PID" >/dev/null 2>&1 || true; fi
  if [ -n "${BACKEND_PID:-}" ]; then kill "$BACKEND_PID" >/dev/null 2>&1 || true; fi
  docker rm -f "$PB_CONTAINER_NAME" >/dev/null 2>&1 || true
  docker volume rm -f "$PB_VOLUME_NAME" >/dev/null 2>&1 || true
}

wait_for_url() {
  url="$1"
  name="$2"
  attempts="${3:-60}"
  i=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge "$attempts" ]; then
      echo "Timed out waiting for $name at $url" >&2
      exit 1
    fi
    sleep 1
  done
}

trap cleanup EXIT INT TERM

docker rm -f "$PB_CONTAINER_NAME" >/dev/null 2>&1 || true
docker volume rm -f "$PB_VOLUME_NAME" >/dev/null 2>&1 || true

docker build -f "$REPO_ROOT/pocketbase/Dockerfile" -t "$PB_IMAGE_NAME" "$REPO_ROOT" >/dev/null
docker run -d \
  --name "$PB_CONTAINER_NAME" \
  -p 8091:8090 \
  -e "PB_ADMIN_EMAIL=$PB_ADMIN_EMAIL" \
  -e "PB_ADMIN_PASSWORD=$PB_ADMIN_PASSWORD" \
  -v "$PB_VOLUME_NAME:/pb/pb_data" \
  "$PB_IMAGE_NAME" >/dev/null
wait_for_url "$PB_URL/api/health" "PocketBase" 90

(
  cd "$REPO_ROOT/backend"
  GOOGLE_API_KEY=dummy \
  REQUIRE_AUTH=true \
  JWT_SECRET=auth-e2e-jwt-secret \
  CORS_ORIGINS="$ADDIN_URL,$ADMIN_URL" \
  MANIFEST_BASE_URL="$ADDIN_URL" \
  PB_URL="$PB_URL" \
  PB_ADMIN_EMAIL="$PB_ADMIN_EMAIL" \
  PB_ADMIN_PASSWORD="$PB_ADMIN_PASSWORD" \
  uv run python -m uvicorn automail.main:app --host 127.0.0.1 --port 8180 >"$BACKEND_LOG" 2>&1
) &
BACKEND_PID=$!
wait_for_url "$API_URL/api/health" "backend"

(
  cd "$ADDIN_DIR"
  VITE_API_URL="$API_URL" \
  VITE_PB_URL="$PB_URL" \
  VITE_REQUIRE_AUTH=true \
  VITE_ENABLE_MOCK_MODE=true \
  npm run dev -- --host 127.0.0.1 --port 4173 >"$ADDIN_LOG" 2>&1
) &
ADDIN_PID=$!
wait_for_url "$ADDIN_URL" "addin"

(
  cd "$REPO_ROOT/admin"
  VITE_API_URL="$API_URL" \
  VITE_PB_URL="$PB_URL" \
  VITE_REQUIRE_AUTH=true \
  npm run dev -- --host 127.0.0.1 --port 4174 >"$ADMIN_LOG" 2>&1
) &
ADMIN_PID=$!
wait_for_url "$ADMIN_URL" "admin"

cd "$ADDIN_DIR"
exec npx playwright test -c playwright.auth.config.ts

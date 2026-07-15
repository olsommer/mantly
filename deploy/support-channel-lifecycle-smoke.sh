#!/usr/bin/env bash
# Run one support channel lifecycle smoke proof from the packaged app container.

set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BASE_URL="${MANTLY_BASE_URL:-http://localhost:8080}"
PROJECT_ID="${SUPPORT_PROJECT_ID:-}"
TOKEN="${ADMIN_AUTH_TOKEN:-}"
TIMEOUT="${SUPPORT_SMOKE_TIMEOUT:-15}"

if [ -z "$PROJECT_ID" ]; then
  echo "support channel lifecycle smoke: set SUPPORT_PROJECT_ID in .env or the environment" >&2
  exit 1
fi

if [ -z "$TOKEN" ]; then
  echo "support channel lifecycle smoke: set ADMIN_AUTH_TOKEN in .env or the environment" >&2
  exit 1
fi

compose_cmd=(docker compose)
if [ -n "${DOCKER_COMPOSE_COMMAND:-}" ]; then
  read -r -a compose_cmd <<< "$DOCKER_COMPOSE_COMMAND"
fi

exec "${compose_cmd[@]}" exec -T \
  -e MANTLY_BASE_URL="$BASE_URL" \
  -e SUPPORT_PROJECT_ID="$PROJECT_ID" \
  -e ADMIN_AUTH_TOKEN="$TOKEN" \
  -e SUPPORT_SMOKE_TIMEOUT="$TIMEOUT" \
  app \
  python -m automail.support.channel_lifecycle_smoke "$@"

#!/usr/bin/env bash
# Run the support launch gate from the packaged app container.

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
TIMEOUT="${SUPPORT_LAUNCH_GATE_TIMEOUT:-15}"
BUNDLE_FILE="${SUPPORT_LAUNCH_GATE_BUNDLE_FILE-/app/data/support-launch-proof.json}"
HOST_BUNDLE_FILE="${SUPPORT_LAUNCH_GATE_BUNDLE_OUT:-support-launch-proof.json}"
COPY_BUNDLE="${SUPPORT_LAUNCH_GATE_COPY_BUNDLE:-true}"

if [ -z "$PROJECT_ID" ]; then
  echo "support launch gate: set SUPPORT_PROJECT_ID in .env or the environment" >&2
  exit 1
fi

if [ -z "$TOKEN" ]; then
  echo "support launch gate: set ADMIN_AUTH_TOKEN in .env or the environment" >&2
  exit 1
fi

compose_cmd=(docker compose)
if [ -n "${DOCKER_COMPOSE_COMMAND:-}" ]; then
  read -r -a compose_cmd <<< "$DOCKER_COMPOSE_COMMAND"
fi

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

has_arg() {
  local needle="$1"
  shift
  local arg
  for arg in "$@"; do
    case "$arg" in
      "$needle"|"$needle"=*) return 0 ;;
    esac
  done
  return 1
}

arg_value() {
  local needle="$1"
  shift
  while [ "$#" -gt 0 ]; do
    case "$1" in
      "$needle")
        shift
        printf '%s' "${1:-}"
        return 0
        ;;
      "$needle"=*)
        printf '%s' "${1#*=}"
        return 0
        ;;
    esac
    shift
  done
  return 1
}

launch_args=("$@")
if [ -n "$BUNDLE_FILE" ] && ! has_arg "--bundle-file" "${launch_args[@]}"; then
  launch_args=(--bundle-file "$BUNDLE_FILE" "${launch_args[@]}")
fi
EFFECTIVE_BUNDLE_FILE=""
if bundle_arg="$(arg_value "--bundle-file" "${launch_args[@]}")"; then
  EFFECTIVE_BUNDLE_FILE="$bundle_arg"
fi
if ! is_true "${SUPPORT_SKIP_SCHEMA_GATE:-}"; then
  launch_args=(--schema-gate "${launch_args[@]}")
fi
if is_true "${SUPPORT_SCHEMA_GATE_NO_BOOTSTRAP:-}"; then
  launch_args=(--no-schema-bootstrap "${launch_args[@]}")
fi

set +e
"${compose_cmd[@]}" exec -T \
  -e MANTLY_BASE_URL="$BASE_URL" \
  -e SUPPORT_PROJECT_ID="$PROJECT_ID" \
  -e ADMIN_AUTH_TOKEN="$TOKEN" \
  -e SUPPORT_LAUNCH_GATE_TIMEOUT="$TIMEOUT" \
  app \
  python -m automail.support.launch_gate "${launch_args[@]}"
gate_code=$?
set -e

if [ -n "$EFFECTIVE_BUNDLE_FILE" ] && is_true "$COPY_BUNDLE"; then
  if "${compose_cmd[@]}" cp "app:$EFFECTIVE_BUNDLE_FILE" "$HOST_BUNDLE_FILE" >/dev/null 2>&1; then
    echo "support launch gate: copied bundle to $HOST_BUNDLE_FILE"
  else
    echo "support launch gate: could not copy bundle from app:$EFFECTIVE_BUNDLE_FILE to $HOST_BUNDLE_FILE" >&2
    if [ "$gate_code" -eq 0 ]; then
      exit 1
    fi
  fi
fi

exit "$gate_code"

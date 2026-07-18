#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT")}"
HELPER_IMAGE="${VOLUME_MIGRATION_HELPER_IMAGE:-alpine:3.21}"
CONFIRM="${MANTLY_VOLUME_MIGRATION_CONFIRM:-}"
EXPECTED_CONFIRM="COPY_LEGACY_VOLUMES_TO_MANTLY"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "ERROR: $*" >&2
  exit 1
}

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

volume_empty() {
  local volume="$1"
  docker run --rm -v "$volume:/target:ro" "$HELPER_IMAGE" \
    sh -ec 'test -z "$(find /target -mindepth 1 -maxdepth 1 -print -quit)"'
}

copy_volume() {
  local source="$1"
  local target="$2"
  volume_exists "$source" || fail "Legacy source volume does not exist: $source"
  docker volume create "$target" >/dev/null
  volume_empty "$target" || fail "Target volume is not empty: $target"

  log "Copying $source -> $target"
  docker run --rm \
    -v "$source:/source:ro" \
    -v "$target:/target" \
    "$HELPER_IMAGE" \
    sh -ec 'cd /source; tar -cf - . | (cd /target; tar -xpf -)'

  local source_count target_count
  source_count="$(docker run --rm -v "$source:/source:ro" "$HELPER_IMAGE" sh -ec 'find /source -mindepth 1 | wc -l')"
  target_count="$(docker run --rm -v "$target:/target:ro" "$HELPER_IMAGE" sh -ec 'find /target -mindepth 1 | wc -l')"
  [[ "$source_count" == "$target_count" ]] || fail "Object-count mismatch for $source -> $target"

  docker run --rm \
    -v "$source:/source:ro" \
    -v "$target:/target:ro" \
    "$HELPER_IMAGE" \
    sh -ec '
      cd /source
      find . -type f -print0 | sort -z | xargs -0 sha256sum > /tmp/source.sha256
      cd /target
      find . -type f -print0 | sort -z | xargs -0 sha256sum > /tmp/target.sha256
      diff -u /tmp/source.sha256 /tmp/target.sha256
    '
  log "Verified $target"
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
docker compose version >/dev/null
[[ "$CONFIRM" == "$EXPECTED_CONFIRM" ]] || fail "Set MANTLY_VOLUME_MIGRATION_CONFIRM=$EXPECTED_CONFIRM"

OLD_PB="${LEGACY_PB_VOLUME:-${PROJECT}_isarai_pb_data}"
OLD_APP="${LEGACY_APP_VOLUME:-${PROJECT}_isarai_app_data}"
NEW_PB="${MANTLY_PB_VOLUME:-${PROJECT}_mantly_pb_data}"
NEW_APP="${MANTLY_APP_VOLUME:-${PROJECT}_mantly_app_data}"

cd "$ROOT"
log "Stopping writers before volume migration"
docker compose stop app pocketbase >/dev/null 2>&1 || true

copy_volume "$OLD_PB" "$NEW_PB"
copy_volume "$OLD_APP" "$NEW_APP"

cat <<EOF

Volume migration completed and verified.

Legacy volumes retained for rollback:
  $OLD_PB
  $OLD_APP

Canonical volumes:
  $NEW_PB
  $NEW_APP

Next steps:
  1. Deploy the Compose file that references the canonical volumes.
  2. Start pocketbase/app and run health, auth, tenant, attachment and restore checks.
  3. Keep legacy volumes read-only/unmodified until the rollback window expires.
  4. Delete legacy volumes only after an approved backup and migration sign-off.
EOF

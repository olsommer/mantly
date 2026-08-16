#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT")}"
HELPER_IMAGE="${VOLUME_MIGRATION_HELPER_IMAGE:-alpine:3.21}"
MODE="${1:-copy}"
CONFIRM="${MANTLY_VOLUME_MIGRATION_CONFIRM:-}"
EXPECTED_CONFIRM="COPY_LEGACY_VOLUMES_TO_MANTLY"
BACKUP_BUNDLE="${MANTLY_VERIFIED_BACKUP_BUNDLE:-}"
BACKUP_CHECKSUM="${MANTLY_VERIFIED_BACKUP_CHECKSUM:-${BACKUP_BUNDLE:+$BACKUP_BUNDLE.sha256}}"

OLD_PB="${LEGACY_PB_VOLUME:-${PROJECT}_isarai_pb_data}"
OLD_APP="${LEGACY_APP_VOLUME:-${PROJECT}_isarai_app_data}"
NEW_PB="${MANTLY_PB_VOLUME:-${PROJECT}_mantly_pb_data}"
NEW_APP="${MANTLY_APP_VOLUME:-${PROJECT}_mantly_app_data}"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "ERROR: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

validate_volume_name() {
  local name="$1"
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail "Invalid Docker volume name: $name"
}

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

volume_status() {
  if volume_exists "$1"; then
    printf 'present'
  else
    printf 'absent'
  fi
}

print_inventory() {
  local running
  running="$(docker compose --project-directory "$ROOT" ps --status running --services)"
  cat <<EOF
Compose project: $PROJECT
Running services:
${running:-  (none)}

Volume inventory (read-only):
  legacy PocketBase:  $OLD_PB ($(volume_status "$OLD_PB"))
  legacy application: $OLD_APP ($(volume_status "$OLD_APP"))
  Mantly PocketBase:  $NEW_PB ($(volume_status "$NEW_PB"))
  Mantly application: $NEW_APP ($(volume_status "$NEW_APP"))
EOF
}

verify_backup() {
  [[ -n "$BACKUP_BUNDLE" ]] || fail "MANTLY_VERIFIED_BACKUP_BUNDLE is required"
  [[ -n "$BACKUP_CHECKSUM" ]] || fail "MANTLY_VERIFIED_BACKUP_CHECKSUM is required"
  [[ -s "$BACKUP_BUNDLE" ]] || fail "Verified backup bundle is missing or empty: $BACKUP_BUNDLE"
  [[ -s "$BACKUP_CHECKSUM" ]] || fail "Backup checksum file is missing or empty: $BACKUP_CHECKSUM"

  local expected actual
  expected="$(awk 'NR == 1 {print $1}' "$BACKUP_CHECKSUM")"
  [[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || fail "Backup checksum file does not start with a SHA-256 digest"
  actual="$(sha256sum "$BACKUP_BUNDLE" | awk '{print $1}')"
  [[ "${actual,,}" == "${expected,,}" ]] || fail "Backup bundle checksum verification failed"
  log "Verified backup bundle: $BACKUP_BUNDLE"
}

volume_empty() {
  local volume="$1"
  docker run --rm -v "$volume:/target:ro" "$HELPER_IMAGE" \
    sh -ec 'test -z "$(find /target -mindepth 1 -maxdepth 1 -print -quit)"'
}

target_ready() {
  local volume="$1"
  if volume_exists "$volume"; then
    volume_empty "$volume" || fail "Target volume is not empty: $volume"
  fi
}

copy_volume() {
  local source="$1"
  local target="$2"
  docker volume create "$target" >/dev/null

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

require_command docker
docker compose version >/dev/null
for volume in "$OLD_PB" "$OLD_APP" "$NEW_PB" "$NEW_APP"; do
  validate_volume_name "$volume"
done
[[ "$OLD_PB" != "$OLD_APP" ]] || fail "Legacy PocketBase and application volumes must differ"
[[ "$NEW_PB" != "$NEW_APP" ]] || fail "Target PocketBase and application volumes must differ"
[[ "$OLD_PB" != "$NEW_PB" ]] || fail "Legacy and target PocketBase volumes must differ"
[[ "$OLD_APP" != "$NEW_APP" ]] || fail "Legacy and target application volumes must differ"
[[ "$OLD_PB" != "$NEW_APP" ]] || fail "Legacy PocketBase and target application volumes must differ"
[[ "$OLD_APP" != "$NEW_PB" ]] || fail "Legacy application and target PocketBase volumes must differ"

case "$MODE" in
  inventory)
    print_inventory
    exit 0
    ;;
  copy) ;;
  *) fail "Usage: $0 [inventory|copy]" ;;
esac

require_command awk
require_command sha256sum
[[ "$CONFIRM" == "$EXPECTED_CONFIRM" ]] || fail "Set MANTLY_VOLUME_MIGRATION_CONFIRM=$EXPECTED_CONFIRM"
verify_backup

# Validate every source and target before stopping services or creating volumes.
volume_exists "$OLD_PB" || fail "Legacy source volume does not exist: $OLD_PB"
volume_exists "$OLD_APP" || fail "Legacy source volume does not exist: $OLD_APP"
target_ready "$NEW_PB"
target_ready "$NEW_APP"

cd "$ROOT"
log "Stopping writers before volume migration"
docker compose --project-directory "$ROOT" stop app pocketbase >/dev/null
if docker compose --project-directory "$ROOT" ps --status running --services | grep -Eq '^(app|pocketbase)$'; then
  fail "Application writers are still running"
fi

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
  4. Retire legacy volumes only through a separate, explicitly approved operation.

This script never deletes volumes and never restarts services.
EOF

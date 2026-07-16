#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_INPUT="${1:-}"
CONFIRM_VALUE="${RESTORE_CONFIRM:-}"
EXPECTED_CONFIRM="ERASE_AND_RESTORE_MANTLY"
AGE_IDENTITY_FILE="${BACKUP_AGE_IDENTITY_FILE:-}"
ALLOW_UNENCRYPTED="${ALLOW_UNENCRYPTED_BACKUP:-false}"
HELPER_IMAGE="${BACKUP_HELPER_IMAGE:-alpine:3.21}"
PYTHON_HELPER_IMAGE="${BACKUP_PYTHON_HELPER_IMAGE:-python:3.12-alpine}"
SKIP_SERVICE_HEALTHCHECK="${SKIP_RESTORE_SERVICE_HEALTHCHECK:-false}"
KEEP_WORK_DIR="${KEEP_RESTORE_WORK_DIR:-false}"

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

compose() {
  docker compose --project-directory "$ROOT" "$@"
}

container_for() {
  local service="$1"
  local id
  id="$(compose ps -q "$service")"
  if [[ -z "$id" ]]; then
    log "Creating $service container so its durable mount can be discovered"
    compose create "$service" >/dev/null
    id="$(compose ps -q "$service")"
  fi
  [[ -n "$id" ]] || fail "Unable to resolve container for service: $service"
  printf '%s\n' "$id"
}

mount_source() {
  local container_id="$1"
  local destination="$2"
  docker inspect "$container_id" | python3 -c '
import json
import sys

container = json.load(sys.stdin)[0]
destination = sys.argv[1]
for mount in container.get("Mounts", []):
    if mount.get("Destination") == destination:
        source = mount.get("Name") or mount.get("Source")
        if source:
            print(source)
            raise SystemExit(0)
raise SystemExit(f"No mount found at {destination}")
' "$destination"
}

clear_mount() {
  local source="$1"
  log "Clearing target mount $source"
  docker run --rm -v "$source:/target" "$HELPER_IMAGE" \
    sh -ec 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +'
}

restore_mount() {
  local source="$1"
  local archive="$2"
  log "Restoring $(basename "$archive") into $source"
  docker run --rm \
    -v "$source:/target" \
    -v "$archive:/restore/archive.tar.gz:ro" \
    "$HELPER_IMAGE" \
    sh -ec 'cd /target; tar -xzf /restore/archive.tar.gz'
}

verify_sqlite_mount() {
  local source="$1"
  local require_database="$2"
  docker run --rm -v "$source:/data:ro" "$PYTHON_HELPER_IMAGE" python - "$require_database" <<'PY'
from __future__ import annotations

import pathlib
import sqlite3
import sys

root = pathlib.Path("/data")
require_database = sys.argv[1].lower() == "true"
databases = sorted(path for path in root.rglob("*.db") if path.is_file())
if require_database and not databases:
    raise SystemExit("No SQLite database found in restored PocketBase data")

for database in databases:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if not result or result[0] != "ok":
        raise SystemExit(f"SQLite integrity check failed for {database}: {result}")
    print(f"SQLite integrity OK: {database}")
PY
}

wait_for_internal_services() {
  if [[ "$SKIP_SERVICE_HEALTHCHECK" == true ]]; then
    log "Skipping service health checks by explicit configuration"
    return
  fi

  log "Waiting for PocketBase health"
  for attempt in {1..90}; do
    if compose exec -T pocketbase sh -ec \
      'wget -qO- http://127.0.0.1:8090/api/health >/dev/null 2>&1 || curl -fsS http://127.0.0.1:8090/api/health >/dev/null 2>&1'; then
      break
    fi
    if [[ "$attempt" == 90 ]]; then
      compose logs --no-color pocketbase >&2 || true
      fail "PocketBase did not become healthy after restore"
    fi
    sleep 1
  done

  log "Waiting for FastAPI health"
  for attempt in {1..90}; do
    if compose exec -T app python -c \
      'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=5).read()' >/dev/null 2>&1; then
      break
    fi
    if [[ "$attempt" == 90 ]]; then
      compose logs --no-color app >&2 || true
      fail "FastAPI did not become healthy after restore"
    fi
    sleep 1
  done
}

[[ -n "$BUNDLE_INPUT" ]] || fail "Usage: RESTORE_CONFIRM=$EXPECTED_CONFIRM $0 <backup-bundle>"
[[ "$CONFIRM_VALUE" == "$EXPECTED_CONFIRM" ]] || fail "Set RESTORE_CONFIRM=$EXPECTED_CONFIRM to acknowledge destructive restore"

require_command docker
require_command python3
require_command sha256sum
require_command tar

docker compose version >/dev/null

BUNDLE="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$BUNDLE_INPUT")"
[[ -f "$BUNDLE" ]] || fail "Backup bundle does not exist: $BUNDLE"

if [[ -f "$BUNDLE.sha256" ]]; then
  log "Verifying outer bundle checksum"
  (cd "$(dirname "$BUNDLE")" && sha256sum -c "$(basename "$BUNDLE.sha256")")
else
  log "WARNING: outer bundle checksum file not found: $BUNDLE.sha256" >&2
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mantly-restore.XXXXXX")"
chmod 700 "$WORK_DIR"
cleanup() {
  local status=$?
  if [[ "$KEEP_WORK_DIR" == true || "$status" != 0 ]]; then
    log "Restore work directory retained at $WORK_DIR" >&2
  else
    rm -rf "$WORK_DIR"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

PLAIN_BUNDLE="$BUNDLE"
case "$BUNDLE" in
  *.age)
    require_command age
    [[ -n "$AGE_IDENTITY_FILE" ]] || fail "BACKUP_AGE_IDENTITY_FILE is required for an encrypted backup"
    [[ -r "$AGE_IDENTITY_FILE" ]] || fail "Age identity file is not readable: $AGE_IDENTITY_FILE"
    PLAIN_BUNDLE="$WORK_DIR/backup.tar.gz"
    log "Decrypting backup bundle"
    age --decrypt --identity "$AGE_IDENTITY_FILE" --output "$PLAIN_BUNDLE" "$BUNDLE"
    ;;
  *)
    [[ "$ALLOW_UNENCRYPTED" == true ]] || fail "Unencrypted restore is disabled. Set ALLOW_UNENCRYPTED_BACKUP=true only for an isolated local drill."
    log "WARNING: restoring an explicitly allowed unencrypted local-drill backup" >&2
    ;;
esac

EXTRACT_DIR="$WORK_DIR/extracted"
mkdir -p "$EXTRACT_DIR"
tar -xzf "$PLAIN_BUNDLE" -C "$EXTRACT_DIR"

for required in manifest.json pocketbase-data.tar.gz application-data.tar.gz; do
  [[ -s "$EXTRACT_DIR/$required" ]] || fail "Backup component missing or empty: $required"
done

python3 -m json.tool "$EXTRACT_DIR/manifest.json" >/dev/null
python3 - "$EXTRACT_DIR" <<'PY'
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("formatVersion") != "1":
    raise SystemExit(f"Unsupported backup formatVersion: {manifest.get('formatVersion')}")

for key in ("pocketbase", "application"):
    component = manifest.get("components", {}).get(key)
    if not isinstance(component, dict):
        raise SystemExit(f"Missing manifest component: {key}")
    archive_name = component.get("archive")
    expected_hash = component.get("sha256")
    expected_size = component.get("sizeBytes")
    if not isinstance(archive_name, str) or not isinstance(expected_hash, str):
        raise SystemExit(f"Invalid manifest component metadata: {key}")
    archive = root / archive_name
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    actual_size = archive.stat().st_size
    if actual_hash != expected_hash:
        raise SystemExit(f"SHA-256 mismatch for {archive_name}")
    if not isinstance(expected_size, int) or actual_size != expected_size:
        raise SystemExit(f"Size mismatch for {archive_name}: expected {expected_size}, got {actual_size}")
print("Manifest and component integrity verified")
PY

cd "$ROOT"
APP_CONTAINER="$(container_for app)"
PB_CONTAINER="$(container_for pocketbase)"
APP_VOLUME="$(mount_source "$APP_CONTAINER" /app/data)"
PB_VOLUME="$(mount_source "$PB_CONTAINER" /pb/pb_data)"

log "Stopping application services before destructive restore"
compose stop app pocketbase >/dev/null

clear_mount "$PB_VOLUME"
clear_mount "$APP_VOLUME"
restore_mount "$PB_VOLUME" "$EXTRACT_DIR/pocketbase-data.tar.gz"
restore_mount "$APP_VOLUME" "$EXTRACT_DIR/application-data.tar.gz"

log "Verifying restored SQLite databases before service startup"
verify_sqlite_mount "$PB_VOLUME" true
verify_sqlite_mount "$APP_VOLUME" false

log "Starting restored services"
compose start pocketbase app >/dev/null
wait_for_internal_services

VERIFY_OUTPUT="$WORK_DIR/restore-verification.json"
VERIFY_ARGS=(--output "$VERIFY_OUTPUT")
if [[ -n "${RESTORE_API_URL:-}" ]]; then VERIFY_ARGS+=(--api-url "$RESTORE_API_URL"); fi
if [[ -n "${RESTORE_PB_URL:-}" ]]; then VERIFY_ARGS+=(--pb-url "$RESTORE_PB_URL"); fi
if [[ -n "${PB_ADMIN_EMAIL:-}" ]]; then VERIFY_ARGS+=(--pb-admin-email "$PB_ADMIN_EMAIL"); fi
if [[ -n "${PB_ADMIN_PASSWORD:-}" ]]; then VERIFY_ARGS+=(--pb-admin-password "$PB_ADMIN_PASSWORD"); fi

python3 "$ROOT/scripts/verify-restore.py" "${VERIFY_ARGS[@]}"

if [[ -n "${RESTORE_EVIDENCE_OUTPUT:-}" ]]; then
  mkdir -p "$(dirname "$RESTORE_EVIDENCE_OUTPUT")"
  cp "$VERIFY_OUTPUT" "$RESTORE_EVIDENCE_OUTPUT"
  chmod 600 "$RESTORE_EVIDENCE_OUTPUT" 2>/dev/null || true
  log "Wrote restore verification evidence to $RESTORE_EVIDENCE_OUTPUT"
fi

log "Restore completed and verified"

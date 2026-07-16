#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR_INPUT="${1:-$ROOT/backups}"
OUTPUT_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT_DIR_INPUT")"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BASENAME="mantly-backup-$TIMESTAMP"
FORMAT_VERSION="1"
ALPINE_IMAGE="${BACKUP_HELPER_IMAGE:-alpine:3.21}"
ALLOW_UNENCRYPTED="${ALLOW_UNENCRYPTED_BACKUP:-false}"
AGE_RECIPIENT="${BACKUP_AGE_RECIPIENT:-}"
BACKUP_REASON="${BACKUP_REASON:-scheduled}"
BACKUP_OPERATOR="${BACKUP_OPERATOR:-unknown}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT")}" 

mkdir -p "$OUTPUT_DIR"
chmod 700 "$OUTPUT_DIR" 2>/dev/null || true
WORK_DIR="$(mktemp -d "$OUTPUT_DIR/.${BASENAME}.work.XXXXXX")"
chmod 700 "$WORK_DIR"

APP_WAS_RUNNING=false
PB_WAS_RUNNING=false
SERVICES_STOPPED=false
SUCCESS=false

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

is_running() {
  docker inspect --format '{{.State.Running}}' "$1" 2>/dev/null | grep -q '^true$'
}

mount_source() {
  local container_id="$1"
  local destination="$2"
  local source
  source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "'"$destination"'"}}{{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "$container_id")"
  [[ -n "$source" ]] || fail "No mount found at $destination in container $container_id"
  printf '%s\n' "$source"
}

restart_services() {
  if [[ "$SERVICES_STOPPED" != true ]]; then
    return
  fi

  log "Restoring service state"
  if [[ "$PB_WAS_RUNNING" == true ]]; then
    compose start pocketbase >/dev/null || true
  fi
  if [[ "$APP_WAS_RUNNING" == true ]]; then
    compose start app >/dev/null || true
  fi
  SERVICES_STOPPED=false
}

cleanup() {
  local status=$?
  restart_services
  if [[ "$SUCCESS" == true ]]; then
    rm -rf "$WORK_DIR"
  else
    log "Backup failed; diagnostic work directory retained at $WORK_DIR" >&2
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

archive_mount() {
  local source="$1"
  local output_name="$2"
  log "Archiving $output_name"
  docker run --rm \
    -v "$source:/source:ro" \
    -v "$WORK_DIR:/backup" \
    "$ALPINE_IMAGE" \
    sh -ec 'cd /source; tar -czf "/backup/'"$output_name"'" .; test -s "/backup/'"$output_name"'"'
}

require_command docker
require_command python3
require_command sha256sum
require_command tar

docker compose version >/dev/null

if [[ -z "$AGE_RECIPIENT" && "$ALLOW_UNENCRYPTED" != true ]]; then
  fail "BACKUP_AGE_RECIPIENT is required. Set ALLOW_UNENCRYPTED_BACKUP=true only for an isolated local drill."
fi
if [[ -n "$AGE_RECIPIENT" ]]; then
  require_command age
fi

cd "$ROOT"
APP_CONTAINER="$(container_for app)"
PB_CONTAINER="$(container_for pocketbase)"
APP_VOLUME="$(mount_source "$APP_CONTAINER" /app/data)"
PB_VOLUME="$(mount_source "$PB_CONTAINER" /pb/pb_data)"

if is_running "$APP_CONTAINER"; then APP_WAS_RUNNING=true; fi
if is_running "$PB_CONTAINER"; then PB_WAS_RUNNING=true; fi

log "Stopping application writers for a consistent snapshot"
compose stop app pocketbase >/dev/null
SERVICES_STOPPED=true

archive_mount "$PB_VOLUME" pocketbase-data.tar.gz
archive_mount "$APP_VOLUME" application-data.tar.gz

PB_SHA="$(sha256sum "$WORK_DIR/pocketbase-data.tar.gz" | awk '{print $1}')"
APP_SHA="$(sha256sum "$WORK_DIR/application-data.tar.gz" | awk '{print $1}')"
PB_SIZE="$(wc -c < "$WORK_DIR/pocketbase-data.tar.gz" | tr -d ' ')"
APP_SIZE="$(wc -c < "$WORK_DIR/application-data.tar.gz" | tr -d ' ')"
GIT_COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')"
HOSTNAME_VALUE="$(hostname 2>/dev/null || printf 'unknown')"

export FORMAT_VERSION TIMESTAMP BACKUP_REASON BACKUP_OPERATOR COMPOSE_PROJECT
export PB_VOLUME APP_VOLUME PB_SHA APP_SHA PB_SIZE APP_SIZE GIT_COMMIT HOSTNAME_VALUE
python3 - "$WORK_DIR/manifest.json" <<'PY'
import json
import os
import sys

manifest = {
    "formatVersion": os.environ["FORMAT_VERSION"],
    "createdAt": os.environ["TIMESTAMP"],
    "reason": os.environ["BACKUP_REASON"],
    "operator": os.environ["BACKUP_OPERATOR"],
    "source": {
        "host": os.environ["HOSTNAME_VALUE"],
        "gitCommit": os.environ["GIT_COMMIT"],
        "composeProject": os.environ["COMPOSE_PROJECT"],
        "servicesStoppedForConsistency": True,
    },
    "components": {
        "pocketbase": {
            "archive": "pocketbase-data.tar.gz",
            "mount": os.environ["PB_VOLUME"],
            "sha256": os.environ["PB_SHA"],
            "sizeBytes": int(os.environ["PB_SIZE"]),
        },
        "application": {
            "archive": "application-data.tar.gz",
            "mount": os.environ["APP_VOLUME"],
            "sha256": os.environ["APP_SHA"],
            "sizeBytes": int(os.environ["APP_SIZE"]),
        },
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

python3 -m json.tool "$WORK_DIR/manifest.json" >/dev/null
[[ "$(sha256sum "$WORK_DIR/pocketbase-data.tar.gz" | awk '{print $1}')" == "$PB_SHA" ]] || fail "PocketBase archive hash changed"
[[ "$(sha256sum "$WORK_DIR/application-data.tar.gz" | awk '{print $1}')" == "$APP_SHA" ]] || fail "Application archive hash changed"

OUTER_BUNDLE="$OUTPUT_DIR/$BASENAME.tar.gz"
tar -C "$WORK_DIR" -czf "$OUTER_BUNDLE" manifest.json pocketbase-data.tar.gz application-data.tar.gz
[[ -s "$OUTER_BUNDLE" ]] || fail "Outer backup bundle is empty"

FINAL_BUNDLE="$OUTER_BUNDLE"
if [[ -n "$AGE_RECIPIENT" ]]; then
  FINAL_BUNDLE="$OUTER_BUNDLE.age"
  log "Encrypting backup bundle for configured age recipient"
  age --encrypt --recipient "$AGE_RECIPIENT" --output "$FINAL_BUNDLE" "$OUTER_BUNDLE"
  rm -f "$OUTER_BUNDLE"
else
  log "WARNING: producing an unencrypted local-drill backup" >&2
fi

sha256sum "$FINAL_BUNDLE" > "$FINAL_BUNDLE.sha256"
chmod 600 "$FINAL_BUNDLE" "$FINAL_BUNDLE.sha256"

restart_services
SUCCESS=true

log "Backup complete"
printf 'bundle=%s\nchecksum=%s\n' "$FINAL_BUNDLE" "$FINAL_BUNDLE.sha256"

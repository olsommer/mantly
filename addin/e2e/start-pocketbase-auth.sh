#!/bin/sh

set -eu

IMAGE_NAME="${E2E_PB_IMAGE:-mantly-pocketbase-auth-e2e}"
CONTAINER_NAME="${E2E_PB_CONTAINER:-mantly-pocketbase-auth-e2e}"
PB_DATA_DIR="${E2E_PB_DATA_DIR:-/tmp/mantly-pocketbase-auth-e2e}"
PB_HOST_PORT="${E2E_PB_PORT:-8091}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
rm -rf "$PB_DATA_DIR"
mkdir -p "$PB_DATA_DIR"

docker build -f "$REPO_ROOT/pocketbase/Dockerfile" -t "$IMAGE_NAME" "$REPO_ROOT"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

docker run \
  -d \
  --name "$CONTAINER_NAME" \
  -p "$PB_HOST_PORT:8090" \
  -e "PB_ADMIN_EMAIL=${PB_ADMIN_EMAIL:?PB_ADMIN_EMAIL is required}" \
  -e "PB_ADMIN_PASSWORD=${PB_ADMIN_PASSWORD:?PB_ADMIN_PASSWORD is required}" \
  -v "$PB_DATA_DIR:/pb/pb_data" \
  "$IMAGE_NAME"

while docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q true; do
  sleep 1
done

exit 1

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/isarai-email-agent-uv-cache}"

echo "== Backend Ruff =="
(
  cd "$ROOT/backend"
  uv run ruff check automail tests
)

echo "== Backend Pyright =="
(
  cd "$ROOT/backend"
  uv run pyright
)

for app in admin addin landing; do
  echo "== $app lint/build =="
  (
    cd "$ROOT/$app"
    npm run lint
    npm run build
  )
done

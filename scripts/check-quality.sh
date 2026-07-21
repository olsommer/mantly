#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/isarai-email-agent-uv-cache}"

echo "== Backend Ruff =="
(
  cd "$ROOT/backend"
  uv run ruff check automail tests ../e2e
)

echo "== Backend pytest =="
(
  cd "$ROOT/backend"
  uv run pytest -q
)

if [[ "${MANTLY_STRICT_PYRIGHT:-0}" == "1" ]]; then
  echo "== Backend Pyright (strict, opt-in while the legacy baseline is reduced) =="
  (
    cd "$ROOT/backend"
    uv run pyright
  )
else
  echo "== Backend Pyright skipped (set MANTLY_STRICT_PYRIGHT=1 to run) =="
fi

for app in admin addin landing; do
  echo "== $app lint/build =="
  (
    cd "$ROOT/$app"
    npm run lint
    npm run build
  )
done

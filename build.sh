#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Defaults (on-prem local dev) ──────────────────────────────────────────────
SAAS=false
PB_URL="${VITE_PB_URL:-http://localhost:8090}"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Build the Outlook add-in, admin SPA, and optional landing page.

Options:
  --saas            Build for SaaS mode (sets VITE_IS_SAAS=true)
  --pb-url URL      PocketBase URL baked into the SPAs
                    (default: \$VITE_PB_URL or http://localhost:8090)
  -h, --help        Show this help message

Environment variables (override via env or flags):
  VITE_PB_URL       PocketBase URL (--pb-url takes precedence)
  VITE_IS_SAAS      Set to "true" for SaaS builds (--saas takes precedence)

Examples:
  # On-prem local dev (default)
  ./build.sh

  # SaaS local dev
  ./build.sh --saas

  # Custom PocketBase URL
  ./build.sh --pb-url /pb
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --saas) SAAS=true; shift ;;
        --pb-url) PB_URL="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

echo "=== Build configuration ==="
echo "  PB_URL:  $PB_URL"
echo "  SaaS:    $SAAS"
echo ""

# ── Build Outlook add-in ──────────────────────────────────────────────────────
echo "=== Building Outlook add-in ==="
cd "$SCRIPT_DIR/addin"
npm ci
VITE_PB_URL="$PB_URL" \
VITE_REQUIRE_AUTH=true \
VITE_ENABLE_MOCK_MODE=false \
    npm run build

echo ""
echo "=== Add-in built successfully ==="
echo "Output: $SCRIPT_DIR/addin/dist/"
ls -la "$SCRIPT_DIR/addin/dist/"

# ── Build admin SPA ───────────────────────────────────────────────────────────
echo ""
echo "=== Building admin SPA ==="
cd "$SCRIPT_DIR/admin"
npm ci
VITE_PB_URL="$PB_URL" \
VITE_REQUIRE_AUTH=true \
VITE_IS_SAAS="$SAAS" \
    npm run build

echo ""
echo "=== Admin built successfully ==="
echo "Output: $SCRIPT_DIR/admin/dist/"
ls -la "$SCRIPT_DIR/admin/dist/"

# ── Build landing page (optional) ────────────────────────────────────────────
echo ""
if [ -d "$SCRIPT_DIR/landing" ]; then
    echo "=== Building landing page ==="
    cd "$SCRIPT_DIR/landing"
    npm ci
    npm run build

    echo ""
    echo "=== Landing page built successfully ==="
    echo "Output: $SCRIPT_DIR/landing/dist/"
    ls -la "$SCRIPT_DIR/landing/dist/"
else
    echo "=== Skipping landing page (directory not found) ==="
fi

echo ""
echo "=== To start the server ==="
echo "cd $SCRIPT_DIR/backend && uv run python -m automail.main"

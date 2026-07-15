#!/usr/bin/env bash
# inject-manifest.sh — Replace placeholders in manifest.xml
#
# Usage:
#   VITE_API_URL=https://mantly.yourdomain.com ./scripts/inject-manifest.sh
#   ADDIN_BASE_URL=https://addin.mantly.io VITE_API_URL=https://api.mantly.io ./scripts/inject-manifest.sh
#
# Optional:
#   ADDIN_ID=<uuid>   — custom add-in ID (defaults to the SaaS store UUID)
#
# Output:
#   addin/manifest.prod.xml  (valid XML with actual values)
#
# The original manifest.xml is never modified so it stays usable as a template.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_SRC="$SCRIPT_DIR/../addin/manifest.xml"
MANIFEST_OUT="$SCRIPT_DIR/../addin/manifest.prod.xml"

BACKEND_URL="${VITE_API_URL:-}"
ADDIN_BASE_URL="${ADDIN_BASE_URL:-$BACKEND_URL}"
ASSET_BASE_URL="${ASSET_BASE_URL:-$BACKEND_URL}"
if [ -z "${ADDIN_TASKPANE_URL:-}" ]; then
    if [ "$ADDIN_BASE_URL" = "$BACKEND_URL" ]; then
        ADDIN_TASKPANE_URL="$ADDIN_BASE_URL/addin/index.html"
    else
        ADDIN_TASKPANE_URL="$ADDIN_BASE_URL/"
    fi
fi
# Default add-in ID for the SaaS / Microsoft Store version
ADDIN_ID="${ADDIN_ID:-a1b2c3d4-e5f6-7890-abcd-ef1234567890}"

if [ -z "$BACKEND_URL" ]; then
    echo "ERROR: VITE_API_URL is not set." >&2
    echo "Usage: VITE_API_URL=https://mantly.yourdomain.com $0" >&2
    exit 1
fi

if [ ! -f "$MANIFEST_SRC" ]; then
    echo "ERROR: $MANIFEST_SRC not found." >&2
    exit 1
fi

BRAND_JSON="$SCRIPT_DIR/../brand.json"
if [ ! -f "$BRAND_JSON" ]; then
    echo "ERROR: $BRAND_JSON not found." >&2
    exit 1
fi

APP_BRAND_NAME="$(node -e "console.log(require(process.argv[1]).addinDisplayName)" "$BRAND_JSON")"
APP_PROVIDER_NAME="$(node -e "console.log(require(process.argv[1]).providerName)" "$BRAND_JSON")"
APP_DESCRIPTION_DE="$(node -e "console.log(require(process.argv[1]).descriptionDe)" "$BRAND_JSON")"
APP_SUPPORT_URL="$(node -e "console.log(require(process.argv[1]).supportUrl)" "$BRAND_JSON")"

sed -e "s|BACKEND_URL|${BACKEND_URL}|g" \
    -e "s|ADDIN_BASE_URL|${ADDIN_BASE_URL}|g" \
    -e "s|ASSET_BASE_URL|${ASSET_BASE_URL}|g" \
    -e "s|ADDIN_TASKPANE_URL|${ADDIN_TASKPANE_URL}|g" \
    -e "s|ADDIN_ID|${ADDIN_ID}|g" \
    -e "s|APP_BRAND_NAME|${APP_BRAND_NAME}|g" \
    -e "s|APP_PROVIDER_NAME|${APP_PROVIDER_NAME}|g" \
    -e "s|APP_DESCRIPTION_DE|${APP_DESCRIPTION_DE}|g" \
    -e "s|APP_SUPPORT_URL|${APP_SUPPORT_URL}|g" \
    "$MANIFEST_SRC" > "$MANIFEST_OUT"

echo "=== Manifest written to: $MANIFEST_OUT ==="
echo "    Backend URL: $BACKEND_URL"
echo "    Add-in URL:  $ADDIN_BASE_URL"
echo "    Asset URL:   $ASSET_BASE_URL"
echo "    Add-in ID:   $ADDIN_ID"

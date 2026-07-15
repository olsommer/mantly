#!/usr/bin/env bash
# release-onprem.sh — Build and push multi-arch on-prem images to GHCR.
#
# Usage:
#   ./scripts/release-onprem.sh 1.0.0          # tagged release
#   ./scripts/release-onprem.sh                 # :latest only
#
# Prerequisites:
#   - docker buildx (included in Docker Desktop)
#   - ghcr.io login: echo $GITHUB_TOKEN | docker login ghcr.io -u isarai-de --password-stdin

set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io/isarlabs}"
VERSION="${1:-}"
PLATFORMS="linux/amd64,linux/arm64"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

validate_version() {
    if [ -n "$VERSION" ] && [[ ! "$VERSION" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
        echo "Invalid VERSION '$VERSION'. Use a Docker tag: letters, numbers, underscore, dot, or dash; max 128 chars." >&2
        exit 64
    fi
}

validate_registry() {
    if [[ ! "$REGISTRY" =~ ^[a-z0-9][a-z0-9._:-]*(/[a-z0-9][a-z0-9._-]*)*$ ]]; then
        echo "Invalid REGISTRY '$REGISTRY'. Use a Docker registry/repository prefix like ghcr.io/isarlabs." >&2
        exit 64
    fi
}

validate_version
validate_registry

# Determine tags
APP_IMAGE="$REGISTRY/isarai-email-agent"
PB_IMAGE="$REGISTRY/isarai-pocketbase"

TAGS=("--tag" "$APP_IMAGE:latest")
PB_TAGS=("--tag" "$PB_IMAGE:latest")

if [ -n "$VERSION" ]; then
    TAGS+=("--tag" "$APP_IMAGE:$VERSION")
    PB_TAGS+=("--tag" "$PB_IMAGE:$VERSION")
    echo "=== Releasing version $VERSION ==="
else
    echo "=== Releasing :latest (no version tag) ==="
fi

echo ""
echo "Registry:   $REGISTRY"
echo "Platforms:  $PLATFORMS"
echo "App image:  $APP_IMAGE"
echo "PB image:   $PB_IMAGE"
echo ""

echo "=== Checking support package readiness ==="
if command -v uv >/dev/null 2>&1; then
    (cd "$ROOT/backend" && uv run python -m automail.support.package_gate --root "$ROOT")
else
    PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" python3 -m automail.support.package_gate --root "$ROOT"
fi

# Ensure buildx builder exists
BUILDER_NAME="isarai-multiarch"
if ! docker buildx inspect "$BUILDER_NAME" > /dev/null 2>&1; then
    echo "Creating buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --use --bootstrap
else
    docker buildx use "$BUILDER_NAME"
fi

# Build and push PocketBase image
echo ""
echo "=== Building PocketBase image (multi-arch) ==="
docker buildx build \
    --platform "$PLATFORMS" \
    --file "$ROOT/pocketbase/Dockerfile" \
    "${PB_TAGS[@]}" \
    --push \
    "$ROOT"

# Build and push app image (Cython-compiled)
echo ""
echo "=== Building app image (multi-arch, Cython-compiled) ==="
docker buildx build \
    --platform "$PLATFORMS" \
    --file "$ROOT/Dockerfile.onprem" \
    --build-arg VITE_PB_URL=/pb \
    --build-arg VITE_IS_SAAS=false \
    "${TAGS[@]}" \
    --push \
    "$ROOT"

echo ""
echo "=== Done ==="
echo ""
echo "Images pushed:"
echo "  $APP_IMAGE:latest"
echo "  $PB_IMAGE:latest"
if [ -n "$VERSION" ]; then
    echo "  $APP_IMAGE:$VERSION"
    echo "  $PB_IMAGE:$VERSION"
fi
echo ""
echo "Customer delivery:"
if [ "${SKIP_CUSTOMER_PACKAGE:-false}" = "true" ]; then
    echo "  Skipped because SKIP_CUSTOMER_PACKAGE=true"
    echo "  Manual package command: ./scripts/package-customer.sh $VERSION"
else
    "$ROOT/scripts/package-customer.sh" "$VERSION"
fi

#!/usr/bin/env bash
# package-customer.sh — Bundle the customer delivery files into a .tar.gz
#
# Usage:
#   ./scripts/package-customer.sh 1.0.0    # versioned package
#   ./scripts/package-customer.sh           # generic package

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
VERSION="${1:-}"
REGISTRY="${REGISTRY:-ghcr.io/isarlabs}"

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

if [ -n "$VERSION" ]; then
    PACKAGE_NAME="mantly-${VERSION}"
else
    PACKAGE_NAME="mantly"
fi

OUT_DIR="$ROOT/dist"
STAGING="$OUT_DIR/$PACKAGE_NAME"

echo "=== Packaging customer delivery: $PACKAGE_NAME ==="
echo "=== Checking support package readiness ==="
if command -v uv >/dev/null 2>&1; then
    (cd "$ROOT/backend" && uv run python -m automail.support.package_gate --root "$ROOT")
else
    PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" python3 -m automail.support.package_gate --root "$ROOT"
fi

SUPPORT_PACKAGE_GATE_JSON="$(
    ROOT="$ROOT" PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import json
import os

from automail.support.package_gate import check_package_readiness

result = check_package_readiness(os.environ["ROOT"])
print(json.dumps({"ready": result.ok, "checked": result.checked}, separators=(",", ":")))
PY
)"

# Clean and create staging directory.
rm -rf "$STAGING"
mkdir -p "$STAGING/scripts" "$STAGING/docs/operations"

# Copy deployment and support files.
cp "$ROOT/deploy/docker-compose.yml"  "$STAGING/docker-compose.yml"
cp "$ROOT/deploy/.env.example"        "$STAGING/.env.example"
cp "$ROOT/deploy/Caddyfile"           "$STAGING/Caddyfile"
install -m 755 "$ROOT/deploy/support-launch-gate.sh" "$STAGING/support-launch-gate.sh"
install -m 755 "$ROOT/deploy/support-schema-gate.sh" "$STAGING/support-schema-gate.sh"
install -m 755 "$ROOT/deploy/support-channel-lifecycle-smoke.sh" "$STAGING/support-channel-lifecycle-smoke.sh"
install -m 755 "$ROOT/deploy/support-channel-activation-plan.sh" "$STAGING/support-channel-activation-plan.sh"
cp "$ROOT/docs/deploy-onprem.md" "$STAGING/README.md"

# Recovery is part of the production customer handoff, not an optional source-only tool.
install -m 755 "$ROOT/scripts/backup.sh" "$STAGING/scripts/backup.sh"
install -m 755 "$ROOT/scripts/restore.sh" "$STAGING/scripts/restore.sh"
install -m 755 "$ROOT/scripts/verify-restore.py" "$STAGING/scripts/verify-restore.py"
cp "$ROOT/docs/deploy-onprem-recovery.md" "$STAGING/BACKUP-AND-RECOVERY.md"
cp "$ROOT/docs/operations/backup-and-recovery.md" "$STAGING/docs/operations/backup-and-recovery.md"
cp "$ROOT/docs/operations/restore-drill-template.md" "$STAGING/docs/operations/restore-drill-template.md"

IMAGE_TAG="${VERSION:-latest}"
GENERATED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
cat > "$STAGING/release-manifest.json" <<EOF
{
  "kind": "mantly_onprem_release_manifest",
  "packageName": "$PACKAGE_NAME",
  "version": "$VERSION",
  "imageTag": "$IMAGE_TAG",
  "generatedAt": "$GENERATED_AT",
  "images": {
    "app": "$REGISTRY/isarai-email-agent:$IMAGE_TAG",
    "pocketbase": "$REGISTRY/isarai-pocketbase:$IMAGE_TAG"
  },
  "supportScripts": [
    "support-launch-gate.sh",
    "support-schema-gate.sh",
    "support-channel-lifecycle-smoke.sh",
    "support-channel-activation-plan.sh"
  ],
  "recovery": {
    "backupScript": "scripts/backup.sh",
    "restoreScript": "scripts/restore.sh",
    "verifyScript": "scripts/verify-restore.py",
    "runbook": "docs/operations/backup-and-recovery.md",
    "drillTemplate": "docs/operations/restore-drill-template.md",
    "encryptedByDefault": true,
    "formatVersion": "1"
  },
  "supportLaunchProof": {
    "firstRun": "./support-launch-gate.sh --run",
    "steadyStateGate": "./support-launch-gate.sh",
    "bundleFile": "support-launch-proof.json"
  },
  "supportChannelActivationPlan": {
    "kind": "support_channel_activation_plan",
    "script": "./support-channel-activation-plan.sh",
    "apiPath": "/api/admin/projects/<project-id>/channels/activation-plan",
    "adminRoute": "/channels",
    "downloadFile": "support-channel-activation-plan-<project-id>.json",
    "planFile": "support-channel-activation-plan.json",
    "secretTemplateFile": "support-channel-activation-secrets.env"
  },
  "supportPackageGate": $SUPPORT_PACKAGE_GATE_JSON
}
EOF

# If version specified, pin it in the compose file.
if [ -n "$VERSION" ]; then
    sed -i.bak "s/^# VERSION=.*/VERSION=$VERSION/" "$STAGING/.env.example"
    rm -f "$STAGING/.env.example.bak"
fi

sed -i.bak "s|^REGISTRY=.*|REGISTRY=$REGISTRY|" "$STAGING/.env.example"
rm -f "$STAGING/.env.example.bak"

# Create the tarball.
cd "$OUT_DIR"
tar czf "${PACKAGE_NAME}.tar.gz" "$PACKAGE_NAME"
rm -rf "$STAGING"

echo ""
echo "=== Package created ==="
echo "  $OUT_DIR/${PACKAGE_NAME}.tar.gz"
echo ""
echo "Contents:"
tar tzf "$OUT_DIR/${PACKAGE_NAME}.tar.gz"

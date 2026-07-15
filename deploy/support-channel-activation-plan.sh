#!/usr/bin/env bash
# Fetch the support channel activation plan handoff artifact.

set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BASE_URL="${MANTLY_BASE_URL:-${PUBLIC_URL:-http://localhost}}"
PROJECT_ID="${SUPPORT_PROJECT_ID:-}"
TOKEN="${ADMIN_AUTH_TOKEN:-}"
PLAN_FILE="${SUPPORT_CHANNEL_ACTIVATION_PLAN_OUT:-support-channel-activation-plan.json}"
SECRET_FILE="${SUPPORT_CHANNEL_ACTIVATION_SECRETS_OUT:-support-channel-activation-secrets.env}"
WRITE_SECRETS="${SUPPORT_CHANNEL_ACTIVATION_WRITE_SECRETS:-true}"

if [ -z "$PROJECT_ID" ]; then
  echo "support channel activation plan: set SUPPORT_PROJECT_ID in .env or the environment" >&2
  exit 1
fi

if [ -z "$TOKEN" ]; then
  echo "support channel activation plan: set ADMIN_AUTH_TOKEN in .env or the environment" >&2
  exit 1
fi

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

tmp_file="$(mktemp)"
cleanup() {
  rm -f "$tmp_file"
}
trap cleanup EXIT

curl -fsS \
  -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/admin/projects/$PROJECT_ID/channels/activation-plan" \
  -o "$tmp_file"

mv "$tmp_file" "$PLAN_FILE"
trap - EXIT
echo "support channel activation plan: wrote $PLAN_FILE"

if is_true "$WRITE_SECRETS"; then
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$PLAN_FILE" "$SECRET_FILE" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
template = str(plan.get("secrets", {}).get("template") or "").strip()
if template:
    Path(sys.argv[2]).write_text(f"{template}\n", encoding="utf-8")
    print(f"support channel activation plan: wrote {sys.argv[2]}")
else:
    print("support channel activation plan: no missing secret template")
PY
  else
    echo "support channel activation plan: python3 missing; skipped $SECRET_FILE extraction" >&2
  fi
fi

#!/usr/bin/env bash
# Run the support schema gate from the packaged app container.

set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

compose_cmd=(docker compose)
if [ -n "${DOCKER_COMPOSE_COMMAND:-}" ]; then
  read -r -a compose_cmd <<< "$DOCKER_COMPOSE_COMMAND"
fi

exec "${compose_cmd[@]}" exec -T app python -m automail.support.schema_gate "$@"

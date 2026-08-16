#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* ]]; then
  ROOT="$(cygpath -w "$ROOT")"
  export MSYS_NO_PATHCONV=1
fi

suffix="$$-${RANDOM}"
caddy_container="mantly-quality-caddy-${suffix}"
pocketbase_container="mantly-quality-pocketbase-${suffix}"
admin_container="mantly-quality-admin-${suffix}"
addin_container="mantly-quality-addin-${suffix}"
landing_container="mantly-quality-landing-${suffix}"
caddy_data_volume="mantly-quality-caddy-data-${suffix}"
caddy_config_volume="mantly-quality-caddy-config-${suffix}"
pocketbase_data_volume="mantly-quality-pocketbase-data-${suffix}"

containers=(
  "$caddy_container"
  "$pocketbase_container"
  "$admin_container"
  "$addin_container"
  "$landing_container"
)
volumes=(
  "$caddy_data_volume"
  "$caddy_config_volume"
  "$pocketbase_data_volume"
)

cleanup() {
  docker rm --force --volumes "${containers[@]}" >/dev/null 2>&1 || true
  docker volume rm --force "${volumes[@]}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for compose_file in \
  docker-compose.yml \
  docker-compose.community.yml \
  docker-compose.onprem.yml \
  deploy/docker-compose.yml; do
  docker compose -f "$ROOT/$compose_file" config --no-interpolate --quiet
done

container_port() {
  docker port "$1" "$2/tcp" | sed -n '1s/.*://p'
}

wait_for_status() {
  local container="$1"
  local port="$2"
  local expected="$3"
  local path="${4:-/}"
  local host_port
  local status

  host_port="$(container_port "$container" "$port")"
  for _ in $(seq 1 60); do
    status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 1 --max-time 2 "http://127.0.0.1:${host_port}${path}" || true)"
    if [[ "$status" == "$expected" ]]; then
      return 0
    fi
    sleep 1
  done

  echo "Container $container did not return HTTP $expected on port $port." >&2
  docker logs "$container" >&2 || true
  return 1
}

docker volume create "$caddy_data_volume" >/dev/null
docker volume create "$caddy_config_volume" >/dev/null
docker volume create "$pocketbase_data_volume" >/dev/null

# Simulate volumes created by the former root-running images.
docker run --rm --user 0:0 --entrypoint /bin/sh \
  -v "$caddy_data_volume:/data" \
  -v "$caddy_config_volume:/config" \
  mantly-caddy-quality -ec \
  'touch /data/root-owned /config/root-owned && chmod 600 /data/root-owned /config/root-owned && chown 0:0 /data/root-owned /config/root-owned'
docker run --rm --user 0:0 --entrypoint /bin/sh \
  -v "$pocketbase_data_volume:/pb/pb_data" \
  mantly-pocketbase-quality -ec \
  'touch /pb/pb_data/root-owned && chmod 600 /pb/pb_data/root-owned && chown 0:0 /pb/pb_data/root-owned'

# Match the constrained one-shot ownership services in the Compose files.
docker run --rm --user 0:0 --network none --read-only \
  --cap-drop ALL --cap-add CHOWN --security-opt no-new-privileges:true \
  --entrypoint /bin/chown \
  -v "$caddy_data_volume:/data" \
  -v "$caddy_config_volume:/config" \
  mantly-caddy-quality -R 10001:10001 /data /config
docker run --rm --user 0:0 --network none --read-only \
  --cap-drop ALL --cap-add CHOWN --security-opt no-new-privileges:true \
  --entrypoint /usr/bin/chown \
  -v "$pocketbase_data_volume:/pb/pb_data" \
  mantly-pocketbase-quality -R 10001:10001 /pb/pb_data

docker run --rm --entrypoint /bin/sh \
  -v "$caddy_data_volume:/data" \
  -v "$caddy_config_volume:/config" \
  mantly-caddy-quality -ec \
  'test "$(id -u)" = 10001 && test -w /data/root-owned && test -w /config/root-owned'
docker run --rm --entrypoint /bin/sh \
  -v "$pocketbase_data_volume:/pb/pb_data" \
  mantly-pocketbase-quality -ec \
  'test "$(id -u)" = 10001 && test -w /pb/pb_data/root-owned'

docker run --rm --entrypoint /usr/bin/caddy mantly-caddy-quality \
  validate --config /etc/caddy/Caddyfile

docker run -d --name "$caddy_container" -p 127.0.0.1::80 \
  -v "$caddy_data_volume:/data" \
  -v "$caddy_config_volume:/config" \
  mantly-caddy-quality caddy file-server --listen :80 --root /usr/share/caddy >/dev/null
test "$(docker exec "$caddy_container" id -u)" = 10001
docker exec "$caddy_container" /bin/sh -ec \
  'test "$(stat -c "%u:%g:%a" /etc/caddy/Caddyfile)" = "0:0:444" && test ! -w /etc/caddy/Caddyfile'
wait_for_status "$caddy_container" 80 200

docker run -d --name "$pocketbase_container" -p 127.0.0.1::8090 \
  -v "$pocketbase_data_volume:/pb/pb_data" \
  -e PB_ADMIN_EMAIL=quality@example.com \
  -e PB_ADMIN_PASSWORD='QualitySmoke123!' \
  mantly-pocketbase-quality >/dev/null
test "$(docker exec "$pocketbase_container" id -u)" = 10001
wait_for_status "$pocketbase_container" 8090 200 /api/health

for spec in \
  "$admin_container:mantly-admin-quality" \
  "$addin_container:mantly-addin-quality" \
  "$landing_container:mantly-landing-quality"; do
  container="${spec%%:*}"
  image="${spec#*:}"
  docker run -d --name "$container" -p 127.0.0.1::8080 "$image" >/dev/null
  test "$(docker exec "$container" id -u)" = 101
  wait_for_status "$container" 8080 200
done

echo "Production image runtime and root-owned-volume upgrade smoke passed."

#!/bin/sh
# start.sh — apply migrations, upsert superuser, serve PocketBase.
#
# The PocketBase binary is baked into the Docker image at build time.
# No internet access is required at runtime.

set -e

PB_BINARY="/pb/pocketbase"

if [ ! -f "$PB_BINARY" ]; then
    echo "ERROR: PocketBase binary not found at $PB_BINARY"
    echo "The binary should be downloaded during 'docker build'. Check the Dockerfile."
    exit 1
fi

# Start PocketBase in background so migrations run before superuser upsert.
set -- serve \
    --http=0.0.0.0:8090 \
    --dir=/pb/pb_data \
    --migrationsDir=/pb/pb_migrations \
    --hooksDir=/pb/pb_hooks

if [ -n "${PB_CORS_ORIGINS:-}" ]; then
    set -- "$@" --origins="$PB_CORS_ORIGINS"
fi

"$PB_BINARY" "$@" &
PB_PID=$!

# Wait for PocketBase to be ready (up to 30 seconds).
MAX_WAIT=30
i=0
until wget -qO- "http://localhost:8090/api/health" > /dev/null 2>&1; do
    if [ $i -ge $MAX_WAIT ]; then
        echo "ERROR: PocketBase did not start within ${MAX_WAIT}s"
        exit 1
    fi
    i=$((i + 1))
    sleep 1
done
echo "PocketBase ready after ${i}s"

# Create or update superuser — idempotent, safe on every restart.
if [ -n "${PB_ADMIN_EMAIL}" ] && [ -n "${PB_ADMIN_PASSWORD}" ]; then
    echo "Upserting superuser: ${PB_ADMIN_EMAIL}"
    "$PB_BINARY" superuser upsert "${PB_ADMIN_EMAIL}" "${PB_ADMIN_PASSWORD}" \
        --dir=/pb/pb_data
    echo "Superuser ready."
else
    echo "WARNING: PB_ADMIN_EMAIL / PB_ADMIN_PASSWORD not set — superuser not created."
fi

# Bring PocketBase to foreground so the container stays alive.
wait $PB_PID

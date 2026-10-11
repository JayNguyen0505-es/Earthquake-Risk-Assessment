#!/usr/bin/env bash
set -e

# Resolve paths so this script can be called from any directory.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
deployment_dir="$PWD"
mkdir -p .runtime

# Start the Docker services.
docker compose -f "$deployment_dir/compose.yaml" up -d mysql nginx

# Start the already-built backend in the background.
export QUARKUS_HTTP_HOST=127.0.0.1 QUARKUS_HTTP_PORT=8080
export DB_URL="${DB_URL:-jdbc:mysql://127.0.0.1:${MYSQL_PORT:-3306}/vasteq?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&characterEncoding=UTF-8}"
nohup setsid python3 "$deployment_dir/../backend/scripts/run.py" \
    >.runtime/backend.log 2>&1 </dev/null &
echo "$!" >.runtime/backend.pid

printf 'Startup requested. Frontend: http://localhost:28080/\n'
printf 'Backend log: %s/.runtime/backend.log\n' "$deployment_dir"

#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 300
printf 'Stack started. Dashboard http://localhost:%s\n' "${WEB_PORT:-5173}"

#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U pipeline -d postgres <<'SQL'
SELECT 'CREATE DATABASE pipeline_test OWNER pipeline'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='pipeline_test') \gexec
SQL
docker compose exec -T -e TEST_DATABASE_URL=postgresql+psycopg://pipeline:pipeline-local@db:5432/pipeline_test api python -m pytest -q

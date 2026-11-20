\set ON_ERROR_STOP on
\timing on
BEGIN;
CREATE TEMP TABLE benchmark_runs (workspace text, created_at timestamptz, id uuid, status text);
INSERT INTO benchmark_runs
SELECT 'workspace-' || (n % 200),
       timestamptz '2025-01-01 00:00:00+00' + n * interval '1 minute',
       md5(n::text)::uuid,
       CASE WHEN n % 7 = 0 THEN 'failed' ELSE 'succeeded' END
FROM generate_series(1, 200000) AS s(n);
ANALYZE benchmark_runs;
\echo 'Before composite index'
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM benchmark_runs WHERE workspace='workspace-17'
  AND created_at >= timestamptz '2025-04-01 00:00:00+00'
ORDER BY created_at DESC,id DESC LIMIT 50;
CREATE INDEX benchmark_runs_workspace_created ON benchmark_runs(workspace,created_at DESC,id DESC);
ANALYZE benchmark_runs;
\echo 'After composite index (same leading columns and sort as migration 002)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM benchmark_runs WHERE workspace='workspace-17'
  AND created_at >= timestamptz '2025-04-01 00:00:00+00'
ORDER BY created_at DESC,id DESC LIMIT 50;
ROLLBACK;

# Verification record

The application services were run directly on Linux using PostgreSQL 16.2, Airflow 2.10.5, dbt Core 1.9.4 with the PostgreSQL adapter, Prometheus 3.3.0, Grafana 11.6.0, and Chromium. The production frontend build was served by Vite preview for this check. The Compose deployment uses Nginx.

| Check | Observed result |
| --- | --- |
| Compose configuration | Compose 2.35.1 validated the normal configuration and the browser-test profile. |
| Database and Airflow | Started from a fresh database directory, applied app and Airflow migrations, and recognized the DAG. A cron-scheduled run and manual runs reached success. |
| pytest | 6 passed using a real PostgreSQL test database. Coverage includes invalid input, bounded source backoff, workspace isolation, authorization, concurrent linked retry, destination uniqueness, and statistics. |
| Frontend | TypeScript checking and the Vite build passed. |
| Browser | 1 Playwright test passed in Chromium. It forced an initial SSE connection failure, observed reconnection and live failure updates, read validation details, submitted the corrected retry, checked the audit view and verified the viewer restriction. |
| Scripted demo | `DEMO PASSED`. The changed batch recorded 48 affected orders and preserved destination data. Concurrent requests produced one audited retry. Replaying the corrected source left 480 distinct North orders. South exercised two transient backoff events and advanced its incremental checkpoint. The test checked the authenticated event replay in both workspaces. |
| dbt | Successful builds each reported 14 passes (2 models and 12 tests) and no errors. SQL assertions matched the daily totals to the destination rows and verified quality trends. |
| Monitoring | `SMOKE PASSED`. Prometheus reported the application target as up. Grafana loaded the provisioned dashboard and reached Prometheus through its datasource. After the scripted and browser demos, both sources reported 2 failed runs and 2 successful retries. |
| Restart | Restarted the Linux services against the same database directory. Repeated initialization and smoke checks passed. The scheduled run, 3 demo users, 480 North orders, and 120 South orders persisted. |
| Terraform | `terraform fmt -check` and `terraform init -backend=false` passed. `terraform validate` stopped before schema validation because the AWS provider could not open a Unix socket in the workspace. No AWS resources were created. |
| Archive and scripts | Checked the ZIP contents and file integrity, extracted it into a directory with spaces using Linux PowerShell 7.5, parsed all four PowerShell scripts, and validated the extracted Compose configuration. Bash scripts passed syntax checks. |

Docker image builds and container startup were blocked by unavailable Docker daemon access. The Linux service run verified the application workflow. Docker Desktop and Windows PowerShell execution remain unverified.

## PostgreSQL indexing example

The query in `scripts/index-example.sql` selected the latest 50 matching runs for one workspace after a date cutoff. Both executions used the same 200,000 synthetic rows and predicates.

| Plan | Observed execution time | Observed work |
| --- | ---: | --- |
| Before index | 15.242 ms | Sequential scan reading 2,041 local buffers. PostgreSQL filtered out 199,648 rows and used a top-N sort. |
| After index | 0.053 ms | Composite index scan returned 50 rows in index order with 50 local buffer hits and 3 local reads. |

These timings are from one PostgreSQL 16.2 run and depend on data distribution, cache, and hardware. The production analogue is `migrations/002_run_history.sql`.

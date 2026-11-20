import os
import time

import httpx

from ops.api import AIRFLOW, AIRFLOW_AUTH
from ops.db import engine, one

API = os.getenv("DEMO_API", "http://127.0.0.1:8000")
PROM = os.getenv("DEMO_PROMETHEUS", "http://prometheus:9090")
GRAFANA = os.getenv("DEMO_GRAFANA", "http://grafana:3000")


def check(desc, callback, seconds=75):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if callback():
                print(f"OK {desc}", flush=True)
                return
            last = "condition false"
        except (httpx.HTTPError, ValueError, KeyError) as error:
            last = str(error)
        time.sleep(2)
    raise RuntimeError(f"Timed out checking {desc}: {last}")


def main():
    with httpx.Client(timeout=8, trust_env=False) as client:
        def get(base, path, **options):
            return client.get(base + path, **options).raise_for_status().json()

        check("API live and ready", lambda: get(API, "/health/live")["ok"] and get(API, "/health/ready")["ok"])
        with engine.connect() as connection:
            assert one(connection, "SELECT count(*) AS n FROM users")["n"] == 3
            assert one(connection, "SELECT count(*) AS n FROM schema_migrations")["n"] >= 2
        print("OK migrations and exactly three demo users")
        check("Airflow recognizes orders_pipeline",
              lambda: get(AIRFLOW, "/api/v1/dags/orders_pipeline", auth=AIRFLOW_AUTH)["is_active"])
        check("Prometheus scrapes pipelineops", lambda: any(
            target["labels"].get("job") == "pipelineops" and target["health"] == "up"
            for target in get(PROM, "/api/v1/targets")["data"]["activeTargets"]))
        check("Grafana dashboard and Prometheus data source", lambda:
              get(GRAFANA, "/api/dashboards/uid/pipelineops")["dashboard"]["uid"] == "pipelineops"
              and get(GRAFANA, "/api/datasources/uid/pipelineops-prom/health")["status"].lower() == "ok")
    print("SMOKE PASSED", flush=True)


if __name__ == "__main__":
    main()

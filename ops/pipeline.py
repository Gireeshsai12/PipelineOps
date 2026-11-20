import json
import os
import subprocess
from pathlib import Path
from uuid import UUID

from ops.core import fetch_orders, validate_batch
from ops.db import ROOT, engine, one, query, rows
from ops.runs import create_run, event, scheduled_id, window


def resolve(external_id, requested_id=None):
    with engine.begin() as connection:
        if requested_id:
            run_id = UUID(requested_id)
            run = one(connection, "SELECT * FROM runs WHERE id=:id FOR UPDATE", id=run_id)
            if not run:
                raise ValueError("Requested run does not exist")
        else:
            workspace = os.getenv("PIPELINE_SCHEDULE_WORKSPACE", "north")
            run_id = scheduled_id(external_id)
            start, end = window(connection, workspace)
            run = create_run(connection, workspace, "airflow-schedule", "clean", start, end,
                             "incremental", run_id=run_id, scheduled=True)
        if run["status"] in ("failed", "succeeded"):
            raise RuntimeError("Run already terminal. Use the PipelineOps retry workflow.")
        query(connection, """
            UPDATE runs SET status='running',started_at=coalesce(started_at,now())
            WHERE id=:id
            """, id=run_id)
        event(connection, run, "pipeline", "running", "Airflow accepted run")
        return str(run_id)


def record(run, task, state, message):
    with engine.begin() as connection:
        event(connection, run, task, state, message)


def lookup(run_id):
    with engine.connect() as connection:
        return one(connection, "SELECT * FROM runs WHERE id=:id", id=UUID(run_id))


def ingest(run):
    payload = fetch_orders(os.getenv("SOURCE_URL", "http://source:8080"), run["revision"],
                           run["start_date"], run["end_date"], run["correlation"],
                           lambda message: record(run, "ingestion", "backoff", message))
    with engine.begin() as connection:
        query(connection, "DELETE FROM staged WHERE run_id=:id", id=run["id"])
        if payload:
            from sqlalchemy import text
            connection.execute(text("""
                INSERT INTO staged VALUES (:id,:number,CAST(:payload AS jsonb))
                """), [{"id": run["id"], "number": i, "payload": json.dumps(row)}
                       for i, row in enumerate(payload, 1)])
    return f"Fetched {len(payload)} source rows"


def validate(run):
    with engine.begin() as connection:
        staged = rows(connection, "SELECT payload FROM staged WHERE run_id=:id ORDER BY row_num",
                      id=run["id"])
        valid, issues = validate_batch([row["payload"] for row in staged])
        for number, order_id, reason in issues:
            query(connection, """
                INSERT INTO validation_failures VALUES (:id,:number,:order_id,:reason)
                ON CONFLICT DO NOTHING
                """, id=run["id"], number=number, order_id=order_id, reason=reason)
    if issues:
        raise ValueError(f"Validation rejected the entire batch with {len(issues)} violations")
    return f"Validated {len(valid)} rows"


def load(run):
    with engine.begin() as connection:
        query(connection, """
            INSERT INTO orders(workspace,order_id,order_date,amount,source_run)
            SELECT :workspace,payload->>'order_id',CAST(payload->>'order_date' AS date),
                   CAST(payload->>'amount' AS numeric),:id
            FROM staged WHERE run_id=:id ORDER BY payload->>'order_id'
            ON CONFLICT (workspace,order_id) DO UPDATE SET order_date=excluded.order_date,
              amount=excluded.amount,source_run=excluded.source_run
            """, workspace=run["workspace"], id=run["id"])
    return "Committed transactional upsert"


def transform(run):
    location = Path(os.getenv("DBT_PROJECT_DIR", str(ROOT / "dbt")))
    subprocess.run([os.getenv("DBT_BIN", "dbt"), "build", "--project-dir", str(location),
                    "--profiles-dir", str(location)], check=True, timeout=180)
    return "dbt built and tested order totals and quality trends"


def finish(run, status, message):
    with engine.begin() as connection:
        changed = one(connection, """
            UPDATE runs SET status=:status,ended_at=now()
            WHERE id=:id AND status NOT IN ('succeeded','failed') RETURNING id
            """, status=status, id=run["id"])
        if not changed:
            return
        if status == "succeeded" and run["mode"] == "incremental":
            query(connection, """
                INSERT INTO checkpoints VALUES (:workspace,:end)
                ON CONFLICT (workspace) DO UPDATE
                SET last_end=greatest(checkpoints.last_end,excluded.last_end)
                """, workspace=run["workspace"], end=run["end_date"])
        event(connection, run, "pipeline", status, message)


def execute(run_id, task, operation):
    run = lookup(run_id)
    record(run, task, "running", "Task started")
    try:
        message = operation(run)
    except Exception as error:
        record(run, task, "failed", str(error) if type(error) in (ValueError, RuntimeError)
               else type(error).__name__)
        finish(run, "failed", f"{task} failed")
        raise
    record(run, task, "succeeded", message)
    return run

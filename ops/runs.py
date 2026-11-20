import os
from datetime import date, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from ops.core import FIRST_DATE
from ops.db import log, one, query


def event(connection, run, task, state, message):
    # Serialize publication per workspace so a committed SSE cursor cannot skip a late commit.
    query(connection, "SELECT pg_advisory_xact_lock(741, hashtext(:workspace))",
          workspace=run["workspace"])
    query(connection, """
        INSERT INTO run_events(workspace,run_id,correlation,task,state,message)
        VALUES (:workspace,:id,:correlation,:task,:state,:message)
        """, workspace=run["workspace"], id=run["id"], correlation=run["correlation"],
        task=task, state=state, message=message)
    log("run_event", workspace=run["workspace"], run_id=run["id"],
        correlation=run["correlation"], task=task, state=state, message=message)


def window(connection, workspace, start=None, end=None):
    if start is not None:
        return start, end
    checkpoint = one(connection, "SELECT last_end FROM checkpoints WHERE workspace=:workspace",
                     workspace=workspace)
    days = int(os.getenv("PIPELINE_WINDOW_DAYS", "1"))
    if not 1 <= days <= 366:
        raise ValueError("PIPELINE_WINDOW_DAYS must be between 1 and 366")
    first_date = date.fromisoformat(os.getenv("PIPELINE_FIRST_SOURCE_DATE", FIRST_DATE.isoformat()))
    start = checkpoint["last_end"] if checkpoint else first_date
    return start, start + timedelta(days=days)


def create_run(connection, workspace, actor, revision, start, end, mode, parent=None, run_id=None,
               scheduled=False):
    run = one(connection, """
        INSERT INTO runs(id,workspace,actor,revision,start_date,end_date,mode,parent_id,correlation,dispatched_at)
        VALUES (:id,:workspace,:actor,:revision,:start,:end,:mode,:parent,:correlation,
                CASE WHEN :scheduled THEN now() ELSE NULL END)
        ON CONFLICT DO NOTHING RETURNING *
        """, id=run_id or uuid4(), workspace=workspace, actor=actor, revision=revision,
        start=start, end=end, mode=mode, parent=parent, correlation=uuid4(), scheduled=scheduled)
    if run is None:
        return one(connection, """
            SELECT * FROM runs WHERE workspace=:workspace AND
              (id=:id OR parent_id=:parent)
            """, workspace=workspace, id=run_id, parent=parent)
    query(connection, """
        INSERT INTO audit_events(workspace,run_id,actor,action) VALUES (:workspace,:id,:actor,:action)
        """, workspace=workspace, id=run["id"], actor=actor,
        action="retry_corrected" if parent and revision == "corrected" else "retry" if parent else "start")
    event(connection, run, "pipeline", "queued", "Awaiting Airflow")
    return run


def scheduled_id(external_id):
    return uuid5(NAMESPACE_URL, "pipelineops/airflow/" + external_id)

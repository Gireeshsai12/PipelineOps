import asyncio
import hashlib
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import date
from typing import Literal
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client.core import CounterMetricFamily, HistogramMetricFamily
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

from ops.core import compare, fixture, validate_batch
from ops.db import engine, log, one, password_hash, query, rows
from ops.runs import create_run, event, window

Revision = Literal["clean", "changed", "corrected", "transient"]
bearer = HTTPBearer(auto_error=False)
AIRFLOW = os.getenv("AIRFLOW_URL", "http://airflow-web:8080")
AIRFLOW_AUTH = (os.getenv("AIRFLOW_USER", "pipeline"), os.getenv("AIRFLOW_PASSWORD", "local-airflow-demo"))


def pending_dispatch():
    with engine.connect() as connection:
        return rows(connection, """
            SELECT id, correlation FROM runs WHERE status='queued' AND dispatched_at IS NULL
            ORDER BY created_at LIMIT 20
            """)


def mark_dispatched(run_id):
    with engine.begin() as connection:
        query(connection, "UPDATE runs SET dispatched_at=now() WHERE id=:id", id=run_id)


async def dispatch_loop():
    async with httpx.AsyncClient(base_url=AIRFLOW, auth=AIRFLOW_AUTH, timeout=5, trust_env=False) as client:
        while True:
            try:
                for run in await run_in_threadpool(pending_dispatch):
                    run_id = str(run["id"])
                    result = await client.post("/api/v1/dags/orders_pipeline/dagRuns", json={
                        "dag_run_id": f"api__{run_id}", "conf": {"pipeline_run_id": run_id},
                    })
                    if result.is_success or result.status_code == 409:
                        await run_in_threadpool(mark_dispatched, run_id)
                        log("airflow_dispatch", run_id=run_id, correlation=run["correlation"])
                    else:
                        log("airflow_dispatch_pending", status=result.status_code, correlation=run["correlation"])
                        break
            except Exception as error:
                log("airflow_dispatch_unavailable", error=type(error).__name__)
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(_app):
    worker = asyncio.create_task(dispatch_loop())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title="PipelineOps API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
)


class Credentials(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)


class Launch(BaseModel):
    revision: Revision = "clean"
    mode: Literal["incremental", "backfill"] = "incremental"
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def check_window(self):
        if self.mode == "incremental" and (self.start or self.end):
            raise ValueError("Incremental uses the workspace checkpoint")
        if self.mode == "backfill" and (
            not self.start or not self.end or not 0 < (self.end - self.start).days <= 366
        ):
            raise ValueError("Backfill requires a positive window of up to 366 days")
        return self


class Retry(BaseModel):
    use_corrected_fixture: bool = False


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticated(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(401, "Sign in first")
    return digest(credentials.credentials)


def member(connection, token, workspace, write=False):
    session = one(connection, """
        SELECT username FROM sessions WHERE token_hash=:token AND expires_at>now()
        """, token=token)
    if not session:
        raise HTTPException(401, "Session expired or invalid")
    user = one(connection, """
        SELECT username,role FROM memberships WHERE workspace=:workspace AND username=:username
        """, workspace=workspace, username=session["username"])
    if not user or (write and user["role"] != "operator"):
        raise HTTPException(403, "Workspace permission required")
    return user


def find_run(connection, workspace, run_id, lock=False):
    statement = "SELECT * FROM runs WHERE workspace=:workspace AND id=:id"
    run = one(connection, statement + (" FOR UPDATE" if lock else ""), workspace=workspace, id=run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@app.get("/health/live")
def live():
    return {"ok": True}


@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as connection:
            query(connection, "SELECT 1 FROM runs LIMIT 1")
    except Exception:
        raise HTTPException(503, "Database unavailable") from None
    return {"ok": True}


@app.post("/api/sign-in")
def sign_in(data: Credentials):
    with engine.begin() as connection:
        user = one(connection, "SELECT * FROM users WHERE username=:name", name=data.username)
        salt = user["password_hash"].split(":")[0] if user else "0" * 32
        candidate = password_hash(data.password, salt)
        if not user or not hmac.compare_digest(candidate, user["password_hash"]):
            raise HTTPException(401, "Invalid credentials")
        token = secrets.token_urlsafe(32)
        query(connection, "DELETE FROM sessions WHERE expires_at<=now()")
        query(connection, "INSERT INTO sessions(token_hash,username) VALUES (:token,:name)",
              token=digest(token), name=data.username)
        memberships = rows(connection, """
            SELECT workspace,role FROM memberships WHERE username=:name ORDER BY workspace
            """, name=data.username)
    return {"token": token, "username": data.username, "memberships": memberships}


@app.post("/api/sign-out", status_code=204)
def sign_out(token=Depends(authenticated)):
    with engine.begin() as connection:
        query(connection, "DELETE FROM sessions WHERE token_hash=:token", token=token)
    return Response(status_code=204)


base = "/api/workspaces/{workspace}"


@app.get(base + "/runs")
def history(workspace: str, status: Literal["queued","running","failed","succeeded"] | None = None,
            start: date | None = None, end: date | None = None, token=Depends(authenticated)):
    with engine.connect() as connection:
        member(connection, token, workspace)
        where = ["workspace=:workspace"]
        if status:
            where.append("status=:status")
        if start:
            where.append("created_at>=CAST(:start AS date)")
        if end:
            where.append("created_at<CAST(:end AS date)+interval '1 day'")
        return rows(connection, "SELECT * FROM runs WHERE " + " AND ".join(where) +
                    " ORDER BY created_at DESC,id DESC LIMIT 100",
                    workspace=workspace, status=status, start=start, end=end)


@app.post(base + "/runs", status_code=202)
def launch(workspace: str, launch: Launch, token=Depends(authenticated)):
    with engine.begin() as connection:
        user = member(connection, token, workspace, write=True)
        start, end = window(connection, workspace, launch.start, launch.end)
        return create_run(connection, workspace, user["username"], launch.revision, start, end, launch.mode)


@app.get(base + "/runs/{run_id}")
def detail(workspace: str, run_id: UUID, token=Depends(authenticated)):
    with engine.connect() as connection:
        member(connection, token, workspace)
        run = find_run(connection, workspace, run_id)
        events = rows(connection, """
            SELECT * FROM run_events WHERE workspace=:workspace AND run_id=:id ORDER BY seq
            """, workspace=workspace, id=run_id)
        child = one(connection, """
            SELECT id,status FROM runs WHERE workspace=:workspace AND parent_id=:id
            """, workspace=workspace, id=run_id)
        return {"run": run, "events": events, "retry": child}


@app.get(base + "/runs/{run_id}/failures")
def failures(workspace: str, run_id: UUID, token=Depends(authenticated)):
    with engine.connect() as connection:
        member(connection, token, workspace)
        find_run(connection, workspace, run_id)
        return rows(connection, """
            SELECT row_num,order_id,reason FROM validation_failures WHERE run_id=:id ORDER BY row_num,reason
            """, id=run_id)


@app.post(base + "/runs/{run_id}/retry", status_code=202)
def retry(workspace: str, run_id: UUID, data: Retry, token=Depends(authenticated)):
    with engine.begin() as connection:
        user = member(connection, token, workspace, write=True)
        original = find_run(connection, workspace, run_id, lock=True)
        if original["status"] != "failed":
            raise HTTPException(409, "Only failed runs can be retried")
        if data.use_corrected_fixture and original["revision"] != "changed":
            raise HTTPException(409, "Corrected fixture is available for the changed batch")
        child = one(connection, "SELECT * FROM runs WHERE workspace=:workspace AND parent_id=:id",
                    workspace=workspace, id=run_id)
        if child:
            return child
        revision = "corrected" if data.use_corrected_fixture else original["revision"]
        return create_run(connection, workspace, user["username"], revision, original["start_date"],
                          original["end_date"], original["mode"], parent=run_id)


@app.get(base + "/audit")
def audit(workspace: str, token=Depends(authenticated)):
    with engine.connect() as connection:
        member(connection, token, workspace)
        return rows(connection, """
            SELECT * FROM audit_events WHERE workspace=:workspace ORDER BY id DESC LIMIT 100
            """, workspace=workspace)


@app.get(base + "/comparison")
def comparison(workspace: str, token=Depends(authenticated)):
    with engine.connect() as connection:
        member(connection, token, workspace)
    samples = [fixture(name) for name in ("cohort_clean", "changed")]
    return compare(*[(len(batch), len({issue[0] for issue in validate_batch(batch)[1]}))
                     for batch in samples])


def read_events(token, workspace, cursor):
    with engine.connect() as connection:
        member(connection, token, workspace)
        if cursor is None:
            return one(connection, """
                SELECT coalesce(max(seq),0) AS cursor FROM run_events WHERE workspace=:workspace
                """, workspace=workspace)["cursor"]
        return rows(connection, """
            SELECT * FROM run_events WHERE workspace=:workspace AND seq>:cursor ORDER BY seq LIMIT 100
            """, workspace=workspace, cursor=cursor)


@app.get(base + "/events")
async def stream(workspace: str, request: Request, token=Depends(authenticated),
                 last_event_id: int | None = Header(default=None, ge=0)):
    # Authorize before sending response headers, and recheck before each poll.
    tail = await run_in_threadpool(read_events, token, workspace, None)
    cursor = last_event_id if last_event_id is not None else tail

    async def feed():
        nonlocal cursor
        yield "event: ready\ndata: {}\n\n"
        for tick in range(120):
            if await request.is_disconnected():
                break
            try:
                updates = await run_in_threadpool(read_events, token, workspace, cursor)
            except HTTPException:
                break
            for item in updates:
                cursor = item["seq"]
                payload = json.dumps(jsonable_encoder(item))
                yield f"id: {cursor}\nevent: run\ndata: {payload}\n\n"
            if tick % 10 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(feed(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class Metrics:
    def collect(self):
        with engine.connect() as connection:
            outcomes = rows(connection, """
                SELECT status, parent_id IS NOT NULL AS retry, count(*) AS count
                FROM runs WHERE status IN ('failed','succeeded') GROUP BY 1,2
                """)
            durations = rows(connection, """
                SELECT extract(epoch FROM ended_at-started_at)::float AS seconds
                FROM runs WHERE ended_at IS NOT NULL AND started_at IS NOT NULL
                """)
            count = one(connection, "SELECT count(*) AS count FROM validation_failures")["count"]
        run_count = CounterMetricFamily("pipelineops_runs", "Terminal runs", labels=["outcome","retry"])
        counts = {(row["status"], row["retry"]): row["count"] for row in outcomes}
        for status in ("succeeded", "failed"):
            for retry_value in (False, True):
                run_count.add_metric([status, str(retry_value).lower()], counts.get((status, retry_value), 0))
        yield run_count
        seconds = [row["seconds"] for row in durations]
        duration = HistogramMetricFamily("pipelineops_run_duration_seconds", "Elapsed run duration")
        buckets = [(str(edge), sum(value <= edge for value in seconds)) for edge in (1, 5, 15, 30, 60, 180)]
        duration.add_metric([], buckets + [("+Inf", len(seconds))], sum(seconds))
        yield duration
        yield CounterMetricFamily("pipelineops_validation_failures", "Recorded violations", value=count)


@app.get("/metrics")
def metrics():
    registry = CollectorRegistry()
    registry.register(Metrics())
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

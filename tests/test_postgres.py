import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ops import api, db, pipeline
from ops.core import fixture_window

NORTH = "/api/workspaces/north"
SOUTH = "/api/workspaces/south"
WINDOW = {"mode": "backfill", "start": "2025-01-01", "end": "2025-01-04"}


@pytest.fixture(scope="module")
def database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    engine = create_engine(url, pool_pre_ping=True)
    if not engine.url.database.endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must name a disposable database ending in _test")
    with engine.begin() as connection:
        db.query(connection, "DROP SCHEMA public CASCADE")
        db.query(connection, "CREATE SCHEMA public")
    with pytest.MonkeyPatch.context() as patch:
        for module in (db, api, pipeline):
            patch.setattr(module, "engine", engine)
        db.migrate()
        yield engine
    engine.dispose()


def user(client, username):
    result = client.post("/api/sign-in", json={"username": username, "password": "pipeline-demo"})
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json()["token"]}


def launch(client, auth, cohort, path=NORTH):
    response = client.post(path + "/runs", json={**WINDOW, "revision": cohort}, headers=auth)
    assert response.status_code == 202, response.text
    return response.json()


def stages(run, success):
    pipeline.resolve("pytest", run["id"])
    pipeline.execute(run["id"], "ingestion", pipeline.ingest)
    if not success:
        with pytest.raises(ValueError):
            pipeline.execute(run["id"], "validation", pipeline.validate)
        return
    pipeline.execute(run["id"], "validation", pipeline.validate)
    pipeline.execute(run["id"], "loading", pipeline.load)
    pipeline.finish(pipeline.lookup(run["id"]), "succeeded", "Test load completed")


def test_workflow_authorization_and_concurrency(database, monkeypatch):
    monkeypatch.setattr(pipeline, "fetch_orders", lambda _, revision, start, end, *args:
                        fixture_window(revision, start, end))
    client = TestClient(api.app)
    assert client.get(NORTH + "/runs").status_code == 401
    operator, viewer, south = (user(client, name) for name in ("operator", "viewer", "south-operator"))
    assert client.post(NORTH + "/runs", headers=viewer, json=WINDOW).status_code == 403
    clean = launch(client, operator, "clean")
    stages(clean, success=True)
    bad = launch(client, operator, "changed")
    path = NORTH + "/runs/" + bad["id"]
    stages(bad, success=False)
    with database.connect() as connection:
        assert db.one(connection, "SELECT count(*) AS n FROM orders")["n"] == 240
        assert not db.rows(connection, "SELECT * FROM orders WHERE source_run=:id", id=bad["id"])
    errors = client.get(path + "/failures", headers=viewer).json()
    assert len(errors) == 48
    assert client.post(path + "/retry", headers=viewer, json={}).status_code == 403
    assert client.get(path, headers=south).status_code == 403
    assert client.get(SOUTH + "/runs/" + bad["id"], headers=south).status_code == 404
    assert client.get(NORTH + "/events", headers=south).status_code == 403
    assert client.post(path + "/retry", headers=south, json={}).status_code == 403
    token = api.digest(south["Authorization"].split()[-1])
    assert api.read_events(token, "south", 0) == []
    south_run = launch(client, south, "clean", SOUTH)
    stages(south_run, success=True)
    assert all(event["run_id"] == pipeline.lookup(south_run["id"])["id"]
               for event in api.read_events(token, "south", 0))

    def retry(_):
        response = client.post(path + "/retry", headers=operator, json={"use_corrected_fixture": True})
        assert response.status_code == 202, response.text
        return response.json()

    with ThreadPoolExecutor(2) as pool:
        first, second = list(pool.map(retry, range(2)))
    assert first["id"] == second["id"] and first["parent_id"] == bad["id"]
    stages(first, success=True)
    replay = launch(client, operator, "corrected")
    stages(replay, success=True)
    assert client.get(path + "/failures", headers=viewer).json() == errors
    db.migrate()
    with database.connect() as connection:
        for workspace, expected in (("north", 480), ("south", 240)):
            assert db.one(connection, """
                SELECT count(*) AS n, count(DISTINCT order_id) AS distinct
                FROM orders WHERE workspace=:w
                """, w=workspace) == {"n": expected, "distinct": expected}
        assert db.one(connection, "SELECT count(*) AS n FROM users")["n"] == 3
        assert db.one(connection, """
            SELECT actor,workspace,action FROM audit_events WHERE run_id=:id
            """, id=first["id"]) == {"actor": "operator", "workspace": "north", "action": "retry_corrected"}

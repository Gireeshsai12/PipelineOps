import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx

from ops.db import engine, one, rows

URL = os.getenv("DEMO_API", "http://127.0.0.1:8000")
TIMEOUT = int(os.getenv("DEMO_TIMEOUT", "600"))
NORTH = "/api/workspaces/north"
SOUTH = "/api/workspaces/south"
WINDOW = {"mode": "backfill", "start": "2025-01-01", "end": "2025-01-04"}


def expect(response, status=200):
    if response.status_code != status:
        raise AssertionError(f"{response.request.method} {response.request.url.path}: "
                             f"expected {status}, got {response.status_code}: {response.text[:300]}")
    return response.json()


@contextmanager
def client(username):
    with httpx.Client(base_url=URL, timeout=12, trust_env=False) as session:
        token = expect(session.post("/api/sign-in", json={
            "username": username, "password": "pipeline-demo",
        }))["token"]
        session.headers["Authorization"] = f"Bearer {token}"
        yield session


def launch(session, base, revision, window=WINDOW):
    return expect(session.post(base + "/runs", json={**window, "revision": revision}), 202)


def wait(session, base, run, terminal):
    deadline = time.monotonic() + TIMEOUT
    path = base + "/runs/" + run["id"]
    while time.monotonic() < deadline:
        detail = expect(session.get(path))
        status = detail["run"]["status"]
        if status in ("failed", "succeeded"):
            assert status == terminal, detail
            print(f"OK {run['revision']} {status} {run['id']} correlation={run['correlation']}", flush=True)
            return detail
        time.sleep(2)
    raise TimeoutError(f"Run {run['id']} did not reach {terminal} within {TIMEOUT}s")


def assert_replayed_events(session, base, run, wanted):
    path = base + "/events"
    deadline = time.monotonic() + 20
    observed = []
    with session.stream("GET", path, headers={"Last-Event-ID": "0"}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if time.monotonic() >= deadline:
                break
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            if not payload:
                continue
            assert payload["workspace"] == base.rsplit("/", 1)[1]
            if payload["run_id"] == run["id"]:
                assert payload["correlation"] == run["correlation"]
                if payload["task"] == "pipeline":
                    observed.append(payload["state"])
                if observed == wanted:
                    return
    raise AssertionError(f"SSE pipeline states: expected {wanted}, observed {observed}")


def order_snapshot():
    with engine.connect() as connection:
        return rows(connection, """
            SELECT * FROM orders WHERE workspace='north' ORDER BY order_id
            """)


def main():
    with client("operator") as operator, client("viewer") as viewer, client("south-operator") as south:
        clean = launch(operator, NORTH, "clean")
        wait(operator, NORTH, clean, "succeeded")
        bad = launch(operator, NORTH, "changed")
        wait(operator, NORTH, bad, "failed")
        path = NORTH + "/runs/" + bad["id"]
        issues = expect(operator.get(path + "/failures"))
        assert len({issue["order_id"] for issue in issues}) == 48, issues
        assert_replayed_events(operator, NORTH, bad, ["queued", "running", "failed"])
        with engine.connect() as connection:
            assert not rows(connection, """
                SELECT 1 FROM orders
                WHERE workspace='north' AND source_run=:id
                LIMIT 1
            """, id=bad["id"]), "Failed validation wrote destination rows"
        expect(viewer.post(path + "/retry", json={}), 403)
        assert expect(viewer.get(path))["run"]["id"] == bad["id"]
        expect(south.get(path), 403)
        expect(south.get(SOUTH + "/runs/" + bad["id"]), 404)
        expect(south.get(NORTH + "/events"), 403)
        expect(south.post(path + "/retry", json={}), 403)
        print("OK 48 affected orders, fail-closed writes, viewer and tenant authorization", flush=True)

        def retry():
            return expect(operator.post(path + "/retry", json={"use_corrected_fixture": True}), 202)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: retry(), range(2)))
        assert first["id"] == second["id"] and first["parent_id"] == bad["id"]
        wait(operator, NORTH, first, "succeeded")
        assert expect(operator.get(path + "/failures")) == issues
        audit = [item for item in expect(operator.get(NORTH + "/audit")) if item["run_id"] == first["id"]]
        assert len(audit) == 1 and audit[0]["actor"] == "operator"
        assert audit[0]["action"] == "retry_corrected" and audit[0]["workspace"] == "north" and audit[0]["at"]
        print("OK concurrent retry deduplicated, linked and audited", flush=True)
        recovered = order_snapshot()
        wait(operator, NORTH, launch(operator, NORTH, "corrected"), "succeeded")
        assert [(r["order_id"], r["amount"]) for r in order_snapshot()] == [
            (r["order_id"], r["amount"]) for r in recovered]
        with engine.connect() as connection:
            assert not rows(connection, """
                SELECT workspace,order_id FROM orders GROUP BY 1,2 HAVING count(*) <> 1
                """)
            total = one(connection, """
                SELECT count(*) AS n FROM orders WHERE workspace='north' AND order_id LIKE 'D-%'
                """)["n"]
            analytics = one(connection, """
                SELECT sum(order_count) AS n, sum(order_total) AS total
                FROM analytics.daily_order_totals WHERE workspace='north'
                """)
            expected = one(connection, """
                SELECT count(*) AS n, sum(amount) AS total FROM orders WHERE workspace='north'
                """)
            assert total == 240 and analytics == expected and expected["n"] == 480
            trends = one(connection, """
                SELECT failed_runs,rejected_orders FROM analytics.data_quality_trends
                WHERE workspace='north' AND source_date='2025-01-01'
                """)
            assert trends["failed_runs"] >= 1 and trends["rejected_orders"] >= 48
        print("OK SQL uniqueness, 480 north orders and verified dbt outputs", flush=True)
        transient = launch(south, SOUTH, "transient", {"mode": "incremental"})
        detail = wait(south, SOUTH, transient, "succeeded")
        assert_replayed_events(south, SOUTH, transient, ["queued", "running", "succeeded"])
        assert [event["state"] for event in detail["events"]].count("backoff") == 2
        with engine.connect() as connection:
            assert str(one(connection, "SELECT last_end FROM checkpoints WHERE workspace='south'")["last_end"]) == transient["end_date"]
        print("OK deterministic backoff and incremental checkpoint", flush=True)
        print("DEMO PASSED", flush=True)


if __name__ == "__main__":
    main()

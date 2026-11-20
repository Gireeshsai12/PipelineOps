from datetime import date

import httpx
import pytest

from ops import core
from ops.source import app as source
from fastapi.testclient import TestClient


def test_bad_and_corrected_fixtures_share_ids():
    bad = core.fixture("changed")
    corrected = core.fixture("corrected")
    valid, errors = core.validate_batch(bad)
    assert len(valid) == 192
    assert len(errors) == 48
    assert {e[1] for e in errors} == {row["order_id"] for row in bad[:48]}
    assert [row["order_id"] for row in bad] == [row["order_id"] for row in corrected]
    assert not core.validate_batch(corrected)[1]


def test_date_window_and_duplicate():
    items = core.fixture_window("clean", date(2025, 1, 1), date(2025, 1, 2))
    assert len(items) == 120
    valid, errors = core.validate_batch([items[0], items[0]])
    assert len(valid) == 1 and errors[0][2].endswith("duplicate within batch")


def test_statistics():
    result = core.compare((240, 12), (240, 48))
    assert result["difference_pp"] == pytest.approx(15)
    assert result["p_value"] == pytest.approx(6.74825e-7, rel=0.001)
    assert result["ci95_pp"] == pytest.approx([9.2367, 20.7633], abs=.01)
    assert core.compare((10, 2), (10, 5))["p_value"] is None
    with pytest.raises(ValueError):
        core.compare((0, 0), (10, 5))


def test_transient_source_recovers(monkeypatch):
    api = TestClient(source)
    factory = httpx.Client
    monkeypatch.setattr(core.httpx, "Client", lambda **_: factory(trust_env=False,
        transport=httpx.MockTransport(lambda req: api.get(req.url.raw_path.decode(), headers=req.headers))
    ))
    delays, messages = [], []
    data = core.fetch_orders("http://mock", "transient", date(2025, 1, 1), date(2025, 1, 2),
                             "test", messages.append, sleep=delays.append)
    assert len(data) == 120 and delays == [1, 2]
    assert all("503" in message for message in messages)


def test_transient_failure_is_bounded(monkeypatch):
    factory = httpx.Client
    monkeypatch.setattr(core.httpx, "Client", lambda **_: factory(trust_env=False,
        transport=httpx.MockTransport(lambda req: httpx.Response(503, request=req))))
    delays = []
    with pytest.raises(RuntimeError, match="after 4 attempts"):
        core.fetch_orders("http://mock", "clean", date(2025, 1, 1), date(2025, 1, 2),
                          "test", lambda _: None, sleep=delays.append)
    assert delays == [1, 2, 4]

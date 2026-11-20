import csv
import math
import time
from datetime import date
from decimal import Decimal
from statistics import NormalDist
from typing import Annotated

import httpx
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from ops.db import ROOT

REVISIONS = ("clean", "changed", "corrected", "transient")
FIRST_DATE = date(2025, 1, 1)


class Order(BaseModel):
    order_id: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9-]{1,40}$")]
    order_date: date
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]


def validate_batch(items):
    valid, issues, seen = [], [], set()
    for number, raw in enumerate(items, 1):
        try:
            order = Order.model_validate(raw)
            if order.order_id in seen:
                issues.append((number, order.order_id, "order_id: duplicate within batch"))
            else:
                valid.append(order)
                seen.add(order.order_id)
        except ValidationError as error:
            for issue in error.errors():
                field = ".".join(map(str, issue["loc"]))
                issues.append((number, str(raw.get("order_id", "")), f"{field}: {issue['msg']}"))
    return valid, issues


def fixture(revision):
    name = "clean" if revision == "transient" else revision
    with (ROOT / "fixtures" / f"{name}.csv").open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def fixture_window(revision, start, end):
    return [row for row in fixture(revision) if start <= date.fromisoformat(row["source_date"]) < end]


def fetch_orders(base, revision, start, end, correlation, report, sleep=time.sleep):
    with httpx.Client(timeout=8, trust_env=False) as client:
        for attempt in range(1, 5):
            try:
                response = client.get(f"{base}/orders", params={
                    "revision": revision, "start": start, "end": end, "attempt": attempt,
                }, headers={"X-Correlation-ID": str(correlation)})
                if response.status_code not in {429, 502, 503, 504}:
                    response.raise_for_status()
                    return response.json()
                failure = f"HTTP {response.status_code}"
            except httpx.TransportError as error:
                failure = type(error).__name__
            if attempt == 4:
                raise RuntimeError(f"Source unavailable after {attempt} attempts ({failure})")
            delay = 2 ** (attempt - 1)
            report(f"Source {failure}. Attempt {attempt + 1} in {delay}s.")
            sleep(delay)


def compare(clean, changed):
    clean_n, clean_bad = clean
    changed_n, changed_bad = changed
    if any(t <= 0 or not 0 <= b <= t for t, b in (clean, changed)):
        raise ValueError("Each cohort needs a valid positive sample size.")
    p1, p2 = clean_bad / clean_n, changed_bad / changed_n
    delta = p2 - p1
    pooled = (clean_bad + changed_bad) / (clean_n + changed_n)
    result = {"clean": {"n": clean_n, "failures": clean_bad, "percent": p1 * 100},
              "changed": {"n": changed_n, "failures": changed_bad, "percent": p2 * 100},
              "difference_pp": delta * 100, "p_value": None, "ci95_pp": None}
    if min(clean_bad, clean_n - clean_bad, changed_bad, changed_n - changed_bad,
           clean_n * pooled, changed_n * pooled,
           clean_n * (1 - pooled), changed_n * (1 - pooled)) >= 10:
        standard = math.sqrt(pooled * (1 - pooled) * (1 / clean_n + 1 / changed_n))
        margin = NormalDist().inv_cdf(.975) * math.sqrt(
            p1 * (1 - p1) / clean_n + p2 * (1 - p2) / changed_n
        )
        result["p_value"] = math.erfc(abs(delta / standard) / math.sqrt(2))
        result["ci95_pp"] = [(delta - margin) * 100, (delta + margin) * 100]
    return result

from datetime import date
from typing import Literal

from fastapi import FastAPI, Header, HTTPException

from ops.core import fixture_window
from ops.db import log

app = FastAPI(title="Synthetic orders source")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/orders")
def orders(revision: Literal["clean", "changed", "corrected", "transient"],
           start: date, end: date, attempt: int = 1,
           x_correlation_id: str = Header(default="unknown")):
    if start >= end:
        raise HTTPException(422, "Empty date window")
    log("source_request", correlation=x_correlation_id, revision=revision, attempt=attempt)
    if revision == "transient" and attempt <= 2:
        raise HTTPException(503, "Deterministic temporary outage")
    return fixture_window(revision, start, end)

"""FastAPI surface.

POST /audit          start a run, returns run_id
GET  /audit/{id}/stream  SSE telemetry + lifecycle events
GET  /categories     available category+vendor lists
POST /vote/{category}   cast an audience vote
GET  /vote/stream    SSE stream of live vote tallies
GET  /healthz        liveness probe
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import orjson
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

from app.telemetry import TelemetryBus


app = FastAPI(title="Receipts — Burden of Proof")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── in-memory state ──────────────────────────────────────────────────────────

_RUNS: dict[str, TelemetryBus] = {}
_TASKS: dict[str, asyncio.Task] = {}

_VOTES: dict[str, int] = {}
_VOTE_SUBS: list[asyncio.Queue] = []


# ── request/response models ──────────────────────────────────────────────────

class AuditRequest(BaseModel):
    category: str
    vendor_urls: list[tuple[str, str]] = Field(
        ..., description="List of (vendor_name, url) tuples to audit."
    )
    naive: bool = False
    n: Optional[int] = None


class AuditAccepted(BaseModel):
    run_id: str
    stream_url: str


# ── audit endpoints ──────────────────────────────────────────────────────────

@app.post("/audit", response_model=AuditAccepted)
async def audit(req: AuditRequest) -> AuditAccepted:
    bus = TelemetryBus()
    _RUNS[bus.run_id] = bus

    from app.pipeline.orchestrator import run_market

    task = asyncio.create_task(
        run_market(
            req.category,
            req.vendor_urls,
            bus=bus,
            naive=req.naive,
            n=req.n,
        )
    )
    _TASKS[bus.run_id] = task

    return AuditAccepted(
        run_id=bus.run_id,
        stream_url=f"/audit/{bus.run_id}/stream",
    )


@app.get("/audit/{run_id}/stream")
async def stream(run_id: str) -> EventSourceResponse:
    bus = _RUNS.get(run_id)
    if bus is None:
        raise HTTPException(status_code=404, detail="run not found")

    queue = bus.subscribe()

    async def gen():
        try:
            while True:
                event = await queue.get()
                yield {
                    "event": "telemetry",
                    "data": orjson.dumps(event.model_dump(mode="json")).decode(),
                }
        finally:
            bus.unsubscribe(queue)

    return EventSourceResponse(gen())


# ── categories endpoint ──────────────────────────────────────────────────────

_VENDORS_DIR = Path(__file__).resolve().parents[1] / "data" / "vendors"


@app.get("/categories")
async def categories() -> list[dict]:
    result = []
    if _VENDORS_DIR.exists():
        for f in sorted(_VENDORS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                result.append(data)
                _VOTES.setdefault(data["category"], 0)
            except Exception:
                pass
    return result


# ── vote endpoints ────────────────────────────────────────────────────────────

@app.post("/vote/{category}")
async def vote(category: str) -> dict:
    _VOTES[category] = _VOTES.get(category, 0) + 1
    snapshot = dict(_VOTES)
    for q in list(_VOTE_SUBS):
        try:
            q.put_nowait(snapshot)
        except asyncio.QueueFull:
            pass
    return {"votes": snapshot}


@app.get("/vote/stream")
async def vote_stream() -> EventSourceResponse:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _VOTE_SUBS.append(q)
    q.put_nowait(dict(_VOTES))  # seed current state immediately

    async def gen():
        try:
            while True:
                snapshot = await q.get()
                yield {"event": "votes", "data": orjson.dumps(snapshot).decode()}
        finally:
            if q in _VOTE_SUBS:
                _VOTE_SUBS.remove(q)

    return EventSourceResponse(gen())


# ── health ────────────────────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ── static frontend ───────────────────────────────────────────────────────────

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="ui")

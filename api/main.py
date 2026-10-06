"""HTTP API: REST + Server-Sent Events. Binds to 127.0.0.1; the tailnet reaches it through `tailscale serve`.

uvicorn api.main:app --host 127.0.0.1 --port 8260
"""

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import redis
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from api.library import router as library_router
from core import VERSION, bus
from core import jobs as J
from core import library as L
from core.db import get_engine, session_scope
from core.models import Job, Preset
from core.settings import get_settings

log = logging.getLogger("api")
SMOKE_HTML = (Path(__file__).parent / "smoke.html").read_text(encoding="utf-8")
WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


async def maintenance_loop(stop: asyncio.Event) -> None:
    """Reaper + reconcile also run here, so recovery does not depend on any worker being alive."""
    period = get_settings().heartbeat_s

    def once():
        r = bus.get_redis()
        with session_scope() as s:
            J.reap(s, r)
        with session_scope() as s:
            J.reconcile(s, r)

    while not stop.is_set():
        try:
            await run_in_threadpool(once)
        except Exception:
            log.exception("maintenance pass failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=period)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with session_scope() as s:
            L.sync_presets(s)
    except Exception:
        log.exception("could not sync built-in presets (database down?)")
    stop = asyncio.Event()
    task = asyncio.create_task(maintenance_loop(stop))
    yield
    stop.set()
    await task


app = FastAPI(title="1260", version=VERSION, lifespan=lifespan)
app.include_router(library_router)


def tailnet_user(request: Request) -> str | None:
    # `tailscale serve` adds identity headers for tailnet users; absent for tagged devices and local calls.
    return request.headers.get("Tailscale-User-Login")


# --- health -----------------------------------------------------------------------------------------------


@app.get("/api/health")
def health():
    out = {"status": "ok", "version": VERSION, "db": "ok", "redis": "ok"}
    try:
        with get_engine().connect() as c:
            c.execute(text("select 1"))
    except Exception as e:
        out["db"], out["status"] = f"error: {type(e).__name__}", "degraded"
    try:
        bus.get_redis().ping()
    except redis.RedisError as e:
        out["redis"], out["status"] = f"error: {type(e).__name__}", "degraded"
    return out


# --- jobs -------------------------------------------------------------------------------------------------


class DummyJobIn(BaseModel):
    stage_seconds: float = Field(0.25, ge=0, le=60)
    ticks: int = Field(4, ge=1, le=100)
    fail_at: str | None = None


@app.post("/api/jobs/dummy", status_code=201)
def create_dummy_job(body: DummyJobIn, request: Request):
    """Phase 1: a job that runs timed placeholder stages (no audio)."""
    r = bus.get_redis()
    with session_scope() as s:
        sample, preset = J.get_or_create_dummy_inputs(s)
        job = J.create_job(s, sample.id, preset, {"dummy": body.model_dump()}, created_by=tailnet_user(request))
        job_id = job.id
    with session_scope() as s:  # enqueue only after the job row is committed
        J.enqueue(s, r, job_id)
    return {"id": str(job_id), "short": J.short(job_id)}


def _job_or_404(s, job_id: str) -> Job:
    try:
        job = s.get(Job, uuid.UUID(job_id))
    except ValueError:
        job = None
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@app.get("/api/jobs")
def list_jobs(limit: int = 30):
    with session_scope() as s:
        return J.snapshot(s, bus.get_redis(), limit=limit, log_limit=0)["jobs"]


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    r = bus.get_redis()
    with session_scope() as s:
        job = _job_or_404(s, job_id)
        if job.state == "queued":
            J.finish(s, r, job, "cancelled")
            msg = job.stream_msg_id
        elif job.state == "running":
            r.set(bus.cancel_key(job.id), "1", ex=3600)  # the worker stops at the next stage boundary
            J.log(s, r, "WARN", "api", f"{J.short(job.id)} cancel requested", job.id)
            return {"id": job_id, "state": "cancelling"}
        else:
            raise HTTPException(409, f"job is {job.state}")
    J.ack(r, msg)
    with session_scope() as s:
        J.announce_finish(r, s.get(Job, uuid.UUID(job_id)))
    return {"id": job_id, "state": "cancelled"}


@app.post("/api/jobs/{job_id}/retry", status_code=201)
def retry_job(job_id: str, request: Request):
    """Run the same sample, preset and overrides again as a new job (the failed one stays as history)."""
    r = bus.get_redis()
    with session_scope() as s:
        old = _job_or_404(s, job_id)
        if old.state not in ("failed", "cancelled"):
            raise HTTPException(409, f"job is {old.state}")
        preset = s.get(Preset, old.preset_id)
        job = J.create_job(s, old.sample_id, preset, dict(old.overrides), created_by=tailnet_user(request))
        J.log(s, None, "INFO", "api", f"{J.short(job.id)} retries {J.short(old.id)}", job.id)
        new_id = job.id
    with session_scope() as s:
        J.enqueue(s, r, new_id)
    return {"id": str(new_id), "short": J.short(new_id)}


@app.get("/api/workers")
def list_workers():
    with session_scope() as s:
        return J.snapshot(s, None, limit=0, log_limit=0)["workers"]


# --- live progress (SSE) ----------------------------------------------------------------------------------


def _snapshot() -> dict:
    try:
        r = bus.get_redis()
        r.ping()
    except redis.RedisError:
        r = None  # Postgres alone is enough to rebuild the picture
    with session_scope() as s:
        snap = J.snapshot(s, r)
    snap["redis"] = r is not None
    return snap


def _sse(event: str, data) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@app.get("/api/events")
async def events(request: Request):
    """On connect: a full snapshot from Postgres (+ live Redis progress). Then: pub/sub deltas.

    If Redis is unavailable the stream degrades to a fresh snapshot every 2 s. If Redis drops mid-stream the
    response ends and EventSource reconnects, which yields a new snapshot — no client-side state is trusted.
    """

    async def gen():
        yield "retry: 2000\n\n"
        ar = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        pubsub = ar.pubsub()
        try:
            try:
                await pubsub.subscribe(bus.events_channel())  # subscribe first: no gap before the snapshot
                live = True
            except (redis.RedisError, OSError):
                live = False
            yield _sse("snapshot", await run_in_threadpool(_snapshot))
            last = time.monotonic()
            while not await request.is_disconnected():
                if live:
                    try:
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    except (redis.RedisError, OSError):
                        break
                    if msg:
                        yield _sse("update", msg["data"])
                        last = time.monotonic()
                    elif time.monotonic() - last > 15:
                        yield ": keepalive\n\n"
                        last = time.monotonic()
                else:
                    await asyncio.sleep(2)
                    yield _sse("snapshot", await run_in_threadpool(_snapshot))
        finally:
            try:
                await pubsub.aclose()
                await ar.aclose()
            except Exception:
                pass

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.get("/api/snapshot")
async def snapshot():
    return await run_in_threadpool(_snapshot)


# --- pages ------------------------------------------------------------------------------------------------


@app.get("/smoke", response_class=HTMLResponse, include_in_schema=False)
def smoke():
    """Phase 1 diagnostic page (health, workers, queue, stage progress, log)."""
    return SMOKE_HTML


if (WEB_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """The built UI (web/dist) on the same origin as the API; client-side routes fall back to index.html."""
    if full_path.startswith("api/"):
        raise HTTPException(404, "not found")
    index = WEB_DIST / "index.html"
    if not index.exists():
        return RedirectResponse("/smoke")
    candidate = (WEB_DIST / full_path).resolve()
    if full_path and candidate.is_file() and WEB_DIST in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})

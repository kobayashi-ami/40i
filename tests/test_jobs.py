import json
import signal
import threading

import httpx
from sqlalchemy import select

from core import bus
from core.db import session_scope
from core.models import Job, JobEvent, JobStage
from tests.conftest import wait_for


def job(url, jid):
    return next(j for j in httpx.get(url + "/api/snapshot").json()["jobs"] if j["id"] == jid)


def create(url, **body):
    r = httpx.post(url + "/api/jobs/dummy", json=body, headers={"Tailscale-User-Login": "owner@example.com"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_health(procs):
    url = procs.api()
    assert httpx.get(url + "/api/health").json() == {"status": "ok", "version": "0.1.0", "db": "ok", "redis": "ok"}


def test_job_runs_all_stages_and_persists(procs):
    url = procs.api()
    procs.worker()
    jid = create(url, stage_seconds=0.05)
    wait_for(lambda: job(url, jid)["state"] == "succeeded", 20, "job succeeded")
    with session_scope() as s:
        j = s.get(Job, jid)
        stages = s.scalars(select(JobStage).where(JobStage.job_id == j.id).order_by(JobStage.ordinal)).all()
        assert [st.state for st in stages] == ["succeeded"] * 10
        assert all(st.duration_s and st.duration_s > 0 for st in stages)
        assert j.attempts == 1 and j.result_sha256 and j.created_by == "owner@example.com"
        msgs = s.scalars(select(JobEvent.message).where(JobEvent.job_id == j.id)).all()
        assert "stage 10 output done" in " ".join(msgs)


def test_same_params_same_hash(procs):
    url = procs.api()
    procs.worker()
    a, b = create(url, stage_seconds=0.01), create(url, stage_seconds=0.01)
    wait_for(lambda: job(url, a)["state"] == job(url, b)["state"] == "succeeded", 20, "both succeeded")
    with session_scope() as s:
        assert s.get(Job, a).result_sha256 == s.get(Job, b).result_sha256


def test_failure_records_traceback_and_failed_stage(procs):
    url = procs.api()
    procs.worker()
    jid = create(url, stage_seconds=0.05, fail_at="adc")
    wait_for(lambda: job(url, jid)["state"] == "failed", 20, "job failed")
    j = job(url, jid)
    states = [s["state"] for s in j["stages"]]
    assert states[:4] == ["succeeded"] * 4 and states[4] == "failed" and set(states[5:]) == {"pending"}
    assert "Traceback" in j["error"] and "dummy failure injected at stage adc" in j["error"]
    # retry makes a new job; the failed one stays as history
    new = httpx.post(f"{url}/api/jobs/{jid}/retry").json()["id"]
    assert new != jid and job(url, jid)["state"] == "failed"


def test_sse_snapshot_then_progress(procs):
    url = procs.api()
    procs.worker()
    events: list[tuple[str, dict]] = []
    done = threading.Event()

    def listen():
        with httpx.stream("GET", url + "/api/events", timeout=20) as resp:
            name = None
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    events.append((name, json.loads(line[6:])))
                    if (
                        name == "update"
                        and events[-1][1].get("type") == "job"
                        and events[-1][1].get("state") == "succeeded"
                    ):
                        done.set()
                        return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    wait_for(lambda: events and events[0][0] == "snapshot", 10, "snapshot first")
    create(url, stage_seconds=0.05)
    assert done.wait(20), "no succeeded event over SSE"
    kinds = {e[1].get("type") for e in events[1:]}
    assert {"progress", "job", "log"} <= kinds
    progress = [e[1] for e in events if e[1].get("type") == "progress" and "stage_progress" in e[1]]
    assert any(float(p["stage_progress"]) == 1.0 for p in progress)


def test_kill_9_requeues_then_another_worker_finishes(procs):
    url = procs.api()
    w1 = procs.worker()
    jid = create(url, stage_seconds=0.6, ticks=3)
    wait_for(lambda: job(url, jid)["state"] == "running", 10, "running")
    wait_for(lambda: any(s["state"] == "succeeded" for s in job(url, jid)["stages"]), 10, "one stage done")
    w1.send_signal(signal.SIGKILL)
    w1.wait(5)
    # reaper (in the API) notices the stale heartbeat and puts the job back — never left hanging in "running"
    wait_for(lambda: job(url, jid)["state"] == "queued", 15, "re-queued after kill -9")
    j = job(url, jid)
    assert j["attempts"] == 1 and "lost" in j["error"] and all(s["state"] == "pending" for s in j["stages"])
    snap = httpx.get(url + "/api/snapshot").json()
    assert any(w["state"] == "lost" for w in snap["workers"])
    procs.worker()
    wait_for(lambda: job(url, jid)["state"] == "succeeded", 30, "finished by second worker")
    assert job(url, jid)["attempts"] == 2


def test_gives_up_after_max_attempts(procs):
    url = procs.api(env_extra={"MAX_ATTEMPTS": "1"})
    w = procs.worker()
    jid = create(url, stage_seconds=1.0, ticks=2)
    wait_for(lambda: job(url, jid)["state"] == "running", 10, "running")
    w.send_signal(signal.SIGKILL)
    w.wait(5)
    wait_for(lambda: job(url, jid)["state"] == "failed", 15, "failed after max attempts")


def test_sigterm_hands_job_back_without_spending_an_attempt(procs):
    url = procs.api()
    w = procs.worker()
    jid = create(url, stage_seconds=0.5, ticks=2)
    wait_for(lambda: job(url, jid)["state"] == "running", 10, "running")
    w.send_signal(signal.SIGTERM)
    w.wait(10)
    j = job(url, jid)
    assert j["state"] == "queued" and j["attempts"] == 0
    procs.worker()
    wait_for(lambda: job(url, jid)["state"] == "succeeded", 30, "finished after restart")


def test_redis_wipe_is_recovered_from_postgres(procs):
    url = procs.api()
    jid = create(url, stage_seconds=0.02)  # no worker yet: stays queued
    r = bus.get_redis()
    r.delete(bus.stream_key())  # Redis lost the queue (e.g. restarted without persistence)
    assert r.xlen(bus.stream_key()) == 0
    # the UI picture comes from Postgres regardless
    assert job(url, jid)["state"] == "queued"
    # reconcile (API maintenance loop) puts it back on the stream, and a worker finishes it
    wait_for(lambda: r.xlen(bus.stream_key()) == 1, 10, "re-enqueued from Postgres")
    procs.worker()
    wait_for(lambda: job(url, jid)["state"] == "succeeded", 20, "succeeded after Redis wipe")


def test_snapshot_without_redis_progress_hashes(procs):
    url = procs.api()
    procs.worker()
    jid = create(url, stage_seconds=0.02)
    wait_for(lambda: job(url, jid)["state"] == "succeeded", 20, "succeeded")
    r = bus.get_redis()
    r.delete(*r.scan_iter(f"{bus._p()}:job:*"))
    j = job(url, jid)
    assert j["state"] == "succeeded" and [s["state"] for s in j["stages"]] == ["succeeded"] * 10


def test_cancel_running_and_queued(procs):
    url = procs.api()
    queued = create(url)
    assert httpx.post(f"{url}/api/jobs/{queued}/cancel").json()["state"] == "cancelled"
    procs.worker()
    running = create(url, stage_seconds=0.5, ticks=2)
    wait_for(lambda: job(url, running)["state"] == "running", 10, "running")
    assert httpx.post(f"{url}/api/jobs/{running}/cancel").json()["state"] == "cancelling"
    wait_for(lambda: job(url, running)["state"] == "cancelled", 15, "cancelled at stage boundary")
    assert job(url, queued)["state"] == "cancelled"

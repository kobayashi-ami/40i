"""Job lifecycle shared by the API, the workers and the reaper.

Ordering rule: every state change is committed to Postgres first, then mirrored to Redis and announced on
pub/sub. A crash between the two leaves Postgres right and Redis stale, which `reconcile` repairs.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import redis
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from core import bus
from core.models import Job, JobEvent, JobStage, Preset, Sample, Worker
from core.settings import get_settings

# Stage lists per path. Phase 1 runs them as timed dummies; Phase 2 binds them to engine stage functions.
STAGES = {
    "sp": ["role", "pre_eq", "drive", "capture", "adc", "tune", "vol_env", "dac", "analog", "output"],
    "mpc": ["input", "resample", "nl12_codec", "tune", "deemph_dac"],
}


def now() -> datetime:
    return datetime.now(UTC)


def short(job_id) -> str:
    return str(job_id).replace("-", "")[:4]


# --- events -----------------------------------------------------------------------------------------------


def log(session: Session, r: redis.Redis | None, level: str, source: str, message: str, job_id=None) -> None:
    """Persist a log line, then announce it. Caller commits."""
    session.add(JobEvent(job_id=job_id, level=level, source=source, message=message))
    if r is not None:
        bus.publish(r, {"type": "log", "level": level, "source": source, "message": message, "job_id": job_id})


# --- creation and queueing --------------------------------------------------------------------------------


def get_or_create_dummy_inputs(session: Session) -> tuple[Sample, Preset]:
    """Phase 1 only: a placeholder sample and preset so dummy jobs satisfy the schema."""
    sha = hashlib.sha256(b"1260-dummy-sample").hexdigest()
    sample = session.scalar(select(Sample).where(Sample.sha256 == sha))
    if sample is None:
        sample = Sample(original_name="dummy.wav", sha256=sha, length_s=0.412, sample_rate=44100, role="snare")
        session.add(sample)
    preset = session.scalar(select(Preset).where(Preset.name == "dummy_sp", Preset.version == 1))
    if preset is None:
        preset = Preset(name="dummy_sp", path="sp", params={"tune": -2}, version=1)
        session.add(preset)
    session.flush()
    return sample, preset


def create_job(session: Session, sample_id, preset: Preset, overrides: dict | None = None, created_by=None) -> Job:
    job = Job(sample_id=sample_id, preset_id=preset.id, overrides=overrides or {}, created_by=created_by)
    session.add(job)
    session.flush()
    for i, name in enumerate(STAGES[preset.path]):
        session.add(JobStage(job_id=job.id, ordinal=i, name=name))
    log(session, None, "INFO", "api", f"job {short(job.id)} created ({preset.name})", job.id)
    return job


def enqueue(session: Session, r: redis.Redis, job_id) -> str | None:
    """Put a queued job on the stream and remember the entry id. Returns None if Redis is unreachable."""
    try:
        bus.ensure_group(r)
        msg_id = r.xadd(bus.stream_key(), {"job_id": str(job_id)})
    except redis.RedisError:
        return None
    session.execute(update(Job).where(Job.id == job_id).values(stream_msg_id=msg_id, enqueued_at=now()))
    bus.publish(r, {"type": "job", "job_id": str(job_id), "state": "queued"})
    return msg_id


# --- worker side ------------------------------------------------------------------------------------------


def claim(session: Session, job_id, worker_id: str) -> Job | None:
    """Atomically move a queued job to running. None if it was cancelled or taken meanwhile."""
    row = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.state == "queued")
        .values(state="running", worker_id=worker_id, started_at=now(), attempts=Job.attempts + 1, error=None)
        .returning(Job.id)
    ).first()
    if row is None:
        return None
    return session.get(Job, job_id)


def set_stage(session: Session, job_id, ordinal: int, **values) -> None:
    session.execute(update(JobStage).where(JobStage.job_id == job_id, JobStage.ordinal == ordinal).values(**values))


def mirror_progress(r: redis.Redis, job_id, **fields) -> None:
    try:
        key = bus.progress_key(job_id)
        r.hset(key, mapping={k: str(v) for k, v in fields.items()})
        r.expire(key, 86400)
    except redis.RedisError:
        pass
    bus.publish(r, {"type": "progress", "job_id": str(job_id), **fields})


def finish(session: Session, r: redis.Redis, job: Job, state: str, error: str | None = None, result=None) -> None:
    job.state = state
    job.finished_at = now()
    job.error = error
    if result is not None:
        job.output_path, job.result_sha256 = result
    level = {"succeeded": "INFO", "cancelled": "WARN"}.get(state, "ERR")
    log(session, r, level, short(job.id), f"job {state}" + (f": {error.splitlines()[-1]}" if error else ""), job.id)


def announce_finish(r: redis.Redis, job: Job) -> None:
    mirror_progress(r, job.id, state=job.state)
    bus.publish(r, {"type": "job", "job_id": str(job.id), "state": job.state, "error": job.error})


def ack(r: redis.Redis, msg_id: str | None) -> None:
    if not msg_id:
        return
    try:
        r.xack(bus.stream_key(), bus.GROUP, msg_id)
        r.xdel(bus.stream_key(), msg_id)
    except redis.RedisError:
        pass


def params_hash(preset: Preset, overrides: dict) -> str:
    blob = json.dumps({"preset": preset.params, "path": preset.path, "overrides": overrides}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


# --- heartbeats, reaper, reconcile ------------------------------------------------------------------------


def heartbeat(session: Session, r: redis.Redis, worker_id: str, hostname: str, state: str, version: str) -> None:
    s = get_settings()
    w = session.get(Worker, worker_id)
    if w is None:
        session.add(Worker(id=worker_id, hostname=hostname, last_heartbeat=now(), state=state, version=version))
    else:
        w.last_heartbeat, w.state, w.version = now(), state, version
    try:
        r.set(bus.heartbeat_key(worker_id), state, ex=max(1, int(round(s.heartbeat_ttl_s))))
    except redis.RedisError:
        pass


def requeue_or_fail(session: Session, r: redis.Redis, job: Job, reason: str, source: str) -> None:
    """A running job lost its worker: try again, or give up after MAX_ATTEMPTS."""
    s = get_settings()
    old_msg = job.stream_msg_id
    if job.attempts < s.max_attempts:
        job.state, job.worker_id, job.started_at, job.error = "queued", None, None, reason
        for st in job.stages:
            st.state, st.progress, st.duration_s = "pending", 0.0, None
        log(
            session,
            r,
            "WARN",
            source,
            f"{short(job.id)} → re-queued ({reason}, attempt {job.attempts}/{s.max_attempts})",
            job.id,
        )
        session.flush()
        ack(r, old_msg)
        enqueue(session, r, job.id)
    else:
        job.state, job.finished_at, job.error = "failed", now(), reason
        for st in job.stages:
            if st.state == "running":
                st.state = "failed"
        log(
            session,
            r,
            "ERR",
            source,
            f"{short(job.id)} → FAILED ({reason}, attempt {job.attempts}/{s.max_attempts})",
            job.id,
        )
        ack(r, old_msg)
    bus.publish(r, {"type": "job", "job_id": str(job.id), "state": job.state, "error": job.error})


def reap(session: Session, r: redis.Redis) -> int:
    """Find workers whose Postgres heartbeat is older than the TTL; rescue their running jobs."""
    s = get_settings()
    cutoff = now() - timedelta(seconds=s.heartbeat_ttl_s)
    dead = session.scalars(
        select(Worker)
        .where(Worker.last_heartbeat < cutoff, Worker.state.in_(("idle", "busy")))
        .with_for_update(skip_locked=True)
    ).all()
    rescued = 0
    for w in dead:
        w.state = "lost"
        age = (now() - w.last_heartbeat).total_seconds()
        log(session, r, "WARN", "reaper", f"worker {w.id} heartbeat stale {age:.1f}s")
        jobs = session.scalars(
            select(Job).where(Job.worker_id == w.id, Job.state == "running").with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            requeue_or_fail(session, r, job, f"worker {w.id} lost", "reaper")
            rescued += 1
        bus.publish(r, {"type": "worker", "worker_id": w.id, "state": "lost"})
    return rescued


def reconcile(session: Session, r: redis.Redis) -> int:
    """Make sure every queued job in Postgres has a live stream entry (e.g. after Redis lost its data)."""
    queued = session.scalars(select(Job).where(Job.state == "queued").with_for_update(skip_locked=True)).all()
    fixed = 0
    for job in queued:
        present = False
        if job.stream_msg_id:
            try:
                present = bool(r.xrange(bus.stream_key(), job.stream_msg_id, job.stream_msg_id))
            except redis.RedisError:
                return fixed
        if not present:
            if enqueue(session, r, job.id):
                log(session, r, "INFO", "reconcile", f"{short(job.id)} re-enqueued from Postgres", job.id)
                fixed += 1
    return fixed


# --- snapshot for the UI ----------------------------------------------------------------------------------


def snapshot(session: Session, r: redis.Redis | None, limit: int = 30, log_limit: int = 50) -> dict:
    s = get_settings()
    fresh = now() - timedelta(seconds=s.heartbeat_ttl_s)
    workers = session.scalars(select(Worker).order_by(Worker.id)).all()
    jobs = session.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit)).all()
    events = session.scalars(select(JobEvent).order_by(JobEvent.id.desc()).limit(log_limit)).all()
    counts = dict(session.execute(select(Job.state, func.count()).group_by(Job.state)).all())

    live: dict[str, dict] = {}
    if r is not None:
        try:
            pipe = r.pipeline()
            for j in jobs:
                pipe.hgetall(bus.progress_key(j.id))
            for j, h in zip(jobs, pipe.execute(), strict=True):
                live[str(j.id)] = h
        except redis.RedisError:
            live = {}

    def job_view(j: Job) -> dict:
        lv = live.get(str(j.id), {})
        stages = []
        for st in j.stages:
            prog = st.progress
            if st.state == "running" and lv.get("stage_index") == str(st.ordinal) and "stage_progress" in lv:
                prog = float(lv["stage_progress"])
            stages.append(
                {
                    "ordinal": st.ordinal,
                    "name": st.name,
                    "state": st.state,
                    "progress": prog,
                    "duration_s": st.duration_s,
                }
            )
        return {
            "id": str(j.id),
            "short": short(j.id),
            "state": j.state,
            "worker_id": j.worker_id,
            "attempts": j.attempts,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "finished_at": j.finished_at,
            "error": j.error,
            "created_by": j.created_by,
            "stages": stages,
        }

    return {
        "queue": counts.get("queued", 0),
        "counts": counts,
        "workers": [
            {
                "id": w.id,
                "hostname": w.hostname,
                "state": w.state if w.last_heartbeat >= fresh or w.state == "stopped" else "lost",
                "last_heartbeat": w.last_heartbeat,
                "heartbeat_age_s": (now() - w.last_heartbeat).total_seconds(),
                "version": w.version,
            }
            for w in workers
        ],
        "jobs": [job_view(j) for j in jobs],
        "log": [
            {
                "id": e.id,
                "ts": e.ts,
                "level": e.level,
                "source": e.source,
                "message": e.message,
                "job_id": str(e.job_id) if e.job_id else None,
            }
            for e in reversed(events)
        ],
    }


def still_owner(session: Session, job_id, worker_id: str) -> bool:
    """False once the reaper has handed the job to someone else (e.g. after a long stall)."""
    j = session.get(Job, job_id, populate_existing=True)
    return j is not None and j.state == "running" and j.worker_id == worker_id

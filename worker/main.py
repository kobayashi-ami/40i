"""Worker process: takes jobs from the Redis Stream, runs their stages, records everything in Postgres.

    python -m worker            # one worker; start more processes (or machines) for more throughput

Phase 1 runs timed dummy stages. Phase 2 swaps `run_stage` for the engine's stage functions.
"""

import logging
import os
import signal
import socket
import threading
import time
import traceback

import redis

from core import VERSION, bus
from core import jobs as J
from core.db import session_scope
from core.models import Job, Preset
from core.settings import get_settings

log = logging.getLogger("worker")


class Cancelled(Exception):
    pass


class LostOwnership(Exception):
    pass


class Interrupted(Exception):
    pass


class Worker:
    def __init__(self, worker_id: str | None = None):
        self.hostname = socket.gethostname()
        self.id = worker_id or f"{self.hostname}:{os.getpid()}"
        self.r = bus.get_redis()
        self.state = "idle"
        self.stop = threading.Event()
        self.current: tuple[str, str | None] | None = None  # (job_id, stream msg id)

    # -- liveness ----------------------------------------------------------------------------------------

    def beat(self) -> None:
        with session_scope() as s:
            J.heartbeat(s, self.r, self.id, self.hostname, self.state, VERSION)

    def heartbeat_loop(self) -> None:
        period = get_settings().heartbeat_s
        while not self.stop.wait(period):
            try:
                self.beat()
                with session_scope() as s:
                    J.reap(s, self.r)
                with session_scope() as s:
                    J.reconcile(s, self.r)
            except Exception:  # keep beating through transient DB/Redis errors
                log.exception("heartbeat/reaper pass failed")

    # -- main loop ---------------------------------------------------------------------------------------

    def run(self) -> None:
        bus.ensure_group(self.r)
        self.beat()
        with session_scope() as s:
            J.log(s, self.r, "INFO", self.id, f"worker up (v{VERSION})")
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        while not self.stop.is_set():
            try:
                got = self.r.xreadgroup(bus.GROUP, self.id, {bus.stream_key(): ">"}, count=1, block=1000)
            except redis.ResponseError as e:  # stream/group vanished (Redis wiped): recreate and carry on
                if "NOGROUP" in str(e):
                    bus.ensure_group(self.r)
                    continue
                raise
            except redis.ConnectionError:
                time.sleep(1)
                continue
            for _stream, entries in got or []:
                for msg_id, fields in entries:
                    self.handle(fields["job_id"], msg_id)
        self.shutdown()

    def handle(self, job_id: str, msg_id: str) -> None:
        with session_scope() as s:
            job = J.claim(s, job_id, self.id)
            if job is None:
                J.ack(self.r, msg_id)
                return
            preset = s.get(Preset, job.preset_id)
            path, overrides, n_stages = preset.path, dict(job.overrides), len(job.stages)
            J.log(s, self.r, "INFO", J.short(job_id), f"claimed by {self.id} (attempt {job.attempts})", job.id)
        self.current, self.state = (job_id, msg_id), "busy"
        self.beat()
        J.mirror_progress(self.r, job_id, state="running", worker_id=self.id, stage_index=0, stage_progress=0)
        try:
            for i, name in enumerate(J.STAGES[path][:n_stages]):
                self.run_stage(job_id, i, name, overrides)
            with session_scope() as s:
                job = s.get(Job, job_id)
                preset = s.get(Preset, job.preset_id)
                J.finish(s, self.r, job, "succeeded", result=(None, J.params_hash(preset, overrides)))
        except Cancelled:
            with session_scope() as s:
                J.finish(s, self.r, s.get(Job, job_id), "cancelled")
        except Interrupted:
            with session_scope() as s:
                job = s.get(Job, job_id)
                job.attempts -= 1  # a clean stop is not a failed attempt
                J.requeue_or_fail(s, self.r, job, f"worker {self.id} stopped", self.id)
            self.current, self.state = None, "idle"
            return
        except LostOwnership:
            log.warning("job %s was reassigned while running; dropping it", job_id)
            self.current, self.state = None, "idle"
            return  # the reaper already re-queued and acked
        except Exception:
            tb = traceback.format_exc()
            with session_scope() as s:
                job = s.get(Job, job_id)
                for st in job.stages:
                    if st.state == "running":
                        st.state = "failed"
                J.finish(s, self.r, job, "failed", error=tb)
        with session_scope() as s:
            J.announce_finish(self.r, s.get(Job, job_id))
        J.ack(self.r, msg_id)
        self.current, self.state = None, "idle"
        self.beat()

    def run_stage(self, job_id: str, i: int, name: str, overrides: dict) -> None:
        dummy = overrides.get("dummy", {})
        seconds = float(dummy.get("stage_seconds", 0.25))
        ticks = int(dummy.get("ticks", 4))
        if self.stop.is_set():
            raise Interrupted
        with session_scope() as s:
            if not J.still_owner(s, job_id, self.id):
                raise LostOwnership
            if self.r.exists(bus.cancel_key(job_id)):
                J.set_stage(s, job_id, i, state="cancelled")
                raise Cancelled
            J.set_stage(s, job_id, i, state="running", progress=0.0)
            J.log(s, self.r, "INFO", J.short(job_id), f"stage {i + 1:02d} {name} start", job_id)
        J.mirror_progress(self.r, job_id, state="running", stage=name, stage_index=i, stage_progress=0)
        t0 = time.monotonic()
        for k in range(1, ticks + 1):
            time.sleep(seconds / ticks)
            if dummy.get("fail_at") == name and k == ticks // 2 + 1:
                raise RuntimeError(f"dummy failure injected at stage {name}")
            J.mirror_progress(self.r, job_id, state="running", stage=name, stage_index=i, stage_progress=k / ticks)
        took = time.monotonic() - t0
        with session_scope() as s:
            J.set_stage(s, job_id, i, state="succeeded", progress=1.0, duration_s=took)
            J.log(s, self.r, "INFO", J.short(job_id), f"stage {i + 1:02d} {name} done {took:.3f}s", job_id)

    def shutdown(self) -> None:
        """Graceful stop. A job in flight was already handed back at the next stage boundary (Interrupted)."""
        self.state = "stopped"
        with session_scope() as s:
            J.heartbeat(s, self.r, self.id, self.hostname, "stopped", VERSION)
            J.log(s, self.r, "INFO", self.id, "worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    w = Worker()

    def on_signal(signum, _frame):
        log.info("signal %s: stopping at the next stage boundary", signum)
        w.stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log.info("worker %s starting", w.id)
    w.run()

"""Worker process: takes jobs from the Redis Stream, runs their stages, records everything in Postgres.

    python -m worker            # one worker; start more processes (or machines) for more throughput

Jobs whose overrides contain "dummy" run timed placeholder stages (Phase 1 tests); every other job renders the
stored sample through the engine, one named stage at a time, and writes WAV + spectrogram + params JSON under
DATA_DIR/renders/<job id>/.
"""

import logging
import os
import signal
import socket
import threading
import time
import traceback
from pathlib import Path

import redis
import soundfile as sf

from core import VERSION, bus
from core import jobs as J
from core import library as L
from core.db import session_scope
from core.models import Job, Preset, Sample
from core.settings import get_settings
from engine import pipeline
from engine.render import write_outputs

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
            if "dummy" in overrides:
                for i, name in enumerate(J.STAGES[path][:n_stages]):
                    self.run_stage(job_id, i, name, self.dummy_body(name, overrides["dummy"]))
                result = (None, None)
            else:
                result = self.render(job_id)
            with session_scope() as s:
                job = s.get(Job, job_id)
                preset = s.get(Preset, job.preset_id)
                out_path, digest = result
                J.finish(s, self.r, job, "succeeded", result=(out_path, digest or J.params_hash(preset, overrides)))
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

    def run_stage(self, job_id: str, i: int, name: str, body) -> None:
        """Bookkeeping around one stage: stop/ownership/cancel checks, then Postgres first, then Redis."""
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
        body(
            lambda frac: J.mirror_progress(
                self.r, job_id, state="running", stage=name, stage_index=i, stage_progress=frac
            )
        )
        took = time.monotonic() - t0
        with session_scope() as s:
            J.set_stage(s, job_id, i, state="succeeded", progress=1.0, duration_s=took)
            J.log(s, self.r, "INFO", J.short(job_id), f"stage {i + 1:02d} {name} done {took:.3f}s", job_id)
        J.mirror_progress(self.r, job_id, state="running", stage=name, stage_index=i, stage_progress=1)

    @staticmethod
    def dummy_body(name: str, dummy: dict):
        seconds = float(dummy.get("stage_seconds", 0.25))
        ticks = int(dummy.get("ticks", 4))

        def body(progress):
            for k in range(1, ticks + 1):
                time.sleep(seconds / ticks)
                if dummy.get("fail_at") == name and k == ticks // 2 + 1:
                    raise RuntimeError(f"dummy failure injected at stage {name}")
                progress(k / ticks)

        return body

    def render(self, job_id: str) -> tuple[str, str]:
        """Engine path: read the sample, run each pipeline step as a job stage, write the outputs."""
        with session_scope() as s:
            job = s.get(Job, job_id)
            sample = s.get(Sample, job.sample_id)
            preset = s.get(Preset, job.preset_id)
            path, preset_name = preset.path, preset.name
            params = pipeline.full_params(path, preset.params, job.overrides)
            src = L.sample_path(sample)
            src_name, src_sha = sample.original_name, sample.sha256
        x, sr = sf.read(str(src), dtype="float64", always_2d=False)
        state = {"x": x, "sr": sr, "info": {}}
        for i, (name, fn) in enumerate(pipeline.steps(path, params)):
            self.run_stage(job_id, i, name, lambda _progress, fn=fn: fn(state))
        out_dir = L.renders_dir() / str(job_id)
        meta = write_outputs(
            state["out"], state["rate"], state["info"], path, params, preset_name, src_name, sr, src_sha, out_dir
        )
        rel = str(Path(meta["files"]["wav"]).relative_to(L.data_dir()))
        with session_scope() as s:
            J.log(
                s,
                self.r,
                "INFO",
                J.short(job_id),
                f"wrote {Path(rel).name} · levels {state['info'].get('adc_levels_used', '-')}",
                job_id,
            )
        return rel, meta["output"]["sha256"]

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

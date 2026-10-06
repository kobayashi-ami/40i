"""Integration fixtures: a throwaway Postgres database, an isolated Redis key prefix, and real subprocesses
for the API (uvicorn) and the workers, so kill -9 and restarts are tested for real.

Needs Postgres and Redis reachable at TEST_DATABASE_ADMIN_URL / TEST_REDIS_URL (defaults match compose.yaml).
"""

import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://1260:1260@127.0.0.1:55432/1260")
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
DB_NAME = f"t1260_{uuid.uuid4().hex[:8]}"
TEST_DB_URL = ADMIN_URL.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://") + f"/{DB_NAME}"

BASE_ENV = {
    "DATABASE_URL": TEST_DB_URL,
    "REDIS_URL": REDIS_URL,
    "REDIS_PREFIX": f"t1260-{uuid.uuid4().hex[:8]}",
    "HEARTBEAT_S": "0.5",
    "HEARTBEAT_TTL_S": "2",
    "MAX_ATTEMPTS": "3",
}
os.environ.update(BASE_ENV)


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{DB_NAME}"')
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ},
        check=True,
        capture_output=True,
    )
    yield
    from core.db import get_engine

    get_engine().dispose()
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


@pytest.fixture(autouse=True)
def clean(database):
    from core import bus
    from core.db import get_engine

    with get_engine().begin() as c:
        c.exec_driver_sql("TRUNCATE job_events, job_stages, jobs, workers, presets, samples CASCADE")
    r = bus.get_redis()
    keys = list(r.scan_iter(f"{BASE_ENV['REDIS_PREFIX']}:*"))
    if keys:
        r.delete(*keys)
    yield


class Procs:
    """Starts API and worker subprocesses; kills whatever is left at teardown."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.procs: list[subprocess.Popen] = []
        self.port: int | None = None

    def _spawn(self, args, name, env_extra=None):
        log = open(self.tmp / f"{name}-{len(self.procs)}.log", "w")
        p = subprocess.Popen(
            args, cwd=ROOT, env={**os.environ, **(env_extra or {})}, stdout=log, stderr=subprocess.STDOUT
        )
        self.procs.append(p)
        return p

    def api(self, env_extra=None) -> str:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self._spawn(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            "api",
            env_extra,
        )
        url = f"http://127.0.0.1:{self.port}"
        wait_for(lambda: httpx.get(url + "/api/health", timeout=1).status_code == 200, 15, "api up")
        return url

    def worker(self, env_extra=None) -> subprocess.Popen:
        return self._spawn([sys.executable, "-m", "worker"], "worker", env_extra)

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None:
                p.send_signal(signal.SIGKILL)
                p.wait(5)


@pytest.fixture
def procs(tmp_path):
    ps = Procs(tmp_path)
    yield ps
    ps.stop_all()


def wait_for(pred, timeout: float, what: str, interval: float = 0.1):
    end = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < end:
        try:
            if pred():
                return
        except Exception as e:  # server still starting, etc.
            last_exc = e
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for: {what} (last error: {last_exc!r})")

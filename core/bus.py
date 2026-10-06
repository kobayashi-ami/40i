"""Redis: the job queue (a Stream with one consumer group), live progress hashes, pub/sub, heartbeats.

Nothing here is authoritative. If Redis is wiped, `core.jobs.reconcile` rebuilds the queue from Postgres and
the UI snapshot falls back to the progress stored in `job_stages`.
"""

import json
import time
from functools import cache

import redis

from core.settings import get_settings

GROUP = "workers"


def _p() -> str:
    return get_settings().redis_prefix


def stream_key() -> str:
    return f"{_p()}:jobs"


def progress_key(job_id) -> str:
    return f"{_p()}:job:{job_id}"


def cancel_key(job_id) -> str:
    return f"{_p()}:job:{job_id}:cancel"


def heartbeat_key(worker_id: str) -> str:
    return f"{_p()}:worker:{worker_id}"


def events_channel() -> str:
    return f"{_p()}:events"


@cache
def get_redis(url: str | None = None) -> redis.Redis:
    return redis.Redis.from_url(url or get_settings().redis_url, decode_responses=True)


def ensure_group(r: redis.Redis) -> None:
    try:
        r.xgroup_create(stream_key(), GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def publish(r: redis.Redis, event: dict) -> None:
    """Fire-and-forget fan-out to SSE listeners. Losing one is fine: clients resync from the snapshot."""
    event.setdefault("ts", time.time())
    try:
        r.publish(events_channel(), json.dumps(event, default=str))
    except redis.RedisError:
        pass

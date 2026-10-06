from functools import cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://1260:1260@127.0.0.1:55432/1260"
    redis_url: str = "redis://127.0.0.1:56379/0"
    data_dir: Path = Path("./data")
    api_host: str = "127.0.0.1"
    api_port: int = 8260

    heartbeat_s: float = 5.0
    heartbeat_ttl_s: float = 15.0
    max_attempts: int = 3
    # Key prefix for everything in Redis, so tests can run against a shared server.
    redis_prefix: str = "1260"


@cache
def get_settings() -> Settings:
    return Settings()

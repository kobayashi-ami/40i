"""PostgreSQL schema — the source of truth for every job, stage, event, sample, preset and worker.

Redis only mirrors live progress; anything shown in the UI must be reconstructible from these tables.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled")
STAGE_STATES = ("pending", "running", "succeeded", "failed", "skipped", "cancelled")
ROLES = ("kick", "snare", "hat", "perc", "other")
PATHS = ("sp", "mpc")


class Base(DeclarativeBase):
    pass


def _now():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    length_s: Mapped[float | None] = mapped_column(Float)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    role: Mapped[str | None] = mapped_column(String(8))
    route: Mapped[str] = mapped_column(String(4), nullable=False, default="sp", server_default="sp")  # A=sp, B=mpc
    stored_name: Mapped[str | None] = mapped_column(Text)  # file under DATA_DIR/samples/
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint(f"role IS NULL OR role IN {ROLES}", name="samples_role"),
        CheckConstraint(f"route IN {PATHS}", name="samples_route"),
    )


class Preset(Base):
    __tablename__ = "presets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(String(4), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint(f"path IN {PATHS}", name="presets_path"),
        UniqueConstraint("name", "version", name="presets_name_version"),
    )


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "<hostname>:<pid>"
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")  # idle | busy | stopped | lost
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = _now()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sample_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("samples.id"), nullable=False)
    preset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("presets.id"), nullable=False)
    overrides: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.id"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Redis Stream entry that currently carries this job (re-written on every enqueue).
    stream_msg_id: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(Text)  # Tailscale-User-Login when available
    created_at: Mapped[datetime] = _now()
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_path: Mapped[str | None] = mapped_column(Text)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)

    stages: Mapped[list["JobStage"]] = relationship(order_by="JobStage.ordinal", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(f"state IN {JOB_STATES}", name="jobs_state"),
        Index("ix_jobs_state", "state"),
        Index("ix_jobs_created_at", "created_at"),
        Index("ix_jobs_worker_id", "worker_id"),
    )


class JobStage(Base):
    __tablename__ = "job_stages"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_s: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (CheckConstraint(f"state IN {STAGE_STATES}", name="job_stages_state"),)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = _now()
    level: Mapped[str] = mapped_column(String(8), nullable=False)  # INFO | WARN | ERR
    source: Mapped[str] = mapped_column(Text, nullable=False)  # job short id, "reaper", "api", worker id
    message: Mapped[str] = mapped_column(Text, nullable=False)

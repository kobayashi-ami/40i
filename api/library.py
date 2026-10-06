"""Samples, presets, render jobs and output files."""

import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from core import bus
from core import jobs as J
from core import library as L
from core.db import session_scope
from core.models import Job, Preset, Sample
from engine.params import SCHEMA, deep_merge
from engine.pipeline import full_params
from engine.render import spectrogram_png

router = APIRouter(prefix="/api")


def _uuid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise HTTPException(404, "not found") from e


def sample_view(s: Sample, renders: int = 0) -> dict:
    return {
        "id": str(s.id),
        "name": s.original_name,
        "sha256": s.sha256,
        "length_s": s.length_s,
        "sample_rate": s.sample_rate,
        "role": s.role,
        "route": s.route,
        "created_at": s.created_at,
        "renders": renders,
    }


def preset_view(p: Preset) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "path": p.path,
        "version": p.version,
        "params": p.params,
        "created_at": p.created_at,
    }


# --- samples ----------------------------------------------------------------------------------------------


@router.post("/samples", status_code=201)
def upload_samples(files: Annotated[list[UploadFile], File()]):
    out, errors = [], []
    for f in files:
        data = f.file.read()
        try:
            with session_scope() as s:
                sample, created = L.import_sample(s, f.filename or "upload.wav", data)
                out.append({**sample_view(sample), "created": created})
        except L.NotAudio as e:
            errors.append(str(e))
    if errors and not out:
        raise HTTPException(415, "; ".join(errors))
    return {"samples": out, "errors": errors}


@router.get("/samples")
def list_samples():
    with session_scope() as s:
        counts = dict(
            s.execute(select(Job.sample_id, func.count()).where(Job.state == "succeeded").group_by(Job.sample_id)).all()
        )
        rows = s.scalars(select(Sample).where(Sample.stored_name.is_not(None)).order_by(Sample.created_at.desc()))
        return [sample_view(x, counts.get(x.id, 0)) for x in rows]


class SamplePatch(BaseModel):
    role: str | None = Field(None, pattern="^(kick|snare|hat|perc|other)$")
    route: str | None = Field(None, pattern="^(sp|mpc)$")


@router.patch("/samples/{sample_id}")
def patch_sample(sample_id: str, body: SamplePatch):
    with session_scope() as s:
        x = s.get(Sample, _uuid(sample_id))
        if x is None:
            raise HTTPException(404, "sample not found")
        if body.role is not None:
            x.role = body.role
        if body.route is not None:
            x.route = body.route
        return sample_view(x)


@router.delete("/samples/{sample_id}")
def delete_sample(sample_id: str):
    with session_scope() as s:
        x = s.get(Sample, _uuid(sample_id))
        if x is None:
            raise HTTPException(404, "sample not found")
        if s.scalar(select(func.count()).select_from(Job).where(Job.sample_id == x.id)):
            raise HTTPException(409, "sample has renders; it stays as their source")
        path = L.sample_path(x) if x.stored_name else None
        s.delete(x)
    if path and path.exists():
        path.unlink()
    return {"deleted": sample_id}


def _sample_file(sample_id: str) -> tuple[Sample, Path]:
    with session_scope() as s:
        x = s.get(Sample, _uuid(sample_id))
        if x is None or not x.stored_name:
            raise HTTPException(404, "sample not found")
        return x, L.sample_path(x)


@router.get("/samples/{sample_id}/audio")
def sample_audio(sample_id: str):
    x, p = _sample_file(sample_id)
    return FileResponse(p, media_type="audio/wav", filename=x.original_name)  # Range requests supported


@router.get("/samples/{sample_id}/peaks")
def sample_peaks(sample_id: str, n: int = 200):
    x, _ = _sample_file(sample_id)
    return L.peaks(x, n)


@router.get("/samples/{sample_id}/spectro.png")
def sample_spectro(sample_id: str):
    import soundfile as sf

    x, p = _sample_file(sample_id)
    png = p.with_name(f"{x.sha256}.spectro.png")
    if not png.exists():
        y, sr = sf.read(str(p), dtype="float64", always_2d=True)
        spectrogram_png(y.mean(axis=1), sr, png)
    return FileResponse(png, media_type="image/png")


@router.get("/samples/{sample_id}/renders")
def sample_renders(sample_id: str):
    with session_scope() as s:
        sid = _uuid(sample_id)
        jobs = s.scalars(select(Job).where(Job.sample_id == sid).order_by(Job.created_at.desc()).limit(50)).all()
        sample = s.get(Sample, sid)
        presets = {p.id: p for p in s.scalars(select(Preset).where(Preset.id.in_({j.preset_id for j in jobs})))}
        return [
            {
                "id": str(j.id),
                "short": J.short(j.id),
                "state": j.state,
                "finished_at": j.finished_at,
                **J.job_labels(j, sample, presets.get(j.preset_id)),
            }
            for j in jobs
        ]


# --- presets ----------------------------------------------------------------------------------------------


@router.get("/presets")
def list_presets():
    with session_scope() as s:
        L.sync_presets(s)
        rows = s.scalars(select(Preset).where(Preset.name != "dummy_sp").order_by(Preset.name, Preset.version))
        return [preset_view(p) for p in rows]


@router.get("/params/schema")
def params_schema():
    return {
        k: {"status": v.status, "note": v.note, "candidates": v.candidates, "lo": v.lo, "hi": v.hi}
        for k, v in SCHEMA.items()
    }


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    path: str = Field(pattern="^(sp|mpc)$")
    params: dict


@router.post("/presets", status_code=201)
def save_preset(body: PresetIn):
    with session_scope() as s:
        p = L.save_preset(s, body.name, body.path, full_params(body.path, body.params))
        return preset_view(p)


# --- render jobs ------------------------------------------------------------------------------------------


class RenderIn(BaseModel):
    sample_id: str
    preset_id: str
    overrides: dict = Field(default_factory=dict)


@router.post("/jobs", status_code=201)
def create_render(body: RenderIn, request: Request):
    r = bus.get_redis()
    with session_scope() as s:
        sample = s.get(Sample, _uuid(body.sample_id))
        preset = s.get(Preset, _uuid(body.preset_id))
        if sample is None or not sample.stored_name:
            raise HTTPException(404, "sample not found")
        if preset is None:
            raise HTTPException(404, "preset not found")
        if "dummy" in body.overrides:
            raise HTTPException(422, "use /api/jobs/dummy for dummy jobs")
        full_params(preset.path, preset.params, body.overrides)  # validates the merge shape
        job = J.create_job(s, sample.id, preset, body.overrides, created_by=request.headers.get("Tailscale-User-Login"))
        job_id = job.id
    with session_scope() as s:
        J.enqueue(s, r, job_id)
    return {"id": str(job_id), "short": J.short(job_id)}


def _job_output(job_id: str) -> tuple[Job, Path]:
    with session_scope() as s:
        j = s.get(Job, _uuid(job_id))
        if j is None or not j.output_path:
            raise HTTPException(404, "no output for this job")
        return j, L.data_dir() / j.output_path


@router.get("/jobs/{job_id}/files/{kind}")
def job_file(job_id: str, kind: str):
    """kind: wav | png | json. The WAV carries a download name for dragging into a DAW."""
    _, wav = _job_output(job_id)
    if kind == "wav":
        return FileResponse(wav, media_type="audio/wav", filename=wav.name)
    if kind == "png":
        return FileResponse(wav.with_name(wav.stem + "__spectro.png"), media_type="image/png")
    if kind == "json":
        return FileResponse(wav.with_name(wav.stem + "__params.json"), media_type="application/json")
    raise HTTPException(404, "unknown file kind")


@router.get("/jobs/{job_id}/params")
def job_params(job_id: str):
    """The effective parameters of a job (preset merged with overrides), annotated VER/HYP."""
    with session_scope() as s:
        j = s.get(Job, _uuid(job_id))
        if j is None:
            raise HTTPException(404, "job not found")
        p = s.get(Preset, j.preset_id)
        if j.output_path:
            meta = (L.data_dir() / j.output_path).with_name(Path(j.output_path).stem + "__params.json")
            if meta.exists():
                return json.loads(meta.read_text())
        return {"path": p.path, "params": deep_merge(p.params, {k: v for k, v in j.overrides.items() if k != "dummy"})}

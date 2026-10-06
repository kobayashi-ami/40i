"""Samples on disk, built-in presets in the database, and render outputs.

Audio lives under DATA_DIR (samples/<sha256>.<ext>, renders/<job id>/...); Postgres keeps the metadata and
hashes. Paths stored in the database are relative to DATA_DIR so the data directory can move.
"""

import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import Preset, Sample
from core.settings import get_settings
from engine.params import PRESETS, resolve

DRUM_ROLES = ("kick", "snare", "hat", "perc")
ROLE_WORDS = {
    "kick": ("kick", "kik", "bd", "bass drum"),
    "snare": ("snare", "snr", "sd", "rim", "clap"),
    "hat": ("hat", "hh", "hihat", "cym", "ride"),
    "perc": ("perc", "shaker", "clave", "tom", "conga", "bongo", "cowbell", "tamb"),
}


def data_dir() -> Path:
    d = Path(get_settings().data_dir).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def samples_dir() -> Path:
    d = data_dir() / "samples"
    d.mkdir(parents=True, exist_ok=True)
    return d


def renders_dir() -> Path:
    d = data_dir() / "renders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def guess_role(name: str) -> str:
    words = re.split(r"[^a-z0-9]+", name.lower())
    joined = " ".join(words)
    for role, keys in ROLE_WORDS.items():
        if any(k in words or (len(k) > 3 and k in joined) for k in keys):
            return role
    return "other"


def default_route(role: str) -> str:
    return "sp" if role in DRUM_ROLES else "mpc"


class NotAudio(ValueError):
    pass


def import_sample(session: Session, filename: str, data: bytes) -> tuple[Sample, bool]:
    """Store an uploaded file. Returns (sample, created). The same bytes uploaded twice give the same sample."""
    sha = hashlib.sha256(data).hexdigest()
    existing = session.scalar(select(Sample).where(Sample.sha256 == sha))
    if existing is not None:
        return existing, False
    try:
        info = sf.info(io.BytesIO(data))
    except Exception as e:  # libsndfile could not parse it
        raise NotAudio(f"{filename}: not a readable audio file ({e})") from e
    ext = Path(filename).suffix.lower() or ".wav"
    stored = f"{sha}{ext}"
    (samples_dir() / stored).write_bytes(data)
    role = guess_role(Path(filename).stem)
    s = Sample(
        original_name=filename,
        sha256=sha,
        length_s=info.frames / info.samplerate,
        sample_rate=info.samplerate,
        role=role,
        route=default_route(role),
        stored_name=stored,
    )
    session.add(s)
    session.flush()
    return s, True


def sample_path(sample: Sample) -> Path:
    if not sample.stored_name:
        raise FileNotFoundError(f"sample {sample.id} has no stored file")
    return samples_dir() / sample.stored_name


def peaks(sample: Sample, n: int = 200) -> list[list[float]]:
    """Min/max pairs for drawing a waveform; cached next to the file."""
    n = max(16, min(int(n), 4000))
    cache = samples_dir() / f"{sample.sha256}.peaks{n}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    x, _ = sf.read(str(sample_path(sample)), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    edges = np.linspace(0, len(x), n + 1).astype(int)
    out = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        seg = x[a : max(b, a + 1)] if len(x) else np.zeros(1, dtype=np.float32)
        out.append([round(float(seg.min()), 4), round(float(seg.max()), 4)])
    cache.write_text(json.dumps(out))
    return out


def sync_presets(session: Session) -> int:
    """Make sure every built-in engine preset exists as version 1 (full, resolved parameters)."""
    added = 0
    for name in PRESETS:
        if session.scalar(select(Preset).where(Preset.name == name, Preset.version == 1)) is None:
            path, params = resolve(name)
            session.add(Preset(name=name, path=path, params=params, version=1))
            added += 1
    session.flush()
    return added


def save_preset(session: Session, name: str, path: str, params: dict) -> Preset:
    """Save as the next version of `name` (a fork is simply a new name)."""
    v = session.scalar(select(func.max(Preset.version)).where(Preset.name == name)) or 0
    p = Preset(name=name, path=path, params=params, version=v + 1)
    session.add(p)
    session.flush()
    return p

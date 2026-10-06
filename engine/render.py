"""File-level rendering: read WAV → run a path → write WAV + spectrogram PNG + params JSON."""

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image

from engine import ENGINE_VERSION, mpc, sp
from engine.dsp import mono
from engine.params import annotate, resolve

PATHS = {"sp": sp.render, "mpc": mpc.render}


def render_array(x: np.ndarray, sr: float, preset: str, overrides: dict | None = None):
    path, params = resolve(preset, overrides)
    y, rate, info = PATHS[path](mono(np.asarray(x, dtype=np.float64)), sr, params)
    return y, rate, info, path, params


def output_name(src: Path, preset: str, path: str, params: dict) -> str:
    stem = re.sub(r"[^\w.-]+", "_", src.stem)
    tune = params["tune"]["st"]
    return f"{stem}__{preset.replace('_', '-')}__tune{'+' if tune > 0 else ''}{tune}"


def spectrogram_png(x: np.ndarray, sr: float, path: Path, width: int = 1200, height: int = 400) -> None:
    """Same colour map as design.md §2 (84 dB range, gamma 1.15)."""
    nfft, hop = 1024, 128
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    frames = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop] * np.hanning(nfft)
    mag = np.abs(np.fft.rfft(frames, axis=1)).T
    d = 20 * np.log10(mag + 1e-12)
    d = np.clip((d - d.max() + 84) / 84, 0, 1) ** 1.15
    d = d[::-1]
    stops = [(0.0, "07090C"), (0.40, "0C151F"), (0.60, "183049"), (0.76, "3E6487"), (0.90, "86AFD3"), (1.0, "E3EEF7")]
    pos = [p for p, _ in stops]
    rgb = np.stack([np.interp(d, pos, [int(c[i : i + 2], 16) for _, c in stops]) for i in (0, 2, 4)], -1)
    Image.fromarray(rgb.astype(np.uint8)).resize((width, height), Image.BILINEAR).save(path, optimize=True)


def write_outputs(
    y: np.ndarray,
    rate: float,
    info: dict,
    path: str,
    params: dict,
    preset: str,
    src_name: str,
    src_sr: float,
    src_sha256: str,
    out_dir: Path,
    attach: bool = True,
) -> dict:
    """Write `<name>.wav` (24-bit), and optionally `<name>__spectro.png` and `<name>__params.json`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = output_name(Path(src_name), preset, path, params)
    wav = out_dir / f"{name}.wav"
    # 24-bit PCM; WAV needs an integer rate, so the native SP rate is written as 26042 in the header.
    sf.write(str(wav), np.clip(y, -1.0, 1.0), int(round(rate)), subtype="PCM_24")
    digest = hashlib.sha256(wav.read_bytes()).hexdigest()
    meta = {
        "engine": ENGINE_VERSION,
        "source": {"name": src_name, "sr": src_sr, "sha256": src_sha256},
        "preset": preset,
        "path": path,
        "params": params,
        "params_annotated": annotate(path, params),
        "output": {"file": wav.name, "rate": rate, "sha256": digest, "length_s": len(y) / rate},
        "info": info,
    }
    files = {"wav": str(wav)}
    if attach:
        png = out_dir / f"{name}__spectro.png"
        spectrogram_png(y, rate, png)
        js = out_dir / f"{name}__params.json"
        js.write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str))
        files.update(png=str(png), json=str(js))
    return {"files": files, **meta}


def render_file(
    src: Path, preset: str, overrides: dict | None = None, out_dir: Path | None = None, attach: bool = True
) -> dict:
    x, sr = sf.read(str(src), dtype="float64", always_2d=False)
    y, rate, info, path, params = render_array(x, sr, preset, overrides)
    src_sha = hashlib.sha256(Path(src).read_bytes()).hexdigest()
    return write_outputs(
        y, rate, info, path, params, preset, Path(src).name, sr, src_sha, Path(out_dir or Path(src).parent), attach
    )

"""MPC60 II sample path (CLAUDE.md §B). Pure functions; the non-linear 12-bit codec has three candidates.

input gain → pre-emphasis [HYP] → 40 kHz, band ≈18 kHz → 16-bit → NL-12 encode/decode [HYP]
→ tune [HYP] → de-emphasis → 16-bit DAC → export rate
"""

import numpy as np
from scipy import signal

from engine import MPC_NATIVE_SR
from engine.dsp import db, rbj_biquad, resample_exact

FS = float(MPC_NATIVE_SR)


def emphasis(x: np.ndarray, emph_db: float, emph_fc: float, inverse: bool = False) -> np.ndarray:
    """High-shelf pre-emphasis (or its exact inverse for de-emphasis). HYPOTHESIS: shape and values."""
    b, a = rbj_biquad("hs", FS, emph_fc, emph_db, 0.707)
    return signal.lfilter(a, b, x) if inverse else signal.lfilter(b, a, x)


def to_native(x: np.ndarray, sr: float, band_hz: float) -> np.ndarray:
    y = resample_exact(x, sr, MPC_NATIVE_SR)
    taps = signal.firwin(255, band_hz, fs=FS)
    return signal.lfilter(taps, [1.0], y)


def q16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.round(x * 32768), -32768, 32767).astype(np.int32)


# --- non-linear 12-bit candidates (all HYPOTHESIS) ----------------------------------------------------------


def nl12_pwl(s16: np.ndarray) -> np.ndarray:
    """Segmented companding, A-law-like: sign + 3-bit segment + 8-bit mantissa = 12 bits.

    Segment 0 covers 0..255 at step 1; segment s (1..7) covers [256·2^(s-1), 256·2^s) at step 2^(s-1).
    Quiet material keeps 16-bit-like resolution; loud material gets coarser steps (relative noise stays low).
    """
    sign = np.where(s16 < 0, -1, 1)
    m = np.minimum(np.abs(s16), 32767)
    seg = np.where(m < 256, 0, np.floor(np.log2(np.maximum(m, 256) / 256.0)).astype(int) + 1)
    seg = np.clip(seg, 0, 7)
    step = np.where(seg == 0, 1, 2 ** np.maximum(seg - 1, 0))
    base = np.where(seg == 0, 0, 256 * 2 ** np.maximum(seg - 1, 0))
    mant = np.clip((m - base) // step, 0, 255)
    return (sign * (base + mant * step + step // 2)).astype(np.int32)


def nl12_grng(s16: np.ndarray, block: int = 32) -> np.ndarray:
    """Block floating point (gain ranging): per block, one shift so the peak fits 12 bits."""
    out = np.empty_like(s16)
    for i in range(0, len(s16), block):
        blk = s16[i : i + block]
        peak = int(np.max(np.abs(blk))) if len(blk) else 0
        shift = 0
        while shift < 4 and peak >= 2048 << shift:
            shift += 1
        step = 1 << shift
        q = np.clip(np.floor(blk / step + 0.5), -2048, 2047) * step
        out[i : i + block] = q.astype(np.int32)
    return out


def nl12_mulaw(s16: np.ndarray, mu: float = 255.0) -> np.ndarray:
    """μ-law curve quantised to 12 bits (sign + 11)."""
    x = s16 / 32768.0
    y = np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu)
    yq = np.round(y * 2047) / 2047
    xr = np.sign(yq) * (np.expm1(np.abs(yq) * np.log1p(mu)) / mu)
    return np.clip(np.round(xr * 32768), -32768, 32767).astype(np.int32)


def codec(s16: np.ndarray, curve: str = "pwl", block: int = 32) -> np.ndarray:
    if curve == "pwl":
        return nl12_pwl(s16)
    if curve == "grng":
        return nl12_grng(s16, block)
    if curve == "mulaw":
        return nl12_mulaw(s16)
    raise ValueError(f"unknown codec curve {curve!r}")


def tune(x: np.ndarray, st: float, interp: str = "none") -> np.ndarray:
    r = 2.0 ** (st / 12)
    if r == 1.0:
        return x.copy()
    n = int(np.floor((len(x) - 1) / r)) + 1
    pos = np.arange(n, dtype=np.float64) * r
    if interp == "none":
        return x[np.floor(pos).astype(np.int64)]
    if interp == "linear":
        return np.interp(pos, np.arange(len(x)), x)
    raise ValueError(f"unknown interp {interp!r}")


def render(x: np.ndarray, sr: float, p: dict) -> tuple[np.ndarray, float, dict]:
    i = p["input"]
    y = x * db(i["gain_db"])
    y = to_native(y, sr, p["resample"]["band_hz"])
    if i["emph"]:
        y = emphasis(y, i["emph_db"], i["emph_fc"])
    s16 = q16(y)
    c = codec(s16, p["codec"]["curve"], int(p["codec"]["block"]))
    info = {"codec_levels_used": int(len(np.unique(c)))}
    v = tune(c.astype(np.float64), p["tune"]["st"], p["tune"]["interp"]) / 32768.0
    if i["emph"]:
        v = emphasis(v, i["emph_db"], i["emph_fc"], inverse=True)
    v = q16(v) / 32768.0  # 16-bit DAC
    rate = p["output"]["rate"]
    if rate == "native":
        return v, FS, info
    return resample_exact(v, MPC_NATIVE_SR, int(rate)), float(rate), info

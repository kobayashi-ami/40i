"""SP-1200 drum path. One pure function per stage, numpy in / numpy out.

Signal flow (CLAUDE.md §A):
  pre_eq → drive → capture → adc (AA, sample at the native clock, 12-bit, hard clip) → tune (drop-sample)
  → vol_env → dac (hold at 4× native) → analog (route / channel filter, at 4× native) → output (export rate)

Analog stages run at an oversampled "continuous" rate so that the hold's images and the filters interact as
they would in the box; the export stage is the only place images above the export Nyquist are removed.
"""

from fractions import Fraction

import numpy as np
from scipy import signal

from engine.dsp import as_fraction, db, rbj_biquad, resample_exact

OVERSAMPLE = 4  # analog-domain rate = 4 × native (≈104 kHz)

# Length ratios measured on hardware, from the open-source `pitcher` project (provenance not stated; see
# docs/research.md). Output length / input length for TUNE −n. HYPOTHESIS.
MEASURED_LENGTH_RATIOS = {
    -1: 1.05652677103003,
    -2: 1.1215356033380033,
    -3: 1.1834835840896631,
    -4: 1.253228360845465,
    -5: 1.3310440397149297,
    -6: 1.4039714929646099,
    -7: 1.5028019735639886,
    -8: 1.5766735700797954,
}


# --- analog front end ---------------------------------------------------------------------------------------


def pre_eq(x: np.ndarray, sr: float, type: str, freq: float, gain_db: float, q: float, on: bool = True):
    if not on or gain_db == 0:
        return x
    b, a = rbj_biquad(type, sr, freq, gain_db, q)
    return signal.lfilter(b, a, x)


def drive(x: np.ndarray, in_db: float, curve: str, mix: float, out_db: float, on: bool = True):
    """Soft saturation before the converter. Its output then meets the 12-bit wall in `adc`."""
    if not on:
        return x
    g = db(in_db)
    u = x * g
    if curve == "tanh":
        y = np.tanh(u)
    elif curve == "atan":
        y = np.arctan(u) * (2 / np.pi)
    elif curve == "cubic":
        c = np.clip(u, -1.5, 1.5)
        y = c - (4 / 27) * c**3
    else:
        raise ValueError(f"unknown drive curve {curve!r}")
    return (mix * y + (1 - mix) * x) * db(out_db)


def capture(x: np.ndarray, sr: float, speed: float, on: bool = True):
    """Play the source faster before sampling (e.g. 45 rpm for a 33⅓ record): same sr, shorter, higher."""
    if not on or speed == 1:
        return x
    r = Fraction(speed).limit_denominator(10000)
    return resample_exact(x, r.numerator, r.denominator) if r != 1 else x


# --- converter -----------------------------------------------------------------------------------------------


def aa_filter(x: np.ndarray, fs: float, kind: str, fc: float) -> np.ndarray:
    """Analog anti-alias filter in front of the S/H (HYPOTHESIS: type and cutoff)."""
    if kind == "off":
        return x
    wn = min(fc / (fs / 2), 0.99)
    if kind == "ellip4":  # as modelled in `pitcher`: 4th order, 1 dB ripple, 72 dB stop
        sos = signal.ellip(4, 1, 72, wn, output="sos")
    elif kind == "butter4":
        sos = signal.butter(4, wn, output="sos")
    else:
        raise ValueError(f"unknown AA filter {kind!r}")
    return signal.sosfilt(sos, x)


def adc(
    x: np.ndarray,
    sr: float,
    native_sr="625000/24",
    aa: str = "ellip4",
    aa_fc: float = 12500.0,
    bits: int = 12,
    dither: str = "off",
    seed: int = 0,
) -> np.ndarray:
    """Analog → integer codes at the native clock.

    The input is first upsampled 4× to stand in for the continuous signal, filtered by the (hypothetical) AA,
    then *sampled* at the native instants without any further filtering — what passes the AA aliases, like
    a real sample-and-hold. Codes are clipped hard at full scale. Returns int32 codes in [-2^(b-1), 2^(b-1)-1].
    """
    fs_hi = Fraction(sr) * 4 if not isinstance(sr, Fraction) else sr * 4
    xh = resample_exact(x, sr, fs_hi)
    xh = aa_filter(xh, float(fs_hi), aa, aa_fc)
    nat = as_fraction(native_sr)
    n_out = int(len(xh) * nat / fs_hi)
    t = np.arange(n_out) * (float(fs_hi) / float(nat))  # native instants in hi-rate sample units
    y = np.interp(t, np.arange(len(xh)), xh)
    full = 2 ** (bits - 1)
    if dither == "tpdf":
        rng = np.random.default_rng(seed)
        y = y + (rng.random(n_out) - rng.random(n_out)) / full
    elif dither != "off":
        raise ValueError(f"unknown dither {dither!r}")
    return np.clip(np.round(y * full), -full, full - 1).astype(np.int32)


def tune_ratio(st: int, table: str = "measured") -> float:
    """Read-pointer step per output sample. < 1 lowers pitch (samples get repeated)."""
    if st == 0:
        return 1.0
    if table == "equal_tempered" or st > 0:  # no measured data above 0: fall back to ET (HYPOTHESIS)
        return 2.0 ** (st / 12)
    if table == "measured":
        if st not in MEASURED_LENGTH_RATIOS:
            raise ValueError(f"TUNE {st} outside the measured table (-8..-1)")
        return 1.0 / MEASURED_LENGTH_RATIOS[st]
    raise ValueError(f"unknown tune table {table!r}")


def tune(codes: np.ndarray, st: int, table: str = "measured") -> np.ndarray:
    """Drop-sample pitch shift at a fixed output rate. NO interpolation, by design (CLAUDE.md)."""
    r = tune_ratio(st, table)
    if r == 1.0:
        return codes.copy()
    n = int(np.floor((len(codes) - 1) / r)) + 1
    idx = np.floor(np.arange(n, dtype=np.float64) * r).astype(np.int64)
    return codes[idx]


def vol_env(codes: np.ndarray, native_sr, decay_s: float, on: bool = False) -> np.ndarray:
    """8-bit stepped decay (256 levels) applied to the codes' playback level."""
    if not on:
        return codes.astype(np.float64)
    fs = float(as_fraction(native_sr))
    t = np.arange(len(codes)) / fs
    level = np.floor(255 * np.exp(-t / max(decay_s, 1e-4)) + 1e-9) / 255
    return codes * level


# --- back end ------------------------------------------------------------------------------------------------


def dac(codes: np.ndarray, bits: int = 12, hold: str = "zoh") -> np.ndarray:
    """Codes → volts held for one native period, rendered at OVERSAMPLE × native."""
    v = np.asarray(codes, dtype=np.float64) / 2 ** (bits - 1)
    if hold == "zoh":
        return np.repeat(v, OVERSAMPLE)
    if hold == "linear":
        n = len(v)
        return np.interp(np.arange(n * OVERSAMPLE) / OVERSAMPLE, np.arange(n), v)
    raise ValueError(f"unknown hold {hold!r}")


def _fixed_filter(x, fs, ch: int, curve: str):
    """ch3–4 ≈ 7.5 kHz curve, ch5–6 ≈ 10 kHz (after Yeh 2007 / pitcher). HYPOTHESIS."""
    if curve == "butter2":
        fc = 7500.0 if ch in (3, 4) else 10000.0
        return signal.sosfilt(signal.butter(2, fc / (fs / 2), output="sos"), x)
    if ch in (3, 4):
        freq = [0, 6510, 8000, 10000, 11111, 13020, 15000, 17500, 20000, 24000, fs / 2]
        att = [0, 0, -5, -10, -15, -23, -28, -35, -41, -40, -60]
        taps = signal.firwin2(127, freq, 10 ** (np.array(att) / 20), fs=fs)
        return signal.lfilter(taps, [1.0], x)
    return signal.sosfilt(signal.butter(7, 10000 / (fs / 2), output="sos"), x)


def _ladder(x, fs, fc, env_amt, env_decay_s, res):
    """4-pole ladder low-pass with a level-following cutoff sweep — a behavioural SSM2044 stand-in.

    Zero-delay-feedback (TPT) one-pole stages with global resonance feedback; the cutoff follows a peak
    envelope of the input (attack instant, exponential decay). HYPOTHESIS: all values.
    """
    n = len(x)
    rel = np.exp(-1.0 / (env_decay_s * fs))
    env = np.empty(n)
    e = 0.0
    ax = np.abs(x)
    for i in range(n):
        e = ax[i] if ax[i] > e else e * rel
        env[i] = e
    fcs = np.clip(fc * (2.0 ** (env_amt * 4.0 * np.minimum(env, 1.0))), 20.0, 0.45 * fs)
    g_all = np.tan(np.pi * fcs / fs)
    k = 4.0 * res
    s1 = s2 = s3 = s4 = 0.0
    y = np.empty(n)
    for i in range(n):
        g = g_all[i]
        G = g / (1 + g)
        G2, G3, G4 = G * G, G * G * G, G * G * G * G
        S = G3 * (s1 / (1 + g)) + G2 * (s2 / (1 + g)) + G * (s3 / (1 + g)) + s4 / (1 + g)
        u = (x[i] - k * S) / (1 + k * G4)
        v1 = (u - s1) * G
        lp1 = v1 + s1
        s1 = lp1 + v1
        v2 = (lp1 - s2) * G
        lp2 = v2 + s2
        s2 = lp2 + v2
        v3 = (lp2 - s3) * G
        lp3 = v3 + s3
        s3 = lp3 + v3
        v4 = (lp3 - s4) * G
        lp4 = v4 + s4
        s4 = lp4 + v4
        y[i] = lp4
    return y


def analog(
    x: np.ndarray,
    fs: float,
    route: str = "tip",
    ch: int = 1,
    fc: float = 9800.0,
    env: float = 0.25,
    env_decay_s: float = 0.15,
    res: float = 0.2,
    fixed_curve: str = "pitcher",
) -> np.ndarray:
    """Output stage. `tip` (mono plug) and ch7–8 bypass every filter; `ring`/`mix` apply the channel filter."""
    if route == "tip" or ch in (7, 8):
        return x
    if route not in ("ring", "mix"):
        raise ValueError(f"unknown route {route!r}")
    if ch in (1, 2):
        return _ladder(x, fs, fc, env, env_decay_s, res)
    if ch in (3, 4, 5, 6):
        return _fixed_filter(x, fs, ch, fixed_curve)
    raise ValueError(f"channel {ch} out of 1..8")


def output(x: np.ndarray, native_sr, rate, src: str = "keep_zoh") -> tuple[np.ndarray, float]:
    """Analog-domain signal (at OVERSAMPLE × native) → export rate.

    keep_zoh: band-limit only at the export Nyquist, so hold images up to it survive.
    sinc:     remove everything above the native Nyquist first (a clean reconstruction, for comparison).
    linear:   naive linear interpolation to the export rate.
    native:   decimate back to one value per native period (the held value).
    """
    nat = as_fraction(native_sr)
    fs_hi = nat * OVERSAMPLE
    if rate == "native":
        return x[::OVERSAMPLE].copy(), float(nat)
    rate = int(rate)
    if src == "keep_zoh":
        return resample_exact(x, fs_hi, rate), float(rate)
    if src == "sinc":
        held = x[::OVERSAMPLE]
        return resample_exact(held, nat, rate), float(rate)
    if src == "linear":
        n = int(len(x) * rate / fs_hi)
        t = np.arange(n) * float(fs_hi) / rate
        return np.interp(t, np.arange(len(x)), x), float(rate)
    raise ValueError(f"unknown src {src!r}")


# --- the chain -----------------------------------------------------------------------------------------------


def render(x: np.ndarray, sr: float, p: dict) -> tuple[np.ndarray, float, dict]:
    """Run the full drum path. Returns (audio, export_rate, info)."""
    info: dict = {}
    y = pre_eq(x, sr, **p["pre_eq"])
    y = drive(y, **p["drive"])
    y = capture(y, sr, **p["capture"])
    a = p["adc"]
    codes = adc(y, sr, a["native_sr"], a["aa"], a["aa_fc"], a["bits"], a["dither"], a["seed"])
    info["adc_levels_used"] = int(len(np.unique(codes)))
    full = 2 ** (a["bits"] - 1)
    info["adc_clipped"] = int(np.sum((codes == full - 1) | (codes == -full)))
    info["native_sr"] = float(as_fraction(a["native_sr"]))
    codes = tune(codes, p["tune"]["st"], p["tune"]["table"])
    info["tune_ratio"] = tune_ratio(p["tune"]["st"], p["tune"]["table"])
    lvl = vol_env(codes, a["native_sr"], **p["vol_env"])
    v = dac(lvl, a["bits"], p["dac"]["hold"])
    fs_hi = float(as_fraction(a["native_sr"]) * OVERSAMPLE)
    v = analog(v, fs_hi, **p["analog"])
    out, rate = output(v, a["native_sr"], p["output"]["rate"], p["output"]["src"])
    return out, rate, info

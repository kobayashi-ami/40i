"""Small DSP helpers shared by the stages."""

from fractions import Fraction

import numpy as np
from scipy import signal


def db(x: float) -> float:
    return 10.0 ** (x / 20.0)


def as_fraction(sr) -> Fraction:
    if isinstance(sr, Fraction):
        return sr
    if isinstance(sr, str) and "/" in sr:
        n, d = sr.split("/")
        return Fraction(int(n), int(d))
    return Fraction(sr).limit_denominator(1000)


def resample_exact(x: np.ndarray, sr_in, sr_out) -> np.ndarray:
    """Band-limited resampling with an exact rational ratio (polyphase FIR)."""
    r = as_fraction(sr_out) / as_fraction(sr_in)
    if r == 1:
        return x.copy()
    return signal.resample_poly(x, r.numerator, r.denominator, axis=-1)


def rbj_biquad(kind: str, fs: float, f0: float, gain_db: float, q: float) -> tuple[np.ndarray, np.ndarray]:
    """RBJ audio-EQ cookbook: 'ls' low shelf, 'hs' high shelf, 'pk' peaking."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / fs
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if kind == "pk":
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        den = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    elif kind in ("ls", "hs"):
        s = 2 * np.sqrt(a) * alpha
        if kind == "ls":
            b = [a * ((a + 1) - (a - 1) * cw + s), 2 * a * ((a - 1) - (a + 1) * cw), a * ((a + 1) - (a - 1) * cw - s)]
            den = [(a + 1) + (a - 1) * cw + s, -2 * ((a - 1) + (a + 1) * cw), (a + 1) + (a - 1) * cw - s]
        else:
            b = [a * ((a + 1) + (a - 1) * cw + s), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - s)]
            den = [(a + 1) - (a - 1) * cw + s, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - s]
    else:
        raise ValueError(f"unknown EQ type {kind!r}")
    b, den = np.array(b), np.array(den)
    return b / den[0], den / den[0]


def mono(x: np.ndarray) -> np.ndarray:
    return x if x.ndim == 1 else x.mean(axis=1)

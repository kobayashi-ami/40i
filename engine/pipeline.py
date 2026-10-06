"""The two paths as named step lists, so a worker can run them one stage at a time and report progress.

Step names match `core.jobs.STAGES`. Running every step in order gives exactly `sp.render` / `mpc.render`.
"""

from collections.abc import Callable

import numpy as np

from engine import MPC_NATIVE_SR, mpc, sp
from engine.dsp import as_fraction, db, mono, resample_exact
from engine.params import MPC_DEFAULTS, SP_DEFAULTS, deep_merge

Step = tuple[str, Callable[[dict], None]]


def full_params(path: str, params: dict, overrides: dict | None = None) -> dict:
    defaults = SP_DEFAULTS if path == "sp" else MPC_DEFAULTS
    return deep_merge(deep_merge(defaults, params), overrides or {})


def sp_steps(p: dict) -> list[Step]:
    a = p["adc"]

    def role(s):
        s["y"] = mono(np.asarray(s["x"], dtype=np.float64))

    def pre_eq(s):
        s["y"] = sp.pre_eq(s["y"], s["sr"], **p["pre_eq"])

    def drive(s):
        s["y"] = sp.drive(s["y"], **p["drive"])

    def capture(s):
        s["y"] = sp.capture(s["y"], s["sr"], **p["capture"])

    def adc(s):
        c = sp.adc(s["y"], s["sr"], a["native_sr"], a["aa"], a["aa_fc"], a["bits"], a["dither"], a["seed"])
        full = 2 ** (a["bits"] - 1)
        s["info"].update(
            adc_levels_used=int(len(np.unique(c))),
            adc_clipped=int(np.sum((c == full - 1) | (c == -full))),
            native_sr=float(as_fraction(a["native_sr"])),
        )
        s["codes"] = c

    def tune(s):
        s["codes"] = sp.tune(s["codes"], p["tune"]["st"], p["tune"]["table"])
        s["info"]["tune_ratio"] = sp.tune_ratio(p["tune"]["st"], p["tune"]["table"])

    def vol_env(s):
        s["lvl"] = sp.vol_env(s["codes"], a["native_sr"], **p["vol_env"])

    def dac(s):
        s["v"] = sp.dac(s["lvl"], a["bits"], p["dac"]["hold"])

    def analog(s):
        s["v"] = sp.analog(s["v"], float(as_fraction(a["native_sr"]) * sp.OVERSAMPLE), **p["analog"])

    def output(s):
        s["out"], s["rate"] = sp.output(s["v"], a["native_sr"], p["output"]["rate"], p["output"]["src"])

    return [(f.__name__, f) for f in (role, pre_eq, drive, capture, adc, tune, vol_env, dac, analog, output)]


def mpc_steps(p: dict) -> list[Step]:
    i = p["input"]

    def input(s):  # noqa: A001 - stage name
        s["y"] = mono(np.asarray(s["x"], dtype=np.float64)) * db(i["gain_db"])

    def resample(s):
        y = mpc.to_native(s["y"], s["sr"], p["resample"]["band_hz"])
        s["y"] = mpc.emphasis(y, i["emph_db"], i["emph_fc"]) if i["emph"] else y

    def nl12_codec(s):
        c = mpc.codec(mpc.q16(s["y"]), p["codec"]["curve"], int(p["codec"]["block"]))
        s["info"]["codec_levels_used"] = int(len(np.unique(c)))
        s["c"] = c

    def tune(s):
        s["v"] = mpc.tune(s["c"].astype(np.float64), p["tune"]["st"], p["tune"]["interp"]) / 32768.0

    def deemph_dac(s):
        v = mpc.emphasis(s["v"], i["emph_db"], i["emph_fc"], inverse=True) if i["emph"] else s["v"]
        v = mpc.q16(v) / 32768.0
        rate = p["output"]["rate"]
        if rate == "native":
            s["out"], s["rate"] = v, float(MPC_NATIVE_SR)
        else:
            s["out"], s["rate"] = resample_exact(v, MPC_NATIVE_SR, int(rate)), float(rate)

    return [(f.__name__, f) for f in (input, resample, nl12_codec, tune, deemph_dac)]


def steps(path: str, p: dict) -> list[Step]:
    return sp_steps(p) if path == "sp" else mpc_steps(p)


def run(path: str, p: dict, x: np.ndarray, sr: float, on_step=None) -> tuple[np.ndarray, float, dict]:
    """Run every step. `on_step(index, name)` is called before each step (for progress / cancellation)."""
    state = {"x": x, "sr": sr, "info": {}}
    for k, (name, fn) in enumerate(steps(path, p)):
        if on_step:
            on_step(k, name)
        fn(state)
    return state["out"], state["rate"], state["info"]

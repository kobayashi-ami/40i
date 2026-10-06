"""Parameter schema, status labels (VER / HYP) and built-in presets.

A parameter is VER when docs/research.md cites a source for it, HYP otherwise. HYP parameters always have
switchable candidates or a range, never a single hard-coded value.
"""

import copy
from dataclasses import dataclass, field
from typing import Any

VER, HYP = "VER", "HYP"


@dataclass(frozen=True)
class Param:
    status: str
    note: str
    candidates: tuple | None = None
    lo: float | None = None
    hi: float | None = None
    extra: dict = field(default_factory=dict)


# Keys are dotted paths into the params dict ("sp.adc.bits").
SCHEMA: dict[str, Param] = {
    # --- SP-1200 drum path ------------------------------------------------------------------------------
    "sp.role": Param(VER, "owner's role tag; picks the preset", ("kick", "snare", "hat", "perc", "other")),
    "sp.pre_eq.type": Param(VER, "owner recipe: kick low / snare high", ("ls", "pk", "hs")),
    "sp.pre_eq.freq": Param(VER, "kick 60–100 Hz, snare 5–8 kHz (owner)", lo=20, hi=16000),
    "sp.pre_eq.gain_db": Param(VER, "+9…+12 dB 'ガン突き' (owner)", lo=-24, hi=24),
    "sp.pre_eq.q": Param(VER, "shape", lo=0.1, hi=10),
    "sp.drive.in_db": Param(VER, "'ちょい歪み' (owner)", lo=-24, hi=36),
    "sp.drive.curve": Param(HYP, "the analog stage that clipped is not known", ("tanh", "atan", "cubic")),
    "sp.drive.mix": Param(VER, "dry/wet", lo=0, hi=1),
    "sp.drive.out_db": Param(VER, "level into the ADC", lo=-24, hi=24),
    "sp.capture.speed": Param(VER, "pre-speed, 45/33.33 = 1.35 for the 45 rpm trick", lo=0.25, hi=4),
    "sp.adc.native_sr": Param(VER, "10 MHz / 384; 26040 also quoted", ("625000/24", "26040")),
    "sp.adc.aa": Param(HYP, "input anti-alias filter exists; type unknown", ("ellip4", "butter4", "off")),
    "sp.adc.aa_fc": Param(HYP, "cutoff of the input filter", lo=6000, hi=13020),
    "sp.adc.bits": Param(VER, "12-bit linear", (12,)),
    "sp.adc.dither": Param(VER, "none on the original", ("off", "tpdf")),
    "sp.tune.st": Param(VER, "−8…+7 semitone steps", lo=-8, hi=7),
    "sp.tune.table": Param(HYP, "ET = 2^(n/12); measured = pitcher table", ("measured", "equal_tempered")),
    "sp.vol_env.on": Param(VER, "8-bit stepped decay, optional", (False, True)),
    "sp.vol_env.decay_s": Param(HYP, "decay time", lo=0.01, hi=10),
    "sp.dac.hold": Param(VER, "one DAC into per-channel S/H", ("zoh", "linear")),
    "sp.analog.route": Param(
        VER, "TRS tip = unfiltered, ring = filtered, mix = filtered ch1–6", ("tip", "ring", "mix")
    ),
    "sp.analog.ch": Param(VER, "1–2 SSM2044, 3–6 fixed, 7–8 none", lo=1, hi=8),
    "sp.analog.fc": Param(HYP, "SSM2044 base cutoff (ch1–2)", lo=500, hi=20000),
    "sp.analog.env": Param(HYP, "level-following cutoff sweep amount (ch1–2)", lo=0, hi=1),
    "sp.analog.env_decay_s": Param(HYP, "sweep decay (ch1–2)", lo=0.005, hi=2),
    "sp.analog.res": Param(HYP, "ladder resonance (ch1–2)", lo=0, hi=0.95),
    "sp.analog.fixed_curve": Param(HYP, "ch3–6 curves after Yeh 2007 via pitcher", ("pitcher", "butter2")),
    "sp.output.rate": Param(VER, "export rate", (48000, 44100, "native")),
    "sp.output.src": Param(VER, "how the hold is carried to the export rate", ("keep_zoh", "sinc", "linear")),
    # --- MPC60 II sample path ---------------------------------------------------------------------------
    "mpc.input.gain_db": Param(VER, "input level", lo=-24, hi=24),
    "mpc.input.emph": Param(HYP, "high-pass pre-emphasis reported, values unknown", (True, False)),
    "mpc.input.emph_db": Param(HYP, "shelf amount", lo=0, hi=12),
    "mpc.input.emph_fc": Param(HYP, "shelf corner", lo=500, hi=10000),
    "mpc.resample.band_hz": Param(VER, "20 Hz–18 kHz response", lo=10000, hi=19999),
    "mpc.codec.curve": Param(HYP, "the non-linear 12-bit format is unpublished", ("pwl", "grng", "mulaw")),
    "mpc.codec.block": Param(HYP, "block length for gain ranging", lo=4, hi=1024),
    "mpc.tune.st": Param(HYP, "−12…+6 reported once", lo=-12, hi=6),
    "mpc.tune.interp": Param(HYP, "interpolation unknown", ("none", "linear")),
    "mpc.output.rate": Param(VER, "export rate", (48000, 44100, "native")),
}

SP_DEFAULTS: dict[str, Any] = {
    "role": "other",
    "pre_eq": {"on": False, "type": "pk", "freq": 1000.0, "gain_db": 0.0, "q": 0.71},
    "drive": {"on": True, "in_db": 3.0, "curve": "tanh", "mix": 1.0, "out_db": 0.0},
    "capture": {"on": False, "speed": 1.0},
    "adc": {"native_sr": "625000/24", "aa": "ellip4", "aa_fc": 12500.0, "bits": 12, "dither": "off", "seed": 0},
    "tune": {"st": 0, "table": "measured"},
    "vol_env": {"on": False, "decay_s": 0.5},
    "dac": {"hold": "zoh"},
    "analog": {
        "route": "tip",
        "ch": 1,
        "fc": 9800.0,
        "env": 0.25,
        "env_decay_s": 0.15,
        "res": 0.2,
        "fixed_curve": "pitcher",
    },
    "output": {"rate": 48000, "src": "keep_zoh"},
}

MPC_DEFAULTS: dict[str, Any] = {
    "input": {"gain_db": 0.0, "emph": True, "emph_db": 6.0, "emph_fc": 3200.0},
    "resample": {"band_hz": 18000.0},
    "codec": {"curve": "pwl", "block": 32},
    "tune": {"st": 0, "interp": "none"},
    "output": {"rate": 48000},
}

# Built-in presets: path + overrides on the defaults.
PRESETS: dict[str, dict] = {
    "sp_kick_low": {
        "path": "sp",
        "params": {
            "role": "kick",
            "pre_eq": {"on": True, "type": "ls", "freq": 80.0, "gain_db": 10.0, "q": 0.71},
            "drive": {"in_db": 4.0},
            "tune": {"st": -2},
        },
    },
    "sp_snare_hard": {
        "path": "sp",
        "params": {
            "role": "snare",
            "pre_eq": {"on": True, "type": "hs", "freq": 6500.0, "gain_db": 11.0, "q": 0.71},
            "drive": {"in_db": 6.0, "out_db": 1.5},
            "tune": {"st": -2},
        },
    },
    "sp_hat_air": {
        "path": "sp",
        "params": {
            "role": "hat",
            "pre_eq": {"on": True, "type": "hs", "freq": 8000.0, "gain_db": 6.0, "q": 0.71},
            "drive": {"in_db": 2.0},
            "tune": {"st": -1},
        },
    },
    "sp_perc_ch3": {"path": "sp", "params": {"role": "perc", "tune": {"st": -1}, "analog": {"route": "ring", "ch": 3}}},
    "sp_break_45": {
        "path": "sp",
        "params": {"role": "other", "capture": {"on": True, "speed": 45 / (100 / 3)}, "tune": {"st": -5}},
    },
    "sp_neutral": {"path": "sp", "params": {"drive": {"on": False}}},
    "mpc_nl_pwl": {"path": "mpc", "params": {"codec": {"curve": "pwl"}}},
    "mpc_nl_grng": {"path": "mpc", "params": {"codec": {"curve": "grng"}}},
    "mpc_nl_ulaw": {"path": "mpc", "params": {"codec": {"curve": "mulaw"}}},
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def resolve(preset: str, overrides: dict | None = None) -> tuple[str, dict]:
    """Return (path, full params) for a preset name plus overrides."""
    if preset not in PRESETS:
        raise KeyError(f"unknown preset {preset!r}; choose from {', '.join(sorted(PRESETS))}")
    p = PRESETS[preset]
    defaults = SP_DEFAULTS if p["path"] == "sp" else MPC_DEFAULTS
    return p["path"], deep_merge(deep_merge(defaults, p["params"]), overrides or {})


def set_dotted(params: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    d = params
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def annotate(path: str, params: dict) -> dict:
    """Flatten params with their VER/HYP status, for the JSON sidecar and the UI tags."""
    out = {}

    def walk(prefix, node):
        for k, v in node.items():
            key = f"{prefix}.{k}"
            if isinstance(v, dict):
                walk(key, v)
            else:
                spec = SCHEMA.get(key)
                out[key] = {"value": v, "status": spec.status if spec else None}

    walk(path, params)
    return out

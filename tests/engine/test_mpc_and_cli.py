import json

import numpy as np
import pytest
import soundfile as sf

from engine import mpc
from engine.__main__ import main
from engine.params import PRESETS, SCHEMA, annotate, resolve
from engine.render import render_array

SR = 48000


def snr_db(ref, test):
    return 10 * np.log10(np.sum(ref.astype(float) ** 2) / (np.sum((ref.astype(float) - test) ** 2) + 1e-9))


@pytest.mark.parametrize("curve", ["pwl", "grng", "mulaw"])
def test_nl12_candidates_beat_linear_12_bit_on_quiet_material(curve):
    t = np.arange(SR) / SR
    quiet = np.round(np.sin(2 * np.pi * 440 * t) * 32768 * 10 ** (-40 / 20)).astype(np.int32)  # −40 dBFS
    linear12 = (np.round(quiet / 16) * 16).astype(np.int32)
    coded = mpc.codec(quiet, curve)
    assert snr_db(quiet, coded) > snr_db(quiet, linear12) + 6, curve
    loud = (np.sin(2 * np.pi * 440 * t) * 30000).astype(np.int32)
    assert snr_db(loud, mpc.codec(loud, curve)) > 40


def test_pwl_has_at_most_4096_codes():
    full = np.arange(-32768, 32768, dtype=np.int32)
    assert len(np.unique(mpc.nl12_pwl(full))) <= 4096


def test_emphasis_round_trips():
    x = np.random.default_rng(3).normal(0, 0.1, 40000)
    y = mpc.emphasis(mpc.emphasis(x, 6, 3200), 6, 3200, inverse=True)
    assert np.max(np.abs(y - x)) < 1e-9


def test_mpc_tune_interp_switch():
    x = np.arange(1000, dtype=float)
    assert np.all(mpc.tune(x, -12, "none") == np.floor(np.arange(len(mpc.tune(x, -12))) * 0.5))
    lin = mpc.tune(x, -12, "linear")
    assert lin[1] == pytest.approx(0.5)


def test_mpc_render_band_limit_and_determinism():
    x = np.random.default_rng(5).normal(0, 0.2, SR)
    a, rate, info, path, _ = render_array(x, SR, "mpc_nl_pwl")
    b = render_array(x, SR, "mpc_nl_pwl")[0]
    assert path == "mpc" and rate == SR and np.array_equal(a, b)
    spec = np.abs(np.fft.rfft(a)) ** 2
    f = np.fft.rfftfreq(len(a), 1 / SR)
    assert spec[f > 19500].sum() < 1e-3 * spec[(f > 1000) & (f < 15000)].sum()


def test_every_hypothesis_has_candidates_or_range_and_is_annotated():
    for key, spec in SCHEMA.items():
        assert spec.status in ("VER", "HYP")
        if spec.status == "HYP":
            assert spec.candidates or (spec.lo is not None and spec.hi is not None), key
    path, params = resolve("sp_snare_hard")
    ann = annotate(path, params)
    assert ann["sp.adc.aa"]["status"] == "HYP" and ann["sp.adc.bits"]["status"] == "VER"
    assert ann["sp.tune.table"] == {"value": "measured", "status": "HYP"}
    assert ann["sp.analog.route"]["value"] == "tip"  # owner rig default
    for name in PRESETS:
        resolve(name)


def test_cli_render_writes_wav_png_json(tmp_path, capsys):
    t = np.arange(int(0.3 * 44100)) / 44100
    sf.write(tmp_path / "snare 04.wav", 0.5 * np.sin(2 * np.pi * 200 * t) * np.exp(-t * 20), 44100, subtype="PCM_24")
    rc = main(
        [
            "render",
            str(tmp_path / "snare 04.wav"),
            "--preset",
            "sp_snare_hard",
            "--tune",
            "-2",
            "--set",
            "analog.route=ring",
            "--set",
            "analog.ch=3",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    out = tmp_path / "out"
    stem = "snare_04__sp-snare-hard__tune-2"
    assert (out / f"{stem}.wav").exists() and (out / f"{stem}__spectro.png").exists()
    meta = json.loads((out / f"{stem}__params.json").read_text())
    assert meta["params"]["analog"] == {**meta["params"]["analog"], "route": "ring", "ch": 3}
    info = sf.info(str(out / f"{stem}.wav"))
    assert info.samplerate == 48000 and info.subtype == "PCM_24"
    assert "sha256" in capsys.readouterr().out

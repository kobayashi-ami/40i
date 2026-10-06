"""SP-1200 path: the properties CLAUDE.md §10 asks for, stage by stage."""

import hashlib
import time
from fractions import Fraction

import numpy as np
import pytest

from engine import SP_NATIVE_SR, sp
from engine.dsp import as_fraction
from engine.params import resolve
from engine.render import render_array

SR = 48000


def tone(f, sec=0.5, amp=0.5, sr=SR):
    t = np.arange(int(sec * sr)) / sr
    return amp * np.sin(2 * np.pi * f * t)


def snare(sec=0.4, seed=1):
    t = np.arange(int(sec * SR)) / SR
    rng = np.random.default_rng(seed)
    return 0.6 * (rng.normal(0, 0.4, len(t)) * np.exp(-t * 12) + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25))


def band_energy(x, sr, lo, hi):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return spec[(f >= lo) & (f < hi)].sum()


# --- converter --------------------------------------------------------------------------------------------


def test_native_rate_is_exact_and_configurable():
    assert SP_NATIVE_SR == Fraction(10_000_000, 384) == Fraction(20_000_000, 768)
    x = tone(1000, sec=1.0)
    assert abs(len(sp.adc(x, SR)) - 26041.67) <= 1
    assert abs(len(sp.adc(x, SR, native_sr="26040")) - 26040) <= 1
    assert as_fraction("26040") == 26040


def test_12_bit_codes_never_exceed_4096_levels_and_hard_clip():
    x = np.linspace(-3, 3, 200_000)  # way past full scale
    codes = sp.adc(x, SR, aa="off")
    assert codes.min() == -2048 and codes.max() == 2047
    assert len(np.unique(codes)) <= 4096
    # a quiet signal uses few levels: 12-bit means the step is 1/2048 of full scale
    quiet = sp.adc(tone(500, amp=10 / 2048), SR, aa="off")
    assert set(np.unique(quiet)) <= set(range(-11, 12))


def test_no_dither_by_default_and_seeded_dither_is_deterministic():
    x = tone(440, amp=0.01)
    assert np.array_equal(sp.adc(x, SR), sp.adc(x, SR))
    a = sp.adc(x, SR, dither="tpdf", seed=7)
    assert np.array_equal(a, sp.adc(x, SR, dither="tpdf", seed=7))
    assert not np.array_equal(a, sp.adc(x, SR, dither="tpdf", seed=8))


def test_aa_filter_candidates_change_what_aliases():
    fs = float(SP_NATIVE_SR)
    # 20 kHz is above the native Nyquist (13.02 kHz): without an input filter it folds to ~6.04 kHz
    x = tone(20000, sec=1.0)
    off = sp.adc(x, SR, aa="off") / 2048
    ell = sp.adc(x, SR, aa="ellip4", aa_fc=12500) / 2048
    assert band_energy(off, fs, 5900, 6200) > 100 * band_energy(ell, fs, 5900, 6200)
    # just above Nyquist a 4th-order filter only partly helps: some aliasing still gets through (by design)
    x = tone(15000, sec=1.0)
    off = sp.adc(x, SR, aa="off") / 2048
    ell = sp.adc(x, SR, aa="ellip4", aa_fc=12500) / 2048
    assert 0 < band_energy(ell, fs, 10900, 11200) < band_energy(off, fs, 10900, 11200)


# --- TUNE -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("st", [-1, -2, -5, 3])
def test_tune_equal_tempered_reads_with_ratio_2_pow_n_over_12(st):
    codes = np.arange(10_000, dtype=np.int32)
    out = sp.tune(codes, st, "equal_tempered")
    r = 2 ** (st / 12)
    n = np.arange(len(out))
    assert np.array_equal(out, np.floor(n * r).astype(int))  # pointer = floor(n·r): no interpolation
    assert abs(len(out) * r - len(codes)) <= 1 + r


def test_tune_measured_table_differs_from_equal_tempered():
    assert sp.tune_ratio(-1, "measured") == pytest.approx(1 / 1.05652677103003)
    assert sp.tune_ratio(-2, "measured") == pytest.approx(0.8916346, rel=1e-6)
    assert sp.tune_ratio(-2, "equal_tempered") == pytest.approx(0.8908987, rel=1e-6)
    assert sp.tune_ratio(3, "measured") == sp.tune_ratio(3, "equal_tempered")  # no data above 0
    with pytest.raises(ValueError):
        sp.tune_ratio(-9, "measured")


def test_tune_down_repeats_samples_in_the_drop_sample_pattern():
    codes = np.arange(1000, dtype=np.int32)
    steps = np.diff(sp.tune(codes, -2, "measured"))
    assert set(np.unique(steps)) == {0, 1}  # lower pitch = some samples read twice, never skipped
    # a repeat every 1/(1-r) ≈ 9.2 output samples → modulation at fs·(1−r) ≈ 2822 Hz
    assert np.mean(steps == 0) == pytest.approx(1 - sp.tune_ratio(-2), abs=0.01)


def test_drop_sample_leaves_images_that_interpolation_would_remove():
    x = tone(3000, sec=1.0)
    _, p = resolve("sp_neutral", {"tune": {"st": -2}, "adc": {"aa": "off"}})
    keep, rate, _, _, _ = render_array(x, SR, "sp_neutral", {"tune": {"st": -2}, "adc": {"aa": "off"}})
    clean, _, _, _, _ = render_array(
        x, SR, "sp_neutral", {"tune": {"st": -2}, "adc": {"aa": "off"}, "output": {"src": "sinc"}}
    )
    # images of the hold live above the native Nyquist (13.02 kHz) and survive only with keep_zoh
    img_keep = band_energy(keep, rate, 13500, 23500)
    img_clean = band_energy(clean, rate, 13500, 23500)
    assert img_keep > 100 * img_clean
    # and the drop-sample sidebands (f·r ± fs·(1−r)) are present below Nyquist too
    f_main = 3000 * sp.tune_ratio(-2)
    side = f_main + float(SP_NATIVE_SR) * (1 - sp.tune_ratio(-2))
    assert band_energy(keep, rate, side - 40, side + 40) > 1e-3 * band_energy(keep, rate, f_main - 40, f_main + 40)


# --- envelope, DAC, analog --------------------------------------------------------------------------------


def test_vol_env_uses_256_steps():
    codes = np.full(26042, 2000, dtype=np.int32)
    out = sp.vol_env(codes, SP_NATIVE_SR, decay_s=0.3, on=True)
    levels = np.unique(np.round(out / 2000 * 255))
    assert len(levels) <= 256 and np.all(np.diff(out) <= 0)
    assert np.array_equal(sp.vol_env(codes, SP_NATIVE_SR, 0.3, on=False), codes.astype(float))


def test_dac_holds_each_code_for_one_native_period():
    v = sp.dac(np.array([2047, -2048, 0], dtype=np.int32))
    assert np.allclose(v, np.repeat([2047 / 2048, -1.0, 0.0], sp.OVERSAMPLE))


def test_analog_routes():
    fs = float(SP_NATIVE_SR) * sp.OVERSAMPLE
    x = np.random.default_rng(0).normal(0, 0.2, int(fs * 0.5))
    assert sp.analog(x, fs, route="tip", ch=1) is x  # mono plug: unfiltered
    assert sp.analog(x, fs, route="ring", ch=7) is x  # ch7–8 have no filter
    for ch in (3, 5, 1):  # ≈7.5 kHz curve, ≈10 kHz Butterworth, ladder at 9.8 kHz
        y = sp.analog(x, fs, route="ring", ch=ch, env=0.0)
        hi = band_energy(y, fs, 13000, 20000) / band_energy(x, fs, 13000, 20000)
        lo = band_energy(y, fs, 200, 2000) / band_energy(x, fs, 200, 2000)
        assert hi < 0.1 * lo, f"ch{ch} should low-pass"


def test_ladder_cutoff_follows_level():
    fs = float(SP_NATIVE_SR) * sp.OVERSAMPLE
    n = int(fs * 0.3)
    burst = np.random.default_rng(1).normal(0, 0.3, n) * np.exp(-np.arange(n) / (0.05 * fs))
    open_ = sp.analog(burst, fs, route="ring", ch=1, fc=2000, env=1.0, env_decay_s=0.05)
    closed = sp.analog(burst, fs, route="ring", ch=1, fc=2000, env=0.0)
    head = slice(0, int(0.01 * fs))
    assert band_energy(open_[head], fs, 5000, 15000) > 3 * band_energy(closed[head], fs, 5000, 15000)


# --- whole path -------------------------------------------------------------------------------------------


def test_render_is_deterministic():
    x = snare()
    h = [hashlib.sha256(render_array(x, SR, "sp_snare_hard")[0].tobytes()).hexdigest() for _ in range(2)]
    assert h[0] == h[1]
    other = hashlib.sha256(render_array(x, SR, "sp_snare_hard", {"tune": {"st": -1}})[0].tobytes()).hexdigest()
    assert other != h[0]


def test_native_rate_export_is_one_value_per_period():
    y, rate, _, _, _ = render_array(snare(), SR, "sp_snare_hard", {"output": {"rate": "native"}})
    assert rate == pytest.approx(26041.6667)
    assert len(np.unique(np.round(y * 2048))) <= 4096


def test_capture_speed_then_tune_restores_length():
    x = snare(sec=1.0)
    y, rate, _, _, _ = render_array(x, SR, "sp_break_45")  # ×1.35 capture, TUNE −5 (measured ≈ ×1.331)
    assert abs(len(y) / rate - 1.0) < 0.03


def test_one_second_drum_renders_in_under_a_second():
    x = np.concatenate([snare(sec=0.4), np.zeros(int(0.6 * SR))])
    for preset, ov in [("sp_snare_hard", {}), ("sp_kick_low", {"analog": {"route": "ring", "ch": 1}})]:
        t = time.perf_counter()
        render_array(x, SR, preset, ov)
        assert time.perf_counter() - t < 1.0, preset

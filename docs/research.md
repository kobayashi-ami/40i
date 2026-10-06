# Research notes — VERIFIED / HYPOTHESIS

This file lists every acoustic claim the engine depends on, with a status. The code and UI must carry the same
label (`VER` / `HYP` tags in the UI, a `status` field in parameter metadata).

- **VERIFIED** — stated in the owner's pre-research with a named source. Phase 2 must pin each one to a citable
  primary document (manual, service manual, schematic, datasheet) before the label is final; until then the
  "source" column says what the claim rests on today.
- **HYPOTHESIS** — not settled by a primary source. Implemented as a switchable parameter with candidates, never
  hard-coded, and open to calibration against the owner's reference recordings (Phase 4).

## SP-1200 (drum path, A)

| Claim | Status | Source today | Engine consequence |
|---|---|---|---|
| 12-bit **linear** PCM | VERIFIED | owner pre-research | `adc.bits = 12`, linear quantiser, ≤ 4096 levels (tested) |
| Fixed sample rate ≈ 26.04 kHz; 26 040 Hz and 26 041.67 Hz (10 MHz ÷ 384) both quoted | VERIFIED (exact value open) | owner pre-research | default `26041.6667`, configurable |
| Pitch change is drop-sample: output rate fixed, read pointer step varies, ~no interpolation | VERIFIED | owner pre-research; schematic signal list shows a microcoded voice engine with an 8-bit *increment latch* + carry per channel [S1] | phase accumulator, floor, no interp |
| TUNE step ratio is **not** exactly 2^(n/12) | HYPOTHESIS (strong) | measured-ratio table in `pitcher` [S2] (provenance of the table not stated; repo is based on Yeh 2007 [S3]): −1 → length ×1.05653 (≈ −95 cents), −2 → ×1.12154 (≈ −199 cents) | `tune.ratio_table`: candidates `equal_tempered` / `pitcher_measured`; drop-sample modulation rate becomes 1393 Hz (−1) and 2822 Hz (−2) instead of 1462 / 2841 |
| TUNE range −8 … +7 semitone steps, no fine tune | VERIFIED (secondary) | SP-1200 FAQ / forum summaries [S4] | range −8..+7, integer steps |
| Common practice: sample at 45 rpm, TUNE down to restore pitch (33⅓→45 ≈ +5.2 st) | VERIFIED (practice) | owner pre-research; SP950 behaviour as reference only | `capture` stage + optional lock to TUNE |
| Input anti-alias filter exists and is reasonably effective | VERIFIED (secondary) / HYPOTHESIS (values) | listening test [S5]; `pitcher` models it as 4th-order elliptic, 1 dB ripple, 72 dB stop [S2] | `adc.aa`: on by default; candidates `ellip4` / `butter`; drive harmonics above 13 kHz are mostly removed **before** the ADC, so the grit is not input aliasing |
| ch1–2: SSM2044 4-pole ladder LPF with level-following decay envelope on cutoff | VERIFIED (topology) / HYPOTHESIS (values) | Isla S2400 review description | ZDF ladder model; `fc`, `env_amount`, `env_decay` HYP |
| ch3–6: fixed LPF, cutoff rising slightly with channel number | VERIFIED (topology) / HYPOTHESIS (values) | owner's manual wording via search summaries [S4]; `pitcher`: ch3–4 curve ≈ 7.5 kHz (−23 dB at 13.02 kHz, after Yeh slide 3), ch5–6 ≈ 10 kHz 7th-order Butterworth [S2] | per-channel curve table, HYP |
| ch7–8: no filter | VERIFIED | Isla S2400 review description | bypass |
| Volume envelope at 8-bit resolution, stepped decay | VERIFIED (resolution) / HYPOTHESIS (curve) | owner pre-research | optional stage, 256 steps |
| One 12-bit DAC, time-multiplexed into a sample-and-hold per channel; no reconstruction filter except the channel filters | VERIFIED (secondary) | schematic BOM / signal list: LF398 S/H, `Channel n S/H out` [S1] | ZOH per channel; on unfiltered routes the images reach the output untouched |
| Images above 13.02 kHz are present on the owner's kick and snare | OBSERVED (weak) | owner rig recording 2026-10-05, see below | default analog stage for this owner: **unfiltered** |

### Output routing (decides the analog stage)

| Claim | Status | Source today | Engine consequence |
|---|---|---|---|
| Sounds are assigned to output channels per sound (channel assignment), not fixed by pad | VERIFIED (secondary) | manual via search summaries [S4] | analog stage is chosen per sound, not per pad |
| Individual outs 1–6 are TRS: tip = unfiltered, ring = filtered; a mono plug gives the unfiltered signal and removes that channel from MIX OUT | VERIFIED (secondary) | manual / reissue docs via search summaries [S4] | `analog.route`: `filtered` / `unfiltered_tip` / `mix_out` |
| MIX OUT carries filtered ch1–6 plus ch7–8 | VERIFIED (secondary) | same | `mix_out` route applies the channel filter |
| Common practice: kicks on 3–6, snares 5–7, hats 7, sampled instruments 8; outputs 1–2 avoided for kicks | anecdote | forum summary [S4] | presets only |

## Owner rig observations (2026-10-05, iPhone video of SP-1200 + MPC60II)

Weak evidence: room mic, AAC recording with a hard low-pass at ~15.6 kHz. Usable window above the SP Nyquist is 13–15.5 kHz.

- Tempo ≈ 95.9 BPM (display ≈ 96.0), 2-bar loop, snare on 2 and 4. MPC sample (tonal, 250 Hz–5 kHz, pitch glides) enters on the bar line at 12.4 s.
- Kick and snare: energy continues smoothly through 13.02 kHz. Image/mirror level ratio (13.3–15.3 kHz vs 10.7–12.7 kHz) is −0.4 … −2.9 dB (mean ≈ −1.6) and does not change over the first 90 ms of each hit.
- Predicted ratio for the same bands: unfiltered ZOH −1.7 dB; ch3–4 curve ≈ −10.8 dB; ch5–6 curve ≈ −13.3 dB; ch1–2 dynamic filter would drift more negative as the envelope closes.
- Reading: the owner's kick and snare reach the speakers **unfiltered** (ch7–8, or individual outs on mono plugs).
- Hats (11 hits) give the same ratio (mean −1.6 dB). Three different sounds all unfiltered makes **individual outs on mono (TS) plugs** the more likely wiring; all three on ch7–8 via MIX OUT is possible only if they share channels. The engine result is the same either way: default route `tip` (unfiltered). Owner chose not to check the rear panel (2026-10-06), so this stays an inference.
- TUNE from the recording: spectral autocorrelation of averaged kick and snare spectra (2–12.5 kHz) shows no significant peak at the drop-sample modulation spacing (1393 / 1462 / 2822 / 2841 Hz; all below the 99th percentile of the lag distribution; 2.8 kHz is faintly above median for both). The room/mic recording cannot tell −1 from −2 or ET from measured ratios. Owner declined line recordings for now; the choice moves to listening (both ratio tables selectable).

### Sources

- [S1] Lytrix/EMU-SP1200 — KiCad redraw of the SP-1200 schematic, BOM and signal list (`Plan/SP1200_Signal_Definitions.md`). https://github.com/Lytrix/EMU-SP1200
- [S2] mwcm/pitcher — open-source SP-12/SP-1200 emulation (`pitcher/core.py`). https://github.com/mwcm/pitcher
- [S3] D. T. Yeh, "Physical and Behavioral Circuit Modeling of the SP-12 Sampler", ICMC 2007 (not read directly; blocked by this environment's network policy).
- [S4] SP-1200 Owner's Manual (Craig Anderton, E-mu FI 332 Rev. E) and forum/reissue pages, read only as search-result summaries; primary text still to be checked.
- [S5] llaudioll Listening Session #24. https://llaudioll.de/en/frm_ls24_en/

## MPC60 / MPC60II (sample path, B)

| Claim | Status | Source today | Engine consequence |
|---|---|---|---|
| Fixed 40 kHz, response 20 Hz–18 kHz | VERIFIED | owner pre-research | resample to 40 000, band limit ~18 kHz |
| ADC PCM77P, DAC Burr-Brown PCM54HP (16-bit converters) | VERIFIED | owner pre-research | 16-bit quantise around the codec |
| Memory format is a "special non-linear 12-bit" (lower noise than linear 12-bit), 16-bit converters, 40 kHz | VERIFIED (existence) | owner pre-research; Sound On Sound MPC60 II review (1991) and Music Technology (1988) via search summaries | NL-12 encode/decode stage |
| Exact non-linear 12-bit curve | HYPOTHESIS | — | ≥ 3 candidates: piecewise-linear companding, block-float gain ranging, μ-law-like |
| High-pass pre-emphasis in the record path | HYPOTHESIS | owner pre-research ("described as") | pre-emph / de-emph pair, switchable, values HYP |
| Tune range −12 … +6 semitones | HYPOTHESIS (stated once) | owner pre-research | parameter range, configurable |
| Pitch-shift interpolation method | HYPOTHESIS | — | `none` / `linear` switch |
| 60 and 60II acoustically ~identical | VERIFIED (claim) | owner pre-research | single model |

## Engine mapping (Phase 2)

Every row above is a parameter in `engine/params.py` (`python -m engine params` prints them with VER/HYP).
Defaults chosen where the research is open:

| Parameter | Default | Why |
|---|---|---|
| `sp.adc.aa` / `aa_fc` | `ellip4` @ 12.5 kHz | the `pitcher` model; a 4th-order filter still lets 13–16 kHz partly alias |
| `sp.tune.table` | `measured` | owner approved (design.md §12); ET selectable |
| `sp.analog.route` | `tip` (unfiltered) | owner rig observation (kick, snare, hats all unfiltered) |
| `sp.analog.fixed_curve` | `pitcher` | ch3–4 ≈ 7.5 kHz curve, ch5–6 ≈ 10 kHz Butterworth-7 |
| `sp.analog` ch1–2 | ZDF 4-pole ladder, cutoff ×2^(4·env·level) | behavioural SSM2044 stand-in, all values HYP |
| `mpc.codec.curve` | `pwl` (A-law-like, 1+3+8 bits) | the three candidates differ most on quiet material |
| `mpc.input.emph` | on, +6 dB shelf @ 3.2 kHz | reported, values unknown |

The analog domain runs at 4 × 26 041.67 Hz so the hold's images and the output filters interact before the export
resampler, which is the only place images above the export Nyquist are removed (`output.src = keep_zoh`).

## Calibration hooks (Phase 4)

Every HYPOTHESIS parameter carries `{status, candidates | range, default, note}` in its metadata so a calibration
script can sweep it against a reference recording (spectral difference, envelope difference) and record the
best-fit value with provenance.

## Future: workers on other machines

Not enabled in Phase 1. When needed, Postgres (`pg_hba.conf`) and Redis (`bind` + `protected-mode`, ACL user)
should accept connections only from the tailnet range `100.64.0.0/10` — steps to be written here in Phase 1.

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
| Pitch change is drop-sample: output rate fixed, read pointer step varies, ~no interpolation | VERIFIED | owner pre-research | phase accumulator, step `2^(n/12)`, floor, no interp |
| TUNE range | HYPOTHESIS | — | parameter with configurable min/max |
| Common practice: sample at 45 rpm, TUNE down to restore pitch (33⅓→45 ≈ +5.2 st) | VERIFIED (practice) | owner pre-research; SP950 behaviour as reference only | `capture` stage + optional lock to TUNE |
| Input anti-alias filter: cutoff, order | HYPOTHESIS | — | `adc.aa_fc`, `adc.aa_order`, on/off |
| ch1–2: SSM2044 4-pole ladder LPF with level-following decay envelope on cutoff | VERIFIED (topology) / HYPOTHESIS (values) | Isla S2400 review description | ZDF ladder model; `fc`, `env_amount`, `env_decay` HYP |
| ch3–6: fixed LPF, cutoff rising slightly with channel number | VERIFIED (topology) / HYPOTHESIS (values) | Isla S2400 review description | per-channel `fc` table, HYP |
| ch7–8: no filter | VERIFIED | Isla S2400 review description | bypass |
| Volume envelope at 8-bit resolution, stepped decay | VERIFIED (resolution) / HYPOTHESIS (curve) | owner pre-research | optional stage, 256 steps |
| DAC output without strong reconstruction (imaging retained) | HYPOTHESIS (degree) | owner pre-research | ZOH; reconstruction filter off/weak, switchable |

## MPC60 / MPC60II (sample path, B)

| Claim | Status | Source today | Engine consequence |
|---|---|---|---|
| Fixed 40 kHz, response 20 Hz–18 kHz | VERIFIED | owner pre-research | resample to 40 000, band limit ~18 kHz |
| ADC PCM77P, DAC Burr-Brown PCM54HP (16-bit converters) | VERIFIED | owner pre-research | 16-bit quantise around the codec |
| Memory format is a "special non-linear 12-bit" (lower noise than linear 12-bit) | VERIFIED (existence) | owner pre-research | NL-12 encode/decode stage |
| Exact non-linear 12-bit curve | HYPOTHESIS | — | ≥ 3 candidates: piecewise-linear companding, block-float gain ranging, μ-law-like |
| High-pass pre-emphasis in the record path | HYPOTHESIS | owner pre-research ("described as") | pre-emph / de-emph pair, switchable, values HYP |
| Tune range −12 … +6 semitones | HYPOTHESIS (stated once) | owner pre-research | parameter range, configurable |
| Pitch-shift interpolation method | HYPOTHESIS | — | `none` / `linear` switch |
| 60 and 60II acoustically ~identical | VERIFIED (claim) | owner pre-research | single model |

## Calibration hooks (Phase 4)

Every HYPOTHESIS parameter carries `{status, candidates | range, default, note}` in its metadata so a calibration
script can sweep it against a reference recording (spectral difference, envelope difference) and record the
best-fit value with provenance.

## Future: workers on other machines

Not enabled in Phase 1. When needed, Postgres (`pg_hba.conf`) and Redis (`bind` + `protected-mode`, ACL user)
should accept connections only from the tailnet range `100.64.0.0/10` — steps to be written here in Phase 1.

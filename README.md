# 1260（仮称）

SP-1200 drums × MPC60II samples — an offline timbre engine. Drop a WAV in, get it back rendered through modelled
hardware stages (12-bit linear @ 26.04 kHz with drop-sample TUNE for drums; non-linear 12-bit @ 40 kHz for samples).

Status: **Phase 1 — skeleton** (Postgres/Redis, Alembic, FastAPI + SSE, dummy-stage workers, launchd, tailscale serve).
See `CLAUDE.md` for the phase gates and rules, `design.md` for the UI rules, `docs/research.md` for what is verified
vs. hypothesis, and `docs/runbook.md` to run it on the Mac.

```
make setup && make infra && make migrate && make dev   # http://127.0.0.1:8260/
make test
```

| | |
|---|---|
| ![library](design/mockups/01_library.png) | ![chain](design/mockups/02_chain.png) |
| ![jobs](design/mockups/03_jobs.png) | ![a/b](design/mockups/04_ab.png) |
| ![mobile](design/mockups/05_mobile_progress.png) | ![listen](design/mockups/05b_mobile_listen.png) |
| ![components](design/mockups/06_components.png) | |

Fonts in `design/fonts/` are under the SIL Open Font License (licence files alongside).

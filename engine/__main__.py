"""Command line:

python -m engine render in.wav --preset sp_snare_hard --tune -2
python -m engine render in.wav --preset sp_kick_low --set analog.route=ring --set analog.ch=1 --rate native
python -m engine presets
python -m engine params            # every parameter with its VER / HYP status
"""

import argparse
import json
import sys
from pathlib import Path

from engine.params import PRESETS, SCHEMA, set_dotted
from engine.render import render_file


def parse_value(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(v.lower(), v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render a WAV through a preset")
    r.add_argument("input", type=Path)
    r.add_argument("--preset", required=True)
    r.add_argument("--tune", type=int, help="TUNE in semitone steps (shortcut for --set tune.st=N)")
    r.add_argument("--rate", help="48000 | 44100 | native")
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override, e.g. adc.aa=off")
    r.add_argument("--out-dir", type=Path)
    r.add_argument("--no-attach", action="store_true", help="skip spectrogram PNG and params JSON")
    sub.add_parser("presets", help="list presets")
    sub.add_parser("params", help="list parameters with VER/HYP status")
    a = ap.parse_args(argv)

    if a.cmd == "presets":
        for name, p in sorted(PRESETS.items()):
            print(f"{name:16s} {p['path']:4s} {json.dumps(p['params'], ensure_ascii=False)}")
        return 0
    if a.cmd == "params":
        for key, spec in SCHEMA.items():
            rng = spec.candidates if spec.candidates else (spec.lo, spec.hi)
            print(f"{spec.status}  {key:24s} {rng!s:40s} {spec.note}")
        return 0

    overrides: dict = {}
    for kv in a.set:
        if "=" not in kv:
            ap.error(f"--set expects KEY=VALUE, got {kv!r}")
        k, v = kv.split("=", 1)
        set_dotted(overrides, k, parse_value(v))
    if a.tune is not None:
        set_dotted(overrides, "tune.st", a.tune)
    if a.rate:
        set_dotted(overrides, "output.rate", parse_value(a.rate))
    res = render_file(a.input, a.preset, overrides, a.out_dir, attach=not a.no_attach)
    for kind, f in res["files"].items():
        print(f"{kind:4s} {f}")
    print(f"sha256 {res['output']['sha256']}  rate {res['output']['rate']:.2f}  info {json.dumps(res['info'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

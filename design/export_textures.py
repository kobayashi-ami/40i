"""Export the hairline-metal tiles used by the web UI (design.md §4, §11).

    uv run --group design python design/export_textures.py

Writes web/public/tex/metal-<tone>.png: 256×256, horizontally streaked noise on the token colour, tileable
horizontally (streaks are periodic) and vertically (rows are independent).
"""

from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "tex"
TONES = {"bg0": "#08090B", "bg1": "#0E1114", "bg2": "#14181C", "bg3": "#1B2025", "bg4": "#242A30"}
AMP = {"bg0": 1.0, "bg1": 1.8, "bg2": 2.4, "bg3": 2.4, "bg4": 3.0}


def tile(base: str, amp: float, size: int = 256, seed: int = 1260) -> Image.Image:
    rng = np.random.default_rng(seed)
    rgb = np.array([int(base[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)
    # periodic streaks: a few random coarse knots per row, interpolated with wrap-around
    knots = 6
    k = rng.normal(0, 1, (size, knots)).astype(np.float32)
    x = np.arange(size) / size * knots
    i0 = np.floor(x).astype(int) % knots
    i1 = (i0 + 1) % knots
    t = (x - np.floor(x))[None, :]
    streak = k[:, i0] * (1 - t) + k[:, i1] * t
    fine = rng.normal(0, 0.45, (size, size)).astype(np.float32)
    arr = rgb[None, None, :] + ((streak + fine) * amp)[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, base in TONES.items():
        tile(base, AMP[name]).save(OUT / f"metal-{name}.png", optimize=True)
        print("wrote", OUT / f"metal-{name}.png")

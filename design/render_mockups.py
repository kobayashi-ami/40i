"""1260 — Phase 0 screen mockups.

Renders the five UI mockups (+ a component sheet) as PNG into design/mockups/.
Everything is drawn procedurally with Pillow + numpy so the look can be
iterated in code before any frontend exists.

    python design/render_mockups.py                 # all screens, 1x
    python design/render_mockups.py chain jobs      # subset
    python design/render_mockups.py --hires mobile  # also write @2x (gitignored)

Waveforms and spectrograms are drawn from synthetic signals run through a
*mock* of the drum path (crude, illustrative only — not the engine).
"""

from __future__ import annotations

import hashlib
import math
import sys
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
OUT_DIR = HERE / "mockups"
SCALE = 2  # draw at 2x, downsample for the 1x deliverable
HIRES = False  # --hires: also keep the 2x render


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------


def hx(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


T = {
    # black iron / gunmetal ramp
    "bg0": hx("#08090B"),
    "bg1": hx("#0E1114"),
    "bg2": hx("#14181C"),
    "bg3": hx("#1B2025"),
    "bg4": hx("#242A30"),
    "line": hx("#2A3137"),
    "line2": hx("#394149"),
    "hl": hx("#2C333A"),  # engraved highlight
    "metal": hx("#4C555F"),  # thumbs, screws
    "metal_hi": hx("#6B7580"),
    # text
    "tx_hi": hx("#C5CCD3"),
    "tx_md": hx("#88919B"),
    "tx_lo": hx("#58616B"),
    "tx_xlo": hx("#394149"),
    # the one accent: cold, low-saturation blue
    "ac": hx("#6C97BE"),
    "ac_hi": hx("#A8C8E4"),
    "ac_md": hx("#3E5F7E"),
    "ac_lo": hx("#1D3044"),
    "ac_xlo": hx("#111B25"),
    "seg_off": hx("#131B22"),
    # failure = white heat + hazard hatch (no second hue)
    "fail": hx("#E6EBF0"),
    "fail_bg": hx("#23282D"),
}


@cache
def F(kind: str, size: float) -> ImageFont.FreeTypeFont:
    files = {
        "stencil": "SairaStencilOne-Regular.ttf",
        "cond": "BarlowCondensed-SemiBold.ttf",
        "cond_md": "BarlowCondensed-Medium.ttf",
        "cond_rg": "BarlowCondensed-Regular.ttf",
        "mono": "IBMPlexMono-Regular.ttf",
        "mono_md": "IBMPlexMono-Medium.ttf",
        "lcd": "ShareTechMono-Regular.ttf",
    }
    if kind == "jp":
        return ImageFont.truetype(jp_font_path(), int(size * SCALE))
    return ImageFont.truetype(str(FONT_DIR / files[kind]), int(size * SCALE))


def jp_font_path() -> str:
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return str(FONT_DIR / "BarlowCondensed-Medium.ttf")  # JP labels degrade to tofu-free blank


# --------------------------------------------------------------------------
# canvas + primitives
# --------------------------------------------------------------------------


class Canvas:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w * SCALE, h * SCALE), T["bg0"])
        self.d = ImageDraw.Draw(self.img)
        self.glow = Image.new("RGB", self.img.size, (0, 0, 0))
        self.gd = ImageDraw.Draw(self.glow)

    # coordinate helpers -------------------------------------------------
    @staticmethod
    def s(v: float) -> int:
        return int(round(v * SCALE))

    def box(self, x, y, w, h):
        return [self.s(x), self.s(y), self.s(x + w) - 1, self.s(y + h) - 1]

    def pts(self, pts):
        return [(self.s(px), self.s(py)) for px, py in pts]

    # surfaces -----------------------------------------------------------
    def rect(self, x, y, w, h, fill=None, outline=None, width=1):
        if self.s(w) < 1 or self.s(h) < 1:
            return
        self.d.rectangle(self.box(x, y, w, h), fill=fill, outline=outline, width=self.s(width) if outline else 0)

    def line(self, x0, y0, x1, y1, fill, width=1):
        self.d.line(self.pts([(x0, y0), (x1, y1)]), fill=fill, width=max(1, self.s(width)))

    def hline_engraved(self, x, y, w):
        self.line(x, y, x + w, y, T["bg0"])
        self.line(x, y + 1, x + w, y + 1, T["hl"])

    def vline_engraved(self, x, y, h):
        self.line(x, y, x, y + h, T["bg0"])
        self.line(x + 1, y, x + 1, y + h, T["hl"])

    @staticmethod
    def chamfer_pts(x, y, w, h, c):
        # house signature: TL and BR corners cut at 45deg, TR and BL square
        return [(x + c, y), (x + w, y), (x + w, y + h - c), (x + w - c, y + h), (x, y + h), (x, y + c)]

    def chamfer(self, x, y, w, h, c=8, fill=None, outline=None, width=1):
        p = self.pts(self.chamfer_pts(x, y, w, h, c))
        self.d.polygon(p, fill=fill, outline=outline, width=self.s(width) if outline else 0)

    def metal(self, x, y, w, h, base, amp=2.6, c=0, seed=None, shade=1.6):
        """Brushed (hairline) metal fill, optionally chamfered."""
        W, H = self.s(w), self.s(h)
        if W <= 0 or H <= 0:
            return
        rng = np.random.default_rng(seed if seed is not None else int(x * 7919 + y * 104729 + w * 31 + h) & 0xFFFFFFFF)
        cols = max(3, W // 48)
        streak = rng.normal(0, 1, (H, cols)).astype(np.float32)
        streak = np.asarray(Image.fromarray(streak, mode="F").resize((W, H), Image.BILINEAR))
        fine = rng.normal(0, 0.45, (H, W)).astype(np.float32)
        n = streak + fine
        grad = np.linspace(shade, -shade, H, dtype=np.float32)[:, None]
        arr = np.asarray(base, np.float32)[None, None, :] + (n * amp + grad)[..., None]
        tile = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        if c:
            md.polygon([(px * SCALE, py * SCALE) for px, py in self.chamfer_pts(0, 0, w, h, c)], fill=255)
        else:
            md.rectangle([0, 0, W, H], fill=255)
        self.img.paste(tile, (self.s(x), self.s(y)), mask)

    def panel(self, x, y, w, h, title=None, idx=None, tone="bg2", c=10, screws=True, amp=2.4):
        self.metal(x, y, w, h, T[tone], amp=amp, c=c)
        p = self.chamfer_pts(x, y, w, h, c)
        # bevel: light on top/left edges, dark outline
        self.d.polygon(self.pts(p), outline=T["bg0"], width=self.s(1))
        self.line(x + c, y + 1, x + w - 1, y + 1, T["line2"])
        self.line(x + 1, y + c, x + 1, y + h - 1, T["line"])
        self.line(x + 1, y + c, x + c, y + 1, T["line2"])
        if screws:
            self.screw(x + w - 9, y + 9)
            self.screw(x + 9, y + h - 9)
        if title:
            tx = x + 16 + (c if c > 8 else 0) * 0.4
            if idx:
                wi = self.text(tx, y + 23, idx, F("mono", 10), T["tx_lo"])
                tx += wi + 8
            self.etext(tx, y + 23, title, F("cond", 14), T["tx_md"], tracking=2.6)
            self.hline_engraved(x + 12, y + 33, w - 24)

    def hatch(self, x, y, w, h, color, spacing=6, width=1, mask_pts=None):
        W, H = self.s(w), self.s(h)
        layer = Image.new("L", (W, H), 0)
        ld = ImageDraw.Draw(layer)
        sp = self.s(spacing)
        for i in range(-H, W + H, sp):
            ld.line([(i, H), (i + H, 0)], fill=255, width=self.s(width))
        if mask_pts is not None:
            m = Image.new("L", (W, H), 0)
            ImageDraw.Draw(m).polygon([((px - x) * SCALE, (py - y) * SCALE) for px, py in mask_pts], fill=255)
            layer = ImageChops.multiply(layer, m)
        self.img.paste(Image.new("RGB", (W, H), color), (self.s(x), self.s(y)), layer)

    def blend_rect(self, x, y, w, h, color, alpha):
        region = self.img.crop(tuple(self.box(x, y, w, h)[:2]) + (self.s(x + w), self.s(y + h)))
        over = Image.new("RGB", region.size, color)
        self.img.paste(Image.blend(region, over, alpha), (self.s(x), self.s(y)))

    # hardware -----------------------------------------------------------
    def screw(self, cx, cy, r=3.6):
        rng = np.random.default_rng(int(cx * 31 + cy * 17))
        self.d.ellipse(self.box(cx - r - 0.8, cy - r - 0.8, 2 * r + 1.6, 2 * r + 1.6), fill=T["bg0"])
        self.d.ellipse(self.box(cx - r, cy - r, 2 * r, 2 * r), fill=T["metal"])
        self.d.ellipse(self.box(cx - r + 1.0, cy - r + 1.4, 2 * r - 2, 2 * r - 2), fill=hx("#3F4750"))
        a = rng.uniform(0, math.pi)
        for k in (0, math.pi / 2):  # cross-head
            dx, dy = math.cos(a + k) * (r - 0.9), math.sin(a + k) * (r - 0.9)
            self.line(cx - dx, cy - dy, cx + dx, cy + dy, T["bg0"], width=0.9)

    def led(self, cx, cy, on=True, r=3.2, color=None):
        col = color or T["ac_hi"]
        self.d.ellipse(self.box(cx - r - 1, cy - r - 1, 2 * r + 2, 2 * r + 2), fill=T["bg0"])
        if on:
            self.d.ellipse(self.box(cx - r, cy - r, 2 * r, 2 * r), fill=col)
            self.gd.ellipse(self.box(cx - r - 1, cy - r - 1, 2 * r + 2, 2 * r + 2), fill=col)
            self.d.ellipse(self.box(cx - r * 0.45, cy - r * 0.55, r * 0.6, r * 0.5), fill=hx("#E2EEF8"))
        else:
            self.d.ellipse(self.box(cx - r, cy - r, 2 * r, 2 * r), fill=hx("#192027"))

    def chain_v(self, cx, y0, y1, color=None):
        col = color or T["line2"]
        y, k = y0, 0
        while y + 12 <= y1 + 0.1:
            if k % 2 == 0:
                self.d.rounded_rectangle(self.box(cx - 4, y, 8, 13), radius=self.s(4), outline=col, width=self.s(1.6))
            else:
                self.rect(cx - 1.2, y - 1, 2.4, 15, fill=col)
            y += 9
            k += 1

    def chain_h(self, x0, x1, cy, color=None):
        col = color or T["line2"]
        x, k = x0, 0
        while x + 12 <= x1 + 0.1:
            if k % 2 == 0:
                self.d.rounded_rectangle(self.box(x, cy - 4, 13, 8), radius=self.s(4), outline=col, width=self.s(1.6))
            else:
                self.rect(x - 1, cy - 1.2, 15, 2.4, fill=col)
            x += 9
            k += 1

    # text ---------------------------------------------------------------
    def text(self, x, y, s, font, fill, anchor="ls", tracking=0.0, glow=False):
        """Draw text; returns logical width. tracking is in logical px."""
        if not tracking:
            self.d.text((self.s(x), self.s(y)), s, font=font, fill=fill, anchor=anchor)
            if glow:
                self.gd.text((self.s(x), self.s(y)), s, font=font, fill=fill, anchor=anchor)
            return font.getlength(s) / SCALE
        tr = tracking * SCALE
        widths = [font.getlength(ch) for ch in s]
        total = sum(widths) + tr * (len(s) - 1)
        h, v = anchor[0], anchor[1]
        sx = self.s(x) - (total / 2 if h == "m" else total if h == "r" else 0)
        for ch, cw in zip(s, widths, strict=True):
            self.d.text((sx, self.s(y)), ch, font=font, fill=fill, anchor="l" + v)
            if glow:
                self.gd.text((sx, self.s(y)), ch, font=font, fill=fill, anchor="l" + v)
            sx += cw + tr
        return total / SCALE

    def etext(self, x, y, s, font, fill, anchor="ls", tracking=0.0):
        """Engraved: faint highlight one px below, then the text."""
        self.text(x, y + 1, s, font, T["hl"], anchor, tracking)
        return self.text(x, y, s, font, fill, anchor, tracking)

    def label(self, x, y, s, size=11, fill=None, anchor="ls", tracking=1.6, kind="cond_md"):
        return self.text(x, y, s.upper(), F(kind, size), fill or T["tx_md"], anchor, tracking)

    def mono(self, x, y, s, size=11, fill=None, anchor="ls", kind="mono"):
        return self.text(x, y, s, F(kind, size), fill or T["tx_hi"], anchor)

    # 7-segment ----------------------------------------------------------
    SEGMAP = {
        "0": "abcdef",
        "1": "bc",
        "2": "abged",
        "3": "abgcd",
        "4": "fgbc",
        "5": "afgcd",
        "6": "afgedc",
        "7": "abc",
        "8": "abcdefg",
        "9": "abcdfg",
        "-": "g",
        " ": "",
        "A": "abcefg",
        "b": "cdefg",
        "C": "adef",
        "c": "deg",
        "d": "bcdeg",
        "E": "adefg",
        "F": "aefg",
        "H": "bcefg",
        "L": "def",
        "P": "abefg",
        "r": "eg",
        "t": "defg",
        "U": "bcdef",
        "n": "ceg",
        "o": "cdeg",
        "u": "cde",
        "q": "abcfg",
        "Y": "bcdfg",
        "S": "afgcd",
        "+": "g",
    }

    def seg7(self, x, y, h, text, on=None, off=None, glow=True, skew=0.09, gap=None):
        """Draw a 7-seg readout with ghost segments. (x, y) = top-left. Returns width."""
        on = on or T["ac_hi"]
        off = off or T["seg_off"]
        w = h * 0.52
        t = h * 0.115
        g = gap if gap is not None else h * 0.2
        cells = []
        for ch in text:
            if ch == "." and cells:
                cells[-1][1] = True
            else:
                cells.append([ch, False])
        cx = x
        for ch, dp in cells:
            self._digit(cx, y, w, h, t, ch, dp, on, off, glow, skew)
            cx += w + g + (t * 2.4 if dp else 0)
        return cx - g - x

    def _digit(self, x, y, w, h, t, ch, dp, on, off, glow, skew):
        hh = h / 2
        e = t * 0.5
        segs = {
            "a": [(x + e, y), (x + w - e, y), (x + w - t, y + t), (x + t, y + t)],
            "d": [(x + t, y + h - t), (x + w - t, y + h - t), (x + w - e, y + h), (x + e, y + h)],
            "g": [
                (x + e, y + hh),
                (x + t, y + hh - e),
                (x + w - t, y + hh - e),
                (x + w - e, y + hh),
                (x + w - t, y + hh + e),
                (x + t, y + hh + e),
            ],
            "f": [(x, y + e), (x + t, y + t), (x + t, y + hh - e), (x, y + hh - e * 0.2)],
            "e": [(x, y + hh + e * 0.2), (x + t, y + hh + e), (x + t, y + h - t), (x, y + h - e)],
            "b": [(x + w, y + e), (x + w, y + hh - e * 0.2), (x + w - t, y + hh - e), (x + w - t, y + t)],
            "c": [(x + w, y + hh + e * 0.2), (x + w, y + h - e), (x + w - t, y + h - t), (x + w - t, y + hh + e)],
        }
        lit = self.SEGMAP.get(ch, "")
        if ch == "+":  # plus = g + short vertical
            segs["v"] = [
                (x + w / 2 - e, y + hh - h * 0.22),
                (x + w / 2 + e, y + hh - h * 0.22),
                (x + w / 2 + e, y + hh + h * 0.22),
                (x + w / 2 - e, y + hh + h * 0.22),
            ]
            lit = "gv"
        for name, poly in segs.items():
            if name == "v" and ch != "+":
                continue
            sk = [(px + (y + h - py) * skew, py) for px, py in poly]
            # inset slightly so segments read as separate
            is_on = name in lit
            self.d.polygon(self.pts(sk), fill=on if is_on else off)
            if is_on and glow:
                self.gd.polygon(self.pts(sk), fill=on)
        if dp:
            r = t * 0.62
            px = x + w + t * 1.0 + r
            self.d.ellipse(self.box(px - r, y + h - 2 * r, 2 * r, 2 * r), fill=on)
            if glow:
                self.gd.ellipse(self.box(px - r, y + h - 2 * r, 2 * r, 2 * r), fill=on)

    def lcd_window(self, x, y, w, h):
        self.rect(x - 1, y - 1, w + 2, h + 2, fill=T["bg0"])
        self.rect(x, y, w, h, fill=hx("#070B0F"), outline=hx("#1A232C"))
        self.line(x + 1, y + 1, x + w - 2, y + 1, hx("#03050A"))

    # controls -----------------------------------------------------------
    def tag(self, x, y, kind):
        """VER = sourced (accent outline); HYP = hypothesis (grey, hatched)."""
        w, h = 22, 11
        if kind == "HYP":
            self.rect(x, y, w, h, fill=T["bg1"])
            self.hatch(x, y, w, h, hx("#20262C"), spacing=3)
            self.rect(x, y, w, h, outline=T["tx_lo"])
            self.text(x + w / 2, y + h / 2 + 0.5, "HYP", F("mono_md", 7.5), T["tx_md"], anchor="mm")
        else:
            self.rect(x, y, w, h, fill=T["ac_xlo"], outline=T["ac_md"])
            self.text(x + w / 2, y + h / 2 + 0.5, "VER", F("mono_md", 7.5), T["ac"], anchor="mm")
        return w

    def slider(self, x, y, w, label, value, pos, bipolar=False, tag=None, dim=False, jp=None):
        lab_col = T["tx_lo"] if dim else T["tx_md"]
        lw = self.label(x, y + 9, label, 11, lab_col, tracking=1.4)
        tx = x + lw + 5
        if jp:
            tx += self.text(tx, y + 9, jp, F("jp", 9), T["tx_lo"]) + 5
        if tag:
            self.tag(tx, y + 0.5, tag)
        self.mono(x + w, y + 9.5, value, 11.5, T["tx_lo"] if dim else T["tx_hi"], anchor="rs")
        ty = y + 17
        self.rect(x, ty, w, 5, fill=T["bg0"], outline=hx("#05070A"))
        for i in range(9):
            tx_ = x + 2 + (w - 4) * i / 8
            self.line(tx_, ty + 8, tx_, ty + (11 if i in (0, 4, 8) else 9.5), T["tx_xlo"])
        px = x + 2 + (w - 4) * pos
        fill_col = T["ac_lo"] if dim else T["ac_md"]
        if bipolar:
            cx = x + w / 2
            self.rect(min(cx, px), ty + 1, abs(px - cx), 3, fill=fill_col)
        else:
            self.rect(x + 1, ty + 1, px - x - 1, 3, fill=fill_col)
        # thumb: machined cap
        self.rect(px - 4.5, ty - 5, 9, 15, fill=T["bg0"])
        self.rect(px - 4, ty - 4.5, 8, 14, fill=T["tx_lo"] if dim else T["metal"])
        self.line(px - 3.5, ty - 4, px + 3.5, ty - 4, T["metal_hi"] if not dim else T["tx_lo"])
        self.line(px, ty - 2.5, px, ty + 7.5, T["bg0"])

    def seg(self, x, y, w, h, items, active, size=12, dim=False, mono=False):
        n = len(items)
        cw = w / n
        self.rect(x - 1, y - 1, w + 2, h + 2, fill=T["bg0"])
        for i, it in enumerate(items):
            cx = x + i * cw
            act = i == active if not isinstance(active, (set, list)) else i in active
            if act:
                self.rect(cx, y, cw - 1, h, fill=T["ac_lo"])
                self.rect(cx, y, cw - 1, 2, fill=T["ac"])
                col = T["ac_hi"]
            else:
                self.rect(cx, y, cw - 1, h, fill=T["bg1"])
                self.line(cx, y, cx + cw - 2, y, T["bg3"])
                col = T["tx_lo"] if dim else T["tx_md"]
            font = F("mono_md", size - 1) if mono else F("cond", size)
            self.text(cx + cw / 2, y + h / 2 + 1, it, font, col, anchor="mm", tracking=0 if mono else 1.2)

    def button(self, x, y, w, h, label, state="normal", size=13):
        c = 6
        if state == "primary":
            self.chamfer(x - 1, y - 1, w + 2, h + 2, c, fill=T["bg0"])
            self.chamfer(x, y, w, h, c, fill=T["ac_lo"], outline=T["ac"])
            self.line(x + c, y + 2, x + w - 2, y + 2, T["ac_md"])
            col = T["ac_hi"]
        elif state == "hover":
            self.chamfer(x, y, w, h, c, fill=T["bg4"], outline=T["ac_md"])
            col = T["tx_hi"]
        elif state == "running":
            self.chamfer(x, y, w, h, c, fill=T["ac_xlo"], outline=T["ac_md"])
            self.hatch(x, y, w, h, T["ac_lo"], spacing=8, width=3, mask_pts=self.chamfer_pts(x, y, w, h, c))
            col = T["ac"]
        elif state == "failed":
            self.chamfer(x, y, w, h, c, fill=T["fail_bg"])
            self.hatch(x, y, w, h, hx("#30363C"), spacing=6, width=2, mask_pts=self.chamfer_pts(x, y, w, h, c))
            self.chamfer(x, y, w, h, c, outline=T["fail"])
            col = T["fail"]
        elif state == "disabled":
            self.chamfer(x, y, w, h, c, fill=T["bg2"], outline=T["line"])
            col = T["tx_xlo"]
        else:
            self.chamfer(x - 1, y - 1, w + 2, h + 2, c, fill=T["bg0"])
            self.chamfer(x, y, w, h, c, fill=T["bg3"], outline=T["line2"])
            self.line(x + c, y + 1.5, x + w - 2, y + 1.5, T["bg4"])
            col = T["tx_hi"]
        self.text(x + w / 2, y + h / 2 + 1, label.upper(), F("cond", size), col, anchor="mm", tracking=2)

    def toggle(self, x, y, on):
        """Small rocker: 22x12."""
        self.rect(x - 1, y - 1, 24, 14, fill=T["bg0"])
        self.rect(x, y, 22, 12, fill=T["bg1"])
        if on:
            self.rect(x + 11, y + 1, 10, 10, fill=T["metal"])
            self.line(x + 11, y + 1, x + 20, y + 1, T["metal_hi"])
            self.rect(x + 2, y + 5, 7, 2, fill=T["ac"])
        else:
            self.rect(x + 1, y + 1, 10, 10, fill=hx("#383F47"))
            self.rect(x + 13, y + 5, 7, 2, fill=T["tx_xlo"])

    def seg_progress(self, x, y, w, h, n, done, partial=0.0, failed=None, dim=False):
        """Stage progress: n segments; `done` complete, then one partial."""
        gap = 2
        sw = (w - gap * (n - 1)) / n
        for i in range(n):
            sx = x + i * (sw + gap)
            if failed is not None and i == failed:
                self.rect(sx, y, sw, h, fill=T["fail_bg"])
                self.hatch(sx, y, sw, h, T["fail"], spacing=4, width=1)
                self.rect(sx, y, sw, h, outline=T["fail"])
            elif i < done:
                self.rect(sx, y, sw, h, fill=T["ac_md"] if dim else T["ac"])
            elif i == done and partial > 0 and failed is None:
                self.rect(sx, y, sw, h, fill=T["bg0"])
                self.rect(sx, y, sw * partial, h, fill=T["ac_hi"])
                self.gd.rectangle(self.box(sx, y, sw * partial, h), fill=T["ac"])
            else:
                self.rect(sx, y, sw, h, fill=T["bg0"], outline=hx("#1C2228"))

    # signal drawings ----------------------------------------------------
    def waveform(self, x, y, w, h, sig, color, grid=True, center=True, gain=1.0):
        if grid:
            for i in range(1, 4):
                self.line(x, y + h * i / 4, x + w, y + h * i / 4, hx("#151A1F"))
        W = self.s(w)
        n = len(sig)
        edges = np.linspace(0, n, W + 1).astype(int)
        mid = self.s(y + h / 2)
        half = self.s(h / 2) - 1
        for i in range(W):
            seg_ = sig[edges[i] : max(edges[i + 1], edges[i] + 1)]
            lo, hi = float(seg_.min()) * gain, float(seg_.max()) * gain
            lo, hi = max(lo, -1), min(hi, 1)
            self.d.line([(self.s(x) + i, mid - int(hi * half)), (self.s(x) + i, mid - int(lo * half))], fill=color)
        if center:
            self.line(x, y + h / 2, x + w, y + h / 2, hx("#232A31"))

    def spectrogram(self, x, y, w, h, sig, sr, fmax=24000):
        img = spec_image(sig, sr, self.s(w), self.s(h), fmax)
        self.img.paste(img, (self.s(x), self.s(y)))

    # finish -------------------------------------------------------------
    def save(self, name):
        glow = self.glow.filter(ImageFilter.GaussianBlur(5 * SCALE))
        glow = Image.eval(glow, lambda v: int(v * 0.32))
        out = ImageChops.screen(self.img, glow)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        if HIRES:
            out.save(OUT_DIR / f"{name}@2x.png", optimize=True)
        out.resize((self.w, self.h), Image.LANCZOS).save(OUT_DIR / f"{name}.png", optimize=True)
        print("wrote", OUT_DIR / f"{name}.png")


# --------------------------------------------------------------------------
# synthetic audio + mock processing (illustration only)
# --------------------------------------------------------------------------

SR = 48000


def _t(sec):
    return np.arange(int(sec * SR)) / SR


def s_kick(seed=1):
    t = _t(0.6)
    f = 44 + 120 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / SR
    click = np.random.default_rng(seed).normal(0, 1, len(t)) * np.exp(-t * 400) * 0.3
    return (np.sin(ph) * np.exp(-t * 6.0) + click) * 0.9


def _onepole(x, a):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = a * acc + (1 - a) * v
        y[i] = acc
    return y * 2.2


def s_snare(seed=2):
    t = _t(0.42)
    rng = np.random.default_rng(seed)
    nz = rng.normal(0, 1, len(t))
    for _ in range(2):  # darken the noise a little (two one-pole passes)
        nz = _onepole(nz, 0.55)
    body = np.sin(2 * np.pi * 186 * t) * np.exp(-t * 26)
    return np.tanh((nz * 0.35 * np.exp(-t * 11) + body * 0.7) * 1.4) * 0.85


def s_hat(seed=3, dec=60):
    t = _t(0.12 if dec > 30 else 0.6)
    nz = np.random.default_rng(seed).normal(0, 1, len(t))
    nz = np.diff(nz, prepend=0)
    return nz * np.exp(-t * dec) * 0.22


def s_rhodes(sec=5.2, seed=4):
    t = _t(sec)
    out = np.zeros_like(t)
    chords = [(220, 261.6, 329.6, 392.0), (196, 246.9, 293.7, 349.2)]
    for k, st in enumerate(np.arange(0, sec, 1.3)):
        ch = chords[k % 2]
        idx = t >= st
        tt = t[idx] - st
        env = np.exp(-tt * 1.8)
        for f in ch:
            out[idx] += np.sin(2 * np.pi * f * tt + 0.8 * np.sin(2 * np.pi * f * 2 * tt) * np.exp(-tt * 6)) * env * 0.14
    return out + np.random.default_rng(seed).normal(0, 0.004, len(t))


def s_beat(sec=2.6):
    out = np.zeros(int(sec * SR))

    def put(sig, at, g=1.0):
        i = int(at * SR)
        n = min(len(sig), len(out) - i)
        out[i : i + n] += sig[:n] * g

    step = 60 / 92 / 2
    for k in range(int(sec / step)):
        put(s_hat(10 + k), k * step, 0.35 if k % 2 else 0.22)
    for at in (0, step * 3, step * 4.0 * 1.5 + step):
        put(s_kick(), at)
    for at in (step * 2, step * 6):
        put(s_snare(), at, 0.7)
    put(s_rhodes(sec, seed=11) * 1.6, 0.0)  # tonal layer: harmonics make the ZOH images legible
    return np.tanh(out * 1.1) * 0.9


def mock_drum_path(x, tune=-2, capture=1.0, hi=True, drive=1.8):
    """Rough stand-in for path A so the mockups show the right *kind* of artefacts."""
    if hi:
        x = x + 2.0 * np.diff(x, prepend=0)
    x = np.tanh(drive * x)
    if capture != 1.0:  # pre-speed (e.g. 45 rpm)
        n = int(len(x) / capture)
        x = np.interp(np.arange(n) * capture, np.arange(len(x)), x)
    fs = 26041.6667
    k = np.ones(3) / 3
    x = np.convolve(x, k, mode="same")  # token AA
    n = int(len(x) * fs / SR)
    y = np.interp(np.arange(n) * SR / fs, np.arange(len(x)), x)
    y = np.clip(np.round(y * 2047), -2048, 2047) / 2047  # 12-bit linear
    r = 2 ** (tune / 12)
    y = y[np.floor(np.arange(int(len(y) / r)) * r).astype(int)]  # drop-sample
    m = int(len(y) * SR / fs)
    return y[np.minimum(np.floor(np.arange(m) * fs / SR).astype(int), len(y) - 1)]  # ZOH out


def spec_image(sig, sr, W, H, fmax):
    nfft, hop = 1024, 96
    win = np.hanning(nfft)
    sig = np.concatenate([np.zeros(nfft // 2), sig, np.zeros(nfft)])
    frames = np.lib.stride_tricks.sliding_window_view(sig, nfft)[::hop] * win
    mag = np.abs(np.fft.rfft(frames, axis=1)).T
    db = 20 * np.log10(mag + 1e-9)
    db = np.clip((db - db.max() + 84) / 84, 0, 1) ** 1.15
    nb = int(fmax / (sr / 2) * (nfft // 2))
    db = db[:nb][::-1]
    stops = [
        (0.0, "#07090C"),
        (0.38, "#0C151F"),
        (0.58, "#183049"),
        (0.74, "#3E6487"),
        (0.88, "#86AFD3"),
        (1.0, "#E3EEF7"),
    ]
    pos = [p for p, _ in stops]
    rgb = np.stack([np.interp(db, pos, [hx(c)[i] for _, c in stops]) for i in range(3)], -1)
    img = Image.fromarray(rgb.astype(np.uint8), "RGB")
    return img.resize((W, H), Image.BILINEAR)


def sha(name):
    h = hashlib.sha256(name.encode()).hexdigest()
    return f"{h[:4]}…{h[-4:]}"


# --------------------------------------------------------------------------
# shared frame
# --------------------------------------------------------------------------

W_D, H_D = 1440, 900
NAV = [("01", "LIB"), ("02", "CHAIN"), ("03", "JOBS"), ("04", "A/B")]


def frame(c: Canvas, active: int, title: str, sub: str):
    c.metal(0, 0, W_D, H_D, T["bg0"], amp=1.0, shade=0)
    # top bar
    c.metal(0, 0, W_D, 52, T["bg2"], amp=2.6)
    c.line(0, 51, W_D, 51, T["bg0"])
    c.line(0, 52, W_D, 52, T["hl"])
    # logo block
    c.rect(0, 0, 88, 52, fill=T["bg1"])
    c.line(88, 0, 88, 52, T["bg0"])
    c.etext(44, 35, "1260", F("stencil", 25), T["tx_hi"], anchor="ms")
    c.line(22, 41, 66, 41, T["ac_md"])
    # title
    c.text(112, 31, f"{active + 1:02d}", F("mono", 11), T["tx_lo"])
    c.etext(136, 33, title, F("cond", 22), T["tx_hi"], tracking=4)
    tw = F("cond", 22).getlength(title) / SCALE + 4 * (len(title) - 1)
    c.vline_engraved(136 + tw + 18, 16, 22)
    c.mono(136 + tw + 32, 31, sub, 11, T["tx_lo"])
    # status cluster, right to left
    x = W_D - 24
    x -= c.seg7(x - 26, 16, 20, "03", glow=True) + 2
    c.label(x - 6, 31, "QUEUE", 11, T["tx_lo"], anchor="rs")
    x -= 70
    c.seg7(x - 13, 16, 20, "2")
    c.label(x - 20, 31, "WRK", 11, T["tx_lo"], anchor="rs")
    x -= 66
    c.vline_engraved(x, 14, 24)
    for name in ("RDS", "PG"):
        x -= 46
        c.led(x + 34, 26, True, r=2.8)
        c.label(x + 26, 31, name, 11, T["tx_md"], anchor="rs")
    x -= 16
    c.vline_engraved(x, 14, 24)
    host = "m4pro.tail3c9e.ts.net"
    hw = c.mono(x - 14, 30.5, host, 11, T["tx_md"], anchor="rs")
    c.led(x - 22 - hw, 26, True, r=2.8)
    c.label(x - 32 - hw, 31, "TAILNET", 11, T["tx_lo"], anchor="rs")

    # rail
    c.metal(0, 53, 88, H_D - 53 - 28, T["bg1"], amp=1.8)
    c.line(88, 53, 88, H_D - 28, T["bg0"])
    c.line(87, 53, 87, H_D - 28, T["hl"])
    for i, (num, lab) in enumerate(NAV):
        y = 70 + i * 74
        act = i == active
        if act:
            c.rect(0, y, 87, 62, fill=T["ac_xlo"])
            c.rect(0, y, 3, 62, fill=T["ac"])
        c.mono(44, y + 22, num, 10, T["ac"] if act else T["tx_lo"], anchor="ms")
        c.label(44, y + 42, lab, 15, T["ac_hi"] if act else T["tx_md"], anchor="ms", tracking=2.2, kind="cond")
        c.led(44, y + 53, act, r=2.2)
        c.hline_engraved(14, y + 68, 60)
    c.chain_v(44, 400, H_D - 80, color=hx("#232A31"))
    c.screw(44, H_D - 56)

    # bottom strip
    c.rect(0, H_D - 28, W_D, 28, fill=T["bg0"])
    c.line(0, H_D - 28, W_D, H_D - 28, T["line"])
    items = ["PG 16 · OK", "REDIS 7.4 · OK", "WORKERS 2/2 LIVE", "QUEUE 3", "127.0.0.1:8260 → tailscale serve :443"]
    x = 104
    for it in items:
        x += c.mono(x, H_D - 10, it, 10, T["tx_lo"]) + 28
    c.mono(W_D - 16, H_D - 10, "v0.0.0-phase0   14:22:07", 10, T["tx_lo"], anchor="rs")


# --------------------------------------------------------------------------
# 01 LIBRARY
# --------------------------------------------------------------------------

LIB = [
    ("kick_01_boom.wav", "KCK", "A", 0.612, 44100, s_kick(1)),
    ("kick_02_sub_long.wav", "KCK", "A", 1.204, 48000, np.concatenate([s_kick(2), s_kick(2)[::-1] * 0.05])),
    ("kick_03_dusty.wav", "KCK", "A", 0.388, 44100, s_kick(3)[: int(0.388 * SR)]),
    ("snare_01_rim.wav", "SNR", "A", 0.233, 44100, s_snare(4)[: int(0.233 * SR)]),
    ("snare_04_crack.wav", "SNR", "A", 0.412, 44100, s_snare(5)),
    ("snare_07_layer.wav", "SNR", "A", 0.508, 96000, s_snare(6)),
    ("hat_c_02.wav", "HAT", "A", 0.088, 44100, s_hat(7)),
    ("hat_o_05_long.wav", "HAT", "A", 0.612, 48000, s_hat(8, dec=7)),
    ("perc_shaker_a.wav", "PRC", "A", 0.301, 44100, s_hat(9, dec=14)),
    ("perc_clave_lo.wav", "PRC", "A", 0.145, 44100, np.sin(2 * np.pi * 900 * _t(0.145)) * np.exp(-_t(0.145) * 40)),
    ("brk_dusty_92.wav", "OTH", "A", 2.608, 44100, s_beat()),
    ("loop_rhodes_92.wav", "OTH", "B", 5.217, 48000, s_rhodes()),
    ("str_stab_dm.wav", "OTH", "B", 1.380, 44100, s_rhodes(1.38, 5) * 1.4),
    (
        "vox_chop_ah.wav",
        "OTH",
        "B",
        0.902,
        48000,
        np.sin(2 * np.pi * 220 * _t(0.9)) * np.sin(np.pi * _t(0.9) / 0.9) * 0.5,
    ),
]
SEL = 4


def screen_library():
    c = Canvas(W_D, H_D)
    frame(c, 0, "LIBRARY", "42 samples · 03:12 total")

    # left column ------------------------------------------------------
    x, y, w = 104, 68, 296
    c.panel(x, y, w, 236, "INTAKE", "A")
    dz = (x + 14, y + 46, w - 28, 120)
    c.rect(*dz, fill=T["bg1"])
    c.hatch(*dz, hx("#161B20"), spacing=7)
    # crop marks instead of a dashed border
    for px, py, sx, sy in [
        (dz[0], dz[1], 1, 1),
        (dz[0] + dz[2], dz[1], -1, 1),
        (dz[0], dz[1] + dz[3], 1, -1),
        (dz[0] + dz[2], dz[1] + dz[3], -1, -1),
    ]:
        c.line(px, py, px + 14 * sx, py, T["tx_lo"], 1.4)
        c.line(px, py, px, py + 14 * sy, T["tx_lo"], 1.4)
    c.text(dz[0] + dz[2] / 2, dz[1] + 60, "DROP WAV", F("stencil", 24), T["tx_md"], anchor="ms", tracking=2)
    c.mono(dz[0] + dz[2] / 2, dz[1] + 82, "WAV · AIFF · ANY SR · ANY DEPTH", 9.5, T["tx_lo"], anchor="ms")
    # upload rows
    rows = [("brk_think_45rpm.wav", 0.58, False), ("loop_rhodes_92.wav", 1.0, True)]
    for i, (nm, p, ok) in enumerate(rows):
        ry = y + 186 + i * 22
        c.mono(x + 16, ry, nm, 10.5, T["tx_hi"] if not ok else T["tx_md"])
        c.rect(x + 166, ry - 7, 64, 5, fill=T["bg0"])
        c.rect(x + 166, ry - 7, 64 * p, 5, fill=T["ac"] if not ok else T["ac_md"])
        c.mono(x + w - 16, ry, "SHA OK" if ok else f"{int(p * 100)}%", 9.5, T["tx_lo"] if ok else T["ac"], anchor="rs")

    y2 = y + 252
    c.panel(x, y2, w, 176, "FILTER", "B")
    c.seg(x + 16, y2 + 48, w - 32, 26, ["ALL", "KCK", "SNR", "HAT", "PRC", "OTH"], 0, size=12)
    counts = ["42", "9", "11", "8", "6", "8"]
    cw = (w - 32) / 6
    for i, n in enumerate(counts):
        c.mono(x + 16 + cw * i + cw / 2, y2 + 90, n, 9.5, T["tx_lo"], anchor="ms")
    c.seg(x + 16, y2 + 102, 120, 22, ["A", "B", "A+B"], 2, size=11, mono=True)
    c.label(x + 148, y2 + 117, "ROUTE", 10.5, T["tx_lo"])
    c.rect(x + 16, y2 + 134, w - 32, 26, fill=T["bg0"], outline=T["line"])
    c.mono(x + 26, y2 + 151, "/ snare", 11, T["tx_hi"])
    c.rect(x + 78, y2 + 139, 1.4, 16, fill=T["ac"])
    c.mono(x + w - 26, y2 + 151, "11 hits", 10, T["tx_lo"], anchor="rs")

    y3 = y2 + 192
    c.panel(x, y3, w, 852 - y3 - 0, "STORE", "C")
    c.lcd_window(x + 16, y3 + 48, w - 32, 70)
    c.seg7(x + 28, y3 + 60, 46, "042")
    c.label(x + 148, y3 + 80, "SAMPLES", 11, T["tx_lo"])
    c.mono(x + 148, y3 + 100, "03:12.48 total", 10.5, T["tx_md"])
    stats = [("DATA DIR", "~/1260/data"), ("SIZE", "812.4 MB"), ("DUP (SHA)", "0"), ("UNROLED", "3")]
    for i, (k, v) in enumerate(stats):
        ry = y3 + 146 + i * 22
        c.label(x + 16, ry, k, 10.5, T["tx_lo"])
        c.mono(x + w - 16, ry, v, 10.5, T["tx_md"], anchor="rs")
        c.line(x + 16, ry + 7, x + w - 16, ry + 7, hx("#1A1F24"))

    # center: table ------------------------------------------------------
    tx, tw_ = 416, 648
    c.panel(tx, 68, tw_, 784, "SAMPLES", "D", tone="bg1", amp=1.6)
    cols = [
        ("#", 16),
        ("NAME", 44),
        ("ROLE", 236),
        ("RT", 286),
        ("LEN", 318),
        ("SR", 372),
        ("SHA256", 426),
        ("WAVE", 514),
    ]
    hy = 68 + 58
    for name, cx in cols:
        c.label(tx + cx, hy, name, 10.5, T["tx_lo"], tracking=1.8)
    c.hline_engraved(tx + 12, hy + 8, tw_ - 24)
    for i, (nm, role, rt, ln, sr, sig) in enumerate(LIB):
        ry = hy + 14 + i * 40
        sel = i == SEL
        hov = i == 10
        if sel:
            c.rect(tx + 8, ry, tw_ - 16, 38, fill=T["ac_xlo"])
            c.rect(tx + 8, ry, 2, 38, fill=T["ac"])
        elif hov:
            c.rect(tx + 8, ry, tw_ - 16, 38, fill=T["bg3"])
        base = ry + 24
        c.mono(tx + 16, base, f"{i + 1:02d}", 10, T["tx_lo"])
        c.mono(tx + 44, base, nm, 11.5, T["ac_hi"] if sel else T["tx_hi"])
        # role stamp
        rc = T["ac"] if sel else T["tx_md"]
        c.rect(tx + 236, ry + 11, 36, 16, outline=rc)
        c.text(tx + 254, ry + 20, role, F("cond", 11.5), rc, anchor="mm", tracking=1.2)
        c.mono(tx + 286, base, rt, 11, T["ac"] if rt == "A" else T["tx_md"])
        c.mono(tx + 318, base, f"{ln:.3f}", 10.5, T["tx_md"])
        c.mono(tx + 372, base, f"{sr / 1000:g}k", 10.5, T["tx_md"])
        c.mono(tx + 426, base, sha(nm), 10, T["tx_lo"])
        c.waveform(tx + 514, ry + 6, 118, 26, sig, T["ac"] if sel else hx("#56606A"), grid=False)
        c.line(tx + 12, ry + 39, tx + tw_ - 12, ry + 39, hx("#13171B"))

    fy = 852 - 34
    c.hline_engraved(tx + 12, fy - 10, tw_ - 24)
    c.mono(tx + 16, fy + 8, "14 / 42", 10.5, T["tx_md"])
    c.seg(tx + tw_ - 16 - 132, fy - 4, 132, 20, ["1", "2", "3"], 0, size=10, mono=True)
    c.label(tx + tw_ - 160, fy + 8, "PAGE", 10.5, T["tx_lo"], anchor="rs")

    # right: detail ------------------------------------------------------
    dx, dw = 1080, 344
    c.panel(dx, 68, dw, 784, "DETAIL", "E")
    nm, role, rt, ln, sr, sig = LIB[SEL]
    c.text(dx + 16, 132, nm, F("cond", 22), T["tx_hi"], tracking=0.6)
    c.mono(dx + 16, 152, f"sha256 {hashlib.sha256(nm.encode()).hexdigest()[:24]}…", 9.5, T["tx_lo"])
    c.lcd_window(dx + 16, 168, dw - 32, 150)
    c.waveform(dx + 20, 174, dw - 40, 138, sig, T["ac"], grid=True)
    # time ruler
    for k in range(5):
        rx = dx + 20 + (dw - 40) * k / 4
        c.line(rx, 320, rx, 325, T["tx_lo"])
        c.mono(rx, 337, f"{ln * k / 4:.2f}", 9, T["tx_lo"], anchor="ms" if 0 < k < 4 else ("ls" if k == 0 else "rs"))
    c.label(dx + 16, 374, "ROLE", 11, T["tx_md"])
    c.seg(dx + 16, 384, dw - 32, 34, ["KICK", "SNARE", "HAT", "PERC", "OTHER"], 1, size=13)
    c.label(dx + 16, 448, "ROUTE", 11, T["tx_md"])
    c.seg(dx + 16, 458, dw - 32, 30, ["A  ·  12B LIN 26.04K", "B  ·  12B NL 40K"], 0, size=12)
    meta = [
        ("LEN", f"{ln:.3f} s"),
        ("SR", f"{sr} Hz"),
        ("CH", "1 / MONO"),
        ("DEPTH", "24 int"),
        ("PEAK", "-0.8 dBFS"),
        ("ADDED", "2026-10-05 13:58"),
    ]
    for i, (k, v) in enumerate(meta):
        col, row = i % 2, i // 2
        mx = dx + 16 + col * 164
        my = 528 + row * 40
        c.label(mx, my, k, 10, T["tx_lo"])
        c.mono(mx, my + 18, v, 12, T["tx_hi"])
    c.hline_engraved(dx + 12, 650, dw - 24)
    c.label(dx + 16, 676, "LAST RENDERS", 10.5, T["tx_lo"])
    for i, (p, tn, st) in enumerate([("sp_snare_hard", "-2", "OK"), ("sp_snare_hard", "-1", "OK")]):
        ry = 698 + i * 20
        c.mono(dx + 16, ry, f"{p}  tune {tn}", 10.5, T["tx_md"])
        c.mono(dx + dw - 16, ry, st, 10, T["ac"], anchor="rs")
    c.button(dx + 16, 780, 196, 40, "SEND TO CHAIN", "primary", size=14)
    c.button(dx + 222, 780, dw - 238, 40, "REMOVE", "normal")
    c.save("01_library")


# --------------------------------------------------------------------------
# 02 CHAIN
# --------------------------------------------------------------------------


def stage_box(c: Canvas, x, y, w, h, num, name, cap, on=True, sel=False, jp=None, spine_x=None):
    """One stage module. Left block (132px): index, name, caption, bypass rocker."""
    if spine_x is not None:  # shackle from the chain spine into the module
        node = T["ac_hi"] if sel else (T["ac"] if on else T["tx_xlo"])
        c.line(spine_x + 5, y + 16, x, y + 16, T["line2"], 1.4)
        c.rect(spine_x - 3, y + 13, 7, 7, fill=T["bg0"])
        c.rect(spine_x - 2, y + 14, 5, 5, fill=node)
        if sel or on:
            c.gd.rectangle(c.box(spine_x - 2, y + 14, 5, 5), fill=node if sel else T["ac_md"])
    c.metal(x, y, w, h, T["bg3"] if sel else T["bg2"], amp=2.2, c=7)
    p = c.chamfer_pts(x, y, w, h, 7)
    c.d.polygon(c.pts(p), outline=T["ac"] if sel else T["bg0"], width=c.s(1))
    c.line(x + 7, y + 1, x + w - 2, y + 1, T["line2"])
    c.mono(x + 12, y + 21, num, 10, T["ac"] if sel else T["tx_lo"])
    c.text(x + 32, y + 21, name, F("cond", 15), T["tx_hi"] if on else T["tx_lo"], tracking=1.4)
    if jp:  # owner's own word for the stage, in place of the caption
        c.text(x + 12, y + 38, jp, F("jp", 10.5), T["tx_md"])
    else:
        c.mono(x + 12, y + 37, cap, 9.5, T["tx_lo"])
    c.toggle(x + 104, y + 9, on)
    c.vline_engraved(x + 132, y + 8, h - 16)
    if not on:
        c.hatch(x + 134, y + 2, w - 136, h - 4, hx("#101316"), spacing=5, width=1.4)


def seg_field(c: Canvas, x, y, w, label, items, active, tag=None, mono=False, size=11, dim=False):
    lw = c.label(x, y + 9, label, 11, T["tx_lo"] if dim else T["tx_md"], tracking=1.4)
    if tag:
        c.tag(x + lw + 5, y + 0.5, tag)
    c.seg(x, y + 14, w, 20, items, active, size=size, mono=mono, dim=dim)


def value_field(c: Canvas, x, y, label, value, tag=None, size=13, col=None):
    lw = c.label(x, y + 9, label, 11, T["tx_md"], tracking=1.4)
    if tag:
        c.tag(x + lw + 5, y + 0.5, tag)
    c.mono(x, y + 30, value, size, col or T["tx_hi"], kind="mono_md")


def screen_chain():
    c = Canvas(W_D, H_D)
    frame(c, 1, "CHAIN", "snare_04_crack.wav → A · preset sp_snare_hard v3")

    # path A -------------------------------------------------------------
    ax, aw = 104, 664
    c.panel(ax, 68, aw, 784, None, tone="bg1", amp=1.4, screws=False)
    c.etext(ax + 18, 94, "A", F("stencil", 22), T["ac"])
    c.etext(ax + 40, 93, "DRUM PATH", F("cond", 17), T["tx_hi"], tracking=3)
    c.tag(ax + 170, 83, "VER")
    c.mono(ax + aw - 18, 92, "12-BIT LINEAR · 26 041.67 Hz · DROP-SAMPLE", 10, T["tx_lo"], anchor="rs")
    c.hline_engraved(ax + 12, 104, aw - 24)
    spine = ax + 22
    c.chain_v(spine, 112, 842, color=hx("#2A3138"))
    sx, sw = ax + 40, aw - 54
    px0 = sx + 146
    pw = sx + sw - 14 - px0
    gut = 20
    cw = (pw - 3 * gut) / 4

    def col(i):
        return px0 + i * (cw + gut)

    span2 = 2 * cw + gut
    y = 114
    gap = 9

    def nxt(h):
        nonlocal y
        y0 = y
        y += h + gap
        return y0

    r = 20  # param row offset inside a stage

    y0 = nxt(62)
    stage_box(c, sx, y0, sw, 62, "01", "ROLE", "→ preset", spine_x=spine)
    seg_field(c, col(0), y0 + r, span2, "ROLE", ["KCK", "SNR", "HAT", "PRC", "OTH"], 1)
    value_field(c, col(2), y0 + r, "PRESET", "sp_snare_hard", size=12)

    y0 = nxt(62)
    stage_box(c, sx, y0, sw, 62, "02", "PRE-EQ", "role preset", jp="ガン突き", spine_x=spine)
    seg_field(c, col(0), y0 + r, cw, "TYPE", ["LS", "PK", "HS"], 2)
    c.slider(col(1), y0 + r, cw, "FREQ", "6.50k", 0.62)
    c.slider(col(2), y0 + r, cw, "GAIN", "+11.0", 0.92, bipolar=True)
    c.slider(col(3), y0 + r, cw, "Q", "0.71", 0.3)

    y0 = nxt(62)
    stage_box(c, sx, y0, sw, 62, "03", "DRIVE", "tanh → 12b wall", jp="ちょい歪み", spine_x=spine)
    c.slider(col(0), y0 + r, cw, "IN", "+6.0", 0.66, bipolar=True)
    seg_field(c, col(1), y0 + r, cw, "CURVE", ["TANH", "ATAN", "CUB"], 0, size=10)
    c.slider(col(2), y0 + r, cw, "MIX", "100%", 1.0)
    c.slider(col(3), y0 + r, cw, "OUT", "-3.0", 0.4, bipolar=True)

    y0 = nxt(62)
    stage_box(c, sx, y0, sw, 62, "04", "CAPTURE", "pre-speed", spine_x=spine)
    seg_field(c, col(0), y0 + r, cw, "SPEED", ["×1", "45", "USR"], 1, mono=True, size=10)
    c.lcd_window(col(1), y0 + 14, cw, 36)
    c.seg7(col(1) + 10, y0 + 22, 20, "1.350", gap=4)
    value_field(c, col(2), y0 + r, "SHIFT", "+5.20 st", size=12)
    c.label(col(3), y0 + r + 9, "LOCK TUNE", 11, T["tx_md"], tracking=1.4)
    c.toggle(col(3), y0 + r + 16, False)

    y0 = nxt(78)
    stage_box(c, sx, y0, sw, 78, "05", "ADC", "AA·SRC·12b·clip", spine_x=spine)
    c.slider(col(0), y0 + 14, cw, "AA FC", "12.5k", 0.7, tag="HYP")
    c.slider(col(1), y0 + 14, cw, "ORDER", "8", 0.5, tag="HYP")
    value_field(c, col(2), y0 + 14, "RATE", "26041.67", tag="VER", size=12.5)
    value_field(c, col(3), y0 + 14, "BITS", "12 LIN", tag="VER", size=12.5)
    c.hline_engraved(px0, y0 + 50, pw)
    c.label(col(0), y0 + 68, "DITHER", 10.5, T["tx_lo"])
    c.seg(col(0) + 46, y0 + 56, cw - 46, 17, ["OFF", "TPDF"], 0, size=10)
    c.label(col(1), y0 + 68, "CLIP", 10.5, T["tx_lo"])
    c.mono(col(1) + 30, y0 + 68, "hard ±2048", 10, T["tx_md"])
    c.label(col(2), y0 + 68, "LEVELS", 10.5, T["tx_lo"])
    c.mono(col(2) + 46, y0 + 68, "≤ 4096", 10, T["tx_md"])

    y0 = nxt(80)
    stage_box(c, sx, y0, sw, 80, "06", "TUNE", "drop-sample", sel=True, spine_x=spine)
    c.lcd_window(col(0), y0 + 10, cw, 60)
    c.seg7(col(0) + 18, y0 + 18, 44, "-2")
    c.label(col(1), y0 + 26, "RATIO", 11, T["tx_md"], tracking=1.4)
    c.mono(col(1), y0 + 46, "2^(-2/12) = 0.890899", 12, T["ac_hi"])
    c.mono(col(1), y0 + 65, "step 1 1 1 1 1 1 1 1 0 1 …", 10, T["tx_lo"])
    seg_field(c, col(3), y0 + 17, cw, "STEP", ["SEMI", "FINE"], 0)
    c.mono(col(3), y0 + 65, "range TBD", 9.5, T["tx_lo"])

    y0 = nxt(50)
    stage_box(c, sx, y0, sw, 50, "07", "VOL ENV", "8-bit steps", on=False, spine_x=spine)
    c.slider(col(0), y0 + 12, cw, "DECAY", "—", 0.5, dim=True)
    c.slider(col(1), y0 + 12, cw, "STEPS", "256", 1.0, dim=True)

    y0 = nxt(56)
    stage_box(c, sx, y0, sw, 56, "08", "DAC", "zero-order hold", spine_x=spine)
    seg_field(c, col(0), y0 + 14, cw, "HOLD", ["ZOH", "LIN"], 0)
    c.slider(col(1), y0 + 14, cw, "RECON", "OFF", 0.0, tag="HYP")

    y0 = nxt(66)
    stage_box(c, sx, y0, sw, 66, "09", "ANALOG", "per channel", spine_x=spine)
    seg_field(c, col(0), y0 + 12, span2, "CH", [str(i) for i in range(1, 9)], 0, mono=True)
    c.mono(col(0), y0 + 60, "1-2 LADDER · 3-6 FIXED · 7-8 THRU", 9, T["tx_lo"])
    c.slider(col(2), y0 + 14, cw, "FC", "9.8k", 0.58, tag="HYP")
    c.slider(col(3), y0 + 14, cw, "ENV", "0.25", 0.25, tag="HYP")

    y0 = nxt(56)
    stage_box(c, sx, y0, sw, 56, "10", "OUTPUT", "48k · 24-bit", spine_x=spine)
    seg_field(c, col(0), y0 + 14, span2, "RATE", ["48000", "44100", "NATIVE"], 0, mono=True, size=10)
    seg_field(c, col(2), y0 + 14, span2, "SRC", ["KEEP-ZOH", "SINC", "LINEAR"], 0, size=10)

    # path B -------------------------------------------------------------
    bx, bw = 784, 352
    c.panel(bx, 68, bw, 784, None, tone="bg1", amp=1.4, screws=False)
    c.etext(bx + 18, 94, "B", F("stencil", 22), T["tx_md"])
    c.etext(bx + 38, 93, "SAMPLE PATH", F("cond", 17), T["tx_hi"], tracking=3)
    c.mono(bx + bw - 16, 92, "12-BIT NL · 40 kHz", 10, T["tx_lo"], anchor="rs")
    c.hline_engraved(bx + 12, 104, bw - 24)
    c.mono(bx + 16, 124, "STANDBY — sample routed to A", 10, T["tx_lo"])
    bspine = bx + 20
    c.chain_v(bspine, 134, 842, color=hx("#22292F"))
    bsx, bsw = bx + 36, bw - 48
    y = 138
    bq = (bsw - 44) / 2

    def bstage(h, num, name, cap):
        nonlocal y
        y0 = y
        c.line(bspine + 5, y0 + 16, bsx, y0 + 16, T["line2"], 1.4)
        c.rect(bspine - 3, y0 + 13, 7, 7, fill=T["bg0"])
        c.rect(bspine - 2, y0 + 14, 5, 5, fill=T["ac_md"])
        c.metal(bsx, y0, bsw, h, T["bg2"], amp=2.0, c=7)
        c.d.polygon(c.pts(c.chamfer_pts(bsx, y0, bsw, h, 7)), outline=T["bg0"], width=c.s(1))
        c.line(bsx + 7, y0 + 1, bsx + bsw - 2, y0 + 1, T["line2"])
        c.mono(bsx + 12, y0 + 21, num, 10, T["tx_lo"])
        c.text(bsx + 32, y0 + 21, name, F("cond", 15), T["tx_hi"], tracking=1.4)
        c.mono(bsx + bsw - 40, y0 + 20, cap, 9.5, T["tx_lo"], anchor="rs")
        c.toggle(bsx + bsw - 34, y0 + 9, True)
        c.hline_engraved(bsx + 10, y0 + 30, bsw - 20)
        y += h + 9
        return y0

    y0 = bstage(96, "01", "INPUT", "pre-emph")
    c.slider(bsx + 14, y0 + 42, bq, "GAIN", "0.0", 0.5, bipolar=True)
    c.slider(bsx + 30 + bq, y0 + 42, bq, "EMPH", "+6 dB", 0.7, tag="HYP")

    y0 = bstage(96, "02", "RESAMPLE", "→ 40 kHz")
    value_field(c, bsx + 14, y0 + 42, "RATE", "40000", tag="VER")
    c.slider(bsx + 30 + bq, y0 + 42, bq, "BAND", "18.0k", 0.75, tag="VER")

    y0 = bstage(170, "03", "NL-12 CODEC", "16→12nl→16")
    seg_field(c, bsx + 14, y0 + 40, bsw - 28, "CURVE CANDIDATE", ["PWL", "GAIN-RNG", "MU-LAW"], 0, tag="HYP", size=12)
    gx, gy, gw, gh = bsx + 14, y0 + 96, 104, 60
    c.lcd_window(gx, gy, gw, gh)
    xs = np.linspace(-1, 1, 80)
    ys = np.sign(xs) * np.interp(np.abs(xs), [0, 0.125, 0.25, 0.5, 1], [0, 0.35, 0.55, 0.78, 1])
    c.line(gx + 2, gy + gh / 2, gx + gw - 2, gy + gh / 2, hx("#1A232C"))
    curve = [(gx + 3 + (u + 1) / 2 * (gw - 6), gy + gh / 2 - v * gh / 2 * 0.85) for u, v in zip(xs, ys, strict=True)]
    c.d.line(
        c.pts(curve),
        fill=T["ac"],
        width=c.s(1.2),
    )
    c.slider(bsx + 134, y0 + 100, bsw - 148, "KNEE", "0.125", 0.25, tag="HYP")
    c.mono(bsx + 134, y0 + 150, "A/B/C switchable · see docs", 9, T["tx_lo"])

    y0 = bstage(108, "04", "TUNE", "-12 … +6")
    c.lcd_window(bsx + 14, y0 + 40, 74, 50)
    c.seg7(bsx + 24, y0 + 47, 36, "+0")
    seg_field(c, bsx + 104, y0 + 44, bsw - 118, "INTERP", ["NONE", "LINEAR"], 0, tag="HYP", size=12)

    y0 = bstage(132, "05", "DE-EMPH · DAC", "16b → out")
    c.slider(bsx + 14, y0 + 42, bq, "DE-EMPH", "-6 dB", 0.3, tag="HYP")
    value_field(c, bsx + 30 + bq, y0 + 42, "DAC", "16-bit")
    seg_field(c, bsx + 14, y0 + 82, bsw - 28, "OUT", ["48000", "44100", "40000"], 0, mono=True, size=10)

    # inspector ----------------------------------------------------------
    ix, iw = 1152, 272
    c.panel(ix, 68, iw, 784, "RENDER", "R")
    c.label(ix + 16, 126, "PRESET", 10.5, T["tx_lo"])
    c.mono(ix + 16, 146, "sp_snare_hard", 14, T["tx_hi"], kind="mono_md")
    c.mono(ix + iw - 16, 146, "v3 · edited", 10, T["ac"], anchor="rs")
    c.button(ix + 16, 160, 116, 28, "SAVE", "normal", size=12)
    c.button(ix + 140, 160, 116, 28, "FORK", "hover", size=12)
    c.hline_engraved(ix + 12, 204, iw - 24)
    c.label(ix + 16, 230, "TUNE", 12, T["tx_md"], kind="cond", tracking=3)
    c.mono(ix + iw - 16, 230, "semitones", 10, T["tx_lo"], anchor="rs")
    c.lcd_window(ix + 16, 242, iw - 32, 120)
    c.seg7(ix + 70, 256, 92, "-2", gap=18)
    c.mono(ix + 28, 354, "A·06", 9.5, T["tx_lo"])
    c.mono(ix + iw - 28, 354, "×0.8909", 9.5, T["ac"], anchor="rs")
    c.seg(ix + 16, 374, iw - 32, 30, ["-3", "-2", "-1", "0", "+1"], 1, size=13, mono=True)
    c.hline_engraved(ix + 12, 422, iw - 24)
    c.label(ix + 16, 446, "OUTPUT", 10.5, T["tx_lo"])
    c.mono(ix + 16, 468, "snare_04_crack", 11, T["tx_hi"])
    c.mono(ix + 16, 484, "__sp-snare-hard", 11, T["tx_hi"])
    c.mono(ix + 16, 500, "__tune-2.wav", 11, T["ac_hi"])
    c.mono(ix + 16, 524, "WAV 24-bit · 48 kHz", 10.5, T["tx_md"])
    c.label(ix + 16, 562, "ATTACH", 10.5, T["tx_lo"])
    for i, (k, on) in enumerate([("SPECTROGRAM PNG", True), ("PARAMS JSON", True), ("NATIVE-RATE WAV", False)]):
        ry = 580 + i * 24
        c.toggle(ix + 16, ry, on)
        c.label(ix + 48, ry + 10, k, 11, T["tx_hi"] if on else T["tx_lo"])
    c.hline_engraved(ix + 12, 660, iw - 24)
    c.label(ix + 16, 684, "PARAM HASH", 10.5, T["tx_lo"])
    c.mono(ix + 16, 704, "a41f 9be0 77c3 09c2", 11.5, T["tx_md"])
    c.mono(ix + 16, 722, "deterministic · seedless", 9.5, T["tx_lo"])
    c.button(ix + 16, 772, iw - 32, 56, "RENDER", "primary", size=20)
    c.save("02_chain")


# --------------------------------------------------------------------------
# 03 JOBS
# --------------------------------------------------------------------------

STAGES_A = ["ROLE", "EQ", "DRV", "CAP", "ADC", "TUNE", "ENV", "DAC", "ANA", "OUT"]

JOBS = [
    # id, sample, preset, state, done, partial, failed, elapsed
    ("7f2a", "snare_04_crack.wav", "sp_snare_hard", "RUN", 5, 0.6, None, "0.41"),
    ("7f29", "kick_01_boom.wav", "sp_kick_low", "RUN", 8, 0.3, None, "0.62"),
    ("7f28", "brk_dusty_92.wav", "sp_break_45", "QUE", 0, 0, None, "—"),
    ("7f27", "loop_rhodes_92.wav", "mpc_nl_pwl", "QUE", 0, 0, None, "—"),
    ("7f26", "hat_c_02.wav", "sp_hat_air", "QUE", 0, 0, None, "—"),
    ("7f25", "snare_07_layer.wav", "sp_snare_hard", "FAIL", 4, 0, 4, "0.18"),
    ("7f24", "kick_03_dusty.wav", "sp_kick_low", "OK", 10, 0, None, "0.57"),
    ("7f23", "snare_01_rim.wav", "sp_snare_hard", "OK", 10, 0, None, "0.33"),
    ("7f22", "perc_clave_lo.wav", "sp_perc_ch3", "OK", 10, 0, None, "0.21"),
    ("7f21", "kick_01_boom.wav", "sp_kick_low", "CXL", 2, 0, None, "0.07"),
    ("7f20", "str_stab_dm.wav", "mpc_nl_ulaw", "OK", 5, 0, None, "0.88"),
]


def state_chip(c: Canvas, x, y, st):
    w, h = 40, 16
    if st == "RUN":
        c.rect(x, y, w, h, fill=T["ac_lo"], outline=T["ac"])
        col = T["ac_hi"]
    elif st in ("FAIL", "LOST"):
        c.rect(x, y, w, h, fill=T["fail_bg"])
        c.hatch(x, y, w, h, hx("#3A4046"), spacing=4)
        c.rect(x, y, w, h, outline=T["fail"])
        col = T["fail"]
    elif st == "OK":
        c.rect(x, y, w, h, outline=T["ac_md"])
        col = T["ac"]
    else:
        c.rect(x, y, w, h, outline=T["line2"])
        col = T["tx_md"] if st == "QUE" else T["tx_lo"]
    c.text(x + w / 2, y + h / 2 + 0.5, st, F("mono_md", 9), col, anchor="mm")


def screen_jobs():
    c = Canvas(W_D, H_D)
    frame(c, 2, "JOBS", "live · sse · 3 subscribers")

    # KPI strip
    kpis = [("QUEUE", "03", False), ("RUNNING", "02", False), ("DONE 24H", "118", False), ("FAILED 24H", "01", True)]
    kx = 104
    for k, v, bad in kpis:
        w = 218
        c.panel(kx, 68, w, 96, None, screws=False, c=8)
        c.label(kx + 16, 92, k, 11, T["tx_md"], tracking=2.2)
        c.lcd_window(kx + 16, 102, w - 32, 50)
        if bad:
            c.hatch(kx + 17, 103, w - 34, 48, hx("#141A1F"), spacing=6)
            c.seg7(kx + w - 30 - 3 * 25, 110, 34, f"{v:>3}", on=T["fail"], glow=True)
        else:
            c.seg7(kx + w - 30 - 3 * 25, 110, 34, f"{v:>3}")
        kx += w + 12
    c.panel(kx, 68, 1424 - kx, 96, None, screws=False, c=8)
    c.label(kx + 16, 92, "THROUGHPUT", 11, T["tx_md"], tracking=2.2)
    c.mono(kx + 16, 124, "0.42 s / job  (p50)", 13, T["tx_hi"])
    c.mono(kx + 16, 144, "0.88 s / job  (p95) · 1 s drum < 1 s", 10.5, T["tx_lo"])
    c.screw(1424 - 10, 78)

    # workers
    wx, ww = 104, 340
    c.panel(wx, 180, ww, 412, "WORKERS", "W")
    workers = [
        ("m4pro:41822", "LIVE", 0.8, "7f2a · 06 TUNE", "0.3.1"),
        ("m4pro:41823", "LIVE", 1.4, "7f29 · 09 ANA", "0.3.1"),
        ("studio-mini:9031", "LOST", 47.2, "7f25 → requeued", "0.3.0"),
    ]
    for i, (wid, st, hb, cur, ver) in enumerate(workers):
        y = 228 + i * 116
        lost = st == "LOST"
        c.rect(wx + 14, y, ww - 28, 104, fill=T["bg1"], outline=T["bg0"])
        if lost:
            c.hatch(wx + 14, y, ww - 28, 104, hx("#181D22"), spacing=7, width=1.5)
        c.led(wx + 30, y + 20, not lost, r=3.2)
        c.mono(wx + 44, y + 25, wid, 13, T["tx_hi"] if not lost else T["tx_md"], kind="mono_md")
        state_chip(c, wx + ww - 70, y + 12, "RUN" if not lost else "LOST")
        c.label(wx + 28, y + 52, "HEARTBEAT", 10, T["tx_lo"])
        # heartbeat decay bar: TTL 15s
        frac = max(0.0, 1 - hb / 15)
        c.rect(wx + 112, y + 44, 120, 6, fill=T["bg0"])
        if frac > 0:
            c.rect(wx + 112, y + 44, 120 * frac, 6, fill=T["ac"])
        else:
            c.hatch(wx + 112, y + 44, 120, 6, T["fail"], spacing=3)
        c.mono(wx + ww - 28, y + 52, f"{hb:.1f}s", 11, T["fail"] if lost else T["tx_hi"], anchor="rs")
        c.label(wx + 28, y + 74, "JOB", 10, T["tx_lo"])
        c.mono(wx + 112, y + 74, cur, 11, T["ac_hi"] if not lost else T["tx_md"])
        c.label(wx + 28, y + 94, "VER", 10, T["tx_lo"])
        c.mono(wx + 112, y + 94, f"{ver}  pid {wid.split(':')[1]}", 10, T["tx_md"])

    # job table
    jx, jw = 456, 620
    c.panel(jx, 180, jw, 412, "QUEUE / HISTORY", "J", tone="bg1", amp=1.5)
    hy = 236
    for name, cx in [("ID", 16), ("SAMPLE", 64), ("PRESET", 220), ("ST", 330), ("STAGES", 382), ("SEC", 600)]:
        c.label(jx + cx, hy, name, 10.5, T["tx_lo"], tracking=1.8, anchor="rs" if name == "SEC" else "ls")
    c.hline_engraved(jx + 12, hy + 7, jw - 24)
    for i, (jid, smp, pre, st, done, part, failed, el) in enumerate(JOBS):
        ry = hy + 12 + i * 30
        sel = jid == "7f25"
        if sel:
            c.rect(jx + 8, ry, jw - 16, 28, fill=T["bg3"])
            c.rect(jx + 8, ry, 2, 28, fill=T["fail"])
        b = ry + 19
        dim = st in ("OK", "CXL")
        c.mono(jx + 16, b, jid, 11, T["tx_md"])
        c.mono(jx + 64, b, smp[:20], 10.5, T["tx_lo"] if dim else T["tx_hi"])
        c.mono(jx + 220, b, pre, 10, T["tx_lo"] if dim else T["tx_md"])
        state_chip(c, jx + 326, ry + 6, st)
        n = 5 if pre.startswith("mpc") else 10
        c.seg_progress(jx + 382, ry + 10, 180 if n == 10 else 88, 9, n, done, part, failed, dim=dim)
        c.mono(jx + jw - 20, b, el, 10.5, T["tx_md"], anchor="rs")

    # detail
    dx, dw = 1092, 332
    c.panel(dx, 180, dw, 672, "JOB 7f25", "→")
    state_chip(c, dx + dw - 58, 208, "FAIL")
    c.mono(dx + 16, 234, "snare_07_layer.wav", 12, T["tx_hi"], kind="mono_md")
    c.mono(dx + 16, 252, "sp_snare_hard v3 · tune -2 · worker studio-mini", 9.5, T["tx_lo"])
    for i, (s, t_, st) in enumerate(
        [
            ("01 ROLE", "0.001", "OK"),
            ("02 PRE-EQ", "0.004", "OK"),
            ("03 DRIVE", "0.002", "OK"),
            ("04 CAPTURE", "0.000", "OK"),
            ("05 ADC", "0.171", "FAIL"),
            ("06 TUNE", "—", ""),
            ("07 VOL ENV", "—", "BYP"),
            ("08 DAC", "—", ""),
            ("09 ANALOG", "—", ""),
            ("10 OUTPUT", "—", ""),
        ]
    ):
        ry = 284 + i * 22
        bad = st == "FAIL"
        if bad:
            c.rect(dx + 12, ry - 15, dw - 24, 21, fill=T["fail_bg"])
            c.hatch(dx + 12, ry - 15, 6, 21, T["fail"], spacing=3)
        col = T["fail"] if bad else (T["tx_hi"] if st == "OK" else T["tx_lo"])
        c.mono(dx + 24, ry, s, 10.5, col)
        c.mono(dx + 200, ry, t_, 10.5, col, anchor="rs")
        c.mono(dx + dw - 18, ry, st, 9.5, T["fail"] if bad else (T["ac"] if st == "OK" else T["tx_lo"]), anchor="rs")
    c.label(dx + 16, 518, "TRACEBACK", 10.5, T["tx_md"])
    c.lcd_window(dx + 14, 528, dw - 28, 236)
    tb = [
        "Traceback (most recent call last):",
        '  File "engine/stages/adc.py", line 88,',
        "    in resample_to_native",
        "    y = poly_resample(x, up, down)",
        '  File "engine/dsp/resample.py", line 41,',
        "    in poly_resample",
        "ValueError: input SR 96000 not in",
        "  supported set; set allow_any_sr",
        "",
        "worker lost heartbeat 47.2s → job",
        "marked FAILED by reaper (attempt 1/3)",
    ]
    for i, ln in enumerate(tb):
        c.mono(dx + 24, 548 + i * 16.5, ln, 9.5, T["fail"] if ln.startswith("ValueError") else T["tx_md"])
    c.mono(dx + 24, 752, "attempt 1/3 · retry re-enqueues to stream", 9.5, T["tx_lo"])
    c.button(dx + 16, 788, 96, 40, "RETRY", "primary")
    c.button(dx + 120, 788, 96, 40, "CANCEL", "normal")
    c.button(dx + 224, 788, dw - 240, 40, "LOG", "hover")

    # log tail
    lx, lw = 104, 972
    c.panel(lx, 608, lw, 244, "LOG TAIL", "L", tone="bg1", amp=1.4)
    c.label(lx + lw - 210, 631, "FOLLOW", 10.5, T["tx_md"])
    c.toggle(lx + lw - 164, 621, True)
    c.label(lx + lw - 124, 631, "LEVEL", 10.5, T["tx_lo"])
    c.seg(lx + lw - 90, 617, 72, 18, ["INFO", "ERR"], 0, size=9.5, mono=True)
    logs = [
        ("14:22:06.913", "INFO", "7f2a", "stage 05 adc done 0.012s · levels used 3711/4096"),
        ("14:22:06.925", "INFO", "7f2a", "stage 06 tune start ratio=0.890899 mode=drop"),
        ("14:22:06.981", "INFO", "7f29", "stage 08 dac done hold=zoh recon=off"),
        ("14:22:07.004", "INFO", "7f29", "stage 09 analog start ch=1 ladder fc=9.8k env=0.25"),
        ("14:22:07.016", "WARN", "reaper", "worker studio-mini:9031 heartbeat stale 47.2s"),
        ("14:22:07.017", "ERR ", "7f25", "ValueError: input SR 96000 not in supported set"),
        ("14:22:07.018", "INFO", "reaper", "7f25 → FAILED (attempt 1/3) · stream XACK"),
        ("14:22:07.051", "INFO", "api", "sse snapshot sent to 100.101.7.22 (iPhone)"),
        ("14:22:07.102", "INFO", "7f2a", "progress 06 tune 0.60"),
    ]
    for i, (ts, lv, src, msg) in enumerate(logs):
        ry = 666 + i * 20
        err = lv.startswith("ERR")
        if err:
            c.rect(lx + 12, ry - 14, lw - 24, 19, fill=T["fail_bg"])
        c.mono(lx + 20, ry, ts, 10.5, T["tx_lo"])
        c.mono(
            lx + 120, ry, lv, 10.5, T["fail"] if err else (T["tx_hi"] if lv == "WARN" else T["tx_lo"]), kind="mono_md"
        )
        c.mono(lx + 162, ry, src, 10.5, T["ac"] if src.startswith("7f") else T["tx_md"])
        c.mono(lx + 222, ry, msg, 10.5, T["fail"] if err else T["tx_hi"] if lv == "WARN" else T["tx_md"])
    c.save("03_jobs")


# --------------------------------------------------------------------------
# 04 A/B
# --------------------------------------------------------------------------


def screen_ab():
    c = Canvas(W_D, H_D)
    frame(c, 3, "A/B", "brk_dusty_92.wav · sp_break_45 · capture ×1.350 · tune -5")
    a = s_beat()
    b = mock_drum_path(a, tune=-5, capture=1.35, hi=False, drive=1.4)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]

    # transport
    c.panel(104, 68, 1320, 76, None, screws=False, c=10)
    # A/B rocker
    rx, ry = 124, 84
    c.rect(rx - 1, ry - 1, 130, 46, fill=T["bg0"])
    c.rect(rx, ry, 64, 44, fill=T["bg1"])
    c.text(rx + 32, ry + 24, "A", F("stencil", 22), T["tx_lo"], anchor="mm")
    c.metal(rx + 64, ry, 64, 44, T["bg4"], amp=3)
    c.rect(rx + 64, ry, 64, 3, fill=T["ac"])
    c.text(rx + 96, ry + 24, "B", F("stencil", 22), T["ac_hi"], anchor="mm")
    c.label(rx + 140, ry + 18, "DRY", 10.5, T["tx_lo"])
    c.label(rx + 140, ry + 36, "WET", 10.5, T["ac"])
    # play / stop / loop drawn as glyph shapes
    px = 330
    c.rect(px, ry, 44, 44, fill=T["bg3"], outline=T["line2"])
    c.d.polygon(c.pts([(px + 16, ry + 12), (px + 32, ry + 22), (px + 16, ry + 32)]), fill=T["ac_hi"])
    c.rect(px + 52, ry, 44, 44, fill=T["bg3"], outline=T["line2"])
    c.rect(px + 66, ry + 14, 16, 16, fill=T["tx_md"])
    c.rect(px + 104, ry, 44, 44, fill=T["ac_lo"], outline=T["ac"])
    c.text(px + 126, ry + 24, "LOOP", F("cond", 11), T["ac_hi"], anchor="mm", tracking=1)
    c.lcd_window(px + 168, ry, 176, 44)
    c.seg7(px + 182, ry + 9, 26, "0.812", gap=5)
    c.mono(px + 334, ry + 38, "s", 10, T["tx_lo"], anchor="rs")
    c.label(px + 360, ry + 18, "LEVEL MATCH", 10.5, T["tx_md"])
    c.toggle(px + 360, ry + 26, True)
    c.mono(px + 392, ry + 36, "-14.2 LUFS", 10.5, T["tx_hi"])
    # meters
    mx = 900
    for i, (lab, v) in enumerate([("A", 0.62), ("B", 0.71)]):
        my = ry + 6 + i * 20
        c.label(mx, my + 9, lab, 11, T["tx_lo"] if lab == "A" else T["ac"])
        for k in range(32):
            on = k / 32 < v
            col = (T["ac"] if k < 26 else T["ac_hi"]) if on else T["seg_off"]
            if lab == "A" and on:
                col = T["tx_lo"]
            c.rect(mx + 16 + k * 9, my, 7, 10, fill=col)
    c.mono(1404, ry + 18, "PEAK  -0.9", 10.5, T["tx_md"], anchor="rs")
    c.mono(1404, ry + 36, "PEAK  -0.3", 10.5, T["ac"], anchor="rs")

    # waveform overlay
    c.panel(104, 156, 1036, 214, "WAVEFORM", "1", tone="bg1", amp=1.3)
    c.lcd_window(118, 200, 1008, 152)
    c.waveform(122, 204, 1000, 144, a, hx("#3A4249"), grid=True)
    c.waveform(122, 204, 1000, 144, b, T["ac"], grid=False, center=False, gain=0.92)
    c.line(122 + 1000 * 0.31, 202, 122 + 1000 * 0.31, 350, T["ac_hi"], 1)
    for k in range(9):
        x = 122 + 1000 * k / 8
        c.mono(x, 366, f"{2.6 * k / 8:.2f}", 9, T["tx_lo"], anchor="ms" if 0 < k < 8 else ("ls" if k == 0 else "rs"))

    # spectrograms
    sw = 510
    for i, (lab, sig, sub) in enumerate([("A · SOURCE", a, "44.1k in"), ("B · RENDER", b, "48k out")]):
        x = 104 + i * (sw + 16)
        c.panel(x, 384, sw, 468, f"SPECTRUM {lab}", str(i + 2), tone="bg1", amp=1.3)
        c.mono(x + sw - 18, 407, sub, 10, T["tx_lo"], anchor="rs")
        gx, gy, gw, gh = x + 48, 428, sw - 66, 396
        c.lcd_window(gx - 2, gy - 2, gw + 4, gh + 4)
        c.spectrogram(gx, gy, gw, gh, sig, SR)
        for f in (0, 4, 8, 12, 16, 20, 24):
            fy = gy + gh - gh * f / 24
            c.line(gx - 6, fy, gx - 2, fy, T["tx_lo"])
            c.mono(gx - 9, fy + 3, f"{f}k", 9, T["tx_lo"], anchor="rs")
        if i == 1:
            # native Nyquist and the image band above it
            ny = gy + gh - gh * 13.02 / 24
            for k in range(0, int(gw), 8):
                c.line(gx + k, ny, gx + k + 4, ny, T["ac_hi"])
            c.mono(gx + gw - 6, ny - 6, "13.02k  NYQ 26.04k", 9.5, T["ac_hi"], anchor="rs")
            bx = gx + gw + 6
            c.line(bx, gy + 2, bx, ny - 2, T["ac"])
            c.line(bx - 3, gy + 2, bx, gy + 2, T["ac"])
            c.line(bx - 3, ny - 2, bx, ny - 2, T["ac"])
            c.text(bx - 10, gy + 18, "ZOH IMAGES", F("cond", 11), T["ac"], anchor="rs", tracking=1.5)

    # metrics
    mx, mw = 1156, 268
    c.panel(mx, 156, mw, 696, "DELTA", "Δ")
    c.label(mx + 120, 214, "A", 10.5, T["tx_lo"], anchor="rs")
    c.label(mx + 180, 214, "B", 10.5, T["ac"], anchor="rs")
    c.label(mx + mw - 16, 214, "Δ", 10.5, T["tx_md"], anchor="rs")
    c.hline_engraved(mx + 12, 222, mw - 24)
    rows = [
        ("PEAK", "-0.9", "-0.3", "+0.6"),
        ("RMS", "-14.8", "-13.1", "+1.7"),
        ("CREST", "13.9", "12.8", "-1.1"),
        ("CENTROID", "3.41k", "4.02k", "+0.61k"),
        (">13K E", "-41.0", "-27.6", "+13.4"),
        ("LEVELS", "—", "3488", "/4096"),
        ("LEN", "2.608", "2.611", "+3ms"),
    ]
    for i, (k, va, vb, dv) in enumerate(rows):
        y = 246 + i * 26
        c.label(mx + 16, y, k, 10.5, T["tx_md"])
        c.mono(mx + 120, y, va, 11, T["tx_lo"], anchor="rs")
        c.mono(mx + 180, y, vb, 11, T["ac_hi"], anchor="rs")
        c.mono(mx + mw - 16, y, dv, 11, T["tx_hi"], anchor="rs")
    c.hline_engraved(mx + 12, 434, mw - 24)
    c.label(mx + 16, 458, "PARAMS.JSON", 10.5, T["tx_lo"])
    c.lcd_window(mx + 14, 468, mw - 28, 222)
    js = [
        "{",
        '  "path": "sp",',
        '  "capture": 1.35,',
        '  "adc": {',
        '    "sr": 26041.6667,',
        '    "bits": 12,',
        '    "aa_fc": 12500  // HYP',
        "  },",
        '  "tune": -5,',
        '  "dac": "zoh",',
        '  "analog": {"ch": 1}',
        "}",
    ]
    for i, ln in enumerate(js):
        c.mono(mx + 24, 488 + i * 16.5, ln, 9.8, T["tx_lo"] if "HYP" in ln else T["tx_md"])
    c.label(mx + 16, 716, "FILES", 10.5, T["tx_lo"])
    for i, (fn, h_) in enumerate(
        [
            ("brk_dusty_92__…tune-5.wav", "c09e"),
            ("brk_dusty_92__…spectro.png", "77a1"),
            ("brk_dusty_92__…params.json", "a41f"),
        ]
    ):
        y = 738 + i * 19
        c.mono(mx + 16, y, fn, 10, T["tx_hi"])
        c.mono(mx + mw - 16, y, h_, 10, T["tx_lo"], anchor="rs")
    c.button(mx + 16, 800, mw - 32, 36, "DRAG OUT", "primary", size=13)
    c.save("04_ab")


# --------------------------------------------------------------------------
# 05 MOBILE (390 x 844)
# --------------------------------------------------------------------------


def screen_mobile():
    W, H = 390, 844
    c = Canvas(W, H)
    c.metal(0, 0, W, H, T["bg0"], amp=1.0, shade=0)
    # status bar area (system)
    c.mono(28, 30, "14:22", 13, T["tx_hi"], kind="mono_md")
    c.rect(W - 50, 20, 24, 11, outline=T["tx_md"])
    c.rect(W - 48, 22, 15, 7, fill=T["tx_md"])
    # header
    c.metal(0, 46, W, 56, T["bg2"], amp=2.6)
    c.line(0, 101, W, 101, T["bg0"])
    c.line(0, 102, W, 102, T["hl"])
    c.etext(16, 83, "1260", F("stencil", 24), T["tx_hi"])
    c.line(16, 90, 68, 90, T["ac_md"])
    c.vline_engraved(84, 62, 26)
    c.etext(98, 82, "JOBS", F("cond", 19), T["tx_hi"], tracking=3)
    c.led(W - 22, 74, True, r=3)
    c.mono(W - 32, 78, "tailnet", 10, T["tx_lo"], anchor="rs")

    # kpis
    y = 116
    kp = [("Q", "03", False), ("RUN", "02", False), ("WRK", "2/2", False), ("FAIL", "1", True)]
    kw = (W - 32 - 18) / 4
    for i, (k, v, bad) in enumerate(kp):
        x = 16 + i * (kw + 6)
        c.lcd_window(x, y, kw, 54)
        c.label(x + 8, y + 14, k, 9.5, T["fail"] if bad else T["tx_lo"])
        if "/" in v:
            c.seg7(x + 10, y + 22, 22, "2", gap=3)
            c.mono(x + 30, y + 44, "/2", 11, T["tx_md"])
        else:
            c.seg7(x + kw - 10 - len(v) * 15, y + 22, 22, v, gap=3, on=T["fail"] if bad else None)

    def job_card(y, jid, smp, pre, stage, done, part, failed=None, st="RUN", el="0.41s", h=118):
        c.panel(16, y, W - 32, h, None, screws=False, c=8, tone="bg2")
        if failed is not None:
            c.rect(17, y + 8, 3, h - 16, fill=T["fail"])
        elif st == "RUN":
            c.rect(17, y + 8, 3, h - 16, fill=T["ac"])
        c.mono(30, y + 24, jid, 10.5, T["tx_lo"])
        c.mono(64, y + 24, smp, 12, T["tx_hi"], kind="mono_md")
        state_chip(c, W - 72, y + 12, st)
        c.mono(30, y + 42, pre, 10, T["tx_md"])
        c.mono(W - 32, y + 42, el, 10, T["tx_md"], anchor="rs")
        c.text(30, y + 72, stage, F("cond", 22), T["fail"] if failed is not None else T["ac_hi"], tracking=2)
        if failed is None and st == "RUN":
            c.mono(W - 32, y + 72, f"{int((done + part) * 10)}%", 13, T["tx_hi"], anchor="rs", kind="mono_md")
        c.seg_progress(30, y + 86, W - 62, 12, 10, done, part, failed, dim=st == "OK")
        for k, s_ in enumerate(STAGES_A):
            if k % 3 == 0 or k == 9:
                sx = 30 + k * ((W - 62 + 2) / 10)
                c.mono(sx, y + 111, s_, 7.5, T["tx_lo"])

    job_card(184, "7f2a", "snare_04_crack.wav", "sp_snare_hard · tune -2", "06  TUNE", 5, 0.6)
    job_card(312, "7f29", "kick_01_boom.wav", "sp_kick_low · tune -1", "09  ANALOG", 8, 0.3, el="0.62s")
    job_card(
        440,
        "7f25",
        "snare_07_layer.wav",
        "ValueError @ 05 ADC",
        "FAIL  05 ADC",
        4,
        0,
        failed=4,
        st="FAIL",
        el="0.18s",
        h=162,
    )
    c.button(30, 562, 150, 32, "RETRY", "primary", size=12)
    c.button(190, 562, W - 220, 32, "TRACE", "normal", size=12)

    # queue rows
    y = 618
    c.label(16, y, "QUEUED", 10.5, T["tx_md"], tracking=2.2)
    c.hline_engraved(16, y + 8, W - 32)
    for i, (jid, smp, pre) in enumerate(
        [
            ("7f28", "brk_dusty_92.wav", "sp_break_45"),
            ("7f27", "loop_rhodes_92.wav", "mpc_nl_pwl"),
            ("7f26", "hat_c_02.wav", "sp_hat_air"),
        ]
    ):
        ry = y + 32 + i * 26
        c.mono(16, ry, jid, 10.5, T["tx_lo"])
        c.mono(54, ry, smp, 11, T["tx_hi"])
        c.mono(W - 16, ry, pre, 9.5, T["tx_lo"], anchor="rs")

    # tab bar
    c.metal(0, H - 78, W, 78, T["bg1"], amp=2)
    c.line(0, H - 78, W, H - 78, T["line"])
    tabs = ["JOBS", "WORKERS", "LOG"]
    tw = W / 3
    for i, t_ in enumerate(tabs):
        act = i == 0
        if act:
            c.rect(i * tw + 20, H - 78, tw - 40, 2, fill=T["ac"])
        c.label(
            i * tw + tw / 2, H - 46, t_, 13, T["ac_hi"] if act else T["tx_md"], anchor="ms", tracking=2.4, kind="cond"
        )
        c.led(i * tw + tw / 2, H - 34, act, r=2)
    c.rect(W / 2 - 67, H - 13, 134, 5, fill=T["tx_md"])  # home indicator
    c.save("05_mobile_progress")


# --------------------------------------------------------------------------
# 06 COMPONENT SHEET (tokens, type, states) — reference for design.md
# --------------------------------------------------------------------------


def screen_components():
    c = Canvas(W_D, H_D)
    c.metal(0, 0, W_D, H_D, T["bg0"], amp=1.0, shade=0)
    c.etext(32, 52, "1260", F("stencil", 30), T["tx_hi"])
    c.etext(124, 50, "COMPONENT SHEET", F("cond", 20), T["tx_md"], tracking=4)
    c.mono(W_D - 32, 48, "phase 0 · not a screen", 10, T["tx_lo"], anchor="rs")
    c.hline_engraved(32, 66, W_D - 64)

    # colour tokens
    c.panel(32, 84, 440, 392, "TOKENS", "01")
    names = [
        "bg0",
        "bg1",
        "bg2",
        "bg3",
        "bg4",
        "line",
        "line2",
        "metal",
        "tx_hi",
        "tx_md",
        "tx_lo",
        "tx_xlo",
        "ac_xlo",
        "ac_lo",
        "ac_md",
        "ac",
        "ac_hi",
        "seg_off",
        "fail_bg",
        "fail",
    ]
    for i, n in enumerate(names):
        col, row = i % 2, i // 2
        x, y = 48 + col * 210, 130 + row * 33
        c.rect(x - 1, y - 1, 34, 24, fill=T["bg0"])
        c.rect(x, y, 32, 22, fill=T[n])
        c.mono(x + 42, y + 10, n, 10.5, T["tx_hi"])
        c.mono(x + 42, y + 22, "#{:02X}{:02X}{:02X}".format(*T[n]), 9, T["tx_lo"])

    # type
    c.panel(488, 84, 440, 392, "TYPE", "02")
    c.text(504, 158, "1260 STENCIL", F("stencil", 30), T["tx_hi"])
    c.mono(504, 176, "Saira Stencil One · logo, path letters, drop zone", 9.5, T["tx_lo"])
    c.text(504, 220, "CHAIN  DRUM PATH", F("cond", 22), T["tx_hi"], tracking=4)
    c.mono(504, 238, "Barlow Condensed SemiBold · titles, stage names (+tracking)", 9.5, T["tx_lo"])
    c.label(504, 274, "freq  gain  order  heartbeat", 12, T["tx_md"])
    c.mono(504, 292, "Barlow Condensed Medium · UPPERCASE labels 10.5–12", 9.5, T["tx_lo"])
    c.mono(504, 330, "26041.67  +11.0 dB  a41f…09c2", 13, T["tx_hi"])
    c.mono(504, 348, "IBM Plex Mono · every value, id, path, log", 9.5, T["tx_lo"])
    c.lcd_window(504, 364, 150, 56)
    c.seg7(518, 372, 40, "-2")
    c.seg7(580, 382, 24, "1.35", gap=4)
    c.mono(668, 396, "7-SEG (drawn) · TUNE, counts", 9.5, T["tx_lo"])
    c.text(504, 456, "ガン突き  ちょい歪み", F("jp", 12), T["tx_md"])
    c.mono(680, 456, "JP: owner words only", 9.5, T["tx_lo"])

    # buttons
    c.panel(944, 84, 464, 392, "BUTTON STATES", "03")
    states = [
        ("normal", "SAVE"),
        ("hover", "FORK"),
        ("primary", "RENDER"),
        ("running", "RENDERING"),
        ("failed", "FAILED"),
        ("disabled", "RENDER"),
    ]
    for i, (st, lab) in enumerate(states):
        col, row = i % 2, i // 2
        x, y = 960 + col * 220, 130 + row * 70
        c.button(x, y, 200, 38, lab, st)
        c.mono(x, y + 54, st, 9.5, T["tx_lo"])
    c.label(960, 352, "CHIPS", 10.5, T["tx_lo"])
    for i, st in enumerate(["RUN", "QUE", "OK", "FAIL", "CXL", "LOST"]):
        state_chip(c, 960 + i * 50, 362, st)
    c.label(960, 412, "TAGS", 10.5, T["tx_lo"])
    c.tag(960, 420, "VER")
    c.mono(988, 430, "sourced", 9.5, T["tx_md"])
    c.tag(1060, 420, "HYP")
    c.mono(1088, 430, "hypothesis · calibratable", 9.5, T["tx_md"])

    # controls
    c.panel(32, 492, 660, 376, "CONTROLS", "04")
    c.slider(48, 540, 180, "GAIN", "+11.0 dB", 0.92, bipolar=True)
    c.slider(248, 540, 180, "AA FC", "12.5k", 0.7, tag="HYP")
    c.slider(448, 540, 180, "DECAY", "—", 0.5, dim=True)
    c.mono(48, 592, "slider · bipolar", 9.5, T["tx_lo"])
    c.mono(248, 592, "slider · hypothesis param", 9.5, T["tx_lo"])
    c.mono(448, 592, "slider · stage bypassed", 9.5, T["tx_lo"])
    c.seg(48, 612, 300, 26, ["KCK", "SNR", "HAT", "PRC", "OTH"], 1)
    c.seg(368, 612, 260, 26, ["48000", "44100", "NATIVE"], 0, mono=True, size=11)
    c.toggle(48, 662, True)
    c.mono(78, 672, "on", 9.5, T["tx_lo"])
    c.toggle(118, 662, False)
    c.mono(148, 672, "bypass", 9.5, T["tx_lo"])
    c.led(220, 668, True)
    c.led(240, 668, False)
    c.mono(254, 672, "led", 9.5, T["tx_lo"])
    c.screw(300, 668)
    c.mono(312, 672, "screw (TR + BL only)", 9.5, T["tx_lo"])
    c.label(48, 712, "STAGE PROGRESS", 10.5, T["tx_lo"])
    c.seg_progress(48, 722, 300, 10, 10, 5, 0.6)
    c.mono(360, 731, "running", 9.5, T["tx_lo"])
    c.seg_progress(48, 744, 300, 10, 10, 4, 0, failed=4)
    c.mono(360, 753, "failed @05", 9.5, T["tx_lo"])
    c.seg_progress(48, 766, 300, 10, 10, 10, 0, dim=True)
    c.mono(360, 775, "done", 9.5, T["tx_lo"])
    c.label(48, 812, "CHAIN DIVIDER", 10.5, T["tx_lo"])
    c.chain_h(48, 640, 832)
    c.chain_v(672, 520, 856)

    # panel anatomy
    c.panel(708, 492, 700, 376, "PANEL ANATOMY", "05")
    c.panel(732, 548, 300, 160, "TITLE", "A")
    c.mono(748, 600, "chamfer TL + BR = 10", 10, T["tx_md"])
    c.mono(748, 618, "hairline metal fill", 10, T["tx_md"])
    c.mono(748, 636, "1px dark outline, light top bevel", 10, T["tx_md"])
    c.mono(748, 654, "engraved rule under title", 10, T["tx_md"])
    c.mono(748, 672, "screws at TR and BL", 10, T["tx_md"])
    stage_box(c, 1060, 548, 330, 62, "06", "TUNE", "drop-sample", sel=True, spine_x=1046)
    stage_box(c, 1060, 620, 330, 62, "07", "VOL ENV", "8-bit steps", on=False, spine_x=1046)
    c.chain_v(1046, 540, 700, color=hx("#2A3138"))
    c.mono(1060, 702, "stage: selected / bypassed", 9.5, T["tx_lo"])
    c.lcd_window(732, 730, 300, 110)
    c.waveform(736, 734, 292, 102, s_snare(5), T["ac"])
    c.mono(1060, 760, "LCD window = any live readout:", 10, T["tx_md"])
    c.mono(1060, 778, "waveform, spectrum, 7-seg, trace", 10, T["tx_md"])
    c.mono(1060, 812, "glow: blur 5px · 32% · lit only", 10, T["tx_lo"])
    c.save("06_components")


SCREENS = {
    "library": screen_library,
    "chain": screen_chain,
    "jobs": screen_jobs,
    "ab": screen_ab,
    "mobile": screen_mobile,
    "components": screen_components,
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--hires" in args:
        HIRES = True
        args.remove("--hires")
    names = args or list(SCREENS)
    for nm in names:
        SCREENS[nm]()

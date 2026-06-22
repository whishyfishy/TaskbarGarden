"""Generate the app icon (desktop_cat/app_icon.ico) — a clean, simple
custom mark: a friendly cat face on the app's warm-dark rounded badge.

Run:  py -3.12 tools/make_icon.py

Produces a multi-resolution .ico (16/24/32/48/64/128/256) so Windows picks
the crispest size for the titlebar, taskbar, and alt-tab.  Drawn as vector
geometry (supersampled then downscaled) so it stays sharp at every size,
unlike upscaling a 16px sprite.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw


# Brand palette — matches the island pill / hub accent.
_BG_TOP   = (38, 36, 33)     # warm near-black
_BG_BOT   = (28, 27, 25)
_ACCENT   = (111, 140, 214)  # #6f8cd6 accent blue (ear inner / collar)
_FUR      = (243, 239, 231)  # warm off-white (Sao is a pale cat)
_FUR_SH   = (214, 208, 196)  # soft shadow side
_FACE     = (45, 43, 40)     # eyes / nose / mouth lines


def _rounded_badge(d: ImageDraw.ImageDraw, size: int) -> None:
    """Warm rounded-square badge background with a subtle vertical shade."""
    r = int(size * 0.22)
    # Vertical gradient by drawing horizontal bands.
    for y in range(size):
        t = y / max(1, size - 1)
        col = tuple(int(_BG_TOP[i] + (_BG_BOT[i] - _BG_TOP[i]) * t) for i in range(3))
        d.line([(0, y), (size, y)], fill=col + (255,))
    # Punch the rounded-rect mask: redraw corners transparent.
    mask = Image.new('L', (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return mask


def _draw_cat(size: int) -> Image.Image:
    """Render the PAW mark at `size` px (RGBA): a chunky main pad plus
    four toe beans, in warm off-white on the rounded badge."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mask = _rounded_badge(d, size)

    cx = size / 2
    paw = _FUR + (255,)

    def bean(ccx: float, ccy: float, w: float, h: float) -> None:
        d.ellipse([ccx - w / 2, ccy - h / 2, ccx + w / 2, ccy + h / 2], fill=paw)

    # Main pad — a rounded triangle-ish blob, lower-center.
    pad_w = size * 0.46
    pad_h = size * 0.40
    pad_cy = size * 0.62
    # Build the pad as an overlapping cluster of ellipses for a soft,
    # organic "bean" shape (a single ellipse reads too plain).
    bean(cx, pad_cy, pad_w, pad_h)
    bean(cx - pad_w * 0.26, pad_cy + pad_h * 0.10, pad_w * 0.55, pad_h * 0.78)
    bean(cx + pad_w * 0.26, pad_cy + pad_h * 0.10, pad_w * 0.55, pad_h * 0.78)
    bean(cx, pad_cy - pad_h * 0.20, pad_w * 0.72, pad_h * 0.70)

    # Four toe beans arcing above the pad.  Outer two sit lower + smaller,
    # inner two higher + a touch bigger — the classic paw silhouette.
    toe_w = size * 0.20
    toe_h = size * 0.23
    toe_y = size * 0.33
    specs = [
        (cx - size * 0.255, toe_y + size * 0.045, 0.86),   # far left
        (cx - size * 0.085, toe_y - size * 0.025, 1.0),    # inner left
        (cx + size * 0.085, toe_y - size * 0.025, 1.0),    # inner right
        (cx + size * 0.255, toe_y + size * 0.045, 0.86),   # far right
    ]
    for tx, ty, scl in specs:
        bean(tx, ty, toe_w * scl, toe_h * scl)

    # Apply the rounded-badge mask so corners are clipped.
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(here, 'desktop_cat', 'app_icon.ico')
    # Supersample at 256 then let Pillow build all the .ico sizes from it.
    SS = 256
    master = _draw_cat(SS)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48),
             (64, 64), (128, 128), (256, 256)]
    master.save(out_path, format='ICO', sizes=sizes)
    # Also drop a PNG preview for quick eyeballing.
    master.save(os.path.join(here, 'desktop_cat', 'app_icon.png'))
    print(f'wrote {out_path}  ({", ".join(f"{w}" for w, _ in sizes)})')


if __name__ == '__main__':
    main()

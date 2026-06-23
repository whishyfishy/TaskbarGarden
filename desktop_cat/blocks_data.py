"""
Placeable blocks — a tiny 2D-Minecraft layer.  The user enters "block mode"
(hub toggle), and clicks place SQUARE blocks on a perfect, gap-free grid.  Two
styles (dirt-with-grass-top / grassy-all-around), R switches.  Blocks become
collision platforms Sao can stand and jump on, and fade in/out by how close she
is.  Saved to blocks.json at the project root.

Grid: square cells of BLOCK_SIZE px.  Columns are anchored at x=0; rows are
anchored to the floor so row 0's bottom sits exactly on the taskbar top.  A cell
(c, r) therefore occupies a perfect, gapless square — no spaced-out rows.
"""
from __future__ import annotations

import json
import math
import os

BLOCK_SIZE: int   = 22       # square cell = block size (logical px); gap-free grid
TORCH_RADIUS: int = 116      # px — the grid only shows within this of the cursor
# Proximity fade: distance from Sao's centre to a block's centre.
BLOCK_FADE_NEAR: int = 80    # within this → fully opaque
BLOCK_FADE_FAR:  int = 168   # beyond this → fully invisible
# Sentinel hwnd base so blocks slot into the collision Platform system without
# clashing with real (positive) or bottom-edge (down to ~-2**32) hwnds.
BLOCK_HWND_BASE: int = -(1 << 33)
MAX_BLOCKS: int = 400        # safety cap on placements

STYLE_DIRT  = 0   # brown dirt body + green grass cap on top
STYLE_GRASS = 1   # grassy all around

_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'blocks.json',
)


def cell_at(px: float, py: float, floor: int) -> tuple[int, int]:
    """Grid cell (col, row) containing screen point (px, py)."""
    c = math.floor(px / BLOCK_SIZE)
    r = math.floor((floor - py) / BLOCK_SIZE)
    return (c, r)


def cell_rect(c: int, r: int, floor: int) -> tuple[int, int, int, int]:
    """Pixel rect (x, y, w, h) of cell (c, r).  Row 0 sits on the floor."""
    x = c * BLOCK_SIZE
    y = floor - (r + 1) * BLOCK_SIZE
    return (x, y, BLOCK_SIZE, BLOCK_SIZE)


def cell_center(c: int, r: int, floor: int) -> tuple[float, float]:
    x, y, w, h = cell_rect(c, r, floor)
    return (x + w / 2.0, y + h / 2.0)


def block_hwnd(c: int, r: int) -> int:
    """A stable, unique negative hwnd for a cell, for collision platforms."""
    key = (c + 100000) * 1000000 + (r + 100000) + 1
    return BLOCK_HWND_BASE - key


def is_block_hwnd(hwnd: int) -> bool:
    return hwnd < BLOCK_HWND_BASE


def load_blocks() -> dict:
    """Return {(c, r): style}."""
    try:
        with open(_SAVE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            out = {}
            for b in data:
                if isinstance(b, dict) and 'c' in b and 'r' in b:
                    out[(int(b['c']), int(b['r']))] = int(b.get('style', 0)) & 1
            return out
    except (OSError, ValueError, TypeError):
        pass
    return {}


def save_blocks(blocks: dict) -> None:
    """Persist {(c, r): style}."""
    try:
        payload = [{'c': c, 'r': r, 'style': int(s)} for (c, r), s in blocks.items()]
        tmp = _SAVE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        os.replace(tmp, _SAVE_PATH)
    except OSError:
        pass

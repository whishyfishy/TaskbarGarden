"""Sticky-note persistence.

Source of truth lives in desktop_cat/stickies.json so the React Library
Hub AND the Python StickyManager can both read + write.

A sticky shape:
    {
      'id':            str,         # stable, generated React-side
      'title':         str,         # short header label (often empty)
      'body':          str,         # the actual note text
      'color':         str,         # hex, e.g. '#fef3a8'
      'pinned':        bool,        # when True, a floating window is shown
      # ── pin-only fields (only meaningful when pinned == True) ───────
      'pin_x':         int,         # screen position (logical pixels)
      'pin_y':         int,
      'pin_w':         int,         # window size
      'pin_h':         int,
      'fade_strength': float,       # 0.0..1.0; 0=never fade, 1=fade to ~30%
    }

Defaults applied at load time so older saves missing the pin-only fields
don't blow up.
"""
from __future__ import annotations

import json
import os
from typing import Any


_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'stickies.json',
)


_DEFAULTS: dict[str, Any] = {
    'title':         '',
    'body':          '',          # plain-text (rendered in the hub)
    'body_html':     '',          # rich HTML if floating-window formatted
    'body_font_pt':  12,          # base font size in the floating window
    'color':         '#fef3a8',   # warm-yellow stickie default
    'pinned':        False,
    'pin_x':         220,
    'pin_y':         140,
    'pin_w':         220,
    'pin_h':         180,
    'fade_strength': 0.0,
}


def _coerce(s: dict) -> dict:
    """Apply defaults + clamp numeric fields to safe ranges."""
    out: dict[str, Any] = {}
    for k, default in _DEFAULTS.items():
        out[k] = s.get(k, default) if isinstance(s, dict) else default
    out['id'] = str(s.get('id', '')) if isinstance(s, dict) else ''
    if not out['id']:
        # No id is unusable; caller should drop these.
        return {}
    try:
        out['pin_x'] = int(out['pin_x'])
        out['pin_y'] = int(out['pin_y'])
        out['pin_w'] = max(120, int(out['pin_w']))
        out['pin_h'] = max(100, int(out['pin_h']))
    except (TypeError, ValueError):
        out['pin_x'], out['pin_y'] = 220, 140
        out['pin_w'], out['pin_h'] = 220, 180
    try:
        out['fade_strength'] = max(0.0, min(1.0, float(out['fade_strength'])))
    except (TypeError, ValueError):
        out['fade_strength'] = 0.0
    try:
        out['body_font_pt'] = max(8, min(36, int(out['body_font_pt'])))
    except (TypeError, ValueError):
        out['body_font_pt'] = 12
    out['pinned']    = bool(out['pinned'])
    out['title']     = str(out['title']     or '')
    out['body']      = str(out['body']      or '')
    out['body_html'] = str(out['body_html'] or '')
    out['color']     = str(out['color']     or '#fef3a8')
    return out


def load() -> list[dict]:
    try:
        with open(_SAVE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        print(f'[stickies_data] load failed: {e}')
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for s in data:
        if not isinstance(s, dict):
            continue
        c = _coerce(s)
        if c:
            out.append(c)
    return out


def save(stickies: list[dict]) -> None:
    """Write the full sticky list to disk.  Logs (instead of silently
    swallowing) on failure so the user sees errors in the console.
    Writes via a tmp+replace so a crash mid-write can't corrupt the file."""
    try:
        payload = [_coerce(s) for s in stickies if isinstance(s, dict)]
        tmp_path = _SAVE_PATH + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, _SAVE_PATH)
    except OSError as e:
        print(f'[stickies_data] save failed: {e}')


def patch_one(sticky_id: str, **fields) -> None:
    """Apply a partial update to one sticky on disk.  Used by the floating
    window when the user edits text / drags / resizes / changes color."""
    if not sticky_id:
        return
    data = load()
    changed = False
    for s in data:
        if s.get('id') == sticky_id:
            for k, v in fields.items():
                if s.get(k) != v:
                    s[k] = v
                    changed = True
            break
    if changed:
        save(data)


def mtime() -> float:
    try:
        return os.path.getmtime(_SAVE_PATH)
    except OSError:
        return 0.0

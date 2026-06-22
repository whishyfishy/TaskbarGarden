"""
Decor data — persistent rocks + shrubs (grass tufts / bushes).

These were being regenerated randomly every session, so the user's
desktop scene would shuffle around on every launch.  Now we save the
positions + variants to ``decor.json`` at the project root so the layout
stays consistent until the user explicitly resets it.

Schema::

    {
      "rocks":  [{"x": int, "variant": 0|1}, ...],
      "shrubs": [{"x": int, "variant": int, "bush_style": bool}, ...]
    }

``y`` is intentionally NOT saved — it's always the current ``screen_floor``
and is re-applied at load time, so the decor follows the taskbar height
across machines / monitor changes.
"""
from __future__ import annotations

import json
import os

_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'decor.json',
)


def load() -> dict | None:
    """Return ``{'rocks': [...], 'shrubs': [...]}`` or ``None`` if there's
    no save file yet (caller should generate fresh decor + call ``save``)."""
    try:
        with open(_SAVE_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rocks = data.get('rocks')
    shrubs = data.get('shrubs')
    if not isinstance(rocks, list) or not isinstance(shrubs, list):
        return None
    # Sanitize — drop malformed entries, coerce types.
    clean_rocks = []
    for r in rocks:
        if not isinstance(r, dict):
            continue
        try:
            clean_rocks.append({
                'x':       int(r.get('x', 0)),
                'variant': 1 if int(r.get('variant', 0)) == 1 else 0,
            })
        except (ValueError, TypeError):
            continue
    clean_shrubs = []
    for s in shrubs:
        if not isinstance(s, dict):
            continue
        try:
            clean_shrubs.append({
                'x':          int(s.get('x', 0)),
                'variant':    int(s.get('variant', 0)),
                'bush_style': bool(s.get('bush_style', False)),
            })
        except (ValueError, TypeError):
            continue
    return {'rocks': clean_rocks, 'shrubs': clean_shrubs}


def save(rocks: list, shrubs: list) -> None:
    """Persist the current decor positions.  ``rocks`` is a list of ``Rock``
    dataclasses and ``shrubs`` is a list of ``Shrub`` dataclasses — we just
    read ``.x`` / ``.variant`` / ``.bush_style`` off each."""
    try:
        payload = {
            'rocks': [
                {'x': int(r.x), 'variant': int(getattr(r, 'variant', 0))}
                for r in rocks
            ],
            'shrubs': [
                {
                    'x':          int(s.x),
                    'variant':    int(getattr(s, 'variant', 0)),
                    'bush_style': bool(getattr(s, 'bush_style', False)),
                }
                for s in shrubs
            ],
        }
        with open(_SAVE_PATH, 'w') as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass

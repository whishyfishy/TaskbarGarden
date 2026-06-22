"""Persistent settings for the dynamic island pill.

Lives in desktop_cat/island.json.  Settings panel reads/writes via the
bridge; the island itself watches mtime to react to live changes.
"""
from __future__ import annotations

import json
import os
from typing import Any


_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'island.json',
)

_DEFAULTS: dict[str, Any] = {
    'enabled':        False,    # pill hidden by default — enable it in Settings
    # Anchor edge: 'top' | 'left' | 'right'.  The pill always docks to
    # one of these — it can't float in the middle of the screen.
    'anchor':         'top',
    # Position along the anchor edge.  For 'top' this is x; for 'left'
    # and 'right' it's y.  Defaults to centered on the anchor.
    'edge_pos':       -1,         # -1 = not yet placed; island picks center
    'hidden':         False,      # True if the user has tucked the pill against its anchor
    'pinned':         True,       # default True — pill stays expanded at top.  Drag-down to unpin.
    'click_through':  False,
    'hide_fullscreen': True,
    # Pomodoro focus-timer length in minutes.  Edited from the hub
    # settings window (NOT from inside the pill).  The timer lane reads
    # this on construction and whenever prefs hot-reload.
    'pomodoro_minutes': 25,
    # Plain (non-pomodoro) quick-timer length in minutes, also set from
    # the window.  Used when the user starts a "simple timer".
    'timer_minutes': 5,
    # Which timer mode the pill should run: 'pomodoro' | 'timer'.  Set
    # from the window; the pill displays + runs whatever is active.
    'timer_mode': 'pomodoro',
    # A monotonic counter the window bumps to tell the running pill
    # "(re)start the active timer now".  The pill watches this via the
    # prefs mtime poll and starts a fresh countdown when it changes.
    'timer_start_token': 0,
    # Bumped by the window to tell the running pill "reset + pause now".
    'timer_stop_token': 0,
    'lanes': {
        # Timer-focused pill: the timer is the main display; next_task is
        # the brief due-assignment popup.  (music/clipboard/due_today
        # lanes were removed.)
        'timer':      True,
        'next_task':  True,
    },
}


def load() -> dict[str, Any]:
    try:
        with open(_SAVE_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return dict(_DEFAULTS, lanes=dict(_DEFAULTS['lanes']))
    if not isinstance(d, dict):
        return dict(_DEFAULTS, lanes=dict(_DEFAULTS['lanes']))
    out = dict(_DEFAULTS, lanes=dict(_DEFAULTS['lanes']))
    for k in _DEFAULTS:
        if k == 'lanes':
            v = d.get('lanes')
            if isinstance(v, dict):
                for lk in out['lanes']:
                    if lk in v:
                        out['lanes'][lk] = bool(v[lk])
        elif k in d:
            out[k] = d[k]
    return out


def save(state: dict[str, Any]) -> None:
    try:
        tmp = _SAVE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, _SAVE_PATH)
    except OSError as e:
        print(f'[island_data] save failed: {e}')


def patch(**fields) -> None:
    s = load()
    for k, v in fields.items():
        if k == 'lanes' and isinstance(v, dict):
            s.setdefault('lanes', {}).update(v)
        else:
            s[k] = v
    save(s)


def mtime() -> float:
    try:
        return os.path.getmtime(_SAVE_PATH)
    except OSError:
        return 0.0

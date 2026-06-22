"""
Inventory — persistent wallet and seed bag for Sao's garden economy.

Currencies:
  coins    — misc economy; buy macron seeds, username
  macrons  — harvested from macron plants (only grow during Pomodoro)
             used to buy crop seeds

Seeds (items in bag, not yet planted):
  flower_seeds, macron_seeds
"""
from __future__ import annotations

import json
import os

_SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inventory.json')

# Caps: max planted at once in the garden
FLOWER_PLANT_CAP  = 7
MACRON_PLANT_CAP  = 1

# Legacy caps kept so any old save-loading code doesn't NameError
CARROT_PLANT_CAP  = 0
POTATO_PLANT_CAP  = 0

# Seed bag cap
FLOWER_SEED_CAP   = FLOWER_PLANT_CAP * 3
MACRON_SEED_CAP   = MACRON_PLANT_CAP * 3

# First-run gift seeds
FIRST_RUN_FLOWER_SEEDS = 1
FIRST_RUN_MACRON_SEEDS = 1

_DEFAULTS: dict = {
    'coins':        0,
    'macrons':      0,
    'flower_seeds': FIRST_RUN_FLOWER_SEEDS,
    'macron_seeds': FIRST_RUN_MACRON_SEEDS,
}

_VALID_KEYS = set(_DEFAULTS)

# ── Bug roster ────────────────────────────────────────────────────────────
# Restored after the gamification pivot so main.py can read
# abug_slots / bbug_slots and spawn the ladybug + friend bug sprites again.
# The slots default to including one ladybug (abug1) + one friend bug
# (abug3) so users see both critters out of the box, no purchasing UI.
ABUG_KINDS = ['abug1', 'abug2', 'abug3']   # abug1=ladybug, abug3=friend bug
BBUG_KINDS = ['bbug1', 'bbug2', 'bbug3']
ABUG_SLOT_COUNT = 4
BBUG_SLOT_COUNT = 2

_DEFAULT_ABUG_SLOTS = ['abug1', 'abug3', None, None]
_DEFAULT_BBUG_SLOTS = [None, None]


def _coerce_bug_slots(raw: dict) -> dict:
    """Pull abug_slots / bbug_slots out of the raw JSON, sanitize lengths
    and values.  Anything unrecognised becomes None so the renderer skips it."""
    out = {}
    a = raw.get('abug_slots')
    if isinstance(a, list):
        out['abug_slots'] = [(v if v in ABUG_KINDS else None) for v in a[:ABUG_SLOT_COUNT]]
        while len(out['abug_slots']) < ABUG_SLOT_COUNT:
            out['abug_slots'].append(None)
    else:
        out['abug_slots'] = list(_DEFAULT_ABUG_SLOTS)
    b = raw.get('bbug_slots')
    if isinstance(b, list):
        out['bbug_slots'] = [(v if v in BBUG_KINDS else None) for v in b[:BBUG_SLOT_COUNT]]
        while len(out['bbug_slots']) < BBUG_SLOT_COUNT:
            out['bbug_slots'].append(None)
    else:
        out['bbug_slots'] = list(_DEFAULT_BBUG_SLOTS)
    return out


def load() -> dict:
    try:
        with open(_SAVE_PATH) as f:
            raw = json.load(f)
        out = dict(_DEFAULTS)
        for k, v in raw.items():
            if k in _VALID_KEYS:
                try:
                    out[k] = int(v)
                except (ValueError, TypeError):
                    pass
        out.update(_coerce_bug_slots(raw))
        return out
    except (OSError, ValueError, TypeError):
        out = dict(_DEFAULTS)
        out['abug_slots'] = list(_DEFAULT_ABUG_SLOTS)
        out['bbug_slots'] = list(_DEFAULT_BBUG_SLOTS)
        return out


def save(inv: dict) -> None:
    try:
        clean = {k: max(0, int(inv.get(k, _DEFAULTS.get(k, 0)))) for k in _DEFAULTS}
        # Persist bug slot rosters so the ladybug / friend bug stays after restart.
        bug = _coerce_bug_slots({
            'abug_slots': inv.get('abug_slots', _DEFAULT_ABUG_SLOTS),
            'bbug_slots': inv.get('bbug_slots', _DEFAULT_BBUG_SLOTS),
        })
        clean.update(bug)
        with open(_SAVE_PATH, 'w') as f:
            json.dump(clean, f)
    except OSError:
        pass


def add_coins(inv: dict, n: int = 1) -> None:
    inv['coins'] = inv.get('coins', 0) + n


def spend_coins(inv: dict, n: int) -> bool:
    if inv.get('coins', 0) >= n:
        inv['coins'] -= n
        return True
    return False


def add_macrons(inv: dict, n: int = 1) -> None:
    inv['macrons'] = inv.get('macrons', 0) + n


def spend_macrons(inv: dict, n: int) -> bool:
    if inv.get('macrons', 0) >= n:
        inv['macrons'] -= n
        return True
    return False


def add_seed(inv: dict, seed_type: str, n: int = 1) -> bool:
    """Add n seeds of the given type. Returns False if bag is already full."""
    cap_map = {
        'flower_seeds': FLOWER_SEED_CAP,
        'macron_seeds': MACRON_SEED_CAP,
    }
    key = seed_type if seed_type.endswith('_seeds') else f'{seed_type}_seeds'
    cap = cap_map.get(key, 999)
    current = inv.get(key, 0)
    if current >= cap:
        return False
    inv[key] = min(current + n, cap)
    return True


def use_seed(inv: dict, seed_type: str) -> bool:
    """Consume 1 seed of given type. Returns False if none left."""
    key = seed_type if seed_type.endswith('_seeds') else f'{seed_type}_seeds'
    if inv.get(key, 0) > 0:
        inv[key] -= 1
        return True
    return False

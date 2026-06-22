"""
Persistent user profile for Desktop Cat.
Stores first-run onboarding answers (who the user is, what they named
their little companion, skin + personality). Kept deliberately tiny.
"""

import json
import os

_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'user_profile.json',
)

SKIN_TONES: list[tuple[str, tuple[int, int, int]]] = [
    ('pale',  (252, 230, 210)),
    ('cream', (244, 210, 180)),
    ('peach', (232, 182, 148)),
    ('tan',   (206, 152, 112)),
    ('brown', (148,  98,  68)),
    ('white', (245, 245, 245)),
    ('gray',  (188, 188, 188)),
    ('mint',  (186, 228, 196)),
]

PERSONALITIES: list[str] = ['calm', 'medium', 'active']

_DEFAULTS: dict = {
    'onboarded':    False,
    'user_name':    '',
    'char_name':    'sao',
    'skin_color':   'cream',
    'personality':  'medium',
}


def load() -> dict:
    try:
        with open(_SAVE_PATH) as f:
            raw = json.load(f)
        out = dict(_DEFAULTS)
        for k, v in raw.items():
            if k in out:
                out[k] = v
        return out
    except (OSError, ValueError):
        return dict(_DEFAULTS)


def save(profile: dict) -> None:
    try:
        clean = {k: profile.get(k, v) for k, v in _DEFAULTS.items()}
        with open(_SAVE_PATH, 'w') as f:
            json.dump(clean, f)
    except OSError:
        pass


def is_onboarded() -> bool:
    return bool(load().get('onboarded'))


# ── Profile reset ──────────────────────────────────────────────────────────
# All persistent JSON state owned by the app, listed by basename.  Anything
# the user might want wiped when they choose "delete profile" goes here.
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ_DIR = os.path.dirname(_PKG_DIR)

# Files inside desktop_cat/ (saved by the various windows)
_WIPE_PKG_FILES = (
    'bedroom_items.json',
    'clipboard.json',
    'garden.json',
    'inventory.json',
    'message_board.json',
    'pomodoro.json',
    'task_flowers.json',
    'world_settings.json',
    '_theme.json',
)

# Files at project root
_WIPE_ROOT_FILES = (
    'user_profile.json',
    'sao_profile.json',
)


def wipe_all() -> list[str]:
    """Delete every saved-state file the app owns.

    After this, `is_onboarded()` returns False and the next launch shows the
    onboarding flow as if it were a brand-new install.  Returns the list of
    filenames that were actually removed (for logging / display).
    """
    removed: list[str] = []
    for base in _WIPE_PKG_FILES:
        p = os.path.join(_PKG_DIR, base)
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed.append(base)
        except OSError:
            pass
    for base in _WIPE_ROOT_FILES:
        p = os.path.join(_PROJ_DIR, base)
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed.append(base)
        except OSError:
            pass
    return removed

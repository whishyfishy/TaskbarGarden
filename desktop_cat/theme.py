"""
Global UI theme — light/dark palette switching with persistence.

Windows query colors via the singleton `theme.X` accessors below.  Each window
should connect `theme.changed` to its `update()` slot in `__init__` so the UI
repaints in place when the user flips the toggle from the Settings window.

The active mode is persisted to `_theme.json` next to this module so the
choice survives restarts.

Accent colors (mint, blue, rose, lav, amber) are intentionally identical in
both modes so widget meaning stays stable; only the chrome (background, card,
border, text) shifts between palettes.
"""

import json
import os
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui  import QColor

_PREF_PATH = os.path.join(os.path.dirname(__file__), '_theme.json')


class _Theme(QObject):
    """Singleton theme controller — emits `changed` on mode flip."""
    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._mode: str = self._load()

    # ── Persistence ─────────────────────────────────────────────────────────
    def _load(self) -> str:
        try:
            with open(_PREF_PATH) as f:
                d = json.load(f)
            m = d.get('mode')
            if m in ('light', 'dark'):
                return m
        except (OSError, ValueError):
            pass
        return 'light'

    def _save(self) -> None:
        try:
            with open(_PREF_PATH, 'w') as f:
                json.dump({'mode': self._mode}, f)
        except OSError:
            pass

    # ── State ───────────────────────────────────────────────────────────────
    def is_dark(self) -> bool:
        return self._mode == 'dark'

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode in ('light', 'dark') and mode != self._mode:
            self._mode = mode
            self._save()
            self.changed.emit()

    def toggle(self) -> None:
        self.set_mode('dark' if self._mode == 'light' else 'light')

    # ── Color accessors ─────────────────────────────────────────────────────
    # Body / chrome
    @property
    def bg(self) -> QColor:
        return QColor(0x22, 0x23, 0x28, 252) if self.is_dark() \
            else QColor(0xF7, 0xF7, 0xFA, 252)

    @property
    def bg_solid(self) -> QColor:
        return QColor(0x22, 0x23, 0x28) if self.is_dark() \
            else QColor(0xF7, 0xF7, 0xFA)

    @property
    def header_bg(self) -> QColor:
        return QColor(0x18, 0x19, 0x1D, 250) if self.is_dark() \
            else QColor(0xEC, 0xEC, 0xF1)

    @property
    def header_top(self) -> QColor:
        return QColor(0x20, 0x21, 0x26) if self.is_dark() \
            else QColor(0xF4, 0xF4, 0xF8)

    @property
    def border(self) -> QColor:
        return QColor(0xFF, 0xFF, 0xFF, 30) if self.is_dark() \
            else QColor(0x00, 0x00, 0x00, 36)

    @property
    def border_in(self) -> QColor:
        return QColor(0xFF, 0xFF, 0xFF, 18) if self.is_dark() \
            else QColor(0x00, 0x00, 0x00, 18)

    # Text
    @property
    def title(self) -> QColor:
        return QColor(0xF0, 0xF0, 0xF2) if self.is_dark() \
            else QColor(0x1F, 0x1F, 0x21)

    @property
    def label(self) -> QColor:
        return QColor(0xF0, 0xF0, 0xF2) if self.is_dark() \
            else QColor(0x1F, 0x1F, 0x21)

    @property
    def muted(self) -> QColor:
        return QColor(0xA8, 0xA8, 0xB0) if self.is_dark() \
            else QColor(0x60, 0x60, 0x68)

    @property
    def muted_dim(self) -> QColor:
        return QColor(0x70, 0x70, 0x78) if self.is_dark() \
            else QColor(0x8A, 0x8A, 0x92)

    # Card / surface
    @property
    def card(self) -> QColor:
        return QColor(0x2D, 0x2E, 0x33) if self.is_dark() \
            else QColor(0xFF, 0xFF, 0xFF)

    @property
    def card_alt(self) -> QColor:
        return QColor(0x33, 0x34, 0x39) if self.is_dark() \
            else QColor(0xFF, 0xFF, 0xFF)

    @property
    def card_hov(self) -> QColor:
        return QColor(0x46, 0x82, 0xE6, 50) if self.is_dark() \
            else QColor(0x46, 0x82, 0xE6, 22)

    @property
    def hover(self) -> QColor:
        return QColor(0xFF, 0xFF, 0xFF, 22) if self.is_dark() \
            else QColor(0x00, 0x00, 0x00, 16)

    @property
    def press(self) -> QColor:
        return QColor(0xFF, 0xFF, 0xFF, 38) if self.is_dark() \
            else QColor(0x00, 0x00, 0x00, 28)

    # Input
    @property
    def input_bg(self) -> QColor:
        return QColor(0x1A, 0x20, 0x2A) if self.is_dark() \
            else QColor(0xF0, 0xF5, 0xFF)

    @property
    def input_fg(self) -> QColor:
        return QColor(0xF0, 0xF0, 0xF2) if self.is_dark() \
            else QColor(0x1F, 0x1F, 0x21)

    # Accents (constant across themes)
    @property
    def accent(self) -> QColor:
        return QColor(0x46, 0x82, 0xE6)

    @property
    def accent_blue(self) -> QColor:
        return QColor(0x46, 0x82, 0xE6)

    @property
    def accent_mint(self) -> QColor:
        return QColor(0x4F, 0xB3, 0x86)

    @property
    def accent_rose(self) -> QColor:
        return QColor(0xE8, 0x4C, 0x4C)

    @property
    def accent_lav(self) -> QColor:
        return QColor(0x9A, 0x7C, 0xD8)

    @property
    def accent_amber(self) -> QColor:
        return QColor(0xC4, 0x8A, 0x30)

    @property
    def danger(self) -> QColor:
        return QColor(0xE8, 0x4C, 0x4C)

    @property
    def success(self) -> QColor:
        return QColor(0x4F, 0xB3, 0x86)

    # Pin / close button surfaces
    @property
    def close_btn_idle(self) -> QColor:
        return QColor(0x55, 0x40, 0x46) if self.is_dark() \
            else QColor(0xF8, 0xE8, 0xE8)

    @property
    def pin_btn_idle(self) -> QColor:
        return QColor(0x40, 0x4A, 0x55) if self.is_dark() \
            else QColor(0xE8, 0xEC, 0xF0)


# Singleton — import this everywhere
theme = _Theme()


def connect_repaint(widget) -> None:
    """Helper: connect theme.changed to widget.update() for live repaints."""
    try:
        theme.changed.connect(widget.update)
    except Exception:
        pass

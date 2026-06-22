"""
Global (system-wide) hotkeys, implemented via Win32 RegisterHotKey and
dispatched through a Qt native event filter so callbacks run on the GUI
thread.

Only a few predefined shortcuts for now — custom user keybinds are a later
feature.

Usage:
    hk = GlobalHotkeys(app)
    hk.register('ctrl+alt+p', on_start_pomodoro)
    hk.register('ctrl+alt+n', on_toggle_pin_mode)
    hk.install()
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
from typing import Callable

from PyQt6.QtCore import QAbstractNativeEventFilter


_user32 = ctypes.windll.user32

_WM_HOTKEY = 0x0312

# Modifiers accepted by RegisterHotKey.
_MOD_ALT     = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT   = 0x0004
_MOD_WIN     = 0x0008
_MOD_NOREPEAT = 0x4000   # don't fire repeatedly while held

_MOD_NAMES = {
    'ctrl':    _MOD_CONTROL,
    'control': _MOD_CONTROL,
    'alt':     _MOD_ALT,
    'shift':   _MOD_SHIFT,
    'win':     _MOD_WIN,
    'meta':    _MOD_WIN,
}

# A pragmatic subset of virtual-key codes — everything a user would realistically
# bind for the two shortcuts we currently ship. Expand when custom keybinds land.
_VK = {
    **{chr(c): c for c in range(ord('A'), ord('Z') + 1)},  # A..Z
    **{str(d): 0x30 + d for d in range(10)},               # 0..9
    'space':  0x20, 'tab': 0x09, 'enter': 0x0D, 'return': 0x0D,
    'escape': 0x1B, 'esc': 0x1B,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
}


def _parse(accel: str) -> tuple[int, int]:
    """
    'ctrl+alt+p'  →  (mods, vk)
    Raises ValueError on an unparseable string.
    """
    parts = [p.strip().lower() for p in accel.split('+') if p.strip()]
    if not parts:
        raise ValueError(f'empty hotkey: {accel!r}')
    mods = 0
    key: str | None = None
    for p in parts:
        if p in _MOD_NAMES:
            mods |= _MOD_NAMES[p]
        else:
            if key is not None:
                raise ValueError(f'more than one non-modifier key: {accel!r}')
            key = p
    if key is None:
        raise ValueError(f'no key in hotkey: {accel!r}')
    vk = _VK.get(key.upper()) if key.isalpha() and len(key) == 1 else _VK.get(key)
    if vk is None:
        raise ValueError(f'unknown key: {key!r}')
    return mods | _MOD_NOREPEAT, vk


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callbacks: dict[int, Callable[[], None]]):
        super().__init__()
        self._cbs = callbacks

    def nativeEventFilter(self, event_type, message):  # type: ignore[override]
        # MSG* on Windows. Check wParam (hotkey id) when msg == WM_HOTKEY.
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == _WM_HOTKEY:
            cb = self._cbs.get(int(msg.wParam))
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass
                return True, 0
        return False, 0


class GlobalHotkeys:
    """
    Thin wrapper around RegisterHotKey. Register callbacks *before* calling
    install(); anything registered afterwards is honoured too.
    """

    def __init__(self, app) -> None:
        self._app = app
        self._next_id = 1
        self._registered: list[tuple[int, str]] = []   # (id, accel) for cleanup
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._filter: _Filter | None = None

    def register(self, accel: str, callback: Callable[[], None]) -> bool:
        try:
            mods, vk = _parse(accel)
        except ValueError:
            return False
        hk_id = self._next_id
        self._next_id += 1
        ok = bool(_user32.RegisterHotKey(None, hk_id, mods, vk))
        if not ok:
            return False
        self._registered.append((hk_id, accel))
        self._callbacks[hk_id] = callback
        return True

    def install(self) -> None:
        if self._filter is not None:
            return
        self._filter = _Filter(self._callbacks)
        self._app.installNativeEventFilter(self._filter)

    def uninstall(self) -> None:
        for hk_id, _ in self._registered:
            _user32.UnregisterHotKey(None, hk_id)
        self._registered.clear()
        self._callbacks.clear()
        if self._filter is not None and self._app is not None:
            self._app.removeNativeEventFilter(self._filter)
            self._filter = None

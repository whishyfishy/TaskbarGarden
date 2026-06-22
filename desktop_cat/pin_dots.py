"""Pinned-window indicators — a blue outline that tracks each pinned window.

For every always-on-top-pinned window we float a frameless, click-through,
topmost overlay that draws a thin blue rounded border around the window so
you can see at a glance which windows are pinned.

Tracking is **event-driven, not polled**: we install a Windows event hook
(`SetWinEventHook` for `EVENT_OBJECT_LOCATIONCHANGE`).  The OS calls us the
instant a window moves or resizes, so the outline stays glued to the window
even during a fast drag — no 8 Hz lag.  A slow safety-net timer still runs
to catch pin add/remove, minimise/restore and z-order changes (which the
location hook doesn't cover).

If the event hook can't be installed for any reason we fall back to a
faster poll so the feature still works, just less smoothly.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget


_BORDER_COLOR = QColor(111, 140, 214)   # #6f8cd6 — the app's accent blue
_BORDER_W     = 2                        # outline thickness (logical px)
_MARGIN       = 3                        # how far outside the window the outline sits
_RADIUS       = 9                        # rounded-corner radius

# Win32 event-hook constants.
_EVENT_OBJECT_LOCATIONCHANGE = 0x800B
_WINEVENT_OUTOFCONTEXT       = 0x0000
_OBJID_WINDOW                = 0
_CHILDID_SELF                = 0
_GA_ROOT                     = 2

# WinEventProc signature: void (HWINEVENTHOOK, DWORD event, HWND, LONG idObject,
#                                LONG idChild, DWORD idEventThread, DWORD dwmsEventTime)
_WinEventProcType = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
)


class _PinOutline(QWidget):
    """A single always-on-top, click-through outline widget."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                               | Qt.WindowType.WindowStaysOnTopHint
                               | Qt.WindowType.Tool
                               | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Soft outer halo, then the crisp accent border.
        halo = QColor(_BORDER_COLOR); halo.setAlpha(70)
        p.setPen(QPen(halo, _BORDER_W + 2))
        inset = (_BORDER_W + 2) / 2
        p.drawRoundedRect(int(inset), int(inset),
                          int(self.width() - 2 * inset),
                          int(self.height() - 2 * inset), _RADIUS, _RADIUS)
        p.setPen(QPen(_BORDER_COLOR, _BORDER_W))
        inset2 = _BORDER_W / 2 + 1
        p.drawRoundedRect(int(inset2), int(inset2),
                          int(self.width() - 2 * inset2),
                          int(self.height() - 2 * inset2), _RADIUS, _RADIUS)


class PinDotManager:
    """Owns the outline overlays and keeps them glued to the pinned windows.

    GetWindowRect returns PHYSICAL pixels; Qt positions windows in LOGICAL
    pixels, so we divide by the device-pixel-ratio (this machine runs 150%).
    """

    def __init__(self, pin_manager) -> None:
        self._pm = pin_manager
        self._outlines: dict[int, _PinOutline] = {}     # hwnd → outline
        self._pinned_hwnds: set[int] = set()            # for the event-hook filter

        # Safety-net poll: catches add/remove/minimise/z-order (the location
        # hook only covers move/resize).  Slow because the hook does the
        # fast work now.
        self._timer = QTimer()
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._reconcile)
        self._timer.start()

        # Event hook for instant move/resize tracking.
        self._hook = None
        self._user32 = None
        try:
            self._user32 = ctypes.windll.user32
            # Handles are 64-bit pointers — the default c_int restype would
            # truncate them.  Declare signatures so GetAncestor returns the
            # real root HWND and the hook handle survives intact.
            self._user32.GetAncestor.restype  = wintypes.HWND
            self._user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            self._user32.SetWinEventHook.restype = wintypes.HANDLE
            self._user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
            self._proc = _WinEventProcType(self._on_win_event)   # keep ref alive!
            self._hook = self._user32.SetWinEventHook(
                _EVENT_OBJECT_LOCATIONCHANGE, _EVENT_OBJECT_LOCATIONCHANGE,
                0, self._proc, 0, 0, _WINEVENT_OUTOFCONTEXT)
        except Exception:
            self._hook = None
        if not self._hook:
            # No hook → fall back to a fast poll so tracking still works.
            self._timer.setInterval(60)

    # ── DPI helper ────────────────────────────────────────────────────────
    def _dpr(self) -> float:
        try:
            from PyQt6.QtGui import QGuiApplication
            scr = QGuiApplication.primaryScreen()
            return (scr.devicePixelRatio() if scr else 1.0) or 1.0
        except Exception:
            return 1.0

    # ── Windows event-hook callback (fires the instant a window moves) ─────
    def _on_win_event(self, _hook, _event, hwnd, id_object, id_child,
                      _thread, _time) -> None:
        # Ignore non-window objects (cursor, caret, etc.) — they fire this
        # event constantly and would be pure overhead.
        if id_object != _OBJID_WINDOW or id_child != _CHILDID_SELF or not hwnd:
            return
        if not self._pinned_hwnds:
            return
        try:
            root = self._user32.GetAncestor(hwnd, _GA_ROOT)
            root = int(root) if root else int(hwnd)
        except Exception:
            root = int(hwnd)
        if root in self._pinned_hwnds:
            self._position_one(root)

    # ── Position a single outline over its window's live rect ──────────────
    def _position_one(self, hwnd: int) -> None:
        ol = self._outlines.get(hwnd)
        if ol is None:
            return
        try:
            import win32gui
            if win32gui.IsIconic(hwnd):
                if ol.isVisible():
                    ol.hide()
                return
            l, t, r, b = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        dpr = self._dpr()
        x = l / dpr - _MARGIN
        y = t / dpr - _MARGIN
        w = (r - l) / dpr + 2 * _MARGIN
        h = (b - t) / dpr + 2 * _MARGIN
        if w <= 0 or h <= 0:
            return
        ol.setGeometry(int(x), int(y), int(w), int(h))
        if not ol.isVisible():
            ol.show()
        ol.raise_()

    # ── Safety-net reconcile: sync the set of outlines to the pin list ─────
    def _reconcile(self) -> None:
        if self._pm is None:
            return
        try:
            rects = self._pm.pinned_rects()
        except Exception:
            return
        live = set()
        for r in rects:
            hwnd = int(r.get('hwnd', 0))
            if not hwnd:
                continue
            live.add(hwnd)
            if hwnd not in self._outlines:
                self._outlines[hwnd] = _PinOutline()
            if r.get('minimised'):
                ol = self._outlines[hwnd]
                if ol.isVisible():
                    ol.hide()
                continue
            self._position_one(hwnd)
        # Drop outlines for windows no longer pinned.
        for hwnd in list(self._outlines.keys()):
            if hwnd not in live:
                ol = self._outlines.pop(hwnd)
                try:
                    ol.hide(); ol.deleteLater()
                except Exception:
                    pass
        self._pinned_hwnds = live

    def clear(self) -> None:
        for ol in self._outlines.values():
            try:
                ol.hide(); ol.deleteLater()
            except Exception:
                pass
        self._outlines.clear()
        self._pinned_hwnds = set()
        if self._hook and self._user32:
            try:
                self._user32.UnhookWinEvent(self._hook)
            except Exception:
                pass
            self._hook = None

"""
Pin-on-cursor tool.

When the user activates "pin mode" (via the Clipboard panel button or the
predefined keybind), the next left-click anywhere on screen is interpreted as
"pin this window always-on-top".

Rules the user asked for:
  - Clicking the TOP of a window pins that window.
  - Clicking away doesn't un-pin — once pinned, it stays until:
      * the window is closed (X'd out)                         → un-pin immediately,
      * the window is minimised and not restored for 5 minutes → un-pin.
  - Restoring a minimised pinned window resets its idle timer.

Implementation notes
  - We poll GetAsyncKeyState for the left mouse button once per tick so the
    cat overlay stays click-through (no need to grab mouse input globally).
  - `WindowFromPoint` resolves the HWND under the cursor; we walk up to the
    top-level ancestor with `GetAncestor(GA_ROOT)` so clicking inside the
    title bar still pins the real window.
  - `SetWindowPos(HWND_TOPMOST / HWND_NOTOPMOST)` is how we toggle pinning.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time
from dataclasses import dataclass
from typing import Callable

import win32con
import win32gui


# ── Win32 helpers ─────────────────────────────────────────────────────────────

_user32 = ctypes.windll.user32

_VK_LBUTTON = 0x01
_GA_ROOT    = 2

# Idle-minimised → un-pin after this many seconds.
PIN_MINIMISED_TIMEOUT_S = 300.0   # 5 minutes


def _async_key_down(vk: int) -> bool:
    # High bit set = key is currently pressed.
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def _cursor_pos() -> tuple[int, int]:
    pt = ctypes.wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _toplevel_hwnd_at(x: int, y: int) -> int:
    pt = ctypes.wintypes.POINT(x, y)
    child = _user32.WindowFromPoint(pt)
    if not child:
        return 0
    root = _user32.GetAncestor(child, _GA_ROOT)
    return int(root or child)


def _window_alive(hwnd: int) -> bool:
    return bool(_user32.IsWindow(hwnd))


def _set_topmost(hwnd: int, on: bool) -> None:
    flag = win32con.HWND_TOPMOST if on else win32con.HWND_NOTOPMOST
    win32gui.SetWindowPos(
        hwnd, flag, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
    )


# Shell / taskbar surfaces.  These are never pinnable themselves, but a
# click on one almost always means "pin the app this taskbar button is
# for" — so we wait for the window it activates and pin that instead.
_SHELL_CLASSES = {
    'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'TrayNotifyWnd',
    'MSTaskListWClass', 'MSTaskSwWClass', 'ReBarWindow32',
    'Progman', 'WorkerW', 'NotifyIconOverflowWindow',
    'Windows.UI.Core.CoreWindow',
    'Windows.UI.Input.InputSite.WindowClass',
    'TopLevelWindowForOverflowXamlIsland',
    'Shell_InputSwitchTopLevelWindow', 'XamlExplorerHostIslandWindow',
}


def _class_name(hwnd: int) -> str:
    try:
        return win32gui.GetClassName(hwnd)
    except Exception:
        return ''


def _is_shell(hwnd: int) -> bool:
    return _class_name(hwnd) in _SHELL_CLASSES


def _foreground_hwnd() -> int:
    try:
        return int(win32gui.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _is_pinnable(hwnd: int) -> bool:
    """True only for a real, visible, reasonably-sized top-level app window
    — not the shell/taskbar, a tooltip, or a zero-size helper surface.
    This is what stops bogus 'hwnd 123456' pins."""
    if not hwnd or not _window_alive(hwnd):
        return False
    if _is_shell(hwnd):
        return False
    try:
        if not win32gui.IsWindowVisible(hwnd):
            return False
    except Exception:
        return False
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        if (r - l) < 48 or (b - t) < 48:
            return False
    except Exception:
        return False
    return True


# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class _Pinned:
    hwnd: int
    title: str
    minimised_since: float | None = None   # wall-clock seconds; None = not min


class PinManager:
    """
    Central manager. Drive it by calling `tick()` once per game frame
    (~60Hz is fine — we only read the mouse state, cheap).

    Hosts never call win32 directly — they go through `activate_pin_mode()`
    / `deactivate_pin_mode()` / `clear_all()`.
    """

    def __init__(self,
                 ignore_hwnds: Callable[[], set[int]] | None = None) -> None:
        self._pin_pending: bool = False
        self._pinned: dict[int, _Pinned] = {}
        self._lmb_was_down: bool = False
        # After a taskbar-icon click we don't pin the taskbar — we wait for
        # the window it raises to the foreground and pin that.
        self._await_fg: bool = False
        self._await_fg_deadline: float = 0.0
        self._await_fg_baseline: int = 0
        # Hwnds that should never be pinned (our own overlay / panels).
        self._ignore: Callable[[], set[int]] = ignore_hwnds or (lambda: set())
        # Callback fired whenever the pinned set changes — lets the clipboard
        # panel redraw the count without polling.
        self._on_change: list[Callable[[], None]] = []

    # ── Public API ──

    @property
    def pin_mode_active(self) -> bool:
        return self._pin_pending

    @property
    def pinned_count(self) -> int:
        return len(self._pinned)

    def pinned_titles(self) -> list[str]:
        return [p.title for p in self._pinned.values()]

    def pinned_list(self) -> list[dict]:
        """[{hwnd, title}, ...] for the Settings UI."""
        return [{'hwnd': p.hwnd, 'title': p.title}
                for p in self._pinned.values()]

    def pinned_rects(self) -> list[dict]:
        """Live geometry of each pinned window, for the titlebar dot
        overlay: [{hwnd, x, y, w, h, minimised}].  Skips dead windows."""
        out: list[dict] = []
        for hwnd, p in self._pinned.items():
            if not _window_alive(hwnd):
                continue
            try:
                if win32gui.IsIconic(hwnd):
                    out.append({'hwnd': hwnd, 'minimised': True,
                                'x': 0, 'y': 0, 'w': 0, 'h': 0})
                    continue
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                out.append({'hwnd': hwnd, 'minimised': False,
                            'x': l, 'y': t, 'w': r - l, 'h': b - t})
            except Exception:
                continue
        return out

    def unpin(self, hwnd: int) -> None:
        """Remove a single pin by hwnd (Settings 'Remove' button)."""
        p = self._pinned.pop(int(hwnd), None)
        if p is not None and _window_alive(p.hwnd):
            try:
                _set_topmost(p.hwnd, False)
            except Exception:
                pass
        self._notify()

    def on_change(self, cb: Callable[[], None]) -> None:
        self._on_change.append(cb)

    def activate_pin_mode(self) -> None:
        self._pin_pending = True
        # Swallow any left button that happens to be held when mode turns on
        # so we don't immediately pin whatever was under the cursor.
        self._lmb_was_down = _async_key_down(_VK_LBUTTON)
        self._notify()

    def deactivate_pin_mode(self) -> None:
        self._pin_pending = False
        self._await_fg = False
        self._notify()

    def toggle_pin_mode(self) -> None:
        if self._pin_pending:
            self.deactivate_pin_mode()
        else:
            self.activate_pin_mode()

    def unpin_all(self) -> None:
        for p in list(self._pinned.values()):
            if _window_alive(p.hwnd):
                try:
                    _set_topmost(p.hwnd, False)
                except Exception:
                    pass
        self._pinned.clear()
        self._notify()

    # ── Per-frame tick ──

    def tick(self) -> None:
        self._poll_click()
        self._resolve_await_fg()
        self._sweep_pinned()

    # ── Internal ──

    def _notify(self) -> None:
        for cb in self._on_change:
            try:
                cb()
            except Exception:
                pass

    def _poll_click(self) -> None:
        down = _async_key_down(_VK_LBUTTON)
        just_clicked = down and not self._lmb_was_down
        self._lmb_was_down = down
        if not (self._pin_pending and just_clicked):
            return

        x, y = _cursor_pos()
        hwnd = _toplevel_hwnd_at(x, y)
        if not hwnd or hwnd in self._ignore():
            return

        # Clicked the taskbar / shell (e.g. an app's taskbar icon).  Don't
        # pin the taskbar itself — wait for the window it raises and pin
        # that.  Resolved in `_resolve_await_fg`.
        if _is_shell(hwnd):
            self._await_fg = True
            self._await_fg_deadline = time.monotonic() + 2.5
            self._await_fg_baseline = _foreground_hwnd()
            return

        # Ignore clicks on non-window junk (tooltips, zero-size surfaces) —
        # this is what used to produce bogus 'hwnd 123456' pins.
        if not _is_pinnable(hwnd):
            return

        self._pin_window(hwnd)

    def _pin_window(self, hwnd: int) -> None:
        """Toggle one concrete top-level window's always-on-top pin, then
        leave pin mode."""
        hwnd = int(hwnd)
        # Already pinned → toggle off instead of re-pinning.
        if hwnd in self._pinned:
            try:
                _set_topmost(hwnd, False)
            except Exception:
                pass
            self._pinned.pop(hwnd, None)
            self._pin_pending = False
            self._await_fg = False
            self._notify()
            return

        try:
            title = win32gui.GetWindowText(hwnd) or f'hwnd {hwnd}'
        except Exception:
            title = f'hwnd {hwnd}'

        try:
            _set_topmost(hwnd, True)
        except Exception:
            return

        self._pinned[hwnd] = _Pinned(hwnd=hwnd, title=title)
        self._pin_pending = False
        self._await_fg = False
        self._notify()

    def _resolve_await_fg(self) -> None:
        """After a taskbar-icon click, Windows raises the app to the
        foreground.  Pin that window once it appears, or give up after the
        short deadline."""
        if not self._await_fg:
            return
        if time.monotonic() > self._await_fg_deadline:
            self._await_fg = False
            return
        fg = _foreground_hwnd()
        if not fg or fg == self._await_fg_baseline:
            return
        if fg in self._ignore() or not _is_pinnable(fg):
            return
        self._pin_window(fg)

    def _sweep_pinned(self) -> None:
        """Enforce the minimise / close rules once per tick."""
        if not self._pinned:
            return
        now = time.monotonic()
        to_remove: list[int] = []
        changed = False

        for hwnd, p in self._pinned.items():
            # 1) Window gone (X'd out) → drop immediately.
            if not _window_alive(hwnd):
                to_remove.append(hwnd)
                changed = True
                continue

            # 2) Minimise state transitions.
            is_min = False
            try:
                is_min = bool(win32gui.IsIconic(hwnd))
            except Exception:
                pass

            if is_min:
                if p.minimised_since is None:
                    p.minimised_since = now
                    changed = True
                elif now - p.minimised_since >= PIN_MINIMISED_TIMEOUT_S:
                    try:
                        _set_topmost(hwnd, False)
                    except Exception:
                        pass
                    to_remove.append(hwnd)
                    changed = True
            else:
                # Restored — reset the timer and make sure topmost is still
                # set (Windows sometimes drops the flag on restore).
                if p.minimised_since is not None:
                    p.minimised_since = None
                    changed = True
                    try:
                        _set_topmost(hwnd, True)
                    except Exception:
                        pass

        for h in to_remove:
            self._pinned.pop(h, None)
        if changed:
            self._notify()

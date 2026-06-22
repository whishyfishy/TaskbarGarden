import win32gui
from collections import deque
from typing import Any

from desktop_cat.collision import Platform

MIN_CHILD_W        = 60    # physical px — minimum width to be a useful platform
MIN_CHILD_H        = 8     # physical px — minimum height
MAX_PER_WIN        = 12    # cap child platforms per parent window
CHILD_RESCAN_EVERY = 60    # ticks between background rescans (~1 s at 60 FPS)

# Win32 control classes that produce useful landing platforms.
# Opt-in list — everything else is ignored.
_USEFUL_CLASSES = {
    # Classic Win32
    "ToolbarWindow32",      # toolbars (Notepad++, VLC, Paint, older apps)
    "ReBarWindow32",        # rebar containers holding toolbars
    "msctls_statusbar32",   # status bars at window bottom
    "SysTabControl32",      # tab bars
    "SysTreeView32",        # tree views (File Explorer nav pane, Regedit)
    "SysListView32",        # list views (Task Manager, older File Explorer)
    "EDIT",                 # plain text edit boxes (Notepad body)
    "RichEdit20W",          # rich text boxes
    "RichEdit50W",          # rich text editors (WordPad)
    "SysHeader32",          # column headers in list views
    "Button",               # large buttons — size filter removes tiny ones
    "ComboBox",             # combo-boxes in toolbars
    # Windows 11 Shell / File Explorer
    "SHELLDLL_DefView",     # file list content area (main pane)
    "NamespacetreeControl", # nav pane container (wraps SysTreeView32)
    "ShellTabWindowClass",  # File Explorer tab bar
    # Microsoft Office ribbon
    "MsoCommandBarDock",    # ribbon toolbar strip
    "MsoCommandBar",        # individual ribbon bar
    "NetUIHWND",            # Office/Windows UI host control
    "NUIPane",              # Office UI pane
}


class ChildScanner:
    """
    Scans child windows of top-level windows to find UI elements that can
    serve as additional cat landing platforms.

    Uses a two-tier cache:
      - Dirty-first: if a parent window opens/moves/resizes, it is rescanned
        immediately on the next get_platforms() call.
      - Round-robin: every CHILD_RESCAN_EVERY ticks one cached parent is quietly
        rescanned to catch changes that don't move or resize the window.
    """

    def __init__(self) -> None:
        self._cache: dict[int, list[Platform]] = {}
        self._dirty: set[int] = set()
        self._rr_queue: deque[int] = deque()
        self._rr_tick: int = 0
        self._current_parent: int = 0  # set during _scan_parent for owner tagging

    # ── public API ────────────────────────────────────────────────────────────

    def mark_dirty(self, parent_hwnd: int) -> None:
        """Mark a parent window for immediate rescan (call on open/move/resize)."""
        self._dirty.add(parent_hwnd)

    def remove_parent(self, parent_hwnd: int) -> None:
        """Remove a parent window from all tracking (call on window close)."""
        self._cache.pop(parent_hwnd, None)
        self._dirty.discard(parent_hwnd)
        try:
            self._rr_queue.remove(parent_hwnd)
        except ValueError:
            pass

    def get_platforms(self, parent_hwnds: list[int], tick: int) -> list[Platform]:
        """
        Return all cached child platforms for the given parent windows.
        Rescans dirty parents immediately; advances round-robin once per
        CHILD_RESCAN_EVERY calls.
        """
        # Dirty-first: rescan any parent that changed since last call
        dirty_now = self._dirty & set(parent_hwnds)
        for hwnd in dirty_now:
            self._cache[hwnd] = self._scan_parent(hwnd)
            if hwnd not in self._rr_queue:
                self._rr_queue.append(hwnd)
        self._dirty -= dirty_now

        # Seed cache for parents seen for the first time
        for hwnd in parent_hwnds:
            if hwnd not in self._cache:
                self._cache[hwnd] = self._scan_parent(hwnd)
                self._rr_queue.append(hwnd)

        # Round-robin background rescan
        self._rr_tick += 1
        if self._rr_tick >= CHILD_RESCAN_EVERY and self._rr_queue:
            self._rr_tick = 0
            hwnd = self._rr_queue[0]
            self._rr_queue.rotate(-1)
            if hwnd in parent_hwnds:
                self._cache[hwnd] = self._scan_parent(hwnd)

        # Collect results
        result: list[Platform] = []
        for hwnd in parent_hwnds:
            result.extend(self._cache.get(hwnd, []))
        return result

    # ── private helpers ───────────────────────────────────────────────────────

    def _scan_parent(self, parent_hwnd: int) -> list[Platform]:
        try:
            left, top, right, _ = win32gui.GetWindowRect(parent_hwnd)
        except Exception:
            return []
        parent_w   = right - left
        parent_top = top

        acc: list[Platform] = []
        self._current_parent = parent_hwnd
        try:
            win32gui.EnumChildWindows(
                parent_hwnd,
                self._visit_child,
                (acc, parent_w, parent_top),
            )
        except Exception:
            pass
        finally:
            self._current_parent = 0
        return acc[:MAX_PER_WIN]

    def _visit_child(self, child_hwnd: int, param: Any) -> bool:
        acc, parent_w, parent_top = param

        if not win32gui.IsWindowVisible(child_hwnd):
            return True

        try:
            cls = win32gui.GetClassName(child_hwnd)
        except Exception:
            return True
        if cls not in _USEFUL_CLASSES:
            return True

        try:
            left, top, right, bottom = win32gui.GetWindowRect(child_hwnd)
        except Exception:
            return True

        w = right - left
        h = bottom - top

        if w < MIN_CHILD_W or h < MIN_CHILD_H:
            return True

        # Skip platforms that start at/near the screen left edge — these extend
        # off-screen due to DWM shadows and cause the cat to get stuck at x=0.
        if left < 10:
            return True

        # Skip child whose top sits within 4 px of the parent top —
        # that's title bar chrome already covered by the parent top platform.
        if top <= parent_top + 4:
            return True

        # Skip anything above the safe screen zone (physical px).
        # Catches DWM-shadow children in maximized windows that would put
        # the cat off-screen even though the parent is scanned for children.
        if top < 40:
            return True

        # Skip near-full-width elements — these are client area containers
        # (a single drawing surface for the whole window), not useful ledges.
        if parent_w > 0 and w > parent_w * 0.95:
            return True

        acc.append(Platform(hwnd=child_hwnd, x=left, y=top, w=w, h=h, title=cls,
                            solid=False,  # landing surface only — no side wall push
                            owner_hwnd=self._current_parent))
        return True

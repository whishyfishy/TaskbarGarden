"""Taskbar app-icon lookup via UI Automation.

Windows 11 doesn't expose individual taskbar-button rects to plain Win32, but
the UI Automation tree does.  We use it to find where each *running* app's
taskbar icon sits, so Sao can walk into a real icon (and we can draw an
"inside" bar under it).

The query walks part of the UIA tree, so it's relatively slow (tens to a few
hundred ms) — ALWAYS call `query_running_icons` off the GUI thread.  Results
are returned in LOGICAL pixels (physical ÷ dpi_ratio) to match the game space.
"""
from __future__ import annotations

from collections import deque

try:
    import uiautomation as _auto
    _HAVE = True
except Exception:                       # pragma: no cover
    _HAVE = False


def available() -> bool:
    return _HAVE


def query_running_icons(dpi_ratio: float) -> list[dict]:
    """Return [{name, cx, top, left, right, bottom}] (logical px) for taskbar
    buttons that represent apps with an open window.  Empty on any failure.

    Run this on a worker thread — it's slow and touches COM.
    """
    if not _HAVE or dpi_ratio <= 0:
        return []
    import comtypes
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    out: list[dict] = []
    try:
        tray = _auto.PaneControl(searchDepth=1, ClassName='Shell_TrayWnd')
        if not tray.Exists(0.4, 0.05):
            return out
        q = deque([(tray, 0)])
        while q:
            ctrl, depth = q.popleft()
            if depth > 7:
                continue
            try:
                children = ctrl.GetChildren()
            except Exception:
                continue
            for c in children:
                try:
                    if c.ControlTypeName == 'ButtonControl':
                        nm = c.Name or ''
                        # Only apps with a live window — these are the ones Sao
                        # could be "working inside".  (Pinned-but-closed apps say
                        # just "<App> pinned"; running ones say "running window".)
                        if 'running window' in nm:
                            r = c.BoundingRectangle
                            if r.width() > 4:
                                out.append({
                                    'name':  nm.split(' - ')[0].strip(),
                                    'cx':    int((r.left + r.right) / 2 / dpi_ratio),
                                    'top':   int(r.top    / dpi_ratio),
                                    'left':  int(r.left   / dpi_ratio),
                                    'right': int(r.right  / dpi_ratio),
                                    'bottom':int(r.bottom / dpi_ratio),
                                })
                except Exception:
                    pass
                q.append((c, depth + 1))
    except Exception:
        pass
    finally:
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass
    return out

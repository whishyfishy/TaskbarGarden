from unittest.mock import patch, MagicMock
from desktop_cat.child_scanner import ChildScanner, MAX_PER_WIN, CHILD_RESCAN_EVERY

# Fake hwnds used across tests
PARENT = 100
CHILD  = 200

# Parent rect: left=0, top=50, right=800, bottom=600  (750px wide, 550px tall)
PARENT_RECT = (0, 50, 800, 600)
# Toolbar child rect: left=20, top=90, right=620, bottom=130  (600w x 40h) — passes all filters
# left=20 (>= 10) so it's not filtered by the screen-left-edge guard
CHILD_RECT  = (20, 90, 620, 130)


def make_enum(children):
    """Return a fake EnumChildWindows that calls the callback for each child hwnd."""
    def _enum(parent_hwnd, callback, param):
        for hwnd in children:
            callback(hwnd, param)
    return _enum


def base_patches(extra_rects=None, cls="ToolbarWindow32", visible=True,
                 children=None):
    """
    Build a dict of win32gui patches for a single-parent, single-child scenario.
    extra_rects: {hwnd: rect} to extend the default rects dict.
    """
    rects = {PARENT: PARENT_RECT, CHILD: CHILD_RECT}
    if extra_rects:
        rects.update(extra_rects)

    if children is None:
        children = [CHILD]

    return {
        "GetWindowRect":      lambda hwnd: rects[hwnd],
        "EnumChildWindows":   make_enum(children),
        "IsWindowVisible":    lambda hwnd: visible,
        "GetClassName":       lambda hwnd: cls,
    }


# ── 1. Valid toolbar child returns one Platform ───────────────────────────────

def test_scan_returns_valid_toolbar():
    scanner = ChildScanner()
    with patch.multiple("win32gui", **base_patches()):
        platforms = scanner._scan_parent(PARENT)
    assert len(platforms) == 1
    p = platforms[0]
    assert p.hwnd == CHILD
    assert p.x == 20 and p.y == 90
    assert p.w == 600 and p.h == 40
    assert p.title == "ToolbarWindow32"


# ── 2. Invisible child is skipped ────────────────────────────────────────────

def test_invisible_child_skipped():
    scanner = ChildScanner()
    with patch.multiple("win32gui", **base_patches(visible=False)):
        platforms = scanner._scan_parent(PARENT)
    assert platforms == []


# ── 3. Unknown Win32 class is skipped ────────────────────────────────────────

def test_unknown_class_skipped():
    scanner = ChildScanner()
    with patch.multiple("win32gui", **base_patches(cls="SomeRandomWidget")):
        platforms = scanner._scan_parent(PARENT)
    assert platforms == []


# ── 4. Too-narrow child is skipped ───────────────────────────────────────────

def test_too_narrow_skipped():
    narrow_rect = (0, 90, 20, 130)   # w=20, below MIN_CHILD_W=60
    scanner = ChildScanner()
    with patch.multiple("win32gui",
                        **base_patches(extra_rects={CHILD: narrow_rect})):
        platforms = scanner._scan_parent(PARENT)
    assert platforms == []


# ── 5. Result is capped at MAX_PER_WIN even with many valid children ──────────

def test_max_per_win_cap():
    many_children = list(range(1000, 1020))  # 20 child hwnds
    # Each child has the same rect as CHILD (passes all filters)
    all_rects = {PARENT: PARENT_RECT}
    all_rects.update({hwnd: CHILD_RECT for hwnd in many_children})

    scanner = ChildScanner()
    with patch.multiple("win32gui",
                        GetWindowRect=lambda hwnd: all_rects[hwnd],
                        EnumChildWindows=make_enum(many_children),
                        IsWindowVisible=lambda hwnd: True,
                        GetClassName=lambda hwnd: "ToolbarWindow32"):
        platforms = scanner._scan_parent(PARENT)

    assert len(platforms) == MAX_PER_WIN


# ── 6. Cache hit — EnumChildWindows called only once for two get_platforms ────

def test_cache_hit_avoids_rescan():
    scanner = ChildScanner()
    mock_enum = MagicMock(side_effect=make_enum([CHILD]))

    with patch.multiple("win32gui",
                        GetWindowRect=lambda hwnd: {PARENT: PARENT_RECT,
                                                     CHILD: CHILD_RECT}[hwnd],
                        EnumChildWindows=mock_enum,
                        IsWindowVisible=lambda hwnd: True,
                        GetClassName=lambda hwnd: "ToolbarWindow32"):
        scanner.get_platforms([PARENT], tick=1)  # seeds cache
        scanner.get_platforms([PARENT], tick=2)  # should use cache

    assert mock_enum.call_count == 1


# ── 7. Dirty flag forces immediate rescan ────────────────────────────────────

def test_dirty_flag_triggers_rescan():
    scanner = ChildScanner()
    mock_enum = MagicMock(side_effect=make_enum([CHILD]))

    with patch.multiple("win32gui",
                        GetWindowRect=lambda hwnd: {PARENT: PARENT_RECT,
                                                     CHILD: CHILD_RECT}[hwnd],
                        EnumChildWindows=mock_enum,
                        IsWindowVisible=lambda hwnd: True,
                        GetClassName=lambda hwnd: "ToolbarWindow32"):
        scanner.get_platforms([PARENT], tick=1)  # initial scan
        scanner.mark_dirty(PARENT)
        scanner.get_platforms([PARENT], tick=2)  # dirty → rescan

    assert mock_enum.call_count == 2


# ── 8. remove_parent clears cache entry ──────────────────────────────────────

def test_remove_parent_clears_cache():
    scanner = ChildScanner()
    with patch.multiple("win32gui", **base_patches()):
        scanner.get_platforms([PARENT], tick=1)

    scanner.remove_parent(PARENT)
    assert PARENT not in scanner._cache
    assert PARENT not in scanner._dirty
    assert PARENT not in scanner._rr_queue


# ── 9. Round-robin fires after CHILD_RESCAN_EVERY ticks ──────────────────────

def test_round_robin_advances_after_n_ticks():
    scanner = ChildScanner()
    mock_enum = MagicMock(side_effect=make_enum([CHILD]))

    with patch.multiple("win32gui",
                        GetWindowRect=lambda hwnd: {PARENT: PARENT_RECT,
                                                     CHILD: CHILD_RECT}[hwnd],
                        EnumChildWindows=mock_enum,
                        IsWindowVisible=lambda hwnd: True,
                        GetClassName=lambda hwnd: "ToolbarWindow32"):
        for t in range(CHILD_RESCAN_EVERY):
            scanner.get_platforms([PARENT], tick=t)

    # First call seeds the cache (1 scan), then on tick CHILD_RESCAN_EVERY-1
    # the rr_tick reaches CHILD_RESCAN_EVERY and triggers a second scan.
    assert mock_enum.call_count == 2


# ── 10. All returned platforms have positive hwnd ────────────────────────────

def test_all_platforms_have_positive_hwnd():
    scanner = ChildScanner()
    with patch.multiple("win32gui", **base_patches()):
        platforms = scanner.get_platforms([PARENT], tick=1)
    assert all(p.hwnd > 0 for p in platforms)


# ── 11. Child above safe screen zone (top < 40 physical px) is skipped ───────

def test_child_above_screen_zone_skipped():
    # Simulates a maximized window (parent_top=-7) with a DWM-shadow child
    # at absolute screen y=10, which is in the off-screen title bar region.
    maximized_parent_rect = (0, -7, 800, 977)
    above_screen_child_rect = (0, 10, 600, 45)   # absolute top=10, h=35

    scanner = ChildScanner()
    with patch.multiple("win32gui",
                        GetWindowRect=lambda hwnd: {PARENT: maximized_parent_rect,
                                                     CHILD: above_screen_child_rect}[hwnd],
                        EnumChildWindows=make_enum([CHILD]),
                        IsWindowVisible=lambda hwnd: True,
                        GetClassName=lambda hwnd: "ToolbarWindow32"):
        platforms = scanner._scan_parent(PARENT)
    assert platforms == []

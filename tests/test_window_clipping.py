"""Visibility-clipping tests for WindowScanner.

Windows behind (higher z-index) must have their top/bottom edges clipped
by any foreground window whose rect covers that y-coordinate. A fully
occluded edge must emit no platform at all.
"""
from unittest.mock import patch
from desktop_cat.window_scanner import WindowScanner, MIN_SEGMENT_W_PHYS
from desktop_cat.event_bus import EventBus


def _patch_win32(windows):
    """
    windows: list of (hwnd, title, cls, (l,t,r,b)) in FRONT-TO-BACK order
    (EnumWindows enumerates front-first).
    """
    def fake_enum(callback, extra):
        for hwnd, *_ in windows:
            callback(hwnd, extra)

    def fake_rect(hwnd):
        return next((r for h, _, __, r in windows if h == hwnd), (0, 0, 0, 0))

    return patch.multiple(
        "win32gui",
        EnumWindows=fake_enum,
        IsWindowVisible=lambda h: True,
        IsIconic=lambda h: False,
        GetWindowText=lambda h: next((t for hh, t, *_ in windows if hh == h), ""),
        GetClassName=lambda h: next((c for hh, _, c, *_ in windows if hh == h), ""),
        GetWindowRect=fake_rect,
    )


def _scan(windows):
    scanner = WindowScanner(bus=EventBus())
    with _patch_win32(windows):
        return scanner.scan()


# ── baseline: unoccluded window emits one full-width top + bottom ────────────

def test_unoccluded_window_full_width():
    wins = [(1001, "Notepad", "Notepad", (100, 200, 400, 500))]
    platforms = _scan(wins)
    tops = [p for p in platforms if p.hwnd > 0]
    bots = [p for p in platforms if p.hwnd < 0]
    assert len(tops) == 1 and tops[0].w == 300 and tops[0].owner_hwnd == 1001
    assert len(bots) == 1 and bots[0].w == 300 and bots[0].owner_hwnd == 1001


# ── front window that doesn't overlap y: back window is unaffected ───────────

def test_front_window_not_overlapping_y_no_clip():
    # Front window sits fully above the back window — doesn't cover its top edge.
    wins = [
        (1,    "Front", "F", (0,   0, 500,  50)),   # bottom=50
        (1001, "Back",  "B", (100, 200, 400, 500)), # top=200 → not covered
    ]
    platforms = _scan(wins)
    tops = [p for p in platforms if p.hwnd > 0]
    assert len(tops) == 1 and tops[0].w == 300


# ── front window covers the middle of a back window's top edge: 2 segments ───

def test_partial_middle_occlusion_splits_into_two():
    wins = [
        (1,    "Front", "F", (200, 150, 300, 400)),  # covers x=200..300 at y=200
        (1001, "Back",  "B", (100, 200, 400, 500)),
    ]
    platforms = _scan(wins)
    tops = [p for p in platforms if p.hwnd > 0 and p.owner_hwnd == 1001]
    assert len(tops) == 2
    widths = sorted(p.w for p in tops)
    assert widths == [100, 100]   # 100..200 and 300..400


# ── front window covers the entire top edge: back emits NO top platform ─────

def test_full_top_occlusion_no_top_platform():
    wins = [
        (1,    "Front", "F", (0,   150, 500, 400)),   # y=150..400 covers back.top=200 fully in x
        (1001, "Back",  "B", (100, 200, 400, 500)),
    ]
    platforms = _scan(wins)
    # Back's top at y=200 is fully covered → no top segment for owner=1001.
    assert not any(p.owner_hwnd == 1001 and p.y == 200 for p in platforms)


# ── back-behind-back: occlusion respects z-order, not just iteration ─────────

def test_z_order_respected():
    # Three windows: z=0 (front) is small, z=1 (middle) is medium, z=2 (back)
    # is wide. Middle should clip back; front should clip both.
    wins = [
        (1, "Front",  "F", (300, 180, 500, 400)),   # z=0
        (2, "Middle", "M", (100, 210, 700, 450)),   # z=1, top=210
        (3, "Back",   "B", (50,  220, 900, 500)),   # z=2, top=220
    ]
    platforms = _scan(wins)
    back_tops = [p for p in platforms if p.owner_hwnd == 3 and p.y == 220]
    # Back top (y=220) is covered at x=300..500 by Front AND at x=100..700 by Middle.
    # Net visible on back.top: [50..100] and [700..900].
    assert len(back_tops) == 2
    widths = sorted(p.w for p in back_tops)
    assert widths == [50, 200]


# ── segments narrower than MIN_SEGMENT_W_PHYS are dropped ────────────────────

def test_tiny_slivers_dropped():
    # Front leaves only a tiny 5px sliver on each side — below threshold.
    sliver = 5
    front_l = 100 + sliver
    front_r = 400 - sliver
    wins = [
        (1,    "Front", "F", (front_l, 150, front_r, 400)),
        (1001, "Back",  "B", (100,     200, 400,     500)),
    ]
    platforms = _scan(wins)
    back_tops = [p for p in platforms if p.owner_hwnd == 1001 and p.y == 200]
    # Each remaining sliver is only `sliver` px wide; threshold drops them.
    assert sliver < MIN_SEGMENT_W_PHYS
    assert back_tops == []


# ── unique synthetic hwnds per segment (so collision can track them) ────────

def test_segments_have_unique_hwnds():
    wins = [
        (1,    "Front", "F", (200, 150, 300, 400)),
        (1001, "Back",  "B", (100, 200, 400, 500)),
    ]
    platforms = _scan(wins)
    tops = [p for p in platforms if p.owner_hwnd == 1001 and p.y == 200]
    assert len(tops) == 2
    assert tops[0].hwnd != tops[1].hwnd
    # All segments of the same edge share owner_hwnd.
    assert {p.owner_hwnd for p in tops} == {1001}

"""Tests for window_scanner.check_occluded."""
from unittest.mock import patch
from desktop_cat.window_scanner import check_occluded

# Fake hwnds
CAT_WIN  = 100   # the window the cat is standing on
FRONT_WIN = 10   # z_index=0 — in front of everything
BEHIND_WIN = 200 # z_index=2 — behind the cat's window

# Z-order: FRONT_WIN(0) → CAT_WIN(1) → BEHIND_WIN(2)
Z_ORDER = {FRONT_WIN: 0, CAT_WIN: 1, BEHIND_WIN: 2}

# Physical-pixel rectangles (left, top, right, bottom)
FRONT_RECT  = (0,   0, 800, 600)   # covers most of screen
BEHIND_RECT = (0, 100, 400, 400)   # behind cat — irrelevant

CAT_CX = 400.0
CAT_CY = 300.0


def _mock_rect(hwnd):
    return {FRONT_WIN: FRONT_RECT, BEHIND_WIN: BEHIND_RECT}.get(hwnd, (0, 0, 0, 0))


# ── 1. Cat on floor (on_hwnd=None / 0) → never occluded ─────────────────────

def test_floor_never_occluded():
    assert check_occluded(0, CAT_CX, CAT_CY, Z_ORDER) is False


# ── 2. Cat's window is the frontmost — nothing in front ──────────────────────

def test_cat_is_frontmost_not_occluded():
    z = {CAT_WIN: 0, BEHIND_WIN: 1}
    with patch("win32gui.GetWindowRect", side_effect=_mock_rect):
        assert check_occluded(CAT_WIN, CAT_CX, CAT_CY, z) is False


# ── 3. Front window covers cat centre → occluded ─────────────────────────────

def test_front_window_covers_cat():
    with patch("win32gui.GetWindowRect", side_effect=_mock_rect):
        result = check_occluded(CAT_WIN, CAT_CX, CAT_CY, Z_ORDER)
    assert result is True


# ── 4. Front window exists but cat is outside its rect → not occluded ────────

def test_front_window_does_not_cover_cat():
    # Cat at (900, 300) — outside FRONT_RECT which ends at x=800
    with patch("win32gui.GetWindowRect", side_effect=_mock_rect):
        result = check_occluded(CAT_WIN, 900.0, CAT_CY, Z_ORDER)
    assert result is False


# ── 5. Bottom platform: caller resolves owner_hwnd before calling ────────────

def test_bottom_platform_owner_resolved_by_caller():
    # Callers now pass the resolved top-level owner hwnd (positive), not the
    # platform's synthetic hwnd. A cat on a bottom-edge segment of CAT_WIN
    # still has owner_hwnd=CAT_WIN, so behaviour matches the positive case.
    with patch("win32gui.GetWindowRect", side_effect=_mock_rect):
        result = check_occluded(CAT_WIN, CAT_CX, CAT_CY, Z_ORDER)
    assert result is True


# ── 6. Cat's window not in z_order (just closed) → not occluded ──────────────

def test_unknown_window_not_occluded():
    with patch("win32gui.GetWindowRect", side_effect=_mock_rect):
        result = check_occluded(999, CAT_CX, CAT_CY, Z_ORDER)
    assert result is False


# ── 7. GetWindowRect raises → that window is skipped, no crash ───────────────

def test_get_window_rect_exception_skipped():
    def _bad_rect(hwnd):
        raise OSError("access denied")

    with patch("win32gui.GetWindowRect", side_effect=_bad_rect):
        # Should not raise; no window can be checked so result is False
        result = check_occluded(CAT_WIN, CAT_CX, CAT_CY, Z_ORDER)
    assert result is False

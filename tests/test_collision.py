from desktop_cat.physics import CatState
from desktop_cat.collision import Platform, resolve_collision

FLOOR = 1000
CAT_W, CAT_H = 24, 24


def make_cat(**kwargs) -> CatState:
    defaults = dict(x=100.0, y=100.0, width=CAT_W, height=CAT_H)
    defaults.update(kwargs)
    return CatState(**defaults)


def make_platform(hwnd=1, x=50, y=300, w=200, h=100) -> Platform:
    return Platform(hwnd=hwnd, x=x, y=y, w=w, h=h)


# --- landing on platform ---

def test_cat_lands_on_platform_top():
    plat = make_platform(y=300)
    # cat falling, bottom just crosses platform top
    prev = make_cat(y=275.0, vy=50.0)  # bottom=299
    curr = make_cat(y=278.0, vy=50.0)  # bottom=302, crossed 300
    result = resolve_collision(curr, [plat], FLOOR, prev_state=prev)
    assert result.grounded is True
    assert result.on_hwnd == plat.hwnd
    assert result.bottom == plat.top
    assert result.vy == 0.0


def test_cat_does_not_land_when_moving_up():
    plat = make_platform(y=300)
    cat = make_cat(y=280.0, vy=-100.0)  # moving up, bottom=304
    result = resolve_collision(cat, [plat], FLOOR)
    assert result.grounded is False


def test_cat_does_not_land_when_not_above_platform():
    plat = make_platform(x=500, y=300, w=100, h=50)
    prev = make_cat(x=0.0, y=275.0, vy=50.0)
    curr = make_cat(x=0.0, y=280.0, vy=50.0)
    result = resolve_collision(curr, [plat], FLOOR, prev_state=prev)
    assert result.grounded is False


# --- screen floor ---

def test_cat_stops_at_screen_floor():
    cat = make_cat(y=FLOOR - CAT_H + 5, vy=200.0)
    result = resolve_collision(cat, [], FLOOR)
    assert result.grounded is True
    assert result.bottom == FLOOR
    assert result.vy == 0.0


# --- ledge edge detection ---

def test_cat_falls_off_left_edge():
    plat = make_platform(x=100, y=300, w=100, h=50)
    # cat grounded, walked off left edge (x=90, right=114 — still overlaps... let's put it fully off)
    cat = make_cat(x=70.0, y=276.0, grounded=True, on_hwnd=plat.hwnd)  # right=94 < plat.left=100
    result = resolve_collision(cat, [plat], FLOOR)
    assert result.grounded is False
    assert result.on_hwnd is None


def test_cat_falls_off_right_edge():
    plat = make_platform(x=100, y=300, w=100, h=50)
    # cat right side past platform right (x=205, left=205 >= plat.right=200)
    cat = make_cat(x=205.0, y=276.0, grounded=True, on_hwnd=plat.hwnd)
    result = resolve_collision(cat, [plat], FLOOR)
    assert result.grounded is False
    assert result.on_hwnd is None


def test_cat_stays_on_platform_when_centered():
    plat = make_platform(x=100, y=300, w=200, h=50)
    cat = make_cat(x=150.0, y=276.0, grounded=True, on_hwnd=plat.hwnd)
    result = resolve_collision(cat, [plat], FLOOR)
    assert result.grounded is True


# --- window close ---

def test_cat_falls_when_platform_disappears():
    cat = make_cat(y=276.0, grounded=True, on_hwnd=99)
    # platform 99 not in list
    result = resolve_collision(cat, [], FLOOR)
    assert result.grounded is False
    assert result.on_hwnd is None


def test_cat_gets_startled_upward_on_close():
    cat = make_cat(y=276.0, grounded=True, on_hwnd=99, vy=0.0)
    result = resolve_collision(cat, [], FLOOR)
    assert result.vy < 0  # kicked upward


# --- no platforms ---

def test_cat_falls_freely_with_no_platforms():
    cat = make_cat(y=100.0, vy=50.0)
    result = resolve_collision(cat, [], FLOOR)
    assert result.grounded is False


# --- bottom-edge platform (window bottom as ledge) ---

def test_cat_lands_on_bottom_edge_platform():
    """Bottom-edge platforms (hwnd < 0) behave like any top-edge platform."""
    # A bottom-edge platform is just a thin platform at window.bottom
    bottom_plat = Platform(hwnd=-999, x=50, y=400, w=200, h=8)
    prev = make_cat(y=375.0, vy=50.0)   # bottom = 399, above ledge
    curr = make_cat(y=378.0, vy=50.0)   # bottom = 402, crossed 400
    result = resolve_collision(curr, [bottom_plat], FLOOR, prev_state=prev)
    assert result.grounded is True
    assert result.on_hwnd == -999
    assert result.bottom == bottom_plat.top


# --- ignore_hwnd (hop-down phase-through) ---

def test_cat_phases_through_ignored_platform():
    """Cat should NOT land on the platform whose hwnd is in ignore_hwnd."""
    plat = make_platform(hwnd=7, y=300)
    prev = make_cat(y=275.0, vy=50.0)  # bottom=299, above ledge
    curr = make_cat(y=278.0, vy=50.0)  # bottom=302, would normally land
    result = resolve_collision(curr, [plat], FLOOR, prev_state=prev, ignore_hwnd=7)
    assert result.grounded is False
    assert result.on_hwnd is None


def test_cat_still_lands_on_non_ignored_platform():
    """Cat should land normally on platforms that are NOT ignored."""
    plat = make_platform(hwnd=7, y=300)
    prev = make_cat(y=275.0, vy=50.0)
    curr = make_cat(y=278.0, vy=50.0)
    result = resolve_collision(curr, [plat], FLOOR, prev_state=prev, ignore_hwnd=99)
    assert result.grounded is True
    assert result.on_hwnd == 7

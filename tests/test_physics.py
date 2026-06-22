from desktop_cat.physics import (
    CatState, apply_physics, jump, walk, stop_walking,
    GRAVITY, JUMP_POWER, JUMP_MIN_POWER, WALK_SPEED, RUN_SPEED, MAX_FALL_SPEED,
)


def make_cat(**kwargs) -> CatState:
    defaults = dict(x=100.0, y=100.0)
    defaults.update(kwargs)
    return CatState(**defaults)


# --- gravity ---

def test_gravity_increases_vy():
    cat = make_cat(vy=0.0)
    cat2 = apply_physics(cat, dt=0.1)  # small dt so we don't hit the clamp
    assert abs(cat2.vy - GRAVITY * 0.1) < 0.001


def test_gravity_accumulates_over_frames():
    cat = make_cat(vy=0.0)
    cat = apply_physics(cat, dt=0.5)
    cat = apply_physics(cat, dt=0.5)
    assert cat.vy > 0
    assert cat.y > 100.0


def test_fall_speed_clamped():
    cat = make_cat(vy=MAX_FALL_SPEED)
    cat2 = apply_physics(cat, dt=1.0)
    assert cat2.vy == MAX_FALL_SPEED


def test_position_updates_with_velocity():
    cat = make_cat(x=0.0, y=0.0, vx=100.0, vy=0.0)
    cat2 = apply_physics(cat, dt=1.0)
    assert cat2.x == 100.0


def test_grounded_reset_after_physics():
    cat = make_cat(grounded=True)
    cat2 = apply_physics(cat, dt=0.016)
    assert cat2.grounded is False  # collision resolves grounded, not physics


# --- jump ---

def test_jump_sets_upward_velocity():
    cat = make_cat(grounded=True)
    cat2 = jump(cat)
    assert cat2.vy == -JUMP_POWER
    assert cat2.grounded is False


def test_jump_custom_power():
    cat = make_cat(grounded=True)
    cat2 = jump(cat, power=500.0)
    assert cat2.vy == -500.0


def test_jump_ignored_when_airborne():
    cat = make_cat(grounded=False, vy=0.0)
    cat2 = jump(cat)
    assert cat2.vy == 0.0


# --- walk ---

def test_walk_right():
    cat = make_cat(vx=0.0)
    cat2 = walk(cat, direction=1)
    assert cat2.vx == WALK_SPEED


def test_walk_left():
    cat = make_cat(vx=0.0)
    cat2 = walk(cat, direction=-1)
    assert cat2.vx == -WALK_SPEED


def test_run_faster_than_walk():
    walk_cat = walk(make_cat(), direction=1, run=False)
    run_cat = walk(make_cat(), direction=1, run=True)
    assert run_cat.vx > walk_cat.vx
    assert run_cat.vx == RUN_SPEED


def test_stop_walking_zeroes_vx():
    cat = make_cat(vx=100.0)
    cat2 = stop_walking(cat)
    assert cat2.vx == 0.0


# --- friction ---

def test_friction_slows_grounded_cat():
    cat = make_cat(x=0.0, y=0.0, vx=100.0, grounded=True)
    cat2 = apply_physics(cat, dt=1.0 / 60)
    assert 0 < cat2.vx < 100.0


def test_no_friction_when_airborne():
    cat = make_cat(x=0.0, y=0.0, vx=100.0, grounded=False)
    cat2 = apply_physics(cat, dt=1.0 / 60)
    assert cat2.vx == 100.0


# --- immutability ---

def test_apply_physics_returns_new_state():
    cat = make_cat()
    cat2 = apply_physics(cat, dt=0.016)
    assert cat is not cat2
    assert cat.y == 100.0  # original unchanged

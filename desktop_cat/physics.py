from dataclasses import dataclass, replace
from typing import Optional

GRAVITY = 1100.0    # px/s²  (was 1800 — lower = floatier, more visible arc)
MAX_FALL_SPEED = 1200.0
FRICTION = 0.93     # horizontal damping per frame when grounded and not walking (~1s walk→idle transition)
WALK_SPEED = 40.0   # px/s
RUN_SPEED  = 85.0   # px/s
JUMP_POWER = 850.0  # px/s upward — max height ≈ 328px (850²/2*1100)
JUMP_MIN_POWER = 250.0  # below this it's just a stumble, not a real jump


@dataclass(frozen=True)
class CatState:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    grounded: bool = False
    on_hwnd: Optional[int] = None
    width: int = 24
    height: int = 24

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height


def apply_physics(state: CatState, dt: float) -> CatState:
    vy = min(state.vy + GRAVITY * dt, MAX_FALL_SPEED)
    vx = state.vx
    if state.grounded and vx != 0.0:
        vx *= FRICTION ** (dt * 60)  # frame-rate independent friction
        if abs(vx) < 1.5:            # snap tiny residuals to zero — no endless micro-drift
            vx = 0.0

    x = state.x + vx * dt
    y = state.y + vy * dt

    return replace(state, x=x, y=y, vx=vx, vy=vy, grounded=False)


def jump(state: CatState, power: float = JUMP_POWER) -> CatState:
    if not state.grounded:
        return state
    return replace(state, vy=-power, grounded=False)


def walk(state: CatState, direction: int, run: bool = False) -> CatState:
    speed = RUN_SPEED if run else WALK_SPEED
    return replace(state, vx=direction * speed)


def stop_walking(state: CatState) -> CatState:
    return replace(state, vx=0.0)

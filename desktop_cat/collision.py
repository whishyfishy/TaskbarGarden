from dataclasses import dataclass, replace
from typing import Optional

from desktop_cat.physics import CatState

LAND_TOLERANCE = 8.0   # px — how far past the ledge top we allow before snapping


@dataclass(frozen=True)
class Platform:
    hwnd: int
    x: int
    y: int
    w: int
    h: int
    title: str = ""
    solid: bool = True   # False → landing surface only, no left/right wall push
    owner_hwnd: int = 0  # top-level window this belongs to; 0 = floor/unowned.
                         # Used so multi-segment splits (from visibility clipping)
                         # can still be mapped back to their real window.

    @property
    def left(self) -> int:
        return self.x

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def top(self) -> int:
        return self.y


def resolve_collision(
    state: CatState,
    platforms: list[Platform],
    screen_floor: int,
    prev_state: Optional[CatState] = None,
    ignore_hwnd: Optional[int] = None,
) -> CatState:
    prev = prev_state if prev_state is not None else state

    # --- hard ceiling: never let the cat fly above the top of the screen ---
    if state.y < 0:
        state = replace(state, y=0.0, vy=max(state.vy, 0.0))

    # --- screen floor ---
    if state.bottom >= screen_floor:
        return replace(state, y=screen_floor - state.height, vy=0.0, grounded=True, on_hwnd=None)

    # --- check if cat is still on its current platform (ledge-edge detection) ---
    if state.grounded and state.on_hwnd is not None:
        current = _find_platform(state.on_hwnd, platforms)
        if current is None:
            # platform closed — fall
            return replace(state, grounded=False, on_hwnd=None, vy=min(state.vy, -200.0))
        # Use the sprite's centre X as the fall-off point rather than any
        # pixel of the hitbox.  This prevents Sao from visually floating in
        # thin air when only a sliver of her hitbox still overlaps the edge.
        cat_cx = state.x + state.width / 2
        if cat_cx <= current.left or cat_cx >= current.right:
            # walked off the edge
            return replace(state, grounded=False, on_hwnd=None)

    # --- top-edge landing ---
    if state.vy >= 0:  # only when falling or stationary vertically
        for platform in _sorted_by_priority(platforms):
            if ignore_hwnd is not None and platform.hwnd == ignore_hwnd:
                continue  # hop-down: phase through this platform on the way down
            if _cat_overlaps_x(state, platform):
                prev_bottom = prev.bottom
                curr_bottom = state.bottom
                top = platform.top
                if prev_bottom <= top + LAND_TOLERANCE and curr_bottom >= top:
                    landed = replace(
                        state,
                        y=top - state.height,
                        vy=0.0,
                        grounded=True,
                        on_hwnd=platform.hwnd,
                    )
                    return landed

    return state


def _find_platform(hwnd: int, platforms: list[Platform]) -> Optional[Platform]:
    for p in platforms:
        if p.hwnd == hwnd:
            return p
    return None


def _cat_overlaps_x(state: CatState, platform: Platform) -> bool:
    return state.right > platform.left and state.left < platform.right


def _sorted_by_priority(platforms: list[Platform]) -> list[Platform]:
    # Higher platforms (lower y value) checked first to land on the topmost surface
    return sorted(platforms, key=lambda p: p.y)


def _resolve_walls(state: CatState, platforms: list[Platform]) -> CatState:
    x = state.x
    for platform in platforms:
        if not platform.solid:
            continue   # child / bottom-edge platforms are landing surfaces only

        cat_top = state.top
        cat_bottom = state.bottom
        plat_top = platform.top
        plat_bottom = platform.y + platform.h

        # Only push if cat body overlaps platform vertically (not just the ledge)
        if cat_bottom <= plat_top or cat_top >= plat_bottom:
            continue

        # Left wall
        if state.left < platform.right and state.right > platform.right:
            x = max(x, platform.right)
        # Right wall
        if state.right > platform.left and state.left < platform.left:
            x = min(x, platform.left - state.width)

    return replace(state, x=x)

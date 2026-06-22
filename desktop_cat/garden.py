"""
Garden system — plants that grow along the taskbar edge as Sao tends them.

Plants live at fixed x positions.  Each time Sao finishes an interact session
near a plant, its tend_count increments; when it reaches TEND_TO_GROW the
plant advances one growth stage (0=seed → 4=full flower).
"""

import random
from dataclasses import dataclass, field
from datetime import date as _date, datetime as _datetime

PLANT_STAGES  = 5   # 0 seed | 1 sprout | 2 small | 3 bud | 4 flower/crop

# plant_type constants
PLANT_FLOWER = 0
PLANT_MACRON = 1
# Legacy aliases so any old serialised data with these values loads gracefully
PLANT_POTATO = 99
PLANT_CARROT = 99

# Ticks at stage 4 before a crop (carrot/potato) auto-harvests (60 fps → 3600 = 1 min)
# Set to 3600 * 60 = 216000 for a real hour; use smaller value for testing
HARVEST_TICKS: int = 3600 * 60   # 1 hour real-time
MACRON_REGROW_TICKS: int = 3600 * 10  # 10 minutes to regrow macrons on leaves
# Sessions needed to advance from each stage to the next (index = current stage)
TEND_TO_GROW_BY_STAGE: list[int] = [1, 1, 2, 3]  # early stages grow fast

# Half-widths (logical px from plant centre) of the visible sprite per stage.
# Used to compute distance from cat sprite edge to plant sprite edge.
PLANT_HALF_WIDTHS: list[int] = [3, 3, 5, 5, 5]

# Height of plant top above floor (logical px) per stage, based on S=2 sprite scale.
# stage 0=seed(2px), 1=sprout(8px), 2=small(12px), 3=bud(20px), 4=flower(22px)
PLANT_TOP_HEIGHTS: list[int] = [2, 8, 12, 20, 22]

# Number of flower variants — one per distinct flower sprite type.
# 5 types: green-flower, blue, red, white, tall-blue
FLOWER_VARIANT_COUNT: int = 5

# Human-readable names for each flower variant (index = variant % FLOWER_VARIANT_COUNT)
FLOWER_NAMES: list[str] = [
    'green flower',       # 0  green flower
    'blue flower',        # 1  blue flower
    'red flower',         # 2  red flower
    'white flower',       # 3  white flower
    'tall blue flower',   # 4  tall light blue flower
]

# Shuffled "bag" so every variant — including the two greens — is guaranteed
# to cycle in instead of relying on uniform luck (uniform randint sometimes
# starved the greens in practice).
_VARIANT_BAG: list[int] = []


def _next_variant() -> int:
    if not _VARIANT_BAG:
        _VARIANT_BAG.extend(range(FLOWER_VARIANT_COUNT))
        random.shuffle(_VARIANT_BAG)
    return _VARIANT_BAG.pop()


def _parse_dt(s: str, end_of_day: bool = False) -> _datetime | None:
    """Parse either an ISO date ('YYYY-MM-DD') or full ISO datetime string.

    A bare date ('YYYY-MM-DD' with no time) is ambiguous about WHEN in the
    day it means.  `end_of_day=True` treats it as 23:59:59 that day, which
    is what a due date means ("due June 1" = anytime up to the end of
    June 1).  Without that, a bare due-date was read as 00:00 at the START
    of the day, so a flower hit full bloom a whole day early.  Full ISO
    datetimes (which carry an explicit time) are used as-is regardless.

    Returns None if the string is unparseable (caller decides the fallback).
    """
    if not s:
        return None
    # Detect a DATE-ONLY string ('YYYY-MM-DD', 10 chars, no 'T'/space/':').
    # IMPORTANT: Python 3.11+ `datetime.fromisoformat` happily parses a
    # bare date as midnight, so we must check this BEFORE that call —
    # otherwise end_of_day never takes effect and due dates read as the
    # START of the day (flowers bloom a day early).
    s = s.strip()
    is_date_only = (len(s) == 10 and s[4:5] == '-' and 'T' not in s
                    and ':' not in s and ' ' not in s)
    if is_date_only:
        try:
            d = _date.fromisoformat(s)
        except (ValueError, TypeError):
            return None
        if end_of_day:
            return _datetime(d.year, d.month, d.day, 23, 59, 59)
        return _datetime(d.year, d.month, d.day)
    try:
        return _datetime.fromisoformat(s)   # full datetime carries its own time
    except (ValueError, TypeError):
        return None


@dataclass
class TaskFlower:
    """A task seed planted on the taskbar floor. Blooms toward its due date."""
    x: float              # logical-px screen position
    task_text: str        # the todo item text
    due_date: str         # ISO date or datetime — accepts both
    planted_date: str     # ISO date or datetime (when it was planted)
    done: bool = False    # True once the user checks off the task (→ wilted)
    # Stable ID linking back to the Library Hub todo (xv4 React state).
    # Empty for legacy flowers planted before the React-hub integration —
    # those still match against task_text as a fallback.  Used by the
    # reconciler in main.py to sync done/remove without losing the link
    # when the user edits the todo's display text.
    todo_id: str = ''
    # Sprite variant: 0=green 1=blue 2=red 3=white 4=tall-blue.  Picked
    # randomly at plant time so every todo has a distinct-looking flower.
    variant: int = 0
    # Pop-out animation counter.  Set to POP_ANIM_TICKS when the matching
    # todo is checked off — the renderer scales+fades the flower over the
    # countdown, then main.py drops it from task_flowers.  0 means idle.
    pop_anim_ticks: int = 0
    # Priority from the linked todo ('high' for labs/quizzes/tests/exams,
    # else 'normal').  High-priority flowers glow purple as they near their
    # due date instead of the usual warm-gold bloom halo.
    priority: str = 'normal'

    def bloom_frac(self) -> float:
        """0.0 (just planted) → 1.0 (due date reached). Sub-day precise."""
        d0 = _parse_dt(self.planted_date)
        d1 = _parse_dt(self.due_date, end_of_day=True)
        if d0 is None or d1 is None:
            return 0.0
        total = (d1 - d0).total_seconds()
        if total <= 0:
            return 1.0
        elapsed = (_datetime.now() - d0).total_seconds()
        return max(0.0, min(1.0, elapsed / total))

    def is_past_due(self) -> bool:
        d1 = _parse_dt(self.due_date, end_of_day=True)
        if d1 is None:
            return False
        return _datetime.now() > d1


# Pop-out animation length in 60 fps ticks (~0.5 s).
POP_ANIM_TICKS: int = 30


@dataclass
class FallingSeed:
    """A seed falling from above to plant itself on the taskbar floor."""
    x: float
    y: float
    vy: float = 0.0
    task_text: str = ''
    due_date: str = ''


@dataclass
class Plant:
    x: int              # logical-px position along screen
    stage: int = 0
    tend_count: int = 0
    variant: int = 0      # flower colour variant 0–(FLOWER_VARIANT_COUNT-1)
    has_bee: bool = False  # only ~1/6 plants get a bee
    plant_type: int = 0   # 0=flower, 1=potato, 2=carrot, 3=macron
    harvest_timer: int = 0  # ticks at stage 4 before auto-harvest (3600=1 min at 60fps)
    fruitless: bool = False   # macron plant: True after Sao harvests macrons
    fruitless_timer: int = 0  # ticks since fruitless; resets to False after MACRON_REGROW_TICKS
    bug_kind: str = ''    # '' = plain bee (or none); 'bbug1'/'bbug2'/'bbug3' = purchased bee variant
    # Frame index into the variant's sprite animation.  Starts at 0 (seed);
    # advances by FLOWER_FRAMES_PER_TEND per tend, capped by current stage.
    growth_frame: int = 0
    # Per-instance draw-scale multiplier for flowers (1.0 = base size).
    # Randomised in add_plant() so each flower is slightly different in size.
    size_scale: float = 1.0
    # Facing direction: 1 = normal, -1 = horizontally flipped.
    facing: int = 1
    # Per-instance hue rotation (0–359) applied to flower sprites.
    # 0 = original sprite colors; non-zero shifts the whole hue wheel.
    hue_offset: int = 0


class Garden:
    def __init__(self, positions: list[int] | None = None,
                 plants: 'list[Plant] | None' = None):
        """
        If *plants* is provided (loaded from JSON), use it directly.
        Otherwise start empty — plants are added by seed-based planting.
        *positions* is kept for backward compatibility but ignored when
        no plants are provided (we no longer randomly pre-populate).
        """
        if plants is not None:
            self.plants: list[Plant] = plants
        else:
            self.plants = []

    def add_plant(self, x: int, plant_type: int,
                  bbug_slots: 'list[str | None] | None' = None) -> Plant:
        """Add a new plant at logical-px position x and return it."""
        has_bee  = plant_type == PLANT_FLOWER and random.random() < 1 / 6
        bug_kind = ''

        variant = _next_variant()

        # Per-instance size multiplier for flowers (non-flowers stay at 1.0).
        # Per-instance facing: flowers can be mirrored horizontally.
        # hue_offset is always 0 — each sprite already has its own distinct colour.
        if plant_type == PLANT_FLOWER:
            size_scale = random.uniform(0.90, 1.10)
            facing     = random.choice([-1, 1])
            hue_offset = 0
        else:
            size_scale = 1.0
            facing     = 1
            hue_offset = 0

        p = Plant(
            x=x,
            variant=variant,
            has_bee=has_bee,
            plant_type=plant_type,
            bug_kind=bug_kind,
            size_scale=size_scale,
            facing=facing,
            hue_offset=hue_offset,
        )
        self.plants.append(p)
        return p

    def remove_plant(self, plant: 'Plant') -> None:
        """Remove a plant (after harvest, orc destruction, etc.)."""
        if plant in self.plants:
            self.plants.remove(plant)

    def tick_harvest(self, pomodoro_active: bool = False) -> 'list[tuple[Plant, int]]':
        """Kept for compatibility; carrots/potatoes are now harvested by Sao interact.
        Only retained in case other code paths need it; returns empty list.
        """
        return []

    def tick_macron_regrow(self) -> None:
        """Advance fruitless timers on stage-4 macron plants; re-enable when ready."""
        for plant in self.plants:
            if (plant.plant_type == PLANT_MACRON
                    and plant.stage == PLANT_STAGES - 1
                    and plant.fruitless):
                plant.fruitless_timer += 1
                if plant.fruitless_timer >= MACRON_REGROW_TICKS:
                    plant.fruitless = False
                    plant.fruitless_timer = 0

    def tend(self, cat_x: float, pomodoro_active: bool = False) -> Plant | None:
        """
        Called at the end of each taskbar interact session.
        Finds the nearest plant and advances its growth.  Returns the plant.

        Flowers use a stage-gated frame model: growth_frame advances each tend
        but is capped by the current stage.  Stage advances based on tend_count
        (same TEND_TO_GROW_BY_STAGE system as crops), unlocking more frames.

        Crops (potato/carrot/macron) keep the original tend-count → stage system.
        """
        if not self.plants:
            return None
        nearest = min(self.plants, key=lambda p: abs(p.x - cat_x))
        nearest.tend_count += 1

        if nearest.plant_type == PLANT_FLOWER:
            from desktop_cat.sprite_sheet import flower_total_frames, FLOWER_FRAMES_PER_TEND
            total = max(PLANT_STAGES, flower_total_frames(nearest.variant))
            growing_stages = PLANT_STAGES - 1  # 4 growth stages (1–4)

            # Stage advances based on tend_count
            needed = (TEND_TO_GROW_BY_STAGE[nearest.stage]
                      if nearest.stage < len(TEND_TO_GROW_BY_STAGE) else 999)
            if nearest.tend_count >= needed and nearest.stage < PLANT_STAGES - 1:
                nearest.stage += 1
                nearest.tend_count = 0

            # Frame cap for the current stage: stage 0 → only frame 0,
            # stages 1–4 unlock equal fractions of the total animation.
            if nearest.stage == 0:
                stage_frame_cap = 0
            else:
                stage_frame_cap = min(total - 1,
                                      (total * nearest.stage) // growing_stages - 1)
            nearest.growth_frame = min(stage_frame_cap,
                                       nearest.growth_frame + FLOWER_FRAMES_PER_TEND)
            return nearest

        # ── Crops: original stage-count system ──────────────────────────────
        needed = (TEND_TO_GROW_BY_STAGE[nearest.stage]
                  if nearest.stage < len(TEND_TO_GROW_BY_STAGE) else 999)
        if nearest.tend_count >= needed and nearest.stage < PLANT_STAGES - 1:
            nearest.stage     += 1
            nearest.tend_count = 0
        return nearest

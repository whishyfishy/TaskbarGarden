"""
Ambient critters — tiny bugs orbiting flowers, butterflies drifting by, coins,
and decorative shrubs with wind animation.
Pure visual: no physics, just direct position updates each tick.
"""

import math
import random
from dataclasses import dataclass, field

_BUG_COLORS = [
    (35, 20,  8),   # dark brown
    (18, 38, 12),   # dark green
    (20, 15, 40),   # dark blue-purple
]

# Main wing color, then pattern/spot color
_BUTTERFLY_PALETTE = [
    ((150, 190, 250), ( 80, 110, 200)),   # blue + darker blue spots
    ((245, 200,  90), (160, 120,  20)),   # warm yellow + amber spots
    ((215, 160, 235), (140,  80, 175)),   # pale purple + deep purple
    ((185, 235, 200), ( 90, 160, 115)),   # mint + forest green
    ((250, 165, 165), (190,  70,  70)),   # soft red + deep rose
]

# ABug visual overrides — distinct palette per bought variant
_ABUG_PALETTE: dict = {
    'abug1': ((230, 220, 130), (180, 150,  40)),   # pale yellow drone
    'abug2': ((180, 100, 220), ( 90,  30, 130)),   # deep purple — rare lifter
    'abug3': ((255, 180, 200), (220, 100, 140)),   # pink friend bug
}


@dataclass
class Bug:
    x: float
    y: float
    home_x: float
    home_y: float
    angle: float           # primary orbit angle (radians)
    orbit_r: float         # base orbit radius (logical px)
    angle_speed: float     # radians per tick (negative = CCW)
    color: tuple
    phase2: float = 0.0        # secondary oscillation phase
    phase2_speed: float = 0.0  # secondary oscillation speed
    kind: str = 'plain'        # 'plain' | 'bbug1' | 'bbug2' | 'bbug3'

    def tick(self) -> None:
        # Primary orbit with irregular speed modulation
        self.angle  += self.angle_speed * (1.0 + 0.40 * math.sin(self.angle * 2.7))
        self.phase2 += self.phase2_speed
        # Radius breathes in and out so it never traces the same circle twice
        r = self.orbit_r * (1.0 + 0.50 * math.sin(self.phase2 * 1.7))
        # Secondary vertical drift creates a wandering figure-8 feel
        vdrift = math.sin(self.phase2 * 2.3) * 3.5
        self.x = self.home_x + math.cos(self.angle) * r
        self.y = self.home_y + math.sin(self.angle) * r * 0.55 + vdrift


@dataclass
class Butterfly:
    x: float
    y: float
    vx: float              # horizontal speed px/tick
    vy: float              # vertical drift
    phase: float           # wing-flap phase (always advancing)
    color: tuple           # main wing colour
    color2: tuple          # spot / pattern colour
    # State machine for landing on a flower / rock:
    #   drifting     — free wander
    #   considering  — gentle bias toward target while still drifting
    #   approaching  — velocity-steered toward HOVER POINT (above flower)
    #                  — opposing velocity gracefully decelerates first
    #   hovering     — sit above flower with full-speed wings + small bob
    #   descending   — slowly drop straight down onto the flower
    #   landed       — wings decelerate to zero, sit for land_timer
    #   noticed / fleeing — Sao reactions
    state: str
    alpha: int = 255
    wander_timer: int = 0  # ticks until next direction nudge
    kind: str = 'plain'    # 'plain' | 'abug1' | 'abug2' | 'abug3'
    speed_mul: float = 1.0  # base flap speed multiplier
    hue_shift: int = 0      # degrees (0–359) applied to sprite at first draw
    land_x: float = 0.0     # landing target x — the flower's top
    land_y: float = 0.0     # landing target y — sits on this when 'landed'
    land_timer: int = 0     # ticks remaining while landed
    land_cooldown: int = 0  # ticks before considering landing again after takeoff
    approach_timer: int = 0 # ticks remaining in 'considering' state before committing
    hover_timer: int = 0    # ticks remaining in 'hovering' state before descending
    flap_speed: float = 0.14  # current wing-flap rate (decelerates when landing/landed)
    # Per-instance landing randomness so no two butterflies land identically.
    hover_height: float = 28.0     # px above flower they pause at (overridden when target picked)
    hover_offset_x: float = 0.0    # horizontal offset for the hover point (left/right of flower)
    land_offset_x: float = 0.0     # final landing x offset (sit slightly off-center)
    # 'hover'  = pause above flower, then descend (the showy landing)
    # 'direct' = curve straight onto the flower, no pause (the quick landing)
    # 'lazy'   = long looping arc — flies past and curves back in
    # picked randomly when entering 'considering' so the same butterfly
    # may land differently next time, AND different butterflies on the
    # same flower don't look like copies of each other.
    landing_style: str = 'hover'
    # Approach-curve perpendicular offset — adds a sideways swerve to the
    # 'approaching' path so it's not a straight line.  Magnitude in px;
    # sign sets which side of the straight line the butterfly arcs through.
    approach_curve: float = 0.0
    # Jiggle sync — when the flower under a landed butterfly sways, the
    # renderer reads these to wiggle the butterfly the same amount.  Set
    # by renderer.pulse_landed_butterfly() when its plant gets jiggled.
    jiggle_active: int = 0
    jiggle_total: int = 80     # match plant's jiggle total so they're in sync

    def tick(self) -> None:
        self.phase += self.flap_speed * self.speed_mul
        if self.land_cooldown > 0:
            self.land_cooldown -= 1
        # Jiggle sync — count down so the renderer can wiggle landed
        # butterflies when their flower sways.
        if self.jiggle_active > 0:
            self.jiggle_active -= 1

        if self.state == 'drifting':
            self.flap_speed = min(0.14, self.flap_speed + 0.005)  # restore after landing
            self.wander_timer -= 1
            if self.wander_timer <= 0:
                self.wander_timer = random.randint(40, 100)
                nudge = random.uniform(-0.5, 0.5)
                self.vx = max(-0.9, min(0.9, self.vx + nudge))
                if abs(self.vx) < 0.08:
                    self.vx = random.choice([-0.25, 0.25])
                self.vy = random.uniform(-0.10, 0.10)
            self.x += self.vx
            self.y += self.vy + math.sin(self.phase) * 0.20

        elif self.state == 'considering':
            # Drifting normally but gradually biasing toward the target.
            # This creates a natural "wandering in that direction" feel before
            # committing to the final approach.
            self.flap_speed = min(0.14, self.flap_speed + 0.003)
            self.wander_timer -= 1
            if self.wander_timer <= 0:
                self.wander_timer = random.randint(30, 80)
                nudge = random.uniform(-0.35, 0.35)
                self.vx = max(-0.9, min(0.9, self.vx + nudge))
                self.vy = random.uniform(-0.10, 0.10)
            # Small gravitational bias toward target
            dx = self.land_x - self.x
            dy = self.land_y - self.y
            dist = max(0.001, (dx * dx + dy * dy) ** 0.5)
            self.vx += (dx / dist) * 0.018
            self.vy += (dy / dist) * 0.010
            self.x += self.vx
            self.y += self.vy + math.sin(self.phase) * 0.20
            self.approach_timer -= 1
            if self.approach_timer <= 0:
                if dist < 140:
                    # Close enough — start velocity-steered approach toward
                    # the HOVER point (above the flower), not the flower
                    # itself.  This creates a natural arcing path.
                    self.state = 'approaching'
                else:
                    self.state = 'drifting'  # gave up — too far

        elif self.state == 'approaching':
            # Steer current velocity toward the landing target.
            #   'hover' style → aim ABOVE the flower (then hovering → descending)
            #   'direct' style → aim straight AT the flower (skip the pause)
            # Also add a perpendicular swerve (`approach_curve`) so the path
            # arcs through the air instead of being a straight beeline.
            # The blend rate is intentionally LOW so a butterfly moving
            # the wrong direction decelerates naturally — no snap reversal.
            if self.landing_style == 'direct':
                hx = self.land_x + self.land_offset_x
                hy = self.land_y - 4.0                     # tiny above so we ease in
            else:
                hx = self.land_x + self.hover_offset_x
                hy = self.land_y - self.hover_height
            dx = hx - self.x
            dy = hy - self.y
            dist = max(0.001, (dx * dx + dy * dy) ** 0.5)
            # Perpendicular swerve — only meaningful when we're still far.
            # Fades to zero as we approach (multiply by dist/200 capped at 1).
            curve_strength = min(1.0, dist / 200.0) * self.approach_curve
            # Perpendicular unit vector (rotate (dx, dy) by 90°)
            perp_x = -dy / dist
            perp_y =  dx / dist
            # Target speed scales with distance — fast far, slow close.
            # Per-instance speed_mul varies the absolute speed.
            target_speed = min(0.95, max(0.18, dist * 0.022)) * (0.85 + 0.30 * (self.speed_mul - 0.85))
            desired_vx = (dx / dist) * target_speed + perp_x * curve_strength * 0.008
            desired_vy = (dy / dist) * target_speed * 0.85 + perp_y * curve_strength * 0.008
            # Blend rate is per-instance: 0.05-0.08 — different butterflies
            # turn at different rates, so paths look distinct.
            blend = 0.05 + 0.03 * abs(math.sin(self.phase * 0.5))   # subtle organic variation
            self.vx += (desired_vx - self.vx) * blend
            self.vy += (desired_vy - self.vy) * blend
            self.x += self.vx
            self.y += self.vy + math.sin(self.phase) * 0.10
            self.flap_speed = min(0.14, self.flap_speed + 0.003)
            # Decay the curve toward zero so it doesn't keep pulling.
            self.approach_curve *= 0.985
            # Threshold for "arrived" depends on style.
            arrive_dist = 6.0 if self.landing_style == 'direct' else 14.0
            if dist < arrive_dist:
                if self.landing_style == 'direct':
                    # Direct landing — flow straight into 'landed'
                    self.state = 'landed'
                    self.x = self.land_x + self.land_offset_x
                    self.y = self.land_y
                    self.vx = self.vy = 0.0
                    self.flap_speed = 0.04
                else:
                    # Hover style — pause above first
                    self.state = 'hovering'
                    self.hover_timer = random.randint(50, 160)   # 0.8–2.7 s — varied
                    self.vx *= 0.4
                    self.vy *= 0.4

        elif self.state == 'hovering':
            # Sit ABOVE the flower (not directly — uses hover_offset_x) with
            # wings at full speed and a natural bob.  Periodic micro-nudges
            # so the hover position drifts a little, not robotic.
            self.flap_speed = min(0.14, self.flap_speed + 0.005)
            hx = self.land_x + self.hover_offset_x
            hy = self.land_y - self.hover_height
            # Small wandering nudge so the hover isn't perfectly still
            self.wander_timer -= 1
            if self.wander_timer <= 0:
                self.wander_timer = random.randint(18, 36)
                self.vx += random.uniform(-0.18, 0.18)
                self.vy += random.uniform(-0.10, 0.10)
            # Pull-back toward hover point + drag
            self.vx += (hx - self.x) * 0.025 - self.vx * 0.08
            self.vy += (hy - self.y) * 0.025 - self.vy * 0.08
            self.x += self.vx
            self.y += self.vy + math.sin(self.phase) * 0.35   # gentle vertical bob
            self.hover_timer -= 1
            if self.hover_timer <= 0:
                self.state = 'descending'
                self.vx *= 0.3          # mostly stop horizontal drift
                self.vy = 0.0

        elif self.state == 'descending':
            # Drop down onto the flower with wings winding down.  Land at
            # land_x + land_offset_x (not perfectly centered) so different
            # butterflies sit at different spots on the same flower.
            target_x = self.land_x + self.land_offset_x
            dy = self.land_y - self.y
            speed = max(0.18, min(0.55, dy * 0.06))
            self.x += (target_x - self.x) * 0.18
            self.y += speed
            self.flap_speed = max(0.045, self.flap_speed - 0.004)
            if dy < 1.5:
                self.x, self.y = target_x, self.land_y
                self.flap_speed = 0.04
                self.vx = self.vy = 0.0
                self.state = 'landed'

        elif self.state == 'landed':
            # Wings keep decelerating to a full stop.  Jiggle sync handled
            # at the top of tick().  Land_timer counts down to take-off.
            self.flap_speed = max(0.0, self.flap_speed - 0.002)
            self.land_timer -= 1
            if self.land_timer <= 0:
                self._take_off()

        elif self.state == 'noticed':
            self.flap_speed = min(0.14, self.flap_speed + 0.008)
            self.x += self.vx
            self.y += math.sin(self.phase) * 0.20

        else:  # fleeing
            self.flap_speed = min(0.18, self.flap_speed + 0.01)
            self.x += self.vx
            self.y += math.sin(self.phase) * 0.18

    def _take_off(self) -> None:
        """Leave a landing spot and return to drifting with a long cooldown."""
        self.state = 'drifting'
        self.flap_speed = 0.06   # wings still slow at first
        self.land_cooldown = random.randint(900, 1800)  # 15–30 s before landing again
        self.vx = random.choice([-1, 1]) * random.uniform(0.25, 0.55)
        self.vy = -random.uniform(0.15, 0.35)           # take off upward
        self.wander_timer = random.randint(60, 120)

    @property
    def alive(self) -> bool:
        return self.alpha > 0


@dataclass
class CollectEffect:
    """Radial-line pop burst when a coin is collected or a butterfly vanishes."""
    x: float
    y: float
    frame: int  = 0
    color: tuple = (245, 215, 90)   # golden default for coins
    n_lines: int = 6                # number of radial spokes

    def tick(self) -> None:
        self.frame += 1

    @property
    def alive(self) -> bool:
        return self.frame < 22

    @property
    def alpha(self) -> int:
        return max(0, 255 - self.frame * 12)

    @property
    def radius(self) -> float:
        return self.frame * 1.1


# ── Factories ─────────────────────────────────────────────────────────────────

def make_bug(flower_x: int, flower_top_y: int, kind: str = 'plain') -> Bug:
    color = random.choice(_BUG_COLORS)
    return Bug(
        x=float(flower_x),
        y=float(flower_top_y),
        home_x=float(flower_x),
        home_y=float(flower_top_y),
        angle=random.uniform(0.0, math.tau),
        orbit_r=random.uniform(6.0, 11.0),       # tighter orbit around flower
        angle_speed=random.uniform(0.018, 0.045) * random.choice([-1, 1]),
        color=color,
        phase2=random.uniform(0.0, math.tau),     # start at random secondary phase
        phase2_speed=random.uniform(0.022, 0.050),
        kind=kind,
    )


def make_butterfly(screen_w: int, spawn_y: float, kind: str = 'plain') -> Butterfly:
    from_left = random.random() < 0.5
    x  = -14.0 if from_left else float(screen_w + 14)
    # ABug1 (lazy drone) drifts much slower than a normal butterfly
    if kind == 'abug1':
        speed = random.uniform(0.10, 0.22)
    else:
        speed = random.uniform(0.30, 0.60)
    vx = speed if from_left else -speed
    if kind in _ABUG_PALETTE:
        col, col2 = _ABUG_PALETTE[kind]
    else:
        col, col2 = random.choice(_BUTTERFLY_PALETTE)
    return Butterfly(
        x=x,
        y=spawn_y,
        vx=vx,
        vy=random.uniform(-0.08, 0.08),
        phase=random.uniform(0.0, math.tau),
        color=col,
        color2=col2,
        state='drifting',
        wander_timer=random.randint(30, 70),
        kind=kind,
        speed_mul=random.uniform(0.85, 1.15),
        hue_shift=random.choice([
            # Muted red / rose
            340, 355, 5,
            # Warm rust / brown / amber family (feels earthy)
            18, 25, 32, 40, 52, 60,
            # Green family (naturey)
            78, 95, 112, 130,
            # Teal / muted blue (occasional cool accent)
            152, 175, 205, 235,
        ]),
    )


def make_collect_effect(x: float, y: float) -> CollectEffect:
    return CollectEffect(x=x, y=y)


def make_butterfly_pop(x: float, y: float, color: tuple) -> CollectEffect:
    """Pastel radial burst when a butterfly is caught — 8 spokes, lighter colour."""
    r, g, b = color
    light = (min(255, r + 55), min(255, g + 55), min(255, b + 55))
    return CollectEffect(x=x, y=y, color=light, n_lines=8)


# ── Friend Bug (ABug3) — small pastel cursor critter ─────────────────────────

# Pastel base palette — every bug picks one and then jitters its channels
_FRIEND_PASTEL_BASES: list[tuple[int, int, int]] = [
    (255, 200, 220),   # pink
    (200, 220, 255),   # baby blue
    (210, 245, 220),   # mint
    (255, 240, 200),   # cream / pale yellow
    (235, 215, 255),   # lavender
    (200, 240, 235),   # pale teal
    (255, 220, 235),   # rose
    (215, 235, 255),   # sky
]


def _pastel_jitter(base: tuple[int, int, int]) -> tuple[int, int, int]:
    """Shift each channel by ±18 to give every bug a slightly different shade."""
    r, g, b = base
    return (
        max(120, min(255, r + random.randint(-18, 12))),
        max(120, min(255, g + random.randint(-18, 12))),
        max(120, min(255, b + random.randint(-18, 12))),
    )


@dataclass
class FriendBug:
    """A small pastel bug that either wanders freely or flocks to the cursor.

    States:
      - 'wandering':   drifts around screen like a butterfly (the "real" ABug3)
      - 'approaching': flying slowly toward target_x/target_y (cursor swarm)
      - 'attached':    sitting on/near cursor at cluster_dx/cluster_dy offset
      - 'scattering':  shaken off — flies toward a screen edge
    """
    x: float
    y: float
    color: tuple
    state: str = 'approaching'
    cluster_dx: float = 0.0
    cluster_dy: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    alpha: int = 255
    flap_phase: float = 0.0
    wander_timer: int = 0
    origin: str = 'swarm'   # 'swarm' | 'wanderer' — wanderers return to wandering on scatter
    hue_shift: int = 0       # degrees (0–359) applied to sprite at first draw
    land_x: float = 0.0
    land_y: float = 0.0
    land_timer: int = 0
    # Scatter flight shaping: a gentle per-tick turn (curve) so the escape
    # path isn't a straight line, plus a cosine bob amplitude tied to the
    # wing-flap so they bounce along their path like a real flying bug.
    scatter_curve: float = 0.0   # radians/tick the velocity rotates by
    scatter_bob: float   = 0.0   # px of perpendicular cosine bob along the path
    # When set to >= 0 the friend bug is "riding" lazy_bugs[ride_idx] — its
    # land_x/y are updated each frame by main.py to follow the ladybug's
    # current position so the bug travels with it.
    ride_idx: int = -1

    def tick(self, target_x: float = 0.0, target_y: float = 0.0) -> None:
        self.flap_phase += 0.20

        if self.state == 'wandering':
            self.wander_timer -= 1
            if self.wander_timer <= 0:
                self.wander_timer = random.randint(40, 100)
                nudge = random.uniform(-0.5, 0.5)
                self.vx = max(-0.85, min(0.85, self.vx + nudge))
                if abs(self.vx) < 0.08:
                    self.vx = random.choice([-0.28, 0.28])
                self.vy = random.uniform(-0.12, 0.12)
            self.x += self.vx
            self.y += self.vy + math.sin(self.flap_phase) * 0.30

        elif self.state == 'approaching':
            tx = target_x + self.cluster_dx
            ty = target_y + self.cluster_dy
            dx = tx - self.x
            dy = ty - self.y
            dist = max(0.001, (dx * dx + dy * dy) ** 0.5)
            speed = 1.6
            if dist < 30.0:
                speed *= max(0.25, dist / 30.0)
            self.x += (dx / dist) * speed
            self.y += (dy / dist) * speed + math.sin(self.flap_phase) * 0.22
            if dist < 1.5:
                self.state = 'attached'

        elif self.state == 'landing':
            dx = self.land_x - self.x
            dy = self.land_y - self.y
            dist = max(0.001, (dx * dx + dy * dy) ** 0.5)
            speed = min(1.0, max(0.25, dist * 0.10))
            self.x += (dx / dist) * speed
            self.y += (dy / dist) * speed + math.sin(self.flap_phase) * 0.06
            if dist < 2.5:
                self.x, self.y = self.land_x, self.land_y
                self.state = 'landed'

        elif self.state == 'landed':
            self.land_timer -= 1
            if self.land_timer <= 0:
                # Take off — clear any ladybug ride reference so the bug
                # returns to free wandering and gets a fresh chance later.
                self.ride_idx = -1
                self.state = 'wandering'
                self.vx = random.choice([-1, 1]) * random.uniform(0.2, 0.5)
                self.vy = -random.uniform(0.05, 0.15)
                self.wander_timer = random.randint(40, 80)

        elif self.state == 'scattering':
            # Gently rotate the velocity each tick so the escape arcs instead of
            # flying dead straight.
            if self.scatter_curve:
                _c = math.cos(self.scatter_curve)
                _s = math.sin(self.scatter_curve)
                _vx, _vy = self.vx, self.vy
                self.vx = _vx * _c - _vy * _s
                self.vy = _vx * _s + _vy * _c
            # Cosine bob perpendicular to the direction of travel, driven by the
            # wing-flap, so the bug bounces along its path as it flaps.
            spd = max(0.001, (self.vx * self.vx + self.vy * self.vy) ** 0.5)
            perp_x, perp_y = -self.vy / spd, self.vx / spd
            bob = math.cos(self.flap_phase) * self.scatter_bob
            self.x += self.vx + perp_x * bob
            self.y += self.vy + perp_y * bob
            # Gently fade as they flee, so a curved path that loops back on
            # screen still always dies instead of orbiting forever.
            self.alpha = max(0, self.alpha - 3)

    @property
    def alive(self) -> bool:
        if self.state in ('wandering', 'landed', 'landing'):
            return True
        return self.alpha > 0


def make_friend_bug(spawn_x: float, spawn_y: float,
                    cluster_dx: float, cluster_dy: float) -> 'FriendBug':
    base  = random.choice(_FRIEND_PASTEL_BASES)
    color = _pastel_jitter(base)
    return FriendBug(
        x=spawn_x,
        y=spawn_y,
        color=color,
        state='approaching',
        cluster_dx=cluster_dx,
        cluster_dy=cluster_dy,
        flap_phase=random.uniform(0.0, math.tau),
        hue_shift=random.choice([
            # Warm brown / amber
            20, 30, 48,
            # Green family — heavier weight for the "nature buddy" feel
            72, 88, 105, 122, 140,
            # Teal / blue-green
            162, 190,
            # Occasional blue / violet
            220, 265,
        ]),
    )


# ── Lazy Bug (ABug1) — fat ground-dwelling critter ────────────────────────────

_LAZY_BUG_COLORS: list[tuple[int, int, int]] = [
    (175, 160, 210),  # dusty lavender
    (155, 190, 172),  # sage green
    (210, 172, 155),  # warm terracotta
    (162, 185, 215),  # slate blue
    (195, 175, 155),  # warm pebble
]


@dataclass
class LazyBug:
    """A fat round bug that hides near rocks and occasionally waddles — or guides
    the knight toward an orc.

    States:
      - 'resting':   sitting still near home_x, antennae bob gently
      - 'waddling':  slow roam near home rock
      - 'backing':   orc spotted — faces orc, shuffles away
      - 'fleeing':   turns away and walks toward knight to attract them
      - 'leading':   knight following — walks back toward orc
    """
    x: float
    y: float          # floor_y — bug sits on this line
    color: tuple
    home_x: float = 0.0   # x of home rock (hides near here when idle)
    vx: float = 0.0
    idle_phase: float = 0.0
    state: str = 'resting'
    state_timer: int = 0
    direction: int = 1    # last walk direction (used for waddling)
    facing: int = 1       # visual facing: 1=right head, -1=left head
    hue_shift: int = 0    # small red-family hue rotation for ladybug sprite
    idle_anim_active: bool  = False   # True while playing frames 5-8 (idle stretch)
    idle_anim_phase: float  = 0.0    # 0 → 2π over the idle anim cycle

    def tick(self) -> None:
        self.idle_phase += 0.055
        # Idle stretch animation (frames 5-8) — triggered randomly while resting
        if self.state == 'resting':
            if self.idle_anim_active:
                self.idle_anim_phase += 0.10
                if self.idle_anim_phase >= math.tau:
                    self.idle_anim_active = False
                    self.idle_anim_phase  = 0.0
            elif random.random() < 0.0015:   # ~0.15 % per tick → every ~11 s on average
                self.idle_anim_active = True
                self.idle_anim_phase  = 0.0
        else:
            self.idle_anim_active = False   # cancel idle anim if waddling
        # Auto-transition only for idle states; orc states are driven by main.py
        if self.state in ('resting', 'waddling'):
            self.state_timer -= 1
            if self.state_timer <= 0:
                if self.state == 'resting':
                    if random.random() < 0.18:
                        self.state = 'waddling'
                        self.direction = random.choice([-1, 1])
                        self.facing = self.direction
                        self.vx = self.direction * random.uniform(0.25, 0.55)
                        self.state_timer = random.randint(50, 130)
                    else:
                        self.state_timer = random.randint(90, 240)
                else:  # waddling → rest
                    self.state = 'resting'
                    self.vx = 0.0
                    self.state_timer = random.randint(120, 360)
        self.x += self.vx   # always apply velocity (0.0 when resting)


def make_lazy_bug(x: float, floor_y: float, home_x: float = 0.0) -> 'LazyBug':
    color = random.choice(_LAZY_BUG_COLORS)
    # Small hue shifts keep the ladybug recognizably red (±20° around 0°)
    hue_shift = random.choice([-20, -12, -6, 0, 6, 12, 20])
    return LazyBug(
        x=x,
        y=floor_y,
        home_x=home_x if home_x else x,
        color=color,
        idle_phase=random.uniform(0.0, math.tau),
        state_timer=random.randint(60, 200),
        hue_shift=hue_shift,
    )


# ── Snail — rare ambient critter, despawns behind large rocks ─────────────────

@dataclass
class Snail:
    """Rare ambient critter that crawls slowly across the floor.
    Spawns from one screen edge and walks to the other.
    Despawns when it reaches a large rock (variant >= 1).
    Rendered behind large rocks so it appears to hide underneath them.
    """
    x: float
    y: float           # floor_y — sits on this line
    vx: float = 0.0   # horizontal speed (very slow, ~0.15 px/tick)
    anim_phase: float = 0.0   # cycles through sprite frames
    facing: int = 1   # 1 = moving right, -1 = moving left

    def tick(self) -> None:
        self.x += self.vx
        self.anim_phase += 0.06   # slow frame cycle


def make_snail(screen_w: int, floor_y: float) -> 'Snail':
    from_left = random.random() < 0.5
    x  = -10.0 if from_left else float(screen_w + 10)
    vx = random.uniform(0.12, 0.20) if from_left else -random.uniform(0.12, 0.20)
    return Snail(
        x=x,
        y=floor_y,
        vx=vx,
        anim_phase=random.uniform(0.0, math.tau),
        facing=1 if from_left else -1,
    )


# ── Shrubs ─────────────────────────────────────────────────────────────────────

_SHRUB_COLORS = [
    (( 28,  82, 34), ( 48, 115, 52), ( 66, 148, 62)),  # mid green
    (( 22,  68, 28), ( 38,  95, 44), ( 55, 125, 58)),  # dark green
    (( 38,  88, 26), ( 55, 118, 38), ( 72, 148, 50)),  # yellow-green
    (( 22,  72, 50), ( 38, 102, 70), ( 52, 132, 90)),  # teal-green
]


@dataclass
class Shrub:
    """
    Decorative vegetation — either a grass tuft (bush_style=False) or a
    small dense bush (bush_style=True).  Three wind frames (neutral /
    lean-right / lean-left) are shared by both styles.
    """
    x: float
    y: float            # floor_y — bottom of the shrub
    variant: int = 0    # 0-3 → colour palette
    wind_frame: int = 0 # 0=neutral, 1=lean-right, 2=lean-left (legacy; unused since renderer drives sway)
    wind_timer: int = 0 # ticks until next frame change (legacy)
    bush_style: bool = False  # True → dense 4-blade bush; False → grass tuft
    # Live sway state, driven by the renderer's breeze + disturbance system.
    disturb: float = 0.0      # 0..1 decaying amplitude after Sao/cursor brushes past
    disturb_dir: float = 0.0  # -1 / +1 — which way it was knocked

    def tick(self) -> None:
        self.wind_timer -= 1
        if self.wind_timer <= 0:
            if self.wind_frame == 0:
                r = random.random()
                if r < 0.28:
                    self.wind_frame = 1
                    self.wind_timer = random.randint(18, 32)
                elif r < 0.50:
                    self.wind_frame = 2
                    self.wind_timer = random.randint(18, 32)
                else:
                    self.wind_frame = 0
                    self.wind_timer = random.randint(70, 180)
            else:
                self.wind_frame = 0
                self.wind_timer = random.randint(80, 200)


def make_shrub(x: float, floor_y: float, bush_style: bool = False) -> 'Shrub':
    return Shrub(
        x=x,
        y=floor_y,
        variant=random.randint(0, len(_SHRUB_COLORS) - 1),
        wind_frame=0,
        wind_timer=random.randint(30, 160),
        bush_style=bush_style,
    )


# ── Rocks ──────────────────────────────────────────────────────────────────────

@dataclass
class Rock:
    """
    Static decorative rock — rendered from a sprite sheet with two size variants.
    y = floor_y (bottom edge of the rock sits on the ground).
    """
    x: float
    y: float       # floor_y — bottom of the rock
    variant: int = 0   # 0 = small (1×), 1 = medium (2×)


def make_rock(x: float, floor_y: float, variant: int = 0) -> Rock:
    return Rock(x=x, y=floor_y, variant=variant)

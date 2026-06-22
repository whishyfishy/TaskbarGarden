"""
NPC visitors — ambient characters that wander on the taskbar floor.

Sprite sheet: fixed-width cells (not locomotion strips).
Each cell is ORC_CELL_W × ORC_CELL_H px; rows = animation states.
"""

import os
import random
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QPixmap, QPainter, QColor

# ── Orc sprite sheet geometry ─────────────────────────────────────────────────
ORC_CELL_W   = 100    # px per cell in source sheet
ORC_CELL_H   = 100    # px per cell in source sheet
ORC_H        = 31     # logical-px body height (used for scale target + physics y)
ORC_CANVAS_H = 80     # logical-px canvas height (extra headroom for attack arcs)
ORC_FRAME_W  = 40     # logical-px physics width (wall bounds, attack positioning)
ORC_CANVAS_W = 64     # logical-px render canvas width (extra room for horizontal arc)

_ALPHA_THRESHOLD     = 10
_INTERIOR_OVERLAY_A  = 44    # white overlay alpha — only hits interior pixels (55 × 0.8)

# Row definitions: name → (row_index, n_frames, ticks_per_frame)
ORC_ROW_DEFS: dict[str, tuple[int, int, int]] = {
    'idle':   (0, 6, 10),
    'walk':   (1, 8,  7),
    'attack': (2, 6, 25),   # row 2, 6 frames; 25 ticks per frame (slow for debugging)
}
ORC_ATTACK_HIT_FRAME = 3    # which frame of 'attack' triggers the plant pop (peak of swing)

# Per-frame tick durations for attack animation — ratio 2:1:4:1:2:2
# Last 3 frames (post-hit follow-through) run slightly faster.
ORC_ATTACK_FRAME_TICKS: tuple[int, ...] = (16, 8, 32, 6, 10, 13)

# Walk / wander
ORC_SPEED_MIN           = 0.45
ORC_SPEED_MAX           = 0.85
ORC_WANDER_CHANGE_TICKS = 300
ORC_IDLE_CHANCE         = 0.40
ORC_WANDER_LEFT_CHANCE  = 0.30
ORC_WANDER_RIGHT_CHANCE = 0.30

# Spawn timing (ticks at 60 fps)
VISITOR_SPAWN_MIN = 7200
VISITOR_SPAWN_MAX = 18000

# ── Soldier sprite sheet geometry ────────────────────────────────────────────
SOLDIER_SHEET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'sprites', 'Soldier.png')
SOLDIER_CELL_W   = 100
SOLDIER_CELL_H   = 100
SOLDIER_H        = 38     # 20% smaller than previous (47 * 0.8)
SOLDIER_CANVAS_H = 77
SOLDIER_FRAME_W  = 48
SOLDIER_CANVAS_W = 64
SOLDIER_MAX      = 1

SOLDIER_ROW_DEFS: dict[str, tuple[int, int, int]] = {
    'idle':   (0, 6, 10),
    'walk':   (1, 8,  7),
    'attack': (2, 6, 12),   # row 2, 6 populated frames, 12 ticks/frame
}

SOLDIER_ATTACK_HIT_FRAME: int              = 3
SOLDIER_ATTACK_FRAME_TICKS: tuple[int,...] = (12, 12, 12, 6, 9, 9)
SOLDIER_ORC_DETECT_DIST: int               = 280   # px — soldier spots orc within this range
SOLDIER_ORC_APPROACH_RANGE: int            = 500   # px — soldier wanders toward orc when within this range
SOLDIER_ATTACK_SWING_SPEED: float          = 0.35  # px/tick — slow drift during attack swing
SOLDIER_HIT_RANGE: int                     = 120   # px — orc must be within this on hit frame

ORC_KNIGHT_FLEE_DIST: int   = 200   # px — orc notices approaching knight and runs
ORC_FLEE_SPEED: float       = 0.70  # px/tick — slower than knight approach (1.1)
ORC_HIT_FLEE_SPEED: float   = 4.20  # px/tick — fast flee after being prodded
ORC_HIT_BOUNCE_VY: float    = -3.5  # initial upward velocity (less vertical, more forward)
ORC_HIT_BOOST_TICKS: int    = 60    # 1 s window for post-hit speed to settle


# ── NpcAnimator ───────────────────────────────────────────────────────────────

class NpcAnimator:
    """
    Loads frames from a fixed-cell sprite sheet.
    Two-pass loading: first measures blob heights per row so all frames in
    the same row use a uniform scale factor (eliminates 1-px size jitter).
    Interior-only white overlay: edge pixels keep their original colours.
    """

    def __init__(self):
        self._frames:  dict[str, list[QPixmap]] = {}
        self._flipped: dict[str, list[QPixmap]] = {}
        self.loaded = False

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, path: str,
             row_defs: dict[str, tuple[int, int, int]],
             cell_w: int, cell_h: int,
             frame_w: int, target_h: int,
             canvas_h: int | None = None,
             body_anim: str = 'walk') -> bool:
        """
        target_h  – desired body height in px (controls scale).
        canvas_h  – actual canvas height in px (>= target_h gives arc headroom).
                    Defaults to target_h if not supplied.
        body_anim – row whose blob height is the universal scale reference so
                    rows with large arcs don't shrink the orc body to a dot.
        """
        if canvas_h is None:
            canvas_h = target_h
        sheet = QPixmap(path)
        if sheet.isNull():
            print(f'[NpcAnimator] could not load: {path}')
            return False

        # ── Phase 1: measure every row, collect cells ─────────────────────
        all_cells:  dict[str, list] = {}
        all_ref_h:  dict[str, int]  = {}
        for name, (row_idx, n_frames, _tpf) in row_defs.items():
            y0 = row_idx * cell_h
            cells = []
            blob_heights = []
            for i in range(n_frames):
                cell = sheet.copy(QRect(i * cell_w, y0, cell_w, cell_h))
                cells.append(cell)
                _, bh = self._measure_blob(cell)
                blob_heights.append(bh)
            all_cells[name] = cells
            all_ref_h[name] = max((h for h in blob_heights if h > 0),
                                  default=target_h)

        # Body reference height: use walk (or idle) so arcs don't shrink orc
        body_ref_h = all_ref_h.get(body_anim,
                     all_ref_h.get('idle', target_h))

        # ── Phase 2: build frames — cap ref_h so arcs don't shrink orc ───
        for name, (_, n_frames, _tpf) in row_defs.items():
            # Non-body rows (attack etc.) are clamped to body scale so the
            # orc appears the same physical size regardless of arc extent.
            ref_h = min(all_ref_h[name], body_ref_h)

            frames = [
                self._cell_to_frame(cell, frame_w, canvas_h, ref_h,
                                    body_target_h=target_h)
                for cell in all_cells[name]
            ]
            self._frames[name] = frames
            self._flipped[name] = [
                QPixmap.fromImage(
                    f.toImage().mirrored(horizontal=True, vertical=False)
                )
                for f in frames
            ]

        self.loaded = True
        return True

    def get_frame(self, anim_name: str, frame_idx: int,
                  facing_right: bool) -> QPixmap | None:
        bank = self._frames if facing_right else self._flipped
        frames = bank.get(anim_name)
        if not frames:
            return None
        return frames[frame_idx % len(frames)]

    # ── Internals ─────────────────────────────────────────────────────────────

    def _measure_blob(self, cell: QPixmap) -> tuple[int, int]:
        """Return (blob_w, blob_h) of non-transparent content in cell."""
        img = cell.toImage()
        cw, ch = cell.width(), cell.height()
        min_x, max_x, min_y, max_y = cw, 0, ch, 0
        for y in range(ch):
            for x in range(cw):
                if (img.pixel(x, y) >> 24) & 0xFF > _ALPHA_THRESHOLD:
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x
                    if y < min_y: min_y = y
                    if y > max_y: max_y = y
        if max_x < min_x:
            return 0, 0
        return max_x - min_x + 1, max_y - min_y + 1

    def _cell_to_frame(self, cell: QPixmap,
                       frame_w: int, canvas_h: int,
                       scale_ref_h: int,
                       body_target_h: int | None = None) -> QPixmap:
        """
        Extract blob, scale uniformly so the body fits body_target_h px,
        bottom-align on a frame_w × canvas_h canvas (canvas_h >= body_target_h
        gives headroom for attack arcs), then mute interior colours only.
        """
        if body_target_h is None:
            body_target_h = canvas_h
        img = cell.toImage()
        cw, ch = cell.width(), cell.height()

        min_x, max_x, min_y, max_y = cw, 0, ch, 0
        for y in range(ch):
            for x in range(cw):
                if (img.pixel(x, y) >> 24) & 0xFF > _ALPHA_THRESHOLD:
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x
                    if y < min_y: min_y = y
                    if y > max_y: max_y = y

        canvas = QPixmap(frame_w, canvas_h)
        canvas.fill(Qt.GlobalColor.transparent)
        if max_x < min_x:
            return canvas

        blob_w = max_x - min_x + 1
        blob_h = max_y - min_y + 1
        cropped = cell.copy(QRect(min_x, min_y, blob_w, blob_h))

        # Scale so the body fits body_target_h — arcs may extend above canvas_h
        scale    = body_target_h / scale_ref_h
        scaled_w = max(1, int(blob_w * scale))
        scaled_h = max(1, int(blob_h * scale))
        scaled   = cropped.scaled(
            scaled_w, scaled_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

        # Centre horizontally, bottom-align vertically within the taller canvas
        dx = (frame_w - scaled.width()) // 2
        dy = canvas_h - scaled.height()
        p = QPainter(canvas)
        p.drawPixmap(QPoint(dx, dy), scaled)
        p.end()

        # ── Interior-only white overlay ───────────────────────────────────
        # Build a mask covering only pixels that have non-transparent
        # neighbours in all 4 directions (i.e. not on the silhouette edge).
        s_img = canvas.toImage()
        sw, sh = canvas.width(), canvas.height()

        mask = QPixmap(sw, sh)
        mask.fill(Qt.GlobalColor.transparent)
        mp = QPainter(mask)
        mp.setPen(Qt.PenStyle.NoPen)
        mp.setBrush(QColor(255, 255, 255, _INTERIOR_OVERLAY_A))

        for py in range(sh):
            for px in range(sw):
                if (s_img.pixel(px, py) >> 24) & 0xFF <= _ALPHA_THRESHOLD:
                    continue
                # interior = all 4 cardinal neighbours are also opaque
                interior = True
                for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = px + ddx, py + ddy
                    if nx < 0 or nx >= sw or ny < 0 or ny >= sh:
                        interior = False
                        break
                    if (s_img.pixel(nx, ny) >> 24) & 0xFF <= _ALPHA_THRESHOLD:
                        interior = False
                        break
                if interior:
                    mp.drawRect(px, py, 1, 1)
        mp.end()

        # Composite the interior mask onto canvas
        fp = QPainter(canvas)
        fp.drawPixmap(0, 0, mask)
        fp.end()

        return canvas


# ── Visitor dataclass ─────────────────────────────────────────────────────────

@dataclass
class Visitor:
    """
    Single NPC visitor wandering on the taskbar floor.
    x, y = top-left of the ORC_FRAME_W × ORC_H render canvas.
    """
    x:             float
    y:             float
    vx:            float
    screen_w:      int
    kind:          str  = 'orc'
    anim_name:     str  = 'walk'
    facing_right:  bool = True
    frame_w:       int  = ORC_FRAME_W
    row_defs:      dict = field(default_factory=lambda: ORC_ROW_DEFS)
    # Attack state
    has_attacked:       bool  = False
    attack_state:       str   = 'none'   # 'none' | 'approaching' | 'swinging'
    attack_target_x:    float = -1.0     # x position to walk to before swinging
    _attack_plant_idx:  int   = field(default=-1,    repr=False)
    _attack_done_ticks: int   = field(default=0,     repr=False)
    _attack_hit_fired:  bool  = field(default=False, repr=False)
    # Animation
    _anim_tick:    int  = field(default=0, repr=False)
    _anim_frame:   int  = field(default=0, repr=False)
    _wander_ticks: int  = field(default=0, repr=False)
    # Per-kind
    alert:              bool  = False
    _dead:              bool  = field(default=False, repr=False)
    attack_frame_ticks: tuple = ORC_ATTACK_FRAME_TICKS
    # Hit reaction (orc boing + flash when prodded by knight)
    hit_flash_ticks:    int   = field(default=0,     repr=False)
    fleeing_from_knight: bool = field(default=False, repr=False)
    bounce_y:           float = field(default=0.0,   repr=False)  # px up from floor
    bounce_vy:          float = field(default=0.0,   repr=False)  # upward is negative
    floor_y:            float = field(default=0.0,   repr=False)  # set by main
    hit_boost_ticks:    int   = field(default=0,     repr=False)  # speed boost countdown

    def tick(self) -> None:
        # ── Hit flash countdown ───────────────────────────────────────────
        if self.hit_flash_ticks > 0:
            self.hit_flash_ticks -= 1

        # ── Bounce physics (boing after knight hit) ───────────────────────
        if self.bounce_y > 0.0 or self.bounce_vy < 0.0:
            self.bounce_vy += 0.55   # gravity
            self.bounce_y  -= self.bounce_vy
            if self.bounce_y <= 0.0:
                self.bounce_y  = 0.0
                self.bounce_vy = 0.0
            # sync y so sprite stays at correct floor position minus bounce
            if self.floor_y > 0:
                self.y = self.floor_y - self.bounce_y

        # ── Fleeing off-screen: skip all wander/attack, walk until gone ──
        if self.fleeing_from_knight:
            if self.hit_boost_ticks > 0:
                self.hit_boost_ticks -= 1
                # Decay quickly from hit impulse toward a gentle 110% of normal speed
                target = ORC_FLEE_SPEED * 1.1 * (1 if self.vx >= 0 else -1)
                self.vx += (target - self.vx) * 0.12
            else:
                target = ORC_FLEE_SPEED * (1 if self.vx >= 0 else -1)
                self.vx += (target - self.vx) * 0.04
            self.x += self.vx
            offscreen_margin = self.frame_w + 40
            if self.x < -offscreen_margin or self.x > self.screen_w + offscreen_margin:
                self._dead = True
            self._advance_anim()
            return

        # ── Attack states override normal wandering ───────────────────────
        if self.attack_state == 'approaching':
            dx = self.attack_target_x - self.x
            if abs(dx) < 6:
                # Arrived — start the attack swing
                self.vx = 0.0
                self.attack_state      = 'swinging'
                self.anim_name         = 'attack'
                self._anim_frame       = 0
                self._anim_tick        = 0
                self._attack_done_ticks = 0
                self._attack_hit_fired  = False
            else:
                speed = ORC_SPEED_MAX * 1.3   # approach slightly faster
                self.vx           = speed if dx > 0 else -speed
                self.facing_right = dx > 0
                self.anim_name    = 'walk'
                self.x += self.vx   # actually move — vx alone doesn't advance x
            self._advance_anim()
            return

        if self.attack_state == 'swinging':
            self.vx = 0.0
            self._attack_done_ticks += 1
            total = sum(self.attack_frame_ticks)
            if self._attack_done_ticks >= total:
                # Animation complete — switch to idle with a long pause
                self.attack_state  = 'none'
                self.has_attacked  = True
                self.anim_name     = 'idle'
                self._anim_frame   = 0
                self._anim_tick    = 0
                self.vx            = 0.0
                self._wander_ticks = ORC_WANDER_CHANGE_TICKS
            else:
                # Variable per-frame timing — walk cumulative buckets
                t = 0
                for i, ft in enumerate(self.attack_frame_ticks):
                    t += ft
                    if self._attack_done_ticks <= t:
                        self._anim_frame = i
                        break
            # Soldier drifts slowly toward attack target while swinging
            if self.kind == 'soldier' and self.attack_target_x >= 0:
                dx = self.attack_target_x - self.x
                if abs(dx) > 8:
                    self.x += SOLDIER_ATTACK_SWING_SPEED * (1.0 if dx > 0 else -1.0)
                    self.facing_right = dx > 0
            return

        # ── Normal wandering ──────────────────────────────────────────────
        self._wander_ticks -= 1
        if self._wander_ticks <= 0:
            self._wander_ticks = ORC_WANDER_CHANGE_TICKS
            r = random.random()
            if r < ORC_IDLE_CHANCE:
                self.vx        = 0.0
                self.anim_name = 'idle'
            elif r < ORC_IDLE_CHANCE + ORC_WANDER_LEFT_CHANCE:
                self.vx           = -random.uniform(ORC_SPEED_MIN, ORC_SPEED_MAX)
                self.anim_name    = 'walk'
                self.facing_right = False
            else:
                self.vx           = random.uniform(ORC_SPEED_MIN, ORC_SPEED_MAX)
                self.anim_name    = 'walk'
                self.facing_right = True

        # ── Movement + wall bounce ────────────────────────────────────────
        self.x += self.vx
        if self.x <= 0 and self.vx < 0:
            self.x            = 0.0
            self.vx           = random.uniform(ORC_SPEED_MIN, ORC_SPEED_MAX)
            self.facing_right = True
            self.anim_name    = 'walk'
            self._wander_ticks = ORC_WANDER_CHANGE_TICKS // 2
        elif self.x >= self.screen_w - self.frame_w and self.vx > 0:
            self.x            = float(self.screen_w - self.frame_w)
            self.vx           = -random.uniform(ORC_SPEED_MIN, ORC_SPEED_MAX)
            self.facing_right = False
            self.anim_name    = 'walk'
            self._wander_ticks = ORC_WANDER_CHANGE_TICKS // 2

        self._advance_anim()

    def _advance_anim(self) -> None:
        row_def = self.row_defs.get(self.anim_name)
        if row_def is None:
            return
        _row, n_frames, tpf = row_def
        self._anim_tick += 1
        if self._anim_tick >= tpf:
            self._anim_tick  = 0
            self._anim_frame = (self._anim_frame + 1) % n_frames

    @property
    def frame(self) -> int:
        return self._anim_frame

    @property
    def alive(self) -> bool:
        return not self._dead


# ── Factory ───────────────────────────────────────────────────────────────────

def make_orc(screen_w: int, floor_y: int) -> Visitor:
    """Spawn an orc in the middle of the screen, starting idle."""
    x = float(screen_w // 2 - ORC_FRAME_W // 2)
    return Visitor(
        x=x,
        y=float(floor_y - ORC_CANVAS_H),  # top of canvas; body bottom-aligns to floor
        vx=0.0,
        screen_w=screen_w,
        anim_name='idle',
        facing_right=True,
    )


def make_soldier(screen_w: int, floor_y: int) -> Visitor:
    """Spawn a soldier in the left quarter of the screen, starting idle."""
    x = float(screen_w // 4 - SOLDIER_FRAME_W // 2)
    return Visitor(
        x=x,
        y=float(floor_y - SOLDIER_CANVAS_H),
        vx=0.0,
        screen_w=screen_w,
        kind='soldier',
        anim_name='idle',
        facing_right=True,
        frame_w=SOLDIER_FRAME_W,
        row_defs=SOLDIER_ROW_DEFS,
        attack_frame_ticks=SOLDIER_ATTACK_FRAME_TICKS,
    )


def make_orc_edge(screen_w: int, floor_y: int, from_right: bool = False) -> Visitor:
    """Spawn an orc entering from left or right edge by walking in."""
    if from_right:
        x = float(screen_w - 10)
        vx = -ORC_SPEED_MAX
        facing_right = False
    else:
        x = 10.0
        vx = ORC_SPEED_MAX
        facing_right = True
    return Visitor(
        x=x,
        y=float(floor_y - ORC_CANVAS_H),
        vx=vx,
        screen_w=screen_w,
        anim_name='walk',
        facing_right=facing_right,
    )


def make_soldier_edge(screen_w: int, floor_y: int, from_right: bool = False) -> Visitor:
    """Spawn a soldier entering from left or right edge by walking in."""
    if from_right:
        x = float(screen_w - 10)
        vx = -ORC_SPEED_MAX
        facing_right = False
    else:
        x = 10.0
        vx = ORC_SPEED_MAX
        facing_right = True
    return Visitor(
        x=x,
        y=float(floor_y - SOLDIER_CANVAS_H),
        vx=vx,
        screen_w=screen_w,
        kind='soldier',
        anim_name='walk',
        facing_right=facing_right,
        frame_w=SOLDIER_FRAME_W,
        row_defs=SOLDIER_ROW_DEFS,
        attack_frame_ticks=SOLDIER_ATTACK_FRAME_TICKS,
    )

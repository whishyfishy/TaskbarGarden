import os
import math
import time
import random as _rnd
from PyQt6.QtWidgets import QWidget, QMenu
from PyQt6.QtCore import Qt, QPoint, QRect, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QCursor, QPixmap, QPainterPath, QImage, QBrush, QTransform, QLinearGradient

from desktop_cat.physics import CatState, RUN_SPEED
from desktop_cat.collision import Platform
from desktop_cat import blocks_data
from desktop_cat.animator import Animator, CAT_W, CAT_H, FRAME_W
from desktop_cat.event_bus import EventBus
from desktop_cat.pomodoro_overlay import PomodoroOverlay
from desktop_cat.sprite_sheet import (SpriteSheet, register_loaded_sheet,
                                       ANIM_BUTTERFLY, ANIM_BUG_TINY,
                                       ANIM_LADYBUG, ANIM_SNAIL,
                                       ANIM_GREEN_PLANT,
                                       ANIM_MACRON,
                                       ANIM_BLUE_FLOWER, ANIM_RED_FLOWER, ANIM_WHITE_FLOWER,
                                       ANIM_GREEN_FLOWER, ANIM_TALL_FLOWER)

def _apply_hue_shift(frames: list, hue_shift: int, sat_delta: int = 0,
                     val_clamp: int = 255, protect_green_stems: bool = False,
                     force_hue: 'int | None' = None) -> list:
    """Return new list of hue-rotated (and optionally desaturated/clamped) QPixmaps.
    Runs once per critter/flower instance then cached — never called per frame.

    protect_green_stems: skip pixels where hue is green-family (70-160°) and
        value < 130 — preserves dark green trunks when recoloring petal flowers.
    val_clamp: reduce any pixel brighter than this value (kills shiny highlights).
    force_hue: if set, every pixel's hue becomes this exact value (used by the
        'gween been' mode to paint anything green regardless of its base colour).
    """
    if not frames or (hue_shift == 0 and sat_delta == 0 and val_clamp == 255
                      and not protect_green_stems and force_hue is None):
        return frames
    result = []
    for frame in frames:
        img = frame.toImage()
        for py in range(img.height()):
            for px in range(img.width()):
                c = img.pixelColor(px, py)
                if c.alpha() > 10:
                    h, s, v = c.hsvHue(), c.saturation(), c.value()
                    # Protect dark green stems from hue rotation
                    if protect_green_stems and 70 <= h <= 160 and v < 130:
                        if val_clamp < 255:
                            c.setHsv(h, s, min(v, val_clamp), c.alpha())
                            img.setPixelColor(px, py, c)
                        continue
                    c.setHsv(
                        force_hue if force_hue is not None else (h + hue_shift) % 360,
                        max(0, min(255, s + sat_delta)),
                        min(v, val_clamp), c.alpha(),
                    )
                    img.setPixelColor(px, py, c)
        result.append(QPixmap.fromImage(img))
    return result


# Grass-green hue (HSV degrees) used by the 'gween bean' mode.
_GREEN_HUE = 105

# Grass sway is event-driven, not constant.  Two things move the grass:
#   1. An occasional BREEZE — a gust front that sweeps left → right.
#   2. DISTURBANCE — Sao or the cursor brushing past nearby blades.
_WIND_K        = 0.018   # ripple spatial frequency (radians/px) → wavelength ≈ 350 px
_WIND_SPEED    = 0.090   # ripple phase advance per frame during a breeze
_BREEZE_AMP    = 3.0     # max blade-tip lean (px) at the heart of a gust
_BREEZE_SPEED  = 7.0     # px/frame the gust front travels rightward
_BREEZE_WIDTH  = 230.0   # px — half-spread of the gust envelope
_BREEZE_GAP    = (480, 1100)   # ticks of calm between breezes (random in range)
_DISTURB_RADIUS_SAO    = 26.0  # px — Sao's body is wide, so a moderate reach
_DISTURB_RADIUS_CURSOR = 14.0  # px — cursor must be almost literally on the tuft
_DISTURB_AMP    = 5.0     # px lean at full disturbance
_DISTURB_DECAY  = 0.025   # per-frame decay — slow so the bent blade HOLDS a beat
                          # (~0.7s) and eases back gently (not a quick/rigid snap)

# Number of distinct grass-tuft blade layouts (see _draw_grass_tuft).
# The last two layouts are taller "reedy" tufts, so ~25% of grass stands taller.
_GRASS_TUFT_VARIANTS = 8
# Extra height multiplier for the ~30% of tufts flagged tall when the
# "Extra tall grass" toggle is on (applied to blade height only, not width).
_GRASS_TALL_MULT = 1.85
# Density-slider maxima: number of TALL tufts at 100%.  (The grass amount is
# count-based — this many tufts scattered across the floor.)  The short
# backing-grass "bed" is a SEPARATE lever (set_grass_bed) drawn behind them.
_GRASS_MAX = 192
_ROCK_MAX  = 14


class _GrassTuft:
    """One decorative grass tuft in the density carpet.  Mutable so it can hold
    its own live disturbance state (set when Sao/cursor brushes past)."""
    __slots__ = ('x', 'variant', 'scale', 'disturb', 'disturb_dir', 'layer', 'tall')

    def __init__(self, x: float, variant: int, scale: float,
                 layer: int = 1, tall: bool = False):
        self.x = x
        self.variant = variant
        self.scale = scale
        self.disturb = 0.0       # 0..1 decaying amplitude
        self.disturb_dir = 0.0   # -1 / +1 knock direction
        self.layer = layer       # 0 = behind Sao, 1 = in front of her
        self.tall = tall         # extra-tall variation (when the toggle is on)

# Hue shift (degrees) per flower variant (5 variants, one per flower type).
# anim_type = variant % 5  →  0=green  1=blue  2=red  3=white  4=tall-blue
_FLOWER_VARIANT_HUE: list[int] = [0] * 5   # use natural sprite colours for all variants

# Draw scale per anim type: [green-flower, blue, red, white, tall-blue]
_FLOWER_ANIM_SCALES: list[float] = [1.1, 1.1, 1.1, 1.1, 0.92]


# (petal_bright, petal_shadow, centre_bright, centre_shadow)
# Must stay in sync with FLOWER_VARIANT_COUNT and FLOWER_NAMES in garden.py
_FLOWER_PALETTES = [
    ((230,  80, 140), (170,  45,  95), (255, 220,  50), (195, 160,  25)),  # 0  rose (pink)
    ((155,  85, 228), (110,  50, 175), (255, 200,  75), (195, 148,  35)),  # 1  lavender (purple)
    ((238, 120,  38), (185,  78,  18), (205,  45,  45), (155,  25,  25)),  # 2  poppy (orange/red)
    (( 65, 170, 232), ( 35, 118, 175), (255, 242, 165), (205, 192, 100)),  # 3  forget-me-not (blue)
    ((255, 170,  80), (200, 115,  35), (115,  48, 200), ( 80,  25, 155)),  # 4  peach lily
    ((255, 230, 100), (195, 168,  42), (235,  80,  70), (175,  35,  30)),  # 5  sunflower (yellow/red)
    ((200, 240, 180), (130, 175, 100), ( 40, 140,  80), ( 22,  95,  55)),  # 6  lily (pale green)
    ((218,  40,  55), (160,  20,  28), (248, 248, 248), (195, 195, 195)),  # 7  crimson rose (red/white)
    (( 38, 185, 180), ( 22, 130, 125), (212, 168,  38), (158, 118,  22)),  # 8  teal bloom (teal/gold)
    ((240, 120,  95), (185,  75,  55), ( 78, 195, 148), ( 42, 140,  95)),  # 9  coral bell (coral/mint)
    (( 48,  88, 210), ( 28,  55, 158), (255, 235,  60), (205, 180,  28)),  # 10 cornflower (deep blue/yellow)
    ((248, 248, 248), (195, 190, 185), (175, 145, 220), (130, 100, 175)),  # 11 daisy (white/lavender)
    # ── 6 new variants (12-17) ──────────────────────────────────────────
    ((255, 195,  60), (205, 142,  22), ( 75, 155, 230), ( 45, 105, 175)),  # 12 amber bloom (amber/sky)
    ((228,  68, 175), (172,  38, 128), (255, 225, 110), (200, 168,  55)),  # 13 magenta fern (magenta/gold)
    ((240,  90, 195), (185,  50, 148), ( 88, 205, 155), ( 48, 148,  98)),  # 14 blushing bell (pink/mint)
    ((205,  55, 215), (152,  28, 165), (255, 235, 180), (200, 175, 110)),  # 15 rose hydrangea (magenta/cream)
    ((255, 148,  42), (200,  95,  18), (118, 185,  65), ( 78, 130,  35)),  # 16 tangerine (orange/green)
    ((248, 168,  48), (195, 115,  18), (205,  78,  42), (155,  45,  18)),  # 17 marigold (warm orange/ember)
]

CAT_COLOR = QColor(220, 50, 50)
DEBUG_TOP_EDGE_COLOR  = QColor(0, 220, 255)    # cyan — top ledge line
DEBUG_BOT_EDGE_COLOR  = QColor(255, 180, 0)    # orange — bottom ledge line
DEBUG_TEXT_COLOR      = QColor(255, 255, 255)

HIT_RADIUS = 24        # px — how close the cursor must be to the cat centre to grab it
MACARON_HIT = 16       # px — grab radius for the draggable macaron treat
_CAT_DRAW_SCALE = 1.08 # Sao rendered 8 % larger than her physics footprint

# Default sprite folder: desktop_cat/sprites/ next to this file
_DEFAULT_SPRITE_DIR = os.path.join(os.path.dirname(__file__), 'sprites')


def _anim_name(cat: CatState, winding_up: bool = False) -> str:
    """Map cat physics state to animation name."""
    if not cat.grounded or winding_up:
        return 'jump'
    speed = abs(cat.vx)
    if speed > RUN_SPEED * 0.55:
        return 'run'
    if speed > 1.5:
        return 'walk'
    return 'idle'


class CatOverlay(QWidget):
    def __init__(self, debug: bool = False,
                 sprite_dir: str = _DEFAULT_SPRITE_DIR,
                 bus: EventBus | None = None):
        super().__init__()
        self.debug = debug
        self._bus  = bus
        self._cat: CatState | None = None
        self._platforms: list[Platform] = []

        self.is_dragging = False
        self._drag_offset = QPoint(0, 0)
        self._drag_pos    = QPoint(0, 0)
        self._occluded: bool = False

        # Intro drop trail (rarity-colored streak when Sao falls from sky)
        self._intro_drop_active: bool   = False
        self._intro_drop_color: QColor  = QColor(200, 200, 210)
        self._intro_drop_rarity: str    = 'grey'
        self._aura_particles: list      = []   # [x, y, vx, vy, age, max_age, hue_offset]
        self._intro_drop_landed: bool   = False

        self._pulse_ticks: int      = 0
        self._last_pulse_cycle: int = 0
        self._is_interacting: bool  = False
        self._active_plant = None        # Plant being interacted with
        self._indicator_tick: int = 0    # drives animated "..." above plant
        # Butterfly-chase exclamation mark
        self._butterfly_chase: bool    = False
        self._exclaim_spring: float    = 0.0   # pop-in spring phase (radians)
        self._exclaim_decay:  float    = 0.0   # 1.0→0 pop-in envelope
        self._exclaim_y:      float    = 0.0   # smoothed Y position (lerp lag)
        self._exclaim_ticks:  int      = 0     # ticks since chase started

        self._garden = None
        self._garden_floor_y: int = 0
        self._task_flowers: list  = []
        self._falling_seeds: list = []

        # Startup grow animation — displayed stage floats toward actual stage
        _GROW_RATE = 1 / 28          # 1 stage per 28 ticks → ~1.9 s seed-to-bloom at 60 fps
        self._plant_display_stages: list[float] = []   # one per plant
        self._plant_display_frames: list[float] = []   # growth_frame per plant, animated on startup
        self._plant_grow_delay: int = 18   # ticks to wait before growing starts
        self._plant_grow_rate: float = _GROW_RATE
        self._plant_jiggle: list[dict] = []   # per-plant sway animation state
        # Task-flower bloom animation: displayed frac grows toward the live
        # bloom_frac (used on startup + after a click-dismiss regrow).
        self._task_flower_display_fracs: list[float] = []  # one per task flower
        # Ticks each flower stays hidden after being clicked (then it regrows).
        self._flower_hidden_ticks: list[float] = []

        # Hover-tooltip state
        self._hovered_plant_idx: int | None = None
        self._hovered_task_flower_idx: int | None = None
        self._bugs: list        = []
        self._butterflies: list = []
        self._friend_bugs: list = []
        self._lazy_bugs: list   = []
        self._coins: list       = []
        self._effects: list     = []
        self._shrubs: list      = []
        self._rocks: list       = []
        self._rock_pixmaps: list = []  # [small (1×), medium (2×)] cached QPixmap
        # User-toggleable decor visibility (from hub Settings → world_settings.json).
        self._flowers_hidden: bool = False   # hides garden plants + task flowers
        self._rocks_hidden:   bool = False   # hides the static rocks
        self._cat_hidden:     bool = False   # hides Sao herself
        self._creatures_hidden: bool = False # master: hides ALL ambient creatures
        # Per-species hides (in addition to the master toggle above).
        self._ladybugs_hidden:   bool = False
        self._butterflies_hidden: bool = False
        self._friendbugs_hidden: bool = False
        # "Gween bean" mode — everything goes green-ish.
        self._greenbeans: bool = False
        self._green_rock_cache: dict = {}   # id(pixmap) → green-tinted pixmap
        # Density-controlled decor carpets (sliders in hub Settings, 0..100).
        # Available always — NOT tied to greenbeans.
        self._grass_density: int = 0
        self._rock_density:  int = 0
        # Extra grass tufts carpeting the floor: list of _GrassTuft (mutable so
        # each can carry its own live disturbance state).  Regenerated when the
        # grass-density slider changes.
        self._extra_grass: list = []
        # Extra purely-cosmetic rocks: [(x, scale)] regenerated on slider change.
        self._extra_rocks: list = []
        # Cache of scaled (+ optionally mossy) extra-rock pixmaps, keyed by
        # (rounded scale, greenbeans) so we don't re-scale/tint every frame.
        self._extra_rock_cache: dict = {}
        # Breeze state: a gust front sweeping left → right.  None = calm air.
        self._breeze_front: 'float | None' = None
        self._breeze_phase: float = 0.0
        self._breeze_timer: int = _rnd.randint(*_BREEZE_GAP)
        self._prev_cursor_x: float = 0.0
        # ── Grass CPU optimisation ──────────────────────────────────────────
        # Combined (extra grass + shrubs) list, rebuilt only when either set
        # changes — avoids re-allocating a concat every frame in _tick_grass.
        self._all_grass: list = []
        # Frames of active disturbance remaining.  While 0 (and no breeze) the
        # per-blade decay/apply loops are skipped entirely.
        self._disturb_ticks_left: int = 0
        # Pre-rendered static grass carpet (all tufts at rest).  Blitted in one
        # drawPixmap when the air is calm + nothing is disturbed, instead of
        # redrawing every tuft each frame.  Invalidated on density change.
        self._grass_carpet_pms: dict = {}       # layer (0=back,1=front) → cached pixmap
        self._grass_carpet_baseline: int = 48   # px of headroom above the floor
        # Static short-grass bed (the ground layer that fills gaps at high
        # density).  Rebuilt on density/width change; blitted behind the tufts.
        self._grass_bed_pm: 'QPixmap | None' = None
        self._grass_bed_dirty: bool = True
        self._grass_bed_baseline: int = 13  # px tall (room for varied blade heights)
        self._grass_bed_density: int = 0    # own slider (0..100), separate from tufts
        self._extra_tall_grass: bool = False  # ~30% of tufts grow extra tall
        # "Working inside an app" marker — (cx, top_y) of the window Sao has
        # ducked into, or None.  Drawn as a small coloured underline.
        self._work_ind: 'tuple[int, int] | None' = None
        self._work_ind_phase: float = 0.0
        self._cat_working: bool = False   # hidden because she's inside an app
        # Cat opacity while stepping into / out of a taskbar icon (1.0 = solid).
        self._cat_enter_alpha: float = 1.0
        # Brief speech bubble above Sao's head (reactions like "Nice work!").
        self._sao_msg: str = ''
        self._sao_msg_until_ms: int = 0
        # Napping — sleepy Z's drift up off her head.
        self._napping: bool = False
        self._nap_phase: float = 0.0
        # Macaron treat (fed from the hub).  main owns its logic; the overlay
        # draws it + lets the user drag it around like Sao.
        self._macaron: 'tuple | None' = None   # (cx, by, alpha) draw position, or None
        self._macaron_grab: bool = False        # True while the user is dragging it
        self._macaron_grab_off = QPoint(0, 0)
        self._macaron_drag_pt  = QPoint(0, 0)
        self._feed_requested: bool = False      # set by the hub bridge, drained by main
        # Placeable blocks (2D-Minecraft).  main owns the dict {(c,r): style};
        # the overlay draws them, shows the grid, and handles placement clicks.
        self._blocks: dict = {}                 # shared ref, set by main
        self._block_mode: bool = False
        self._block_style: int = 0              # 0=dirt+grass-top, 1=grassy
        self._on_blocks_changed = None          # callback → main persists
        self._block_pm_cache: dict = {}         # style → pre-rendered QPixmap
        # (cx, bottom_y) of the taskbar icon Sao is working inside → teal bar.
        self._work_icon_bar: 'tuple[int, int] | None' = None
        # x of the flower Sao is currently tending (forced in front of her so
        # she reads as "behind / working on it"), or None.
        self._gardening_flower_x: 'int | None' = None
        # todo_id of the flower to pulse-highlight (hub hover), or ''.
        self._highlight_flower_id: str = ''
        self._ground_grass_layout: list | None = None  # precomputed [(x, frame_idx, flip)]
        self._plant_foreground: list[bool] = []   # True = flower draws in front of Sao

        self._hut_x: int = 0
        self._hut_floor_y: int = 0
        self._hut_smoke: list = []
        self._hut_indicator_tick: int = 0
        self._sao_in_hut: bool = False
        self._hut_pixmap: QPixmap | None = None
        self._taskbar_bg_left: int = 0    # cached strip bounds (set in set_hut)
        self._taskbar_bg_right: int = 0
        # House hover / press / jiggle button state
        self._hut_hover: bool         = False
        self._hut_pressed: bool       = False
        self._hut_jiggle: float       = 0.0   # phase (radians)
        self._hut_jiggle_decay: float = 0.0   # 1.0→0.0 amplitude envelope
        # Hut drag-to-reposition state.  The house is click-through by
        # default (so it never blocks taskbar apps underneath); the user
        # arms move-mode from Sao's right-click menu, which makes the house
        # grabbable until they drop it.
        self._hut_dragging:   bool = False
        self._hut_move_armed: bool = False
        self._hut_hidden:   bool  = False   # True = sprite hidden; hub via Sao right-click
        self._on_hut_moved: 'callable | None' = None   # (x) → save new position
        # Task-flower drag-to-reposition: hold + move a flower to place it.
        self._on_flower_moved: 'callable | None' = None  # () → persist new x's
        self._flower_drag_idx: int | None = None
        self._flower_drag_started: bool = False
        self._flower_press_x: int = 0
        self._on_hut_hide:  'callable | None' = None   # () → save hidden flag
        # Candle glow: rare double-pulse state machine
        self._hut_glow_state: str  = 'idle'   # idle|on1|off1|on2|done
        self._hut_glow_timer: int  = _rnd.randint(200, 450)
        # Interior window cursor state
        self._cursor_over_interior: bool = False

        self._dust: list = []   # skid dust particles (reference from main)

        # Pomodoro overlay — flip-dot timer panel + hut/strip transition.
        # Lives in the world overlay; driven by PomodoroWindow callbacks.
        self.pomodoro = PomodoroOverlay()

        self._visitors: list = []   # NPC visitors (reference from main)
        self._soldiers: list = []   # Soldier NPCs (reference from main)

        self._scared_of_orc: bool    = False   # drives reddish exclamation mark
        self._orc_fear_fading: bool  = False   # True while red ! is fading out after fear ends

        # Animators — load after QApplication exists
        self._animator: Animator | None = None
        self._sprite_dir = sprite_dir

        # Hand-drawn sprite sheet (flowers, butterflies)
        self._sprites: SpriteSheet | None = None
        # Flower tint cache: (anim_idx, hue_shift) → list[QPixmap] (all frames, tinted once)
        self._flower_tinted_cache: dict[tuple[int, int], list[QPixmap]] = {}
        self._snails: list = []

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self._click_through: bool | None = None   # cache: skip redundant setAttribute
        self._set_click_through(True)

    def showEvent(self, event) -> None:
        """Load sprites on first show (QApplication is guaranteed ready)."""
        super().showEvent(event)
        if self._animator is None:
            anim = Animator(self._sprite_dir)
            if anim.load():
                self._animator = anim
            else:
                print('[CatOverlay] sprites failed to load — using blob fallback')
        if not self._rock_pixmaps:
            rock_path = os.path.join(self._sprite_dir, 'rock.png')
            rock_pm = QPixmap(rock_path)
            if not rock_pm.isNull():
                # Crop bottom 13 % so the rock sits flush on the ground
                crop_h = max(1, int(rock_pm.height() * 0.87))
                rock_pm = rock_pm.copy(0, 0, rock_pm.width(), crop_h)
                # Force every non-transparent pixel to full opacity so rocks
                # look solid, not washed-out from semi-transparent source pixels
                _rimg = rock_pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
                for _ry in range(_rimg.height()):
                    for _rx in range(_rimg.width()):
                        _px = _rimg.pixel(_rx, _ry)
                        if ((_px >> 24) & 0xFF) > 20:
                            _rimg.setPixel(_rx, _ry, _px | 0xFF000000)
                rock_pm = QPixmap.fromImage(_rimg)
                self._rock_pixmaps = [
                    rock_pm,                                         # 1× small
                    rock_pm.scaled(                                  # 2× medium
                        rock_pm.width() * 2, rock_pm.height() * 2,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    ),
                ]
            else:
                print('[CatOverlay] rock.png failed to load')

        if self._sprites is None:
            ss = SpriteSheet(scale=2)
            if ss.load():
                self._sprites = ss
                register_loaded_sheet(ss)
            else:
                print('[CatOverlay] AnimationsBugsAndFlowers.png failed to load')

    # ------------------------------------------------------------------
    # Public API for main loop
    # ------------------------------------------------------------------

    def set_flowers_hidden(self, hidden: bool) -> None:
        """Toggle visibility of garden plants + task flowers."""
        self._flowers_hidden = bool(hidden)
        self.update()

    def set_rocks_hidden(self, hidden: bool) -> None:
        """Toggle visibility of the static decorative rocks."""
        self._rocks_hidden = bool(hidden)
        self.update()

    def say(self, text: str, ms: int = 2800) -> None:
        """Show a brief speech bubble above Sao (auto-clears after `ms`).
        It only renders while she's actually on screen — if she's hidden or
        tucked inside an app the reaction is simply skipped."""
        text = (text or '').strip()
        if not text:
            return
        from PyQt6.QtCore import QDateTime
        self._sao_msg = text[:40]
        self._sao_msg_until_ms = QDateTime.currentMSecsSinceEpoch() + max(600, int(ms))
        self.update()

    def set_cat_hidden(self, hidden: bool) -> None:
        """Toggle visibility of Sao herself (she keeps living, just unseen)."""
        self._cat_hidden = bool(hidden)
        self.update()

    def set_creatures_hidden(self, hidden: bool) -> None:
        """Master toggle for ALL ambient creatures (butterflies, ladybugs,
        friend-bugs)."""
        self._creatures_hidden = bool(hidden)
        self.update()

    def set_ladybugs_hidden(self, hidden: bool) -> None:
        self._ladybugs_hidden = bool(hidden); self.update()

    def set_butterflies_hidden(self, hidden: bool) -> None:
        self._butterflies_hidden = bool(hidden); self.update()

    def set_friendbugs_hidden(self, hidden: bool) -> None:
        self._friendbugs_hidden = bool(hidden); self.update()

    def set_greenbeans(self, on: bool) -> None:
        """Toggle 'gween bean' — bugs go green, rocks tint mossy green.  (Grass
        amount is now its own slider, independent of this.)  Clears tint caches
        so the green re-applies."""
        on = bool(on)
        if on == self._greenbeans:
            return
        self._greenbeans = on
        # Drop cached tints so they rebuild for / against green mode.
        for _lb in self._lazy_bugs:      _lb._tinted_frames = None
        for _bf in self._butterflies:    _bf._tinted_frames = None
        for _fb in self._friend_bugs:
            _fb._tinted_sitting = None; _fb._tinted_flying = None
        self._green_rock_cache = {}
        self._extra_rock_cache = {}     # mossy/plain variants must rebuild
        self.update()

    def _regen_extra_grass(self) -> None:
        """(Re)build the grass-density carpet from the current slider value."""
        self._grass_carpet_pms = {}         # static caches are now stale
        n = round(self._grass_density / 100.0 * _GRASS_MAX)
        if n <= 0:
            self._extra_grass = []
            self._rebuild_all_grass()
            return
        rng = _rnd.Random(42)            # fixed seed → stable layout across paints
        w   = max(400, self.width())
        # ~30% of tufts go BEHIND Sao (layer 0) for depth; ~30% are flagged tall
        # (extra-tall when that toggle is on).  Both rolled independently.
        self._extra_grass = [
            _GrassTuft(rng.randint(6, w - 6),
                       rng.randint(0, _GRASS_TUFT_VARIANTS - 1),
                       rng.uniform(0.7, 1.5),
                       layer=0 if rng.random() < 0.30 else 1,
                       tall=rng.random() < 0.30)
            for _ in range(n)
        ]
        self._rebuild_all_grass()

    def _regen_extra_rocks(self) -> None:
        """(Re)build the cosmetic extra-rock scatter from the slider value."""
        n = round(self._rock_density / 100.0 * _ROCK_MAX)
        if n <= 0:
            self._extra_rocks = []
            return
        rng = _rnd.Random(99)
        w   = max(400, self.width())
        # Mix the SMALL and MEDIUM rock sprites (like the real decor rocks) so
        # the extras aren't all tiny — medium is the 2x sprite, so a 0.7-1.0x
        # medium reads bigger than a scaled small.
        out = []
        for _ in range(n):
            rx = rng.randint(16, w - 16)
            if rng.random() < 0.45:
                out.append((rx, 1, rng.uniform(0.7, 1.05)))   # medium base
            else:
                out.append((rx, 0, rng.uniform(1.1, 1.8)))    # small base, scaled up
        self._extra_rocks = out

    def set_grass_density(self, value) -> None:
        """Grass carpet density 0..100 (hub slider).  Available always."""
        try:
            v = max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            return
        if v == self._grass_density:
            return
        self._grass_density = v
        self._extra_grass = []          # rebuild lazily on next paint
        self.update()

    def set_extra_tall_grass(self, on: bool) -> None:
        """Toggle the extra-tall variation on ~30% of grass tufts."""
        on = bool(on)
        if on == self._extra_tall_grass:
            return
        self._extra_tall_grass = on
        self._grass_carpet_pms = {}   # heights changed → rebuild cached carpets
        self.update()

    def set_grass_bed(self, value) -> None:
        """Short backing-grass 'bed' density 0..100 (its own hub lever)."""
        try:
            v = max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            return
        if v == self._grass_bed_density:
            return
        self._grass_bed_density = v
        self._grass_bed_dirty = True
        self.update()

    def set_rock_density(self, value) -> None:
        """Cosmetic extra-rock density 0..100 (hub slider)."""
        try:
            v = max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            return
        if v == self._rock_density:
            return
        self._rock_density = v
        self._extra_rocks = []
        self._extra_rock_cache = {}
        self.update()

    def _green_rock(self, pm: 'QPixmap') -> 'QPixmap':
        """Mossy rock for greenbeans mode: a green tint that only creeps up
        from the BOTTOM along a ragged (non-straight) line, fading out toward
        the top.  The rock's own light/dark shading is preserved (we keep each
        pixel's value/brightness and only push its hue toward green), so it
        still reads as a rock — just one with moss at its base."""
        if not self._greenbeans or pm is None or pm.isNull():
            return pm
        key = id(pm)
        cached = self._green_rock_cache.get(key)
        if cached is not None:
            return cached
        try:
            img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            w, h = img.width(), img.height()
            # Per-column moss height (px up from the bottom).  Two out-of-phase
            # sines + a tiny hash give a ragged, non-repeating waterline.
            def _moss_top(col: int) -> float:
                base = 0.34 * h
                wob  = (math.sin(col * 0.55) * 0.10
                        + math.sin(col * 0.21 + 1.7) * 0.13) * h
                jag  = ((col * 2654435761) % 7 - 3) * 0.012 * h
                return h - max(2.0, base + wob + jag)
            for col in range(w):
                top = _moss_top(col)
                span = max(1.0, h - top)
                for row in range(h):
                    c = img.pixelColor(col, row)
                    if c.alpha() <= 10 or row < top:
                        continue
                    strength = 0.20 + 0.70 * ((row - top) / span)   # deeper = greener
                    strength = max(0.0, min(0.95, strength))
                    hh, s, v = c.hsvHue(), c.saturation(), c.value()
                    new_s = min(255, int(s + strength * 150))
                    new_v = int(v * (1.0 - strength * 0.22))         # moss darkens a touch
                    c.setHsv(_GREEN_HUE, new_s, new_v, c.alpha())
                    img.setPixelColor(col, row, c)
            tinted = QPixmap.fromImage(img)
        except Exception:
            tinted = pm
        self._green_rock_cache[key] = tinted
        return tinted

    def _grey_wash(self, pm: 'QPixmap') -> 'QPixmap':
        """Sao keeps her natural colours even in greenbeans mode — she's the
        one thing that stays normal so she pops against the green world.
        Kept as a pass-through so the call site doesn't need a branch."""
        return pm

    def _breeze_lean(self, x: float) -> float:
        """Horizontal lean (px) at world-x `x` from the current breeze, or 0 if
        the air is calm.  A gust front (Gaussian envelope) sweeps left → right;
        within it the blades ripple, so wind reads as blowing in from the left."""
        if self._breeze_front is None:
            return 0.0
        env = math.exp(-((x - self._breeze_front) / _BREEZE_WIDTH) ** 2)
        return _BREEZE_AMP * env * math.sin(_WIND_K * x - self._breeze_phase)

    def _grass_lean(self, x: float, obj) -> float:
        """Total blade lean (px) for a tuft/shrub: the breeze plus its own
        decaying disturbance from Sao or the cursor having brushed past."""
        return self._breeze_lean(x) + obj.disturb * _DISTURB_AMP * obj.disturb_dir

    def _tick_grass(self, cat) -> None:
        """Advance grass animation once per frame: schedule/advance the breeze,
        then rustle any grass that Sao or the cursor is sweeping past."""
        # ── Breeze: occasional gust front travelling left → right ───────────
        if self._breeze_front is not None:
            self._breeze_front += _BREEZE_SPEED
            self._breeze_phase += _WIND_SPEED
            if self._breeze_front > self.width() + _BREEZE_WIDTH:
                self._breeze_front = None
                self._breeze_timer = _rnd.randint(*_BREEZE_GAP)
        else:
            self._breeze_timer -= 1
            if self._breeze_timer <= 0:
                self._breeze_front = -_BREEZE_WIDTH   # enter from off the left edge
                self._breeze_phase = 0.0

        # ── Disturbance: Sao + cursor brushing past grass ───────────────────
        # Each disturber is (x, dir, radius).  Sao's body is wide so she gets a
        # broader reach; the cursor must be almost literally ON a tuft.
        fy = self._garden_floor_y
        disturbers: list[tuple[float, float, float]] = []
        if cat is not None and cat.grounded and abs(cat.vx) > 0.6:
            disturbers.append((cat.x + cat.width / 2,
                               1.0 if cat.vx > 0 else -1.0, _DISTURB_RADIUS_SAO))
        try:
            cur = self.mapFromGlobal(QCursor.pos())
            cx  = float(cur.x())
            # The blades stand up to ~28 px above the floor, so let the cursor
            # rustle them from higher up (over the tips), not just right at the
            # floor line.
            if fy > 0 and (fy - 34) <= cur.y() <= (fy + 8):
                dxc = cx - self._prev_cursor_x
                if abs(dxc) > 1.5:
                    disturbers.append((cx, 1.0 if dxc > 0 else -1.0,
                                       _DISTURB_RADIUS_CURSOR))
            self._prev_cursor_x = cx
        except Exception:
            pass

        # Fast path: nothing is disturbed and nothing new is arriving → skip the
        # per-blade loops entirely (the common idle case).
        if not disturbers and self._disturb_ticks_left <= 0:
            return

        # Decay every blade's disturbance, then (re)apply from any disturber.
        grass = self._all_grass
        if self._disturb_ticks_left > 0:
            self._disturb_ticks_left -= 1
            for g in grass:
                if g.disturb > 0.0:
                    g.disturb = max(0.0, g.disturb - _DISTURB_DECAY)
        for (dx, ddir, radius) in disturbers:
            peak = 0.0
            for g in grass:
                d = abs(g.x - dx)
                if d < radius:
                    strength = 1.0 - d / radius
                    if strength > g.disturb:
                        g.disturb = strength
                        g.disturb_dir = ddir
                        if strength > peak:
                            peak = strength
            # Keep the decay loop alive just long enough for this push to settle.
            life = int(peak / _DISTURB_DECAY) + 2
            if life > self._disturb_ticks_left:
                self._disturb_ticks_left = life

    def set_work_indicator(self, pos) -> None:
        """Show / move the 'Sao is working inside this app' marker.
        pos is (center_x, window_top_y) in logical px, or None to clear."""
        self._work_ind = pos

    def set_cat_working(self, working: bool) -> None:
        """Hide Sao because she's ducked inside an app to work (distinct from
        being in the hut, so the house's sleep indicator isn't triggered)."""
        self._cat_working = bool(working)

    def set_cat_enter_alpha(self, alpha: float) -> None:
        """Opacity of Sao while she's stepping into / out of a taskbar icon.
        1.0 = fully solid, 0.0 = invisible (fully inside the app)."""
        try:
            a = float(alpha)
        except (TypeError, ValueError):
            a = 1.0
        self._cat_enter_alpha = max(0.0, min(1.0, a))

    def set_work_icon_bar(self, pos) -> None:
        """Show / move the teal 'Sao is inside this app' bar drawn under a
        taskbar icon.  pos is (center_x, bottom_y) in logical px, or None."""
        self._work_icon_bar = pos

    def set_garden(self, garden, floor_y: int) -> None:
        """Attach a Garden so plants are drawn every frame."""
        self._garden       = garden
        self._garden_floor_y = floor_y
        # Start each plant's displayed stage at its ACTUAL saved stage so that
        # crops (potatoes, carrots) appear immediately at their correct size.
        # Flower growth_frames also start at their saved value so they don't
        # need to re-animate from scratch on every session load.
        plants = garden.plants if garden else []
        self._plant_display_stages = []
        self._plant_display_frames = []
        for p in plants:
            if getattr(p, 'plant_type', 0) == 0:   # PLANT_FLOWER — grow in from seed
                self._plant_display_stages.append(0.0)
                self._plant_display_frames.append(0.0)
            else:                                    # Crops — appear immediately
                self._plant_display_stages.append(float(p.stage))
                self._plant_display_frames.append(float(getattr(p, 'growth_frame', 0)))
        self._plant_grow_delay = 80   # short pre-animation pause
        self._plant_jiggle = [
            {'idle': _rnd.randint(600, 1800), 'active': 0, 'total': 80}
            for _ in plants
        ]
        # Randomly assign each flower a depth layer (True=foreground/in-front of Sao).
        # Crops are always background (they're on the ground).
        self._plant_foreground = [
            (getattr(p, 'plant_type', 0) == 0 and _rnd.random() < 0.5)
            for p in plants
        ]

    def set_grass_positions(self, positions: list[tuple[int, int]]) -> None:
        """No-op — grass background removed."""

    def set_task_flowers(self, flowers: list) -> None:
        """Store reference to the live task-flower list.

        Existing flowers keep their grow progress; brand-new flowers start at
        0 so they animate up.  (main re-pushes this list whenever todos change,
        so we must NOT blanket-reset or flowers would re-grow constantly.)
        """
        self._task_flowers = flowers
        n   = len(flowers)
        cur = self._task_flower_display_fracs
        self._task_flower_display_fracs = [cur[i] if i < len(cur) else 0.0
                                           for i in range(n)]
        ch = self._flower_hidden_ticks
        self._flower_hidden_ticks = [ch[i] if i < len(ch) else 0.0
                                     for i in range(n)]

    def set_falling_seeds(self, seeds: list) -> None:
        """Store reference to the live falling-seed list."""
        self._falling_seeds = seeds

    def set_critters(self, bugs: list, butterflies: list,
                     coins: list, effects: list) -> None:
        """Store references to the live critter lists (mutated each tick by main)."""
        self._bugs        = bugs
        self._butterflies = butterflies
        self._coins       = []   # coins removed
        self._effects     = effects

    # ── Macaron treat ───────────────────────────────────────────────────
    def request_feed(self) -> None:
        """Called by the hub bridge when the user hits 'feed'."""
        self._feed_requested = True

    def consume_feed_request(self) -> bool:
        """main drains this each tick; True once per hub 'feed' press."""
        if self._feed_requested:
            self._feed_requested = False
            return True
        return False

    def set_macaron(self, cx, by, alpha: float = 1.0) -> None:
        """Place (or clear with cx=None) the macaron treat at centre-x `cx`,
        bottom-y `by`.  `alpha` lets main fade it if needed."""
        self._macaron = None if cx is None else (float(cx), float(by), float(alpha))

    def macaron_grabbed(self) -> bool:
        return self._macaron_grab

    def macaron_drag_pos(self) -> QPoint:
        return self._macaron_drag_pt

    # ── Blocks ──────────────────────────────────────────────────────────
    def set_blocks(self, blocks: dict) -> None:
        """Share main's {(c,r): style} dict so the overlay can draw + edit it."""
        self._blocks = blocks

    def set_block_mode(self, on: bool) -> None:
        self._block_mode = bool(on)
        # Capture all clicks while placing; restore normal click-through on exit
        # (the next hit-test refines it based on what's under the cursor).
        self._set_click_through(not self._block_mode)
        self.update()

    def cycle_block_style(self) -> None:
        self._block_style ^= 1
        self.update()

    def set_friend_bugs(self, friend_bugs: list) -> None:
        """Store reference to the FriendBug list (ABug3 cursor pets)."""
        self._friend_bugs = friend_bugs

    def set_lazy_bugs(self, lazy_bugs: list) -> None:
        """Store reference to the LazyBug list (ABug1 ground critters)."""
        self._lazy_bugs = lazy_bugs

    def set_snails(self, snails: list) -> None:
        """Store reference to the ambient Snail list."""
        self._snails = snails

    def set_shrubs(self, shrubs: list) -> None:
        """Store reference to the static shrub list (spawned once at session start)."""
        self._shrubs = shrubs
        self._rebuild_all_grass()

    def _rebuild_all_grass(self) -> None:
        """Refresh the combined grass list used by the per-frame disturbance
        loop, so _tick_grass never re-concats two lists every frame."""
        self._all_grass = list(self._extra_grass) + list(self._shrubs)

    def set_rocks(self, rocks: list) -> None:
        """Store reference to the static rock list (spawned once at session start)."""
        self._rocks = rocks

    def rock_top_y(self, rock) -> float:
        """Return the y-coordinate of the visible top surface of a rock sprite."""
        if not self._rock_pixmaps:
            return float(rock.y) - 20
        pm = self._rock_pixmaps[rock.variant % len(self._rock_pixmaps)]
        return float(rock.y) - pm.height()

    def plant_top_y(self, plant) -> float:
        """Return the y-coordinate of the visible top surface of a flower plant's sprite.

        Uses the same frame and scale logic as _draw_plant so the returned y
        exactly matches the top pixel of what's drawn on screen.  Falls back to
        the PLANT_TOP_HEIGHTS table if the sprite sheet isn't loaded yet.
        """
        from desktop_cat.garden import PLANT_TOP_HEIGHTS
        floor_y = float(self._garden_floor_y)
        if not (self._sprites and self._sprites.loaded):
            return floor_y - PLANT_TOP_HEIGHTS[min(getattr(plant, 'stage', 0), 4)] * 2
        anim_type = getattr(plant, 'variant', 0) % 5
        anim_idx  = [ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER,
                     ANIM_RED_FLOWER, ANIM_WHITE_FLOWER, ANIM_TALL_FLOWER][anim_type]
        hue_shift = _FLOWER_VARIANT_HUE[getattr(plant, 'variant', 0) % len(_FLOWER_VARIANT_HUE)]
        cache_key = (anim_idx, hue_shift)
        tinted = self._flower_tinted_cache.get(cache_key) or self._sprites.frames(anim_idx)
        if tinted:
            gf = getattr(plant, 'growth_frame', 0)
            # Same stage-4 snap as _draw_plant
            if plant.stage >= 4 and len(tinted) > 1:
                gf = len(tinted) - 1
            gf    = max(0, min(gf, len(tinted) - 1))
            frame = tinted[gf]
            scale = _FLOWER_ANIM_SCALES[min(anim_type, len(_FLOWER_ANIM_SCALES) - 1)] * getattr(plant, 'size_scale', 1.0)
            sh    = int(frame.height() * scale)
            return floor_y - sh
        return floor_y - PLANT_TOP_HEIGHTS[min(getattr(plant, 'stage', 0), 4)] * 2

    def jiggle_plant_at(self, x: float) -> None:
        """Immediately trigger a sway animation on the nearest flower plant to x.

        Called when a bug lands on or takes off from a plant, so the plant
        visually reacts.  Only jiggles flowers (not crops); only activates if
        a flower is within 60 px of x.
        """
        if not self._garden:
            return
        best_i = -1
        best_d = 60.0  # px radius — ignore plants farther than this
        for i, plant in enumerate(self._garden.plants):
            if getattr(plant, 'plant_type', 0) != 0:  # flowers only
                continue
            d = abs(plant.x - x)
            if d < best_d:
                best_d = d
                best_i = i
        if best_i >= 0 and best_i < len(self._plant_jiggle):
            jig = self._plant_jiggle[best_i]
            jig['active'] = jig['total']
            jig['idle']   = _rnd.randint(600, 1800)
            # Sync — wiggle any landed butterflies that are sitting on this
            # plant so they shake with the flower instead of looking glued.
            self._pulse_landed_butterflies_at(self._garden.plants[best_i].x)

    def _pulse_landed_butterflies_at(self, x: float, radius: float = 20.0) -> None:
        """Trigger jiggle_active on any landed butterflies near `x`.  Called
        whenever a flower's jiggle starts so its passengers shake too."""
        if not self._butterflies:
            return
        for bf in self._butterflies:
            if getattr(bf, 'state', '') != 'landed':
                continue
            if abs(getattr(bf, 'land_x', bf.x) - x) <= radius:
                bf.jiggle_active = bf.jiggle_total

    def set_active_plant(self, plant) -> None:
        """Called by main when Sao starts/stops tending a plant."""
        self._active_plant = plant
        if plant is None:
            self._indicator_tick = 0

    def set_hut(self, x: int, floor_y: int) -> None:
        """Register hut position. floor_y = screen_h (absolute bottom)."""
        self._hut_x       = x
        self._hut_floor_y = floor_y
        self._hut_smoke   = []
        # Load cabin PNG and scale to ~46 px tall (same apparent size as old mushroom house)
        house_path = os.path.join(self._sprite_dir, 'sao_house_cabin.png')
        if os.path.exists(house_path):
            pm = QPixmap(house_path)
            if not pm.isNull():
                TARGET_H = 46
                scale    = TARGET_H / pm.height()
                scaled   = pm.scaled(
                    max(1, int(pm.width() * scale)),
                    TARGET_H,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,  # nearest-neighbour → crisp pixels
                )
                self._hut_pixmap = self._add_outline(scaled)
            else:
                self._hut_pixmap = None
        else:
            self._hut_pixmap = None
        # Cache strip bounds so _draw_taskbar_bg never flickers.
        # The olive strip now HUGS the house (user: "make it way shorter
        # length-wise") — just a small margin each side of the sprite,
        # instead of the old half-width-left + 2-widths-right sprawl.
        hw = self._hut_pixmap.width() if (self._hut_pixmap and not self._hut_pixmap.isNull()) else 42
        _margin = int(hw * 0.18)
        self._taskbar_bg_left  = max(0, x - hw // 2 - _margin)
        self._taskbar_bg_right = x + hw // 2 + _margin

    def set_dust(self, particles: list) -> None:
        """Store reference to the live dust-particle list (mutated each tick by main)."""
        self._dust = particles

    def set_visitors(self, visitors: list) -> None:
        """No-op — orc/knight removed."""

    def set_soldiers(self, soldiers: list) -> None:
        """No-op — orc/knight removed."""

    def set_sao_in_hut(self, inside: bool) -> None:
        self._sao_in_hut = inside
        if not inside:
            self._hut_indicator_tick = 0

    def set_height_scale(self, mod: float) -> None:
        global _CAT_DRAW_SCALE
        _CAT_DRAW_SCALE = 1.08 * mod

    # ── Intro drop-in trail (rarity-colored streak behind Sao) ───────────────
    def start_intro_drop(self, rarity: str) -> None:
        """Enable a colored trail behind Sao while she's falling from the sky.

        Call at the start of `_begin_main_loop`. The trail auto-clears when the
        cat lands (overlay watches cat.grounded each frame).
        """
        _RARITY_COLORS = {
            'grey':     (200, 200, 210),
            'common':   (200, 200, 210),
            'uncommon': (120, 200, 120),
            'rare':     ( 80, 140, 220),
            'epic':     (160,  80, 220),
            'legendary':(220, 160,  40),
        }
        rgb = _RARITY_COLORS.get(rarity, (200, 200, 210))
        self._intro_drop_active = True
        self._intro_drop_color  = QColor(*rgb)
        self._intro_drop_rarity = rarity
        self._aura_particles    = []
        self._intro_drop_landed = False

    def _stop_intro_drop(self) -> None:
        self._intro_drop_active = False
        self._aura_particles = []

    def house_screen_pos(self) -> tuple[int, int] | None:
        """Center of the house sprite in screen coords (None if not laid out)."""
        if self._hut_x <= 0:
            return None
        # Hut anchors at bottom-center, floor_y is the ground line
        return (int(self._hut_x), int(self._hut_floor_y) - 16)

    def has_intro_drop_landed(self) -> bool:
        """True if the intro drop is still active but Sao has touched ground."""
        return self._intro_drop_active and self._intro_drop_landed

    def consume_intro_drop_landing(self) -> tuple[float, float, QColor] | None:
        """Pop the landing event so main can fire an impact effect once."""
        if not self.has_intro_drop_landed():
            return None
        cat = self._cat
        if cat is None:
            self._stop_intro_drop()
            return None
        cx = float(cat.x + cat.width / 2)
        cy = float(cat.y + cat.height)
        col = QColor(self._intro_drop_color)
        self._stop_intro_drop()
        return (cx, cy, col)

    def _draw_intro_drop_trail(self, p: QPainter) -> None:
        """Draw soft aura particles radiating from Sao while she's falling."""
        if not self._intro_drop_active or not self._aura_particles:
            return
        base = self._intro_drop_color
        p.setPen(Qt.PenStyle.NoPen)
        for (x, y, vx, vy, age, max_age, hue_off) in self._aura_particles:
            frac  = age / max_age                       # 0=fresh, 1=dead
            alpha = int(160 * (1.0 - frac) ** 1.8)     # soft quadratic fade
            r     = 3.5 + frac * 4.0                   # grows gently as it drifts
            if self._intro_drop_rarity == 'rainbow':
                hue = int((hue_off + age * 6) % 360)
                col = QColor.fromHsv(hue, 190, 255, alpha)
            else:
                col = QColor(base.red(), base.green(), base.blue(), alpha)
            p.setBrush(QBrush(col))
            p.drawEllipse(QRectF(x - r, y - r, r * 2, r * 2))

    def update_state(self, cat: CatState, platforms: list[Platform],
                     occluded: bool = False,
                     wind_up_frac: float = 0.0,
                     anim_override: str | None = None,
                     chasing_butterfly: bool = False,
                     scared_of_orc: bool = False) -> None:
        self._cat       = cat
        self._platforms = platforms
        self._occluded  = occluded
        self._is_interacting = anim_override is not None and anim_override.startswith('interact')
        self._napping = (anim_override == 'nap')
        if self._napping:
            self._nap_phase += 0.018

        # Intro drop aura tracking
        if self._intro_drop_active and cat is not None:
            import random as _r, math as _m
            cx = float(cat.x + cat.width / 2)
            cy = float(cat.y + cat.height / 2)
            # Spawn 3 soft aura particles each tick
            for _ in range(3):
                angle = _r.uniform(0, _m.tau)
                speed = _r.uniform(0.3, 1.0)
                vx = _m.cos(angle) * speed
                vy = _m.sin(angle) * speed - 0.5   # bias upward
                max_age = _r.randint(28, 58)
                hue_off = _r.randint(0, 360)
                self._aura_particles.append([cx, cy, vx, vy, 0, max_age, hue_off])
            # Tick all particles (velocity + damping)
            for pt in self._aura_particles:
                pt[0] += pt[2]; pt[1] += pt[3]   # x += vx, y += vy
                pt[2] *= 0.92; pt[3] *= 0.92      # damp
                pt[4] += 1                         # age
            self._aura_particles = [pt for pt in self._aura_particles if pt[4] < pt[5]]
            if cat.grounded and not self._intro_drop_landed:
                self._intro_drop_landed = True
                # Will be cleared next frame; main can read this flag
                # via has_intro_drop_landed() for impact effect.

        # Exclamation mark — shown for butterfly chase AND orc fear.
        # Orc fear pins decay at 1.0 while active, then fades out when fear ends.
        show_exclaim      = chasing_butterfly or scared_of_orc
        prev_exclaim      = self._butterfly_chase or self._scared_of_orc or self._orc_fear_fading
        prev_scared_orc   = self._scared_of_orc
        self._butterfly_chase = chasing_butterfly
        self._scared_of_orc   = scared_of_orc

        # Fear just ended — trigger red fade-out
        if prev_scared_orc and not scared_of_orc:
            self._orc_fear_fading = True
            self._exclaim_decay   = 1.0   # fresh fade from full alpha
            self._exclaim_y       = float(cat.y)

        if show_exclaim and not prev_exclaim:
            # Fresh trigger — pop in immediately
            self._exclaim_spring  = math.pi * 0.5
            self._exclaim_decay   = 1.0
            self._exclaim_y       = float(cat.y)
            self._exclaim_ticks   = 0
            self._orc_fear_fading = False

        if show_exclaim:
            if chasing_butterfly:
                # Butterfly: spring pop-in and Y lerp for bobbing effect
                self._exclaim_spring += 0.28
                self._exclaim_y      += (float(cat.y) - self._exclaim_y) * 0.35
                self._exclaim_decay   = max(0.0, self._exclaim_decay - 0.035)
            else:
                # Orc fear: static above head, decay pinned at 1.0 while active
                self._exclaim_y     = float(cat.y)
                self._exclaim_decay = 1.0
            self._exclaim_ticks += 1
        elif self._orc_fear_fading:
            # Red ! fading out — count down decay
            self._exclaim_y       = float(cat.y)
            self._exclaim_decay   = max(0.0, self._exclaim_decay - 0.045)
            self._exclaim_ticks  += 1
            if self._exclaim_decay <= 0.0:
                self._orc_fear_fading = False
        else:
            self._exclaim_ticks   = 0
        if self._animator:
            winding_up = wind_up_frac > 0.0
            anim = anim_override if anim_override else _anim_name(cat, winding_up)
            self._animator.update(
                anim,
                cat.vx,
                vy=cat.vy,
                grounded=cat.grounded,
                wind_up_frac=wind_up_frac,
            )
            if (self._is_interacting
                    and self._animator.cycle_just_completed
                    and self._animator.cycle_count - self._last_pulse_cycle >= 2):
                self._pulse_ticks      = 35
                self._last_pulse_cycle = self._animator.cycle_count
        if self._active_plant is not None:
            self._indicator_tick += 1
        # (House + on-taskbar pomodoro flip-dots were removed — their per-frame
        # smoke / jiggle / state-machine ticks no longer run.)
        # Startup grow animation — advance displayed stages toward actual
        self._tick_grow_animation()
        self._tick_plant_jiggle()
        self._tick_grass(cat)          # breeze + Sao/cursor disturbance for grass
        self._work_ind_phase += 0.06   # drives work-marker + flower-highlight pulses
        self._update_hit_test()
        self.update()

    def drag_position(self) -> QPoint:
        return self._drag_pos

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        # Block mode: left-click places (or replaces) a block at the hovered
        # cell; right-click removes it.  Toggling avoids needing a separate
        # erase tool.
        if self._block_mode and self._garden_floor_y > 0:
            cell = blocks_data.cell_at(event.pos().x(), event.pos().y(),
                                       self._garden_floor_y)
            if event.button() == Qt.MouseButton.RightButton:
                self._blocks.pop(cell, None)
            elif event.button() == Qt.MouseButton.LeftButton:
                if self._blocks.get(cell) == self._block_style:
                    self._blocks.pop(cell, None)        # same style → erase (toggle)
                elif len(self._blocks) < blocks_data.MAX_BLOCKS or cell in self._blocks:
                    self._blocks[cell] = self._block_style
            else:
                return
            if self._on_blocks_changed:
                self._on_blocks_changed()
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # Grab the macaron treat to drag it around (checked first so it can be
        # picked up even if it's sitting near Sao).
        if self._macaron is not None:
            mcx, mby, _ma = self._macaron
            if (abs(event.pos().x() - mcx) < MACARON_HIT
                    and abs(event.pos().y() - (mby - 6)) < MACARON_HIT):
                self._macaron_grab     = True
                self._macaron_grab_off = event.pos() - QPoint(int(mcx), int(mby))
                self._macaron_drag_pt  = QPoint(int(mcx), int(mby))
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        # Grab Sao to drag her (only when she's actually visible).
        if (self._cat is not None and not self._sao_in_hut
                and not self._cat_working and not self._cat_hidden):
            cat_cx = int(self._cat.x + self._cat.width  / 2)
            cat_cy = int(self._cat.y + self._cat.height / 2)
            if (abs(event.pos().x() - cat_cx) < HIT_RADIUS and
                    abs(event.pos().y() - cat_cy) < HIT_RADIUS):
                cat_pos = QPoint(int(self._cat.x), int(self._cat.y))
                self._drag_offset = event.pos() - cat_pos
                self._drag_pos    = cat_pos
                self.is_dragging  = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        # Press on a flower → start a drag candidate.  A quick click (no
        # movement) tucks it away; holding and moving repositions it.
        if self._hovered_task_flower_idx is not None:
            self._flower_drag_idx     = self._hovered_task_flower_idx
            self._flower_drag_started = False
            self._flower_press_x      = event.pos().x()
            return

    def _dismiss_flower(self, idx: int) -> None:
        """Hide a clicked flower for ~5 s, then it regrows from a sprout back
        to full bloom (the same seed→bloom animation used on startup)."""
        if 0 <= idx < len(self._flower_hidden_ticks):
            self._flower_hidden_ticks[idx] = 300   # ~5 s at 60 fps
            if idx < len(self._task_flower_display_fracs):
                self._task_flower_display_fracs[idx] = 0.0   # regrow from sprout
            self._hovered_task_flower_idx = None
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._macaron_grab:
            self._macaron_drag_pt = event.pos() - self._macaron_grab_off
            self.update()
            return
        if self._hut_dragging:
            self._hut_x = max(20, min(self.width() - 20, event.pos().x()))
            self.update()
            return
        # Dragging a task flower to reposition it along the taskbar.
        if self._flower_drag_idx is not None:
            if abs(event.pos().x() - self._flower_press_x) > 4:
                if not self._flower_drag_started:
                    self._flower_drag_started = True
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._flower_drag_started:
                idx = self._flower_drag_idx
                if 0 <= idx < len(self._task_flowers):
                    newx = max(8, min(self.width() - 8, event.pos().x()))
                    try:
                        self._task_flowers[idx].x = float(newx)
                    except Exception:
                        pass
                    self.update()
            return
        if self.is_dragging:
            self._drag_pos = event.pos() - self._drag_offset
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._macaron_grab:
            self._macaron_grab = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._hut_dragging:
            self._hut_dragging   = False
            self._hut_move_armed = False   # one drop ends move-mode
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if self._on_hut_moved:
                self._on_hut_moved(self._hut_x)
            self.update()
            return
        if self.pomodoro.mouse_release(event.pos()):
            self.update()
            return
        # Finish a flower drag (persist) — or, if it never moved, treat the
        # press as a click and tuck the flower away.
        if self._flower_drag_idx is not None:
            idx = self._flower_drag_idx
            dragged = self._flower_drag_started
            self._flower_drag_idx     = None
            self._flower_drag_started = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if dragged:
                if self._on_flower_moved:
                    self._on_flower_moved()
            else:
                self._dismiss_flower(idx)
            self.update()
            return
        if self.is_dragging:
            self.is_dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _make_menu(self) -> 'QMenu':
        """A right-click menu with explicit dark styling — without this the
        items inherit an unreadable palette (text invisible until hovered)."""
        menu = QMenu(self)
        menu.setStyleSheet(
            'QMenu{background:#26262b;color:#eaeaf0;border:1px solid #3a3a42;'
            'border-radius:8px;padding:5px;}'
            'QMenu::item{padding:7px 22px 7px 16px;border-radius:6px;'
            'background:transparent;}'
            'QMenu::item:selected{background:#3b6ea5;color:#ffffff;}'
            'QMenu::separator{height:1px;background:#3a3a42;margin:5px 10px;}'
        )
        return menu

    def contextMenuEvent(self, event) -> None:
        if self._cat is None:
            return
        cursor = self.mapFromGlobal(QCursor.pos())

        # Sao right-click menu
        cat_cx  = int(self._cat.x + self._cat.width  / 2)
        cat_cy  = int(self._cat.y + self._cat.height / 2)
        if abs(cursor.x() - cat_cx) > HIT_RADIUS * 2 or abs(cursor.y() - cat_cy) > HIT_RADIUS * 2:
            return

        menu = self._make_menu()

        open_act = menu.addAction('Open window')
        hide_act = menu.addAction('Hide Sao & décor')
        menu.addSeparator()
        quit_act = menu.addAction('Quit')

        action = menu.exec(event.globalPos())

        if action == open_act and self._bus:
            self._bus.publish('OPEN_HUB', {})
        elif action == hide_act and self._bus:
            self._bus.publish('HIDE_ALL', {})
        elif action == quit_act:
            if self._bus:
                self._bus.publish('QUIT_APP', {})
            else:
                from PyQt6.QtWidgets import QApplication
                QApplication.quit()

    def set_gardening_flower(self, x) -> None:
        """x of the flower Sao is tending (drawn in front of her), or None."""
        self._gardening_flower_x = x

    def set_highlight_flower(self, todo_id: str) -> None:
        """todo_id of the flower to pulse (hub hover), or '' to clear."""
        tid = str(todo_id or '')
        if tid != self._highlight_flower_id:
            self._highlight_flower_id = tid
            self.update()

    @staticmethod
    def _stable_front(key) -> bool:
        """Deterministic, no-flicker 'is in front of Sao' for a decor item."""
        return bool(hash(key) & 1)

    def _flower_is_front(self, tf) -> bool:
        gx = self._gardening_flower_x
        if gx is not None and abs(int(tf.x) - gx) <= 22:
            return True   # she's tending it → she stays behind it
        return self._stable_front((str(getattr(tf, 'todo_id', '')), int(tf.x)))

    def _flower_sprite_geom(self, tf):
        """(frame_pixmap, draw_x, draw_top, sw, sh) for a task flower, or None.
        Used for pixel-perfect hover hit-testing on larger blooms."""
        if not self._sprites or not self._sprites.loaded:
            return None
        from desktop_cat.sprite_sheet import (ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER,
                                               ANIM_RED_FLOWER, ANIM_WHITE_FLOWER,
                                               ANIM_TALL_FLOWER)
        anim_type = (getattr(tf, 'variant', 0) or 0) % 5
        anim_idx  = [ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER, ANIM_RED_FLOWER,
                     ANIM_WHITE_FLOWER, ANIM_TALL_FLOWER][anim_type]
        frames = self._sprites.frames(anim_idx)
        if not frames:
            return None
        n  = len(frames)
        gf = max(0, min(int(round(tf.bloom_frac() * (n - 1))), n - 1))
        frame = frames[gf]
        scale = _FLOWER_ANIM_SCALES[min(anim_type, len(_FLOWER_ANIM_SCALES) - 1)]
        sw = int(frame.width() * scale)
        sh = int(frame.height() * scale)
        return (frame, int(tf.x) - sw // 2, self._garden_floor_y - sh, sw, sh)

    def _flower_pixel_hit(self, tf, cx, cy) -> bool:
        """True only if the cursor is over a non-transparent pixel of the
        flower sprite (not just its bounding box)."""
        g = self._flower_sprite_geom(tf)
        if g is None:
            return False
        frame, dx, dtop, sw, sh = g
        if sw <= 0 or sh <= 0 or not (dx <= cx < dx + sw and dtop <= cy < dtop + sh):
            return False
        fx = max(0, min(int((cx - dx) / sw * frame.width()),  frame.width()  - 1))
        fy = max(0, min(int((cy - dtop) / sh * frame.height()), frame.height() - 1))
        try:
            return frame.toImage().pixelColor(fx, fy).alpha() > 40
        except Exception:
            return True

    def _flower_due_today(self, tf) -> bool:
        """True if the flower's task is due today or overdue."""
        from datetime import date as _d
        try:
            due = _d.fromisoformat((tf.due_date or '')[:10])
        except Exception:
            return False
        return (due - _d.today()).days <= 0

    def _draw_task_flowers(self, painter: QPainter, front: bool) -> None:
        if not self._task_flowers or self._flowers_hidden:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        hid = self._highlight_flower_id
        hov = self._hovered_task_flower_idx
        hd  = self._flower_hidden_ticks
        df  = self._task_flower_display_fracs
        for i, tf in enumerate(self._task_flowers):
            if i < len(hd) and hd[i] > 0:
                continue   # clicked-away — hidden for a few seconds, then returns
            if self._flower_is_front(tf) != front:
                continue
            disp = df[i] if i < len(df) else tf.bloom_frac()
            self._draw_task_flower(
                painter, int(tf.x), self._garden_floor_y,
                disp, tf.done,
                overdue=tf.is_past_due() and not tf.done,
                variant=getattr(tf, 'variant', 0),
                pop_ticks=getattr(tf, 'pop_anim_ticks', 0),
                due_today=self._flower_due_today(tf),
                highlight=bool(hid and str(getattr(tf, 'todo_id', '')) == hid),
                faded=(i == hov))

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        # No antialiasing — pixel art looks best without it
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if self.debug:
            self._draw_platforms(painter)

        cat = self._cat
        _cat_visible = (cat is not None and not self._occluded
                        and not self._sao_in_hut and not self._cat_hidden
                        and not self._cat_working)
        _on_window   = cat is not None and cat.on_hwnd is not None

        # (Intro drop-in bubble trail removed — Sao still drops in, just
        # without the trailing bubbles.)

        # Sao on a window platform → draw BEHIND the house
        if _cat_visible and _on_window:
            _pos = self._drag_pos if self.is_dragging else QPoint(int(cat.x), int(cat.y))
            self._draw_cat(painter, _pos, cat.width, cat.height)

        # Teal "Sao is inside this app" bar under its taskbar icon.
        if self._work_icon_bar is not None:
            self._draw_work_icon_bar(painter)

        # ── Snail — behind large rocks so it hides underneath them ───────────
        for sn in self._snails:
            self._draw_snail(painter, sn)

        # ── Background layer — big rocks + bushes rendered BEHIND Sao ───────
        if self._rocks and self._rock_pixmaps and not self._rocks_hidden:
            for rock in self._rocks:
                if rock.variant >= 1:
                    pm = self._rock_pixmaps[min(rock.variant,
                                                len(self._rock_pixmaps) - 1)]
                    pm = self._green_rock(pm)
                    painter.drawPixmap(QPoint(int(rock.x) - pm.width() // 2,
                                             int(rock.y) - pm.height()), pm)
        if self._shrubs:
            painter.setPen(Qt.PenStyle.NoPen)
            for shrub in self._shrubs:
                if shrub.bush_style:
                    self._draw_shrub(painter, shrub)

        self._draw_dust(painter)

        # Background garden pass — flowers assigned to the back layer appear
        # behind Sao (giving the illusion of depth in the plant bed)
        if self._garden is not None and not self._flowers_hidden:
            self._draw_garden(painter, foreground_pass=False)

        # Background small rocks + task flowers — the ~half assigned to the
        # BACK layer, so Sao passes in FRONT of them (depth randomised per item).
        if self._rocks and self._rock_pixmaps and not self._rocks_hidden:
            pm0      = self._rock_pixmaps[0]
            pm0_draw = self._green_rock(pm0)
            for rock in self._rocks:
                if rock.variant == 0 and not self._stable_front((int(rock.x), int(rock.y))):
                    painter.drawPixmap(QPoint(int(rock.x) - pm0_draw.width() // 2,
                                             int(rock.y) - pm0_draw.height()), pm0_draw)
        # Cosmetic extra-rock scatter (slider-driven), behind Sao.
        if (self._rock_density > 0 and self._rock_pixmaps
                and not self._rocks_hidden and self._garden_floor_y > 0):
            self._draw_extra_rocks(painter)
        self._draw_task_flowers(painter, front=False)

        # Placeable blocks — drawn behind Sao so she stands on top of them.
        if self._blocks and self._garden_floor_y > 0:
            self._draw_blocks(painter, cat)

        # Grass BED (ground layer) + the ~30% of tufts assigned BEHIND Sao,
        # drawn before her so she appears to stand among the grass.
        if self._garden_floor_y > 0:
            if self._grass_bed_density > 0:
                if (self._grass_bed_dirty
                        or (self._grass_bed_pm is not None
                            and self._grass_bed_pm.width() != self.width())):
                    self._build_grass_bed()
                if self._grass_bed_pm is not None:
                    painter.drawPixmap(
                        0, self._garden_floor_y - self._grass_bed_baseline,
                        self._grass_bed_pm)
            self._paint_grass_layer(painter, 0)

        # Sao on the floor → drawn in front of background layer
        if _cat_visible and not _on_window:
            _pos = self._drag_pos if self.is_dragging else QPoint(int(cat.x), int(cat.y))
            self._draw_cat(painter, _pos, cat.width, cat.height)

        # ── Foreground layer — small rocks + grass tufts in front of Sao ────
        if self._rocks and self._rock_pixmaps and not self._rocks_hidden:
            pm0      = self._rock_pixmaps[0]
            pm0_draw = self._green_rock(pm0)
            for rock in self._rocks:
                if rock.variant == 0 and self._stable_front((int(rock.x), int(rock.y))):
                    painter.drawPixmap(QPoint(int(rock.x) - pm0_draw.width() // 2,
                                             int(rock.y) - pm0_draw.height()), pm0_draw)
        if self._shrubs:
            painter.setPen(Qt.PenStyle.NoPen)
            for shrub in self._shrubs:
                if not shrub.bush_style:
                    self._draw_shrub(painter, shrub)

        # Front grass tufts (~70%) — drawn over Sao for a "walking through it"
        # look.  (The bed + back ~30% were drawn before her, above.)
        self._paint_grass_layer(painter, 1)

        # Foreground garden pass — remaining flowers drawn in front of Sao
        if self._garden is not None and not self._flowers_hidden:
            self._draw_garden(painter, foreground_pass=True)

        # Foreground task flowers — the ~half assigned to the FRONT layer
        # (plus whichever Sao is currently tending), drawn over her.
        self._draw_task_flowers(painter, front=True)

        # Falling seeds descending to the floor
        if self._falling_seeds:
            painter.setPen(Qt.PenStyle.NoPen)
            for fs in self._falling_seeds:
                self._draw_falling_seed(painter, int(fs.x), int(fs.y))

        # Critters on top of everything (hidden when creatures are toggled off)
        painter.setPen(Qt.PenStyle.NoPen)
        if not self._creatures_hidden:
            if not self._ladybugs_hidden:
                for lb in self._lazy_bugs:
                    self._draw_lazy_bug(painter, lb)
            for bug in self._bugs:          # flower bees follow the master toggle only
                self._draw_bug(painter, bug)
            if not self._butterflies_hidden:
                for bf in self._butterflies:
                    if bf.alive:
                        self._draw_butterfly(painter, bf)
            if not self._friendbugs_hidden:
                for fb in self._friend_bugs:
                    if fb.alive:
                        self._draw_friend_bug(painter, fb)
        for eff in self._effects:
            if eff.alive:
                self._draw_collect_effect(painter, eff)

        # Exclamation mark — always on top, even above critters
        if (self._butterfly_chase or self._scared_of_orc or self._orc_fear_fading) and _cat_visible:
            _ep = self._drag_pos if self.is_dragging else QPoint(int(cat.x), int(cat.y))
            self._draw_exclamation(painter, _ep, cat.width, cat.height)

        # Flower / plant hover tooltip — drawn very last (topmost)
        if self._hovered_plant_idx is not None and self._garden is not None:
            plants = self._garden.plants
            if self._hovered_plant_idx < len(plants):
                self._draw_plant_tooltip(painter, plants[self._hovered_plant_idx],
                                         self._hovered_plant_idx)
        elif self._hovered_task_flower_idx is not None:
            tfs = self._task_flowers
            if self._hovered_task_flower_idx < len(tfs):
                self._draw_task_flower_tooltip(painter,
                                               tfs[self._hovered_task_flower_idx])

        # Block-placement grid + ghost (only while in block mode), on top.
        if self._block_mode and self._garden_floor_y > 0:
            self._draw_block_grid(painter)

        # Macaron treat — drawn near world level so Sao can come eat it.
        if self._macaron is not None:
            if self._macaron_grab:
                self._draw_macaron_treat(painter, self._macaron_drag_pt.x(),
                                         self._macaron_drag_pt.y(), 1.0)
            else:
                _mcx, _mby, _ma = self._macaron
                self._draw_macaron_treat(painter, _mcx, _mby, _ma)

        # Sao speech bubble — a brief reaction above her head, topmost.
        if _cat_visible and self._sao_msg:
            from PyQt6.QtCore import QDateTime as _QDT
            if _QDT.currentMSecsSinceEpoch() < self._sao_msg_until_ms:
                _bp = self._drag_pos if self.is_dragging else QPoint(int(cat.x), int(cat.y))
                self._draw_sao_bubble(painter, _bp, cat.width)
            else:
                self._sao_msg = ''

        # Napping Z's — drift up off her head while she dozes.
        if _cat_visible and self._napping and not self._sao_msg:
            self._draw_nap_zs(painter, int(cat.x), int(cat.y), cat.width)

        painter.end()

    def _draw_blocks(self, painter: QPainter, cat) -> None:
        """Blit every placed block (cached pixmap), fading each by how close Sao
        is (so they reveal as she nears).  In block mode they're shown at full
        opacity so you can see what you're editing."""
        floor = self._garden_floor_y
        cat_cx = cat.x + cat.width / 2 if cat is not None else 0.0
        cat_cy = cat.y + cat.height / 2 if cat is not None else 0.0
        near = blocks_data.BLOCK_FADE_NEAR
        far  = blocks_data.BLOCK_FADE_FAR
        S = blocks_data.BLOCK_SIZE
        for (c, r), style in self._blocks.items():
            x, y, _w, _h = blocks_data.cell_rect(c, r, floor)
            if self._block_mode or cat is None:
                alpha = 1.0
            else:
                bx, by = x + S / 2, y + S / 2
                d = math.hypot(bx - cat_cx, by - cat_cy)
                if d >= far:
                    continue
                alpha = 1.0 if d <= near else (far - d) / float(far - near)
            painter.setOpacity(alpha)
            painter.drawPixmap(x, y, self._block_pixmap(style))
        painter.setOpacity(1.0)

    def _block_pixmap(self, style: int) -> 'QPixmap':
        """Cached pixely Minecraft-ish block: textured texels, jagged grass/dirt
        boundary, speckles, ever-so-slightly rounded corners.  One per style."""
        pm = self._block_pm_cache.get(style)
        if pm is not None:
            return pm
        S = blocks_data.BLOCK_SIZE
        T = 2
        n = S // T
        # Grass tones taken from the ground grass palette (_GRASS_COLS) so the
        # blocks blend with the lawn rather than looking like stark MC blocks.
        if style == blocks_data.STYLE_DIRT:
            top = [(52, 125, 55), (82, 165, 74), (65, 138, 64)]
            bod = [(126, 90, 58), (112, 80, 50), (138, 102, 66), (104, 74, 48)]
            grass_rows = 3
        else:
            top = [(52, 125, 55), (82, 165, 74), (65, 138, 64), (44, 112, 78)]
            bod = top
            grass_rows = n
        pm = QPixmap(S, S)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setPen(Qt.PenStyle.NoPen)
        seed = 1234567 if style == blocks_data.STYLE_DIRT else 7654321
        for tx in range(n):
            col_h = grass_rows + (((seed ^ (tx * 83492791)) >> 3) % 3 - 1)
            for ty in range(n):
                if (tx in (0, n - 1)) and (ty in (0, n - 1)):
                    continue  # rounded corners
                pal = top if ty < col_h else bod
                hsh = (tx * 374761393) ^ (ty * 668265263) ^ seed
                col = pal[hsh % len(pal)]
                if ty == n - 1 or tx == n - 1:
                    col = (int(col[0] * 0.82), int(col[1] * 0.82), int(col[2] * 0.82))
                p.setBrush(QColor(*col))
                p.drawRect(tx * T, ty * T, T, T)
        p.end()
        self._block_pm_cache[style] = pm
        return pm

    def _draw_block_grid(self, painter: QPainter) -> None:
        """The torch-lit placement grid around the cursor + a ghost of the
        block about to be placed, plus a tiny style/▢ R hint."""
        cur   = self.mapFromGlobal(QCursor.pos())
        floor = self._garden_floor_y
        S = blocks_data.BLOCK_SIZE
        R = blocks_data.TORCH_RADIUS
        ccur, rcur = blocks_data.cell_at(cur.x(), cur.y(), floor)
        span = R // S + 1
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for dc in range(-span, span + 1):
            for dr in range(-span, span + 1):
                x, y, w, h = blocks_data.cell_rect(ccur + dc, rcur + dr, floor)
                gx, gy = x + w / 2, y + h / 2
                d = math.hypot(gx - cur.x(), gy - cur.y())
                if d > R:
                    continue
                av = int(64 * (1.0 - d / R))
                if av <= 1:
                    continue
                painter.setPen(QColor(255, 255, 255, av))
                painter.drawRect(x, y, w, h)
        # Ghost of the block to be placed.
        gx, gy, gw, gh = blocks_data.cell_rect(ccur, rcur, floor)
        painter.setOpacity(0.55)
        painter.drawPixmap(gx, gy, self._block_pixmap(self._block_style))
        painter.setOpacity(1.0)
        painter.setPen(QColor(255, 255, 255, 200))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(gx, gy, gw, gh)
        # Style hint above the cursor.
        f = QFont('Segoe UI', 8)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(255, 255, 255, 215))
        _name = 'dirt' if self._block_style == blocks_data.STYLE_DIRT else 'grass'
        painter.drawText(gx, gy - 6, f'{_name}  ·  R switch  ·  Esc exit')

    def _draw_macaron_treat(self, painter: QPainter, cx, by, alpha: float = 1.0) -> None:
        """A small pink macaron (two shells + cream filling), centred at x=cx
        with its bottom at y=by.  Pixel-art to match the garden sprites."""
        painter.setPen(Qt.PenStyle.NoPen)
        a   = max(0, min(255, int(255 * alpha)))
        MP  = QColor(242, 180, 212, a)   # shell body
        MS  = QColor(206, 138, 172, a)   # shell shadow edge
        MH  = QColor(255, 219, 236, a)   # shell highlight
        FIL = QColor(255, 228, 190, a)   # cream filling
        S   = 2
        x   = int(cx); base = int(by)

        def blk(bx, bup, w, h, c):
            painter.setBrush(c)
            painter.drawRect(x + bx * S, base - (bup + h) * S, w * S, h * S)

        # bottom shell
        blk(-3, 0, 6, 2, MP); blk(-3, 0, 1, 2, MS); blk(2, 0, 1, 2, MS)
        blk(-2, 2, 4, 1, MH)
        # cream filling
        blk(-3, 3, 6, 1, FIL)
        # top shell
        blk(-3, 4, 6, 2, MP); blk(-3, 4, 1, 2, MS); blk(2, 4, 1, 2, MS)
        blk(-2, 6, 4, 1, MH)

    def _draw_nap_zs(self, painter: QPainter, cx: int, cy: int, cat_w: int) -> None:
        """Three little 'z's rising and fading above Sao's head while she naps."""
        base_x = cx + cat_w // 2 + 6
        base_y = cy + 2
        f = QFont('Segoe UI', 0)
        for i in range(3):
            t = (self._nap_phase + i / 3.0) % 1.0   # 0→1 life of each z
            alpha = int(210 * (1.0 - t))             # fade out as it rises
            if alpha <= 0:
                continue
            size = 9 + int(i * 2.5)                   # later z's slightly bigger
            f.setPixelSize(size)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor(150, 170, 230, alpha))
            x = base_x + int(i * 4 + math.sin(t * 6.28) * 2)
            y = base_y - int(t * 26) - i * 6
            painter.drawText(x, y, 'z')

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _draw_sao_bubble(self, painter: QPainter, cat_pos: QPoint, cat_w: int) -> None:
        """A small rounded speech bubble with a downward tail, centered above
        Sao's head — used for short reactions like 'Nice work! 🌸'."""
        text = self._sao_msg
        if not text:
            return
        from PyQt6.QtGui import QFont, QFontMetrics, QColor, QPainterPath
        font = QFont('Segoe UI', 9)
        font.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(font)
        PAD_X, PAD_Y = 9, 6
        tw, th = fm.horizontalAdvance(text), fm.height()
        bw, bh = tw + PAD_X * 2, th + PAD_Y * 2
        cat_cx = cat_pos.x() + cat_w // 2
        bx = cat_cx - bw // 2
        by = cat_pos.y() - bh - 10            # gap above her head
        bx = max(4, min(bx, self.width() - bw - 4))
        by = max(2, by)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(252, 250, 245, 242))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bx, by, bw, bh, 9, 9)
        # Downward tail pointing at Sao
        tail_cx = max(bx + 10, min(cat_cx, bx + bw - 10))
        path = QPainterPath()
        path.moveTo(tail_cx - 6, by + bh)
        path.lineTo(tail_cx + 6, by + bh)
        path.lineTo(tail_cx,     by + bh + 7)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QColor(40, 38, 34))
        painter.setFont(font)
        painter.drawText(bx + PAD_X, by + PAD_Y + fm.ascent(), text)

    def _set_click_through(self, enabled: bool) -> None:
        # Called ~60×/s from the hit-test; skip the Qt round-trip when unchanged.
        if enabled == self._click_through:
            return
        self._click_through = enabled
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)

    def set_interior_cursor_active(self, active: bool) -> None:
        """Called by InteriorWindow when cursor enters/leaves it."""
        self._cursor_over_interior = active
        # Keep overlay click-through while interior window is active
        if active:
            self._set_click_through(True)

    def _cursor_over_hut(self, cursor: QPoint) -> bool:
        """True if cursor is within the house sprite bounds — accounts for
        the pomodoro tween so the hut stays clickable while shrunken."""
        if (self._hut_x <= 0 or self._hut_pixmap is None
                or self._hut_pixmap.isNull()):
            return False
        pw = self._hut_pixmap.width()
        ph = self._hut_pixmap.height()
        pomo_dx, pomo_dy, pomo_s = self.pomodoro.hut_transform()
        cx_h = self._hut_x + pomo_dx
        fy_h = self._hut_floor_y + pomo_dy
        pw_s = max(1, int(pw * pomo_s))
        ph_s = max(1, int(ph * pomo_s))
        return (cx_h - pw_s // 2 <= cursor.x() <= cx_h + pw_s // 2 and
                fy_h - ph_s <= cursor.y() <= fy_h)

    def _cursor_over_strip(self, cursor: QPoint) -> bool:
        """True if cursor is within the green taskbar strip (but not the house itself)."""
        if self._taskbar_bg_right <= 0 or self._garden_floor_y <= 0:
            return False
        INSET = 8
        top = self._garden_floor_y + INSET
        bot = self.height() - INSET
        return (self._taskbar_bg_left <= cursor.x() <= self._taskbar_bg_right and
                top <= cursor.y() <= bot)

    def _disarm_hut_move(self) -> None:
        """Cancel armed move-mode if the user never grabbed the house."""
        if self._hut_move_armed and not self._hut_dragging:
            self._hut_move_armed = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def _hut_proximity_alpha(self) -> float:
        """House opacity based on how close Sao is — like the potato blocks.
        Faint when Sao is far (so it doesn't obscure taskbar apps), solid
        when she's near, being moved, or resting inside it."""
        # Always fully visible while interacting with / moving the house, or
        # when Sao is tucked inside it.
        if (self._hut_move_armed or self._hut_dragging or self._hut_hover
                or self._sao_in_hut):
            return 1.0
        if self._cat is None:
            return 1.0
        _MIN, _NEAR, _FAR = 0.22, 90.0, 320.0
        dx = abs((self._cat.x + self._cat.width / 2) - self._hut_x)
        if dx <= _NEAR:
            return 1.0
        if dx >= _FAR:
            return _MIN
        t = (dx - _NEAR) / (_FAR - _NEAR)
        return 1.0 - t * (1.0 - _MIN)

    def _hut_current_scale(self) -> float:
        """Scale factor for the house sprite (hover grow, press shrink, jiggle on release)."""
        if self._hut_pressed:
            return 0.90
        if self._hut_jiggle_decay > 0.0:
            # Settle toward hover scale (1.08) if cursor is still over house,
            # so there is no jump when the jiggle finishes.
            base = 1.08 if self._hut_hover else 1.0
            return base + 0.05 * math.sin(self._hut_jiggle) * self._hut_jiggle_decay
        if self._hut_hover:
            return 1.08
        return 1.0

    def _tick_hut_jiggle(self) -> None:
        """Advance the post-click spring-jiggle animation."""
        if self._hut_jiggle_decay > 0.0:
            self._hut_jiggle       += 0.28   # slower phase → smoother, gentler oscillation
            self._hut_jiggle_decay  = max(0.0, self._hut_jiggle_decay - 0.050)

    def _update_hit_test(self) -> None:
        if self.is_dragging:
            return
        # In block mode the whole overlay captures clicks (so we can place
        # blocks anywhere) and the grid follows the cursor.
        if self._block_mode:
            self._set_click_through(False)
            self.update()
            return
        cursor = self.mapFromGlobal(QCursor.pos())

        over_cat = False
        # Only grab (and therefore block clicks for) Sao when she's actually
        # visible — not while hidden inside an app / occluded / in the hut.
        if (self._cat is not None and not self._sao_in_hut
                and not self._cat_working and not self._cat_hidden
                and not self._occluded):
            cat_cx = int(self._cat.x + self._cat.width  / 2)
            cat_cy = int(self._cat.y + self._cat.height / 2)
            over_cat = (abs(cursor.x() - cat_cx) < HIT_RADIUS and
                        abs(cursor.y() - cat_cy) < HIT_RADIUS)


        # ── Flower / plant hover (for tooltip) ───────────────────────────
        old_pi  = self._hovered_plant_idx
        old_tfi = self._hovered_task_flower_idx
        self._hovered_plant_idx       = None
        self._hovered_task_flower_idx = None
        floor_y = self._garden_floor_y
        if floor_y > 0:
            cx_cur, cy_cur = cursor.x(), cursor.y()
            # Regular plants
            if self._garden is not None:
                from desktop_cat.garden import PLANT_TOP_HEIGHTS
                for i, plant in enumerate(self._garden.plants):
                    s    = (int(self._plant_display_stages[i])
                            if i < len(self._plant_display_stages) else plant.stage)
                    h_px = PLANT_TOP_HEIGHTS[min(s, len(PLANT_TOP_HEIGHTS) - 1)] * 2 + 4
                    if (abs(cx_cur - plant.x) <= 14 and
                            floor_y - h_px - 2 <= cy_cur <= floor_y + 2):
                        self._hovered_plant_idx = i
                        break
            # Task flowers: large blooms (>=40%) use a pixel-perfect test so
            # the tooltip only triggers over the ACTUAL sprite; smaller ones
            # keep the loose box so they stay easy to hover.
            if self._hovered_plant_idx is None:
                hd = self._flower_hidden_ticks
                for j, tf in enumerate(self._task_flowers):
                    # Skip flowers that are currently dismissed (hidden, mid-
                    # regrow) — there's no sprite there to hover or tooltip.
                    if j < len(hd) and hd[j] > 0:
                        continue
                    if tf.bloom_frac() >= 0.40:
                        if self._flower_pixel_hit(tf, cx_cur, cy_cur):
                            self._hovered_task_flower_idx = j
                            break
                    elif (abs(cx_cur - tf.x) <= 16 and
                            floor_y - 42 <= cy_cur <= floor_y + 2):
                        self._hovered_task_flower_idx = j
                        break
        if old_pi != self._hovered_plant_idx or old_tfi != self._hovered_task_flower_idx:
            self.update()

        # Sao, the interior window, and (now) a flower under the cursor capture
        # the mouse.  Clicking a flower dismisses it for a few seconds (it
        # regrows after), which clears it out of the way of the button behind.
        over_flower = self._hovered_task_flower_idx is not None
        over_macaron = False
        if self._macaron is not None:
            mcx, mby, _ma = self._macaron
            over_macaron = (abs(cursor.x() - mcx) < MACARON_HIT
                            and abs(cursor.y() - (mby - 6)) < MACARON_HIT)
        interactive = (over_cat or over_flower or over_macaron
                       or self._cursor_over_interior or self._macaron_grab)
        self._set_click_through(not interactive)
        self.setCursor(Qt.CursorShape.ClosedHandCursor   if self.is_dragging else
                       Qt.CursorShape.OpenHandCursor     if over_cat else
                       Qt.CursorShape.PointingHandCursor if over_flower else
                       Qt.CursorShape.ArrowCursor)

    def _draw_cat(self, painter: QPainter, pos: QPoint, w: int, h: int) -> None:
        if self._animator:
            frame = self._animator.current_frame()
            if frame is not None:
                bounce = self._animator.run_bounce_offset
                fw, fh = frame.width(), frame.height()
                # Scale up by _CAT_DRAW_SCALE (nearest-neighbour keeps pixels crisp)
                sw = int(fw * _CAT_DRAW_SCALE)
                sh = int(fh * _CAT_DRAW_SCALE)
                scaled = frame.scaled(sw, sh,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation)
                scaled = self._grey_wash(scaled)   # subtle grey in greenbeans mode
                # Centre wider sprite over physics box; keep feet at the same floor level
                draw_x = int(pos.x()) - (sw - w) // 2
                draw_y = int(pos.y()) + bounce - (sh - fh)   # shift up by extra height
                # Fade her out as she steps into a taskbar icon.
                ea = self._cat_enter_alpha
                if ea < 1.0:
                    painter.save()
                    painter.setOpacity(max(0.0, min(1.0, ea)))
                    painter.drawPixmap(QPoint(draw_x, draw_y), scaled)
                    painter.restore()
                else:
                    painter.drawPixmap(QPoint(draw_x, draw_y), scaled)
                    self._draw_pulse(painter, pos)
                return

        # Fallback: red blob
        painter.setBrush(CAT_COLOR)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(pos.x(), pos.y(), w, h)

    def _draw_pulse(self, painter: QPainter, pos: QPoint) -> None:
        if self._pulse_ticks <= 0:
            return
        frac   = self._pulse_ticks / 35          # 1→0 as it fades
        radius = int((1 - frac) * 22 + 4)        # grows 4→26 px
        alpha  = int(frac * 70)                   # very faint, 70→0
        cx = pos.x() + CAT_W // 2
        cy = pos.y() + CAT_H // 2
        painter.setPen(QColor(255, 220, 120, alpha))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
        self._pulse_ticks -= 1

    def _draw_exclamation(self, painter: QPainter, pos: QPoint, w: int, h: int) -> None:
        """
        White pixel-art '!' above Sao.
        - Pops in with a damped spring on first frame of chase.
        - Position lerp-follows cat.y (0.15 lag → lags during jumps/runs).
        - run_bounce_offset from animator is applied so it bobs with Sao's run stride.
        - Full colour (~160 alpha) for the first ~2.5 s, then fades to 50 % (~80).
        """
        # Apply the same run-bounce the sprite uses, so exclamation bobs in sync
        bounce = self._animator.run_bounce_offset if self._animator else 0

        # How far the scaled sprite top sits above cat.y (due to 1.08 scale)
        h_scale_extra = int(h * (_CAT_DRAW_SCALE - 1.0))   # ≈ 3 px for CAT_H=40

        # Spring pop-in offset — only for butterfly chase, fades over ~28 ticks
        spring_off = 0 if self._scared_of_orc else int(-5 * math.sin(self._exclaim_spring) * self._exclaim_decay)

        # Final Y: cat.y + bounce offset + above-sprite gap + spring (orc: no spring)
        y_base = int(self._exclaim_y) + bounce - h_scale_extra - 10 + spring_off
        cx     = int(pos.x()) + w // 2

        # Colour and alpha depend on which mode is active
        if self._scared_of_orc:
            # Actively scared — full brightness red
            alpha = 160
            col   = QColor(255, 110, 110, alpha)
        elif self._orc_fear_fading:
            # Fear just ended — red fading out via decay
            alpha = int(160 * self._exclaim_decay)
            col   = QColor(255, 110, 110, alpha)
        else:
            # Butterfly chase — white, full brightness for 150 ticks then dim
            alpha = 160 if self._exclaim_ticks < 150 else 80
            col   = QColor(255, 255, 255, alpha)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        if self._scared_of_orc:
            # Slightly larger for visibility — 3 px wide, 9 px bar, 3×3 dot
            painter.drawRect(cx - 1, y_base,       3, 9)  # exclamation bar
            painter.drawRect(cx - 1, y_base + 11,  3, 3)  # dot
        else:
            painter.drawRect(cx - 1, y_base,      2, 7)   # exclamation bar
            painter.drawRect(cx - 1, y_base + 9,  2, 2)   # dot

    def _draw_dust(self, painter: QPainter) -> None:
        """Draw skid-stop dust puffs."""
        painter.setPen(Qt.PenStyle.NoPen)
        for dp in self._dust:
            age   = dp['age']
            alpha = max(0, 230 - age * 9)
            size  = max(2, 12 - age // 3)
            col   = QColor(220, 205, 175, alpha)
            painter.setBrush(col)
            painter.drawEllipse(int(dp['x']) - size // 2,
                                int(dp['y']) - size // 2,
                                size, size)

    def _tick_hut_smoke(self) -> None:
        """Advance smoke particles and occasionally spawn new ones."""
        if self._hut_x <= 0:
            return
        # Candle double-pulse state machine
        self._hut_glow_timer -= 1
        if self._hut_glow_timer <= 0:
            if self._hut_glow_state == 'idle':
                self._hut_glow_state = 'on1';  self._hut_glow_timer = 10
            elif self._hut_glow_state == 'on1':
                self._hut_glow_state = 'off1'; self._hut_glow_timer = 7
            elif self._hut_glow_state == 'off1':
                self._hut_glow_state = 'on2';  self._hut_glow_timer = 9
            elif self._hut_glow_state == 'on2':
                self._hut_glow_state = 'idle'; self._hut_glow_timer = _rnd.randint(220, 500)

        if len(self._hut_smoke) < 6 and _rnd.randint(0, 24) == 0:
            # Smoke origin: cabin chimney sits at ~top-left of the sprite.
            # The pixmap height includes 2px outline PAD on each side (+4 total).
            # ph - 8  ≈ approx chimney-tip row in the rendered art.
            if self._hut_pixmap and not self._hut_pixmap.isNull():
                ph  = self._hut_pixmap.height()
                _sy = float(self._hut_floor_y - ph + 8)   # ≈ chimney tip row
            else:
                _sy = float(self._hut_floor_y - 42)   # procedural chimney top
            self._hut_smoke.append({
                'x':    float(self._hut_x - 12),      # cabin chimney is slightly left of centre
                'y':    _sy,
                'age':  0,
                'dx':   _rnd.uniform(-0.12, 0.12),
                'rise': _rnd.uniform(0.12, 0.22),   # each puff rises at its own pace
                'sz':   _rnd.uniform(0.8, 1.4),     # per-puff size multiplier
            })
        for p in self._hut_smoke:
            p['age'] += 1
            p['y']   -= p['rise']
            p['x']   += p['dx']
        self._hut_smoke[:] = [p for p in self._hut_smoke if p['age'] < 80]

    @staticmethod
    def _add_outline(pixmap: QPixmap) -> QPixmap:
        """Add a 2-px dark pixel-art outline to a pixmap.
        The canvas is expanded by PAD px on every side so art that touches the
        original edges still gets a full outline (fixes left-side cutoff).
        A 2-px outline is produced by stamping neighbours at offsets ±1 and ±2."""
        img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = img.width(), img.height()
        PAD  = 3                             # 3-px border to accommodate 2-px outline
        ow, oh = w + 2 * PAD, h + 2 * PAD
        out  = QImage(ow, oh, QImage.Format.Format_ARGB32)
        out.fill(0)                          # start fully transparent
        OUTLINE = 0xFF1A1008                 # near-black with warm undertone
        # Offsets that form a filled 2-px thick border (diamond / cross at radius 2)
        _OFFSETS = [
            (-1,  0), ( 1,  0), ( 0, -1), ( 0,  1),   # 1-px cardinal
            (-2,  0), ( 2,  0), ( 0, -2), ( 0,  2),   # 2-px cardinal
            (-1, -1), ( 1, -1), (-1,  1), ( 1,  1),   # 1-px diagonal
        ]
        for y in range(h):
            for x in range(w):
                if ((img.pixel(x, y) >> 24) & 0xFF) > 10:
                    for ddx, ddy in _OFFSETS:
                        nx, ny = x + ddx, y + ddy
                        ox, oy = nx + PAD, ny + PAD
                        if 0 <= ox < ow and 0 <= oy < oh:
                            in_orig = 0 <= nx < w and 0 <= ny < h
                            orig_a  = (img.pixel(nx, ny) >> 24) & 0xFF if in_orig else 0
                            if orig_a < 10:
                                out.setPixel(ox, oy, OUTLINE)
        p = QPainter(out)
        p.drawImage(PAD, PAD, img)           # original image offset by the padding
        p.end()
        return QPixmap.fromImage(out)

    def _draw_taskbar_bg(self, painter: QPainter) -> None:
        """Rounded pixelated green patch behind the house/garden area."""
        if self._garden_floor_y <= 0 or self._taskbar_bg_right <= 0:
            return
        CELL  = 10
        # Equal inset on top and bottom so the strip floats inside the taskbar
        # (like the Search bar in the user's screenshot)
        INSET = 8
        top   = self._garden_floor_y + INSET - 4  # raised so the olive sits higher behind the house
        bot   = self.height() - INSET

        # Use cached bounds (computed once in set_hut — no per-frame fluctuation)
        left_x  = self._taskbar_bg_left
        right_x = self._taskbar_bg_right

        strip_w = right_x - left_x
        strip_h = bot - top
        if strip_w <= 0 or strip_h <= 0:
            return

        # Push fresh strip / hut bounds to the pomodoro overlay so its panel
        # rect tracks any DPI / window movement.
        self.pomodoro.update_layout(left_x, right_x, top, bot,
                                    self._hut_x, self._hut_floor_y)

        # Hiding the hut hides its olive strip too (they're one decoration).
        # Done AFTER update_layout so the pomodoro panel still positions.
        if self._hut_hidden:
            return

        # Pomodoro animation: strip slides DOWN off-screen (and stays gone
        # while timer is active). The grass overlay below is drawn separately
        # and is unaffected.
        strip_dy = self.pomodoro.strip_offset_y()
        skip_pill = strip_dy >= strip_h + 8
        if strip_dy != 0 and not skip_pill:
            top += strip_dy
            bot += strip_dy

        # Muted grey-beige-green to complement the cabin's stone/earth tones
        BASE  = (88,  96, 72)   # desaturated olive-grey (main fill)
        DEEP  = (72,  80, 58)   # darker shadow cell
        SURF  = (106, 112, 86)  # lighter highlight cell

        if not skip_pill:
            # Clip to a rounded-rect (pill shape) so the edges are smooth
            radius = strip_h * 0.55          # tall radius → pill / oval ends
            clip   = QPainterPath()
            clip.addRoundedRect(QRectF(left_x, top, strip_w, strip_h), radius, radius)
            painter.save()
            # Base strip opacity, scaled by the same Sao-proximity fade as
            # the house so the two vanish/appear together.
            painter.setOpacity(0.86 * self._hut_proximity_alpha())
            painter.setClipPath(clip)
            painter.setPen(Qt.PenStyle.NoPen)

            cols = (strip_w + CELL - 1) // CELL
            rows = (strip_h + CELL - 1) // CELL
            for row in range(rows):
                for col in range(cols):
                    h = (col * 7 + row * 13) % 47
                    if h < 1:
                        c = SURF
                    elif h < 3:
                        c = DEEP
                    else:
                        c = BASE
                    painter.setBrush(QColor(*c))
                    painter.drawRect(left_x + col * CELL, top + row * CELL, CELL, CELL)

            # Hover white tint over the whole strip when cursor is over the house
            if self._hut_hover and not self._hut_pressed:
                painter.setBrush(QColor(255, 255, 255, 26))
                painter.drawRect(left_x, top, strip_w, strip_h)

            painter.restore()   # removes clip + restores opacity to 1.0

    def _draw_work_icon_bar(self, painter: QPainter) -> None:
        """Warm-yellow 'Sao is inside this app' bar drawn under its taskbar
        icon — mirrors the Windows open-app underline, in a glowing gold so it
        reads as 'Sao is here'."""
        if self._work_icon_bar is None:
            return
        cx, bottom_y = self._work_icon_bar
        pulse = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._work_ind_phase))
        BAR_W, BAR_H = 30, 4
        y = bottom_y - BAR_H - 2           # sit just above the icon's bottom edge
        painter.setPen(Qt.PenStyle.NoPen)
        # Soft glow halo
        glow = QColor(252, 211, 77, int(85 * pulse))
        painter.setBrush(glow)
        painter.drawRoundedRect(cx - BAR_W // 2 - 4, y - 4,
                                BAR_W + 8, BAR_H + 8, 6, 6)
        # Solid bar
        bar = QColor(250, 200, 60, int(245 * (0.6 + 0.4 * pulse)))
        painter.setBrush(bar)
        painter.drawRoundedRect(cx - BAR_W // 2, y, BAR_W, BAR_H,
                                BAR_H // 2, BAR_H // 2)

    def _draw_hut(self, painter: QPainter) -> None:
        """
        House rendering — user's PNG sprite (primary) with procedural mushroom fallback.
        Shared tail: glow, smoke particles, '...' indicator.
        """
        S  = 2
        # Pomodoro tween — slide hut to the bottom-left of the flip-dot panel
        # and shrink it. Applied multiplicatively on top of hover/press scale.
        pomo_dx, pomo_dy, pomo_s = self.pomodoro.hut_transform()
        cx = self._hut_x + pomo_dx
        fy = self._hut_floor_y + pomo_dy
        painter.setPen(Qt.PenStyle.NoPen)

        # Proximity fade — the cabin is faint when Sao is far so it doesn't
        # obscure taskbar apps, and solid when she's near / it's being moved.
        painter.save()
        painter.setOpacity(self._hut_proximity_alpha())

        # ── Branch: PNG sprite vs procedural ─────────────────────────────
        if self._hut_pixmap is not None and not self._hut_pixmap.isNull():
            # ── User's mushroom PNG — nearest-neighbour scale keeps pixels crisp ──
            pw = self._hut_pixmap.width()
            ph = self._hut_pixmap.height()
            s  = self._hut_current_scale() * pomo_s
            if abs(s - 1.0) > 0.002:
                draw_w = max(1, int(pw * s))
                draw_h = max(1, int(ph * s))
                pm_draw = self._hut_pixmap.scaled(
                    draw_w, draw_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            else:
                draw_w, draw_h, pm_draw = pw, ph, self._hut_pixmap
            # Pivot from bottom-centre. Positive _DRAW_PAD shifts the whole sprite
            # downward so the base sinks into the taskbar floor visually.
            _DRAW_PAD = 4
            draw_x = cx - draw_w // 2
            painter.drawPixmap(draw_x, fy - draw_h + _DRAW_PAD, pm_draw)
            glow_cy = fy - max(10, draw_h // 4) + _DRAW_PAD
            dot_y   = fy - draw_h + _DRAW_PAD - 8
        else:
            # ── Procedural mushroom fallback ──────────────────────────────
            def r(dx: int, dy_up: int, w: int, h: int, col: tuple) -> None:
                painter.setBrush(QColor(*col))
                painter.drawRect(cx + dx * S, fy - (dy_up + h) * S, w * S, h * S)

            K  = ( 28,  14,   6)
            CR = (148,  50,  44)
            CL = (192,  82,  72)
            CS = ( 90,  26,  20)
            SP = (242, 237, 222)
            WL = (212, 172, 112)
            WD = (158, 118,  72)
            DW = (105,  65,  28)
            YW = (228, 182,  50)

            r( -6, 0, 12, 7, K);  r( -5, 1, 10, 5, WD);  r( -3, 1, 8, 5, WL)
            r( -2, 0,  4, 7, K);  r( -2, 1,  4, 6, DW);  r( -1, 3, 2, 2, YW)
            r(  1, 1,  1, 1, (178, 138, 34))

            for half, dy, col in [
                    (7,6,CS),(8,7,CS),(10,8,CR),(11,9,CR),(11,10,CR),(10,11,CR),
                    (9,12,CR),(8,13,CL),(7,14,CL),(6,15,CL),(5,16,CL),(4,17,CL),
                    (3,18,CL),(2,19,CL),(1,20,CL)]:
                r(-half-1, dy, 1, 1, K)
                r( half,   dy, 1, 1, K)
                r(-half,   dy, half*2, 1, col)

            r(-8,10,2,2,SP); r(4,11,2,2,SP); r(-2,13,2,2,SP); r(2,9,1,1,SP)
            r(-1,20,2,3,K);  r(-1,20,2,2,(115,70,38))
            r(-2,22,4,1,K);  r(-1,22,2,1,(85,45,16))

            glow_cy = fy - 4 * S
            dot_y   = fy - 26 * S

        # ── Candle glow — only when Sao is inside ────────────────────────
        if self._sao_in_hut and self._hut_glow_state in ('on1', 'on2'):
            painter.setPen(Qt.PenStyle.NoPen)
            for radius, alpha in [(15, 22), (9, 50), (4, 90)]:
                painter.setBrush(QColor(255, 200, 60, alpha))
                painter.drawEllipse(cx - radius, glow_cy - radius,
                                    radius * 2, radius * 2)

        # ── Smoke particles ───────────────────────────────────────────────
        painter.setPen(Qt.PenStyle.NoPen)
        for p in self._hut_smoke:
            age   = p['age']
            alpha = max(0, 200 - age * 3)
            size  = max(2, int((2 + age // 14) * p.get('sz', 1.0)))
            painter.setBrush(QColor(210, 210, 210, alpha))
            painter.drawEllipse(int(p['x']) - size // 2,
                                int(p['y']) - size // 2,
                                size, size)

        # ── "..." indicator when Sao is inside ───────────────────────────
        if self._sao_in_hut:
            period = 200
            phase  = self._hut_indicator_tick % period
            if phase < 165:
                n_dots  = (phase // 55) + 1
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 200))
                spacing = 7
                start_x = cx - ((n_dots - 1) * spacing) // 2
                for i in range(n_dots):
                    painter.drawEllipse(start_x + i * spacing - 1,
                                        dot_y - 1, 3, 3)

        painter.restore()   # undo the proximity-fade opacity

    # ------------------------------------------------------------------
    # Grow animation
    # ------------------------------------------------------------------

    def _tick_grow_animation(self) -> None:
        """Advance displayed plant stages and task-flower bloom fracs (startup animation)."""
        # ── Regular plants ────────────────────────────────────────────────
        if self._garden and self._garden.plants:
            if self._plant_grow_delay > 0:
                self._plant_grow_delay -= 1
            else:
                for i, plant in enumerate(self._garden.plants):
                    if i >= len(self._plant_display_stages):
                        self._plant_display_stages.append(0.0)
                    if i >= len(self._plant_display_frames):
                        self._plant_display_frames.append(0.0)
                    disp = self._plant_display_stages[i]
                    if disp > plant.stage:
                        self._plant_display_stages[i] = float(plant.stage)
                        self._plant_display_frames[i] = float(getattr(plant, 'growth_frame', 0))
                    elif disp < plant.stage:
                        self._plant_display_stages[i] = min(
                            float(plant.stage),
                            disp + self._plant_grow_rate,
                        )
                    # Animate growth_frame on startup.
                    # For fully-bloomed flowers still mid-grow-animation, target the
                    # LAST sprite frame so the bloom is always visible even when
                    # plant.growth_frame is 0 (old saves without the field set).
                    disp_f = self._plant_display_frames[i]
                    if (plant.stage >= 4
                            and self._plant_display_stages[i] < 4.0
                            and getattr(plant, 'plant_type', 0) == 0
                            and self._sprites and self._sprites.loaded):
                        _at = getattr(plant, 'variant', 0) % 5
                        _ai = [ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER,
                               ANIM_RED_FLOWER, ANIM_WHITE_FLOWER, ANIM_TALL_FLOWER][_at]
                        _hue = _FLOWER_VARIANT_HUE[getattr(plant, 'variant', 0) % len(_FLOWER_VARIANT_HUE)]
                        _fr = (self._flower_tinted_cache.get((_ai, _hue))
                               or self._sprites.frames(_ai))
                        target_f = float(len(_fr) - 1) if _fr else float(getattr(plant, 'growth_frame', 0))
                    else:
                        target_f = float(getattr(plant, 'growth_frame', 0))
                    if disp_f < target_f:
                        # Sync with stage animation so frames complete at the same
                        # time as disp_stage reaches plant.stage.
                        rate = target_f * self._plant_grow_rate / max(float(plant.stage), 1)
                        # Floor matches the tall-blue flower's natural pace
                        # (14 frames over 4 stages × 28 ticks ≈ 0.12 fr/tick).
                        # Without this, flowers with shorter animations (white = 5
                        # frames, blue/red = 6, green = 9) feel sluggish because
                        # each frame holds for ~3× longer than tall's; floored,
                        # every flower has the same per-frame snappiness and the
                        # shorter ones just finish blooming a bit sooner.
                        rate = max(0.12, rate)
                        self._plant_display_frames[i] = min(target_f, disp_f + rate)
                    elif disp_f > target_f:
                        self._plant_display_frames[i] = target_f

        # ── Task flowers — grow the displayed frac toward live bloom_frac ──
        # Gives the seed→bloom grow-in on startup AND the regrow after a
        # click-dismiss.  While a flower is hidden (just clicked) it stays
        # collapsed at 0 so it visibly sprouts back up when it returns.
        tfs = self._task_flowers
        df  = self._task_flower_display_fracs
        hd  = self._flower_hidden_ticks
        _GROW = 0.014   # ~70 ticks (≈1.2 s) seed→full bloom
        for i, tf in enumerate(tfs):
            if i >= len(df):
                df.append(0.0)
            if i >= len(hd):
                hd.append(0.0)
            if hd[i] > 0:
                hd[i] -= 1
                df[i] = 0.0   # stay a sprout while hidden → regrows on return
                continue
            target = tf.bloom_frac()
            if df[i] < target:
                df[i] = min(target, df[i] + _GROW)
            elif df[i] > target + 0.02:
                df[i] = target

    def _tick_plant_jiggle(self) -> None:
        """Randomly trigger a gentle sway on flower plants.
        Also keeps _plant_jiggle and _plant_foreground in sync with plant list."""
        if not self._garden:
            return
        n = len(self._garden.plants)
        # Extend auxiliary lists for newly-added plants
        while len(self._plant_jiggle) < n:
            self._plant_jiggle.append(
                {'idle': _rnd.randint(600, 1800), 'active': 0, 'total': 80})
        while len(self._plant_foreground) < n:
            p = self._garden.plants[len(self._plant_foreground)]
            self._plant_foreground.append(
                getattr(p, 'plant_type', 0) == 0 and _rnd.random() < 0.5)
        del self._plant_jiggle[n:]
        del self._plant_foreground[n:]
        for i, jig in enumerate(self._plant_jiggle):
            if jig['active'] > 0:
                jig['active'] -= 1
            else:
                jig['idle'] -= 1
                if jig['idle'] <= 0:
                    jig['active'] = jig['total']
                    jig['idle']   = _rnd.randint(600, 1800)
                    # Pulse any butterflies sitting on this plant so they
                    # shake too when the flower starts its idle sway.
                    if i < len(self._garden.plants):
                        self._pulse_landed_butterflies_at(self._garden.plants[i].x)

    # ------------------------------------------------------------------
    # Hover tooltips
    # ------------------------------------------------------------------

    def _draw_tooltip(self, painter: QPainter, lines: list[str],
                      anchor_x: int, anchor_y: int) -> None:
        """
        Draw a pill-shaped tooltip with *lines* of text.
        *anchor_x/y* is the bottom-centre of the plant sprite — tooltip
        floats above it.  Never clips off screen left/right.
        """
        if not lines:
            return

        font = QFont('Courier New', 1)
        font.setPixelSize(13)
        font.setBold(False)
        painter.setFont(font)
        fm = painter.fontMetrics()

        PAD_X, PAD_Y, LINE_GAP = 10, 6, 3
        line_h = fm.height()
        max_w  = max(fm.horizontalAdvance(ln) for ln in lines)
        tip_w  = max_w + PAD_X * 2
        tip_h  = line_h * len(lines) + LINE_GAP * (len(lines) - 1) + PAD_Y * 2

        # Position: centre on anchor_x, float above plant
        tx = anchor_x - tip_w // 2
        ty = anchor_y - tip_h - 8

        # Clamp within screen
        sw = self.width()
        tx = max(4, min(tx, sw - tip_w - 4))
        ty = max(4, ty)

        # Background pill
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(22, 18, 12, 210))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(tx, ty, tip_w, tip_h, 7, 7)

        # Tiny arrow pointing down toward anchor
        arrow_cx = anchor_x - 1
        arrow_cx = max(tx + 8, min(arrow_cx, tx + tip_w - 8))
        painter.setBrush(QColor(22, 18, 12, 210))
        path = QPainterPath()
        path.moveTo(arrow_cx - 5, ty + tip_h)
        path.lineTo(arrow_cx + 5, ty + tip_h)
        path.lineTo(arrow_cx,     ty + tip_h + 6)
        path.closeSubpath()
        painter.drawPath(path)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Text
        y_text = ty + PAD_Y
        for k, line in enumerate(lines):
            # First line = name → slightly brighter
            col = QColor(255, 240, 210) if k == 0 else QColor(210, 205, 195)
            painter.setPen(col)
            font.setBold(k == 0)
            painter.setFont(font)
            painter.drawText(tx + PAD_X, y_text + fm.ascent(), line)
            y_text += line_h + LINE_GAP

    def _draw_plant_tooltip(self, painter: QPainter, plant, idx: int) -> None:
        """Tooltip for a regular garden plant."""
        from desktop_cat.garden import FLOWER_NAMES, FLOWER_VARIANT_COUNT, PLANT_STAGES
        floor_y  = self._garden_floor_y
        from desktop_cat.garden import PLANT_TOP_HEIGHTS
        disp_s   = (int(self._plant_display_stages[idx])
                    if idx < len(self._plant_display_stages) else plant.stage)
        top_h    = PLANT_TOP_HEIGHTS[min(disp_s, len(PLANT_TOP_HEIGHTS) - 1)] * 2

        if plant.plant_type == 1:
            name = 'potato'
        elif plant.plant_type == 2:
            name = 'carrot'
        elif plant.plant_type == 3:
            name = 'macron'
        else:
            name = FLOWER_NAMES[plant.variant % FLOWER_VARIANT_COUNT]

        stage_names = ['seed', 'sprout', 'small', 'bud', 'full bloom']
        stage_str   = stage_names[min(plant.stage, len(stage_names) - 1)]
        lines = [
            name,
            f'stage {plant.stage}/{PLANT_STAGES - 1}  ·  {stage_str}',
        ]
        if plant.has_bee:
            lines.append('🐝 has a bee friend')

        self._draw_tooltip(painter, lines, plant.x, floor_y - top_h)

    def _draw_task_flower_tooltip(self, painter: QPainter, tf) -> None:
        """Tooltip for a task flower."""
        from datetime import date as _dt
        floor_y = self._garden_floor_y
        pct     = int(tf.bloom_frac() * 100)
        lines   = [tf.task_text[:28] + ('…' if len(tf.task_text) > 28 else '')]
        if tf.done:
            lines.append('✓ completed  ·  wilted')
        else:
            lines.append(f'bloom {pct}%')
            if tf.due_date:
                try:
                    d1   = _dt.fromisoformat(tf.due_date)
                    diff = (d1 - _dt.today()).days
                    if diff < 0:
                        lines.append(f'overdue {abs(diff)}d')
                    elif diff == 0:
                        lines.append('due today!')
                    else:
                        lines.append(f'due in {diff}d  ({d1.strftime("%b %d")})')
                except ValueError:
                    pass
        # Anchor the tooltip to the TOP of the actual sprite so the box floats
        # fully above the bloom instead of covering it.
        geom = self._flower_sprite_geom(tf)
        top_y = geom[2] if geom else (floor_y - 42)
        self._draw_tooltip(painter, lines, int(tf.x), top_y - 2)

    # ------------------------------------------------------------------
    # Garden drawing
    # ------------------------------------------------------------------

    def _draw_garden(self, painter: QPainter,
                     foreground_pass: bool = True) -> None:
        """Draw plants.

        foreground_pass=True  → plants in front of Sao (drawn after her)
        foreground_pass=False → plants behind Sao (drawn before her)

        The *active* plant (being tended) is always foreground regardless.
        Crops (potato/carrot/macron) are always background.
        """
        painter.setPen(Qt.PenStyle.NoPen)
        floor_y = self._garden_floor_y
        for i, plant in enumerate(self._garden.plants):
            # Determine which pass this plant belongs to
            is_foreground = (
                plant is self._active_plant                  # tended plant → always front
                or (i < len(self._plant_foreground)
                    and self._plant_foreground[i])
            )
            if is_foreground != foreground_pass:
                continue

            # Use animated display stage (may be less than actual during startup)
            disp_stage = (int(self._plant_display_stages[i])
                          if i < len(self._plant_display_stages)
                          else plant.stage)
            # Use animated display frame during startup; once caught up, use live value.
            # Do NOT clamp disp_gf to actual_gf during the startup bloom animation —
            # actual_gf is 0 in old saves, which would lock frames at 0 forever.
            actual_gf = getattr(plant, 'growth_frame', 0)
            disp_gf   = (int(self._plant_display_frames[i])
                         if i < len(self._plant_display_frames) else actual_gf)
            in_startup = (i < len(self._plant_display_stages)
                          and self._plant_display_stages[i] < float(plant.stage))
            growth_frame = disp_gf if in_startup else min(actual_gf, disp_gf)
            # Jiggle angle for flowers
            _jig_angle = 0.0
            if getattr(plant, 'plant_type', 0) == 0 and i < len(self._plant_jiggle):
                _jig = self._plant_jiggle[i]
                if _jig['active'] > 0:
                    _t = 1.0 - _jig['active'] / _jig['total']
                    _jig_angle = 3.5 * math.sin(_t * math.pi) * math.sin(_t * math.pi * 6)
            self._draw_plant(painter, plant.x, floor_y, disp_stage,
                             getattr(plant, 'variant', 0),
                             getattr(plant, 'plant_type', 0),
                             getattr(plant, 'fruitless', False),
                             growth_frame=growth_frame,
                             size_scale=getattr(plant, 'size_scale', 1.0),
                             facing=getattr(plant, 'facing', 1),
                             hue_offset=getattr(plant, 'hue_offset', 0),
                             jiggle_angle=_jig_angle)
        if foreground_pass and self._active_plant is not None:
            self._draw_plant_indicator(painter, self._active_plant)

    def _draw_potato_plant(self, painter: QPainter, x: int, floor_y: int,
                           stage: int) -> None:
        """
        Potato plant.  Stages 1-3: a simple leafy stalk getting taller.
        Stage 4: stalk + the crown of the potato peeking above the soil.

        Only the top ~quarter of the potato is visible (the tuber is mostly
        underground); it looks like a rounded brown bump at soil level.
        """
        S  = 2
        painter.setPen(Qt.PenStyle.NoPen)

        def r(dx: int, dy_up: int, w: int, h: int, col: tuple) -> None:
            painter.setBrush(QColor(*col))
            painter.drawRect(x + dx * S, floor_y - (dy_up + h) * S, w * S, h * S)

        # Greens
        SD = ( 85, 170, 55)
        SM = (110, 200, 70)
        LM = ( 48, 118, 50)
        LL = ( 70, 148, 60)
        SO = ( 68,  44, 18)  # soil
        # Potato skin
        PK = (175, 140, 70)  # main tan
        PS = (140, 106, 46)  # shadow sides
        PH = (208, 172, 100) # highlight crown

        if stage == 0:
            # Soil mound with a hint of something planted
            r(-2, 0, 5, 1, SO)
            r(-1, 1, 3, 1, (SO[0]+14, SO[1]+10, SO[2]+6))
            r( 0, 2, 1, 1, (52, 118, 38))

        elif stage == 1:
            # Tiny shoot — thin stem + 2 small leaves
            r(-2, 0, 5, 1, SO)
            r( 0, 1, 1, 3, SD)
            r(-1, 2, 1, 1, LM)
            r( 1, 2, 1, 1, LM)
            r( 0, 3, 1, 1, LL)

        elif stage == 2:
            # Stalk getting taller, one leaf pair
            r(-1, 0, 3, 1, SO)
            r( 0, 1, 1, 4, SD)
            r(-2, 2, 2, 1, LM)
            r( 1, 2, 2, 1, LM)
            r( 0, 4, 1, 1, LL)

        elif stage == 3:
            # Fuller leafy stalk
            r( 0, 0, 1, 6, SD)
            r( 0, 4, 1, 2, SM)
            r(-2, 2, 2, 1, LM);  r( 1, 2, 2, 1, LM)
            r(-2, 4, 2, 1, LM);  r( 1, 4, 2, 1, LM)
            r(-1, 5, 1, 1, LL);  r( 1, 5, 1, 1, LL)
            r( 0, 6, 1, 1, LL)

        else:  # stage 4 — potato crown emerging
            # Soil around the potato bump
            r(-3, 0, 7, 1, SO)
            # Potato body at ground level (top ~quarter visible)
            r(-2, 0, 5, 1, PK)   # main crown
            r(-2, 0, 1, 1, PS)   # left shadow edge
            r( 2, 0, 1, 1, PS)   # right shadow edge
            r(-1, 1, 3, 1, PH)   # bright rounded tip of potato
            # Stalk rising from potato
            r( 0, 2, 1, 4, SD)
            r( 0, 5, 1, 2, SM)
            # Leaf pairs
            r(-3, 3, 3, 1, (44, 105, 38));  r( 1, 3, 3, 1, (44, 105, 38))
            r(-2, 4, 2, 1, LM);             r( 1, 4, 2, 1, LM)
            r(-3, 5, 3, 1, LM);             r( 1, 5, 3, 1, LM)
            r(-1, 6, 1, 1, LL);             r( 1, 6, 1, 1, LL)

    def _draw_carrot_plant(self, painter: QPainter, x: int, floor_y: int,
                           stage: int) -> None:
        S = 2
        painter.setPen(Qt.PenStyle.NoPen)

        def r(dx: int, dy_up: int, w: int, h: int, col: tuple) -> None:
            painter.setBrush(QColor(*col))
            painter.drawRect(x + dx * S, floor_y - (dy_up + h) * S, w * S, h * S)

        SO = (68,  44, 18)   # soil
        SD = (85, 170, 55)   # stem dark
        LM = (48, 118, 50)   # leaf mid
        LL = (70, 148, 60)   # leaf light
        CR = (208, 100, 40)  # carrot orange
        CH = (230, 140, 60)  # carrot highlight
        CS = (160,  70, 20)  # carrot shadow

        if stage == 0:
            r(-2, 0, 5, 1, SO)
            r(-1, 1, 3, 1, (SO[0]+14, SO[1]+10, SO[2]+6))
            r( 0, 2, 1, 1, (52, 118, 38))

        elif stage == 1:
            r(-2, 0, 5, 1, SO)
            r( 0, 1, 1, 3, SD)
            r(-1, 2, 1, 1, LM);  r(1, 2, 1, 1, LM)
            r( 0, 4, 1, 1, LL)

        elif stage == 2:
            r(-1, 0, 3, 1, SO)
            r( 0, 1, 1, 4, SD)
            r(-2, 2, 2, 1, LM);  r(1, 2, 2, 1, LM)
            r(-1, 4, 1, 1, LL);  r(1, 4, 1, 1, LL)

        elif stage == 3:
            r( 0, 0, 1, 5, SD)
            r(-2, 2, 2, 1, LM);  r(1, 2, 2, 1, LM)
            r(-2, 4, 2, 1, LM);  r(1, 4, 2, 1, LM)
            r( 0, 5, 1, 1, LL)
            # Hint of orange root at soil
            r(-1, 0, 3, 1, CR)

        else:  # stage 4 — carrot crown visible
            r(-3, 0, 7, 1, SO)
            r(-1, 0, 3, 2, CR)
            r(-1, 1, 1, 1, CS);  r(1, 1, 1, 1, CS)
            r( 0, 2, 1, 1, CH)
            r( 0, 3, 1, 4, SD)
            r(-2, 4, 2, 1, LM);  r(1, 4, 2, 1, LM)
            r(-3, 5, 3, 1, LM);  r(1, 5, 3, 1, LM)
            r(-1, 6, 1, 1, LL);  r(1, 6, 1, 1, LL)

    # Stage → animation frame for the macron plant (frames 0-9 = growth, 10 = harvest).
    # fruitless stage-4 uses frame 9 (fully grown plant, no pastry visible).
    _MACRON_STAGE_FRAME = [0, 2, 5, 8, 9]   # indices: stage 0-4 → base frame

    def _draw_macron_plant(self, painter: QPainter, x: int, floor_y: int,
                           stage: int, fruitless: bool = False) -> None:
        """Draw macron plant from the ANIM_MACRON sprite strip.

        Frames 0-9 show the plant growing; frame 10 (the last frame) shows
        the fully-grown plant with a macron ready to harvest.  When fruitless
        is True (the macron has been picked and the plant is regrowing) the
        final-stage frame is 9 instead of 10.
        """
        if self._sprites and self._sprites.loaded:
            frames = self._sprites.frames(ANIM_MACRON)
            if frames:
                s = max(0, min(stage, 4))
                fi = self._MACRON_STAGE_FRAME[s]
                if s >= 4 and not fruitless:
                    fi = len(frames) - 1   # last frame = macron harvest-ready
                fi = max(0, min(fi, len(frames) - 1))
                frame = frames[fi]
                scale = 0.9
                fw, fh = frame.width(), frame.height()
                sw, sh = max(1, int(fw * scale)), max(1, int(fh * scale))
                scaled = frame.scaled(
                    sw, sh,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                painter.drawPixmap(QPoint(x - sw // 2, floor_y - sh), scaled)
                return

        # ── Fallback: procedural pixel-art macron ─────────────────────────
        S = 2
        painter.setPen(Qt.PenStyle.NoPen)

        def r(dx: int, dy_up: int, w: int, h: int, col: tuple) -> None:
            painter.setBrush(QColor(*col))
            painter.drawRect(x + dx * S, floor_y - (dy_up + h) * S, w * S, h * S)

        SO  = (68,  44, 18)
        ST  = (200, 170, 160)
        MP  = (242, 180, 212)
        MS  = (210, 140, 175)
        MH  = (255, 215, 235)
        FIL = (255, 230, 195)

        if stage == 0:
            r(-2, 0, 5, 1, SO)
            r(-1, 1, 3, 1, (SO[0]+14, SO[1]+10, SO[2]+6))
            r( 0, 2, 1, 1, MP)
        elif stage == 1:
            r(-1, 0, 3, 1, SO)
            r( 0, 1, 1, 3, ST)
            r( 0, 4, 1, 1, MP)
        elif stage == 2:
            r( 0, 0, 1, 4, ST)
            r(-1, 4, 3, 2, MP);  r(-1, 4, 1, 1, MS);  r( 0, 5, 2, 1, MH)
        elif stage == 3:
            r( 0, 0, 1, 4, ST)
            r(-2, 4, 5, 2, MP);  r(-2, 4, 1, 2, MS);  r( 2, 4, 1, 2, MS)
            r(-1, 5, 4, 1, MH);  r(-2, 3, 5, 1, FIL)
        else:
            r( 0, 0, 1, 3, ST)
            if fruitless:
                WL = (160, 180, 155)
                r(-3, 2, 3, 1, WL);  r( 1, 3, 3, 1, WL)
            else:
                r(-3, 2, 7, 3, MP);  r(-3, 2, 1, 3, MS);  r( 3, 2, 1, 3, MS)
                r(-2, 4, 6, 1, MH);  r(-3, 4, 7, 1, FIL)
                r(-3, 5, 7, 3, MP);  r(-3, 5, 1, 3, MS);  r( 3, 5, 1, 3, MS)
                r(-2, 7, 6, 1, MH)

    def _draw_plant(self, painter: QPainter, x: int, floor_y: int,
                stage: int, variant: int = 0, plant_type: int = 0,
                fruitless: bool = False, growth_frame: int = 0,
                size_scale: float = 1.0, facing: int = 1,
                hue_offset: int = 0, jiggle_angle: float = 0.0) -> None:
        """
        Draw a plant.  S=2 so one sprite-pixel = 2×2 logical px.
        plant_type: 0=flower, 1=potato, 2=carrot, 3=macron
        size_scale: per-instance multiplier applied on top of _FLOWER_ANIM_SCALES
        facing: 1=normal, -1=horizontally flipped
        jiggle_angle: rotation in degrees for the sway idle animation (pivot at base)
        """
        if plant_type == 1:
            self._draw_potato_plant(painter, x, floor_y, stage)
            return
        if plant_type == 2:
            self._draw_carrot_plant(painter, x, floor_y, stage)
            return
        if plant_type == 3:
            self._draw_macron_plant(painter, x, floor_y, stage, fruitless=fruitless)
            return

        # ── Flower: sprite sheet path ─────────────────────────────────────────
        if self._sprites and self._sprites.loaded:
            anim_type = variant % 5   # 0=green 1=blue 2=red 3=white 4=tall-blue
            anim_idx  = [ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER,
                         ANIM_RED_FLOWER, ANIM_WHITE_FLOWER, ANIM_TALL_FLOWER][anim_type]
            hue_shift = _FLOWER_VARIANT_HUE[variant % len(_FLOWER_VARIANT_HUE)]
            scale     = _FLOWER_ANIM_SCALES[min(anim_type, len(_FLOWER_ANIM_SCALES) - 1)] * size_scale
            cache_key = (anim_idx, hue_shift)
            if cache_key not in self._flower_tinted_cache:
                raw = self._sprites.frames(anim_idx)
                self._flower_tinted_cache[cache_key] = _apply_hue_shift(
                    raw, hue_shift, protect_green_stems=True)
            tinted = self._flower_tinted_cache[cache_key]
            if tinted:
                # Stage-4 = fully bloomed; always show the last animation frame
                # regardless of growth_frame.  Old saves may have growth_frame
                # values from a different-length sprite that would land mid-animation.
                if stage >= 4 and len(tinted) > 1:
                    gf = len(tinted) - 1
                else:
                    gf = max(0, min(growth_frame, len(tinted) - 1))
                frame = tinted[gf]
                fw, fh = frame.width(), frame.height()
                sw, sh = int(fw * scale), int(fh * scale)
                scaled = frame.scaled(
                    sw, sh,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                if facing == -1:
                    scaled = scaled.transformed(QTransform().scale(-1, 1))
                if jiggle_angle != 0.0:
                    painter.save()
                    painter.translate(x, floor_y)
                    painter.rotate(jiggle_angle)
                    painter.drawPixmap(QPoint(-sw // 2, -sh), scaled)
                    painter.restore()
                else:
                    painter.drawPixmap(QPoint(x - sw // 2, floor_y - sh), scaled)
                return

        S = 2
        painter.setPen(Qt.PenStyle.NoPen)

        def r(dx: int, dy_up: int, w: int, h: int, col: tuple) -> None:
            painter.setBrush(QColor(*col))
            painter.drawRect(x + dx * S, floor_y - (dy_up + h) * S, w * S, h * S)

        SD = (85, 170, 55)    # stem
        SM = (110, 200, 70)   # stem highlight
        LD = (30,  88, 38)    # leaf dark (underside)
        LM = (48, 118, 50)    # leaf mid
        LL = (66, 145, 58)    # leaf light (top surface)
        SO = (68,  44, 18)    # soil

        pal   = _FLOWER_PALETTES[variant % len(_FLOWER_PALETTES)]
        P1, P2, C1, C2 = pal   # petal bright, petal shadow, centre bright, centre shadow

        if stage == 0:
            # Seed — flat soil mound with a tiny green tuft on top
            r(-2, 0, 5, 1, SO)                                # wide flat base
            r(-1, 1, 3, 1, (SO[0]+14, SO[1]+10, SO[2]+6))    # slightly raised centre
            r(-1, 2, 1, 1, (52, 118, 38))                     # left grass pixel
            r( 1, 2, 1, 1, (42,  98, 28))                     # right grass pixel (darker)

        elif stage == 1:
            # Sprout — 4 sp tall
            r( 0, 0, 1, 3, SD)     # dark stem
            r(-1, 1, 1, 1, LM)     # left leaf
            r( 1, 1, 1, 1, LM)     # right leaf
            r( 0, 3, 1, 1, LL)     # pale growing tip

        elif stage == 2:
            # Small plant — 6 sp tall, two leaf pairs
            r( 0, 0, 1, 5, SD)
            r( 0, 3, 1, 2, SM)     # lighter upper stem
            r(-2, 2, 2, 1, LD)     # lower-left leaf dark
            r(-2, 3, 2, 1, LM)     # lower-left leaf bright
            r( 1, 3, 2, 1, LD)     # lower-right leaf dark
            r( 1, 4, 2, 1, LM)     # lower-right leaf bright
            r( 0, 5, 1, 1, LL)     # tip

        elif stage == 3:
            # Bud — plump, 12 sp tall
            r( 0, 0, 1, 8, SD)     # stem dark
            r( 0, 5, 1, 3, SM)     # upper stem lighter
            # Lower leaf pair (3 wide with tip highlight)
            r(-3, 2, 3, 1, LD);  r(-3, 3, 2, 1, LM);  r(-2, 4, 1, 1, LL)
            r( 1, 3, 3, 1, LD);  r( 1, 4, 2, 1, LM);  r( 3, 5, 1, 1, LL)
            # Upper small leaf pair
            r(-2, 5, 2, 1, LM);  r(-2, 6, 1, 1, LL)
            r( 1, 6, 2, 1, LM);  r( 2, 7, 1, 1, LL)
            # Bud — 3 wide × 4 tall, rounded look
            r(-1,  8, 3, 1, P2)    # bud base shadow
            r(-1,  9, 3, 2, P1)    # bud body bright
            r( 0,  9, 1, 2, C1)    # centre colour seam
            r(-1, 11, 3, 1, P1)    # bud top cap
            r( 0, 11, 1, 1, P2)    # bud tip shadow (rounded look)

        else:
            # Full flower — thick cross petals, 3×3 centre, 14 sp tall
            r( 0, 0, 1, 8, SD)     # stem dark
            r( 0, 4, 1, 4, SM)     # upper stem lighter
            # Lower leaf pair (3 wide with tip highlight)
            r(-3, 2, 3, 1, LD);  r(-3, 3, 2, 1, LM);  r(-2, 4, 1, 1, LL)
            r( 1, 3, 3, 1, LD);  r( 1, 4, 2, 1, LM);  r( 3, 5, 1, 1, LL)
            # Upper small leaf pair
            r(-2, 5, 2, 1, LM);  r(-2, 6, 1, 1, LL)
            r( 1, 6, 2, 1, LM);  r( 2, 7, 1, 1, LL)
            # ── Petals (draw before centre so centre overlaps joins) ──
            # Bottom petal — 3 wide × 2 tall
            r(-1,  7, 3, 2, P1);  r( 0,  7, 1, 1, P2)
            # Left petal — 2 wide × 3 tall
            r(-3,  9, 2, 3, P1);  r(-3, 10, 1, 1, P2)
            # Right petal — 2 wide × 3 tall
            r( 2,  9, 2, 3, P1);  r( 3, 10, 1, 1, P2)
            # Top petal — 3 wide × 2 tall
            r(-1, 12, 3, 2, P1);  r( 0, 13, 1, 1, P2)
            # ── Centre (3×3) drawn last so it sits on top of petal joins ──
            r(-1,  9, 3, 3, C1)
            r( 0, 10, 1, 1, C2)   # centre shadow spot

    def _draw_bug(self, painter: QPainter, bug) -> None:
        """Tiny pixel bee — compact, ~6×8 px total."""
        bx = int(bug.x)
        by = int(bug.y)

        yellow = QColor(235, 192, 12)
        y_dark = QColor(175, 138,  8)
        black  = QColor(22,  14,  5)
        wing_c = QColor(210, 235, 255, 115)

        painter.setPen(Qt.PenStyle.NoPen)

        # Wings — narrow ellipses just above body
        painter.setBrush(wing_c)
        painter.drawEllipse(bx - 4, by - 2, 3, 2)   # left wing
        painter.drawEllipse(bx + 1, by - 2, 3, 2)   # right wing

        # Head — 1px tall, 3px wide
        painter.setBrush(black)
        painter.drawRect(bx - 1, by - 3, 3, 1)
        painter.setBrush(yellow)
        painter.drawRect(bx,     by - 3, 1, 1)      # face mark

        # Body — 3 stripes (yellow / black / dark-yellow), 3px wide
        painter.setBrush(yellow)
        painter.drawRect(bx - 1, by - 2, 3, 1)
        painter.setBrush(black)
        painter.drawRect(bx - 1, by - 1, 3, 1)
        painter.setBrush(y_dark)
        painter.drawRect(bx - 1, by,     3, 1)
        painter.setBrush(black)
        painter.drawRect(bx,     by + 1, 1, 1)      # stinger pixel

        # Antennae — 1-pixel stalks + dot tips
        painter.setBrush(black)
        painter.drawRect(bx - 1, by - 5, 1, 1)      # left stalk
        painter.drawRect(bx + 1, by - 5, 1, 1)      # right stalk
        painter.drawRect(bx - 2, by - 5, 1, 1)      # left tip
        painter.drawRect(bx + 2, by - 5, 1, 1)      # right tip

    def _draw_rocks(self, painter: QPainter) -> None:
        """Render pre-scaled rock sprites at floor level (bottom of rock = rock.y)."""
        for rock in self._rocks:
            pm = self._green_rock(self._rock_pixmaps[rock.variant % len(self._rock_pixmaps)])
            x  = int(rock.x) - pm.width() // 2
            y  = int(rock.y) - pm.height()   # bottom of sprite sits on the floor
            painter.drawPixmap(QPoint(x, y), pm)

    # Per-variant grass-tuft blade layouts: each blade is (x_offset, height).
    # Same visual language as the existing grass tufts in _draw_shrub, just a
    # few more arrangements so the carpet doesn't look stamped.
    _GRASS_TUFTS = [
        [(-5, 6), (-2, 9), ( 2, 7)],
        [(-4, 8), ( 0, 10), ( 4, 7)],
        [(-3, 7), ( 1, 9),  ( 5, 6)],
        [(-5, 7), (-1, 10), ( 3, 8)],
        [(-6, 5), (-2, 8), ( 1, 6), ( 4, 9)],          # 4-blade, wider
        [(-4, 6), (-1, 11), ( 2, 8), ( 5, 5)],         # 4-blade, tall centre
        [(-4, 12), (-1, 16), ( 3, 13)],                # tall reedy tuft
        [(-5, 10), (-2, 15), ( 1, 12), ( 4, 14)],      # tall 4-blade clump
    ]
    # Four green palettes (dark, mid, light) reused from the grass tufts.
    _GRASS_COLS = [
        ((32,  90, 38), (52, 125, 55), (82, 165, 74)),
        ((25,  72, 30), (42, 100, 48), (65, 138, 64)),
        ((42,  95, 28), (65, 130, 40), (95, 172, 54)),
        ((25,  78, 55), (44, 112, 78), (66, 150, 102)),
    ]

    def _draw_extra_rocks(self, painter: QPainter) -> None:
        """Draw the cosmetic extra-rock scatter (slider-driven).  Reuses the
        small rock sprite scaled per-rock; greenbeans gives them mossy tint."""
        if not self._extra_rocks:
            self._regen_extra_rocks()
        if not self._rock_pixmaps:
            return
        fy = self._garden_floor_y
        for (rx, base_idx, rscale) in self._extra_rocks:
            base = self._rock_pixmaps[min(base_idx, len(self._rock_pixmaps) - 1)]
            if base is None or base.isNull():
                continue
            pm = self._scaled_extra_rock(base, base_idx, rscale)
            painter.drawPixmap(QPoint(int(rx) - pm.width() // 2, fy - pm.height()), pm)

    def _scaled_extra_rock(self, base: 'QPixmap', base_idx: int,
                           rscale: float) -> 'QPixmap':
        """Cached scaled (+ mossy in greenbeans) copy of a rock sprite."""
        key = (base_idx, round(rscale, 2), self._greenbeans)
        pm  = self._extra_rock_cache.get(key)
        if pm is not None:
            return pm
        w = max(4, int(base.width() * rscale))
        h = max(3, int(base.height() * rscale))
        pm = base.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.FastTransformation)
        if self._greenbeans:
            pm = self._green_rock(pm)
        self._extra_rock_cache[key] = pm
        return pm

    def _build_grass_bed(self) -> 'QPixmap | None':
        """Render the static short-grass BED — a dense row of tiny blades across
        the whole width that fills the gaps between the tall tufts.  It ramps in
        above _GRASS_BED_START and reaches a solid carpet at 100%.  Doesn't move
        (it's baked into a pixmap), so it costs one blit per frame."""
        self._grass_bed_dirty = False
        self._grass_bed_pm = None
        strength = max(0.0, min(1.0, self._grass_bed_density / 100.0))
        if strength <= 0.0:
            return None
        w = max(1, self.width())
        H = self._grass_bed_baseline
        pm = QPixmap(w, H + 2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setPen(Qt.PenStyle.NoPen)
        cols = self._GRASS_COLS
        rng = _rnd.Random(7)                 # fixed seed → stable bed each rebuild
        # Chunky, OVERLAPPING blades (2-3 px wide) so it reads as a lush mat, not
        # thin hairs.  IRREGULAR spacing + heights so it never looks stamped.
        base_step = max(2, int(round(6 - 3 * strength)))   # avg gap shrinks w/ slider
        x = 0
        while x < w:
            shade = cols[rng.randrange(len(cols))]
            # mix all three tones (dark/mid/light) for depth, weighted to mid
            col = QColor(*shade[rng.choice((0, 1, 1, 2, 2))])
            bh = 3 + int(round(strength * 4)) + rng.randint(0, 4)   # ~3–11 px, very varied
            ww = 2 + (1 if rng.random() < 0.45 else 0)              # 2–3 px wide
            p.setBrush(col)
            p.drawRect(x, H - bh, ww, bh)
            # Irregular gap: jitter ±2 around the average so it's not periodic.
            x += max(1, base_step + rng.randint(-2, 3))
        p.end()
        self._grass_bed_pm = pm
        return pm

    def _build_grass_carpet(self, layer: int) -> 'QPixmap | None':
        """Render the at-rest carpet for ONE depth layer (0=behind Sao, 1=front)
        into a cached pixmap, so calm frames blit it in one drawPixmap."""
        tufts = [t for t in self._extra_grass if t.layer == layer]
        if not tufts:
            self._grass_carpet_pms[layer] = None
            return None
        w  = max(1, self.width())
        base = self._grass_carpet_baseline
        pm = QPixmap(w, base + 4)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setPen(Qt.PenStyle.NoPen)
        # At rest there's no breeze and every tuft.disturb is 0, so _grass_lean
        # returns 0 — the cached render matches the live per-tuft draw exactly.
        for tuft in tufts:
            self._draw_grass_tuft(p, tuft, base)
        p.end()
        self._grass_carpet_pms[layer] = pm
        return pm

    def _paint_grass_layer(self, painter: QPainter, layer: int) -> None:
        """Draw one grass depth layer — cached blit when calm, per-tuft when a
        breeze or disturbance is animating."""
        if self._grass_density <= 0 or self._garden_floor_y <= 0:
            return
        if not self._extra_grass:
            self._regen_extra_grass()
        animating = (self._breeze_front is not None or self._disturb_ticks_left > 0)
        if animating:
            painter.setPen(Qt.PenStyle.NoPen)
            for tuft in self._extra_grass:
                if tuft.layer == layer:
                    self._draw_grass_tuft(painter, tuft, self._garden_floor_y)
        else:
            pm = self._grass_carpet_pms.get(layer)
            if pm is None or (not isinstance(pm, bool) and pm.width() != self.width()):
                pm = self._build_grass_carpet(layer)
            if pm:
                painter.drawPixmap(
                    0, self._garden_floor_y - self._grass_carpet_baseline, pm)

    def _draw_grass_tuft(self, painter: QPainter, tuft, fy: int) -> None:
        """Draw one grass tuft from the density carpet.  `tuft` is a _GrassTuft
        carrying x / variant / scale + its live disturbance.  Blades bend by the
        breeze plus the tuft's own rustle when Sao/cursor sweeps past."""
        cx = int(tuft.x)
        variant = tuft.variant
        scale   = tuft.scale
        blades = self._GRASS_TUFTS[variant % len(self._GRASS_TUFTS)]
        LD, LM, LL = self._GRASS_COLS[variant % len(self._GRASS_COLS)]
        # Total lean for this tuft's position (px, can be fractional).
        lean = self._grass_lean(cx, tuft)
        # Extra-tall variation: ~30% of tufts grow taller (height only, not
        # width) when the toggle is on.
        h_mult = _GRASS_TALL_MULT if (self._extra_tall_grass and tuft.tall) else 1.0
        painter.setPen(Qt.PenStyle.NoPen)

        for bx_off, bh in blades:
            bh   = max(2, int(round(bh * scale * h_mult)))
            bx   = cx + int(round(bx_off * scale))
            split = bh * 2 // 3
            # Lower (rooted) section stays put; upper sections lean with wind.
            painter.setBrush(QColor(*LD))
            painter.drawRect(bx, fy - split, 2, split)
            mid_h = bh - split - 1
            if mid_h > 0:
                painter.setBrush(QColor(*LM))
                painter.drawRect(bx + int(round(lean)), fy - bh + 1, 2, mid_h)
            painter.setBrush(QColor(*LL))
            painter.drawRect(bx + int(round(lean * 2)), fy - bh, 1, 1)

    def _draw_shrub(self, painter: QPainter, shrub) -> None:
        """
        Vegetation sprite with two styles:
          • grass tuft  (bush_style=False) — 3 spread blades, ragged silhouette
          • edge bush   (bush_style=True)  — 4-5 tight blades + ground mound,
                                             similar height but denser / rounder
        Both share wind-lean animation (lean ±1/2 px on upper blade sections).
        """
        sx = int(shrub.x)
        fy = int(shrub.y)
        # Event-driven lean: breeze gust + this shrub's own disturbance from
        # Sao/cursor brushing past.  Calm air → 0 (no idle wiggle).
        lean = int(round(self._grass_lean(sx, shrub)))

        _COLS = [
            ((32,  90, 38), (52, 125, 55), (82, 165, 74)),
            ((25,  72, 30), (42, 100, 48), (65, 138, 64)),
            ((42,  95, 28), (65, 130, 40), (95, 172, 54)),
            ((25,  78, 55), (44, 112, 78), (66, 150, 102)),
        ]
        LD, LM, LL = _COLS[shrub.variant % 4]
        painter.setPen(Qt.PenStyle.NoPen)

        def _blade(bx_off: int, bh: int) -> None:
            bx    = sx + bx_off
            split = bh * 2 // 3
            painter.setBrush(QColor(*LD))
            painter.drawRect(bx, fy - split, 2, split)
            mid_h = bh - split - 1
            if mid_h > 0:
                painter.setBrush(QColor(*LM))
                painter.drawRect(bx + lean, fy - bh + 1, 2, mid_h)
            painter.setBrush(QColor(*LL))
            painter.drawRect(bx + lean * 2, fy - bh, 1, 1)

        if not shrub.bush_style:
            # ── Grass tuft: 3 blades, wide spacing ───────────────────────
            _GRASS = [
                [(-5, 6), (-2, 9), ( 2, 7)],
                [(-4, 8), ( 0, 10), ( 4, 7)],
                [(-3, 7), ( 1, 9),  ( 5, 6)],
                [(-5, 7), (-1, 10), ( 3, 8)],
            ]
            for bx_off, bh in _GRASS[shrub.variant % 4]:
                _blade(bx_off, bh)
        else:
            # ── Rounded pixel-art bush — chunky blob with 5 green tones ─────
            # Inspired by classic pixel-art bush sprites: circular/oval silhouette,
            # dark interior, light outer face, highlight spots on top.
            # Wind lean shifts rows above y_up=6 by ±1 px (gentle sway).
            v = shrub.variant % 4
            # Per-variant palette: (soil, dark, mid, light, highlight)
            _BPAL = [
                ((42, 26, 10), (28, 78, 30), (52, 122, 46), (88, 172, 65), (128, 212, 82)),
                ((38, 22,  9), (25, 70, 26), (46, 108, 40), (78, 155, 58), (115, 196, 76)),
                ((44, 28, 10), (35, 92, 28), (62, 138, 44), (100, 185, 65), (140, 222, 82)),
                ((40, 24, 12), (28, 80, 46), (50, 122, 68), (82, 165, 98),  (118, 202, 125)),
            ]
            SH, DK, MD, LT, HL = _BPAL[v]

            def br(xo: int, y_up: int, w: int, h: int, col: tuple) -> None:
                lo = lean if y_up > 6 else 0   # upper rows sway with wind
                painter.setBrush(QColor(*col))
                painter.drawRect(sx + xo + lo, fy - y_up, w, h)

            if v == 0:    # compact round ~22w × 16h
                br(-3,  1,  8, 1, SH)
                br(-7,  2, 14, 2, DK)
                br(-9,  4, 18, 2, DK)
                br(-9,  6, 18, 3, MD)
                br(-8,  9, 17, 3, MD)
                br(-6, 12, 14, 2, LT)
                br(-4, 14,  9, 2, LT)
                br(-1, 16,  4, 1, HL)
                br(-6,  5,  3, 2, DK)   # left dark pocket
                br( 4,  5,  3, 2, DK)   # right dark pocket
                br(-2, 13,  5, 1, HL)   # inner highlight

            elif v == 1:  # wider round ~26w × 16h
                br(-5,  1, 12, 1, SH)
                br(-9,  2, 20, 2, DK)
                br(-11, 4, 24, 2, DK)
                br(-11, 6, 24, 3, MD)
                br(-10, 9, 22, 3, MD)
                br(-8, 12, 18, 2, LT)
                br(-5, 14, 12, 2, LT)
                br(-2, 16,  6, 1, HL)
                br(-8,  5,  4, 2, DK)
                br( 5,  5,  4, 2, DK)
                br(-3, 13,  4, 1, HL)
                br( 2, 13,  3, 1, HL)

            elif v == 2:  # wide flat ~28w × 13h
                br(-6,  1, 14, 1, SH)
                br(-10, 2, 22, 2, DK)
                br(-12, 4, 26, 2, DK)
                br(-12, 6, 26, 3, MD)
                br(-11, 9, 24, 2, LT)
                br(-8, 11, 18, 2, LT)
                br(-4, 13,  9, 1, HL)
                br(-9,  5,  4, 2, DK)
                br( 6,  5,  4, 2, DK)
                br(-5, 12,  4, 1, HL)
                br( 3, 12,  3, 1, HL)

            else:         # tall full ~22w × 20h
                br(-3,  1,  7, 1, SH)
                br(-7,  2, 14, 2, DK)
                br(-9,  4, 18, 2, DK)
                br(-9,  6, 18, 3, MD)
                br(-9,  9, 18, 4, MD)
                br(-8, 13, 17, 4, LT)
                br(-6, 17, 14, 2, LT)
                br(-3, 19,  7, 1, HL)
                br(-7,  7,  3, 3, DK)   # left deep pocket
                br( 5,  7,  3, 3, DK)   # right deep pocket
                br(-3, 18,  4, 1, HL)
                br( 2, 18,  3, 1, HL)

    def _draw_plant_indicator(self, painter: QPainter, plant) -> None:
        """
        Animated '...' above the plant being tended.
        3 dots appear one at a time over 60 ticks, then vanish for 30, repeat.
        """
        period = 90
        phase  = self._indicator_tick % period
        if phase >= 75:   # blank for last 15 ticks of cycle
            return
        n_dots = (phase // 25) + 1   # 1, 2, or 3 dots

        from desktop_cat.garden import PLANT_TOP_HEIGHTS
        stage  = getattr(plant, 'stage', 4)
        top_h  = PLANT_TOP_HEIGHTS[min(stage, len(PLANT_TOP_HEIGHTS) - 1)]
        dot_y  = self._garden_floor_y - top_h - 6   # 6px above plant top

        dot_col = QColor(255, 255, 255, 180)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_col)
        spacing = 4
        total_w = (n_dots - 1) * spacing
        start_x = plant.x - total_w // 2
        for i in range(n_dots):
            painter.drawEllipse(start_x + i * spacing - 1, dot_y - 1, 3, 3)

    def _draw_task_flower(self, painter: QPainter, x: int, floor_y: int,
                          bloom_frac: float, wilted: bool,
                          overdue: bool = False,
                          variant: int = 0,
                          pop_ticks: int = 0,
                          due_today: bool = False,
                          highlight: bool = False,
                          faded: bool = False) -> None:
        """Draw a task flower using the real per-variant sprite system.

        bloom_frac (0.0 → 1.0) maps linearly to the variant's growth-frame
        animation, so the flower visibly grows from seed to bloom as the
        due-date approaches.

        Visual flourishes layered on top of the sprite render:
          • When bloom_frac >= 0.95 and not done: a soft yellow-tinted
            glow halo (yellow mixed with the variant's hue) so the user
            can spot urgent-soon flowers at a glance.
          • When `pop_ticks` > 0: scale up + fade out over the countdown
            (driven by main.py's tick).  Triggered when the matching
            todo is checked off — the flower briefly pops then vanishes.
          • When `wilted` and no pop in flight: a muted/grayer paint so
            the flower reads as "completed but still on screen".
        """
        # Sprite path requires the loaded sheet; if it didn't load for
        # any reason, render a small dot so the user still sees where the
        # todo lives.  (Old pixel-art fallback removed — it didn't use
        # the new sprites and was visually inconsistent.)
        if not self._sprites or not self._sprites.loaded:
            painter.setBrush(QColor(0xC8, 0x9B, 0x5A))
            painter.drawEllipse(x - 4, floor_y - 8, 8, 8)
            return

        from desktop_cat.sprite_sheet import (ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER,
                                               ANIM_RED_FLOWER, ANIM_WHITE_FLOWER,
                                               ANIM_TALL_FLOWER)
        anim_type = (variant or 0) % 5
        anim_idx  = [ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER, ANIM_RED_FLOWER,
                     ANIM_WHITE_FLOWER, ANIM_TALL_FLOWER][anim_type]
        frames = self._sprites.frames(anim_idx)
        if not frames:
            return

        # Map bloom_frac → growth frame.  Frame 0 is the seed/sprout, last
        # frame is the full bloom.  Round so we hit the last frame exactly
        # at frac=1.0 instead of going slightly past it.
        n = len(frames)
        gf = max(0, min(int(round(bloom_frac * (n - 1))), n - 1))
        frame = frames[gf]
        scale = _FLOWER_ANIM_SCALES[min(anim_type, len(_FLOWER_ANIM_SCALES) - 1)]
        sw = int(frame.width() * scale)
        sh = int(frame.height() * scale)

        # Pop animation: scales the flower up and fades it out over the
        # countdown.  Reads "✨ poof".
        pop_progress = 0.0
        pop_opacity  = 1.0
        if pop_ticks > 0:
            from desktop_cat.garden import POP_ANIM_TICKS
            pop_progress = 1.0 - max(0.0, min(1.0, pop_ticks / POP_ANIM_TICKS))
            pop_opacity  = max(0.0, 1.0 - pop_progress)
        pop_scale = 1.0 + 0.35 * pop_progress

        scaled = frame.scaled(int(sw * pop_scale), int(sh * pop_scale),
                              Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.FastTransformation)
        if wilted and pop_ticks == 0:
            # Subtle grayscale for completed-but-still-on-screen flowers.
            # In practice this state is very short (pop animation kicks in
            # immediately on done flip), but kept for completeness.
            from PyQt6.QtGui import QImage
            img = scaled.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            for py_ in range(img.height()):
                for px_ in range(img.width()):
                    px = img.pixel(px_, py_)
                    a  = (px >> 24) & 0xFF
                    if a == 0:
                        continue
                    r  = (px >> 16) & 0xFF
                    g  = (px >>  8) & 0xFF
                    b  =  px        & 0xFF
                    gray = (r * 30 + g * 59 + b * 11) // 100
                    img.setPixel(px_, py_,
                                 (a << 24) | (gray << 16) | (gray << 8) | gray)
            scaled = QPixmap.fromImage(img)

        if highlight and pop_ticks == 0:
            # Hub to-do hover → recolour the flower's ACTUAL pixels yellow
            # (brightness preserved from each pixel's luminance so it still
            # reads as a flower, just turned yellow).
            from PyQt6.QtGui import QImage
            img = scaled.toImage().convertToFormat(QImage.Format.Format_ARGB32)
            for py_ in range(img.height()):
                for px_ in range(img.width()):
                    px = img.pixel(px_, py_)
                    a  = (px >> 24) & 0xFF
                    if a == 0:
                        continue
                    r = (px >> 16) & 0xFF; g = (px >> 8) & 0xFF; b = px & 0xFF
                    lum = (r * 30 + g * 59 + b * 11) / 100.0 / 255.0
                    f   = 0.55 + 0.45 * lum
                    yr  = min(255, int(255 * f))
                    yg  = min(255, int(212 * f))
                    yb  = min(255, int(45 * f))
                    img.setPixel(px_, py_, (a << 24) | (yr << 16) | (yg << 8) | yb)
            scaled = QPixmap.fromImage(img)

        # ── Glow halo ─────────────────────────────────────────────────────
        # Painted BEFORE the flower so the sprite renders on top.
        #   • Due TODAY (or overdue): a purple halo — "this needs doing today".
        #   • Otherwise: a warm-yellow halo only at the very end (95 %+).
        _glow_threshold = 0.55 if due_today else 0.95
        if (not wilted and pop_ticks == 0 and not faded
                and bloom_frac >= _glow_threshold):
            if due_today:
                # Amethyst purple — same hue for every variant so "due today"
                # reads consistently regardless of the flower's own colour.
                r0, g0, b0 = (170, 90, 235)
                _intensity = 0.4   # 60 % softer than the yellow halo
            else:
                # Variant-tinted yellow.  All blends lean warm — yellow is the
                # dominant signal "this is urgent".
                variant_color = [
                    (180, 220,  80),   # green   → yellow-green
                    (220, 200,  80),   # blue    → soft warm yellow (no green)
                    (255, 170,  60),   # red     → warm orange-yellow
                    (255, 240, 170),   # white   → pale soft yellow
                    (210, 220,  80),   # tall    → bright lemon
                ][anim_type]
                r0, g0, b0 = variant_color
                _intensity = 1.0
            # Centre the halo roughly mid-petal-cluster (60 % up the sprite).
            glow_cx = x
            glow_cy = floor_y - int(sh * 0.6 * pop_scale)
            # Soft gentle pulse using a slow sine of a per-instance phase
            # (x-derived so different flowers don't pulse in lockstep).
            t = (self._time_phase if hasattr(self, '_time_phase') else 0.0)
            pulse = 0.85 + 0.15 * math.sin(t * 2.0 + x * 0.013)
            int_a = lambda base: int(base * pulse * pop_opacity * _intensity)
            # Due-today gets a slightly larger, softer aura.
            _rings = ([(34, 24), (24, 46), (14, 74)] if due_today
                      else [(28, 22), (20, 42), (12, 68)])
            for radius, alpha in _rings:
                painter.setBrush(QColor(r0, g0, b0, int_a(alpha)))
                painter.drawEllipse(glow_cx - radius, glow_cy - radius,
                                    radius * 2, radius * 2)

        # ── The sprite itself ────────────────────────────────────────────
        # Cursor hovering the flower → fade to ~20 % so the user can see (and
        # click) the taskbar app behind it.
        eff_op = min(pop_opacity, 0.20) if faded else pop_opacity
        if eff_op < 1.0:
            painter.setOpacity(eff_op)
        new_w = scaled.width()
        new_h = scaled.height()
        painter.drawPixmap(QPoint(x - new_w // 2, floor_y - new_h), scaled)
        if eff_op < 1.0:
            painter.setOpacity(1.0)

        # Overdue flowers (not done): tiny red urgency dot above the bloom,
        # only at high bloom_frac so we don't dot every sprout.
        if overdue and not wilted and pop_ticks == 0 and bloom_frac >= 0.7:
            painter.setBrush(QColor(220, 60, 40))
            painter.drawEllipse(x - 3, floor_y - new_h - 6, 6, 6)

    def _draw_falling_seed(self, painter: QPainter, x: int, y: int) -> None:
        """Tiny falling seed — a small glowing lavender dot with a trail."""
        painter.setPen(Qt.PenStyle.NoPen)
        # Trail
        for i in range(1, 4):
            alpha = 80 - i * 20
            painter.setBrush(QColor(185, 120, 255, max(0, alpha)))
            painter.drawEllipse(x - 2, y - i * 3 - 2, 4, 4)
        # Seed body
        painter.setBrush(QColor(185, 120, 255, 230))
        painter.drawEllipse(x - 3, y - 3, 6, 6)
        # Bright centre
        painter.setBrush(QColor(220, 200, 255, 255))
        painter.drawEllipse(x - 1, y - 2, 3, 3)

    def _draw_lazy_bug(self, painter: QPainter, lb) -> None:
        """Ladybug sprite — frames 0-4 walking, frames 5-8 idle stretch.
        Hue-shifted and flipped by facing direction."""
        if not (self._sprites and self._sprites.loaded):
            return
        raw_frames = self._sprites.frames(ANIM_LADYBUG)
        if not raw_frames:
            return
        # Lazy per-instance tint cache
        if not getattr(lb, '_tinted_frames', None):
            if self._greenbeans:
                lb._tinted_frames = _apply_hue_shift(raw_frames, 0, sat_delta=15, force_hue=_GREEN_HUE)
            else:
                lb._tinted_frames = _apply_hue_shift(raw_frames, getattr(lb, 'hue_shift', 0))
        frames = lb._tinted_frames or raw_frames

        n_total = len(frames)
        # Frames 0-3 = walk loop, 4+ = partial idle animation.
        walk_frames = frames[:min(4, n_total)]
        idle_frames = frames[4:n_total] if n_total > 4 else [frames[0]]

        if lb.state in ('resting',):
            if getattr(lb, 'idle_anim_active', False) and idle_frames:
                n_idle = len(idle_frames)
                fi = min(int(lb.idle_anim_phase / math.tau * n_idle), n_idle - 1)
                frame = idle_frames[fi]
            else:
                frame = walk_frames[0]   # rest pose = first walk frame
        else:
            nw = len(walk_frames)
            frame = walk_frames[int(lb.idle_phase / (2 * math.pi) * nw) % nw]

        # Ladybug frames are auto-cropped from a 36×39 grid, so each frame is
        # tightly bounded to the bug (bottom-aligned → sits on the floor, no
        # float). 1.7× larger than the old size so it's easy to see, then a
        # further +10%.
        scale = 0.75 * 1.7 * 1.1
        sw = int(frame.width()  * scale)
        sh = int(frame.height() * scale)
        cx = int(lb.x) - sw // 2
        cy = int(lb.y) - sh          # sit on the floor line

        painter.save()
        if lb.facing < 0:
            painter.translate(cx + sw, cy)
            painter.scale(-1, 1)
            painter.drawPixmap(QRect(0, 0, sw, sh), frame)
        else:
            painter.drawPixmap(QRect(cx, cy, sw, sh), frame)
        painter.restore()

    def _draw_snail(self, painter: QPainter, sn) -> None:
        """Snail sprite — cycles slowly, flipped by facing direction."""
        if not (self._sprites and self._sprites.loaded):
            return
        frames = self._sprites.frames(ANIM_SNAIL)
        if not frames:
            return
        n = len(frames)
        frame_idx = int(sn.anim_phase / (2 * math.pi) * n) % n
        frame = frames[frame_idx]
        scale = 0.91   # ~30% bigger than the old 0.7
        sw = int(frame.width()  * scale)
        sh = int(frame.height() * scale)
        cx = int(sn.x) - sw // 2
        cy = int(sn.y) - sh
        painter.save()
        if sn.facing < 0:
            painter.translate(cx + sw, cy)
            painter.scale(-1, 1)
            painter.drawPixmap(QRect(0, 0, sw, sh), frame)
        else:
            painter.drawPixmap(QRect(cx, cy, sw, sh), frame)
        painter.restore()

    def _draw_friend_bug(self, painter: QPainter, fb) -> None:
        """Tiny sprite bug.  Flying frames normally; sitting frames when attached to cursor."""
        if not (self._sprites and self._sprites.loaded):
            return

        # 'landing' state keeps flying frames — bug is still mid-air approaching the spot
        attached = getattr(fb, 'state', '') in ('attached', 'landed')

        # --- resolve base frames ---
        if attached:
            raw_sit = self._sprites.tiny_bug_sitting_frames()
            if not raw_sit:
                raw_sit = self._sprites.frames(ANIM_BUG_TINY)
            if not getattr(fb, '_tinted_sitting', None):
                if self._greenbeans:
                    fb._tinted_sitting = _apply_hue_shift(raw_sit, 0, val_clamp=200, force_hue=_GREEN_HUE)
                else:
                    fb._tinted_sitting = _apply_hue_shift(raw_sit, getattr(fb, 'hue_shift', 0),
                                                          sat_delta=-65, val_clamp=200)
            frames = fb._tinted_sitting or raw_sit
            # Play once and hold on last frame — no looping
            n = min(len(frames), 3)
            frame_idx = min(int(fb.flap_phase / (2 * math.pi) * n), n - 1)
            scale = 1.25   # 2.5x original 0.5x
        else:
            raw_fly = self._sprites.tiny_bug_flying_frames()
            if not raw_fly:
                raw_fly = self._sprites.frames(ANIM_BUG_TINY)
            if not getattr(fb, '_tinted_flying', None):
                if self._greenbeans:
                    fb._tinted_flying = _apply_hue_shift(raw_fly, 0, val_clamp=200, force_hue=_GREEN_HUE)
                else:
                    fb._tinted_flying = _apply_hue_shift(raw_fly, getattr(fb, 'hue_shift', 0),
                                                         sat_delta=-65, val_clamp=200)
            frames = fb._tinted_flying or raw_fly
            n = len(frames)
            frame_idx = int(fb.flap_phase / (2 * math.pi) * n) % n
            scale = 1.0    # 2x original 0.5x

        frame = frames[frame_idx]
        # Wings-down push lifts the flying bug up by 2px
        lift = -2 if (not attached and frame_idx in (4, 5)) else 0

        sw = int(frame.width()  * scale)
        sh = int(frame.height() * scale)
        x  = int(fb.x) - sw // 2
        y  = int(fb.y) - sh // 2 + lift

        painter.save()
        painter.setOpacity(fb.alpha / 255.0)
        painter.drawPixmap(QRect(x, y, sw, sh), frame)
        painter.restore()

    def _draw_butterfly(self, painter: QPainter, bf) -> None:
        """
        Draw a butterfly using the hand-drawn sprite sheet.
        bf.phase advances at 0.14 * bf.speed_mul per tick, starting at a random
        offset, so butterflies naturally flap out of sync and at slightly different
        speeds (0.85–1.15×).  Falls back to procedural if the sheet isn't loaded.
        """
        raw_frames = self._sprites.frames(ANIM_BUTTERFLY) if self._sprites else []
        # Lazy per-instance hue-shift cache — runs once, then reused every frame
        if raw_frames and not getattr(bf, '_tinted_frames', None):
            if self._greenbeans:
                bf._tinted_frames = _apply_hue_shift(raw_frames, 0, val_clamp=190, force_hue=_GREEN_HUE)
            else:
                bf._tinted_frames = _apply_hue_shift(raw_frames, getattr(bf, 'hue_shift', 0),
                                                     sat_delta=-70, val_clamp=190)
        frames = getattr(bf, '_tinted_frames', None) or raw_frames

        if frames:
            # Use only a subset of frames for cleaner flutter (0, 1, 3, 4, 8).
            keyframe_indices = [0, 1, 3, 4, 8]
            valid = [i for i in keyframe_indices if i < len(frames)]
            n_kf  = len(valid)
            # Frame rate driven purely by the phase accumulator, which advances
            # at bf.flap_speed * bf.speed_mul per tick.  When flap_speed → 0
            # the wings naturally stop.  Use a fixed divisor so 1 full
            # flap-cycle = π radians of phase.
            frame_idx = int(bf.phase / math.pi * n_kf) % n_kf
            frame     = frames[valid[frame_idx]]
            sw = int(frame.width()  * 0.75)
            sh = int(frame.height() * 0.75)
            state = getattr(bf, 'state', '')
            # Anchor on flower top only once actually landed/descending.  Earlier
            # states (considering, approaching, hovering) keep the centred
            # anchor so the butterfly flies through air, not skimming the ground.
            if state in ('landed', 'descending'):
                cx = int(bf.x) - sw // 2
                cy = int(bf.y) - sh      # bottom of sprite at bf.y
            else:
                cx = int(bf.x) - sw // 2
                cy = int(bf.y) - sh // 2
            # Jiggle sync — when the flower under a landed butterfly sways,
            # shake the butterfly with the SAME envelope the plant uses
            # (`sin(t·π) * sin(t·π·6)`) so left/right peaks line up.
            # Plant rotates ±3.5° around its base.  Top of a ~50 px stem
            # displaces sin(3.5°) * 50 ≈ 3 px.  Butterfly amplitude is set
            # to match that — over-shaking made the butterfly look like a
            # different animation rather than riding the flower.
            # Direction convention: positive angle in Qt rotates clockwise
            # → plant top moves RIGHT → butterfly x-offset positive (right).
            # If this ever feels reversed, NEGATE the formula here.
            jig_active = getattr(bf, 'jiggle_active', 0)
            jig_total  = max(1, getattr(bf, 'jiggle_total', 80))
            jx_off = 0.0
            if state == 'landed' and jig_active > 0:
                t = 1.0 - jig_active / jig_total
                # Match the plant: 3.5° * stem_height ≈ 3 px peak.
                jx_off = 3.0 * math.sin(t * math.pi) * math.sin(t * math.pi * 6)
            painter.save()
            painter.setOpacity(bf.alpha / 255.0)
            # Use translate() with floats so QPainter sub-pixel positions
            # the sprite — no integer rounding stair-stepping that made
            # the previous shake look twitchy.
            if getattr(bf, 'vx', 0) < 0:
                painter.translate(cx + sw + jx_off, cy)
                painter.scale(-1, 1)
                painter.drawPixmap(QRect(0, 0, sw, sh), frame)
            else:
                painter.translate(cx + jx_off, cy)
                painter.drawPixmap(QRect(0, 0, sw, sh), frame)
            painter.restore()
            return

        # ── Procedural fallback (sheet not loaded) ────────────────────────
        cx  = int(bf.x)
        cy  = int(bf.y)
        f   = math.sin(bf.phase)
        a   = bf.alpha
        uo  = int(-f * 2)
        lo  = int(-f * 1)
        wc  = QColor(bf.color[0],  bf.color[1],  bf.color[2],  a)
        sc  = QColor(bf.color2[0], bf.color2[1], bf.color2[2], a)
        bc  = QColor(30, 18, 6, a)
        painter.setPen(Qt.PenStyle.NoPen)
        u0 = cy - 5 + uo
        painter.setBrush(wc)
        painter.drawRect(cx - 5, u0,     4, 1); painter.drawRect(cx + 1, u0,     4, 1)
        painter.drawRect(cx - 6, u0 + 1, 5, 1); painter.drawRect(cx + 1, u0 + 1, 5, 1)
        painter.drawRect(cx - 7, u0 + 2, 6, 1); painter.drawRect(cx + 1, u0 + 2, 6, 1)
        painter.drawRect(cx - 6, u0 + 3, 5, 1); painter.drawRect(cx + 1, u0 + 3, 5, 1)
        painter.setBrush(sc)
        painter.drawRect(cx - 5, u0 + 1, 2, 1); painter.drawRect(cx + 3, u0 + 1, 2, 1)
        painter.drawRect(cx - 5, u0 + 2, 2, 1); painter.drawRect(cx + 3, u0 + 2, 2, 1)
        l0 = cy - 1 + lo
        painter.setBrush(wc)
        painter.drawRect(cx - 6, l0,     5, 1); painter.drawRect(cx + 1, l0,     5, 1)
        painter.drawRect(cx - 5, l0 + 1, 4, 1); painter.drawRect(cx + 1, l0 + 1, 4, 1)
        painter.drawRect(cx - 4, l0 + 2, 3, 1); painter.drawRect(cx + 1, l0 + 2, 3, 1)
        painter.setBrush(sc)
        painter.drawRect(cx - 4, l0, 2, 1); painter.drawRect(cx + 2, l0, 2, 1)
        painter.setBrush(bc)
        painter.drawRect(cx - 1, cy - 5, 2, 8)
        painter.drawRect(cx - 3, cy - 7, 1, 2); painter.drawRect(cx + 2, cy - 7, 1, 2)
        painter.drawRect(cx - 4, cy - 8, 2, 1); painter.drawRect(cx + 2, cy - 8, 2, 1)

    def _draw_collect_effect(self, painter: QPainter, eff) -> None:
        """Radial-line pop burst: spokes shoot outward then fade over ~22 ticks."""
        a = eff.alpha
        if a <= 0:
            return
        frame = eff.frame
        cx, cy = int(eff.x), int(eff.y)
        cr, cg, cb = eff.color
        n = eff.n_lines

        painter.setBrush(Qt.BrushStyle.NoBrush)

        # ── Radial spokes: short dashes that travel outward ──────────────
        r_outer = frame * 1.6
        r_inner = max(0.0, r_outer - 7)
        if r_outer > 0:
            painter.setPen(QPen(QColor(cr, cg, cb, a), 2))
            for i in range(n):
                angle = math.tau * i / n
                cos_a, sin_a = math.cos(angle), math.sin(angle)
                painter.drawLine(
                    int(cx + cos_a * r_inner), int(cy + sin_a * r_inner),
                    int(cx + cos_a * r_outer), int(cy + sin_a * r_outer),
                )

        # ── Thin expanding ring ───────────────────────────────────────────
        r_ring = max(1, int(frame * 0.85))
        ring_a = max(0, a - 70)
        if ring_a > 0:
            painter.setPen(QPen(QColor(cr, cg, cb, ring_a), 1))
            painter.drawEllipse(cx - r_ring, cy - r_ring, r_ring * 2, r_ring * 2)

        painter.setPen(Qt.PenStyle.NoPen)

    def _draw_platforms(self, painter: QPainter) -> None:
        font = QFont("Arial", 8)
        painter.setFont(font)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for p in self._platforms:
            is_bottom = p.hwnd < 0
            color = DEBUG_BOT_EDGE_COLOR if is_bottom else DEBUG_TOP_EDGE_COLOR
            painter.setPen(color)
            painter.drawLine(p.x, p.y, p.x + p.w, p.y)
            if not is_bottom:
                painter.setPen(DEBUG_TEXT_COLOR)
                painter.drawText(p.x + 4, p.y - 3, p.title[:30] if p.title else str(p.hwnd))

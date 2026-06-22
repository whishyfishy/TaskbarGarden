"""
Pomodoro overlay — the flip-dot timer panel that lives ON the world overlay
(taskbar area), plus the hut-shrink/strip-slide transition that segues
between idle world and active timer.

Owned by `CatOverlay` (renderer.py); ticked once per game-loop frame (60Hz).
The PomodoroWindow drives state transitions through start_pomodoro(),
update_remaining(), set_phase(), stop_pomodoro().

Visual model: a sparse grid of dots over the taskbar with NO panel background.
Dots start in camouflage (matches taskbar). A slow, slightly-rough left→right
wave flips them to a soft cream colour. Digits (MM:SS) draw as cream-coloured
dots inside the lit field. When ≤60 s remain on the current phase the lit
dots and digits both turn red.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui  import (QColor, QPainter, QPainterPath, QPen, QFont,
                          QFontMetrics, QPolygon)


# ── Animation timings (ticks @ 60Hz) ──────────────────────────────────────────
_IN_HOUSE_TICKS    = 36      # ~0.6 s — house move/shrink + strip slide-down
_IN_REVEAL_TICKS   = 190     # ~3.2 s — flip-dot wave left→right (slow)
_IN_DIGITS_TICKS   = 22      # ~0.37 s — digits ease-in after wave
_OUT_DIGITS_TICKS  = 14      # ~0.23 s — digits fade-out
_OUT_REVEAL_TICKS  = 140     # ~2.3 s — reverse wave
_OUT_HOUSE_TICKS   = 32      # ~0.53 s — strip slide-up + overshoot settle

# Strip-slide tuning (pixels)
_STRIP_WINDUP_BUMP = 7       # how far the strip pops UP before sliding away
_STRIP_OVERSHOOT   = 12      # how far above resting the strip flies on return

# Per-dot jitter — within a single column, individual dots flip up to this
# many "column-units" before/after the nominal column wave-time. Bigger =
# rougher / more analogue feel.
_JITTER_AMP = 0.55

# Flip-dot transition: while a dot is mid-flip it draws as a thin oval that
# expands to the full circle. Width is in "column units" of the wave, so a
# bigger value = slower visible flip animation per dot.
_FLIP_TRANSITION        = 0.165   # digit-change flips (unchanged)
_FLIP_TRANSITION_REVEAL = 0.2145  # initial reveal flips: 30% longer oval


# House transform during run state
_HUT_RUN_SCALE      = 0.78   # 78% of normal size while timer is running
_HUT_RUN_INSET_X    = 4      # px from panel-left to house centre offset
_HUT_RUN_INSET_Y    = 0

# Long-press cancel: dots flood yellow from left to right; reaches full → cancel.
_HOLD_CANCEL_TICKS    = 90   # 1.5s — full hold-to-cancel duration
_PRESS_RETREAT_TICKS  = 30   # 0.5s — how fast yellow recedes when released early
_PRESS_PAUSE_THRESHOLD = 30  # 0.5s — must hold longer than this before cancel bar starts

# Dot grid — chunky dots, generous spacing
_DOT_DIAM    = 5
_DOT_SPACING = 6

# "Almost out of time" threshold — dots + digits switch to red at this.
_ALARM_SECS = 60

# Tooltip
_TIP_FONT_PX = 12

# 4×5 compact pixel font for digits ───────────────────────────────────────────
_DIGIT_FONT: dict[str, list[str]] = {
    '0': ['0110', '1001', '1001', '1001', '0110'],
    '1': ['0010', '0110', '0010', '0010', '0111'],
    '2': ['1110', '0001', '0110', '1000', '1111'],
    '3': ['1110', '0001', '0110', '0001', '1110'],
    '4': ['1010', '1010', '1111', '0010', '0010'],
    '5': ['1111', '1000', '1110', '0001', '1110'],
    '6': ['0110', '1000', '1110', '1001', '0110'],
    '7': ['1111', '0001', '0010', '0100', '0100'],
    '8': ['0110', '1001', '0110', '1001', '0110'],
    '9': ['0110', '1001', '0111', '0001', '0110'],
}
_DIGIT_W = 4
_DIGIT_H = 5
# Vertical colon — 1 col wide, dots at rows 0,1 and 3,4 (skip middle).
_COLON_ROWS = (0, 1, 3, 4)
_COLON_W    = 1


# Per-dot digit-change transition.
# Ones-seconds (s2) flips very slowly (10% of the base speed).
# All other digits flip at 50% of the base speed.
# Jitter adds a small stable per-dot timing spread within each group.
_DIGIT_CHANGE_TICKS_S2    = 100   # ones-seconds: 10× slower
_DIGIT_CHANGE_TICKS_OTHER = 20    # minutes + tens-seconds: 2× slower
_DIGIT_CHANGE_JITTER      = 0     # all dots in a digit flip simultaneously


# ── Taskbar colour sampling (fallback safe) ───────────────────────────────────
_cached_taskbar_rgb: tuple[int, int, int] | None = None

def _sample_taskbar_color() -> tuple[int, int, int]:
    """Sample the actual Windows taskbar background colour once (cached)."""
    global _cached_taskbar_rgb
    if _cached_taskbar_rgb is not None:
        return _cached_taskbar_rgb
    rgb = (24, 24, 28)   # safe dark fallback
    try:
        import win32gui
        hwnd = win32gui.FindWindow('Shell_TrayWnd', None)
        if hwnd:
            rect = win32gui.GetWindowRect(hwnd)
            tw = rect[2] - rect[0]
            th = rect[3] - rect[1]
            sx = max(40, tw // 4)
            sy = max(4, th // 2)
            hdc = win32gui.GetWindowDC(hwnd)
            try:
                pix = win32gui.GetPixel(hdc, sx, sy)
                if pix != -1:
                    r =  pix        & 0xFF
                    g = (pix >>  8) & 0xFF
                    b = (pix >> 16) & 0xFF
                    rgb = (r, g, b)
            finally:
                win32gui.ReleaseDC(hwnd, hdc)
    except Exception:
        pass
    _cached_taskbar_rgb = rgb
    return rgb


def _slightly_darker(rgb: tuple[int, int, int], amount: int = 4) -> tuple[int, int, int]:
    return (max(0, rgb[0] - amount),
            max(0, rgb[1] - amount),
            max(0, rgb[2] - amount))


# ── Easing ────────────────────────────────────────────────────────────────────
def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3

def _ease_in_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t ** 3

def _ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2


# ── Phase identifiers (kept for window↔overlay API parity) ────────────────────
PHASE_WORK  = 'work'
PHASE_BREAK = 'break'
PHASE_LONG  = 'long_break'

# Alarm + paused + hold colours (independent of color mode)
_C_ALARM   = (190,  48,  44)   # deep red — phase ≤ 60 s remaining
_C_HOLD    = (245, 200,  60)   # yellow — long-press cancel wave + paused digits

# ── Colour-mode derivation ────────────────────────────────────────────────────
# Two modes: 0 = "pop" (complementary hue + value flip, dark panel + white
# digits), 1 = "light" (desaturated near-white panel + near-black digits).
# Both are derived from the live taskbar colour so the panel always feels
# tied to the system bar.

def _rgb_to_hsl(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        return (0.0, 0.0, l)
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = ((g - b) / d) + (6 if g < b else 0)
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return (h / 6, s, l)


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    if s == 0:
        v = int(round(l * 255))
        return (v, v, v)
    def hue2rgb(p, q, t):
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r = hue2rgb(p, q, h + 1/3)
    g = hue2rgb(p, q, h)
    b = hue2rgb(p, q, h - 1/3)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _derive_palette(taskbar_rgb: tuple[int, int, int],
                    mode: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Return (panel_rgb, digit_rgb) derived from the taskbar colour."""
    h, s, l = _rgb_to_hsl(taskbar_rgb)
    if mode == 1:
        # Light mode — desaturate, lift to near-white. Digit = near-black.
        panel = _hsl_to_rgb(h, max(0.0, s * 0.15), 0.93)
        digit = (10, 10, 10)
    else:
        # Pop mode — complementary hue, flip value (dark→darker, light→light),
        # boost saturation. Digit = white.
        h2 = (h + 0.5) % 1.0
        s2 = min(1.0, max(0.55, s + 0.30))
        l2 = max(0.18, min(0.30, 1.0 - l) * 0.5 + 0.15)
        panel = _hsl_to_rgb(h2, s2, l2)
        digit = (255, 255, 255)
    return (panel, digit)


def _stable_jitter(col: int, row: int) -> float:
    """Stable per-dot offset in [-_JITTER_AMP, +_JITTER_AMP] (column units)."""
    h = (col * 73856093) ^ (row * 19349663)
    h &= 0xFFFFFFFF
    return ((h % 1000) / 1000.0 - 0.5) * 2.0 * _JITTER_AMP


class PomodoroOverlay:
    """All world-overlay state for the pomodoro timer."""

    on_pause_clicked: callable | None = None
    on_cancel_clicked: callable | None = None

    def __init__(self) -> None:
        self.state = 'idle'        # idle|animating_in|revealing|running|animating_out
        self._t = 0
        self._out_substate = 'digits'   # digits|reveal|house

        self.remaining_seconds: int = 0
        self.phase: str = PHASE_WORK
        self.paused: bool = False

        self._panel_rect = QRect(0, 0, 0, 0)
        self._strip_rect = QRect(0, 0, 0, 0)

        self._hut_x_orig = 0
        self._hut_floor_y = 0

        self._hover = False
        self._cursor_pos = QPoint(-1, -1)
        self._mouse_pressed = False
        self._press_ticks = 0    # ticks held this press; resets on release
        self._press_wave = 0.0   # 0..1 — yellow wave from left; only advances
                                 # after _PRESS_PAUSE_THRESHOLD ticks of hold

        # Colour mode is fixed at 0 (pop — complementary hue, saturated panel).
        self.color_mode: int = 0

        # Display mode: 0 = flipdot grid, 1 = plain digital readout
        self.display_mode: int = 0

        # Digit-change rough transition.
        # _old_digit_cells — cells BEFORE the last second-tick change.
        # _cur_digit_cells — cells AFTER the last change (matches live digits).
        # _prev_group_map / _cur_group_map — per-cell group ('s2'|'other') at
        #   old/new state, used to pick the correct per-group transition speed.
        self._frame_tick: int = 0
        self._old_digit_cells: set[tuple[int, int]] = set()
        self._cur_digit_cells: set[tuple[int, int]] = set()
        self._prev_group_map: dict[tuple[int, int], str] = {}
        self._cur_group_map:  dict[tuple[int, int], str] = {}
        self._digit_change_tick: int = -10000

        # Pause-state colour-change flip transition tracking.
        self._paused_change_tick: int = -10000

    # ── Public API ─────────────────────────────────────────────────────────

    def start_pomodoro(self, remaining: int, phase: str) -> None:
        if self.state in ('running', 'revealing', 'animating_in'):
            return
        self.remaining_seconds = remaining
        self.phase = phase
        self.paused = False
        self.state = 'animating_in'
        self._t = 0
        _sample_taskbar_color()

    def stop_pomodoro(self) -> None:
        if self.state in ('idle', 'animating_out'):
            self.state = 'idle'
            self._t = 0
            return
        self.state = 'animating_out'
        self._out_substate = 'digits'
        self._t = 0
        self._mouse_pressed = False
        self._press_ticks = 0
        self._press_wave = 0.0

    def update_remaining(self, secs: int) -> None:
        self.remaining_seconds = max(0, int(secs))

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def set_paused(self, paused: bool) -> None:
        if paused != self.paused:
            self._paused_change_tick = self._frame_tick
        self.paused = paused

    def is_active(self) -> bool:
        return self.state != 'idle'

    def set_display_mode(self, mode: int) -> None:
        self.display_mode = 1 if int(mode) == 1 else 0

    def hut_is_offset(self) -> bool:
        return self.state in ('animating_in', 'revealing', 'running', 'animating_out')

    def panel_rect(self) -> QRect:
        return QRect(self._panel_rect)

    # ── Per-frame tick ─────────────────────────────────────────────────────

    def tick(self) -> None:
        # Frame counter advances every game tick regardless of state — used
        # for the digit-change rough transition timer.
        self._frame_tick += 1
        if self.state == 'idle':
            return
        self._t += 1

        if self.state == 'animating_in':
            if self._t >= _IN_HOUSE_TICKS:
                self.state = 'revealing'
                self._t = 0
            return

        if self.state == 'revealing':
            if self._t >= _IN_REVEAL_TICKS + _IN_DIGITS_TICKS:
                self.state = 'running'
                self._t = 0
            return

        if self.state == 'running':
            # Advance / retreat the yellow press wave.
            # Cancel bar only starts after _PRESS_PAUSE_THRESHOLD ticks so a
            # quick tap always registers as pause, never as an accidental cancel.
            holding = self._mouse_pressed and self._cursor_in_panel()
            if holding:
                self._press_ticks += 1
                if self._press_ticks > _PRESS_PAUSE_THRESHOLD:
                    self._press_wave = min(1.0,
                        self._press_wave + 1.0 / _HOLD_CANCEL_TICKS)
                    if self._press_wave >= 1.0:
                        self._mouse_pressed = False
                        self._press_ticks = 0
                        self._press_wave = 0.0
                        if self.on_cancel_clicked is not None:
                            self.on_cancel_clicked()
            else:
                self._press_ticks = 0
                self._press_wave = max(0.0,
                    self._press_wave - 1.0 / _PRESS_RETREAT_TICKS)
            return

        if self.state == 'animating_out':
            if self._out_substate == 'digits':
                if self._t >= _OUT_DIGITS_TICKS:
                    self._out_substate = 'reveal'
                    self._t = 0
            elif self._out_substate == 'reveal':
                if self._t >= _OUT_REVEAL_TICKS:
                    self._out_substate = 'house'
                    self._t = 0
            elif self._out_substate == 'house':
                if self._t >= _OUT_HOUSE_TICKS:
                    self.state = 'idle'
                    self._t = 0

    # ── Layout ─────────────────────────────────────────────────────────────

    def update_layout(self,
                      strip_left: int, strip_right: int,
                      strip_top: int, strip_bot: int,
                      hut_x: int, hut_floor_y: int) -> None:
        self._strip_rect = QRect(strip_left, strip_top,
                                 max(0, strip_right - strip_left),
                                 max(0, strip_bot - strip_top))
        # Panel matches strip horizontally exactly — no overflow into the
        # system tray. Stretched vertically to fill the taskbar so 5-row
        # digits fit cleanly with chunky dots.
        panel_top = max(0, strip_top - 10)
        panel_bot = strip_bot + 6
        self._panel_rect = QRect(strip_left, panel_top,
                                 max(0, strip_right - strip_left),
                                 max(0, panel_bot - panel_top))
        self._hut_x_orig = hut_x
        self._hut_floor_y = hut_floor_y

    # ── Hut transform ──────────────────────────────────────────────────────

    def hut_transform(self) -> tuple[int, int, float]:
        if not self.hut_is_offset():
            return (0, 0, 1.0)

        target_x = self._panel_rect.left() + _HUT_RUN_INSET_X - self._hut_x_orig
        target_y = _HUT_RUN_INSET_Y
        target_s = _HUT_RUN_SCALE

        if self.state == 'animating_in':
            t = _ease_in_out(self._t / max(1, _IN_HOUSE_TICKS))
            return (int(target_x * t),
                    int(target_y * t),
                    1.0 + (target_s - 1.0) * t)

        if self.state in ('revealing', 'running'):
            return (target_x, target_y, target_s)

        if self.state == 'animating_out':
            if self._out_substate == 'house':
                t = _ease_in_out(self._t / max(1, _OUT_HOUSE_TICKS))
                return (int(target_x * (1.0 - t)),
                        int(target_y * (1.0 - t)),
                        target_s + (1.0 - target_s) * t)
            return (target_x, target_y, target_s)

        return (0, 0, 1.0)

    # ── Strip slide-down ──────────────────────────────────────────────────

    def strip_offset_y(self) -> int:
        """Vertical offset of the taskbar pill.

        Going AWAY (animating_in): brief upward wind-up bump, then quick slide
        down out of view.

        Coming BACK (animating_out / house): quick slide up past the resting
        position to a small overshoot, then ease back down to settle.
        """
        if self.state == 'idle':
            return 0
        slide_dist = self._strip_rect.height() + 12

        if self.state == 'animating_in':
            t = self._t / max(1, _IN_HOUSE_TICKS)
            wind = 0.22  # first ~22% of the duration is the up-bump
            if t < wind:
                # Half-sine bump: 0 → -BUMP → 0
                phase = t / wind
                return -int(round(_STRIP_WINDUP_BUMP * math.sin(phase * math.pi)))
            # Main slide down — ease in so it accelerates away
            t2 = (t - wind) / (1.0 - wind)
            return int(round(slide_dist * _ease_in_cubic(t2)))

        if self.state in ('revealing', 'running'):
            return slide_dist

        if self.state == 'animating_out' and self._out_substate == 'house':
            t = self._t / max(1, _OUT_HOUSE_TICKS)
            rise = 0.65  # first ~65%: rise from below to above resting
            if t < rise:
                t1 = _ease_out_cubic(t / rise)
                # slide_dist (below) → -OVERSHOOT (above resting)
                return int(round(slide_dist + (-_STRIP_OVERSHOOT - slide_dist) * t1))
            # Settle from -OVERSHOOT back to 0 with an ease-out
            t2 = _ease_out_cubic((t - rise) / (1.0 - rise))
            return int(round(-_STRIP_OVERSHOOT * (1.0 - t2)))

        if self.state == 'animating_out':
            return slide_dist

        return 0

    # ── Drawing ────────────────────────────────────────────────────────────

    def draw(self, painter: QPainter) -> None:
        """Draw the dot field. NO panel background — dots only.
        Called BEFORE the hut so the hut renders on top."""
        if not self.is_active():
            return
        if self.state == 'animating_in':
            return
        if self.state == 'animating_out' and self._out_substate == 'house':
            return

        panel = self._panel_rect
        if panel.width() <= 0 or panel.height() <= 0:
            return

        alarm = (self.state == 'running'
                 and 0 < self.remaining_seconds <= _ALARM_SECS)
        tr, tg, tb = _sample_taskbar_color()
        # Background dots: 65% black, 35% toward the taskbar hue so the tint reads.
        if alarm:
            c2 = QColor(*_C_ALARM)
        else:
            c2 = QColor(tr * 35 // 100, tg * 35 // 100, tb * 35 // 100)
        c3 = QColor(255, 255, 255)
        c_hold = QColor(*_C_HOLD)
        if self.paused and self.state == 'running':
            c3 = c_hold

        # Click capture — applies to BOTH display modes. Without this fill,
        # transparent gaps in the panel pass clicks through to the taskbar
        # and tap-to-pause silently fails.
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 2))
        painter.drawRect(panel)
        painter.restore()

        # Digital readout mode — draw a compact slab around the digits and
        # bail before the dot-grid renderer runs.
        if self.display_mode == 1:
            # Slab background: 40% of taskbar color → clearly tinted but still
            # dark. Alarm red overrides as usual.
            if alarm:
                slab_bg = QColor(*_C_ALARM)
            else:
                slab_bg = QColor(tr * 40 // 100,
                                 tg * 40 // 100,
                                 tb * 40 // 100)
            self._draw_digital(painter, panel, slab_bg, c3)
            if self.state == 'running' and self._hover:
                self._draw_tooltip(painter)
            return

        # Compute dot grid — drop one column for breathing room.
        cols_natural = max(1, panel.width()  // _DOT_SPACING)
        rows_natural = max(1, panel.height() // _DOT_SPACING)
        cols = max(1, cols_natural - 1)
        rows = max(1, rows_natural)

        grid_w = cols * _DOT_SPACING
        grid_h = rows * _DOT_SPACING
        ox = panel.left() + (panel.width()  - grid_w) // 2 + _DOT_SPACING // 2
        oy = panel.top()  + (panel.height() - grid_h) // 2 + _DOT_SPACING // 2

        digits_alpha = self._digits_alpha()
        digit_group  = self._digit_group_map(cols, rows)
        digit_cells  = set(digit_group.keys())

        # Detect digit change → snapshot OLD state, update CURRENT state.
        # _old_digit_cells / _prev_group_map hold what was shown before;
        # _cur_* tracks the live display for comparison next tick.
        if digits_alpha >= 1.0 and digit_cells != self._cur_digit_cells:
            self._digit_change_tick = self._frame_tick
            self._old_digit_cells = set(self._cur_digit_cells)
            self._prev_group_map  = dict(self._cur_group_map)
            self._cur_digit_cells = digit_cells
            self._cur_group_map   = dict(digit_group)
        # Window covers the slowest possible transition (s2 group).
        change_age = self._frame_tick - self._digit_change_tick
        in_change_window = change_age < (_DIGIT_CHANGE_TICKS_S2 + _DIGIT_CHANGE_JITTER)

        # Rounded-corner mask — skip a small L-shaped clip at each corner so
        # the panel reads as a rounded rect instead of a hard rectangle.
        # Skips the outermost 2x2 of dots minus the diagonal cell at each
        # corner (so each corner loses 3 dots: corner + above + beside).
        corner_skip: set[tuple[int, int]] = set()
        if cols >= 4 and rows >= 4:
            corner_skip = {
                (0, 0), (1, 0), (0, 1),
                (cols - 1, 0), (cols - 2, 0), (cols - 1, 1),
                (0, rows - 1), (1, rows - 1), (0, rows - 2),
                (cols - 1, rows - 1), (cols - 2, rows - 1), (cols - 1, rows - 2),
            }

        # Reveal progress in dot-column units (with slop for jitter).
        # wave_pos goes from -JITTER_AMP → cols + JITTER_AMP across the
        # reveal so dots near both edges fully participate.
        wave_pos = self._wave_position(cols)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        # Yellow press-wave threshold (in column-fraction units 0..1)
        press_wave = self._press_wave

        # Pause colour-change oval: digit cells flip when paused/unpaused.
        paused_change_age = self._frame_tick - self._paused_change_tick
        paused_oval_active = (digits_alpha >= 1.0
                              and paused_change_age < _DIGIT_CHANGE_TICKS_OTHER)
        paused_change_progress = max(0.0, min(1.0,
            paused_change_age / max(1, _DIGIT_CHANGE_TICKS_OTHER)))

        # Convert press_wave (0..1 fraction) to col units so the cancel wave
        # uses identical math to the reveal wave, giving the same per-dot jitter
        # and oval timing.
        press_wave_cols = press_wave * cols

        for col in range(cols):
            for row in range(rows):
                if (col, row) in corner_skip:
                    continue
                cx = ox + col * _DOT_SPACING
                cy = oy + row * _DOT_SPACING

                jitter = _stable_jitter(col, row)
                local_t = wave_pos - (col + jitter)

                # Un-flipped dots not drawn — grid reveals out of nothing.
                if local_t <= 0:
                    continue

                # Cancel-wave progress per dot — mirrors reveal wave math exactly.
                # Positive = wave has reached this dot; negative = not yet.
                press_local_t = press_wave_cols - (col + jitter)
                in_press_zone = press_local_t > 0

                in_digit_now  = (col, row) in digit_cells
                in_digit_prev = (col, row) in self._old_digit_cells

                # Per-dot rough transition: compute change_progress (0→1) for
                # dots whose digit-membership flipped at the last second tick.
                # Speed depends on digit group: s2 (ones-seconds) is much slower.
                change_progress = 1.0
                if (in_change_window and digits_alpha >= 1.0
                        and in_digit_now != in_digit_prev):
                    grp = (digit_group.get((col, row))
                           or self._prev_group_map.get((col, row), 'other'))
                    ticks = (_DIGIT_CHANGE_TICKS_S2 if grp == 's2'
                             else _DIGIT_CHANGE_TICKS_OTHER)
                    jh = ((col * 928371) ^ (row * 113711)) & 0xFF
                    per_dot_delay = (jh / 255.0) * _DIGIT_CHANGE_JITTER
                    change_progress = max(0.0, min(1.0,
                        (change_age - per_dot_delay) / ticks))

                # ── Colour — target color only, no mid-transition blending ──
                # The oval shape carries the "flip" feel; color snaps immediately
                # to the destination so there's no intermediate hue shift.
                if in_press_zone:
                    brush_color = c_hold
                elif in_digit_now and digits_alpha > 0:
                    if digits_alpha >= 1.0:
                        brush_color = c3
                    else:
                        # Initial wave reveal only: blend c2 → c3 as digits fade in
                        brush_color = QColor(
                            int(c2.red()   * (1-digits_alpha) + c3.red()   * digits_alpha),
                            int(c2.green() * (1-digits_alpha) + c3.green() * digits_alpha),
                            int(c2.blue()  * (1-digits_alpha) + c3.blue()  * digits_alpha),
                        )
                else:
                    brush_color = c2

                painter.setBrush(brush_color)

                # ── Shape (oval for mid-flip) ─────────────────────────────
                # Priority order: reveal wave → digit pop-in → digit value
                # change → pause colour change → cancel-wave front → full circle.
                # All ovals grow thin→full so the flip direction is consistent.
                if local_t < _FLIP_TRANSITION_REVEAL:
                    # Initial reveal wave — longer oval window
                    eh = max(1, int(round(_DOT_DIAM * local_t / _FLIP_TRANSITION_REVEAL)))
                    painter.drawEllipse(cx - _DOT_DIAM // 2,
                                        cy - eh // 2,
                                        _DOT_DIAM, eh)
                elif (in_digit_now and 0 < digits_alpha < 1.0
                        and digits_alpha < _FLIP_TRANSITION_REVEAL):
                    # Digit cells popping in for the first time after the wave
                    eh = max(1, int(round(
                        _DOT_DIAM * digits_alpha / _FLIP_TRANSITION_REVEAL)))
                    painter.drawEllipse(cx - _DOT_DIAM // 2,
                                        cy - eh // 2,
                                        _DOT_DIAM, eh)
                elif (in_change_window and digits_alpha >= 1.0
                        and in_digit_now != in_digit_prev
                        and change_progress < _FLIP_TRANSITION):
                    # Digit value changed — flip oval
                    eh = max(1, int(round(
                        _DOT_DIAM * change_progress / _FLIP_TRANSITION)))
                    painter.drawEllipse(cx - _DOT_DIAM // 2,
                                        cy - eh // 2,
                                        _DOT_DIAM, eh)
                elif (paused_oval_active and in_digit_now
                        and paused_change_progress < _FLIP_TRANSITION):
                    # Pause/unpause colour flip on digit cells
                    eh = max(1, int(round(
                        _DOT_DIAM * paused_change_progress / _FLIP_TRANSITION)))
                    painter.drawEllipse(cx - _DOT_DIAM // 2,
                                        cy - eh // 2,
                                        _DOT_DIAM, eh)
                elif press_wave > 0 and press_local_t < _FLIP_TRANSITION_REVEAL:
                    # Cancel wave front — same oval math as the reveal wave,
                    # same jitter so it has the same organic roughness.
                    # press_local_t is 0 (just reached) → _FLIP_TRANSITION_REVEAL (full).
                    # For dots NOT yet in press zone, press_local_t is negative →
                    # this branch is only reached when in_press_zone is True
                    # (press_local_t > 0) so we only need the upper bound check.
                    eh = max(1, int(round(
                        _DOT_DIAM * press_local_t / _FLIP_TRANSITION_REVEAL)))
                    painter.drawEllipse(cx - _DOT_DIAM // 2,
                                        cy - eh // 2,
                                        _DOT_DIAM, eh)
                else:
                    painter.drawEllipse(cx - _DOT_DIAM // 2,
                                        cy - _DOT_DIAM // 2,
                                        _DOT_DIAM, _DOT_DIAM)

        painter.restore()

        if self.state == 'running' and self._hover:
            self._draw_tooltip(painter)

    # ── Wave / digit helpers ───────────────────────────────────────────────

    def _wave_position(self, cols: int) -> float:
        """Current wave head position in dot-column units (with edge slop)."""
        slop = _JITTER_AMP + 1.0
        full = cols + slop * 2
        if self.state == 'revealing':
            t = min(1.0, self._t / max(1, _IN_REVEAL_TICKS))
            t = _ease_out_cubic(t)
            return -slop + t * full
        if self.state == 'running':
            return cols + slop * 2
        if self.state == 'animating_out':
            if self._out_substate == 'digits':
                return cols + slop * 2
            if self._out_substate == 'reveal':
                t = min(1.0, self._t / max(1, _OUT_REVEAL_TICKS))
                # Reverse: wave retreats RIGHT→LEFT, so we shift the head
                # backwards. Easier: pretend wave_pos shrinks from full→0.
                t = _ease_in_cubic(t)
                return -slop + (1.0 - t) * full
            return -slop
        return -slop

    def _digits_alpha(self) -> float:
        if self.state == 'revealing':
            after_wave = self._t - _IN_REVEAL_TICKS
            if after_wave <= 0:
                return 0.0
            return min(1.0, after_wave / max(1, _IN_DIGITS_TICKS))
        if self.state == 'running':
            return 1.0
        if self.state == 'animating_out' and self._out_substate == 'digits':
            return max(0.0, 1.0 - self._t / max(1, _OUT_DIGITS_TICKS))
        return 0.0

    def _digit_group_map(self, cols: int,
                         rows: int) -> dict[tuple[int, int], str]:
        """Map (col, row) → group label ('s2' | 'other') for all digit cells.

        's2' = ones-seconds digit (flips slowly); 'other' = everything else.
        Text is centred across the full panel width; the hut is painted on top
        of the dot layer by the renderer so any overlap behind it is invisible.
        """
        secs = max(0, int(self.remaining_seconds))
        mins = min(99, secs // 60)
        m1, m2 = f'{mins:02d}'
        s1, s2 = f'{secs % 60:02d}'

        # (char, gap_after, group)
        layout: list[tuple[str, int, str]] = [
            (m1, 1, 'other'), (m2, 1, 'other'),
            (':', 1, 'other'),
            (s1, 1, 'other'), (s2, 0, 's2'),
        ]
        text_pixel_w = sum((_COLON_W if ch == ':' else _DIGIT_W) + g
                           for ch, g, _ in layout)
        text_pixel_h = _DIGIT_H

        if cols <= 0 or rows <= 0:
            return {}

        # Centre across the full panel width, then nudge 1 dot right so the
        # block visually sits between the hut and the right edge.
        start_col = max(0, (cols - text_pixel_w) // 2) + 1
        start_row = max(0, (rows - text_pixel_h) // 2)

        result: dict[tuple[int, int], str] = {}
        cur_col = start_col
        for ch, gap, grp in layout:
            if ch == ':':
                for py in _COLON_ROWS:
                    result[(cur_col, start_row + py)] = grp
                cur_col += _COLON_W + gap
                continue
            glyph = _DIGIT_FONT.get(ch)
            if glyph is not None:
                for py in range(_DIGIT_H):
                    row_str = glyph[py]
                    for px in range(_DIGIT_W):
                        if row_str[px] == '1':
                            result[(cur_col + px, start_row + py)] = grp
            cur_col += _DIGIT_W + gap

        return result

    # ── Tooltip ────────────────────────────────────────────────────────────

    # ── Digital readout (7-segment LED style) ──────────────────────────────

    # Segment membership per digit. Segments are labelled:
    #     a (top), b (top-R), c (bot-R), d (bot), e (bot-L), f (top-L), g (mid)
    _SEG_MAP = {
        '0': 'abcdef',  '1': 'bc',     '2': 'abdeg',  '3': 'abcdg',
        '4': 'bcfg',    '5': 'acdfg',  '6': 'acdefg', '7': 'abc',
        '8': 'abcdefg', '9': 'abcdfg',
    }

    def _draw_digital(self, painter: QPainter, panel: QRect,
                      bg: QColor, fg: QColor) -> None:
        """7-segment LED-style MM:SS readout in a compact slab around the digits."""
        secs = max(0, int(self.remaining_seconds))
        mins = min(99, secs // 60)
        digits = f"{mins:02d}{secs % 60:02d}"

        # ── Layout — sized off the available digit height ──────────────────
        pad_y     = max(3, panel.height() // 10)
        digit_h   = panel.height() - 2 * pad_y
        digit_w   = max(8, int(digit_h * 0.55))
        seg_t     = max(2, digit_h // 9)
        digit_gap = max(2, digit_w // 6)
        colon_w   = max(seg_t * 2, digit_w // 4)
        slab_pad_x = max(6, digit_w // 2)
        slab_pad_y = max(3, pad_y // 2)

        digits_w = digit_w * 4 + digit_gap * 3 + colon_w
        slab_w   = digits_w + 2 * slab_pad_x
        slab_h   = digit_h + 2 * slab_pad_y

        # Centre the slab in the space to the right of the hut.
        # Mirror the dot-grid placement: shift +1 dot off centre so the slab
        # nestles between the hut and the right edge.
        hut_clear_px = 36
        avail_left   = panel.left() + hut_clear_px
        avail_right  = panel.right()
        slab_x       = avail_left + ((avail_right - avail_left) - slab_w) // 2
        slab_x       = max(panel.left() + 2, slab_x)
        slab_y       = panel.top() + (panel.height() - slab_h) // 2

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Compact rounded slab around just the digits
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(slab_x, slab_y, slab_w, slab_h, 6, 6)

        # Faint "off" segments for that classic LED look
        off_color = QColor(fg.red(), fg.green(), fg.blue(), 28)

        x = slab_x + slab_pad_x
        y0 = slab_y + slab_pad_y
        for i, ch in enumerate(digits):
            self._draw_seg_digit(painter, x, y0, digit_w, digit_h, seg_t,
                                 ch, fg, off_color)
            x += digit_w + digit_gap
            if i == 1:
                # Colon between MM and SS
                cy_top = y0 + digit_h // 3
                cy_bot = y0 + digit_h * 2 // 3
                dot_r  = max(2, seg_t)
                cx     = x + colon_w // 2 - digit_gap // 2
                painter.setBrush(fg)
                painter.drawEllipse(cx - dot_r, cy_top - dot_r,
                                    dot_r * 2, dot_r * 2)
                painter.drawEllipse(cx - dot_r, cy_bot - dot_r,
                                    dot_r * 2, dot_r * 2)
                x += colon_w

        # Yellow press-wave bar — grows left→right over the slab as the user
        # holds down. Clipped to the slab's rounded-rect shape so it stays inside.
        if self._press_wave > 0:
            bar_w = int(slab_w * self._press_wave)
            if bar_w > 0:
                clip_path = QPainterPath()
                clip_path.addRoundedRect(slab_x, slab_y, slab_w, slab_h, 6.0, 6.0)
                painter.setClipPath(clip_path)
                painter.setBrush(QColor(_C_HOLD[0], _C_HOLD[1], _C_HOLD[2], 160))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(slab_x, slab_y, bar_w, slab_h)
                painter.setClipping(False)

        painter.restore()

    @classmethod
    def _draw_seg_digit(cls, painter: QPainter, x: int, y: int,
                        w: int, h: int, t: int, char: str,
                        on_color: QColor, off_color: QColor) -> None:
        """Render one 7-segment digit. Off segments draw faintly so the
        unlit-but-visible LCD/LED aesthetic comes through."""
        active = set(cls._SEG_MAP.get(char, ''))
        mid_y  = y + (h - t) // 2
        half_h = (h - t) // 2

        # Segment polygons — angled ends so segments meet cleanly at corners.
        b = t  # bevel size at segment ends

        def horiz(yy: int) -> QPolygon:
            return QPolygon([
                QPoint(x + b,         yy),
                QPoint(x + w - b,     yy),
                QPoint(x + w - b - b, yy + t // 2),
                QPoint(x + w - b,     yy + t),
                QPoint(x + b,         yy + t),
                QPoint(x + b + b,     yy + t // 2),
            ])

        def vert(xx: int, yy: int) -> QPolygon:
            return QPolygon([
                QPoint(xx,         yy + b),
                QPoint(xx + t // 2, yy + b - b),
                QPoint(xx + t,     yy + b),
                QPoint(xx + t,     yy + half_h - b),
                QPoint(xx + t // 2, yy + half_h),
                QPoint(xx,         yy + half_h - b),
            ])

        segs = {
            'a': horiz(y),
            'g': horiz(mid_y),
            'd': horiz(y + h - t),
            'f': vert(x,         y),
            'b': vert(x + w - t, y),
            'e': vert(x,         mid_y + t // 2),
            'c': vert(x + w - t, mid_y + t // 2),
        }

        painter.setPen(Qt.PenStyle.NoPen)
        for name, poly in segs.items():
            painter.setBrush(on_color if name in active else off_color)
            painter.drawPolygon(poly)

    def _draw_tooltip(self, painter: QPainter) -> None:
        if self._mouse_pressed:
            text = 'hold to cancel…'
        elif self.paused:
            text = 'click to resume'
        else:
            text = 'click to pause  ·  hold to cancel'
        font = QFont('Segoe UI Variable', 1)
        font.setPixelSize(_TIP_FONT_PX)
        font.setBold(True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text) + 14
        th = _TIP_FONT_PX + 8
        panel = self._panel_rect
        tx = panel.left() + (panel.width() - tw) // 2
        ty = panel.top() - th - 6
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(20, 20, 24, 230))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(tx, ty, tw, th, 5, 5)
        painter.setPen(QColor(240, 240, 244))
        painter.drawText(QRect(tx, ty, tw, th),
                         Qt.AlignmentFlag.AlignCenter, text)

    # ── Mouse / hover ──────────────────────────────────────────────────────

    def cursor_over_panel(self, pos: QPoint) -> bool:
        if self.state not in ('revealing', 'running'):
            return False
        return self._panel_rect.contains(pos)

    def update_hover(self, pos: QPoint) -> bool:
        self._cursor_pos = pos
        new_hover = self.cursor_over_panel(pos)
        if new_hover != self._hover:
            self._hover = new_hover
            return True
        return False

    def _cursor_in_panel(self) -> bool:
        return self._panel_rect.contains(self._cursor_pos)

    def mouse_press(self, pos: QPoint) -> bool:
        if self.state != 'running':
            return False
        if not self._panel_rect.contains(pos):
            return False
        self._mouse_pressed = True
        self._press_ticks = 0
        return True

    def mouse_release(self, pos: QPoint) -> bool:
        if not self._mouse_pressed:
            return False
        # A tap held shorter than the deadband never started the cancel bar,
        # so it's always a pause toggle regardless of wave state.
        was_quick = self._press_ticks < _PRESS_PAUSE_THRESHOLD
        consumed  = self._panel_rect.contains(pos)
        self._mouse_pressed = False
        self._press_ticks = 0
        if consumed and was_quick:
            if self.on_pause_clicked is not None:
                self.on_pause_clicked()
        return consumed

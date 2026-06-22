"""
Pomodoro window — minimal square panel with three screens:

    'start'    — big circular START button + small 'Options' link
    'running'  — big circular PAUSE/RESUME button + small 'Cancel' link
                 (drives the on-overlay flip-dot timer panel)
    'options'  — settings list + 'Back' link

The actual countdown digits live on the world overlay (PomodoroOverlay,
managed by CatOverlay). This window owns:
  - Settings persistence (work/break/long/rounds + toggles)
  - Phase + remaining-second logic
  - Push to overlay each second
  - Animation kick-off / tear-down on START / Cancel
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Callable

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import (Qt, QPoint, QRect, QRectF, QTimer,
                             QPropertyAnimation, QEasingCurve, pyqtProperty)
from PyQt6.QtGui     import QPainter, QColor, QPen, QFont, QPainterPath, QBrush

from desktop_cat.retro_ui import configure_floating_panel, cancel_window_dimming
from desktop_cat.theme    import theme
from desktop_cat.pomodoro_overlay import PHASE_WORK, PHASE_BREAK, PHASE_LONG


_SAVE_PATH = os.path.join(os.path.dirname(__file__), 'pomodoro.json')

# Window geometry — square, more compact than the old tall rectangle
_W = 280
_H = 300
_RADIUS = 14

_OPEN_MS  = 220
_CLOSE_MS = 160
_POP_SCALE_START = 0.85

# Cycle option lists
_WORK_OPTS       = [15, 20, 25, 30, 45, 60]
_BREAK_OPTS      = [3, 5, 10, 15]
_LONG_BREAK_OPTS = [15, 20, 30]
_ROUNDS_OPTS     = [2, 3, 4, 5, 6]

_DEFAULT_SETTINGS: dict = {
    'work_mins':         25,
    'break_mins':        5,
    'long_break_mins':   15,
    'rounds':            4,
    'visual_flash':      True,
    'auto_start':        False,
    'block_apps':        False,
    'task':              'focus time',
    'completed_today':   0,
    'last_date':         '',
    'streak':            0,
    'last_streak_date':  '',
    'completed_round':   0,
}

# Palette (mutated on theme flip)
_C_BG       = QColor(0xF7, 0xF7, 0xFA, 252)
_C_HEADER   = QColor(0xEC, 0xEC, 0xF1)
_C_BORDER   = QColor(0x00, 0x00, 0x00, 36)
_C_TEXT     = QColor(0x1F, 0x1F, 0x21)
_C_MUTED    = QColor(0x60, 0x60, 0x68)
_C_LINK     = QColor(0x46, 0x82, 0xE6)
_C_START    = QColor(0xE2, 0x70, 0x55)        # warm orange-red — START
_C_PAUSE    = QColor(0x6F, 0xC1, 0x8B)        # mint green — PAUSE
_C_RESUME   = QColor(0xE2, 0x70, 0x55)
_C_DIVIDER  = QColor(0x00, 0x00, 0x00, 24)
_C_CYCLE_BG = QColor(0xFF, 0xFF, 0xFF)


def _refresh_palette() -> None:
    if theme.is_dark():
        _C_BG.setRgb(0x22, 0x23, 0x28, 252)
        _C_HEADER.setRgb(0x18, 0x19, 0x1D)
        _C_BORDER.setRgb(0xFF, 0xFF, 0xFF, 30)
        _C_TEXT.setRgb(0xF0, 0xF0, 0xF2)
        _C_MUTED.setRgb(0xA8, 0xA8, 0xB0)
        _C_DIVIDER.setRgb(0xFF, 0xFF, 0xFF, 24)
        _C_CYCLE_BG.setRgb(0x33, 0x34, 0x39)
    else:
        _C_BG.setRgb(0xF7, 0xF7, 0xFA, 252)
        _C_HEADER.setRgb(0xEC, 0xEC, 0xF1)
        _C_BORDER.setRgb(0x00, 0x00, 0x00, 36)
        _C_TEXT.setRgb(0x1F, 0x1F, 0x21)
        _C_MUTED.setRgb(0x60, 0x60, 0x68)
        _C_DIVIDER.setRgb(0x00, 0x00, 0x00, 24)
        _C_CYCLE_BG.setRgb(0xFF, 0xFF, 0xFF)


_refresh_palette()
theme.changed.connect(_refresh_palette)


def _font(px: int, *, bold: bool = False) -> QFont:
    f = QFont('Segoe UI Variable', 1)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


class PomodoroWindow(QWidget):
    """Minimal pomodoro launcher.

    Hooks (set after construction):
        on_start_animation(remaining_seconds, phase)
        on_stop_animation()
        on_remaining_changed(remaining_seconds, phase)
        on_pause_state_changed(paused)
    """

    on_start_animation:    Callable | None = None
    on_stop_animation:     Callable | None = None
    on_remaining_changed:  Callable | None = None
    on_pause_state_changed: Callable | None = None

    def __init__(self) -> None:
        super().__init__()
        configure_floating_panel(self)
        self.setFixedSize(_W, _H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._settings = self._load()
        self._roll_date()

        # Screen state: 'start' | 'running' | 'options'
        self._screen = 'start'

        # Timer state
        self._phase     = PHASE_WORK
        self._remaining = int(self._settings['work_mins']) * 60
        self._total     = self._remaining
        self._running   = False     # True between start and pause/cancel
        self._paused    = False

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

        # Window animation state
        self._anim_scale: float = 1.0
        self._closing = False
        self._drag_offset: QPoint | None = None
        self._hovered_key: str | None = None

        # Hover-tracked rects, recomputed each paint
        self._hit_rects: dict[str, QRect] = {}

        theme.changed.connect(self.update)

    # ── Persistence ─────────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            with open(_SAVE_PATH) as f:
                raw = json.load(f)
            s = dict(_DEFAULT_SETTINGS)
            for k, v in raw.items():
                if k in s:
                    s[k] = v
            return s
        except (OSError, ValueError):
            return dict(_DEFAULT_SETTINGS)

    def _save(self) -> None:
        try:
            with open(_SAVE_PATH, 'w') as f:
                json.dump(self._settings, f)
        except OSError:
            pass

    def _roll_date(self) -> None:
        today = date.today().isoformat()
        if self._settings.get('last_date', '') != today:
            self._settings['completed_today'] = 0
            self._settings['last_date'] = today
            self._settings['completed_round'] = 0

    # ── Animatable scale ────────────────────────────────────────────────────

    @pyqtProperty(float)
    def anim_scale(self) -> float:    # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    # ── Show / close ────────────────────────────────────────────────────────

    def show_animated(self, x: int, y: int) -> None:
        self._closing = False
        self._anim_scale = _POP_SCALE_START
        self.setWindowOpacity(0.0)
        self.move(x, y)
        self.show()
        self.setFocus()

        scale = QPropertyAnimation(self, b'anim_scale', self)
        scale.setDuration(_OPEN_MS)
        scale.setStartValue(_POP_SCALE_START)
        scale.setEndValue(1.0)
        scale.setEasingCurve(QEasingCurve.Type.OutBack)
        scale.start()
        self._open_scale_anim = scale

        op = QPropertyAnimation(self, b'windowOpacity', self)
        op.setDuration(_OPEN_MS)
        op.setStartValue(0.0)
        op.setEndValue(1.0)
        op.start()
        self._open_op_anim = op

    def close_animated(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._save()
        cancel_window_dimming(self)

        s = QPropertyAnimation(self, b'anim_scale', self)
        s.setDuration(_CLOSE_MS)
        s.setStartValue(self._anim_scale)
        s.setEndValue(_POP_SCALE_START)
        s.start()
        self._close_scale_anim = s

        o = QPropertyAnimation(self, b'windowOpacity', self)
        o.setDuration(_CLOSE_MS)
        o.setStartValue(self.windowOpacity())
        o.setEndValue(0.0)
        o.finished.connect(self.close)
        o.start()
        self._close_op_anim = o

        QTimer.singleShot(_CLOSE_MS + 100, self._force_close_if_needed)

    def _force_close_if_needed(self) -> None:
        if self._closing and self.isVisible():
            self.setWindowOpacity(0.0)
            self.close()

    def closeEvent(self, event) -> None:
        self._save()
        if self._running:
            # Timer is active — just hide the window; the tick must keep going
            # so the overlay continues counting. The window will re-open from
            # the hub in its running state.
            event.ignore()
            self.hide()
            return
        self._tick.stop()
        super().closeEvent(event)

    # ── Timer logic ─────────────────────────────────────────────────────────

    def _phase_total(self, phase: str) -> int:
        if phase == PHASE_WORK:
            return int(self._settings['work_mins']) * 60
        if phase == PHASE_BREAK:
            return int(self._settings['break_mins']) * 60
        return int(self._settings['long_break_mins']) * 60

    def _start(self) -> None:
        if self._remaining <= 0:
            self._remaining = self._phase_total(self._phase)
            self._total = self._remaining
        # Switch UI to running screen and kick off overlay animation.
        self._screen   = 'running'
        self._running  = True
        self._paused   = False
        self._tick.start()
        if self.on_start_animation is not None:
            self.on_start_animation(self._remaining, self._phase)
        if self.on_pause_state_changed is not None:
            self.on_pause_state_changed(False)
        self.update()

    # Public: keybind-friendly entry point (used by global hotkey).
    def start_from_keybind(self) -> None:
        if self._running:
            return
        self._start()

    def _toggle_pause(self) -> None:
        if not self._running:
            return
        self._paused = not self._paused
        if self._paused:
            self._tick.stop()
        else:
            self._tick.start()
        if self.on_pause_state_changed is not None:
            self.on_pause_state_changed(self._paused)
        self.update()

    def _cancel(self) -> None:
        """User explicitly cancels — reverse animation, return to start screen."""
        self._tick.stop()
        self._running = False
        self._paused  = False
        self._screen  = 'start'
        # Reset remaining to phase total for next start
        self._remaining = self._phase_total(self._phase)
        self._total = self._remaining
        if self.on_stop_animation is not None:
            self.on_stop_animation()
        self.update()

    def _on_tick(self) -> None:
        if self._remaining > 0:
            self._remaining -= 1
        if self.on_remaining_changed is not None:
            self.on_remaining_changed(self._remaining, self._phase)
        if self._remaining <= 0:
            self._advance_phase()
        self.update()

    def _advance_phase(self) -> None:
        was = self._phase
        if was == PHASE_WORK:
            self._roll_date()
            self._settings['completed_today'] = int(self._settings.get('completed_today', 0)) + 1
            self._settings['completed_round'] = int(self._settings.get('completed_round', 0)) + 1
            self._update_streak()
            rounds = int(self._settings.get('rounds', 4))
            cr = int(self._settings.get('completed_round', 0))
            if rounds > 0 and cr % rounds == 0:
                next_phase = PHASE_LONG
                self._settings['completed_round'] = 0
            else:
                next_phase = PHASE_BREAK
        else:
            next_phase = PHASE_WORK

        self._phase = next_phase
        self._remaining = self._phase_total(next_phase)
        self._total = self._remaining
        self._save()

        # Push fresh values to overlay
        if self.on_remaining_changed is not None:
            self.on_remaining_changed(self._remaining, self._phase)

        if not self._settings.get('auto_start', False):
            # Pause until user clicks resume
            self._paused = True
            self._tick.stop()
            if self.on_pause_state_changed is not None:
                self.on_pause_state_changed(True)

    def _update_streak(self) -> None:
        today = date.today().isoformat()
        last  = self._settings.get('last_streak_date', '')
        if last == today:
            return
        if last:
            try:
                last_d = date.fromisoformat(last)
                if (date.today() - last_d) == timedelta(days=1):
                    self._settings['streak'] = int(self._settings.get('streak', 0)) + 1
                else:
                    self._settings['streak'] = 1
            except ValueError:
                self._settings['streak'] = 1
        else:
            self._settings['streak'] = 1
        self._settings['last_streak_date'] = today

    # ── Layout helpers ──────────────────────────────────────────────────────

    def _content_rect(self) -> QRect:
        # Inner content area below the title bar
        return QRect(0, 28, _W, _H - 28)

    def _close_rect(self) -> QRect:
        return QRect(_W - 26, 6, 18, 18)

    def _big_button_rect(self) -> QRect:
        """Square containing the big circular START / PAUSE button (~80% H)."""
        cr = self._content_rect()
        # Reserve ~36px at the bottom for the small Options/Cancel link
        avail_h = cr.height() - 38
        size = min(cr.width() - 32, avail_h)
        x = cr.left() + (cr.width()  - size) // 2
        y = cr.top()  + (avail_h - size) // 2 + 4
        return QRect(x, y, size, size)

    def _link_rect(self) -> QRect:
        """Small text-button rect at the bottom (Options / Cancel / Back)."""
        return QRect(0, _H - 32, _W, 24)

    # ── Painting ────────────────────────────────────────────────────────────

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Scale-pop transform (open animation only)
        if self._anim_scale != 1.0:
            cx = _W / 2; cy = _H / 2
            p.translate(cx, cy)
            p.scale(self._anim_scale, self._anim_scale)
            p.translate(-cx, -cy)

        self._hit_rects.clear()

        # Background card
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, _W - 1, _H - 1, _RADIUS, _RADIUS)
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_C_BG)
        p.drawRect(0, 0, _W, _H)

        # Title bar
        p.setBrush(_C_HEADER)
        p.drawRect(0, 0, _W, 28)
        p.setPen(_C_TEXT)
        p.setFont(_font(12, bold=True))
        title = {
            'start':   'pomodoro',
            'running': 'pomodoro · running',
            'options': 'pomodoro · options',
        }[self._screen]
        p.drawText(QRect(12, 0, _W - 60, 28),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # Close X
        cr = self._close_rect()
        self._hit_rects['close'] = cr
        hov = self._hovered_key == 'close'
        if hov:
            p.setBrush(QColor(0xE8, 0x4C, 0x4C))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(cr, 4, 4)
            p.setPen(QPen(QColor(255, 255, 255), 1.6))
        else:
            p.setPen(QPen(_C_MUTED, 1.6))
        cxc, cyc = cr.center().x(), cr.center().y()
        p.drawLine(cxc - 4, cyc - 4, cxc + 4, cyc + 4)
        p.drawLine(cxc + 4, cyc - 4, cxc - 4, cyc + 4)

        # Body
        if self._screen == 'start':
            self._paint_start(p)
        elif self._screen == 'running':
            self._paint_running(p)
        else:
            self._paint_options(p)

        # Outer hairline
        p.setClipping(False)
        p.setPen(QPen(_C_BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, _W - 1, _H - 1), _RADIUS, _RADIUS)

    # ── Screen: START ───────────────────────────────────────────────────────

    def _paint_start(self, p: QPainter) -> None:
        rect = self._big_button_rect()
        self._hit_rects['big'] = rect
        hov = self._hovered_key == 'big'
        self._draw_circle_button(p, rect, _C_START, 'START', hov)

        # Small Options link
        lr = self._link_rect()
        self._hit_rects['options'] = lr
        hov_l = self._hovered_key == 'options'
        p.setPen(_C_LINK if hov_l else _C_MUTED)
        p.setFont(_font(13, bold=hov_l))
        p.drawText(lr, Qt.AlignmentFlag.AlignCenter, 'Options')

    # ── Screen: RUNNING ─────────────────────────────────────────────────────

    def _paint_running(self, p: QPainter) -> None:
        rect = self._big_button_rect()
        self._hit_rects['big'] = rect
        hov = self._hovered_key == 'big'
        if self._paused:
            self._draw_circle_button(p, rect, _C_RESUME, 'RESUME', hov,
                                      glyph='play')
        else:
            self._draw_circle_button(p, rect, _C_PAUSE, 'PAUSE', hov,
                                      glyph='pause')

        # Cancel link
        lr = self._link_rect()
        self._hit_rects['cancel'] = lr
        hov_l = self._hovered_key == 'cancel'
        p.setPen(QColor(0xE8, 0x4C, 0x4C) if hov_l else _C_MUTED)
        p.setFont(_font(13, bold=hov_l))
        p.drawText(lr, Qt.AlignmentFlag.AlignCenter, 'Cancel')

    # ── Screen: OPTIONS ─────────────────────────────────────────────────────

    _OPTION_ROWS = [
        ('work_mins',       'work minutes',     'cycle'),
        ('break_mins',      'break minutes',    'cycle'),
        ('long_break_mins', 'long break',       'cycle'),
        ('rounds',          'rounds',           'cycle'),
        ('visual_flash',    'visual flash',     'toggle'),
        ('auto_start',      'auto start next',  'toggle'),
        ('block_apps',      'block apps',       'toggle'),
    ]

    @staticmethod
    def _cycle_opts(key: str) -> list[int]:
        return {
            'work_mins':       _WORK_OPTS,
            'break_mins':      _BREAK_OPTS,
            'long_break_mins': _LONG_BREAK_OPTS,
            'rounds':          _ROUNDS_OPTS,
        }.get(key, [])

    def _paint_options(self, p: QPainter) -> None:
        cr = self._content_rect()
        x  = cr.left() + 16
        y  = cr.top()  + 8
        row_h = 30
        label_w = 130
        ctrl_w  = 84

        p.setFont(_font(13))
        for key, label, kind in self._OPTION_ROWS:
            row_rect = QRect(x, y, _W - 32, row_h)
            p.setPen(_C_TEXT)
            p.drawText(QRect(x, y, label_w, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       label)
            ctrl_rect = QRect(_W - 16 - ctrl_w, y + 3, ctrl_w, row_h - 6)
            self._hit_rects[f'opt:{key}'] = ctrl_rect
            hov = self._hovered_key == f'opt:{key}'
            if kind == 'toggle':
                self._draw_toggle(p, ctrl_rect, bool(self._settings.get(key, False)), hov)
            else:
                self._draw_cycle(p, ctrl_rect, key, hov)
            y += row_h

        # Back link
        lr = self._link_rect()
        self._hit_rects['back'] = lr
        hov_l = self._hovered_key == 'back'
        p.setPen(_C_LINK if hov_l else _C_MUTED)
        p.setFont(_font(13, bold=hov_l))
        p.drawText(lr, Qt.AlignmentFlag.AlignCenter, '← Back')

    # ── Drawing primitives ──────────────────────────────────────────────────

    def _draw_circle_button(self, p: QPainter, rect: QRect, fill: QColor,
                            label: str, hov: bool, *, glyph: str = '') -> None:
        c = fill.lighter(112) if hov else fill
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(rect)
        # Subtle inset highlight
        p.setPen(QPen(c.lighter(125), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect.adjusted(3, 3, -3, -3))

        # Glyph or label
        p.setPen(QColor(255, 255, 255))
        if glyph == 'pause':
            # Two vertical bars
            bw = max(6, rect.width() // 9)
            bh = rect.height() // 3
            cxc, cyc = rect.center().x(), rect.center().y()
            gap = bw + 6
            p.setBrush(QColor(255, 255, 255))
            p.drawRoundedRect(cxc - gap // 2 - bw, cyc - bh // 2, bw, bh, 2, 2)
            p.drawRoundedRect(cxc + gap // 2,      cyc - bh // 2, bw, bh, 2, 2)
        elif glyph == 'play':
            # Triangle
            cxc, cyc = rect.center().x(), rect.center().y()
            size = rect.width() // 4
            from PyQt6.QtGui import QPolygon
            poly = QPolygon([
                QPoint(cxc - size // 2, cyc - size),
                QPoint(cxc - size // 2, cyc + size),
                QPoint(cxc + size,      cyc),
            ])
            p.setBrush(QColor(255, 255, 255))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(poly)
        else:
            p.setFont(_font(max(18, rect.width() // 6), bold=True))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_toggle(self, p: QPainter, rect: QRect, on: bool, hov: bool) -> None:
        # Reduce to a pill the right side of the row
        h = min(22, rect.height())
        pill = QRect(rect.right() - 44, rect.top() + (rect.height() - h) // 2, 44, h)
        on_color  = QColor(0x4F, 0xB3, 0x86)
        off_color = QColor(0xC8, 0xC8, 0xCE)
        track = (on_color if on else off_color).lighter(112 if hov else 100)
        p.setBrush(track)
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(pill, h // 2, h // 2)
        kx = pill.right() - h + 2 if on else pill.left() + 2
        p.setBrush(QColor(255, 255, 255))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(kx, pill.top() + 2, h - 4, h - 4)

    def _draw_cycle(self, p: QPainter, rect: QRect, key: str, hov: bool) -> None:
        bg = _C_CYCLE_BG.lighter(112) if hov else _C_CYCLE_BG
        p.setBrush(bg)
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(rect, 4, 4)
        p.setFont(_font(13, bold=True))
        p.setPen(_C_TEXT)
        p.drawText(QRect(rect.left() + 6, rect.top(), 12, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, '<')
        p.drawText(QRect(rect.right() - 18, rect.top(), 12, rect.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, '>')
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                   str(self._settings.get(key, 0)))

    def _cycle_advance(self, key: str) -> None:
        opts = self._cycle_opts(key)
        if not opts:
            return
        cur = int(self._settings.get(key, opts[0]))
        try:
            idx = opts.index(cur)
            nxt = opts[(idx + 1) % len(opts)]
        except ValueError:
            nxt = opts[0]
        self._settings[key] = nxt
        # If timer idle and we changed the current phase length, refresh remaining
        if not self._running:
            if key == 'work_mins' and self._phase == PHASE_WORK:
                self._remaining = nxt * 60; self._total = self._remaining
            elif key == 'break_mins' and self._phase == PHASE_BREAK:
                self._remaining = nxt * 60; self._total = self._remaining
            elif key == 'long_break_mins' and self._phase == PHASE_LONG:
                self._remaining = nxt * 60; self._total = self._remaining
        self._save()

    # ── Mouse ───────────────────────────────────────────────────────────────

    def _hit_at(self, pos: QPoint) -> str | None:
        for key, r in self._hit_rects.items():
            if r.contains(pos):
                return key
        return None

    def mouseMoveEvent(self, event) -> None:
        key = self._hit_at(event.pos())
        if key != self._hovered_key:
            self._hovered_key = key
            self.update()
        if self._drag_offset is not None:
            self.move(self.pos() + event.pos() - self._drag_offset)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        key = self._hit_at(event.pos())
        if key is None:
            self._drag_offset = event.pos()
            return

        if key == 'close':
            self.close_animated()
            return
        if key == 'big':
            if self._screen == 'start':
                self._start()
            elif self._screen == 'running':
                self._toggle_pause()
            return
        if key == 'options':
            self._screen = 'options'
            self._hovered_key = None
            self.update()
            return
        if key == 'back':
            self._screen = 'running' if self._running else 'start'
            self._hovered_key = None
            self.update()
            return
        if key == 'cancel':
            self._cancel()
            return
        if key.startswith('opt:'):
            opt_key = key[4:]
            for k, _l, kind in self._OPTION_ROWS:
                if k == opt_key:
                    if kind == 'toggle':
                        self._settings[k] = not self._settings.get(k, False)
                        self._save()
                    else:
                        self._cycle_advance(k)
                    self.update()
                    return

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._screen == 'options':
                self._screen = 'running' if self._running else 'start'
                self.update()
            else:
                self.close_animated()
        else:
            super().keyPressEvent(event)

    # ── Reverse-animation hook (called from overlay long-press cancel) ──────

    def force_cancel_from_overlay(self) -> None:
        """Called when the user long-presses on the flip-dot panel."""
        self._cancel()

    def force_pause_from_overlay(self) -> None:
        """Called when the user clicks (short-press) on the flip-dot panel."""
        if self._running:
            self._toggle_pause()

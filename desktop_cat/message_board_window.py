"""
Assignments Window for Desktop Cat — calendar + task list + weekly view.

Three tabs:
  * calendar  — month grid with task dots; click a day for a popover of tasks
  * tasks     — every assignment in a clean checklist grouped by due-date bucket
  * weekly    — the next 7 days at a glance, each day with its own task list

Tasks with a due date automatically flow into the Garden window as plantable
seeds; planting and check-off actions stay in sync with this window through
the `data_changed` signal handled by main.py.

The whole window honours the global light/dark theme — colors are mutated in
place when the user toggles the switch in the Settings window.
"""

import json
import os
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import (Qt, QPoint, QRect, QRectF, QDate,
                              pyqtProperty, pyqtSignal,
                              QPropertyAnimation, QParallelAnimationGroup,
                              QEasingCurve, QTimer)
from PyQt6.QtGui     import QPainter, QPixmap, QColor, QFont, QPen, QBrush

from desktop_cat.retro_ui import (configure_floating_panel, paint_window_chrome,
                                   close_button_rect, pin_button_rect,
                                   notify_pin_toggled, cancel_window_dimming,
                                   HEADER_H, RADIUS_PX)
from desktop_cat.theme import theme

_SAVE_PATH = os.path.join(os.path.dirname(__file__), 'message_board.json')

_OPEN_MS         = 220
_CLOSE_MS        = 160
_POP_SCALE_START = 0.80

# ── Layout ────────────────────────────────────────────────────────────────────
_W         = 380
_PAD       = 12
_TAB_H     = 34
_CONTENT_H = 470
_H         = HEADER_H + _TAB_H + 4 + _CONTENT_H + _PAD   # 30+34+4+470+12 = 550

# ── Palette — mutated in place by `_refresh_palette()` on theme change ──────
# These QColor objects are shared by reference with every paint call below;
# mutating them in place means the next repaint picks up the new theme without
# us having to re-import or rewire anything.
_C_BG            = QColor(0xF7, 0xF7, 0xFA, 252)
_C_BORDER        = QColor(0x00, 0x00, 0x00, 36)
_C_BORDER_IN     = QColor(0x00, 0x00, 0x00, 18)
_C_TITLE         = QColor(0x1F, 0x1F, 0x21)
_C_LABEL         = QColor(0x1F, 0x1F, 0x21)
_C_MUTED         = QColor(0x60, 0x60, 0x68)
_C_SEC_LABEL     = QColor(0x60, 0x60, 0x68)
# Accent colors stay constant in both modes for visual identity
_C_ACCENT_MINT   = QColor(0x4F, 0xB3, 0x86)
_C_ACCENT_BLUE   = QColor(0x46, 0x82, 0xE6)
_C_ACCENT_LAV    = QColor(0x9A, 0x7C, 0xD8)
_C_ACCENT_ROSE   = QColor(0xE8, 0x4C, 0x4C)
_C_ACCENT_AMBER  = QColor(0xC4, 0x8A, 0x30)
# Card / surface (these DO shift with theme)
_C_CARD          = QColor(0xFF, 0xFF, 0xFF)
_C_CARD_HOV      = QColor(0x46, 0x82, 0xE6, 22)
_C_INPUT_BG      = QColor(0xF0, 0xF5, 0xFF)
_C_INPUT_FG      = QColor(0x1F, 0x1F, 0x21)


def _refresh_palette() -> None:
    """Re-tune palette colors in place when the theme flips."""
    if theme.is_dark():
        _C_BG.setRgb(0x22, 0x23, 0x28, 252)
        _C_BORDER.setRgb(0xFF, 0xFF, 0xFF, 30)
        _C_BORDER_IN.setRgb(0xFF, 0xFF, 0xFF, 18)
        _C_TITLE.setRgb(0xF0, 0xF0, 0xF2)
        _C_LABEL.setRgb(0xF0, 0xF0, 0xF2)
        _C_MUTED.setRgb(0xA8, 0xA8, 0xB0)
        _C_SEC_LABEL.setRgb(0xA8, 0xA8, 0xB0)
        _C_CARD.setRgb(0x2D, 0x2E, 0x33)
        _C_CARD_HOV.setRgb(0x46, 0x82, 0xE6, 50)
        _C_INPUT_BG.setRgb(0x1A, 0x20, 0x2A)
        _C_INPUT_FG.setRgb(0xF0, 0xF0, 0xF2)
    else:
        _C_BG.setRgb(0xF7, 0xF7, 0xFA, 252)
        _C_BORDER.setRgb(0x00, 0x00, 0x00, 36)
        _C_BORDER_IN.setRgb(0x00, 0x00, 0x00, 18)
        _C_TITLE.setRgb(0x1F, 0x1F, 0x21)
        _C_LABEL.setRgb(0x1F, 0x1F, 0x21)
        _C_MUTED.setRgb(0x60, 0x60, 0x68)
        _C_SEC_LABEL.setRgb(0x60, 0x60, 0x68)
        _C_CARD.setRgb(0xFF, 0xFF, 0xFF)
        _C_CARD_HOV.setRgb(0x46, 0x82, 0xE6, 22)
        _C_INPUT_BG.setRgb(0xF0, 0xF5, 0xFF)
        _C_INPUT_FG.setRgb(0x1F, 0x1F, 0x21)


_refresh_palette()
theme.changed.connect(_refresh_palette)


_TABS = ['calendar', 'tasks', 'weekly']

_FLOWER_KINDS = [
    'rose', 'lavender', 'poppy', 'forget-me-not', 'peach lily', 'sunflower',
    'lily', 'crimson rose', 'teal bloom', 'coral bell', 'cornflower', 'daisy',
]

_MAX_TODO_LEN = 64
_MAX_TODOS    = 100

_DEFAULT_DATA: dict = {
    'todos':   [],
    'flowers': {k: 0 for k in _FLOWER_KINDS},
    'active_tab': 'calendar',
}

# Calendar geometry
_CAL_HDR_H  = 32
_CAL_DOW_H  = 22
_CAL_CELL_H = 60
_CAL_ROWS   = 6
_CAL_COLS   = 7

_DOW_LABELS  = ('S', 'M', 'T', 'W', 'T', 'F', 'S')
_MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December']
_MONTH_ABBR  = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
_DAY_NAMES_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                   'Friday', 'Saturday', 'Sunday']


# ── Helpers ──────────────────────────────────────────────────────────────────
def _parse_due(due_str):
    """Parse 'due' (ISO date OR datetime) → datetime, or None on failure."""
    if not due_str:
        return None
    try:
        return _datetime.fromisoformat(due_str)
    except (ValueError, TypeError):
        try:
            d = _date.fromisoformat(due_str)
            return _datetime.combine(d, _datetime.min.time())
        except (ValueError, TypeError):
            return None


def _due_qdate(due_str):
    dt = _parse_due(due_str)
    return None if dt is None else QDate(dt.year, dt.month, dt.day)


def _format_time(h: int, m: int) -> str:
    ampm = 'AM' if h < 12 else 'PM'
    h12  = h % 12 or 12
    return f'{h12}:{m:02d} {ampm}'


class MessageBoardWindow(QWidget):
    data_changed = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        configure_floating_panel(self)
        self.setFixedSize(_W, _H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._data: dict = self._load()
        self._anim_scale: float = 1.0
        self._main_anim: QParallelAnimationGroup | None = None
        self._closing: bool = False
        self._pinned: bool = False
        self._drag_offset: QPoint | None = None
        self._hovered_key: str | None = None
        self._scroll_y: int = 0
        self._cursor_blink: bool = True

        # Calendar state
        today = QDate.currentDate()
        self._view_year:  int = today.year()
        self._view_month: int = today.month()
        # Selected day shown in popover; None = no popover
        self._selected_day: QDate | None = None

        # Add-task draft state (used by calendar popover and tasks tab)
        self._draft_text:   str   = ''
        self._draft_date:   QDate = today.addDays(1)
        self._draft_hour:   int   = 17
        self._draft_minute: int   = 0
        self._adding:       bool  = False  # is the inline input visible?

        # blinking cursor
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_timer.start()

        # Repaint when the user flips light/dark
        theme.changed.connect(self.update)

    # ── Persistence ──────────────────────────────────────────────────────────
    def _load(self) -> dict:
        d = {k: (dict(v) if isinstance(v, dict) else
                 list(v) if isinstance(v, list) else v)
             for k, v in _DEFAULT_DATA.items()}
        try:
            with open(_SAVE_PATH) as f:
                raw = json.load(f)
            for k, v in raw.items():
                if k == 'flowers' and isinstance(v, dict):
                    for fk in _FLOWER_KINDS:
                        d['flowers'][fk] = int(v.get(fk, 0))
                elif k == 'todos' and isinstance(v, list):
                    d['todos'] = list(v)
                elif k == 'active_tab':
                    if v in ('todo', 'list'):
                        d['active_tab'] = 'tasks'
                    elif v in ('garden', 'flowers'):
                        # Old tabs no longer exist — fall back to weekly
                        d['active_tab'] = 'weekly'
                    elif v in _TABS:
                        d['active_tab'] = v
        except (OSError, ValueError):
            pass
        # Backfill schema
        for t in d.get('todos', []):
            t.setdefault('due',     None)
            t.setdefault('done',    False)
            t.setdefault('planted', False)
        for k in _FLOWER_KINDS:
            d['flowers'].setdefault(k, 0)
        if d.get('active_tab') not in _TABS:
            d['active_tab'] = 'calendar'
        return d

    def _save(self) -> None:
        try:
            snapshot = {
                'todos':      list(self._data.get('todos', [])),
                'flowers':    dict(self._data.get('flowers', {})),
                'active_tab': self._data.get('active_tab', 'calendar'),
            }
            with open(_SAVE_PATH, 'w') as f:
                json.dump(snapshot, f)
        except OSError:
            pass

    # Public API — bumped from main.py when a flower fully blooms
    def add_flower(self, kind: str) -> None:
        if kind in self._data['flowers']:
            self._data['flowers'][kind] += 1
            self.update()
            self._save()

    # ── Animatable scale ─────────────────────────────────────────────────────
    @pyqtProperty(float)
    def anim_scale(self) -> float:          # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                      # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    def _toggle_blink(self) -> None:
        self._cursor_blink = not self._cursor_blink
        if self._adding:
            self.update()

    # ── Show / close ─────────────────────────────────────────────────────────
    def show_animated(self, x: int, y: int) -> None:
        self._closing    = False
        self._anim_scale = _POP_SCALE_START
        self.setWindowOpacity(0.0)
        self.move(x, y)
        self.show()
        self.setFocus()

        scale_anim = QPropertyAnimation(self, b'anim_scale', self)
        scale_anim.setDuration(_OPEN_MS)
        scale_anim.setStartValue(_POP_SCALE_START)
        scale_anim.setEndValue(1.0)
        scale_anim.setEasingCurve(QEasingCurve.Type.OutBack)

        op_anim = QPropertyAnimation(self, b'windowOpacity', self)
        op_anim.setDuration(_OPEN_MS)
        op_anim.setStartValue(0.0)
        op_anim.setEndValue(1.0)
        op_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        if self._main_anim is not None:
            self._main_anim.stop()

        self._main_anim = QParallelAnimationGroup(self)
        self._main_anim.addAnimation(scale_anim)
        self._main_anim.addAnimation(op_anim)
        self._main_anim.start()

    def close_animated(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._save()

        # Cancel any ecosystem dim/restore animation to avoid windowOpacity
        # property conflicts.
        cancel_window_dimming(self)

        if self._main_anim is not None:
            self._main_anim.stop()
            self._main_anim = None

        # Store as instance vars to keep the sip wrapper alive for the full run.
        self._close_scale_anim = QPropertyAnimation(self, b'anim_scale', self)
        self._close_scale_anim.setDuration(_CLOSE_MS)
        self._close_scale_anim.setStartValue(self._anim_scale)
        self._close_scale_anim.setEndValue(_POP_SCALE_START)
        self._close_scale_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._close_scale_anim.start()

        self._close_op_anim = QPropertyAnimation(self, b'windowOpacity', self)
        self._close_op_anim.setDuration(_CLOSE_MS)
        self._close_op_anim.setStartValue(self.windowOpacity())
        self._close_op_anim.setEndValue(0.0)
        self._close_op_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._close_op_anim.finished.connect(self.close)
        self._close_op_anim.start()

        QTimer.singleShot(_CLOSE_MS + 100, self._force_close_if_needed)

    def _force_close_if_needed(self) -> None:
        if self._closing and self.isVisible():
            self.setWindowOpacity(0.0)
            self.close()

    def closeEvent(self, event) -> None:
        self._blink_timer.stop()
        self._save()
        super().closeEvent(event)

    def refresh(self) -> None:
        """Reload from disk and reset ephemeral UI state."""
        self._data         = self._load()
        self._scroll_y     = 0
        self._hovered_key  = None
        self._closing      = False
        self._selected_day = None
        self._adding       = False
        self._draft_text   = ''
        today = QDate.currentDate()
        self._view_year    = today.year()
        self._view_month   = today.month()
        self._draft_date   = today.addDays(1)
        self._draft_hour   = 17
        self._draft_minute = 0
        self._blink_timer.start()
        self.update()

    # ── Geometry ─────────────────────────────────────────────────────────────
    def _close_rect(self) -> QRect:
        return close_button_rect(QRect(0, 0, _W, _H))

    def _pin_rect(self) -> QRect:
        return pin_button_rect(QRect(0, 0, _W, _H))

    def _tab_rects(self) -> dict[str, QRect]:
        top   = HEADER_H
        left  = _PAD
        total = _W - 2 * _PAD
        tw    = total // len(_TABS)
        return {name: QRect(left + i * tw, top, tw - 2, _TAB_H)
                for i, name in enumerate(_TABS)}

    def _content_rect(self) -> QRect:
        top = HEADER_H + _TAB_H + 4
        return QRect(_PAD, top, _W - 2 * _PAD, _CONTENT_H - 4)

    # ── Render ───────────────────────────────────────────────────────────────
    def _render_buf(self) -> QPixmap:
        buf = QPixmap(_W, _H)
        buf.fill(Qt.GlobalColor.transparent)
        p = QPainter(buf)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        paint_window_chrome(p, QRect(0, 0, _W, _H), 'board',
                            close_rect=self._close_rect(),
                            close_hover=self._hovered_key == '__close__',
                            pin_rect=self._pin_rect(),
                            pin_active=self._pinned,
                            pin_hover=self._hovered_key == '__pin__')
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        self._draw_tabs(p)

        cr = self._content_rect()
        p.setClipRect(cr)
        tab = self._data.get('active_tab', 'calendar')
        if tab == 'calendar':
            self._draw_calendar_tab(p, cr)
        elif tab == 'tasks':
            self._draw_tasks_tab(p, cr)
        elif tab == 'weekly':
            self._draw_weekly_tab(p, cr)
        p.setClipping(False)

        # Popover overlay (only on calendar tab when a day is selected)
        if tab == 'calendar' and self._selected_day is not None:
            p.setClipRect(cr)
            self._draw_popover(p, cr)
            p.setClipping(False)

        p.end()
        return buf

    def _draw_tabs(self, p: QPainter) -> None:
        active = self._data.get('active_tab', 'calendar')
        rects  = self._tab_rects()

        band_y = HEADER_H + _TAB_H
        p.setPen(QPen(QColor(0x00, 0x00, 0x00, 18), 1))
        p.drawLine(0, band_y, _W, band_y)

        font = QFont('Segoe UI Variable', 1)
        for name, r in rects.items():
            is_active = name == active
            is_hov    = self._hovered_key == f'tab:{name}'
            rf = QRectF(r).adjusted(2, 4, -2, -4)
            if is_active:
                p.setBrush(QBrush(_C_ACCENT_BLUE))
                p.setPen(Qt.PenStyle.NoPen)
            elif is_hov:
                p.setBrush(QBrush(QColor(0x00, 0x00, 0x00, 14)))
                p.setPen(Qt.PenStyle.NoPen)
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rf, 9, 9)
            font.setWeight(QFont.Weight.DemiBold if is_active else QFont.Weight.Normal)
            font.setPixelSize(13)
            p.setFont(font)
            p.setPen(QColor(0xFF, 0xFF, 0xFF) if is_active else _C_MUTED)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, name)

    # ── Task data helpers ────────────────────────────────────────────────────
    def _todos_for_day(self, qd: QDate) -> list[tuple[int, dict]]:
        """[(idx, todo), ...] for tasks due on the given day, sorted by time."""
        out = []
        for i, t in enumerate(self._data.get('todos', [])):
            d = _due_qdate(t.get('due'))
            if d is not None and d == qd:
                out.append((i, t))

        def _key(item):
            dt = _parse_due(item[1].get('due'))
            return (dt.hour, dt.minute) if dt else (0, 0)
        out.sort(key=_key)
        return out

    def _count_for_day(self, qd: QDate) -> tuple[int, int]:
        op = dn = 0
        for _, t in self._todos_for_day(qd):
            if t.get('done'):
                dn += 1
            else:
                op += 1
        return (op, dn)

    # ── Calendar tab ─────────────────────────────────────────────────────────
    def _calendar_header_rect(self) -> QRect:
        cr = self._content_rect()
        return QRect(cr.left(), cr.top(), cr.width(), _CAL_HDR_H)

    def _cal_prev_rect(self) -> QRect:
        h = self._calendar_header_rect()
        return QRect(h.left() + 4, h.top() + 4, 28, h.height() - 8)

    def _cal_next_rect(self) -> QRect:
        h = self._calendar_header_rect()
        return QRect(h.left() + 36, h.top() + 4, 28, h.height() - 8)

    def _cal_today_rect(self) -> QRect:
        h = self._calendar_header_rect()
        return QRect(h.right() - 60, h.top() + 4, 56, h.height() - 8)

    def _cal_dow_rect(self) -> QRect:
        cr = self._content_rect()
        return QRect(cr.left(), cr.top() + _CAL_HDR_H, cr.width(), _CAL_DOW_H)

    def _cal_grid_rect(self) -> QRect:
        cr = self._content_rect()
        top = cr.top() + _CAL_HDR_H + _CAL_DOW_H
        return QRect(cr.left(), top, cr.width(), _CAL_ROWS * _CAL_CELL_H)

    def _cal_cell_w(self) -> float:
        return self._cal_grid_rect().width() / _CAL_COLS

    def _cal_cell_rect(self, row: int, col: int) -> QRect:
        g  = self._cal_grid_rect()
        cw = self._cal_cell_w()
        return QRect(int(g.left() + col * cw), g.top() + row * _CAL_CELL_H,
                     int(cw + 0.5), _CAL_CELL_H)

    def _cal_day_at(self, pos: QPoint) -> tuple[QDate, bool] | None:
        """Return (QDate, in_view_month) for the cell at pos, or None."""
        g = self._cal_grid_rect()
        if not g.contains(pos):
            return None
        cw  = self._cal_cell_w()
        col = int((pos.x() - g.left()) // cw)
        row = (pos.y() - g.top()) // _CAL_CELL_H
        if not (0 <= col < _CAL_COLS and 0 <= row < _CAL_ROWS):
            return None
        first     = QDate(self._view_year, self._view_month, 1)
        first_col = first.dayOfWeek() % 7   # Sun=0
        idx       = row * _CAL_COLS + col
        offset    = idx - first_col
        return (first.addDays(offset),
                0 <= offset < first.daysInMonth())

    def _draw_calendar_tab(self, p: QPainter, cr: QRect) -> None:
        font = QFont('Segoe UI Variable', 1)

        # ── Chevrons + month title + today button ───────────────────────────
        for rect, dx, key in ((self._cal_prev_rect(), -1, 'cal_prev'),
                              (self._cal_next_rect(),  1, 'cal_next')):
            hov = self._hovered_key == key
            if hov:
                p.setBrush(QBrush(QColor(0x00, 0x00, 0x00, 16)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(rect), 6, 6)
            p.setPen(QPen(_C_ACCENT_BLUE, 2))
            cx = rect.center().x(); cy = rect.center().y()
            if dx < 0:
                p.drawLine(cx + 3, cy - 5, cx - 3, cy)
                p.drawLine(cx - 3, cy, cx + 3, cy + 5)
            else:
                p.drawLine(cx - 3, cy - 5, cx + 3, cy)
                p.drawLine(cx + 3, cy, cx - 3, cy + 5)

        font.setPixelSize(15); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_TITLE)
        title_r = QRect(cr.left() + 70, cr.top(),
                        cr.width() - 140, _CAL_HDR_H)
        p.drawText(title_r, Qt.AlignmentFlag.AlignCenter,
                   f"{_MONTH_NAMES[self._view_month - 1]} {self._view_year}")

        tr     = self._cal_today_rect()
        hov_t  = self._hovered_key == 'cal_today'
        p.setBrush(QBrush(_C_CARD_HOV if hov_t else QColor(0, 0, 0, 0)))
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.drawRoundedRect(tr, 7, 7)
        font.setPixelSize(11); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(tr, Qt.AlignmentFlag.AlignCenter, 'today')

        # ── DOW strip ───────────────────────────────────────────────────────
        font.setPixelSize(11); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_MUTED)
        dow = self._cal_dow_rect()
        cw  = self._cal_cell_w()
        for i, lbl in enumerate(_DOW_LABELS):
            cell = QRect(int(dow.left() + i * cw), dow.top(),
                         int(cw + 0.5), dow.height())
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, lbl)

        # ── Month grid cells ───────────────────────────────────────────────
        first     = QDate(self._view_year, self._view_month, 1)
        first_col = first.dayOfWeek() % 7
        days_in   = first.daysInMonth()
        today     = QDate.currentDate()

        for r in range(_CAL_ROWS):
            for c in range(_CAL_COLS):
                idx      = r * _CAL_COLS + c
                offset   = idx - first_col
                qd       = first.addDays(offset)
                in_month = 0 <= offset < days_in
                cell     = self._cal_cell_rect(r, c)
                self._draw_calendar_cell(p, font, cell, qd, in_month,
                                         qd == today)

    def _draw_calendar_cell(self, p: QPainter, font: QFont, cell: QRect,
                            qd: QDate, in_month: bool, is_today: bool) -> None:
        is_sel = (self._selected_day == qd) if self._selected_day else False
        hov    = self._hovered_key == f'day:{qd.toString(Qt.DateFormat.ISODate)}'

        # Background highlight
        cell_inner = QRectF(cell).adjusted(2, 2, -2, -2)
        if is_today and in_month:
            p.setBrush(QBrush(_C_INPUT_BG))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(cell_inner, 6, 6)
        if hov and in_month:
            p.setBrush(QBrush(_C_CARD_HOV))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(cell_inner, 6, 6)
        if is_sel and in_month:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_C_ACCENT_BLUE, 2))
            p.drawRoundedRect(cell_inner, 6, 6)

        # Day number
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold if (is_today or is_sel)
                       else QFont.Weight.Normal)
        p.setFont(font)
        if not in_month:
            p.setPen(QColor(0xC0, 0xC0, 0xC8))
        elif is_today:
            p.setPen(_C_ACCENT_BLUE)
        else:
            p.setPen(_C_LABEL)
        n_rect = QRect(cell.left() + 6, cell.top() + 4,
                       cell.width() - 12, 16)
        p.drawText(n_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   str(qd.day()))

        # Task indicator dots
        if not in_month:
            return
        items = self._todos_for_day(qd)
        if not items:
            return

        max_show = 3
        dot_y    = cell.top() + cell.height() - 14
        d_size   = 5
        gap      = 2
        total    = len(items)
        shown    = min(total, max_show)
        block_w  = shown * d_size + (shown - 1) * gap
        if total > max_show:
            block_w += 14
        x0 = cell.left() + (cell.width() - block_w) // 2

        p.setPen(Qt.PenStyle.NoPen)
        any_overdue = False
        now_dt = _datetime.now()
        for i, (_, t) in enumerate(items[:max_show]):
            done    = bool(t.get('done'))
            dt      = _parse_due(t.get('due'))
            overdue = (dt is not None and not done and dt < now_dt)
            any_overdue = any_overdue or overdue
            if done:
                col = _C_ACCENT_MINT
            elif overdue:
                col = _C_ACCENT_ROSE
            else:
                col = _C_ACCENT_BLUE
            p.setBrush(QBrush(col))
            p.drawEllipse(x0 + i * (d_size + gap), dot_y, d_size, d_size)

        if total > max_show:
            font.setPixelSize(9); font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(_C_MUTED)
            p.drawText(QRect(x0 + shown * (d_size + gap), dot_y - 3,
                             18, 12),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f'+{total - max_show}')

    # ── Popover ──────────────────────────────────────────────────────────────
    def _popover_rect(self) -> QRect:
        cr = self._content_rect()
        mh = 12
        mv = 26
        return QRect(cr.left() + mh, cr.top() + mv,
                     cr.width() - 2 * mh, cr.height() - 2 * mv)

    def _popover_close_rect(self) -> QRect:
        pr = self._popover_rect()
        return QRect(pr.right() - 30, pr.top() + 8, 22, 22)

    def _popover_add_rect(self) -> QRect:
        pr = self._popover_rect()
        return QRect(pr.left() + 12, pr.bottom() - 38, pr.width() - 24, 30)

    def _popover_input_rect(self) -> QRect:
        pr = self._popover_rect()
        return QRect(pr.left() + 12, pr.bottom() - 84, pr.width() - 24, 36)

    def _popover_time_row_rect(self) -> QRect:
        pr = self._popover_rect()
        return QRect(pr.left() + 12, pr.bottom() - 42, pr.width() - 24, 30)

    _ARROW_W = 28

    def _pop_time_prev_rect(self) -> QRect:
        r = self._popover_time_row_rect()
        return QRect(r.left(), r.top(), self._ARROW_W, r.height())

    def _pop_time_next_rect(self) -> QRect:
        r = self._popover_time_row_rect()
        return QRect(r.right() - self._ARROW_W, r.top(),
                     self._ARROW_W, r.height())

    def _pop_save_rect(self) -> QRect:
        """Save button on the right side of the popover input row."""
        ir = self._popover_input_rect()
        return QRect(ir.right() - 32, ir.top() + 4, 28, ir.height() - 8)

    def _pop_cancel_rect(self) -> QRect:
        """Cancel ✕ on the left side of the input row."""
        ir = self._popover_input_rect()
        return QRect(ir.left() + 4, ir.top() + 4, 28, ir.height() - 8)

    def _popover_task_rects(self) -> list[tuple[int, QRect, QRect, QRect]]:
        """Return [(todo_idx, row, check, delete), ...] for the popover."""
        if self._selected_day is None:
            return []
        pr      = self._popover_rect()
        items   = self._todos_for_day(self._selected_day)
        out     = []
        list_top = pr.top() + 50
        list_bot = pr.bottom() - (96 if self._adding else 48)
        row_h    = 36
        for i, (idx, _t) in enumerate(items):
            y = list_top + i * row_h - self._scroll_y
            if y > list_bot or y + row_h < list_top:
                continue
            row  = QRect(pr.left() + 12, y, pr.width() - 24, row_h - 4)
            chk  = QRect(row.left() + 8, row.center().y() - 9, 18, 18)
            delr = QRect(row.right() - 26, row.center().y() - 9, 18, 18)
            out.append((idx, row, chk, delr))
        return out

    def _draw_popover(self, p: QPainter, cr: QRect) -> None:
        # Backdrop dim
        p.setBrush(QBrush(QColor(0xF7, 0xF7, 0xFA, 200)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(cr)

        pr = self._popover_rect()
        # Panel card
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QBrush(QColor(0xFF, 0xFF, 0xFF)))
        p.setPen(QPen(QColor(0x00, 0x00, 0x00, 60), 1))
        p.drawRoundedRect(QRectF(pr).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

        font = QFont('Segoe UI Variable', 1)
        qd   = self._selected_day
        dow_idx = (qd.dayOfWeek() - 1) % 7

        # Header: full date + close
        font.setPixelSize(14); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_TITLE)
        p.drawText(QRect(pr.left() + 14, pr.top() + 6, pr.width() - 50, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f'{_DAY_NAMES_LONG[dow_idx]}, '
                   f'{_MONTH_ABBR[qd.month()-1]} {qd.day()}')

        op, dn = self._count_for_day(qd)
        font.setPixelSize(11); font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(_C_MUTED)
        sub = (f'{op} open · {dn} done' if (op + dn) else 'no tasks yet')
        p.drawText(QRect(pr.left() + 14, pr.top() + 26, pr.width() - 50, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)

        # Close button
        cls = self._popover_close_rect()
        hov_cls = self._hovered_key == 'pop_close'
        p.setBrush(QBrush(_C_ACCENT_ROSE if hov_cls
                          else QColor(0x00, 0x00, 0x00, 14)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(cls), 6, 6)
        p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF) if hov_cls else _C_MUTED, 1.5,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx_d = cls.center().x(); cy_d = cls.center().y(); d = 4
        p.drawLine(cx_d - d, cy_d - d, cx_d + d, cy_d + d)
        p.drawLine(cx_d + d, cy_d - d, cx_d - d, cy_d + d)

        # Divider
        p.setPen(QPen(_C_BORDER_IN, 1))
        p.drawLine(pr.left() + 12, pr.top() + 48, pr.right() - 12, pr.top() + 48)

        # Tasks list
        items = self._todos_for_day(qd)
        if not items and not self._adding:
            font.setPixelSize(13); font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(_C_MUTED)
            p.drawText(QRect(pr.left(), pr.top() + 80, pr.width(), 30),
                       Qt.AlignmentFlag.AlignCenter,
                       'nothing planned for this day')

        for idx, row, chk, delr in self._popover_task_rects():
            t = self._data['todos'][idx]
            self._draw_task_row(p, font, row, chk, delr, t, idx)

        # Bottom: input row OR add button
        if self._adding:
            self._draw_popover_input(p, font)
        else:
            self._draw_add_button(p, font, self._popover_add_rect(),
                                  '+  add task for this day', 'pop_add')

    def _draw_popover_input(self, p: QPainter, font: QFont) -> None:
        ir = self._popover_input_rect()

        # Cancel button on the left
        cr_b = self._pop_cancel_rect()
        hov_c = self._hovered_key == 'pop_cancel'
        p.setBrush(QBrush(QColor(0x00, 0x00, 0x00, 14) if not hov_c
                          else _C_ACCENT_ROSE))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cr_b)
        p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF) if hov_c else _C_MUTED, 1.5,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        ccx = cr_b.center().x(); ccy = cr_b.center().y(); d = 4
        p.drawLine(ccx - d, ccy - d, ccx + d, ccy + d)
        p.drawLine(ccx + d, ccy - d, ccx - d, ccy + d)

        # Save (✓) button on the right
        sv  = self._pop_save_rect()
        hov_s = self._hovered_key == 'pop_save'
        p.setBrush(QBrush(_C_ACCENT_MINT if hov_s
                          else _C_ACCENT_MINT.lighter(130)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(sv)
        p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 2,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        scx = sv.center().x(); scy = sv.center().y()
        p.drawLine(scx - 4, scy, scx - 1, scy + 4)
        p.drawLine(scx - 1, scy + 4, scx + 5, scy - 4)

        # Text input field
        text_r = QRect(ir.left() + 36, ir.top(),
                       ir.width() - 72, ir.height())
        p.setBrush(QBrush(_C_INPUT_BG))
        p.setPen(QPen(_C_ACCENT_BLUE, 2))
        p.drawRoundedRect(QRectF(text_r).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        font.setPixelSize(13); font.setBold(False)
        p.setFont(font)
        txt = self._draft_text + ('|' if self._cursor_blink else '')
        p.setPen(_C_INPUT_FG if self._draft_text else _C_MUTED)
        p.drawText(QRect(text_r.left() + 10, text_r.top(),
                         text_r.width() - 14, text_r.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   txt if self._draft_text else 'task description…')

        # Time picker row
        tr_r = self._popover_time_row_rect()
        time_str = _format_time(self._draft_hour, self._draft_minute)
        self._draw_dt_row(p, font, tr_r, time_str,
                          'pop_time_prev', 'pop_time_next')

    # ── Tasks tab (all tasks) ────────────────────────────────────────────────
    _TASKS_HDR_H    = 30
    _TASKS_DRAFT_H  = 130   # text input + date row + time row + save bar
    _TASKS_ROW_H    = 50
    _TASKS_GROUP_H  = 26    # section label height

    def _tasks_add_btn_rect(self) -> QRect:
        cr = self._content_rect()
        return QRect(cr.right() - 30, cr.top() + 2, 26, 26)

    def _tasks_input_rect(self) -> QRect:
        cr = self._content_rect()
        return QRect(cr.left(), cr.top() + self._TASKS_HDR_H,
                     cr.width(), 36)

    def _tasks_date_row_rect(self) -> QRect:
        cr = self._content_rect()
        return QRect(cr.left(),
                     cr.top() + self._TASKS_HDR_H + 36 + 6,
                     cr.width(), 30)

    def _tasks_time_row_rect(self) -> QRect:
        r = self._tasks_date_row_rect()
        return QRect(r.left(), r.bottom() + 4, r.width(), 30)

    def _tasks_date_prev_rect(self) -> QRect:
        r = self._tasks_date_row_rect()
        return QRect(r.left(), r.top(), self._ARROW_W, r.height())

    def _tasks_date_next_rect(self) -> QRect:
        r = self._tasks_date_row_rect()
        return QRect(r.right() - self._ARROW_W, r.top(),
                     self._ARROW_W, r.height())

    def _tasks_time_prev_rect(self) -> QRect:
        r = self._tasks_time_row_rect()
        return QRect(r.left(), r.top(), self._ARROW_W, r.height())

    def _tasks_time_next_rect(self) -> QRect:
        r = self._tasks_time_row_rect()
        return QRect(r.right() - self._ARROW_W, r.top(),
                     self._ARROW_W, r.height())

    def _tasks_save_rect(self) -> QRect:
        r = self._tasks_time_row_rect()
        return QRect(r.right() - 60, r.bottom() + 6, 56, 22)

    def _tasks_cancel_rect(self) -> QRect:
        r = self._tasks_time_row_rect()
        return QRect(r.right() - 124, r.bottom() + 6, 60, 22)

    def _tasks_list_top(self) -> int:
        """Y where the grouped list begins."""
        cr = self._content_rect()
        if self._adding:
            return cr.top() + self._TASKS_HDR_H + self._TASKS_DRAFT_H
        return cr.top() + self._TASKS_HDR_H + 4

    def _grouped_tasks(self) -> list[tuple[str, list[tuple[int, dict]]]]:
        """Group todos into time buckets: overdue, today, tomorrow,
        this week, later, no date, completed.

        Returns ordered (label, [(idx, todo), ...]) tuples; empty groups omitted.
        """
        today = _date.today()
        groups: dict[str, list[tuple[int, dict]]] = {
            'overdue':   [],
            'today':     [],
            'tomorrow':  [],
            'this week': [],
            'later':     [],
            'no date':   [],
            'completed': [],
        }
        for i, t in enumerate(self._data.get('todos', [])):
            if t.get('done'):
                groups['completed'].append((i, t))
                continue
            d = _due_qdate(t.get('due'))
            if d is None:
                groups['no date'].append((i, t))
                continue
            d_py = _date(d.year(), d.month(), d.day())
            diff = (d_py - today).days
            if diff < 0:
                groups['overdue'].append((i, t))
            elif diff == 0:
                groups['today'].append((i, t))
            elif diff == 1:
                groups['tomorrow'].append((i, t))
            elif diff <= 6:
                groups['this week'].append((i, t))
            else:
                groups['later'].append((i, t))

        # Sort each non-completed group by due datetime
        def _sort_key(item):
            dt = _parse_due(item[1].get('due'))
            return (dt or _datetime.max, item[0])
        for k, lst in groups.items():
            if k != 'completed':
                lst.sort(key=_sort_key)
            else:
                lst.sort(key=lambda it: it[0])

        return [(k, v) for k, v in groups.items() if v]

    def _task_list_rects(self) -> list[tuple[int, QRect, QRect, QRect]]:
        """Iterate the grouped list with section headers, returning per-row rects.

        Section headers are interleaved by drawing logic; here we only return
        actual task row rects so click targets line up.
        """
        cr = self._content_rect()
        out = []
        y = self._tasks_list_top() - self._scroll_y
        for label, items in self._grouped_tasks():
            y += self._TASKS_GROUP_H   # section header eats space
            for idx, _t in items:
                row  = QRect(cr.left(), y, cr.width(), self._TASKS_ROW_H - 4)
                chk  = QRect(row.left() + 8, row.center().y() - 11, 22, 22)
                delr = QRect(row.right() - 30, row.center().y() - 11, 22, 22)
                out.append((idx, row, chk, delr))
                y += self._TASKS_ROW_H
            y += 4   # gap between groups
        return out

    def _draw_tasks_tab(self, p: QPainter, cr: QRect) -> None:
        font = QFont('Segoe UI Variable', 1)

        todos = self._data.get('todos', [])
        done  = sum(1 for t in todos if t.get('done'))
        total = len(todos)

        # Header
        font.setPixelSize(11); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_SEC_LABEL)
        p.drawText(QRect(cr.left() + 2, cr.top(),
                         cr.width() - 80, self._TASKS_HDR_H - 4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   'ALL TASKS')
        font.setPixelSize(11); font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(QRect(cr.left() + 2, cr.top(),
                         cr.width() - 40, self._TASKS_HDR_H - 4),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f'{done}/{total}')

        # Add button (top right)
        ar  = self._tasks_add_btn_rect()
        hov = self._hovered_key == 'tasks_add'
        p.setBrush(QBrush(_C_ACCENT_MINT if hov else _C_ACCENT_MINT.lighter(130)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(ar)
        p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 2,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx_a = ar.center().x(); cy_a = ar.center().y()
        if self._adding:
            # ✕ when adding-mode is on (close the form)
            d = 4
            p.drawLine(cx_a - d, cy_a - d, cx_a + d, cy_a + d)
            p.drawLine(cx_a + d, cy_a - d, cx_a - d, cy_a + d)
        else:
            d = 5
            p.drawLine(cx_a - d, cy_a, cx_a + d, cy_a)
            p.drawLine(cx_a, cy_a - d, cx_a, cy_a + d)

        # Inline draft input (only when adding)
        if self._adding:
            self._draw_tasks_input(p, font)

        # Grouped task list
        if not todos:
            font.setPixelSize(14); font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(_C_MUTED)
            empty_y = self._tasks_list_top() + 16
            p.drawText(QRect(cr.left(), empty_y, cr.width(), 30),
                       Qt.AlignmentFlag.AlignCenter,
                       'nothing on your plate — tap + to add')
            return

        # Draw groups
        y = self._tasks_list_top() - self._scroll_y
        for label, items in self._grouped_tasks():
            # Section header
            sec_r = QRect(cr.left() + 2, y, cr.width() - 4,
                          self._TASKS_GROUP_H)
            if sec_r.bottom() >= cr.top() and sec_r.top() <= cr.bottom():
                # Pill colour for the section
                pill_col = self._section_color(label)
                font.setPixelSize(10); font.setWeight(QFont.Weight.DemiBold)
                p.setFont(font)
                fm = p.fontMetrics()
                lbl_w = fm.horizontalAdvance(label.upper()) + 18
                pill = QRect(sec_r.left(), sec_r.top() + 6, lbl_w, 16)
                p.setBrush(QBrush(pill_col.lighter(170)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(pill, 8, 8)
                p.setPen(pill_col.darker(125))
                p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label.upper())
                # count
                font.setPixelSize(10); font.setWeight(QFont.Weight.Normal)
                p.setFont(font)
                p.setPen(_C_MUTED)
                p.drawText(QRect(pill.right() + 8, sec_r.top() + 4,
                                 100, 18),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           f'{len(items)}')
            y += self._TASKS_GROUP_H

            for idx, _t in items:
                row  = QRect(cr.left(), y, cr.width(),
                             self._TASKS_ROW_H - 4)
                chk  = QRect(row.left() + 8, row.center().y() - 11, 22, 22)
                delr = QRect(row.right() - 30, row.center().y() - 11, 22, 22)
                if row.bottom() >= cr.top() and row.top() <= cr.bottom():
                    self._draw_task_row(p, font, row, chk, delr,
                                        self._data['todos'][idx], idx)
                y += self._TASKS_ROW_H
            y += 4   # gap

    def _section_color(self, label: str) -> QColor:
        """Section pill colour by bucket name."""
        return {
            'overdue':   _C_ACCENT_ROSE,
            'today':     _C_ACCENT_AMBER,
            'tomorrow':  _C_ACCENT_BLUE,
            'this week': _C_ACCENT_LAV,
            'later':     _C_ACCENT_BLUE,
            'no date':   _C_MUTED,
            'completed': _C_ACCENT_MINT,
        }.get(label, _C_MUTED)

    def _draw_tasks_input(self, p: QPainter, font: QFont) -> None:
        # Text input box
        ir = self._tasks_input_rect()
        p.setBrush(QBrush(_C_INPUT_BG))
        p.setPen(QPen(_C_ACCENT_BLUE, 2))
        p.drawRoundedRect(QRectF(ir).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        font.setPixelSize(14); font.setBold(False)
        p.setFont(font)
        txt = self._draft_text + ('|' if (self._cursor_blink and self._adding) else '')
        p.setPen(_C_INPUT_FG if self._draft_text else _C_MUTED)
        p.drawText(QRect(ir.left() + 12, ir.top(),
                         ir.width() - 16, ir.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   txt if self._draft_text else 'what do you need to do?')

        # Date / time picker rows
        self._draw_dt_row(p, font, self._tasks_date_row_rect(),
                          self._draft_date.toString('ddd, MMM d'),
                          'tasks_date_prev', 'tasks_date_next')
        self._draw_dt_row(p, font, self._tasks_time_row_rect(),
                          _format_time(self._draft_hour, self._draft_minute),
                          'tasks_time_prev', 'tasks_time_next')

        # Save / cancel buttons
        save_r = self._tasks_save_rect()
        cnl_r  = self._tasks_cancel_rect()
        hov_s  = self._hovered_key == 'tasks_save'
        hov_c  = self._hovered_key == 'tasks_cancel'

        # cancel
        p.setBrush(QBrush(_C_CARD_HOV if hov_c else QColor(0, 0, 0, 0)))
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.drawRoundedRect(cnl_r, 7, 7)
        font.setPixelSize(11); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(cnl_r, Qt.AlignmentFlag.AlignCenter, 'cancel')

        # save
        p.setBrush(QBrush(_C_ACCENT_BLUE if hov_s else _C_ACCENT_BLUE.lighter(115)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(save_r, 7, 7)
        font.setPixelSize(11); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(0xFF, 0xFF, 0xFF))
        p.drawText(save_r, Qt.AlignmentFlag.AlignCenter, 'save')

    # ── Task row drawing (shared by popover + tasks tab) ─────────────────────
    def _draw_task_row(self, p: QPainter, font: QFont,
                       row: QRect, chk: QRect, delr: QRect,
                       t: dict, idx: int) -> None:
        hov = self._hovered_key == f'task:{idx}'
        # Card
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QBrush(_C_CARD_HOV if hov else _C_CARD))
        p.setPen(QPen(_C_BORDER_IN, 1))
        p.drawRoundedRect(QRectF(row).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)

        # Checkbox circle
        hov_chk = self._hovered_key == f'task_chk:{idx}'
        if t.get('done'):
            p.setBrush(QBrush(_C_ACCENT_MINT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(chk)
            p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 2,
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                           Qt.PenJoinStyle.RoundJoin))
            p.drawLine(chk.left() + 5, chk.center().y(),
                       chk.center().x() - 1, chk.bottom() - 5)
            p.drawLine(chk.center().x() - 1, chk.bottom() - 5,
                       chk.right() - 4, chk.top() + 5)
        else:
            ring = _C_ACCENT_MINT.darker(110) if hov_chk else QColor(0xC0, 0xC0, 0xC8)
            p.setBrush(QBrush(QColor(0xFF, 0xFF, 0xFF, 220)))
            p.setPen(QPen(ring, 2))
            p.drawEllipse(chk)

        # Text
        text_r = QRect(row.left() + 38, row.top() + 6,
                       row.width() - 78, row.height() - 12)
        font.setPixelSize(13); font.setWeight(QFont.Weight.Normal if t.get('done')
                                              else QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_MUTED if t.get('done') else _C_INPUT_FG)
        p.drawText(text_r,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   t.get('text', ''))
        if t.get('done'):
            ty = text_r.center().y()
            tw = min(len(t.get('text', '')) * 8, text_r.width() - 4)
            p.setPen(QPen(_C_MUTED, 1))
            p.drawLine(text_r.left(), ty, text_r.left() + tw, ty)

        # Due-date / time pill below text
        due = t.get('due')
        if due:
            self._draw_due_pill(p, font, row, t)

        # Planted indicator (small leaf icon if planted)
        if t.get('planted') and not t.get('done'):
            p.setBrush(QBrush(_C_ACCENT_MINT.lighter(120)))
            p.setPen(Qt.PenStyle.NoPen)
            ind_r = QRect(row.right() - 56, row.top() + 6, 18, 18)
            p.drawEllipse(ind_r)
            font.setPixelSize(10); font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(0xFF, 0xFF, 0xFF))
            p.drawText(ind_r, Qt.AlignmentFlag.AlignCenter, '✦')

        # Delete button
        hov_del = self._hovered_key == f'task_del:{idx}'
        p.setBrush(QBrush(_C_ACCENT_ROSE if hov_del
                          else QColor(0x00, 0x00, 0x00, 12)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(delr), 6, 6)
        cx_d = delr.center().x(); cy_d = delr.center().y()
        p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF) if hov_del else _C_MUTED, 1.5,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(cx_d - 4, cy_d - 4, cx_d + 4, cy_d + 4)
        p.drawLine(cx_d + 4, cy_d - 4, cx_d - 4, cy_d + 4)

    def _draw_due_pill(self, p: QPainter, font: QFont,
                       row: QRect, t: dict) -> None:
        dt = _parse_due(t.get('due'))
        if dt is None:
            return
        now    = _datetime.now()
        diff_s = (dt - now).total_seconds()
        diff_d = (dt.date() - _date.today()).days
        time_s = _format_time(dt.hour, dt.minute).lower().replace(' ', '')

        if t.get('done'):
            label = 'done'
            col   = _C_ACCENT_MINT
        elif diff_s < 0:
            if abs(diff_s) < 3600:
                label = 'overdue'
            else:
                label = f'overdue {abs(diff_d) or 1}d'
            col = _C_ACCENT_ROSE
        elif diff_d == 0:
            label = f'today {time_s}'
            col   = _C_ACCENT_AMBER
        elif diff_d == 1:
            label = f'tomorrow {time_s}'
            col   = _C_ACCENT_BLUE
        elif diff_d <= 6:
            label = f'in {diff_d}d'
            col   = _C_ACCENT_LAV
        else:
            label = f'{_MONTH_ABBR[dt.month - 1]} {dt.day}'
            col   = _C_ACCENT_BLUE

        font.setPixelSize(10); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        fm = p.fontMetrics()
        bw = fm.horizontalAdvance(label) + 14
        pill = QRect(row.right() - 36 - bw, row.top() + 6, bw, 16)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QBrush(col.lighter(170)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(pill, 8, 8)
        p.setPen(col.darker(125))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)

    # ── Generic ‹ value › row ────────────────────────────────────────────────
    def _draw_dt_row(self, p: QPainter, font: QFont, row: QRect,
                     value_text: str, prev_key: str, next_key: str) -> None:
        AW       = self._ARROW_W
        hov_prev = self._hovered_key == prev_key
        hov_next = self._hovered_key == next_key

        p.setBrush(QBrush(_C_INPUT_BG))
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(QRectF(row).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        # ‹
        lrect = QRect(row.left(), row.top(), AW, row.height())
        if hov_prev:
            p.setBrush(QBrush(QColor(0x00, 0x00, 0x00, 14)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(lrect).adjusted(1, 1, -1, -1), 7, 7)
        p.setPen(QPen(_C_ACCENT_BLUE, 2))
        cx = lrect.center().x(); cy = lrect.center().y()
        p.drawLine(cx + 4, cy - 5, cx - 2, cy)
        p.drawLine(cx - 2, cy, cx + 4, cy + 5)

        # ›
        rrect = QRect(row.right() - AW, row.top(), AW, row.height())
        if hov_next:
            p.setBrush(QBrush(QColor(0x00, 0x00, 0x00, 14)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(rrect).adjusted(1, 1, -1, -1), 7, 7)
        p.setPen(QPen(_C_ACCENT_BLUE, 2))
        cx = rrect.center().x(); cy = rrect.center().y()
        p.drawLine(cx - 4, cy - 5, cx + 2, cy)
        p.drawLine(cx + 2, cy, cx - 4, cy + 5)

        # centre label
        font.setPixelSize(13); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_TITLE)
        cr_lbl = QRect(row.left() + AW, row.top(),
                       row.width() - 2 * AW, row.height())
        p.drawText(cr_lbl, Qt.AlignmentFlag.AlignCenter, value_text)

    def _draw_add_button(self, p: QPainter, font: QFont,
                         rect: QRect, label: str, key: str) -> None:
        hov = self._hovered_key == key
        p.setBrush(QBrush(_C_ACCENT_BLUE.lighter(180) if hov
                          else QColor(0x46, 0x82, 0xE6, 16)))
        p.setPen(QPen(_C_ACCENT_BLUE, 1, Qt.PenStyle.DashLine))
        p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        font.setPixelSize(13); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_ACCENT_BLUE)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    # ── Weekly tab — next 7 days at a glance ────────────────────────────────
    _WK_HDR_H        = 30      # tab section header
    _WK_DAY_HDR_H    = 28      # day section header (date + count pill)
    _WK_TASK_H       = 32      # height of one task row
    _WK_EMPTY_H      = 22      # height of "no tasks" placeholder
    _WK_GAP          = 6       # gap between days

    def _weekly_days(self) -> list[QDate]:
        """Return [today, today+1, …, today+6]."""
        t = QDate.currentDate()
        return [t.addDays(i) for i in range(7)]

    def _draw_weekly_tab(self, p: QPainter, cr: QRect) -> None:
        font = QFont('Segoe UI Variable', 1)

        # Tab header row
        font.setPixelSize(11); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_SEC_LABEL)
        p.drawText(QRect(cr.left() + 2, cr.top(),
                         cr.width() - 80, self._WK_HDR_H - 4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   'NEXT 7 DAYS')

        # Total count for the week (open / done)
        days        = self._weekly_days()
        wk_open     = 0
        wk_done     = 0
        for d in days:
            o, dn = self._count_for_day(d)
            wk_open += o
            wk_done += dn
        font.setPixelSize(11); font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(QRect(cr.left() + 2, cr.top(),
                         cr.width() - 4, self._WK_HDR_H - 4),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f'{wk_open} open · {wk_done} done')

        # ── Day sections ────────────────────────────────────────────────────
        y = cr.top() + self._WK_HDR_H - self._scroll_y
        today = QDate.currentDate()
        for i, qd in enumerate(days):
            dow_idx  = (qd.dayOfWeek() - 1) % 7
            is_today = (qd == today)
            is_tomr  = (qd == today.addDays(1))
            items    = self._todos_for_day(qd)

            # Section title text
            if is_today:
                title = f'TODAY · {_DAY_NAMES_LONG[dow_idx][:3]}, {_MONTH_ABBR[qd.month()-1]} {qd.day()}'
                accent = _C_ACCENT_AMBER
            elif is_tomr:
                title = f'TOMORROW · {_DAY_NAMES_LONG[dow_idx][:3]}, {_MONTH_ABBR[qd.month()-1]} {qd.day()}'
                accent = _C_ACCENT_BLUE
            else:
                title = f'{_DAY_NAMES_LONG[dow_idx].upper()} · {_MONTH_ABBR[qd.month()-1]} {qd.day()}'
                accent = _C_ACCENT_LAV

            # Section header pill — coloured strip on the left
            hdr_r = QRect(cr.left(), y, cr.width(), self._WK_DAY_HDR_H)
            if hdr_r.bottom() >= cr.top() and hdr_r.top() <= cr.bottom():
                # Left accent strip
                p.setBrush(QBrush(accent))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(hdr_r.left(), hdr_r.top() + 4,
                                         3, hdr_r.height() - 8), 1.5, 1.5)
                # Title
                font.setPixelSize(11); font.setWeight(QFont.Weight.DemiBold)
                p.setFont(font)
                p.setPen(accent if (is_today or is_tomr) else _C_LABEL)
                p.drawText(QRect(hdr_r.left() + 12, hdr_r.top(),
                                 hdr_r.width() - 80, hdr_r.height()),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           title)
                # Count badge on the right
                font.setPixelSize(10); font.setWeight(QFont.Weight.DemiBold)
                p.setFont(font)
                if items:
                    op = sum(1 for _, t in items if not t.get('done'))
                    dn = sum(1 for _, t in items if t.get('done'))
                    cnt = f'{op}/{op + dn}' if dn else str(op)
                    fm = p.fontMetrics()
                    bw = fm.horizontalAdvance(cnt) + 14
                    pill = QRect(hdr_r.right() - bw - 4,
                                 hdr_r.top() + 6, bw, 16)
                    p.setBrush(QBrush(accent.lighter(170)))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(pill, 8, 8)
                    p.setPen(accent.darker(125))
                    p.drawText(pill, Qt.AlignmentFlag.AlignCenter, cnt)
            y += self._WK_DAY_HDR_H

            # Day's tasks
            if not items:
                if y + self._WK_EMPTY_H >= cr.top() and y <= cr.bottom():
                    font.setPixelSize(11); font.setWeight(QFont.Weight.Normal)
                    p.setFont(font)
                    p.setPen(_C_MUTED)
                    p.drawText(QRect(cr.left() + 12, y,
                                     cr.width() - 24, self._WK_EMPTY_H),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                               '— no tasks')
                y += self._WK_EMPTY_H
            else:
                for idx, t in items:
                    if y + self._WK_TASK_H >= cr.top() and y <= cr.bottom():
                        self._draw_weekly_task_row(p, font, cr, y, t, idx)
                    y += self._WK_TASK_H
            y += self._WK_GAP

    def _draw_weekly_task_row(self, p: QPainter, font: QFont,
                              cr: QRect, y: int, t: dict, idx: int) -> None:
        """Compact one-line task row used in the weekly view."""
        row  = QRect(cr.left() + 8, y + 2, cr.width() - 16, self._WK_TASK_H - 6)
        chk  = QRect(row.left() + 6, row.center().y() - 8, 16, 16)
        delr = QRect(row.right() - 24, row.center().y() - 9, 18, 18)

        hov = self._hovered_key == f'task:{idx}'
        # Row card
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QBrush(_C_CARD_HOV if hov else _C_CARD))
        p.setPen(QPen(_C_BORDER_IN, 1))
        p.drawRoundedRect(QRectF(row).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)

        # Checkbox
        hov_chk = self._hovered_key == f'task_chk:{idx}'
        if t.get('done'):
            p.setBrush(QBrush(_C_ACCENT_MINT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(chk)
            p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 2,
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                           Qt.PenJoinStyle.RoundJoin))
            p.drawLine(chk.left() + 4, chk.center().y(),
                       chk.center().x() - 1, chk.bottom() - 4)
            p.drawLine(chk.center().x() - 1, chk.bottom() - 4,
                       chk.right() - 3, chk.top() + 4)
        else:
            ring = _C_ACCENT_MINT.darker(110) if hov_chk else _C_MUTED
            p.setBrush(QBrush(_C_CARD))
            p.setPen(QPen(ring, 2))
            p.drawEllipse(chk)

        # Task text
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Normal if t.get('done')
                       else QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_MUTED if t.get('done') else _C_INPUT_FG)
        text = t.get('text', '')
        # Time badge inline at the right
        dt = _parse_due(t.get('due'))
        time_s = _format_time(dt.hour, dt.minute) if dt else ''

        # Reserve space for the time pill on the right
        pill_w = 0
        if time_s:
            font.setPixelSize(10); font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            fm = p.fontMetrics()
            pill_w = fm.horizontalAdvance(time_s.lower().replace(' ', '')) + 14

        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Normal if t.get('done')
                       else QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_MUTED if t.get('done') else _C_INPUT_FG)
        text_r = QRect(row.left() + 30, row.top(),
                       row.width() - 60 - pill_w, row.height())
        p.drawText(text_r,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   text)
        if t.get('done'):
            ty = text_r.center().y()
            tw = min(len(text) * 7, text_r.width() - 4)
            p.setPen(QPen(_C_MUTED, 1))
            p.drawLine(text_r.left(), ty, text_r.left() + tw, ty)

        # Time pill
        if time_s:
            font.setPixelSize(10); font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            tx = time_s.lower().replace(' ', '')
            now = _datetime.now()
            overdue = (dt is not None and dt < now and not t.get('done'))
            col = (_C_ACCENT_ROSE if overdue
                   else _C_ACCENT_MINT if t.get('done')
                   else _C_ACCENT_BLUE)
            pill_r = QRect(row.right() - 30 - pill_w,
                           row.top() + 7, pill_w, 14)
            p.setBrush(QBrush(col.lighter(170)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(pill_r, 7, 7)
            p.setPen(col.darker(125))
            p.drawText(pill_r, Qt.AlignmentFlag.AlignCenter, tx)

        # Delete
        hov_del = self._hovered_key == f'task_del:{idx}'
        p.setBrush(QBrush(_C_ACCENT_ROSE if hov_del
                          else QColor(0x00, 0x00, 0x00, 12)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(delr), 5, 5)
        cx_d = delr.center().x(); cy_d = delr.center().y()
        p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF) if hov_del else _C_MUTED, 1.5,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(cx_d - 4, cy_d - 4, cx_d + 4, cy_d + 4)
        p.drawLine(cx_d + 4, cy_d - 4, cx_d - 4, cy_d + 4)

    def _weekly_row_iter(self):
        """Yield (kind, idx_or_None, rect_or_dict) for the weekly tab.

        Used by hit-testing.  kind is one of: 'task' (with a task rect dict).
        """
        cr = self._content_rect()
        y = cr.top() + self._WK_HDR_H - self._scroll_y
        for qd in self._weekly_days():
            y += self._WK_DAY_HDR_H
            items = self._todos_for_day(qd)
            if not items:
                y += self._WK_EMPTY_H
            else:
                for idx, _t in items:
                    row  = QRect(cr.left() + 8, y + 2,
                                 cr.width() - 16, self._WK_TASK_H - 6)
                    chk  = QRect(row.left() + 6, row.center().y() - 8, 16, 16)
                    delr = QRect(row.right() - 24, row.center().y() - 9,
                                 18, 18)
                    yield (idx, row, chk, delr)
                    y += self._WK_TASK_H
            y += self._WK_GAP

    # ── Paint ────────────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:
        buf = self._render_buf()
        p   = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        fw, fh = self.width(), self.height()
        s = self._anim_scale
        if s != 1.0:
            dw = int(fw * s); dh = int(fh * s)
            p.drawPixmap((fw - dw) // 2, (fh - dh) // 2, dw, dh, buf)
        else:
            p.drawPixmap(0, 0, buf)
        p.end()

    # ── Hit-testing ──────────────────────────────────────────────────────────
    def _hit_key(self, pos: QPoint) -> str | None:
        if self._close_rect().contains(pos):
            return '__close__'
        if self._pin_rect().contains(pos):
            return '__pin__'
        for name, r in self._tab_rects().items():
            if r.contains(pos):
                return f'tab:{name}'

        cr = self._content_rect()
        if not cr.contains(pos):
            return None

        tab = self._data.get('active_tab', 'calendar')

        # Popover (calendar tab only) takes priority
        if tab == 'calendar' and self._selected_day is not None:
            pr = self._popover_rect()
            if self._popover_close_rect().contains(pos):
                return 'pop_close'
            if self._adding:
                if self._pop_cancel_rect().contains(pos):
                    return 'pop_cancel'
                if self._pop_save_rect().contains(pos):
                    return 'pop_save'
                if self._pop_time_prev_rect().contains(pos):
                    return 'pop_time_prev'
                if self._pop_time_next_rect().contains(pos):
                    return 'pop_time_next'
                if self._popover_input_rect().contains(pos):
                    return 'pop_input'
            else:
                if self._popover_add_rect().contains(pos):
                    return 'pop_add'
            for idx, row, chk, delr in self._popover_task_rects():
                if chk.contains(pos):
                    return f'task_chk:{idx}'
                if delr.contains(pos):
                    return f'task_del:{idx}'
                if row.contains(pos):
                    return f'task:{idx}'
            if pr.contains(pos):
                return 'pop_panel'
            return 'pop_close'   # outside panel → close

        if tab == 'calendar':
            if self._cal_prev_rect().contains(pos):
                return 'cal_prev'
            if self._cal_next_rect().contains(pos):
                return 'cal_next'
            if self._cal_today_rect().contains(pos):
                return 'cal_today'
            day_hit = self._cal_day_at(pos)
            if day_hit is not None:
                qd, _in_month = day_hit
                return f'day:{qd.toString(Qt.DateFormat.ISODate)}'

        elif tab == 'tasks':
            if self._tasks_add_btn_rect().contains(pos):
                return 'tasks_add'
            if self._adding:
                if self._tasks_input_rect().contains(pos):
                    return 'tasks_input'
                if self._tasks_date_prev_rect().contains(pos):
                    return 'tasks_date_prev'
                if self._tasks_date_next_rect().contains(pos):
                    return 'tasks_date_next'
                if self._tasks_time_prev_rect().contains(pos):
                    return 'tasks_time_prev'
                if self._tasks_time_next_rect().contains(pos):
                    return 'tasks_time_next'
                if self._tasks_save_rect().contains(pos):
                    return 'tasks_save'
                if self._tasks_cancel_rect().contains(pos):
                    return 'tasks_cancel'
            # Walk the list using same iteration as draw
            y = self._tasks_list_top() - self._scroll_y
            for label, items in self._grouped_tasks():
                y += self._TASKS_GROUP_H
                for idx, _t in items:
                    row  = QRect(cr.left(), y, cr.width(),
                                 self._TASKS_ROW_H - 4)
                    chk  = QRect(row.left() + 8, row.center().y() - 11, 22, 22)
                    delr = QRect(row.right() - 30, row.center().y() - 11, 22, 22)
                    if chk.contains(pos):
                        return f'task_chk:{idx}'
                    if delr.contains(pos):
                        return f'task_del:{idx}'
                    if row.contains(pos):
                        return f'task:{idx}'
                    y += self._TASKS_ROW_H
                y += 4

        elif tab == 'weekly':
            for idx, row, chk, delr in self._weekly_row_iter():
                if chk.contains(pos):
                    return f'task_chk:{idx}'
                if delr.contains(pos):
                    return f'task_del:{idx}'
                if row.contains(pos):
                    return f'task:{idx}'

        return None

    # ── Mouse ────────────────────────────────────────────────────────────────
    def mouseMoveEvent(self, event) -> None:
        key = self._hit_key(event.pos())
        if key != self._hovered_key:
            self._hovered_key = key
            self.update()
        if self._drag_offset is not None:
            self.move(self.pos() + event.pos() - self._drag_offset)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        key = self._hit_key(event.pos())

        if key == '__close__':
            self.close_animated(); return
        if key == '__pin__':
            return
        if key is None:
            self._drag_offset = event.pos(); return
        if key.startswith('tab:'):
            name = key.split(':')[1]
            self._commit_or_cancel_draft()
            self._data['active_tab'] = name
            self._scroll_y    = 0
            self._selected_day = None
            self._adding      = False
            self._save(); self.update(); return

        tab = self._data.get('active_tab', 'calendar')

        # Popover handling first (calendar tab)
        if tab == 'calendar' and self._selected_day is not None:
            self._handle_popover_click(key); return

        # Calendar tab — month nav, day select
        if tab == 'calendar':
            if key == 'cal_prev':
                m = self._view_month - 1; y = self._view_year
                if m < 1: m = 12; y -= 1
                self._view_month, self._view_year = m, y
                self.update(); return
            if key == 'cal_next':
                m = self._view_month + 1; y = self._view_year
                if m > 12: m = 1; y += 1
                self._view_month, self._view_year = m, y
                self.update(); return
            if key == 'cal_today':
                t = QDate.currentDate()
                self._view_year, self._view_month = t.year(), t.month()
                self.update(); return
            if key.startswith('day:'):
                iso = key.split(':', 1)[1]
                qd  = QDate.fromString(iso, Qt.DateFormat.ISODate)
                # Switch to that month if it's adjacent overflow
                if qd.month() != self._view_month or qd.year() != self._view_year:
                    self._view_year, self._view_month = qd.year(), qd.month()
                self._selected_day = qd
                self._adding       = False
                self._draft_text   = ''
                self._draft_date   = qd
                # Default time = 5pm, or now+1h if today
                today = QDate.currentDate()
                if qd == today:
                    now = _datetime.now()
                    h, m = (now.hour + 1) % 24, 0
                    self._draft_hour, self._draft_minute = h, m
                else:
                    self._draft_hour, self._draft_minute = 17, 0
                self.update(); return

        # Tasks tab
        elif tab == 'tasks':
            if key == 'tasks_add':
                if self._adding:
                    self._commit_or_cancel_draft()
                else:
                    self._adding     = True
                    self._draft_text = ''
                    today = QDate.currentDate()
                    self._draft_date   = today.addDays(1)
                    self._draft_hour   = 17
                    self._draft_minute = 0
                self.update(); return
            if key == 'tasks_input':
                self._adding = True; self.update(); return
            if key == 'tasks_date_prev':
                self._draft_date = self._draft_date.addDays(-1)
                self.update(); return
            if key == 'tasks_date_next':
                self._draft_date = self._draft_date.addDays(1)
                self.update(); return
            if key == 'tasks_time_prev':
                tot = (self._draft_hour * 60 + self._draft_minute - 15) % (24 * 60)
                self._draft_hour, self._draft_minute = divmod(tot, 60)
                self.update(); return
            if key == 'tasks_time_next':
                tot = (self._draft_hour * 60 + self._draft_minute + 15) % (24 * 60)
                self._draft_hour, self._draft_minute = divmod(tot, 60)
                self.update(); return
            if key == 'tasks_save':
                self._commit_draft()
                self.update(); return
            if key == 'tasks_cancel':
                self._adding = False
                self._draft_text = ''
                self.update(); return
            if key.startswith('task_chk:'):
                self._toggle_done(int(key.split(':')[1]))
                self.update(); return
            if key.startswith('task_del:'):
                self._delete_todo(int(key.split(':')[1]))
                self.update(); return
            if key.startswith('task:'):
                # Future: open detail.  For now: no-op.
                return

        # Weekly tab
        elif tab == 'weekly':
            if key.startswith('task_chk:'):
                self._toggle_done(int(key.split(':')[1]))
                self.update(); return
            if key.startswith('task_del:'):
                self._delete_todo(int(key.split(':')[1]))
                self.update(); return
            if key.startswith('task:'):
                return

        # Header drag
        if event.pos().y() < HEADER_H:
            self._drag_offset = event.pos()

    def _handle_popover_click(self, key: str) -> None:
        if key == 'pop_close' or key == 'pop_panel':
            if key == 'pop_close':
                self._selected_day = None
                self._adding       = False
                self._draft_text   = ''
                self._save(); self.update()
            return
        if key == 'pop_add':
            self._adding     = True
            self._draft_text = ''
            today = QDate.currentDate()
            if self._selected_day == today:
                now = _datetime.now()
                self._draft_hour, self._draft_minute = (now.hour + 1) % 24, 0
            else:
                self._draft_hour, self._draft_minute = 17, 0
            self.update(); return
        if key == 'pop_cancel':
            self._adding     = False
            self._draft_text = ''
            self.update(); return
        if key == 'pop_save':
            # Use selected_day as the date
            self._draft_date = self._selected_day
            self._commit_draft()
            self.update(); return
        if key == 'pop_input':
            self._adding = True; self.update(); return
        if key == 'pop_time_prev':
            tot = (self._draft_hour * 60 + self._draft_minute - 15) % (24 * 60)
            self._draft_hour, self._draft_minute = divmod(tot, 60)
            self.update(); return
        if key == 'pop_time_next':
            tot = (self._draft_hour * 60 + self._draft_minute + 15) % (24 * 60)
            self._draft_hour, self._draft_minute = divmod(tot, 60)
            self.update(); return
        if key.startswith('task_chk:'):
            self._toggle_done(int(key.split(':')[1]))
            self.update(); return
        if key.startswith('task_del:'):
            self._delete_todo(int(key.split(':')[1]))
            self.update(); return

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        self._save()
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._close_rect().contains(event.pos()):
            self.close_animated()
        elif self._pin_rect().contains(event.pos()):
            self._toggle_pin()

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        notify_pin_toggled(self, self._pinned)
        self.update()

    def wheelEvent(self, event) -> None:
        tab = self._data.get('active_tab', 'calendar')
        if tab not in ('tasks', 'weekly'):
            return
        delta = -int(event.angleDelta().y() / 2)
        self._scroll_y = max(0, self._scroll_y + delta)
        if tab == 'tasks':
            groups   = self._grouped_tasks()
            n_rows   = sum(len(items) for _, items in groups)
            n_groups = len(groups)
            total_h  = (n_rows * self._TASKS_ROW_H +
                        n_groups * self._TASKS_GROUP_H + 40)
            max_s    = max(0, total_h - (_CONTENT_H - self._TASKS_HDR_H - 60))
        else:  # weekly
            total_h = self._WK_HDR_H
            for d in self._weekly_days():
                total_h += self._WK_DAY_HDR_H + self._WK_GAP
                items = self._todos_for_day(d)
                if items:
                    total_h += len(items) * self._WK_TASK_H
                else:
                    total_h += self._WK_EMPTY_H
            max_s = max(0, total_h - (_CONTENT_H - 24))
        self._scroll_y = min(self._scroll_y, max_s)
        self.update()

    # ── CRUD ─────────────────────────────────────────────────────────────────
    def _commit_draft(self) -> None:
        text = self._draft_text.strip()
        if not text or len(self._data['todos']) >= _MAX_TODOS:
            self._adding = False
            self._draft_text = ''
            return
        dt = _datetime(self._draft_date.year(),
                       self._draft_date.month(),
                       self._draft_date.day(),
                       self._draft_hour, self._draft_minute)
        new_todo = {
            'text':    text,
            'done':    False,
            'due':     dt.isoformat(),
            'planted': False,
        }
        self._data['todos'].append(new_todo)
        self.data_changed.emit(dict(self._data))
        self._save()
        self._adding     = False
        self._draft_text = ''

    def _commit_or_cancel_draft(self) -> None:
        """Called when switching tabs / closing — discard the in-progress draft."""
        self._adding     = False
        self._draft_text = ''

    def _toggle_done(self, idx: int) -> None:
        todos = self._data.get('todos', [])
        if 0 <= idx < len(todos):
            todos[idx]['done'] = not todos[idx].get('done', False)
            self.data_changed.emit(dict(self._data))
            self._save()

    def _delete_todo(self, idx: int) -> None:
        todos = self._data.get('todos', [])
        if 0 <= idx < len(todos):
            todos.pop(idx)
            self.data_changed.emit(dict(self._data))
            self._save()

    # ── Keyboard ─────────────────────────────────────────────────────────────
    def keyPressEvent(self, event) -> None:
        k = event.key()
        if k == Qt.Key.Key_Escape:
            if self._adding:
                self._adding     = False
                self._draft_text = ''
                self.update(); return
            if self._selected_day is not None:
                self._selected_day = None
                self.update(); return
            self.close_animated(); return

        if self._adding:
            if k == Qt.Key.Key_Return or k == Qt.Key.Key_Enter:
                # In popover, save uses selected_day; in tasks tab, draft_date
                if (self._data.get('active_tab') == 'calendar'
                        and self._selected_day is not None):
                    self._draft_date = self._selected_day
                self._commit_draft()
                self.update(); return
            if k == Qt.Key.Key_Backspace:
                self._draft_text = self._draft_text[:-1]
                self.update(); return
            t = event.text()
            if t and t.isprintable() and len(self._draft_text) < _MAX_TODO_LEN:
                self._draft_text += t
                self.update(); return
            return

        super().keyPressEvent(event)

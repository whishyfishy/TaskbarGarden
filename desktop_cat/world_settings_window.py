"""
World Settings panel for Desktop Cat.
Opened from the bedroom glove (world settings) button.
"""

import json
import os
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import Qt, QPoint, QRect, pyqtProperty, pyqtSignal
from PyQt6.QtCore    import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QTimer
from PyQt6.QtGui     import QPainter, QPixmap, QColor, QFont, QPen, QBrush

from desktop_cat import sounds
from desktop_cat import user_profile
from desktop_cat.retro_ui import (configure_floating_panel, paint_pixel_chrome,
                                   notify_pin_toggled, cancel_window_dimming)
from desktop_cat.theme import theme

_SAVE_PATH = os.path.join(os.path.dirname(__file__), 'world_settings.json')

_OPEN_MS         = 220
_CLOSE_MS        = 160
_POP_SCALE_START = 0.80

_DEFAULT_SETTINGS: dict = {
    # World
    'rain':                False,
    'house_x':             0.5,     # float 0.0–1.0 (left → right)
    'rocks_on':            True,
    'grass_on':            True,
    # Garden
    'flowers_hidden':      False,
    'flower_size':         1,       # 0=small  1=normal  2=large
    'flower_opacity':      1,       # 0=subtle  1=normal  2=bold
    'greenbeans':          False,
    'greenbeans_ultra':    False,
    # Audio
    'sound_effects':       True,
    'notification_fx':     True,
    'notifications':       True,
    # Display
    'performance_mode':    False,
    'greyscale':           False,
    'pomo_display_mode':   0,       # 0=flipdot grid  1=plain digital readout
    # Kept for back-compat (not shown in UI but still saved)
    'butterflies':         True,
    'goblin_knight':       True,
}

# ── Layout ────────────────────────────────────────────────────────────────────
_W          = 310
_BORDER     = 3
_PAD        = 14
_TITLE_H    = 30
_ROW_H      = 42
_ROW_GAP    = 4
_SEC_H      = 30
_VIEWPORT_H = 430
_H          = _BORDER + _TITLE_H + 2 + _VIEWPORT_H + 6 + _BORDER

# ── Palette — mutated by `_refresh_palette()` on theme change ────────────────
_C_BG            = QColor(0xF7, 0xF7, 0xFA, 252)
_C_HEADER        = QColor(0xEC, 0xEC, 0xF1)
_C_BORDER        = QColor(0x00, 0x00, 0x00, 36)
_C_BORDER_LT     = QColor(0x00, 0x00, 0x00, 18)
_C_TEXT          = QColor(0x1F, 0x1F, 0x21)
_C_LABEL         = QColor(0x1F, 0x1F, 0x21)
_C_MUTED         = QColor(0x60, 0x60, 0x68)
_C_DIVIDER       = QColor(0x00, 0x00, 0x00, 24)
_C_SEC_LABEL     = QColor(0x60, 0x60, 0x68)
_C_ON            = QColor(0x4F, 0xB3, 0x86)
_C_OFF           = QColor(0xC8, 0xC8, 0xCE)
_C_KNOB          = QColor(0xFF, 0xFF, 0xFF)
_C_CYCLE_BG      = QColor(0xFF, 0xFF, 0xFF)
_C_CYCLE_FG      = QColor(0x1F, 0x1F, 0x21)
_C_SLIDER_TRACK  = QColor(0xE0, 0xE0, 0xE6)
_C_SLIDER_FILL   = QColor(0x46, 0x82, 0xE6)
_C_SLIDER_THUMB  = QColor(0xFF, 0xFF, 0xFF)
_C_SCROLLBAR     = QColor(0xE0, 0xE0, 0xE6)
_C_SCROLLTHUMB   = QColor(0xA0, 0xA0, 0xA8)


def _refresh_palette() -> None:
    """Re-tune palette in place when the global theme flips."""
    if theme.is_dark():
        _C_BG.setRgb(0x22, 0x23, 0x28, 252)
        _C_HEADER.setRgb(0x18, 0x19, 0x1D)
        _C_BORDER.setRgb(0xFF, 0xFF, 0xFF, 30)
        _C_BORDER_LT.setRgb(0xFF, 0xFF, 0xFF, 18)
        _C_TEXT.setRgb(0xF0, 0xF0, 0xF2)
        _C_LABEL.setRgb(0xF0, 0xF0, 0xF2)
        _C_MUTED.setRgb(0xA8, 0xA8, 0xB0)
        _C_DIVIDER.setRgb(0xFF, 0xFF, 0xFF, 24)
        _C_SEC_LABEL.setRgb(0xA8, 0xA8, 0xB0)
        _C_OFF.setRgb(0x55, 0x55, 0x5C)
        _C_KNOB.setRgb(0xF0, 0xF0, 0xF2)
        _C_CYCLE_BG.setRgb(0x33, 0x34, 0x39)
        _C_CYCLE_FG.setRgb(0xF0, 0xF0, 0xF2)
        _C_SLIDER_TRACK.setRgb(0x40, 0x42, 0x48)
        _C_SLIDER_THUMB.setRgb(0xF0, 0xF0, 0xF2)
        _C_SCROLLBAR.setRgb(0x33, 0x34, 0x39)
        _C_SCROLLTHUMB.setRgb(0x6E, 0x6E, 0x76)
    else:
        _C_BG.setRgb(0xF7, 0xF7, 0xFA, 252)
        _C_HEADER.setRgb(0xEC, 0xEC, 0xF1)
        _C_BORDER.setRgb(0x00, 0x00, 0x00, 36)
        _C_BORDER_LT.setRgb(0x00, 0x00, 0x00, 18)
        _C_TEXT.setRgb(0x1F, 0x1F, 0x21)
        _C_LABEL.setRgb(0x1F, 0x1F, 0x21)
        _C_MUTED.setRgb(0x60, 0x60, 0x68)
        _C_DIVIDER.setRgb(0x00, 0x00, 0x00, 24)
        _C_SEC_LABEL.setRgb(0x60, 0x60, 0x68)
        _C_OFF.setRgb(0xC8, 0xC8, 0xCE)
        _C_KNOB.setRgb(0xFF, 0xFF, 0xFF)
        _C_CYCLE_BG.setRgb(0xFF, 0xFF, 0xFF)
        _C_CYCLE_FG.setRgb(0x1F, 0x1F, 0x21)
        _C_SLIDER_TRACK.setRgb(0xE0, 0xE0, 0xE6)
        _C_SLIDER_THUMB.setRgb(0xFF, 0xFF, 0xFF)
        _C_SCROLLBAR.setRgb(0xE0, 0xE0, 0xE6)
        _C_SCROLLTHUMB.setRgb(0xA0, 0xA0, 0xA8)


_refresh_palette()
theme.changed.connect(_refresh_palette)

_CYCLE_LABELS: dict[str, list[str]] = {
    'flower_size':       ['small',  'normal', 'large' ],
    'flower_opacity':    ['subtle', 'normal', 'bold'  ],
    'pomo_display_mode': ['flipdot', 'digital'        ],
}

# ctrl_type: 'toggle' | 'cycle:<key>' | 'slider:<key>' | 'section'
_ROWS_DEF: list[tuple[str, str, str]] = [
    ('_sec_world',         '~ world',          'section'),
    ('rain',               'rainy days',       'toggle'),
    ('rocks_on',           'rocks',            'toggle'),
    ('house_x',            'house spot',       'slider:house_x'),
    ('_sec_garden',        '~ garden',         'section'),
    ('flowers_hidden',     'hide flowers',     'toggle'),
    ('grass_on',           'grass',            'toggle'),
    ('flower_size',        'flower size',      'cycle:flower_size'),
    ('flower_opacity',     'flower opacity',   'cycle:flower_opacity'),
    ('greenbeans',         'greenbeans',       'toggle'),
    ('greenbeans_ultra',   'greenbeans ultra', 'toggle'),
    ('_sec_audio',         '~ sounds',         'section'),
    ('sound_effects',      'sound fx',         'toggle'),
    ('notification_fx',    'notification fx',  'toggle'),
    ('notifications',      'notifications',    'toggle'),
    ('_sec_display',       '* display',        'section'),
    ('performance_mode',   'performance mode', 'toggle'),
    ('greyscale',          'greyscale',        'toggle'),
    ('pomo_display_mode',  'timer style',      'cycle:pomo_display_mode'),
    ('dark_mode',          'dark mode',        'theme_toggle'),
    ('_sec_danger',        '! danger zone',    'section'),
    ('delete_profile',     'reset profile',    'danger_button'),
]

_CONTENT_H: int = sum(
    _SEC_H if ctrl == 'section' else (_ROW_H + _ROW_GAP)
    for _, _, ctrl in _ROWS_DEF
)
_LABEL_W = 136   # px reserved for row labels


class WorldSettingsWindow(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        configure_floating_panel(self)
        self.setFixedSize(_W, _H)
        self.setMouseTracking(True)

        self._settings               = self._load()
        self._anim_scale: float      = 1.0
        self._main_anim: QParallelAnimationGroup | None = None
        self._closing                = False
        self._pinned                 = False
        self._drag_offset: QPoint | None  = None
        self._hovered_key: str | None     = None
        self._scroll_y: int          = 0
        self._max_scroll: int        = max(0, _CONTENT_H - _VIEWPORT_H)
        self._slider_drag_key: str | None = None
        self._apply_audio()

        # Repaint when the user flips light/dark
        theme.changed.connect(self.update)

        # ── Profile-reset two-stage confirmation ─────────────────────────
        # First click: arms the button (label flips to "really? click again").
        # Second click within ~3 s: actually wipes everything and quits.
        # Auto-disarms after the timeout if no second click comes.
        self._delete_armed: bool = False
        self._delete_arm_timer = QTimer(self)
        self._delete_arm_timer.setSingleShot(True)
        self._delete_arm_timer.setInterval(3000)
        self._delete_arm_timer.timeout.connect(self._disarm_delete)

    def _apply_audio(self) -> None:
        on = bool(self._settings.get('sound_effects', True))
        sounds.set_enabled(on)
        if on:
            sounds.start_ambient(volume=0.16)
        else:
            sounds.stop_ambient()

    # ── Persistence ───────────────────────────────────────────────────────────

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

    # ── Animatable scale ──────────────────────────────────────────────────────

    @pyqtProperty(float)
    def anim_scale(self) -> float:          # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                      # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    # ── Open / close ──────────────────────────────────────────────────────────

    def show_animated(self, x: int, y: int) -> None:
        self._closing    = False
        self._anim_scale = _POP_SCALE_START
        self.setWindowOpacity(0.0)
        self.move(x, y)
        self.show()

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

        # Stop any existing open/close animation group.
        if self._main_anim is not None:
            self._main_anim.stop()
            self._main_anim = None

        # Store animations as instance variables — keeps the Python (sip) wrapper
        # alive for the full animation duration and prevents premature GC from
        # destroying the underlying C++ QPropertyAnimation mid-run.
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

        # Safety net: if both animations somehow stall, force-close.
        QTimer.singleShot(_CLOSE_MS + 100, self._force_close_if_needed)

    def _force_close_if_needed(self) -> None:
        if self._closing and self.isVisible():
            self.setWindowOpacity(0.0)
            self.close()

    def closeEvent(self, event) -> None:
        self._save()
        super().closeEvent(event)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _content_top(self) -> int:
        return _BORDER + _TITLE_H + 2

    def _close_rect(self) -> QRect:
        return QRect(_W - _BORDER - _PAD - 16, _BORDER + 5, 16, _TITLE_H - 8)

    def _pin_rect(self) -> QRect:
        cr = self._close_rect()
        return QRect(cr.x() - cr.width() - 4, cr.y(), cr.width(), cr.height())

    def _control_rects(self) -> dict[str, QRect]:
        rects: dict[str, QRect] = {}
        ct = self._content_top()
        vb = ct + _VIEWPORT_H
        y  = ct - self._scroll_y

        for row_key, _label, ctrl in _ROWS_DEF:
            if ctrl == 'section':
                y += _SEC_H
                continue
            row_y = y + _ROW_GAP // 2
            if row_y + _ROW_H > ct and row_y < vb:
                if ctrl in ('toggle', 'theme_toggle'):
                    tw, th = 44, 22
                    rects[row_key] = QRect(_W - _BORDER - _PAD - tw,
                                           row_y + (_ROW_H - th) // 2, tw, th)
                elif ctrl == 'danger_button':
                    bw, bh = 142, 26
                    rects[row_key] = QRect(_W - _BORDER - _PAD - bw,
                                           row_y + (_ROW_H - bh) // 2, bw, bh)
                elif ctrl.startswith('cycle:'):
                    cw, ch = 76, 24
                    rects[row_key] = QRect(_W - _BORDER - _PAD - cw,
                                           row_y + (_ROW_H - ch) // 2, cw, ch)
                elif ctrl.startswith('slider:'):
                    lx = _BORDER + _PAD + _LABEL_W + 4
                    sw = _W - _BORDER - _PAD - 10 - lx
                    sh = 14
                    rects[row_key] = QRect(lx, row_y + (_ROW_H - sh) // 2, sw, sh)
            y += _ROW_H + _ROW_GAP
        return rects

    def _control_at(self, pos: QPoint) -> str | None:
        for key, rect in self._control_rects().items():
            if rect.contains(pos):
                return key
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_toggle(self, p: QPainter, rect: QRect, on: bool, hov: bool) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h = rect.height()
        r = h // 2
        track = (_C_ON if on else _C_OFF).lighter(112 if hov else 100)
        p.setBrush(QBrush(track))
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(rect, r, r)
        # Knob
        kx = rect.right() - h + 2 if on else rect.left() + 2
        p.setBrush(QBrush(_C_KNOB))
        p.setPen(QPen(_C_BORDER, 1))
        p.drawEllipse(kx, rect.top() + 2, h - 4, h - 4)

    def _draw_danger_button(self, p: QPainter, rect: QRect, hov: bool) -> None:
        """Pill-shaped destructive button.  Two visual states:
          * idle  — soft-red outline, dark red text
          * armed — solid red fill, white text + 'click to confirm' label
        """
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        red       = QColor(0xE8, 0x4C, 0x4C)
        red_dark  = QColor(0xC1, 0x3A, 0x3A)
        red_soft  = QColor(0xE8, 0x4C, 0x4C, 30)
        radius = rect.height() // 2

        if self._delete_armed:
            # Solid red filled pill
            fill = red.darker(108) if hov else red
            p.setBrush(QBrush(fill))
            p.setPen(QPen(red_dark, 1))
            p.drawRoundedRect(rect, radius, radius)
            label = 'really? click again'
            text_col = QColor(0xFF, 0xFF, 0xFF)
        else:
            # Outline pill, light wash on hover
            p.setBrush(QBrush(red_soft if hov else QColor(0, 0, 0, 0)))
            p.setPen(QPen(red, 1.5))
            p.drawRoundedRect(rect, radius, radius)
            label = 'delete profile'
            text_col = red if not hov else red_dark

        font = QFont('Segoe UI Variable', 1)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(text_col)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_cycle(self, p: QPainter, rect: QRect, sk: str, hov: bool) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        val    = self._settings.get(sk, 0)
        labels = _CYCLE_LABELS.get(sk, [])
        text   = labels[val] if 0 <= val < len(labels) else str(val)
        bg     = _C_CYCLE_BG.lighter(115 if hov else 100)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(_C_BORDER, 2))
        p.drawRect(rect.adjusted(1, 1, -1, -1))
        # Arrow hints
        font = QFont('Segoe UI Variable', 1)
        font.setPixelSize(13)
        font.setBold(False)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(QRect(rect.left() + 2, rect.top(), 12, rect.height()),
                   Qt.AlignmentFlag.AlignCenter, '<')
        p.drawText(QRect(rect.right() - 14, rect.top(), 12, rect.height()),
                   Qt.AlignmentFlag.AlignCenter, '>')
        font.setBold(True)
        p.setFont(font)
        p.setPen(_C_TEXT)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_slider(self, p: QPainter, rect: QRect, sk: str, hov: bool) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        val = float(self._settings.get(sk, 0.5))
        h   = rect.height()
        r   = h // 2
        # Track
        p.setBrush(QBrush(_C_SLIDER_TRACK))
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(rect, r, r)
        # Filled portion
        fill_w = max(r * 2, int(rect.width() * val))
        p.setBrush(QBrush(_C_SLIDER_FILL))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRect(rect.left(), rect.top(), fill_w, h), r, r)
        # Thumb circle
        tx = rect.left() + int((rect.width() - h) * val)
        p.setBrush(QBrush(_C_SLIDER_THUMB.lighter(112 if hov else 100)))
        p.setPen(QPen(_C_BORDER, 1))
        p.drawEllipse(tx, rect.top(), h, h)

    def _render_buf(self) -> QPixmap:
        buf = QPixmap(_W, _H)
        buf.fill(Qt.GlobalColor.transparent)
        p = QPainter(buf)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Pixel-art chrome (shared with hub / pomodoro / clipboard / board)
        cr = self._close_rect()
        hov_close = self._hovered_key == '__close__'
        paint_pixel_chrome(p, _W, _H,
                           header_h=_BORDER + _TITLE_H,
                           border=_BORDER,
                           title='world settings',
                           close_rect=cr,
                           close_hover=hov_close,
                           body_color=_C_BG,
                           pin_rect=self._pin_rect(),
                           pin_active=self._pinned,
                           pin_hover=self._hovered_key == '__pin__')
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # ── Scrollable content ────────────────────────────────────────────────
        ct = self._content_top()
        p.setClipRect(QRect(_BORDER, ct, _W - _BORDER * 2, _VIEWPORT_H))

        ctrl_rects = self._control_rects()
        y          = ct - self._scroll_y

        label_font = QFont('Segoe UI Variable', 1)
        label_font.setPixelSize(16)
        label_font.setBold(False)

        sec_font = QFont('Segoe UI Variable', 1)
        sec_font.setPixelSize(15)
        sec_font.setBold(True)

        for row_key, label, ctrl in _ROWS_DEF:
            if ctrl == 'section':
                if y + _SEC_H > ct and y < ct + _VIEWPORT_H:
                    cy2 = y + _SEC_H // 2
                    p.setFont(sec_font)
                    fm = p.fontMetrics()
                    lbl_w = fm.horizontalAdvance(label) + 8
                    lx = _BORDER + _PAD
                    # Left stub line
                    p.setPen(QPen(_C_DIVIDER, 1))
                    p.drawLine(lx, cy2, lx + 6, cy2)
                    # Label
                    p.setPen(_C_SEC_LABEL)
                    p.drawText(
                        QRect(lx + 6, y + 2, lbl_w, _SEC_H - 4),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        label,
                    )
                    # Right divider
                    p.setPen(QPen(_C_DIVIDER, 1))
                    p.drawLine(lx + 6 + lbl_w + 4, cy2,
                               _W - _BORDER - _PAD, cy2)
                y += _SEC_H
                continue

            row_y = y + _ROW_GAP // 2
            if row_y + _ROW_H > ct and row_y < ct + _VIEWPORT_H:
                p.setFont(label_font)
                p.setPen(_C_LABEL)
                p.drawText(
                    QRect(_BORDER + _PAD, row_y, _LABEL_W, _ROW_H),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
                rect = ctrl_rects.get(row_key)
                if rect:
                    hov = self._hovered_key == row_key
                    if ctrl == 'toggle':
                        self._draw_toggle(p, rect,
                                          bool(self._settings.get(row_key, False)), hov)
                    elif ctrl == 'theme_toggle':
                        # State comes from the global theme, not _settings
                        self._draw_toggle(p, rect, theme.is_dark(), hov)
                    elif ctrl == 'danger_button':
                        self._draw_danger_button(p, rect, hov)
                    elif ctrl.startswith('cycle:'):
                        self._draw_cycle(p, rect, ctrl.split(':')[1], hov)
                    elif ctrl.startswith('slider:'):
                        self._draw_slider(p, rect, ctrl.split(':')[1], hov)
            y += _ROW_H + _ROW_GAP

        # ── Scrollbar ─────────────────────────────────────────────────────────
        p.setClipping(False)
        if _CONTENT_H > _VIEWPORT_H:
            sw      = 4
            sx      = _W - _BORDER - sw - 2
            ratio   = _VIEWPORT_H / _CONTENT_H
            thumb_h = max(20, int(_VIEWPORT_H * ratio))
            sr      = self._scroll_y / self._max_scroll if self._max_scroll else 0.0
            thumb_y = ct + int((_VIEWPORT_H - thumb_h) * sr)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setBrush(QBrush(_C_SCROLLBAR))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(sx, ct, sw, _VIEWPORT_H, 2, 2)
            p.setBrush(QBrush(_C_SCROLLTHUMB))
            p.drawRoundedRect(sx, thumb_y, sw, thumb_h, 2, 2)

        p.end()
        return buf

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

    # ── Mouse / wheel events ──────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        delta = -int(event.angleDelta().y() / 2)
        self._scroll_y = max(0, min(self._max_scroll, self._scroll_y + delta))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._slider_drag_key:
            self._update_slider(self._slider_drag_key, event.pos())
            return
        pos = event.pos()
        if self._close_rect().contains(pos):
            key: str | None = '__close__'
        elif self._pin_rect().contains(pos):
            key = '__pin__'
        else:
            key = self._control_at(pos)
        if key != self._hovered_key:
            self._hovered_key = key
            self.update()
        if self._drag_offset is not None:
            self.move(self.pos() + event.pos() - self._drag_offset)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._close_rect().contains(event.pos()):
            self.close_animated()
            return
        if self._pin_rect().contains(event.pos()):
            return  # handled on release
        row_key = self._control_at(event.pos())
        if row_key:
            for k, _l, c in _ROWS_DEF:
                if k == row_key and c.startswith('slider:'):
                    self._slider_drag_key = row_key
                    self._update_slider(row_key, event.pos())
                    return
            self._activate(row_key)
        else:
            self._drag_offset = event.pos()

    def mouseReleaseEvent(self, event) -> None:
        self._slider_drag_key = None
        self._drag_offset     = None
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

    def _update_slider(self, row_key: str, pos: QPoint) -> None:
        rect = self._control_rects().get(row_key)
        if not rect:
            return
        for k, _l, c in _ROWS_DEF:
            if k == row_key and c.startswith('slider:'):
                sk = c.split(':')[1]
                h  = rect.height()
                t  = max(0.0, min(1.0,
                         (pos.x() - rect.left() - h // 2) / max(1, rect.width() - h)))
                self._settings[sk] = round(t, 3)
                self.update()
                self.settings_changed.emit(dict(self._settings))
                self._save()
                break

    def _activate(self, row_key: str) -> None:
        for k, _label, ctrl in _ROWS_DEF:
            if k != row_key:
                continue
            if ctrl == 'toggle':
                self._settings[row_key] = not self._settings.get(row_key, False)
            elif ctrl == 'theme_toggle':
                # Flip the global theme — every theme-aware window repaints
                # via the `theme.changed` signal.
                theme.toggle()
                self.update()
                if row_key == 'sound_effects':
                    self._apply_audio()
                # No settings_changed for theme — it's persisted internally.
                return
            elif ctrl == 'danger_button' and row_key == 'delete_profile':
                self._handle_delete_profile()
                return
            elif ctrl.startswith('cycle:'):
                ck = ctrl.split(':')[1]
                n  = len(_CYCLE_LABELS.get(ck, []))
                if n:
                    self._settings[ck] = (self._settings.get(ck, 0) + 1) % n
            self.update()
            self.settings_changed.emit(dict(self._settings))
            self._save()
            if row_key == 'sound_effects':
                self._apply_audio()
            break

    # ── Profile reset flow ───────────────────────────────────────────────
    def _disarm_delete(self) -> None:
        """Called by the auto-disarm timer if the user doesn't confirm."""
        if self._delete_armed:
            self._delete_armed = False
            self.update()

    def _handle_delete_profile(self) -> None:
        """First click arms; second click within 3 s wipes everything."""
        if not self._delete_armed:
            self._delete_armed = True
            self._delete_arm_timer.start()
            self.update()
            return

        # Confirmed — wipe everything and quit.
        self._delete_armed = False
        self._delete_arm_timer.stop()
        try:
            user_profile.wipe_all()
        finally:
            # Quit the whole app.  Onboarding will run next launch because
            # `is_onboarded()` now returns False.
            from PyQt6.QtWidgets import QApplication
            QApplication.quit()

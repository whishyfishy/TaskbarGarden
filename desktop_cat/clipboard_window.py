"""
Clipboard & tools panel — opened from the bedroom anvil.

Three clipboard slots (click to copy back; + button saves current system
clipboard into an empty slot). Predefined keybinds are listed beneath:
  - start pomodoro timer from current settings
  - activate "pin on cursor" tool

Visual style matches message_board / pomodoro (warm amber woodcut theme).
"""
from __future__ import annotations

import json
import os
from typing import Callable

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import Qt, QPoint, QRect, pyqtProperty
from PyQt6.QtCore    import QTimer, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from PyQt6.QtGui     import QPainter, QPixmap, QColor, QFont, QPen, QGuiApplication, QBrush

from desktop_cat.retro_ui import (configure_floating_panel, paint_window_chrome,
                                   close_button_rect, pin_button_rect,
                                   notify_pin_toggled, cancel_window_dimming,
                                   HEADER_H, RADIUS_PX)
from desktop_cat.theme import theme
from PyQt6.QtGui import QPainterPath, QLinearGradient
from PyQt6.QtCore import QRectF

_SAVE_PATH = os.path.join(os.path.dirname(__file__), 'clipboard.json')

_OPEN_MS         = 220
_CLOSE_MS        = 160
_POP_SCALE_START = 0.80

# ── Palette — mutated by `_refresh_palette()` on theme change ──────────────
_C_BG            = QColor(0xF7, 0xF7, 0xFA, 252)
_C_HEADER        = QColor(0xEC, 0xEC, 0xF1)
_C_BORDER        = QColor(0x00, 0x00, 0x00, 36)
_C_BORDER_LT     = QColor(0x00, 0x00, 0x00, 18)
_C_TEXT          = QColor(0x1F, 0x1F, 0x21)
_C_LABEL         = QColor(0x1F, 0x1F, 0x21)
_C_MUTED         = QColor(0x60, 0x60, 0x68)
_C_SEC_LABEL     = QColor(0x60, 0x60, 0x68)

# Card fills
_C_CARD          = QColor(0xFF, 0xFF, 0xFF)
_C_CARD_HOV      = QColor(0x46, 0x82, 0xE6, 22)
_C_CARD_FILLED   = QColor(0xF0, 0xF5, 0xFF)
_C_INPUT_FG      = QColor(0x1F, 0x1F, 0x21)

# Accents — constant in both modes
_C_ACCENT_MINT   = QColor(0x4F, 0xB3, 0x86)
_C_ACCENT_AMBER  = QColor(0x46, 0x82, 0xE6)
_C_ACCENT_LAV    = QColor(0x9A, 0x7C, 0xD8)


def _refresh_palette() -> None:
    if theme.is_dark():
        _C_BG.setRgb(0x22, 0x23, 0x28, 252)
        _C_HEADER.setRgb(0x18, 0x19, 0x1D)
        _C_BORDER.setRgb(0xFF, 0xFF, 0xFF, 30)
        _C_BORDER_LT.setRgb(0xFF, 0xFF, 0xFF, 18)
        _C_TEXT.setRgb(0xF0, 0xF0, 0xF2)
        _C_LABEL.setRgb(0xF0, 0xF0, 0xF2)
        _C_MUTED.setRgb(0xA8, 0xA8, 0xB0)
        _C_SEC_LABEL.setRgb(0xA8, 0xA8, 0xB0)
        _C_CARD.setRgb(0x2D, 0x2E, 0x33)
        _C_CARD_HOV.setRgb(0x46, 0x82, 0xE6, 50)
        _C_CARD_FILLED.setRgb(0x1A, 0x20, 0x2A)
        _C_INPUT_FG.setRgb(0xF0, 0xF0, 0xF2)
    else:
        _C_BG.setRgb(0xF7, 0xF7, 0xFA, 252)
        _C_HEADER.setRgb(0xEC, 0xEC, 0xF1)
        _C_BORDER.setRgb(0x00, 0x00, 0x00, 36)
        _C_BORDER_LT.setRgb(0x00, 0x00, 0x00, 18)
        _C_TEXT.setRgb(0x1F, 0x1F, 0x21)
        _C_LABEL.setRgb(0x1F, 0x1F, 0x21)
        _C_MUTED.setRgb(0x60, 0x60, 0x68)
        _C_SEC_LABEL.setRgb(0x60, 0x60, 0x68)
        _C_CARD.setRgb(0xFF, 0xFF, 0xFF)
        _C_CARD_HOV.setRgb(0x46, 0x82, 0xE6, 22)
        _C_CARD_FILLED.setRgb(0xF0, 0xF5, 0xFF)
        _C_INPUT_FG.setRgb(0x1F, 0x1F, 0x21)


_refresh_palette()
theme.changed.connect(_refresh_palette)

_TITLE_TEXT = 'clipboard / keys'

# ── Layout ────────────────────────────────────────────────────────────────────
_W            = 320
_BORDER       = 0          # no separate border — chrome handles it
_PAD          = 14
_TITLE_H      = HEADER_H   # align with shared chrome constant
_SEC_GAP      = 10

_SLOTS_COUNT  = 3
_SLOT_H       = 72
_SLOT_GAP     = 8
_SLOTS_BLOCK_H = _SLOTS_COUNT * _SLOT_H + (_SLOTS_COUNT - 1) * _SLOT_GAP

_KEYBIND_H    = 48
_KEYBIND_GAP  = 6
_PREDEFINED = [
    ('pomodoro',  'ctrl+alt+p', 'start pomodoro timer',       _C_ACCENT_MINT),
    ('pin_tool',  'ctrl+alt+n', 'pin tool — click a window',  _C_ACCENT_LAV),
]
_KEYBINDS_BLOCK_H = len(_PREDEFINED) * _KEYBIND_H + \
    (len(_PREDEFINED) - 1) * _KEYBIND_GAP

_FOOTER_H = 28
_HDR_H    = 22

_H = (_TITLE_H
      + _PAD
      + _HDR_H + 6 + _SLOTS_BLOCK_H
      + _SEC_GAP
      + _HDR_H + 6 + _KEYBINDS_BLOCK_H
      + _SEC_GAP
      + _FOOTER_H
      + _PAD)

_PREVIEW_MAX_CHARS = 140   # truncate long clipboard entries for display


# ── Persistence ───────────────────────────────────────────────────────────────

def _load_slots() -> list[str]:
    try:
        with open(_SAVE_PATH) as f:
            raw = json.load(f)
        slots = raw.get('slots') or []
        out: list[str] = []
        for i in range(_SLOTS_COUNT):
            v = slots[i] if i < len(slots) else ''
            out.append(v if isinstance(v, str) else '')
        return out
    except (OSError, ValueError):
        return [''] * _SLOTS_COUNT


def _save_slots(slots: list[str]) -> None:
    try:
        with open(_SAVE_PATH, 'w') as f:
            json.dump({'slots': slots}, f)
    except OSError:
        pass


# ── Clipboard helpers ────────────────────────────────────────────────────────

def _get_system_clipboard() -> str:
    cb = QGuiApplication.clipboard()
    return cb.text() if cb else ''


def _set_system_clipboard(text: str) -> None:
    cb = QGuiApplication.clipboard()
    if cb:
        cb.setText(text)


# ── Widget ────────────────────────────────────────────────────────────────────

class ClipboardWindow(QWidget):
    def __init__(self,
                 on_start_pomodoro: Callable[[], None] | None = None,
                 on_toggle_pin_tool: Callable[[], None] | None = None,
                 get_pin_status: Callable[[], tuple[bool, int]] | None = None,
                 ) -> None:
        """
        on_start_pomodoro   — fired when the user clicks the pomodoro keybind
                              row (or when the global hotkey fires).
        on_toggle_pin_tool  — fired when the user clicks the pin-tool keybind
                              row or uses the global hotkey.
        get_pin_status      — callable returning (pin_mode_active, pinned_count)
                              so the row can reflect live state.
        """
        super().__init__()
        configure_floating_panel(self)
        self.setFixedSize(_W, _H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._on_start_pomodoro   = on_start_pomodoro   or (lambda: None)
        self._on_toggle_pin_tool  = on_toggle_pin_tool  or (lambda: None)
        self._get_pin_status      = get_pin_status      or (lambda: (False, 0))

        self._slots: list[str] = _load_slots()
        self._hovered_key: str | None = None
        self._copied_flash_idx: int = -1   # slot index flashing "copied!"
        self._copied_flash_ticks: int = 0

        self._anim_scale: float = 1.0
        self._main_anim: QParallelAnimationGroup | None = None
        self._closing: bool = False
        self._pinned: bool = False
        self._drag_offset: QPoint | None = None

        from PyQt6.QtCore import QTimer
        # Flash decay timer (also repaints pin-status row live).
        self._t = QTimer(self)
        self._t.setInterval(66)
        self._t.timeout.connect(self._tick)
        self._t.start()

        # Repaint when the user flips light/dark
        theme.changed.connect(self.update)

    # ── Public: called from main loop for live pin-status updates ───────────
    def pin_status_changed(self) -> None:
        self.update()

    # ── Scale animatable ────────────────────────────────────────────────────
    @pyqtProperty(float)
    def anim_scale(self) -> float:          # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                      # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    def _tick(self) -> None:
        if self._copied_flash_ticks > 0:
            self._copied_flash_ticks -= 1
            if self._copied_flash_ticks == 0:
                self._copied_flash_idx = -1
            self.update()
        else:
            # Still repaint so pin-mode ACTIVE indicator can pulse/update.
            self.update()

    # ── Open / close ────────────────────────────────────────────────────────
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
        _save_slots(self._slots)

        # Cancel any ecosystem dim/restore animation to avoid windowOpacity
        # property conflicts.  deleteLater() in _cancel_anim ensures the old
        # animation is fully removed from Qt's object tree.
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
        _save_slots(self._slots)
        super().closeEvent(event)

    # ── Geometry ────────────────────────────────────────────────────────────
    def _close_rect(self) -> QRect:
        return close_button_rect(self.rect())

    def _pin_rect(self) -> QRect:
        return pin_button_rect(self.rect())

    def _content_top(self) -> int:
        return _TITLE_H + _PAD

    def _slots_header_rect(self) -> QRect:
        return QRect(_PAD, self._content_top(), _W - 2 * _PAD, _HDR_H)

    def _slot_rects(self) -> list[QRect]:
        top = self._content_top() + _HDR_H + 6
        width = _W - 2 * _PAD
        out: list[QRect] = []
        for i in range(_SLOTS_COUNT):
            y = top + i * (_SLOT_H + _SLOT_GAP)
            out.append(QRect(_PAD, y, width, _SLOT_H))
        return out

    def _slot_action_rect(self, slot_rect: QRect) -> QRect:
        # Rounded button right-aligned, vertically centred in the slot.
        bh = 30; bw = 36
        return QRect(slot_rect.right() - bw - 6,
                     slot_rect.center().y() - bh // 2, bw, bh)

    def _slot_clear_rect(self, slot_rect: QRect) -> QRect:
        # Small ✕ circle in top-right corner of slot.
        s = 20
        return QRect(slot_rect.right() - s - 4, slot_rect.top() + 4, s, s)

    def _keybinds_header_rect(self) -> QRect:
        y = self._slot_rects()[-1].bottom() + _SEC_GAP
        return QRect(_PAD, y, _W - 2 * _PAD, _HDR_H)

    def _keybind_rects(self) -> list[QRect]:
        top = self._keybinds_header_rect().bottom() + 6
        width = _W - 2 * _PAD
        out: list[QRect] = []
        for i in range(len(_PREDEFINED)):
            y = top + i * (_KEYBIND_H + _KEYBIND_GAP)
            out.append(QRect(_PAD, y, width, _KEYBIND_H))
        return out

    def _footer_rect(self) -> QRect:
        y = self._keybind_rects()[-1].bottom() + _SEC_GAP
        return QRect(_PAD, y, _W - 2 * _PAD, _FOOTER_H)

    # ── Drawing ─────────────────────────────────────────────────────────────
    def _render_buf(self) -> QPixmap:
        buf = QPixmap(_W, _H)
        buf.fill(Qt.GlobalColor.transparent)
        p = QPainter(buf)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        paint_window_chrome(p, self.rect(), _TITLE_TEXT,
                            close_rect=self._close_rect(),
                            close_hover=self._hovered_key == '__close__',
                            pin_rect=self._pin_rect(),
                            pin_active=self._pinned,
                            pin_hover=self._hovered_key == '__pin__')

        # Slots section
        self._draw_section_header(p, self._slots_header_rect(), 'Clipboard Slots')
        for i, rect in enumerate(self._slot_rects()):
            self._draw_slot(p, i, rect)

        # Keybinds section
        self._draw_section_header(p, self._keybinds_header_rect(), 'Shortcuts')
        for i, rect in enumerate(self._keybind_rects()):
            self._draw_keybind(p, i, rect)

        # Footer
        self._draw_footer(p, self._footer_rect())

        p.end()
        return buf

    def _draw_section_header(self, p: QPainter, rect: QRect, text: str) -> None:
        # Muted label — no heavy line, just small uppercase label
        font = QFont('Segoe UI Variable', 1)
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(_C_SEC_LABEL)
        p.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   text.upper())

    def _slot_preview(self, text: str) -> str:
        if not text:
            return ''
        s = text.strip().replace('\n', ' ').replace('\t', ' ')
        if len(s) > _PREVIEW_MAX_CHARS:
            s = s[:_PREVIEW_MAX_CHARS - 1] + '…'
        return s

    def _draw_slot(self, p: QPainter, i: int, rect: QRect) -> None:
        filled = bool(self._slots[i])
        hov_card   = self._hovered_key == f'slot:{i}'
        hov_action = self._hovered_key == f'slot_action:{i}'
        hov_clear  = self._hovered_key == f'slot_clear:{i}'
        flashing   = self._copied_flash_idx == i and self._copied_flash_ticks > 0

        # Card — rounded 10px, white surface, faint blue border on hover
        r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        if flashing:
            p.setBrush(QBrush(_C_ACCENT_MINT.lighter(175)))
            p.setPen(QPen(_C_ACCENT_MINT, 1.5))
        elif hov_card or hov_action:
            p.setBrush(QBrush(_C_CARD_HOV if not filled else _C_CARD_FILLED))
            p.setPen(QPen(QColor(0x46, 0x82, 0xE6, 80), 1.5))
        elif filled:
            p.setBrush(QBrush(_C_CARD_FILLED))
            p.setPen(QPen(_C_BORDER_LT, 1))
        else:
            p.setBrush(QBrush(_C_CARD))
            p.setPen(QPen(_C_BORDER_LT, 1))
        p.drawRoundedRect(r, 10, 10)

        # Slot number badge — small filled circle
        cx_num = rect.left() + 22
        cy_num = rect.center().y()
        num_r = QRectF(cx_num - 11, cy_num - 11, 22, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_C_ACCENT_AMBER if filled else QColor(0x00, 0x00, 0x00, 20)))
        p.drawEllipse(num_r)
        f = QFont('Segoe UI Variable', 1); f.setPixelSize(13)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(0xFF, 0xFF, 0xFF) if filled else _C_MUTED)
        p.drawText(num_r.toRect(), Qt.AlignmentFlag.AlignCenter, str(i + 1))

        # Preview / placeholder text
        act = self._slot_action_rect(rect)
        text_r = QRect(rect.left() + 40, rect.top() + 8,
                       act.left() - rect.left() - 46, rect.height() - 16)
        f.setPixelSize(13); f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        if flashing:
            p.setPen(_C_ACCENT_MINT.darker(140))
            p.drawText(text_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       'copied ✓')
        elif filled:
            p.setPen(_C_TEXT)
            p.drawText(text_r,
                       Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignTop,
                       self._slot_preview(self._slots[i]))
        else:
            p.setPen(_C_MUTED)
            p.drawText(text_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       'empty — click to save clipboard')

        # Action button — rounded pill, blue accent
        act_r = QRectF(act).adjusted(0.5, 0.5, -0.5, -0.5)
        if hov_action:
            p.setBrush(QBrush(_C_ACCENT_AMBER.darker(110)))
        else:
            p.setBrush(QBrush(_C_ACCENT_AMBER))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(act_r, 8, 8)
        f.setPixelSize(16); f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(0xFF, 0xFF, 0xFF))
        p.drawText(act, Qt.AlignmentFlag.AlignCenter, '+' if not filled else '⎘')

        # Clear ✕ circle (top-right, filled slots only)
        if filled:
            clr = self._slot_clear_rect(rect)
            clr_r = QRectF(clr)
            p.setBrush(QBrush(QColor(0xE8, 0x4C, 0x4C) if hov_clear
                              else QColor(0x00, 0x00, 0x00, 20)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(clr_r)
            p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF) if hov_clear else _C_MUTED, 1.5))
            cx = clr.center().x(); cy = clr.center().y(); d = 4
            p.drawLine(cx - d, cy - d, cx + d, cy + d)
            p.drawLine(cx + d, cy - d, cx - d, cy + d)

    def _draw_keybind(self, p: QPainter, i: int, rect: QRect) -> None:
        name, combo, label, accent = _PREDEFINED[i]
        hov = self._hovered_key == f'keybind:{name}'

        pin_active = False
        pin_count  = 0
        if name == 'pin_tool':
            try:
                pin_active, pin_count = self._get_pin_status()
            except Exception:
                pin_active, pin_count = False, 0

        # Card — rounded 10px
        r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        if pin_active:
            p.setBrush(QBrush(accent.lighter(175)))
            p.setPen(QPen(accent, 1.5))
        elif hov:
            p.setBrush(QBrush(QColor(0x00, 0x00, 0x00, 12)))
            p.setPen(QPen(QColor(0x46, 0x82, 0xE6, 80), 1.5))
        else:
            p.setBrush(QBrush(_C_CARD))
            p.setPen(QPen(_C_BORDER_LT, 1))
        p.drawRoundedRect(r, 10, 10)

        # Accent pill on left
        pill = QRectF(rect.left() + 8, rect.top() + 10, 4, rect.height() - 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(accent))
        p.drawRoundedRect(pill, 2, 2)

        # Label
        f = QFont('Segoe UI Variable', 1); f.setPixelSize(14)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(_C_TEXT)
        label_text = label
        if name == 'pin_tool':
            if pin_active:
                label_text = 'pin ACTIVE — click a window'
            elif pin_count > 0:
                label_text = f'{label}  ({pin_count} pinned)'

        # Reserve space for the keycap badge on right
        cap_w = 104
        p.drawText(QRect(rect.left() + 18, rect.top() + 4,
                         rect.width() - cap_w - 22, rect.height() - 8),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   label_text)

        # Keycap — modern rounded badge
        cap = QRect(rect.right() - cap_w - 2, rect.top() + 9,
                    cap_w, rect.height() - 18)
        p.setBrush(QBrush(_C_BG))
        p.setPen(QPen(_C_BORDER_LT, 1))
        p.drawRoundedRect(QRectF(cap).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        f.setPixelSize(12); f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(accent.darker(130) if not pin_active else accent.darker(160))
        p.drawText(cap, Qt.AlignmentFlag.AlignCenter, combo)

    def _draw_footer(self, p: QPainter, rect: QRect) -> None:
        f = QFont('Segoe UI Variable', 1); f.setPixelSize(14); f.setBold(False)
        p.setFont(f)
        p.setPen(_C_MUTED)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, 'custom keybinds — coming soon')

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

    # ── Hit-testing ─────────────────────────────────────────────────────────
    def _hit_key(self, pos: QPoint) -> str | None:
        if self._close_rect().contains(pos):
            return '__close__'
        if self._pin_rect().contains(pos):
            return '__pin__'
        for i, rect in enumerate(self._slot_rects()):
            if self._slot_action_rect(rect).contains(pos):
                return f'slot_action:{i}'
            if self._slots[i] and self._slot_clear_rect(rect).contains(pos):
                return f'slot_clear:{i}'
            if rect.contains(pos):
                return f'slot:{i}'
        for i, rect in enumerate(self._keybind_rects()):
            if rect.contains(pos):
                return f'keybind:{_PREDEFINED[i][0]}'
        return None

    # ── Mouse ───────────────────────────────────────────────────────────────
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
            return  # handled on release
        if key is None:
            self._drag_offset = event.pos(); return

        if key.startswith('slot_action:'):
            i = int(key.split(':')[1])
            if self._slots[i]:
                # filled → copy back to system clipboard
                _set_system_clipboard(self._slots[i])
            else:
                # empty → save current clipboard
                text = _get_system_clipboard()
                if text:
                    self._slots[i] = text
                    _save_slots(self._slots)
            self._flash_copied(i)
            return

        if key.startswith('slot_clear:'):
            i = int(key.split(':')[1])
            self._slots[i] = ''
            _save_slots(self._slots)
            self.update()
            return

        if key.startswith('slot:'):
            i = int(key.split(':')[1])
            if self._slots[i]:
                _set_system_clipboard(self._slots[i])
                self._flash_copied(i)
            else:
                # empty card: treat a click anywhere as "save current"
                text = _get_system_clipboard()
                if text:
                    self._slots[i] = text
                    _save_slots(self._slots)
                    self._flash_copied(i)
            return

        if key.startswith('keybind:'):
            name = key.split(':')[1]
            if name == 'pomodoro':
                self._on_start_pomodoro()
            elif name == 'pin_tool':
                self._on_toggle_pin_tool()
            self.update()
            return

        # Clicks in empty title strip → drag
        if event.pos().y() < _BORDER + _TITLE_H:
            self._drag_offset = event.pos()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
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

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_animated()
            return
        super().keyPressEvent(event)

    def _flash_copied(self, i: int) -> None:
        self._copied_flash_idx = i
        self._copied_flash_ticks = 18   # ~1.2s at 66ms tick
        self.update()

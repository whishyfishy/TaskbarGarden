"""
Garden Window — shows task seeds available to plant and planted task flowers.

A seed is a todo item that has a due date and hasn't been planted yet.
Clicking "plant" sends a SEED_PLANT event via the EventBus; main.py creates
a FallingSeed that falls onto the taskbar floor.

Seeds can also be dragged directly from the window — grab the seed icon on
a row, drag it toward the taskbar, and release to plant at that x position.
"""
from __future__ import annotations

import os
from datetime import date as _date

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import Qt, QPoint, QRect, QRectF, QTimer, pyqtProperty
from PyQt6.QtCore    import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from PyQt6.QtGui     import QPainter, QPixmap, QColor, QFont, QPen, QBrush, QPainterPath

from desktop_cat.retro_ui import (configure_floating_panel, paint_window_chrome,
                                   close_button_rect, pin_button_rect,
                                   notify_pin_toggled, register_sao_window,
                                   cancel_window_dimming, HEADER_H, RADIUS_PX)
from desktop_cat.theme import theme
import desktop_cat.inventory as _inv_mod
from desktop_cat.inventory import ABUG_KINDS, BBUG_KINDS, ABUG_SLOT_COUNT, BBUG_SLOT_COUNT


# ---------------------------------------------------------------------------
# Floating seed drag-indicator
# ---------------------------------------------------------------------------

class _SeedDragHint(QWidget):
    """Tiny transparent floating window showing a purple seed during drag."""
    _SIZE = 28

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self._SIZE, self._SIZE)

    def move_to_cursor(self, global_pos: QPoint) -> None:
        self.move(global_pos.x() - self._SIZE // 2,
                  global_pos.y() - self._SIZE // 2)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        cx, cy = self._SIZE // 2, self._SIZE // 2
        S = 5
        # Outer shadow
        p.setBrush(QBrush(QColor(80, 30, 140, 180)))
        p.drawEllipse(cx - S - 1, cy - S - 1, S * 2 + 3, S * 2 + 3)
        # Main petal colour
        p.setBrush(QBrush(QColor(160, 90, 220, 230)))
        p.drawEllipse(cx - S, cy - S, S * 2, S * 2)
        # Inner glow
        p.setBrush(QBrush(QColor(220, 195, 255, 255)))
        p.drawEllipse(cx - 2, cy - 2, 5, 5)
        p.end()


# ── Layout ─────────────────────────────────────────────────────────────────────
_W         = 340
_PAD       = 12
_HDR_H     = 22      # section-header row height
_SEC_GAP   = 14      # gap between sections
_CONTENT_H = 416     # content area height (below chrome HEADER_H)
_H         = HEADER_H + _PAD + _CONTENT_H + _PAD   # 30+12+416+12 = 470

_OPEN_MS         = 220
_CLOSE_MS        = 160
_POP_SCALE_START = 0.80

# ── Palette — mutated by `_refresh_palette()` on theme change ──────────────
_C_BG        = QColor(0xF7, 0xF7, 0xFA, 252)
_C_BORDER_LT = QColor(0x00, 0x00, 0x00, 18)
_C_TEXT      = QColor(0x1F, 0x1F, 0x21)
_C_MUTED     = QColor(0x60, 0x60, 0x68)
_C_SEC_LABEL = QColor(0x60, 0x60, 0x68)
_C_CARD      = QColor(0xFF, 0xFF, 0xFF)
_C_CARD_HOV  = QColor(0x46, 0x82, 0xE6, 22)
# Accents — constant in both modes
_C_LAV       = QColor(0x9A, 0x7C, 0xD8)
_C_ROSE      = QColor(0xE8, 0x4C, 0x4C)
_C_AMBER     = QColor(0xC4, 0x8A, 0x20)


def _refresh_palette() -> None:
    if theme.is_dark():
        _C_BG.setRgb(0x22, 0x23, 0x28, 252)
        _C_BORDER_LT.setRgb(0xFF, 0xFF, 0xFF, 18)
        _C_TEXT.setRgb(0xF0, 0xF0, 0xF2)
        _C_MUTED.setRgb(0xA8, 0xA8, 0xB0)
        _C_SEC_LABEL.setRgb(0xA8, 0xA8, 0xB0)
        _C_CARD.setRgb(0x2D, 0x2E, 0x33)
        _C_CARD_HOV.setRgb(0x46, 0x82, 0xE6, 50)
    else:
        _C_BG.setRgb(0xF7, 0xF7, 0xFA, 252)
        _C_BORDER_LT.setRgb(0x00, 0x00, 0x00, 18)
        _C_TEXT.setRgb(0x1F, 0x1F, 0x21)
        _C_MUTED.setRgb(0x60, 0x60, 0x68)
        _C_SEC_LABEL.setRgb(0x60, 0x60, 0x68)
        _C_CARD.setRgb(0xFF, 0xFF, 0xFF)
        _C_CARD_HOV.setRgb(0x46, 0x82, 0xE6, 22)


_refresh_palette()
theme.changed.connect(_refresh_palette)

# Purple flower colours for the seed icon
_SEED_PETAL  = (160,  90, 220)
_SEED_SHADOW = (110,  50, 170)
_SEED_CENTRE = (180, 220, 255)

_ROW_H = 64

# ── Bug loadout tab ────────────────────────────────────────────────────────
_TAB_H     = 30           # height of the Seeds / Inventory tab bar
_BOX_W     = 72           # slot box width
_BOX_H     = 56           # slot box height
_BOX_GAP   = 8            # gap between boxes
_SPARE_H   = 44           # height of each spare-bug row

_BUG_LABELS: dict[str, str] = {
    'abug1': 'Lazy Drone',
    'abug2': 'Lifter Moth',
    'abug3': 'Friend Bug',
    'bbug1': 'Bountiful Bee',
    'bbug2': 'Regrow Bee',
    'bbug3': 'Wardbee',
    'plain': 'Butterfly',
}
_BUG_COLOR: dict[str, tuple] = {
    'abug1': (230, 220, 130),
    'abug2': (180, 100, 220),
    'abug3': (255, 180, 200),
    'bbug1': (220, 180,  40),
    'bbug2': ( 80, 200, 150),
    'bbug3': (190,  60,  60),
    'plain': (150, 190, 250),
}
_BUG_DESC: dict[str, str] = {
    'abug1': 'guides the knight',
    'abug2': 'lifts Sao',
    'abug3': 'lands on cursor',
    'bbug1': '50% double drop',
    'bbug2': '50% auto-replant',
    'bbug3': 'wards off orc',
    'plain': 'default flutter',
}


def _due_label(due_str: str | None) -> tuple[str, QColor]:
    """Return (display text, colour) for a due-date badge."""
    if not due_str:
        return ('', _C_MUTED)
    try:
        d1   = _date.fromisoformat(due_str)
        diff = (d1 - _date.today()).days
        if diff < 0:
            return (f'overdue {abs(diff)}d', _C_ROSE)
        elif diff == 0:
            return ('due today!', _C_AMBER)
        elif diff <= 3:
            return (f'{diff}d left', _C_AMBER)
        else:
            return (f"{d1.strftime('%b')} {d1.day}", _C_LAV)
    except ValueError:
        return ('', _C_MUTED)


class GardenWindow(QWidget):
    def __init__(self,
                 *,
                 get_todos=None,
                 get_task_flowers=None,
                 on_seed_plant=None,
                 on_task_flower_delete=None,
                 bus=None,
                 get_inventory=None,
                 save_inventory=None) -> None:
        super().__init__()
        # Callbacks provided by main.py / hub_window
        self._get_todos              = get_todos              or (lambda: [])
        self._get_task_flowers       = get_task_flowers       or (lambda: [])
        self._on_seed_plant          = on_seed_plant          or (lambda text, due, x=None, y=None: None)
        self._on_task_flower_delete  = on_task_flower_delete  or (lambda text: None)
        self._bus                    = bus
        self._get_inventory          = get_inventory          or (lambda: {})
        self._save_inventory         = save_inventory         or (lambda _: None)

        configure_floating_panel(self)
        self.setFixedSize(_W, _H)
        self.setMouseTracking(True)
        register_sao_window(self)

        self._anim_scale: float = 1.0
        self._main_anim: QParallelAnimationGroup | None = None
        self._closing  = False
        self._pinned   = False
        self._drag_offset: QPoint | None = None
        self._hovered_key: str | None = None
        self._scroll_y: int = 0
        self._active_tab: int = 0   # 0 = Seeds & Flowers, 1 = Bug Inventory

        # Drag-and-drop seed state
        self._drag_pending: dict | None    = None   # seed todo waiting for threshold
        self._drag_start_pos: QPoint | None = None  # press position (widget coords)
        self._dragging_seed: dict | None   = None   # active drag payload
        self._drag_hint: _SeedDragHint | None = None  # floating indicator widget

        # Repaint when the user flips light/dark
        theme.changed.connect(self.update)

    # ── Animatable scale ───────────────────────────────────────────────────────
    @pyqtProperty(float)
    def anim_scale(self) -> float:           # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                       # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    # ── Show / close ───────────────────────────────────────────────────────────
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
        """Called ~100 ms after the close animation should have finished.
        If the window is still visible (animation got stuck), close it now."""
        if self._closing and self.isVisible():
            self.setWindowOpacity(0.0)
            self.close()

    # ── Geometry helpers ───────────────────────────────────────────────────────
    def _close_rect(self) -> QRect:
        return close_button_rect(QRect(0, 0, _W, _H))

    def _pin_rect(self) -> QRect:
        return pin_button_rect(QRect(0, 0, _W, _H))

    def _tab_bar_rect(self) -> QRect:
        top = HEADER_H + _PAD
        return QRect(_PAD, top, _W - 2 * _PAD, _TAB_H)

    def _content_rect(self) -> QRect:
        top = HEADER_H + _PAD + _TAB_H + 6
        h   = _CONTENT_H - _TAB_H - 6
        return QRect(_PAD, top, _W - 2 * _PAD, h)

    # ── Data helpers ───────────────────────────────────────────────────────────
    def _plantable_seeds(self):
        """Todos with a due date that haven't been planted yet.

        A seed is plantable iff:
          * it has a due date,
          * it isn't done,
          * it isn't already represented by a TaskFlower on the taskbar, AND
          * its 'planted' flag is False (set when its seed lands → flower).

        The 'planted' flag is the critical guard: if a flower is later removed,
        the assignment is also deleted (bidirectional sync), but on the off
        chance the assignment lingers it must NEVER reappear as a re-plantable
        seed.  The flag survives even after the flower is gone.
        """
        planted_texts = {tf.task_text for tf in self._get_task_flowers()}
        return [t for t in self._get_todos()
                if t.get('due') and t['text'] not in planted_texts
                and not t.get('done')
                and not t.get('planted')]

    def _planted_flowers(self):
        """All currently-planted task flowers."""
        return list(self._get_task_flowers())

    # ── Item rects ─────────────────────────────────────────────────────────────
    def _seeds_block_h(self) -> int:
        """Height of the seeds section's body (rows OR the empty-state hint).

        When there are zero seeds we still reserve a row so the 'add tasks
        with due dates' hint and the 'Planted' header below it don't overlap.
        """
        seeds = self._plantable_seeds()
        if not seeds:
            return 36         # height of the empty-state hint line + breathing room
        return len(seeds) * _ROW_H

    def _seed_rects(self) -> list[tuple[int, dict, QRect, QRect]]:
        """(idx, todo, row_rect, plant_btn_rect) for each plantable seed."""
        cr  = self._content_rect()
        y   = cr.top() + _HDR_H + 4 - self._scroll_y
        out = []
        for i, t in enumerate(self._plantable_seeds()):
            row  = QRect(cr.left(), y, cr.width(), _ROW_H - 4)
            btn  = QRect(row.right() - 64, row.top() + (_ROW_H - 28) // 2, 62, 28)
            out.append((i, t, row, btn))
            y += _ROW_H
        return out

    def _flower_rects(self) -> list[tuple[int, object, QRect, QRect]]:
        """(idx, TaskFlower, row_rect, del_btn_rect)."""
        cr    = self._content_rect()
        y     = (cr.top() + _HDR_H + 4
                 + self._seeds_block_h()
                 + _SEC_GAP + _HDR_H + 4
                 - self._scroll_y)
        out   = []
        for i, tf in enumerate(self._planted_flowers()):
            row     = QRect(cr.left(), y, cr.width(), _ROW_H - 4)
            del_btn = QRect(row.right() - 28, row.center().y() - 12, 24, 24)
            out.append((i, tf, row, del_btn))
            y += _ROW_H
        return out

    # ── Draw helpers ───────────────────────────────────────────────────────────
    def _draw_section_header(self, p: QPainter, rect: QRect, text: str) -> None:
        """Muted uppercase label — matches clipboard / keys style."""
        f = QFont('Segoe UI Variable', 1)
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(_C_SEC_LABEL)
        p.drawText(rect,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   text.upper())

    def _draw_seed_icon(self, p: QPainter, cx: int, cy: int, frac: float) -> None:
        """Tiny pixel seed / bloom icon.  frac 0 = seed, 1 = full bloom."""
        S = 2
        p.setPen(Qt.PenStyle.NoPen)
        if frac < 0.25:
            # Seed: tiny brown oval
            p.setBrush(QBrush(QColor(120, 85, 40)))
            p.drawEllipse(cx - S, cy - S, S * 2, S * 2)
        elif frac < 0.6:
            # Sprout: stem + tiny leaf
            p.setBrush(QBrush(QColor(55, 118, 38)))
            p.drawRect(cx - S, cy - S * 3, S, S * 3)
            p.setBrush(QBrush(QColor(70, 148, 55)))
            p.drawRect(cx - S * 2, cy - S * 2, S, S)
        else:
            # Small bloom: petals
            p.setBrush(QBrush(QColor(*_SEED_PETAL)))
            for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                p.drawRect(cx + dx * S - S, cy + dy * S - S, S * 2, S * 2)
            p.setBrush(QBrush(QColor(*_SEED_CENTRE)))
            p.drawRect(cx - S, cy - S, S * 2, S * 2)

    # ── Bug loadout helpers ───────────────────────────────────────────────────
    def _spare_bugs(self, inv: dict) -> dict[str, int]:
        """Kinds that are owned but not yet placed in any slot."""
        owned      = inv.get('bug_owned', {})
        a_slots    = inv.get('abug_slots', [None] * ABUG_SLOT_COUNT)
        b_slots    = inv.get('bbug_slots', [None] * BBUG_SLOT_COUNT)
        spare: dict[str, int] = {}
        for kind in ABUG_KINDS + BBUG_KINDS:
            total    = owned.get(kind, 0)
            slotted  = a_slots.count(kind) + b_slots.count(kind)
            leftover = total - slotted
            if leftover > 0:
                spare[kind] = leftover
        return spare

    def _slot_box_rects(self, cr: QRect) -> dict[str, list[tuple[str | None, QRect]]]:
        """Returns {category: [(kind_or_None, rect), ...]} for ABug + BBug slots."""
        x0 = cr.left()
        y  = cr.top() + _HDR_H + 4

        # ABug: 4 slots in 2 columns
        a_rects: list[tuple[str | None, QRect]] = []
        inv = self._get_inventory()
        a_slots = list(inv.get('abug_slots', [None] * ABUG_SLOT_COUNT))
        while len(a_slots) < ABUG_SLOT_COUNT:
            a_slots.append(None)
        for i in range(ABUG_SLOT_COUNT):
            col = i % 2
            row = i // 2
            bx  = x0 + col * (_BOX_W + _BOX_GAP)
            by  = y  + row * (_BOX_H + _BOX_GAP)
            a_rects.append((a_slots[i], QRect(bx, by, _BOX_W, _BOX_H)))

        # BBug: 2 slots in a single row, below ABug grid
        b_y = y + 2 * (_BOX_H + _BOX_GAP) + _HDR_H + 8
        b_rects: list[tuple[str | None, QRect]] = []
        b_slots = list(inv.get('bbug_slots', [None] * BBUG_SLOT_COUNT))
        while len(b_slots) < BBUG_SLOT_COUNT:
            b_slots.append(None)
        for i in range(BBUG_SLOT_COUNT):
            bx = x0 + i * (_BOX_W + _BOX_GAP)
            b_rects.append((b_slots[i], QRect(bx, b_y, _BOX_W, _BOX_H)))

        return {'abug': a_rects, 'bbug': b_rects}

    def _spare_bug_rects(self, cr: QRect, slot_rects: dict) -> list[tuple[str, int, QRect]]:
        """(kind, count, rect) for each spare bug row."""
        inv   = self._get_inventory()
        spare = self._spare_bugs(inv)
        if not spare:
            return []
        # Position below the bbug section header + slots
        b_rects = slot_rects['bbug']
        bottom  = max(r.bottom() for _, r in b_rects) if b_rects else cr.top()
        y = bottom + _HDR_H + 12
        out = []
        for kind, count in spare.items():
            out.append((kind, count, QRect(cr.left(), y, cr.width(), _SPARE_H)))
            y += _SPARE_H + 4
        return out

    def _draw_bug_box(self, p: QPainter, kind: str | None, rect: QRect,
                      label: str, hovered: bool, empty_slot: bool) -> None:
        """Draws a single slot box or spare-pool badge."""
        r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        col = _BUG_COLOR.get(kind or 'plain', (150, 190, 250))
        accent = QColor(*col)

        if empty_slot:
            p.setBrush(QBrush(QColor(0, 0, 0, 8 if not hovered else 18)))
            p.setPen(QPen(QColor(0, 0, 0, 35), 1, Qt.PenStyle.DashLine))
        elif hovered:
            tint = QColor(accent); tint.setAlpha(40)
            p.setBrush(QBrush(tint))
            p.setPen(QPen(accent.darker(120), 1))
        else:
            tint = QColor(accent); tint.setAlpha(22)
            p.setBrush(QBrush(tint))
            p.setPen(QPen(accent.darker(140), 1))
        p.drawRoundedRect(r, 8, 8)

        # Accent strip at top
        if not empty_slot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(accent))
            p.drawRoundedRect(QRectF(rect.left() + 6, rect.top() + 5, rect.width() - 12, 3), 1.5, 1.5)

        # Wing/dot icon (tiny)
        cx = rect.center().x()
        cy = rect.top() + 22
        if not empty_slot:
            c = QColor(*col)
            p.setPen(Qt.PenStyle.NoPen)
            # Left wing
            p.setBrush(QBrush(c))
            p.drawEllipse(cx - 10, cy - 4, 10, 7)
            # Right wing
            p.drawEllipse(cx + 1, cy - 4, 10, 7)
            # Body
            p.setBrush(QBrush(c.darker(160)))
            p.drawEllipse(cx - 3, cy - 5, 6, 10)
        else:
            p.setPen(QPen(QColor(0, 0, 0, 40), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx - 7, cy - 5, 14, 10)

        # Label
        f = QFont('Segoe UI Variable', 1); f.setPixelSize(10); f.setBold(not empty_slot)
        p.setFont(f)
        p.setPen(_C_MUTED if empty_slot else _C_TEXT)
        p.drawText(QRect(rect.left() + 2, rect.bottom() - 18, rect.width() - 4, 16),
                   Qt.AlignmentFlag.AlignCenter,
                   'empty' if empty_slot else label)

    def _draw_loadout_tab(self, p: QPainter, cr: QRect) -> None:
        inv        = self._get_inventory()
        slot_rects = self._slot_box_rects(cr)
        spare_list = self._spare_bug_rects(cr, slot_rects)

        # ── ABug section ────────────────────────────────────────────────────
        self._draw_section_header(
            p, QRect(cr.left(), cr.top(), cr.width(), _HDR_H),
            f'Butterfly slots  ({ABUG_SLOT_COUNT})',
        )
        for i, (kind, rect) in enumerate(slot_rects['abug']):
            if rect.bottom() < cr.top() or rect.top() > cr.bottom():
                continue
            hov   = self._hovered_key == f'aslot:{i}'
            label = _BUG_LABELS.get(kind or 'plain', 'Butterfly')
            self._draw_bug_box(p, kind, rect, label, hov, kind is None)

        # ── BBug section ────────────────────────────────────────────────────
        b_rects = slot_rects['bbug']
        b_y = (b_rects[0][1].top() - _HDR_H - 6) if b_rects else cr.top()
        self._draw_section_header(
            p, QRect(cr.left(), b_y, cr.width(), _HDR_H),
            f'Bee slots  ({BBUG_SLOT_COUNT})',
        )
        for i, (kind, rect) in enumerate(b_rects):
            if rect.bottom() < cr.top() or rect.top() > cr.bottom():
                continue
            hov   = self._hovered_key == f'bslot:{i}'
            label = _BUG_LABELS.get(kind or '', 'empty')
            self._draw_bug_box(p, kind, rect, label, hov, kind is None)

        # ── Unequipped / spare bugs ──────────────────────────────────────────
        if spare_list:
            first_y = spare_list[0][2].top() - _HDR_H - 6
            self._draw_section_header(
                p, QRect(cr.left(), first_y, cr.width(), _HDR_H),
                'Unequipped  (click to fill next slot)',
            )
        for kind, count, rect in spare_list:
            if rect.bottom() < cr.top() or rect.top() > cr.bottom():
                continue
            hov   = self._hovered_key == f'spare:{kind}'
            col   = QColor(*_BUG_COLOR.get(kind, (200, 200, 200)))
            tint  = QColor(col); tint.setAlpha(35 if hov else 18)
            p.setPen(QPen(col.darker(130), 1))
            p.setBrush(QBrush(tint))
            p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

            # Wing icon
            cx, cy = rect.left() + 24, rect.center().y()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(cx - 10, cy - 4, 10, 7)
            p.drawEllipse(cx + 1, cy - 4, 10, 7)
            p.setBrush(QBrush(col.darker(160)))
            p.drawEllipse(cx - 3, cy - 5, 6, 10)

            # Label + desc
            f = QFont('Segoe UI Variable', 1); f.setPixelSize(12); f.setBold(True)
            p.setFont(f)
            p.setPen(_C_TEXT)
            p.drawText(QRect(cx + 16, rect.top() + 6, rect.width() - cx - 16, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f'{_BUG_LABELS.get(kind, kind)}  ×{count}')
            f2 = QFont('Segoe UI Variable', 1); f2.setPixelSize(10)
            p.setFont(f2)
            p.setPen(_C_MUTED)
            p.drawText(QRect(cx + 16, rect.top() + 24, rect.width() - cx - 50, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       _BUG_DESC.get(kind, ''))

            # "fill slot" hint on hover
            if hov:
                f3 = QFont('Segoe UI Variable', 1); f3.setPixelSize(10)
                p.setFont(f3)
                p.setPen(QColor(col.red(), col.green(), col.blue(), 200))
                p.drawText(QRect(rect.right() - 80, rect.top() + 4, 76, rect.height() - 8),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           '+ fill slot →')

        if not spare_list:
            # Nothing unequipped
            after_b = max((r.bottom() for _, r in b_rects), default=cr.top()) + 14
            f = QFont('Segoe UI Variable', 1); f.setPixelSize(12)
            p.setFont(f)
            p.setPen(_C_MUTED)
            p.drawText(QRect(cr.left(), after_b, cr.width(), 28),
                       Qt.AlignmentFlag.AlignCenter,
                       'buy bugs in the Shop · Carrots tab')

    def _hit_key_loadout(self, pos: QPoint, cr: QRect) -> str | None:
        if not cr.contains(pos):
            return None
        slot_rects = self._slot_box_rects(cr)
        for i, (_, rect) in enumerate(slot_rects['abug']):
            if rect.contains(pos):
                return f'aslot:{i}'
        for i, (_, rect) in enumerate(slot_rects['bbug']):
            if rect.contains(pos):
                return f'bslot:{i}'
        spare_list = self._spare_bug_rects(cr, slot_rects)
        for kind, _count, rect in spare_list:
            if rect.contains(pos):
                return f'spare:{kind}'
        return None

    def _handle_loadout_click(self, key: str) -> None:
        inv = self._get_inventory()
        a_slots = list(inv.get('abug_slots', [None] * ABUG_SLOT_COUNT))
        b_slots = list(inv.get('bbug_slots', [None] * BBUG_SLOT_COUNT))
        while len(a_slots) < ABUG_SLOT_COUNT: a_slots.append(None)
        while len(b_slots) < BBUG_SLOT_COUNT: b_slots.append(None)

        if key.startswith('aslot:'):
            i = int(key.split(':')[1])
            if 0 <= i < ABUG_SLOT_COUNT and a_slots[i] is not None:
                a_slots[i] = None   # eject → back to spare pool
                inv['abug_slots'] = a_slots
                self._save_inventory(inv)

        elif key.startswith('bslot:'):
            i = int(key.split(':')[1])
            if 0 <= i < BBUG_SLOT_COUNT and b_slots[i] is not None:
                b_slots[i] = None
                inv['bbug_slots'] = b_slots
                self._save_inventory(inv)

        elif key.startswith('spare:'):
            kind  = key.split(':')[1]
            is_ab = kind in ABUG_KINDS
            slots = a_slots if is_ab else b_slots
            try:
                idx = slots.index(None)   # first empty slot
                slots[idx] = kind
                if is_ab:
                    inv['abug_slots'] = a_slots
                else:
                    inv['bbug_slots'] = b_slots
                self._save_inventory(inv)
            except ValueError:
                pass   # no empty slot available

    # ── Render ─────────────────────────────────────────────────────────────────
    def _render_buf(self) -> QPixmap:
        buf = QPixmap(_W, _H)
        buf.fill(Qt.GlobalColor.transparent)
        p = QPainter(buf)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # ── Chrome — clean Win11 white frame ─────────────────────────────────
        paint_window_chrome(p, QRect(0, 0, _W, _H), 'garden',
                            close_rect=self._close_rect(),
                            close_hover=self._hovered_key == '__close__',
                            pin_rect=self._pin_rect(),
                            pin_active=self._pinned,
                            pin_hover=self._hovered_key == '__pin__')

        # ── Tab bar ─────────────────────────────────────────────────────────────
        tb  = self._tab_bar_rect()
        tw  = tb.width() // 2
        _TABS_DEF = [('Seeds & Flowers', 0), ('Bug Inventory', 1)]
        for label, idx in _TABS_DEF:
            tr   = QRect(tb.left() + idx * tw, tb.top(), tw, tb.height())
            active = self._active_tab == idx
            hov    = self._hovered_key == f'tab:{idx}'
            p.setPen(Qt.PenStyle.NoPen)
            if active:
                p.setBrush(QBrush(QColor(0x46, 0x82, 0xE6, 22 if not theme.is_dark() else 50)))
            elif hov:
                p.setBrush(QBrush(QColor(0, 0, 0, 10)))
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(tr).adjusted(1, 1, -1, -1), 7, 7)
            if active:
                p.setBrush(QBrush(QColor(0x46, 0x82, 0xE6)))
                p.drawRoundedRect(QRectF(tr.left() + 10, tr.bottom() - 3, tw - 20, 3), 1.5, 1.5)
            ft = QFont('Segoe UI Variable', 1); ft.setPixelSize(12)
            ft.setBold(active)
            p.setFont(ft)
            p.setPen(QColor(0x46, 0x82, 0xE6) if active else _C_MUTED)
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, label)
        # Divider between tab bar and content
        p.setPen(QPen(_C_BORDER_LT, 1))
        p.drawLine(tb.left(), tb.bottom() + 3, tb.right(), tb.bottom() + 3)

        cr = self._content_rect()
        p.setClipRect(cr.adjusted(-2, -2, 2, 2))

        if self._active_tab == 1:
            self._draw_loadout_tab(p, cr)
            p.setClipping(False)
            p.end()
            return buf

        seeds = self._plantable_seeds()

        # ── Seeds section header ─────────────────────────────────────────────
        self._draw_section_header(
            p,
            QRect(cr.left(), cr.top(), cr.width(), _HDR_H),
            f'Seeds ready to plant  ({len(seeds)})',
        )

        if not seeds:
            f = QFont('Segoe UI Variable', 1); f.setPixelSize(13); f.setBold(False)
            p.setFont(f)
            p.setPen(_C_MUTED)
            p.drawText(
                QRect(cr.left(), cr.top() + _HDR_H + 8, cr.width(), 28),
                Qt.AlignmentFlag.AlignCenter,
                'add tasks with due dates in the board ✦',
            )

        # ── Seed rows ────────────────────────────────────────────────────────
        for _i, t, row, btn in self._seed_rects():
            if row.bottom() < cr.top() or row.top() > cr.bottom():
                continue
            hov = self._hovered_key == f'seed:{_i}'

            # White card
            r = QRectF(row).adjusted(0.5, 0.5, -0.5, -0.5)
            if hov:
                p.setBrush(QBrush(_C_CARD_HOV))
                p.setPen(QPen(QColor(0x46, 0x82, 0xE6, 80), 1))
            else:
                p.setBrush(QBrush(_C_CARD))
                p.setPen(QPen(_C_BORDER_LT, 1))
            p.drawRoundedRect(r, 10, 10)

            # ── Drag grip: 2×3 blue dots ─────────────────────────────────────
            p.setPen(Qt.PenStyle.NoPen)
            gx  = row.left() + 8
            gy  = row.center().y()
            dot_a = 210 if hov else 110
            for _ddx in (0, 4):
                for _ddy in (-5, 0, 5):
                    p.setBrush(QBrush(QColor(0x46, 0x82, 0xE6, dot_a)))
                    p.drawEllipse(gx + _ddx, gy + _ddy - 1, 3, 3)

            # "drag to plant" label on hover
            if hov:
                f2 = QFont('Segoe UI Variable', 1); f2.setPixelSize(9)
                p.setFont(f2)
                p.setPen(QColor(0x46, 0x82, 0xE6, 200))
                p.drawText(
                    QRect(row.left() + 1, row.bottom() - 14, 34, 12),
                    Qt.AlignmentFlag.AlignCenter,
                    '↓ drag',
                )

            # Seed icon
            self._draw_seed_icon(p, row.left() + 26, row.center().y(), 0.1)

            # Task text — elide if too long
            text_w = row.width() - 42 - 70
            f3 = QFont('Segoe UI Variable', 1); f3.setPixelSize(14); f3.setBold(True)
            p.setFont(f3)
            p.setPen(_C_TEXT)
            elided = p.fontMetrics().elidedText(
                t.get('text', ''), Qt.TextElideMode.ElideRight, text_w)
            p.drawText(
                QRect(row.left() + 38, row.top() + 8, text_w, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )

            # Due badge pill
            badge_txt, badge_col = _due_label(t.get('due'))
            if badge_txt:
                fb = QFont('Segoe UI Variable', 1); fb.setPixelSize(11)
                p.setFont(fb)
                bw = p.fontMetrics().horizontalAdvance(badge_txt) + 14
                badge_r = QRect(row.left() + 34, row.top() + row.height() - 20, bw, 16)
                p.setBrush(QBrush(badge_col.lighter(175)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(badge_r, 8, 8)
                p.setPen(badge_col.darker(140))
                p.drawText(badge_r, Qt.AlignmentFlag.AlignCenter, badge_txt)

            # Plant button
            hov_btn = self._hovered_key == f'plant:{_i}'
            p.setBrush(QBrush(_C_LAV.darker(115) if hov_btn else _C_LAV))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(btn).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            fp = QFont('Segoe UI Variable', 1); fp.setPixelSize(13); fp.setBold(True)
            p.setFont(fp)
            p.setPen(QColor(255, 255, 255))
            p.drawText(btn, Qt.AlignmentFlag.AlignCenter, '+ plant')

        # ── Planted flowers section header ────────────────────────────────────
        flowers      = self._planted_flowers()
        flow_sec_top = (cr.top() + _HDR_H + 4
                        + self._seeds_block_h()
                        + _SEC_GAP
                        - self._scroll_y)
        if cr.top() - _HDR_H <= flow_sec_top <= cr.bottom():
            self._draw_section_header(
                p,
                QRect(cr.left(), flow_sec_top, cr.width(), _HDR_H),
                f'Planted  ({len(flowers)})',
            )

        # ── Flower rows ───────────────────────────────────────────────────────
        for _i, tf, row, del_btn in self._flower_rects():
            if row.bottom() < cr.top() or row.top() > cr.bottom():
                continue
            bf     = tf.bloom_frac()
            wilted = tf.done
            hov    = self._hovered_key == f'flower:{_i}'

            # White card
            r = QRectF(row).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setBrush(QBrush(_C_CARD_HOV if hov else _C_CARD))
            p.setPen(QPen(_C_BORDER_LT, 1))
            p.drawRoundedRect(r, 10, 10)

            # Tiny bloom icon
            self._draw_seed_icon(p, row.left() + 18, row.center().y(),
                                 0.0 if wilted else bf)

            # Task text — elide if too long
            text_w = row.width() - 38 - 36
            ft = QFont('Segoe UI Variable', 1)
            ft.setPixelSize(14); ft.setBold(not wilted)
            p.setFont(ft)
            p.setPen(_C_MUTED if wilted else _C_TEXT)
            elided = p.fontMetrics().elidedText(
                tf.task_text, Qt.TextElideMode.ElideRight, text_w)
            p.drawText(
                QRect(row.left() + 34, row.top() + 8, text_w, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )

            # Status badge
            if wilted:
                status = 'done ✓';          sc = _C_MUTED
            elif bf >= 1.0 and tf.is_past_due():
                status = 'overdue! ✦';      sc = _C_AMBER
            elif bf >= 1.0:
                status = 'fully bloomed ✦'; sc = _C_LAV
            else:
                pct    = int(bf * 100)
                status = f'blooming… {pct}%'; sc = _C_MUTED
            fs = QFont('Segoe UI Variable', 1); fs.setPixelSize(11)
            p.setFont(fs)
            p.setPen(sc)
            p.drawText(
                QRect(row.left() + 34, row.top() + row.height() - 20,
                      row.width() - 70, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                status,
            )

            # ── Delete button — ✕ in rounded square, red on hover ────────────
            hov_del = self._hovered_key == f'del:{_i}'
            p.setBrush(QBrush(_C_ROSE if hov_del else QColor(0x00, 0x00, 0x00, 15)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(del_btn), 6, 6)
            cx  = del_btn.center().x()
            cy  = del_btn.center().y()
            d   = 5
            p.setPen(QPen(QColor(255, 255, 255) if hov_del else _C_MUTED, 1.5))
            p.drawLine(cx - d, cy - d, cx + d, cy + d)
            p.drawLine(cx + d, cy - d, cx - d, cy + d)

        p.setClipping(False)
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

    # ── Hit testing ────────────────────────────────────────────────────────────
    def _hit_key(self, pos: QPoint) -> str | None:
        if self._close_rect().contains(pos):
            return '__close__'
        if self._pin_rect().contains(pos):
            return '__pin__'
        # Tab bar
        tb = self._tab_bar_rect()
        if tb.contains(pos):
            tw  = tb.width() // 2
            idx = (pos.x() - tb.left()) // tw
            return f'tab:{idx}'
        cr = self._content_rect()
        if self._active_tab == 1:
            return self._hit_key_loadout(pos, cr)
        if not cr.contains(pos):
            return None
        for _i, _t, row, btn in self._seed_rects():
            if btn.contains(pos):
                return f'plant:{_i}'
            if row.contains(pos):
                return f'seed:{_i}'
        for _i, _tf, row, del_btn in self._flower_rects():
            if del_btn.contains(pos):
                return f'del:{_i}'
            if row.contains(pos):
                return f'flower:{_i}'
        return None

    # ── Input ──────────────────────────────────────────────────────────────────
    def mouseMoveEvent(self, e) -> None:
        # ── Seed drag threshold / tracking ──────────────────────────────
        if (self._drag_pending is not None
                and e.buttons() & Qt.MouseButton.LeftButton
                and self._drag_start_pos is not None):
            if (e.pos() - self._drag_start_pos).manhattanLength() > 8:
                # Threshold crossed — activate drag
                if self._dragging_seed is None:
                    self._dragging_seed  = self._drag_pending
                    self._drag_pending   = None
                    self._drag_hint      = _SeedDragHint()
                    self._drag_hint.show()
                    self.grabMouse()
                if self._drag_hint:
                    self._drag_hint.move_to_cursor(e.globalPosition().toPoint())
            return

        if self._dragging_seed is not None and self._drag_hint:
            self._drag_hint.move_to_cursor(e.globalPosition().toPoint())
            return

        key = self._hit_key(e.pos())
        if key != self._hovered_key:
            self._hovered_key = key
            self.update()
        if self._drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(self.pos() + e.pos() - self._drag_offset)

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        key = self._hit_key(e.pos())
        if key == '__close__':
            self.close_animated(); return
        if key == '__pin__':
            return  # handled on release
        if key is None:
            if e.pos().y() <= HEADER_H:
                self._drag_offset = e.pos()
            return
        if key.startswith('tab:'):
            return  # handled on release
        if key.startswith('aslot:') or key.startswith('bslot:') or key.startswith('spare:'):
            return  # loadout clicks handled on release
        if key.startswith('plant:'):
            idx = int(key.split(':')[1])
            seeds = self._plantable_seeds()
            if 0 <= idx < len(seeds):
                t = seeds[idx]
                self._on_seed_plant(t['text'], t.get('due', ''))
                self.update()
            return
        if key.startswith('del:'):
            # Handled on release to avoid accidental deletions
            return
        if key.startswith('seed:'):
            # Start potential drag gesture
            idx = int(key.split(':')[1])
            seeds = self._plantable_seeds()
            if 0 <= idx < len(seeds):
                self._drag_pending   = seeds[idx]
                self._drag_start_pos = e.pos()
            return
        if e.pos().y() <= HEADER_H:
            self._drag_offset = e.pos()

    def mouseReleaseEvent(self, e) -> None:
        # ── End seed drag ────────────────────────────────────────────────
        if self._dragging_seed is not None:
            self.releaseMouse()
            if self._drag_hint:
                self._drag_hint.close()
                self._drag_hint = None
            gp = e.globalPosition().toPoint()
            self._on_seed_plant(
                self._dragging_seed['text'],
                self._dragging_seed.get('due', ''),
                gp.x(),
                gp.y(),
            )
            self._dragging_seed  = None
            self._drag_pending   = None
            self._drag_start_pos = None
            self.update()
            return

        self._drag_pending   = None
        self._drag_start_pos = None
        self._drag_offset    = None

        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._close_rect().contains(e.pos()):
            self.close_animated()
        elif self._pin_rect().contains(e.pos()):
            self._toggle_pin()
        else:
            key = self._hit_key(e.pos())
            if key and key.startswith('tab:'):
                idx = int(key.split(':')[1])
                if idx in (0, 1):
                    self._active_tab = idx
                    self._scroll_y   = 0
                    self.update()
            elif key and (key.startswith('aslot:') or key.startswith('bslot:')
                          or key.startswith('spare:')):
                self._handle_loadout_click(key)
                self.update()
            elif key and key.startswith('del:'):
                idx = int(key.split(':')[1])
                flowers = self._planted_flowers()
                if 0 <= idx < len(flowers):
                    self._on_task_flower_delete(flowers[idx].task_text)
                    self.update()

    def wheelEvent(self, e) -> None:
        delta   = -int(e.angleDelta().y() / 2)
        seeds   = len(self._plantable_seeds())
        flowers = len(self._planted_flowers())
        total_h = (seeds + flowers) * _ROW_H + 2 * _HDR_H + _SEC_GAP + 20
        cr      = self._content_rect()
        max_s   = max(0, total_h - cr.height())
        self._scroll_y = max(0, min(self._scroll_y + delta, max_s))
        self.update()

    def leaveEvent(self, _e) -> None:
        if self._hovered_key:
            self._hovered_key = None
            self.update()

    def _cancel_drag(self) -> None:
        """Abort any active seed drag cleanly."""
        if self._dragging_seed is not None:
            try:
                self.releaseMouse()
            except Exception:
                pass
            if self._drag_hint:
                self._drag_hint.close()
                self._drag_hint = None
            self._dragging_seed  = None
        self._drag_pending   = None
        self._drag_start_pos = None

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close_animated()
        else:
            super().keyPressEvent(e)

    # ── Pin ────────────────────────────────────────────────────────────────────
    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        notify_pin_toggled(self, self._pinned)
        self.update()

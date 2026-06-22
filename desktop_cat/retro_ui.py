"""
Shared retro-OS style tokens and widgets for the SAO Hub and all sub-windows.

Design language:
  - Flat colours, 1px black borders, slightly rounded corners.
  - Classic title bar (darker grey strip, bold title, ✕ close).
  - White/light-grey bodies, big readable pixel text.
  - No orange/brown tint, no muddy pixel textures.

Use `paint_window_chrome(painter, rect, title, close_rect=...)` from a QWidget's
paintEvent to get a consistent frame. Use `RetroButton` for the big stacked
hub / panel buttons.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import (Qt, QRect, QRectF, QPoint, QSize, QEvent, QObject,
                             QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal)
from PyQt6.QtGui     import (QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
                             QPainterPath, QLinearGradient)

from desktop_cat.theme import theme


# ── Colour tokens ─────────────────────────────────────────────────────────────
# These QColor instances are MUTATED in place by `_refresh_palette()` whenever
# the theme flips, so module-level imports like `from retro_ui import C_BG` in
# other files keep seeing the live values.  Initial values match the light
# palette; `_refresh_palette()` is called once at module load (after defs) to
# pick up whatever mode `theme` was loaded into.
C_BG         = QColor(0xF7, 0xF7, 0xFA)              # window body
C_BG_ALT     = QColor(0xFF, 0xFF, 0xFF)              # input/button fill
C_HEADER     = QColor(0xEC, 0xEC, 0xF1)              # title bar tint
C_HEADER_DK  = QColor(0x00, 0x00, 0x00, 24)          # header divider
C_BORDER     = QColor(0x00, 0x00, 0x00, 36)          # outer hairline
C_BORDER_LT  = QColor(0x00, 0x00, 0x00, 18)          # inner dividers
C_TEXT       = QColor(0x1F, 0x1F, 0x21)              # primary text
C_TEXT_MUTED = QColor(0x60, 0x60, 0x68)              # muted body text
C_ACCENT     = QColor(0x46, 0x82, 0xE6)              # Windows blue
C_ACCENT_LT  = QColor(0x46, 0x82, 0xE6, 32)          # pale blue hover wash
C_DANGER     = QColor(0xE8, 0x4C, 0x4C)              # close hover red
C_SUCCESS    = QColor(0x4F, 0xB3, 0x86)              # green confirmation

# Extra modern tokens (used by chrome + buttons)
C_HOVER      = QColor(0x00, 0x00, 0x00, 16)
C_PRESS      = QColor(0x00, 0x00, 0x00, 28)
C_TEXT_DIM   = QColor(0x8A, 0x8A, 0x92)


def _mut(c: QColor, r: int, g: int, b: int, a: int = 255) -> None:
    """Mutate an existing QColor in place — preserves identity for re-exports."""
    c.setRgb(r, g, b, a)


def _refresh_palette() -> None:
    """Re-tune the module's QColor tokens based on current theme.

    All tokens above are imported by name from many modules; we mutate them
    in place so existing references stay live without re-importing.
    """
    if theme.is_dark():
        _mut(C_BG,         0x22, 0x23, 0x28)
        _mut(C_BG_ALT,     0x2D, 0x2E, 0x33)
        _mut(C_HEADER,     0x18, 0x19, 0x1D)
        _mut(C_HEADER_DK,  0xFF, 0xFF, 0xFF, 24)
        _mut(C_BORDER,     0xFF, 0xFF, 0xFF, 30)
        _mut(C_BORDER_LT,  0xFF, 0xFF, 0xFF, 18)
        _mut(C_TEXT,       0xF0, 0xF0, 0xF2)
        _mut(C_TEXT_MUTED, 0xA8, 0xA8, 0xB0)
        _mut(C_TEXT_DIM,   0x70, 0x70, 0x78)
        _mut(C_HOVER,      0xFF, 0xFF, 0xFF, 22)
        _mut(C_PRESS,      0xFF, 0xFF, 0xFF, 38)
        _mut(C_ACCENT_LT,  0x46, 0x82, 0xE6, 50)
    else:
        _mut(C_BG,         0xF7, 0xF7, 0xFA)
        _mut(C_BG_ALT,     0xFF, 0xFF, 0xFF)
        _mut(C_HEADER,     0xEC, 0xEC, 0xF1)
        _mut(C_HEADER_DK,  0x00, 0x00, 0x00, 24)
        _mut(C_BORDER,     0x00, 0x00, 0x00, 36)
        _mut(C_BORDER_LT,  0x00, 0x00, 0x00, 18)
        _mut(C_TEXT,       0x1F, 0x1F, 0x21)
        _mut(C_TEXT_MUTED, 0x60, 0x60, 0x68)
        _mut(C_TEXT_DIM,   0x8A, 0x8A, 0x92)
        _mut(C_HOVER,      0x00, 0x00, 0x00, 16)
        _mut(C_PRESS,      0x00, 0x00, 0x00, 28)
        _mut(C_ACCENT_LT,  0x46, 0x82, 0xE6, 32)
    # Accent / danger / success are theme-stable — left at construction values.


_refresh_palette()
theme.changed.connect(_refresh_palette)

# Layout constants. BORDER_PX is now a *visual* hairline (kept for any
# legacy callers that read it for layout math).
BORDER_PX   = 1
RADIUS_PX   = 10         # rounded corners for the panel
HEADER_H    = 30
PAD         = 12
BUTTON_H    = 44


# ── Fonts ─────────────────────────────────────────────────────────────────────
def _modern_family() -> str:
    f = QFont('Segoe UI Variable', 1)
    if f.exactMatch():
        return 'Segoe UI Variable'
    return 'Segoe UI'


def font_body(size: int = 12, bold: bool = False) -> QFont:
    f = QFont(_modern_family(), 1)
    f.setPixelSize(size)
    f.setBold(bold)
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return f


def font_title(size: int = 14) -> QFont:
    f = QFont(_modern_family(), 1)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight.DemiBold)
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return f


# ── Frame painter ─────────────────────────────────────────────────────────────
def paint_window_chrome(p: QPainter, rect: QRect, title: str,
                        close_rect: QRect | None = None,
                        close_hover: bool = False,
                        pin_rect: QRect | None = None,
                        pin_active: bool = False,
                        pin_hover: bool = False) -> QRect:
    """
    Paint a modern, antialiased, rounded-corner window frame:
      - Soft white surface with rounded corners (RADIUS_PX)
      - Subtle tinted header band with a 1px divider underneath
      - Left-aligned title in DemiBold sans-serif
      - Modern square-rounded close (✕) and optional pin button

    Returns the inner content rect (below the header).
    """
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    body = QRectF(rect)
    radius = RADIUS_PX

    # Clip to rounded shape so the header tint can paint a flat rect
    # without spilling past the corners.
    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    p.save()
    p.setClipPath(path)

    # 1. Body fill
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(C_BG))
    p.drawRect(body)

    # 2. Header band — gentle vertical gradient
    header = QRectF(body.x(), body.y(), body.width(), HEADER_H)
    grad = QLinearGradient(header.topLeft(), header.bottomLeft())
    grad.setColorAt(0.0, C_HEADER)
    grad.setColorAt(1.0, QColor(C_HEADER.red(), C_HEADER.green(),
                                C_HEADER.blue(), 180))
    p.setBrush(QBrush(grad))
    p.drawRect(header)

    # 3. Header divider
    p.setPen(QPen(C_HEADER_DK, 1))
    y_div = int(body.y()) + HEADER_H - 1
    p.drawLine(int(body.x()), y_div, int(body.right()), y_div)

    p.restore()

    # 4. Outer hairline border on the rounded shape
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    # 5. Title — left-aligned, modern
    title_font = font_title(13)
    p.setFont(title_font)
    p.setPen(C_TEXT)
    title_x = rect.x() + 14
    title_w = (close_rect.x() - 8 - title_x) if close_rect is not None \
        else rect.width() - 28
    p.drawText(QRect(title_x, rect.y(), max(0, title_w), HEADER_H),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               title)

    # 6. Close button
    if close_rect is not None:
        _paint_close_button(p, close_rect, close_hover)

    # 7. Pin button (optional)
    if pin_rect is not None:
        _paint_pin_button(p, pin_rect, pin_active, pin_hover)

    # Inner content rect (below header)
    inner = QRect(
        rect.x(),
        rect.y() + HEADER_H,
        rect.width(),
        rect.height() - HEADER_H,
    )
    return inner


def pin_button_rect(window_rect: QRect) -> QRect:
    """Rect of the 📌 pin button, just left of the ✕ button. Same size."""
    cr = close_button_rect(window_rect)
    return QRect(cr.x() - cr.width() - 4, cr.y(), cr.width(), cr.height())


def _paint_close_button(p: QPainter, rect: QRect, hover: bool) -> None:
    """Modern close button — rounded square, fills red on hover."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    if hover:
        p.setBrush(QBrush(C_DANGER))
        p.drawRoundedRect(QRectF(rect), 6, 6)
        p.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 1.6))
    else:
        p.setPen(QPen(C_TEXT_MUTED, 1.6))
    cx, cy = rect.center().x(), rect.center().y()
    d = max(4, min(6, rect.width() // 4))
    p.drawLine(cx - d, cy - d, cx + d, cy + d)
    p.drawLine(cx + d, cy - d, cx - d, cy + d)


def _paint_pin_button(p: QPainter, rect: QRect,
                      active: bool, hover: bool) -> None:
    """Modern pin button — fills accent blue when pinned."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    if active:
        p.setBrush(QBrush(C_ACCENT))
        p.drawRoundedRect(QRectF(rect), 6, 6)
        ink = QColor(0xFF, 0xFF, 0xFF)
    elif hover:
        p.setBrush(QBrush(C_HOVER))
        p.drawRoundedRect(QRectF(rect), 6, 6)
        ink = C_TEXT
    else:
        ink = C_TEXT_MUTED
    cx, cy = rect.center().x(), rect.center().y()
    p.setPen(QPen(ink, 1.6))
    p.setBrush(QBrush(ink))
    p.drawEllipse(QRectF(cx - 3.5, cy - 5, 7, 7))
    p.drawLine(cx, cy + 2, cx, cy + 6)


def paint_pixel_chrome(p: QPainter, w: int, h: int,
                       header_h: int, border: int, title: str,
                       close_rect: QRect | None = None,
                       close_hover: bool = False,
                       body_color: QColor | None = None,
                       pin_rect: QRect | None = None,
                       pin_active: bool = False,
                       pin_hover: bool = False) -> None:
    """
    Paint modern, antialiased rounded chrome into rect (0, 0, w, h) using the
    caller's local header/border sizes — so existing content layouts don't
    have to change.
    """
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    bg = body_color if body_color is not None else C_BG
    radius = RADIUS_PX

    body = QRectF(0, 0, w, h)
    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    p.save()
    p.setClipPath(path)

    # Body fill
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(bg))
    p.drawRect(body)

    # Header band — gentle gradient
    header = QRectF(0, 0, w, header_h)
    grad = QLinearGradient(header.topLeft(), header.bottomLeft())
    grad.setColorAt(0.0, C_HEADER)
    grad.setColorAt(1.0, QColor(C_HEADER.red(), C_HEADER.green(),
                                C_HEADER.blue(), 180))
    p.setBrush(QBrush(grad))
    p.drawRect(header)

    # Header divider hairline
    p.setPen(QPen(C_HEADER_DK, 1))
    p.drawLine(0, header_h - 1, w, header_h - 1)

    p.restore()

    # Outer hairline border on the rounded shape
    p.setPen(QPen(C_BORDER, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    # Title — left-aligned modern
    p.setFont(font_title(13))
    p.setPen(C_TEXT)
    title_x = 14
    title_w = (close_rect.x() - 8 - title_x) if close_rect is not None \
        else (w - 28)
    p.drawText(QRect(title_x, 0, max(0, title_w), header_h),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               title)

    # Close button
    if close_rect is not None:
        _paint_close_button(p, close_rect, close_hover)

    # Pin button (optional)
    if pin_rect is not None:
        _paint_pin_button(p, pin_rect, pin_active, pin_hover)


def close_button_rect(window_rect: QRect) -> QRect:
    """Rect of the ✕ button inside the header, right-aligned. Rounded square."""
    size = 22
    return QRect(
        window_rect.x() + window_rect.width() - size - 6,
        window_rect.y() + (HEADER_H - size) // 2,
        size, size,
    )


# ── Retro button widget ───────────────────────────────────────────────────────
class RetroButton(QWidget):
    """
    Big flat retro-OS button. Clean white fill, 1px border, bold pixel label,
    optional leading icon painter (callable(painter, QRect)).
    """
    clicked = pyqtSignal()

    def __init__(self,
                 label: str,
                 icon_painter: Callable[[QPainter, QRect], None] | None = None,
                 *,
                 accent: QColor | None = None,
                 height: int = BUTTON_H,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        self._icon  = icon_painter
        self._accent = accent
        self._hover = False
        self._pressed = False
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(240, BUTTON_H)

    def setLabel(self, s: str) -> None:
        self._label = s
        self.update()

    def enterEvent(self, e) -> None:
        self._hover = True; self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        # NOTE: don't reset _pressed here. On Windows with translucent
        # frameless tool windows, the cursor can briefly leave a child
        # widget's hit rect mid-click (especially during opacity / scale
        # animations), and resetting _pressed on Leave would eat the
        # release and swallow the click. mouseReleaseEvent already
        # re-checks rect().contains(), so a genuine drag-off still
        # correctly fails to click.
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True; self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            if self.rect().contains(e.pos()):
                self.clicked.emit()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Modern flat surface: hover/press washes, hairline border on hover.
        if self._pressed:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(C_PRESS))
            p.drawRoundedRect(r, 8, 8)
        elif self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(C_HOVER))
            p.drawRoundedRect(r, 8, 8)

        if self._hover or self._pressed:
            p.setPen(QPen(C_BORDER, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 8, 8)

        lx = self.rect().x() + 12

        # Accent pill + dot
        if self._accent is not None:
            pill_h = 22
            pill = QRectF(lx, (self.height() - pill_h) / 2, 4, pill_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._accent))
            p.drawRoundedRect(pill, 2, 2)

            dot = QRectF(lx + 14, (self.height() - 10) / 2, 10, 10)
            p.setBrush(QBrush(self._accent.lighter(115)))
            p.drawEllipse(dot)
            p.setBrush(QBrush(self._accent))
            p.drawEllipse(dot.adjusted(2.5, 2.5, -2.5, -2.5))
            lx = int(dot.right()) + 12

        # Optional icon
        if self._icon is not None:
            icon_rect = QRect(lx, self.rect().center().y() - 10, 20, 20)
            p.save()
            self._icon(p, icon_rect)
            p.restore()
            lx = icon_rect.right() + 10

        # Label
        p.setPen(C_TEXT)
        p.setFont(font_title(14))
        tx = QRect(lx, self.rect().y(),
                   self.rect().width() - (lx - self.rect().x()) - 30,
                   self.rect().height())
        p.drawText(tx,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._label)

        # Trailing chevron
        cx = self.rect().right() - 16
        cy = self.rect().center().y()
        p.setPen(QPen(C_TEXT_DIM, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(cx - 3, cy - 4, cx + 1, cy)
        p.drawLine(cx + 1, cy, cx - 3, cy + 4)


# ── HubEcosystem — per-window idle-fade state ────────────────────────────────
class HubEcosystem(QObject):
    """
    Independent dim-state for each SAO window.

    Behaviour:
      - Hovering window A restores only A (B, C, D are unaffected).
      - When the cursor leaves window A, A starts its own 5-second countdown
        and then fades to DIM_OPACITY on its own.
      - Pinned windows (_pinned=True on the widget) never auto-dim regardless
        of cursor position.

    Use via the module-level `register_sao_window(widget)` helper.
    """
    _inst: 'HubEcosystem | None' = None

    DIM_OPACITY  = 0.35
    DIM_DELAY_MS = 5000   # 5 seconds idle before fade
    FADE_MS      = 400
    RESTORE_MS   = 120

    @classmethod
    def instance(cls) -> 'HubEcosystem':
        if cls._inst is None:
            cls._inst = HubEcosystem()
        return cls._inst

    def __init__(self) -> None:
        super().__init__()
        self._widgets:    set[QWidget]                    = set()
        self._hovered:    set[QWidget]                    = set()
        self._anims:      dict[int, QPropertyAnimation]   = {}
        self._dim_timers: dict[int, QTimer]               = {}

    # ── Registration ──────────────────────────────────────────────────────────
    def register(self, w: QWidget) -> None:
        if w in self._widgets:
            return
        self._widgets.add(w)
        w.installEventFilter(self)
        w.destroyed.connect(lambda _=None, ww=w: self._on_destroyed(ww))

    def _on_destroyed(self, w: QWidget) -> None:
        self._widgets.discard(w)
        self._hovered.discard(w)
        self._anims.pop(id(w), None)
        t = self._dim_timers.pop(id(w), None)
        if t is not None:
            try:
                t.stop()
            except RuntimeError:
                pass

    # ── Pin toggle callback ───────────────────────────────────────────────────
    def on_pin_toggled(self, w: QWidget, pinned: bool) -> None:
        """Call after toggling w._pinned so the ecosystem reacts immediately."""
        if pinned:
            # Pinned → cancel any pending dim, snap back to full opacity.
            self._cancel_dim_timer(w)
            self._cancel_anim(w)
            w.setWindowOpacity(1.0)
        else:
            # Unpinned → if cursor is not on the window, start the idle timer.
            if w not in self._hovered:
                self._start_dim_timer(w)

    # ── Event filter ──────────────────────────────────────────────────────────
    def eventFilter(self, obj, e):
        if obj not in self._widgets:
            return False
        t = e.type()
        if t == QEvent.Type.Enter:
            self._on_enter(obj)
        elif t == QEvent.Type.Leave:
            self._on_leave(obj)
        elif t == QEvent.Type.Show:
            self._cancel_dim_timer(obj)
            self._cancel_anim(obj)
            obj.setWindowOpacity(1.0)
            from PyQt6.QtGui import QCursor
            if obj.frameGeometry().contains(QCursor.pos()):
                self._on_enter(obj)
            else:
                self._on_leave(obj)   # start the idle countdown immediately
        elif t == QEvent.Type.Hide:
            self._hovered.discard(obj)
            self._cancel_dim_timer(obj)
            self._cancel_anim(obj)
        elif t == QEvent.Type.MouseButtonPress:
            self._on_enter(obj)   # safety net: any click → restore this window
        return False

    # ── Per-widget state transitions ──────────────────────────────────────────
    def _on_enter(self, w: QWidget) -> None:
        self._hovered.add(w)
        self._cancel_dim_timer(w)
        # Restore only THIS window — others stay at whatever opacity they have.
        if w.windowOpacity() < 0.999:
            self._animate(w, 1.0, self.RESTORE_MS)

    def _on_leave(self, w: QWidget) -> None:
        self._hovered.discard(w)
        if not getattr(w, '_pinned', False):
            self._start_dim_timer(w)

    def _start_dim_timer(self, w: QWidget) -> None:
        wid = id(w)
        t = self._dim_timers.get(wid)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(self.DIM_DELAY_MS)
            t.timeout.connect(lambda ww=w: self._dim_widget(ww))
            self._dim_timers[wid] = t
        t.start()   # restart countdown if already running

    def _cancel_dim_timer(self, w: QWidget) -> None:
        t = self._dim_timers.get(id(w))
        if t is not None:
            t.stop()

    def _dim_widget(self, w: QWidget) -> None:
        if (w not in self._widgets
                or not w.isVisible()
                or w in self._hovered
                or getattr(w, '_pinned', False)
                or getattr(w, '_closing', False)):
            return
        self._animate(w, self.DIM_OPACITY, self.FADE_MS)

    def _animate(self, w: QWidget, target: float, ms: int) -> None:
        self._cancel_anim(w)
        a = QPropertyAnimation(w, b'windowOpacity', w)
        a.setDuration(ms)
        a.setStartValue(w.windowOpacity())
        a.setEndValue(target)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.start()
        self._anims[id(w)] = a

    def _cancel_anim(self, w: QWidget) -> None:
        prev = self._anims.pop(id(w), None)
        if prev is not None:
            prev.stop()
            prev.deleteLater()   # Fully remove from Qt's object tree so it cannot
                                 # interfere with subsequent QPropertyAnimations that
                                 # target the same property on the same widget.


def register_sao_window(widget: QWidget) -> None:
    """Register a widget with the shared SAO hub auto-dim ecosystem."""
    HubEcosystem.instance().register(widget)


def notify_pin_toggled(widget: QWidget, pinned: bool) -> None:
    """Call after toggling widget._pinned so the ecosystem reacts."""
    HubEcosystem.instance().on_pin_toggled(widget, pinned)


def cancel_window_dimming(widget: QWidget) -> None:
    """Cancel any ecosystem-managed dim/restore animation for this widget.

    Call at the very start of close_animated() to prevent the 'restore to
    full opacity' animation (triggered by MouseButtonPress in the event
    filter) from fighting the close animation on the same windowOpacity
    property — which is the root cause of windows appearing to freeze when
    clicking the close button.
    """
    eco = HubEcosystem.instance()
    eco._cancel_dim_timer(widget)
    eco._cancel_anim(widget)


# Backwards-compat alias: old call sites constructed `AutoDim(widget)` which
# just registered that widget in the shared ecosystem.
class AutoDim:  # pragma: no cover
    def __init__(self, widget: QWidget, **_ignored) -> None:
        register_sao_window(widget)


def configure_floating_panel(widget: QWidget) -> None:
    """
    Apply the flag combo we use for the hub and every sub-window:
      - Frameless
      - Stays on top (Tool windows don't appear in the taskbar)
      - Translucent background for rounded-corner painting

    IMPORTANT: we intentionally do NOT set WA_ShowWithoutActivating here.
    On Windows, a frameless translucent Tool window that never activates
    drops a huge fraction of mouse clicks — buttons feel dead. The hub
    needs to activate on show so its children receive reliable input.

    Sub-windows that shouldn't steal activation from the hub get the
    attribute applied individually via HubWindow._prepare_subwindow.

    Call once in __init__ before show().
    """
    widget.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool,
    )
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

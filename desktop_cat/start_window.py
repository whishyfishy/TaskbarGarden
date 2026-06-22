"""
Compact start-up gate for Desktop Cat.
Shown on every non-first-run launch: a tiny cute paper card with the
user's mini-me name and a big SPAWN button.
"""

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore    import Qt, QPoint, QRect, pyqtProperty, pyqtSignal
from PyQt6.QtCore    import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from PyQt6.QtGui     import QPainter, QPixmap, QColor, QFont, QPen

from desktop_cat.user_profile import load as profile_load, SKIN_TONES


_OPEN_MS         = 260
_CLOSE_MS        = 180
_POP_SCALE_START = 0.78

_W        = 260
_H        = 200
_BORDER   = 6
_PAD      = 18
_BTN_H    = 56

# cute paper palette (matches onboarding)
_C_PAPER     = QColor(254, 250, 242)
_C_BORDER    = QColor(225, 205, 175)
_C_BORDER_IN = QColor(250, 240, 220)
_C_SHADOW    = QColor(175, 155, 130, 60)
_C_TITLE     = QColor(108,  78,  52)
_C_TEXT      = QColor( 84,  64,  48)
_C_MUTED     = QColor(155, 130, 104)
_C_ACCENT    = QColor(232, 140, 160)
_C_ACCENT_D  = QColor(198, 108, 130)
_C_CLOSE_HOV = QColor(230, 138, 138, 170)


class StartWindow(QWidget):
    spawn_requested = pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_W, _H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._profile: dict      = profile_load()
        self._anim_scale: float  = 1.0
        self._main_anim: QParallelAnimationGroup | None = None
        self._closing: bool      = False
        self._drag_offset: QPoint | None = None
        self._hovered_key: str | None     = None

    # ── Animatable scale ──────────────────────────────────────────────────────

    @pyqtProperty(float)
    def anim_scale(self) -> float:          # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                      # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    # ── Open / close ──────────────────────────────────────────────────────────

    def show_animated(self, x: int | None = None, y: int | None = None) -> None:
        if x is None or y is None:
            scr = QApplication.primaryScreen().geometry()
            x = scr.x() + (scr.width() - _W) // 2
            y = scr.y() + (scr.height() - _H) // 2
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

        scale_anim = QPropertyAnimation(self, b'anim_scale', self)
        scale_anim.setDuration(_CLOSE_MS)
        scale_anim.setStartValue(self._anim_scale)
        scale_anim.setEndValue(_POP_SCALE_START)
        scale_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        op_anim = QPropertyAnimation(self, b'windowOpacity', self)
        op_anim.setDuration(_CLOSE_MS)
        op_anim.setStartValue(self.windowOpacity())
        op_anim.setEndValue(0.0)
        op_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        if self._main_anim is not None:

            self._main_anim.stop()

        self._main_anim = QParallelAnimationGroup(self)
        self._main_anim.addAnimation(scale_anim)
        self._main_anim.addAnimation(op_anim)
        self._main_anim.finished.connect(self.close)
        self._main_anim.start()

    # ── Geometry ──────────────────────────────────────────────────────────────

    def _close_rect(self) -> QRect:
        return QRect(_W - _BORDER - 8 - 16, _BORDER + 6, 16, 16)

    def _spawn_rect(self) -> QRect:
        return QRect(_BORDER + _PAD, _H - _BORDER - _PAD - _BTN_H,
                     _W - 2 * (_BORDER + _PAD), _BTN_H)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _render_buf(self) -> QPixmap:
        buf = QPixmap(_W, _H)
        buf.fill(Qt.GlobalColor.transparent)
        p = QPainter(buf)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Shadow + paper
        p.setBrush(_C_SHADOW); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(3, 5, _W - 6, _H - 6, 14, 14)
        p.setBrush(_C_PAPER)
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(1, 1, _W - 2, _H - 2, 12, 12)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_C_BORDER_IN, 1))
        p.drawRoundedRect(4, 4, _W - 8, _H - 8, 9, 9)

        # Close
        cr = self._close_rect()
        hov_close = self._hovered_key == '__close__'
        if hov_close:
            p.setBrush(_C_CLOSE_HOV); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cr.adjusted(-1, -1, 1, 1))
        font = QFont('Courier New', 1)
        font.setPixelSize(11); font.setBold(False); p.setFont(font)
        p.setPen(_C_TITLE if hov_close else _C_MUTED)
        p.drawText(cr, Qt.AlignmentFlag.AlignCenter, 'x')

        # Greeting
        font.setPixelSize(13); font.setBold(True); p.setFont(font)
        p.setPen(_C_TITLE)
        user = self._profile.get('user_name', '') or 'friend'
        char = self._profile.get('char_name', 'sao') or 'sao'
        p.drawText(QRect(0, 22, _W, 22),
                   Qt.AlignmentFlag.AlignCenter, f'hi, {user} ✿')
        font.setPixelSize(11); font.setBold(False); p.setFont(font)
        p.setPen(_C_TEXT)
        p.drawText(QRect(0, 44, _W, 20),
                   Qt.AlignmentFlag.AlignCenter,
                   f'bring {char} to life?')

        # Little preview blob (skin-colored)
        skin = self._profile.get('skin_color', SKIN_TONES[1][0])
        skin_rgb = next((rgb for n, rgb in SKIN_TONES if n == skin),
                        SKIN_TONES[1][1])
        bx = _W // 2 - 14
        by = 70
        p.setBrush(QColor(*skin_rgb))
        p.setPen(QPen(_C_ACCENT_D, 1))
        p.drawEllipse(bx, by, 28, 28)
        p.setBrush(_C_TITLE); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(bx + 8,  by + 11, 3, 3)
        p.drawEllipse(bx + 17, by + 11, 3, 3)
        p.setPen(QPen(_C_TITLE, 1))
        p.drawArc(bx + 9, by + 15, 10, 6, 200 * 16, 140 * 16)

        # Spawn button
        sr = self._spawn_rect()
        hov = self._hovered_key == 'spawn'
        base = _C_ACCENT.darker(110) if hov else _C_ACCENT
        p.setBrush(base)
        p.setPen(QPen(_C_ACCENT_D, 2))
        p.drawRoundedRect(sr, 16, 16)
        font.setPixelSize(17); font.setBold(True); p.setFont(font)
        p.setPen(_C_TITLE)
        p.drawText(sr, Qt.AlignmentFlag.AlignCenter, 'SPAWN ♥')

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

    # ── Mouse ────────────────────────────────────────────────────────────────

    def _hit_key(self, pos: QPoint) -> str | None:
        if self._close_rect().contains(pos):
            return '__close__'
        if self._spawn_rect().contains(pos):
            return 'spawn'
        return None

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
        key = self._hit_key(event.pos())
        if key == '__close__':
            # Close without spawning — user can relaunch
            self.close_animated()
            return
        if key == 'spawn':
            self.spawn_requested.emit(dict(self._profile))
            self.close_animated()
            return
        self._drag_offset = event.pos()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_offset = None

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                            Qt.Key.Key_Space):
            self.spawn_requested.emit(dict(self._profile))
            self.close_animated()
        elif event.key() == Qt.Key.Key_Escape:
            self.close_animated()

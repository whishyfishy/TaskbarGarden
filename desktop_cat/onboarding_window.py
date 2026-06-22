"""
First-run onboarding window for Desktop Cat.
Cute soft-white paper window that collects user name, mini-me name,
skin color, personality, and ends with a big SPAWN button.
"""

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore    import Qt, QPoint, QRect, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtCore    import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from PyQt6.QtGui     import QPainter, QPixmap, QColor, QFont, QPen

from desktop_cat.user_profile import (
    SKIN_TONES, PERSONALITIES, load as profile_load, save as profile_save,
)

_OPEN_MS         = 260
_CLOSE_MS        = 180
_POP_SCALE_START = 0.78

# ── Layout ────────────────────────────────────────────────────────────────────
_W            = 360
_H            = 440
_BORDER       = 6
_PAD          = 18
_TITLE_H      = 40
_DOTS_H       = 16
_NAV_H        = 46
_CONTENT_TOP  = _BORDER + _TITLE_H + 4
_CONTENT_H    = _H - _CONTENT_TOP - _NAV_H - _DOTS_H - _BORDER - 4

_MAX_NAME_LEN = 18

# ── Colors — cute soft-white paper ────────────────────────────────────────────
_C_PAPER        = QColor(254, 250, 242)    # warm paper
_C_PAPER_HOV    = QColor(246, 238, 224)
_C_BORDER       = QColor(225, 205, 175)    # sand
_C_BORDER_IN    = QColor(250, 240, 220)    # soft inner highlight
_C_SHADOW       = QColor(175, 155, 130, 60)
_C_TITLE        = QColor(108,  78,  52)    # cocoa
_C_TEXT         = QColor( 84,  64,  48)
_C_MUTED        = QColor(155, 130, 104)
_C_ACCENT       = QColor(232, 140, 160)    # blossom pink
_C_ACCENT_D     = QColor(198, 108, 130)
_C_MINT         = QColor(148, 212, 168)
_C_MINT_D       = QColor(102, 170, 128)
_C_AMBER        = QColor(240, 200, 122)
_C_LAV          = QColor(188, 196, 232)
_C_INPUT_BG     = QColor(248, 242, 230)
_C_INPUT_BRD    = QColor(212, 185, 148)
_C_DOT          = QColor(215, 192, 165)
_C_DOT_ACT      = QColor(232, 140, 160)
_C_BTN_NEUTRAL  = QColor(238, 228, 210)
_C_BTN_NEUTRAL_H= QColor(228, 216, 196)
_C_CLOSE_HOV    = QColor(230, 138, 138, 170)

# ── Step definitions ──────────────────────────────────────────────────────────
# 0: welcome   1: user name   2: sao name (with "finalize" button)
# After step 2's finalize, the window closes and host opens CardRevealWindow.
_NUM_STEPS = 3


class OnboardingWindow(QWidget):
    # Emitted when the user has filled in user_name + char_name and clicked
    # "finalize". The argument is the user profile dict (already saved). The
    # host should then open CardRevealWindow → and finally spawn Sao.
    finalize_requested = pyqtSignal(dict)
    # Kept for skip-onboarding (close button) compatibility — host treats it
    # the same as finalize but without the card-reveal flow.
    spawn_requested    = pyqtSignal(dict)

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

        self._profile: dict = profile_load()
        # ensure sensible defaults for the form
        if not self._profile.get('skin_color'):
            self._profile['skin_color'] = SKIN_TONES[1][0]
        if self._profile.get('personality') not in PERSONALITIES:
            self._profile['personality'] = 'medium'

        self._step: int         = 0
        self._anim_scale: float = 1.0
        self._main_anim: QParallelAnimationGroup | None = None
        self._step_anim: QPropertyAnimation | None      = None
        self._step_offset: float = 0.0
        self._closing: bool     = False
        self._drag_offset: QPoint | None = None
        self._hovered_key: str | None     = None
        self._focus_field: str | None     = 'user_name'  # active input when on step 1/2
        self._cursor_blink  = True

        self._blink = QTimer(self)
        self._blink.setInterval(500)
        self._blink.timeout.connect(self._toggle_blink)
        self._blink.start()

        # Animation tick (drives subtle pulsing on the finalize button)
        self._anim_t: float = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(50)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

    def _toggle_blink(self) -> None:
        self._cursor_blink = not self._cursor_blink
        if self._step in (1, 2):
            self.update()

    def _on_tick(self) -> None:
        self._anim_t += 0.05
        if self._step == 2:
            # Pulse the finalize button
            self.update()

    # ── Animatable scale ──────────────────────────────────────────────────────

    @pyqtProperty(float)
    def anim_scale(self) -> float:          # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                      # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    @pyqtProperty(float)
    def step_offset(self) -> float:         # type: ignore[override]
        return self._step_offset

    @step_offset.setter                     # type: ignore[override]
    def step_offset(self, v: float) -> None:
        self._step_offset = v
        self.update()

    # ── Open / close ──────────────────────────────────────────────────────────

    def show_animated(self, x: int | None = None, y: int | None = None) -> None:
        # Default centered on primary screen
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

    # ── Step navigation ───────────────────────────────────────────────────────

    def _go_step(self, new_step: int) -> None:
        new_step = max(0, min(_NUM_STEPS - 1, new_step))
        if new_step == self._step:
            return
        direction = 1 if new_step > self._step else -1
        self._step = new_step

        # focus field on text steps
        if new_step == 1:
            self._focus_field = 'user_name'
        elif new_step == 2:
            self._focus_field = 'char_name'
        else:
            self._focus_field = None

        # slide animation
        self._step_offset = -direction * 24.0
        self._step_anim = QPropertyAnimation(self, b'step_offset', self)
        self._step_anim.setDuration(180)
        self._step_anim.setStartValue(self._step_offset)
        self._step_anim.setEndValue(0.0)
        self._step_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._step_anim.start()
        self.update()

    def _can_advance(self) -> bool:
        if self._step == 1:
            return bool(self._profile.get('user_name', '').strip())
        if self._step == 2:
            return bool(self._profile.get('char_name', '').strip())
        return True

    def _finalize(self) -> None:
        """User clicked finalize — persist user profile and spawn."""
        self._profile['onboarded'] = True
        profile_save(self._profile)
        self.finalize_requested.emit(dict(self._profile))
        self.close_animated()

    def _finish_and_spawn(self) -> None:
        """Skip path (close button) — just spawn."""
        self._profile['onboarded'] = True
        profile_save(self._profile)
        self.spawn_requested.emit(dict(self._profile))
        self.close_animated()

    # ── Geometry ──────────────────────────────────────────────────────────────

    def _close_rect(self) -> QRect:
        return QRect(_W - _BORDER - 10 - 18, _BORDER + 9, 18, 18)

    def _content_rect(self) -> QRect:
        return QRect(_BORDER + _PAD, _CONTENT_TOP,
                     _W - 2 * (_BORDER + _PAD), _CONTENT_H)

    def _nav_rect(self) -> QRect:
        top = _H - _BORDER - _NAV_H
        return QRect(_BORDER + _PAD, top,
                     _W - 2 * (_BORDER + _PAD), _NAV_H - 4)

    def _dots_rect(self) -> QRect:
        top = _H - _BORDER - _NAV_H - _DOTS_H
        return QRect(_BORDER, top, _W - 2 * _BORDER, _DOTS_H)

    def _back_rect(self) -> QRect:
        nav = self._nav_rect()
        w = 90
        return QRect(nav.left(), nav.top() + 6, w, nav.height() - 8)

    def _next_rect(self) -> QRect:
        nav = self._nav_rect()
        w = 110
        return QRect(nav.right() - w, nav.top() + 6, w, nav.height() - 8)

    def _input_rect(self) -> QRect:
        """Text input box for current text step (user name or char name)."""
        cr = self._content_rect()
        return QRect(cr.left() + 20, cr.top() + 120,
                     cr.width() - 40, 32)

    def _skin_rects(self) -> list[QRect]:
        cr = self._content_rect()
        top = cr.top() + 180
        sw  = 26
        gap = 6
        total = len(SKIN_TONES) * sw + (len(SKIN_TONES) - 1) * gap
        x0 = cr.left() + (cr.width() - total) // 2
        return [QRect(x0 + i * (sw + gap), top, sw, sw)
                for i in range(len(SKIN_TONES))]

    def _personality_rects(self) -> list[QRect]:
        cr = self._content_rect()
        top = cr.top() + 232
        pw = 82
        gap = 8
        total = len(PERSONALITIES) * pw + (len(PERSONALITIES) - 1) * gap
        x0 = cr.left() + (cr.width() - total) // 2
        return [QRect(x0 + i * (pw + gap), top, pw, 26)
                for i in range(len(PERSONALITIES))]

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _render_buf(self) -> QPixmap:
        buf = QPixmap(_W, _H)
        buf.fill(Qt.GlobalColor.transparent)
        p = QPainter(buf)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Soft shadow
        p.setBrush(_C_SHADOW)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(3, 5, _W - 6, _H - 6, 14, 14)

        # Paper body
        p.setBrush(_C_PAPER)
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(1, 1, _W - 2, _H - 2, 12, 12)
        # inner highlight
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_C_BORDER_IN, 1))
        p.drawRoundedRect(4, 4, _W - 8, _H - 8, 9, 9)

        # Title bar band
        font = QFont('Courier New', 1)
        font.setPixelSize(13); font.setBold(True)
        p.setFont(font)
        p.setPen(_C_TITLE)
        titles = [
            '* welcome',
            '* who are you?',
            '* name your companion',
        ]
        p.drawText(QRect(_BORDER + _PAD, _BORDER + 4,
                         _W - 2 * (_BORDER + _PAD) - 24, _TITLE_H - 6),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   titles[self._step])

        # Close button (skip onboarding)
        cr = self._close_rect()
        hov_close = self._hovered_key == '__close__'
        if hov_close:
            p.setBrush(_C_CLOSE_HOV)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cr.adjusted(-1, -1, 1, 1))
        font.setPixelSize(11); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_TITLE if hov_close else _C_MUTED)
        p.drawText(cr, Qt.AlignmentFlag.AlignCenter, 'x')

        # Title divider — dotted line for cuteness
        p.setPen(QPen(_C_BORDER, 1, Qt.PenStyle.DotLine))
        p.drawLine(_BORDER + _PAD, _BORDER + _TITLE_H,
                   _W - _BORDER - _PAD, _BORDER + _TITLE_H)

        # Content (per step)
        content = self._content_rect()
        p.save()
        p.setClipRect(content)
        p.translate(self._step_offset, 0)
        if self._step == 0:
            self._draw_step_welcome(p, content)
        elif self._step == 1:
            self._draw_step_user_name(p, content)
        else:
            self._draw_step_char_name(p, content)
        p.restore()

        # Progress dots
        dots = self._dots_rect()
        dot_size = 7
        gap = 10
        total = _NUM_STEPS * dot_size + (_NUM_STEPS - 1) * gap
        x0 = dots.left() + (dots.width() - total) // 2
        for i in range(_NUM_STEPS):
            cx = x0 + i * (dot_size + gap)
            cy = dots.top() + (dots.height() - dot_size) // 2
            if i == self._step:
                p.setBrush(_C_DOT_ACT)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(cx - 1, cy - 1, dot_size + 2, dot_size + 2)
            else:
                p.setBrush(_C_DOT if i > self._step else _C_ACCENT.lighter(140))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(cx, cy, dot_size, dot_size)

        # Nav row
        self._draw_nav(p)

        p.end()
        return buf

    # ── Step renderers ────────────────────────────────────────────────────────

    def _draw_step_welcome(self, p: QPainter, cr: QRect) -> None:
        font = QFont('Courier New', 1)
        font.setPixelSize(22); font.setBold(True)
        p.setFont(font)
        p.setPen(_C_TITLE)
        p.drawText(QRect(cr.left(), cr.top() + 30, cr.width(), 40),
                   Qt.AlignmentFlag.AlignCenter, 'hi there ✿')

        font.setPixelSize(12); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_TEXT)
        p.drawText(QRect(cr.left() + 10, cr.top() + 90,
                         cr.width() - 20, 140),
                   Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter
                   | Qt.AlignmentFlag.AlignTop,
                   "a tiny friend is about to move onto your desktop.\n\n"
                   "she wanders your taskbar and grows a flower for each task. "
                   "her hub lets you manage to-dos, pin windows, and write "
                   "sticky notes.\n\n"
                   "let's set her up together — it only takes a sec.")

        # Sprite sketch — tiny blob with face to set the tone
        p.setBrush(_C_ACCENT.lighter(130))
        p.setPen(QPen(_C_ACCENT_D, 1))
        bx = cr.left() + cr.width() // 2 - 18
        by = cr.bottom() - 56
        p.drawEllipse(bx, by, 36, 36)
        p.setBrush(_C_TITLE)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(bx + 10, by + 14, 4, 4)
        p.drawEllipse(bx + 22, by + 14, 4, 4)
        p.setPen(QPen(_C_TITLE, 1))
        p.drawArc(bx + 12, by + 18, 12, 8, 200 * 16, 140 * 16)

    def _draw_step_user_name(self, p: QPainter, cr: QRect) -> None:
        font = QFont('Courier New', 1)
        font.setPixelSize(14); font.setBold(True)
        p.setFont(font)
        p.setPen(_C_TITLE)
        p.drawText(QRect(cr.left(), cr.top() + 30, cr.width(), 30),
                   Qt.AlignmentFlag.AlignCenter, 'what should i call you?')

        font.setPixelSize(11); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(QRect(cr.left() + 10, cr.top() + 66,
                         cr.width() - 20, 40),
                   Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter
                   | Qt.AlignmentFlag.AlignTop,
                   "this is how your mini-me will address you")

        # Input
        ir = self._input_rect()
        active = self._focus_field == 'user_name'
        p.setBrush(_C_INPUT_BG)
        p.setPen(QPen(_C_ACCENT if active else _C_INPUT_BRD, 2 if active else 1))
        p.drawRoundedRect(ir, 6, 6)
        font.setPixelSize(13); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_TEXT)
        txt = self._profile.get('user_name', '')
        display = txt if txt else ''
        if active and self._cursor_blink:
            display = display + '_'
        elif not txt:
            display = 'type your name…'
            p.setPen(_C_MUTED)
        p.drawText(QRect(ir.left() + 10, ir.top(),
                         ir.width() - 20, ir.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   display)

    def _draw_step_char_name(self, p: QPainter, cr: QRect) -> None:
        font = QFont('Courier New', 1)
        font.setPixelSize(14); font.setBold(True)
        p.setFont(font)
        p.setPen(_C_TITLE)
        p.drawText(QRect(cr.left(), cr.top() + 30, cr.width(), 24),
                   Qt.AlignmentFlag.AlignCenter, 'name your companion')

        font.setPixelSize(11); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(QRect(cr.left() + 10, cr.top() + 66,
                         cr.width() - 20, 40),
                   Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter
                   | Qt.AlignmentFlag.AlignTop,
                   "she'll live on your taskbar, grow a flower\n"
                   "for each task, and keep you company.")

        # Name input
        ir = self._input_rect()
        active = self._focus_field == 'char_name'
        p.setBrush(_C_INPUT_BG)
        p.setPen(QPen(_C_ACCENT if active else _C_INPUT_BRD, 2 if active else 1))
        p.drawRoundedRect(ir, 6, 6)
        font.setPixelSize(13); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_TEXT)
        txt = self._profile.get('char_name', '')
        display = txt if txt else ''
        if active and self._cursor_blink:
            display = display + '_'
        elif not txt:
            display = 'e.g. sao'
            p.setPen(_C_MUTED)
        p.drawText(QRect(ir.left() + 10, ir.top(),
                         ir.width() - 20, ir.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   display)

        # Small hint at bottom
        font.setPixelSize(10); font.setBold(False)
        p.setFont(font)
        p.setPen(_C_MUTED)
        p.drawText(QRect(cr.left(), cr.bottom() - 40, cr.width(), 20),
                   Qt.AlignmentFlag.AlignCenter,
                   'press spawn when you\'re ready ✿')

    # ── Nav row ───────────────────────────────────────────────────────────────

    def _draw_nav(self, p: QPainter) -> None:
        font = QFont('Courier New', 1)

        # Back button (not on first step)
        if self._step > 0:
            br = self._back_rect()
            hov = self._hovered_key == 'nav_back'
            p.setBrush(_C_BTN_NEUTRAL_H if hov else _C_BTN_NEUTRAL)
            p.setPen(QPen(_C_BORDER, 1))
            p.drawRoundedRect(br, 10, 10)
            font.setPixelSize(12); font.setBold(False)
            p.setFont(font)
            p.setPen(_C_TEXT)
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, '< back')

        # Right-side button: 'next >' on intermediate steps, 'finalize ✦' on last
        nr = self._next_rect()
        can_go = self._can_advance()
        hov = self._hovered_key == 'nav_next'
        is_finalize = self._step == _NUM_STEPS - 1

        if is_finalize and can_go:
            # Pulsing accent — invitation to finalize
            import math
            pulse = math.sin(self._anim_t * 3.0) * 0.5 + 0.5
            r = int(_C_ACCENT.red()   + (255 - _C_ACCENT.red())   * pulse * 0.18)
            g = int(_C_ACCENT.green() + (255 - _C_ACCENT.green()) * pulse * 0.18)
            b = int(_C_ACCENT.blue()  + (255 - _C_ACCENT.blue())  * pulse * 0.18)
            base   = QColor(r, g, b)
            base_h = _C_ACCENT_D
            brd    = _C_ACCENT_D
            label  = 'finalize ✦'
        elif can_go:
            base   = _C_MINT
            base_h = _C_MINT_D
            brd    = _C_MINT_D
            label  = 'next >'
        else:
            base   = _C_BTN_NEUTRAL
            base_h = _C_BTN_NEUTRAL_H
            brd    = _C_BORDER
            label  = 'finalize ✦' if is_finalize else 'next >'

        p.setBrush(base_h if hov else base)
        p.setPen(QPen(brd, 1))
        p.drawRoundedRect(nr, 10, 10)
        font.setPixelSize(12); font.setBold(False)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255) if (is_finalize and can_go)
                  else (_C_TITLE if can_go else _C_MUTED))
        p.drawText(nr, Qt.AlignmentFlag.AlignCenter, label)

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

    # ── Hit testing ───────────────────────────────────────────────────────────

    def _hit_key(self, pos: QPoint) -> str | None:
        if self._close_rect().contains(pos):
            return '__close__'
        if self._step > 0 and self._back_rect().contains(pos):
            return 'nav_back'
        if self._next_rect().contains(pos):
            return 'nav_next'
        if self._step == 1 and self._input_rect().contains(pos):
            return 'input_user'
        if self._step == 2 and self._input_rect().contains(pos):
            return 'input_char'
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
            # Skip onboarding — mark onboarded with defaults, spawn anyway
            self._finish_and_spawn()
            return
        if key == 'nav_back':
            self._go_step(self._step - 1)
            return
        if key == 'nav_next':
            if not self._can_advance():
                return
            if self._step == _NUM_STEPS - 1:
                self._finalize()
            else:
                self._go_step(self._step + 1)
            return
        if key == 'input_user':
            self._focus_field = 'user_name'
            self.update(); return
        if key == 'input_char':
            self._focus_field = 'char_name'
            self.update(); return

        # Drag from anywhere else
        self._drag_offset = event.pos()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_offset = None

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        k = event.key()

        if k == Qt.Key.Key_Escape:
            self._finish_and_spawn()
            return

        if k == Qt.Key.Key_Return or k == Qt.Key.Key_Enter:
            if not self._can_advance():
                return
            if self._step == _NUM_STEPS - 1:
                self._finalize()
            else:
                self._go_step(self._step + 1)
            return

        # Text input for name fields
        field = self._focus_field
        if self._step == 1:
            field = 'user_name'
        elif self._step == 2 and field != 'char_name':
            # Only accept typing if user is focused on char name
            return
        elif self._step not in (1, 2):
            return

        cur_key = 'user_name' if self._step == 1 else 'char_name'
        cur = self._profile.get(cur_key, '')

        if k == Qt.Key.Key_Backspace:
            self._profile[cur_key] = cur[:-1]
            self.update(); return
        t = event.text()
        if t and t.isprintable() and len(cur) < _MAX_NAME_LEN:
            self._profile[cur_key] = cur + t
            self.update()

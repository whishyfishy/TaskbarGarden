"""Floating frameless sticky-note window — clean view mode.

Each pinned sticky in the Library Hub spawns one of these.  It's an
always-on-top frameless widget that lives on the desktop independent of
the hub — you can close the hub, close the app's main window, and the
sticky stays put.

Look:
  • Just the body text in view mode (no header chrome).
  • A small dot in the top-right corner.  Click it to reveal a popup
    panel with color swatches, transparency slider, and the unpin (×)
    button.  Click outside the popup or press Escape to dismiss it.

Drag:
  • The top ~22 px strip is invisibly draggable (no header bar — keeps
    the view clean).  Cursor changes to a grab hand on hover.

Resize:
  • Bottom-right corner has a small grip.

Rich-text editing:
  • Ctrl+B   — toggle bold on selection (or at cursor)
  • Ctrl+I   — toggle italic
  • Ctrl+=   — bump font size up (also Ctrl++ for keyboards where +
                requires Shift)
  • Ctrl+-   — bump font size down

Persistence:
  • Body text is saved as body (plain) AND body_html (rich) via a small
    debounce.  The hub view always uses body; the floating window
    prefers body_html when present so formatting round-trips.

Transparency:
  • fade_strength 0.0   → always 100 % opacity
  • fade_strength 0.5   → fades to ~65 %   after ~1.5 s of no hover
  • fade_strength 1.0   → fades to ~30 %

Coordinates with main.py via desktop_cat.stickies_data — every persistent
mutation goes through stickies_data.patch_one(id, **fields), which the
main process's StickyManager observes via mtime polling.
"""
from __future__ import annotations

from PyQt6.QtCore    import (Qt, QPoint, QRect, QSize, QTimer,
                             QPropertyAnimation, pyqtSignal, QEvent)
from PyQt6.QtGui     import (QColor, QPainter, QPainterPath, QCursor,
                             QKeyEvent, QTextCharFormat, QFont)
from PyQt6.QtWidgets import (QWidget, QTextEdit, QSizeGrip, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QSlider,
                             QFrame)

from desktop_cat import stickies_data


# Palette offered when the user picks a color.  Soft pastel tones that
# read well as desktop stickies; must match xv4 STICKY_COLORS in the JSX.
_PALETTE = [
    '#fef3a8',   # warm yellow (default)
    '#fed5a8',   # peach
    '#fcb1a8',   # coral
    '#d8b4f8',   # lavender
    '#a8d4fc',   # sky blue
    '#a8f0c2',   # mint
    '#f0e9d2',   # cream
    '#e8e1d4',   # taupe
]

# How long with no hover before we start fading (ms).
_HOVER_FADE_DELAY_MS = 1500
# Animation duration when fading in/out (ms).
_FADE_ANIM_MS        = 280
# Debounce on saving text edits to disk (ms).
_TEXT_SAVE_DEBOUNCE_MS = 350
# Drag-handle strip height — invisibly draggable area at the top of the
# sticky.  Keep small so it doesn't eat into the visible body.
_DRAG_STRIP_H = 18
# Dot button — tiny round affordance in the top-right corner that
# opens the controls popup.
_DOT_SIZE = 12


def _opacity_at_fade(fade_strength: float) -> float:
    """Map slider value (0..1) → opacity-when-not-hovered (1.0..0.30).

    Slider all the way left (0.0) → no fade (stays at 1.0).
    Slider all the way right (1.0) → fades to 0.30 (visible but ghostly).
    Half (0.5) → ~0.65.
    """
    return max(0.30, 1.0 - 0.70 * max(0.0, min(1.0, fade_strength)))


# ─────────────────────────────────────────────────────────────────────
# Inner QTextEdit subclass — adds Ctrl+B / Ctrl+I / Ctrl+= / Ctrl+-
# ─────────────────────────────────────────────────────────────────────

class _StickyTextEdit(QTextEdit):
    """QTextEdit with rich-text keyboard shortcuts.

    Bold + italic toggle the matching font flag on the current
    selection.  When there's no selection, the toggle applies at the
    cursor (any new typing inherits the new style).

    Font-size shortcuts walk the size up/down in 1-pt steps over the
    selection (or the whole document if nothing is selected).  Bounded
    8..36 so the user can't accidentally make the text invisible or
    huge enough to overflow the window.
    """
    fontSizeChanged = pyqtSignal(int)   # emits new base size pt

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_pt = 12
        # Start in read-only mode — body click should drag the sticky,
        # not enter text-edit mode.  Double-click switches to editing.
        self._set_read_only_mode(True)

    # ── click/drag/double-click flow ───────────────────────────────
    #
    # In read-only mode the text editor "passes through" mouse events
    # to its parent (the StickyWindow) by calling e.ignore() in
    # mousePressEvent / mouseMoveEvent / mouseReleaseEvent.  That lets
    # the StickyWindow's drag handler take over, so the whole body
    # behaves like a draggable block.
    #
    # Double-click flips to TextEditorInteraction + focus.  Losing
    # focus or pressing Esc reverts.

    def _set_read_only_mode(self, on: bool) -> None:
        self.setReadOnly(on)
        if on:
            self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            self.viewport().setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            self.viewport().setCursor(QCursor(Qt.CursorShape.IBeamCursor))

    def mousePressEvent(self, e: QKeyEvent) -> None:
        if self.isReadOnly():
            # Don't act on the click — let StickyWindow take it for drag.
            e.ignore(); return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QKeyEvent) -> None:
        if self.isReadOnly():
            e.ignore(); return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QKeyEvent) -> None:
        if self.isReadOnly():
            e.ignore(); return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e: QKeyEvent) -> None:
        # Always handle dbl-click ourselves: flip to edit mode if we're
        # currently read-only, otherwise let the editor handle it (word
        # selection).
        if self.isReadOnly():
            self._set_read_only_mode(False)
            self.setFocus()
            e.accept(); return
        super().mouseDoubleClickEvent(e)

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        # Revert to read-only so the next single click drags again.
        if not self.isReadOnly():
            self._set_read_only_mode(True)

    def set_base_pt(self, pt: int) -> None:
        self._base_pt = max(8, min(36, int(pt)))
        f = self.font()
        f.setPointSize(self._base_pt)
        self.setFont(f)

    def base_pt(self) -> int:
        return self._base_pt

    def keyPressEvent(self, e: QKeyEvent) -> None:
        mod = e.modifiers()
        key = e.key()
        # Esc → exit edit mode (revert to read-only, ready to drag again)
        if key == Qt.Key.Key_Escape and not self.isReadOnly():
            self._set_read_only_mode(True)
            self.clearFocus()
            e.accept(); return
        if mod & Qt.KeyboardModifier.ControlModifier:
            # Bold
            if key == Qt.Key.Key_B:
                self._toggle_bold()
                e.accept(); return
            # Italic
            if key == Qt.Key.Key_I:
                self._toggle_italic()
                e.accept(); return
            # Font up — Ctrl + Plus / Ctrl + Equal (so the user doesn't
            # need to press Shift on US-layout keyboards).
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self._bump_font(+1)
                e.accept(); return
            # Font down — Ctrl + Minus
            if key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                self._bump_font(-1)
                e.accept(); return
        super().keyPressEvent(e)

    # ── helpers ────────────────────────────────────────────────────
    def _toggle_bold(self) -> None:
        cur = self.textCursor()
        # When there's a selection use its current weight; otherwise the
        # cursor's char format.
        fmt = cur.charFormat() if not cur.hasSelection() else cur.charFormat()
        is_bold = fmt.fontWeight() >= QFont.Weight.Bold.value
        new_w = QFont.Weight.Normal.value if is_bold else QFont.Weight.Bold.value
        nf = QTextCharFormat()
        nf.setFontWeight(new_w)
        self.mergeCurrentCharFormat(nf)

    def _toggle_italic(self) -> None:
        cur = self.textCursor()
        fmt = cur.charFormat()
        is_italic = fmt.fontItalic()
        nf = QTextCharFormat()
        nf.setFontItalic(not is_italic)
        self.mergeCurrentCharFormat(nf)

    def _bump_font(self, delta: int) -> None:
        new = max(8, min(36, self._base_pt + delta))
        if new == self._base_pt:
            return
        self.set_base_pt(new)
        self.fontSizeChanged.emit(new)



# ─────────────────────────────────────────────────────────────────────
# Main sticky window
# ─────────────────────────────────────────────────────────────────────

class StickyWindow(QWidget):
    """Single floating sticky note."""

    persisted = pyqtSignal()   # any disk write happened, hub should re-read

    def __init__(self, sticky: dict, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint
                                | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(160, 120)
        self._sid           = sticky.get('id', '')
        self._color         = str(sticky.get('color') or '#fef3a8')
        self._fade_strength = float(sticky.get('fade_strength') or 0.0)
        self._title         = str(sticky.get('title') or '')
        self._body          = str(sticky.get('body') or '')
        self._body_html     = str(sticky.get('body_html') or '')
        self._body_font_pt  = int(sticky.get('body_font_pt') or 12)
        # Geometry — initial pos/size from the saved record
        x = int(sticky.get('pin_x', 220))
        y = int(sticky.get('pin_y', 140))
        w = int(sticky.get('pin_w', 220))
        h = int(sticky.get('pin_h', 180))
        self.setGeometry(x, y, max(160, w), max(120, h))

        self._build_ui()

        # Hover-fade plumbing
        self.setMouseTracking(True)
        self._opacity_anim: QPropertyAnimation | None = None
        self._fade_timer = QTimer(self); self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._do_fade_out)
        self.setWindowOpacity(1.0)
        self._hovered = False

        # Save debounce
        self._save_timer = QTimer(self); self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_text)
        # Resize-save debounce
        self._resize_timer = QTimer(self); self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._flush_geometry)

        # Drag state — sticky is draggable from anywhere on the body
        # (the QTextEdit forwards clicks to us when read-only).
        self._drag_offset: QPoint | None = None
        self._drag_start_global: QPoint | None = None
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # No header layout — body fills the whole sticky.  The top
        # _DRAG_STRIP_H px is reserved for dragging (handled in
        # mousePressEvent); the editor leaves padding-top so its first
        # line doesn't sit underneath the drag strip.
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Body — editable rich-text note
        self._editor = _StickyTextEdit(self)
        if self._body_html:
            self._editor.setHtml(self._body_html)
        else:
            self._editor.setPlainText(self._body)
        self._editor.set_base_pt(self._body_font_pt)
        self._editor.setFrameStyle(QFrame.Shape.NoFrame)
        self._editor.setStyleSheet(
            'QTextEdit { background: transparent; color: rgba(20,30,50,0.92); '
            f'padding: {_DRAG_STRIP_H}px 14px 12px 14px; border: none; '
            'font-family: "Inter", "Segoe UI", system-ui, sans-serif; '
            'line-height: 1.45; selection-background-color: rgba(80,120,200,0.30); }'
            'QScrollBar:vertical { background: transparent; width: 6px; margin: 4px 2px; }'
            'QScrollBar::handle:vertical { background: rgba(20,30,50,0.25); border-radius: 3px; min-height: 24px; }'
            'QScrollBar::handle:vertical:hover { background: rgba(20,30,50,0.45); }'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: none; }'
            'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }'
        )
        self._editor.textChanged.connect(self._on_text_changed)
        self._editor.fontSizeChanged.connect(self._on_font_size_changed)
        root.addWidget(self._editor, 1)

        # Bottom-right resize grip — embedded in a thin bottom row
        bot = QHBoxLayout(); bot.setContentsMargins(0, 0, 2, 2); bot.setSpacing(0)
        bot.addStretch(1)
        self._grip = QSizeGrip(self)
        self._grip.setFixedSize(14, 14)
        bot.addWidget(self._grip)
        root.addLayout(bot)

        # Dot — small EXIT dot overlay in the top-right corner.
        # Click → unpin (closes this floating window).  No popup,
        # no color/transparency picker — those live in the hub's
        # Stickies tab now.  Keeps the floating note distraction-free.
        self._dot = QPushButton('', self)
        self._dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        self._dot.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._dot.setToolTip('unpin')
        self._dot.clicked.connect(self._on_unpin_clicked)
        self._dot.raise_()
        self._apply_dot_style()
        self._reposition_dot()

    def _apply_dot_style(self) -> None:
        # Exit dot — blends with the sticky color (darker shade of the
        # paper) so it doesn't visually scream against the pastel.
        # Only on HOVER does it warm toward red, giving the "close"
        # affordance right when the cursor lands on it.
        base   = QColor(self._color).darker(150)   # ~33% darker than sticky
        hover  = QColor(190, 60, 50)               # warm red, only on hover
        self._dot.setStyleSheet(
            f'QPushButton {{ background: {base.name()}; border: none; '
            f'border-radius: {_DOT_SIZE // 2}px; }}'
            f'QPushButton:hover {{ background: {hover.name()}; }}'
        )

    def _reposition_dot(self) -> None:
        # Top-right corner with a small margin
        m = 6
        self._dot.move(self.width() - _DOT_SIZE - m, m)

    # ------------------------------------------------------------------
    # Custom paint — rounded-rect body with the chosen color + soft shadow
    # ------------------------------------------------------------------

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)
        p.fillPath(path, QColor(self._color))
        # Soft outline so it doesn't merge with bright wallpaper
        p.setPen(QColor(0, 0, 0, 36))
        p.drawPath(path)

    # ------------------------------------------------------------------
    # Top-strip dragging (invisible — there's no header bar)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Drag — sticky behaves like a draggable block.  Press anywhere on
    # the body (the text editor forwards events to us when read-only),
    # move to drag, release to drop.  Double-click on the text area
    # enters edit mode (handled by _StickyTextEdit itself).
    # ------------------------------------------------------------------

    def mousePressEvent(self, evt) -> None:
        if evt.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (evt.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            self._drag_start_global = evt.globalPosition().toPoint()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            evt.accept()
            return
        super().mousePressEvent(evt)

    def mouseMoveEvent(self, evt) -> None:
        if self._drag_offset is not None:
            self.move(evt.globalPosition().toPoint() - self._drag_offset)
            evt.accept()
            return
        super().mouseMoveEvent(evt)

    def mouseReleaseEvent(self, evt) -> None:
        if self._drag_offset is not None:
            moved = QPoint()
            if self._drag_start_global is not None:
                moved = evt.globalPosition().toPoint() - self._drag_start_global
            self._drag_offset = None
            self._drag_start_global = None
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            # Only persist position if it actually moved (skip the
            # "click without drag" case to avoid useless disk writes).
            if abs(moved.x()) > 2 or abs(moved.y()) > 2:
                stickies_data.patch_one(self._sid,
                                        pin_x=int(self.x()),
                                        pin_y=int(self.y()))
                self.persisted.emit()
            evt.accept()
            return
        super().mouseReleaseEvent(evt)

    def resizeEvent(self, evt) -> None:
        super().resizeEvent(evt)
        self._reposition_dot()
        self._resize_timer.start(120)

    def _flush_geometry(self) -> None:
        stickies_data.patch_one(self._sid,
                                pin_w=int(self.width()),
                                pin_h=int(self.height()))
        self.persisted.emit()

    def _on_unpin_clicked(self) -> None:
        stickies_data.patch_one(self._sid, pinned=False)
        self.persisted.emit()
        # Window will close when StickyManager sees the disk change.

    # ------------------------------------------------------------------
    # Escape key dismisses the popup (also handled by clicks outside)
    # ------------------------------------------------------------------

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape and self._popup is not None:
            self._close_popup()
            e.accept(); return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------
    # Hover-fade
    # ------------------------------------------------------------------

    def enterEvent(self, _evt) -> None:
        self._hovered = True
        self._fade_timer.stop()
        self._set_opacity(1.0)

    def leaveEvent(self, _evt) -> None:
        self._hovered = False
        self._fade_timer.start(_HOVER_FADE_DELAY_MS)

    def _do_fade_out(self) -> None:
        if self._hovered:
            return
        target = _opacity_at_fade(self._fade_strength)
        if abs(target - 1.0) < 0.01:
            return
        self._set_opacity(target)

    def _set_opacity(self, target: float) -> None:
        if self._opacity_anim is not None:
            self._opacity_anim.stop()
        cur = self.windowOpacity()
        if abs(cur - target) < 0.01:
            return
        anim = QPropertyAnimation(self, b'windowOpacity')
        anim.setDuration(_FADE_ANIM_MS)
        anim.setStartValue(cur)
        anim.setEndValue(target)
        anim.start()
        self._opacity_anim = anim

    # ------------------------------------------------------------------
    # Text edits → debounced disk writes
    # ------------------------------------------------------------------

    def _on_text_changed(self) -> None:
        # Snapshot both plain + rich so hub-edits and floating-edits
        # round-trip cleanly.  Hub-edits clear body_html so we re-render
        # as plain on the next mount.
        self._body      = self._editor.toPlainText()
        self._body_html = self._editor.toHtml()
        self._save_timer.start(_TEXT_SAVE_DEBOUNCE_MS)

    def _flush_text(self) -> None:
        stickies_data.patch_one(self._sid,
                                body=self._body,
                                body_html=self._body_html)
        self.persisted.emit()

    def _on_font_size_changed(self, pt: int) -> None:
        self._body_font_pt = pt
        stickies_data.patch_one(self._sid, body_font_pt=pt)
        # Don't emit persisted — font size doesn't affect the hub render

    # ------------------------------------------------------------------
    # External updates from the StickyManager (React-side edit etc.)
    # ------------------------------------------------------------------

    def apply_external_update(self, sticky: dict) -> None:
        # Body — prefer rich HTML when present, else plain text.  We
        # diff to avoid clobbering the cursor while the user is typing.
        new_html = str(sticky.get('body_html') or '')
        new_body = str(sticky.get('body') or '')
        changed_text = False
        if new_html:
            if new_html != self._body_html:
                self._body_html = new_html
                self._body      = new_body
                self._editor.blockSignals(True)
                self._editor.setHtml(new_html)
                self._editor.blockSignals(False)
                changed_text = True
        else:
            # No HTML → plain text view.  React-side edit will clear html.
            if new_body != self._body or self._body_html:
                self._body      = new_body
                self._body_html = ''
                self._editor.blockSignals(True)
                self._editor.setPlainText(new_body)
                self._editor.blockSignals(False)
                changed_text = True
        # Font size
        new_pt = int(sticky.get('body_font_pt') or 12)
        if new_pt != self._body_font_pt:
            self._body_font_pt = new_pt
            self._editor.set_base_pt(new_pt)
        # Color
        new_color = str(sticky.get('color') or self._color)
        if new_color != self._color:
            self._color = new_color
            self._apply_dot_style()
            self.update()
        # Fade
        new_fade = float(sticky.get('fade_strength') or 0.0)
        if abs(new_fade - self._fade_strength) > 0.01:
            self._fade_strength = max(0.0, min(1.0, new_fade))
            if not self._hovered:
                self._do_fade_out()
        # Title (currently unused in the view but kept in sync)
        self._title = str(sticky.get('title') or '')
        _ = changed_text  # currently unused, kept for future signalling

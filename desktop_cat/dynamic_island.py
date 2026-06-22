"""Dynamic-island pill — a floating glance surface for music, next task,
due-today count, and a focus timer.

Modes:
  • Compact   — one lane visible (~300×40 px).  Cycles between music
                (when playing) and next-task every few seconds.
  • Expanded  — on hover, height grows to show all enabled lanes
                stacked (~340×N px), Apple-style.
  • Snapped   — when dragged near a screen edge, slides off-screen and
                leaves a tiny "tab" the user can hover/click to re-summon.
  • Hidden    — fully invisible while a fullscreen app is in front.

Click-through (optional):
  • When enabled, the pill is mouse-transparent so clicks fall through
    to whatever's under it.  A cursor-position poller detects when the
    user actually hovers the pill area for a moment and briefly disables
    the transparent flag so they can interact.

Source of truth for prefs is desktop_cat/island.json (see island_data.py).
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime
from typing import Any

import ctypes
from ctypes import wintypes

from PyQt6.QtCore    import (Qt, QPoint, QRect, QSize, QTimer, QEvent,
                             QPropertyAnimation, QEasingCurve, pyqtSignal)
from PyQt6.QtGui     import (QColor, QPainter, QPainterPath, QFont, QCursor,
                             QPen, QBrush, QGuiApplication)
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
                              QSizePolicy)

from desktop_cat import island_data


# Visual constants — Premium "dark glass" pill from the island-lab.jsx
# reference (tend-island-export).  Translucent near-black body with a
# hairline white border and a drop-shadow.  Warm-white text, accent
# color driven by which lane is showing.
_BG          = QColor(0, 0, 0, 255)         # fully opaque pure black per user spec
_BORDER      = QColor(255, 255, 255, 18)    # 1px hairline — slightly softer over pure black
_OUTLINE     = QColor(0, 0, 0, 90)
_TEXT        = QColor(243, 239, 231)        # #f3efe7 — warm off-white
_TEXT_DIM    = QColor(157, 151, 138)        # #9d978a — muted warm
_ACCENT_PEACH = QColor(223, 142, 106)       # #df8e6a — music
_ACCENT_GREEN = QColor(106, 168, 106)       # #6aa86a — next task
_ACCENT_AMBER = QColor(224, 164, 78)        # #e0a44e — due today
_ACCENT_PURPL = QColor(143, 134, 224)       # #8f86e0 — focus / timer
_ACCENT_TEAL  = QColor(90, 180, 178)         # #5ab4b2 — clipboard
_RADIUS_PX   = 21       # ~half the 42-px height → clean stadium pill

# Sizing — pill BODY is dynamic-width along the major axis, fixed 38px
# along the minor.  Text sizes haven't changed; just the chrome around
# them got tighter ("smaller outer box, text and stuff the same").
#
# Width morphs between 132/170/260 px based on which lane is showing
# (compact / mid / wide).  See _adjust_edge_pos_to_center — width changes
# now grow/shrink the pill from its CENTER, not just its right edge.
#
# Window dimensions are body + _PADDING on each side so the bloop scale
# animation has headroom and doesn't clip at the widget edge.
_PILL_LONG   = 430     # MAX along the major axis (== _MAX_PILL)
_PILL_SHORT  = 42      # along the minor axis (~30% smaller per user)
# Lane width keys — legacy, kept so old refs don't break; width is now
# content-driven (see content_width()), not keyed.
_WIDTHS = {'compact': 160, 'mid': 220, 'wide': 320}

# ── Content-fit sizing ──────────────────────────────────────────────
# The pill major-axis length is CONTENT-DRIVEN: each lane reports
# content_width() and the pill hugs it (clamped below) so there's no
# dead space.  Width grows from the RIGHT edge only.
_MIN_PILL    = 118     # never narrower than this
_MAX_PILL    = 430     # never wider — long titles elide past here
# Shared lane sizing (single source of truth for paint AND hit-test AND
# content_width so they never drift) — all ~30% smaller than before.
_PAD_L      = 10
_PAD_R      = 12
_GAP        = 9
_LEAD_DIA   = 26
_BTN_CELL   = 30       # transport/timer hit cell width (full lane height tall)
_FONT_TITLE = 10
_FONT_SUB   = 8
_FONT_TRAIL = 9
_FONT_GLYPH = 13
_MAX_TEXT_W = 220      # text column caps here, then elides
_MIN_TEXT_W = 56       # floor so short labels ("24:16"/"Focus") never elide
# Padding around pill body inside the window — covers BOTH the bloop
# scale (max ~16 px each side) AND the melting peek flares (up to ~20
# px each side along the anchor edge).
_PADDING     = 24
# How far the melting peek flares extend along the anchor edge at
# visible_frac=0 (fully hidden / heavy peek).  Lerps to 0 at frac=1.
# Bigger = more dramatic "stuck to the screen edge" look when peeking
# a hidden pill via hover.
_PEEK_FLARE_PX = 28
_LANE_H      = _PILL_SHORT
_EDGE_GAP    = 7       # small breathing space when popped
# Horizontal space reserved on the LEFT of the body for the scroll
# arrow, before the lead-icon circle starts.  Read in three places
# (base lane paint, music EQ overlay, menu-icon layout) so the arrow,
# lead circle, and menu buttons all agree on where the handle ends.
_HANDLE_RESERVE = 28

# Behaviour
#
# Polling intervals tuned for low GUI-thread cost.  Earlier the island
# polled SMTC + file IO every 1s on the GUI thread which caused visible
# lag during drag/hover.  Music check is now slow (3 s — music titles
# don't change every second), todo file is mtime-gated, fullscreen poll
# stays at 1.5 s (cheap GetWindowRect call).
_POLL_MS              = 2000       # main poll — todos + lane refresh
_FULLSCREEN_POLL_MS   = 1500
# How long the due-assignment lane stays popped before reverting to the
# timer, and how far ahead of the due time we consider an assignment
# "due soon" (worth a popup).
_DUE_POPUP_MS         = 6000       # ~6 s glance, then back to the timer
_DUE_SOON_MINUTES     = 60         # pop when an assignment is due within this

# Drag / anchor / peek tuning
_DRAG_CLICK_THRESHOLD_PX = 5       # cursor moved < this between press/release → click
# Progressive resistance — perpendicular drag uses `d / sqrt(1 + d/scale)`.
# This is a SQUARE-ROOT growth curve: the pill always keeps moving as the
# cursor moves further, just at an ever-decreasing rate.  Concretely with
# scale=30 the ratios run roughly 1:1.2  → 1:1.7 → 1:2.5 → 1:3.5 → 1:5
# over a few hundred px.  Earlier I used d/(1+d/scale) which ASYMPTOTES
# at `scale`, producing an invisible-wall feel at the far end of a drag.
_RESIST_SCALE_PX         = 30        # legacy — unused after the asymptote rewrite
_RESIST_CAP_PX           = 50        # max pixels the pill can stray from its anchor during drag
# Edge switching requires the cursor to actually reach a CORNER zone.
_CORNER_ZONE_PX          = 120
# Minimize gesture — cursor-space pull toward the anchor.  User wants
# this easy to trigger ("registers I'm trying to hide it earlier when
# I drag it up"), so 10 px is plenty — a small intentional shove.
_MINIMIZE_PUSH_PX        = 25       # cursor px INTO anchor required to hide+unpin — DELIBERATE drag-up only (was 4 which fired on jitter)
_PEEK_SHOWING_PX         = 3       # how much of the pill peeks when fully hidden — just a thin black strip; mask is wider so hover still triggers
_HOVER_PEEK_FRAC         = 0.0     # visible_frac target while hovering hidden — 0 = full melt (max curves)
# When the user hover-peeks a hidden pill, the body sits THIS many px
# below the screen edge.  Curves attach EXACTLY at this gap (lip = gap)
# so there's no visible space between the screen edge and the top of
# the curves.  Smaller = pill closer to edge.  Critical: this also
# determines how far the body needs to "travel" between hidden and
# peek — a smaller gap means less travel, which means less risk of
# the body lerping PAST the user's cursor and causing hover oscillation.
_PEEK_BODY_GAP_PX        = 14
_VISIBLE_FRAC_LERP       = 0.28    # per-tick lerp toward target visibility
_POS_LERP                = 0.32    # per-tick lerp toward anchor-resolved position
# Bloop disabled — user feedback was that it only scaled the painted
# background pill while the child-widget text + icons stayed at 1.0 scale,
# so the pop looked like the pill had a glitchy border instead of a unified
# bounce.  Keeping the variables around (with peak=0) so callers don't break.
# Proper content-scaled bloop would need to rebuild the lane render in
# paintEvent (no child widgets); revisit when there's time.
_BLOOP_DURATION_MS       = 1
_BLOOP_PEAK              = 0.0     # disabled
_BLOOP_PEAK_PHASE        = 0.22

# When the cursor enters the pill, slide it OUT a few extra pixels from
# the anchor so it visually "pops" toward the user.  Lerped via the
# normal anim tick — no extra timer.
_HOVER_OFFSET_PX         = 10
_HOVER_LERP              = 0.22    # per-tick interpolation toward target
_AUTO_HIDE_MS            = 2500    # popped pill auto-hides after cursor leaves zone this long
_PEEK_GLANCE_MS          = 2200    # how long the pill peeks out when its display changes
_ANIM_TIMER_MS           = 16      # ~60 fps


# ── Windows fullscreen detection ────────────────────────────────────────

def _foreground_is_fullscreen() -> bool:
    """True if the foreground window covers the entire primary screen.
    A real "fullscreen" game/video; a maximized normal window does NOT
    count because Windows shrinks it slightly to keep the taskbar visible.
    """
    if sys.platform != 'win32':
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        # CRITICAL: ignore our OWN windows.  The overlay is itself a
        # fullscreen-sized transparent window, so when the user clicks Sao or a
        # flower and it takes focus, it would otherwise look "fullscreen" and we
        # would hide everything.  Only real OTHER apps count.
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        return (rect.left <= 0 and rect.top <= 0
                and rect.right >= screen_w and rect.bottom >= screen_h)
    except Exception:
        return False


# ── Helpers ─────────────────────────────────────────────────────────────

def _fmt_relative_due(due_iso: str | None) -> str:
    """Tiny date → 'due in 2h' / 'due Fri' / 'due 5d' helper."""
    if not due_iso:
        return ''
    try:
        d = date.fromisoformat(due_iso[:10])
    except Exception:
        return ''
    today = date.today()
    delta = (d - today).days
    if delta < 0:  return f'overdue {-delta}d'
    if delta == 0: return 'due today'
    if delta == 1: return 'due tmrw'
    if delta < 7:  return f'due {["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d.weekday()]}'
    return f'due in {delta}d'


_TODOS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                            'library_todos.json')
_TODOS_CACHE: list[dict] = []
_TODOS_MTIME: float = -1.0


def _read_library_todos() -> list[dict]:
    """Cheap getter — reads & parses the todos JSON only when the file's
    mtime has changed since the last call.  Previously this opened the
    file twice per second (once per lane in _NextTask/_DueToday refresh),
    which was a real ~5-15 ms hit per poll on a non-cold file system.
    Now both lanes share the cached list and re-parse only on actual change.
    """
    global _TODOS_CACHE, _TODOS_MTIME
    try:
        mt = os.path.getmtime(_TODOS_PATH)
    except OSError:
        return _TODOS_CACHE
    if mt == _TODOS_MTIME:
        return _TODOS_CACHE
    try:
        with open(_TODOS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _TODOS_CACHE = data if isinstance(data, list) else []
        _TODOS_MTIME = mt
    except (OSError, ValueError):
        pass
    return _TODOS_CACHE


# ── Single-lane content widgets ─────────────────────────────────────────

class _Lane(QFrame):
    """Base lane row.  Subclasses set self._title / self._sub / self._dot
    in refresh() and call self.update().

    Two orientations:
      • horizontal — drawn left-to-right, used on top anchor
      • vertical   — painter rotated 90° clockwise so text reads down
                      the screen, used on left/right anchors
    """
    clicked = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        # No fixed height/width — orientation drives dimensions.  Lane
        # expands to fill the body's allocated space.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._label = label
        self._title = ''
        self._sub   = ''
        # Title point size + weight — subclasses can bump them (the timer
        # lane shows big bold clock digits now that its sub-label is gone).
        self._title_pt = _FONT_TITLE
        self._title_weight = QFont.Weight.DemiBold
        self._dot   = None        # legacy — kept so existing subclasses don't break; unused in new paint
        self._right = ''          # trail text (right-aligned badge / chevron)
        self._visible_lane = True
        self._vertical: bool = False
        # Premium-style attrs — subclasses override.
        self._accent: QColor    = _TEXT        # per-lane accent color
        self._icon_char: str    = '•'          # fallback glyph (used only if _icon_kind is '')
        self._icon_kind: str    = ''           # vector lead icon: 'clock'|'note'|'star'|'bang'
        self._width_key: str    = 'wide'       # body major-axis width key (compact/mid/wide)
        # Hover state — driven by DynamicIsland's enter/leaveEvent.  When
        # true the lane paints a 3-stripe drag handle on the far left
        # ahead of the lead-icon circle.
        self._hover: bool       = False
        # Pin state — pushed from DynamicIsland.  When True, the drag
        # handle renders as a small pin / filled dot to show the pill
        # is locked open.
        self._pinned: bool      = False
        # Optional progress arc rendered AROUND the lead-icon circle.
        # 0.0 = no arc, 1.0 = full circle.  Subclasses set this in
        # refresh() to indicate progress (e.g. _TimerLane fills the arc
        # as the focus timer counts down).  Rendered in the lane's
        # accent color so it ties visually to the icon.
        self._progress_arc: float = 0.0

    def set_vertical(self, vertical: bool) -> None:
        self._vertical = bool(vertical)
        self.update()

    def set_hover(self, hover: bool) -> None:
        if self._hover == bool(hover):
            return
        self._hover = bool(hover)
        self.update()

    def set_pinned(self, pinned: bool) -> None:
        if self._pinned == bool(pinned):
            return
        self._pinned = bool(pinned)
        self.update()

    def _extra_trail_reserve(self) -> int:
        """Subclasses override to reserve extra horizontal space on the
        right of the body text — e.g. _MusicLane paints transport
        buttons over the trail area and needs the title to elide
        before those buttons rather than overlap them."""
        return 0

    def content_width(self) -> int:
        """Pixel width the pill needs to show THIS lane snugly — drives
        the content-fit sizing so the pill hugs its contents (no dead
        space).  Uses the SAME constants the paint code uses.

        Memoized on (title, sub, right) because this is called from the
        60-fps animation tick (via _window_size_for_anchor) and building
        a QFontMetrics every frame would be needless churn."""
        key = (self._title, self._sub, self._right, self._extra_trail_reserve())
        if getattr(self, '_cw_key', None) == key:
            return self._cw_val
        from PyQt6.QtGui import QFont, QFontMetrics
        # Measure with the lane's ACTUAL title font (subclasses bump size /
        # weight — e.g. the timer's big bold digits), else the pill sizes
        # itself for 10pt text and clips the wider glyphs ("25:00" → "24…").
        tf = QFont('Segoe UI', self._title_pt); tf.setWeight(self._title_weight)
        sf = QFont('Segoe UI', _FONT_SUB);   sf.setWeight(QFont.Weight.Medium)
        tw = max(QFontMetrics(tf).horizontalAdvance(self._title or ''),
                 QFontMetrics(sf).horizontalAdvance(self._sub or ''))
        tw = max(_MIN_TEXT_W, min(tw, _MAX_TEXT_W))
        left  = _PAD_L + _LEAD_DIA + _GAP
        right = _PAD_R + self._extra_trail_reserve()
        if self._right:
            bf = QFont('Segoe UI', _FONT_TRAIL); bf.setWeight(QFont.Weight.DemiBold)
            right += QFontMetrics(bf).horizontalAdvance(self._right) + 2 * 7 + 8
        self._cw_key = key
        self._cw_val = int(left + tw + right)
        return self._cw_val

    @staticmethod
    def _draw_transport_icon(p, rect: QRect, kind: str, color: QColor,
                              scale: float = 1.0) -> None:
        """Draw a FAT transport icon as a filled QPainterPath shape,
        centered on rect.center().  No background circle — the icon IS
        the button.  `scale` enlarges the whole icon for the hover/press
        'pop'.  All icons occupy the SAME ~16×16 visual box.
        Kinds used now: 'play', 'pause'.  ('prev'/'next' kept for any
        future use but the music lane that used them is gone.)"""
        cx, cy = rect.center().x(), rect.center().y()
        s = scale
        p.setBrush(color); p.setPen(Qt.PenStyle.NoPen)
        if kind == 'play':
            ww, h = int(15 * s), int(16 * s)
            x0 = cx - ww // 2 - 1     # optical nudge for the triangle mass
            path = QPainterPath()
            path.moveTo(x0,      cy - h // 2)
            path.lineTo(x0,      cy + h // 2)
            path.lineTo(x0 + ww, cy)
            path.closeSubpath()
            p.drawPath(path)
        elif kind == 'pause':
            bw, bh, gap = int(5 * s), int(16 * s), int(5 * s)
            total = 2 * bw + gap
            x0 = cx - total // 2
            r = max(1, int(2 * s))
            p.drawRoundedRect(x0,            cy - bh // 2, bw, bh, r, r)
            p.drawRoundedRect(x0 + bw + gap, cy - bh // 2, bw, bh, r, r)

    @staticmethod
    def _draw_lead_icon(p: QPainter, rect: QRect, kind: str, color: QColor) -> None:
        """Draw a lead-circle icon as a vector shape, geometrically
        centered in `rect`.  Replaces the font glyphs (which centered
        inconsistently).  Kinds: 'clock', 'note', 'star', 'bang'."""
        cx, cy = rect.center().x(), rect.center().y()
        if kind == 'clock':
            ring = QPen(color, 2.0); ring.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(ring); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(rect.adjusted(6, 6, -6, -6))     # ~14-dia face
            hand = QPen(color, 2.0); hand.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(hand)
            p.drawLine(cx, cy, cx, cy - 5)                 # minute (up)
            p.drawLine(cx, cy, cx + 4, cy + 1)             # hour
        elif kind == 'note':
            # Eighth note — filled head + stem + flag.
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
            p.drawEllipse(QRect(cx - 6, cy + 1, 7, 5))
            stem = QPen(color, 2.0); stem.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(stem)
            p.drawLine(cx + 1, cy + 4, cx + 1, cy - 7)
            p.drawLine(cx + 1, cy - 7, cx + 4, cy - 4)
        elif kind == 'star':
            # 4-point sparkle (concave star).
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
            s = 8
            path = QPainterPath()
            path.moveTo(cx, cy - s)
            path.quadTo(cx, cy, cx + s, cy)
            path.quadTo(cx, cy, cx, cy + s)
            path.quadTo(cx, cy, cx - s, cy)
            path.quadTo(cx, cy, cx, cy - s)
            p.drawPath(path)
        elif kind == 'bang':
            # Exclamation — vertical bar + dot.
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
            p.drawRoundedRect(cx - 1, cy - 8, 3, 10, 1, 1)
            p.drawEllipse(QRect(cx - 1, cy + 4, 3, 3))
        elif kind == 'clip':
            # Clipboard — board + clip + content lines (for the clipboard lane).
            board = QPen(color, 2.0); board.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(board); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRect(cx - 6, cy - 7, 12, 14), 2, 2)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
            p.drawRoundedRect(cx - 4, cy - 10, 8, 4, 1, 1)     # clip
            p.setPen(QPen(color, 1.5, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(cx - 3, cy - 1, cx + 3, cy - 1)
            p.drawLine(cx - 3, cy + 3, cx + 1, cy + 3)

    def refresh(self) -> None:
        """Override.  Pull fresh data into self._title/self._sub/etc."""
        pass

    # NOTE: lanes are mouse-transparent (WA_TransparentForMouseEvents set
    # in DynamicIsland.__init__) — they never receive mouse events.  All
    # input is owned by DynamicIsland._dispatch_click.  The old
    # mouseReleaseEvent → clicked signal handler was removed because it
    # caused double dispatch.  `clicked` is kept as a no-op-friendly
    # signal only so legacy connect() calls don't crash.

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        # When the pill is vertical (left/right anchor), rotate the
        # painter 90° clockwise so we can use the same horizontal layout
        # math.  In this rotated frame, the "horizontal width" of the
        # lane is self.height(), and the "vertical height" is self.width().
        if self._vertical:
            p.translate(self.width(), 0)
            p.rotate(90)
            w, h = self.height(), self.width()
        else:
            w, h = self.width(), self.height()

        # ── Layout: [ lead circle ]  [ title / sub ]  [ trail ] ──
        # All dimensions come from the shared sizing constants (single
        # source of truth, also used by content_width + hit-test).
        pad_l, pad_r, gap = _PAD_L, _PAD_R, _GAP
        lead_dia = _LEAD_DIA
        cy = h // 2

        # Lead circle — accent-tinted background + accent-colored icon.
        # Sits flush at pad_l now that the carousel scroll-dot is gone.
        lead_x = pad_l
        lead_rect = QRect(lead_x, cy - lead_dia // 2, lead_dia, lead_dia)
        tinted = QColor(self._accent)
        tinted.setAlpha(70)      # ~26% mix over the dark glass
        p.setBrush(tinted); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(lead_rect)
        # Optional progress arc OUTSIDE the lead circle (timer elapsed).
        if self._progress_arc > 0.0:
            arc_pen = QPen(self._accent, 2)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(arc_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            arc_rect = lead_rect.adjusted(-2, -2, 2, 2)
            span = -int(max(0.0, min(1.0, self._progress_arc)) * 5760)
            p.drawArc(arc_rect, 90 * 16, span)
        # Lead icon.  Prefer a custom VECTOR icon (geometrically centered
        # in the circle) over a font glyph — Segoe UI Symbol glyphs like
        # ◷ have inconsistent internal padding so AlignCenter left them
        # visibly off (user: "the clock icon is also off").  Falls back
        # to the glyph only if a lane hasn't declared an _icon_kind.
        if getattr(self, '_icon_kind', ''):
            self._draw_lead_icon(p, lead_rect, self._icon_kind, self._accent)
        elif self._icon_char:
            icon_font = QFont('Segoe UI Symbol', _FONT_GLYPH)
            icon_font.setWeight(QFont.Weight.DemiBold)
            p.setFont(icon_font)
            p.setPen(self._accent)
            p.drawText(lead_rect, Qt.AlignmentFlag.AlignCenter, self._icon_char)

        # 2. Trail — right-aligned text in a soft accent pill if `_right`
        # contains non-whitespace.
        trail_font = QFont('Segoe UI', _FONT_TRAIL)
        trail_font.setWeight(QFont.Weight.DemiBold)
        trail_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 96)
        trail_w = 0
        trail_rect = None
        if self._right:
            p.setFont(trail_font)
            trail_text_w = p.fontMetrics().horizontalAdvance(self._right)
            trail_pad_x  = 7
            trail_h      = 20
            trail_w      = trail_text_w + 2 * trail_pad_x
            trail_rect   = QRect(w - pad_r - trail_w, cy - trail_h // 2,
                                 trail_w, trail_h)
            badge_bg = QColor(self._accent)
            badge_bg.setAlpha(50)
            p.setBrush(badge_bg); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(trail_rect, 10, 10)
            p.setPen(self._accent)
            p.drawText(trail_rect, Qt.AlignmentFlag.AlignCenter, self._right)

        # 3. Body — title (14pt 600) above sub (11.5pt dim), stacked.
        body_x = lead_x + lead_dia + gap
        # Subclasses can reserve extra space on the right for lane-specific
        # widgets they paint over the trail area (e.g. _MusicLane's pair
        # of play/pause + next buttons).  Without this the title text
        # would elide based only on the base trail badge width and
        # overlap the music transport controls.
        extra_trail = self._extra_trail_reserve()
        body_w = max(0, w - body_x - pad_r - (trail_w + 8 if trail_w else 0) - extra_trail)
        title_font = QFont('Segoe UI', self._title_pt)
        title_font.setWeight(self._title_weight)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 97)
        sub_font   = QFont('Segoe UI', _FONT_SUB)
        sub_font.setWeight(QFont.Weight.Medium)

        title = self._title or ''
        sub   = self._sub   or ''
        if sub:
            # Two-row stack — centered vertically as a group.
            row_h = h // 2
            title_rect = QRect(body_x, 2,           body_w, row_h)
            sub_rect   = QRect(body_x, row_h - 2,   body_w, row_h)
            p.setFont(title_font); p.setPen(_TEXT)
            elided = p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, body_w)
            p.drawText(title_rect,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       elided)
            p.setFont(sub_font); p.setPen(_TEXT_DIM)
            elided_sub = p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, body_w)
            p.drawText(sub_rect,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       elided_sub)
        else:
            # Single row — vertically centered.
            p.setFont(title_font); p.setPen(_TEXT)
            elided = p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, body_w)
            p.drawText(QRect(body_x, 0, body_w, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       elided)



class _NextTaskLane(_Lane):
    def __init__(self, parent=None):
        super().__init__('next task', parent)
        self._accent    = _ACCENT_GREEN
        self._icon_char = '✦'             # small flourish — reads as "task / focus"
        self._icon_kind = 'star'
        self._width_key = 'wide'
        # Transient override: a just-planted assignment to flash for a moment.
        self._override_title = ''
        self._override_until_ms = 0.0

    def set_override(self, title: str, ms: int = 3200) -> None:
        from PyQt6.QtCore import QDateTime
        self._override_title = str(title or '')[:60]
        self._override_until_ms = QDateTime.currentMSecsSinceEpoch() + ms

    def refresh(self) -> None:
        """This lane is the DUE-ASSIGNMENT POPUP.  It's only `_visible_lane`
        (i.e. poppable) when the soonest open assignment is due TODAY or
        overdue — that's the "a brief bit beforehand" trigger.  Otherwise
        it stays hidden and the pill shows the timer.  `_popup_key` is a
        stable id so the same assignment only pops once."""
        # A freshly-planted assignment temporarily takes over the popup.
        from PyQt6.QtCore import QDateTime
        if (self._override_title
                and QDateTime.currentMSecsSinceEpoch() < self._override_until_ms):
            self._title = self._override_title
            self._sub   = 'just planted 🌱'
            self._right = 'new'
            self._visible_lane = True
            self._popup_key = f"plant|{self._override_title}"
            return
        todos = _read_library_todos()
        today = date.today()
        candidates = [t for t in todos
                      if not t.get('done') and t.get('due')]
        candidates.sort(key=lambda t: t.get('due') or '9999')
        soon = None
        for t in candidates:
            try:
                d = date.fromisoformat((t.get('due') or '')[:10])
            except Exception:
                continue
            if (d - today).days <= 0:      # due today or overdue
                soon = (t, d); break
        if soon is None:
            self._visible_lane = False
            self._popup_key = ''
            self._title = ''; self._sub = ''; self._right = ''
            return
        t, d = soon
        self._title = t.get('name') or '(untitled)'
        self._sub   = _fmt_relative_due(t.get('due'))
        self._right = 'now' if (d - today).days == 0 else 'due'
        self._visible_lane = True
        self._popup_key = f"{self._title}|{t.get('due')}"



class _TimerLane(_Lane):
    """Self-contained 25-min focus timer with VISIBLE play/pause + reset
    buttons in the trail (user-requested: "i dont see a pause button
    for the timer").  Per-button hover feedback + press flash, same as
    music lane.
    """
    def __init__(self, parent=None):
        super().__init__('timer', parent)
        self._accent    = _ACCENT_PURPL
        self._icon_char = '◷'             # fallback only
        self._icon_kind = 'clock'         # vector clock — centered, unlike the glyph
        self._width_key = 'mid'           # short content; let the pill shrink
        self._title_pt     = _FONT_TITLE + 3           # bigger clock digits (sub-label removed)
        self._title_weight = QFont.Weight.Bold         # thicker, clock-like
        # Mode + duration come from settings (island.json), set from the
        # app window — NOT from inside the pill.  'pomodoro' uses
        # pomodoro_minutes; 'timer' uses timer_minutes.
        self._mode      = self._load_mode()
        self._total_s   = self._load_duration_s()
        self._left_s    = self._total_s
        self._running   = False
        # Pomodoro auto-cycle: when a work interval ends we flip to a short
        # break, then back to work, and so on (a gentle chime marks each
        # switch).  Quick-timer mode never cycles.
        self._on_break  = False
        # Mirrors island.json timer_start_token; when the window bumps it
        # the pill (re)starts a fresh countdown.  -1 so the first real
        # token (>=0) doesn't auto-fire on launch.
        self._start_token = -1
        # Mirrors island.json timer_stop_token — a bump = "reset + pause".
        self._stop_token  = -1
        # Brief green tint on the timer after a fresh start.
        self._green_until_ms = 0.0
        self._tick = QTimer(self); self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        # NOTE: do NOT connect clicked→_toggle.  The lane is mouse-
        # transparent; play/pause is driven solely by the parent's
        # _dispatch_click hitting the play_pause button_rect.  The old
        # `clicked.connect(self._toggle)` meant ANY click reaching the
        # timer lane (incl. the scroll dot) toggled the timer.
        # Visual feedback state — kept in sync from
        # DynamicIsland._refresh_hover_from_cursor (hover) and
        # DynamicIsland._dispatch_click (press flash).
        self._hovered_btn: str = ''
        self._flash_btn: str = ''
        self._flash_end_ms: float = 0.0

    def _extra_trail_reserve(self) -> int:
        # Two hit cells (play/pause + reset) + gap + buffer.
        return 2 * _BTN_CELL + 2 + 8

    def button_rects(self, w: int, h: int) -> list[tuple[str, QRect]]:
        """Geometry of the timer's transport buttons in lane-local coords.
        Full-height hit cells — generous so clicks register."""
        pad_r, cell, gap = _PAD_R, _BTN_CELL, 2
        reset_x = w - pad_r - cell
        pp_x    = reset_x - gap - cell
        return [('play_pause', QRect(pp_x,    0, cell, h)),
                ('reset',      QRect(reset_x, 0, cell, h))]

    def flash_button(self, kind: str) -> None:
        from PyQt6.QtCore import QDateTime
        self._flash_btn = kind
        self._flash_end_ms = QDateTime.currentMSecsSinceEpoch() + 150
        self.update()
        QTimer.singleShot(170, self.update)

    def update_hovered_button(self, local_pos: QPoint) -> None:
        w = self.height() if self._vertical else self.width()
        h = self.width()  if self._vertical else self.height()
        new = ''
        for kind, rect in self.button_rects(w, h):
            if rect.contains(local_pos):
                new = kind; break
        if new != self._hovered_btn:
            self._hovered_btn = new
            self.update()

    @staticmethod
    def _load_mode() -> str:
        try:
            m = str(island_data.load().get('timer_mode', 'pomodoro'))
        except Exception:
            m = 'pomodoro'
        return m if m in ('pomodoro', 'timer') else 'pomodoro'

    def _load_duration_s(self, prefs: dict | None = None) -> int:
        """Active mode's length (minutes) → seconds, clamped 1..180.
        Reads `prefs` if given, else the live island.json."""
        try:
            if prefs is None:
                prefs = island_data.load()
            key = 'timer_minutes' if self._mode == 'timer' else 'pomodoro_minutes'
            mins = int(prefs.get(key, 5 if self._mode == 'timer' else 25))
        except Exception:
            mins = 5 if self._mode == 'timer' else 25
        mins = max(1, min(180, mins))
        return mins * 60

    def sync_from_prefs(self, prefs: dict) -> bool:
        """Called when island.json changes.  Picks up mode + duration
        changes, and (re)starts the countdown when the window bumps
        timer_start_token.  Returns True if a start-token bump (re)started
        the timer — the island uses this to peek the pill out."""
        new_mode = prefs.get('timer_mode', 'pomodoro')
        if new_mode not in ('pomodoro', 'timer'):
            new_mode = 'pomodoro'
        if new_mode != self._mode:
            self._mode = new_mode
        new_total = self._load_duration_s(prefs)
        # A stop-token bump = explicit "reset + pause the timer now".
        stop_tok = int(prefs.get('timer_stop_token', 0) or 0)
        if self._stop_token < 0:
            self._stop_token = stop_tok          # adopt baseline on first sync
        elif stop_tok != self._stop_token:
            self._stop_token = stop_tok
            self.reset()
        # A start-token bump = explicit "start the active timer now".
        token = int(prefs.get('timer_start_token', 0) or 0)
        if token != self._start_token:
            self._start_token = token
            self._on_break = False          # a fresh start always begins with work
            self._total_s = new_total
            self._left_s  = new_total
            self._running = True
            from PyQt6.QtCore import QDateTime
            self._green_until_ms = QDateTime.currentMSecsSinceEpoch() + 1100
            if not self._tick.isActive():
                self._tick.start()
            self.refresh(); self.update()
            return True
        # No explicit start — just keep an at-rest timer's length current.
        if new_total != self._total_s:
            at_rest = (not self._running and self._left_s == self._total_s)
            self._total_s = new_total
            if at_rest:
                self._left_s = new_total
            self.refresh(); self.update()
        return False

    # Back-compat alias (DynamicIsland._maybe_reload_prefs used to call this).
    def reload_duration(self) -> None:
        self.sync_from_prefs(island_data.load())

    def mouseDoubleClickEvent(self, e) -> None:
        # Double-click anywhere on the lane resets the timer.
        self.reset()

    def _toggle(self) -> None:
        self._running = not self._running
        if self._running:
            if self._left_s <= 0: self._left_s = self._total_s
            self._tick.start()
        else:
            self._tick.stop()
        self.refresh()
        self.update()

    def _break_s(self) -> int:
        """Break length (minutes → seconds), from island.json break_minutes
        (default 5), clamped 1..60."""
        try:
            mins = int(island_data.load().get('break_minutes', 5))
        except Exception:
            mins = 5
        return max(1, min(60, mins)) * 60

    def _play_switch_chime(self) -> None:
        try:
            from desktop_cat import sounds
            sounds.play('softbell', volume=0.7)
        except Exception:
            pass

    def _notify_island_switch(self) -> None:
        """Ask the parent island to pop the pill out so a hidden pill still
        notifies the user that the timer flipped / finished."""
        try:
            win = self.window()
            if hasattr(win, 'notify_timer_switch'):
                win.notify_timer_switch()
        except Exception:
            pass

    def _on_tick(self) -> None:
        if self._left_s > 0:
            self._left_s -= 1
        elif self._mode == 'pomodoro':
            # Work interval (or break) just ended — auto-flip to the other
            # and keep running.  A gentle chime + green flash mark the switch.
            self._on_break = not self._on_break
            self._total_s  = self._break_s() if self._on_break else self._load_duration_s()
            self._left_s   = self._total_s
            from PyQt6.QtCore import QDateTime
            self._green_until_ms = QDateTime.currentMSecsSinceEpoch() + 1100
            self._play_switch_chime()
            self._notify_island_switch()
        else:
            # Quick-timer: stop at zero (with the same soft chime).
            self._running = False
            self._tick.stop()
            self._play_switch_chime()
            self._notify_island_switch()
        self.refresh()
        # CRITICAL: repaint every tick.  Without this the seconds
        # decrement in memory but the widget only repaints when some
        # OTHER event triggers paint (hover etc.), so the clock looked
        # "stuck at 20:00 then jumped" — exactly the reported bug.
        self.update()

    def refresh(self) -> None:
        mm = self._left_s // 60
        ss = self._left_s %  60
        self._title = f'{mm:02d}:{ss:02d}'
        # Progress arc — sweeps clockwise as the timer counts down.
        if self._total_s > 0 and self._left_s < self._total_s:
            self._progress_arc = (self._total_s - self._left_s) / self._total_s
        else:
            self._progress_arc = 0.0
        # No sub-label at all — the pill shows ONLY the big, centered clock
        # digits.  (The play/pause button already conveys running vs paused,
        # so the old 'Focus' / 'Timer' / '25 min' text was just noise.)
        self._sub   = ''
        self._right = ''
        self._visible_lane = True
        # During a Pomodoro break the icon tints green so work vs. break
        # reads at a glance; otherwise the normal purple accent.
        self._accent = QColor(78, 206, 120) if self._on_break else _ACCENT_PURPL

    def reset(self) -> None:
        # Back to a fresh work interval — clear any break state and reload
        # the configured length (the break length must not stick around).
        self._on_break = False
        self._total_s  = self._load_duration_s()
        self._left_s   = self._total_s
        self._running  = False
        self._tick.stop()
        self.refresh()
        self.update()

    def paintEvent(self, evt) -> None:
        # Suppress base trail badge.
        saved_right = self._right
        self._right = ''
        # Green hue-shift for ~1 s right after a fresh start.
        from PyQt6.QtCore import QDateTime as _QDT
        _green = _QDT.currentMSecsSinceEpoch() < self._green_until_ms
        saved_accent = self._accent
        if _green:
            self._accent = QColor(78, 206, 120)
        super().paintEvent(evt)
        self._accent = saved_accent
        self._right = saved_right
        if not self._visible_lane:
            return
        # Custom transport buttons: [ play/pause | reset ]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._vertical:
            p.translate(self.width(), 0); p.rotate(90)
            w, h = self.height(), self.width()
        else:
            w, h = self.width(), self.height()
        from PyQt6.QtCore import QDateTime
        now_ms = QDateTime.currentMSecsSinceEpoch()
        for kind, rect in self.button_rects(w, h):
            flashing = (self._flash_btn == kind and now_ms < self._flash_end_ms)
            hovered  = (self._hovered_btn == kind)
            # No circle — fat white icon that pops on hover/press, same
            # feel as the music transport buttons.
            scale = 1.18 if flashing else (1.10 if hovered else 1.0)
            col_v = 255 if (flashing or hovered) else 225
            white = QColor(col_v, col_v, col_v)
            if kind == 'play_pause':
                self._draw_transport_icon(
                    p, rect, 'pause' if self._running else 'play', white, scale)
            elif kind == 'reset':
                # Reset icon — circular-arrow (3/4 circle + arrowhead).
                # rad 7 → 14px wide so it matches the pause's ~16px box
                # (was 18px, too big), and a fatter 3.6px stroke so it
                # reads as heavy as the pause's solid bars.
                cx, cy = rect.center().x(), rect.center().y()
                rad = int(7 * scale)
                pen = QPen(white, 3.6 * scale)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
                arc_rect = QRect(cx - rad, cy - rad, 2 * rad, 2 * rad)
                p.drawArc(arc_rect, 30 * 16, 270 * 16)
                import math
                ang = math.radians(30)
                tip_x = cx + rad * math.cos(ang)
                tip_y = cy - rad * math.sin(ang)
                a = 3.4 * scale     # bigger arrowhead to match the fatter stroke
                p.setBrush(white); p.setPen(Qt.PenStyle.NoPen)
                arrow = QPainterPath()
                arrow.moveTo(tip_x + a,     tip_y - a)
                arrow.lineTo(tip_x - a * 1.6, tip_y)
                arrow.lineTo(tip_x + a * 0.5, tip_y + a * 2)
                arrow.closeSubpath()
                p.drawPath(arrow)




# ── Main island widget ─────────────────────────────────────────────────

class DynamicIsland(QWidget):
    # Emitted when the user clicks a lane that "represents" something the
    # hub window can show in detail.  main.py wires this to the same
    # handler the hut/tray uses, so clicking a task in the pill pops the
    # Library Hub open at the to-do tab.
    open_hub_requested = pyqtSignal()
    # Emitted (True/False) when a fullscreen app appears / disappears, so the
    # main overlay can hide Sao + décor too (not just the pill).
    fullscreen_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint
                                | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # Translucent background means the pill body is custom-painted in
        # paintEvent.  Children sit on top of that.

        # The pill is now TIMER-FOCUSED.  Music + clipboard + the carousel
        # menu were removed (music's SMTC subprocess was the main lag
        # source, and the carousel added confusing surface area).  Two
        # lanes only:
        #   • index 0 — the focus/pomodoro/custom TIMER (the normal display)
        #   • index 1 — next-due assignment, shown only as a BRIEF auto
        #               popup when something's due soon, then reverts to
        #               the timer.
        # Starting / configuring timers happens in the app-window settings;
        # the pill just runs the active timer + offers play/pause + reset.
        self._lanes: list[_Lane] = [
            _TimerLane(self),
            _NextTaskLane(self),
        ]

        self._body = QWidget(self)
        # CRITICAL: the body + lanes are PURE PAINTERS.  All mouse input
        # must reach DynamicIsland itself so the single _dispatch_click /
        # drag state machine owns every click.  Without this the child
        # lane widgets received their OWN mouseReleaseEvents and fired a
        # SECOND, competing action (e.g. _TimerLane.clicked→_toggle, or
        # _MusicLane's stale hardcoded x-zone play/pause) — that double
        # dispatch is what caused: songs skipping on edge-switch, needing
        # a double-click on the music carousel, and the timer toggling
        # when you clicked the scroll dot.  Mouse-transparent children
        # route 100% of input to the parent.
        self._body.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(4, 4, 4, 4)
        self._body_layout.setSpacing(0)
        for l in self._lanes:
            l.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._body_layout.addWidget(l)

        # Hover state.  When the cursor enters the pill we lerp two
        # things via the normal anim tick:
        #   • the lane's drag-handle bars (drawn on the left of the lane
        #     paintEvent when self._mouse_over)
        #   • _hover_offset — pushes the pill OUT from its anchor edge
        #     by up to _HOVER_OFFSET_PX, so the pill visibly "pops"
        #     toward the user.
        self._mouse_over = False
        self._hover_offset: float = 0.0    # current interpolated value
        # Pin state — clicking the drag-handle icon (3-stripes on left
        # of the expanded pill) toggles this.  When pinned, the pill
        # stays in expanded position even when the cursor leaves the
        # hover zone.  Click again to unpin.
        self._pinned: bool = False
        self._mouse_left_ms: float = 0.0   # timestamp cursor left zone (0 = currently over)
        # Transient peek: timestamp (ms) until which the pill stays popped
        # out even without hover/pin.  Bumped by peek() whenever the
        # display changes (timer started, view switched, due popup) so the
        # pill briefly slides into view to show the update, then retracts.
        self._peek_until_ms: float = 0.0

        # Display selection.  index 0 = TIMER (the normal display).
        # index 1 = next-due assignment, surfaced ONLY as a brief auto
        # popup by _poll_all when something's due soon, then reverts to
        # the timer.  `_due_popup_until_ms` is the timestamp the popup
        # ends; while it's in the future the due lane is shown.
        self._compact_idx = 0                      # default to the timer
        self._due_popup_until_ms: float = 0.0
        self._due_popup_key: str = ''              # which assignment is popped (dedupe)

        # Periodic refresh.  Lane data + priority selection.  Cheap —
        # mtime-gated todo file read + cached SMTC snapshot read.  SMTC
        # polling itself now happens in a daemon background thread inside
        # smtc_reader.SmtcReader, so this Qt timer never blocks the GUI.
        self._poll_timer = QTimer(self); self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_all)
        self._poll_timer.start()

        # Slow hover-poll timer.  When the pill is hidden+idle the
        # anim_timer is stopped to save CPU; this slower timer polls
        # cursor position to detect when the user moves into the hover
        # zone, then kicks the anim_timer to play the peek-out animation.
        # Without this, the polled hover override only worked while
        # already animating — Qt's enterEvent would fire unreliably on
        # the mask's rounded corners and we'd miss hover starts.
        self._hover_poll_timer = QTimer(self); self._hover_poll_timer.setInterval(50)
        self._hover_poll_timer.timeout.connect(self._poll_hover_wake)
        self._hover_poll_timer.start()

        # Fullscreen poller — independent so it stays cheap
        self._fs_timer = QTimer(self); self._fs_timer.setInterval(_FULLSCREEN_POLL_MS)
        self._fs_timer.timeout.connect(self._check_fullscreen)
        self._fs_timer.start()
        self._hidden_for_fullscreen = False

        # Click-through wake poller (only running when click-through is on)
        self._wake_timer = QTimer(self); self._wake_timer.setInterval(100)
        self._wake_timer.timeout.connect(self._click_through_poll)
        self._wake_last_in_pill_ms: float = 0.0
        self._click_through_armed = False  # currently set transparent?

        # Drag state — anchor-locked dragging with rubber-band resistance.
        self._dragging              = False
        self._drag_press_global     = QPoint()  # cursor at mousedown
        self._drag_press_anchor     = ''        # anchor at mousedown
        self._drag_press_edge_pos   = 0         # edge_pos at mousedown
        self._drag_press_hidden     = False
        self._drag_press_window_pos = QPoint()  # window pos at mousedown
        # Max INTO-the-anchor cursor pull (cursor-space, not resisted).
        # Used to detect deliberate "shove against the edge" gestures vs
        # accidental brushes against the screen border.
        self._drag_max_into_anchor  = 0
        # Set True by _maybe_smart_anchor_switch when a mid-drag anchor
        # morph is in flight — mouseMoveEvent skips drag math during this
        # window so cursor moves don't fight the QPropertyAnimation.
        self._drag_morph_pending: bool = False

        # Anchor model — pill always docked to top/left/right edge.
        self._anchor: str   = 'top'        # set from prefs below
        self._edge_pos: int = 0            # x on top, y on side
        self._hidden: bool  = False        # tucked against the anchor edge?
        self._visible_frac: float = 1.0    # 0=fully hidden, 1=fully active
        # Bloop animation — small scale pop when un-hiding.  Tracks the
        # END timestamp (ms); paintEvent computes a 0..1 phase from now.
        self._bloop_end_ms:  float = 0.0
        # Anchor-morph animation — set when the user switches anchors
        # (top → side, etc.).  While active, the per-tick position lerp
        # is skipped so the morph's geometry animation isn't fought.
        self._morph_anim:   QPropertyAnimation | None = None
        self._morph_active: bool = False
        # Animation timer — drives smooth slides for both visible_frac and
        # the window's actual position (lerps toward anchor-resolved target).
        self._anim_timer = QTimer(self); self._anim_timer.setInterval(_ANIM_TIMER_MS)
        self._anim_timer.timeout.connect(self._tick_animation)

        # Load settings + apply geometry/transparency
        self._prefs = island_data.load()
        self._prefs_mtime = island_data.mtime()
        # 800 ms so a window "Start" / settings change reaches the pill
        # quickly (it just stats island.json mtime — cheap).
        self._prefs_check_timer = QTimer(self); self._prefs_check_timer.setInterval(800)
        self._prefs_check_timer.timeout.connect(self._maybe_reload_prefs)
        self._prefs_check_timer.start()

        # IMPORTANT: do NOT enable mouseTracking.  With it on, the widget
        # gets a mouseMoveEvent for every single pixel of cursor movement
        # while hovering the pill (no button held), tens of thousands of
        # events per minute.  We don't use hover-move anywhere (hover
        # peek is driven by enterEvent / leaveEvent), so leaving it off
        # cuts ambient event load and stops the "pill follows my cursor
        # on hover" stale-drag bug at the source.
        self.setMouseTracking(False)
        self._body.setMouseTracking(False)

        # Window dimensions are computed for the current anchor (horizontal
        # for top, vertical for left/right) plus a generous padding so
        # bloop scale animations have headroom to expand without clipping.
        self._load_anchor_state_from_prefs()
        self._apply_window_size_for_anchor()
        # Place the window at its anchor-resolved target immediately so
        # the user sees it on the right spot (no flicker from a default
        # (0,0) → first-animation-tick teleport).
        self.move(self._resolve_anchor_pos())
        self._apply_click_through(self._prefs.get('click_through', False))
        self._poll_all()
        self._relayout_for_mode(animate=False)     # init — snap, no morph pop

    # ── anchor + visibility geometry ──────────────────────────────────
    #
    # The pill is always docked to one of three screen edges (top, left,
    # right).  Its position along the edge is `_edge_pos` (x for top, y
    # for sides).  `_visible_frac` (0..1) animates between "tucked
    # against the edge" (0) and "fully extended" (1):
    #
    #   anchor = 'top':
    #     full   → (edge_pos,   _EDGE_GAP)
    #     hidden → (edge_pos,   -h + _PEEK_SHOWING_PX)
    #
    #   anchor = 'left':
    #     full   → (_EDGE_GAP,  edge_pos)
    #     hidden → (-w + _PEEK_SHOWING_PX, edge_pos)
    #
    #   anchor = 'right':
    #     full   → (screen_w - w - _EDGE_GAP, edge_pos)
    #     hidden → (screen_w - _PEEK_SHOWING_PX, edge_pos)
    #
    # During a drag we bypass this entirely and let the user push the
    # pill around (with heavy perpendicular resistance — see
    # mouseMoveEvent).  On release we snap back to anchor.

    def _load_anchor_state_from_prefs(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr is None: return
        geo = scr.geometry()
        anchor = str(self._prefs.get('anchor') or 'top').lower()
        if anchor not in ('top', 'left', 'right'):
            anchor = 'top'
        self._anchor = anchor
        ep = int(self._prefs.get('edge_pos', -1))
        if ep < 0:
            # Centered along the anchor's major axis.
            ww, wh = self._window_size_for_anchor(anchor)
            if anchor == 'top':
                ep = (geo.width()  - ww) // 2
            else:
                ep = (geo.height() - wh) // 2
        self._edge_pos = ep
        self._hidden = bool(self._prefs.get('hidden', False))
        self._pinned = bool(self._prefs.get('pinned', False))
        self._visible_frac = self._target_visible_frac()

    def _is_vertical_anchor(self, anchor: str | None = None) -> bool:
        a = anchor or self._anchor
        return a in ('left', 'right')

    def _current_long(self) -> int:
        """Pill body's major-axis length — CONTENT-DRIVEN so the pill
        hugs its contents (no dead space).  The active lane reports
        content_width(); menu mode reports the 3-button row width.
        Clamped to [_MIN_PILL, _MAX_PILL]."""
        if not hasattr(self, '_lanes') or not self._lanes:
            return _MIN_PILL
        idx = max(0, min(self._compact_idx, len(self._lanes) - 1))
        need = self._lanes[idx].content_width()
        return max(_MIN_PILL, min(int(need), _MAX_PILL))


    def _window_size_for_anchor(self, anchor: str | None = None,
                                 long_override: int | None = None) -> tuple[int, int]:
        """Total window dimensions including padding, for the given anchor.
        Horizontal on top, vertical on left/right.  The major-axis length
        defaults to whatever the current lane needs (`_current_long`) but
        callers can pass `long_override` to compute the size for a hypothetical
        lane (used by the width-morph animator before swapping lanes)."""
        long_axis = long_override if long_override is not None else self._current_long()
        if self._is_vertical_anchor(anchor):
            return (_PILL_SHORT + 2 * _PADDING, long_axis + 2 * _PADDING)
        return (long_axis + 2 * _PADDING, _PILL_SHORT + 2 * _PADDING)

    def _pill_body_rect(self) -> QRect:
        """The painted pill body — derived from CURRENT window size minus
        padding.  Tied to the window so that when a QPropertyAnimation
        animates the geometry property (morph between horizontal and
        vertical), the body lerps with it proportionally.

        Previously this returned fixed dimensions based on the anchor,
        which meant the body jumped to its new shape at the start of the
        morph and either overflowed or under-filled the morphing window —
        showing as a clipped rectangle until the morph finished.
        """
        return QRect(_PADDING, _PADDING,
                     max(1, self.width()  - 2 * _PADDING),
                     max(1, self.height() - 2 * _PADDING))

    def _refresh_mask_and_body(self) -> None:
        """Rebuild the rounded mask + reposition the lane container for
        the current widget size.  Called from _apply_window_size_for_anchor
        AND from resizeEvent so the mask stays in sync with the morph
        animation's per-frame size changes.
        """
        from PyQt6.QtGui import QBitmap
        body = self._pill_body_rect()
        # Mask is bigger than the body to leave room for both:
        #   • bloop scale animation (up to ~16 px each side)
        #   • melting peek flares (up to _PEEK_FLARE_PX each side)
        bloop_room = int(max(_PILL_LONG, _PILL_SHORT) * _BLOOP_PEAK / 2 + 2)
        inflate = max(bloop_room, _PEEK_FLARE_PX + 2)
        mask_rect = body.adjusted(-inflate, -inflate, inflate, inflate)
        bm = QBitmap(self.width(), self.height())
        bm.fill(Qt.GlobalColor.color0)
        bm_p = QPainter(bm)
        bm_p.setBrush(Qt.GlobalColor.color1)
        bm_p.setPen(Qt.PenStyle.NoPen)
        bm_p.drawRoundedRect(mask_rect, _RADIUS_PX + inflate,
                             _RADIUS_PX + inflate)
        bm_p.end()
        self.setMask(bm)
        if hasattr(self, '_body'):
            self._body.setGeometry(body)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # Mask + body must follow the widget through the morph
        # animation's per-frame geometry changes — otherwise the body
        # gets clipped to whatever shape the mask was at animation start.
        self._refresh_mask_and_body()

    def _adjust_edge_pos_to_center(self, old_w: int, old_h: int,
                                   new_w: int, new_h: int) -> None:
        """When the pill changes size (lane switch → new width), shift
        _edge_pos so the new window stays centered on the OLD window's
        center.  Without this the pill only grows toward its right edge
        because edge_pos is the LEFT-edge anchor.
        Top anchor:  delta = (new_w - old_w) / 2 along x.
        Side anchor: delta = (new_h - old_h) / 2 along y.
        """
        if self._is_vertical_anchor():
            delta = (new_h - old_h) // 2
        else:
            delta = (new_w - old_w) // 2
        if delta != 0:
            self._edge_pos = max(0, self._edge_pos - delta)

    def _apply_window_size_for_anchor(self, animate: bool = False,
                                       preserve_center: bool = True) -> None:
        """Resize + remask for the current anchor.

        When `animate=True` (called from the release handler after an
        anchor switch), the resize+move is run through a QPropertyAnimation
        on the geometry property so it smoothly morphs from horizontal
        to vertical (or back) over ~280 ms instead of snapping.

        Internal layout (mask, body geometry, lane orientation) flips
        IMMEDIATELY so the new orientation paints throughout the morph
        — which gives the squish-and-grow effect rather than a snap at
        the end.

        `preserve_center=True` (default) adjusts _edge_pos before the
        animation so the new size is centered on the OLD window's center
        — used for lane-driven width changes so the pill grows/shrinks
        symmetrically.  Anchor switches pass False because they've
        already set _edge_pos to the cursor's intended position.
        """
        ww, wh = self._window_size_for_anchor()
        cur_w_pre, cur_h_pre = self.width(), self.height()
        if preserve_center and (cur_w_pre, cur_h_pre) != (ww, wh):
            self._adjust_edge_pos_to_center(cur_w_pre, cur_h_pre, ww, wh)
        # 1. Lane orientation flips immediately — text rotates so we don't
        #    see a horizontal lane in a vertical body (or vice versa)
        #    during the morph.
        if hasattr(self, '_lanes'):
            vertical = self._is_vertical_anchor()
            for l in self._lanes:
                l.set_vertical(vertical)
        # 2. Refresh mask + body geometry for current widget size.  Called
        #    again on every resize event during the morph animation.
        self._refresh_mask_and_body()
        # 2. Resize.  Either snap (default) or animate.
        cur_w, cur_h = self.width(), self.height()
        if (cur_w, cur_h) == (ww, wh):
            return
        if not animate:
            self.resize(ww, wh)
            return
        # Animated morph — animate the whole geometry rect so the position
        # also lerps to the new anchor-resolved spot.  We stop the
        # standard position lerp during this animation (set via the
        # _morph_active flag the tick respects).
        #
        # 420ms OutBack matches the reference's `cubic-bezier(.34,1.32,.5,1)`
        # — a tiny overshoot at the end so the width settles with a soft
        # "snap" rather than a stiff stop.  Used for BOTH anchor-orientation
        # changes AND lane-driven width changes (compact ↔ wide).
        target_pos  = self._resolve_anchor_pos()
        target_rect = QRect(target_pos.x(), target_pos.y(), ww, wh)
        if self._morph_anim is not None:
            self._morph_anim.stop()
        anim = QPropertyAnimation(self, b'geometry')
        anim.setDuration(420)
        anim.setStartValue(self.geometry())
        anim.setEndValue(target_rect)
        oc = QEasingCurve(QEasingCurve.Type.OutBack)
        oc.setOvershoot(1.2)               # softer overshoot than default 1.7
        anim.setEasingCurve(oc)
        anim.finished.connect(self._on_morph_finished)
        anim.start()
        self._morph_anim   = anim
        self._morph_active = True

    def _save_anchor_state(self) -> None:
        island_data.patch(
            anchor   = self._anchor,
            edge_pos = int(self._edge_pos),
            hidden   = bool(self._hidden),
            pinned   = bool(self._pinned),
        )
        self._prefs_mtime = island_data.mtime()

    # ── prefs reload (hot-loaded from settings panel) ────────────────

    def _maybe_reload_prefs(self) -> None:
        mt = island_data.mtime()
        if mt == self._prefs_mtime:
            return
        self._prefs_mtime = mt
        new = island_data.load()
        if new.get('click_through') != self._prefs.get('click_through'):
            self._apply_click_through(new.get('click_through', False))
        self._prefs = new
        # Push timer settings (mode / duration / start-token) to the timer
        # lane — this is how the app window starts a pomodoro or quick
        # timer and how it changes the length.
        started = False
        for l in self._lanes:
            if isinstance(l, _TimerLane):
                if l.sync_from_prefs(new):
                    started = True
        if started:
            # Window hit Start — jump to the timer display + peek the pill
            # out so the user sees the countdown begin.
            self._compact_idx = self._TIMER_IDX
            self._relayout_for_mode(animate=True)
            self.peek()
        else:
            self._relayout_for_mode()
        # Lanes / fullscreen toggles take effect next paint.  Enabled
        # toggles the window visibility itself.
        if not self._prefs.get('enabled', True):
            self.hide()
        elif self._hidden_for_fullscreen:
            pass
        else:
            self.show()
            self._ensure_animating()

    # ── click-through ────────────────────────────────────────────────

    def _apply_click_through(self, on: bool) -> None:
        # Toggle the transparent-for-input flag on this window.  Qt
        # requires the window to be hidden + reshown for the flag change
        # to take effect on Windows.
        flags = self.windowFlags()
        if on:
            flags = flags | Qt.WindowType.WindowTransparentForInput
            self._wake_timer.start()
        else:
            flags = flags & ~Qt.WindowType.WindowTransparentForInput
            self._wake_timer.stop()
            self._click_through_armed = False
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self._click_through_armed = on

    def _click_through_poll(self) -> None:
        # Toggle off click-through when the cursor lingers over the
        # pill rect for ~250ms; toggle back on after the cursor leaves
        # for ~_CLICK_THRU_WAKE_MS.
        if not self._click_through_armed:
            # User-disabled wake; stop polling
            return
        cur = QCursor.pos()
        in_pill = self.geometry().contains(cur)
        now_ms = QTimer().remainingTime()  # not strictly time, but good enough; use a Q clock instead
        from PyQt6.QtCore import QDateTime
        now_ms = QDateTime.currentMSecsSinceEpoch()
        if in_pill:
            if self._wake_last_in_pill_ms == 0:
                self._wake_last_in_pill_ms = now_ms
            elif now_ms - self._wake_last_in_pill_ms > 250:
                # Briefly disable transparent flag
                flags = self.windowFlags()
                if flags & Qt.WindowType.WindowTransparentForInput:
                    self.setWindowFlags(flags & ~Qt.WindowType.WindowTransparentForInput)
                    self.show()
        else:
            self._wake_last_in_pill_ms = 0
            # Restore transparent if it's been off too long
            flags = self.windowFlags()
            if not (flags & Qt.WindowType.WindowTransparentForInput):
                self.setWindowFlags(flags | Qt.WindowType.WindowTransparentForInput)
                self.show()

    # ── refresh / lane cycling ──────────────────────────────────────

    def _poll_all(self) -> None:
        # Cheap: refreshes lane text + priority selection.  Does NOT call
        # SMTC anymore — that runs on its own slower timer (_poll_smtc).
        for l in self._lanes:
            l.refresh()
        # Decide what to display: timer normally, due-assignment briefly.
        self._select_display()

    # Lane indices in the timer-only model.
    _TIMER_IDX = 0
    _DUE_IDX   = 1

    def _select_display(self) -> None:
        """Timer-focused display logic.  Normally shows the TIMER.  When
        an assignment becomes due soon, briefly pops the due lane for a
        few seconds (once per assignment), then reverts to the timer.
        Pinned pill = user is looking at it, leave the current display.
        """
        from PyQt6.QtCore import QDateTime
        now = QDateTime.currentMSecsSinceEpoch()
        due_lane = self._lanes[self._DUE_IDX]

        # Trigger a popup when a due assignment appears and we haven't
        # already popped THIS one.  due_lane.refresh() sets _visible_lane
        # + a stable _popup_key when something's due-soon.
        key = getattr(due_lane, '_popup_key', '')
        if (key and key != self._due_popup_key
                and due_lane._visible_lane and not self._pinned):
            self._due_popup_key = key
            self._due_popup_until_ms = now + _DUE_POPUP_MS

        want_due = (now < self._due_popup_until_ms and due_lane._visible_lane
                    and not self._pinned)
        target = self._DUE_IDX if want_due else self._TIMER_IDX
        # Clear the dedupe key once the assignment is no longer due-soon,
        # so the SAME assignment can re-pop next time it qualifies.
        if not due_lane._visible_lane:
            self._due_popup_key = ''
        if self._compact_idx != target:
            self._compact_idx = target
            self._relayout_for_mode(animate=True)
            # The view just changed — briefly pop the pill out so the
            # user sees the new display (e.g. a due-assignment popup).
            self.peek()

    def _is_lane_renderable(self, idx: int) -> bool:
        return self._lane_enabled(idx) and self._lanes[idx]._visible_lane

    def _current_lane_visible(self) -> bool:
        return self._is_lane_renderable(self._compact_idx)

    def _lane_enabled(self, idx: int) -> bool:
        keys = ['timer', 'next_task']
        if idx < 0 or idx >= len(keys):
            return True
        return self._prefs.get('lanes', {}).get(keys[idx], True)

    def _relayout_for_mode(self, animate: bool = True) -> None:
        # Always-single-line layout.  Only the current cycle index's
        # lane is shown.  Resize / reposition the window for the
        # current anchor + current lane's width key — animated by default
        # so the pill smoothly grows/shrinks between lanes (the Premium
        # dynamic-width morph from the reference).  Init passes
        # animate=False to avoid a "first paint" pop.
        for i, l in enumerate(self._lanes):
            l.setVisible(i == self._compact_idx and self._is_lane_renderable(i))
            # Push current pin state to each lane so they paint correctly
            # even right after a swap.
            l.set_pinned(self._pinned)
        # preserve_center=False → the LEFT edge stays put and the pill
        # grows/shrinks on the RIGHT only (user: "when it changes length
        # it should only extend on the right side").
        self._apply_window_size_for_anchor(animate=animate, preserve_center=False)
        self.update()

    # ── hover (pauses rotation; peeks out a hidden pill) ────────────

    def enterEvent(self, _evt) -> None:
        # Qt's event-based hover is used as a fallback wake-up trigger;
        # the real hover state is recomputed every anim tick from
        # QCursor.pos() against a static slop zone (see
        # _refresh_hover_from_cursor).  Without the polled override the
        # rounded-corner widget mask creates dead zones at the corners
        # where the cursor falls out and triggers enter/leave thrash —
        # which is the "preview oscillates back to nib" bug.
        self._ensure_animating()

    def leaveEvent(self, _evt) -> None:
        # Same as enterEvent — defer the actual mouse_over update to
        # the polled tick check so we don't get false-negatives from
        # the mask's rounded corners.
        self._ensure_animating()

    def _poll_hover_wake(self) -> None:
        """Slow hover-poll (20 Hz).  Runs always.  Refreshes mouse_over
        from the cursor position; if anything changed and the anim
        timer is idle, kicks it so the peek-out / retract animation
        runs.  Skipped during drag (drag math owns the state)."""
        if self._dragging:
            return
        old = self._mouse_over
        self._refresh_hover_from_cursor()
        if self._mouse_over != old:
            self._ensure_animating()

    def _refresh_hover_from_cursor(self) -> None:
        """Polled hover detection.  Uses TWO different zones depending
        on current state, to give the user fine control:

          • NIB state (mouse_over=False): zone is TIGHT — literally the
            3-px visible nib strip.  User has to put their cursor
            directly over the nib to wake the pill, so the rest of the
            screen edge is clickable for other apps.

          • EXPANDED state (mouse_over=True): zone is GENEROUS — covers
            the full body extent + scoops + small slop, so the user can
            move their cursor anywhere on the visible pill without
            accidentally losing it.

        The state-dependent zone is what prevents the back-and-forth
        oscillation: once expanded, the zone is big enough that the
        cursor doesn't fall out as the body moves under it.
        """
        from PyQt6.QtGui import QCursor
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return
        geo = scr.geometry()
        cur = QCursor.pos()
        # CHEAP EARLY-OUT: if the cursor hasn't moved since the last call
        # AND the pill geometry hasn't changed, there is nothing new to
        # compute — hover state, button-hover, and zones all depend only
        # on (cursor, edge_pos, width, anchor, mode).  This runs from BOTH
        # the 20 Hz hover poll AND the 60 Hz anim tick, so skipping the
        # zone math + mapFromGlobal + per-button hit-tests on an idle
        # mouse is the single biggest steady-state CPU win.
        sig = (cur.x(), cur.y(), self._edge_pos, self._current_long(),
               self._anchor, self._compact_idx, self._mouse_over)
        if getattr(self, '_hover_sig', None) == sig:
            return
        self._hover_sig = sig
        ww, _wh = self._window_size_for_anchor()
        body_long = self._current_long()
        # Body's x position in screen (for top anchor) — body sits PADDING
        # px in from the window's left edge.
        body_lead_screen = self._edge_pos + _PADDING
        if self._mouse_over:
            # EXPANDED: generous zone covering the visible pill + slop
            SLOP = 10
            if self._anchor == 'top':
                zx_start = body_lead_screen - SLOP
                zx_end   = body_lead_screen + body_long + SLOP
                zy_start = 0
                zy_end   = _PEEK_BODY_GAP_PX + _PILL_SHORT + SLOP
            elif self._anchor == 'left':
                zx_start = 0
                zx_end   = _PEEK_BODY_GAP_PX + _PILL_SHORT + SLOP
                zy_start = body_lead_screen - SLOP
                zy_end   = body_lead_screen + body_long + SLOP
            else:  # right
                zx_start = geo.width() - _PEEK_BODY_GAP_PX - _PILL_SHORT - SLOP
                zx_end   = geo.width()
                zy_start = body_lead_screen - SLOP
                zy_end   = body_lead_screen + body_long + SLOP
        else:
            # NIB: tight zone, just the visible nib strip — no slop.
            # User has to literally hover the nib to wake the pill.
            if self._anchor == 'top':
                zx_start = body_lead_screen
                zx_end   = body_lead_screen + body_long
                zy_start = 0
                zy_end   = _PEEK_SHOWING_PX
            elif self._anchor == 'left':
                zx_start = 0
                zx_end   = _PEEK_SHOWING_PX
                zy_start = body_lead_screen
                zy_end   = body_lead_screen + body_long
            else:  # right
                zx_start = geo.width() - _PEEK_SHOWING_PX
                zx_end   = geo.width()
                zy_start = body_lead_screen
                zy_end   = body_lead_screen + body_long
        in_zone = (zx_start <= cur.x() <= zx_end and zy_start <= cur.y() <= zy_end)
        if in_zone != self._mouse_over:
            self._mouse_over = in_zone
            if hasattr(self, '_lanes') and self._lanes:
                if in_zone:
                    self._lanes[self._compact_idx].set_hover(True)
                else:
                    for l in self._lanes:
                        l.set_hover(False)
        # Per-button hover feedback for the timer lane's play/pause +
        # reset buttons.  Lane-local coords via mapFromGlobal so the
        # hover lands exactly where the buttons are painted.
        if in_zone and hasattr(self, '_lanes') and self._lanes:
            lane = self._lanes[self._compact_idx]
            if hasattr(lane, 'update_hovered_button'):
                lane.update_hovered_button(lane.mapFromGlobal(cur))
        elif hasattr(self, '_lanes') and self._lanes:
            for l in self._lanes:
                if hasattr(l, 'update_hovered_button'):
                    l.update_hovered_button(QPoint(-1, -1))

    # ── target visibility + animation tick ──────────────────────────

    def _target_visible_frac(self) -> float:
        """Target for visible_frac.  After the position/melt decoupling
        (commit `Island W`), visible_frac drives ONLY the melt amount
        in paintEvent — the pill's actual on-screen position is now
        chosen directly inside _resolve_anchor_pos based on the state
        triple (hidden, hover, dragging) without going through this lerp.
        So:
            visible_frac → 1.0  : clean rounded rect, no curves
            visible_frac → 0.0  : full melt (max flare + lip) — drawn
                                  when the pill is hidden, so the curves
                                  attach the body to the screen edge
        """
        if self._dragging:
            return 1.0
        if not self._hidden:
            return 1.0
        return 0.0     # full melt when hidden — curves drawn at full strength

    def _resolve_anchor_pos(self) -> QPoint:
        """Window (x, y) for the current anchor + edge_pos + visible_frac.

        Two coordinate gotchas:
          • The window is bigger than the painted pill body by _PADDING
            on each side (room for the bloop scale animation).  Body
            positions must be back-converted to window positions.
          • When `hidden`, the peek pixels must be BODY pixels, not
            padding pixels — otherwise the user sees only transparent
            window padding and thinks the pill vanished.

        Concretely for top anchor:
            full:    body top = _EDGE_GAP            → window y = _EDGE_GAP - _PADDING
            hidden:  body bottom = _PEEK_SHOWING_PX  → window y = peek - body_h - _PADDING
        """
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return self.pos()
        geo = scr.geometry()
        # IMPORTANT: use anchor-AWARE dimensions, not self.width()/height().
        # During an anchor morph, self.width()/height() are still the OLD
        # orientation (the QPropertyAnimation animates the geometry from
        # old to new) — but we need the target position computed with the
        # NEW orientation.
        w, h = self._window_size_for_anchor()
        # EXPANDED if hovering OR pinned OR currently in a transient peek
        # (display just changed).  NIB otherwise.  Drag handled outside.
        from PyQt6.QtCore import QDateTime
        peeking = QDateTime.currentMSecsSinceEpoch() < self._peek_until_ms
        expanded = self._mouse_over or self._pinned or peeking
        if self._anchor == 'top':
            edge_pos = max(0, min(self._edge_pos, geo.width() - w))
            if expanded:
                y = _PEEK_BODY_GAP_PX - _PADDING
            else:
                y = _PEEK_SHOWING_PX - _PILL_SHORT - _PADDING
            return QPoint(edge_pos, y)
        elif self._anchor == 'left':
            edge_pos = max(0, min(self._edge_pos, geo.height() - h))
            if expanded:
                x = _PEEK_BODY_GAP_PX - _PADDING
            else:
                x = _PEEK_SHOWING_PX - _PILL_SHORT - _PADDING
            return QPoint(x, edge_pos)
        else:  # right
            edge_pos = max(0, min(self._edge_pos, geo.height() - h))
            if expanded:
                x = geo.width() - w - (_PEEK_BODY_GAP_PX - _PADDING)
            else:
                x = geo.width() - _PEEK_SHOWING_PX - _PADDING
            return QPoint(x, edge_pos)

    def _tick_animation(self) -> None:
        """60-fps tick.  Lerps both visible_frac AND the window position
        toward their targets.  Stops when both are settled.

        No-op while the user is actively dragging OR while an anchor-
        morph QPropertyAnimation is running (the morph owns the
        geometry; we mustn't fight it)."""
        # Always recompute hover from the live cursor — overrides Qt's
        # event-based mouse_over.  In the simplified model the pill's
        # docked position IS hover-driven: hovering picks the expanded
        # position, leaving picks the nib position.  No separate
        # "popped" / auto-hide logic needed.
        self._refresh_hover_from_cursor()
        if self._dragging:
            # Belt-and-braces guard: if mouseReleaseEvent never fired
            # (focus shift / capture stolen by another window / a
            # tooltip popup eating the event / cursor going off-screen
            # past the screen edge during a hide gesture), _dragging
            # would be stuck True forever AND the hide/anchor-switch
            # decisions would never run.  Cross-check against the GLOBAL
            # button state — if no button is actually held right now,
            # the release was missed.
            #
            # DEBOUNCE: a single "no buttons" tick can be a transient
            # Windows quirk when the cursor crosses screen edges or apps
            # steal focus briefly.  Triggering finish_drag on a transient
            # would jump the pill mid-drag and cause back-and-forth
            # glitching.  Require N consecutive ticks before acting.
            from PyQt6.QtGui import QGuiApplication as _QGA, QCursor
            if not (_QGA.mouseButtons() & Qt.MouseButton.LeftButton):
                self._missed_release_count = getattr(self, '_missed_release_count', 0) + 1
                if self._missed_release_count < 4:    # ~64 ms of consistent "no button"
                    return
                self._missed_release_count = 0
                self._dragging = False
                cur_global = QCursor.pos()
                moved = (abs(cur_global.x() - self._drag_press_global.x())
                         + abs(cur_global.y() - self._drag_press_global.y()))
                if getattr(self, '_drag_did_move', False) or moved >= _DRAG_CLICK_THRESHOLD_PX:
                    self._finish_drag(cur_global)
                else:
                    self._save_anchor_state()
                # fall through to lerp logic below
            else:
                self._missed_release_count = 0
                return
        # 1. visible_frac → target
        target_vf = self._target_visible_frac()
        vf_settled = abs(target_vf - self._visible_frac) < 0.005
        if vf_settled:
            self._visible_frac = target_vf
        else:
            self._visible_frac += (target_vf - self._visible_frac) * _VISIBLE_FRAC_LERP
        # 1b. hover_offset → target.  Suppressed while hidden so the
        # hover-peek animation owns the position.
        target_ho = (_HOVER_OFFSET_PX
                     if (self._mouse_over and not self._hidden) else 0.0)
        ho_settled = abs(target_ho - self._hover_offset) < 0.3
        if ho_settled:
            self._hover_offset = target_ho
        else:
            self._hover_offset += (target_ho - self._hover_offset) * _HOVER_LERP
        # 2. position → anchor-resolved target (skipped during morph)
        if self._morph_active:
            pos_settled = True   # morph anim owns the position
        else:
            target_pos = self._resolve_anchor_pos()
            cur = self.pos()
            dx = target_pos.x() - cur.x()
            dy = target_pos.y() - cur.y()
            pos_settled = abs(dx) <= 1 and abs(dy) <= 1
            if pos_settled:
                self.move(target_pos)
            else:
                self.move(cur.x() + int(round(dx * _POS_LERP)),
                          cur.y() + int(round(dy * _POS_LERP)))
        # 3. trigger a repaint so the bloop scale interpolation updates
        if self._bloop_end_ms > 0:
            self.update()
        # 4. idle the timer when nothing's moving (saves CPU)
        from PyQt6.QtCore import QDateTime
        now_ms = QDateTime.currentMSecsSinceEpoch()
        bloop_done = now_ms >= self._bloop_end_ms
        if vf_settled and ho_settled and pos_settled and bloop_done:
            if self._bloop_end_ms > 0:
                self._bloop_end_ms = 0
                self.update()    # final repaint at scale 1.0
            self._anim_timer.stop()

    def _ensure_animating(self) -> None:
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def flash_task(self, title: str) -> None:
        """Briefly take over the pill to show a just-planted assignment, then
        let it revert to the timer.  Pops the pill out so it's seen."""
        try:
            from PyQt6.QtCore import QDateTime
            due_lane = self._lanes[self._DUE_IDX]
            due_lane.set_override(title, 3200)
            due_lane.refresh()
            self._due_popup_until_ms = QDateTime.currentMSecsSinceEpoch() + 3200
            self._due_popup_key = f"plant|{title}"
            if not self._pinned and self._compact_idx != self._DUE_IDX:
                self._compact_idx = self._DUE_IDX
                self._relayout_for_mode(animate=True)
            self.peek(2600)
            self.update()
        except Exception:
            pass

    def notify_timer_switch(self) -> None:
        """Called by the timer lane when a Pomodoro auto-switches work↔break.
        Jump to the timer display and peek the pill out so the user notices
        even if it was tucked away."""
        try:
            self._compact_idx = self._TIMER_IDX
            self._relayout_for_mode(animate=True)
        except Exception:
            pass
        self.peek(2800)

    def peek(self, ms: int = _PEEK_GLANCE_MS) -> None:
        """Briefly pop the pill out of hiding to show a fresh update,
        then let it retract.  No-op (well, harmless) when the pill isn't
        hidden — it's already visible.  Called whenever the displayed
        content changes (timer started, view switched, due popup)."""
        # Safeguard: if the WINDOW itself got hidden (e.g. a transient
        # fullscreen detection earlier), a peek must bring it back — otherwise
        # the timer chimes but nothing shows.  Don't override a real fullscreen
        # app or a user-disabled pill.
        if (not self.isVisible() and not self._hidden_for_fullscreen
                and self._prefs.get('enabled', True)):
            self.show()
        from PyQt6.QtCore import QDateTime
        end = QDateTime.currentMSecsSinceEpoch() + ms
        if end <= self._peek_until_ms:
            return                       # already peeking at least this long
        self._peek_until_ms = end
        self._ensure_animating()
        # Kick the anim timer again right after the peek window ends so
        # the retract slide runs even if everything had settled meanwhile.
        QTimer.singleShot(ms + 30, self._ensure_animating)

    def _on_morph_finished(self) -> None:
        """Anchor-switch QPropertyAnimation finished — hand position
        control back to the per-tick lerp.  Also resets the drag
        baseline if the morph was kicked by a mid-drag smart switch,
        so the user's continued cursor movement picks up cleanly from
        the pill's new resting spot."""
        self._morph_active = False
        self._morph_anim = None
        if getattr(self, '_drag_morph_pending', False):
            self._drag_morph_pending = False
            if self._dragging:
                from PyQt6.QtGui import QCursor
                cur = QCursor.pos()
                self._drag_press_global     = cur
                self._drag_press_window_pos = self.frameGeometry().topLeft()
                self._drag_press_edge_pos   = self._edge_pos
                self._drag_max_into_anchor  = 0
        self._ensure_animating()

    def _trigger_bloop(self) -> None:
        """Play a small scale-pop animation (used when restoring a
        hidden pill, and when switching anchor edges)."""
        from PyQt6.QtCore import QDateTime
        self._bloop_end_ms = QDateTime.currentMSecsSinceEpoch() + _BLOOP_DURATION_MS
        self._ensure_animating()

    def _bloop_scale(self) -> float:
        """0..1 progress mapped to a smooth bounce curve.

        Reads: quick-but-eased rise to peak in the first ~22 %, then a
        long ease-out decay over the remaining ~78 % back to 1.0.
        Both halves use ease-out (cubic) so the curve is smooth at the
        endpoints and at the peak — no sudden direction changes.
        """
        if self._bloop_end_ms <= 0:
            return 1.0
        from PyQt6.QtCore import QDateTime
        now_ms = QDateTime.currentMSecsSinceEpoch()
        remaining = self._bloop_end_ms - now_ms
        if remaining <= 0:
            return 1.0
        phase = 1.0 - (remaining / _BLOOP_DURATION_MS)   # 0..1
        peak  = _BLOOP_PEAK_PHASE
        if phase < peak:
            # Ramp UP — ease-out cubic so the bump is visible early
            # (rises fast at the start) then eases into the peak.
            t = phase / peak
            ease = 1.0 - (1.0 - t) ** 3
            return 1.0 + _BLOOP_PEAK * ease
        else:
            # Settle DOWN — ease-out cubic over the remaining duration
            # so the pill smoothly comes back to scale 1.0 without a
            # noticeable inflection.
            t = (phase - peak) / (1.0 - peak)
            ease = 1.0 - (1.0 - t) ** 3
            return 1.0 + _BLOOP_PEAK * (1.0 - ease)

    # ── drag with edge-lock + perpendicular spring resistance ───────

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e); return
        # Cancel any in-flight morph — otherwise the QPropertyAnimation
        # keeps stepping geometry on top of the user's drag, causing the
        # pill to fight the cursor and "snap back" mid-drag.
        if self._morph_anim is not None:
            try: self._morph_anim.stop()
            except Exception: pass
            self._morph_anim = None
            self._morph_active = False
        self._dragging              = True
        self._drag_press_global     = e.globalPosition().toPoint()
        self._drag_press_anchor     = self._anchor
        self._drag_press_edge_pos   = self._edge_pos
        self._drag_press_hidden     = self._hidden
        self._drag_max_into_anchor  = 0
        self._missed_release_count  = 0     # reset safety-guard debounce counter
        # STICKY "did this drag actually move?" flag.  Set True the moment
        # the cursor strays past the click threshold OR an anchor switch
        # fires, and it STAYS True for the rest of the drag.  Release uses
        # this — NOT a fresh distance-from-baseline calc — to decide
        # click-vs-drag, because a mid-drag anchor morph RESETS the drag
        # baseline (_drag_press_global), which would otherwise make a long
        # cross-edge drag look like a zero-distance click and fire whatever
        # button is under the cursor (the "it skips the song" bug).
        self._drag_did_move         = False
        # If we WERE hidden, un-hide RIGHT NOW (not on release).  This
        # has two effects:
        #   1. The pill pops to active position immediately on press,
        #      with a bloop — the user sees they've grabbed something
        #      real instead of "is it dragging?".
        #   2. The drag baseline (press_window_pos) is the ACTIVE
        #      position, not the hidden one, so the drag math is sane
        #      from frame 1.
        # An accidental re-hide can only happen via the end-of-drag
        # gesture (cursor pulled INTO the anchor on release), which
        # requires an intentional shove.
        if self._hidden:
            self._hidden = False
            self._visible_frac = 1.0
            # Snap to active position immediately so press_window_pos
            # below reflects where the pill actually is.
            self.move(self._resolve_anchor_pos())
            self._trigger_bloop()
            self._save_anchor_state()
        else:
            # Already active — force visible_frac to 1 in case we were
            # mid-peek-fade from a hover.
            self._visible_frac = 1.0
        self._drag_press_window_pos = self.frameGeometry().topLeft()
        self._ensure_animating()
        e.accept()

    @staticmethod
    def _resist(distance: int) -> int:
        """Asymptotic resistance — the pill is allowed AT MOST _RESIST_CAP_PX
        away from its anchor regardless of how far the cursor moves.  This
        was a sqrt curve before, which had no cap and meant a 1000-px drag
        sent the pill 170 px off-screen.  Now:

            f(d) = cap * d / (d + cap)        →  approaches `cap` as d→∞

        Concretely with cap=50:
            d= 25 →  17  (1:1.5)
            d= 50 →  25  (1:2)
            d=100 →  33  (1:3)
            d=300 →  43  (1:7)
            d=∞   →  50

        Combined with the per-anchor clamp in mouseMoveEvent that blocks
        movement INTO the anchor direction entirely, the pill can no
        longer be dragged off-screen.
        """
        if distance == 0:
            return 0
        sign = 1 if distance >= 0 else -1
        d = abs(distance)
        return int(round(sign * _RESIST_CAP_PX * d / (d + _RESIST_CAP_PX)))

    def _maybe_smart_anchor_switch(self, cur: QPoint, geo) -> bool:
        """Conservative mid-drag anchor switch.  Fires ONLY when the user
        has clearly committed to a different wall:
            • cursor has moved FAR from the current anchor's edge (≥120 px)
              — so they're not just hovering near a corner ambiguously
            • cursor is CLOSE to a different screen edge (≤80 px)
              — so they're aiming somewhere specific
        Both conditions = clear intent → SMOOTH morph to the new wall.
        Drag is paused for the duration of the morph (~280 ms) so the
        user's cursor movement doesn't fight the QPropertyAnimation;
        when the morph finishes the drag resumes with a fresh baseline.
        """
        AWAY_THRESH = 120
        EDGE_THRESH = 80
        dist = {'top':   cur.y(),
                'left':  cur.x(),
                'right': geo.width()  - cur.x()}
        away = dist[self._anchor]
        if away < AWAY_THRESH:
            return False
        del dist[self._anchor]
        target = min(dist, key=dist.get)
        if dist[target] >= EDGE_THRESH:
            return False
        # Commit.  Set anchor + new edge_pos, then kick the SMOOTH morph.
        self._anchor = target
        nw, nh = self._window_size_for_anchor(target)
        if target == 'top':
            self._edge_pos = max(0, min(cur.x() - nw // 2, geo.width()  - nw))
        else:
            self._edge_pos = max(0, min(cur.y() - nh // 2, geo.height() - nh))
        self._apply_window_size_for_anchor(animate=True, preserve_center=False)
        # Pause drag math for the morph duration — drag baseline gets
        # reset in _on_morph_finished so the user's continued cursor
        # movement after the morph picks up cleanly.
        self._drag_morph_pending = True
        self._drag_press_anchor  = target
        return True

    def mouseMoveEvent(self, e) -> None:
        if not self._dragging:
            super().mouseMoveEvent(e); return
        # Stale-drag guard.  If a release event got eaten (focus shift,
        # right-click menu, window-stack jiggle) and _dragging was left
        # True, this move would be processed as drag — every hover-move
        # would warp the pill to the cursor.  Detect by checking that
        # mouse buttons are ACTUALLY held; if not, force-release.
        if not e.buttons():
            self._dragging = False
            self._save_anchor_state()
            self._ensure_animating()
            super().mouseMoveEvent(e); return
        scr = QGuiApplication.primaryScreen()
        if scr is None: return
        geo = scr.geometry()
        cur  = e.globalPosition().toPoint()
        # While a mid-drag anchor morph is animating, swallow move events
        # — let the QPropertyAnimation own the geometry.  Drag baseline
        # is reset in _on_morph_finished when the morph ends.
        if self._drag_morph_pending:
            e.accept(); return
        # Smart anchor switch — only fires when user has clearly committed
        # to a different wall (see _maybe_smart_anchor_switch).
        if self._maybe_smart_anchor_switch(cur, geo):
            self._drag_did_move = True   # a switch is unambiguously a drag
            e.accept(); return
        w, h = self.width(), self.height()
        # Cursor delta since the press
        dx = cur.x() - self._drag_press_global.x()
        dy = cur.y() - self._drag_press_global.y()
        # Mark the drag as "real" once the cursor has strayed past the
        # click threshold.  Sticky for the rest of the drag (see
        # mousePressEvent) so a later baseline reset can't un-mark it.
        if abs(dx) + abs(dy) >= _DRAG_CLICK_THRESHOLD_PX:
            self._drag_did_move = True
        # Where the window WANTED to go (free drag)
        wanted_x = self._drag_press_window_pos.x() + dx
        wanted_y = self._drag_press_window_pos.y() + dy
        # Apply edge-axis freedom + progressive perpendicular resistance.
        # The "anchor axis" tracks cursor 1:1 (clamped to screen); the
        # perpendicular axis goes through _resist() so big pulls feel
        # heavy and never fully escape the pill's edge magnetism.
        #
        # We also track "max cursor pull INTO the anchor" — used at
        # release time to detect a deliberate shove-into-the-edge
        # minimize gesture (vs just brushing the screen border).
        # Ideal window-edge for the current anchor (body sits at _EDGE_GAP
        # from screen edge, but window edge is _PADDING further out).
        # Per-anchor drag math.  The "edge axis" tracks the cursor 1:1
        # (clamped to screen).  The "perpendicular axis" is one-directional:
        # away-from-anchor goes through _resist (asymptotes at _RESIST_CAP_PX),
        # toward-anchor is clamped at the anchor edge — the pill physically
        # cannot leave its anchor side of the screen.  The cursor going
        # further into the anchor still counts toward the minimize gesture
        # (tracked separately via _drag_max_into_anchor).
        if self._anchor == 'top':
            ideal_y = _EDGE_GAP - _PADDING
            free_x = max(0, min(wanted_x, geo.width() - w))
            delta_y = wanted_y - ideal_y
            actual_y = ideal_y + self._resist(delta_y) if delta_y > 0 else ideal_y
            self.move(free_x, actual_y)
            self._edge_pos = free_x
            into = -delta_y
            if into > self._drag_max_into_anchor:
                self._drag_max_into_anchor = into
        elif self._anchor == 'left':
            ideal_x = _EDGE_GAP - _PADDING
            free_y = max(0, min(wanted_y, geo.height() - h))
            delta_x = wanted_x - ideal_x
            actual_x = ideal_x + self._resist(delta_x) if delta_x > 0 else ideal_x
            self.move(actual_x, free_y)
            self._edge_pos = free_y
            into = -delta_x
            if into > self._drag_max_into_anchor:
                self._drag_max_into_anchor = into
        else:  # right
            ideal_x = geo.width() - w - (_EDGE_GAP - _PADDING)
            free_y = max(0, min(wanted_y, geo.height() - h))
            delta_x = wanted_x - ideal_x
            actual_x = ideal_x + self._resist(delta_x) if delta_x < 0 else ideal_x
            self.move(actual_x, free_y)
            self._edge_pos = free_y
            into = delta_x
            if into > self._drag_max_into_anchor:
                self._drag_max_into_anchor = into
        e.accept()




    def _lane_index(self, cls) -> int:
        for i, l in enumerate(self._lanes):
            if isinstance(l, cls):
                return i
        return -1


    # ── clipboard monitor + toast ────────────────────────────────────



    def _dispatch_click(self, press_local: QPoint) -> str:
        """Route a single-click.  Returns 'consumed' (a timer button was
        hit) or 'body' (caller treats it as a pin-toggle).

        Only the timer lane has buttons now (play/pause + reset).  We
        hit-test in the visible lane's OWN coordinate system so the
        click lands exactly on the painted button."""
        if not self._lanes:
            return 'body'
        cur = self._lanes[self._compact_idx]
        if not isinstance(cur, _TimerLane):
            return 'body'                # due-popup lane has no buttons
        lp = cur.mapFrom(self, press_local)
        if cur._vertical:
            lw, lh = cur.height(), cur.width()
            lx, ly = lp.y(), cur.width() - lp.x()
        else:
            lw, lh = cur.width(), cur.height()
            lx, ly = lp.x(), lp.y()
        lpt = QPoint(lx, ly)
        for kind, rect in cur.button_rects(lw, lh):
            if rect.contains(lpt):
                cur.flash_button(kind)
                if kind == 'play_pause':
                    cur._toggle()
                elif kind == 'reset':
                    cur.reset()
                return 'consumed'
        return 'body'

    def _dispatch_double_click(self) -> None:
        """Double-click the body: timer → toggle run/pause; due-popup →
        open the Library Hub."""
        if not self._lanes:
            return
        cur = self._lanes[self._compact_idx]
        if isinstance(cur, _TimerLane):
            cur._toggle()
            cur.flash_button('play_pause')
        else:
            self.open_hub_requested.emit()

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        for l in self._lanes:
            l.set_pinned(self._pinned)
        self._save_anchor_state()
        self._ensure_animating()

    def mouseReleaseEvent(self, e) -> None:
        if not self._dragging:
            super().mouseReleaseEvent(e); return
        self._dragging = False
        cur = e.globalPosition().toPoint()
        # Click-vs-drag uses the STICKY _drag_did_move flag (set in
        # mouseMoveEvent / on anchor switch), NOT a fresh distance calc —
        # a mid-drag anchor morph resets _drag_press_global, so a long
        # cross-edge drag can end a few px from the (reset) baseline and
        # would otherwise be misread as a click, firing whatever button
        # is under the cursor (the "switching edges skips the song" bug).
        moved = (abs(cur.x() - self._drag_press_global.x())
                 + abs(cur.y() - self._drag_press_global.y()))
        is_click = (not self._drag_did_move) and moved < _DRAG_CLICK_THRESHOLD_PX
        if is_click:
            # Click, not a drag.  Dispatch to button-hit-tests immediately.
            # If the click landed on the BODY (no button), defer the
            # pin-toggle by the system double-click interval — that
            # window of time is reserved for a possible second click,
            # which will be promoted to a double-click and trigger the
            # lane's open action instead.
            if not self._drag_press_hidden:
                press_local = self._drag_press_global - self.frameGeometry().topLeft()
                result = self._dispatch_click(press_local)
                if result == 'body':
                    # Schedule deferred pin-toggle — cancelled if a
                    # double-click comes within the doubleclick window.
                    from PyQt6.QtWidgets import QApplication
                    self._pending_body_click = True
                    QTimer.singleShot(QApplication.doubleClickInterval(),
                                      self._fire_pending_body_click)
            self._ensure_animating()
            e.accept(); return

        # It was a real drag — delegate to _finish_drag.
        self._finish_drag(cur)
        e.accept()

    def _fire_pending_body_click(self) -> None:
        """Single-click pin-toggle fires after the double-click window
        elapses with no second click.  Cancelled by mouseDoubleClickEvent."""
        if not getattr(self, '_pending_body_click', False):
            return
        self._pending_body_click = False
        self._toggle_pin()

    def mouseDoubleClickEvent(self, e) -> None:
        """User double-clicked.  Cancels the pending single-click pin
        toggle and triggers the lane's open action instead.  Only fires
        for body clicks; button clicks are immediate (no defer)."""
        # Cancel pending single-click.
        self._pending_body_click = False
        # Re-route: button hits trigger their action immediately on
        # double-click too (so a fast double-tap on play/pause still
        # toggles play/pause, not lane action).
        press_local = e.position().toPoint()
        result = self._dispatch_click(press_local)
        if result == 'body':
            self._dispatch_double_click()
        e.accept()

    def _finish_drag(self, cur: QPoint) -> None:
        """End-of-drag decision logic: hide / anchor switch / snap back.
        Called from mouseReleaseEvent on the normal path AND from the
        missed-release safety guard in _tick_animation — that's the
        important bit; without sharing this logic, a drag that ended
        with cursor off-screen (Windows dropped our mouse capture, so
        no release event fired) would never trigger the hide gesture.

        ALL decisions below use CURSOR-SPACE distances — where the user
        actually moved their cursor — NOT the pill's resisted display
        position.  The resistance asymptote caps pill travel at ~50 px
        from its anchor, so reading pill position would make the
        thresholds unreachable.
        """
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            self._save_anchor_state(); self._ensure_animating(); return
        geo = scr.geometry()

        # 1. Hide gesture.  Two triggers, either is enough:
        #   • end_into ≥ _MINIMIZE_PUSH_PX — cursor pulled the threshold
        #     number of px INTO the anchor from where it pressed
        #   • OR cursor at the anchor's screen edge — Windows clamps
        #     cursor.y / cursor.x to the screen bounds, so if the user
        #     "pushed past" the edge the cursor ends up sitting exactly
        #     on it.  That's a clear signal of "I want to dock this".
        if self._drag_press_anchor == 'top':
            end_into  = self._drag_press_global.y() - cur.y()
            end_away  = cur.y() - self._drag_press_global.y()    # drag DOWN
            off_screen = cur.y() <= 1
        elif self._drag_press_anchor == 'left':
            end_into  = self._drag_press_global.x() - cur.x()
            end_away  = cur.x() - self._drag_press_global.x()
            off_screen = cur.x() <= 1
        else:  # right
            end_into  = cur.x() - self._drag_press_global.x()
            end_away  = self._drag_press_global.x() - cur.x()
            off_screen = cur.x() >= geo.width() - 2
        # Drag-AWAY-from-anchor (DOWN for top anchor, RIGHT from left
        # anchor, LEFT from right anchor) → PIN the pill open.  User
        # spec: "if i drag that hover downwards, it shouldnt hide
        # again unless i drag it back into the screen".  So drag-away
        # = grab it out, drag-into-edge = put it back.  15-px threshold
        # — small enough that any noticeable drag-down works.
        if end_away >= 15 and not self._pinned:
            self._pinned = True
            for l in self._lanes:
                l.set_pinned(True)
        # Drag INTO the anchor edge (UP for top, etc.) — hide AND unpin
        # so the pill returns to nib mode and stays there until next hover.
        if end_into >= _MINIMIZE_PUSH_PX or off_screen:
            self._hidden = True
            if self._pinned:
                self._pinned = False
                for l in self._lanes:
                    l.set_pinned(False)
        else:
            # 2. Edge switching — cursor near a different edge at release.
            cx_pos, cy_pos = cur.x(), cur.y()
            near_top    = cy_pos <= _CORNER_ZONE_PX
            near_left   = cx_pos <= _CORNER_ZONE_PX
            near_right  = cx_pos >= geo.width()  - _CORNER_ZONE_PX
            new_anchor = self._drag_press_anchor
            if self._drag_press_anchor == 'top':
                if near_left:    new_anchor = 'left'
                elif near_right: new_anchor = 'right'
            elif self._drag_press_anchor == 'left':
                if near_top and not near_left:    new_anchor = 'top'
                elif near_right:                  new_anchor = 'right'
            elif self._drag_press_anchor == 'right':
                if near_top and not near_right:   new_anchor = 'top'
                elif near_left:                   new_anchor = 'left'
            if new_anchor != self._anchor:
                self._anchor = new_anchor
                nw, nh = self._window_size_for_anchor(new_anchor)
                if new_anchor == 'top':
                    self._edge_pos = max(0, min(cur.x() - nw // 2, geo.width() - nw))
                else:
                    self._edge_pos = max(0, min(cur.y() - nh // 2, geo.height() - nh))
                self._apply_window_size_for_anchor(animate=True, preserve_center=False)
                self._trigger_bloop()
            was_hidden = self._hidden
            self._hidden = False
            if was_hidden:
                self._trigger_bloop()

        self._save_anchor_state()
        self._ensure_animating()

    def _snap_back(self) -> None:
        """Spring back to whatever the current anchor + edge_pos resolves to."""
        self._ensure_animating()

    # ── fullscreen detection ────────────────────────────────────────

    def _check_fullscreen(self) -> None:
        if not self._prefs.get('hide_fullscreen', True):
            return
        fs = _foreground_is_fullscreen()
        if fs and not self._hidden_for_fullscreen:
            self._hidden_for_fullscreen = True
            self.hide()
            self.fullscreen_changed.emit(True)
        elif not fs and self._hidden_for_fullscreen:
            self._hidden_for_fullscreen = False
            if self._prefs.get('enabled', True):
                self.show()
            self.fullscreen_changed.emit(False)

    # ── custom paint (dark rounded pill background) ─────────────────

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = self._pill_body_rect()
        cx = body.center().x()
        cy = body.center().y()
        scale = self._bloop_scale()
        if scale != 1.0:
            p.translate(cx, cy)
            p.scale(scale, scale)
            p.translate(-cx, -cy)
        # Per user spec: scrap the scoops/wings entirely.  Pill shape
        # in EVERY state — nib, expanded, drag.  _build_melting_path
        # is kept in the file for possible future use but no longer
        # invoked anywhere.
        path = QPainterPath()
        path.addRoundedRect(float(body.x()), float(body.y()),
                            float(body.width()), float(body.height()),
                            _RADIUS_PX, _RADIUS_PX)
        p.fillPath(path, _BG)
        p.setPen(QPen(_OUTLINE, 1))
        p.drawPath(path)
        # The lane child widgets paint their own content (timer / due
        # popup) on top of this background.



    @staticmethod

    def _build_melting_path(self, body: QRect, frac: float) -> QPainterPath:
        """Body shape with concave scoops connecting the body to its
        anchor screen edge.  The lip amount is auto-computed from the
        body's CURRENT distance to the anchor edge in screen coords:

          • Body at the docked/expanded position → lip = the distance,
            so curves attach exactly at the screen edge.
          • Body further out → lip caps at MAX_LIP; curves grow up to
            MAX_LIP px but no further (just a small hanging chrome).
          • Body above the screen edge (nib state, mostly off-screen)
            → lip = 0; no visible curves, just the bottom of the body
            peeking through.

        The `frac` parameter is kept for compatibility but ignored —
        the path shape is now determined by the live geometry, not the
        visible_frac state.
        """
        path = QPainterPath()
        bx, by, bw, bh = body.x(), body.y(), body.width(), body.height()
        r = _RADIUS_PX
        # Body's distance from the screen anchor edge, in widget coords.
        # In widget coords body top is at `by`; the anchor edge is at
        # widget coord `-self.y()` (since self.y() is the window's screen
        # position).  So the "gap" from body top to screen edge is
        # by + self.y() (which equals body's screen y).
        if self._anchor == 'top':
            body_edge_dist = self.y() + by             # = body_y_screen
        elif self._anchor == 'left':
            body_edge_dist = self.x() + bx
        else:  # right
            scr = QGuiApplication.primaryScreen()
            screen_w = scr.geometry().width() if scr is not None else 0
            body_edge_dist = screen_w - (self.x() + bx + bw)
        MAX_LIP = _PEEK_BODY_GAP_PX + 4   # gentle cap above the docked gap
        lip = max(0, min(int(body_edge_dist), MAX_LIP))
        melt = lip / MAX_LIP if MAX_LIP > 0 else 0.0
        top_r = max(0, int(round(r * (1.0 - melt))))
        flare = int(_PEEK_FLARE_PX * melt)
        # Render as plain rounded rect when nowhere near edge (no scoops
        # needed and integer rounding artefacts at very low melt look bad)
        if lip == 0:
            path.addRoundedRect(float(bx), float(by), float(bw), float(bh), r, r)
            return path

        # Concave-scoop bezier parameter — k≈0.55 approximates a quarter
        # circle, which reads as a clean "Apple Dynamic Island" scoop.
        K = 0.55
        if self._anchor == 'top':
            # Body bottom + sides — unchanged regardless of melt.
            path.moveTo(bx + r, by + bh)
            path.lineTo(bx + bw - r, by + bh)
            path.quadTo(bx + bw, by + bh, bx + bw, by + bh - r)
            path.lineTo(bx + bw, by + top_r)
            # Top-right rounded corner (shrinks with melt).
            if top_r > 0:
                path.quadTo(bx + bw, by, bx + bw - top_r, by)
            # CONCAVE scoop UP-RIGHT from body corner area to expanded
            # top-right.  Tangent at start = vertical (up), tangent at
            # end = horizontal (right) — so the curve scoops INWARD,
            # like a quarter-circle cut into the dark area.
            anchor_x = bx + bw - top_r if top_r > 0 else bx + bw
            path.cubicTo(
                anchor_x,                  by - lip * K,
                bx + bw + flare * (1 - K), by - lip,
                bx + bw + flare,           by - lip,
            )
            # Flat top across the expanded shape at y = by - lip.
            path.lineTo(bx - flare, by - lip)
            # CONCAVE scoop DOWN-LEFT mirror back to body top-left.
            end_x = bx + top_r if top_r > 0 else bx
            path.cubicTo(
                bx - flare * (1 - K), by - lip,
                end_x,                by - lip * K,
                end_x,                by,
            )
            # Top-left rounded corner.
            if top_r > 0:
                path.quadTo(bx, by, bx, by + top_r)
            path.lineTo(bx, by + bh - r)
            path.quadTo(bx, by + bh, bx + r, by + bh)
            path.closeSubpath()

        elif self._anchor == 'left':
            # Left anchor: scoops go LEFT (toward the screen left edge).
            # Same concave-scoop logic rotated 90° clockwise.
            path.moveTo(bx + bw - r, by)
            path.lineTo(bx + bw, by + r)
            path.lineTo(bx + bw, by + bh - r)
            path.quadTo(bx + bw, by + bh, bx + bw - r, by + bh)
            path.lineTo(bx + top_r, by + bh)
            if top_r > 0:
                path.quadTo(bx, by + bh, bx, by + bh - top_r)
            anchor_y = bx + bh - top_r if top_r > 0 else by + bh
            # Scoop DOWN-LEFT
            path.cubicTo(
                bx - lip * K,         by + bh - top_r if top_r > 0 else by + bh,
                bx - lip,             by + bh + flare * (1 - K),
                bx - lip,             by + bh + flare,
            )
            path.lineTo(bx - lip, by - flare)
            # Scoop UP-LEFT mirror back to top-left of body
            end_y = by + top_r if top_r > 0 else by
            path.cubicTo(
                bx - lip,             by - flare * (1 - K),
                bx - lip * K,         end_y,
                bx,                   end_y,
            )
            if top_r > 0:
                path.quadTo(bx, by, bx + top_r, by)
            path.closeSubpath()

        else:  # right anchor
            rx = bx + bw
            path.moveTo(bx + r, by)
            path.lineTo(bx, by + r)
            path.lineTo(bx, by + bh - r)
            path.quadTo(bx, by + bh, bx + r, by + bh)
            path.lineTo(rx - top_r, by + bh)
            if top_r > 0:
                path.quadTo(rx, by + bh, rx, by + bh - top_r)
            # Concave scoop DOWN-RIGHT to expanded bottom-right
            path.cubicTo(
                rx + lip * K,         by + bh - top_r if top_r > 0 else by + bh,
                rx + lip,             by + bh + flare * (1 - K),
                rx + lip,             by + bh + flare,
            )
            path.lineTo(rx + lip, by - flare)
            # Concave scoop UP-RIGHT mirror
            end_y = by + top_r if top_r > 0 else by
            path.cubicTo(
                rx + lip,             by - flare * (1 - K),
                rx + lip * K,         end_y,
                rx,                   end_y,
            )
            if top_r > 0:
                path.quadTo(rx, by, rx - top_r, by)
            path.closeSubpath()

        return path



# Module-level factory.  main.py calls this once at startup.
def create_and_show() -> DynamicIsland:
    """Always create the island window so the prefs-check timer stays alive.
    The window starts hidden if the user hasn't enabled it yet; toggling
    'Show timer island' in Settings will call show() via _maybe_reload_prefs."""
    isl = DynamicIsland()
    if isl._prefs.get('enabled', False):
        isl.show()
    # else: stays hidden but alive — _maybe_reload_prefs fires every 800 ms
    # and will call show() as soon as 'enabled' becomes True in island.json.
    return isl

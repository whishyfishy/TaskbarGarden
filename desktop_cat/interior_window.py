"""
House interior overlay for Desktop Cat.

Frameless, transparent-background widget — no OS title bar or X button.
Draws the bedroom pixel art inside a custom pixel-art wooden frame.
Draggable by clicking anywhere.  Closed by clicking the hut button again.

Animations
----------
  show_animated(x, y)  — expand + fade-in pop on open
  close_animated()     — shrink + fade-out, then actually close

Auto-dim
--------
  After ~0.75 s with no mouse on the window, fades to partial transparency.
  Mouse re-entry immediately restores full opacity.

Edit mode
---------
  Hold left mouse button still for 2 s → enters edit mode.
  Grid outlines appear, items shake.  Drag items to new cells; they snap on drop.
  Click bedroom background or outside window to exit.
"""

import json
import math
import os
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore    import Qt, QPoint, QRect, QTimer, pyqtProperty, QEvent
from PyQt6.QtCore    import QPropertyAnimation, QParallelAnimationGroup, QEasingCurve
from PyQt6.QtGui     import QPainter, QPixmap, QColor, QRegion, QPen, QFont
from desktop_cat.world_settings_window import WorldSettingsWindow
from desktop_cat.pomodoro_window       import PomodoroWindow
from desktop_cat.message_board_window  import MessageBoardWindow
from desktop_cat.clipboard_window      import ClipboardWindow

_SPRITE_DIR      = os.path.join(os.path.dirname(__file__), 'sprites')
_INTERIOR_SPRITE = os.path.join(_SPRITE_DIR, 'bedroom_interior.png')
_ITEMS_SAVE_PATH = os.path.join(os.path.dirname(__file__), 'bedroom_items.json')

_SCALE       = 2       # 2× base upscale
_SIZE_FACTOR = 0.572   # 0.52 × 1.10 — 10 % bigger than previous

# Dark fill for interior window openings (dark grey, semi-opaque)
_WINDOW_FILL = QColor(30, 30, 35, 220)

# Sprite tint — warm brown, baked onto opaque pixels only via SourceAtop
_SPRITE_TINT = QColor(108, 80, 46, 50)

# Animation durations (ms)
_OPEN_MS  = 220
_CLOSE_MS = 160
_DIM_MS   = 400

# Scale range for open/close pop
_POP_SCALE_START = 0.80

# Auto-dim settings
_DIM_DELAY_MS = 750    # idle time after mouse leaves before dimming
_DIM_OPACITY  = 0.35

# Edit mode
_HOLD_MS        = 2000   # hold duration to enter edit mode
_EDIT_OPACITY   = 0.82   # window opacity while in edit mode
_SHAKE_AMP      = 2      # widget-pixel shake amplitude
_SHAKE_SPEED    = 0.22   # phase increment per 16 ms tick
_PRESS_SCALE    = 0.82   # item scale while held (click feedback)
_MOVE_THRESHOLD = 6      # pixels of movement that cancels hold-to-edit

# ── Bedroom placement grid (sprite coordinates) ──────────────────────────────
_GRID_COLS = [(16,43),(48,75),(80,107),(112,139),(144,171)]
_GRID_ROWS = [(100,127),(132,159),(164,191),(196,209)]

_GRID_CELLS: dict[tuple[int,int], tuple[int,int]] = {}
for _ri, (_y0, _y1) in enumerate(_GRID_ROWS):
    for _ci in range(5):
        if _ri == 3 and _ci >= 3:
            continue
        _GRID_CELLS[(_ri, _ci)] = (_y0, _y1)
_GRID_CELLS[(2,3)] = (164, 183)
_GRID_CELLS[(2,4)] = (164, 183)
_GRID_CELLS[(3,0)] = (196, 215)
_GRID_CELLS[(3,1)] = (196, 215)
_GRID_CELLS[(3,2)] = (196, 215)

# Non-rectangular clips per cell: list of (x, y, w, h) in sprite px
_GRID_CLIPS: dict[tuple[int,int], list[tuple[int,int,int,int]]] = {
    (2,2): [(104, 184, 4, 8)],
    (3,2): [(104, 196, 4, 20)],
}

# Full unclipped cell centers (rows treated as full 28 px for center calc)
_FULL_ROWS = [(100,127),(132,159),(164,191),(196,223)]
_COL_CX    = [(x0+x1)//2 for x0,x1 in _GRID_COLS]
_ROW_CY    = [(y0+y1)//2 for y0,y1 in _FULL_ROWS]

_PLACEHOLDER_SIZE = 28   # sprite pixels

# ── Pixel-art item sprites (16×16 grids, '.' = transparent) ──────────────────
_SPRITES: dict[str, dict] = {
    'glove': {
        'rows': [
            '......AAAA......',
            '.....ABBBBA.....',
            '....ABBBBBBZ....',
            '...ABBBBBBBZ....',
            '..AABBBBBBBBZ...',
            '.ZAABBBBBBBBZ...',
            'ZZAABBBBBBBBBZ..',
            'ZZAABBBBBBBBBZ..',
            '.ZZABBBBBBBBBZ..',
            '..ZZABBBBBBBZ...',
            '..ZZZBBBBBBZZ...',
            '...ZZZBBBBBZ....',
            '....ZZBBBBZZ....',
            '....ZZBBBBZ.....',
            '.....ZZZZZ......',
            '......ZZZ.......',
        ],
        'palette': {
            'A': (228, 192, 110, 255),
            'B': (168, 122,  52, 255),
            'Z': ( 95,  58,  15, 255),
        },
    },
    'anvil': {
        'rows': [
            '..HAAAAAAAAAAA..',
            '.HAAAAAAAAAAAA..',
            'HAAAAAAAAAAAABB.',
            'ZAAAAAAAAAAABBB.',
            'ZAAAAAAAAAAAABZ.',
            '.ZBBBBBBBBBBBZ..',
            '..ZBBBBBBBBBBZ..',
            '..ZBMMMMMMMMZZ..',
            '..ZMMMDDDDMMZ...',
            '..ZDDDDDDDDDZ...',
            '..ZDDDDDDDDDZ...',
            '.ZZDDDDDDDDDZZ..',
            'ZDDDDDDDDDDDDDZ.',
            'ZDDDDDDDDDDDDDZ.',
            'ZDDDDDDDDDDDDDZZ',
            'ZZZZZZZZZZZZZZZ.',
        ],
        'palette': {
            'H': (245, 250, 255, 255),
            'A': (175, 182, 195, 255),
            'B': (125, 130, 142, 255),
            'M': ( 90,  94, 108, 255),
            'D': ( 52,  55,  65, 255),
            'Z': ( 30,  32,  38, 255),
        },
    },
    'work_table': {
        'rows': [
            'AAAAAAAAAAAAAAAA',
            'AAAEAAAEAAAEAAA.',
            'AAAAAAAAAAAAAAAA',
            'BBBBBBBBBBBBBBBB',
            'BBBBBBBBBBBBBBBB',
            'BBBBBBBBBBBBBBBB',
            '................',
            '................',
            'CC..........CC..',
            'CC..........CC..',
            'CC..........CC..',
            'CC..........CC..',
            'CC..........CC..',
            'CC..........CC..',
            'DD..........DD..',
            'DD..........DD..',
        ],
        'palette': {
            'A': (228, 192, 112, 255),
            'E': (248, 215, 140, 255),
            'B': (162, 118,  52, 255),
            'C': (128,  88,  38, 255),
            'D': ( 90,  58,  20, 255),
        },
    },
    'circle_table': {
        'rows': [
            '....AAAAAAAA....',
            '..AAAAAAAAAAAA..',
            '.AAAAAAAAAAAAAA.',
            'AAAAAAAAAAAAAAAA',
            'AABAAAAAAAAABAA.',
            'AAAAAAAAAAAAAAAA',
            '.BBBBBBBBBBBBB..',
            '..BBBBBBBBBBB...',
            '....BBCCCBB.....',
            '.....BCCCB......',
            '.....BCCCB......',
            '.....BCCCB......',
            '.....BCCCB......',
            '....BDDDDDB.....',
            '...BDDDDDDDB....',
            '....DDDDDDDD....',
        ],
        'palette': {
            'A': (228, 192, 112, 255),
            'B': (168, 128,  58, 255),
            'C': (128,  92,  38, 255),
            'D': ( 90,  58,  20, 255),
        },
    },
    'coin_bag': {
        'rows': [
            '.....CCCC.......',
            '....CCDDCC......',
            '....CCDDCC......',
            '.....CCCC.......',
            '....AAAAAA......',
            '...AAAAAAAAAA...',
            '..AAAAAAAAAAAA..',
            '.AAAABAAAABAAAA.',
            '.AAAAAAAAAAAAAA.',
            '.AAAAAAAAAAAAAA.',
            '.AAAABAAAABAAAA.',
            '..ZZAAAAAAAAZZ..',
            '..ZZAAAAAAAAAZ..',
            '...ZZZAAAAAZZ...',
            '....ZZZZZZZZ....',
            '.....ZZZZZZ.....',
        ],
        'palette': {
            'C': ( 88,  58,  14, 255),
            'D': ( 45,  28,   5, 255),
            'A': (218, 178,  42, 255),
            'B': (255, 228, 112, 255),
            'Z': (145, 100,  15, 255),
        },
    },
    'bed': {
        'rows': [
            'FFFFFFFFFFFFFFFF',
            'FFFFFFFFFFFFFFFF',
            'FWWWWWWWWWWWWWWF',
            'FWwwwwwwwwwwwwWF',
            'FWwwwwwwwwwwwwWF',
            'FWWWWWWWWWWWWWWF',
            'FCCCCCCCCCCCCCCF',
            'FCcCcCcCcCcCcCcF',
            'FCCCCCCCCCCCCCCF',
            'FCcCcCcCcCcCcCcF',
            'FCCCCCCCCCCCCCCF',
            'FCcCcCcCcCcCcCcF',
            'FCCCCCCCCCCCCCCF',
            'FFFFFFFFFFFFFFFF',
            'FFFFFFFFFFFFFFFF',
            'FFFFFFFFFFFFFFFF',
        ],
        'palette': {
            'F': (142,  92,  38, 255),
            'W': (245, 240, 225, 255),
            'w': (195, 188, 170, 255),
            'C': ( 82, 122, 202, 255),
            'c': ( 58,  96, 165, 255),
        },
    },
    'lamp': {
        'rows': [
            '....SSSSSSSS....',
            '...SSSSSSSSSS...',
            '..SSSSSSSSSSSS..',
            '.LSSSSSSSSSSSSL.',
            'LLSSSSSSSSSSSLLL',
            '.LLLLSSSSLLLL...',
            '....PPPPPPPP....',
            '.....PPPPPP.....',
            '......PPPP......',
            '.......PP.......',
            '.......PP.......',
            '.......PP.......',
            '.......PP.......',
            '.......PP.......',
            '....PPPPPPPP....',
            '...PPPPPPPPPP...',
        ],
        'palette': {
            'S': (248, 228, 138, 255),
            'L': (175, 148,  58, 255),
            'P': ( 78,  58,  26, 255),
        },
    },
}

_PLACEHOLDERS: list[tuple[tuple[int,int], str]] = [
    ((0,1), 'glove'),
    ((0,4), 'anvil'),
    ((1,2), 'work_table'),
    ((1,0), 'circle_table'),
    ((2,3), 'coin_bag'),
    ((3,1), 'lamp'),
    ((3,2), 'bed'),
]

_ITEM_LABELS: dict[str, str] = {
    'glove':        'world settings',
    'anvil':        'clipboard & tools',
    'work_table':   'pomodoro',
    'circle_table': 'plants, badges',
    'coin_bag':     'shop',
    'bed':          'profile',
    'lamp':         'notes, reminders',
}

_ITEM_COLORS: dict[str, QColor] = {
    'glove':        QColor(210, 120,  50),
    'anvil':        QColor(140, 145, 160),
    'work_table':   QColor(160, 110,  50),
    'circle_table': QColor(220, 180,  70),
    'coin_bag':     QColor(210, 170,  30),
    'bed':          QColor( 80, 120, 200),
    'lamp':         QColor(240, 210,  90),
}


class InteriorWindow(QWidget):
    def __init__(self, interior_path: str = _INTERIOR_SPRITE, overlay=None,
                 on_start_pomodoro=None,
                 on_toggle_pin_tool=None,
                 get_pin_status=None):
        super().__init__()
        self._overlay = overlay
        self._on_start_pomodoro  = on_start_pomodoro
        self._on_toggle_pin_tool = on_toggle_pin_tool
        self._get_pin_status     = get_pin_status

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        # ── Load and scale sprite ─────────────────────────────────────────
        self._pixmap = QPixmap(_INTERIOR_SPRITE)
        if not self._pixmap.isNull():
            self._pixmap = self._pixmap.scaled(
                int(self._pixmap.width()  * _SCALE * _SIZE_FACTOR),
                int(self._pixmap.height() * _SCALE * _SIZE_FACTOR),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            tp = QPainter(self._pixmap)
            tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            tp.fillRect(self._pixmap.rect(), _SPRITE_TINT)
            tp.end()

        img_w = self._pixmap.width()  if not self._pixmap.isNull() else 300
        img_h = self._pixmap.height() if not self._pixmap.isNull() else 250

        border  = 8
        total_w = img_w + border + 4
        total_h = img_h + border + 4
        self.setFixedSize(total_w, total_h)

        self._sprite_x = border
        self._sprite_y = border

        self._window_clip: QRegion = self._build_window_region()

        # ── Open/close animation ──────────────────────────────────────────
        self._anim_scale: float                       = 1.0
        self._main_anim:  QParallelAnimationGroup | None = None
        self._closing:    bool                        = False

        # ── Auto-dim ──────────────────────────────────────────────────────
        self._dim_timer = QTimer(self)
        self._dim_timer.setSingleShot(True)
        self._dim_timer.setInterval(_DIM_DELAY_MS)
        self._dim_timer.timeout.connect(self._start_dim)
        self._dim_anim: QPropertyAnimation | None = None

        # ── Window drag ───────────────────────────────────────────────────
        self._drag_offset: QPoint | None = None

        # ── Items (mutable placement dict, persisted to disk) ────────────
        self._items: dict[tuple[int,int], str] = self._load_items()

        # ── Edit mode ────────────────────────────────────────────────────
        self._edit_mode:    bool                      = False
        self._press_timer   = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.setInterval(_HOLD_MS)
        self._press_timer.timeout.connect(self._enter_edit_mode)
        self._press_pos:    QPoint | None             = None
        self._pressed_cell: tuple[int,int] | None     = None

        self._shake_timer = QTimer(self)
        self._shake_timer.setInterval(16)
        self._shake_timer.timeout.connect(self._on_shake_tick)
        self._shake_phase: float = 0.0

        self._dragging_cell: tuple[int,int] | None = None
        self._drag_item_pos: QPoint | None         = None

        # ── Hover state ──────────────────────────────────────────────────
        self._hovered_cell: tuple[int,int] | None = None

        # ── Sub-windows ──────────────────────────────────────────────────
        self._world_settings: WorldSettingsWindow | None = None
        self._pomodoro:       PomodoroWindow | None      = None
        self._message_board:  MessageBoardWindow | None  = None
        self._clipboard:      ClipboardWindow | None     = None

        QApplication.instance().installEventFilter(self)

    # ── Animatable scale property ─────────────────────────────────────────────

    @pyqtProperty(float)
    def anim_scale(self) -> float:          # type: ignore[override]
        return self._anim_scale

    @anim_scale.setter                      # type: ignore[override]
    def anim_scale(self, v: float) -> None:
        self._anim_scale = v
        self.update()

    # ── Public show / close ───────────────────────────────────────────────────

    def show_animated(self, x: int, y: int) -> None:
        self._closing = False
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
        self._main_anim.finished.connect(self._on_open_finished)
        self._main_anim.start()

    def close_animated(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._edit_mode = False
        self._shake_timer.stop()
        self._press_timer.stop()
        self._dim_timer.stop()
        if self._dim_anim:
            self._dim_anim.stop()

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

    def closeEvent(self, event) -> None:
        self._save_items()
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    # ── Item persistence ──────────────────────────────────────────────────────

    def _save_items(self) -> None:
        data = {f'{ri},{ci}': name for (ri, ci), name in self._items.items()}
        try:
            with open(_ITEMS_SAVE_PATH, 'w') as f:
                json.dump(data, f)
        except OSError:
            pass

    @staticmethod
    def _load_items() -> dict[tuple[int,int], str]:
        try:
            with open(_ITEMS_SAVE_PATH) as f:
                data = json.load(f)
            items = {}
            for key, name in data.items():
                ri, ci = map(int, key.split(','))
                if (ri, ci) in _GRID_CELLS and isinstance(name, str) and name in _SPRITES:
                    items[(ri, ci)] = name
            return items if items else dict(_PLACEHOLDERS)
        except (OSError, ValueError, KeyError):
            return dict(_PLACEHOLDERS)

    # ── Auto-dim ──────────────────────────────────────────────────────────────

    def _on_open_finished(self) -> None:
        self._dim_timer.start()

    def _start_dim(self) -> None:
        if self._closing or self._edit_mode:
            return
        if self._dim_anim:
            self._dim_anim.stop()
        self._dim_anim = QPropertyAnimation(self, b'windowOpacity', self)
        self._dim_anim.setDuration(_DIM_MS)
        self._dim_anim.setStartValue(self.windowOpacity())
        self._dim_anim.setEndValue(_DIM_OPACITY)
        self._dim_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._dim_anim.start()

    def _restore_opacity(self) -> None:
        if self._edit_mode:
            return
        self._dim_timer.stop()
        if self._dim_anim:
            self._dim_anim.stop()
            self._dim_anim = None
        if not self._closing:
            restore = QPropertyAnimation(self, b'windowOpacity', self)
            restore.setDuration(120)
            restore.setStartValue(self.windowOpacity())
            restore.setEndValue(1.0)
            restore.setEasingCurve(QEasingCurve.Type.OutCubic)
            restore.start()

    # ── Edit mode ─────────────────────────────────────────────────────────────

    def _enter_edit_mode(self) -> None:
        self._edit_mode     = True
        self._drag_offset   = None   # cancel any window drag in progress
        self._pressed_cell  = None
        self._shake_phase   = 0.0
        self._shake_timer.start()
        self._dim_timer.stop()
        if self._dim_anim:
            self._dim_anim.stop()
            self._dim_anim = None
        op = QPropertyAnimation(self, b'windowOpacity', self)
        op.setDuration(200)
        op.setStartValue(self.windowOpacity())
        op.setEndValue(_EDIT_OPACITY)
        op.start()
        self.update()

    def _exit_edit_mode(self) -> None:
        self._edit_mode      = False
        self._dragging_cell  = None
        self._drag_item_pos  = None
        self._pressed_cell   = None
        self._shake_timer.stop()
        op = QPropertyAnimation(self, b'windowOpacity', self)
        op.setDuration(200)
        op.setStartValue(self.windowOpacity())
        op.setEndValue(1.0)
        op.start()
        self.update()

    def _on_shake_tick(self) -> None:
        self._shake_phase += _SHAKE_SPEED
        self.update()

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _widget_to_sprite(self, pos: QPoint) -> tuple[float, float]:
        sc = _SCALE * _SIZE_FACTOR
        return (pos.x() - self._sprite_x) / sc, (pos.y() - self._sprite_y) / sc

    def _item_at_pos(self, pos: QPoint) -> tuple[int,int] | None:
        sx, sy = self._widget_to_sprite(pos)
        half = _PLACEHOLDER_SIZE / 2
        for (ri, ci) in self._items:
            if abs(sx - _COL_CX[ci]) <= half and abs(sy - _ROW_CY[ri]) <= half:
                return (ri, ci)
        return None

    def _nearest_cell(self, pos: QPoint) -> tuple[int,int]:
        sx, sy = self._widget_to_sprite(pos)
        best, best_dist = next(iter(_GRID_CELLS)), float('inf')
        for cell in _GRID_CELLS:
            ri, ci = cell
            d = (sx - _COL_CX[ci])**2 + (sy - _ROW_CY[ri])**2
            if d < best_dist:
                best_dist = d
                best = cell
        return best

    def _on_item_click(self, cell: tuple[int, int]) -> None:
        name = self._items.get(cell)
        if name == 'glove':
            if self._world_settings is None or not self._world_settings.isVisible():
                self._world_settings = WorldSettingsWindow()
                # Position to the right of the bedroom
                gx = self.x() + self.width() + 8
                gy = self.y()
                self._world_settings.show_animated(gx, gy)
            else:
                self._world_settings.close_animated()
        elif name == 'work_table':
            if self._pomodoro is None or not self._pomodoro.isVisible():
                self._pomodoro = PomodoroWindow()
                # Position to the right of the bedroom
                gx = self.x() + self.width() + 8
                gy = self.y()
                self._pomodoro.show_animated(gx, gy)
            else:
                self._pomodoro.close_animated()
        elif name == 'lamp':
            if self._message_board is None or not self._message_board.isVisible():
                self._message_board = MessageBoardWindow()
                # Position to the right of the bedroom
                gx = self.x() + self.width() + 8
                gy = self.y()
                self._message_board.show_animated(gx, gy)
            else:
                self._message_board.close_animated()
        elif name == 'anvil':
            if self._clipboard is None or not self._clipboard.isVisible():
                self._clipboard = ClipboardWindow(
                    on_start_pomodoro=self._on_start_pomodoro,
                    on_toggle_pin_tool=self._on_toggle_pin_tool,
                    get_pin_status=self._get_pin_status,
                )
                gx = self.x() + self.width() + 8
                gy = self.y()
                self._clipboard.show_animated(gx, gy)
            else:
                self._clipboard.close_animated()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _build_window_region(self) -> QRegion:
        if self._pixmap.isNull():
            return QRegion()
        img = self._pixmap.toImage()
        w, h = img.width(), img.height()
        is_transp = [[(img.pixel(x, y) >> 24 & 0xFF) <= 128 for x in range(w)] for y in range(h)]
        exterior  = [[False] * w for _ in range(h)]
        queue: list[tuple[int,int]] = []
        for x in range(w):
            for y in (0, h-1):
                if is_transp[y][x] and not exterior[y][x]:
                    exterior[y][x] = True; queue.append((x, y))
        for y in range(h):
            for x in (0, w-1):
                if is_transp[y][x] and not exterior[y][x]:
                    exterior[y][x] = True; queue.append((x, y))
        head = 0
        while head < len(queue):
            cx, cy = queue[head]; head += 1
            for ddx, ddy in ((-1,0),(1,0),(0,-1),(0,1)):
                nx, ny = cx+ddx, cy+ddy
                if 0 <= nx < w and 0 <= ny < h and not exterior[ny][nx] and is_transp[ny][nx]:
                    exterior[ny][nx] = True; queue.append((nx, ny))
        region = QRegion()
        sx, sy = self._sprite_x, self._sprite_y
        for y in range(h):
            for x in range(w):
                if is_transp[y][x] and not exterior[y][x]:
                    region = region.united(QRegion(QRect(sx+x, sy+y, 1, 1)))
        return region

    @staticmethod
    def _draw_sprite(p: QPainter, name: str, cx: int, cy: int,
                     pixel_size: int, clip: QRegion | None = None) -> None:
        if name not in _SPRITES:
            return
        data    = _SPRITES[name]
        rows    = data['rows']
        palette = data['palette']
        n       = len(rows)
        total   = pixel_size * n
        ox      = cx - total // 2
        oy      = cy - total // 2
        if clip is not None:
            p.save()
            p.setClipRegion(clip)
        for ry_, row in enumerate(rows):
            for rx_, ch in enumerate(row):
                if ch == '.' or ch not in palette:
                    continue
                p.fillRect(ox + rx_ * pixel_size, oy + ry_ * pixel_size,
                           pixel_size, pixel_size, QColor(*palette[ch]))
        if clip is not None:
            p.restore()

    def _draw_placeholders(self, p: QPainter) -> None:
        sx, sy = self._sprite_x, self._sprite_y
        sc     = _SCALE * _SIZE_FACTOR

        def s(v: int) -> int:
            return int(v * sc)

        base_half = max(1, s(_PLACEHOLDER_SIZE) // 2)

        # "EDIT MODE" label or hover label — higher up, bigger font
        label_text = None
        if self._edit_mode:
            label_text = 'EDIT MODE'
        elif self._hovered_cell and self._hovered_cell in self._items:
            sprite_name = self._items[self._hovered_cell]
            if sprite_name in _ITEM_LABELS:
                label_text = _ITEM_LABELS[sprite_name]

        if label_text:
            font = QFont('Courier New', 1)
            font.setPixelSize(max(10, s(13)))
            font.setBold(True)
            p.setFont(font)
            text_rect = QRect(sx + s(16), sy + s(26), s(155), s(28))
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(text_rect.adjusted(1, 1, 1, 1), Qt.AlignmentFlag.AlignCenter, label_text)
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label_text)

        # Dashed grid outlines
        if self._edit_mode:
            p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.PenStyle.DashLine))
            for (ri, ci), (y0, y1) in _GRID_CELLS.items():
                x0, x1 = _GRID_COLS[ci]
                p.drawRect(sx + s(x0), sy + s(y0), s(x1 - x0), s(y1 - y0))

        # Snap-target highlight while dragging
        if self._edit_mode and self._dragging_cell and self._drag_item_pos:
            target = self._nearest_cell(self._drag_item_pos)
            if target != self._dragging_cell:
                ri, ci = target
                x0, x1 = _GRID_COLS[ci]
                y0, y1 = _GRID_CELLS[target]
                p.setPen(QPen(QColor(255, 255, 255, 180), 2))
                p.drawRect(sx + s(x0), sy + s(y0), s(x1 - x0), s(y1 - y0))

        # Draw placed items as colored circles
        r = base_half
        for (ri, ci), name in self._items.items():
            if (ri, ci) == self._dragging_cell:
                continue

            cx = sx + s(_COL_CX[ci])
            cy = sy + s(_ROW_CY[ri])
            ox = int(math.sin(self._shake_phase + ci * 0.9 + ri * 0.5) * _SHAKE_AMP) if self._edit_mode else 0
            pr = max(1, int(r * (_PRESS_SCALE if (ri, ci) == self._pressed_cell else 1.0)))
            color = _ITEM_COLORS.get(name, QColor(180, 180, 180))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(cx + ox - pr, cy - pr, pr * 2, pr * 2)

        # Dragged item follows cursor
        if self._dragging_cell and self._drag_item_pos and self._dragging_cell in self._items:
            mx, my = self._drag_item_pos.x(), self._drag_item_pos.y()
            name = self._items[self._dragging_cell]
            color = _ITEM_COLORS.get(name, QColor(180, 180, 180))
            p.setOpacity(0.75)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(mx - r, my - r, r * 2, r * 2)
            p.setOpacity(1.0)

        # Hover highlight — white overlay on hovered circle
        if not self._edit_mode and self._hovered_cell and self._hovered_cell in self._items:
            ri, ci = self._hovered_cell
            cx = sx + s(_COL_CX[ci])
            cy = sy + s(_ROW_CY[ri])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    def paintEvent(self, _event) -> None:
        fw, fh = self.width(), self.height()

        buf = QPixmap(fw, fh)
        buf.fill(Qt.GlobalColor.transparent)
        bp = QPainter(buf)
        bp.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._window_clip.isEmpty():
            bp.save()
            bp.setClipRegion(self._window_clip)
            bp.fillRect(buf.rect(), _WINDOW_FILL)
            bp.restore()

        if not self._pixmap.isNull():
            bp.drawPixmap(self._sprite_x, self._sprite_y, self._pixmap)

        self._draw_placeholders(bp)
        bp.end()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s = self._anim_scale
        if s != 1.0:
            dw = int(fw * s); dh = int(fh * s)
            dx = (fw - dw) // 2; dy = (fh - dh) // 2
            p.drawPixmap(dx, dy, dw, dh, buf)
        else:
            p.drawPixmap(0, 0, buf)
        p.end()

    # ── Event filter (exit edit mode on click outside) ────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if (self._edit_mode
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            global_pos = event.globalPosition().toPoint()
            if not self.rect().contains(self.mapFromGlobal(global_pos)):
                self._exit_edit_mode()
        return False

    # ── Mouse events ─────────────────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        self._restore_opacity()
        if self._overlay is not None:
            self._overlay.set_interior_cursor_active(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered_cell = None
        self.update()
        if self._overlay is not None:
            self._overlay.set_interior_cursor_active(False)
        if not self._closing and not self._edit_mode:
            self._dim_timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._edit_mode:
            cell = self._item_at_pos(event.pos())
            if cell:
                self._dragging_cell  = cell
                self._drag_item_pos  = event.pos()
            else:
                self._exit_edit_mode()
        else:
            self._press_pos    = event.pos()
            self._pressed_cell = self._item_at_pos(event.pos())
            self._press_timer.start()
            self._drag_offset = event.pos()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        # Track hover state for label display
        hovered = self._item_at_pos(event.pos())
        if hovered != self._hovered_cell:
            self._hovered_cell = hovered
            self.update()

        if self._edit_mode:
            if self._dragging_cell is not None:
                self._drag_item_pos = event.pos()
                self.update()
        else:
            self._restore_opacity()
            if self._press_pos is not None:
                if (event.pos() - self._press_pos).manhattanLength() > _MOVE_THRESHOLD:
                    self._press_timer.stop()
                    self._pressed_cell = None
            if self._drag_offset is not None:
                self.move(self.pos() + event.pos() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._edit_mode:
            if self._dragging_cell is not None and self._drag_item_pos is not None:
                target = self._nearest_cell(self._drag_item_pos)
                color  = self._items.pop(self._dragging_cell)
                if target in self._items:
                    self._items[self._dragging_cell] = self._items[target]
                self._items[target] = color
                self._dragging_cell = None
                self._drag_item_pos = None
                self.update()
        else:
            was_cell = self._pressed_cell
            timer_was_active = self._press_timer.isActive()
            self._press_timer.stop()
            self._pressed_cell = None
            self._drag_offset  = None
            self._hovered_cell = self._item_at_pos(event.pos())
            # Short click (not a hold, not a drag) → open sub-window
            if was_cell and timer_was_active:
                self._on_item_click(was_cell)
            self.update()

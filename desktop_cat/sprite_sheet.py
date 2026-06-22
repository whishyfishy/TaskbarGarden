"""
Loader for the hand-drawn sprite sheet (AnimationsBugsAndFLowers.png).

Grid spec:
  cell   = 32 × 32 px
  gap    = 10 px between cells
  stride = 42 px

Animations are separated by 2+ consecutive blank cells when reading
left-to-right, top-to-bottom (like a book).  The tiny-bug animation has a
1-cell gap between flying and sitting sub-states — that gap is NOT enough to
start a new animation in this detector (needs 2+), so flying+sitting land in
one array; callers can split on the midpoint themselves if needed.

Animation indices (in the order they appear in the sheet):
  0 = ANIM_HYDRANGEA   — large blue hydrangea grow cycle (rows 1-2)
  1 = ANIM_GREEN_PLANT — tropical green plant grow cycle (rows 3-5)
  2 = ANIM_GRASS       — 3 static grass variants (row 5, after gap)
  3 = ANIM_FLOWER2     — second flower type grow cycle (rows 6-7)
  4 = ANIM_SNAIL       — snail crawl (rows 7-9)
  5 = ANIM_BUTTERFLY   — red butterfly flutter (rows 9-10)
  6 = ANIM_LADYBUG     — ladybug (rows 10-11)
  7 = ANIM_BUG_TINY    — yellow tiny bug: flying + sitting (rows 11-13)
  8 = ANIM_BUG_CAR     — bug in a red car, 5 frames (last rows)

The sheet is looked up in two places (first match wins):
  1. <project>/desktop_cat/sprites/AnimationsBugsAndFlowers.png
  2. ~/OneDrive/College/Claude Access/Animaition PNGs/AnimationsBugsAndFLowers.png
"""
from __future__ import annotations

import os
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPixmap

# ---------------------------------------------------------------------------
# Grid constants
# ---------------------------------------------------------------------------
CELL   = 32
GAP    = 20
STRIDE = CELL + GAP   # 52 px

# Hardcoded animation frame ranges (0-indexed cell indices, inclusive).
# HYDRANGEA and GREEN_PLANT are loaded from separate per-flower PNG files
# (flower_hydrangea.png / flower_green.png); their ranges below are placeholders
# and will be overridden in load().  FLOWER2 now lives at cells 0-13 of the
# main sheet (the blue flower at the top of rework.png / AnimationsBugsAndFlowers.png).
_ANIM_RANGES: list[tuple[int, int]] = [
    (0,   13),   # 0 HYDRANGEA:   placeholder — overridden by flower_hydrangea.png
    (0,    0),   # 1 GREEN_PLANT: placeholder — overridden by flower_green.png
    (35,  37),   # 2 GRASS:       3 static grass variants
    (0,   13),   # 3 FLOWER2:     rows 0-1 of main sheet; watermark filtered in load()
    (53,  64),   # 4 SNAIL:       snail crawl
    (67,  75),   # 5 BUTTERFLY:   butterfly flutter
    (78,  82),   # 6 LADYBUG:     ladybug
    (85,  96),   # 7 BUG_TINY:    tiny bug flying + sitting
    (100, 104),  # 8 BUG_CAR:     bug in car
]

GRID_COLS = 8  # Columns in the sprite sheet

# ---------------------------------------------------------------------------
# Animation index constants
# ---------------------------------------------------------------------------
ANIM_HYDRANGEA   = 0
ANIM_GREEN_PLANT = 1
ANIM_GRASS       = 2
ANIM_FLOWER2     = 3
ANIM_SNAIL       = 4
ANIM_BUTTERFLY   = 5
ANIM_LADYBUG     = 6
ANIM_BUG_TINY    = 7
ANIM_BUG_CAR     = 8
ANIM_MACRON       = 9   # macron plant — loaded from standalone macron.png
ANIM_GROUND_GRASS = 10
ANIM_BLUE_FLOWER  = 11  # blue flower  — flowers_brw.png cells 0-5  (6 growth frames)
ANIM_RED_FLOWER   = 12  # red flower   — flowers_brw.png cells 7-12 (6 growth frames)
ANIM_WHITE_FLOWER = 13  # white flower — flowers_brw.png cells 15-21 (7 growth frames)
ANIM_GREEN_FLOWER = 14  # green flower — flower_green2.png cells 0-8 (9 growth frames)
ANIM_TALL_FLOWER  = 15  # tall blue flower — flower_tall.png cells 0-13 (14 growth frames)

# Standalone sprite files loaded after the main sheet.
# Format: { anim_index: (filename, max_frames) }
# max_frames caps how many cells are collected (excludes the Resprite logo).
# The _is_watermark filter in _load_strip acts as a second safety net.
_STANDALONE_SPRITES: dict[int, tuple[str, int]] = {
    ANIM_HYDRANGEA:    ('flower_hydrangea.png',  9),   # STRIDE-grid, 9 frames (legacy, unused as flower type)
    ANIM_GREEN_PLANT:  ('flower_green.png',      0),   # plain strip — see _PLAIN_STRIP_CONFIG
    ANIM_MACRON:       ('macron.png',            0),   # plain 32×32 grid — see _PLAIN_STRIP_CONFIG
    ANIM_GROUND_GRASS: ('grass_ground.png',      0),   # all frames (STRIDE grid)
    ANIM_LADYBUG:      ('ladybug.png',           0),   # plain 16×32 grid — see _PLAIN_STRIP_CONFIG
    ANIM_BLUE_FLOWER:  ('flowers_brw.png',       0),   # plain 32×32 grid — see _PLAIN_STRIP_CONFIG
    ANIM_RED_FLOWER:   ('flowers_brw.png',       0),   # plain 32×32 grid — see _PLAIN_STRIP_CONFIG
    ANIM_WHITE_FLOWER: ('flowers_brw.png',       0),   # plain 32×32 grid — see _PLAIN_STRIP_CONFIG
    ANIM_GREEN_FLOWER: ('flower_green2.png',     0),   # plain 32×32 grid — see _PLAIN_STRIP_CONFIG
    ANIM_TALL_FLOWER:  ('flower_tall.png',       0),   # plain 32×32 grid — see _PLAIN_STRIP_CONFIG
}

# Per-animation config for sprites that use a dense grid (no STRIDE gaps).
# Format: { anim_idx: (frame_w, frame_h, max_frames, y_offset, min_pixels, no_crop, start_cell, skip_cells?) }
#   frame_w    — width of each cell in pixels
#   frame_h    — height of each cell; None = full image height (single-row strip)
#   max_frames — stop after collecting this many real frames (0 = no limit)
#   y_offset   — skip this many pixels at the top of the image before scanning
#   min_pixels — skip cells with fewer non-transparent pixels than this
#   no_crop    — when True, keep full cell; when False, auto-trim transparent borders
#   start_cell — skip this many cells (in scan order) before starting to collect
#   skip_cells — (optional) tuple of absolute cell indices to skip even if they pass
#                the pixel count test.  Use for cells where the artist placed the
#                Resprite watermark badge IN BETWEEN real animation frames, with a
#                stray pixel of art smearing the bounding box so the aspect-ratio
#                watermark filter no longer flags it.
#
# flowers_brw.png: 256×96, 32×32 px per frame, sequential global cell layout:
#   Cells  0-5:  Blue  (6 frames)  |  cell 6: blank separator
#   Cells  7-12: Red   (6 frames)  |  cells 13-14: blank separators
#   Cells 15-21: White (7 frames)  |  cells 19-20: watermark badge (skipped)
# flower_green2.png: 256×64, 32×32 px per frame.  Cells 0-8 = 9 growth frames.
# flower_tall.png:   256×448, 32×32 px per frame. Cells 0-13 = 14 growth frames.
# macron.png:        256×64, 32×32 px per frame.  Cells 0-10 = 11 growth frames.
# no_crop=True  → keep the full cell rectangle (artist sized it intentionally).
# no_crop=False → auto-trim transparent edges.
_PLAIN_STRIP_CONFIG: dict[int, tuple] = {
    ANIM_GREEN_PLANT:  (16, 20,  8, 0,  0, False,  0),  # 16×20 px, 8 growth frames
    ANIM_LADYBUG:      (36, 47, 10, 30,  3, False, 0),  # start at row 0 (top-down walk); 0-3 walk, 4-9 idle
    ANIM_BLUE_FLOWER:  (32, 32,  6, 0,  4, False,  0),  # cells 0-5
    ANIM_RED_FLOWER:   (32, 32,  6, 0,  4, False,  7),  # cells 7-12 (skip 0-6)
    # White flower: cells 15-21 contain its 7 growth frames, BUT the artist
    # parked the Resprite watermark inside cells 19 and 20 (with a stray
    # pre-bloom pixel above the badge).  The aspect-ratio watermark filter
    # is fooled by the extra pixel, so we explicitly skip 19+20 here.
    # That leaves 5 real frames: cells 15, 16, 17, 18, 21.
    ANIM_WHITE_FLOWER: (32, 32,  5, 0,  4, False, 15, (19, 20)),
    ANIM_MACRON:       (32, 32, 11, 0,  4, False,  0),  # cells 0-10
    ANIM_GREEN_FLOWER: (32, 32,  9, 0,  4, False,  0),  # cells 0-8
    ANIM_TALL_FLOWER:  (32, 32, 14, 0,  4, False,  0),  # cells 0-13
}

# Which animation each flower variant maps to (cycles through 5 types).
# variant % 5  →  animation index
# 0=green-flower  1=blue  2=red  3=white  4=tall-blue
_FLOWER_ANIM_MAP: list[int] = [
    ANIM_GREEN_FLOWER, ANIM_BLUE_FLOWER,
    ANIM_RED_FLOWER, ANIM_WHITE_FLOWER, ANIM_TALL_FLOWER,
]

# ANIM_BUG_TINY contains both flying and sitting sub-states separated by a
# 1-cell gap (too small to trigger animation boundary detection, which needs 2+
# cells). The split index is determined at load time by scanning for the gap.
# This will be set by SpriteSheet.load() if ANIM_BUG_TINY is present.
_TINY_BUG_FLYING_END: int = -1  # Index where flying frames end; sitting starts at this

# Fallback total when the sheet isn't loaded yet (so tend() still works at
# startup before the QApplication has shown the overlay).  Plants tended in
# that brief window still progress; the renderer will clamp to the actual
# animation length once the sheet finishes loading.
DEFAULT_FLOWER_TOTAL_FRAMES: int = 16

# How many frames a flower advances per successful tend session.  Larger
# values = faster visible progress per Sao interaction.
FLOWER_FRAMES_PER_TEND: int = 1

# Module-level singleton — set by the renderer once it successfully loads the
# sheet, so other modules (garden.py) can look up per-variant frame counts
# without holding their own reference.
_LOADED_SHEET: 'SpriteSheet | None' = None


def register_loaded_sheet(sheet: 'SpriteSheet') -> None:
    """Called by the renderer immediately after a successful load()."""
    global _LOADED_SHEET
    _LOADED_SHEET = sheet


def flower_total_frames(variant: int) -> int:
    """
    Total animation frame count for `variant`'s flower type.  Falls back to
    DEFAULT_FLOWER_TOTAL_FRAMES if the sheet hasn't been loaded yet.
    """
    if _LOADED_SHEET is not None and _LOADED_SHEET.loaded:
        n = len(_LOADED_SHEET.flower_frames(variant))
        if n > 0:
            return n
    return DEFAULT_FLOWER_TOTAL_FRAMES

# Candidate paths — first one that exists wins.
_SHEET_CANDIDATES: list[str] = [
    # Preferred: copy the file into the project sprites folder.
    os.path.join(os.path.dirname(__file__), 'sprites', 'AnimationsBugsAndFlowers.png'),
    # Fallback: original location in the user's OneDrive.
    os.path.join(os.path.expanduser('~'), 'OneDrive', 'College',
                 'Claude Access', 'Animaition PNGs',
                 'AnimationsBugsAndFLowers.png'),
]


def _find_sheet() -> str:
    for p in _SHEET_CANDIDATES:
        if os.path.isfile(p):
            return p
    return ''


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SpriteSheet:
    """
    Lazy-loaded sprite-sheet.  Call load() after QApplication exists.
    All QPixmap access happens post-load; before that, every accessor returns
    an empty list / None so callers can use the sheet unconditionally.
    """

    def __init__(self, scale: int = 1) -> None:
        """
        scale – integer pixel-art upscale applied to every extracted frame.
                1 = native 32 px cells; 2 = 64 px; etc.
        """
        self._scale   = scale
        self._loaded  = False
        # List of animations; each is a list of QPixmap frames.
        self._anims: list[list[QPixmap]] = []
        # Index where ANIM_BUG_TINY's flying frames end and sitting frames begin.
        # Set during load() by scanning the raw image. -1 if not found.
        self._tiny_bug_split_idx: int = -1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> bool:
        """Load frames using hardcoded animation ranges.  Returns True on success."""
        path = _find_sheet()
        if not path:
            print('[SpriteSheet] sheet not found in any candidate location.')
            print('  Copy AnimationsBugsAndFlowers.png to desktop_cat/sprites/')
            return False

        img = QImage(path)
        if img.isNull():
            print(f'[SpriteSheet] failed to open image: {path}')
            return False

        pm = QPixmap.fromImage(img)
        anims: list[list[QPixmap]] = []

        # Flower animations have the watermark filtered out; other animations
        # (grass, snail, butterfly …) are loaded as-is since the shape heuristic
        # would wrongly flag horizontal sprites like grass.
        _FLOWER_ANIM_INDICES = {ANIM_HYDRANGEA, ANIM_GREEN_PLANT, ANIM_FLOWER2}
        for anim_i, (start, end) in enumerate(_ANIM_RANGES):
            filter_wm = anim_i in _FLOWER_ANIM_INDICES
            anim_frames: list[QPixmap] = []
            for cell_idx in range(start, end + 1):
                r, c = divmod(cell_idx, GRID_COLS)
                frame = _extract(pm, r, c, self._scale)
                if filter_wm and _is_watermark(frame):
                    continue   # skip Resprite logo badge
                anim_frames.append(frame)
            anims.append(anim_frames)

        # ── Standalone sprite files ──────────────────────────────────────────
        # Load per-animation PNGs that live outside the main sheet.
        # Indices already in _anims get replaced; higher indices extend the list.
        sprites_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sprites')
        for anim_idx, (basename, max_f) in _STANDALONE_SPRITES.items():
            override_path = os.path.join(sprites_dir, basename)
            if not os.path.isfile(override_path):
                print(f'[SpriteSheet] standalone sprite not found: {basename}')
                continue
            if anim_idx in _PLAIN_STRIP_CONFIG:
                cfg = _PLAIN_STRIP_CONFIG[anim_idx]
                fw, fh, mf, y_off, min_px = cfg[:5]
                no_crop    = bool(cfg[5]) if len(cfg) > 5 else False
                start_cell = int(cfg[6])  if len(cfg) > 6 else 0
                skip_cells = tuple(cfg[7]) if len(cfg) > 7 else ()
                frames = _load_plain_strip(override_path, self._scale,
                                           frame_w=fw, frame_h=fh, max_frames=mf,
                                           y_offset=y_off, min_pixels=min_px,
                                           no_crop=no_crop, start_cell=start_cell,
                                           skip_cells=skip_cells)
            else:
                frames = _load_strip(override_path, self._scale, max_frames=max_f)
            if not frames:
                print(f'[SpriteSheet] no frames loaded from {basename}')
                continue
            # Extend the list if this anim index is beyond the main-sheet count
            while len(anims) <= anim_idx:
                anims.append([])
            anims[anim_idx] = frames
            print(f'[SpriteSheet] standalone anim={anim_idx}: '
                  f'{len(frames)} frames from {basename}')

        self._anims  = anims
        self._loaded = True

        # Detect the flying/sitting split in ANIM_BUG_TINY if present
        if len(anims) > ANIM_BUG_TINY:
            self._detect_tiny_bug_split()

        summary = ', '.join(f'{i}:{len(a)}fr' for i, a in enumerate(anims))
        print(f'[SpriteSheet] loaded {len(anims)} animations from {os.path.basename(path)}')
        print(f'  {summary}')
        if self._tiny_bug_split_idx >= 0:
            print(f'  [ANIM_BUG_TINY] split at frame {self._tiny_bug_split_idx}: '
                  f'{self._tiny_bug_split_idx} flying, '
                  f'{len(anims[ANIM_BUG_TINY]) - self._tiny_bug_split_idx} sitting')
        return True

    def frames(self, anim_idx: int) -> list[QPixmap]:
        """All frames for animation `anim_idx`.  Empty list if not loaded / OOB."""
        if not self._loaded or anim_idx >= len(self._anims):
            return []
        return self._anims[anim_idx]

    def get(self, anim_idx: int, frame_idx: int = 0) -> QPixmap | None:
        """Single frame; None if not available."""
        frames = self.frames(anim_idx)
        return frames[frame_idx % len(frames)] if frames else None

    def flower_frames(self, variant: int) -> list[QPixmap]:
        """Frames for the flower animation that matches `variant`."""
        anim_idx = _FLOWER_ANIM_MAP[variant % len(_FLOWER_ANIM_MAP)]
        return self.frames(anim_idx)

    def growth_frame_pixmap(self, variant: int,
                            growth_frame: int) -> QPixmap | None:
        """
        Return the QPixmap for a flower at exactly `growth_frame` of its
        animation.  Frame index is clamped to the animation's range — no idle
        cycling, no automatic motion: the displayed frame is *exactly* whatever
        progress Sao has tended into the plant.
        """
        frames = self.flower_frames(variant)
        if not frames:
            return None
        idx = max(0, min(growth_frame, len(frames) - 1))
        return frames[idx]

    def half_frame(self, anim_idx: int, frame_idx: int = 0) -> QPixmap | None:
        """
        Return the top half of a frame — used for edge/transition grass tufts
        that appear shorter and sit a little lower to blend into the ground.
        """
        f = self.get(anim_idx, frame_idx)
        if f is None:
            return None
        half_h = max(1, f.height() // 2)
        return f.copy(QRect(0, 0, f.width(), half_h))

    def tiny_bug_flying_frames(self) -> list[QPixmap]:
        """
        Frames for the flying sub-state of ANIM_BUG_TINY.
        Empty list if not loaded or split not detected.
        """
        if not self._loaded or len(self._anims) <= ANIM_BUG_TINY:
            return []
        if self._tiny_bug_split_idx < 0:
            return []
        return self._anims[ANIM_BUG_TINY][:self._tiny_bug_split_idx]

    def tiny_bug_sitting_frames(self) -> list[QPixmap]:
        """
        Frames for the sitting sub-state of ANIM_BUG_TINY.
        Empty list if not loaded or split not detected.
        """
        if not self._loaded or len(self._anims) <= ANIM_BUG_TINY:
            return []
        if self._tiny_bug_split_idx < 0:
            return []
        return self._anims[ANIM_BUG_TINY][self._tiny_bug_split_idx:]

    def _detect_tiny_bug_split(self) -> None:
        """
        Detect the split between flying and sitting frames in ANIM_BUG_TINY by
        finding the frame with the most visual discontinuity (the gap).

        The sprite sheet has a 1-cell white gap between the two sub-states; this
        gap becomes a mostly-blank frame in the extracted animation. Comparing
        frame similarity identifies where the sharpest visual break occurs.
        """
        frames = self._anims[ANIM_BUG_TINY]
        if len(frames) < 2:
            return

        def frame_dissimilarity(f1: QPixmap, f2: QPixmap) -> int:
            """Count non-white pixels that differ between two frames."""
            i1 = f1.toImage()
            i2 = f2.toImage()
            h = min(i1.height(), i2.height())
            w = min(i1.width(), i2.width())
            diff = 0
            for y in range(h):
                for x in range(w):
                    p1 = i1.pixel(x, y)
                    p2 = i2.pixel(x, y)
                    if p1 != p2:
                        diff += 1
            return diff

        # Find the transition with the largest visual gap
        max_gap = 0
        split_idx = -1
        for i in range(len(frames) - 1):
            gap = frame_dissimilarity(frames[i], frames[i + 1])
            if gap > max_gap * 1.2:  # 20% threshold to detect the sharpest break
                max_gap = gap
                split_idx = i + 1

        self._tiny_bug_split_idx = split_idx if split_idx > 0 else -1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_watermark(pm: QPixmap) -> bool:
    """Return True if this (auto-cropped) frame looks like the Resprite logo badge.

    After _extract() crops transparent borders the watermark is a short, very
    wide rectangle (the "MADE WITH RESPRITE" badge).  Real plant frames are
    always at least as tall as they are wide, so a width-to-height ratio ≥ 2.5
    combined with an absolute width ≥ 20 px unambiguously identifies the logo
    without ever misclassifying seeds, stems, or spread-out blooms.
    """
    w, h = pm.width(), pm.height()
    if h < 2:
        return False
    return w >= 20 and w >= h * 2.5


def _load_strip(path: str, scale: int, max_frames: int = 0) -> list[QPixmap]:
    """Load non-blank, non-watermark cells from a standalone sprite PNG.

    Uses the same CELL/STRIDE/GRID_COLS grid as the main sheet.
    max_frames: stop after collecting this many real frames (0 = no limit).
    The _is_watermark check acts as a secondary filter for the logo badge.
    """
    img = QImage(path)
    if img.isNull():
        return []
    pm     = QPixmap.fromImage(img)
    rows   = max(1, (img.height() + STRIDE - 1) // STRIDE)
    frames: list[QPixmap] = []
    for r in range(rows):
        for c in range(GRID_COLS):
            if max_frames > 0 and len(frames) >= max_frames:
                return frames          # hit the exact frame cap
            x0 = c * STRIDE
            y0 = r * STRIDE
            if x0 >= img.width() or y0 >= img.height():
                continue
            cell_w = min(STRIDE, img.width()  - x0)
            cell_h = min(STRIDE, img.height() - y0)
            has_px = False
            for py_ in range(cell_h):
                if has_px:
                    break
                for px_ in range(cell_w):
                    if ((img.pixel(x0 + px_, y0 + py_) >> 24) & 0xFF) > 10:
                        has_px = True
                        break
            if has_px:
                frame = _extract(pm, r, c, scale)
                if not _is_watermark(frame):
                    frames.append(frame)
    return frames


def _load_plain_strip(path: str, scale: int,
                      frame_w: int = CELL,
                      frame_h: int | None = None,
                      max_frames: int = 0,
                      y_offset: int = 0,
                      min_pixels: int = 0,
                      no_crop: bool = False,
                      start_cell: int = 0,
                      skip_cells: tuple[int, ...] = ()) -> list[QPixmap]:
    """Load frames from a dense sprite grid with no inter-frame gaps.

    frame_w    — width of each cell (default: CELL = 32 px).
    frame_h    — height of each cell.  None = full image height (single-row strip).
                 Set to 32 for square-cell 2D grids.
    max_frames — stop after collecting this many real frames (0 = no limit).
    y_offset   — skip this many pixels at the top before scanning (lets you jump
                 past logo/noise rows to the actual art region).
    min_pixels — skip cells with fewer than this many non-transparent pixels.
                 Used to filter out logo fragments that contain a handful of stray
                 pixels but are not real animation frames.
    no_crop    — when True, keep the full cell rectangle rather than trimming
                 transparent borders.  Use when the artist sized the frame
                 intentionally and the bounding box would misrepresent it.
    start_cell — skip this many cells (in scan order) before collecting frames.
                 Used to address the second or third animation packed in the same
                 file (e.g. Red/White flowers share flowers_brw.png with Blue).
    skip_cells — absolute cell indices (0-based, in scan order) to drop even if
                 they pass the pixel-count check.  Use for cells where the artist
                 placed the Resprite watermark badge interleaved with real frames.
    """
    skip_set = set(skip_cells)
    img = QImage(path)
    if img.isNull():
        return []
    pm     = QPixmap.fromImage(img)
    img_w  = img.width()
    img_h  = img.height()
    cell_h = (img_h - y_offset) if frame_h is None else frame_h
    if cell_h <= 0:
        return []
    n_cols  = max(1, img_w // frame_w)
    scan_h  = img_h - y_offset
    n_rows  = max(1, scan_h // cell_h)
    frames: list[QPixmap] = []
    cell_idx = 0
    for row in range(n_rows):
        for col in range(n_cols):
            if max_frames > 0 and len(frames) >= max_frames:
                return frames
            if cell_idx < start_cell:
                cell_idx += 1
                continue
            if cell_idx in skip_set:
                cell_idx += 1
                continue
            cell_idx += 1
            x0 = col * frame_w
            y0 = y_offset + row * cell_h
            w  = min(frame_w, img_w - x0)
            h  = min(cell_h,  img_h - y0)
            if w <= 0 or h <= 0:
                continue
            # Count non-transparent pixels (used for both has-content and min_pixels checks)
            px_count = 0
            for py_ in range(h):
                for px_ in range(w):
                    if ((img.pixel(x0 + px_, y0 + py_) >> 24) & 0xFF) > 10:
                        px_count += 1
            if px_count < max(1, min_pixels):
                continue
            raw = pm.copy(QRect(x0, y0, w, h))
            if no_crop:
                # Keep the full cell — artist sized it intentionally
                frame = raw
            else:
                # Auto-crop transparent borders to tight bounding box
                raw_img = raw.toImage()
                min_x, min_y = w, h
                max_x, max_y = 0, 0
                for py_ in range(h):
                    for px_ in range(w):
                        if ((raw_img.pixel(px_, py_) >> 24) & 0xFF) > 10:
                            min_x = min(min_x, px_)
                            min_y = min(min_y, py_)
                            max_x = max(max_x, px_)
                            max_y = max(max_y, py_)
                if max_x < min_x:
                    continue  # blank cell
                frame = raw.copy(QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))
                if _is_watermark(frame):
                    continue
            if scale != 1:
                frame = frame.scaled(
                    frame.width() * scale, frame.height() * scale,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            frames.append(frame)
    return frames


def _cell_has_content(img: QImage, row: int, col: int) -> bool:
    """True if any pixel in the grid cell is visible sprite content."""
    x0 = col * STRIDE
    y0 = row * STRIDE
    w  = min(CELL, img.width()  - x0)
    h  = min(CELL, img.height() - y0)
    if w <= 0 or h <= 0:
        return False
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            px = img.pixel(x, y)
            a  = (px >> 24) & 0xFF
            if a < 20:
                continue  # fully transparent → not content
            r  = (px >> 16) & 0xFF
            g  = (px >>  8) & 0xFF
            b  =  px        & 0xFF
            # Visible pixel that isn't pure white → content
            if r < _WHITE_MIN or g < _WHITE_MIN or b < _WHITE_MIN:
                return True
    return False


def _extract(pm: QPixmap, row: int, col: int, scale: int) -> QPixmap:
    """Extract one grid cell (full stride area to catch sprites that bleed
    beyond 32×32) and optionally up-scale it.  Auto-crops transparent borders
    so the returned pixmap tightly wraps the visible art."""
    x = col * STRIDE
    y = row * STRIDE
    # Grab the full stride area to capture art that extends into the gap
    w = min(STRIDE, pm.width()  - x)
    h = min(STRIDE, pm.height() - y)
    raw = pm.copy(QRect(x, y, w, h))
    # Auto-crop transparent borders
    img = raw.toImage()
    min_x, min_y = w, h
    max_x, max_y = 0, 0
    for py_ in range(h):
        for px_ in range(w):
            if ((img.pixel(px_, py_) >> 24) & 0xFF) > 10:
                min_x = min(min_x, px_)
                min_y = min(min_y, py_)
                max_x = max(max_x, px_)
                max_y = max(max_y, py_)
    if max_x < min_x:
        # Completely empty cell — return a tiny transparent pixmap
        frame = raw.copy(QRect(0, 0, CELL, CELL))
    else:
        frame = raw.copy(QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))
    if scale != 1:
        frame = frame.scaled(
            frame.width() * scale, frame.height() * scale,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
    return frame

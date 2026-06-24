"""
Sprite animation system for Desktop Cat.

The sprite sheets are locomotion strips — the character physically walks across
the row, so cell boundaries don't align with character boundaries.  We extract
frames by scanning the full strip for distinct character blobs (contiguous runs
of non-transparent columns), then crop and centre each blob into a CAT_W×CAT_H
pixmap.
"""

import os
import math
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QPixmap, QPainter

# ── Spritesheet geometry ──────────────────────────────────────────────────────
SPRITE_W     = 16
SPRITE_H     = 20
SPRITE_ROW   = 2    # row 2 = right-facing side profile
RENDER_SCALE = 2

CAT_W  = SPRITE_W * RENDER_SCALE        # 32 logical px — physics / collision width
CAT_H  = SPRITE_H * RENDER_SCALE        # 40 logical px
FRAME_W = (SPRITE_W + 24) * RENDER_SCALE # 80 logical px — rendering frame (wider to avoid limb clip)

# ── Animation definitions: name → (frame_count, ticks_per_frame) ─────────────
ANIM: dict[str, tuple[int, int]] = {
    'idle':           (5,  8),
    'walk':           (5, 10),   # base tpf — overridden per-frame by _FRAME_TPF below
    'run':            (7,  6),
    'jump':           (6,  5),
    'interact_far':   (5, 16),   # row 2 (index 2) — side profile, ~20px from plant
    'interact_mid':   (5, 16),   # row 1 (index 1) — ~10px from plant
    'interact_close': (5, 16),   # row 0 (index 0) — front facing, right on top
    'attack':         (9,  3),   # punch — side profile; one-shot lunge at the cursor
}

# Per-frame tick overrides for variable-speed animations.
# {name: [tpf_frame0, tpf_frame1, ...]}  Falls back to ANIM base tpf if absent.
# Walk: frames 0,2 = feet close together (slightly slower)
#        frames 1,3 = mid-stride (slightly faster)
_FRAME_TPF: dict[str, list[int]] = {
    'walk': [12, 8, 12, 8, 10],
    # Attack: slow wind-up (frames 0-2), a snappy swing (frame 3), then a held
    # follow-through on the last two frames.  Frame index 2 (the cocked-back
    # pose) is held double-length (16) for a beefier wind-up.  Sum = 58 — keep
    # PUNCH_ANIM_TICKS in sync.
    'attack': [9, 9, 16, 3, 9, 12],
}

_SHEET_FILE: dict[str, str] = {
    'idle':           '16x16 Idle-Sheet.png',
    'walk':           '16x16 Walk-Sheet.png',
    'run':            '16x16 Run-Sheet.png',
    'jump':           '16x16 Jump-Sheet.png',
    'interact_far':   '16x16 Interact-Sheet.png',
    'interact_mid':   '16x16 Interact-Sheet.png',
    'interact_close': '16x16 Interact-Sheet.png',
    'attack':         '16x16 Attack-Sheet.png',
}

# Per-animation row override (0-indexed). Falls back to SPRITE_ROW if not set.
_SHEET_ROW: dict[str, int] = {
    'interact_far':   2,   # row 3 visually (index 2) — side profile
    'interact_mid':   1,   # row 2 visually (index 1)
    'interact_close': 0,   # row 1 visually (index 0) — front facing
}

# Per-animation absolute Y pixel offset, for sheets whose rows don't sit on the
# 20px grid the locomotion sheets use.  The Attack sheet has 5 rows of ~24px
# pitch (bands at y=7/32/56/79/103); the middle right-facing punch row sits at
# y≈56, so we read a 20px window starting just above it.
_SHEET_Y0: dict[str, int] = {
    'attack': 54,
}

_ALPHA_THRESHOLD  = 10
LANDING_HOLD_TICKS = 14   # ~0.23s to hold landing frame before returning to idle/walk
MAX_RUN_BOUNCE     = 3    # logical-px peak upward offset during run bounding arc


def _find_blobs(strip: QPixmap) -> list[tuple[int, int]]:
    """
    Scan a strip and return a list of (left_x, right_x) for each contiguous
    group of columns that contain non-transparent pixels.
    """
    img = strip.toImage()
    w, h = strip.width(), strip.height()

    col_occ = [False] * w
    for x in range(w):
        for y in range(h):
            if (img.pixel(x, y) >> 24) & 0xFF > _ALPHA_THRESHOLD:
                col_occ[x] = True
                break

    blobs: list[tuple[int, int]] = []
    in_blob = False
    start = 0
    for x in range(w):
        if col_occ[x] and not in_blob:
            start = x
            in_blob = True
        elif not col_occ[x] and in_blob:
            blobs.append((start, x - 1))
            in_blob = False
    if in_blob:
        blobs.append((start, w - 1))

    return blobs


def _blob_to_frame(strip: QPixmap, left: int, right: int) -> QPixmap:
    """
    Extract a blob from the strip, centre it horizontally, and bottom-align it
    vertically so feet always sit at the same y across all frames.
    """
    img = strip.toImage()
    blob_w = right - left + 1

    # Find the bottom-most non-transparent row in this blob
    bot_y = 0
    for x in range(left, right + 1):
        for y in range(strip.height() - 1, -1, -1):
            if (img.pixel(x, y) >> 24) & 0xFF > _ALPHA_THRESHOLD:
                if y > bot_y:
                    bot_y = y
                break

    cropped = strip.copy(QRect(left, 0, blob_w, strip.height()))

    # Place centred horizontally, bottom-aligned vertically.
    # Use FRAME_W (wider than CAT_W) so extended limbs in run frames don't clip.
    frame = QPixmap(FRAME_W, CAT_H)
    frame.fill(Qt.GlobalColor.transparent)
    dx = (FRAME_W - blob_w) // 2
    dy = CAT_H - 1 - bot_y          # shift so bottom pixel lands at CAT_H-1
    p = QPainter(frame)
    p.drawPixmap(QPoint(dx, dy), cropped)
    p.end()
    return frame


def _extract_frames(strip: QPixmap, n_frames: int) -> list[QPixmap]:
    """
    Find character blobs in the full strip and convert each into a centred
    CAT_W×CAT_H pixmap.  The actual number of frames equals the number of
    blobs found (which may be less than n_frames if some characters span
    cell boundaries with no gap between them).
    """
    blobs = _find_blobs(strip)
    return [_blob_to_frame(strip, l, r) for l, r in blobs]


class Animator:
    def __init__(self, sprite_dir: str):
        self._dir = sprite_dir
        self._frames_right: dict[str, list[QPixmap]] = {}
        self._frames_left:  dict[str, list[QPixmap]] = {}
        self._loaded = False

        self._name             = 'idle'
        self._frame            = 0
        self._ticks            = 0
        self.facing_right      = True
        self._was_grounded     = True
        self._landing_ticks    = 0
        self._cycle_completed  = False
        self._cycle_count      = 0

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def cycle_just_completed(self) -> bool:
        return self._cycle_completed

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def run_bounce_offset(self) -> int:
        """Negative-Y (upward) pixel offset for the run bounding effect.
        Ground-contact frames (index 0 and n//2) return 0.
        Airborne frames follow a smooth sin arc between ground contacts.
        """
        if self._name != 'run':
            return 0
        frames = self._frames_right.get('run', [])
        n = len(frames)
        if n < 4:
            return 0
        _, tpf = ANIM.get('run', (1, 5))
        half = n // 2
        if self._frame == 0 or self._frame == half:
            return 0   # ground-contact frame
        if 1 <= self._frame < half:
            phase_frame = self._frame - 1
            phase_len   = half - 1
        else:
            phase_frame = self._frame - (half + 1)
            phase_len   = n - half - 1
        if phase_len <= 0:
            return 0
        t    = phase_frame * tpf + self._ticks
        dur  = phase_len   * tpf
        frac = t / dur
        return -int(MAX_RUN_BOUNCE * math.sin(math.pi * frac))

    def load(self) -> bool:
        """Load and pre-build all frame pixmaps. Call after QApplication exists."""
        for name, filename in _SHEET_FILE.items():
            path = os.path.join(self._dir, filename)
            sheet = QPixmap(path)
            if sheet.isNull():
                print(f'[Animator] could not load: {path}')
                return False

            n_frames, _ = ANIM[name]
            y0 = _SHEET_Y0.get(name, _SHEET_ROW.get(name, SPRITE_ROW) * SPRITE_H)

            # Grab up to one extra SPRITE_W column beyond the last cell so
            # limbs that overflow their cell boundary (e.g. the arm in run
            # frame 7) are captured.  Scale at exactly 2× whatever we grabbed,
            # so animations that have no overflow keep correct proportions.
            n_sprite_cols = min(n_frames * SPRITE_W + SPRITE_W, sheet.width())
            raw    = sheet.copy(QRect(0, y0, n_sprite_cols, SPRITE_H))
            tight  = raw.scaled(
                n_sprite_cols * RENDER_SCALE, CAT_H,   # exact 2× — no distortion
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            # Pad 16px of transparent space on each side so limbs in the first
            # and last frames are never clipped by the canvas edge regardless of
            # how far they extend into neighbouring cells in the original sheet.
            PAD = 16
            scaled = QPixmap(tight.width() + PAD * 2, CAT_H)
            scaled.fill(Qt.GlobalColor.transparent)
            _p = QPainter(scaled)
            _p.drawPixmap(QPoint(PAD, 0), tight)
            _p.end()

            right = _extract_frames(scaled, n_frames)
            if not right:
                print(f'[Animator] no frames found for: {name}')
                return False
            self._frames_right[name] = right
            self._frames_left[name] = [
                QPixmap.fromImage(f.toImage().mirrored(horizontal=True, vertical=False))
                for f in right
            ]

        self._loaded = True
        return True

    def update(self, anim_name: str, vx: float,
               vy: float = 0.0, grounded: bool = True,
               wind_up_frac: float = 0.0, face_override: 'int | None' = None) -> None:
        """Advance one tick. Call exactly once per game tick."""
        # Facing direction.  Normally derived from horizontal velocity, but a
        # face_override (1=right, -1=left) can force it — used for the
        # backwards-shuffle ("moonwalk") part of a graceful turn.
        if face_override is not None:
            self.facing_right = face_override > 0
        elif vx > 0.5:
            self.facing_right = True
        elif vx < -0.5:
            self.facing_right = False

        # ── Nap: hold a single frame (interact_mid / row index 1, frame 2) ──
        if anim_name == 'nap':
            self._name = 'interact_mid'
            frames = self._frames_right.get('interact_mid', [])
            self._frame = min(2, len(frames) - 1) if frames else 0
            self._cycle_completed = False
            self._was_grounded = grounded
            return

        just_landed = grounded and not self._was_grounded

        # ── Landing hold: keep jump sheet frame 4 briefly after touching down ──
        if just_landed and self._name == 'jump':
            self._landing_ticks = LANDING_HOLD_TICKS

        if self._landing_ticks > 0:
            self._landing_ticks -= 1
            self._name  = 'jump'
            jump_frames = self._frames_right.get('jump', [])
            self._frame = min(4, len(jump_frames) - 1)
            self._was_grounded = grounded
            return

        # ── Normal anim switch ─────────────────────────────────────────────────
        if anim_name != self._name:
            self._name  = anim_name
            self._frame = 0
            self._ticks = 0

        # ── Jump: physics-driven frame selection, no cycling ──────────────────
        if self._name == 'jump':
            jump_frames = self._frames_right.get('jump', [])
            n = len(jump_frames)
            if n > 0:
                if wind_up_frac > 0.0:
                    # wind-up: frame 0 (crouch) for first 60%, frame 1 (launch) for last 40%
                    self._frame = 0 if wind_up_frac >= 0.5 else min(1, n - 1)
                elif vy < -5.0:
                    self._frame = min(2, n - 1)   # rising
                else:
                    self._frame = min(3, n - 1)   # falling / peak
            self._was_grounded = grounded
            return

        # ── All other anims: normal tick-based cycling ─────────────────────────
        n_frames = len(self._frames_right.get(self._name, []))
        if n_frames == 0:
            self._cycle_completed = False
            self._was_grounded = grounded
            return
        _, base_tpf = ANIM.get(self._name, (1, 8))
        frame_tpfs  = _FRAME_TPF.get(self._name)
        tpf = frame_tpfs[self._frame % len(frame_tpfs)] if frame_tpfs else base_tpf
        self._ticks += 1
        if self._ticks >= tpf:
            self._ticks = 0
            prev_frame  = self._frame
            self._frame = (self._frame + 1) % n_frames
            if self._frame == 0 and prev_frame == n_frames - 1:
                self._cycle_count    += 1
                self._cycle_completed = True
            else:
                self._cycle_completed = False
        else:
            self._cycle_completed = False

        self._was_grounded = grounded

    def current_frame(self) -> QPixmap | None:
        """Return the pre-built QPixmap for the current frame and facing direction."""
        if not self._loaded:
            return None
        frames = (self._frames_right if self.facing_right else self._frames_left).get(self._name)
        if not frames:
            return None
        return frames[self._frame % len(frames)]

import ctypes
import ctypes.wintypes
import json
import os
import sys
import random
import threading
import argparse
from dataclasses import replace, asdict
from datetime import date as _date, datetime as _datetime

# Qt sets DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 automatically.
# win32gui returns PHYSICAL pixels; Qt renders in LOGICAL pixels.
# We scale all win32gui coords down by devicePixelRatio.

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QPoint
from PyQt6.QtGui import QCursor
import math

from desktop_cat.event_bus import EventBus
import desktop_cat.physics as _phys
from desktop_cat.physics import CatState, apply_physics, walk, stop_walking, jump, JUMP_MIN_POWER, GRAVITY
from desktop_cat.collision import Platform, resolve_collision
import win32gui
import win32con
from desktop_cat.window_scanner import (WindowScanner, ScanScheduler,
                                        check_occluded, has_fullscreen_window)
from desktop_cat.renderer import CatOverlay
from desktop_cat.animator import CAT_W, CAT_H
from desktop_cat.garden import (Garden, PLANT_HALF_WIDTHS, PLANT_TOP_HEIGHTS,
                                TaskFlower, FallingSeed, Plant,
                                FLOWER_NAMES, FLOWER_VARIANT_COUNT, PLANT_STAGES,
                                PLANT_FLOWER, PLANT_MACRON)
import desktop_cat.inventory as inv_mod
from desktop_cat.inventory import FLOWER_PLANT_CAP, MACRON_PLANT_CAP
from desktop_cat.critters import (Bug, Butterfly, CollectEffect, Shrub, Rock,
                                   FriendBug, make_friend_bug,
                                   LazyBug, make_lazy_bug,
                                   Snail, make_snail,
                                   make_bug, make_butterfly,
                                   make_collect_effect, make_butterfly_pop,
                                   make_shrub, make_rock)
from desktop_cat.pomodoro_window import PomodoroWindow
from desktop_cat.interior_window import InteriorWindow  # legacy, unwired
from desktop_cat.library_hub_window import LibraryHubWindow
from desktop_cat.pin_manager     import PinManager
from desktop_cat.global_hotkeys  import GlobalHotkeys
from desktop_cat.onboarding_window import OnboardingWindow
from desktop_cat import user_profile
from desktop_cat import sounds
from desktop_cat import blocks_data
from desktop_cat import taskbar_icons

TICK_MS = 1000 // 60        # ~16ms = 60 FPS
SCAN_EVERY = 3              # scan windows every 3rd tick (~20 Hz)

# Wandering
WANDER_CHANGE_TICKS = 420   # ~7s between direction changes (calmer pace)
IDLE_PAUSE_TICKS    = 220   # ~3.7s forced pause after landing (heavier idle)
NAP_AFTER_TICKS     = 5400  # ~90s with the cursor away → Sao dozes off (daytime).
                            # After 9 PM this is scaled to 40% (~36s), so she
                            # naps much more often at night.
NAP_NEAR_PX         = 95    # cursor within this of her wakes her / blocks napping

# Jump behaviour
WIND_UP_TICKS       = 20    # ~0.33s crouch before launching
JUMP_CONSIDER_TICKS = 600   # ~10s between jump opportunities (rarer jumps)
JUMP_CHANCE         = 0.35  # probability of actually jumping when opportunity arises
BURST_CHANCE        = 0.08  # probability of queuing another jump quickly (rare burst)
JUMP_HORIZONTAL_RANGE   = 500
JUMP_MAX_HEIGHT         = 450
MIN_JUMP_PLATFORM_W     = 80    # logical px — skip tiny child platforms as jump targets
MAX_JUMP_ATTEMPTS     = 3
JUMP_GIVE_UP_TICKS    = 300 # ~5s cooldown after giving up

# Descend behaviour
DESCEND_CHANCE = 0.45

# Cute one-liners Sao pops in a speech bubble when you finish a task.
_SAO_DONE_LINES = ('Nice work! 🌸', 'One down! ✨', 'Proud of you 💛',
                   'Yay, done! 🌷', 'Keep it up! 🍃', 'So tidy! ✨',
                   'Lovely! 🌼', 'Look at you go! ⭐')
_SAO_EAT_LINES  = ('nom nom ♡', 'mmm! 🍪', 'tasty~', 'yum! ♡', 'so good!')
MACARON_NOTICE_PX = 480   # she only chases/eats a treat within this horizontal range
# Beach ball — floaty (low gravity, air-filled bounce) toy Sao bats with her paw.
BALL_RADIUS      = 14      # ~15% smaller than before
BALL_GRAVITY     = 0.34    # lower → floatier, falls gently (lots of air inside)
BALL_RESTITUTION = 0.74    # bounciness
BALL_AIR         = 0.992   # gentle drag
BALL_REST_VY     = 1.0     # below this bounce speed at the floor → it settles
BALL_KICK        = 9.0     # horizontal impulse from a bat
BALL_POP         = 7.0     # base upward impulse from a bat (randomised per hit)
BALL_NOTICE      = 640     # how close (horizontal) before she notices / chases it
BALL_PUNCH_CD    = 20      # ticks between bats (it's a toy, no hard rate-limit)
BALL_APPROACH_MAX = 700    # she'll chase/wait under the ball this long before giving up

# Taskbar drop — Sao occasionally hops down into the taskbar to walk around
TASKBAR_DROP_CHANCE  = 0.38   # probability per wander-change when on floor
INTERACT_TICKS_MIN   = 240    # ~4 s minimum at-bottom time
INTERACT_TICKS_MAX   = 540    # ~9 s maximum at-bottom time

# Plant interaction — Sao approaches and tends a plant at taskbar level
PLANT_INTERACT_CHANCE    = 0.50   # probability per wander-change when on floor
PLANT_APPROACH_TICKS_MIN = 180    # ~3 s tending a plant
PLANT_APPROACH_TICKS_MAX = 400    # ~6.7 s tending a plant

# Run transition smoothing
WANDER_ACCEL_TICKS  = 18   # ~0.3s ramp from walk→run speed at run start
WANDER_DECEL_TICKS  = 24   # ~0.4s ramp from run→walk speed at run end
WANDER_BOOST_TICKS  = 8    # ~0.13s slight overspeed at walk-start after run

# Walk-around — Sao walks off one screen edge and re-enters from the other
# when a fullscreen window blocks all jump paths.
WALK_AROUND_SPEED    = 120    # px/s while walking off-screen

# Occlusion
# The cat is only hidden when it has been continuously covered for this many
# ticks — prevents flicker when a window is dragged quickly past the cat.
OCCLUDE_HIDE_TICKS   = 90   # ~1.5 s of stable coverage before hiding (reduces tab-switch false positives)
# After this many ticks hidden the cat teleports to bottom-left and walks in.
OCCLUDE_ESCAPE_TICKS = 1800  # ~30 s

# Re-assert overlay z-order every N ticks so it stays above taskbar/new windows
TOPMOST_REASSERT_TICKS = 60   # ~1 s — re-assert frequently so tab switches don't let windows slip above

# Mouse proximity
CURSOR_SLOW_RADIUS = 48   # hover within this many px of Sao → she brakes so she's easy to click
HOVER_STOP_TICKS   = 60   # she only holds still ~1 s for a hovering cursor, then carries on

# Cursor punch — when the user WIGGLES the cursor back and forth over Sao in
# rapid succession she gets annoyed, runs to the cursor, and throws a wind-up
# punch that knocks it sideways + slightly up.
PUNCH_NEAR_PX        = 130   # cursor within this horizontal range (she'll run over)
PUNCH_FLOOR_PX       = 55    # …and within this many px of the floor (≈ taskbar level)
PUNCH_RANGE          = 18    # how close she gets before throwing the punch
PUNCH_APPROACH_MAX   = 220   # give up the approach after this many ticks
PUNCH_WINDOW_TICKS   = 180 * 60  # rate-limit window: 3 minutes at 60 fps
PUNCH_MAX_PER_WINDOW = 2     # at most this many punches per window, then she leaves it be
PUNCH_ANIM_TICKS     = 58    # full punch — MUST equal sum(_FRAME_TPF['attack'])
PUNCH_SWING_ELAPSED  = 34    # tick within the punch when the fist lands (start of frame index 3)
PUNCH_REACH          = 10    # logical px her body lunges into the swing
PUNCH_COOLDOWN       = 720   # ticks (~12 s) before she can punch again — spaces the two
                             # allowed punches out so they're never back-to-back
PUNCH_CURSOR_KICK    = 26.0  # initial horizontal knockback speed (physical px/tick); decays
PUNCH_CURSOR_KICK_UP = 16    # one-time upward pop (physical px) when the fist lands
PUNCH_CURSOR_DECAY   = 0.78  # per-tick slide decay → smooth glide-and-slow
# Pester trigger: count cursor "passes" over Sao (entering her zone).  Reaching
# PESTER_TRIGGER passes within PESTER_WINDOW ticks annoys her into a punch.
PESTER_ZONE_PX       = 34    # half-width of the "over Sao" zone for a pass to count
PESTER_TRIGGER       = 4     # this many rapid passes → she swings
PESTER_WINDOW        = 110   # ticks; passes must come within this rolling window or reset

# Critters
BUG_SYNC_TICKS          = 300    # re-sync bugs to flower stages every 5 s
BUTTERFLY_SPAWN_MIN     = 2400   # 40 s min between butterfly spawns (rare)
BUTTERFLY_SPAWN_MAX     = 7200   # 2 min max — a butterfly is a special moment
BUTTERFLY_CHASE_TICKS   = 180    # 3 s max chase before butterfly flees anyway
BUTTERFLY_FLEE_DIST     = 55     # px — Sao this close → butterfly flees

# "Working inside an app" — when Sao is standing on an open window she may
# duck inside it to work for a while (instead of trekking to the house).
# She vanishes into the window and a small coloured marker shows where she
# went; she pops back out when done.
WORK_INSIDE_CHANCE   = 0.35   # chance per wander-change (while on a window) to go in
WORK_STAY_TICKS_MIN  = 2400   # ~40 s minimum inside
WORK_STAY_TICKS_MAX  = 7200   # ~2 min maximum inside

# ── Walk-into-taskbar-icon mechanic ───────────────────────────────────────
ICON_ENTER_CHANCE    = 0.62   # chance, once she's wandering the taskbar, to go into an icon
ICON_FADE_DIST       = 46     # px from the icon centre over which she fades in/out
ICON_SEEK_TIMEOUT    = 120    # frames (~2 s) to wait on the UIA query before giving up
ICON_WALK_SPEED      = 1.2    # px/tick while approaching / leaving the icon
ICON_POLL_TICKS      = 20     # frames between movement re-checks while she's inside
ICON_MOVE_POP        = 16     # px the icon must shift for Sao to get startled out
ICON_POP_VY          = -340.0 # upward kick (px/s) when she hops back out of an icon
ICON_POP_VX          = 55.0   # gentle sideways drift as she pops out
ICON_FADE_FRAMES     = 16     # frames to fade her back in as she pops out
ICON_COOLDOWN_TICKS  = 3600   # ~60 s lockout after leaving before she'll enter another app


def _get_work_area_physical() -> tuple[int, int, int, int]:
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left",   ctypes.c_long),
            ("top",    ctypes.c_long),
            ("right",  ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]
    rect = RECT()
    ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom


def scale_platforms(platforms: list[Platform], ratio: float) -> list[Platform]:
    return [
        Platform(
            hwnd=p.hwnd,
            x=int(p.x / ratio),
            y=int(p.y / ratio),
            w=int(p.w / ratio),
            h=int(p.h / ratio),
            title=p.title,
            solid=p.solid,            # preserve — child/bottom platforms must stay non-solid
            owner_hwnd=p.owner_hwnd,  # preserve owner linkage across scaling
        )
        for p in platforms
    ]


def cursor_distance_to_cat(cat: CatState, overlay) -> float:
    cursor = overlay.mapFromGlobal(QCursor.pos())
    cat_cx = cat.x + cat.width / 2
    cat_cy = cat.y + cat.height / 2
    return math.hypot(cursor.x() - cat_cx, cursor.y() - cat_cy)


def find_platform(hwnd: int, platforms: list[Platform]) -> Platform | None:
    for p in platforms:
        if p.hwnd == hwnd:
            return p
    return None


def _owner_of_on_hwnd(on_hwnd: int | None, platforms: list[Platform]) -> int:
    """
    Resolve a cat.on_hwnd (which stores a platform's synthetic hwnd) back to
    its owning top-level window hwnd. Falls back to abs(on_hwnd) if the
    platform is no longer in the list (e.g. just closed).
    """
    if on_hwnd is None or on_hwnd == 0:
        return 0
    p = find_platform(on_hwnd, platforms)
    if p is not None and p.owner_hwnd:
        return p.owner_hwnd
    return abs(on_hwnd)


def pick_jump_target(cat: CatState, platforms: list[Platform],
                     z_order: dict[int, int] | None = None) -> Platform | None:
    """
    Find the best nearby platform above the cat to jump to.

    The `platforms` list is already visibility-clipped by WindowScanner: every
    entry is a currently-visible segment of a window's top/bottom edge (or a
    child UI element). So we no longer need a z_order guard here — if a segment
    exists in the list, the user can see it and Sao is allowed to land there.
    The `z_order` parameter is kept for API stability.
    """
    cat_cx     = cat.x + cat.width / 2
    cat_bottom = cat.y + cat.height
    candidates = []
    for p in platforms:
        plat_cx = p.x + p.w / 2
        dx = abs(plat_cx - cat_cx)
        dy = cat_bottom - p.top  # positive = platform is above

        # Placed blocks are valid targets even when narrow (a single 22px block
        # would otherwise be filtered out by the min-width rule).
        if p.w < MIN_JUMP_PLATFORM_W and not blocks_data.is_block_hwnd(p.hwnd):
            continue
        if dx > JUMP_HORIZONTAL_RANGE:
            continue
        if dy < 10:
            continue
        if dy > JUMP_MAX_HEIGHT:
            continue

        # Don't bother jumping to another segment of the window Sao is already
        # on — she'd just step sideways within the same edge.
        if cat.on_hwnd is not None and p.owner_hwnd and \
                p.owner_hwnd == _owner_of_on_hwnd(cat.on_hwnd, platforms):
            continue

        score = -dy + (JUMP_HORIZONTAL_RANGE - dx) * 0.3
        # Strongly bias her toward jumping onto placed blocks (so they easily
        # beat window ledges) — they're meant to be fun to build on.
        if blocks_data.is_block_hwnd(p.hwnd):
            score += 400
        candidates.append((score, p))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def aim_jump(cat: CatState, target: Platform) -> CatState:
    """Jump toward target with just enough power to clear it, plus a random margin."""
    dy = (cat.y + cat.height) - target.top
    dy = max(dy, 1.0)

    min_power = math.sqrt(2 * GRAVITY * dy)
    if min_power < JUMP_MIN_POWER:
        return cat  # unchanged — caller checks for this

    overshoot    = random.uniform(1.08, 1.30)
    power        = min(min_power * overshoot, _phys.JUMP_POWER)
    travel_time  = (2 * power) / GRAVITY
    target_cx    = target.x + target.w / 2
    cat_cx       = cat.x + cat.width / 2
    vx           = max(-350.0, min(350.0, (target_cx - cat_cx) / travel_time))

    state = jump(cat, power=power * 0.9)       # 10% shorter vertical
    return replace(state, vx=vx * 0.5)         # 50% shorter horizontal


def _block_traverse(state, prev, bplats):
    """Smarter block traversal: when Sao walks into a placed block in her path,
    auto-step UP onto it if it's a low step (~1 block), or stop at it if it's
    too tall (placed blocks aren't general walls, so this only applies to them).
    Cheap — iterates the cached block platforms only while she's walking, with a
    quick x-proximity reject."""
    if not bplats or not state.grounded or abs(state.vx) < 0.3:
        return state
    STEP  = blocks_data.BLOCK_SIZE + 4   # auto-step up to ~one block tall
    feet  = state.y + state.height
    right = state.vx > 0
    cl, cr   = state.x, state.x + state.width
    pcl, pcr = prev.x, prev.x + state.width

    def _has_block_above(p):
        # A block sitting directly on top of p → p is part of a wall, no headroom.
        for q in bplats:
            if q is p:
                continue
            if abs((q.y + q.h) - p.top) < 2 and q.x < p.x + p.w and q.x + q.w > p.x:
                return True
        return False

    for p in bplats:
        if cr < p.x - 4 or cl > p.x + p.w + 4:
            continue                                  # not horizontally near
        if feet <= p.top + 1 or state.y >= p.y + p.h:
            continue                                  # not in her vertical path
        crossing = (right and pcr <= p.left and cr > p.left) or \
                   ((not right) and pcl >= p.right and cl < p.right)
        if not crossing:
            continue
        if feet - p.top <= STEP and not _has_block_above(p):
            return replace(state, y=p.top - state.height,
                           grounded=True, on_hwnd=p.hwnd)   # step up onto it
        # Too tall, or a wall with no headroom → stop against it.
        new_x = p.left - state.width if right else p.right
        return replace(state, x=float(new_x), vx=0.0)
    return state


def _hex_to_rgb(h):
    """'#eb5a5a' → (235, 90, 90), or None if unparseable."""
    try:
        h = (h or '').lstrip('#')
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except (ValueError, TypeError):
        pass
    return None


def _snap_drop_platform(state, platforms):
    """When the user releases a drag, find a window ledge to drop Sao onto even
    if her feet aren't *exactly* on it — a forgiving catch so she doesn't fall
    straight through a window she was clearly dropped on.  Returns the Platform
    whose top is nearest her feet (within tolerance) and under her centre, else
    None."""
    SNAP_UP   = 34.0   # px her feet may be ABOVE a ledge and still catch
    SNAP_DOWN = 16.0   # px her feet may be slightly BELOW the ledge and still catch
    cx     = state.x + state.width / 2
    bottom = state.y + state.height
    best   = None
    best_d = 1e9
    for p in platforms:
        if cx <= p.left or cx >= p.right:
            continue
        if (bottom - SNAP_UP) <= p.top <= (bottom + SNAP_DOWN):
            d = abs(p.top - bottom)
            if d < best_d:
                best_d = d
                best   = p
    return best


def main():
    parser = argparse.ArgumentParser(description="Desktop Cat")
    parser.add_argument("--debug", action="store_true", help="Show window platform outlines")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ── App identity + icon ───────────────────────────────────────────
    # Without this, Windows shows the python.exe logo on our windows and
    # in the taskbar.  Set a stable AppUserModelID so the taskbar treats
    # us as our own app (and uses our icon), then load app_icon.ico and
    # apply it app-wide.  Every QWidget window inherits app.windowIcon()
    # unless it sets its own, so this covers the hub, pill, stickies, etc.
    app.setApplicationName('Desktop Cat')
    app.setApplicationDisplayName('Sao')
    # A custom AppUserModelID is only needed when running from SOURCE — there
    # the host process is python.exe, so without this the taskbar shows the
    # Python logo.  In the packaged .exe the process IS Sao.exe with our paw
    # icon embedded, and setting a custom ID with no registered shortcut makes
    # Windows fall back to a default icon — so skip it when frozen.
    if not getattr(sys, 'frozen', False):
        # NOTE: do NOT `import ctypes` here — a local import would make `ctypes`
        # a local of main(), and since this branch is skipped in the frozen .exe
        # the name would be unbound for the rest of main() (incl. the game
        # loop's cursor/icon ctypes calls).  Use the module-level import.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'Whishy.DesktopCat.Sao')
        except Exception:
            pass
    try:
        from PyQt6.QtGui import QIcon
        # In a PyInstaller build the bundled data lives under sys._MEIPASS
        # (the _internal folder), NOT next to the entry script — so resolve
        # against that when frozen, else against this file's dir.
        _icon_base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
        _icon_path = os.path.join(_icon_base, 'desktop_cat', 'app_icon.ico')
        if os.path.exists(_icon_path):
            _app_icon = QIcon(_icon_path)
            app.setWindowIcon(_app_icon)
    except Exception:
        pass

    dpi_ratio = app.primaryScreen().devicePixelRatio()

    _, _, phys_w, phys_floor = _get_work_area_physical()
    screen_w     = int(phys_w    / dpi_ratio)
    screen_floor = int(phys_floor / dpi_ratio)

    screen_rect   = app.primaryScreen().geometry()
    screen_h      = screen_rect.height()           # logical — actual screen bottom
    phys_screen_w = int(screen_rect.width()  * dpi_ratio)
    phys_screen_h = int(screen_rect.height() * dpi_ratio)

    overlay = CatOverlay(debug=args.debug)
    overlay.setGeometry(app.primaryScreen().geometry())
    overlay.show()

    # ── DPI diagnostic ────────────────────────────────────────────────────
    # Writes the scaling/geometry values to ~/sao_dpi_debug.log so a misbehaving
    # machine (e.g. wrong size / everything in a corner) can be diagnosed without
    # reproducing it here.  Harmless on a healthy setup.
    try:
        import platform as _plat
        _u32 = ctypes.windll.user32
        _L = [f"Sao DPI debug — {_plat.platform()}  frozen={getattr(sys,'frozen',False)}"]
        try:
            _ctx = _u32.GetThreadDpiAwarenessContext()
            _L.append(f"awareness={_u32.GetAwarenessFromDpiAwarenessContext(_ctx)} "
                      f"(0=unaware 1=system 2=permon 3=permon_v2)")
        except Exception as _e:
            _L.append(f"awareness query failed: {_e}")
        try:
            _L.append(f"GetDpiForSystem={_u32.GetDpiForSystem()}")
        except Exception:
            pass
        _L.append(f"SM_CXSCREEN/CYSCREEN = {_u32.GetSystemMetrics(0)} x {_u32.GetSystemMetrics(1)}")
        _L.append(f"SPI_GETWORKAREA raw (l,t,r,b) = {_get_work_area_physical()}")
        _L.append(f"computed: dpi_ratio={dpi_ratio} screen_w={screen_w} "
                  f"screen_floor={screen_floor} screen_h={screen_h} "
                  f"phys_screen={phys_screen_w}x{phys_screen_h}")
        _ps = app.primaryScreen()
        _L.append(f"primaryScreen name={_ps.name()} geom={_ps.geometry().getRect()} "
                  f"avail={_ps.availableGeometry().getRect()} dpr={_ps.devicePixelRatio()} "
                  f"ldpi={_ps.logicalDotsPerInch()} pdpi={_ps.physicalDotsPerInch()}")
        for _i, _s in enumerate(app.screens()):
            _L.append(f"screen[{_i}] name={_s.name()} geom={_s.geometry().getRect()} "
                      f"dpr={_s.devicePixelRatio()} ldpi={_s.logicalDotsPerInch()}")
        _L.append(f"overlay geom={overlay.geometry().getRect()} "
                  f"frame={overlay.frameGeometry().getRect()} dpr={overlay.devicePixelRatioF()}")
        try:
            _L.append(f"rounding_policy={app.highDpiScaleFactorRoundingPolicy()}")
        except Exception:
            pass
        with open(os.path.join(os.path.expanduser('~'), 'sao_dpi_debug.log'),
                  'w', encoding='utf-8') as _df:
            _df.write("\n".join(str(_x) for _x in _L) + "\n")
    except Exception:
        pass
    # Expose the overlay to the hub bridge (e.g. hover-a-todo → highlight flower).
    try:
        from desktop_cat import pin_registry as _pin_reg
        _pin_reg.set_overlay(overlay)
    except Exception:
        pass

    # Bump overlay above the taskbar — both are HWND_TOPMOST, but creation order
    # determines z; calling SetWindowPos after show() wins the race.
    win32gui.SetWindowPos(
        int(overlay.winId()),
        win32con.HWND_TOPMOST,
        0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
    )

    bus = EventBus()
    scanner = WindowScanner(bus=bus, own_hwnd=int(overlay.winId()))
    scan_sched = ScanScheduler()   # event-driven: skip rescans on a static desktop
    overlay._bus = bus   # give overlay access to bus for right-click menu

    # SAO Hub — old retro launcher (kept but no longer opened by house click)
    hub_window = None   # legacy old-hub handle — always None now (kept so the
                        # dead `if hub_window is not None` guards stay valid)

    # SAO Library — new React-based hub (opens when house is clicked)
    lib_window: LibraryHubWindow | None = None

    # Persist the hub window's last position so it reopens where the user
    # left it, across app restarts.
    _HUB_POS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'desktop_cat', 'hub_pos.json')

    def _load_hub_pos():
        try:
            with open(_HUB_POS_PATH, encoding='utf-8') as _f:
                d = json.load(_f)
            return (int(d['x']), int(d['y']))
        except Exception:
            return None

    def _save_hub_pos(pos) -> None:
        if not pos:
            return
        try:
            with open(_HUB_POS_PATH, 'w', encoding='utf-8') as _f:
                json.dump({'x': int(pos[0]), 'y': int(pos[1])}, _f)
        except Exception:
            pass

    hub_last_pos = _load_hub_pos()

    def _on_hut_clicked(_) -> None:
        nonlocal lib_window, hub_last_pos
        if lib_window is not None and lib_window.isVisible():
            hub_last_pos = (lib_window.x(), lib_window.y())
            _save_hub_pos(hub_last_pos)
            lib_window.close_animated()
            # Closing the hub used to leave the user staring at an empty
            # screen wondering where the pill went (it sits as a 3px nib
            # when unpinned).  Peek it out for a moment so it's obviously
            # still there.
            try:
                if _island_window is not None:
                    _island_window.peek()
            except Exception:
                pass
        else:
            lib_window = LibraryHubWindow()
            win_h = lib_window.height()
            if hub_last_pos is not None:
                spawn_x, spawn_y = hub_last_pos
            else:
                spawn_x = 130
                spawn_y = max(20, screen_h - win_h - 58)
            lib_window.show_animated(spawn_x, spawn_y)

    bus.subscribe('HUT_CLICKED', _on_hut_clicked)

    # ── Garden ────────────────────────────────────────────────────────────────
    _GARDEN_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'desktop_cat', 'garden.json',
    )

    def _load_garden_plants() -> list[Plant] | None:
        """Return saved Plant list or None if no valid save exists."""
        try:
            with open(_GARDEN_PATH) as _f:
                raw = json.load(_f)
            plants = []
            for d in raw:
                plants.append(Plant(
                    x=int(d['x']),
                    stage=int(d.get('stage', 0)),
                    tend_count=int(d.get('tend_count', 0)),
                    variant=int(d.get('variant', 0)),
                    has_bee=bool(d.get('has_bee', False)),
                    plant_type=int(d.get('plant_type', 0)),
                    harvest_timer=int(d.get('harvest_timer', 0)),
                    fruitless=bool(d.get('fruitless', False)),
                    fruitless_timer=int(d.get('fruitless_timer', 0)),
                    bug_kind=str(d.get('bug_kind', '') or ''),
                ))
            return plants if plants else []
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _save_garden() -> None:
        try:
            data = [
                {
                    'x':             p.x,
                    'stage':         p.stage,
                    'tend_count':    p.tend_count,
                    'variant':       p.variant,
                    'has_bee':       p.has_bee,
                    'plant_type':      p.plant_type,
                    'harvest_timer':   p.harvest_timer,
                    'fruitless':       p.fruitless,
                    'fruitless_timer': p.fruitless_timer,
                    'bug_kind':        p.bug_kind,
                }
                for p in garden.plants
            ]
            with open(_GARDEN_PATH, 'w') as _f:
                json.dump(data, _f)
        except OSError:
            pass

    _margin   = 80
    # Random garden plants are out as of the 2026-05-28 trim.  The taskbar
    # should ONLY show task_flowers (one per todo from the Library Hub).
    # Garden stays in the code (Sao still has tending animations etc.) but
    # is always empty at startup — old saves are ignored, fresh runs don't
    # auto-spawn the 5 starter flowers any more.
    garden = Garden(plants=[])
    _is_new_garden: bool = False   # skip the starter-flower auto-spawn block
    overlay.set_garden(garden, screen_floor)

    # ── Pinned sticky notes ───────────────────────────────────────────────────
    # Each "pinned" sticky in the Library Hub spawns a floating frameless
    # always-on-top window managed here.  Source of truth is stickies.json
    # (read+written by both sides).  We mtime-poll the file in on_tick and
    # reconcile: spawn missing windows, close unpinned ones, push external
    # edits into open windows.
    from desktop_cat import stickies_data as _stickies_data
    from desktop_cat.sticky_window import StickyWindow as _StickyWindow

    _sticky_windows: dict[str, '_StickyWindow'] = {}
    _stickies_mtime: list[float] = [_stickies_data.mtime()]

    def _notify_stickies_updated() -> None:
        """Tell the hub (if open) that stickies.json changed so it can re-read."""
        try:
            if lib_window is not None and hasattr(lib_window, '_bridge'):
                lib_window._bridge.stickiesUpdated.emit()
        except Exception:
            pass

    def _reconcile_sticky_windows() -> None:
        fresh = _stickies_data.load()
        fresh_pinned = {s['id']: s for s in fresh if s.get('pinned') and s.get('id')}
        # Close windows whose sticky was unpinned or deleted
        for sid in list(_sticky_windows.keys()):
            if sid not in fresh_pinned:
                w = _sticky_windows.pop(sid)
                try: w.close(); w.deleteLater()
                except Exception: pass
        # Spawn or update windows for each pinned sticky
        for sid, s in fresh_pinned.items():
            if sid in _sticky_windows:
                _sticky_windows[sid].apply_external_update(s)
            else:
                w = _StickyWindow(s)
                w.persisted.connect(_notify_stickies_updated)
                w.show()
                _sticky_windows[sid] = w

    # Spawn windows for whatever's pinned at startup.
    _reconcile_sticky_windows()

    # ── Dynamic island ────────────────────────────────────────────────────────
    # The floating pill (music / next task / due-today / focus timer).
    # Spawned independently of the hub so it survives hub close.  Manages
    # its own polling + settings reload from desktop_cat/island.json.
    try:
        from desktop_cat import dynamic_island as _dynamic_island
        _island_window = _dynamic_island.create_and_show()
        # Clicking a task/due lane on the island opens (and focuses)
        # the Library Hub — distinct from `_on_hut_clicked` which TOGGLES.
        # Toggle behaviour would be confusing here: user clicks a task
        # expecting to see it, hub disappears.
        def _open_hub_from_island() -> None:
            nonlocal lib_window, hub_last_pos
            if lib_window is not None and lib_window.isVisible():
                lib_window.raise_()
                lib_window.activateWindow()
                return
            lib_window = LibraryHubWindow()
            win_h = lib_window.height()
            if hub_last_pos is not None:
                spawn_x, spawn_y = hub_last_pos
            else:
                spawn_x = 130
                spawn_y = max(20, screen_h - win_h - 58)
            lib_window.show_animated(spawn_x, spawn_y)
        # create_and_show() always returns a DynamicIsland (never None).
        # The window starts hidden if enabled=False; the 800ms prefs-check
        # timer inside it will call show() when the user flips the toggle.
        _island_window.open_hub_requested.connect(_open_hub_from_island)
        # Hide the whole overlay (Sao + grass + rocks + flowers) while a
        # fullscreen app/video is in front — same trigger the pill uses.
        def _on_fullscreen_changed(fs: bool) -> None:
            try:
                overlay.hide() if fs else overlay.show()
            except Exception:
                pass
        _island_window.fullscreen_changed.connect(_on_fullscreen_changed)
    except Exception as _isle_exc:
        print(f'[dynamic_island] failed to spawn: {_isle_exc}')
        _island_window = None

    # (Potato blocks removed.)

    # ── Inventory ─────────────────────────────────────────────────────────────
    inventory: dict = inv_mod.load()

    def _get_planted_counts() -> dict:
        counts = {'flower': 0, 'macron': 0}
        type_map = {PLANT_FLOWER: 'flower', PLANT_MACRON: 'macron'}
        for _p in garden.plants:
            k = type_map.get(_p.plant_type)
            if k:
                counts[k] += 1
        return counts

    # ── Task Flowers ──────────────────────────────────────────────────────────
    _TASK_FLOWERS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'desktop_cat', 'task_flowers.json',
    )
    _BOARD_DATA_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'desktop_cat', 'message_board.json',
    )

    def _load_task_flowers() -> list:
        try:
            with open(_TASK_FLOWERS_PATH) as _f:
                raw = json.load(_f)
            return [TaskFlower(**d) for d in raw]
        except (OSError, ValueError, TypeError):
            return []

    def _save_task_flowers() -> None:
        try:
            with open(_TASK_FLOWERS_PATH, 'w') as _f:
                json.dump([asdict(tf) for tf in task_flowers], _f)
        except OSError:
            pass

    def _load_todos_from_file() -> list:
        """Fallback: read todos directly from message_board.json when Board isn't open."""
        try:
            with open(_BOARD_DATA_PATH) as _f:
                d = json.load(_f)
            return d.get('todos', [])
        except (OSError, ValueError):
            return []

    task_flowers: list[TaskFlower] = _load_task_flowers()
    falling_seeds: list[FallingSeed] = []

    SEED_GRAVITY = 900.0   # px/s² — fast & snappy fall (was 260, felt floaty)

    overlay.set_task_flowers(task_flowers)
    overlay.set_falling_seeds(falling_seeds)
    # Dragging a flower in the overlay mutates its .x in place; persist on drop.
    overlay._on_flower_moved = _save_task_flowers

    def _on_seed_plant(text: str, due: str,
                       screen_x: int | None = None,
                       screen_y: int | None = None) -> None:
        """Called from GardenWindow when user clicks 'plant' or drags a seed.

        - `screen_x` / `screen_y` are global cursor coordinates from a drag-drop.
        - When omitted (plant button click), x is randomised and y is up high.
        - Refuses to plant if the same task is already growing OR already
          mid-air, so quick double-clicks / double-drags can't duplicate.
        """
        # Dedupe: same task already planted or falling → ignore.
        if any(tf.task_text == text for tf in task_flowers):
            return
        if any(fs.task_text == text for fs in falling_seeds):
            return

        if screen_x is not None:
            sx = float(max(_margin, min(screen_x, screen_w - _margin)))
        else:
            sx = float(random.randint(screen_w // 5, 4 * screen_w // 5))
        if screen_y is not None:
            # Drop from where the user released — clamp into a sane range
            # so it can't start below the floor or above the top of screen.
            sy = float(max(0, min(screen_y, screen_floor - 4)))
        else:
            sy = float(max(0, screen_h - 300))
        falling_seeds.append(FallingSeed(x=sx, y=sy, vy=0.0,
                                          task_text=text, due_date=due))

    def _on_crop_seed_plant(seed_type: str,
                            screen_x: int | None = None,
                            screen_y: int | None = None) -> None:
        """Called from ShopWindow when user drags a crop seed onto the taskbar.

        seed_type: 'flower' | 'macron'
        Inventory deduction already happened in ShopWindow before this is called.
        """
        plant_type_map = {
            'flower': PLANT_FLOWER,
            'macron': PLANT_MACRON,
        }
        ptype = plant_type_map.get(seed_type, PLANT_FLOWER)

        # Cap check (planted count)
        cap_map = {
            PLANT_FLOWER: FLOWER_PLANT_CAP,
            PLANT_MACRON: MACRON_PLANT_CAP,
        }
        _crop_tag = f'__crop__{seed_type}'
        planted = (
            sum(1 for _p in garden.plants if _p.plant_type == ptype) +
            sum(1 for _fs in falling_seeds if _fs.task_text == _crop_tag)
        )
        if planted >= cap_map.get(ptype, 99):
            # Already at cap; refund the seed
            inv_mod.add_seed(inventory, seed_type)
            inv_mod.save(inventory)
            return

        if screen_x is not None:
            sx = float(max(_margin, min(screen_x, screen_w - _margin)))
        else:
            sx = float(random.randint(screen_w // 5, 4 * screen_w // 5))
        if screen_y is not None:
            sy = float(max(0, min(screen_y, screen_floor - 4)))
        else:
            sy = float(max(0, screen_h - 300))

        # Use a FallingSeed to animate falling; when it lands, create a real Plant
        falling_seeds.append(FallingSeed(x=sx, y=sy, vy=0.0,
                                          task_text=f'__crop__{seed_type}',
                                          due_date=''))

    def _debug_give_resources() -> None:
        """Debug: add +10 of every currency and save."""
        nonlocal inventory
        for key in ('coins', 'macrons'):
            inventory[key] = inventory.get(key, 0) + 10
        inv_mod.save(inventory)

    def _on_username_change(new_name: str) -> None:
        _prof = user_profile.load()
        _prof['user_name'] = new_name
        user_profile.save(_prof)

    def _mark_todo_planted(task_text: str) -> None:
        """Set the matching todo's 'planted' flag to True in both live + JSON.

        Once a todo has been planted into a flower, it must never reappear as a
        plantable seed in the garden window — even after the flower is removed
        (the seed shouldn't bounce back).  The flag persists across deletes.
        """
        if (hub_window is not None
                and hub_window._message_board is not None):
            board = hub_window._message_board
            todos = board._data.get('todos', [])
            changed = False
            for t in todos:
                if t.get('text') == task_text and not t.get('planted'):
                    t['planted'] = True
                    changed = True
            if changed:
                board._save()
                board.update()
            return
        try:
            with open(_BOARD_DATA_PATH) as _f:
                _bd = json.load(_f)
            _todos = _bd.get('todos', [])
            _changed = False
            for t in _todos:
                if t.get('text') == task_text and not t.get('planted'):
                    t['planted'] = True
                    _changed = True
            if _changed:
                with open(_BOARD_DATA_PATH, 'w') as _f:
                    json.dump(_bd, _f)
        except (OSError, ValueError):
            pass

    def _remove_todo_from_board(task_text: str) -> None:
        """Remove the todo matching task_text from both the live board and saved JSON.

        Called whenever a task flower is deleted so the two data sources stay in
        sync.  Safe to call even if no matching todo exists (no-op).
        """
        # ── Live board (if open) ──────────────────────────────────────────────
        if (hub_window is not None
                and hub_window._message_board is not None):
            board = hub_window._message_board
            todos = board._data.get('todos', [])
            new_todos = [t for t in todos if t.get('text') != task_text]
            if len(new_todos) != len(todos):
                board._data['todos'] = new_todos
                board._save()
                board.update()
            return   # board's _save() already wrote the file

        # ── Board not open — patch the JSON file directly ─────────────────────
        try:
            with open(_BOARD_DATA_PATH) as _f:
                _bd = json.load(_f)
            _todos = _bd.get('todos', [])
            _new   = [t for t in _todos if t.get('text') != task_text]
            if len(_new) != len(_todos):
                _bd['todos'] = _new
                with open(_BOARD_DATA_PATH, 'w') as _f:
                    json.dump(_bd, _f)
        except (OSError, ValueError):
            pass

    def _on_task_flower_delete(task_text: str) -> None:
        """Queue a task flower for Sao to walk over and interact with before removing."""
        nonlocal task_flowers, flower_to_remove, flower_target_x, taskbar_state, target_plant
        # Remove the matching todo from the assignments board immediately — the
        # flower itself is removed after Sao finishes his interaction animation.
        _remove_todo_from_board(task_text)
        match = next((tf for tf in task_flowers if tf.task_text == task_text), None)
        if (match is not None
                and taskbar_state in ('normal', 'approaching_plant', 'interacting_plant')):
            # Interrupt any plant tending and send Sao to the flower
            flower_to_remove = task_text
            flower_target_x  = match.x
            target_plant     = None
            overlay.set_active_plant(None)
            taskbar_state    = 'approaching_flower'
        else:
            # Cat is busy or flower not found — remove immediately
            task_flowers = [tf for tf in task_flowers if tf.task_text != task_text]
            overlay.set_task_flowers(task_flowers)
            _save_task_flowers()

    def _on_board_data_changed(data: dict) -> None:
        """Sync task flower state when todos change in the Board window.

        Handles two cases:
        1. A todo's 'done' flag changed → mirror that on the matching TaskFlower.
        2. A todo was deleted → remove the matching TaskFlower so the taskbar
           flower disappears when the user deletes the assignment.
        """
        nonlocal task_flowers
        todos     = data.get('todos', [])
        todo_texts = {t.get('text') for t in todos}
        changed   = False

        # ── Remove flowers whose todos were deleted ───────────────────────────
        new_flowers = [tf for tf in task_flowers if tf.task_text in todo_texts]
        if len(new_flowers) != len(task_flowers):
            task_flowers = new_flowers
            overlay.set_task_flowers(task_flowers)
            changed = True

        # ── Sync 'done' state ────────────────────────────────────────────────
        for tf in task_flowers:
            for t in todos:
                if t.get('text') == tf.task_text:
                    new_done = bool(t.get('done'))
                    if tf.done != new_done:
                        tf.done  = new_done
                        changed  = True
                    break

        if changed:
            _save_task_flowers()

    # ── Library Hub todo reconciler ────────────────────────────────────────
    # The React Hub writes its combined todo list to library_todos.json
    # (via SaoBridge.saveLibraryTodos).  We diff that against our
    # task_flowers list by todo_id:
    #   • new todo (no matching flower) and not done → enqueue plant
    #   • existing flower whose todo flipped done → mark wilted
    #   • existing flower whose todo flipped back to undone → un-wilt
    #   • existing flower whose todo vanished from the list → remove
    # Polled in on_tick via mtime check so we don't hammer the disk.

    _LIBRARY_TODOS_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'library_todos.json',
    )

    def _reconcile_library_todos() -> None:
        nonlocal task_flowers
        try:
            with open(_LIBRARY_TODOS_PATH, 'r', encoding='utf-8') as f:
                fresh = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(fresh, list):
            return
        fresh_by_id = {t['id']: t for t in fresh
                       if isinstance(t, dict) and t.get('id')}

        changed = False
        existing_by_id = {tf.todo_id: tf for tf in task_flowers if tf.todo_id}

        # 1. New todos → queue for planting.
        # We skip:
        #   • done ones (no point planting an already-wilted flower)
        #   • already-past-due ones (Canvas keeps old assignments in the
        #     feed even when the user finished them; planting + immediately
        #     marking overdue would just be noise)
        from datetime import datetime as _dt
        _today_iso = _dt.now().date().isoformat()
        for tid, t in fresh_by_id.items():
            if tid in existing_by_id:
                continue
            if t.get('done'):
                continue
            _due = (t.get('due') or '').strip()
            if _due and _due < _today_iso:
                continue   # past-due at import time → don't plant
            # Skip if already queued (avoid duplicates if user spams adds).
            if any(item.get('todo_id') == tid for item in _plant_queue):
                continue
            _plant_queue.append({
                'todo_id':   tid,
                'task_text': t.get('name') or 'untitled',
                'due_date':  _due,
                'priority':  t.get('priority') or 'normal',
                'flower':    t.get('flower'),   # 0..4 = chosen variant; -1/None = random
            })

        # 2. Sync done state + drop flowers whose todos vanished
        from desktop_cat.garden import POP_ANIM_TICKS
        survivors = []
        said_reaction = False   # one Sao reaction per pass (no bulk-spam)
        for tf in task_flowers:
            tid = tf.todo_id
            if tid and tid in fresh_by_id:
                t = fresh_by_id[tid]
                _new_pri = t.get('priority') or 'normal'
                if getattr(tf, 'priority', 'normal') != _new_pri:
                    tf.priority = _new_pri
                    changed = True
                new_done = bool(t.get('done'))
                if tf.done != new_done:
                    tf.done = new_done
                    if new_done and tf.pop_anim_ticks == 0:
                        # Kick off the pop-out animation.  Renderer
                        # scales+fades during this; main.py drops the
                        # flower from the list when it hits 0.
                        tf.pop_anim_ticks = POP_ANIM_TICKS
                        # Sao cheers you on with a brief bubble (once per pass).
                        if not said_reaction:
                            said_reaction = True
                            try:
                                overlay.say(random.choice(_SAO_DONE_LINES))
                            except Exception:
                                pass
                    changed = True
                survivors.append(tf)
            elif tid and tid not in fresh_by_id:
                # Linked todo removed → also pop with an animation so the
                # flower doesn't just snap out of existence.
                if tf.pop_anim_ticks == 0:
                    tf.done           = True
                    tf.pop_anim_ticks = POP_ANIM_TICKS
                survivors.append(tf)
                changed = True
            else:
                # Legacy flower with no todo_id — leave alone.
                survivors.append(tf)
        if len(survivors) != len(task_flowers):
            task_flowers = survivors
            overlay.set_task_flowers(task_flowers)

        if changed:
            _save_task_flowers()

    def _pick_plant_x(screen_w: int, screen_floor: int) -> float:
        """Pick a random x within the floor for a new flower.  Tries to
        avoid stacking right on top of an existing flower / rock; if
        every random pick is too close, falls back to the last try."""
        margin = 80
        chosen = float(screen_w // 2)
        for _ in range(12):
            x = random.uniform(margin, max(margin + 1, screen_w - margin))
            ok = True
            for tf in task_flowers:
                if abs(tf.x - x) < 40:
                    ok = False; break
            if not ok:
                continue
            for _lp in (garden.plants if garden else []):
                if abs(_lp.x - x) < 40:
                    ok = False; break
            if not ok:
                continue
            for _lr in rocks:
                if abs(_lr.x - x) < 36:
                    ok = False; break
            if ok:
                return x
            chosen = x
        return chosen

    def _get_todos_for_garden() -> list:
        """Live list of todos — from open Board window, else from file."""
        if (hub_window is not None
                and hub_window._message_board is not None
                and hub_window._message_board.isVisible()):
            return hub_window._message_board._data.get('todos', [])
        return _load_todos_from_file()

    # (House removed — Sao now rests by ducking into open windows to "work".)

    # Critters
    bugs: list[Bug]              = []
    butterflies: list[Butterfly] = []
    effects: list[CollectEffect] = []
    bug_for_plant: dict[int, Bug] = {}   # plant-index → Bug
    bug_sync_timer: int          = 0
    butterfly_timer: int         = random.randint(BUTTERFLY_SPAWN_MIN, BUTTERFLY_SPAWN_MAX)
    butterfly_chase_target: Butterfly | None = None
    butterfly_chase_ticks: int   = 0
    butterfly_catchable: bool    = False   # True = Sao can actually reach it (1%)
    butterfly_hop_count: int     = 0       # hops fired during current chase (max 3)
    butterfly_target_speed: float = 0.0   # final speed the butterfly ramps up to
    dust_particles: list         = []      # skid dust puffs
    # ABug3 cursor mechanic — small pastel FriendBugs flock toward still cursor
    cursor_last_pos: tuple[int, int] = (-1, -1)
    cursor_still_ticks: int      = 0
    # Jitter-tolerant stillness for the punch (a held mouse wobbles a pixel or
    # two, which would never satisfy the exact-pixel counter above).
    punch_still_ref_x: int       = -999
    punch_still_ref_y: int       = -999
    punch_still_ticks: int       = 0
    friend_bugs: list[FriendBug] = []
    friend_bug_spawn_timer: int  = 0          # countdown to next bug arrival
    # Cursor-landing rarity (user: "make them a lot more rare to land on
    # your cursor", but never zero).  Eligible only after a long stillness,
    # then a tiny per-tick chance, then a long cooldown before it can
    # happen again.  Tuned so that even with the cursor parked perfectly
    # still for a full hour you'd see only ~3-4 landings; in real use the
    # cursor moves (resetting the stillness counter) so it's rarer still —
    # a genuinely special, occasional moment rather than a frequent event.
    CURSOR_STILL_TRIGGER         = 90 * 60    # 90 s of stillness before eligible
    FRIEND_BUG_CURSOR_CHANCE     = 1.0 / 1800 # per-tick fire chance (~30s avg once eligible)
    FRIEND_BUG_CURSOR_COOLDOWN   = 600 * 60   # 10 min lockout after a landing
    friend_bug_cursor_cooldown: int = 0
    FRIEND_BUG_MAX               = 10
    FRIEND_BUG_INTERVAL_MIN      = 10 * 60    # 10s
    FRIEND_BUG_INTERVAL_MAX      = 25 * 60    # 25s
    # ABug1 — lazy ground critters.  A ladybug is a RARE, occasional visitor:
    # even with an abug1 slot equipped she should not be a permanent fixture.
    # She waddles in, hangs around for a short visit, then leaves — with a
    # long lockout before the next appearance so spotting her feels special.
    lazy_bugs: list[LazyBug]     = []
    LAZY_BUG_EDGE_MARGIN         = 120        # bounce before hitting screen edge
    LADYBUG_SPAWN_CHANCE         = 1.0 / 800  # per-tick fire chance (~13s avg once eligible)
    LADYBUG_VISIT_MIN            = 30 * 60    # 30 s minimum visit
    LADYBUG_VISIT_MAX            = 70 * 60    # 70 s maximum visit
    LADYBUG_COOLDOWN_MIN         = 2 * 60 * 60   # 2 min minimum lockout
    LADYBUG_COOLDOWN_MAX         = 5 * 60 * 60   # 5 min maximum lockout
    ladybug_cooldown: int        = 8 * 60 * 60   # start with a delay so she's not instant
    ladybug_visit_ticks: int     = 0
    ladybug_leaving: bool        = False
    # Visibility toggles driven by hub Settings → world_settings.json.
    cat_hidden: bool             = False   # hide Sao herself
    creatures_hidden: bool       = False   # hide butterflies / ladybugs / friend-bugs
    # Snail — a rare, slow ambient critter that crawls across the floor and
    # tucks under a big rock.  Behaves like the ladybug (edge-spawn, cooldown).
    snails: list[Snail]          = []
    # TEMP (testing): spawn constantly so the snail is easy to verify.  Revert
    # to the rare values in the comments once confirmed working.
    SNAIL_SPAWN_CHANCE           = 1.0           # rare: 1.0 / 1200
    SNAIL_COOLDOWN_MIN           = 3 * 60        # rare: 4 * 60 * 60  (4 min)
    SNAIL_COOLDOWN_MAX           = 6 * 60        # rare: 9 * 60 * 60  (9 min)
    snail_cooldown: int          = 0             # rare: 3 * 60 * 60
    overlay.set_critters(bugs, butterflies, [], effects)
    overlay.set_friend_bugs(friend_bugs)
    overlay.set_lazy_bugs(lazy_bugs)
    overlay.set_snails(snails)
    overlay.set_dust(dust_particles)

    # Shrubs — grass tufts biased toward screen edges (avoid middle third)
    # Only placed where the renderer's deterministic grass patches land so they
    # don't appear to float over bare taskbar sections.
    def _shrub_on_grass(x: int) -> bool:
        """Replicate the renderer's grass-patch formula for a given x position."""
        _GCELL  = 4
        _PATCH_W = 88
        _ANCHOR_R = 70
        gw = screen_w
        pc = max(1, (gw + _PATCH_W - 1) // _PATCH_W)
        pi = min(pc - 1, x // _PATCH_W)
        patch_cx = pi * _PATCH_W + _PATCH_W // 2
        # Near a plant → always grass in renderer
        for _ap in garden.plants:
            if abs(patch_cx - int(_ap.x)) < _ANCHOR_R:
                return True
        if not ((pi * 37 + 11) % 5 < 2):
            return False
        # Renderer also cuts 4 deterministic extra gaps
        _zone_w = max(1, gw // 4)
        for _gi in range(4):
            _zs = _gi * _zone_w
            _ze = (_gi + 1) * _zone_w
            _gh  = (_gi * 73856093 + 19349663) & 0xFFFF
            _gapw = (5 + ((_gi * 91234567 + 7654321) & 0xFF) % 8) * _GCELL
            _ms  = max(_zs, _ze - _gapw)
            _gs  = _zs + (_gh * max(1, _ms - _zs)) // 0x10000
            if _gs <= x < _gs + _gapw:
                return False
        return True

    # ── Shrubs + Rocks ───────────────────────────────────────────────
    # First-time launch: generate randomly in left/right thirds.  After
    # that: re-use the saved positions from decor.json so the desktop
    # scene stays consistent across launches.  Only `y` is reapplied at
    # load time so the layout adapts to taskbar height changes.
    from desktop_cat import decor_data
    _saved_decor = decor_data.load()
    _mid_lo = screen_w // 3
    _mid_hi = 2 * screen_w // 3

    shrubs: list[Shrub] = []
    rocks:  list[Rock]  = []
    if _saved_decor is not None:
        for s in _saved_decor['shrubs']:
            shrubs.append(Shrub(
                x=float(max(18, min(screen_w - 18, s['x']))),
                y=float(screen_floor),
                variant=s['variant'],
                wind_frame=0,
                wind_timer=random.randint(30, 160),
                bush_style=s['bush_style'],
            ))
        for r in _saved_decor['rocks']:
            rocks.append(make_rock(
                float(max(20, min(screen_w - 20, r['x']))),
                float(screen_floor),
                variant=r['variant'],
            ))
    else:
        # Fresh generation — random layout, then save so subsequent runs reuse it.
        _n_shrubs       = random.randint(11, 15)   # a bit more grass than before
        _shrub_min_gap  = 28
        _shrub_attempts = 0
        while len(shrubs) < _n_shrubs and _shrub_attempts < 3000:
            _shrub_attempts += 1
            r = random.random()
            if r < 0.50:            # left third
                sx = random.randint(18, _mid_lo - 10)
            else:                   # right third
                sx = random.randint(_mid_hi + 10, screen_w - 18)
            # Occasionally cluster near an existing plant (±30 px offset)
            if random.random() < 0.35 and garden.plants:
                sx = random.choice([p.x for p in garden.plants]) + random.randint(-30, 30)
                sx = max(18, min(screen_w - 18, sx))
            if not _shrub_on_grass(sx):
                continue
            if all(abs(sx - s.x) >= _shrub_min_gap for s in shrubs):
                shrubs.append(make_shrub(float(sx), float(screen_floor)))

        _n_rocks       = random.randint(3, 5)
        _rock_min_gap  = 50
        _rock_outer    = screen_w // 6
        _rock_attempts = 0
        while len(rocks) < _n_rocks and _rock_attempts < 3000:
            _rock_attempts += 1
            if random.random() < 0.50:   # left third
                rx = random.randint(20, _mid_lo - 15)
            else:                         # right third
                rx = random.randint(_mid_hi + 15, screen_w - 20)
            _variant = 1 if (rx < _rock_outer or rx > screen_w - _rock_outer) else 0
            if (all(abs(rx - r.x) >= _rock_min_gap for r in rocks) and
                    all(abs(rx - s.x) >= 20 for s in shrubs)):
                rocks.append(make_rock(float(rx), float(screen_floor), variant=_variant))
        # Save so the next launch reuses the same scene
        decor_data.save(rocks, shrubs)

    overlay.set_shrubs(shrubs)
    overlay.set_rocks(rocks)

    # ── Placeable blocks (2D-Minecraft) ───────────────────────────────────
    blocks = blocks_data.load_blocks()   # {(c, r): style}, mutated by the overlay
    _block_plats: list = []              # cached merged collision platforms
    _blocks_dirty = [True]               # rebuild the cache only when blocks change
    def _save_blocks() -> None:
        blocks_data.save_blocks(blocks)
        _blocks_dirty[0] = True
    overlay.set_blocks(blocks)
    overlay._on_blocks_changed = _save_blocks
    block_r_was_down = [False]            # edge-detect the R key while placing

    def _get_block_platforms() -> list:
        """Square blocks → collision platforms (cached; rebuilt only when blocks
        change).  Horizontally-adjacent blocks in a row merge into one wide
        platform so Sao walks across a row smoothly instead of catching seams."""
        if not _blocks_dirty[0]:
            return _block_plats
        _blocks_dirty[0] = False
        from collections import defaultdict
        by_row: dict = defaultdict(list)
        for (c, r) in blocks:
            by_row[r].append(c)
        out = []
        for r, cols in by_row.items():
            cols.sort()
            run_start = prev = cols[0]
            for c in cols[1:] + [None]:
                if c == prev + 1:
                    prev = c
                    continue
                x, y, _w, h = blocks_data.cell_rect(run_start, r, screen_floor)
                w = (prev - run_start + 1) * blocks_data.BLOCK_SIZE
                out.append(Platform(hwnd=blocks_data.block_hwnd(run_start, r),
                                    x=x, y=y, w=w, h=h, solid=True))
                if c is not None:
                    run_start = prev = c
        _block_plats[:] = out
        return _block_plats

    # Pomodoro window — created once, shown/hidden on demand
    pomodoro_win = PomodoroWindow()

    # Wire window ↔ overlay flip-dot panel
    def _pomo_start(remaining: int, phase: str) -> None:
        overlay.pomodoro.start_pomodoro(remaining, phase)

    def _pomo_stop() -> None:
        overlay.pomodoro.stop_pomodoro()

    def _pomo_remaining(secs: int, phase: str) -> None:
        overlay.pomodoro.update_remaining(secs)
        overlay.pomodoro.set_phase(phase)

    def _pomo_paused(paused: bool) -> None:
        overlay.pomodoro.set_paused(paused)

    pomodoro_win.on_start_animation     = _pomo_start
    pomodoro_win.on_stop_animation      = _pomo_stop
    pomodoro_win.on_remaining_changed   = _pomo_remaining
    pomodoro_win.on_pause_state_changed = _pomo_paused

    # Overlay → window: clicks on the flip-dot panel pause / cancel
    overlay.pomodoro.on_pause_clicked  = pomodoro_win.force_pause_from_overlay
    overlay.pomodoro.on_cancel_clicked = pomodoro_win.force_cancel_from_overlay

    # Apply persisted pomodoro display mode from world_settings.json
    import json as _json
    _ws_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'desktop_cat', 'world_settings.json',
    )
    try:
        with open(_ws_path) as _f:
            _ws = _json.load(_f)
        overlay.pomodoro.set_display_mode(int(_ws.get('pomo_display_mode', 0)))
        _focus0 = bool(_ws.get('focus_mode', False))
        overlay.set_flowers_hidden(_focus0 or bool(_ws.get('flowers_hidden', False)))
        if hasattr(overlay, 'set_rocks_hidden'):
            overlay.set_rocks_hidden(_focus0 or bool(_ws.get('rocks_hidden', False)))
        cat_hidden       = _focus0 or bool(_ws.get('cat_hidden', False))
        creatures_hidden = _focus0 or bool(_ws.get('creatures_hidden', False))
        if hasattr(overlay, 'set_cat_hidden'):
            overlay.set_cat_hidden(cat_hidden)
        if hasattr(overlay, 'set_creatures_hidden'):
            overlay.set_creatures_hidden(creatures_hidden)
        for _attr, _key in (('set_ladybugs_hidden', 'ladybugs_hidden'),
                            ('set_butterflies_hidden', 'butterflies_hidden'),
                            ('set_friendbugs_hidden', 'friendbugs_hidden')):
            if hasattr(overlay, _attr):
                getattr(overlay, _attr)(bool(_ws.get(_key, False)))
        if hasattr(overlay, 'set_greenbeans'):
            overlay.set_greenbeans(bool(_ws.get('greenbeans', False)))
        if hasattr(overlay, 'set_grass_density'):
            overlay.set_grass_density(_ws.get('grass_density', 35))
        if hasattr(overlay, 'set_grass_bed'):
            overlay.set_grass_bed(_ws.get('grass_bed', 0))
        if hasattr(overlay, 'set_extra_tall_grass'):
            overlay.set_extra_tall_grass(bool(_ws.get('extra_tall_grass', False)))
        if hasattr(overlay, 'set_ball_color'):
            _bc = _hex_to_rgb(_ws.get('ball_color', '#eb5a5a'))
            if _bc:
                overlay.set_ball_color(_bc)
        if hasattr(overlay, 'set_rock_density'):
            overlay.set_rock_density(_ws.get('rock_density', 0))
        if hasattr(overlay, 'set_block_mode'):
            overlay.set_block_mode(bool(_ws.get('block_mode', False)))
    except (OSError, ValueError, TypeError):
        overlay.pomodoro.set_display_mode(0)

    def _apply_world_settings(settings: dict) -> None:
        nonlocal cat_hidden, creatures_hidden
        try:
            overlay.pomodoro.set_display_mode(int(settings.get('pomo_display_mode', 0)))
        except (TypeError, ValueError):
            pass
        # Sound-effects toggle from the hub Settings → applies live.
        try:
            sounds.set_enabled(bool(settings.get('sound_effects', False)))
        except Exception:
            pass
        # Focus mode = "reduce distractions": force-hide Sao, critters,
        # flowers and rocks while on, without clobbering the individual
        # show/hide prefs underneath (turning Focus off restores them).
        focus = bool(settings.get('focus_mode', False))
        overlay.set_flowers_hidden(focus or bool(settings.get('flowers_hidden', False)))
        if hasattr(overlay, 'set_rocks_hidden'):
            overlay.set_rocks_hidden(focus or bool(settings.get('rocks_hidden', False)))
        cat_hidden       = focus or bool(settings.get('cat_hidden', False))
        creatures_hidden = focus or bool(settings.get('creatures_hidden', False))
        if hasattr(overlay, 'set_cat_hidden'):
            overlay.set_cat_hidden(cat_hidden)
        if hasattr(overlay, 'set_creatures_hidden'):
            overlay.set_creatures_hidden(creatures_hidden)
        for _attr, _key in (('set_ladybugs_hidden', 'ladybugs_hidden'),
                            ('set_butterflies_hidden', 'butterflies_hidden'),
                            ('set_friendbugs_hidden', 'friendbugs_hidden')):
            if hasattr(overlay, _attr):
                getattr(overlay, _attr)(bool(settings.get(_key, False)))
        if hasattr(overlay, 'set_greenbeans'):
            overlay.set_greenbeans(bool(settings.get('greenbeans', False)))
        if hasattr(overlay, 'set_grass_density'):
            overlay.set_grass_density(settings.get('grass_density', 35))
        if hasattr(overlay, 'set_grass_bed'):
            overlay.set_grass_bed(settings.get('grass_bed', 0))
        if hasattr(overlay, 'set_extra_tall_grass'):
            overlay.set_extra_tall_grass(bool(settings.get('extra_tall_grass', False)))
        if hasattr(overlay, 'set_ball_color'):
            _bc = _hex_to_rgb(settings.get('ball_color', '#eb5a5a'))
            if _bc:
                overlay.set_ball_color(_bc)
        if hasattr(overlay, 'set_rock_density'):
            overlay.set_rock_density(settings.get('rock_density', 0))
        if hasattr(overlay, 'set_block_mode'):
            overlay.set_block_mode(bool(settings.get('block_mode', False)))
    _on_world_settings_changed = _apply_world_settings   # legacy alias

    # Live-poll world_settings.json (written by the hub Settings panel via
    # the saveWorldSettings bridge) so flower/rock toggles apply without
    # restart.  Cheap: an mtime stat every 1.2 s, re-read only on change.
    _ws_poll_state = {'mtime': -1.0}
    def _poll_world_settings() -> None:
        try:
            mt = os.path.getmtime(_ws_path)
        except OSError:
            return
        if mt == _ws_poll_state['mtime']:
            return
        _ws_poll_state['mtime'] = mt
        try:
            with open(_ws_path) as _f:
                _apply_world_settings(_json.load(_f))
        except (OSError, ValueError, TypeError):
            pass
    _ws_timer = QTimer()
    _ws_timer.setInterval(1200)
    _ws_timer.timeout.connect(_poll_world_settings)
    _ws_timer.start()
    _poll_world_settings()   # prime the mtime cache

    # ── Canvas auto-sync (hourly) ─────────────────────────────────────
    # The user shouldn't have to open the hub + hit Sync to see new
    # assignments.  Re-fetch the iCal feed every hour in the background;
    # run_sync writes library data the hub + flowers read.  Runs in a
    # worker thread so the network fetch never stalls the GUI.
    def _merge_canvas_into_todos() -> None:
        """Fold the freshly-synced Canvas items into library_todos.json —
        the file the flowers + hub read.  Mirrors the React hub's onSyncCanvas
        merge so new assignments become flowers WITHOUT needing the hub open:
        manual todos and per-item done-state are preserved; canvas:* entries
        are rebuilt from the current feed."""
        from desktop_cat import canvas_sync
        try:
            with open(_LIBRARY_TODOS_PATH, encoding='utf-8') as _f:
                existing = _json.load(_f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
        manual    = [t for t in existing
                     if not str(t.get('id', '')).startswith('canvas:')]
        prev_done = {t.get('id'): bool(t.get('done')) for t in existing}
        canvas_items = []
        for c in canvas_sync.all_work_items():
            cid = 'canvas:' + str(c.get('uid') or c.get('id') or c.get('title') or '')
            iso = (c.get('start_iso') or c.get('due') or '')[:10]
            canvas_items.append({
                'id':       cid,
                'name':     c.get('title') or c.get('name') or '(untitled)',
                'due':      iso,
                'done':     bool(prev_done.get(cid, False)),
                'source':   'canvas',
                'priority': c.get('priority') or 'normal',
            })
        merged = manual + canvas_items
        tmp = _LIBRARY_TODOS_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as _f:
            _json.dump(merged, _f, indent=2)
        os.replace(tmp, _LIBRARY_TODOS_PATH)

    def _auto_sync_canvas() -> None:
        import threading
        def _work() -> None:
            try:
                from desktop_cat import canvas_sync
                cfg_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'desktop_cat', 'library_config.json')
                url, a_days, p_days = '', 7, 14
                try:
                    with open(cfg_path, encoding='utf-8') as _f:
                        _c = _json.load(_f) or {}
                    url    = (_c.get('canvas_url') or '').strip()
                    a_days = int(_c.get('lookahead_assignment_days', 7))
                    p_days = int(_c.get('lookahead_project_days', 14))
                except Exception:
                    pass
                if url:
                    canvas_sync.run_sync(url, a_days, p_days)
                    # Propagate the fresh feed into the flowers' todo file.
                    _merge_canvas_into_todos()
            except Exception as _e:
                print(f'[canvas auto-sync] {_e}')
        threading.Thread(target=_work, daemon=True).start()
    _canvas_timer = QTimer()
    _canvas_timer.setInterval(60 * 60 * 1000)   # 1 hour
    _canvas_timer.timeout.connect(_auto_sync_canvas)
    _canvas_timer.start()
    # Kick one shortly after launch so a fresh start picks up new items
    # without waiting an hour (delayed so it doesn't fight startup).
    QTimer.singleShot(8000, _auto_sync_canvas)

    # Pin manager + global hotkeys — predefined keybinds + pin-on-cursor tool.
    def _ignore_hwnds() -> set[int]:
        hs: set[int] = {int(overlay.winId())}
        if hub_window is not None:
            try:
                hs.add(int(hub_window.winId()))
            except Exception:
                pass
            for w in (hub_window._world_settings,
                      hub_window._pomodoro,
                      hub_window._message_board,
                      hub_window._clipboard):
                if w is not None:
                    try:
                        hs.add(int(w.winId()))
                    except Exception:
                        pass
        try:
            hs.add(int(pomodoro_win.winId()))
        except Exception:
            pass
        return hs

    pin_manager = PinManager(ignore_hwnds=_ignore_hwnds)
    # Publish it so the Library-Hub bridge (Settings UI) can arm pin mode
    # and list / remove pins.
    try:
        from desktop_cat import pin_registry
        pin_registry.set_pin_manager(pin_manager)
    except Exception:
        pass
    # Floating dot indicators over each pinned window's titlebar.
    try:
        from desktop_cat.pin_dots import PinDotManager
        pin_dot_manager = PinDotManager(pin_manager)
    except Exception as _pd_exc:
        print(f'[pin_dots] failed: {_pd_exc}')
        pin_dot_manager = None
    # Also teach the window scanner to skip the same SAO panel windows so
    # Sao doesn't land on invisible frameless-tool-window platforms.
    scanner._extra_skip_hwnds = _ignore_hwnds

    def _start_pomodoro_from_keybind() -> None:
        if not pomodoro_win.isVisible():
            spawn_x = screen_w - 320
            spawn_y = max(20, screen_h - pomodoro_win.height() - 80)
            pomodoro_win.show_animated(spawn_x, spawn_y)
        pomodoro_win.start_from_keybind()
        pomodoro_win.raise_()

    hotkeys = GlobalHotkeys(app)
    hotkeys.register('ctrl+alt+p', _start_pomodoro_from_keybind)
    hotkeys.register('ctrl+alt+n', pin_manager.toggle_pin_mode)
    hotkeys.install()

    # Snapshot baseline physics + detection / behavior constants — Sao's stat
    # modifiers are applied in `_begin_main_loop` (after onboarding has had a
    # chance to generate her profile).
    _PHYS_RUN_BASE  = _phys.RUN_SPEED
    _PHYS_WALK_BASE = _phys.WALK_SPEED
    _PHYS_JUMP_BASE = _phys.JUMP_POWER

    cat = CatState(x=float(screen_w // 2), y=float(screen_floor - CAT_H),
                   width=CAT_W, height=CAT_H)
    platforms: list[Platform] = []

    tick_count       = 0
    wander_ticks     = 0
    wander_dir       = random.choice([-1, 1])
    wander_run_ticks = 0    # ticks remaining in a run burst (0 = walking)
    # Graceful turn — an occasional lifelike direction change (decelerate, stop,
    # a little backwards shuffle, then flip).  '' = not turning.
    turn_phase       = ''   # '' | 'decel' | 'pause' | 'back'
    turn_ticks       = 0
    turn_old_dir     = 1    # direction she was facing
    turn_new_dir     = 1    # direction she'll commit to
    idle_pause       = 0
    is_jumping       = False
    # Cursor-punch state
    attack_phase     = ''   # '' | 'approach' | 'punch'
    cursor_low_ticks = 0    # ticks the cursor has parked low next to her
    approach_ticks   = 0    # ticks spent running toward the cursor
    attack_ticks     = 0    # >0 = mid-punch (counts down)
    attack_dir       = 1    # direction of the current lunge
    attack_origin_x  = 0.0  # x she springs out from and back to
    attack_cooldown  = 0    # ticks until she may punch again
    cursor_slide_vx  = 0.0  # physical px/tick the knocked cursor is still sliding
    punch_window_ticks = PUNCH_WINDOW_TICKS  # countdown of the current 3-min budget window
    punch_count_3min   = 0  # punches thrown in the current window (cap = PUNCH_MAX_PER_WINDOW)
    was_dragging       = False  # True if Sao was being mouse-dragged last tick
    nap_ticks          = 0       # consecutive ticks of zero mouse movement
    napping            = False   # True while she's dozing (stands still + Z's)
    nap_cursor_ref     = (0, 0)  # cursor pos last tick, for movement detection
    macaron            = None    # {'x','y','vy','state'} treat on the desktop, or None
    macaron_eat_ticks  = 0       # ticks held in the 'eating' interact pose
    meal_nap_timer     = 0       # >0 → counting down to a post-macaron food-coma nap
    ball               = None    # {'x','y','vx','vy'} beach ball (centre), or None
    ball_punch_cd      = 0       # ticks until she may bat the ball again
    attack_target      = 'cursor'  # what the current punch targets: 'cursor' | 'ball'
    # Pester tracking — how many rapid passes the cursor has made over Sao.
    pester_count       = 0    # passes counted in the current window
    pester_decay       = 0    # ticks left before the count resets (rolling window)
    pester_was_over    = False  # was the cursor inside her zone last tick?
    hover_stop_ticks   = 0  # how long she's been held still by a hovering cursor
    descend_ticks    = 0    # independent timer for dropping off window platforms

    jump_ticks           = random.randint(0, JUMP_CONSIDER_TICKS)
    jump_target_hwnd: int | None = None
    jump_attempts        = 0
    jump_cooldown        = 0
    wind_up_ticks        = 0
    pending_jump_target  = None

    # Walk-around state: Sao walks off one edge and re-enters from the other
    walk_around_dir: int = 0   # 0=inactive, ±1=direction

    # Taskbar drop state machine
    # 'normal'            — standing on top of taskbar (screen_floor), normal behaviour
    # 'falling'           — dropped below taskbar, floor is now screen_h
    # 'at_bottom'         — walking freely at screen_h (walk only, no run)
    # 'returning'         — jumped back up from screen_h, floor is screen_floor again
    # 'approaching_plant' — walking to a chosen plant at screen_floor
    # 'interacting_plant' — tending a plant (interact anim, distance-based row)
    # 'seeking_icon'      — standing still while the UIA taskbar-icon query runs
    # 'walking_to_icon'   — strolling toward a running app's icon, fading as she nears
    # 'inside_icon'       — hidden inside the app; teal bar pulses under its icon
    # 'exiting_icon'      — stepping back out of the icon, fading back in
    # 'approaching_flower'— walking to a task flower to interact and remove it
    # 'removing_flower'   — playing interact anim before the flower disappears
    taskbar_state: str        = 'normal'
    interact_ticks: int       = 0
    target_plant              = None   # Plant | None — plant being approached/tended
    plant_interact_ticks: int = 0
    plant_target_dist: int    = 0     # random stop distance (negative = overlap)
    hut_ticks: int = 0                  # countdown while Sao works inside a window
    work_window_hwnd: 'int | None' = None   # hwnd of the app Sao is working inside

    # ── Walk-into-taskbar-icon mechanic ────────────────────────────────────
    # Sao strolls along the taskbar, steps into a running app's icon (fading
    # out as she enters), "works" there a while (teal bar under the icon),
    # then fades back out and walks away.  Icon rects come from UI Automation
    # on a worker thread (see desktop_cat/taskbar_icons.py) since the query is
    # slow and touches COM.
    work_icon: 'dict | None'  = None   # {name, cx, top, bottom, ...} she's entering
    icon_seek_ticks: int      = 0      # frames spent waiting on the icon query
    icon_exit_dir: int        = 1      # direction she walks out after working
    icon_fade_ticks: int      = 0      # frames elapsed in the pop-out fade-in
    icon_poll_pending: bool   = False  # True while a movement re-check query is in flight
    icon_cooldown_ticks: int  = 0      # after leaving, she won't re-enter until this hits 0
    icon_fg_hwnd: int         = 0      # foreground window when she ducked in (legacy; no longer pops her)
    icon_click_prev: bool     = False  # left-button state last frame, for click-edge detection
    _icon_query = {'icons': None, 'busy': False}  # shared with the worker thread

    def _request_icon_query():
        """Kick off a background UIA sweep for running-app taskbar icons.
        Result lands in _icon_query['icons'] (a list); no-op if one's already
        running or UIA isn't available."""
        if _icon_query['busy'] or not taskbar_icons.available():
            return
        _icon_query['busy']  = True
        _icon_query['icons'] = None
        def _work():
            try:
                _icon_query['icons'] = taskbar_icons.query_running_icons(dpi_ratio)
            except Exception:
                _icon_query['icons'] = []
            finally:
                _icon_query['busy'] = False
        threading.Thread(target=_work, daemon=True).start()
    wander_walk_boost_ticks: int = 0  # ticks of slightly boosted walk after run ends
    wander_accel_ticks: int   = 0     # ticks elapsed since run start (for ramp-up)
    wander_pre_walk_ticks: int = 0    # walk phase before run starts
    step_sfx_tick: int        = 0     # ticks since last footstep sfx
    skid_ticks: int = 0               # ticks remaining in a skid-stop
    skid_dir:   int = 0               # direction Sao was running when skid triggered
    will_skid:  bool = False          # if True, next run→decel transition becomes a skid
    hop_down_ignore_hwnd: int | None = None  # set during a hop-down to phase through current platform
    _occlude_raw_ticks: int = 0   # consecutive ticks the cat has been covered
    occluded_ticks: int = 0       # ticks the cat has been stably hidden
    _has_fullscreen: bool = False  # cached at scan time — True when a fullscreen window covers the screen
    is_occluded: bool = False     # True → renderer hides the blob
    is_paused: bool = False       # True → freeze all movement, play idle

    # Task-flower removal — Sao walks to the flower, interacts, then it disappears
    flower_to_remove:    str | None = None   # task_text queued for cat interaction
    flower_remove_ticks: int        = 0      # countdown during removal interaction
    flower_target_x:     float      = 0.0   # x position of the flower being removed

    # Task-flower PLANTING — populated by the Library Hub todos reconciler.
    # Each item: {'todo_id': str, 'task_text': str, 'due_date': str}.
    # When Sao is idle she pops the head off, picks a random x, walks
    # there, plays interact_close, then a TaskFlower spawns at that x.
    _plant_queue:        list = []
    plant_pending:       dict | None = None  # the {todo_id, task_text, due_date} currently being planted
    plant_target_x:      float       = 0.0
    plant_anim_ticks:    int         = 0
    # Track which library_todos.json mtime we've already reconciled so we
    # don't reparse the file every frame.
    _library_todos_mtime: list = [0.0]


    def on_toggle_pause(_):
        nonlocal is_paused
        is_paused = not is_paused

    def on_pomodoro_open(_):
        if pomodoro_win.isVisible():
            pomodoro_win.raise_()
            pomodoro_win.activateWindow()
            return
        # Spawn near right side of screen
        spawn_x = screen_w - 320
        spawn_y = max(20, screen_h - pomodoro_win.height() - 80)
        pomodoro_win.show_animated(spawn_x, spawn_y)

    bus.subscribe('TOGGLE_PAUSE',   on_toggle_pause)
    bus.subscribe('POMODORO_OPEN',  on_pomodoro_open)

    def on_tick():
        nonlocal cat, platforms, tick_count
        nonlocal wander_ticks, wander_dir, wander_run_ticks, idle_pause, is_jumping, descend_ticks
        nonlocal attack_phase, cursor_low_ticks, approach_ticks
        nonlocal attack_ticks, attack_dir, attack_origin_x, attack_cooldown, cursor_slide_vx
        nonlocal punch_window_ticks, punch_count_3min, hover_stop_ticks
        nonlocal pester_count, pester_decay, pester_was_over, was_dragging
        nonlocal nap_ticks, napping, nap_cursor_ref, macaron, macaron_eat_ticks
        nonlocal meal_nap_timer, ball, ball_punch_cd, attack_target
        nonlocal turn_phase, turn_ticks, turn_old_dir, turn_new_dir
        nonlocal jump_ticks, jump_target_hwnd, jump_attempts, jump_cooldown
        nonlocal wind_up_ticks, pending_jump_target
        nonlocal walk_around_dir
        nonlocal taskbar_state, interact_ticks, target_plant, plant_interact_ticks, plant_target_dist
        nonlocal hut_ticks, work_window_hwnd, flower_to_remove, flower_remove_ticks, flower_target_x
        nonlocal work_icon, icon_seek_ticks, icon_exit_dir, icon_poll_pending
        nonlocal icon_fade_ticks, icon_cooldown_ticks, icon_fg_hwnd, icon_click_prev
        nonlocal plant_pending, plant_target_x, plant_anim_ticks
        nonlocal wander_walk_boost_ticks, wander_accel_ticks, wander_pre_walk_ticks
        nonlocal step_sfx_tick
        nonlocal skid_ticks, skid_dir, will_skid
        nonlocal bugs, butterflies, effects, bug_for_plant, bug_sync_timer
        nonlocal butterfly_timer, butterfly_chase_target, butterfly_chase_ticks
        nonlocal butterfly_catchable, butterfly_hop_count, butterfly_target_speed
        nonlocal cursor_last_pos, cursor_still_ticks, friend_bug_spawn_timer
        nonlocal punch_still_ref_x, punch_still_ref_y, punch_still_ticks
        nonlocal friend_bug_cursor_cooldown
        nonlocal ladybug_cooldown, ladybug_visit_ticks, ladybug_leaving
        nonlocal snail_cooldown
        nonlocal task_flowers, falling_seeds
        nonlocal hop_down_ignore_hwnd, _occlude_raw_ticks, occluded_ticks, is_occluded, is_paused
        nonlocal _has_fullscreen

        # Tick task-flower pop-out animations.  When a flower's pop_anim_ticks
        # was kicked by the reconciler (done flipped true), count it down each
        # frame; once it hits 0 the flower is dropped from the list and the
        # renderer sees one less item.  Cheap loop so we do it every frame.
        if task_flowers:
            popped_any = False
            for _tf in task_flowers:
                if _tf.pop_anim_ticks > 0:
                    _tf.pop_anim_ticks -= 1
            still = [_tf for _tf in task_flowers if not _tf.done or _tf.pop_anim_ticks > 0]
            if len(still) != len(task_flowers):
                task_flowers = still
                overlay.set_task_flowers(task_flowers)
                _save_task_flowers()
                popped_any = True

        if tick_count % 30 == 0:
            # Pinned sticky windows: mtime-poll stickies.json.  React writes
            # happen here too, so the floating windows track the hub's view.
            try:
                _mt = _stickies_data.mtime()
                if _mt != _stickies_mtime[0]:
                    _stickies_mtime[0] = _mt
                    _reconcile_sticky_windows()
            except OSError:
                pass
            # Same idea for the React Hub's todo list: reconcile against
            # task_flowers so new todos queue a planting trip for Sao,
            # done flags wilt the matching flower, deletes remove them.
            try:
                if os.path.exists(_LIBRARY_TODOS_PATH):
                    _mt = os.path.getmtime(_LIBRARY_TODOS_PATH)
                    if _mt != _library_todos_mtime[0]:
                        _library_todos_mtime[0] = _mt
                        _reconcile_library_todos()
            except OSError:
                pass

        # Always process bus events so TOGGLE_PAUSE fires immediately
        if tick_count % SCAN_EVERY == 0:
            bus.tick()

        # Intro-drop landing impact — fires once when Sao first touches ground
        # after dropping from the sky (every program boot).
        if hasattr(overlay, 'consume_intro_drop_landing'):
            _land = overlay.consume_intro_drop_landing()
            if _land is not None:
                _lx, _ly, _lcol = _land
                # Burst of colored sparks
                for _ in range(8):
                    effects.append(make_collect_effect(_lx, _ly))
                sounds.play('plop', volume=0.55)

        # Pin manager — poll for clicks + enforce min/close rules every frame.
        pin_manager.tick()

        # Periodically re-assert overlay stays above taskbar and new windows
        if tick_count % TOPMOST_REASSERT_TICKS == 0:
            win32gui.SetWindowPos(
                int(overlay.winId()),
                win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )

        dt = TICK_MS / 1000.0

        _CROP_PREFIX = '__crop__'

        def _tick_falling_seeds() -> None:
            """Advance falling-seed physics — runs every tick even when the
            game is paused so a seed can never get stuck in midair."""
            for fs in falling_seeds[:]:
                fs.vy += SEED_GRAVITY * dt
                fs.y  += fs.vy * dt
                if fs.y >= screen_floor:
                    falling_seeds.remove(fs)
                    effects.append(make_collect_effect(fs.x, float(screen_floor - 8)))
                    sounds.play('plop', volume=0.30)

                    if fs.task_text.startswith(_CROP_PREFIX):
                        # Crop seed — create a garden Plant
                        stype = fs.task_text[len(_CROP_PREFIX):]
                        ptype_map = {
                            'flower': PLANT_FLOWER,
                            'macron': PLANT_MACRON,
                        }
                        ptype = ptype_map.get(stype, PLANT_FLOWER)
                        garden.add_plant(int(fs.x), ptype,
                                         bbug_slots=inventory.get('bbug_slots', []))
                        _save_garden()
                        overlay.set_garden(garden, screen_floor)
                    else:
                        # Task seed → task flower
                        task_flowers.append(TaskFlower(
                            x=fs.x,
                            task_text=fs.task_text,
                            due_date=fs.due_date,
                            planted_date=_datetime.now().isoformat(timespec='seconds'),
                        ))
                        _save_task_flowers()
                        _mark_todo_planted(fs.task_text)
                        overlay.set_task_flowers(task_flowers)

        if is_paused:
            overlay.update_state(cat, platforms, occluded=False, anim_override='idle')
            tick_count += 1
            _tick_falling_seeds()
            return

        prev_cat     = cat
        was_grounded = cat.grounded

        # ── window scan ──────────────────────────────────────────────────
        # The full EnumWindows + DWM sweep is the single most expensive thing
        # per frame.  Windows only move/resize/restack on user input, so the
        # scheduler polls three cheap signals (foreground hwnd, foreground
        # rect, mouse-button) and only rescans when the desktop could have
        # changed — otherwise Sao coasts on the cached platform list.
        if scan_sched.should_scan():
            raw = scanner.tick()
            # Cache fullscreen state at scan time (DWM calls are slow for every tick)
            _has_fullscreen = has_fullscreen_window(
                scanner.z_order, phys_screen_w, phys_screen_h)
            platforms = scale_platforms(raw, dpi_ratio)

        # _vis_platforms: what Sao can actually collide with / jump to.
        # WindowScanner already clips every platform to its visible portion
        # (subtracting any rect in front of its owner window), so the old
        # "z==0 only" filter is redundant. A platform is in this list iff the
        # user can actually see that edge. Fullscreen still clears everything
        # so Sao falls back down to the taskbar behaviour set.
        if _has_fullscreen:
            _vis_platforms = []
        else:
            _vis_platforms = platforms
        # Placed blocks are always solid (she can stand/jump on them even when
        # they're faded out), so add them as platforms unless fully covered.
        _block_plats_now = _get_block_platforms() if (blocks and not _has_fullscreen) else []
        if _block_plats_now:
            _vis_platforms = _vis_platforms + _block_plats_now

        # While in block mode, R cycles the style being placed (polled globally;
        # only active during placement so it doesn't shadow normal typing).
        # Escape exits block mode — needed because the overlay captures all
        # clicks while placing, so the hub toggle can't be clicked to leave.
        if getattr(overlay, '_block_mode', False):
            try:
                _r_down   = bool(ctypes.windll.user32.GetAsyncKeyState(0x52) & 0x8000)
                _esc_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
            except Exception:
                _r_down = _esc_down = False
            if _r_down and not block_r_was_down[0]:
                overlay.cycle_block_style()
            block_r_was_down[0] = _r_down
            if _esc_down:
                overlay.set_block_mode(False)
                try:    # persist so the hub toggle reflects the exit
                    with open(_ws_path, 'r', encoding='utf-8') as _bf:
                        _bd = _json.load(_bf)
                    if not isinstance(_bd, dict):
                        _bd = {}
                except Exception:
                    _bd = {}
                _bd['block_mode'] = False
                try:
                    with open(_ws_path, 'w', encoding='utf-8') as _bf:
                        _json.dump(_bd, _bf, indent=2)
                    _ws_poll_state['mtime'] = os.path.getmtime(_ws_path)
                except Exception:
                    pass

        # ── snap cat to window top while grounded ────────────────────────
        if cat.grounded and cat.on_hwnd is not None:
            plat = find_platform(cat.on_hwnd, _vis_platforms)
            if plat is not None:
                snap_y = float(plat.top - cat.height)
                if abs(cat.y - snap_y) < 80:
                    cat = replace(cat, y=snap_y)

        # ── drag override (physics replaced by mouse) ────────────────────
        if overlay.is_dragging:
            dp = overlay.drag_position()
            cat = replace(cat,
                x=float(dp.x()), y=float(dp.y()),
                vx=0.0, vy=0.0,
                grounded=False, on_hwnd=None,
            )
            is_jumping       = False
            jump_target_hwnd = None
            # Picking her up cancels any taskbar-bottom excursion, so when she's
            # released the floor is the taskbar top again (not the very bottom).
            if taskbar_state != 'normal':
                taskbar_state = 'normal'
            was_dragging = True

        else:
            # Just released this frame?  Try to catch a window ledge she was
            # dropped near, so she reliably lands on it instead of falling
            # through (forgiving — helps across DPI/geometry differences).
            if was_dragging:
                was_dragging = False
                _drop = _snap_drop_platform(cat, _vis_platforms)
                if _drop is not None:
                    cat = replace(cat, y=float(_drop.top - cat.height),
                                  vx=0.0, vy=0.0, grounded=True,
                                  on_hwnd=_drop.hwnd)
            # ── physics + collision ───────────────────────────────────────
            # During taskbar drop/at_bottom, lower the hard floor to screen_h
            # so Sao can fall past the taskbar into the icon strip.
            # Keep floor at screen_h while Sao is still physically below the taskbar,
            # including during 'returning' so the jump isn't immediately snapped away.
            if taskbar_state in ('falling', 'at_bottom', 'seeking_icon',
                                 'walking_to_icon', 'inside_icon', 'exiting_icon'):
                effective_floor = screen_h
            elif taskbar_state == 'returning' and cat.bottom > screen_floor:
                effective_floor = screen_h
            else:
                effective_floor = screen_floor
            cat = apply_physics(cat, dt)
            cat = resolve_collision(cat, _vis_platforms, effective_floor,
                                    prev_state=prev_cat,
                                    ignore_hwnd=hop_down_ignore_hwnd)
            # Auto-step up onto / stop at placed blocks in her path.
            if blocks:
                cat = _block_traverse(cat, prev_cat, _get_block_platforms())
            # Hard screen-edge walls — always clamp; kill momentum on impact
            _clamped_x = max(0.0, min(cat.x, screen_w - cat.width))
            _vx = cat.vx
            if _clamped_x <= 0.0 and _vx < 0:
                _vx = 0.0
            elif _clamped_x >= screen_w - cat.width and _vx > 0:
                _vx = 0.0
            cat = replace(cat, x=_clamped_x, vx=_vx)

        # ── landing detection (AFTER physics so grounded is current) ─────
        just_landed = not was_grounded and cat.grounded

        if just_landed:
            idle_pause           = IDLE_PAUSE_TICKS
            is_jumping           = False
            hop_down_ignore_hwnd = None

            # Taskbar state transitions on landing
            if taskbar_state == 'falling':
                # Landed at screen bottom — walk around freely for a while
                taskbar_state  = 'at_bottom'
                interact_ticks = random.randint(INTERACT_TICKS_MIN, INTERACT_TICKS_MAX)
            elif taskbar_state == 'returning':
                # Landed back on taskbar top — return to normal
                taskbar_state = 'normal'

            if jump_target_hwnd is not None:
                # Owner-aware hit check: any segment (top or bottom, any index)
                # of the target window counts as a hit.
                _landed_owner = _owner_of_on_hwnd(cat.on_hwnd, _vis_platforms)
                _target_owner = _owner_of_on_hwnd(jump_target_hwnd, _vis_platforms)
                hit = (cat.on_hwnd == jump_target_hwnd or
                       (_landed_owner != 0 and _landed_owner == _target_owner))
                if hit:
                    jump_attempts = 0
                    # burst: small chance to queue another jump right away
                    if random.random() < BURST_CHANCE:
                        jump_ticks = JUMP_CONSIDER_TICKS
                else:
                    jump_attempts += 1
                    if jump_attempts >= MAX_JUMP_ATTEMPTS:
                        jump_cooldown = JUMP_GIVE_UP_TICKS
                        jump_attempts = 0
                jump_target_hwnd = None

        # ── safety net: is_jumping can't be True while grounded ───────────
        if cat.grounded:
            is_jumping = False

        # ── critter ticks — MUST be before idle_pause early return so critters
        #    never freeze when Sao lands or is in any other paused state ─────
        _cursor_near = cursor_distance_to_cat(cat, overlay) < CURSOR_SLOW_RADIUS
        if _cursor_near:
            hover_stop_ticks += 1
        else:
            hover_stop_ticks = 0
        # `cursor_close` now means "actively pausing FOR the cursor" — true only
        # for the first ~1 s of a hover (in case the user wants to click her).
        # After that she carries on and won't stop again until the cursor leaves
        # and returns.
        cursor_close = _cursor_near and hover_stop_ticks <= HOVER_STOP_TICKS

        bug_sync_timer += 1
        if bug_sync_timer >= BUG_SYNC_TICKS:
            bug_sync_timer = 0
            # Rebuild valid set: only plants with bee that still exist
            _valid_bee_idx = {
                i for i, p in enumerate(garden.plants)
                if p.stage >= 1 and p.has_bee
            }
            # Remove orphaned bugs (max 1 per plant, plants removed, or bee lost)
            for _si in [k for k in bug_for_plant if k not in _valid_bee_idx]:
                _orph = bug_for_plant.pop(_si)
                if _orph in bugs:
                    bugs.remove(_orph)
            # Add missing bugs and update heights
            for i, plant in enumerate(garden.plants):
                if i in _valid_bee_idx:
                    top_y = screen_floor - PLANT_TOP_HEIGHTS[plant.stage]
                    if i not in bug_for_plant:
                        _bk = plant.bug_kind if plant.bug_kind else 'plain'
                        bug_for_plant[i] = make_bug(plant.x, top_y, kind=_bk)
                        bugs.append(bug_for_plant[i])
                    else:
                        bug_for_plant[i].home_y = float(top_y)
        for bug in bugs:
            bug.tick()

        # Grass sway (breeze + Sao/cursor disturbance) is now driven entirely by
        # the renderer in _tick_grass — no per-shrub wind bookkeeping here.

        # ── Wandering ABug3 — one per equipped slot, drifts freely like a butterfly ──
        # Count by origin='wanderer' — stable across state transitions (wandering/approaching/attached).
        _abug3_slots = inventory.get('abug_slots', []).count('abug3')
        # Keep a couple wandering at once (like the butterflies) whenever they're
        # enabled at all — not just one.
        _desired_wanderers = max(2, _abug3_slots) if _abug3_slots > 0 else 0
        _wanderer_count = sum(1 for _fb in friend_bugs if _fb.origin == 'wanderer')
        # Remove excess wanderers when ABug3 is unequipped from slots
        if _wanderer_count > _desired_wanderers:
            _to_remove = _wanderer_count - _desired_wanderers
            for _xfb in list(friend_bugs):
                if _xfb.origin == 'wanderer' and _to_remove > 0:
                    friend_bugs.remove(_xfb)
                    _to_remove -= 1
        elif _wanderer_count < _desired_wanderers:
            _from_left = random.random() < 0.5
            _wx = -14.0 if _from_left else float(screen_w + 14)
            _wy = random.uniform(screen_floor * 0.15, screen_floor * 0.85)
            _wbug = make_friend_bug(_wx, _wy, 0.0, 0.0)
            _wbug.state  = 'wandering'
            _wbug.origin = 'wanderer'   # mark at birth so count stays stable
            _wbug.vx = random.uniform(0.35, 0.65) * (1 if _from_left else -1)
            _wbug.vy = random.uniform(-0.10, 0.10)
            _wbug.wander_timer = random.randint(30, 80)
            friend_bugs.append(_wbug)

        # ── Landing-spot list — bloomed flowers + rocks ─────────────────────
        # Butterflies, friend-bugs, and ladybugs can land here.  Built each
        # frame so deleted/freshly-bloomed plants are reflected immediately.
        # Has to live ABOVE the friend-bug loop because that loop reads it
        # when rolling a landing target.
        _land_spots: list[tuple[float, float]] = []
        if garden:
            for _lp in garden.plants:
                if _lp.stage >= 3 and getattr(_lp, 'plant_type', 0) == 0:
                    _land_spots.append((float(_lp.x), overlay.plant_top_y(_lp)))
        for _lr in rocks:
            _land_spots.append((float(_lr.x), overlay.rock_top_y(_lr)))
        # While Sao naps she's a perch too — butterflies can land on her head.
        if napping and cat.grounded:
            _land_spots.append((cat.x + cat.width / 2, cat.y + 6.0))

        # Bounce wandering friend bugs off screen edges AND occasionally
        # commit a landing on a rock / flower / ladybug.  Ladybug ride is
        # a moving target — main.py tracks the ladybug's position each
        # frame and updates the bug's land_x/y so it follows.
        for _wfb in friend_bugs:
            if _wfb.state == 'wandering':
                _edge_m = 80
                if _wfb.x < _edge_m and _wfb.vx < 0:
                    _wfb.vx = abs(_wfb.vx)
                    _wfb.wander_timer = 0
                elif _wfb.x > screen_w - _edge_m and _wfb.vx > 0:
                    _wfb.vx = -abs(_wfb.vx)
                    _wfb.wander_timer = 0
                _taskbar_h = max(screen_h - screen_floor, 20)
                if _wfb.y < screen_floor - _taskbar_h * 2.5:
                    _wfb.vy = abs(_wfb.vy) + 0.05
                elif _wfb.y > screen_floor - 5 and _wfb.vy > 0:
                    _wfb.vy = -abs(_wfb.vy)
                # ── Roll for landing ──
                # ~0.15 % per tick → average ~11 s between attempts per bug.
                # Prefer the closest target within reach: ladybug if one is
                # near, otherwise a flower / rock from _land_spots.
                if (_wfb.alpha == 255 and _wfb.origin == 'wanderer'
                        and random.random() < 0.0015):
                    _picked = False
                    # 35 % chance to ride a ladybug if one is within 320 px
                    if lazy_bugs and random.random() < 0.35:
                        _lb_close = sorted(lazy_bugs, key=lambda lb: abs(lb.x - _wfb.x))
                        _lb = _lb_close[0]
                        if abs(_lb.x - _wfb.x) < 320:
                            _wfb.ride_idx   = lazy_bugs.index(_lb)
                            _wfb.land_x     = float(_lb.x)
                            _wfb.land_y     = float(_lb.y) - 10.0
                            _wfb.land_timer = random.randint(180, 480)
                            _wfb.state      = 'landing'
                            _picked = True
                    # Otherwise pick a static land spot (rock / flower top)
                    if not _picked and _land_spots:
                        _close = sorted(_land_spots, key=lambda s: abs(s[0] - _wfb.x))
                        if _close and abs(_close[0][0] - _wfb.x) < 350:
                            _wfb.ride_idx   = -1
                            _wfb.land_x     = float(_close[0][0])
                            _wfb.land_y     = float(_close[0][1])
                            _wfb.land_timer = random.randint(120, 360)
                            _wfb.state      = 'landing'
            # Ride sync — if landing on / sitting on a ladybug, keep tracking it.
            if _wfb.ride_idx >= 0 and _wfb.state in ('landing', 'landed'):
                if 0 <= _wfb.ride_idx < len(lazy_bugs):
                    _lb = lazy_bugs[_wfb.ride_idx]
                    _wfb.land_x = float(_lb.x)
                    _wfb.land_y = float(_lb.y) - 10.0
                    if _wfb.state == 'landed':
                        # Snap onto the ladybug exactly so the bug rides along
                        # with it as it waddles instead of staying behind.
                        _wfb.x = _wfb.land_x
                        _wfb.y = _wfb.land_y
                else:
                    # Ladybug gone — drop the ride and fly off
                    _wfb.ride_idx = -1
                    _wfb.state    = 'wandering'
                    _wfb.vx       = random.choice([-0.5, 0.5])
                    _wfb.vy       = -0.2

        # When cursor is still long enough, a wandering ABug3 *might* come to
        # the cursor — but this should be RARE and special (user feedback:
        # "make them a lot more rare to land on your cursor").  Gating:
        #   • the stillness threshold is long (see CURSOR_STILL_TRIGGER)
        #   • once eligible, only a small per-tick probability actually fires
        #   • a long cooldown after any landing so it can't re-trigger soon
        #   • at most ONE bug approaches per trigger (not the whole swarm)
        if cursor_still_ticks >= CURSOR_STILL_TRIGGER and friend_bug_cursor_cooldown <= 0:
            # ~1-in-this-many chance per tick while eligible → on average a
            # long wait even once the cursor's been parked a while.
            if random.random() < FRIEND_BUG_CURSOR_CHANCE:
                _cands = [b for b in friend_bugs
                          if b.state == 'wandering' and b.origin == 'wanderer']
                if _cands:
                    _wfb = random.choice(_cands)
                    _ang = random.uniform(math.pi * 1.05, math.pi * 1.95)
                    _r   = random.uniform(2.0, 14.0)
                    _wfb.cluster_dx = math.cos(_ang) * _r
                    _wfb.cluster_dy = math.sin(_ang) * _r * 0.85
                    _wfb.state  = 'approaching'
                    friend_bug_cursor_cooldown = FRIEND_BUG_CURSOR_COOLDOWN
        if friend_bug_cursor_cooldown > 0:
            friend_bug_cursor_cooldown -= 1

        butterfly_timer -= 1
        if butterfly_timer <= 0:
            butterfly_timer = random.randint(BUTTERFLY_SPAWN_MIN, BUTTERFLY_SPAWN_MAX)
            # Butterfly cap.  This used to be tied to the number of BLOOMED
            # garden flowers, but post-pivot the random garden flowers are
            # gone (only task flowers remain) so _bloomed was ~0 and the cap
            # collapsed — and it then SUBTRACTED ABug3 wanderers, which drove
            # it to 0 whenever a wanderer was equipped.  Result: butterflies
            # essentially never spawned.  Now there's a guaranteed baseline
            # of 2, bumped by bloomed flowers, independent of wanderers.
            _bloomed = sum(1 for _p in garden.plants
                           if _p.stage == 4 and _p.plant_type == 0)
            _bf_max  = min(4, 2 + _bloomed)
            if len(butterflies) < _bf_max:
                # Height distribution: peak at half-taskbar above floor, rarer higher/lower
                # Always above the taskbar floor (never below screen_floor)
                taskbar_h = max(screen_h - screen_floor, 20)
                # triangular: most common = 0.5 taskbar above floor; min 0.15 so never on floor
                _h_frac = random.triangular(0.15, 2.0, 0.5)
                spawn_y = float(screen_floor - _h_frac * taskbar_h)
                # Pick butterfly kind — plain stays most common; ABug2 is rare.
                # ABug1 is a ground critter (see lazy_bugs below); ABug3 is FriendBug.
                _abug_slots = inventory.get('abug_slots', [])
                _kind_pool: list[str] = ['plain'] * 6
                for _s in _abug_slots:
                    if _s == 'abug2':
                        _kind_pool.append(_s)   # rare lifter
                _kind = random.choice(_kind_pool)
                butterflies.append(make_butterfly(screen_w, spawn_y, kind=_kind))

        # ── ABug1 (Ladybug) — a RARE visitor, not a permanent ground critter ────
        # She only shows up when an abug1 slot is equipped AND creatures aren't
        # hidden.  Even then she waddles in occasionally, lingers for a short
        # visit, then leaves — with a multi-minute lockout before the next one.
        _abug1_enabled = inventory.get('abug_slots', []).count('abug1') > 0 \
                         and not creatures_hidden
        if not _abug1_enabled:
            # Feature off (or creatures hidden) — clear her out and reset.
            if lazy_bugs:
                lazy_bugs.clear()
            ladybug_visit_ticks = 0
            ladybug_leaving = False
        else:
            if ladybug_cooldown > 0:
                ladybug_cooldown -= 1

            if not lazy_bugs:
                # Eligible to appear once the lockout has elapsed; then it's a
                # low per-tick roll so the moment of arrival is unpredictable.
                if ladybug_cooldown <= 0 and random.random() < LADYBUG_SPAWN_CHANCE:
                    _large_rocks = [_r for _r in rocks if _r.variant == 1]
                    if _large_rocks:
                        _home_rock = min(_large_rocks, key=lambda _r: abs(_r.x - screen_w // 2))
                        _home_x = float(_home_rock.x)
                    else:
                        _home_x = float(screen_w // 3)
                    lazy_bugs.append(make_lazy_bug(_home_x, float(screen_floor), _home_x))
                    ladybug_visit_ticks = random.randint(LADYBUG_VISIT_MIN, LADYBUG_VISIT_MAX)
                    ladybug_leaving = False
            else:
                # She's here — count down her visit, then send her off.
                if not ladybug_leaving:
                    ladybug_visit_ticks -= 1
                    if ladybug_visit_ticks <= 0:
                        ladybug_leaving = True

        for _lb in lazy_bugs:
            _lb.tick()

            if ladybug_leaving:
                # Head for the nearest screen edge and don't stop until off it.
                _edge_dir = -1 if _lb.x < screen_w / 2 else 1
                _lb.state     = 'waddling'
                _lb.direction = _edge_dir
                _lb.facing    = _edge_dir
                _lb.vx        = _edge_dir * 0.55
            elif _lb.state == 'waddling' and abs(_lb.x - _lb.home_x) > 180:
                # Waddling: drift back toward home rock if too far
                _lb.direction = 1 if _lb.home_x > _lb.x else -1
                _lb.facing    = _lb.direction
                _lb.vx        = _lb.direction * 0.38

            # Hard screen bounds for all moving states (skipped while leaving so
            # she can walk fully off-screen instead of resting at the edge).
            if not ladybug_leaving:
                if _lb.x < 20 and _lb.vx < 0:
                    _lb.vx = 0.0; _lb.state = 'resting'
                elif _lb.x > screen_w - 20 and _lb.vx > 0:
                    _lb.vx = 0.0; _lb.state = 'resting'

        # Once she's walked off-screen, remove her and start the lockout.
        if ladybug_leaving and lazy_bugs:
            lazy_bugs[:] = [_lb for _lb in lazy_bugs if -40 < _lb.x < screen_w + 40]
            if not lazy_bugs:
                ladybug_leaving = False
                ladybug_visit_ticks = 0
                ladybug_cooldown = random.randint(LADYBUG_COOLDOWN_MIN, LADYBUG_COOLDOWN_MAX)

        # ── Snail — rare, slow crawl across the floor; tucks under a big rock ──
        if not creatures_hidden:
            if not snails:
                if snail_cooldown > 0:
                    snail_cooldown -= 1
                elif random.random() < SNAIL_SPAWN_CHANCE:
                    snails.append(make_snail(screen_w, float(screen_floor)))
            for _sn in snails:
                _sn.tick()
            if snails:
                # Despawn when fully off-screen, or when it reaches a big rock
                # (variant >= 1) — it "hides" underneath (drawn behind it).
                _big_rock_xs = [r.x for r in rocks if getattr(r, 'variant', 0) >= 1]
                _survivors = []
                for _sn in snails:
                    if _sn.x < -30 or _sn.x > screen_w + 30:
                        continue
                    if any(abs(_sn.x - rx) < 8 for rx in _big_rock_xs):
                        continue   # tucked under a rock → gone
                    _survivors.append(_sn)
                if len(_survivors) != len(snails):
                    snails[:] = _survivors
                    if not snails:
                        snail_cooldown = random.randint(SNAIL_COOLDOWN_MIN,
                                                        SNAIL_COOLDOWN_MAX)
        elif snails:
            snails.clear()

        # ── ABug3 (Friend Bug) — small pastel bugs that fly in & land on cursor ──
        _cur = overlay.mapFromGlobal(QCursor.pos())
        _cur_xy = (_cur.x(), _cur.y())
        _abug3_active = 'abug3' in inventory.get('abug_slots', [])

        if _cur_xy == cursor_last_pos:
            cursor_still_ticks += 1
        else:
            cursor_still_ticks = 0
            cursor_last_pos    = _cur_xy
        # Jitter-tolerant version (±5 px) used by the punch arming.
        if abs(_cur.x() - punch_still_ref_x) <= 5 and abs(_cur.y() - punch_still_ref_y) <= 5:
            punch_still_ticks += 1
        else:
            punch_still_ticks = 0
            punch_still_ref_x, punch_still_ref_y = _cur.x(), _cur.y()
            # Mouse moved — swarm bugs flee to edges; wanderer returns to wandering
            if friend_bugs:
                for _fb in friend_bugs:
                    if _fb.state in ('approaching', 'attached'):
                        if _fb.origin == 'wanderer':
                            # Resume wandering instead of fleeing off-screen
                            _fb.state = 'wandering'
                            _fb.wander_timer = 0
                        else:
                            # Fly off in a TRULY random direction (any angle),
                            # with a slightly varied speed, a gentle curve, and
                            # a flap-driven bob so the escape reads as organic.
                            _ang = random.uniform(0.0, math.tau)
                            _spd = random.uniform(1.8, 3.6)   # a bit slower
                            _fb.vx = math.cos(_ang) * _spd
                            _fb.vy = math.sin(_ang) * _spd
                            # Curve: small per-tick turn, random sign so some
                            # bank left and some right.
                            _fb.scatter_curve = random.choice([-1, 1]) * random.uniform(0.004, 0.022)
                            # Bob: a touch of perpendicular wobble along the path.
                            _fb.scatter_bob = random.uniform(0.3, 0.9)
                            _fb.state = 'scattering'
                friend_bug_spawn_timer = random.randint(FRIEND_BUG_INTERVAL_MIN,
                                                        FRIEND_BUG_INTERVAL_MAX)

        # ── Pester detection: count rapid cursor passes OVER Sao ─────────────
        # A "pass" = the cursor entering her zone after being outside it.
        # Wiggling the mouse back and forth over her racks up passes fast; once
        # PESTER_TRIGGER passes land within PESTER_WINDOW ticks she gets annoyed.
        if pester_decay > 0:
            pester_decay -= 1
        else:
            pester_count = 0          # window lapsed — forgive and forget
        _pc_cx = cat.x + cat.width / 2
        _over_sao = (abs(_cur.x() - _pc_cx) <= PESTER_ZONE_PX
                     and (cat.y - 18) <= _cur.y() <= (cat.y + cat.height + 14))
        if _over_sao and not pester_was_over:
            pester_count += 1
            pester_decay  = PESTER_WINDOW   # refresh the rolling window on each pass
        pester_was_over = _over_sao

        # Spawn a new friend bug while cursor stays still long enough
        if (_abug3_active
                and cursor_still_ticks >= CURSOR_STILL_TRIGGER
                and len([fb for fb in friend_bugs if fb.state != 'scattering']) < FRIEND_BUG_MAX):
            friend_bug_spawn_timer -= 1
            if friend_bug_spawn_timer <= 0:
                friend_bug_spawn_timer = random.randint(FRIEND_BUG_INTERVAL_MIN,
                                                        FRIEND_BUG_INTERVAL_MAX)
                # Random cluster offset around cursor — biased to upper hemisphere
                # (so bugs cover the top of the cursor like the reference image).
                # Use random angle in the upper half-disc and varying radius.
                _ang   = random.uniform(math.pi * 1.05, math.pi * 1.95)   # mostly above
                _r     = random.uniform(2.0, 14.0)
                _cdx   = math.cos(_ang) * _r
                _cdy   = math.sin(_ang) * _r * 0.85   # slightly squished disc
                # Spawn from a random height on either wall
                _from_left = random.random() < 0.5
                _spawn_x   = -12.0 if _from_left else float(screen_w + 12)
                _spawn_y   = random.uniform(30.0, float(screen_h - 30))
                friend_bugs.append(make_friend_bug(_spawn_x, _spawn_y, _cdx, _cdy))

        # Tick friend bugs
        for _fb in friend_bugs:
            _fb.tick(float(_cur_xy[0]), float(_cur_xy[1]))
            if _fb.state == 'attached':
                _fb.x = float(_cur_xy[0]) + _fb.cluster_dx
                _fb.y = float(_cur_xy[1]) + _fb.cluster_dy
        # Cull: wandering bugs stay forever (bounce keeps them on screen);
        # swarm/scattering bugs are culled when off-screen or alpha=0
        friend_bugs[:] = [
            fb for fb in friend_bugs
            if fb.state == 'wandering'
            or (fb.alive and -60 <= fb.x <= screen_w + 60 and -60 <= fb.y <= screen_h + 60)
        ]

        _cat_cx_bf = cat.x + cat.width / 2
        for bf in butterflies:
            _bf_prev_state = bf.state
            bf.tick()
            # Jiggle the nearest plant on land / take-off, so the flower wiggles.
            if _bf_prev_state != 'landed' and bf.state == 'landed':
                overlay.jiggle_plant_at(bf.land_x)
            elif _bf_prev_state == 'landed' and bf.state != 'landed':
                overlay.jiggle_plant_at(bf.land_x)
            if bf.state in ('drifting', 'considering', 'approaching', 'hovering'):
                # Soft horizontal bounce so they stay on screen
                edge_margin = 80
                if bf.x < edge_margin and bf.vx < 0:
                    bf.vx = abs(bf.vx)
                    bf.wander_timer = 0
                elif bf.x > screen_w - edge_margin and bf.vx > 0:
                    bf.vx = -abs(bf.vx)
                    bf.wander_timer = 0
                # Soft vertical bounds: keep mostly above floor, allow brief dips below
                taskbar_h = max(screen_h - screen_floor, 20)
                if bf.y < screen_floor - taskbar_h * 2.2:
                    bf.vy = abs(bf.vy) + 0.05   # gently push back down
                elif bf.y > screen_h - 4 and bf.vy > 0:
                    bf.vy = -abs(bf.vy)           # bounce off absolute bottom
                # ── Consider landing on a nearby flower / rock ──────────────
                # Wait until cooldown expires + fully visible.  Roll a small
                # probability per tick so landing feels organic, not robotic.
                if (bf.state == 'drifting' and _land_spots
                        and bf.alpha == 255 and bf.land_cooldown == 0
                        and random.random() < 0.0012):
                    _close = sorted(_land_spots, key=lambda s: abs(s[0] - bf.x))
                    if _close and abs(_close[0][0] - bf.x) < 450:
                        bf.land_x         = _close[0][0]
                        bf.land_y         = _close[0][1]
                        bf.land_timer     = random.randint(900, 2400)  # 15–40 s landed
                        bf.approach_timer = random.randint(120, 240)   # 2–4 s wandering toward it
                        # Per-instance landing randomness — different hover
                        # height, slight off-center hover, and a final landing
                        # x offset so no two butterflies land identically.
                        bf.hover_height   = random.uniform(18.0, 42.0)
                        bf.hover_offset_x = random.uniform(-12.0, 12.0)
                        bf.land_offset_x  = random.uniform(-4.0, 4.0)
                        # Landing style — 45% pause-above-then-descend, 55%
                        # smooth direct curve.  Eliminates the "every butterfly
                        # does the same three-phase dance" feel.
                        bf.landing_style  = 'hover' if random.random() < 0.45 else 'direct'
                        # Perpendicular swerve magnitude (with sign) so the
                        # approach path curves through the air instead of
                        # being a straight line.  Some butterflies arc wider
                        # than others; some arc the opposite way.
                        bf.approach_curve = random.choice([-1, 1]) * random.uniform(20.0, 60.0)
                        bf.state          = 'considering'
            elif bf.state == 'fleeing':
                # If Sao is now far away, butterfly calms down and resumes drifting
                if abs(bf.x - _cat_cx_bf) > screen_w // 4:
                    bf.state = 'drifting'
                    # Slow down to drifting speed
                    bf.vx = (1 if bf.vx >= 0 else -1) * random.uniform(0.3, 0.6)
                    bf.vy = random.uniform(-0.08, 0.08)
                    bf.wander_timer = random.randint(40, 80)
        for bf in butterflies:
            if bf.x <= -40 or bf.x >= screen_w + 40:
                bf.alpha = 0
        # Don't despawn cursor-attached bugs based on x-bounds (cursor may be at edge)
        butterflies[:] = [bf for bf in butterflies if bf.alive]

        # Tick macron regrow (fruitless → ready after MACRON_REGROW_TICKS)
        garden.tick_macron_regrow()
        for eff in effects:
            eff.tick()
        effects[:] = [e for e in effects if e.alive]

        # ── idle pause (sit still, skip behaviour this tick) ─────────────
        # ── Macaron treat: spawn + physics (always runs, before idle/nap) ──
        # Spawn it stuck to the cursor (pressing the hub macaron) so you can
        # drag it straight out of the window; it drops when you release.
        if overlay.consume_feed_request() and macaron is None:
            _mc0 = overlay.mapFromGlobal(QCursor.pos())
            macaron = {'x': float(_mc0.x()), 'y': float(_mc0.y()),
                       'vy': 0.0, 'state': 'cursor'}
        if macaron is not None:
            if macaron['state'] == 'cursor':
                _mc = overlay.mapFromGlobal(QCursor.pos())
                macaron['x'] = float(_mc.x())
                macaron['y'] = float(_mc.y())
                macaron['vy'] = 0.0
                try:
                    _lbtn = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
                except Exception:
                    _lbtn = False
                if not _lbtn:
                    macaron['state'] = 'falling'   # released → let it drop
            elif overlay.macaron_grabbed():
                _dp = overlay.macaron_drag_pos()
                macaron['x'] = float(_dp.x())
                macaron['y'] = float(_dp.y())
                macaron['vy'] = 0.0
                macaron['state'] = 'held'
            else:
                if macaron['state'] == 'held':
                    macaron['state'] = 'falling'
                if macaron['state'] == 'falling':
                    macaron['vy'] = min(22.0, macaron['vy'] + 1.2)
                    macaron['y'] += macaron['vy']
                    # Land on the highest surface under it — a block top in the
                    # same column, or the floor.
                    _land = float(screen_floor)
                    if blocks:
                        _mcol = math.floor(macaron['x'] / blocks_data.BLOCK_SIZE)
                        for (_bc, _br) in blocks:
                            if _bc != _mcol:
                                continue
                            _bt = float(screen_floor - (_br + 1) * blocks_data.BLOCK_SIZE)
                            if macaron['y'] >= _bt and _bt < _land:
                                _land = _bt
                    if macaron['y'] >= _land:
                        macaron['y']  = _land
                        macaron['vy'] = 0.0
                        macaron['state'] = 'resting'
            macaron['x'] = max(8.0, min(float(screen_w - 8), macaron['x']))
            overlay.set_macaron(macaron['x'], macaron['y'], 1.0)

        # ── Beach ball: spawn + floaty bounce physics (always runs) ────────
        if overlay.consume_ball_request() and ball is None:
            ball = {'x': float(screen_w * 0.5), 'y': float(screen_floor - 120),
                    'vx': 0.0, 'vy': 0.0}
        if ball is not None:
            R = BALL_RADIUS
            if overlay.ball_grabbed():
                _bp = overlay.ball_drag_pos()
                _nx, _ny = float(_bp.x()), float(_bp.y())
                ball['vx'] = (_nx - ball['x']) * 0.5   # throw velocity on release
                ball['vy'] = (_ny - ball['y']) * 0.5
                ball['x'], ball['y'] = _nx, _ny
            else:
                ball['vy'] += BALL_GRAVITY
                ball['vx'] *= BALL_AIR
                ball['vy'] *= BALL_AIR
                # A breeze nudges a near-stationary ball downwind (teeny bit).
                if abs(ball['vx']) < 0.4 and ball['y'] + R >= screen_floor - 2:
                    _wind = overlay.breeze_strength_at(ball['x']) if hasattr(overlay, 'breeze_strength_at') else 0.0
                    if _wind > 0.0:
                        ball['vx'] += _wind * 0.18                # wind from the left → drift right
                ball['x'] += ball['vx']
                ball['y'] += ball['vy']
                if ball['y'] + R >= screen_floor:               # floor bounce
                    ball['y'] = float(screen_floor - R)
                    if ball['vy'] > BALL_REST_VY:
                        # bounce back up, with a little random variation in height
                        ball['vy'] = -ball['vy'] * BALL_RESTITUTION * random.uniform(0.9, 1.18)
                    else:
                        ball['vy'] = 0.0
                    ball['vx'] *= 0.96                            # rolling friction
                if ball['x'] - R < 0:                             # walls
                    ball['x'] = float(R); ball['vx'] = abs(ball['vx']) * BALL_RESTITUTION
                elif ball['x'] + R > screen_w:
                    ball['x'] = float(screen_w - R); ball['vx'] = -abs(ball['vx']) * BALL_RESTITUTION
                if ball['y'] - R < 0:                             # ceiling
                    ball['y'] = float(R); ball['vy'] = abs(ball['vy']) * BALL_RESTITUTION
            if ball_punch_cd > 0:
                ball_punch_cd -= 1
            overlay.set_ball(ball['x'], ball['y'])

        if idle_pause > 0:
            idle_pause -= 1
            # Zero her velocity + force the idle animation, otherwise the
            # leftover run/walk speed makes the animator hold a frozen run frame
            # (or flicker between two) for the whole pause.
            cat = stop_walking(cat)
            overlay.update_state(cat, platforms, wind_up_frac=0.0,
                                 anim_override='idle')
            tick_count += 1
            return

        # ── Napping ───────────────────────────────────────────────────────
        # After a long stretch with the cursor away from her she dozes off:
        # stands still on a single interact frame with little Z's.  She wakes
        # (with a tiny startled hop) only when the cursor comes NEAR her — not
        # whenever the mouse moves somewhere else on screen.
        _curn  = overlay.mapFromGlobal(QCursor.pos())
        _ncx   = cat.x + cat.width / 2
        _ncy   = cat.y + cat.height / 2
        _near  = (abs(_curn.x() - _ncx) < NAP_NEAR_PX
                  and abs(_curn.y() - _ncy) < NAP_NEAR_PX)
        if napping:
            if (_near or overlay.is_dragging or not cat.grounded
                    or taskbar_state != 'normal' or macaron is not None):
                napping   = False
                nap_ticks = 0
                # Startled awake by the cursor → a tiny hop.
                if _near and cat.grounded and not overlay.is_dragging:
                    cat = jump(cat, power=JUMP_MIN_POWER)
                    is_jumping = True
            else:
                cat = stop_walking(cat)
                overlay.update_state(cat, platforms, anim_override='nap')
                tick_count += 1
                return
        else:
            nap_ticks = 0 if _near else nap_ticks + 1
            # Idle-triggered napping happens ONLY at night (after 9 PM, before
            # 6 AM) — during the day a parked mouse never makes her sleep; only
            # a post-macaron food coma does.  Keeps her awake while you work.
            _night = _datetime.now().hour >= 21 or _datetime.now().hour < 6
            _idle_nap = _night and nap_ticks >= NAP_AFTER_TICKS * 0.4
            _coma = False
            if meal_nap_timer > 0:
                meal_nap_timer -= 1
                if meal_nap_timer <= 0:
                    _coma = True
            if (cat.grounded and taskbar_state == 'normal' and not is_jumping
                    and not overlay.is_dragging and macaron is None
                    and (_idle_nap or _coma)):
                napping = True

        # ── Graceful turn ─────────────────────────────────────────────────
        # An occasional lifelike reversal: decelerate → stop → a little
        # backwards shuffle (moonwalk, still facing the old way) → flip.  Drives
        # her fully while active; the wander logic resumes after.
        if turn_phase and cat.grounded and taskbar_state == 'normal':
            turn_ticks += 1
            _face = None
            if turn_phase == 'decel':
                frac = min(1.0, turn_ticks / 12.0)
                cat  = replace(cat, vx=float(turn_old_dir) * _phys.WALK_SPEED * (1.0 - frac))
                _anim = 'walk'
                if turn_ticks >= 12:
                    turn_phase = 'pause'; turn_ticks = 0; cat = stop_walking(cat)
            elif turn_phase == 'pause':
                cat = stop_walking(cat)
                _anim = 'idle'
                if turn_ticks >= 8:
                    turn_phase = 'back'; turn_ticks = 0
            else:  # 'back' — moonwalk: drift the NEW way while FACING the old way
                cat   = replace(cat, vx=float(turn_new_dir) * _phys.WALK_SPEED * 0.45)
                _face = turn_old_dir
                _anim = 'walk'
                if turn_ticks >= 14:
                    wander_dir = turn_new_dir
                    turn_phase = ''
            overlay.update_state(cat, platforms, occluded=is_occluded,
                                 anim_override=_anim, face_override=_face)
            tick_count += 1
            return
        elif turn_phase:
            turn_phase = ''   # lost the floor / left normal state → abort the turn

        # ── Macaron feeding: chase / jump-at / eat the treat, but only when
        #    it's within her view range (she ignores one across the screen). ──
        if (macaron is not None and cat.grounded and taskbar_state == 'normal'
                and not is_jumping and attack_phase == ''):
            _sao_cx = cat.x + cat.width / 2
            _mdx    = macaron['x'] - _sao_cx
            if abs(_mdx) < MACARON_NOTICE_PX:
                _feet  = cat.y + cat.height
                _level = abs(macaron['y'] - _feet) < 26
                if macaron['state'] == 'resting' and abs(_mdx) < 20 and _level:
                    # Reached it on the same surface — eat (hold interact pose).
                    cat = stop_walking(cat)
                    macaron_eat_ticks += 1
                    if macaron_eat_ticks >= 36:
                        macaron = None
                        macaron_eat_ticks = 0
                        overlay.set_macaron(None, 0)
                        overlay.say(random.choice(_SAO_EAT_LINES))
                        # Full + content → a food-coma nap after a little while.
                        meal_nap_timer = random.randint(300, 540)   # ~5–9 s
                    overlay.update_state(cat, platforms, occluded=is_occluded,
                                         anim_override='interact_close')
                    tick_count += 1
                    return
                else:
                    macaron_eat_ticks = 0
                    # Follow the treat horizontally (run if it's a fair way off).
                    _run  = abs(_mdx) > 90
                    cat   = walk(cat, 1 if _mdx > 0 else -1, run=_run)
                    _anim = 'run' if _run else None
                    _above = _feet - macaron['y']   # how far above her feet it is
                    # Hop at it ONLY when she's under it AND it's within a hopeful
                    # reach height — otherwise she just trots along underneath it
                    # (so she tracks the cursor instead of bouncing in place).
                    if (macaron['state'] in ('held', 'falling', 'cursor')
                            and abs(_mdx) < 55 and 24 < _above < 170
                            and jump_cooldown == 0):
                        cat = jump(cat, power=JUMP_MIN_POWER * 1.2)
                        is_jumping   = True
                        jump_cooldown = 50
                        _anim = None
                    overlay.update_state(cat, platforms, occluded=is_occluded,
                                         anim_override=_anim)
                    tick_count += 1
                    return

        # ── jump give-up cooldown ─────────────────────────────────────────
        if jump_cooldown > 0:
            jump_cooldown -= 1

        # ── taskbar-icon re-entry cooldown ────────────────────────────────
        if icon_cooldown_ticks > 0:
            icon_cooldown_ticks -= 1

        # ── jump consideration ────────────────────────────────────────────
        # Runs every JUMP_CONSIDER_TICKS while grounded and not in cooldown.
        # Not every opportunity leads to a jump — the cat may choose to wander.
        # No jumping while occluded: the cat must walk sideways out from
        # behind the covering window first, then jump once it's visible again.
        if (cat.grounded and jump_cooldown == 0 and not is_occluded
                and taskbar_state == 'normal' and walk_around_dir == 0
                and wind_up_ticks == 0 and pending_jump_target is None):
            # Guard above: don't re-consider while already winding up — the eager
            # block re-trigger was resetting wind_up_ticks every few ticks so the
            # jump never fired and she froze in the crouch.
            # If a placed block is within reach she gets eager — consider jumps
            # much more often (and more likely) so blocks are fun to play on.
            _block_near = False
            if blocks:
                _scx  = cat.x + cat.width / 2
                _feet = cat.y + cat.height
                for _bp in _get_block_platforms():
                    if (abs((_bp.x + _bp.w / 2) - _scx) < 210
                            and -12 < (_feet - _bp.top) < JUMP_MAX_HEIGHT):
                        _block_near = True
                        break
            jump_ticks += 9 if _block_near else 1
            _thresh = (JUMP_CONSIDER_TICKS // 8) if _block_near else JUMP_CONSIDER_TICKS
            if jump_ticks >= _thresh:
                jump_ticks = 0
                if random.random() < (0.88 if _block_near else JUMP_CHANCE):
                    # If a fullscreen window covers the screen, skip jumping (edges are now walls)
                    if has_fullscreen_window(scanner.z_order, phys_screen_w, phys_screen_h):
                        pass   # walk-around disabled — edges are walls
                    else:
                        target = pick_jump_target(cat, _vis_platforms, scanner.z_order)
                        if target is not None:
                            pending_jump_target = target
                            wind_up_ticks       = WIND_UP_TICKS

        # ── wind-up countdown → fire jump ────────────────────────────────
        if wind_up_ticks > 0:
            wind_up_ticks -= 1
            if wind_up_ticks == 0 and pending_jump_target is not None:
                new_cat = aim_jump(cat, pending_jump_target)
                if new_cat is not cat:
                    cat              = new_cat
                    is_jumping       = True
                    jump_target_hwnd = pending_jump_target.hwnd
                pending_jump_target = None

        # cancel wind-up if cat gets knocked off ground mid-wind-up
        if wind_up_ticks > 0 and not cat.grounded:
            wind_up_ticks       = 0
            pending_jump_target = None

        # ── wandering & hop-down ─────────────────────────────────────────

        # Pending-plant check — if the Library Hub reconciler queued a new
        # todo to plant, and Sao is idle, pop it and go.  This sits BEFORE
        # the wander branch so planting takes priority over idle wander but
        # not over cursor-close / flower-remove / macron-harvest which
        # already grabbed her attention.
        if (taskbar_state == 'normal' and cat.grounded and not cursor_close
                and plant_pending is None and _plant_queue):
            plant_pending     = _plant_queue.pop(0)
            plant_target_x    = _pick_plant_x(screen_w, screen_floor)
            plant_anim_ticks  = 0
            taskbar_state     = 'approaching_seed'

        # Macron harvest check — proactively approach a ready stage-4 macron plant
        if taskbar_state == 'normal' and cat.grounded and not cursor_close:
            _cat_cx3 = cat.x + cat.width / 2
            for _mp in garden.plants:
                if (_mp.plant_type == PLANT_MACRON
                        and _mp.stage == PLANT_STAGES - 1
                        and not _mp.fruitless
                        and abs(_mp.x - _cat_cx3) < 840):
                    target_plant      = _mp
                    plant_target_dist = random.randint(-6, 10)
                    taskbar_state     = 'approaching_plant'
                    break

        # Butterfly proximity → start chase
        if (butterfly_chase_target is None and taskbar_state == 'normal'
                and cat.grounded and not is_jumping and not cursor_close):
            for bf in butterflies:
                if bf.state == 'drifting' and abs(bf.x - (cat.x + cat.width/2)) < screen_w // 6:
                    butterfly_chase_target = bf
                    butterfly_chase_ticks  = 0
                    butterfly_hop_count    = 0
                    butterfly_target_speed = 0.0
                    chase_dir = 1 if bf.x > cat.x + cat.width / 2 else -1
                    # Two tiers: 10% catchable (slow), 90% escape (faster than Sao)
                    # Sao's run = ~1.42 px/tick — escape tier must stay above that
                    if random.random() < 0.10:
                        butterfly_target_speed = random.uniform(0.30, 0.50)  # catchable
                        butterfly_catchable = True
                    else:
                        butterfly_target_speed = random.uniform(1.9, 2.6)    # escape
                        butterfly_catchable = False
                    bf.vx = chase_dir * 0.35   # brief slow start so chase feels real
                    bf.state = 'noticed'
                    break

        # walk-around disabled (edges are walls) — force-clear if ever set
        if walk_around_dir != 0:
            walk_around_dir = 0

        # ── seeking_icon: stand still while the UIA query runs ─────────────
        elif taskbar_state == 'seeking_icon':
            cat = stop_walking(cat)
            icon_seek_ticks += 1
            _icons = _icon_query['icons']
            if _icons is not None:
                # Query finished. Pick a RANDOM running app so she visits
                # different ones (picking 'nearest' always landed on the same
                # icon — usually Edge — since she tends to wander to one spot).
                if _icons:
                    work_icon = random.choice(_icons)
                    taskbar_state = 'walking_to_icon'
                else:
                    work_icon     = None
                    taskbar_state = 'at_bottom'
            elif icon_seek_ticks > ICON_SEEK_TIMEOUT:
                # Query is taking too long / hung — give up and resume wandering.
                work_icon     = None
                taskbar_state = 'at_bottom'

        # ── walking_to_icon: stroll to the icon, fading as she steps in ────
        elif taskbar_state == 'walking_to_icon' and work_icon is not None:
            target_cx = work_icon['cx']
            cat_cx    = cat.x + cat.width / 2
            dist      = target_cx - cat_cx
            # Fade out as she nears the centre (1.0 far → 0.0 at centre), eased
            # with a smoothstep so the fade glides instead of ramping linearly.
            _f = min(1.0, abs(dist) / ICON_FADE_DIST)
            overlay.set_cat_enter_alpha(_f * _f * (3.0 - 2.0 * _f))
            if abs(dist) <= ICON_WALK_SPEED + 0.5:
                # Fully inside — hide her, drop the teal bar, start the timer.
                cat       = stop_walking(cat)
                overlay.set_cat_enter_alpha(0.0)
                overlay.set_cat_working(True)
                overlay.set_work_icon_bar((int(work_icon['cx']),
                                           int(work_icon['bottom'])))
                hut_ticks = random.randint(WORK_STAY_TICKS_MIN, WORK_STAY_TICKS_MAX)
                # Walk back out toward screen centre so she never fades against
                # a wall (icons near the edge could otherwise trap her).
                icon_exit_dir = -1 if work_icon['cx'] > screen_w / 2 else 1
                icon_seek_ticks   = 0       # reused as the movement-poll counter
                icon_poll_pending = False
                # Remember what window was in front when she ducked in — if the
                # user opens / switches to a window, she pops back out.
                try:
                    icon_fg_hwnd = win32gui.GetForegroundWindow()
                except Exception:
                    icon_fg_hwnd = 0
                # Seed click-edge state True so a button already held at entry
                # needs a fresh press inside her icon to pop her out.
                icon_click_prev = True
                taskbar_state = 'inside_icon'
            else:
                _dir = 1 if dist > 0 else -1
                cat  = walk(cat, _dir)

        # ── inside_icon: hidden, working; yellow bar pulses under the icon ─
        elif taskbar_state == 'inside_icon' and work_icon is not None:
            cat = stop_walking(cat)
            # Keep her parked under the icon so she re-emerges in the right spot.
            cat = replace(cat, x=float(work_icon['cx'] - cat.width / 2),
                          vx=0.0, vy=0.0)
            overlay.set_work_icon_bar((int(work_icon['cx']),
                                       int(work_icon['bottom'])))
            hut_ticks -= 1

            # She pops out ONLY when the user clicks the very taskbar icon
            # she's hiding in.  Alt-tabbing, switching tabs, or clicking some
            # OTHER app's icon used to startle her out (any foreground change
            # did) — that was far too trigger-happy.  Now we watch for a
            # left-click that lands inside her icon's rectangle.
            _icon_bumped = False
            try:
                _lmb_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
            except Exception:
                _lmb_down = False
            _lmb_click = _lmb_down and not icon_click_prev
            icon_click_prev = _lmb_down
            if _lmb_click:
                try:
                    _mx, _my = win32gui.GetCursorPos()              # physical px
                    _lx, _ly = _mx / dpi_ratio, _my / dpi_ratio     # → logical px
                    # A left-click in her icon's column, down on the taskbar,
                    # frees her.  Measured from the icon CENTRE (more robust than
                    # the raw left/right rect) with a ~one-icon tolerance.
                    if (abs(_lx - work_icon['cx']) <= 42
                            and _ly >= screen_floor - 30):
                        _icon_bumped = True
                except Exception:
                    pass

            # Watch the icon: if the user grabs and drags it around (it moves),
            # Sao also gets startled out.  We re-query its position on a worker
            # thread every so often and compare to where she ducked in.
            if icon_poll_pending and _icon_query['icons'] is not None:
                icon_poll_pending = False
                _live = _icon_query['icons']
                _match = next((d for d in _live
                               if d['name'] == work_icon['name']), None)
                if _match is None or abs(_match['cx'] - work_icon['cx']) > ICON_MOVE_POP:
                    _icon_bumped = True
                elif abs(_match['top'] - work_icon['top']) > ICON_MOVE_POP:
                    _icon_bumped = True
                else:
                    work_icon = _match   # track the icon so click-detection stays accurate
            if (not icon_poll_pending) and (not _icon_query['busy']):
                icon_seek_ticks += 1
                if icon_seek_ticks >= ICON_POLL_TICKS:
                    icon_seek_ticks   = 0
                    icon_poll_pending = True
                    _request_icon_query()

            if _icon_bumped or hut_ticks <= 0:
                # Pop her up and out of the icon with a little upward hop —
                # physics carries the arc, collision lands her back down.
                overlay.set_cat_working(False)
                overlay.set_work_icon_bar(None)
                cat = replace(cat, x=float(work_icon['cx'] - cat.width / 2),
                              vx=float(icon_exit_dir) * ICON_POP_VX,
                              vy=ICON_POP_VY, grounded=False, on_hwnd=None)
                icon_fade_ticks = 0
                icon_cooldown_ticks = ICON_COOLDOWN_TICKS   # ~1 min before re-entry
                taskbar_state   = 'exiting_icon'

        # ── exiting_icon: hop back out of the icon, fading back in ─────────
        elif taskbar_state == 'exiting_icon' and work_icon is not None:
            # Time-based ease-in fade as she arcs up (smoothstep), independent
            # of the physics arc so it always finishes cleanly.
            icon_fade_ticks += 1
            _f = min(1.0, icon_fade_ticks / ICON_FADE_FRAMES)
            overlay.set_cat_enter_alpha(_f * _f * (3.0 - 2.0 * _f))
            # Once she's fully visible AND has landed again, resume wandering.
            if icon_fade_ticks >= ICON_FADE_FRAMES and cat.grounded:
                overlay.set_cat_enter_alpha(1.0)
                work_icon      = None
                wander_dir     = icon_exit_dir
                interact_ticks = random.randint(INTERACT_TICKS_MIN, INTERACT_TICKS_MAX)
                taskbar_state  = 'at_bottom'

        # ── at-bottom: walk freely at screen_h (walk only), count down ─────
        elif taskbar_state == 'at_bottom':
            if cat.grounded:
                if cursor_close and attack_phase == '':
                    # Hover-brake works down here too (not just on the desktop).
                    cat = replace(cat, vx=cat.vx * 0.55 if abs(cat.vx) > 0.05 else 0.0)
                else:
                    if cat.x <= 1.0 and wander_dir == -1:
                        wander_dir = 1
                    elif cat.x >= screen_w - cat.width - 1.0 and wander_dir == 1:
                        wander_dir = -1
                    cat = walk(cat, wander_dir)  # walk speed only — no running at bottom
            interact_ticks -= 1
            # Occasionally duck into a real taskbar app icon to "work" — but
            # not for a while after she last left one (so she isn't constantly
            # ducking in and out), and not while the cursor is hovering her.
            if (interact_ticks <= 0 and cat.grounded and not cursor_close
                    and icon_cooldown_ticks <= 0
                    and taskbar_icons.available()
                    and random.random() < ICON_ENTER_CHANCE):
                _request_icon_query()
                icon_seek_ticks = 0
                cat             = stop_walking(cat)
                taskbar_state   = 'seeking_icon'
            elif interact_ticks <= 0 and cat.grounded:
                # Only jump back when grounded — jump() silently no-ops if airborne,
                # which would flip taskbar_state while leaving her below the floor.
                power = math.sqrt(2 * GRAVITY * max(screen_h - screen_floor, 10)) * 1.2
                cat           = jump(cat, power=power)
                taskbar_state = 'returning'

        # ── approaching plant: walk to plant on taskbar ───────────────────
        elif taskbar_state == 'approaching_plant' and target_plant is not None:
            if cat.grounded:
                plant_hw = PLANT_HALF_WIDTHS[target_plant.stage]
                cat_cx   = cat.x + cat.width / 2
                if cat_cx < target_plant.x:
                    # approaching from left: dist = gap between cat right edge and plant left edge
                    dist     = (target_plant.x - plant_hw) - (cat.x + cat.width)
                    approach = 1
                else:
                    # approaching from right: dist = gap between plant right edge and cat left edge
                    dist     = cat.x - (target_plant.x + plant_hw)
                    approach = -1
                if dist <= plant_target_dist:
                    cat = stop_walking(cat)
                    taskbar_state        = 'interacting_plant'
                    plant_interact_ticks = random.randint(PLANT_APPROACH_TICKS_MIN,
                                                          PLANT_APPROACH_TICKS_MAX)
                    overlay.set_active_plant(target_plant)
                else:
                    cat = walk(cat, approach)  # walk speed only at taskbar

        # ── interacting with plant: stand still, animate, count down ──────
        elif taskbar_state == 'interacting_plant':
            cat = stop_walking(cat)
            plant_interact_ticks -= 1
            if plant_interact_ticks <= 0:
                if target_plant is not None:
                    _pom_active = (hasattr(pomodoro_win, 'is_running') and pomodoro_win.is_running())
                    _tp = target_plant  # local alias so removal is safe
                    if (_tp.stage == PLANT_STAGES - 1
                            and _tp.plant_type == PLANT_MACRON
                            and not _tp.fruitless):
                        # Collect macrons from leaves; plant stays but goes fruitless
                        inventory['macrons'] = inventory.get('macrons', 0) + 1
                        _tp.fruitless = True
                        _tp.fruitless_timer = 0
                        inv_mod.save(inventory)
                        effects.append(make_collect_effect(float(_tp.x), float(screen_floor - 16)))
                    else:
                        _prev_stage = _tp.stage
                        tended = garden.tend(cat.x + cat.width / 2, pomodoro_active=_pom_active)
                        # If a flower just reached full bloom (stage 4), record it
                        if (tended is not None and tended.stage == 4
                                and _prev_stage < 4
                                and tended.plant_type == PLANT_FLOWER
                                and hub_window is not None
                                and hub_window._message_board is not None):
                            _fname = FLOWER_NAMES[tended.variant % FLOWER_VARIANT_COUNT]
                            hub_window._message_board.add_flower(_fname)
                    _save_garden()
                overlay.set_active_plant(None)
                target_plant  = None
                taskbar_state = 'normal'
                wander_ticks  = 0

        # ── approaching task flower for removal ──────────────────────────
        elif taskbar_state == 'approaching_flower':
            if flower_to_remove is None:
                taskbar_state = 'normal'
                wander_ticks  = 0
            elif cat.grounded:
                cat_cx = cat.x + cat.width / 2
                dx = flower_target_x - cat_cx
                if abs(dx) <= 18:
                    cat = stop_walking(cat)
                    taskbar_state       = 'removing_flower'
                    flower_remove_ticks = 70    # ~1.2 s of interact animation
                elif dx > 0:
                    cat = walk(cat, 1)
                else:
                    cat = walk(cat, -1)

        # ── removing task flower: interact anim → flower disappears ───────
        elif taskbar_state == 'removing_flower':
            cat = stop_walking(cat)
            flower_remove_ticks -= 1
            if flower_remove_ticks <= 0 and flower_to_remove is not None:
                task_flowers = [tf for tf in task_flowers
                                if tf.task_text != flower_to_remove]
                overlay.set_task_flowers(task_flowers)
                _save_task_flowers()
                flower_to_remove    = None
                flower_remove_ticks = 0
                taskbar_state       = 'normal'
                wander_ticks        = 0

        # ── approaching plant spot for a new flower (queued by reconciler) ─
        # Mirror of approaching_flower: Sao walks to plant_target_x, then
        # transitions to 'planting_seed' for the interact animation.
        elif taskbar_state == 'approaching_seed':
            if plant_pending is None:
                taskbar_state = 'normal'
                wander_ticks  = 0
            elif cat.grounded:
                cat_cx = cat.x + cat.width / 2
                dx = plant_target_x - cat_cx
                if abs(dx) <= 18:
                    cat = stop_walking(cat)
                    taskbar_state    = 'planting_seed'
                    plant_anim_ticks = 70    # ~1.2 s of interact animation
                elif dx > 0:
                    cat = walk(cat, 1)
                else:
                    cat = walk(cat, -1)

        # ── planting seed: interact anim → TaskFlower spawns at Sao's feet ─
        elif taskbar_state == 'planting_seed':
            cat = stop_walking(cat)
            plant_anim_ticks -= 1
            if plant_anim_ticks <= 0 and plant_pending is not None:
                from desktop_cat.garden import TaskFlower
                from datetime import datetime as _dt
                tf = TaskFlower(
                    x            = float(plant_target_x),
                    task_text    = plant_pending.get('task_text') or 'untitled',
                    due_date     = plant_pending.get('due_date') or _dt.now().isoformat(),
                    planted_date = _dt.now().isoformat(),
                    done         = False,
                    todo_id      = plant_pending.get('todo_id') or '',
                    priority     = plant_pending.get('priority') or 'normal',
                    # Sprite type (0..4 = green/blue/red/white/tall-blue).
                    # Honour the user's pick from the composer; -1 / missing
                    # → random so each todo's flower looks distinct.
                    variant      = (int(plant_pending['flower'])
                                    if isinstance(plant_pending.get('flower'), (int, float))
                                       and 0 <= int(plant_pending['flower']) <= 4
                                    else random.randint(0, 4)),
                )
                task_flowers.append(tf)
                overlay.set_task_flowers(task_flowers)
                _save_task_flowers()
                # Little sparkle burst where the new flower springs up.
                effects.append(make_collect_effect(float(plant_target_x),
                                                   float(screen_floor - 16)))
                # Flash the planted assignment on the timer pill for a moment.
                try:
                    if _island_window is not None:
                        _island_window.flash_task(tf.task_text)
                except Exception:
                    pass
                plant_pending    = None
                plant_anim_ticks = 0
                taskbar_state    = 'normal'
                wander_ticks     = 0

        # ── normal wandering / hop-down ───────────────────────────────────
        elif (cat.grounded and not is_jumping and not cursor_close
              and wind_up_ticks == 0 and taskbar_state == 'normal'
              and attack_phase == ''):

            if butterfly_chase_target is not None:
                if not butterfly_chase_target.alive:
                    butterfly_chase_target = None
                    butterfly_chase_ticks  = 0
                    butterfly_catchable    = False
                    butterfly_hop_count    = 0
                else:
                    bf  = butterfly_chase_target
                    dx  = bf.x - (cat.x + cat.width / 2)
                    chase_dir  = 1 if bf.vx >= 0 else -1
                    wander_dir = 1 if dx > 0 else -1
                    butterfly_chase_ticks += 1

                    # Ramp to tier speed — escape ramps fast (~1s), catchable slow (~3s)
                    current_spd = abs(bf.vx)
                    ramp_rate   = 0.030 if not butterfly_catchable else 0.008
                    ramp_spd    = min(butterfly_target_speed, current_spd + ramp_rate)
                    bf.vx       = chase_dir * ramp_spd

                    # Catchable butterfly: Sao gets close enough → caught, vanish
                    if butterfly_catchable and abs(dx) < 20:
                        bf.alpha = 0   # caught — vanish
                        effects.append(make_butterfly_pop(bf.x, bf.y, bf.color))
                        butterfly_chase_target = None
                        butterfly_chase_ticks  = 0
                        butterfly_catchable    = False
                        butterfly_hop_count    = 0
                        wander_run_ticks = 0
                        # Sao was sprinting — skid to a stop
                        if cat.grounded and abs(cat.vx) > 1.0:
                            skid_ticks = 48
                            skid_dir   = wander_dir
                            wander_dir = 0
                    elif butterfly_chase_ticks >= BUTTERFLY_CHASE_TICKS:
                        # Timed out — butterfly glides off at a steady pace
                        bf.vx    = chase_dir * max(abs(bf.vx), 0.8) * 1.1
                        bf.state = 'fleeing'
                        butterfly_chase_target = None
                        butterfly_chase_ticks  = 0
                        butterfly_catchable    = False
                        butterfly_hop_count    = 0
                        wander_run_ticks = 0
                        # Sao gives up — skid + brief pause so the give-up reads clearly
                        if cat.grounded and abs(cat.vx) > 1.0:
                            skid_ticks  = 52
                            skid_dir    = wander_dir
                            wander_dir  = 0
                            idle_pause  = 30   # brief stand still after giving up
                    else:
                        cat = walk(cat, wander_dir, run=True)
                        # Hop only when: Sao is close, butterfly is above her,
                        # and we haven't used up our 3 hops for this chase.
                        bf_above = screen_floor - bf.y   # px butterfly is above floor
                        cat_top  = cat.y                  # top of Sao sprite
                        bf_is_higher = bf.y < cat_top     # butterfly above Sao's head
                        if (cat.grounded
                                and butterfly_hop_count < 3
                                and bf_is_higher
                                and abs(dx) < 160
                                and bf_above > 10
                                and butterfly_chase_ticks % 55 == 28):
                            hop_h     = bf_above * 0.75
                            hop_power = math.sqrt(2 * GRAVITY * hop_h)
                            cat = jump(cat, power=hop_power)
                            # Lean forward into the jump
                            cat = replace(cat, vx=wander_dir * _phys.RUN_SPEED * 0.9)
                            butterfly_hop_count += 1

                # Skip normal wander logic entirely while chasing
                overlay.update_state(cat, platforms, occluded=is_occluded,
                                     wind_up_frac=0.0, anim_override=None,
                                     chasing_butterfly=(butterfly_chase_target is not None))
                tick_count += 1
                return

            # Force direction reversal at screen edges — sometimes with a
            # graceful turn (she's "next to a wall"), otherwise an instant flip.
            if cat.x <= 1.0 and wander_dir == -1:
                wander_run_ticks = 0
                if turn_phase == '' and cat.grounded and random.random() < 0.5:
                    turn_phase = 'decel'; turn_ticks = 0
                    turn_old_dir = -1; turn_new_dir = 1
                else:
                    wander_dir = 1
            elif cat.x >= screen_w - cat.width - 1.0 and wander_dir == 1:
                wander_run_ticks = 0
                if turn_phase == '' and cat.grounded and random.random() < 0.5:
                    turn_phase = 'decel'; turn_ticks = 0
                    turn_old_dir = 1; turn_new_dir = -1
                else:
                    wander_dir = -1

            wander_ticks += 1
            if wander_ticks >= WANDER_CHANGE_TICKS:
                wander_ticks = 0
                on_floor = cat.on_hwnd is None
                r = random.random()
                if on_floor and not is_occluded and r < TASKBAR_DROP_CHANCE:
                    # Drop down to the taskbar floor and wander around for a bit.
                    cat           = replace(cat, vy=80.0, grounded=False)
                    taskbar_state = 'falling'
                    wander_dir    = random.choice([-1, 1])
                elif on_floor and not is_occluded and r < TASKBAR_DROP_CHANCE + PLANT_INTERACT_CHANCE and garden.plants:
                    # Prefer ready macron plants (they have macrons waiting to collect)
                    _ready_macrons = [p for p in garden.plants
                                      if p.plant_type == PLANT_MACRON
                                      and p.stage == PLANT_STAGES - 1
                                      and not p.fruitless]
                    if _ready_macrons:
                        target_plant = random.choice(_ready_macrons)
                    else:
                        # Walk to a plant and tend it; skip fruitless macrons (nothing to collect)
                        _tendable = [p for p in garden.plants
                                     if not (p.plant_type == PLANT_MACRON
                                             and p.stage == PLANT_STAGES - 1
                                             and p.fruitless)]
                        if not _tendable:
                            _tendable = garden.plants
                        target_plant = random.choice(_tendable)
                    # Random stop: overlap by up to 16px, or stop up to 32px away
                    # Gives all three interact rows a fair chance
                    plant_target_dist = random.randint(-6, 10)
                    taskbar_state     = 'approaching_plant'
                    wander_run_ticks  = 0
                else:
                    # 40% stop, 30% each direction; only 35% of moves become runs
                    _prev_dir  = wander_dir
                    wander_dir = random.choices([-1, 0, 1], weights=[3, 4, 3])[0]
                    # Occasionally a real reversal gets a graceful turn instead
                    # of an instant flip (random, ~20%).
                    if (wander_dir == -_prev_dir and _prev_dir != 0
                            and turn_phase == '' and cat.grounded
                            and random.random() < 0.2):
                        turn_phase = 'decel'; turn_ticks = 0
                        turn_old_dir = _prev_dir; turn_new_dir = wander_dir
                    if wander_dir != 0:
                        is_run_trip = random.random() < 0.35
                        if is_run_trip:
                            wander_run_ticks        = WANDER_CHANGE_TICKS - 60
                            wander_pre_walk_ticks   = 30   # walk first before run starts
                            will_skid               = random.random() < 0.65   # 65% chance of skid stop
                        else:
                            wander_run_ticks        = 0
                            wander_pre_walk_ticks   = 0
                            will_skid               = False
                        wander_accel_ticks      = 0
                        wander_walk_boost_ticks = 0
                    else:
                        wander_run_ticks        = 0
                        wander_pre_walk_ticks   = 0
                        wander_accel_ticks      = 0
                        wander_walk_boost_ticks = 0
                        will_skid               = False

            if cat.grounded:
                if wander_dir != 0:
                    if wander_pre_walk_ticks > 0:
                        # Walk phase before run starts
                        wander_pre_walk_ticks -= 1
                        cat = walk(cat, wander_dir)
                    elif wander_run_ticks > 0:
                        wander_run_ticks -= 1
                        wander_accel_ticks = min(wander_accel_ticks + 1, WANDER_ACCEL_TICKS)
                        if wander_run_ticks == 0:
                            wander_walk_boost_ticks = WANDER_BOOST_TICKS
                        # Skid stop: skip decel phase, let friction handle the slide
                        if will_skid and wander_run_ticks == WANDER_DECEL_TICKS:
                            will_skid               = False
                            skid_ticks              = 42   # ~0.7s of dust
                            skid_dir                = wander_dir
                            wander_dir              = 0
                            wander_run_ticks        = 0
                            wander_walk_boost_ticks = 0
                            wander_accel_ticks      = 0
                            # Reset wander timer so it doesn't fire mid-skid and kill the slide
                            wander_ticks            = WANDER_CHANGE_TICKS - skid_ticks - 15
                        elif wander_run_ticks < WANDER_DECEL_TICKS:
                            # Tail of run: blend run→walk speed
                            frac  = wander_run_ticks / WANDER_DECEL_TICKS  # 1→0
                            blend = _phys.WALK_SPEED + (_phys.RUN_SPEED - _phys.WALK_SPEED) * frac
                            cat   = replace(cat, vx=wander_dir * blend)
                        elif wander_accel_ticks < WANDER_ACCEL_TICKS:
                            # Head of run: blend walk→run speed
                            frac  = wander_accel_ticks / WANDER_ACCEL_TICKS  # 0→1
                            blend = _phys.WALK_SPEED + (_phys.RUN_SPEED - _phys.WALK_SPEED) * frac
                            cat   = replace(cat, vx=wander_dir * blend)
                        else:
                            cat = walk(cat, wander_dir, run=True)
                    else:
                        wander_accel_ticks = 0
                        if wander_walk_boost_ticks > 0:
                            wander_walk_boost_ticks -= 1
                            cat = replace(cat, vx=wander_dir * _phys.WALK_SPEED * 1.3)
                        else:
                            cat = walk(cat, wander_dir)

        elif cat.grounded and cursor_close and attack_phase == '':
            # Cursor is hovering her → actively brake to a gentle stop and
            # cancel any run burst, so she's easy to click instead of zipping
            # away.  (Friction alone let a run keep sliding for a while.)
            wander_run_ticks = 0
            if abs(cat.vx) > 0.05:
                cat = replace(cat, vx=cat.vx * 0.55)
            else:
                cat = replace(cat, vx=0.0)

        # ── independent descend timer — runs outside the elif chain so jumps
        #    don't starve it.  Fires when Sao has been on a window platform for
        #    a while, regardless of jump activity. ────────────────────────────
        on_window_platform = (cat.grounded and not is_occluded
                              and walk_around_dir == 0 and taskbar_state == 'normal'
                              and hop_down_ignore_hwnd is None
                              and cat.on_hwnd is not None and cat.on_hwnd > 0)
        if on_window_platform:
            descend_ticks += 1
            if descend_ticks >= 180 and random.random() < DESCEND_CHANCE / 180:
                descend_ticks = 0
                hop_down_ignore_hwnd = cat.on_hwnd
                cat        = replace(cat, vy=120.0, grounded=False)
                wander_dir = random.choice([-1, 1])
        else:
            descend_ticks = 0

        # ── skid dust ─────────────────────────────────────────────────────────
        if skid_ticks > 0:
            skid_ticks -= 1
            if cat.grounded:   # spawn every tick for denser cloud
                for _ in range(random.randint(2, 4)):
                    dust_particles.append({
                        'x':   float(cat.x + cat.width / 2 + random.uniform(-10, 10)),
                        'y':   float(cat.y + cat.height - 2),
                        'vx':  float(random.uniform(-0.6, 0.6) - skid_dir * 0.5),
                        'vy':  float(random.uniform(-1.4, -0.4)),
                        'age': 0,
                    })
        for _dp in dust_particles:
            _dp['age'] += 1
            _dp['x']   += _dp['vx']
            _dp['y']   += _dp['vy']
            _dp['vy']  += 0.05   # mild gravity drag
        dust_particles[:] = [dp for dp in dust_particles if dp['age'] < 28]

        # ── occlusion disabled — Sao is always visible ───────────────────────
        # Sao never hides behind windows; she only ever lands on the frontmost
        # window (z=0), so occlusion cannot occur in practice.
        is_occluded        = False
        _occlude_raw_ticks = 0
        occluded_ticks     = 0

        # Safety net: evict Sao from a platform that is no longer visible.
        # Since _vis_platforms is visibility-clipped, a missing platform means
        # either the window closed, moved away, or got occluded here. One check
        # covers all cases — no separate z-order lookup needed.
        if cat.grounded and cat.on_hwnd is not None:
            if find_platform(cat.on_hwnd, _vis_platforms) is None:
                cat              = replace(cat, grounded=False, vy=50.0, on_hwnd=None)
                jump_target_hwnd = None
                is_jumping       = False

        # (critter ticks moved earlier — before state machine — so they are
        #  never skipped by coin/butterfly chase early returns)

        wind_up_frac  = wind_up_ticks / WIND_UP_TICKS if wind_up_ticks > 0 else 0.0
        anim_override = None
        if taskbar_state == 'interacting_plant' and target_plant is not None:
            plant_hw = PLANT_HALF_WIDTHS[target_plant.stage]
            cat_cx   = cat.x + cat.width / 2
            if cat_cx < target_plant.x:
                # negative = cat right edge overlaps plant left edge
                dist = (target_plant.x - plant_hw) - (cat.x + cat.width)
            else:
                dist = cat.x - (target_plant.x + plant_hw)
            # dist < 0  → pixels overlapping   → row 1 (front-facing)
            # dist 0-10 → just touching/close  → row 2 (angled)
            # dist > 10 → clearly separated    → row 3 (side profile)
            if dist < 0:
                anim_override = 'interact_close'
            elif dist <= 10:
                anim_override = 'interact_mid'
            else:
                anim_override = 'interact_far'
        elif taskbar_state == 'removing_flower':
            anim_override = 'interact_close'   # Sao bats/pokes the flower
        elif taskbar_state == 'planting_seed':
            anim_override = 'interact_close'   # Sao pats the soil down
        # ── Falling seeds physics ─────────────────────────────────────────
        _tick_falling_seeds()

        # ── Movement sound hooks ─────────────────────────────────────────
        # Footstep + jump sounds were removed — too distracting.  (Sao now
        # only makes sound for deliberate events like the timer chime.)

        # While planting / tending a flower, keep Sao BEHIND it (the flower
        # she's working on draws in front of her); otherwise depth is random.
        if taskbar_state in ('planting_seed', 'approaching_flower',
                             'removing_flower'):
            overlay.set_gardening_flower(int(cat.x + cat.width / 2))
        else:
            overlay.set_gardening_flower(None)

        # ── Cursor punch — run over to a cursor parked low beside her, then
        #    throw a wind-up punch that knocks the cursor. ───────────────────
        if attack_cooldown > 0:
            attack_cooldown -= 1

        # Cursor knockback slide — glides then decelerates after a punch lands.
        # SetCursorPos already clamps to the desktop, so there's no manual edge
        # math here: a wrong GetSystemMetrics width in the packaged app was
        # making the old clamp fire every tick and freeze the slide.
        if abs(cursor_slide_vx) > 0.6:
            try:
                _pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(_pt))
                ctypes.windll.user32.SetCursorPos(_pt.x + int(round(cursor_slide_vx)), _pt.y)
            except Exception:
                pass
            cursor_slide_vx *= PUNCH_CURSOR_DECAY
        else:
            cursor_slide_vx = 0.0

        # 3-minute punch budget — at most PUNCH_MAX_PER_WINDOW swings, then she
        # leaves the cursor alone until the window rolls over.
        punch_window_ticks -= 1
        if punch_window_ticks <= 0:
            punch_window_ticks = PUNCH_WINDOW_TICKS
            punch_count_3min   = 0

        if attack_phase == 'punch':
            anim_override = 'attack'
            elapsed = PUNCH_ANIM_TICKS - attack_ticks
            # Body lunges forward INTO the swing, then eases back to origin.
            if elapsed >= PUNCH_SWING_ELAPSED:
                k = (elapsed - PUNCH_SWING_ELAPSED) / max(1, PUNCH_ANIM_TICKS - PUNCH_SWING_ELAPSED)
                jab = math.sin(min(1.0, k) * math.pi) * PUNCH_REACH
            else:
                jab = 0.0   # still winding up — stays planted
            cat = replace(cat, x=attack_origin_x + attack_dir * jab, vx=float(attack_dir))
            if elapsed == PUNCH_SWING_ELAPSED:
                if attack_target == 'ball':
                    if ball is not None:
                        ball['vx'] = float(attack_dir) * BALL_KICK * random.uniform(0.85, 1.25)
                        ball['vy'] = -BALL_POP * random.uniform(0.7, 1.4)   # varied height
                else:
                    cursor_slide_vx = float(attack_dir) * PUNCH_CURSOR_KICK
                    # Immediate first shove + a one-time upward pop.
                    try:
                        _hp = ctypes.wintypes.POINT()
                        ctypes.windll.user32.GetCursorPos(ctypes.byref(_hp))
                        ctypes.windll.user32.SetCursorPos(
                            _hp.x + int(attack_dir * PUNCH_CURSOR_KICK),
                            _hp.y - PUNCH_CURSOR_KICK_UP)
                    except Exception:
                        pass
            attack_ticks -= 1
            if attack_ticks <= 0:
                cat = replace(cat, x=attack_origin_x, vx=0.0)
                attack_phase = ''
                if attack_target == 'ball':
                    ball_punch_cd = BALL_PUNCH_CD
                else:
                    attack_cooldown  = PUNCH_COOLDOWN
                    punch_count_3min += 1   # used one of her 2 cursor punches
                attack_target = 'cursor'

        elif attack_phase == 'approach':
            _cat_cx = cat.x + cat.width / 2
            approach_ticks += 1
            if attack_target == 'ball':
                # Chase the bouncing ball — follow its x and wait under it, then
                # bat it once it drops low + she's close.
                if ball is None or not cat.grounded or approach_ticks > BALL_APPROACH_MAX:
                    attack_phase  = ''
                    attack_target = 'cursor'
                    attack_cooldown = 10
                    cat = stop_walking(cat)
                else:
                    _dx = ball['x'] - _cat_cx
                    _ball_low = ball['y'] + BALL_RADIUS >= screen_floor - 42
                    if abs(_dx) <= PUNCH_RANGE + BALL_RADIUS and _ball_low:
                        attack_phase    = 'punch'
                        attack_ticks    = PUNCH_ANIM_TICKS
                        attack_dir      = 1 if _dx >= 0 else -1
                        attack_origin_x = float(cat.x)
                        cat = stop_walking(cat)
                    elif abs(_dx) > 10:
                        _run = abs(_dx) > 110
                        cat = walk(cat, 1 if _dx > 0 else -1, run=_run)
                        anim_override = 'run' if _run else None
                    else:
                        cat = stop_walking(cat)   # under it, waiting for it to fall
            else:
                _cur = overlay.mapFromGlobal(QCursor.pos())
                _dx  = _cur.x() - _cat_cx
                if (not cat.grounded or approach_ticks > PUNCH_APPROACH_MAX
                        or _cur.y() < screen_floor - PUNCH_FLOOR_PX):
                    attack_phase    = ''            # cursor left the zone / gave up
                    attack_cooldown = 15
                    cat = stop_walking(cat)
                elif abs(_dx) <= PUNCH_RANGE:
                    attack_phase    = 'punch'       # close enough — swing
                    attack_ticks    = PUNCH_ANIM_TICKS
                    attack_dir      = 1 if _dx >= 0 else -1
                    attack_origin_x = float(cat.x)
                    cat = stop_walking(cat)
                else:
                    cat = walk(cat, 1 if _dx > 0 else -1, run=True)
                    anim_override = 'run'

        elif (cat.grounded and not is_jumping and attack_cooldown == 0
              and taskbar_state == 'normal' and cat.on_hwnd is None):
            # Bat a nearby ball (free play), else react to cursor pestering.
            _started = False
            if ball is not None and ball_punch_cd == 0:
                _bdx = ball['x'] - (cat.x + cat.width / 2)
                # Start chasing whenever it's within range — even while it's
                # still bouncing high — so she follows it around and waits under
                # it to bat it again.
                if abs(_bdx) < BALL_NOTICE:
                    attack_phase   = 'approach'
                    attack_target  = 'ball'
                    approach_ticks = 0
                    _started = True
            if (not _started and punch_count_3min < PUNCH_MAX_PER_WINDOW
                    and pester_count >= PESTER_TRIGGER):
                attack_phase   = 'approach'
                attack_target  = 'cursor'
                approach_ticks = 0
                pester_count   = 0
                pester_decay   = 0

        overlay.update_state(cat, platforms, occluded=is_occluded,
                             wind_up_frac=wind_up_frac,
                             anim_override=anim_override,
                             chasing_butterfly=(butterfly_chase_target is not None))
        tick_count += 1

    timer = QTimer()
    timer.timeout.connect(on_tick)

    # ── Spawn gate ───────────────────────────────────────────────────────────
    # Every launch is gated by a cute little window before Sao appears. First
    # run shows the full onboarding flow; subsequent runs show a compact
    # start window with only a SPAWN button. When SPAWN is pressed we drop
    # Sao from above and reveal the decorative sprites one by one with a
    # little plop + sound effect.

    # Ensure sound files exist (synthesized on first use)
    sounds.init()
    # Apply persisted sound_effects toggle + start ambient
    try:
        import json as _json
        _ws_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'desktop_cat', 'world_settings.json',
        )
        with open(_ws_path) as _f:
            _ws = _json.load(_f)
        sounds.set_enabled(bool(_ws.get('sound_effects', False)))
    except (OSError, ValueError):
        sounds.set_enabled(True)
    if sounds.is_enabled():
        sounds.start_ambient(volume=0.16)

    _reveal_queue: list[tuple[str, object]] = []

    def _stash_and_clear_for_reveal() -> None:
        # Snapshot then clear — overlay holds references so clear/append
        # propagates to rendering without re-calling setters.
        for r in rocks:          _reveal_queue.append(('rock',  r))
        for s in shrubs:         _reveal_queue.append(('shrub', s))
        for pl in garden.plants: _reveal_queue.append(('plant', pl))
        random.shuffle(_reveal_queue)
        rocks.clear()
        shrubs.clear()
        garden.plants.clear()

    def _pop_pos_for(kind: str, obj) -> tuple[float, float]:
        """Screen-space center for the plop burst of a revealed item."""
        if kind == 'rock':
            return obj.x, float(screen_floor - 12)
        if kind == 'shrub':
            return obj.x, float(screen_floor - 10)
        if kind == 'plant':
            return float(obj.x), float(screen_floor - 24)
        return 0.0, 0.0

    def _begin_main_loop() -> None:
        nonlocal cat
        # Pop Sao into the middle of the screen with a slight upward kick —
        # she bounces up a touch, then gravity pulls her down and collision
        # lands her on the taskbar floor.
        overlay.start_intro_drop('grey')
        drop_x = float(screen_w // 2 - CAT_W // 2)
        cat = replace(cat, x=drop_x, y=float(screen_h // 2 - CAT_H // 2),
                      vx=0.0, vy=-260.0, grounded=False)
        sounds.play('drop', volume=0.50)

        overlay.show()
        win32gui.SetWindowPos(
            int(overlay.winId()),
            win32con.HWND_TOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
        timer.start(TICK_MS)

        if _reveal_queue:
            reveal = QTimer()
            idx = [0]
            def _reveal_one() -> None:
                if idx[0] >= len(_reveal_queue):
                    reveal.stop()
                    return
                kind, obj = _reveal_queue[idx[0]]
                idx[0] += 1
                if kind == 'rock':    rocks.append(obj)
                elif kind == 'shrub': shrubs.append(obj)
                elif kind == 'plant': garden.plants.append(obj)
                # Plop burst + sound
                px, py = _pop_pos_for(kind, obj)
                effects.append(make_collect_effect(px, py))
                sounds.play('plop', volume=0.45)
            reveal.timeout.connect(_reveal_one)
            # First reveal waits a beat so Sao lands first
            QTimer.singleShot(650, _reveal_one)
            reveal.start(240)
            _begin_main_loop._reveal = reveal  # keep ref alive

    def _on_spawn(profile: dict) -> None:
        # Seed the world personality from the onboarding choice so it
        # reflects in the world settings panel too.
        try:
            import json as _json
            ws_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'desktop_cat', 'world_settings.json',
            )
            try:
                with open(ws_path) as _f:
                    ws = _json.load(_f)
            except (OSError, ValueError):
                ws = {}
            pers_map = {'calm': 0, 'medium': 1, 'active': 2}
            if profile.get('personality') in pers_map:
                ws['personality'] = pers_map[profile['personality']]
            with open(ws_path, 'w') as _f:
                _json.dump(ws, _f)
        except OSError:
            pass
        if _is_new_garden:
            # Scatter 5 starter flowers spread evenly across the screen.
            # Divide into 5 zones and pick a random x within each zone.
            _zone_w = (screen_w - 2 * _margin) // 5
            for _i in range(5):
                _x = _margin + _zone_w * _i + random.randint(_zone_w // 4, 3 * _zone_w // 4)
                garden.add_plant(_x, PLANT_FLOWER)
            _save_garden()
            # Hand them off to the reveal queue so they pop in with Sao.
            for _p in list(garden.plants):
                _reveal_queue.append(('plant', _p))
            garden.plants.clear()

        _begin_main_loop()

    # Always stash + hide; the spawn button on the gate window reveals things
    _stash_and_clear_for_reveal()
    overlay.hide()

    if user_profile.is_onboarded():
        # Returning user → no SPAWN gate; Sao just drops in right away.
        _on_spawn(dict(user_profile.load()))
    else:
        # First run still shows onboarding (it's where the profile is created).
        gate = OnboardingWindow()
        gate.finalize_requested.connect(_on_spawn)
        gate.spawn_requested.connect(_on_spawn)
        gate.show_animated()
        main._spawn_gate = gate  # type: ignore[attr-defined]

    # ── System tray icon ──────────────────────────────────────────────
    # Gives Sao a persistent "real app" presence: a paw in the tray you
    # can always click to open the hub, or right-click → Quit to exit
    # cleanly.  (The app runs windowless otherwise — setQuitOnLastWindow-
    # Closed(False) — so without this there was no obvious way to quit.)
    try:
        from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
        from PyQt6.QtGui import QIcon, QAction
        _tray_base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
        _tray_icon_path = os.path.join(_tray_base, 'desktop_cat', 'app_icon.ico')
        _tray = QSystemTrayIcon(QIcon(_tray_icon_path), parent=app)
        _tray.setToolTip('Sao — Desktop Cat')

        def _open_hub_from_tray() -> None:
            # Reuse the island's hub-opener so behaviour matches the pill.
            try:
                _open_hub_from_island()
            except Exception:
                pass

        def _quit_app() -> None:
            # Quit but KEEP stickies on screen (they're disk-backed and
            # reappear next launch).  Unpin windows + hide the cat first so
            # nothing is left stuck, then quit the event loop.
            try:
                pin_manager.unpin_all()
            except Exception:
                pass
            try:
                overlay.hide()
            except Exception:
                pass
            try:
                if _island_window is not None:
                    _island_window.hide()
            except Exception:
                pass
            app.quit()

        _menu = QMenu()
        _act_open = QAction('Open Sao', _menu)
        _act_open.triggered.connect(_open_hub_from_tray)
        _menu.addAction(_act_open)
        _menu.addSeparator()
        _act_quit = QAction('Quit Sao', _menu)
        _act_quit.triggered.connect(_quit_app)
        _menu.addAction(_act_quit)
        _tray.setContextMenu(_menu)

        # Left-click (Trigger) opens the hub; right-click shows the menu.
        def _on_tray_activated(reason) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                _open_hub_from_tray()
        _tray.activated.connect(_on_tray_activated)
        _tray.show()
        main._tray = _tray  # keep a reference alive

        # Sao's right-click menu (on the cat sprite) routes through the bus
        # to the very same open / quit handlers the tray uses.
        bus.subscribe('OPEN_HUB',  lambda _e=None: _open_hub_from_tray())
        bus.subscribe('QUIT_APP',  lambda _e=None: _quit_app())

        def _hide_all(_e=None) -> None:
            """'Hide Sao & décor' menu item → turn Focus mode on (hides Sao,
            critters, flowers, rocks).  Persisted so the hub Settings reflect
            it; turn it back off there (or via the tray → Open)."""
            try:
                with open(_ws_path) as _f:
                    _ws_now = _json.load(_f)
            except (OSError, ValueError, TypeError):
                _ws_now = {}
            _ws_now['focus_mode'] = True
            try:
                with open(_ws_path, 'w') as _f:
                    _json.dump(_ws_now, _f)
            except OSError:
                pass
            _apply_world_settings(_ws_now)
        bus.subscribe('HIDE_ALL', _hide_all)
    except Exception as _tray_exc:
        print(f'[tray] failed to create system tray icon: {_tray_exc}')

    # On exit, release every pinned window's always-on-top flag so we
    # don't leave the user's other apps stuck topmost after Sao quits.
    app.aboutToQuit.connect(pin_manager.unpin_all)
    # Remember where the hub was so it reopens there next launch.
    app.aboutToQuit.connect(lambda: _save_hub_pos(
        (lib_window.x(), lib_window.y())
        if (lib_window is not None and lib_window.isVisible())
        else hub_last_pos))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

import ctypes
import ctypes.wintypes
import os
import win32gui
import win32con
import win32process

# Our own process ID — every window owned by this PID is skipped from
# platform generation, so Sao can never land on her own hub / sub-panels /
# overlay / gate window / Qt-internal windows. This is the belt-and-suspenders
# guarantee against phantom platforms.
_OWN_PID = os.getpid()


def _is_own_process(hwnd: int) -> bool:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid == _OWN_PID
    except Exception:
        return False

from desktop_cat.collision import Platform
from desktop_cat.event_bus import EventBus
from desktop_cat.child_scanner import ChildScanner

# Set DESKTOP_CAT_DEBUG_PLATFORMS=1 to dump every eligible window + child
# platform once per scan to %TEMP%\desktop_cat_platforms.log. Used to track
# down phantom-platform bugs.
_DEBUG_PLATFORMS = os.environ.get("DESKTOP_CAT_DEBUG_PLATFORMS") == "1"
_DEBUG_LOG_PATH = os.path.join(
    os.environ.get("TEMP", os.path.expanduser("~")),
    "desktop_cat_platforms.log",
)
if _DEBUG_PLATFORMS:
    try:
        with open(_DEBUG_LOG_PATH, "w") as _f:
            _f.write("--- desktop_cat platform debug log ---\n")
    except Exception:
        pass


def _debug_log(msg: str) -> None:
    if not _DEBUG_PLATFORMS:
        return
    try:
        with open(_DEBUG_LOG_PATH, "a") as _f:
            _f.write(msg + "\n")
    except Exception:
        pass

# DwmGetWindowAttribute constants.
_DWMWA_EXTENDED_FRAME_BOUNDS = 9   # visible frame rect, excl. DWM shadow
_DWMWA_CLOAKED               = 14  # non-zero → window is hidden by DWM
                                    # (other virtual desktop, UWP suspend, etc.)
                                    # IsWindowVisible still returns True for these!


def _visible_rect(hwnd: int) -> tuple[int, int, int, int]:
    """
    Return the VISIBLE window rect (physical px), excluding the DWM
    transparent border that GetWindowRect includes on all sides.

    Falls back to GetWindowRect if DWM is unavailable.
    """
    try:
        rc = ctypes.wintypes.RECT()
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd,
            _DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rc),
            ctypes.sizeof(rc),
        )
        if hr == 0:   # S_OK
            return rc.left, rc.top, rc.right, rc.bottom
    except Exception:
        pass
    return win32gui.GetWindowRect(hwnd)

# Titles/classes to always skip
_SKIP_TITLES = {"", "Program Manager"}
_SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "DV2ControlHost"}

# Minimum visible segment width (physical px) — below this, Sao can't stand.
MIN_SEGMENT_W_PHYS = 48

# Segment synthesis: a window with multiple visible top-edge segments emits
# one Platform per segment. The first segment reuses the raw hwnd so existing
# code keeps working unchanged; later segments get a high-bit offset.
_SEGMENT_STRIDE = 1 << 40


def bottom_hwnd(hwnd: int) -> int:
    return -hwnd


def _segment_from_base(base_hwnd: int, seg_idx: int) -> int:
    """Derive a unique synthetic hwnd for segment index `seg_idx` of `base_hwnd`."""
    if seg_idx == 0:
        return base_hwnd
    sign = -1 if base_hwnd < 0 else 1
    return sign * (abs(base_hwnd) + _SEGMENT_STRIDE * seg_idx)


def _visible_segments(x1: int, x2: int,
                      occluders: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Subtract occluder x-intervals from the edge segment [x1, x2).
    Returns list of visible (left, right) sub-intervals in left-to-right order.
    """
    visible: list[tuple[int, int]] = [(x1, x2)]
    for ol, or_ in occluders:
        if or_ <= ol:
            continue
        new_visible: list[tuple[int, int]] = []
        for sl, sr in visible:
            if or_ <= sl or ol >= sr:
                new_visible.append((sl, sr))
                continue
            if ol > sl:
                new_visible.append((sl, ol))
            if or_ < sr:
                new_visible.append((or_, sr))
        visible = new_visible
        if not visible:
            break
    return visible


def _occluders_at_y(y: int, owner_z: int,
                    all_windows: list[tuple[int, int, int, int, int]],
                    z_order: dict[int, int],
                    skip_hwnd: int) -> list[tuple[int, int]]:
    """
    Collect (left, right) x-intervals of windows whose rect covers y AND whose
    z-index is strictly in front of owner_z. skip_hwnd is the edge's own window,
    which never occludes itself.
    """
    out: list[tuple[int, int]] = []
    for hwnd, l, t, r, b in all_windows:
        if hwnd == skip_hwnd:
            continue
        wz = z_order.get(hwnd)
        if wz is None or wz >= owner_z:
            continue
        if t <= y <= b:
            out.append((l, r))
    return out


def has_fullscreen_window(z_order: dict[int, int],
                          phys_w: int, phys_h: int) -> bool:
    """
    Return True if a near-frontmost window TRULY covers the whole screen —
    i.e. a real fullscreen app (game, video) that hides the taskbar.

    Maximised app windows must NOT trigger this: they cover only the work
    area (≈94 % of screen height once you subtract the taskbar), and Sao
    should still be able to walk/jump onto their title bars and edges.
    True fullscreen apps cover ≥99 % of both dimensions and overlap the
    taskbar.  Checks z ≤ 2 so a small popup in front doesn't hide it.
    """
    for hwnd, z in z_order.items():
        if z > 2:
            continue
        try:
            l, t, r, b = _visible_rect(hwnd)
            if (r - l) >= phys_w * 0.99 and (b - t) >= phys_h * 0.99:
                return True
        except Exception:
            pass
    return False


def check_occluded(cat_owner_hwnd: int, cat_cx_phys: float, cat_cy_phys: float,
                   z_order: dict[int, int]) -> bool:
    """
    Return True if a foreground window is covering the cat's centre point.

    cat_owner_hwnd – hwnd of the TOP-LEVEL window the cat stands on (positive,
                     already resolved from Platform.owner_hwnd); 0 = floor.
    cat_cx_phys    – cat centre X in physical pixels.
    cat_cy_phys    – cat centre Y in physical pixels.
    z_order        – {hwnd: z_index}, 0 = frontmost.
    """
    if not cat_owner_hwnd:
        return False  # on the floor — never occluded
    cat_z = z_order.get(cat_owner_hwnd)
    if cat_z is None:
        return False  # window not tracked (e.g. just closed)
    for hwnd, z in z_order.items():
        if z >= cat_z:
            continue  # same level or behind the cat's window
        try:
            left, top, right, bottom = _visible_rect(hwnd)
        except Exception:
            continue
        if left < cat_cx_phys < right and top < cat_cy_phys < bottom:
            return True
    return False


_VK_LBUTTON = 0x01


class ScanScheduler:
    """Decides, each tick, whether the expensive window rescan must run.

    Top-level window geometry and z-order only change in response to user
    input.  Three cheap polls (one syscall each) tell us when that could be
    happening, so we can skip the full ``EnumWindows`` + DWM sweep whenever
    the desktop is static:

      * foreground hwnd changed   → alt-tab, focus steal, a new window, an
                                    app Sao stands on going to the back
      * foreground rect changed   → the active window is being dragged,
                                    resized, or snapped
      * left mouse button down    → a drag could be in progress anywhere
                                    (title-bar grab, resize handle)

    While any of those hold we scan at ~30 Hz and keep scanning for a short
    "settle" window after they stop (so the final dropped/snapped position
    and any snap animation are captured).  When the desktop is quiet we fall
    back to a slow ~1 s safety-net rescan that still catches the rare
    background-initiated change (installer windows, toast notifications, a
    window closing on its own timer).
    """

    ACTIVE_EVERY = 2     # ticks between scans while the user is interacting (~30 Hz)
    SETTLE_TICKS = 45     # keep scanning ~0.75 s after activity stops
    IDLE_EVERY   = 60     # ~1 s safety-net rescan when nothing is happening

    def __init__(self) -> None:
        self._last_fg: int = 0
        self._last_fg_rect: tuple | None = None
        self._settle: int = 0
        self._since_scan: int = 1 << 20   # force a scan on the very first tick

    @staticmethod
    def _foreground() -> int:
        try:
            return int(win32gui.GetForegroundWindow())
        except Exception:
            return 0

    @staticmethod
    def _rect(hwnd: int) -> tuple | None:
        if not hwnd:
            return None
        try:
            return win32gui.GetWindowRect(hwnd)
        except Exception:
            return None

    @staticmethod
    def _mouse_down() -> bool:
        try:
            # High bit set → the button is currently down.
            return bool(ctypes.windll.user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
        except Exception:
            return False

    def should_scan(self) -> bool:
        """Return True if ``WindowScanner.tick()`` should run this frame."""
        self._since_scan += 1

        fg      = self._foreground()
        fg_rect = self._rect(fg)
        active  = (fg != self._last_fg
                   or fg_rect != self._last_fg_rect
                   or self._mouse_down())
        self._last_fg      = fg
        self._last_fg_rect = fg_rect

        if active:
            self._settle = self.SETTLE_TICKS

        if self._settle > 0:
            self._settle -= 1
            if self._since_scan >= self.ACTIVE_EVERY:
                self._since_scan = 0
                return True
            return False

        if self._since_scan >= self.IDLE_EVERY:
            self._since_scan = 0
            return True
        return False


class WindowScanner:
    def __init__(self, bus: EventBus, own_hwnd: int = 0,
                 extra_skip_hwnds=None):
        """
        extra_skip_hwnds – optional callable () -> set[int].  Every hwnd it
        returns is excluded from platform generation (and from the occluder
        list used for visibility clipping).  Use this to keep the cat's own
        overlay windows (hub, sub-panels…) from becoming phantom platforms.
        """
        self._bus = bus
        self._own_hwnd = own_hwnd
        self._extra_skip_hwnds = extra_skip_hwnds  # callable or None
        # _last tracks the per-window raw rect (as a Platform) for change
        # detection — keyed by real hwnd, unaffected by visibility clipping.
        self._last: dict[int, Platform] = {}
        self._child = ChildScanner()
        self._tick  = 0
        self._z_order: dict[int, int] = {}
        self._all_windows: list[tuple[int, int, int, int, int]] = []

    @property
    def z_order(self) -> dict[int, int]:
        """Current z-order snapshot. 0 = foreground."""
        return self._z_order

    # ── enumeration & eligibility ────────────────────────────────────────────

    def _enumerate(self) -> tuple[
        list[tuple[int, int, int, int, int]],
        dict[int, int],
        list[tuple[int, int, int, int, int, str]],
    ]:
        """
        Walk EnumWindows once and return:
          all_windows – [(hwnd, l, t, r, b)] for every visible non-iconic window
                        (used as occluders, even maximised ones that won't
                        themselves emit platforms).
          z_order     – {hwnd: index}, 0 = frontmost.
          eligible    – [(hwnd, l, t, r, b, title)] for windows that pass the
                        title/class/top-edge filters — these are the ones that
                        emit top & bottom platforms.
        """
        own = self._own_hwnd
        skip = self._extra_skip_hwnds() if self._extra_skip_hwnds else set()
        all_windows: list[tuple[int, int, int, int, int]] = []
        z_order: dict[int, int] = {}
        eligible: list[tuple[int, int, int, int, int, str]] = []
        # Track which all_windows entries are system shell (Progman/WorkerW/etc).
        # These stay in all_windows for occlusion math but are excluded from
        # child-platform scanning so wallpaper/icon children don't become
        # phantom ledges floating on the desktop.
        self._shell_hwnds: set[int] = set()

        def _visit(hwnd: int, _) -> None:
            if hwnd == own or hwnd in skip:
                return
            # Skip every window owned by our own process — overlay, hub,
            # sub-panels, gate, pomodoro, and any Qt-internal windows we
            # don't track in the skip set. Prevents Sao from standing on
            # her own UI even if a reference goes stale.
            if _is_own_process(hwnd):
                return
            if not win32gui.IsWindowVisible(hwnd):
                return
            if win32gui.IsIconic(hwnd):
                return
            # Skip cloaked windows — DWM hides them (other virtual desktop,
            # suspended UWP app, Xbox overlay idle state, etc.) but
            # IsWindowVisible still returns True.  Their full-screen rects would
            # act as occluders and wipe out platforms for every real window.
            try:
                _cloaked = ctypes.c_int(0)
                if (ctypes.windll.dwmapi.DwmGetWindowAttribute(
                        hwnd, _DWMWA_CLOAKED,
                        ctypes.byref(_cloaked), ctypes.sizeof(_cloaked)) == 0
                        and _cloaked.value != 0):
                    return
            except Exception:
                pass
            try:
                l, t, r, b = _visible_rect(hwnd)
            except Exception:
                return
            if r <= l or b <= t:
                return

            z_order[hwnd] = len(z_order)   # earlier = more in front
            all_windows.append((hwnd, l, t, r, b))

            try:
                cls = win32gui.GetClassName(hwnd)
            except Exception:
                return
            if cls in _SKIP_CLASSES:
                self._shell_hwnds.add(hwnd)
                return
            try:
                title = win32gui.GetWindowText(hwnd)
            except Exception:
                return
            if title in _SKIP_TITLES:
                return
            if t <= 40:
                # Maximised / near-top: don't emit its own top/bottom platforms,
                # but it still occludes anything behind it.
                return
            eligible.append((hwnd, l, t, r, b, title))

        win32gui.EnumWindows(_visit, None)
        return all_windows, z_order, eligible

    # ── platform building ────────────────────────────────────────────────────

    def _build_edge_platforms(self,
                              all_windows, z_order, eligible,
                              ) -> tuple[list[Platform], list[Platform]]:
        tops: list[Platform] = []
        bots: list[Platform] = []
        for hwnd, l, t, r, b, title in eligible:
            owner_z = z_order[hwnd]

            # Top edge
            top_occ = _occluders_at_y(t, owner_z, all_windows, z_order, hwnd)
            for idx, (sl, sr) in enumerate(_visible_segments(l, r, top_occ)):
                if sr - sl < MIN_SEGMENT_W_PHYS:
                    continue
                seg_hwnd = _segment_from_base(hwnd, idx)
                seg_title = title if idx == 0 else f"{title} #{idx}"
                tops.append(Platform(
                    hwnd=seg_hwnd,
                    x=sl, y=t, w=sr - sl, h=b - t,
                    title=seg_title,
                    owner_hwnd=hwnd,
                ))

            # Bottom edge
            bot_occ = _occluders_at_y(b, owner_z, all_windows, z_order, hwnd)
            for idx, (sl, sr) in enumerate(_visible_segments(l, r, bot_occ)):
                if sr - sl < MIN_SEGMENT_W_PHYS:
                    continue
                seg_hwnd = _segment_from_base(-hwnd, idx)
                bots.append(Platform(
                    hwnd=seg_hwnd,
                    x=sl, y=b, w=sr - sl, h=8,
                    title=f"{title} [bottom]" + ("" if idx == 0 else f" #{idx}"),
                    solid=False,
                    owner_hwnd=hwnd,
                ))
        return tops, bots

    def _clip_child_platforms(self,
                              child_platforms: list[Platform],
                              all_windows, z_order) -> list[Platform]:
        """Clip each child platform by occluders in front of its parent window."""
        out: list[Platform] = []
        for p in child_platforms:
            parent = p.owner_hwnd
            if not parent:
                out.append(p)
                continue
            owner_z = z_order.get(parent)
            if owner_z is None:
                # parent no longer visible — drop
                continue
            occ = _occluders_at_y(p.y, owner_z, all_windows, z_order, parent)
            for idx, (sl, sr) in enumerate(_visible_segments(p.x, p.x + p.w, occ)):
                if sr - sl < MIN_SEGMENT_W_PHYS:
                    continue
                seg_hwnd = _segment_from_base(p.hwnd, idx)
                out.append(Platform(
                    hwnd=seg_hwnd,
                    x=sl, y=p.y, w=sr - sl, h=p.h,
                    title=p.title if idx == 0 else f"{p.title} #{idx}",
                    solid=p.solid,
                    owner_hwnd=parent,
                ))
        return out

    # ── public API ───────────────────────────────────────────────────────────

    def scan(self) -> list[Platform]:
        """Return all (clipped) top + bottom platforms. No event diffing."""
        all_windows, z_order, eligible = self._enumerate()
        self._all_windows = all_windows
        self._z_order = z_order
        tops, bots = self._build_edge_platforms(all_windows, z_order, eligible)
        return tops + bots

    def tick(self) -> list[Platform]:
        all_windows, z_order, eligible = self._enumerate()
        self._all_windows = all_windows
        self._z_order = z_order

        # Diff on RAW per-window rects (not clipped), so events fire correctly
        # when windows genuinely open/close/move — independent of occlusion.
        current: dict[int, Platform] = {
            hwnd: Platform(hwnd=hwnd, x=l, y=t, w=r - l, h=b - t,
                           title=title, owner_hwnd=hwnd)
            for hwnd, l, t, r, b, title in eligible
        }
        prev_hwnds = set(self._last)
        curr_hwnds = set(current)

        for hwnd in curr_hwnds - prev_hwnds:
            self._bus.publish("WINDOW_OPENED", current[hwnd])
            self._child.mark_dirty(hwnd)

        for hwnd in prev_hwnds - curr_hwnds:
            self._bus.publish("WINDOW_CLOSED", self._last[hwnd])
            self._child.remove_parent(hwnd)

        for hwnd in prev_hwnds & curr_hwnds:
            p, q = self._last[hwnd], current[hwnd]
            if p.x != q.x or p.y != q.y:
                self._bus.publish("WINDOW_MOVED", {"old": p, "new": q})
                self._child.mark_dirty(hwnd)
            elif p.w != q.w or p.h != q.h:
                self._bus.publish("WINDOW_RESIZED", {"old": p, "new": q})
                self._child.mark_dirty(hwnd)

        self._last = current

        tops, bots = self._build_edge_platforms(all_windows, z_order, eligible)

        # Child platforms: scan against every visible top-level hwnd (so
        # maximised apps' children are still reachable), then clip. Exclude
        # shell windows (Progman, WorkerW, Shell_TrayWnd, DV2ControlHost) —
        # they're only in all_windows for occlusion math and their children
        # (wallpaper layers, desktop icons) would become phantom ledges.
        child_parents = [hwnd for (hwnd, *_) in all_windows
                         if hwnd not in self._shell_hwnds]
        raw_child = self._child.get_platforms(child_parents, self._tick)
        children = self._clip_child_platforms(raw_child, all_windows, z_order)
        self._tick += 1

        if _DEBUG_PLATFORMS and self._tick % 30 == 0:
            skip = self._extra_skip_hwnds() if self._extra_skip_hwnds else set()
            _debug_log(f"\n=== tick {self._tick} | own={self._own_hwnd} | skip={sorted(skip)} ===")
            _debug_log(f"all_windows ({len(all_windows)}):")
            for hwnd, l, t, r, b in all_windows:
                try:
                    cls = win32gui.GetClassName(hwnd)
                    title = win32gui.GetWindowText(hwnd)
                except Exception:
                    cls, title = "?", "?"
                _debug_log(f"  hwnd={hwnd} cls={cls!r} title={title!r} rect=({l},{t},{r},{b})")
            _debug_log(f"eligible ({len(eligible)}):")
            for hwnd, l, t, r, b, title in eligible:
                _debug_log(f"  hwnd={hwnd} title={title!r} rect=({l},{t},{r},{b})")
            _debug_log(f"top platforms ({len(tops)}):")
            for p in tops:
                _debug_log(f"  hwnd={p.hwnd} owner={p.owner_hwnd} title={p.title!r} y={p.y} x={p.x} w={p.w}")
            _debug_log(f"child platforms ({len(children)}):")
            for p in children:
                _debug_log(f"  hwnd={p.hwnd} owner={p.owner_hwnd} title={p.title!r} y={p.y} x={p.x} w={p.w}")

        return tops + bots + children

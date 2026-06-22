from unittest.mock import patch, MagicMock
from desktop_cat.window_scanner import WindowScanner
from desktop_cat.collision import Platform
from desktop_cat.event_bus import EventBus


def make_scanner() -> WindowScanner:
    return WindowScanner(bus=EventBus())


def _make_enum_patch(windows: list[tuple[int, str, str, tuple]]):
    """
    windows: list of (hwnd, title, classname, (left,top,right,bottom))
    Patches win32gui so EnumWindows iterates our fake windows.
    """
    def fake_enum(callback, extra):
        for hwnd, *_ in windows:
            callback(hwnd, extra)

    def fake_visible(hwnd):
        return True

    def fake_iconic(hwnd):
        return False

    def fake_title(hwnd):
        return next((t for h, t, *_ in windows if h == hwnd), "")

    def fake_class(hwnd):
        return next((c for h, _, c, *_ in windows if h == hwnd), "")

    def fake_rect(hwnd):
        return next((r for h, _, __, r in windows if h == hwnd), (0, 0, 0, 0))

    return {
        "win32gui.EnumWindows": fake_enum,
        "win32gui.IsWindowVisible": fake_visible,
        "win32gui.IsIconic": fake_iconic,
        "win32gui.GetWindowText": fake_title,
        "win32gui.GetClassName": fake_class,
        "win32gui.GetWindowRect": fake_rect,
    }


def with_windows(windows, fn):
    patches = _make_enum_patch(windows)
    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in patches.items()}):
        return fn()


# --- scan ---

def test_scan_returns_platforms():
    wins = [(1001, "Notepad", "Notepad", (100, 200, 400, 500))]
    result = with_windows(wins, lambda: make_scanner().scan())
    # one top + one bottom platform per window
    assert len(result) == 2
    top = next(p for p in result if p.hwnd == 1001)
    assert top.x == 100
    assert top.y == 200
    assert top.w == 300
    assert top.h == 300
    assert top.title == "Notepad"
    bottom = next(p for p in result if p.hwnd == -1001)
    assert bottom.y == 500   # window bottom = top(200) + h(300)
    assert bottom.w == 300


def test_scan_skips_empty_title():
    wins = [(1001, "", "SomeClass", (0, 0, 100, 100))]
    result = with_windows(wins, lambda: make_scanner().scan())
    assert result == []


def test_scan_skips_own_hwnd():
    wins = [(1001, "My Cat", "QWidget", (0, 0, 500, 500))]
    scanner = WindowScanner(bus=EventBus(), own_hwnd=1001)
    patches = _make_enum_patch(wins)
    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in patches.items()}):
        result = scanner.scan()
    assert result == []


def test_scan_skips_zero_size_window():
    wins = [(1001, "Ghost", "SomeClass", (100, 100, 100, 100))]
    result = with_windows(wins, lambda: make_scanner().scan())
    assert result == []


def test_scan_skips_maximized_window():
    # Maximized / near-top windows have top <= 40 (including DWM border offsets)
    wins = [(1001, "Chrome", "Chrome_WidgetWin_1", (0, 8, 1536, 1024))]
    result = with_windows(wins, lambda: make_scanner().scan())
    assert result == []


def test_scan_keeps_window_below_threshold():
    wins = [(1001, "Notepad", "Notepad", (100, 41, 600, 500))]
    result = with_windows(wins, lambda: make_scanner().scan())
    assert any(p.hwnd == 1001 for p in result)


# --- tick events ---

def test_tick_fires_window_opened():
    bus = EventBus()
    scanner = WindowScanner(bus=bus)
    opened = []
    bus.subscribe("WINDOW_OPENED", opened.append)

    wins = [(1001, "Notepad", "Notepad", (100, 200, 400, 500))]
    patches = _make_enum_patch(wins)
    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in patches.items()}):
        scanner.tick()
    bus.tick()
    assert len(opened) == 1
    assert opened[0].hwnd == 1001


def test_tick_fires_window_closed():
    bus = EventBus()
    scanner = WindowScanner(bus=bus)
    closed = []
    bus.subscribe("WINDOW_CLOSED", closed.append)

    wins = [(1001, "Notepad", "Notepad", (100, 200, 400, 500))]
    patches = _make_enum_patch(wins)
    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in patches.items()}):
        scanner.tick()  # first tick — window appears

    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in _make_enum_patch([]).items()}):
        scanner.tick()  # second tick — window gone
    bus.tick()
    assert len(closed) == 1
    assert closed[0].hwnd == 1001


def test_tick_fires_window_moved():
    bus = EventBus()
    scanner = WindowScanner(bus=bus)
    moved = []
    bus.subscribe("WINDOW_MOVED", moved.append)

    first = [(1001, "Notepad", "Notepad", (100, 200, 400, 500))]
    second = [(1001, "Notepad", "Notepad", (150, 200, 450, 500))]  # moved right 50px

    patches1 = _make_enum_patch(first)
    patches2 = _make_enum_patch(second)
    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in patches1.items()}):
        scanner.tick()
    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in patches2.items()}):
        scanner.tick()
    bus.tick()
    assert len(moved) == 1
    assert moved[0]["new"].x == 150


def test_tick_no_events_when_nothing_changes():
    bus = EventBus()
    scanner = WindowScanner(bus=bus)
    events = []
    for ev in ("WINDOW_OPENED", "WINDOW_CLOSED", "WINDOW_MOVED", "WINDOW_RESIZED"):
        bus.subscribe(ev, events.append)

    wins = [(1001, "Notepad", "Notepad", (100, 200, 400, 500))]
    patches = _make_enum_patch(wins)
    with patch.multiple("win32gui", **{k.split(".")[-1]: v for k, v in patches.items()}):
        scanner.tick()
        bus.tick()
        events.clear()  # ignore first-scan opens
        scanner.tick()
        bus.tick()
    assert events == []

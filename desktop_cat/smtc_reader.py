"""Read the currently-playing media from Windows' System Media Transport
Controls (SMTC).

THREADING / PROCESS MODEL — read before changing.

Earlier this module called WinRT synchronously from the GUI thread, which
blocked Qt's event loop for 50–300 ms whenever Spotify was actually
streaming.  Moving the polls to a background *thread* didn't fix it
because PyWinRT holds the Python GIL through its `await IAsyncOperation`
path — even a "background thread" still serialized with the GUI thread
and froze it on every poll.

The only reliable fix is a separate **process** with its own GIL.  This
module now spawns `desktop_cat/smtc_worker.py` as a child Python process
on first `get()`.  The worker polls SMTC at its own pace and atomically
writes the current snapshot to `desktop_cat/_smtc_state.json`.  The main
process reads that file with an mtime check — pure filesystem I/O, no
WinRT, no async, no GIL contention.

Transport controls (play/pause/next/previous) still hit WinRT directly
from the GUI thread because user-triggered actions are rare and one
~50 ms WinRT round-trip on a deliberate click is fine.  Steady-state
polling — which is what was hurting — is gone.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import subprocess
import sys
from typing import Any


# Transport controls still need winsdk in-process (rare path; only fires
# on user click).  Soft-fail to a no-op stub if unavailable.
try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
    )
    _HAS_WINSDK = True
except Exception:
    _HAS_WINSDK = False


_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '_smtc_state.json',
)


class SmtcReader:
    """File-backed reader.  Spawns smtc_worker.py as a child process on
    construction; that process polls SMTC and writes JSON snapshots.
    `current()` reads the JSON file with an mtime cache — typically zero
    work because the file hasn't changed between calls."""

    def __init__(self, enable: bool = True) -> None:
        self._latest: dict[str, Any] | None = None
        self._latest_mtime: float = -1.0
        self._available = _HAS_WINSDK and enable
        self._ctrl_loop: asyncio.AbstractEventLoop | None = None
        self._proc: subprocess.Popen | None = None
        if self._available:
            try:
                self._ctrl_loop = asyncio.new_event_loop()
            except Exception:
                pass
            self._spawn_worker()

    def _spawn_worker(self) -> None:
        """Launch the SMTC polling subprocess.  Detached enough that it
        won't block the main process if it hangs, but inherits stdio
        nothing so it can't spam our console either.  Runs at
        BELOW_NORMAL priority so it can't compete with the main app's
        GUI thread for CPU when Windows is busy."""
        try:
            py = sys.executable or 'py'
            # Windows creation flags
            CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000 if sys.platform == 'win32' else 0
            flags = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
            self._proc = subprocess.Popen(
                [py, '-m', 'desktop_cat.smtc_worker'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                creationflags=flags,
            )
            atexit.register(self._kill_worker)
        except Exception as e:
            # If we can't spawn (e.g. no python in path), fall back to
            # the in-process control path only — current() will keep
            # returning None.
            self._proc = None

    def _kill_worker(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try: self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._available

    def current(self) -> dict[str, Any] | None:
        """Return the latest cached SMTC snapshot.  Reads from the worker's
        state file with an mtime cache — re-parses only when the worker has
        written something new.  Both the mtime call and the cached return
        are cheap; safe to call every poll from the GUI thread."""
        try:
            mt = os.path.getmtime(_STATE_PATH)
        except OSError:
            return self._latest
        if mt == self._latest_mtime:
            return self._latest
        try:
            with open(_STATE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            snap = data.get('snap') if isinstance(data, dict) else None
            self._latest = snap if isinstance(snap, dict) else None
            self._latest_mtime = mt
        except (OSError, ValueError):
            pass
        return self._latest

    def poll(self) -> None:
        """No-op — polling lives in the child process now."""
        return

    # ── transport controls (best-effort; not all sources support all) ──
    #
    # These run on the GUI thread because user clicks are rare and one
    # WinRT round-trip is acceptable.  They DO use winsdk in-process so
    # they're best-effort: if winsdk isn't installed they just return
    # False.  The poll path (in the worker process) is the high-volume
    # one and doesn't touch this code at all.

    def _control(self, fn_name: str) -> bool:
        if not self._available or self._ctrl_loop is None:
            return False
        async def _do():
            mgr = await _SessionManager.request_async()
            if mgr is None: return False
            session = mgr.get_current_session()
            if session is None: return False
            try:
                return await getattr(session, fn_name)()
            except Exception:
                return False
        try:
            return bool(self._ctrl_loop.run_until_complete(_do()))
        except Exception:
            return False

    def play_pause(self) -> bool: return self._control('try_toggle_play_pause_async')
    def next(self)       -> bool: return self._control('try_skip_next_async')
    def previous(self)   -> bool: return self._control('try_skip_previous_async')


# Module-level singleton.  Spawning the subprocess is deferred to first
# get() call so importing this module is still free on machines without
# winsdk (and during pytest collection).
_INSTANCE: SmtcReader | None = None


def get() -> SmtcReader:
    """Lazy singleton.  Reads the music lane pref on first call — if
    music is disabled, returns a stub reader with no subprocess spawned.
    This gives the user a hard kill switch for SMTC entirely: set
    `lanes.music = false` in desktop_cat/island.json and SMTC won't
    touch the system at all on next launch.  Useful for diagnosing
    whether music polling is actually the lag source on a given machine.
    """
    global _INSTANCE
    if _INSTANCE is None:
        enable = True
        try:
            from desktop_cat import island_data
            prefs = island_data.load()
            enable = bool(prefs.get('lanes', {}).get('music', True))
        except Exception:
            pass
        _INSTANCE = SmtcReader(enable=enable)
    return _INSTANCE

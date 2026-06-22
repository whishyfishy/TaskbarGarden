"""SMTC poller — standalone child process.

Runs as `py -3.12 -m desktop_cat.smtc_worker`.  Polls Windows SMTC every
N seconds and writes the current snapshot as JSON to a file the main
process reads.  Lives in its OWN Python interpreter so its GIL is
completely independent of the main app's — which means WinRT's
async-but-GIL-holding calls can't stall the main app's GUI thread even
when Spotify is actively producing metadata.

The previous in-thread approach didn't work because PyWinRT holds the
GIL through its `await IAsyncOperation` path, so a "background thread"
in the same process still froze the GUI thread on every poll.  Separate
process is the only reliable way around it.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time


_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '_smtc_state.json',
)
_TMP_PATH = _STATE_PATH + '.tmp'

_STATUS_NAMES = {
    0: 'closed', 1: 'opened', 2: 'changing',
    3: 'stopped', 4: 'playing', 5: 'paused',
}

_POLL_INTERVAL_S = 2.0


def _import_winsdk():
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as M,
        )
        return M
    except Exception:
        return None


async def _read_one(M):
    """Return the current SMTC snapshot or None.  Catches all exceptions
    so a transient WinRT error doesn't kill the worker."""
    try:
        manager = await M.request_async()
        if manager is None:
            return None
        session = manager.get_current_session()
        if session is None:
            return None
        props = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
    except Exception:
        return None
    if props is None:
        return None
    try:
        status_val = int(playback.playback_status) if playback else -1
    except Exception:
        status_val = -1
    source = ''
    try:
        source = session.source_app_user_model_id or ''
    except Exception:
        pass
    return {
        'title':  (getattr(props, 'title', '')  or '').strip(),
        'artist': (getattr(props, 'artist', '') or '').strip(),
        'album':  (getattr(props, 'album_title', '') or '').strip(),
        'status': _STATUS_NAMES.get(status_val, 'unknown'),
        'source': source,
    }


def _write_state(snap: dict | None) -> None:
    """Atomic write — temp file + rename so a half-written JSON is never
    visible to the main process."""
    payload = json.dumps({'snap': snap, 'ts': time.time()})
    try:
        with open(_TMP_PATH, 'w', encoding='utf-8') as f:
            f.write(payload)
        os.replace(_TMP_PATH, _STATE_PATH)
    except OSError:
        pass


def main() -> int:
    M = _import_winsdk()
    if M is None:
        # winsdk not installed — write null state once and exit.  The main
        # app will see no music lane signal and quietly carry on.
        _write_state(None)
        return 0
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # Ensure we exit if our parent dies (e.g. main app crashes).  On
    # Windows the cleanest way is to inherit the parent's stdin and exit
    # when it closes — but Popen doesn't always wire that.  Instead poll
    # PPID periodically and exit if it changes (orphaned).
    parent_pid = os.getppid() if hasattr(os, 'getppid') else None
    while True:
        try:
            snap = loop.run_until_complete(_read_one(M))
        except Exception:
            snap = None
        _write_state(snap)
        time.sleep(_POLL_INTERVAL_S)
        # Orphan check — bail if the parent went away.
        if parent_pid is not None:
            try:
                if os.getppid() != parent_pid:
                    break
            except Exception:
                pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""
Lifetime + daily activity stats for Sao.

Nothing tracked these before. A single in-memory `Stats` singleton is bumped
from main.py's game loop and flushed to stats.json every ~10 s and on quit.

Daily buckets keep the last `_DAY_CAP` days so the hub can draw trend
charts; lifetime totals never expire.

Pure-ish: all disk access is funnelled through load()/save() so the unit
tests can point _SAVE_PATH at a tmp file.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime

_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'stats.json',
)

_DAY_CAP = 30   # keep this many days of daily/economy buckets

# Every metric the rest of the app may bump. Keeping the list explicit means
# load() can backfill new keys onto an old save file without crashing.
_METRICS = (
    'butterflies_caught',
    'coins_earned',
    'jumps',
    'distance_px',
    'distance_run_px',
    'tasks_done',
    'flowers_bloomed',
)


def _today() -> str:
    return date.today().isoformat()


def _blank() -> dict:
    return {
        'lifetime': {k: 0 for k in _METRICS} | {'playtime_sec': 0},
        'daily': {},      # 'YYYY-MM-DD' -> {metric: n, 'playtime_sec': n}
        'economy': {},    # 'YYYY-MM-DD' -> {coins, carrots, potatoes, macrons}
        'first_seen': datetime.now().isoformat(timespec='seconds'),
    }


class Stats:
    def __init__(self) -> None:
        self._d: dict = _blank()
        self._dirty = False
        self._last_playtime_mark = time.monotonic()
        self._bloom_high_water = 0
        self._tasks_done_seen = 0

    # ── persistence ───────────────────────────────────────────────────────────
    def load(self) -> 'Stats':
        try:
            with open(_SAVE_PATH, encoding='utf-8') as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        d = _blank()
        if isinstance(raw, dict):
            life = raw.get('lifetime', {})
            for k in list(d['lifetime']):
                if isinstance(life.get(k), (int, float)):
                    d['lifetime'][k] = life[k]
            if isinstance(raw.get('daily'), dict):
                d['daily'] = raw['daily']
            if isinstance(raw.get('economy'), dict):
                d['economy'] = raw['economy']
            d['first_seen'] = raw.get('first_seen', d['first_seen'])
        self._d = d
        self._last_playtime_mark = time.monotonic()
        return self

    def save(self) -> None:
        try:
            with open(_SAVE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._d, f, indent=2)
            self._dirty = False
        except OSError:
            pass

    # ── mutation ──────────────────────────────────────────────────────────────
    def _day(self) -> dict:
        return self._d['daily'].setdefault(_today(), {})

    def bump(self, metric: str, n: float = 1) -> None:
        if metric not in self._d['lifetime']:
            self._d['lifetime'][metric] = 0
        self._d['lifetime'][metric] += n
        day = self._day()
        day[metric] = day.get(metric, 0) + n
        self._dirty = True

    def add_distance(self, px: float, running: bool) -> None:
        if px <= 0:
            return
        self.bump('distance_px', px)
        if running:
            self.bump('distance_run_px', px)

    def accrue_playtime(self) -> None:
        """Fold wall-clock since the last mark into playtime totals."""
        now = time.monotonic()
        elapsed = now - self._last_playtime_mark
        self._last_playtime_mark = now
        if elapsed <= 0 or elapsed > 3600:   # ignore sleeps/clock jumps
            return
        self._d['lifetime']['playtime_sec'] += elapsed
        day = self._day()
        day['playtime_sec'] = day.get('playtime_sec', 0) + elapsed
        self._dirty = True

    def snapshot_economy(self, inv: dict) -> None:
        self._d['economy'][_today()] = {
            'coins':    int(inv.get('coins', 0)),
            'carrots':  int(inv.get('carrots', 0)),
            'potatoes': int(inv.get('potatoes', 0)),
            'macrons':  int(inv.get('macrons', 0)),
        }
        self._dirty = True

    def note_bloomed(self, current_full_count: int) -> None:
        """High-water tracking: plants don't have ids, so count the increase
        in fully-bloomed flowers rather than hooking the growth tick."""
        if current_full_count > self._bloom_high_water:
            self.bump('flowers_bloomed',
                      current_full_count - self._bloom_high_water)
            self._bloom_high_water = current_full_count
        elif current_full_count < self._bloom_high_water:
            # garden shrank (harvest/delete) — lower the mark, don't subtract
            self._bloom_high_water = current_full_count

    def note_tasks_done(self, done_count: int) -> None:
        if done_count > self._tasks_done_seen:
            self.bump('tasks_done', done_count - self._tasks_done_seen)
        self._tasks_done_seen = max(self._tasks_done_seen, done_count)

    # ── periodic flush ────────────────────────────────────────────────────────
    def maybe_flush(self) -> None:
        self.accrue_playtime()
        self._prune()
        if self._dirty:
            self.save()

    def _prune(self) -> None:
        for bucket in ('daily', 'economy'):
            keys = sorted(self._d[bucket])
            for old in keys[:-_DAY_CAP]:
                del self._d[bucket][old]

    # ── reads (for the hub) ───────────────────────────────────────────────────
    def lifetime(self) -> dict:
        return dict(self._d['lifetime'])

    def recent(self, metric: str, days: int = 14) -> list[tuple[str, float]]:
        """Return [(label, value), ...] oldest→newest for the last N days,
        zero-filling missing days."""
        from datetime import timedelta
        out: list[tuple[str, float]] = []
        today = date.today()
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            key = d.isoformat()
            val = self._d['daily'].get(key, {}).get(metric, 0)
            out.append((d.strftime('%a'), float(val)))
        return out

    def economy_series(self, days: int = 14) -> list[tuple[str, dict]]:
        from datetime import timedelta
        out: list[tuple[str, dict]] = []
        today = date.today()
        last: dict = {}
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            snap = self._d['economy'].get(d.isoformat())
            if snap:
                last = snap
            out.append((d.strftime('%a'), dict(last)))
        return out


# Module-level singleton used by main.py.
STATS = Stats()

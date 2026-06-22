"""Canvas iCal sync — fetch, parse, classify, persist.

The Library Hub asks us to sync the user's Canvas calendar feed.  We:
  1. fetch the .ics URL (subscription feed — Canvas keeps it current
     for us, so re-fetching is enough to see new items)
  2. parse VEVENT blocks with the stdlib (RFC 5545 subset that Canvas
     actually emits — no 3rd-party calendar lib)
  3. classify each event into:
        - 'todo'    — assignments / submissions     (shown in Todo)
        - 'project' — multi-day work units          (shown in Workshop)
        - 'event'   — everything else               (shown in Calendar)
  4. dedup by UID and persist to canvas_sync.json so the front-end
     can read the categorised lists via the bridge.

All Canvas-derived items get source='canvas' so the UI can render the
white-dot "Sao added this" indicator on them.  Items Sao herself spins
up from a Canvas assignment (a workshop plan, say) carry source='sao'
and also get the dot.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'canvas_sync.json',
)

# ── Classification keywords ───────────────────────────────────────────
# HIGH-priority work — labs, quizzes, tests, summatives.  These get
# priority='high' so the UI can flag them + the taskbar flower glows
# purple as the due date nears.
_HIGH_PATTERNS = (
    'lab', 'quiz', 'test', 'exam', 'midterm', 'final',
    'summative', 'assessment', 'tut ', 'tutorial',
)
# PROJECT-y work — longer-horizon, scanned with the wider look-ahead.
_PROJECT_PATTERNS = (
    'project', 'paper', 'essay', 'thesis', 'capstone',
    'final report', 'group work', 'presentation', 'portfolio',
)
# Generic assignment hints — used only to BOOST confidence, no longer a
# gate.  Canvas assignment feeds put due items in as plain VEVENTs with
# arbitrary titles ("RQ 26", "STEM-Fluency 7"), so we must NOT require a
# keyword match or we silently drop most of the user's real work.

# ---------------------------------------------------------------------------
# iCal parsing
# ---------------------------------------------------------------------------

def _unfold(body: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with a space or tab is a
    continuation of the previous line.  Canvas wraps long DESCRIPTIONs
    aggressively so this is the difference between getting the assignment
    text and getting truncated nonsense.
    """
    raw = body.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out: list[str] = []
    for ln in raw:
        if ln.startswith((' ', '\t')) and out:
            out[-1] += ln[1:]
        else:
            out.append(ln)
    return out


def _unescape_text(s: str) -> str:
    """RFC 5545 TEXT escapes: \\n → newline, \\, → comma, \\; → semi,
    \\\\ → backslash.  Order matters — un-escape the backslash last."""
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == 'n' or nxt == 'N':
                out.append('\n')
            elif nxt in (',', ';', '\\'):
                out.append(nxt)
            else:
                out.append(c)
                out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _parse_dt(value: str) -> datetime | None:
    """Parse an iCal DTSTART/DTEND value.  Supports the three formats
    Canvas actually emits:
        20260528T140000Z   — UTC
        20260528T140000    — floating local
        20260528           — all-day (date only)
    Returns None if the format is something else (we'd rather drop the
    one weird event than crash the whole sync)."""
    value = value.strip()
    try:
        if value.endswith('Z'):
            return datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        if 'T' in value:
            return datetime.strptime(value, '%Y%m%dT%H%M%S')
        if len(value) == 8:
            d = datetime.strptime(value, '%Y%m%d')
            return d.replace(tzinfo=None)
    except ValueError:
        return None
    return None


def parse_ics(body: str) -> list[dict]:
    """Parse an .ics body string into a list of raw event dicts.

    Each dict has the keys we care about; missing properties just don't
    appear in the dict.  No classification yet — that's `classify()`.
    """
    lines = _unfold(body)
    events: list[dict] = []
    current: dict | None = None
    for ln in lines:
        if ln == 'BEGIN:VEVENT':
            current = {}
            continue
        if ln == 'END:VEVENT':
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None:
            continue
        # Split "PROP[;params]:value" — params we don't need for Canvas.
        m = re.match(r'^([A-Z][A-Z0-9-]*)(;[^:]*)?:(.*)$', ln)
        if not m:
            continue
        prop, _params, val = m.group(1), m.group(2), m.group(3)
        if prop == 'UID':
            current['uid'] = val.strip()
        elif prop == 'SUMMARY':
            current['title'] = _unescape_text(val).strip()
        elif prop == 'DESCRIPTION':
            current['description'] = _unescape_text(val).strip()
        elif prop == 'URL':
            current['url'] = val.strip()
        elif prop == 'LOCATION':
            current['location'] = _unescape_text(val).strip()
        elif prop == 'DTSTART':
            dt = _parse_dt(val)
            if dt is not None:
                current['start_iso'] = dt.isoformat()
                current['_start_dt'] = dt
                current['all_day']   = (len(val.strip()) == 8)
        elif prop == 'DTEND':
            dt = _parse_dt(val)
            if dt is not None:
                current['end_iso']  = dt.isoformat()
                current['_end_dt']  = dt
        elif prop == 'CATEGORIES':
            current['categories'] = [c.strip() for c in val.split(',') if c.strip()]
    return events


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _looks_like(title: str, patterns: tuple[str, ...]) -> bool:
    t = title.lower()
    return any(p in t for p in patterns)


def classify(ev: dict) -> str:
    """Bucket an event into 'todo' | 'project'.

    Canvas assignment feeds emit each due item as a plain VEVENT with an
    arbitrary title.  So instead of requiring a keyword (which dropped
    most real work), we keep ANYTHING with a due date and only split off
    longer-horizon 'project' items:
      • title looks project-y, OR
      • spans > 3 days (multi-day work unit)
        → 'project'
      • everything else with a date → 'todo'
    """
    title = ev.get('title', '')
    start = ev.get('_start_dt')
    end   = ev.get('_end_dt')
    if isinstance(start, datetime) and isinstance(end, datetime):
        if (end - start) >= timedelta(days=3):
            return 'project'
    if _looks_like(title, _PROJECT_PATTERNS):
        return 'project'
    return 'todo'


def priority_of(ev: dict) -> str:
    """'high' for labs / quizzes / tests / summatives, else 'normal'.
    High-priority items get a flag in the UI + a purple due-soon flower."""
    return 'high' if _looks_like(ev.get('title', ''), _HIGH_PATTERNS) else 'normal'


def _to_record(ev: dict) -> dict:
    """Strip internal `_dt` helpers and tag with source + kind + priority."""
    rec = {k: v for k, v in ev.items() if not k.startswith('_')}
    rec['source']   = 'canvas'
    rec['kind']     = classify(ev)
    rec['priority'] = priority_of(ev)
    return rec


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Return {url, last_sync_iso, events: [...]}.  Empty if no prior sync."""
    try:
        with open(_STATE_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {'events': []}
        d.setdefault('events', [])
        return d
    except (OSError, ValueError):
        return {'events': []}


def save_state(state: dict) -> None:
    try:
        with open(_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def fetch_ics(url: str, timeout: float = 12.0) -> str:
    """Download the .ics body.  Raises on network failure — caller decides
    whether to surface or swallow."""
    req = urllib.request.Request(url, headers={'User-Agent': 'sao-hub/0.1'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Sync orchestrator
# ---------------------------------------------------------------------------

def _due_dt(rec: dict) -> datetime | None:
    """Best-effort due datetime from a record's stored ISO start."""
    iso = rec.get('start_iso')
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    # Normalise to naive UTC-ish for comparison (Canvas mixes tz-aware Z
    # times and naive all-day dates).
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def _within_lookahead(rec: dict, assignment_days: int, project_days: int) -> bool:
    """Keep a record if its due date is within the look-ahead window for
    its kind.  Past-due items are kept for a short grace (2 days) so a
    just-missed assignment doesn't vanish instantly."""
    due = _due_dt(rec)
    if due is None:
        return True   # no date → keep (rare; let the UI show it)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days_until = (due - now).total_seconds() / 86400.0
    if days_until < -2:
        return False  # well past due → drop
    horizon = project_days if rec.get('kind') == 'project' else assignment_days
    return days_until <= horizon


def run_sync(url: str, assignment_days: int = 7, project_days: int = 14) -> dict:
    """Fetch, parse, classify, merge with the previous run, persist.

    Returns a summary the bridge surfaces to the front-end:
        {
          'ok':         True,
          'added':      {'event': n, 'todo': n, 'project': n},
          'total':      {'event': n, 'todo': n, 'project': n},
          'sao_added':  m,                # items Sao spawned from these
          'last_sync':  ISO timestamp,
          'event_count': raw count for debugging,
        }
    On failure: {'ok': False, 'error': '...'}.

    Dedup by UID — fresh fetches replace the stored record so edits in
    Canvas (renamed assignment, pushed-back due date) propagate.  Items
    that *vanish* from the feed are dropped from storage too, which is
    the same semantics every calendar subscription has.
    """
    if not url:
        return {'ok': False, 'error': 'no canvas url configured'}
    try:
        body = fetch_ics(url)
    except Exception as e:
        return {'ok': False, 'error': f'fetch failed: {e}'}

    raw = parse_ics(body)
    # Keep every dated item (todo OR project) — the old code required an
    # assignment keyword and silently dropped most real work ("RQ 26",
    # "STEM-Fluency 7", etc.).  Then filter by the per-kind look-ahead
    # window so the list stays relevant rather than showing the whole term.
    fresh_records = [_to_record(e) for e in raw if e.get('uid')]
    fresh_records = [r for r in fresh_records
                     if r.get('kind') in ('todo', 'project')
                     and _within_lookahead(r, assignment_days, project_days)]
    fresh_by_uid  = {r['uid']: r for r in fresh_records}

    prior = load_state()
    prior_uids = {r.get('uid') for r in prior.get('events', []) if r.get('uid')}

    # Count what's new per bucket (so the settings card can say
    # "Sao added 3 events, 5 todos, 1 workshop plan").
    added = {'event': 0, 'todo': 0, 'project': 0}
    for uid, rec in fresh_by_uid.items():
        if uid not in prior_uids:
            added[rec['kind']] = added.get(rec['kind'], 0) + 1

    total = {'event': 0, 'todo': 0, 'project': 0}
    for rec in fresh_records:
        total[rec['kind']] = total.get(rec['kind'], 0) + 1

    last_sync = datetime.now(timezone.utc).isoformat()
    state = {
        'url':          url,
        'last_sync':    last_sync,
        'events':       fresh_records,
    }
    save_state(state)

    return {
        'ok':          True,
        'added':       added,
        'total':       total,
        'sao_added':   0,    # Phase A: Sao doesn't spawn anything yet
        'last_sync':   last_sync,
        'event_count': len(fresh_records),
    }


def events_by_kind(kind: str) -> list[dict]:
    """Convenience for the bridge: all stored Canvas items of one kind."""
    state = load_state()
    return [e for e in state.get('events', []) if e.get('kind') == kind]


def all_work_items() -> list[dict]:
    """Every stored Canvas work item — todos AND projects — for the hub's
    to-do list (which is the only surface now)."""
    state = load_state()
    return [e for e in state.get('events', [])
            if e.get('kind') in ('todo', 'project')]

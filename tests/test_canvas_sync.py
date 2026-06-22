"""Tests for desktop_cat/canvas_sync.py — iCal parsing + classification."""
from __future__ import annotations

from desktop_cat import canvas_sync


# ---------------------------------------------------------------------------
# Line unfolding
# ---------------------------------------------------------------------------

def test_unfold_merges_continuation_lines():
    body = "PROP:value\n one\n two"
    out = canvas_sync._unfold(body)
    assert out == ["PROP:valueonetwo"]


def test_unfold_handles_crlf_line_endings():
    body = "A\r\nB\r\n C"
    assert canvas_sync._unfold(body) == ["A", "BC"]


# ---------------------------------------------------------------------------
# Text unescaping
# ---------------------------------------------------------------------------

def test_unescape_newline_and_comma_and_semi():
    raw = r"line1\nline2 \, comma \; semi \\ backslash"
    assert canvas_sync._unescape_text(raw) == "line1\nline2 , comma ; semi \\ backslash"


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def test_parse_dt_utc():
    dt = canvas_sync._parse_dt('20260528T140000Z')
    assert dt is not None
    assert dt.year == 2026 and dt.hour == 14
    assert dt.tzinfo is not None  # UTC


def test_parse_dt_floating_local():
    dt = canvas_sync._parse_dt('20260528T140000')
    assert dt is not None
    assert dt.tzinfo is None


def test_parse_dt_all_day():
    dt = canvas_sync._parse_dt('20260528')
    assert dt is not None
    assert dt.hour == 0


def test_parse_dt_garbage_returns_none():
    assert canvas_sync._parse_dt('not-a-date') is None


# ---------------------------------------------------------------------------
# Full VEVENT parse
# ---------------------------------------------------------------------------

_SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Canvas LMS//Instructure//EN
BEGIN:VEVENT
UID:assignment-1234@instructure.com
SUMMARY:Assignment: PHYS 121 Problem Set 4
DESCRIPTION:Complete problems 1-12\\nDue at the start of class
DTSTART:20260601T235900Z
DTEND:20260601T235900Z
URL:https://canvas.example.edu/courses/1/assignments/1234
END:VEVENT
BEGIN:VEVENT
UID:event-5678@instructure.com
SUMMARY:CSE 311 Lecture
DTSTART:20260528T143000Z
DTEND:20260528T155000Z
LOCATION:GUG 220
END:VEVENT
BEGIN:VEVENT
UID:project-9999@instructure.com
SUMMARY:Final Project: Robot Maze Solver
DTSTART:20260601T000000Z
DTEND:20260615T235900Z
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_finds_three_events():
    events = canvas_sync.parse_ics(_SAMPLE_ICS)
    assert len(events) == 3
    uids = {e['uid'] for e in events}
    assert 'assignment-1234@instructure.com' in uids
    assert 'event-5678@instructure.com'      in uids
    assert 'project-9999@instructure.com'    in uids


def test_parse_ics_extracts_properties():
    events = canvas_sync.parse_ics(_SAMPLE_ICS)
    by_uid = {e['uid']: e for e in events}
    pset = by_uid['assignment-1234@instructure.com']
    assert pset['title'] == 'Assignment: PHYS 121 Problem Set 4'
    assert 'Due at the start of class' in pset['description']
    assert pset['url'] == 'https://canvas.example.edu/courses/1/assignments/1234'
    assert pset['_start_dt'] is not None


def test_parse_ics_skips_malformed_dates_gracefully():
    body = _SAMPLE_ICS.replace('20260528T143000Z', 'BROKEN')
    events = canvas_sync.parse_ics(body)
    # Still parses the other events; the broken-date event simply lacks
    # start_iso but is otherwise present.
    by_uid = {e['uid']: e for e in events}
    broken = by_uid['event-5678@instructure.com']
    assert 'start_iso' not in broken
    assert broken['title'] == 'CSE 311 Lecture'


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_classify_assignment_titles_become_todos():
    events = canvas_sync.parse_ics(_SAMPLE_ICS)
    by_uid = {e['uid']: e for e in events}
    assert canvas_sync.classify(by_uid['assignment-1234@instructure.com']) == 'todo'


def test_classify_short_plain_event_is_todo():
    # A plain dated event with no project keyword now classifies as a
    # 'todo' (was 'event').  Canvas assignment feeds emit real work as
    # arbitrary-titled VEVENTs, so we keep everything dated and let the
    # look-ahead window decide relevance — rather than silently dropping
    # non-keyword items (which lost most of the user's real assignments).
    events = canvas_sync.parse_ics(_SAMPLE_ICS)
    by_uid = {e['uid']: e for e in events}
    assert canvas_sync.classify(by_uid['event-5678@instructure.com']) == 'todo'


def test_classify_multiday_span_is_project():
    events = canvas_sync.parse_ics(_SAMPLE_ICS)
    by_uid = {e['uid']: e for e in events}
    assert canvas_sync.classify(by_uid['project-9999@instructure.com']) == 'project'


def test_classify_short_event_with_project_keyword_is_project():
    body = _SAMPLE_ICS.replace('CSE 311 Lecture', 'Research Paper Topic Approval')
    events = canvas_sync.parse_ics(body)
    by_uid = {e['uid']: e for e in events}
    assert canvas_sync.classify(by_uid['event-5678@instructure.com']) == 'project'


# ---------------------------------------------------------------------------
# Record marshalling
# ---------------------------------------------------------------------------

def test_to_record_strips_internal_dt_and_tags_source():
    events = canvas_sync.parse_ics(_SAMPLE_ICS)
    rec = canvas_sync._to_record(events[0])
    assert rec['source'] == 'canvas'
    assert rec['kind']   in ('event', 'todo', 'project')
    assert all(not k.startswith('_') for k in rec.keys())

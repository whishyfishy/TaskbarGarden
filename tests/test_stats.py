import importlib

from desktop_cat import stats as stats_mod


def _fresh(tmp_path):
    """Reload the module with _SAVE_PATH pointed at a tmp file."""
    importlib.reload(stats_mod)
    stats_mod._SAVE_PATH = str(tmp_path / 'stats.json')
    s = stats_mod.Stats()
    return s


def test_bump_updates_lifetime_and_daily(tmp_path):
    s = _fresh(tmp_path)
    s.bump('jumps', 3)
    s.bump('jumps')
    assert s.lifetime()['jumps'] == 4
    today = s.recent('jumps', 1)
    assert today[-1][1] == 4


def test_distance_running_split(tmp_path):
    s = _fresh(tmp_path)
    s.add_distance(10, running=False)
    s.add_distance(5, running=True)
    lt = s.lifetime()
    assert lt['distance_px'] == 15
    assert lt['distance_run_px'] == 5
    s.add_distance(-3, running=True)   # negative ignored
    assert s.lifetime()['distance_px'] == 15


def test_bloom_high_water_only_counts_increase(tmp_path):
    s = _fresh(tmp_path)
    s.note_bloomed(2)
    s.note_bloomed(2)        # no change
    s.note_bloomed(5)        # +3
    s.note_bloomed(1)        # garden shrank — no negative
    s.note_bloomed(3)        # +2 (from new low water)
    assert s.lifetime()['flowers_bloomed'] == 2 + 3 + 2


def test_tasks_done_monotonic(tmp_path):
    s = _fresh(tmp_path)
    s.note_tasks_done(1)
    s.note_tasks_done(0)     # can't un-count
    s.note_tasks_done(4)
    assert s.lifetime()['tasks_done'] == 4


def test_save_load_roundtrip(tmp_path):
    s = _fresh(tmp_path)
    s.bump('coins_earned', 7)
    s.snapshot_economy({'coins': 9, 'carrots': 2, 'potatoes': 0, 'macrons': 1})
    s.save()

    s2 = stats_mod.Stats().load()
    assert s2.lifetime()['coins_earned'] == 7
    econ = s2.economy_series(1)[-1][1]
    assert econ['coins'] == 9


def test_recent_zero_fills(tmp_path):
    s = _fresh(tmp_path)
    series = s.recent('jumps', 7)
    assert len(series) == 7
    assert all(v == 0 for _, v in series)

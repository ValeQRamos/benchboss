"""Auto-swap marks (marks.py): one file per league, fail closed, every change logged."""

import datetime as dt
import json
import os
import sys

import pytest

from benchboss import lineup_log, store
from benchboss.errors import BenchbossError
from benchboss.marks import MarkStore, week_end


@pytest.fixture
def disk(session):
    """The demo league, with its local files on disk (under the test's BENCHBOSS_HOME)."""
    session.local_state = None
    return session


def roster_player(session, name):
    return next(s.player for s in session.league().me.roster if s.player.name == name)


def test_arm_writes_the_file_in_the_contract_shape(disk):
    daniels = roster_player(disk, "Dyson Daniels")
    mark = MarkStore(disk).arm(daniels, origin="tui")
    path = store.marks_path(disk.client.league_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {"v": 1, "league": disk.client.league_id, "season": disk.client.season,
                   "paused": False, "marks": {str(daniels.id): {
                       "name": "Dyson Daniels", "mode": "auto",
                       "added": "2026-11-04T15:30:00-05:00", "until": "2026-11-08",
                       "baseline": "DAY_TO_DAY", "origin": "tui"}}}
    assert mark.until == week_end(disk).isoformat() == "2026-11-08"  # Sunday: end of the week
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    loaded = MarkStore(disk).load()
    assert loaded.auto_ids() == {daniels.id} and not loaded.paused and not loaded.error


def test_modes_expiry_disarm_and_clear(disk):
    store_ = MarkStore(disk)
    daniels, white = roster_player(disk, "Dyson Daniels"), roster_player(disk, "Coby White")
    store_.arm(daniels, until=disk.today)
    store_.arm(white, "notify")
    marks = store_.load()
    assert marks.auto_ids() == {daniels.id} and marks.notify_ids() == {white.id}
    assert marks.get(daniels.id).until == "2026-11-04"
    # yesterday's mark is gone the next day
    disk._today = disk.today + dt.timedelta(days=1)
    assert set(store_.load().marks) == {white.id}
    assert store_.disarm(white.id) is True
    assert store_.disarm(white.id) is False
    disk._today = None
    store_.arm(daniels)
    assert store_.clear() == 1 and store_.load().marks == {}
    with pytest.raises(BenchbossError, match="unknown auto-swap mode"):
        store_.arm(daniels, "bench")


def test_pause_and_resume(disk):
    store_ = MarkStore(disk)
    store_.arm(roster_player(disk, "Dyson Daniels"))
    store_.set_paused(True)
    assert store_.load().paused and store_.load().marks
    store_.set_paused(False)
    assert not store_.load().paused


def test_another_season_or_league_means_no_marks(disk):
    path = store.marks_path(disk.client.league_id)
    store.write_json(path, {"v": 1, "league": disk.client.league_id, "season": 2020,
                            "paused": True, "marks": {"1": {"name": "Old", "mode": "auto"}}})
    marks = MarkStore(disk).load()
    assert marks.marks == {} and not marks.paused and not marks.error


def test_a_damaged_file_fails_closed_and_clear_starts_over(disk):
    path = store.marks_path(disk.client.league_id)
    store.private_dir(path.parent)
    path.write_text("{not json", encoding="utf-8")
    marks = MarkStore(disk).load()
    assert marks.marks == {} and "damaged" in marks.error
    with pytest.raises(BenchbossError, match="autoswap clear"):
        MarkStore(disk).arm(roster_player(disk, "Dyson Daniels"))
    assert MarkStore(disk).disarm(1) is False
    MarkStore(disk).set_paused(True)  # pausing always works
    assert MarkStore(disk).load().paused
    assert path.with_name("marks.json.damaged").read_text(encoding="utf-8") == "{not json"
    assert MarkStore(disk).clear() == 0 and MarkStore(disk).load().error == ""


def test_an_unknown_mode_in_the_file_never_writes(disk):
    path = store.marks_path(disk.client.league_id)
    store.write_json(path, {"v": 1, "league": disk.client.league_id, "season": disk.client.season,
                            "paused": False, "marks": {"7": {"name": "X", "mode": "bench"}}})
    assert MarkStore(disk).load().auto_ids() == set()


def test_every_change_goes_to_the_lineup_log(disk):
    store_ = MarkStore(disk)
    daniels = roster_player(disk, "Dyson Daniels")
    store_.arm(daniels, "notify", origin="tui")
    store_.disarm(daniels.id, origin="cli")
    store_.set_paused(True)
    store_.set_paused(False)
    recs = lineup_log.read_local(disk)
    assert [(r["event"], r["writer"], r["mode"]) for r in recs] == [
        ("arm", "tui", "attended"), ("disarm", "cli", "attended"),
        ("pause", "cli", "attended"), ("resume", "cli", "attended")]
    assert recs[0]["mark"] == "notify" and recs[0]["player"] == "Dyson Daniels"
    assert all(k in recs[0] for k in lineup_log.REQUIRED)


def test_disarm_and_pause_work_with_espn_down(disk, monkeypatch):
    daniels = roster_player(disk, "Dyson Daniels")
    MarkStore(disk).arm(daniels)
    disk._league = None

    def down(*a, **k):
        raise BenchbossError("could not reach ESPN")

    monkeypatch.setattr(disk, "league", down)
    assert MarkStore(disk).disarm(daniels.id) is True
    MarkStore(disk).set_paused(True)
    assert MarkStore(disk).load().paused
    assert [r["event"] for r in lineup_log.read_local(disk)] == ["arm", "disarm", "pause"]


def test_the_demo_keeps_marks_in_memory(session, tmp_path):
    MarkStore(session).arm(roster_player(session, "Dyson Daniels"))
    assert MarkStore(session).load().auto_ids()
    home = tmp_path / "home"
    assert not home.exists() or not any(home.rglob("*.json*"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_two_writers_do_not_lose_a_change(disk):
    """Every change is read fresh inside the lock: a second store object (another process)
    never overwrites a mark the first one just made."""
    a, b = MarkStore(disk), MarkStore(disk)
    a.arm(roster_player(disk, "Dyson Daniels"))
    b.arm(roster_player(disk, "Coby White"))
    assert len(MarkStore(disk).load().marks) == 2

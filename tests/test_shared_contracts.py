"""The shared pieces every package builds on: names, file shapes and the write path API."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
from dataclasses import replace

import pytest

from benchboss import config as config_mod
from benchboss import lineup_log, news, notify, store
from benchboss.core import guard
from benchboss.core.calendar import Game, SeasonCalendar, clock
from benchboss.core.lineup import LOCK_MARGIN, PlanOptions, plan_day, plan_gain
from benchboss.errors import BenchbossError, GuardRefused
from benchboss.espn.constants import (
    HEALTHY_STATUSES,
    INJURY_TAG,
    KNOWN_STATUSES,
    LINEUP_LOCK_INDIVIDUAL,
    OUT_STATUSES,
    RISK_STATUSES,
    status_class,
)
from benchboss.espn.models import parse_player
from benchboss.service import DiskCache, Outcome, Session
from benchboss.ui import layout
from benchboss.ui.screens import plan as plan_screen

# --- errors and statuses -------------------------------------------------------------------------


def test_guard_refused_is_exit_code_5():
    assert GuardRefused("no").exit_code == 5
    assert issubclass(GuardRefused, BenchbossError)


def test_status_classes_cover_every_known_status_once():
    assert set(INJURY_TAG) == KNOWN_STATUSES
    assert not (HEALTHY_STATUSES & RISK_STATUSES or HEALTHY_STATUSES & OUT_STATUSES
                or RISK_STATUSES & OUT_STATUSES)
    assert [status_class(s) for s in ("ACTIVE", "PROBABLE", "DAY_TO_DAY", "OUT")] == \
        ["ok", "ok", "risk", "out"]
    assert status_class(None) == status_class("") == status_class("FIFTEEN_DAY_DL") == "unknown"


def test_a_missing_injury_status_is_not_known():
    seen = parse_player({"player": {"id": 1, "fullName": "A B", "injuryStatus": "DAY_TO_DAY"}}, 2027)
    missing = parse_player({"player": {"id": 2, "fullName": "C D"}}, 2027)
    assert seen.injury_known and seen.injury_status == "DAY_TO_DAY"
    assert not missing.injury_known and missing.injury_status == "ACTIVE"  # display unchanged


def test_league_reads_the_lineup_lock_type(session):
    assert session.league().lineup_lock_type == LINEUP_LOCK_INDIVIDUAL


# --- calendar --------------------------------------------------------------------------------------

def _schedule(game: dict) -> dict:
    return {"settings": {"proTeams": [{"id": 1, "proGamesByScoringPeriod": {"1": [game]}}]}}


def test_games_keep_tbd_and_locking_flags():
    tip = int(dt.datetime(2026, 10, 20, 23, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    plain = SeasonCalendar.from_raw(_schedule({"scoringPeriodId": 1, "date": tip,
                                               "homeProTeamId": 1, "awayProTeamId": 2}))
    assert plain.game(1, 1).tbd is False and plain.game(1, 1).valid_for_locking is True
    odd = SeasonCalendar.from_raw(_schedule({"scoringPeriodId": 1, "date": tip, "homeProTeamId": 1,
                                             "awayProTeamId": 2, "startTimeTBD": True,
                                             "validForLocking": False}))
    assert odd.game(1, 1).tbd is True and odd.game(1, 1).valid_for_locking is False


def test_clock_shows_the_tip_on_the_wall_clock_of_the_zone():
    from zoneinfo import ZoneInfo

    # 7:00 PM in New York during daylight time is 23:00 UTC; Game.start keeps UTC-5
    start = dt.datetime(2026, 10, 20, 23, 0, tzinfo=dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=-5)))
    assert f"{start:%I:%M %p}" == "06:00 PM"  # what formatting Game.start directly would say
    assert clock(start, ZoneInfo("America/New_York")) == "7:00 PM"
    assert clock(start, ZoneInfo("America/Chicago")) == "6:00 PM"
    assert isinstance(Game(1, start, 1, 2), Game)


# --- the optimizer API ------------------------------------------------------------------------------

def test_plan_day_without_options_is_the_old_plan(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster = lg.me.roster
    old = plan_day(roster, lg.slot_counts, sp, cal)
    new = plan_day(roster, lg.slot_counts, sp, cal, None)
    assert [str(m) for m in old.moves] == [str(m) for m in new.moves]
    assert old.projected == new.projected
    assert PlanOptions().lock_margin == LOCK_MARGIN == dt.timedelta(minutes=3)
    assert PlanOptions().movable is None and PlanOptions().auto is False


def test_plan_gain_lives_in_core_and_the_screen_uses_it(session):
    plans = session.plan_days([session.today_period, session.today_period + 2])
    assert plan_screen.gain is plan_gain
    assert all(plan_gain(p, session.calendar) == plan_screen.gain(p, session.calendar) for p in plans)


def test_guard_codes_are_fixed():
    assert set(guard.CODES) == {f"G{i}" for i in range(1, 10)}
    assert set(guard.CODES) > guard.AUTO_ONLY
    v = guard.Violation("G1", "Dyson Daniels tipped at 7:00 PM", 7)
    assert v.fatal


# --- the write path ---------------------------------------------------------------------------------

def test_apply_plan_without_send_stops_before_the_post(session, monkeypatch):
    def boom(body):
        raise AssertionError("nothing may be sent")

    monkeypatch.setattr(session.client, "transaction", boom)
    monkeypatch.setattr(session, "current_period", lambda strict=False: session.today_period)
    lg = session.league()
    roster = [replace(s, player=replace(s.player, injury_status="ACTIVE"))
              if s.player.name == "Dyson Daniels" else s for s in lg.me.roster]
    monkeypatch.setattr(session, "roster_on", lambda period: roster)
    r = session.apply_plan(session.today_period, opts=PlanOptions(), send=False, writer="monitor")
    assert r.outcome == Outcome.WOULD_SEND and r.kind == "ROSTER" and r.plan.moves
    assert not r.status and not r.error


def test_apply_plan_reports_an_outcome(session, monkeypatch):
    monkeypatch.setattr(session, "current_period", lambda strict=False: session.today_period)
    monkeypatch.setattr(session.client, "transaction", lambda body: {"status": "EXECUTED"})
    first = session.apply_plan(session.today_period)
    assert first.outcome in (Outcome.EXECUTED, Outcome.ALREADY_OPTIMAL)
    monkeypatch.setattr(session.client, "transaction", lambda body: {"status": "FAILED_LINEUPLOCK"})
    lg = session.league()
    bench = [replace(s, slot_id=12) for s in lg.me.roster]  # everyone benched: moves to make
    monkeypatch.setattr(session, "roster_on", lambda period: bench)
    failed = session.apply_plan(session.today_period)
    assert failed.outcome == Outcome.FAILED and failed.status == "FAILED_LINEUPLOCK"
    assert failed.kind == "ROSTER" and failed.error


class _Client:
    def __init__(self, status: dict, teams: list | None = None):
        self.status, self.teams, self.calls = status, teams or [], []
        self.league_id, self.season, self.cookies = 1, 2027, None

    def league(self, *views, scoring_period=None, fantasy_filter=None, params=None):
        self.calls.append((views, scoring_period, params))
        return {"status": self.status, "teams": self.teams}


def test_current_period_strict_refuses_to_guess(session, monkeypatch):
    monkeypatch.setattr(session, "client", _Client({}))
    assert session.current_period() == session.league().scoring_period
    with pytest.raises(BenchbossError):
        session.current_period(strict=True)
    monkeypatch.setattr(session, "client", _Client({"latestScoringPeriod": 9}))
    assert session.current_period(strict=True) == 9


def test_roster_on_asks_espn_for_my_team_only(session):
    lg = session.league()
    raw = next(t for t in session.data["league"]["teams"] if t["id"] == lg.my_team_id)
    fake = _Client({}, [raw])
    real = Session(session.cfg, client=fake)
    real._league = lg
    roster = Session.roster_on(real, 3)
    assert [s.player.id for s in roster] == [s.player.id for s in lg.me.roster]
    assert fake.calls[-1][1] == 3 and ("forTeamId", lg.my_team_id) in fake.calls[-1][2]


# --- local files --------------------------------------------------------------------------------------

def test_paths_live_under_the_config_folder():
    home = config_mod.config_dir()
    assert store.marks_path(42) == home / "leagues" / "42" / "marks.json"
    assert store.monitor_path(42) == home / "leagues" / "42" / "monitor.json"
    assert store.lease_path(42) == home / "leagues" / "42" / "monitor.lock"
    assert store.logs_dir() == home / "logs"
    assert store.notify_env_path() == home / "notify.env"
    when = dt.datetime(2026, 10, 20, 19, 0)
    assert lineup_log.path_for(when) == home / "logs" / "lineup-2026-10.jsonl"


def test_json_files_are_atomic_private_and_fail_loud_when_damaged():
    path = store.marks_path(42)
    assert store.read_json(path, {"marks": {}}) == {"marks": {}}
    store.write_json(path, {"marks": {"7": {"name": "Nikola Jokić"}}})
    assert store.read_json(path)["marks"]["7"]["name"] == "Nikola Jokić"
    assert [p.name for p in path.parent.iterdir()] == ["marks.json"]  # no temp file left
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    path.write_text("{broken")
    with pytest.raises(BenchbossError, match="damaged"):
        store.read_json(path, {})


def test_jsonl_appends_and_reads_back_skipping_broken_lines():
    path = store.logs_dir() / "x.jsonl"
    store.append_jsonl(path, {"a": 1})
    with path.open("a") as f:
        f.write("not json\n")
    store.append_jsonl(path, {"b": "Dončić"})
    assert store.read_jsonl(path) == [{"a": 1}, {"b": "Dončić"}]
    assert store.read_jsonl(store.logs_dir() / "missing.jsonl") == []


def test_memory_mode_never_touches_the_disk():
    memory: dict = {}
    path = store.marks_path(42)
    store.write_json(path, {"x": [1]}, memory=memory)
    got = store.read_json(path, memory=memory)
    got["x"].append(2)  # a copy: changing it changes nothing stored
    assert store.read_json(path, memory=memory) == {"x": [1]}
    store.append_jsonl(path.with_suffix(".jsonl"), {"y": 1}, memory=memory)
    assert store.read_jsonl(path.with_suffix(".jsonl"), memory=memory) == [{"y": 1}]
    with store.locked(path, memory=memory):
        pass
    assert not config_mod.config_dir().exists()


def test_lock_waits_and_takes_over_a_stale_one():
    path = store.marks_path(42)
    with store.locked(path), pytest.raises(BenchbossError, match="busy"), \
            store.locked(path, wait=0.1):
        pass
    lock = path.with_name("marks.json.lock")
    assert not lock.exists()
    lock.write_text("123")
    old = lock.stat().st_mtime - 120
    os.utime(lock, (old, old))
    with store.locked(path, wait=0.1):
        assert lock.exists()
    assert not lock.exists()


def test_redact_hides_cookies_and_member_ids():
    swid = "{ABCDEF12-3456-7890-ABCD-EF1234567890}"
    s2 = "AEabc+def/ghi=jklmnopqrstuvwxyz"
    text = f"memberId {swid} cookie {s2} encoded {urllib.parse.quote(s2, safe='')}"
    out = store.redact(text, (s2, swid, None, "ab"))
    assert swid not in out and s2 not in out and "%2B" not in out
    assert store.redact("{11111111-2222-3333-4444-555555555555}") == store.HIDDEN


def test_disk_cache_uses_a_temp_file_per_process(tmp_path):
    cache = DiskCache(tmp_path / "c")
    cache.put("x", {"a": 1})
    assert cache.get("x", 60) == {"a": 1}
    assert [p.name for p in (tmp_path / "c").iterdir()] == ["x.json"]


# --- the lineup log ------------------------------------------------------------------------------------

def test_the_demo_logs_in_memory_only(session):
    rec = lineup_log.append(session, "monitor", "autoswap", "trial", period=16,
                            moves=[{"player_id": 1, "player": "Dyson Daniels", "from": "BE",
                                    "to": "G"}], outcome=Outcome.WOULD_SEND,
                            note=f"echo {session.client.swid}")
    assert all(k in rec for k in lineup_log.REQUIRED)
    assert rec["league"] == session.league().id and rec["mode"] == "trial"
    assert session.client.swid not in json.dumps(rec)
    assert lineup_log.read(session) == [rec]
    assert not config_mod.config_dir().exists()


def test_the_log_refuses_unknown_names(session):
    with pytest.raises(BenchbossError):
        lineup_log.record(session, "robot", "apply", "attended")
    with pytest.raises(BenchbossError):
        lineup_log.record(session, "cli", "apply", "sometimes")


def test_the_log_reads_only_this_league_across_months(session):
    session.local_state = None  # write real files under the test's BENCHBOSS_HOME
    lineup_log.append(session, "cli", "apply", "attended")
    other = lineup_log.path_for(session.now)
    store.append_jsonl(other, {"v": 1, "league": 999, "event": "apply"})
    last_month = lineup_log.path_for(session.now - dt.timedelta(days=31))
    store.append_jsonl(last_month, {"v": 1, "league": session.league().id, "event": "arm"})
    assert [r["event"] for r in lineup_log.read(session)] == ["arm", "apply"]


# --- layout, config, news, notify ---------------------------------------------------------------------

@pytest.mark.parametrize("w, h, mode, was, compact", [
    (46, 40, "auto", False, True), (79, 40, "auto", False, True), (120, 29, "auto", False, True),
    (120, 40, "auto", False, False), (120, 31, "auto", True, True), (120, 31, "auto", False, False),
    (120, 34, "auto", True, False), (46, 40, "full", False, False), (150, 54, "compact", False, True),
])
def test_compact_switch(w, h, mode, was, compact):
    assert layout.is_compact(w, h, mode, was) is compact


def test_layout_and_notify_settings(monkeypatch):
    assert config_mod.load().layout == "auto" and config_mod.load().notify == {}
    monkeypatch.setenv("BENCHBOSS_LAYOUT", "compact")
    assert config_mod.load().layout == "compact"
    monkeypatch.setenv("BENCHBOSS_LAYOUT", "tiny")
    assert config_mod.load().layout == "auto"
    monkeypatch.delenv("BENCHBOSS_LAYOUT")
    path = config_mod.config_dir() / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"layout": "full", "notify": "mac"}))
    cfg = config_mod.load()
    assert cfg.layout == "full" and cfg.notify == {}
    assert layout.LAYOUTS == config_mod.LAYOUTS
    config_mod.save(cfg)
    assert [p.name for p in path.parent.iterdir()] == ["config.json"]


def test_every_news_download_goes_through_one_seam(monkeypatch):
    calls = []
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def feed(params):
        calls.append(params)
        return {"feed": [{"id": len(calls), "type": "Rotowire", "playerId": params[0][1],
                          "published": stamp, "headline": "h"}]}

    monkeypatch.setattr(news, "_get_feed", feed)
    items = news.fetch(list(range(1, 121)), days=1)
    assert len(calls) == 3 and len(items) == 3
    from benchboss.espn import client

    assert not hasattr(client, "player_news")  # no second copy of the feed URL


def test_notify_names():
    assert notify.BACKENDS == ("mac", "ntfy", "cmd", "log")
    assert notify.default_backends() == (("mac",) if sys.platform == "darwin" else ("log",))
    note = notify.Note("Auto-swap", "Nikola Jokić is healthy", "urgent", "k")
    assert note.priority in notify.PRIORITIES
    assert issubclass(notify.NotifyError, BenchbossError)


def test_the_demo_keeps_local_state_in_memory(session):
    assert session.local_state == {} and Session.local_state is None

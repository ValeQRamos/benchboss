"""The trash radar: box scores of finished games (boxscores.py), the signals (core/radar.py)
and the screen and command on top. Nothing here touches the network: the feed is replaced at
``boxscores._get`` and the demo session has canned box scores."""

import datetime as dt
import io
import json

import pytest
from rich.cells import cell_len
from rich.console import Console

from benchboss import boxscores
from benchboss.cli import main
from benchboss.core import radar as core
from benchboss.espn.constants import (
    AST,
    BLK,
    DD,
    FGA,
    FGM,
    FTA,
    FTM,
    GS,
    MIN,
    PTS,
    REB,
    STL,
    TD,
    TO,
    TPM,
)
from benchboss.espn.models import Player, StatLine
from benchboss.ui.screens import radar as screen
from benchboss.ui.theme import DARK

DAY = dt.date(2026, 11, 6)
SCORING = {PTS: 1.0, REB: 1.0, AST: 2.0, STL: 4.0, BLK: 4.0, TO: -2.0, FGM: 2.0, FGA: -1.0,
           FTM: 1.0, FTA: -1.0, TPM: 1.0}
LABELS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF",
          "+/-"]


def athlete(pid, name, stats, starter=False, dnp=False):
    return {"athlete": {"id": str(pid), "displayName": name}, "starter": starter,
            "didNotPlay": dnp, "stats": stats}


SUMMARY = {"boxscore": {"players": [{
    "team": {"abbreviation": "WSH"},
    "statistics": [{"labels": LABELS, "athletes": [
        athlete(1, "Ace Starter", ["36", "11", "3-13", "1-1", "4-4", "9", "3", "2", "4", "0", "2", "7", "0", "-5"], True),
        athlete(2, "Big Doubledouble", ["30", "20", "8-12", "0-0", "4-6", "12", "4", "1", "0", "0", "3", "9", "2", "5"]),
        athlete(3, "Did Notplay", [], dnp=True),
        athlete(4, "Zero Minutes", ["0", "0", "0-0", "0-0", "0-0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]),
        athlete(5, "No Minutes Yet", ["--"]),
    ]}]}]}}


def player(pid, *, status="FREEAGENT", season=None, l7=None, change=0.0, avg=None, name=None):
    stats = {}
    if season:
        stats["season"] = season
    if l7:
        stats["l7"] = l7
    return Player(pid, name or f"Player {pid}", pro_team_id=5, status=status, owned_change=change,
                  avg=avg, stats=stats)


def line(pid, minutes, fpts_box, starter=False, day=DAY):
    """A box score whose fantasy points are exactly ``fpts_box`` (all of them points scored)."""
    return boxscores.Line(pid, f"Player {pid}", "CLE", f"g{pid}", day, starter,
                          {MIN: float(minutes), PTS: float(fpts_box)})


# --- the box score feed ------------------------------------------------------------------------

def test_parse_summary_reads_every_player_who_played():
    lines = boxscores.parse_summary(SUMMARY, "401", DAY)
    assert [ln.player_id for ln in lines] == [1, 2]
    ace = lines[0]
    assert ace.starter and ace.team == "WSH" and ace.game_id == "401" and ace.day == DAY
    assert ace.stats[MIN] == 36 and ace.stats[PTS] == 11 and ace.stats[REB] == 9
    assert (ace.stats[FGM], ace.stats[FGA], ace.stats[FTM], ace.stats[FTA]) == (3, 13, 4, 4)
    assert ace.stats[TPM] == 1 and ace.stats[STL] == 4 and ace.stats[TO] == 2
    assert ace.stats[DD] == 0.0 and ace.stats[TD] == 0.0  # 11 points, 9 rebounds: no double double
    assert lines[1].stats[DD] == 1.0  # 20 and 12


def test_fantasy_points_use_the_leagues_scoring():
    ace = boxscores.parse_summary(SUMMARY, "401", DAY)[0]
    # 11 + 9 + 2*3 + 4*4 + 0 - 2*2 + 2*3 - 13 + 4 - 4 + 1
    assert ace.fpts(SCORING) == pytest.approx(11 + 9 + 6 + 16 - 4 + 6 - 13 + 4 - 4 + 1)
    assert ace.fpts({}) == 0.0


def test_a_day_is_the_finished_games_only(monkeypatch):
    asked = []

    def feed(path, **params):
        asked.append((path, params))
        if path == "scoreboard":
            return {"events": [{"id": "1", "status": {"type": {"completed": True}}},
                               {"id": "2", "status": {"type": {"completed": False}}},
                               {"id": "3", "status": {"type": {"completed": True}}}]}
        return SUMMARY

    monkeypatch.setattr(boxscores, "_get", feed)
    assert boxscores.finished_games(DAY) == ["1", "3"]
    lines = boxscores.day_lines(DAY)
    assert [(ln.game_id, ln.player_id) for ln in lines] == [("1", 1), ("1", 2), ("3", 1), ("3", 2)]
    assert ("scoreboard", {"dates": "20261106"}) in asked
    assert sorted(p["event"] for path, p in asked if path == "summary") == ["1", "3"]


def test_a_day_without_games_asks_for_no_box_scores(monkeypatch):
    monkeypatch.setattr(boxscores, "_get", lambda path, **p: {"events": []})
    assert boxscores.day_lines(DAY) == []


def test_the_session_reads_today_and_the_days_before(monkeypatch):
    from benchboss.service import Session

    days = []
    monkeypatch.setattr(boxscores, "day_lines", lambda d: days.append(d) or [])
    s = Session.__new__(Session)
    s._today = DAY
    assert s.box_lines(3) == []
    assert days == [DAY, DAY - dt.timedelta(days=1), DAY - dt.timedelta(days=2)]


# --- the signals -------------------------------------------------------------------------------

def season(fpts=20.0, gp=10, mpg=24.0, started=2):
    return StatLine(fpts, fpts * gp, gp, {MIN: mpg, GS: started / gp}, {GS: float(started)})


def kinds(pick):
    return [r.kind for r in pick.reasons]


def test_a_big_night_needs_minutes_and_a_multiple_of_his_average():
    p = player(1, season=season(20.0), avg=20.0)
    (pick,) = core.build([line(1, 31, 44)], [p], SCORING)
    assert kinds(pick) == ["big_night"] and "44.0 fpts in 31 min" in pick.reasons[0].text
    assert core.build([line(1, 31, 29)], [p], SCORING) == []   # under 1.5 times
    assert core.build([line(1, 10, 44)], [p], SCORING) == []   # garbage time
    assert core.build([line(1, 31, 19)], [player(2, season=season(5.0))], SCORING) == []  # not his line
    low = player(1, season=season(8.0), avg=8.0)               # 1.5 times is only 12: the floor holds
    assert core.build([line(1, 31, 15)], [low], SCORING) == []


def test_a_start_from_the_bench_and_a_jump_in_minutes():
    p = player(1, season=season(20.0, gp=10, mpg=18.0, started=2))
    (pick,) = core.build([line(1, 31, 20, starter=True)], [p], SCORING)
    assert kinds(pick) == ["started", "minutes"]
    assert "20%" in pick.reasons[0].text and "31 min (averages 18)" in pick.reasons[1].text
    regular = player(1, season=season(20.0, gp=10, mpg=30.0, started=8))
    assert core.build([line(1, 33, 20, starter=True)], [regular], SCORING) == []


def test_the_slow_signals_come_from_the_splits():
    l7 = StatLine(30.0, 90.0, 3, {MIN: 29.0}, {})
    p = player(1, season=season(20.0, mpg=22.0), l7=l7, change=6.2)
    (pick,) = core.build([], [p], SCORING)
    assert kinds(pick) == ["trend", "form", "rising"]
    assert not any(r.fast for r in pick.reasons) and pick.line is None
    one_game = StatLine(30.0, 30.0, 1, {MIN: 29.0}, {})   # one game says nothing about a week
    assert core.build([], [player(1, season=season(20.0, mpg=22.0), l7=one_game)], SCORING) == []


def test_only_free_agents_count_and_the_strongest_come_first():
    big = player(1, season=season(20.0), avg=20.0)
    both = player(2, season=season(20.0, mpg=18.0, started=1), change=7.0)
    taken = player(3, status="ONTEAM", season=season(20.0), avg=20.0)
    lines = [line(1, 31, 44), line(2, 31, 22, starter=True), line(3, 31, 44)]
    picks = core.build(lines, [big, both, taken], SCORING)
    assert [pk.player.id for pk in picks] == [2, 1]   # started + minutes + rising beats one big night
    assert picks[0].score == 7.0 and picks[1].score == 3.0
    assert picks[1].fpts == 44.0 and picks[1].line.player_id == 1


def test_the_best_game_and_the_newest_game_are_told_apart():
    p = player(1, season=season(20.0, mpg=30.0, started=8), avg=20.0)
    older = line(1, 33, 50, day=DAY - dt.timedelta(days=1))
    newer = line(1, 20, 12, day=DAY)
    (pick,) = core.build([older, newer], [p], SCORING)
    assert kinds(pick) == ["big_night"] and pick.line is newer and pick.fpts == 12.0


def test_candidates_skip_rostered_players_and_cameos_and_start_with_the_best_night():
    lines = [line(1, 30, 20), line(2, 30, 40), line(3, 30, 60), line(4, 8, 99), line(2, 20, 10)]
    assert core.candidates(lines, {3}, SCORING) == [2, 1]
    assert core.candidates(lines, set(), SCORING, limit=1) == [3]  # the best night with minutes


# --- the screen and the command ----------------------------------------------------------------

def test_the_demo_radar_shows_free_agents_with_reasons(capsys):
    main(["--demo", "radar", "--json"])
    picks = json.loads(capsys.readouterr().out)
    assert picks and all(p["status"] in ("FREEAGENT", "WAIVERS") for p in picks)
    assert picks == sorted(picks, key=lambda p: -p["score"])
    first = picks[0]
    assert first["reasons"][0]["fast"] is True and first["last_game"]["fpts"] > 0
    assert {"id", "name", "team", "owned", "owned_change", "reasons", "last_game"} <= set(first)
    names = {p["name"] for p in picks}
    assert {"Egor Demin", "Kyshawn George"} <= names  # a big night, and a jump in minutes


def test_n_limits_the_list_and_days_is_capped(capsys, monkeypatch):
    from benchboss.demo import DemoSession

    asked = []
    real = DemoSession.box_lines
    monkeypatch.setattr(DemoSession, "box_lines", lambda self, days=2: asked.append(days) or real(self, days))
    main(["--demo", "radar", "--json", "-n", "1", "--days", "30"])
    assert len(json.loads(capsys.readouterr().out)) == 1 and asked == [screen.MAX_DAYS]


@pytest.mark.parametrize("width", [40, 46, 60, 80, 120, 150])
def test_every_width_fits(width, session):
    data = screen.load(session)
    console = Console(width=width, record=True, file=io.StringIO(), color_system=None)
    console.print(screen.draw(data, DARK, width))
    text = console.export_text()
    assert max(cell_len(x.rstrip()) for x in text.splitlines()) <= width
    assert "Trash radar" in text
    assert "Egor Demin" in text or "E. Demin" in text


def test_nobody_stands_out_says_so(session):
    text = Console(width=80, record=True, file=io.StringIO(), color_system=None)
    text.print(screen.draw(screen.RadarData([], 2), DARK, 80))
    assert "Nobody stands out yet" in text.export_text()


def test_the_radar_is_a_menu_screen_with_its_own_key():
    from benchboss.ui.app import MENU
    from benchboss.ui.screens import SCREENS

    assert ("radar", "Trash radar", "F") in MENU and SCREENS["radar"] is screen
    keys = [k for _, _, k in MENU]
    assert len(keys) == len(set(keys))

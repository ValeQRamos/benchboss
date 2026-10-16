"""Regression tests for the 1.0.2 audit fixes in the core math and parsing (playoff race,
workload footers, activity JSON)."""

import datetime as dt
import io
import json

import pytest
from rich.console import Console
from rich.table import Table

from benchboss.cli import main
from benchboss.core import playoffs
from benchboss.espn.constants import IR
from benchboss.espn.models import parse_league
from benchboss.ui.screens import playoffs as playoffs_screen
from benchboss.ui.screens import workload
from benchboss.ui.theme import DARK

ET = dt.timezone(dt.timedelta(hours=-5))


def text_of(renderable, width: int = 120) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def at(session, day: int, hour: int, minute: int = 0):
    """Move the demo session to a moment of matchup week 3 (November 2026, Eastern time)."""
    session._today = dt.date(2026, 11, day)
    session._now = dt.datetime(2026, 11, day, hour, minute, tzinfo=ET)
    return session


def league(results, weeks, spots=2, current=None):
    """results: (week, home, away, home_pts, away_pts, winner); empty rosters, like
    tests/test_playoffs_core.py."""
    ids = sorted({r[1] for r in results} | {r[2] for r in results})
    teams = [{"id": tid, "name": f"T{tid}", "owners": [f"m{tid}"], "record": {"overall": {}},
              "roster": {"entries": []}} for tid in ids]
    sched = {"matchupPeriodCount": weeks, "playoffTeamCount": spots,
             "playoffSeedingRule": "H2H_RECORD",
             "matchupPeriods": {str(w): [w] for w in range(1, weeks + 1)}}
    schedule = [{"id": i + 1, "matchupPeriodId": w, "winner": win,
                 "home": {"teamId": h, "totalPoints": hp}, "away": {"teamId": a, "totalPoints": ap}}
                for i, (w, h, a, hp, ap, win) in enumerate(results)]
    raw = {"seasonId": 2027, "settings": {"scheduleSettings": sched},
           "status": {"currentMatchupPeriod": current or weeks},
           "members": [{"id": f"m{t}", "firstName": f"Owner{t}"} for t in ids],
           "teams": teams, "schedule": schedule}
    return parse_league(raw, my_team_id=ids[0])


@pytest.fixture
def race_args(monkeypatch):
    """What Session.playoff_race hands to core.playoffs.race."""
    seen = {}
    real = playoffs.race

    def spy(lg, picks=None, sims=5000, **kw):
        seen.update(kw)
        return real(lg, picks, sims=sims, **kw)

    monkeypatch.setattr(playoffs, "race", spy)
    return seen


# --- core-1: the live week does not count today twice -------------------------------------------

def test_a_finished_week_is_decided_by_its_live_score(session, race_args):
    # Sunday 23:59, every game of the week over: nothing is left to simulate
    r = at(session, 8, 23, 59).playoff_race(sims=200)
    assert race_args["week_progress"] == 1.0
    assert set(race_args["live_left"].values()) == {0.0}
    live = [g for g in r.games if g.live]
    assert live
    for g in live:
        home = 1.0 if g.home_points > g.away_points else 0.0
        assert (r.home_win[g.id], r.away_win[g.id]) == (home, 1.0 - home)


def test_today_counts_as_played_for_the_games_that_tipped_off(session, race_args):
    at(session, 4, 15, 30).playoff_race(sims=10)  # Wednesday, before the first tip at 7 pm
    assert race_args["week_progress"] == pytest.approx(2 / 7)
    at(session, 4, 21, 0).playoff_race(sims=10)   # five of the eight tip times have passed
    assert 2 / 7 < race_args["week_progress"] < 3 / 7
    at(session, 4, 23, 0).playoff_race(sims=10)   # all of them
    assert race_args["week_progress"] == pytest.approx(3 / 7)


def test_the_live_week_simulates_what_the_matchup_projection_has_left(session, race_args):
    for hour in (15, 21, 23):
        at(session, 4, hour).playoff_race(sims=10)
        out = session.outlook()
        left = race_args["live_left"]
        assert left[out.me.team.id] == pytest.approx(out.me.projected - out.me.points)
        assert left[out.opponent.team.id] == pytest.approx(out.opponent.projected - out.opponent.points)


def test_race_keeps_the_live_score_when_nothing_is_left():
    # week 2 is live and over: T1 leads T2 by 30, T4 leads T3 by 30
    lg = league([(1, 1, 2, 1400, 1300, "HOME"), (1, 3, 4, 1400, 1300, "HOME"),
                 (2, 1, 2, 1430, 1400, "UNDECIDED"), (2, 3, 4, 1400, 1430, "UNDECIDED")],
                weeks=2, current=2)
    daily = {t: 200.0 for t in lg.teams}
    r = playoffs.race(lg, sims=500, daily=daily, days_by_week={1: 7, 2: 7}, week_progress=1.0,
                      live_left={t: 0.0 for t in lg.teams})
    assert [r.home_win[g.id] for g in r.games] == [1.0, 0.0]
    assert [o.playoffs for o in r.teams] == [1.0, 1.0, 0.0, 0.0]
    # with points still to come, the same week is open again
    r = playoffs.race(lg, sims=500, daily=daily, days_by_week={1: 7, 2: 7}, week_progress=6 / 7,
                      live_left={t: 200.0 for t in lg.teams})
    assert all(0.0 < r.home_win[g.id] < 1.0 for g in r.games)


# --- core-2: no projections is a coin flip, and the away share is its own -------------------------

def empty_league():
    return league([(1, 1, 2, 0, 0, "UNDECIDED"), (1, 3, 4, 0, 0, "UNDECIDED"),
                   (2, 1, 3, 0, 0, "UNDECIDED"), (2, 2, 4, 0, 0, "UNDECIDED")], weeks=2, current=1)


def test_empty_rosters_play_coin_flips_not_ties():
    r = playoffs.race(empty_league(), sims=2000)
    for g in r.games:
        assert r.home_win[g.id] + r.away_win[g.id] == pytest.approx(1.0)
        assert 0.4 < r.home_win[g.id] < 0.6
    for o in r.teams:
        assert o.proj_wins + o.proj_losses == pytest.approx(2.0)
        assert 0.35 < o.playoffs < 0.65
    out = text_of(playoffs_screen.draw(r, DARK, 90, 1), 90)
    assert ">99%" not in out and "<1%" not in out
    assert "0.0-0.0" not in text_of(playoffs_screen.draw(r, DARK, 120, 0))


def test_a_tied_game_is_neither_sides_win():
    # the live week is over with the same score on both sides: a real tie
    lg = league([(1, 1, 2, 1400, 1300, "HOME"), (1, 3, 4, 1400, 1300, "HOME"),
                 (2, 1, 2, 1400, 1400, "UNDECIDED"), (2, 3, 4, 1400, 1430, "UNDECIDED")],
                weeks=2, current=2)
    r = playoffs.race(lg, sims=200, daily={t: 200.0 for t in lg.teams}, week_progress=1.0,
                      live_left={t: 0.0 for t in lg.teams})
    tie = next(g for g in r.games if {g.home, g.away} == {1, 2})
    assert r.home_win[tie.id] == r.away_win[tie.id] == 0.0
    row = playoffs_screen.game_row(r, tie, DARK, 4, False).plain
    assert ">99%" not in row and row.count("<1%") == 2
    assert next(x for x in r.to_dict()["games"] if x["matchup"] == tie.id)["away_win"] == 0.0


# --- core-3: activity --json keeps the keys it always had -----------------------------------------

def test_activity_json_keeps_the_old_keys_and_adds_new_ones(session, capsys):
    main(["--demo", "--json", "activity"])
    rows = json.loads(capsys.readouterr().out)
    old = {a.player.name: a.to_dict() for a in session.activity()}
    assert rows and set(old) <= {r["player"] for r in rows}
    for r in rows:
        assert {"player", "team", "games", "games_left", "schedule"} <= set(r)
        assert all(isinstance(x, str) for x in r["schedule"])
        assert all(x == "" or x.startswith(("vs ", "@ ")) for x in r["schedule"])
        if r["player"] in old:
            assert {k: r[k] for k in old[r["player"]]} == old[r["player"]]
        assert len(r["days"]) == len(r["schedule"])
        assert {"positions", "slot", "games_in_lineup"} <= set(r)


def test_activity_json_matches_the_dashboard_rows(capsys):
    main(["--demo", "--json", "dash"])
    dash = json.loads(capsys.readouterr().out)["activity"]
    main(["--demo", "--json", "activity"])
    rows = {r["player"]: r for r in json.loads(capsys.readouterr().out)}
    for d in dash:
        assert {k: rows[d["player"]][k] for k in d} == d


# --- core-4: the footers follow each day's slot ---------------------------------------------------

def footers(data) -> dict[str, str]:
    t = next(r for r in workload.draw(data, DARK, 140).renderables if isinstance(r, Table))
    return {str(c.header): getattr(c.footer, "plain", c.footer) for c in t.columns
            if str(c.header) in ("G", "In", "Left")}


def test_a_player_moved_to_ir_midweek_keeps_his_games_in_the_footers(session):
    lg = session.league()
    periods = session.matchup_periods()
    edwards = next(s for s in lg.me.roster if s.player.name == "Anthony Edwards")
    days = {p: {s.player.id: s.slot_id for s in lg.me.roster} for p in periods}
    for p in periods[1:]:  # he starts Monday, then sits on IR from Tuesday on (today too)
        days[p][edwards.player.id] = IR
    edwards.slot_id = IR
    session.lineups = lambda ps: {p: days[p] for p in ps}
    data = workload.load(session)
    row = next(a for a in data.acts if a.player.name == "Anthony Edwards")
    assert row.on_ir and row.games_in_lineup == 1
    per_day = data.per_day()
    feet = footers(data)
    assert feet["In"] == str(sum(a.games_in_lineup for a in data.acts))
    assert feet["G"] == str(sum(per_day))
    assert feet["Left"] == str(sum(n for n, p in zip(per_day, data.periods, strict=True)
                                   if p >= data.today))
    assert int(feet["In"]) <= int(feet["G"])


def test_footers_unchanged_without_ir_moves(session):
    data = workload.load(session)
    active = [a for a in data.acts if not a.on_ir]
    feet = footers(data)
    assert feet == {"G": str(sum(a.games for a in active)),
                    "In": str(sum(a.games_in_lineup for a in active)),
                    "Left": str(sum(a.games_left for a in active))}

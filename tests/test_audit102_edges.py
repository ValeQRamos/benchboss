"""Audit of 1.0.2, edge cases and real data: IR stars in the playoff race, the playoff line,
OUT players in the workload, the dashboard after the season, the watch pool's -n, bench
games in Best trash, empty splits in the preseason, ESPN's prefix name search, agent docs."""

import argparse
import datetime as dt
import io
import json
import re
from pathlib import Path

import pytest
from rich.console import Console

from benchboss.cli import build_parser, main
from benchboss.core import playoffs
from benchboss.espn.constants import BENCH, IR
from benchboss.espn.models import Player, RosterSpot, Team, parse_league
from benchboss.ui import dashboard
from benchboss.ui.screens import finder, view_index, workload
from benchboss.ui.screens import playoffs as playoffs_screen
from benchboss.ui.screens import trash as trash_screen
from benchboss.ui.theme import DARK

ROOT = Path(__file__).resolve().parents[1]
ET = dt.timezone(dt.timedelta(hours=-5))


def text_of(renderable, width: int = 140) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


# --- edges-1: a star on IR is a temporary absence, not a season-long one -------------------------

def test_a_player_on_ir_counts_toward_the_healthy_level(session):
    lg = session.league()
    team = next(t for t in lg.teams.values() if t.id != lg.my_team_id)
    spots = sum(n for slot, n in lg.slot_counts.items() if slot != IR)
    healthy = playoffs.projected_daily(team, spots)
    weekly = session.playoff_race(sims=20).odds(team.id).weekly
    star = max(team.roster, key=lambda s: s.player.proj)
    star.slot_id = IR
    assert playoffs.projected_daily(team, spots) == pytest.approx(healthy)
    assert session.playoff_race(sims=20).odds(team.id).weekly == pytest.approx(weekly)


def test_a_player_back_from_ir_pushes_out_the_weakest():
    roster = [RosterSpot(Player(i, f"P{i}", proj=float(10 + i)), BENCH) for i in range(13)]
    roster.append(RosterSpot(Player(99, "Back Soon", proj=60.0), IR))
    team = Team(1, "Mine", roster=roster)
    best = sorted((s.player.proj for s in roster), reverse=True)[:13]
    rate = playoffs.GAMES_PER_DAY * playoffs.BENCH_LOSS
    assert playoffs.projected_daily(team, 13) == pytest.approx(sum(best) * rate)
    # without the roster size it keeps as many as are off IR now
    assert playoffs.projected_daily(team) == pytest.approx(sum(best) * rate)


# --- edges-2: the rows above the playoff line are the likeliest to get in -------------------------

def _league(results, weeks, divisions, spots, current):
    """results: (week, home, away, home_pts, away_pts, winner); teams 1..n named T1..Tn."""
    ids = sorted({r[1] for r in results} | {r[2] for r in results})
    teams = [{"id": t, "name": f"T{t}", "owners": [f"m{t}"], "record": {"overall": {}},
              "roster": {"entries": []}, "divisionId": divisions[t]} for t in ids]
    sched = {"matchupPeriodCount": weeks, "playoffTeamCount": spots,
             "playoffSeedingRule": "H2H_RECORD",
             "matchupPeriods": {str(w): [w] for w in range(1, weeks + 1)},
             "divisions": [{"id": d, "name": f"D{d}"} for d in sorted(set(divisions.values()))]}
    schedule = [{"id": i + 1, "matchupPeriodId": w, "winner": win,
                 "home": {"teamId": h, "totalPoints": hp}, "away": {"teamId": a, "totalPoints": ap}}
                for i, (w, h, a, hp, ap, win) in enumerate(results)]
    raw = {"seasonId": 2027, "settings": {"scheduleSettings": sched},
           "status": {"currentMatchupPeriod": current},
           "members": [{"id": f"m{t}", "firstName": f"Owner{t}"} for t in ids],
           "teams": teams, "schedule": schedule}
    return parse_league(raw, my_team_id=ids[0])


def test_a_sure_wildcard_sits_above_a_division_coin_flip():
    # Division 0: T1 and T2 are 2-1, T1 won the head-to-head, so T1 has the division and T2
    # the wildcard (3rd of 3 spots) whatever happens. Division 1: T4 and T5 are 2-1 and meet
    # in the last week: the winner takes the division and the 1st seed, the loser misses. So
    # T4 and T5 have a better mean seed than T2 (2.5 against 3.0) but half its odds.
    played = [(1, 1, 2, 100, 90, "HOME"), (1, 4, 3, 100, 90, "HOME"), (1, 5, 6, 100, 90, "HOME"),
              (2, 2, 4, 100, 90, "HOME"), (2, 1, 6, 100, 90, "HOME"), (2, 5, 3, 100, 90, "HOME"),
              (3, 2, 5, 100, 90, "HOME"), (3, 4, 1, 100, 90, "HOME"), (3, 3, 6, 100, 90, "HOME")]
    lg = _league(played + [(4, 4, 5, 0, 0, "UNDECIDED")], weeks=4,
                 divisions={1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 1}, spots=3, current=4)
    r = playoffs.race(lg, sims=400)
    two, four = r.odds(2), r.odds(4)
    assert two.playoffs == 1.0 and 0 < four.playoffs < 1
    assert two.mean_seed > four.mean_seed  # the old sort put T4 above T2
    order = [o.team.id for o in r.teams]
    assert order[:2] == [1, 2]
    shares = [o.playoffs for o in r.teams]
    assert shares == sorted(shares, reverse=True)
    # the dashed line goes under row 3: T1, T2 and the likelier of T4 and T5 are above it
    cols, tight = playoffs_screen.fit_columns(r, DARK, 120)
    above, below = text_of(playoffs_screen.odds_table(r, DARK, cols, tight)).split("╌", 1)
    assert "T1" in above and "T2" in above and "T2" not in below


# --- edges-3: a player who is out is not a game lost to the bench ---------------------------------

def test_out_bench_players_do_not_count_as_games_or_overflow(session):
    before = workload.load(session).per_day()
    bench = [s for s in session.league().me.roster if s.slot_id == BENCH]
    assert len(bench) >= 2
    for s in bench:
        s.player.injury_status = "OUT"
    bench[0].player.injury_status = "SUSPENSION"
    data = workload.load(session)
    out = [a for a in data.acts if a.out]
    assert {a.player.id for a in out} == {s.player.id for s in bench}
    want = [n - sum(1 for a in out if a.schedule[i]) for i, n in enumerate(before)]
    assert data.per_day() == want
    for a in out:
        assert not any(a.benched(i) for i in range(len(a.schedule)))
    text = text_of(workload.draw(data, DARK, 140))
    rows = [line for line in text.splitlines()
            if any(line.startswith(a.player.name) for a in out)]
    assert rows and not any("(" in line for line in rows)  # no "(ATL)" bench games
    assert max(data.per_day()) <= data.starter_slots
    assert "more games than starting spots" not in text


# --- edges-4: after the season nobody plays today and no games are left ---------------------------

def test_dashboard_after_the_season_shows_no_games(session):
    session._today = dt.date(2027, 4, 20)
    session._now = dt.datetime(2027, 4, 20, 12, tzinfo=ET)
    assert not session.in_season
    d = dashboard.collect(session, with_trash=False, with_alerts=False, with_trending=False,
                          with_news=False)
    assert not d.plays_today and not d.opponents_today
    assert d.activity and all(a.games_left == 0 for a in d.activity)
    out = text_of(dashboard.render(d, DARK, 120), 120)
    assert "play today" not in out and "proj. pts" in out
    assert set(re.findall(r"\((\d+) left\)", out)) <= {"0"}
    roster = d.to_dict()["roster"]
    assert not any(r["plays_today"] for r in roster)


def test_dashboard_in_season_still_marks_who_plays_today(session):
    d = dashboard.collect(session, with_trash=False, with_alerts=False, with_trending=False,
                          with_news=False)
    assert d.in_season and d.plays_today
    assert "play today" in text_of(dashboard.render(d, DARK, 120), 120)


# --- edges-6: -n applies to the watch list too ----------------------------------------------------

def test_players_from_watch_honors_n(capsys):
    main(["--demo", "--json", "players", "--from", "watch"])
    every = json.loads(capsys.readouterr().out)
    assert len(every) > 1
    main(["--demo", "--json", "players", "--from", "watch", "-n", "1"])
    one = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in one] == [every[0]["name"]]  # the best projected of the list


# --- edges-7: a game he would spend on your bench is not a game he plays for you ------------------

def test_trash_counts_only_the_games_that_add_points(session):
    picks = session.trash(n=20)
    benched = [pk for pk in picks if pk.bench_days()]
    assert benched  # the demo week has overflow days
    for pk in picks:
        assert pk.games_left == len(pk.game_days())
        assert all(pk.added[d] > 0 for d in pk.game_days())
        assert all(pk.added[d] == 0 for d in pk.bench_days())
        assert pk.to_dict(session.calendar)["games_left"] == len(pk.game_days())
    cal = session.calendar
    span = trash_screen.week_span(picks)
    for pk in benched:
        strip = trash_screen.games_strip(pk, span, cal, DARK)
        assert strip.plain.count("●") == pk.games_left
        assert all(strip.plain[span.index(d)] == "○" for d in pk.bench_days())
    out = text_of(trash_screen.draw(trash_screen.load(session), DARK, 140), 140)
    assert "on your bench" in out


# --- edges-8: an empty split (the preseason) ranks by the projection ------------------------------

def test_sorting_by_an_empty_split_falls_back_to_the_projection(session, monkeypatch):
    real = session.player_pool
    asked = []

    def preseason(source="fa", position=None, n=100, sort="proj", query=None):
        asked.append(sort)
        players = real(source, position, n, sort, query)
        for p in players:
            p.stats = {k: v for k, v in p.stats.items() if k in ("proj", "last")}
        return players

    monkeypatch.setattr(session, "player_pool", preseason)
    data = finder.load(session, sort="season", n=12)
    assert asked == ["season", "proj"] and data.sort == "proj"
    projs = [v for v in (p.fpts("proj") for p in data.players) if v is not None]
    assert projs and projs == sorted(projs, reverse=True)
    out = text_of(finder.draw(data, DARK, 170, view_index(finder, "season")), 170)
    assert "sorted by Proj" in out and "No Season stats yet" in out


def test_a_split_with_numbers_keeps_its_own_ranking(session):
    data = finder.load(session, sort="season", n=12)
    assert data.sort == "season"


# --- edges-9: the demo searches names the way ESPN does (prefix of a first, last or full name) ----

def test_name_search_matches_the_start_of_a_name(session):
    def names(query: str) -> set[str]:
        return {p.name for p in session.player_pool("all", n=50, query=query)}

    alexander = names("Alexander")
    assert "Nickeil Alexander-Walker" in alexander
    assert "Shai Gilgeous-Alexander" not in alexander
    assert "Shai Gilgeous-Alexander" in names("gilgeous")
    assert "Shai Gilgeous-Alexander" in names("Shai Gil")
    assert not names("lexander")


# --- edges-10: the agent docs list every league command and the watch list write ------------------

ACCOUNT = {"app", "setup", "login", "logout", "status", "doctor"}


def test_agent_docs_list_every_league_command():
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    commands = [name for name in sub.choices if name not in ACCOUNT]
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    copilot = (ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert [c for c in commands if f"benchboss {c}" not in agents] == []
    assert [c for c in commands if f"`{c}" not in copilot] == []
    writes = agents.split("### Writes need")[1].split("### Exit codes")[0]
    assert "benchboss watch add" in writes and "benchboss watch remove" in writes
    assert "`watch add`" in copilot and "`watch remove`" in copilot
    assert "news --json --watch" in agents and "news --watch" in copilot


def test_the_watch_list_endpoint_is_documented():
    writes = (ROOT / "docs" / "api" / "04-writes-transactions.md").read_text(encoding="utf-8")
    assert '{"watchList": [' in writes and "maxWatchListPlayers" in writes
    views = (ROOT / "docs" / "api" / "01-league-views.md").read_text(encoding="utf-8")
    assert "`teams[].watchList`" in views

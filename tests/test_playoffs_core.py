"""The playoff race simulation, seeding and tiebreakers, on small made-up leagues."""

import pytest

from benchboss.core import playoffs
from benchboss.errors import BenchbossError
from benchboss.espn.models import parse_league


def league(results, weeks, divisions=None, spots=2, rule="H2H_RECORD", current=None):
    """results: (week, home, away, home_pts, away_pts, winner) with winner HOME/AWAY/TIE or
    UNDECIDED. Teams 1..n are named T1..Tn; divisions maps team id -> division id."""
    ids = sorted({r[1] for r in results} | {r[2] for r in results})
    teams = []
    for tid in ids:
        t = {"id": tid, "name": f"T{tid}", "owners": [f"m{tid}"], "record": {"overall": {}},
             "roster": {"entries": []}}
        if divisions:
            t["divisionId"] = divisions[tid]
        teams.append(t)
    sched = {"matchupPeriodCount": weeks, "playoffTeamCount": spots, "playoffSeedingRule": rule,
             "matchupPeriods": {str(w): [w] for w in range(1, weeks + 1)}}
    if divisions:
        sched["divisions"] = [{"id": d, "name": f"D{d}"} for d in sorted(set(divisions.values()))]
    schedule = [{"id": i + 1, "matchupPeriodId": w, "winner": win,
                 "home": {"teamId": h, "totalPoints": hp}, "away": {"teamId": a, "totalPoints": ap}}
                for i, (w, h, a, hp, ap, win) in enumerate(results)]
    raw = {"seasonId": 2027, "settings": {"scheduleSettings": sched},
           "status": {"currentMatchupPeriod": current or weeks},
           "members": [{"id": f"m{t}", "firstName": f"Owner{t}"} for t in ids],
           "teams": teams, "schedule": schedule}
    return parse_league(raw, my_team_id=ids[0])


def test_a_finished_season_seeds_by_record_and_is_certain():
    lg = league([(1, 1, 2, 100, 90, "HOME"), (1, 3, 4, 100, 90, "HOME"),
                 (2, 1, 3, 100, 90, "HOME"), (2, 2, 4, 100, 90, "HOME")], weeks=2)
    r = playoffs.race(lg, sims=50)
    assert [o.team.id for o in r.teams][:2] == [1, 2] or [o.team.id for o in r.teams][:2] == [1, 3]
    one = r.odds(1)
    assert one.playoffs == 1.0 and one.status == "clinched" and one.seeds[0] == 1.0
    assert r.odds(4).playoffs == 0.0 and r.odds(4).status == "eliminated"
    assert not r.games  # nothing left to play


def test_division_winners_take_the_top_seeds():
    # T3 wins division 1 at 1-1 while T2 (division 0) goes 2-0 behind T1 (3-0)
    lg = league([(1, 1, 2, 100, 90, "HOME"), (1, 3, 4, 100, 90, "HOME"),
                 (2, 1, 4, 100, 90, "HOME"), (2, 2, 3, 100, 90, "HOME"),
                 (3, 1, 3, 100, 90, "HOME"), (3, 2, 4, 100, 90, "HOME")],
                weeks=3, divisions={1: 0, 2: 0, 3: 1, 4: 1})
    st = playoffs._standing_base(lg, playoffs.season_games(lg))
    order, champs = playoffs.seed_order(lg, st, playoffs.base_h2h(playoffs.season_games(lg)))
    assert set(champs) == {1, 3}
    assert order[:2] == [1, 3] and order[2] == 2  # T2 has the better record but no title


def test_head_to_head_breaks_a_tie_before_points():
    # T1 and T2 both 1-1; T2 beat T1 head to head although T1 scored more overall
    games = [(1, 1, 2, 90, 100, "AWAY"), (1, 3, 4, 50, 40, "HOME"),
             (2, 1, 4, 300, 10, "HOME"), (2, 3, 2, 20, 10, "HOME")]
    lg = league(games, weeks=2)
    st = playoffs._standing_base(lg, playoffs.season_games(lg))
    order, _ = playoffs.seed_order(lg, st, playoffs.base_h2h(playoffs.season_games(lg)))
    assert order.index(2) < order.index(1)
    lg_pts = league(games, weeks=2, rule="TOTAL_POINTS_SCORED")
    st = playoffs._standing_base(lg_pts, playoffs.season_games(lg_pts))
    order, _ = playoffs.seed_order(lg_pts, st, playoffs.base_h2h(playoffs.season_games(lg_pts)))
    assert order.index(1) < order.index(2)


def open_league():
    played = [(1, 1, 2, 100, 90, "HOME"), (1, 3, 4, 100, 90, "HOME")]
    later = [(2, 1, 3, 0, 0, "UNDECIDED"), (2, 2, 4, 0, 0, "UNDECIDED"),
             (3, 1, 4, 0, 0, "UNDECIDED"), (3, 2, 3, 0, 0, "UNDECIDED")]
    return league(played + later, weeks=3, current=2)


def test_picks_are_fixed_in_every_simulation():
    lg = open_league()
    base = playoffs.race(lg, sims=400)
    game = next(g for g in base.games if {g.home, g.away} == {2, 4})
    picked = playoffs.race(lg, {game.id: 4}, sims=400)
    assert picked.home_win[game.id] == (1.0 if game.home == 4 else 0.0)
    assert next(g for g in picked.games if g.id == game.id).picked
    assert picked.odds(4).proj_wins >= 1.0


def test_winning_out_clinches_and_losing_out_eliminates():
    lg = open_league()
    mine = [g for g in playoffs.season_games(lg) if not g.decided and 4 in (g.home, g.away)]
    win_out = playoffs.race(lg, {g.id: 4 for g in mine}, sims=200)
    lose_out = playoffs.race(lg, {g.id: (g.home if g.away == 4 else g.away) for g in mine}, sims=200)
    assert win_out.odds(4).playoffs > lose_out.odds(4).playoffs
    assert lose_out.odds(4).playoffs == 0.0


def test_parse_picks_reads_names_and_weeks():
    lg = open_league()
    picks = playoffs.parse_picks(lg, ["T4>T2", "T3>T1@2"])
    games = {g.id: g for g in playoffs.season_games(lg)}
    assert {games[gid].week for gid in picks} == {2}
    assert sorted(picks.values()) == [3, 4]
    for bad in ("T4", "T4>T4", "T1>T2", "T1>T3@9", "T1>T3@x"):
        with pytest.raises(BenchbossError):
            playoffs.parse_picks(lg, [bad])


def test_a_decided_game_cannot_be_picked():
    lg = open_league()
    decided = next(g for g in playoffs.season_games(lg) if g.decided)
    with pytest.raises(BenchbossError):
        playoffs.race(lg, {decided.id: decided.away}, sims=10)


def test_demo_league_race_runs_and_adds_up(session):
    r = session.playoff_race(sims=300)
    assert len(r.teams) == len(session.league().teams)
    assert abs(sum(o.playoffs for o in r.teams) - r.playoff_teams) < 1e-9
    for o in r.teams:
        assert 0.0 <= o.playoffs <= 1.0 and len(o.seeds) == r.playoff_teams
    assert r.to_dict()["teams"][0]["team"] == r.teams[0].team.name

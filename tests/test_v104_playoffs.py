"""1.0.4 playoff race: one count of simulated seasons everywhere, picks that replay the same
seasons, the tie-break chain (and its faster form), the coin flip, the division clinch and
the early-season note."""

import datetime as dt
import inspect
import io
import json
import random
from collections import defaultdict

import pytest
from rich.console import Console

from benchboss.cli import build_parser, main
from benchboss.core import playoffs as core
from benchboss.demo import demo_session
from benchboss.errors import BenchbossError
from benchboss.espn.models import parse_league
from benchboss.ui.screens import playoffs
from benchboss.ui.theme import DARK, LIGHT


def text_of(renderable, width: int = 140) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def league(results, weeks, divisions=None, spots=2, rule="H2H_RECORD", current=None):
    """results: (week, home, away, home_pts, away_pts, winner) with winner HOME, AWAY, TIE or
    UNDECIDED. Teams are T1..Tn with empty rosters (nothing projected); ``divisions`` maps a
    team id to its division id."""
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


@pytest.fixture(scope="module")
def demo_race():
    return playoffs.load(demo_session(), sims=600)


# --- one count of simulated seasons -------------------------------------------------------------

def test_one_simulation_count_everywhere(session):
    assert core.SIMS == 5000 and playoffs.SIMS == core.SIMS
    assert not hasattr(playoffs, "SCENARIO_SIMS")
    assert inspect.signature(core.race).parameters["sims"].default == core.SIMS
    assert inspect.signature(playoffs.load).parameters["sims"].default == core.SIMS
    assert build_parser().parse_args(["playoffs"]).sims == core.SIMS
    assert session.playoff_race().sims == core.SIMS


def test_picks_replay_the_seasons_of_the_race_without_them(session):
    base = session.playoff_race({}, 400)
    game = next(g for g in base.games if g.week == 20)
    picked = session.playoff_race({game.id: game.away}, 400, base=base)
    assert picked.sims == base.sims == 400 and picked.baseline is base
    # the same draws: every game that was not picked comes out exactly as before
    for g in base.games:
        if g.id != game.id:
            assert picked.home_win[g.id] == base.home_win[g.id]
            assert picked.away_win[g.id] == base.away_win[g.id]
    assert picked.away_win[game.id] == 1.0
    # with no picks it is the very same race, whatever the clock says now
    session._now = session.now + dt.timedelta(hours=5)
    again = session.playoff_race({}, base=base)
    assert [(o.team.id, o.playoffs, o.seeds) for o in again.teams] == \
           [(o.team.id, o.playoffs, o.seeds) for o in base.teams]


def test_load_with_picks_compares_against_the_same_seasons():
    s = demo_session()
    picks = core.parse_picks(s.league(), ["Monstars>Tune Squad@20"])
    race = playoffs.load(s, picks, sims=300)
    assert race.baseline is not None and race.baseline.sims == race.sims == 300
    assert not race.baseline.picks


def test_a_team_without_a_plus_minus_keeps_its_share():
    """The bug behind "a percentage that is not right": the first view ran 5,000 seasons and
    each pick 2,000 against another 2,000-season base, so a team could go 47% to 45% with no
    +/- at all."""
    s = demo_session()
    base = playoffs.load(s, sims=1000)
    game = next(g for g in base.games if g.week == 20)
    race = s.playoff_race({game.id: game.home}, base=base)
    cols, _ = playoffs.fit_columns(race, DARK, 200, base=base)
    cells = {head: cells for head, _, cells in cols}
    moved = 0
    for o, share, delta in zip(race.teams, cells["Playoffs"], cells["+/-"], strict=True):
        before = base.odds(o.team.id)
        printed = share.plain.split("%")[0].strip()  # "54", "<1" or ">99"
        now = {"<1": 0, ">99": 100}.get(printed) if printed[0] in "<>" else int(printed)
        was = playoffs.shown_share(before.playoffs)
        assert now == playoffs.shown_share(o.playoffs)
        if delta.plain == "·":
            assert now == was, o.team.name
        else:
            assert int(delta.plain) == now - was != 0, o.team.name
            moved += 1
    assert moved >= 2  # at least the two teams of the picked game
    assert playoffs.shown_share(0.004) == 0 and playoffs.shown_share(0.995) == 100


# --- the simulation adds up ---------------------------------------------------------------------

def test_seed_and_division_shares_add_up(demo_race):
    n = demo_race.playoff_teams
    assert sum(o.playoffs for o in demo_race.teams) == pytest.approx(n)
    for i in range(n):
        assert sum(o.seeds[i] for o in demo_race.teams) == pytest.approx(1.0)
    divisions = len({o.team.division_id for o in demo_race.teams})
    assert sum(o.division for o in demo_race.teams) == pytest.approx(divisions)


# --- the tie-break chain ------------------------------------------------------------------------

def four(rule="H2H_RECORD", divisions=None):
    """Four teams, no games: seed_order gets its standings and head-to-head directly."""
    games = [(1, 1, 2, 0, 0, "UNDECIDED"), (1, 3, 4, 0, 0, "UNDECIDED")]
    return league(games, weeks=1, spots=2, rule=rule, divisions=divisions)


def standings(rows):
    """{team: (wins, losses, points for, points against)} -> seed_order's st."""
    return {t: [w, lo, 0.0, pf, pa] for t, (w, lo, pf, pa) in rows.items()}


def test_equal_records_and_head_to_head_go_to_points_for():
    st = standings({1: (5, 5, 900, 900), 2: (5, 5, 950, 900), 3: (8, 2, 0, 0), 4: (1, 9, 0, 0)})
    h2h = {(1, 2): 1.0, (2, 1): 1.0}
    order, _ = core.seed_order(four(), st, h2h)
    assert order == [3, 2, 1, 4]


def test_then_division_record_then_more_points_against():
    one_division = {1: 0, 2: 0, 3: 0, 4: 0}  # one division: nobody is seeded first
    st = standings({1: (5, 5, 900, 900), 2: (5, 5, 900, 900), 3: (8, 2, 0, 0), 4: (1, 9, 0, 0)})
    # split head to head; 1 beat 3 inside the division, 2 lost to 3
    h2h = {(1, 2): 1.0, (2, 1): 1.0, (1, 3): 1.0, (3, 2): 1.0}
    order, champs = core.seed_order(four(divisions=one_division), st, h2h)
    assert champs == [] and order.index(1) < order.index(2)
    # the same division record: more points against ranks first
    st[2][4] = 950.0
    h2h = {(1, 2): 1.0, (2, 1): 1.0}
    order, _ = core.seed_order(four(divisions=one_division), st, h2h)
    assert order.index(2) < order.index(1)


def test_all_equal_is_a_coin_flip():
    st = standings({1: (5, 5, 900, 900), 2: (5, 5, 900, 900), 3: (8, 2, 0, 0), 4: (1, 9, 0, 0)})
    firsts = {core.seed_order(four(), st, {}, random.Random(k))[0][1] for k in range(40)}
    assert firsts == {1, 2}


def test_the_league_rule_comes_before_head_to_head():
    st = standings({1: (5, 5, 900, 900), 2: (5, 5, 950, 900), 3: (8, 2, 0, 0), 4: (1, 9, 0, 0)})
    h2h = {(1, 2): 2.0}  # 1 swept 2, 2 scored more
    assert core.seed_order(four(), st, h2h)[0][1:3] == [1, 2]
    assert core.seed_order(four("TOTAL_POINTS_SCORED"), st, h2h)[0][1:3] == [2, 1]


def test_three_way_tie_uses_the_combined_head_to_head():
    # 1, 2 and 3 all 5-5; 1 beat both, 2 beat 3; points for say the opposite
    st = standings({1: (5, 5, 800, 900), 2: (5, 5, 850, 900), 3: (5, 5, 990, 900),
                    4: (9, 1, 0, 0)})
    h2h = {(1, 2): 1.0, (1, 3): 1.0, (2, 3): 1.0}
    order, _ = core.seed_order(four(), st, h2h)
    assert order == [4, 1, 2, 3]


def full_sort_seed_order(lg, st, h2h, rng):
    """seed_order as 1.0.3 had it: every team sorted by the whole tie-break chain."""
    divs = defaultdict(list)
    for tid, t in lg.teams.items():
        divs[t.division_id].append(tid)
    flip = {tid: rng.random() for tid in st}

    def pct(v):
        games = v[0] + v[1] + v[2]
        return (v[0] + 0.5 * v[2]) / games if games else 0.0

    def div_pct(tid):
        rivals = set(divs[lg.teams[tid].division_id]) - {tid}
        won = sum(h2h.get((tid, r), 0.0) for r in rivals)
        lost = sum(h2h.get((r, tid), 0.0) for r in rivals)
        return won / (won + lost) if won + lost else 0.0

    def rank(tids):
        def key(tid):
            others = [x for x in tids if x != tid and pct(st[x]) == pct(st[tid])]
            won = sum(h2h.get((tid, o), 0.0) for o in others)
            lost = sum(h2h.get((o, tid), 0.0) for o in others)
            head = won / (won + lost) if won + lost else 0.5
            rule = {"H2H_RECORD": head, "TOTAL_POINTS_SCORED": st[tid][3],
                    "INTRA_DIVISION_RECORD": div_pct(tid),
                    "TOTAL_POINTS_AGAINST": st[tid][4]}.get(lg.seeding_rule, head)
            return (-pct(st[tid]), -rule, -head, -st[tid][3], -div_pct(tid), -st[tid][4], flip[tid])
        return sorted(tids, key=key)

    if len(divs) > 1 and all(k is not None for k in divs):
        champs = rank([rank(m)[0] for m in divs.values()])
        return champs + rank([t for t in st if t not in champs]), champs
    return rank(list(st)), []


@pytest.mark.parametrize("rule", ["H2H_RECORD", "TOTAL_POINTS_SCORED", "INTRA_DIVISION_RECORD",
                                  "TOTAL_POINTS_AGAINST"])
@pytest.mark.parametrize("split", [None, "two", "one"])
def test_the_faster_tie_break_matches_the_full_sort(rule, split):
    ids = list(range(1, 11))
    divisions = {"two": {t: t % 2 for t in ids}, "one": dict.fromkeys(ids, 0)}.get(split)
    games = [(1, t, t + 1, 0, 0, "UNDECIDED") for t in ids[::2]]
    lg = league(games, weeks=1, spots=4, rule=rule, divisions=divisions)
    draw = random.Random(f"{rule}{split}")
    for k in range(300):
        # few distinct records and points, so ties of two, three and more come up often
        st = {t: [draw.choice([3, 4, 5]), draw.choice([3, 4, 5]), draw.choice([0, 0, 1]),
                  draw.choice([800.0, 850.0]), draw.choice([800.0, 850.0])] for t in ids}
        h2h = {(a, b): draw.choice([0.0, 0.5, 1.0, 2.0]) for a in ids for b in ids
               if a != b and draw.random() < 0.4}
        fast = core.seed_order(lg, st, h2h, random.Random(k))
        assert fast == full_sort_seed_order(lg, st, h2h, random.Random(k))


# --- the coin flip and the shared draws ---------------------------------------------------------

def test_picking_a_coin_flip_game_does_not_shift_the_other_games():
    # empty rosters, nothing projected: every open game is a coin flip
    games = [(1, 1, 2, 0, 0, "UNDECIDED"), (1, 3, 4, 0, 0, "UNDECIDED"),
             (2, 1, 3, 0, 0, "UNDECIDED"), (2, 2, 4, 0, 0, "UNDECIDED")]
    lg = league(games, weeks=2, current=1)
    base = core.race(lg, sims=500, in_season=False)
    first = min(base.games, key=lambda g: g.id)
    picked = core.rerun(base, {first.id: first.home})
    assert picked.home_win[first.id] == 1.0
    for g in base.games:
        if g.id != first.id:
            assert picked.home_win[g.id] == base.home_win[g.id]
            assert 0.3 < base.home_win[g.id] < 0.7  # a coin, not a 0-0 tie


def test_rerun_needs_the_league():
    race = core.race(league([(1, 1, 2, 0, 0, "UNDECIDED")], weeks=1), sims=10)
    race.league = None
    with pytest.raises(BenchbossError):
        core.rerun(race, {})


# --- the division clinch ------------------------------------------------------------------------

def three_divisions():
    """Six teams in three divisions of two, two playoff spots, one week left: T1, T3 and T5
    are 2-0 and lead their divisions, T2, T4 and T6 are 0-2."""
    played = [(1, 1, 2, 100, 90, "HOME"), (1, 3, 4, 100, 90, "HOME"), (1, 5, 6, 100, 90, "HOME"),
              (2, 1, 4, 100, 90, "HOME"), (2, 3, 6, 100, 90, "HOME"), (2, 5, 2, 100, 90, "HOME")]
    later = [(3, 1, 3, 0, 0, "UNDECIDED"), (3, 5, 2, 0, 0, "UNDECIDED"), (3, 4, 6, 0, 0, "UNDECIDED")]
    return league(played + later, weeks=3, spots=2, current=3,
                  divisions={1: 0, 2: 0, 3: 1, 4: 1, 5: 2, 6: 2})


def test_a_division_title_does_not_clinch_when_spots_are_fewer_than_divisions():
    lg = three_divisions()
    games = core.season_games(lg)
    clinched, eliminated = core.certainties(lg, games)
    # T1 wins its division whatever happens, but T3 and T5 could both finish 3-0 above it
    assert 1 not in clinched
    assert {2, 4, 6} <= eliminated  # only division winners get in, and they cannot win one
    r = core.race(lg, sims=400, in_season=False)
    assert 0.0 < r.odds(1).playoffs < 1.0 and r.odds(1).status == ""
    assert r.odds(2).playoffs == 0.0 and r.odds(2).status == "eliminated"


def test_beating_the_other_leader_clinches_it():
    lg = three_divisions()
    game = next(g for g in core.season_games(lg) if {g.home, g.away} == {1, 3})
    r = core.race(lg, {game.id: 1}, sims=300, in_season=False)
    assert r.odds(1).status == "clinched" and r.odds(1).playoffs == 1.0


def test_enough_spots_keep_the_division_clinch():
    lg = three_divisions()
    lg.playoff_teams = 3
    clinched, _ = core.certainties(lg, core.season_games(lg))
    assert 1 in clinched  # three spots, three divisions: every division winner gets in


# --- the early-season note ----------------------------------------------------------------------

def test_the_early_note_in_the_cli_and_its_json(capsys):
    main(["--demo", "playoffs", "--sims", "100"])
    out = " ".join(capsys.readouterr().out.split())
    assert "18 weeks left:" in out and "matter most in the last 5 weeks (--view games" in out
    main(["--demo", "playoffs", "--sims", "100", "--view", "games"])
    games = " ".join(capsys.readouterr().out.split())
    assert "18 weeks left:" in games and "matter most in the last 5 weeks." in games
    assert playoffs.early_note(playoffs.load(demo_session(), sims=50), 120, "--view games") == (
        "18 weeks left: odds move a lot this early. Picks matter most in the last 5 weeks "
        "(--view games lists them).")
    main(["--demo", "--json", "playoffs", "--sims", "100"])
    data = json.loads(capsys.readouterr().out)
    assert data["final_stretch_from"] == 16 and data["weeks_left"][0] == 3


@pytest.mark.parametrize("width", [40, 46, 60, 80, 120, 150])
@pytest.mark.parametrize("pal", [DARK, LIGHT], ids=["dark", "light"])
def test_the_early_note_fits_every_width(demo_race, width, pal):
    note = playoffs.early_note(demo_race, width, "e")
    assert note.startswith("18 weeks left") and len(note) <= width
    out = text_of(playoffs.draw(demo_race, pal, width), width)
    assert all(len(line) <= width for line in out.splitlines())


def test_no_early_note_in_the_final_stretch(demo_race):
    late = core.Race(demo_race.teams, [g for g in demo_race.games if g.week >= 16],
                     demo_race.home_win, demo_race.away_win, demo_race.playoff_teams,
                     demo_race.divisions, {}, demo_race.sims, [16, 17, 18, 19, 20])
    assert playoffs.early_note(late, 120, "e") == ""
    assert "weeks left" not in text_of(playoffs.draw(late, DARK, 120), 120)
    assert playoffs.to_json(late)["final_stretch_from"] == 16
    over = core.Race(demo_race.teams, [], {}, {}, 4, demo_race.divisions, {}, 10, [])
    assert playoffs.early_note(over, 120) == "" and playoffs.to_json(over)["final_stretch_from"] is None


def test_the_builder_head_has_the_note_unless_the_window_is_short():
    b = playoffs.PlayoffBuilder(playoffs.load(demo_session(), sims=100), session=None)
    head = text_of(b._draw_head(DARK, 120, 2), 120)
    assert "Picks matter most in the last 5 weeks (e jumps there)." in head
    b.short = True
    assert "weeks left" not in text_of(b._draw_head(DARK, 120, 1), 120)


def test_the_tie_legend_names_the_next_step_when_there_is_room(demo_race):
    wide = " ".join(text_of(playoffs.draw(demo_race, DARK, 160), 160).split())
    assert "Ties broken by head-to-head record, then points for" in wide
    narrow = text_of(playoffs.draw(demo_race, DARK, 46), 46)
    assert "Ties broken by head-to-head record" in narrow and "then points" not in narrow

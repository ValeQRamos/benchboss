"""The standings screen: the league table, the divisions and the moves (offline, demo league)."""

import asyncio
import io
import json

import pytest
from rich.console import Console
from rich.table import Table

from benchboss.cli import main
from benchboss.config import Config
from benchboss.demo import demo_session
from benchboss.errors import BenchbossError
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import standings, view_index
from benchboss.ui.theme import DARK, LIGHT

WIDTHS = (46, 80, 120, 160)
LEAGUE, DIVISIONS, MOVES = 0, 1, 2


@pytest.fixture
def league():
    return demo_session().league()


def text_of(renderable, width: int) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def tables(renderable) -> list[Table]:
    return [r for r in renderable.renderables if isinstance(r, Table)]


def headers(t: Table) -> list[str]:
    return [str(c.header) for c in t.columns]


def column(t: Table, head: str) -> list:
    return list(next(c for c in t.columns if str(c.header) == head)._cells)


def row_index(lines: list[str], team: str) -> int:
    return next(i for i, line in enumerate(lines) if team in line)


def preseason(lg):
    """Everybody 0-0 with zeros, no odds: the app before the first matchup ends."""
    for t in lg.teams.values():
        t.wins = t.losses = t.ties = 0
        t.points_for = t.points_against = t.games_back = 0.0
        t.streak_type, t.streak_length = "", 0
        t.division_record = (0, 0, 0)
        t.acquisitions = t.drops = t.trades = 0
        t.playoff_pct = t.division_win_pct = None
    return lg


# --- the views --------------------------------------------------------------------------------

def test_three_views_and_the_cli_view_flag(capsys):
    assert [k for k, _ in standings.VIEWS] == ["league", "divisions", "moves"]
    assert view_index(standings, "moves") == MOVES
    with pytest.raises(BenchbossError, match="league, divisions, moves"):
        view_index(standings, "playoffs")
    main(["--demo", "standings", "--view", "divisions"])
    out = capsys.readouterr().out
    assert "East" in out and "West" in out and "Div" in out
    main(["--demo", "standings", "--view", "moves"])
    assert "Waiver" in capsys.readouterr().out


def test_league_view_in_espn_seed_order_with_every_column(league):
    out = standings.draw(league, DARK, 120, LEAGUE)
    [t] = tables(out)
    assert headers(t) == ["#", "Team", "Manager", "W-L", "Pct", "GB", "PF", "PA", "Diff", "Strk",
                          "Playoffs"]
    names = [c.plain.split(" ")[0] for c in column(t, "Team")]
    assert names == [x.name.split(" ")[0] for x in league.standings()]
    text = text_of(out, 120)
    assert text.splitlines()[0].startswith("Demo Hoops League")
    assert "week 3 of 20" in text and "top 4 make the playoffs" in text
    brick = next(line for line in text.splitlines() if "Brick City" in line)
    # rank, record, baseball pct, GB dash for the leader, PF, PA, streak, odds with a meter
    for part in ("1", "2-0", "1.000", "3,218.8", "2,856.9", "+361.9", "W2", "87%", "━"):
        assert part in brick
    assert ".500" in text and "0.500" not in text


def test_your_team_is_bold_accent(league):
    [t] = tables(standings.draw(league, DARK, 120, LEAGUE))
    mine = next(c for c in column(t, "Team") if c.plain.startswith("Monstars"))
    assert mine.style == f"bold {DARK.accent}"
    other = next(c for c in column(t, "Team") if c.plain.startswith("Brick City"))
    assert other.style == DARK.text


@pytest.mark.parametrize("pal", [DARK, LIGHT])
def test_diff_has_a_sign_and_good_or_bad_color(league, pal):
    [t] = tables(standings.draw(league, pal, 120, LEAGUE))
    by_team = dict(zip([c.plain for c in column(t, "Team")], column(t, "Diff"), strict=True))
    assert by_team["Brick City"].plain == "+361.9" and by_team["Brick City"].style == pal.good
    assert by_team["Pick and Roll Pros"].plain == "-13.0"
    assert by_team["Pick and Roll Pros"].style == pal.bad
    for team in league.teams.values():
        cell = by_team[team.name]
        assert float(cell.plain.replace(",", "")) == pytest.approx(team.point_diff, abs=0.05)
    # an even difference has no sign and no color
    swish = next(x for x in league.teams.values() if x.name == "Swish Kebab")
    swish.points_against = swish.points_for
    [t] = tables(standings.draw(league, pal, 120, LEAGUE))
    even = dict(zip([c.plain for c in column(t, "Team")], column(t, "Diff"), strict=True))["Swish Kebab"]
    assert even.plain == "0.0" and even.style == pal.dim


def test_streaks_are_colored(league):
    [t] = tables(standings.draw(league, DARK, 120, LEAGUE))
    strk = {c.plain: c.style for c in column(t, "Strk")}
    assert strk["W2"] == DARK.good and strk["L2"] == DARK.bad


def test_playoff_line_sits_after_the_last_playoff_seed(league):
    lines = text_of(standings.draw(league, DARK, 120, LEAGUE), 120).splitlines()
    rule = [i for i, line in enumerate(lines) if line.strip().startswith(standings.LINE * 4)]
    order = league.standings()
    assert len(rule) == 1
    assert row_index(lines, order[3].name) < rule[0] < row_index(lines, order[4].name)
    assert "playoff line" in lines[-1] or "playoff line" in lines[-2]

    league.playoff_teams = 6
    lines = text_of(standings.draw(league, DARK, 120, LEAGUE), 120).splitlines()
    rule = next(i for i, line in enumerate(lines) if line.strip().startswith(standings.LINE * 4))
    assert row_index(lines, order[5].name) < rule < row_index(lines, order[6].name)

    league.playoff_teams = 0  # no playoffs set up: no line, no "top N" in the title
    text = text_of(standings.draw(league, DARK, 120, LEAGUE), 120)
    assert standings.LINE * 4 not in text and "playoff" not in text.splitlines()[0]


@pytest.mark.parametrize("pal", [DARK, LIGHT])
@pytest.mark.parametrize("view", [LEAGUE, DIVISIONS, MOVES])
@pytest.mark.parametrize("width", (20, 30, 46, 60, 80, 100, 120, 160))
def test_every_view_fits_its_width(league, pal, view, width):
    text = text_of(standings.draw(league, pal, width, view), width)
    assert max(len(line) for line in text.splitlines()) <= width
    # names may be cut on a tiny screen, numbers never
    assert "Mon" in text and ("10th" if view == MOVES else "2-0") in text


def test_narrow_widths_drop_secondary_columns_first(league):
    def heads(width, view=LEAGUE):
        return [h for t in tables(standings.draw(league, DARK, width, view)) for h in headers(t)]

    wide, mid, narrow = heads(160), heads(80), heads(46)
    assert "Manager" in wide and "Manager" not in mid
    assert "━" in text_of(standings.draw(league, DARK, 120, LEAGUE), 120)
    assert "━" not in text_of(standings.draw(league, DARK, 80, LEAGUE), 80)  # the meter goes
    assert {"Strk", "Pct"} <= set(heads(100)) and not {"Strk", "Pct"} & set(mid)
    # the key columns stay, and full team names still fit the 46 column board
    assert {"#", "Team", "W-L", "PF", "PA", "Diff"} <= set(narrow)
    text = text_of(standings.draw(league, DARK, 46, LEAGUE), 46)
    for team in league.teams.values():
        assert team.name in text
    assert "3219" in text and "+362" in text  # rounded, never cut
    assert "Div" in heads(46, DIVISIONS) and "W-L" in heads(46, DIVISIONS)


def test_divisions_keep_pf_and_pa_together_and_cut_a_long_division_name(league):
    for width in (46, 60, 74, 80, 100, 120, 160):
        out = standings.draw(league, DARK, width, DIVISIONS)
        heads = {h for t in tables(out) for h in headers(t)}
        assert ("PF" in heads) == ("PA" in heads), width
    league.divisions = {0: "The Northern Lights Conference", 1: "West"}
    lines = text_of(standings.draw(league, DARK, 46, DIVISIONS), 46).splitlines()
    head = next(i for i, line in enumerate(lines) if "The Northern" in line)
    assert "…" in lines[head] and "W-L" in lines[head]  # cut on its own line, never wrapped
    assert lines[head + 1].strip().startswith("─")


def test_moves_keep_full_names_at_46_and_leave_clinch_tags_to_the_standings(league):
    order = league.standings()
    order[0].clinch, order[-1].clinch = "PLAYOFFS", "ELIMINATED"
    out = standings.draw(league, DARK, 46, MOVES)
    [t] = tables(out)
    assert {c.plain for c in column(t, "Team")} == {x.name for x in league.teams.values()}
    assert "Drops" not in headers(t) and {"Adds", "Trades"} <= set(headers(t))
    assert "clinched" not in text_of(standings.draw(league, DARK, 120, MOVES), 120)


def test_divisions_view_sorts_each_division_by_record(league):
    out = standings.draw(league, DARK, 120, DIVISIONS)
    east, west = tables(out)
    assert headers(east)[1] == "East" and headers(west)[1] == "West"
    assert {"W-L", "GB", "Div", "PF", "PA", "Diff", "Strk", "Win div"} <= set(headers(east))
    for t, div_id in ((east, 0), (west, 1)):
        names = [c.plain for c in column(t, headers(t)[1])]
        teams = [next(x for x in league.teams.values() if x.name == n) for n in names]
        assert {x.division_id for x in teams} == {div_id}
        pcts = [standings.win_pct(x) for x in teams]
        assert pcts == sorted(pcts, reverse=True)
        gbs = [c.plain for c in column(t, "GB")]
        assert gbs[0] == "-"
        divs = [c.plain for c in column(t, "Div")]
        assert divs == [standings._record(x.division_record) for x in teams]
    # the stacked tables line up column by column
    assert [c.min_width for c in east.columns] == [c.min_width for c in west.columns]
    text = text_of(out, 120)
    assert "Monstars" in text and "2-0" in text and "games back in the division" in text


def test_division_games_back_counts_from_the_division_leader(league):
    by_name = {t.name: t for t in league.teams.values()}
    leader, other = by_name["Monstars"], by_name["Fast Break Cartel"]
    assert standings.division_gb(leader, other) == 2.0
    assert standings.division_gb(leader, leader) == 0.0


def test_moves_view_follows_the_waiver_order(league):
    out = standings.draw(league, DARK, 120, MOVES)
    [t] = tables(out)
    assert headers(t)[:2] == ["Waiver", "Team"]
    assert {"Adds", "Drops", "Trades"} <= set(headers(t))
    order = [c.plain for c in column(t, "Waiver")]
    assert order[0] == "1st" and order[1] == "2nd" and order[-1] == "10th"
    first = column(t, "Team")[0].plain
    assert next(x for x in league.teams.values() if x.name == first).waiver_rank == 1
    adds = {c.plain: n.plain for c, n in zip(column(t, "Team"), column(t, "Adds"), strict=True)}
    for team in league.teams.values():
        assert adds[team.name] == str(team.acquisitions)
    text = text_of(out, 120)
    assert "15 adds and 0 trades so far" in text and "claim order" in text


def test_clinch_tags_show_and_only_the_ones_used_are_explained(league):
    order = league.standings()
    order[0].clinch, order[-1].clinch = "PLAYOFFS", "ELIMINATED"
    out = standings.draw(league, DARK, 120, LEAGUE)
    [t] = tables(out)
    cells = {c.plain: c for c in column(t, "Team")}
    assert f"{order[0].name} x" in cells and f"{order[-1].name} e" in cells
    text = text_of(out, 120)
    assert "x clinched playoffs" in text and "e eliminated" in text
    assert "clinched division" not in text and "clinched bye" not in text
    assert "x clinched playoffs" not in text_of(standings.draw(demo_session().league(), DARK, 120), 120)
    # a cut name keeps its tag, so the legend never explains a tag that is not on screen
    for team in league.teams.values():
        team.name += " of the Rio Grande Valley"
    for width, view in ((46, LEAGUE), (30, LEAGUE), (46, DIVISIONS)):
        names = [c for t in tables(standings.draw(league, DARK, width, view))
                 for c in t.columns[1]._cells]
        assert next(c for c in names if c.plain.startswith("Fast")).plain.endswith("… e")
        assert next(c for c in names if c.plain.startswith("Brick")).plain.endswith("… x")


def test_missing_odds_read_as_a_dash(league):
    league.standings()[0].playoff_pct = None
    [t] = tables(standings.draw(league, DARK, 80, LEAGUE))
    assert column(t, "Playoffs")[0].plain == "-"
    assert standings._odds(0.001) == "<1%" and standings._odds(0.999) == ">99%"
    assert standings._odds(1.0) == "100%"


def test_preseason_looks_intentional(league):
    preseason(league)
    for view in (LEAGUE, DIVISIONS, MOVES):
        for width in WIDTHS:
            text = text_of(standings.draw(league, LIGHT, width, view), width)
            assert max(len(line) for line in text.splitlines()) <= width
            assert ".000" not in text and "+0" not in text and "-0.0" not in text
    text = text_of(standings.draw(league, DARK, 120, LEAGUE), 120)
    assert "No results yet" in text
    assert "Playoffs" not in text  # no odds from ESPN yet: no empty column
    [t] = tables(standings.draw(league, DARK, 120, LEAGUE))
    assert {c.plain for c in column(t, "Pct")} == {"-"}
    assert {c.plain for c in column(t, "PF")} == {"-"} and {c.plain for c in column(t, "Diff")} == {"-"}
    assert {c.plain for c in column(t, "W-L")} == {"0-0"}
    rows = standings.to_json(league)
    assert all(r["win_pct"] == 0 and r["point_diff"] == 0 and r["streak"] is None for r in rows)


def test_pct_reads_the_baseball_way():
    from benchboss.espn.models import Team

    assert standings._pct3(Team(1, "A", wins=3, losses=1)) == ".750"
    assert standings._pct3(Team(1, "A", wins=4)) == "1.000"
    assert standings._pct3(Team(1, "A", wins=1999, losses=1)) == "1.000"
    assert standings._pct3(Team(1, "A", wins=1, losses=1, ties=2)) == ".500"
    assert standings._pct3(Team(1, "A")) == "-"


# --- JSON -------------------------------------------------------------------------------------

def test_json_keeps_the_old_keys_and_adds_the_new_ones(capsys, league):
    main(["--demo", "--json", "standings"])
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 10
    keys = {"rank", "team", "manager", "record", "wins", "losses", "ties", "win_pct", "games_back",
            "points_for", "points_against", "point_diff", "streak", "playoff_pct", "clinch",
            "division", "division_record", "waiver_rank", "acquisitions", "drops", "trades"}
    assert all(set(r) == keys for r in rows)
    assert [r["rank"] for r in rows] == list(range(1, 11))
    assert [r["team"] for r in rows] == [t.name for t in league.standings()]
    first = rows[0]
    assert first["team"] == "Brick City" and first["record"] == "2-0" and first["win_pct"] == 1.0
    assert first["point_diff"] == pytest.approx(first["points_for"] - first["points_against"], abs=0.1)
    assert first["division"] == "West" and first["streak"] == "W2"
    assert 0 <= first["playoff_pct"] <= 1 and first["clinch"] is None
    assert {r["division"] for r in rows} == {"East", "West"}
    assert sorted(r["waiver_rank"] for r in rows) == list(range(1, 11))


# --- the app ----------------------------------------------------------------------------------

def test_app_cycles_the_views_with_v_and_the_menu_keys_still_work():
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(150, 44)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            seen = []
            for _ in range(3):
                seen.append(text_of(app.query_one("#body").content, 120))
                await pilot.press("v")
                await pilot.pause()
            assert "Playoffs" in seen[0] and "playoff line" in seen[0]
            assert "East" in seen[1] and "Win div" in seen[1]
            assert "Waiver" in seen[2] and "1st" in seen[2]
            assert "Playoffs" in text_of(app.query_one("#body").content, 120)  # back to League
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.current == "roster"

    asyncio.run(run())


def test_a_resize_redraws_at_the_new_width():
    """Textual stores the new size after the app's own resize handler runs: the screen must be
    drawn for the new width, or the table overflows and Rich squeezes the team names away."""
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(150, 44)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.resize_terminal(64, 40)
            await pilot.pause()
            assert app.query_one("#menu").has_class("hidden")  # 64 columns is narrow
            text = text_of(app.query_one("#body").content, 58)  # 64 minus padding and scrollbar
            assert max(len(line) for line in text.splitlines()) <= 58
            assert "Pick and Roll Pros" in text and "Diff" in text

    asyncio.run(run())

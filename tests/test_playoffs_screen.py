"""The playoff race screen: the odds and games-left views, the scenario builder in the app and
the playoffs command, all on the demo league (week 3 of 20, 4 spots, two divisions)."""

import asyncio
import copy
import io
import json
import re

import pytest
from rich.console import Console

from benchboss.cli import main
from benchboss.config import Config
from benchboss.core import playoffs as core
from benchboss.demo import demo_session
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import playoffs
from benchboss.ui.theme import DARK, LIGHT

WIDTHS = (46, 80, 120, 160)
SIMS = 400


def text_of(renderable, width: int = 140) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


@pytest.fixture(scope="module")
def race():
    return playoffs.load(demo_session(), sims=SIMS)


@pytest.fixture(scope="module")
def picked():
    s = demo_session()
    picks = core.parse_picks(s.league(), ["Monstars>Pick and Roll Pros", "Splash Mountain>Monstars@18"])
    return playoffs.load(s, picks, sims=SIMS)


def league_where(case: str):
    """The demo league in the preseason, after the regular season, or with no playoff spots."""
    lg = demo_session().league()
    if case == "nospots":
        lg.playoff_teams = 0
    if case == "preseason":
        lg.current_matchup = 1
        for m in lg.matchups:
            m.winner, m.home.points, m.away.points = "UNDECIDED", 0.0, 0.0
        for t in lg.teams.values():
            t.playoff_pct = None
    if case == "over":
        lg.current_matchup = lg.regular_season_weeks + 1
        for m in lg.matchups:
            if not m.decided:
                m.home.points = 400.0 + (m.home.team_id * 7) % 50
                m.away.points = 400.0 + (m.away.team_id * 11) % 50
                m.winner = "HOME" if m.home.points > m.away.points else "AWAY"
    return lg


# --- the static views ---------------------------------------------------------------------------

@pytest.mark.parametrize("view", [0, 1])
@pytest.mark.parametrize("pal", [DARK, LIGHT], ids=["dark", "light"])
@pytest.mark.parametrize("width", WIDTHS)
def test_both_views_fit_every_width_in_both_themes(race, picked, view, pal, width):
    for data in (race, picked):
        out = text_of(playoffs.draw(data, pal, width, view), width)
        assert all(len(line) <= width for line in out.splitlines()), out
        assert out.startswith("Playoff race")
        assert "…" not in out.split("\n", 3)[3] or view == 1  # the odds table never cuts a name
        if view == 0:
            for o in data.teams:
                assert o.team.name in out
            # nothing is certain in week 3: never a flat 0% or 100%
            assert not re.search(r"(?<![\d<>])0%|(?<![\d>])100%", out)
        else:
            assert "Week 3" in out and "Week 20" in out


def test_the_playoff_line_sits_under_the_last_spot(race):
    for width in WIDTHS:
        lines = text_of(playoffs.draw(race, DARK, width), width).splitlines()
        cut = [i for i, line in enumerate(lines) if "╌╌╌" in line]
        assert len(cut) == 1
        above, below = lines[cut[0] - 1], lines[cut[0] + 1]
        assert race.teams[race.playoff_teams - 1].team.name in above
        assert race.teams[race.playoff_teams].team.name in below


def test_wide_odds_show_seeds_divisions_bars_and_espn(race):
    out = text_of(playoffs.draw(race, DARK, 160), 160)
    for head in ("Div", "W-L", "Proj", "Playoffs", "1st", "4th", "Div title", "ESPN"):
        assert head in out
    assert "━" in out and "division winners seeded first" in out and "5,000" not in out
    assert f"{SIMS} simulated seasons" in out
    narrow = text_of(playoffs.draw(race, DARK, 46), 46)
    assert "ESPN" not in narrow and "━" not in narrow and "Playoffs" in narrow


def test_picks_show_as_picked_and_what_they_change(picked):
    odds = text_of(playoffs.draw(picked, DARK, 120), 120)
    assert "2 picks" in odds and "+/-" in odds
    assert "ESPN" not in odds  # ESPN's odds are the reference only without picks
    games = text_of(playoffs.draw(picked, DARK, 120, 1), 120)
    rows = [line for line in games.splitlines() if line.rstrip().endswith("picked") and " vs " in line]
    assert len(rows) == 2
    assert any("Monstars" in r and "Pick and Roll Pros" in r for r in rows)
    assert all(re.search(r"\b[WL]\b.*vs.*\b[WL]\b", r) for r in rows)
    assert "Week 18" in games  # a picked week shows even outside the final stretch
    data = playoffs.to_json(picked)
    assert {p["winner"] for p in data["picks"]} == {"Monstars", "Splash Mountain"}
    assert all("playoffs_without_picks" in t for t in data["teams"])
    assert json.dumps(data)


def test_games_view_opens_on_the_final_weeks_and_this_week(race):
    out = text_of(playoffs.draw(race, DARK, 120, 1), 120)
    weeks = [int(w) for w in re.findall(r"^Week (\d+)", out, re.M)]
    assert weeks == [3, 16, 17, 18, 19, 20]
    assert "12 earlier weeks hidden (weeks 4 to 15)" in out
    assert "this week" in out and "last week of the regular season" in out
    assert "live " in out  # this week's live scores


def test_the_hidden_weeks_note_skips_a_picked_week():
    s = demo_session()
    data = playoffs.load(s, core.parse_picks(s.league(), ["Swish Kebab>Brick City@6"]), sims=100)
    out = text_of(playoffs.draw(data, DARK, 120, 1), 120)
    assert "Week 6" in out and "11 earlier weeks hidden (weeks 4, 5 and 7 to 15)" in out
    assert playoffs._span([9]) == "week 9" and playoffs._span([9, 10]) == "weeks 9, 10"


def test_a_change_that_rounds_to_zero_reads_as_unchanged(picked):
    now, base = copy.deepcopy(picked), copy.deepcopy(picked.baseline)
    for after, before in zip(now.teams, base.teams, strict=True):
        after.playoffs, before.playoffs = 0.005, 0.0  # half a point: rounds to 0, not "+0"
    out = text_of(playoffs.odds_table(now, DARK, playoffs.fit_columns(now, DARK, 160, base)[0]), 160)
    assert "+/-" in out and not re.search(r" [+-]0 ", out)


def test_no_playoff_spots_preseason_and_season_over():
    none = core.race(league_where("nospots"), sims=100)
    out = text_of(playoffs.draw(none, DARK, 80), 80)
    assert "no playoff spots" in out and "Playoffs" not in out and "╌╌╌" not in out

    pre = core.race(league_where("preseason"), sims=200)
    out = text_of(playoffs.draw(pre, LIGHT, 120), 120)
    assert "clinched" not in out and " out" not in out and "ESPN" not in out
    assert all(o.record == "0-0" for o in pre.teams)
    assert "Week 1" in text_of(playoffs.draw(pre, LIGHT, 120, 1), 120)

    over = core.race(league_where("over"), sims=100)
    assert not over.games
    assert sorted(o.status for o in over.teams) == ["clinched"] * 4 + ["eliminated"] * 6
    for width in WIDTHS:
        out = text_of(playoffs.draw(over, DARK, width), width)
        assert "regular season is over" in out and out.count("clinched") == 4
        assert "Proj" not in out
        games = text_of(playoffs.draw(over, DARK, width, 1), width)
        assert "regular season is over" in games
    assert playoffs.to_json(over)["games"] == []


# --- the scenario builder -----------------------------------------------------------------------

async def settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def drive(app, scenario, size=(140, 44)):
    async def run():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await pilot.press("y")
            await settle(pilot)
            await scenario(pilot)
    asyncio.run(run())


def odds_text(builder, width: int = 100) -> str:
    return text_of(builder._draw_odds(builder.pal, width, 40), width)


def test_a_pick_reruns_the_race_and_c_clears_it():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        b = app.query_one(playoffs.PlayoffBuilder)
        assert app.focused is b and app.current == "playoffs"
        assert "Scenario builder" in str(app.query_one("#status").content)
        before = odds_text(b)
        g = b.current()
        assert g.week == 3 and b.race.me in (g.home, g.away)  # lands on your game this week
        await pilot.press("right")
        assert b.busy and "simulating..." in b._draw_head(b.pal, 140, 1).plain
        await settle(pilot)
        assert b.picks == {g.id: g.away}
        assert b.race is not b.initial and b.race.picks == b.picks
        assert b.race.sims == playoffs.SCENARIO_SIMS and not b.busy
        after = odds_text(b)
        assert after != before and "+/-" in after and "1 pick" in str(b._draw_foot(b.pal, 100, 3))
        # the same side again clears the pick
        await pilot.press("right")
        await settle(pilot)
        assert b.picks == {} and b.race is b.initial
        await pilot.press("l", "down", "h")
        await settle(pilot)
        assert len(b.picks) == 2
        await pilot.press("c")
        await settle(pilot)
        assert b.picks == {} and b.race is b.initial and odds_text(b) == before
        # fast presses: only the last run lands on screen
        await pilot.press("right", "left", "up", "right", "left")
        await settle(pilot)
        assert b.race.picks == b.picks and not b.busy
        assert b.picks == {x.id: x.home for x in b.games[b.cursor:b.cursor + 2]}

    drive(app, scenario)


def test_keys_move_jump_and_clear():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        b = app.query_one(playoffs.PlayoffBuilder)
        start = b.cursor
        await pilot.press("e")
        g = b.current()
        assert g.week == 16 and b.race.me in (g.home, g.away)
        await pilot.press("b")
        assert b.cursor == start
        await pilot.press("pagedown")
        assert b.current().week == 4
        await pilot.press("pageup", "down", "j", "up", "k")
        assert b.current().week == 3
        await pilot.press("left")
        await pilot.press("backspace")
        await settle(pilot)
        assert b.picks == {}
        await pilot.press("left", "0")
        await settle(pilot)
        assert b.picks == {}
        await pilot.press("up", "up", "up")  # already at the top: stays put
        assert b.cursor == 0 or b.current().week == 3

    drive(app, scenario)


def test_menu_keys_still_navigate_from_the_builder():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        assert isinstance(app.focused, playoffs.PlayoffBuilder)
        await pilot.press("s")
        await settle(pilot)
        assert app.current == "standings" and not app.query(playoffs.PlayoffBuilder)
        await pilot.press("y")
        await settle(pilot)
        assert isinstance(app.focused, playoffs.PlayoffBuilder)
        await pilot.press("d")
        await settle(pilot)
        assert app.current == "dash"

    drive(app, scenario)


def test_theme_and_width_changes_keep_the_builder():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        b = app.query_one(playoffs.PlayoffBuilder)
        assert b.has_class("-stacked")  # 140 columns with the menu: odds under the games
        await pilot.press("ctrl+t")
        await settle(pilot)
        assert app.query_one(playoffs.PlayoffBuilder) is b and b.pal is LIGHT
        await pilot.resize_terminal(200, 50)
        await pilot.pause()
        assert not b.has_class("-stacked")
        games = b.query_one("#pb-games")
        assert 40 <= games.size.width <= b.size.width // 2
        assert "Week 3" in text_of(b._draw_games(b.pal, games.size.width, games.size.height))

    drive(app, scenario)


@pytest.mark.parametrize("size", [(80, 24), (60, 30), (200, 20)])
def test_short_windows_keep_the_odds_inside_their_pane(size):
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        await pilot.press("right")
        await settle(pilot)
        b = app.query_one(playoffs.PlayoffBuilder)
        split, odds = b.query_one("#pb-split").region, b.query_one("#pb-odds")
        games = b.query_one("#pb-games")
        assert odds.region.bottom <= split.bottom and games.size.height >= playoffs.GAMES_MIN
        out = text_of(b._draw_odds(b.pal, odds.size.width, odds.size.height), odds.size.width)
        lines = out.rstrip("\n").splitlines()
        assert len(lines) <= odds.size.height
        # what is left of the table: your team and the playoff bubble around the dashed line
        assert "Monstars" in out and "╌╌╌" in out

    drive(app, scenario, size=size)


def test_the_games_list_keeps_the_cursor_in_view():
    b = playoffs.PlayoffBuilder(playoffs.load(demo_session(), sims=100), session=None)
    for i in range(len(b.games)):
        b.cursor = i
        out = text_of(b._draw_games(DARK, 70, 9), 70)
        lines = out.rstrip("\n").splitlines()
        assert len(lines) <= 9 and any(line.startswith("▸") for line in lines)
        assert lines[0].startswith("Week ")  # a heading, pinned when the week is scrolled into
        assert not lines[-1].startswith("Week ")  # never a heading alone at the bottom
    # e on a tall list: the final weeks start the window, not the tail of the week before
    b.action_final()
    lines = text_of(b._draw_games(DARK, 70, 40), 70).splitlines()
    assert lines[0].startswith("Week 16") and lines[1].startswith("▸")


def test_season_over_builder_has_nothing_to_pick():
    over = core.race(league_where("over"), sims=50)
    b = playoffs.PlayoffBuilder(over, session=None)
    assert b.current() is None
    b.action_pick("home")
    b.action_move(1)
    assert b.picks == {}
    assert "regular season is over" in text_of(b._draw_games(DARK, 60, 10))


# --- the command --------------------------------------------------------------------------------

def run(capsys, *args):
    main(list(args))
    return capsys.readouterr().out


def test_cli_picks_views_and_json(capsys):
    out = run(capsys, "--demo", "playoffs", "--sims", "200", "--pick", "Monstars>Pick and Roll Pros")
    assert "1 pick" in out and "+/-" in out
    out = run(capsys, "--demo", "playoffs", "--sims", "200", "--view", "games")
    assert "Week 16" in out and "earlier weeks hidden" in out
    data = json.loads(run(capsys, "--demo", "--json", "playoffs", "--sims", "200",
                          "--pick", "Tune Squad>Monstars@11"))
    assert data["sims"] == 200 and data["picks"][0]["winner"] == "Tune Squad"
    game = next(g for g in data["games"] if g["week"] == 11 and "Monstars" in (g["home"], g["away"]))
    assert game["picked_winner"] == "Tune Squad"
    assert len(data["teams"]) == 10 and "playoffs_without_picks" in data["teams"][0]
    plain = json.loads(run(capsys, "--demo", "--json", "playoffs", "--sims", "100"))
    assert plain["picks"] == [] and "playoffs_without_picks" not in plain["teams"][0]


def test_cli_rejects_a_bad_pick(capsys):
    with pytest.raises(SystemExit):
        main(["--demo", "playoffs", "--pick", "Monstars>Monstars"])
    assert "cannot play itself" in capsys.readouterr().err

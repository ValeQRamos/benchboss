"""Regression tests for the 1.0.2 visual audit: one look and one number on every screen."""

import asyncio
import io
import re
from pathlib import Path

import pytest
from rich.console import Console
from rich.style import Style
from textual.widgets import Input

from benchboss.config import Config
from benchboss.core import playoffs
from benchboss.ui import common, dashboard, views
from benchboss.ui.app import Benchboss
from benchboss.ui.common import fit_title, odds_color, rost_cell, rostered, shooting_pct
from benchboss.ui.screens import finder, roster, standings, trash
from benchboss.ui.theme import DARK, LIGHT

ROOT = Path(__file__).resolve().parents[1]


def repo_file(rel: str) -> Path:
    """A file from the repository; tests that need one skip when run from an sdist."""
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} is not part of this checkout")
    return path


def text_of(renderable, width: int = 160) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def lines_of(renderable, width: int) -> list[str]:
    return [line.rstrip() for line in text_of(renderable, width).splitlines()]


# --- vis-1: the playoff race and the matchup card agree on this week -------------------------------

def test_the_live_week_in_the_race_follows_the_matchup_card(session):
    o = session.outlook()
    assert o.opponent and o.me.projected < o.opponent.projected - 50  # a clear projected loss
    race = session.playoff_race({}, 2000)
    me = session.league().my_team_id
    game = next(g for g in race.games if g.live and me in (g.home, g.away))
    mine = race.home_win[game.id] if game.home == me else 1 - race.home_win[game.id]
    assert mine < 0.4  # was 52%: the 14-day average hid the 29 vs 33 games left


def test_race_scores_the_rest_of_the_live_week_from_live_left(session):
    lg = session.league()
    live = [g for g in playoffs.season_games(lg) if g.live]
    assert live
    g = live[0]
    left = {tid: 0.0 for tid in lg.teams}
    left[g.home] = 3000.0
    assert playoffs.race(lg, sims=200, live_left=left).home_win[g.id] > 0.99
    left[g.home], left[g.away] = 0.0, 3000.0
    assert playoffs.race(lg, sims=200, live_left=left).home_win[g.id] < 0.01


# --- vis-3: % rostered and shooting look the same everywhere ---------------------------------------

def test_shared_formats():
    assert rostered(99.6) == "100" and rostered(46.4) == "46" and rostered(7.12) == "7.1"
    assert shooting_pct(0.4537) == ".454" and shooting_pct(1.0) == "1.000"
    assert shooting_pct(0.0) == ".000"


def test_roster_uses_the_shared_rost_and_shooting_cells(session):
    data = roster.load(session)
    lamelo = next(sp.player for sp in data.league.me.roster if sp.player.name == "LaMelo Ball")
    out = text_of(roster.draw(data, DARK, 200), 200)
    head = next(line for line in out.splitlines() if " Player " in line)
    assert "Rost%" in head and "+/-" not in head
    row = next(line for line in out.splitlines() if "LaMelo Ball" in line)
    assert rost_cell(lamelo, DARK).plain.rstrip() in row
    assert shooting_pct(lamelo.split("season").fg_pct) in row and "%" not in row


def test_trash_and_free_agents_say_rost_with_the_shared_cell(session):
    data = trash.load(session)
    out = text_of(trash.draw(data, DARK, 160), 160)
    assert "Rost%" in out and "Own%" not in out
    for pk in data.picks:
        row = next(line for line in out.splitlines() if pk.player.name in line)
        assert rost_cell(pk.player, DARK).plain.rstrip() in row
    fas = session.free_agents(8)
    out = text_of(views.free_agents(fas, DARK, "Free agents"), 120)
    assert "Rost%" in out and "Own%" not in out and "Δ%" not in out
    for p in fas:
        row = next(line for line in out.splitlines() if p.name in line)
        assert rost_cell(p, DARK).plain.rstrip() in row


def test_finder_and_dashboard_use_the_same_rost_cell(session):
    assert finder.rost_cell is common.rost_cell
    d = dashboard.collect(session)
    out = text_of(dashboard.trending_card(d, DARK), 60)
    for p in d.trending:
        assert rost_cell(p, DARK).plain.strip() in out
    assert not re.search(r"[+-]\d+\.\d%", out)  # no more "+1.7%"


# --- vis-4: the README shows 1.0.2 -----------------------------------------------------------------

def test_readme_shows_the_logo_and_the_new_screens():
    readme = (ROOT / "README.md").read_text()
    assert "docs/images/logo.png" in readme and "🏀" not in readme
    for shot in ("players.png", "playoffs.png"):
        assert f"docs/images/{shot}" in readme and (repo_file("docs/images") / shot).exists()
    for feature in ("Player finder", "Playoff race", "watch list"):
        assert feature.lower() in readme.lower()
    shots = repo_file("tools/screenshots.py").read_text()
    assert '"players"' in shots and '"playoffs"' in shots


def test_changelog_describes_1_0_2():
    log = (ROOT / "CHANGELOG.md").read_text()
    entry = log.split("## [1.0.2]", 1)[1].split("## [1.0.1]", 1)[0]
    assert "Work in progress" not in entry
    assert "Player finder" in entry and "Playoff race" in entry and "watch list" in entry


# --- vis-5: playoff odds read the same on every screen ---------------------------------------------

@pytest.mark.parametrize("pal", [DARK, LIGHT])
def test_odds_have_one_color_scale(pal):
    for v in (0.05, 0.19, 0.2, 0.29, 0.3, 0.59, 0.6, 0.9):
        assert standings._odds_color(v, pal) == odds_color(v, pal)
    assert odds_color(0.29, pal) == pal.warn and odds_color(0.1, pal) == pal.bad
    assert odds_color(0.7, pal) == pal.good


def _color_of(renderable, width: int, text: str):
    console = Console(width=width, file=io.StringIO(), color_system="truecolor")
    for seg in console.render(renderable, console.options.update_width(width)):
        if seg.text.strip() == text:
            return seg.style.color
    raise AssertionError(f"{text!r} not drawn")


def test_dashboard_odds_are_labeled_espn_and_colored_like_standings(session):
    d = dashboard.collect(session)
    odds = d.league.me.playoff_pct
    assert odds is not None
    label = f"{odds * 100:.0f}%"
    out = text_of(dashboard.header(d, DARK, 120), 120)
    assert f"{label} ESPN playoff odds" in out
    assert _color_of(dashboard.header(d, DARK, 120), 120, label) == Style.parse(odds_color(odds, DARK)).color


@pytest.mark.parametrize("width", [36, 40, 44, 46, 120])
def test_the_dashboard_odds_line_is_never_cut(session, width):
    d = dashboard.collect(session)
    line = next(x for x in lines_of(dashboard.header(d, DARK, width), width) if "playoff odds" in x)
    assert "…" not in line and len(line) <= width


# --- vis-6: the finder's pool tabs never hide under the search box ---------------------------------

async def _settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.parametrize("width", [40, 46, 48, 52])
def test_every_finder_tab_shows_in_a_narrow_window(width):
    seen = {}

    async def run():
        app = Benchboss(Config(theme="dark"), demo=True)
        async with app.run_test(size=(width, 40)) as pilot:
            await _settle(pilot)
            await pilot.press("p")
            await _settle(pilot)
            await pilot.pause(0.3)
            view = app.query_one(finder.FinderView)
            tabs = view.query_one("#finder-tabs")
            search = view.query_one("#finder-search", Input)
            seen["plain"] = tabs.content.plain
            seen["fits"] = tabs.regions[-1][2] <= min(tabs.region.width,
                                                      search.region.x - tabs.region.x)
            seen["search"] = search.region.width

    asyncio.run(run())
    assert seen["fits"], seen
    assert all(f" {n}" in seen["plain"] for n in "1234")
    assert seen["search"] >= finder.SEARCH_MIN


# --- vis-7: the titles the app builds keep to one line ---------------------------------------------

def test_fit_title_drops_context_until_it_fits():
    full = fit_title("Inbox", DARK, 200, ("trade offers, claims", "1 needs you"), ("1 needs you",))
    assert full.plain == "Inbox  ·  trade offers, claims  ·  1 needs you"
    short = fit_title("Inbox", DARK, 30, ("trade offers, claims", "1 needs you"), ("1 needs you",))
    assert short.plain == "Inbox  ·  1 needs you"
    assert fit_title("Inbox", DARK, 8, ("trade offers, claims",)).plain == "Inbox"


@pytest.mark.parametrize("sid", ["week", "today", "trades", "inbox"])
@pytest.mark.parametrize("width", [46, 56, 74, 120])
def test_app_titles_never_wrap(session, sid, width):
    app = Benchboss(Config(), demo=True, session=session)
    draw, _ = app._build(sid)
    out = lines_of(draw(DARK, width), width)
    assert out[0] and not out[1], out[:3]  # the title, then the blank line under it
    assert len(out[0]) <= width


# --- vis-8: the Trade finder follows the common look -----------------------------------------------

def test_balance_never_prints_minus_zero():
    bal = {"Monstars": {"PG": -24.2, "SG": -0.2, "SF": 0.4, "PF": -17.0, "C": 26.6}}
    out = text_of(views.needs(bal, "Monstars", DARK, 80), 80)
    row = next(line for line in out.splitlines() if "Monstars" in line)
    assert row.split()[1:] == ["-24", "0", "0", "-17", "+27"]


@pytest.mark.parametrize("width", [40, 46, 80])
def test_balance_title_and_team_names_keep_to_one_line(session, width):
    from benchboss.core import trades as trades_mod

    lg = session.league()
    bal = trades_mod.describe_needs(lg)
    out = lines_of(views.needs(bal, lg.me.name, DARK, width), width)
    assert out[0].startswith("Positional balance") and len(out[0]) <= width
    rows = [line for line in out if re.search(r"[+-]?\d+\s*$", line) and "─" not in line]
    assert len(rows) == len(bal)  # one row per team: no name wrapped onto a second row
    assert all("…" not in re.sub(r"^\s*\S.*?\s{2,}", "", r) for r in rows)  # numbers whole
    assert max(len(line) for line in out) <= width


def test_trade_messages_wrap_under_their_indent(session):
    ideas = session.trades(n=3)
    assert ideas
    out = lines_of(views.trades(ideas, DARK), 60)
    body = [line for line in out if line and not re.match(r"\d+\. ", line)]
    assert body and all(line.startswith("   ") for line in body)

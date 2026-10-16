"""The 1.0.2 roster screen: every stat split, the selected view, the preseason and narrow widths."""

import asyncio
import datetime as dt
import io
import json
import re

import pytest
from rich.console import Console
from rich.table import Table
from textual.widgets import Static

from benchboss.cli import main
from benchboss.config import Config
from benchboss.espn.constants import IR, SPLIT_SHORT
from benchboss.ui import views
from benchboss.ui.app import Benchboss
from benchboss.ui.common import shooting_pct
from benchboss.ui.screens import roster
from benchboss.ui.theme import DARK, LIGHT

KEYS = [k for k, _ in roster.VIEWS]
WIDTHS = (46, 80, 120, 160)


def render(data, width=160, view=0, pal=DARK) -> str:
    console = Console(record=True, width=width, file=io.StringIO())
    console.print(roster.draw(data, pal, width, view))
    return console.export_text()


def headers(table: Table) -> list[str]:
    return [str(c.header).strip() for c in table.columns]


def selected(table: Table, pal=DARK) -> list[str]:
    return [str(c.header).strip() for c in table.columns if c.header_style == f"bold {pal.accent}"]


def column(table: Table, name: str) -> list:
    return list(next(c for c in table.columns if str(c.header).strip() == name).cells)


def row_of(text: str, name: str) -> str:
    return next(line for line in text.splitlines() if name in line)


def rules(text: str) -> int:
    """Lines that are a thin section rule."""
    return sum(1 for line in text.splitlines() if line and set(line) == {"┄"})


def last_names(data) -> list[str]:
    return [" ".join(sp.player.name.split()[1:]) for sp in data.league.me.roster]


@pytest.fixture
def data(session):
    return roster.load(session)


@pytest.fixture
def preseason(session):
    """Five days before opening night: ESPN only has the projection and last season."""
    session._today = session.calendar.date_of(1) - dt.timedelta(days=5)
    for sp in session.league().me.roster:
        sp.player.stats = {k: v for k, v in sp.player.stats.items() if k in ("proj", "last")}
    return roster.load(session)


# --- views ---------------------------------------------------------------------------------------

def test_views_are_the_stat_splits_in_order():
    assert roster.VIEWS == (("season", "Season"), ("l7", "Last 7"), ("l15", "Last 15"),
                            ("l30", "Last 30"), ("proj", "Projected"), ("last", "Last season"))


@pytest.mark.parametrize("view", range(len(KEYS)))
def test_every_view_renders_with_its_title(data, view):
    text = render(data, 160, view)
    first = text.splitlines()[0]
    assert first.startswith("Roster") and "Monstars 2-0" in first
    assert roster.LONG[KEYS[view]] in first
    assert "Fantasy points per game" in text and f"{roster.LONG[KEYS[view]]}, per game" in text
    for name in last_names(data):
        assert name in text


@pytest.mark.parametrize("view", range(len(KEYS)))
def test_the_selected_column_follows_the_view(data, view):
    table = roster.draw(data, DARK, 160, view)
    assert selected(table) == [SPLIT_SHORT[KEYS[view]]]
    # every split sits side by side at full width, then the box score and ownership
    assert headers(table) == ["Slot", "Player", "Pos", "Today", "Avg", "L7", "L15", "L30", "Proj",
                              "Prev", "GP", "MIN", "PTS", "REB", "AST", "STL", "BLK", "3PM", "TO",
                              "FG%", "FT%", "Rost%"]


def test_the_box_score_is_the_selected_split(data):
    lamelo = next(sp.player for sp in data.league.me.roster if sp.player.name == "LaMelo Ball")
    for view, key in enumerate(KEYS):
        line = lamelo.split(key)
        table = roster.draw(data, DARK, 160, view)
        cells = {h: column(table, h)[0].plain for h in ("GP", "PTS", "REB", "FG%")}
        assert cells == {"GP": str(line.gp), "PTS": f"{line.pts:.1f}", "REB": f"{line.reb:.1f}",
                         "FG%": shooting_pct(line.fg_pct)}


def test_cli_view_flag(capsys):
    main(["--demo", "roster", "--view", "l30"])
    assert "Last 30 days" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--demo", "roster", "--view", "l99"])
    assert "unknown view" in capsys.readouterr().err


# --- rows ----------------------------------------------------------------------------------------

def test_starters_in_slot_order_then_bench(data):
    text = render(data, 160)
    slots = [line.split()[0] for line in text.splitlines()
             if line[:2] in ("PG", "SG", "SF", "PF", "C ", "G ", "F ", "UT", "BE", "IR")]
    assert slots == ["PG", "SG", "SF", "PF", "C", "G", "F", "UT", "UT", "UT", "BE", "BE", "BE"]
    assert rules(text) == 1  # one thin rule between the starters and the bench


def test_ir_and_an_empty_slot(session):
    me = session.league().me
    duren = next(sp for sp in me.roster if sp.player.name == "Jalen Duren")
    duren.slot_id = IR
    duren.player.injury_status = "OUT"
    text = render(roster.load(session), 160)
    lines = text.splitlines()
    empty = next(i for i, line in enumerate(lines) if line.startswith("C ") and "Empty" in line)
    bench = next(i for i, line in enumerate(lines) if line.startswith("BE"))
    ir = next(i for i, line in enumerate(lines) if line.startswith("IR"))
    assert empty < bench < ir and "Jalen Duren DET OUT" in lines[ir]
    assert rules(text) == 2  # starters | bench | IR


def test_today_shows_the_opponent(data):
    text = render(data, 160)
    for sp in data.league.me.roster:
        opp = data.opponents[sp.player.id]
        assert " " not in opp and opp.lstrip("@").isalpha()
        assert opp in row_of(text, sp.player.name)


def test_trend_arrows_compare_last_7_days_with_the_season(data):
    text = render(data, 160)
    assert "▲43.3" in row_of(text, "Tobias Harris")   # 43.3 in the last 7 days, 31.4 this season
    assert "▼32.2" in row_of(text, "Dyson Daniels")   # 32.2 against 38.0
    assert "▲" not in row_of(text, "LaMelo Ball") and "▼" not in row_of(text, "LaMelo Ball")


@pytest.mark.parametrize("width,value", [(160, "43.3"), (80, "31.4")])  # on L7, or on Avg
def test_the_trend_arrow_keeps_the_decimal_points_in_line(data, width, value):
    """A right-justified cell loses its trailing spaces, so the arrow goes in front."""
    text = render(data, width)
    harris = row_of(text, "Tobias Harris")
    column_end = harris.index(value) + len(value)
    for sp in data.league.me.roster:
        row = row_of(text, sp.player.name)
        assert row[column_end - 2] == "." and row[column_end - 1].isdigit(), row


def test_the_legend_explains_what_is_on_screen(data):
    wide = render(data, 160).splitlines()[-1]
    for part in ("Avg this season", "L7 L15 L30", "Prev last season", "▲▼",
                 "Rost% of ESPN leagues, ▲▼ change in a week"):
        assert part in wide
    narrow = render(data, 46).splitlines()[-1]
    assert narrow.startswith("▲▼") and len(narrow) <= 46  # the arrows are kept the longest


def test_group_labels_never_look_cramped(data):
    for width in range(46, 161):
        groups = render(data, width).splitlines()[2]
        labels = re.findall(r"(─+) [^─]+ (─+)", groups)
        assert labels and all(len(left) >= 2 and len(right) >= 2 for left, right in labels), groups


def test_an_empty_roster_says_so(session):
    session.league().me.roster.clear()
    data = roster.load(session)
    text = render(data, 80)
    assert text.splitlines()[0].startswith("Roster") and "No players yet" in text
    assert roster.to_json(data) == []


def test_only_the_leader_of_a_stat_stands_out(data):
    table = roster.draw(data, DARK, 160, 0)
    pts = column(table, "PTS")
    leaders = [c.plain for c in pts if c.style == DARK.good]
    assert leaders == ["30.0"]  # Anthony Edwards, nobody else in green
    assert not any(c.style == DARK.good for name in ("GP", "MIN", "TO", "FG%", "FT%")
                   for c in column(table, name))


# --- preseason -----------------------------------------------------------------------------------

@pytest.mark.parametrize("view", range(len(KEYS)))
def test_preseason_falls_back_to_the_projection(preseason, view):
    table = roster.draw(preseason, DARK, 160, view)
    text = render(preseason, 160, view)
    first = text.splitlines()[0]
    key = KEYS[view]
    if key in ("proj", "last"):
        assert "no games" not in first and selected(table) == [SPLIT_SHORT[key]]
        return
    assert "no games yet, showing projections" in first
    assert selected(table) == ["Proj"]
    assert "Projected, per game" in text
    # the empty splits and today's games are left out instead of a column of dashes
    hs = headers(table)
    assert not {"Avg", "L7", "L15", "L30", "Today"} & set(hs)
    assert {"Proj", "Prev", "PTS", "REB", "AST"} <= set(hs)
    lamelo = next(sp.player for sp in preseason.league.me.roster if sp.player.name == "LaMelo Ball")
    assert column(table, "PTS")[0].plain == f"{lamelo.split('proj').pts:.1f}"


def test_preseason_fits_every_width(preseason):
    for w in WIDTHS:
        text = render(preseason, w)
        assert max(len(line) for line in text.splitlines()) <= w
        assert "no games yet" in text.splitlines()[0]


def test_a_missing_projected_stat_reads_as_zero(data):
    """ESPN leaves zeros out of the projections: a center with no threes has no 3PM."""
    gobert = next(sp.player for sp in data.league.me.roster if sp.player.name == "Rudy Gobert")
    gobert.stats["proj"].avg.pop(17, None)
    table = roster.draw(data, DARK, 160, KEYS.index("proj"))
    names = [c.plain for c in column(table, "Player")]
    assert column(table, "3PM")[names.index("Rudy Gobert MIN")].plain == "0.0"


# --- widths --------------------------------------------------------------------------------------

@pytest.mark.parametrize("pal", [DARK, LIGHT], ids=["dark", "light"])
@pytest.mark.parametrize("width", WIDTHS)
def test_width_fitting_keeps_the_names(data, width, pal):
    for view in range(len(KEYS)):
        text = render(data, width, view, pal)
        assert max(len(line) for line in text.splitlines()) <= width
        for name in last_names(data):
            assert name in text
        table = roster.draw(data, pal, width, view)
        assert len(selected(table, pal)) == 1


def test_narrow_screens_drop_columns_in_order(data):
    gone: dict[str, int] = {}
    for width in range(200, 39, -1):
        table = roster.draw(data, DARK, width, 0)
        hs = headers(table)
        for h in ("Rost%", "FG%", "FT%", "TO", "3PM", "GP", "MIN", "STL", "BLK", "L7", "L15",
                  "L30", "Prev"):
            if h not in hs:
                gone.setdefault(h, width)
        if "L15" in hs:  # the names stay whole while a secondary column is left
            assert "Anthony Edwards MIN" in [c.plain for c in column(table, "Player")]
    assert gone["Rost%"] > gone["FG%"] == gone["FT%"] == gone["TO"] == gone["3PM"]
    assert gone["3PM"] > gone["GP"] == gone["MIN"] == gone["STL"] == gone["BLK"]
    assert gone["BLK"] > gone["L7"] == gone["L15"] == gone["L30"] == gone["Prev"]


@pytest.mark.parametrize("view", range(len(KEYS)))
def test_46_columns_show_the_selected_split_and_the_projection(data, view):
    table = roster.draw(data, DARK, 46, view)
    hs = headers(table)
    assert hs[:2] == ["Slot", "Player"]
    assert {SPLIT_SHORT[KEYS[view]], "Proj"} <= set(hs)
    assert not {"Pos", "PTS", "GP", "Rost%"} & set(hs)


def test_very_narrow_screens_shorten_names_last(data):
    text = render(data, 36)
    assert max(len(line) for line in text.splitlines()) <= 36
    assert "A. Edwards" in text


# --- JSON ----------------------------------------------------------------------------------------

def test_json_has_every_split(data):
    rows = roster.to_json(data)
    assert [r["slot"] for r in rows][:5] == ["PG", "SG", "SF", "PF", "C"]
    lamelo = next(r for r in rows if r["name"] == "LaMelo Ball")
    assert set(lamelo["stats"]) == set(KEYS)
    assert lamelo["stats"]["l7"]["per_game"]["PTS"] == 24.0
    assert lamelo["plays_today"] is True and lamelo["opponent_today"] == "@HOU"
    assert {"last7", "last30", "started", "owned", "owned_change"} <= set(lamelo)


def test_cli_json(capsys):
    main(["--demo", "--json", "roster"])
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 13 and all({"slot", "plays_today", "opponent_today", "stats"} <= set(r)
                                   for r in rows)


def test_preseason_json(preseason):
    rows = roster.to_json(preseason)
    assert all(set(r["stats"]) <= {"proj", "last"} for r in rows)
    assert not any(r["plays_today"] or r["opponent_today"] for r in rows)


def test_legacy_wrapper_still_draws(data):
    out = Console(record=True, width=120, file=io.StringIO())
    out.print(views.roster(data.league, DARK, data.plays_today))
    text = out.export_text()
    assert "LaMelo Ball" in text and max(len(line) for line in text.splitlines()) <= 120


# --- the app -------------------------------------------------------------------------------------

def test_app_cycles_the_views_with_v():
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(190, 44)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("o")
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = app.query_one("#body", Static)
            assert app.current == "roster" and selected(body.content) == ["Avg"]
            for key in KEYS[1:] + KEYS[:1]:
                await pilot.press("v")
                await pilot.pause()
                assert selected(body.content) == [SPLIT_SHORT[key]]
            await pilot.press("v")  # Last 7
            await pilot.pause()
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert selected(body.content, LIGHT) == ["L7"]  # the view survives a theme change
            await pilot.press("s")  # the one-key menu still works from the roster
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.current == "standings"

    asyncio.run(run())

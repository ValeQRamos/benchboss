"""The Workload screen: positions, today's slot, bench games and the games-per-day footer.

Since 1.0.4 the starters and the bench share one block (no bench section): most games first
by default, today's slot order under v / --view lineup. IR and players who left this week
keep their own blocks."""

import asyncio
import io
import json

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.table import Table
from rich.text import Text

from benchboss.cli import main
from benchboss.config import Config
from benchboss.core.activity import by_lineup, games_per_day
from benchboss.errors import NetworkError
from benchboss.espn.constants import BENCH, IR
from benchboss.ui import views
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import workload
from benchboss.ui.theme import DARK, LIGHT


def text_of(renderable, width: int = 140) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def table_in(renderable) -> Table:
    return next(r for r in renderable.renderables if isinstance(r, Table))


def player_lines(out: str, names: list[str]) -> list[str]:
    """The rendered lines of the player rows, in screen order."""
    return [line for line in out.splitlines() if any(line.startswith(n) for n in names)]


def spot(session, name):
    return next(s for s in session.league().me.roster if s.player.name == name)


def with_lineups(session, change):
    """Make session.lineups answer today's roster for every day, edited by ``change``."""
    periods = session.matchup_periods()
    base = {s.player.id: s.slot_id for s in session.league().me.roster}
    days = {p: dict(base) for p in periods}
    change(days, periods)
    session.lineups = lambda ps: {p: days[p] for p in ps}


# --- grouping ----------------------------------------------------------------------------------

LINEUP = [k for k, _ in workload.VIEWS].index("lineup")


def test_lineup_view_lists_starters_then_bench_in_one_block_then_ir(session):
    spot(session, "Rudy Gobert").slot_id = IR
    data = workload.load(session)
    starters, bench, ir = by_lineup(data.acts)
    assert [a.slot_id for a in starters] == sorted(a.slot_id for a in starters)
    assert starters[0].player.name == "LaMelo Ball"  # PG comes first
    assert bench and {a.slot_id for a in bench} == {BENCH}
    assert [a.player.name for a in ir] == ["Rudy Gobert"]

    out = text_of(workload.draw(data, DARK, 140, LINEUP))
    names = [a.player.name for a in starters + bench + ir]
    rows = player_lines(out, names)
    assert [next(n for n in names if r.startswith(n)) for r in rows] == names
    # no bench section: the bench follows the starters with no blank line; IR keeps its own
    # block, the slot shown, and IR dimmed
    lines = out.splitlines()
    first_bench = lines.index(next(r for r in rows if r.startswith(bench[0].player.name)))
    assert lines[first_bench - 1].startswith(starters[-1].player.name)
    first_ir = lines.index(rows[-1])
    assert lines[first_ir - 1].strip() == ""
    assert " BE " in rows[len(starters)] and " IR " in rows[-1]
    table = table_in(workload.draw(data, DARK, 140, LINEUP))
    gobert = table.columns[0]._cells[-1]
    assert isinstance(gobert, Text) and gobert.style == DARK.dim


def test_default_view_is_most_games_with_ir_and_gone_blocks(session, monkeypatch):
    from benchboss.espn.models import RosterSpot

    spot(session, "Rudy Gobert").slot_id = IR
    gone = next(p for p in session.free_agents(40)
                if session.calendar.plays(p.pro_team_id, session.matchup_periods()[0]))
    real = type(session).roster_on
    first = session.matchup_periods()[0]

    def roster_on(self, period):  # he played Monday for you and was dropped after it
        roster = real(self, period)
        return roster + [RosterSpot(gone, 0)] if period == first else roster

    monkeypatch.setattr(type(session), "roster_on", roster_on)
    data = workload.load(session)
    assert workload.VIEWS[0][0] == "games"
    out = text_of(workload.draw(data, DARK, 140))
    active = [a for a in data.acts if not a.on_ir and not a.gone]
    names = [a.player.name for a in data.acts]
    rows = player_lines(out, names)
    shown = [next(n for n in names if r.startswith(n)) for r in rows]
    games = {a.player.name: a for a in data.acts}
    head = shown[:len(active)]
    keys = [(-games[n].games, -games[n].games_left, -games[n].player.proj) for n in head]
    assert keys == sorted(keys)  # starters and bench mixed, most games first
    assert {games[n].is_starting for n in head} == {True, False}
    assert shown[len(active):] == ["Rudy Gobert", gone.name]
    # three blocks: a blank line before IR and before the player who left, none inside
    lines = out.splitlines()
    at = [lines.index(r) for r in rows]
    blanks = [i for i in range(at[0], at[-1]) if not lines[i].strip()]
    assert blanks == [at[len(active)] - 1, at[-1] - 1]


def test_players_who_left_are_sorted_by_games_too(session):
    from benchboss.core.activity import Activity

    roster = [a.player for a in workload.load(session).acts]
    one = Activity(roster[0], 1, 0, ["vs LAC"], None, [BENCH], gone=True)
    three = Activity(roster[1], 3, 0, ["vs LAC"] * 3, None, [BENCH] * 3, gone=True)
    active, ir, gone = workload._groups([one, three])
    assert not active and not ir and gone == [three, one]
    # the lineup view keeps the order they came in
    assert workload._groups([one, three], by_lineup=True)[2] == [one, three]


@pytest.mark.parametrize("width", [60, 140])
def test_bench_marks_stay_in_the_default_view(session, width):
    data = workload.load(session)
    out = text_of(workload.draw(data, DARK, width), width)
    if width >= 140:
        harris = player_lines(out, ["Tobias Harris"])[0]
        assert "(UTA)" in harris  # Monday on your bench, still marked
    else:
        assert workload.BENCHED in out and workload.NO_GAME in out


def test_positions_and_slot_columns(session):
    out = text_of(workload.draw(workload.load(session), DARK, 140))
    header = next(line for line in out.splitlines() if line.startswith("Player"))
    assert "Pos" in header and "Slot" in header
    edwards = player_lines(out, ["Anthony Edwards"])[0]
    assert "SG/SF" in edwards and " SG " in edwards


# --- bench games --------------------------------------------------------------------------------

def test_a_game_on_your_bench_is_marked_and_not_counted(session):
    data0 = workload.load(session)
    ball = next(a for a in data0.acts if a.player.name == "LaMelo Ball")
    sunday = len(ball.schedule) - 1
    assert ball.schedule[sunday]  # he plays Sunday
    siakam = next(a for a in data0.acts if a.player.name == "Pascal Siakam")
    saturday = next(i for i, opp in enumerate(siakam.schedule) if opp and i >= 5)

    def change(days, periods):
        days[periods[sunday]][ball.player.id] = BENCH        # a starter sits on Sunday
        days[periods[saturday]][siakam.player.id] = 11       # a bench player starts (UT)

    s = type(session)()
    with_lineups(s, change)
    data = workload.load(s)
    ball = next(a for a in data.acts if a.player.name == "LaMelo Ball")
    siakam = next(a for a in data.acts if a.player.name == "Pascal Siakam")
    assert ball.benched(sunday) and ball.games_in_lineup == ball.games - 1
    assert siakam.games_in_lineup == 1 and not siakam.benched(saturday)

    table = table_in(workload.draw(data, DARK, 140))
    first_day = 3  # Player, Pos, Slot
    rows = [a.player.name for a in workload._ordered(data.acts)]
    sun = table.columns[first_day + sunday]._cells[rows.index("LaMelo Ball")]
    opp = ball.schedule[sunday].replace("vs ", "").replace("@ ", "@")
    assert sun.plain.strip() == f"({opp})" and sun.style == DARK.dim
    sat = table.columns[first_day + saturday]._cells[rows.index("Pascal Siakam")]
    assert "(" not in sat.plain
    out = text_of(workload.draw(data, DARK, 140))
    assert "on your bench" in out


def test_team_codes_line_up_in_a_column_with_bench_games(session):
    data = workload.load(session)
    starters, bench, _ = by_lineup(data.acts)
    day, starter, benched = next((i, s, b) for i in range(len(data.periods))
                                 for s in starters for b in bench
                                 if s.schedule[i] and b.schedule[i]
                                 and s.starting(i) and not b.starting(i))
    out = text_of(workload.draw(data, DARK, 140))
    s_row, b_row = (player_lines(out, [a.player.name])[0] for a in (starter, benched))
    code = starter.schedule[day][-3:]  # "vs MIL" or "@ MIL" -> MIL
    other = benched.schedule[day][-3:]
    # the bench game reads "(ATL)" and its three letters sit right under the starter's
    col = b_row.index(f"{other})")
    assert s_row[col:col + 3] == code and b_row[col - 1] in "(@"


# --- the footer ---------------------------------------------------------------------------------

def test_footer_shows_days_with_more_games_than_starting_spots(session):
    data = workload.load(session)
    per_day = games_per_day(data.acts, len(data.periods))
    spots = session.league().starter_slots
    assert max(per_day) > spots  # the demo week has overflow days
    table = table_in(workload.draw(data, DARK, 140))
    feet = [c.footer for c in table.columns[3:3 + len(data.periods)]]
    for n, foot in zip(per_day, feet, strict=True):
        if n > spots:
            assert foot.plain == f"{n}/{spots}" and foot.style == DARK.warn
        else:
            assert foot.plain == str(n) and foot.style != DARK.warn
    assert table.columns[0].footer.plain == "Games"
    assert f"{max(per_day)}/{spots} more games than starting spots" in text_of(
        workload.draw(data, DARK, 140))


def test_ir_players_do_not_count_toward_the_footer(session):
    before = games_per_day(workload.load(type(session)()).acts, 7)
    spot(session, "Rudy Gobert").slot_id = IR  # before the lineups are read: IR every day
    data = workload.load(session)
    gobert = next(a for a in data.acts if a.player.name == "Rudy Gobert")
    after = games_per_day(data.acts, 7)
    assert after == [b - bool(opp) for b, opp in zip(before, gobert.schedule, strict=True)]


# --- views --------------------------------------------------------------------------------------

def test_most_games_view_sorts_by_games_without_groups(session):
    data = workload.load(session)
    out = text_of(workload.draw(data, DARK, 140, view=0))
    names = [a.player.name for a in data.acts]
    rows = player_lines(out, names)
    shown = [next(n for n in names if r.startswith(n)) for r in rows]
    games = {a.player.name: a for a in data.acts}
    keys = [(-games[n].games, -games[n].games_left, -games[n].player.proj) for n in shown]
    assert keys == sorted(keys)
    body = out.split("─" * 10)[1]
    assert "\n\n" not in body.strip("\n")  # no blank lines between groups
    assert [k for k, _ in workload.VIEWS] == ["games", "lineup"]


def test_cli_view_flag(capsys):
    main(["--demo", "activity", "--view", "games"])
    assert "Workload" in capsys.readouterr().out
    # the old key keeps its meaning: today's slot order (starters, then the bench)
    main(["--demo", "activity", "--view", "lineup"])
    out = capsys.readouterr().out
    # surnames: a narrower console (Windows) shortens the first names
    assert out.index("Ball") < out.index("Pippen")
    with pytest.raises(SystemExit) as e:
        main(["--demo", "activity", "--view", "nope"])
    assert e.value.code == 2


def test_app_cycles_the_views():
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("a")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            assert app.current == "activity"
            assert str(app.query_one("#status").content).startswith("Most games · v for By lineup")
            await pilot.press("v")
            await pilot.pause()
            assert str(app.query_one("#status").content).startswith("By lineup · v for Most games")
            assert app.views["activity"] == 1

    asyncio.run(run())


# --- widths and themes --------------------------------------------------------------------------

@pytest.mark.parametrize("width", [46, 60, 80, 120, 160])
@pytest.mark.parametrize("pal", [DARK, LIGHT])
@pytest.mark.parametrize("view", [0, 1])
def test_fits_every_width_and_keeps_the_counts(session, width, pal, view):
    data = workload.load(session)
    out = text_of(workload.draw(data, pal, width, view), width)
    assert all(cell_len(line) <= width for line in out.splitlines())
    header = next(line for line in out.splitlines() if line.startswith("Player"))
    for col in ("G", "In", "Left"):
        assert f" {col}" in header
    days = out.splitlines()[2]
    for name in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"):
        assert name in days
    assert "…" not in out  # nothing cut at these widths


@pytest.mark.parametrize("width", [40, 46, 60])
def test_a_two_week_matchup_folds_the_days_into_a_strip(session, width):
    first = session.matchup_periods()[0]
    session.matchup_periods = lambda: list(range(first, first + 14))  # the All-Star matchup
    data = workload.load(session)
    out = text_of(workload.draw(data, DARK, width), width)
    assert all(cell_len(line) <= width for line in out.splitlines())
    assert "…" not in out
    header = next(line for line in out.splitlines() if line.startswith("Player"))
    assert "MTWTFSSMTWTFSS" in header and header.split()[-3:] == ["G", "In", "Left"]
    ball = next(a for a in data.acts if a.player.name == "LaMelo Ball")
    row = player_lines(out, ["L. Ball"])[0]
    assert row.split()[-3:] == [str(ball.games), str(ball.games_in_lineup), str(ball.games_left)]


def test_an_empty_roster_says_so(session):
    data = workload.load(session)
    data.acts = []
    out = text_of(workload.draw(data, DARK, 80), 80)
    assert "No players on your roster yet." in out and "Games" not in out


def test_the_dots_legend_reads_as_a_count(session):
    out = text_of(workload.draw(workload.load(session), DARK, 46), 46)
    assert "13 games, more than your 10 spots" in out


def test_narrow_widths_drop_pos_then_slot_then_long_names(session):
    data = workload.load(session)
    wide = text_of(workload.draw(data, DARK, 140), 140)
    mid = text_of(workload.draw(data, DARK, 80), 80)
    narrow = text_of(workload.draw(data, DARK, 46), 46)
    assert "Pos" in wide and "Slot" in wide and "Anthony Edwards" in wide
    assert "Pos" not in mid and "@HOU" in mid
    assert "A. Edwards" in narrow and "Anthony" not in narrow
    assert "●" in narrow and "○" in narrow  # no room for opponents: dots


# --- JSON ---------------------------------------------------------------------------------------

def test_json_shape(session):
    data = workload.load(session)
    rows = workload.to_json(data)
    assert len(rows) == len(session.league().me.roster)
    first = next(r for r in rows if r["player"] == "LaMelo Ball")
    assert set(first) == {"player", "team", "positions", "on_roster", "slot", "games",
                          "games_in_lineup", "games_left", "schedule", "days"}
    assert first["slot"] == "PG" and first["positions"] and first["on_roster"] is True
    assert len(first["days"]) == len(first["schedule"]) == len(data.periods) == 7
    day = first["days"][0]
    assert set(day) == {"date", "opponent", "slot", "starting"}
    assert day["date"] == "2026-11-02" and day["slot"] == "PG" and day["starting"] is True
    no_game = next(d for d in first["days"] if not d["opponent"])
    assert no_game["opponent"] == ""
    bench = next(r for r in rows if r["slot"] == "BE")
    # on the bench from today on; Monday (already played) he started, as the demo lineup had it
    assert bench["games_in_lineup"] < bench["games"] and bench["days"][-1]["starting"] is False
    json.dumps(rows)


def test_cli_json(capsys):
    main(["--demo", "--json", "activity"])
    rows = json.loads(capsys.readouterr().out)
    assert rows and all(isinstance(r["schedule"], list) for r in rows)


# --- when the lineups cannot be read ------------------------------------------------------------

def test_a_lineups_failure_falls_back_to_plain_cells(session):
    def boom(periods):
        raise NetworkError("could not reach ESPN (timed out)")

    session.lineups = boom
    data = workload.load(session)
    assert not data.lineups_known and data.lineup_error
    assert all(a.lineup is None and a.games_in_lineup is None for a in data.acts)
    out = text_of(workload.draw(data, DARK, 140))
    assert "(" not in "".join(player_lines(out, [a.player.name for a in data.acts]))
    table = table_in(workload.draw(data, DARK, 140))
    in_col = next(c for c in table.columns if c.header == "In")
    assert {c.plain for c in in_col._cells} == {"-"}
    assert "Bench games are not marked" in out and "Could not reach ESPN" in out
    narrow = text_of(workload.draw(data, DARK, 46), 46)
    assert "Could not reach ESPN (timed out)." in [line.strip() for line in narrow.splitlines()]
    rows = workload.to_json(data)
    assert all(r["games_in_lineup"] is None for r in rows)
    assert all(d["starting"] is None and d["slot"] is None for r in rows for d in r["days"])


def test_views_activity_wrapper_still_works(session):
    acts = session.activity()
    out = text_of(views.activity(acts, session.calendar, session.matchup_periods(),
                                 session.today_period, DARK))
    assert "Workload" in out and "Anthony Edwards" in out and "(" not in out.split("─")[1]

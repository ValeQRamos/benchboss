"""The player finder: the interactive widget (key p), its CLI table and its JSON."""

import asyncio
import io
import json

import pytest
from rich.console import Console
from textual.widgets import DataTable, Input, Static

from benchboss.cli import main
from benchboss.config import Config
from benchboss.demo import demo_session
from benchboss.errors import BenchbossError
from benchboss.espn.constants import SPLITS
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import finder, view_index
from benchboss.ui.theme import DARK, LIGHT

WATCHED = {"Egor Demin", "Myles Turner", "Dereck Lively II", "Grayson Allen"}


def text_of(renderable, width: int = 160) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


async def settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def drive(scenario, size=(150, 48), theme="dark", app=None):
    app = app or Benchboss(Config(theme=theme), demo=True)

    async def run():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await pilot.press("p")
            await settle(pilot)
            await scenario(pilot, app, app.query_one(finder.FinderView))
    asyncio.run(run())
    return app


def rows(view) -> list[finder.Player]:
    t = view.query_one(DataTable)
    by_id = {p.id: p for p in view.players}
    return [by_id[int(r.key.value)] for r in t.ordered_rows]


def header_of(out: str) -> str:
    """The table's header line (not the title line, which also says Player)."""
    return next(line for line in out.splitlines() if " Player " in f" {line} " and "finder" not in line)


def plain(widget) -> str:
    content = widget.content if isinstance(widget, Static) else widget
    return str(content) if not hasattr(content, "plain") else content.plain


# --- the app ----------------------------------------------------------------------------------------

def test_p_mounts_the_finder_with_the_table_focused():
    async def scenario(pilot, app, view):
        assert app.current == "players"
        t = view.query_one(DataTable)
        assert app.focused is t
        assert t.row_count == len(view.players) > 20
        assert view.source == "fa" and view.split == "proj" and view.sort_key == "proj"
        assert "Free agents" in plain(view.query_one("#finder-title"))
        assert all(p.status in ("FREEAGENT", "WAIVERS") for p in rows(view))
        projs = [p.fpts("proj") for p in rows(view)]
        have = [v for v in projs if v is not None]
        # default sort: the split's FPTS, best first, players without a projection last
        assert have == sorted(have, reverse=True) and projs[:len(have)] == have
        keys = [c.key.value for c in t.ordered_columns]
        assert keys[:6] == ["star", "name", "pos", "owner", "own", "start"]
        assert {"season", "l7", "l15", "l30", "proj", "last", "gp", "fgp", "ftp"} <= set(keys)

    drive(scenario)


def test_switching_pools_with_2_3_4_and_1():
    async def scenario(pilot, app, view):
        await pilot.press("2")
        await settle(pilot)
        assert view.source == "rostered" and rows(view)
        assert all(p.on_team_id for p in rows(view))
        assert "On a team" in plain(view.query_one("#finder-title"))
        await pilot.press("3")
        await settle(pilot)
        assert view.source == "watch"
        assert {p.name for p in rows(view)} == WATCHED
        await pilot.press("4")
        await settle(pilot)
        both = {p.status for p in rows(view)}
        assert "ONTEAM" in both and "FREEAGENT" in both
        await pilot.press("1")
        await settle(pilot)
        assert view.source == "fa" and all(not p.on_team_id for p in rows(view))

    drive(scenario)


def test_owner_column_names_the_team_and_marks_mine():
    async def scenario(pilot, app, view):
        await pilot.press("2")
        await settle(pilot)
        t = view.query_one(DataTable)
        lg = app.session.league()
        mine = next(p for p in rows(view) if p.on_team_id == lg.my_team_id)
        other = next(p for p in rows(view) if p.on_team_id != lg.my_team_id)
        assert t.get_cell(str(mine.id), "owner").plain == lg.me.abbrev.strip()
        assert DARK.accent in str(t.get_cell(str(mine.id), "owner").style)
        assert t.get_cell(str(other.id), "owner").plain == lg.teams[other.on_team_id].abbrev.strip()

    drive(scenario)


def test_space_toggles_the_watch_list_with_a_toast():
    async def scenario(pilot, app, view):
        s = app.session
        t = view.query_one(DataTable)
        target = next(p for p in rows(view) if p.id not in s.watch_list())
        t.move_cursor(row=t.get_row_index(str(target.id)))
        await pilot.pause()
        await pilot.press("space")
        assert t.get_cell(str(target.id), "star").plain == "★"  # at once, before ESPN answers
        await settle(pilot)
        assert target.id in s.watch_list()
        assert any(f"Added {target.name} to your watch list" in n.message
                   for n in app._notifications)
        await pilot.press("asterisk")
        await settle(pilot)
        assert target.id not in s.watch_list()
        assert t.get_cell(str(target.id), "star").plain == ""
        assert any(f"Removed {target.name} from your watch list" in n.message
                   for n in app._notifications)

    drive(scenario)


def test_watch_list_star_rolls_back_when_espn_says_no():
    app = Benchboss(Config(), demo=True)
    calls = []

    def refuse(player_id, watched):
        calls.append((player_id, watched))
        raise BenchbossError("ESPN 500: try again later")

    async def scenario(pilot, app, view):
        app.session.set_watched = refuse
        t = view.query_one(DataTable)
        target = rows(view)[0]
        before = target.id in view.watched
        await pilot.press("space")
        await settle(pilot)
        assert calls == [(target.id, not before)]
        assert (target.id in view.watched) == before
        assert t.get_cell(str(target.id), "star").plain == ("★" if before else "")
        errors = [n for n in app._notifications if n.severity == "error"]
        assert errors and "ESPN 500" in errors[-1].message

    drive(scenario, app=app)


def test_removing_from_the_watch_pool_keeps_the_row_until_reload():
    async def scenario(pilot, app, view):
        await pilot.press("3")
        await settle(pilot)
        first = rows(view)[0]
        await pilot.press("space")
        await settle(pilot)
        assert first.id not in app.session.watch_list()
        assert first in rows(view)  # space again would undo it
        await pilot.press("1")
        await settle(pilot)
        await pilot.press("3")
        await settle(pilot)
        assert len(rows(view)) == 3

    drive(scenario)


def test_sorting_with_keys_and_header_clicks_keeps_the_cursor():
    async def scenario(pilot, app, view):
        t = view.query_one(DataTable)
        t.move_cursor(row=5)
        await pilot.pause()
        keep = view._current_id()
        await pilot.press("greater_than_sign")  # proj -> last
        await pilot.pause()
        assert view.sort_key == "last" and view.sort_desc
        values = [p.fpts("last") for p in rows(view)]
        have = [v for v in values if v is not None]
        assert have == sorted(have, reverse=True) and values[:len(have)] == have
        assert view._current_id() == keep
        await pilot.press("less_than_sign", "less_than_sign")  # back to proj, then l30
        await pilot.pause()
        assert view.sort_key == "l30"
        # a click on a header sorts by it; a second click flips the direction
        t.post_message(DataTable.HeaderSelected(t, t.ordered_columns[4].key, 4,
                                                t.ordered_columns[4].label))
        await pilot.pause()
        assert view.sort_key == "own" and view.sort_desc
        owned = [p.owned for p in rows(view)]
        assert owned == sorted(owned, reverse=True)
        t.post_message(DataTable.HeaderSelected(t, t.ordered_columns[4].key, 4,
                                                t.ordered_columns[4].label))
        await pilot.pause()
        assert view.sort_key == "own" and not view.sort_desc
        assert [p.owned for p in rows(view)] == sorted(owned)
        assert "Rost% ▲" in plain(view.query_one("#finder-title"))
        assert view._current_id() == keep

    drive(scenario)


def test_names_sort_a_to_z_first():
    session = demo_session()
    data = finder.load(session, n=30)
    names = [p.name.lower() for p in finder.ordered(data.players, "name", finder.default_desc("name"),
                                                    "proj", data)]
    assert names == sorted(names)


def test_v_cycles_the_split_and_the_default_sort_follows():
    async def scenario(pilot, app, view):
        await pilot.press("v")
        await pilot.pause()
        assert view.split == "last" and view.sort_key == "last"
        assert app.views["players"] == list(SPLITS).index("last")
        await pilot.press("v")
        await pilot.pause()
        assert view.split == "season" and view.sort_key == "season"
        t = view.query_one(DataTable)
        p = rows(view)[0]
        line = p.split("season")
        assert t.get_cell(str(p.id), "pts").plain == f"{line.pts:.1f}"  # the box score follows
        await pilot.press("greater_than_sign")  # an explicit sort stays when the split changes
        await pilot.press("v")
        await pilot.pause()
        assert view.split == "l7" and view.sort_key == "l7"

    drive(scenario)


def test_position_filter_with_brackets():
    async def scenario(pilot, app, view):
        await pilot.press("right_square_bracket")
        await settle(pilot)
        assert view.position == "PG"
        assert rows(view) and all("PG" in p.positions.split("/") for p in rows(view))
        await pilot.press("right_square_bracket", "right_square_bracket", "right_square_bracket",
                          "right_square_bracket")
        await settle(pilot)
        assert view.position == "C"
        assert all("C" in p.positions.split("/") for p in rows(view))
        await pilot.press("left_square_bracket")
        await settle(pilot)
        assert view.position == "PF"
        assert "PF" in plain(view.query_one("#finder-title"))

    drive(scenario)


def test_search_box_types_freely_and_finds_players():
    async def scenario(pilot, app, view):
        await pilot.press("slash")
        await pilot.pause()
        box = view.query_one("#finder-search", Input)
        assert app.focused is box
        await pilot.press(*"turner")  # letters that are menu keys elsewhere go into the box
        assert app.current == "players" and box.value == "turner"
        await pilot.press("enter")
        await settle(pilot)
        assert app.focused is view.query_one(DataTable)
        assert [p.name for p in rows(view)] == ["Myles Turner"]
        await pilot.press("4")
        await settle(pilot)
        assert {p.name for p in rows(view)} >= {"Myles Turner"}
        await pilot.press("escape")  # escape with the table focused clears the search
        await settle(pilot)
        assert view.query_text is None and len(rows(view)) > 100

    drive(scenario)


def test_search_with_no_hits_says_so_and_escape_clears_it():
    async def scenario(pilot, app, view):
        await pilot.press("slash", *"zzqx", "enter")
        await settle(pilot)
        msg = view.query_one("#finder-message")
        assert msg.has_class("visible")
        assert 'No players match "zzqx" in Free agents' in plain(msg)
        await pilot.press("slash", *"abc", "escape")
        await settle(pilot)
        assert view.query_one("#finder-search", Input).value == ""
        assert view.query_text is None and rows(view)
        assert not msg.has_class("visible")

    drive(scenario)


def test_enter_opens_the_detail_card_with_news_and_escape_closes_it():
    async def scenario(pilot, app, view):
        t = view.query_one(DataTable)
        demin = next(p for p in rows(view) if p.name == "Egor Demin")
        t.move_cursor(row=t.get_row_index(str(demin.id)))
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)
        box = view.query_one("#finder-detail")
        assert box.has_class("open") and view.detail_id == demin.id
        card = text_of(view.query_one("#finder-card").content)
        for label in ("Egor Demin", "Season", "Last 7", "Last 15", "Last 30", "Projected",
                      "Last season", "Rostered", "Started", "FG%", "FT%"):
            assert label in card
        assert "Demin is seeing more minutes" in card  # the demo spin, loaded in a worker
        assert "Worth a speculative add" in card
        await pilot.press("down")  # the card follows the cursor
        await settle(pilot)
        await pilot.pause(0.5)
        nxt = rows(view)[t.cursor_row]
        assert view.detail_id == nxt.id
        assert nxt.name in text_of(view.query_one("#finder-card").content)
        await pilot.press("escape")
        await pilot.pause()
        assert not box.has_class("open") and view.detail_id is None

    drive(scenario)


def test_menu_keys_still_navigate_from_the_finder():
    async def scenario(pilot, app, view):
        await pilot.press("s")
        await settle(pilot)
        assert app.current == "standings"
        await pilot.press("p")
        await settle(pilot)
        await pilot.press("d")
        await settle(pilot)
        assert app.current == "dash"

    drive(scenario)


def test_the_finder_comes_back_as_you_left_it():
    async def scenario(pilot, app, view):
        await pilot.press("3", "v")
        await settle(pilot)
        await pilot.press("o")
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        again = app.query_one(finder.FinderView)
        assert again is not view
        assert again.source == "watch" and again.split == "last"
        assert {p.name for p in rows(again)} == WATCHED

    drive(scenario)


def test_theme_toggle_redraws_the_cells_in_the_new_palette():
    async def scenario(pilot, app, view):
        t = view.query_one(DataTable)
        p = next(x for x in rows(view) if x.id in view.watched)
        assert DARK.accent in str(t.get_cell(str(p.id), "star").style)
        await pilot.press("ctrl+t")
        await settle(pilot)
        assert LIGHT.accent in str(t.get_cell(str(p.id), "star").style)

    drive(scenario)


def test_empty_watch_list_in_the_app_says_how_to_add_one():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot, app, view):
        me = app.session.league().me
        me.watch_list = ()
        await pilot.press("3")
        await settle(pilot)
        msg = plain(view.query_one("#finder-message"))
        assert "Your watch list is empty" in msg and "space" in msg

    drive(scenario, app=app)


def test_narrow_window_scrolls_the_selected_split_into_view():
    async def scenario(pilot, app, view):
        await pilot.pause(0.3)
        t = view.query_one(DataTable)
        keys = [c.key.value for c in t.ordered_columns]
        widths = [c.get_render_width(t) for c in t.ordered_columns]
        i = keys.index("proj")
        right = sum(widths[:i + 1])
        assert right <= t.scroll_x + t.scrollable_content_region.width

    drive(scenario, size=(90, 40))


# --- the CLI table ------------------------------------------------------------------------------------

@pytest.fixture
def fa_data():
    return finder.load(demo_session(), n=25)


@pytest.mark.parametrize("width", [46, 80, 120, 160])
@pytest.mark.parametrize("pal", [DARK, LIGHT])
def test_draw_fits_the_width(fa_data, width, pal):
    out = text_of(finder.draw(fa_data, pal, width, view_index(finder, "proj")), width)
    lines = out.splitlines()
    assert lines[0].startswith("Player finder")
    assert max(len(line) for line in lines) <= width
    assert "Proj" in out
    if width >= 80:
        assert "…" not in out  # names are never cut while there are columns to drop
        assert "Jimmy Butler III GSW OUT" in out


def test_draw_drops_the_box_score_first_and_keeps_everything_at_160(fa_data):
    wide = text_of(finder.draw(fa_data, DARK, 160, view_index(finder, "proj")), 160)
    header = header_of(wide)
    for col in ("Rost%", "Start%", "Avg", "L7", "L15", "L30", "Proj", "Prev", "GP", "MIN", "PTS",
                "REB", "AST", "STL", "BLK", "3PM", "TO", "FG%", "FT%"):
        assert col in header
    mid = text_of(finder.draw(fa_data, DARK, 80, view_index(finder, "proj")), 80)
    header = header_of(mid)
    assert "FT%" not in header and "Start%" not in header
    assert "Avg" in header and "Proj" in header and "Rost%" in header
    narrow = text_of(finder.draw(fa_data, DARK, 46, view_index(finder, "proj")), 46)
    header = header_of(narrow)
    assert "Proj" in header and "Rost%" in header


def test_draw_shows_the_selected_split_box_score(fa_data):
    p = next(x for x in finder.ordered(fa_data.players, "proj", True, "l7", fa_data)
             if x.split("l7") and x.split("l7").pts)
    out = text_of(finder.draw(fa_data, DARK, 170, view_index(finder, "l7")), 170)
    assert "Box score Last 7, per game" in out
    line = next(x for x in out.splitlines() if p.name in x)
    assert f"{p.split('l7').pts:.1f}" in line


def test_draw_in_the_preseason_hides_empty_splits(fa_data):
    for p in fa_data.players:
        p.stats = {k: v for k, v in p.stats.items() if k in ("proj", "last")}
    out = text_of(finder.draw(fa_data, DARK, 120, view_index(finder, "proj")), 120)
    header = header_of(out)
    assert "Proj" in header and "Prev" in header
    for col in ("Avg", "L7", "L15", "L30"):
        assert f" {col} " not in header


def test_empty_watch_list_and_no_hits_messages():
    s = demo_session()
    s.league().me.watch_list = ()
    out = text_of(finder.draw(finder.load(s, source="watch"), DARK, 100))
    assert "Your watch list is empty" in out and 'benchboss watch add "NAME"' in out
    out = text_of(finder.draw(finder.load(s, query="zzqx"), DARK, 100))
    assert 'No players match "zzqx" in Free agents' in out


def test_players_from_watch_lists_the_four_demo_players(capsys):
    main(["--demo", "players", "--from", "watch"])
    out = capsys.readouterr().out
    assert "Watch list" in out
    for name in WATCHED:
        assert name in out
    main(["--demo", "watch"])
    out = capsys.readouterr().out
    assert all(name in out for name in WATCHED)


def test_players_json_keys(capsys):
    main(["--demo", "--json", "players", "--from", "all", "-n", "8"])
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 8
    for row in data:
        assert {"id", "name", "team", "positions", "owned", "owned_change", "started", "stats",
                "watched", "owner", "on_team_id", "last7", "last30"} <= set(row)
        assert isinstance(row["watched"], bool)
        assert row["owner"] is None or isinstance(row["owner"], str)
        assert set(row["stats"]) <= set(SPLITS)
    assert any(row["owner"] for row in data)
    main(["--demo", "--json", "watch"])
    watch = json.loads(capsys.readouterr().out)
    assert {row["name"] for row in watch} == WATCHED and all(row["watched"] for row in watch)
    assert all(row["owner"] is None for row in watch)


def test_players_view_and_sort_follow_each_other(capsys):
    main(["--demo", "players", "--sort", "l7", "-n", "5"])
    assert "sorted by L7" in capsys.readouterr().out
    main(["--demo", "--json", "players", "--view", "season", "-n", "6"])
    data = json.loads(capsys.readouterr().out)
    avgs = [row["stats"]["season"]["fpts"] for row in data if "season" in row["stats"]]
    assert avgs == sorted(avgs, reverse=True)
    with pytest.raises(SystemExit):
        main(["--demo", "players", "--view", "nope"])


def test_preseason_v_skips_splits_without_numbers():
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(150, 48)) as pilot:
            await settle(pilot)
            real = app.session.player_pool

            def preseason(*a, **kw):
                players = real(*a, **kw)
                for p in players:
                    p.stats = {k: v for k, v in p.stats.items() if k in ("proj", "last")}
                return players

            app.session.player_pool = preseason
            await pilot.press("p")
            await settle(pilot)
            view = app.query_one(finder.FinderView)
            await pilot.press("4")  # refetch through the preseason pool
            await settle(pilot)
            keys = [c.key.value for c in view.query_one(DataTable).ordered_columns]
            assert "proj" in keys and "last" in keys
            assert not {"season", "l7", "l15", "l30"} & set(keys)
            await pilot.press("v")
            await pilot.pause()
            assert view.split == "last"
            await pilot.press("v")
            await pilot.pause()
            assert view.split == "proj"
            view.pick("split", "l7")  # a click on an empty split still shows it, and says why
            await pilot.pause()
            assert view.split == "l7"
            assert "No Last 7 stats yet" in plain(view.query_one("#finder-message"))
    asyncio.run(run())


# --- review fixes ---------------------------------------------------------------------------------

def test_rost_cells_line_up_with_or_without_a_change():
    data = finder.load(demo_session(), source="rostered", n=40)
    cells = [finder.rost_cell(p, DARK) for p in data.players]
    assert {c.cell_len for c in cells} == {8}
    assert any(abs(p.owned_change) < 0.05 for p in data.players)  # some have no arrow at all
    out = text_of(finder.draw(data, DARK, 120, view_index(finder, "proj")), 120)
    col = header_of(out).index("Rost%")
    shown = [line[col:col + 3] for line in out.splitlines()
             if any(p.name in line for p in data.players)]
    assert len(shown) == len(data.players)
    assert all(s[-1].isdigit() for s in shown)  # every number ends in the same column
    assert {s.strip() for s in shown} >= {"100", "97"}


def test_a_count_missing_from_a_box_score_is_zero():
    session = demo_session()
    center = next(p for p in session.player_pool("fa", "C", 40, "proj", None)
                  if p.split("proj") and p.split("proj").tpm is None)
    assert finder.box_value(center.split("proj"), "tpm") == 0.0
    assert finder.box_cell(center, "tpm", "proj", DARK).plain == "0.0"
    assert finder.box_value(None, "tpm") is None


def test_cli_names_stay_full_when_a_later_drop_makes_room():
    data = finder.load(demo_session(), source="all", n=8)
    out = text_of(finder.draw(data, DARK, 46, view_index(finder, "proj")), 46)
    assert "Shai Gilgeous-Alexander OKC" in out and "S. Gilgeous" not in out
    assert max(len(line) for line in out.splitlines()) <= 46


def test_watch_pool_in_the_cli_has_no_star_column():
    out = text_of(finder.draw(finder.load(demo_session(), source="watch"), DARK, 100), 100)
    assert "★" not in out


def test_narrow_window_keeps_every_tab_and_split_and_scrolls_by_whole_columns():
    async def scenario(pilot, app, view):
        await pilot.pause(0.3)
        tabs = view.query_one("#finder-tabs")
        search = view.query_one("#finder-search", Input)
        assert [r[4] for r in tabs.regions] == list(finder.TABS)
        assert tabs.regions[-1][2] <= search.region.x - tabs.region.x  # 4 All is not covered
        filters = view.query_one("#finder-filters")
        assert filters.size.height == 2  # Pos on one line, Stats on the next
        assert {r[0] for r in filters.regions if r[3] == "split"} == {1}
        t = view.query_one(DataTable)
        widths = [c.get_render_width(t) for c in t.ordered_columns]
        fixed = sum(widths[:t.fixed_columns])
        starts = {sum(widths[:j]) - fixed for j in range(t.fixed_columns, len(widths))}
        assert t.scroll_x > 0 and t.scroll_x in starts
        last = next(r for r in filters.regions if r[3] == "split" and r[4] == "last")
        await pilot.click("#finder-filters", offset=(last[1] + 1, 1))
        await pilot.pause()
        assert view.split == "last"

    drive(scenario, size=(60, 34))


def test_an_empty_pool_hides_the_table_header():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot, app, view):
        app.session.league().me.watch_list = ()
        await pilot.press("3")
        await settle(pilot)
        assert not view.query_one(DataTable).show_header
        await pilot.press("1")
        await settle(pilot)
        assert view.query_one(DataTable).show_header

    drive(scenario, app=app)


def test_quick_presses_on_the_star_end_where_the_star_ends():
    async def scenario(pilot, app, view):
        pid = view._current_id()
        before = pid in view.watched
        await pilot.press("space", "space", "space")
        await settle(pilot)
        assert (pid in view.watched) != before
        assert (pid in app.session.watch_list()) == (pid in view.watched)
        await pilot.press("enter")
        await pilot.pause()
        assert "close card" in plain(view.query_one("#finder-hint"))

    drive(scenario)

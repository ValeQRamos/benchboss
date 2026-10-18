"""1.0.4: the app on a phone over SSH (the compact layout) and the boards at narrow widths.

The window sizes are the ones measured on phones: 40x32 and 46x30 portrait, 60x24 and
80x24 landscape, 100x12 and 110x14 landscape with the keyboard up; 120x40 and 150x45 are
laptops, whose look tests/test_wide_guards.py pins.
"""

from __future__ import annotations

import asyncio
import io
import re

import pytest
from rich.console import Console
from textual.widgets import DataTable, Footer, Input, OptionList

from benchboss import __version__
from benchboss.cli import Ctx, build_parser
from benchboss.config import Config
from benchboss.demo import demo_session
from benchboss.service import periods_for
from benchboss.ui import common, dashboard, keybar, layout, logo, views
from benchboss.ui.app import MENU, Benchboss
from benchboss.ui.keybar import KeyBar
from benchboss.ui.layout import KeyItem
from benchboss.ui.screens import finder, plan, playoffs, roster, trash
from benchboss.ui.theme import DARK, LIGHT

SIZES = ((40, 32), (46, 30), (60, 24), (80, 24), (120, 40), (150, 45))
STATIC = {"today", "week", "activity", "trash", "news", "trades", "inbox", "standings", "roster"}
TITLE_OWNED_ELSEWHERE = {"news"}  # the news package redraws that screen and its title


def text_of(renderable, width: int) -> str:
    console = Console(width=width, file=io.StringIO(), color_system=None, record=True)
    console.print(renderable)
    return console.export_text()


async def settle(pilot, wait: float = 0.0) -> None:
    for _ in range(2):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
    if wait:
        await pilot.pause(wait)
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


async def until(pilot, ok, timeout: float = 5.0) -> bool:
    for _ in range(int(timeout / 0.05)):
        if ok():
            return True
        await pilot.pause(0.05)
    return ok()


def drive(scenario, size=(46, 40), cfg: Config | None = None, app: Benchboss | None = None):
    app = app or Benchboss(cfg or Config(), demo=True)

    async def run():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await scenario(pilot, app)
    asyncio.run(run())
    assert app.return_code in (None, 0)
    return app


def bottom_row(app) -> str:
    return layout.screen_text(app).splitlines()[-1]


# --- every screen at every size --------------------------------------------------------------------

@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_every_screen_at_every_size(size):
    async def scenario(pilot, app):
        assert app.compact == (size[0] < 80 or size[1] < 30)
        for sid, _, key in [("dash", "", "d"), *MENU]:
            await pilot.press(key)
            await settle(pilot)
            assert app.current == sid
            assert "m menu" in bottom_row(app).lower(), (sid, bottom_row(app))
            if sid in STATIC:
                width = app._width()
                out = text_of(app.query_one("#body").content, width).splitlines()
                assert max(len(x.rstrip()) for x in out) <= width, sid
                if sid not in TITLE_OWNED_ELSEWHERE:
                    assert out[0].strip() and not out[1].strip(), (sid, out[:2])  # one-line title

    drive(scenario, size=size)


# --- the compact switch, the gutter, the key bar --------------------------------------------------

def test_compact_follows_the_window_and_the_setting(monkeypatch):
    async def phone(pilot, app):
        assert app.compact and app.screen.has_class("-compact") and app.screen.has_class("-short")
        assert app.query_one(KeyBar).display and not app.query_one(Footer).display
        assert app._width() == 46 - 3
        await pilot.resize_terminal(120, 29)   # short: still compact
        await settle(pilot)
        assert app.compact and app.short
        await pilot.resize_terminal(120, 32)   # a keyboard closing: no flip back and forth
        await settle(pilot)
        assert app.compact and not app.short
        await pilot.resize_terminal(120, 40)
        await settle(pilot)
        assert not app.compact and not app.screen.has_class("-compact")
        assert app.query_one(Footer).display and not app.query_one(KeyBar).display
        assert app._width() == 120 - 26 - 6  # the menu beside the screen again
        await pilot.resize_terminal(100, 40)
        await settle(pilot)
        assert not app.compact and app._width() == 100 - 6  # menu hidden below NARROW

    drive(phone, size=(46, 24))

    async def turned(pilot, app):
        # compact for the width only: the height hysteresis does not carry over to a wide
        # window of 31 to 33 rows, which opens full when started at that size
        assert app.compact
        await pilot.resize_terminal(100, 31)
        await settle(pilot)
        assert not app.compact
        await pilot.resize_terminal(100, 26)   # a keyboard opening
        await settle(pilot)
        assert app.compact
        await pilot.resize_terminal(100, 31)   # and closing: held by the height
        await settle(pilot)
        assert app.compact
        await pilot.resize_terminal(46, 31)
        await pilot.resize_terminal(100, 34)
        await settle(pilot)
        assert not app.compact

    drive(turned, size=(46, 40))
    drive(lambda pilot, app: _check(not app.compact), size=(100, 31))
    drive(lambda pilot, app: _check(app.compact), size=(120, 40), cfg=Config(layout="compact"))
    drive(lambda pilot, app: _check(not app.compact and app.query_one(Footer).display),
          size=(46, 40), cfg=Config(layout="full"))
    monkeypatch.setenv("BENCHBOSS_LAYOUT", "compact")
    drive(lambda pilot, app: _check(app.compact), size=(150, 45), app=Benchboss(demo=True))
    monkeypatch.setenv("BENCHBOSS_LAYOUT", "tiny")  # not a layout: auto
    drive(lambda pilot, app: _check(not app.compact), size=(150, 45), app=Benchboss(demo=True))


async def _check(ok: bool) -> None:
    assert ok


def test_the_layout_flag_goes_before_or_after_the_command():
    ap = build_parser()
    assert ap.parse_args(["--layout", "compact"]).layout == "compact"
    assert ap.parse_args(["app", "--layout", "full"]).layout == "full"
    assert ap.parse_args(["--demo", "app"]).layout is None
    with pytest.raises(SystemExit):
        ap.parse_args(["--layout", "tiny"])
    assert Ctx(ap.parse_args(["--demo", "--layout", "compact", "app"])).cfg.layout == "compact"


def test_the_key_bar_drops_keys_by_priority_and_never_cuts_one():
    items = [KeyItem("m", "menu", priority=0), KeyItem("/", "search", priority=10),
             KeyItem("space", "★ watch", priority=14), KeyItem("1-4", "pool", priority=20),
             KeyItem("q", "quit", priority=90)]
    for width in range(6, 60):
        out, regions = keybar.fit(items, width, DARK, "demo")
        assert out.cell_len <= width and out.plain.startswith("m menu")
        shown = [items[i] for _, _, i in regions]
        assert all(f"{k.key} {k.label}" in out.plain for k in shown)
        # a key is left out only when it did not fit next to the ones before it in priority
        assert [k.priority for k in shown] == sorted(k.priority for k in shown)
    out, _ = keybar.fit(items, 40, DARK, "demo")
    # 1-4 pool does not fit after the first three; q quit, shorter, still does
    assert out.plain == "m menu  / search  space ★ watch  q quit"
    out, _ = keybar.fit(items[:2], 40, DARK, "demo")
    assert out.plain.endswith("demo") and out.cell_len == 40


def test_a_tap_on_the_key_bar_runs_its_key():
    async def scenario(pilot, app):
        bar = app.query_one(KeyBar)
        assert "m menu" in bottom_row(app)
        start, end, _ = next(r for r in bar.regions if bar._entries[r[2]][0].key == "m")
        await pilot.click(KeyBar, offset=(start + 1 + bar.styles.padding.left, 0))
        await settle(pilot)
        menu = app.query_one("#menu", OptionList)
        assert menu.has_class("page") and app.focused is menu

    drive(scenario, size=(40, 32))


def test_the_top_bar_fits_a_phone():
    async def scenario(pilot, app):
        top = layout.screen_text(app).splitlines()[0]
        assert __version__ not in top and "Monstars" in top and "demo" in top
        assert len(top.rstrip()) <= 40
        await pilot.resize_terminal(120, 40)
        await settle(pilot)
        top = layout.screen_text(app).splitlines()[0]
        assert __version__ in top and "demo data" in top

    drive(scenario, size=(40, 32))


# --- the menu as a page ---------------------------------------------------------------------------------

def test_the_menu_is_a_page_on_a_phone():
    async def scenario(pilot, app):
        menu = app.query_one("#menu", OptionList)
        assert menu.has_class("hidden")
        width = app._width()
        await pilot.press("m")
        await settle(pilot)
        assert menu.has_class("page") and menu.region.width == 46
        assert not app.query_one("#content").display and app.focused is menu
        assert app._width() == width  # the screen behind it keeps its width
        assert "m close" in bottom_row(app)
        for close in ("escape", "backspace", "m"):
            await pilot.press(close)
            await settle(pilot)
            assert menu.has_class("hidden") and app.query_one("#content").display
            await pilot.press("m")
            await settle(pilot)
            assert menu.has_class("page")
        menu.highlighted = next(i for i, (sid, _, _) in enumerate(MENU) if sid == "standings")
        await pilot.press("enter")
        await settle(pilot)
        assert app.current == "standings" and menu.has_class("hidden")
        assert app.focused is app.query_one("#content")
        await pilot.press("m", "j", "j")  # j and k walk the menu too
        await settle(pilot)
        assert menu.highlighted == next(i for i, (sid, _, _) in enumerate(MENU)
                                        if sid == "standings") + 2
        await pilot.press("p")  # a menu letter works from the page
        await settle(pilot)
        assert app.current == "players" and menu.has_class("hidden")
        assert app.focused is app.query_one(finder.FinderView).query_one(DataTable)

    drive(scenario, size=(46, 40))


def test_the_menu_stays_beside_the_screen_on_a_laptop():
    async def scenario(pilot, app):
        menu = app.query_one("#menu", OptionList)
        await pilot.press("m")
        await settle(pilot)
        assert menu.has_class("hidden") and not menu.has_class("page")
        await pilot.press("m")
        await settle(pilot)
        assert not menu.has_class("hidden") and not menu.has_class("page")
        assert app.query_one("#content").display and menu.region.width == 26

    drive(scenario, size=(120, 40))


def test_a_wider_window_turns_the_menu_page_into_the_side_menu():
    async def scenario(pilot, app):
        await pilot.press("m")
        await settle(pilot)
        await pilot.resize_terminal(140, 44)
        await settle(pilot)
        menu = app.query_one("#menu", OptionList)
        assert not menu.has_class("page") and not menu.has_class("hidden")
        assert app.query_one("#content").display
        await pilot.resize_terminal(46, 40)
        await settle(pilot)
        assert menu.has_class("hidden") and app.compact

    drive(scenario, size=(46, 40))


# --- static screens: scrolling and the ball ---------------------------------------------------------

def test_static_screens_scroll_with_phone_keys():
    async def scenario(pilot, app):
        content = app.query_one("#content")
        assert app.focused is content and content.max_scroll_y > 0
        await pilot.press("j", "j")
        await settle(pilot)
        assert content.scroll_y == 2
        await pilot.press("k")
        await settle(pilot)
        assert content.scroll_y == 1
        await pilot.press("space")
        await settle(pilot)
        assert content.scroll_y > 10
        await pilot.press("b")
        await settle(pilot)
        assert content.scroll_y == 0

    drive(scenario, size=(46, 40))


@pytest.mark.parametrize("size, ball", [((90, 26), False), ((100, 12), False), ((100, 40), True),
                                        ((120, 34), True), ((120, 33), False)])
def test_the_ball_needs_a_tall_window(size, ball):
    top = logo.ball(DARK).plain.splitlines()[0].strip()

    async def scenario(pilot, app):
        assert (top in layout.screen_text(app)) is ball

    drive(scenario, size=size)


def test_the_ball_is_the_same_whole_drawing_at_every_width():
    session = demo_session()
    d = dashboard.collect(session)
    rows = [x.rstrip() for x in text_of(logo.ball(DARK), 20).splitlines() if x.strip()]
    for width in (72, 78, 88, 118, 150):
        out = text_of(dashboard.header(d, DARK, width), width).splitlines()
        assert [x[:logo.BALL_WIDTH].rstrip() for x in out[:len(rows)]] == rows
        assert rows[0] not in text_of(dashboard.header(d, DARK, width, logo_ok=False), width)


# --- the dashboard -----------------------------------------------------------------------------------

def test_the_dashboard_goes_two_columns_from_78():
    d = dashboard.collect(demo_session())
    assert any(isinstance(r, dashboard.Columns) for r in dashboard.render(d, DARK, 78).renderables)
    assert not any(isinstance(r, dashboard.Columns) for r in dashboard.render(d, DARK, 77).renderables)
    out = text_of(dashboard.render(d, DARK, 78), 78)
    assert max(len(x.rstrip()) for x in out.splitlines()) <= 78
    assert "╮ ╭" in out  # two cards side by side


@pytest.mark.parametrize("width", range(34, 61, 2))
def test_the_verdict_keeps_to_one_line(width):
    d = dashboard.collect(demo_session())
    out = text_of(dashboard.matchup_card(d, DARK), width)
    line = next(x for x in out.splitlines() if "Up " in x)
    assert "lose by 114" in line


def test_fit_picks_the_longest_wording_that_fits():
    from rich.text import Text

    fit = common.Fit(Text("projected to lose by 114"), Text("proj. lose by 114"))
    assert text_of(fit, 30).strip() == "projected to lose by 114"
    assert text_of(fit, 20).strip() == "proj. lose by 114"
    assert text_of(fit, 10).strip().startswith("proj.")


# --- the player finder ---------------------------------------------------------------------------------

def columns(t: DataTable) -> list[str]:
    return [c.key.value for c in t.ordered_columns]


def test_the_finder_opens_unscrolled_with_the_split_next_to_the_name():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        view = app.query_one(finder.FinderView)
        t = view.query_one(DataTable)
        assert columns(t)[:3] == ["star", "name", "proj"] and t.fixed_columns == 3
        assert t.scroll_x == 0
        assert "J. Butler III GSW OUT" in t.get_cell_at((0, 1)).plain  # short names
        await pilot.press("v")  # the next split takes its place next to the name
        await settle(pilot, 0.3)
        assert columns(t)[2] == view.split == "last" and t.scroll_x == 0
        await pilot.press("full_stop")  # sort by the next column: right after the split
        await settle(pilot, 0.6)
        assert view.sort_key != "last"

    drive(scenario, size=(46, 40))


def test_the_finder_keeps_the_laptop_columns_on_a_laptop():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        t = app.query_one(finder.FinderView).query_one(DataTable)
        assert columns(t)[:4] == ["star", "name", "pos", "owner"] and t.fixed_columns == 2
        assert "Jimmy Butler III GSW OUT" in t.get_cell_at((0, 1)).plain

    drive(scenario, size=(120, 40))


def test_turning_the_phone_keeps_the_splits_in_view():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        t = app.query_one(finder.FinderView).query_one(DataTable)
        for size in ((100, 26), (46, 40), (100, 26)):
            await pilot.resize_terminal(*size)
            await settle(pilot, 0.3)
            assert await until(pilot, lambda: t.scroll_x == 0)
            head = next(x for x in layout.screen_text(app).splitlines() if "Player" in x
                        and "finder" not in x)
            assert "Proj" in head
            if size[0] == 100:
                assert {"Avg", "L7", "Pos"} <= set(head.split())
                assert "PTS" not in head  # not the box score: the splits

    drive(scenario, size=(46, 40))


def test_the_finder_goes_back_to_the_laptop_columns_on_a_bigger_window():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        view = app.query_one(finder.FinderView)
        t = view.query_one(DataTable)
        await pilot.press("enter")
        await settle(pilot, 0.3)
        assert view.has_class("-card") and not t.display
        await pilot.resize_terminal(140, 44)
        await settle(pilot, 0.3)
        assert not app.compact and await until(pilot, lambda: t.fixed_columns == 2)
        assert columns(t)[:3] == ["star", "name", "pos"]
        assert not view.has_class("-card") and t.display and view.detail_id is not None
        assert "Jimmy Butler III GSW OUT" in t.get_cell_at((0, 1)).plain
        assert app.focused is t

    drive(scenario, size=(46, 40))


@pytest.mark.parametrize("size", [(40, 32), (44, 38)])
def test_the_finder_never_shows_a_cut_column(size):
    whole = {"★", "▼", "▲", *finder.HEADERS.values()}

    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        lines = layout.screen_text(app).splitlines()
        head = next(x for x in lines if "Player" in x and "finder" not in x)
        assert set(head.split()) <= whole, head
        t = app.query_one(finder.FinderView).query_one(DataTable)
        assert "proj" in columns(t)[:3]

    drive(scenario, size=size)


def test_every_filter_label_can_be_tapped_on_a_phone():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        view = app.query_one(finder.FinderView)
        bar = view.query_one("#finder-filters")
        lines = str(bar.content).splitlines()
        assert len(lines) == bar.size.height >= 3  # Stats goes on in a third line at 40
        for split in finder.SPLIT_KEYS:
            line, start, *_ = next(r for r in bar.regions if r[3] == "split" and r[4] == split)
            assert finder.SPLIT_PICK[split] in lines[line]
            await pilot.click("#finder-filters", offset=(start + 1, line))
            await settle(pilot, 0.3)
            assert view.split == split, split

    drive(scenario, size=(40, 32))


@pytest.mark.parametrize("size", [(100, 12), (110, 14)])
def test_the_finder_keeps_rows_with_the_keyboard_up(size):
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        view = app.query_one(finder.FinderView)
        t = view.query_one(DataTable)
        assert t.scrollable_content_region.height - 1 >= 3
        bar = view.query_one("#finder-filters")
        assert bar.size.height == 1 and {r[3] for r in bar.regions} == {"cycle_pos", "cycle_split"}
        await pilot.click("#finder-filters", offset=(bar.regions[0][1] + 1, 0))
        await settle(pilot, 0.3)
        assert view.position == "PG"
        await pilot.press("slash")
        await settle(pilot)
        assert view.query_one(Input).has_focus and t.scrollable_content_region.height - 1 >= 3
        assert "⏎ search" in bottom_row(app)

    drive(scenario, size=size)


def test_the_key_bar_offers_no_letter_keys_while_a_search_box_types():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        await pilot.press("slash")
        await settle(pilot)
        bar = app.query_one(KeyBar)
        search = app.query_one(finder.FinderView).query_one(Input)
        assert search.has_focus
        # v d r q would go into the box as letters (and a tap on v typed a "v")
        assert [item.key for item, _ in bar._entries] == ["m", "⏎"]
        assert "v " not in bottom_row(app) and "d dashboard" not in bottom_row(app)
        start = next(r[0] for r in bar.regions if bar._entries[r[2]][0].key == "m")
        await pilot.click(KeyBar, offset=(start + 1 + bar.styles.padding.left, 0))
        await settle(pilot)
        assert app.query_one("#menu").has_class("page") and search.value == ""
        await pilot.press("escape")
        await settle(pilot)
        assert "d dashboard" in bottom_row(app) or "v " in bottom_row(app)

    drive(scenario, size=(100, 12))


def test_the_card_covers_the_table_on_a_phone_and_scrolls():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        view = app.query_one(finder.FinderView)
        t, box = view.query_one(DataTable), view.query_one("#finder-detail")
        await pilot.press("enter")
        await settle(pilot, 0.3)
        assert not t.display and app.focused is box and "⏎ close" in bottom_row(app)
        assert box.max_scroll_y > 0
        await pilot.press("j", "j")
        await settle(pilot)
        assert box.scroll_y == 2
        await pilot.press("k")
        await settle(pilot)
        assert box.scroll_y == 1
        await pilot.press("enter")  # enter closes it too
        await settle(pilot)
        assert t.display and app.focused is t and view.detail_id is None

    drive(scenario, size=(46, 18))


def test_the_finder_answers_to_phone_keys():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot, 0.3)
        view = app.query_one(finder.FinderView)
        t = view.query_one(DataTable)
        await pilot.press("j", "j")
        assert t.cursor_row == 2
        await pilot.press("k")
        assert t.cursor_row == 1
        sort = view.sort_key
        await pilot.press("full_stop")
        await settle(pilot, 0.6)
        assert view.sort_key != sort
        await pilot.press("comma")
        await settle(pilot, 0.6)
        assert view.sort_key == sort
        await pilot.press("right_parenthesis")
        await settle(pilot, 0.3)
        assert view.position == "PG"
        await pilot.press("left_parenthesis")
        await settle(pilot, 0.3)
        assert view.position is None
        await pilot.press("slash", *"dem", "enter")
        await settle(pilot, 0.3)
        assert view.query_text == "dem" and app.focused is t
        await pilot.press("enter")
        await settle(pilot, 0.3)
        assert view.detail_id is not None
        await pilot.press("backspace")  # the card first...
        await settle(pilot)
        assert view.detail_id is None and view.query_text == "dem"
        await pilot.press("backspace")  # ...then the search
        await settle(pilot, 0.3)
        assert view.query_text is None

    drive(scenario, size=(46, 40))


def test_no_widget_takes_a_menu_key():
    from benchboss.ui.app import MenuList, ScrollPane

    taken = {key for _, _, key in MENU} | set("gvmrq") | {"u"}  # u: Auto-swap
    for widget in (finder.FinderView, finder.FinderTable, finder._Detail, playoffs.PlayoffBuilder,
                   MenuList, ScrollPane):
        keys = {k for b in widget.BINDINGS for k in b.key.split(",")}
        # the finder's v is the same key with the same meaning: the next view (its split)
        assert not keys & (taken - ({"v"} if widget is finder.FinderView else set())), widget


def test_the_menu_keys_work_from_the_finder_and_the_builder_on_a_phone():
    async def scenario(pilot, app):
        for start in ("p", "y"):
            for key, sid in (("s", "standings"), ("o", "roster"), ("d", "dash")):
                await pilot.press(start)
                await settle(pilot, 0.2)
                await pilot.press(key)
                await settle(pilot)
                assert app.current == sid

    drive(scenario, size=(46, 40))


# --- the playoff builder ---------------------------------------------------------------------------------

def test_the_builder_changes_week_with_comma_and_full_stop():
    async def scenario(pilot, app):
        await pilot.press("y")
        await settle(pilot, 0.3)
        builder = app.query_one(playoffs.PlayoffBuilder)
        week = builder.current().week
        await pilot.press("full_stop")
        await settle(pilot)
        assert builder.current().week == week + 1
        await pilot.press("comma")
        await settle(pilot)
        assert builder.current().week == week
        assert "j k game" in bottom_row(app) and "h l pick" in bottom_row(app)

    drive(scenario, size=(46, 40))


# --- writes: a tap never sends -------------------------------------------------------------------------

def test_a_tap_on_apply_in_the_key_bar_only_moves_the_focus(monkeypatch):
    sent = []

    async def scenario(pilot, app):
        monkeypatch.setattr(app, "apply", lambda pending: sent.append(pending))
        await pilot.press("t")
        await settle(pilot)
        assert app.pending and "tab apply" in bottom_row(app)
        bar = app.query_one(KeyBar)
        start = next(r[0] for r in bar.regions if bar._entries[r[2]][0].key == "tab")
        await pilot.click(KeyBar, offset=(start + 1 + bar.styles.padding.left, 0))
        await settle(pilot)
        assert app.focused is app.query_one("#apply") and not sent
        assert "send to ESPN" in bottom_row(app)
        await pilot.press("enter")  # right after the tap: a stray second press does nothing
        await settle(pilot)
        assert not sent
        await pilot.pause(0.7)
        await pilot.press("enter")
        await settle(pilot)
        assert len(sent) == 1

    drive(scenario, size=(46, 40))


def test_enter_on_a_phone_plan_never_sends(monkeypatch):
    sent = []

    async def scenario(pilot, app):
        monkeypatch.setattr(app, "apply", lambda pending: sent.append(pending))
        await pilot.press("w")
        await settle(pilot)
        assert app.pending and app.focused is app.query_one("#content")
        await pilot.press("enter", "enter", "space", "j")
        await settle(pilot)
        assert not sent and app.query_one("#actions").has_class("visible")

    drive(scenario, size=(46, 40))


def test_apply_buttons_take_one_row_on_a_phone():
    async def scenario(pilot, app):
        await pilot.press("t")
        await settle(pilot)
        assert app.query_one("#apply").region.height == 1
        assert app.query_one("#actions").region.height == 1

    drive(scenario, size=(46, 18))


# --- lines that used to wrap mid-thought -------------------------------------------------------------

def week_plans(session):
    periods = [p for p in periods_for(session, "week") if p >= session.league().scoring_period]
    return session.plan_days(periods)


@pytest.mark.parametrize("width", range(30, 121, 2))
def test_day_headers_keep_to_one_line(width):
    session = demo_session()
    plans = week_plans(session)
    for p in plans:
        for line in (plan.day_header(p, session.calendar, DARK, width),
                     plan.quiet_day(p, session.calendar, DARK, width)):
            assert line.cell_len <= width, (width, line.plain)


def test_the_day_header_at_exactly_64_columns():
    session = demo_session()
    p = week_plans(session)[0]
    assert plan.day_header(p, session.calendar, DARK, 64).plain == \
        "Wed Nov 4   13 play  ·  proj 382.0  ·  +30.9"
    assert plan.day_header(p, session.calendar, DARK, 66).plain.startswith(
        "Wed Nov 4   13 of your players play")


@pytest.mark.parametrize("width", [34, 37, 40, 43, 46, 58])
def test_the_plan_on_a_phone(width):
    session = demo_session()
    out = text_of(views.plan(week_plans(session), session.calendar, DARK, width), width)
    lines = out.splitlines()
    assert max(len(x.rstrip()) for x in lines) <= width
    assert not any(x.rstrip().endswith(("=", "×", "from the")) for x in lines)
    assert any(re.search(r"DTD: \d+\.\d × 75% = \d+\.\d", x) for x in lines)  # the math whole
    summary = lines[1] if not re.search(r"\d", lines[0].split("days")[-1]) else lines[0]
    assert "proj" in summary and "+188.2" in summary


def test_two_starters_across_from_35_columns():
    session = demo_session()
    p = week_plans(session)[0]
    out = text_of(plan.lineup(p, session.calendar, DARK, 35), 35).splitlines()
    assert all(len(re.findall(r"\b(?:PG|SG|SF|PF|C|G|F|UT) ", x)) == 2 for x in out[:-1])


@pytest.mark.parametrize("width", [37, 40, 46])
def test_trades_never_split_a_name(width):
    from benchboss.core import trades as trades_mod

    lg = demo_session().league()
    ideas = trades_mod.find_trades(lg, limit=8)
    out = text_of(views.trades(ideas, DARK, width=width), width)
    assert max(len(x.rstrip()) for x in out.splitlines()) <= width
    for t in ideas:
        assert any(t.give.name in x for x in out.splitlines())
        assert any(t.get.name in x for x in out.splitlines())
    # the CLI lays them out for its console width the same way
    assert text_of(views.trades(ideas, DARK), width) == out


@pytest.mark.parametrize("width", [30, 34, 37, 40])
def test_the_trash_caption_and_hint_break_between_items(width):
    data = trash.load(demo_session())
    out = [x.rstrip() for x in text_of(trash.draw(data, DARK, width), width).splitlines()]
    assert max(len(x) for x in out) <= width
    assert not any(x.endswith(("minus the", " per", "--drop", "add")) for x in out)
    assert any('benchboss add "Player"' in x for x in out)
    assert any('--drop "Player"' in x for x in out)


@pytest.mark.parametrize("width", [37, 40, 43, 46])
def test_the_roster_keeps_who_plays_today_on_a_phone(width):
    data = roster.load(demo_session())
    out = text_of(roster.draw(data, DARK, width), width)
    assert max(len(x.rstrip()) for x in out.splitlines()) <= width
    ball = next(x for x in out.splitlines() if "Ball" in x)
    assert "@HOU" in ball or "●" in ball


def test_the_roster_drops_the_nba_team_before_today():
    data = roster.load(demo_session())
    narrow = text_of(roster.draw(data, DARK, 38), 38)
    ball = next(x for x in narrow.splitlines() if "Ball" in x)
    assert "●" in ball and "MIN" not in ball and "plays today" in narrow


@pytest.mark.parametrize("pal", [DARK, LIGHT], ids=["dark", "light"])
@pytest.mark.parametrize("width", layout.FIT_WIDTHS)
def test_the_redrawn_boards_fit_every_width(pal, width):
    session = demo_session()
    d = dashboard.collect(session)
    from benchboss.core import trades as trades_mod

    for board in (dashboard.render(d, pal, width), views.plan(week_plans(session),
                                                              session.calendar, pal, width),
                  trash.draw(trash.load(session), pal, width),
                  roster.draw(roster.load(session), pal, width),
                  views.trades(trades_mod.find_trades(session.league(), limit=4), pal, width=width)):
        out = text_of(board, width)
        assert max(len(x.rstrip()) for x in out.splitlines()) <= width

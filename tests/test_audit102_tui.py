"""Regression tests for the 1.0.2 audit of the interactive app: focus, the finder's fetches
and layout, the dashboard timer, the status line and the watch-list toasts."""

import asyncio
import io
import json
import time

import pytest
from rich.console import Console
from textual import events
from textual.widgets import DataTable, LoadingIndicator, OptionList, Static

from benchboss import config as config_mod
from benchboss import inbox
from benchboss.cli import main
from benchboss.config import Config
from benchboss.demo import demo_session
from benchboss.ui import dashboard
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import finder, playoffs
from benchboss.ui.theme import DARK

GOES_TO = {"d": "dash", "s": "standings", "p": "players", "y": "playoffs"}


async def settle(pilot):
    for _ in range(2):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


def drive(scenario, size=(140, 44), app=None):
    """Run ``scenario(pilot, app)`` on the demo app; a crash inside the app fails the test."""
    app = app or Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await scenario(pilot, app)
    asyncio.run(run())
    assert app.return_code in (None, 0)
    return app


def plain(widget) -> str:
    content = widget.content if isinstance(widget, Static) else widget
    return content.plain if hasattr(content, "plain") else str(content)


def text_of(renderable, width: int = 120) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def slow_pool(app, delay: float) -> list:
    """Make the player pool take ``delay`` seconds; returns the list of calls made."""
    real, calls = app.session.player_pool, []

    def pool(*a, **kw):
        calls.append(a)
        time.sleep(delay)
        return real(*a, **kw)

    app.session.player_pool = pool
    return calls


async def until(pilot, check, timeout: float = 5.0):
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, "timed out"
        await pilot.pause(0.02)


# --- tui-1: leaving the finder right after it is drawn ------------------------------------------

@pytest.mark.parametrize("key", list(GOES_TO))
def test_a_menu_key_right_after_the_finder_is_drawn_does_not_crash(key):
    """The key arrives after the finder is mounted but before the focus the app scheduled
    for it runs: that focus used to look for a table that was already gone."""
    app = Benchboss(Config(), demo=True)
    finish, sent = app._finish, []

    def finish_then_key(sid, draw, pending):
        finish(sid, draw, pending)
        if sid == "players" and not sent:
            sent.append(key)
            app.post_message(events.Key(key, key))

    app._finish = finish_then_key

    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        await settle(pilot)
        assert sent and app.current == GOES_TO[key]
        assert app.focused is not None and app.focused.is_attached
        await pilot.press("o")
        await settle(pilot)
        assert app.current == "roster"

    drive(scenario, app=app)


@pytest.mark.parametrize("then", ["players", "dash"])
def test_leaving_the_finder_before_it_is_composed_does_not_crash(then):
    async def scenario(pilot, app):
        app.current = "players"
        draw, _ = app._build("players")
        app._finish("players", draw, None)  # mounts the finder...
        app.action_show(then)               # ...and takes it off before it is composed
        await settle(pilot)
        await settle(pilot)
        assert app.current == then
        if then == "players":
            view = app.query_one(finder.FinderView)
            assert app.focused is view.query_one(DataTable)

    drive(scenario)


def test_late_callbacks_on_a_finder_that_was_left_do_nothing():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        pid, players = view._current_id(), list(view.players)
        app.action_show("dash")
        assert not view._live()  # at once, while Textual is still removing its parts
        late = (lambda: view.focus(), lambda: view._scroll_columns(0, "proj"),
                lambda: view._fetched(view._gen, [], "", "last"),
                lambda: view._news_loaded(pid, [], ""), lambda: view._set_star(pid, True))
        for call in late:
            call()
        assert view.players == players and view._pool_sort == "proj"
        await settle(pilot)
        assert not view.is_attached
        for call in late:
            call()
        assert app.current == "dash" and app.focused is not None and app.focused.is_attached

    drive(scenario)


# --- tui-2: fetching never covers the finder ------------------------------------------------------

def test_a_quiet_refetch_keeps_the_rows_on_screen():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        await pilot.press("4")
        await settle(pilot)
        t = view.query_one(DataTable)
        assert len(view.players) == view.limit  # a full pool: a new sort asks ESPN again
        calls = slow_pool(app, 1.5)
        await pilot.press("greater_than_sign")  # Proj to Prev
        await until(pilot, lambda: calls)
        await pilot.pause()
        assert not view.loading and not app.query(LoadingIndicator)  # Textual's cover stays off
        assert view.fetching
        assert t.row_count == len(view.players) > 0 and app.focused is t
        assert "Loading..." in plain(view.query_one("#finder-title"))
        assert "Everyone" in plain(view.query_one("#finder-title"))
        await settle(pilot)
        assert not view.fetching and "Loading..." not in plain(view.query_one("#finder-title"))
        assert view.sort_key == "last" and view._pool_sort == "last"

    drive(scenario)


def test_a_new_pool_says_loading_in_the_finder_without_covering_it():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        calls = slow_pool(app, 1.5)
        await pilot.press("2")
        await until(pilot, lambda: calls)
        await pilot.pause()
        assert not view.loading and not app.query(LoadingIndicator)
        msg = view.query_one("#finder-message")
        assert msg.has_class("visible") and plain(msg) == "Loading..."
        assert "On a team" in plain(view.query_one("#finder-tabs"))
        assert app.focused is view.query_one(DataTable)
        await settle(pilot)
        assert view.source == "rostered" and view.players and not msg.has_class("visible")

    drive(scenario)


def test_a_sort_espn_already_ranked_the_pool_by_does_not_ask_again():
    """Player, Start% and the box score sort the pool ESPN ranked by the split."""
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        await pilot.press("4")
        await settle(pilot)
        calls = slow_pool(app, 0)
        # Rost% and Proj are ESPN sorts (the pool is ranked by Proj until Rost% asks again)
        for key, asked in (("name", 0), ("start", 0), ("gp", 0), ("own", 1), ("gp", 2),
                           ("proj", 2)):
            view._sort(key)
            await pilot.pause(0.5)
            await settle(pilot)
            assert len(calls) == asked, key
        view._sort("last")
        view._sort("proj")  # back before the pause: nothing to ask
        await pilot.pause(0.5)
        await settle(pilot)
        assert len(calls) == 2

    drive(scenario)


# --- tui-3: the keys stay on the interactive screens ---------------------------------------------

@pytest.mark.parametrize("size,presses", [((100, 40), "mm"), ((140, 40), "mmm")])
def test_hiding_the_menu_gives_the_keys_back_to_the_finder(size, presses):
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        await pilot.press(*presses)
        await settle(pilot)
        assert app.query_one("#menu").has_class("hidden")
        assert app.focused is view.query_one(DataTable)
        await pilot.press("2")
        await settle(pilot)
        assert view.source == "rostered"

    drive(scenario, size=size)


@pytest.mark.parametrize("size,presses", [((100, 40), "mm"), ((140, 40), "mmm")])
def test_hiding_the_menu_gives_the_keys_back_to_the_playoff_builder(size, presses):
    async def scenario(pilot, app):
        await pilot.press("y")
        await settle(pilot)
        builder = app.query_one(playoffs.PlayoffBuilder)
        await pilot.press(*presses)
        await settle(pilot)
        assert app.focused is builder
        await pilot.press("right")
        await settle(pilot)
        assert len(builder.picks) == 1

    drive(scenario, size=size)


def test_a_wider_window_brings_the_menu_back_without_taking_the_keys():
    async def scenario(pilot, app):
        await pilot.press("y")
        await settle(pilot)
        builder = app.query_one(playoffs.PlayoffBuilder)
        menu = app.query_one("#menu", OptionList)
        await pilot.press("right")
        await settle(pilot)
        await pilot.resize_terminal(105, 44)
        await settle(pilot)
        assert menu.has_class("hidden") and app.focused is builder
        await pilot.resize_terminal(140, 44)
        await settle(pilot)
        assert not menu.has_class("hidden") and app.focused is builder
        highlighted, cursor = menu.highlighted, builder.cursor
        await pilot.press("down")
        await settle(pilot)
        assert menu.highlighted == highlighted and builder.cursor != cursor
        assert app.query_one(playoffs.PlayoffBuilder) is builder and len(builder.picks) == 1

    drive(scenario)


def test_static_screens_still_hand_the_keys_to_the_menu_on_a_wider_window():
    async def scenario(pilot, app):
        await pilot.press("s")
        await settle(pilot)
        await pilot.resize_terminal(100, 44)
        await settle(pilot)
        await pilot.resize_terminal(140, 44)
        await settle(pilot)
        assert app.focused is app.query_one("#menu")

    drive(scenario)


@pytest.mark.parametrize("first", ["p", "y"])
def test_picking_a_screen_from_the_menu_on_a_narrow_window(first):
    async def scenario(pilot, app):
        await pilot.press(first)
        await settle(pilot)
        await pilot.press("m")
        await settle(pilot)
        assert app.focused is app.query_one("#menu")
        await pilot.press("s")
        await settle(pilot)
        assert app.current == "standings" and app.focused is app.query_one("#content")
        await pilot.press("p")
        await settle(pilot)
        assert app.focused is app.query_one(finder.FinderView).query_one(DataTable)

    drive(scenario, size=(100, 40))


# --- tui-4: the dashboard reloads every minute ----------------------------------------------------

def test_the_dashboard_timer_reloads_the_dashboard(monkeypatch):
    app = Benchboss(Config(), demo=True)
    assert callable(app._refresh_dashboard)
    timers, set_interval = [], app.set_interval

    def record(interval, callback=None, **kw):
        timers.append((interval, callback))
        return set_interval(interval, callback, **kw)

    app.set_interval = record
    collected, collect = [], dashboard.collect
    monkeypatch.setattr(dashboard, "collect", lambda s: collected.append(1) or collect(s))

    async def scenario(pilot, app):
        tick = next(callback for every, callback in timers if every == 60)
        assert callable(tick)
        before = len(collected)
        tick()
        await settle(pilot)
        assert len(collected) == before + 1
        await pilot.press("s")
        await settle(pilot)
        tick()  # only the dashboard reloads on its own
        await settle(pilot)
        assert len(collected) == before + 1 and app.current == "standings"

    drive(scenario, app=app)


# --- tui-5: the card leaves room for the table ------------------------------------------------------

@pytest.mark.parametrize("size", [(80, 24), (90, 24), (120, 24), (120, 30)])
def test_the_player_card_leaves_five_players_on_a_short_window(size):
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        await pilot.press("enter")
        await settle(pilot)
        box, t = view.query_one("#finder-detail"), view.query_one(DataTable)
        assert box.has_class("open") and box.region.height >= 3
        assert t.scrollable_content_region.height - 1 >= 5  # rows under the header
        hint = view.query_one("#finder-hint")
        assert hint.region.height == 1 and hint.region.bottom <= view.region.bottom

    drive(scenario, size=size)


def test_the_player_card_is_as_tall_as_what_it_shows_on_a_tall_window():
    async def scenario(pilot, app):
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        await pilot.press("enter")
        await settle(pilot)
        box, card = view.query_one("#finder-detail"), view.query_one("#finder-card")
        assert box.max_scroll_y == 0
        assert box.region.height == card.region.height + box.styles.gutter.height  # no blank rows
        assert view.query_one(DataTable).scrollable_content_region.height > box.region.height

    drive(scenario, size=(150, 60))


# --- tui-6: the status line names the split v goes to -----------------------------------------

def test_the_status_line_names_the_split_v_goes_to_in_the_preseason():
    async def scenario(pilot, app):
        real = app.session.player_pool

        def preseason(*a, **kw):
            players = real(*a, **kw)
            for p in players:
                p.stats = {k: v for k, v in p.stats.items() if k in ("proj", "last")}
            return players

        app.session.player_pool = preseason
        status = app.query_one("#status", Static)
        await pilot.press("p")
        await settle(pilot)
        view = app.query_one(finder.FinderView)
        assert plain(status).startswith("Projected · v for Last season ·")
        await pilot.press("v")
        await settle(pilot)
        assert view.split == "last"
        assert plain(status).startswith("Last season · v for Projected ·")
        await pilot.press("v")
        await settle(pilot)
        assert view.split == "proj" and plain(status).startswith("Projected · v for Last season")

    drive(scenario)


def test_the_status_line_follows_every_split_in_season():
    async def scenario(pilot, app):
        status = app.query_one("#status", Static)
        await pilot.press("p")
        await settle(pilot)
        assert plain(status).startswith("Projected · v for Last season ·")
        await pilot.press("v")
        await settle(pilot)
        assert plain(status).startswith("Last season · v for Season ·")

    drive(scenario)


# --- tui-7: a toast is not a read ------------------------------------------------------------------

def test_toasts_show_each_spin_once_and_leave_it_unread(session):
    first = inbox.toast_spins(session)
    assert [who for who, _ in first] == ["Egor Demin", "Dereck Lively II"]
    assert inbox.toast_spins(session) == []
    assert inbox.toast_spins(demo_session()) == []  # remembered on disk
    assert len(inbox.watch_spins(session)) == 2  # still unread
    assert [a.kind for a in inbox.alerts(session)][-2:] == ["spin", "spin"]
    assert not (config_mod.config_dir() / inbox.SEEN_FILE).exists()
    toasted = json.loads((config_mod.config_dir() / inbox.TOASTED_FILE).read_text())
    assert sorted(toasted[str(session.client.league_id)]) == sorted(i.id for _, i in first)


def test_news_already_marked_read_is_never_toasted(session):
    inbox.watch_spins(session, mark_seen=True)
    assert inbox.toast_spins(session) == []
    assert not (config_mod.config_dir() / inbox.TOASTED_FILE).exists()


def test_the_inbox_and_the_cli_keep_watch_list_news_after_the_app_toasts_it(capsys):
    app = Benchboss(Config(), demo=True)
    toasts = []
    app.notify = lambda message, **kw: toasts.append(message)

    async def scenario(pilot, app):
        app.check_spins()
        await settle(pilot)
        assert len(toasts) == 2
        await pilot.press("i")
        await settle(pilot)
        body = text_of(app.query_one("#body", Static).content)
        assert "★ Watch list · Egor Demin" in body and "★ Watch list · Dereck Lively II" in body
        app.check_spins()
        await settle(pilot)
        assert len(toasts) == 2  # still one toast per spin

    drive(scenario, app=app)
    main(["--demo", "alerts"])
    out = capsys.readouterr().out
    assert "★ Watch list · Egor Demin" in out and "--mark-read" in out


# --- tui-8: no hint to press 4 on Everyone ---------------------------------------------------------

def test_no_hits_on_everyone_does_not_suggest_everyone(capsys):
    data = finder.FinderData([], "all", query="zzqx")
    app_tip, cli_tip = (finder.empty_message(data, DARK, app=True).plain,
                        finder.empty_message(data, DARK).plain)
    assert "Press 4" not in app_tip and "escape" in app_tip and "shorter name" in app_tip
    assert "--from all" not in cli_tip and "shorter name" in cli_tip
    fa = finder.empty_message(finder.FinderData([], "fa", query="zzqx"), DARK, app=True).plain
    assert "Press 4 to search everyone" in fa  # from a narrower pool, 4 still helps
    main(["--demo", "players", "--from", "all", "zzqx"])
    out = capsys.readouterr().out
    assert 'No players match "zzqx" in Everyone' in out and "--from all" not in out

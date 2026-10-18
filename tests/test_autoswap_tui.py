"""The Auto-swap screen (key u) and the Roster mark: two presses to arm, one to disarm, the
menu keys still work, nothing goes to ESPN and the app never sends a notification."""

import asyncio
import io

import pytest
from rich.console import Console
from textual.widgets import DataTable

from benchboss import notify
from benchboss.config import Config
from benchboss.marks import MarkStore
from benchboss.ui import layout
from benchboss.ui.app import MENU, Benchboss
from benchboss.ui.layout import FIT_WIDTHS
from benchboss.ui.screens import autoswap as screen
from benchboss.ui.screens import playoffs
from benchboss.ui.theme import DARK, LIGHT

DANIELS = 4869342


async def settle(pilot):
    for _ in range(2):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


def drive(scenario, size=(140, 44)):
    app = Benchboss(Config(), demo=True)

    async def go():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await scenario(pilot, app)

    asyncio.run(go())
    assert app.return_code in (None, 0)
    return app


@pytest.fixture
def clock(monkeypatch):
    """The screen's clock, moved by hand: the second enter must come 0.6 s after the first."""
    now = [100.0]
    monkeypatch.setattr(screen, "_clock", lambda: now[0])
    return now


@pytest.fixture(autouse=True)
def no_pushes(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the app sent a notification")

    monkeypatch.setattr(notify, "send", refuse)


async def open_screen(pilot, app):
    await pilot.press("u")
    await settle(pilot)
    view = app.query_one(screen.AutoswapView)
    assert app.focused is view.query_one(DataTable)
    return view


def marks(app):
    return {pid: m.mode for pid, m in MarkStore(app.session).load().marks.items()}


def test_u_is_the_menu_key_and_no_widget_takes_a_menu_letter():
    assert ("autoswap", "Auto-swap", "u") in MENU
    keys = [k for _, _, k in MENU]
    assert len(keys) == len(set(keys))
    letters = set(keys) | set("gvmrq")
    for b in screen.AutoswapView.BINDINGS:
        assert not set(b.key.split(",")) & letters, b.key
    for item in screen.AutoswapView(screen.AutoswapData([]), type("A", (), {
            "session": None})()).key_items():
        assert item.key not in letters


def test_two_enters_arm_and_one_disarms(clock):
    async def scenario(pilot, app):
        view = await open_screen(pilot, app)
        assert view._row().player.name == "Dyson Daniels"
        await pilot.press("enter")
        await pilot.pause()
        confirm = view.query_one("#as-confirm")
        assert confirm.has_class("open")
        text = str(confirm.content)
        assert "Arm auto-swap for Dyson Daniels?" in text
        assert "starts him at G and benches Scotty Pippen Jr." in text
        await pilot.press("enter")  # a double press: ignored
        await pilot.pause()
        assert marks(app) == {}
        clock[0] += screen.CONFIRM_DELAY + 0.01
        await pilot.press("enter")
        await pilot.pause()
        assert marks(app) == {DANIELS: "auto"}
        assert not view.query_one("#as-confirm").has_class("open")
        assert str(view.query_one(DataTable).get_cell(str(DANIELS), "mark")) == "✓"
        await pilot.press("enter")  # armed: one enter disarms
        await pilot.pause()
        assert marks(app) == {}

    drive(scenario)


@pytest.mark.parametrize("size", [(150, 54), (46, 30)])
def test_the_table_keeps_its_widths_after_arming(size, clock):
    """Arming redraws the table from an event. A frame drawn before Textual measured the new
    rows kept the header widths in its row cache ("Dyson", "7:0", "starts at", no mark)."""
    async def scenario(pilot, app):
        await open_screen(pilot, app)
        await pilot.press("enter")
        clock[0] += screen.CONFIRM_DELAY + 0.01
        await pilot.press("enter")
        await settle(pilot)
        await pilot.pause(0.3)
        assert marks(app) == {DANIELS: "auto"}
        name = "Dyson Daniels" if size[0] >= 60 else "D. Daniels"
        lines = layout.screen_text(app).splitlines()
        assert any("✓" in ln and name in ln and "Pippen" in ln for ln in lines), lines

    drive(scenario, size=size)


def test_any_other_key_cancels_the_question(clock):
    async def scenario(pilot, app):
        view = await open_screen(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        assert view.confirm is None and not view.query_one("#as-confirm").has_class("open")
        await pilot.press("k", "enter")
        await pilot.pause()
        await pilot.press("escape")  # escape cancels first...
        await pilot.pause()
        assert view.confirm is None
        clock[0] += 5
        await pilot.press("enter")  # ...so this is a new first press, not a yes
        await pilot.pause()
        assert marks(app) == {} and view.confirm is not None

    drive(scenario)


def test_alert_only_and_backspace(clock):
    async def scenario(pilot, app):
        view = await open_screen(pilot, app)
        await pilot.press("exclamation_mark")
        await pilot.pause()
        assert marks(app) == {DANIELS: "notify"}  # no question: it never changes the lineup
        assert str(view.query_one(DataTable).get_cell(str(DANIELS), "mark")) == "!"
        await pilot.press("exclamation_mark")
        await pilot.pause()
        assert marks(app) == {}
        await pilot.press("enter")
        clock[0] += 1
        await pilot.press("enter")
        await pilot.pause()
        assert marks(app) == {DANIELS: "auto"}
        await pilot.press("exclamation_mark")  # auto lowers to alert only
        await pilot.pause()
        assert marks(app) == {DANIELS: "notify"}
        await pilot.press("backspace")
        await pilot.pause()
        assert marks(app) == {}

    drive(scenario)


def test_menu_keys_work_from_the_screen_and_the_roster_shows_the_mark(clock):
    async def scenario(pilot, app):
        await open_screen(pilot, app)
        await pilot.press("enter")
        clock[0] += 1
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("o")
        await settle(pilot)
        assert app.current == "roster"
        body = Console(width=140, record=True, file=io.StringIO())
        body.print(app.query_one("#body").content)
        line = next(ln for ln in body.export_text().splitlines() if "Dyson Daniels" in ln)
        assert "✓" in line
        await pilot.press("u")
        await settle(pilot)
        assert app.current == "autoswap"
        await pilot.press("escape")  # back to the menu
        await pilot.pause()
        assert app.focused is app.query_one("#menu")

    drive(scenario)


def test_u_works_from_the_playoff_builder_where_h_picks_home():
    async def scenario(pilot, app):
        await pilot.press("y")
        await settle(pilot)
        app.query_one(playoffs.PlayoffBuilder)
        await pilot.press("u")
        await settle(pilot)
        assert app.current == "autoswap" and app.query(screen.AutoswapView)

    drive(scenario)


@pytest.mark.parametrize("size", [(46, 30), (80, 24)])
def test_the_screen_works_on_a_phone_sized_window(size, clock):
    async def scenario(pilot, app):
        view = await open_screen(pilot, app)
        cols = [c.label.plain for c in view.query_one(DataTable).columns.values()]
        assert "Player" in cols and "If healthy" in cols
        if size[0] < 50:
            assert "Tip" not in cols and "Slot" not in cols
        await pilot.press("enter")
        clock[0] += 1
        await pilot.press("enter")
        await pilot.pause()
        assert marks(app) == {DANIELS: "auto"}

    drive(scenario, size=size)


@pytest.mark.parametrize("pal", [DARK, LIGHT])
@pytest.mark.parametrize("width", FIT_WIDTHS)
def test_the_drawing_fits_every_width(session, width, pal):
    MarkStore(session).arm(next(sp.player for sp in session.league().me.roster
                                if sp.player.name == "Dyson Daniels"))
    data = screen.load(session)
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(screen.draw(data, pal, width))
    lines = console.export_text().splitlines()
    assert all(len(ln.rstrip()) <= width for ln in lines)
    assert lines[0].startswith("Auto-swap")  # the title stays on one line
    assert any("Daniels" in ln and "✓" in ln for ln in lines)

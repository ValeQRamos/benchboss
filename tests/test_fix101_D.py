"""Regression tests for the 1.0.1 fixes to the interactive app, the dashboard and the views."""

import asyncio
import datetime as dt
import io
import json

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.table import Table
from textual.widgets import Button, Static

from benchboss import config as config_mod
from benchboss.cli import main
from benchboss.config import Config
from benchboss.demo import demo_session
from benchboss.ui import dashboard, views
from benchboss.ui.app import Benchboss
from benchboss.ui.theme import DARK, LIGHT


def text_of(renderable, width: int = 140) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def body(app):
    return app.query_one("#body", Static).content


async def settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def drive(app, scenario, size=(140, 44)):
    async def run():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await scenario(pilot)
    asyncio.run(run())


def recorder(app) -> list:
    sent = []
    app.apply = sent.append  # stands in for the worker that writes to ESPN
    return sent


# --- F31, F32, F34: the plan screen and its buttons --------------------------------------------

def test_resize_on_a_plan_keeps_the_plan_and_theme_change_rebuilds_it():
    app = Benchboss(Config(), demo=True)
    sent = recorder(app)

    async def scenario(pilot):
        await pilot.press("w")
        await settle(pilot)
        app.query_one("#cancel").focus()
        await pilot.pause()
        plan = body(app)
        await pilot.resize_terminal(150, 44)
        await pilot.pause()
        # the plan stays on screen with its buttons: nothing else is swapped in behind them
        assert app.current == "week" and body(app) is plan
        assert app.query_one("#actions").has_class("visible") and app.pending
        await pilot.press("ctrl+t")
        await settle(pilot)
        assert not isinstance(app.focused, Button)
        assert app.pending and app.pending["kind"] == "week"
        await pilot.press("enter")  # lands on the menu, never on a button
        await settle(pilot)
        assert sent == []

    drive(app, scenario)


def test_hidden_buttons_never_act():
    app = Benchboss(Config(), demo=True)
    sent = recorder(app)

    async def scenario(pilot):
        await pilot.press("w")
        await settle(pilot)
        app.query_one("#actions").set_class(False, "visible")  # the bar is hidden, the plan armed
        app.query_one("#apply").press()
        await pilot.pause()
        assert sent == []
        await pilot.press("d")
        await settle(pilot)
        assert app.pending is None
        app.query_one("#apply").press()  # its own display is still on: only the bar is hidden
        app.query_one("#cancel").press()
        await pilot.pause()
        assert sent == []
        assert "Cancelled" not in text_of(body(app))

    drive(app, scenario)


def test_apply_needs_a_plan_built_for_today():
    app = Benchboss(Config(), demo=True)
    sent = recorder(app)

    async def scenario(pilot):
        await pilot.press("t")
        await settle(pilot)
        assert app.pending
        app.pending["day"] -= dt.timedelta(days=1)
        app.query_one("#apply").press()
        await pilot.pause()
        assert sent == []
        assert app.pending is None and not app.query_one("#actions").has_class("visible")
        assert "day changed" in text_of(body(app))

    drive(app, scenario)


def test_after_apply_the_focus_leaves_the_hidden_buttons():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        await pilot.press("w")
        await settle(pilot)
        app.query_one("#apply").focus()
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)
        assert "is set" in text_of(body(app))
        assert not isinstance(app.focused, Button)
        menu = app.query_one("#menu")
        before = menu.highlighted
        await pilot.press("down")
        await pilot.pause()
        assert menu.highlighted == before + 1
        assert "Cancelled" not in text_of(body(app))

    drive(app, scenario)


def test_resize_and_theme_change_keep_the_screen_you_are_on():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        await pilot.press("s")
        await settle(pilot)
        await pilot.resize_terminal(130, 40)
        await pilot.pause()
        assert app.current == "standings" and "Brick City" in text_of(body(app))
        await pilot.press("o")
        await settle(pilot)
        assert body(app).header_style == f"bold {DARK.dim}"
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.current == "roster" and isinstance(body(app), Table)
        assert body(app).header_style == f"bold {LIGHT.dim}"  # drawn again in the new palette

    drive(app, scenario)


def test_theme_change_on_the_ai_briefing_does_not_call_the_api_again(monkeypatch):
    from benchboss import news as news_mod

    calls = []
    monkeypatch.setattr(news_mod, "ai_digest", lambda roster, days: calls.append(1) or "briefing")
    app = Benchboss(Config(), demo=False, session=demo_session())

    async def scenario(pilot):
        await pilot.press("g")
        await settle(pilot)
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.current == "ainews" and "briefing" in text_of(body(app))
        assert calls == [1]

    drive(app, scenario)


# --- F36, F62, F23: narrow windows --------------------------------------------------------------

def test_narrow_window_hides_the_menu_and_trash_keeps_net():
    app = Benchboss(Config(), demo=True)
    picks = demo_session().trash(n=12)

    async def scenario(pilot):
        menu = app.query_one("#menu")
        assert menu.has_class("hidden") and not menu.has_focus
        await pilot.press("f")
        await settle(pilot)
        width = app._width()
        assert width <= app.query_one("#body").size.width  # nothing is cropped
        out = text_of(body(app), width)
        for pk in picks:
            assert f"{pk.net:+.1f}" in out
        await pilot.press("m")  # the menu comes back on demand and the table fits again
        await pilot.pause()
        assert not menu.has_class("hidden") and app._width() < width
        table = body(app).renderables[0]
        assert max(cell_len(x.rstrip()) for x in text_of(table, 200).splitlines()) <= app._width()

    drive(app, scenario, size=(80, 24))


def test_side_panel_width_gets_a_readable_dashboard():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        assert 38 <= app._width() <= app.query_one("#body").size.width
        assert "MONSTARS" in text_of(body(app), app._width())

    drive(app, scenario, size=(46, 40))


@pytest.mark.parametrize("width", [40, 50, 66, 80, 100, 120])
def test_trash_table_fits_and_keeps_net_and_g(session, width):
    picks = session.trash(n=10)
    out = text_of(views.trash(picks, session.calendar, DARK, width), width)
    lines = out.splitlines()
    assert max(cell_len(x.rstrip()) for x in lines) <= width
    header = next(x for x in lines if "Player" in x)
    assert "Net" in header and " G " in header
    for pk in picks:
        assert f"{pk.net:+.1f}" in out


def test_trash_names_the_drop_when_its_column_goes(session):
    picks = session.trash(n=10)
    drop = picks[0].drop.name
    same = [pk for pk in picks if pk.drop and pk.drop.name == drop]
    narrow = text_of(views.trash(same, session.calendar, DARK, 66), 66)
    assert "Drop" not in narrow.splitlines()[2]
    assert drop.split()[0] in narrow and "the suggested drop" in narrow
    wide = text_of(views.trash(picks, session.calendar, DARK, 120), 120)
    assert "Drop" in wide and "Own%" in wide


def test_cli_trash_at_80_columns(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    main(["--demo", "trash"])
    out = capsys.readouterr().out
    assert max(cell_len(x.rstrip()) for x in out.splitlines()) <= 80
    top = demo_session().trash(n=1)[0]
    assert "Net" in out and " G " in out and f"{top.net:+.1f}" in out


# --- F33: fresh lineup after Apply ------------------------------------------------------------

def test_apply_forgets_the_cached_league():
    s = demo_session()
    s.apply_days = lambda periods: []  # stands in for ESPN
    app = Benchboss(Config(), demo=False, session=s)

    async def scenario(pilot):
        await pilot.press("t")
        await settle(pilot)
        assert s._league is not None
        app.query_one("#apply").press()
        await settle(pilot)
        assert s._league is None

    drive(app, scenario)


# --- F37, F42: outside the season -------------------------------------------------------------

@pytest.mark.parametrize("day", ["2026-10-15", "2027-04-20"])
def test_outside_the_season_nobody_plays_today(day):
    s = demo_session()
    s._today = dt.date.fromisoformat(day)
    app = Benchboss(Config(), demo=True, session=s)
    draw, _ = app._build("roster")
    assert "●" not in text_of(draw(DARK, 120))
    draw, _ = app._build("activity")
    table = table_in(draw(DARK, 120))
    assert all(c.header_style != f"bold {DARK.accent}" for c in table.columns)
    draw, pending = app._build("today")
    assert pending is None
    out = text_of(draw(DARK, 120))
    assert "`" not in out and "date like" not in out
    if day.startswith("2026"):
        assert "The season starts Tue Oct 20" in out and "Press w" in out


def test_in_season_today_is_highlighted(session):
    app = Benchboss(Config(), demo=True, session=session)
    table = table_in(app._build("activity")[0](DARK, 120))
    assert sum(c.header_style == f"bold {DARK.accent}" for c in table.columns) == 1


def table_in(renderable) -> Table:
    """The table in a screen's drawing (the workload draws a title, the table and a legend)."""
    if isinstance(renderable, Table):
        return renderable
    return next(r for r in renderable.renderables if isinstance(r, Table))


def test_dashboard_trash_card_skips_picks_that_add_nothing(session):
    d = dashboard.collect(session)
    assert dashboard.trash_card(d, DARK) is not None
    for pk in d.trash:
        pk.gain, pk.drop_cost = 0.0, 0.0
    assert dashboard.trash_card(d, DARK) is None
    d.trash[0].gain = 12.0
    out = text_of(dashboard.trash_card(d, DARK), 60)
    assert "+12 pts" in out and "+-" not in out and out.count("pts") == 1


def test_news_hint_matches_where_the_dashboard_runs(session):
    d = dashboard.collect(session)
    assert "n for more" not in text_of(dashboard.render(d, DARK, 120), 120)
    app = Benchboss(Config(), demo=True, session=session)
    assert "n for more" in text_of(app._build("dash")[0](DARK, 120), 120)


# --- F38, F44: ctrl+t saves only the theme ----------------------------------------------------

def test_theme_toggle_saves_only_the_theme(monkeypatch):
    path = config_mod.config_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = {"league_id": 111, "team_id": 1, "season": None, "theme": "dark",
             "league_name": "Main League", "team_name": "Main Team"}
    path.write_text(json.dumps(saved))
    monkeypatch.setenv("BENCHBOSS_LEAGUE_ID", "999")
    monkeypatch.setenv("BENCHBOSS_TEAM_ID", "7")
    monkeypatch.setenv("BENCHBOSS_SEASON", "2026")
    app = Benchboss(config_mod.load(), demo=False, session=demo_session())

    async def scenario(pilot):
        await pilot.press("ctrl+t")
        await pilot.pause()

    drive(app, scenario)
    assert json.loads(path.read_text()) == {**saved, "theme": "light"}


def test_save_theme_without_a_file_and_with_a_broken_one():
    path = config_mod.config_dir() / "config.json"
    assert config_mod.save_theme("light") == path
    assert json.loads(path.read_text()) == {"theme": "light"}
    path.write_text("{not json")
    assert config_mod.save_theme("dark") is None
    assert path.read_text() == "{not json"


# --- F35: r reads the cookies and config again ------------------------------------------------

def test_reload_rebuilds_the_session_and_rereads_config(monkeypatch):
    from benchboss import service

    made = []
    monkeypatch.setattr(service, "Session", lambda cfg: made.append(cfg) or demo_session())
    path = config_mod.config_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"league_id": 1, "team_name": "Old Name"}))
    app = Benchboss(config_mod.load(), demo=False)

    async def scenario(pilot):
        assert len(made) == 1
        await pilot.press("ctrl+t")
        await pilot.pause()
        path.write_text(json.dumps({"league_id": 1, "team_name": "New Name", "theme": "dark"}))
        await pilot.press("r")
        await settle(pilot)
        assert len(made) == 2
        assert app.cfg.team_name == "New Name" and app.cfg.theme == "light"

    drive(app, scenario)


def test_reload_keeps_an_injected_session():
    s = demo_session()
    app = Benchboss(Config(), demo=False, session=s)

    async def scenario(pilot):
        await pilot.press("r")
        await settle(pilot)
        assert app._session is s

    drive(app, scenario)


# --- F70: trades at a position limit ----------------------------------------------------------

def test_trades_at_the_position_limit_say_so(session):
    lg = session.league()
    out = text_of(views.trades([], DARK, "C", lg))
    assert "allows at most 4" in out and "fairness" not in out
    assert "fairness" in text_of(views.trades([], DARK, "PG", lg))
    assert "fairness" in text_of(views.trades([], DARK, "C"))


def test_cli_trades_need_c_at_the_limit(capsys):
    main(["--demo", "trades", "--need", "C"])
    assert "allows at most 4" in capsys.readouterr().out

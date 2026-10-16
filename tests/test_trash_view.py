"""The Best trash screen: the games strip, the width fitting, both palettes, waivers."""

import asyncio
import dataclasses
import datetime as dt
import io

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.segment import Segment
from textual.widgets import Static

from benchboss.config import Config
from benchboss.ui import views
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import trash as screen
from benchboss.ui.theme import DARK, LIGHT

ET = dt.timezone(dt.timedelta(hours=-5))


def render(renderable, width: int) -> tuple[str, set[str]]:
    """The plain text and the set of foreground colors (hex) of a renderable."""
    console = Console(width=width, record=True, file=io.StringIO(), color_system="truecolor")
    console.print(renderable)
    colors = {seg.style.color.get_truecolor().hex for seg in Segment.filter_control(console._record_buffer)
              if seg.style and seg.style.color and seg.text.strip()}
    return console.export_text(), colors


def at(session, day: int, hour: int, minute: int = 0):
    """Move the demo session to a moment of matchup week 3 (November 2026, Eastern time)."""
    session._today = dt.date(2026, 11, day)
    session._now = dt.datetime(2026, 11, day, hour, minute, tzinfo=ET)
    return session


def expected_strip(pk, span, cal) -> str:
    return "".join(" " if pk.best_day is None or d < pk.best_day
                   else "●" if cal.plays(pk.player.pro_team_id, d) else "·" for d in span)


def header_of(text: str) -> str:
    return next(x for x in text.splitlines() if "Player" in x)


def with_claim(session):
    """The demo's top free agents with the second one on waivers."""
    top = [pk.player for pk in session.trash(n=8)]
    claim = dataclasses.replace(top[1], status="WAIVERS")
    session.free_agents = lambda *a, **k: [top[0], claim, *top[2:]]
    return claim


# --- the games strip ---------------------------------------------------------------------------

@pytest.mark.parametrize("when", [None, (2, 12), (4, 20), (6, 12)])
def test_strip_matches_the_calendar(session, when):
    if when:
        at(session, *when)
    cal = session.calendar
    picks = session.trash(n=20)
    span = screen.week_span(picks)
    assert span and span[-1] == session.matchup_periods()[-1]  # through Sunday
    for pk in picks:
        strip = screen.games_strip(pk, span, cal, DARK)
        assert strip.plain == expected_strip(pk, span, cal)
        assert strip.plain.count("●") == pk.games_left == len(pk.game_days(cal))
        if pk.best_day is not None:
            grab = span.index(pk.best_day)
            assert strip.plain[:grab].strip() == ""  # nothing before the grab day
            assert DARK.accent in str(strip.get_style_at_offset(Console(), grab))


def test_spaced_strip_sits_under_the_day_initials(session):
    data = screen.load(session)
    out, _ = render(screen.trash(data.picks, data.calendar, DARK, 160), 160)
    head = header_of(out)
    assert "W T F S S" in head  # Wed Nov 4 to Sun Nov 8
    col = head.index("W T F S S")
    span = screen.week_span(data.picks)
    rows = out.splitlines()[out.splitlines().index(head) + 2:][:len(data.picks)]
    for pk, row in zip(data.picks, rows, strict=True):
        want = " ".join(expected_strip(pk, span, data.calendar))
        assert row[col:col + len(want)] == want


def test_a_game_that_already_tipped_off_is_not_counted(session):
    cal = session.calendar
    pk = next(p for p in session.trash(n=20)
              if p.best_day == session.today_period and cal.plays(p.player.pro_team_id, p.best_day))
    started = dataclasses.replace(pk, games_left=pk.games_left - 1)
    assert started.game_days(cal) == pk.game_days(cal)[1:]
    strip = screen.games_strip(started, screen.week_span([pk]), cal, DARK)
    assert strip.plain[0] == "○" and strip.plain.count("●") == started.games_left


# --- width fitting -----------------------------------------------------------------------------

@pytest.mark.parametrize("pal", [DARK, LIGHT], ids=["dark", "light"])
@pytest.mark.parametrize("width", [46, 80, 120, 160])
def test_every_width_fits_and_keeps_net_and_g(session, width, pal):
    data = screen.load(session)
    for drawing in (screen.draw(data, pal, width), views.trash(data.picks, data.calendar, pal, width)):
        out, _ = render(drawing, width)
        assert max(cell_len(x.rstrip()) for x in out.splitlines()) <= width
        assert out.splitlines()[0].startswith("Best trash")
        head = header_of(out)
        assert " G " in head and " Net" in head
        for pk in data.picks:
            assert f"{pk.net:+.1f}" in out


def test_wide_shows_every_column_and_narrow_shortens_names(session):
    data = screen.load(session)
    wide, _ = render(screen.draw(data, DARK, 160), 160)
    head = header_of(wide)
    for col in ("#", "Pos", "G", "Grab", "+Pts", "Drop", "Net", "Proj", "Own%"):
        assert f" {col} " in f"{head} "
    assert "Mitchell Robinson BOS" in wide and "Sat Nov 7" in wide
    assert "points added if you grab him" in wide.splitlines()[0]
    narrow, _ = render(screen.draw(data, DARK, 46), 46)
    assert "M. Robinson BOS" in narrow and "Mitchell Robinson" not in narrow
    assert "Own%" not in narrow and "Pos" not in header_of(narrow)


def test_ownership_arrows_follow_the_change(session):
    data = screen.load(session)
    out, _ = render(screen.trash(data.picks, data.calendar, DARK, 160), 160)
    for pk in data.picks:
        row = next(x for x in out.splitlines() if pk.player.name in x)
        change = pk.player.owned_change
        assert ("▲" in row) == (change >= 0.1) and ("▼" in row) == (change <= -0.1)
        assert f"{pk.player.owned:.1f}" in row


def test_the_caption_explains_the_columns_briefly(session):
    data = screen.load(session)
    out, _ = render(screen.trash(data.picks, data.calendar, DARK, 120), 120)
    lines = out.splitlines()
    caption = lines[lines.index(header_of(out)) + 2 + len(data.picks):]
    text = " ".join(x.strip() for x in caption if x.strip())
    for key in ("+Pts", "Net", "G ", "*"):
        assert key in text
    assert len(text.split()) <= 40  # the 1.0.1 caption took about 60 words


# --- both palettes -----------------------------------------------------------------------------

def test_light_and_dark_use_their_own_colors(session):
    data = screen.load(session)
    dark_text, dark = render(screen.draw(data, DARK, 120), 120)
    light_text, light = render(screen.draw(data, LIGHT, 120), 120)
    assert dark_text == light_text
    for pal, colors, other in ((DARK, dark, LIGHT), (LIGHT, light, DARK)):
        assert {pal.accent, pal.good, pal.text, pal.dim, pal.warn} <= colors
        assert not colors & {other.accent, other.good, other.text, other.dim}


def test_net_is_the_only_bold_cell_in_a_row(session):
    data = screen.load(session)
    console = Console(width=160, record=True, file=io.StringIO(), color_system="truecolor")
    console.print(screen.trash(data.picks, data.calendar, DARK, 160))
    lines = list(Segment.split_lines(console._record_buffer))
    rows = [ln for ln in lines if any(pk.player.name in seg.text for seg in ln for pk in data.picks)]
    assert len(rows) == len(data.picks)
    for row in rows:
        bold = [seg.text.strip() for seg in row if seg.style and seg.style.bold and seg.text.strip()]
        assert len(bold) == 1 and bold[0].startswith(("+", "-"))


# --- waivers, hint, empty week -----------------------------------------------------------------

def test_waiver_claims_are_marked(session):
    claim = with_claim(session)
    data = screen.load(session)
    pick = next(pk for pk in data.picks if pk.player.id == claim.id)
    assert pick.on_waivers and pick.best_day > session.today_period
    wide, _ = render(screen.draw(data, DARK, 120), 120)
    row = next(x for x in wide.splitlines() if claim.name in x)
    assert "(W)" in row and "(W) on waivers" in wide
    narrow, _ = render(screen.draw(data, DARK, 46), 46)  # no Grab column: (W) follows the name
    assert "Grab" not in header_of(narrow)
    row = next(x for x in narrow.splitlines() if claim.short_name in x)
    assert "(W)" in row
    assert sum("(W)" in x for x in narrow.splitlines()) == 2  # the row and the caption


def test_app_draw_has_the_hint_and_the_cli_prints_just_the_table(session):
    data = screen.load(session)
    app, _ = render(screen.draw(data, DARK, 120), 120)
    cli, _ = render(views.trash(data.picks, data.calendar, DARK, 120), 120)
    assert 'benchboss add "Player" --drop "Player"' in app
    assert "benchboss add" not in cli and cli.startswith("Best trash")
    narrow, _ = render(screen.draw(data, DARK, 40), 40)
    assert "Grab one from a terminal:\nbenchboss add" in narrow


def test_nothing_left_on_sunday_night(session):
    at(session, 8, 16)  # Sunday after the first tip-off
    data = screen.load(session)
    out, _ = render(screen.draw(data, DARK, 46), 46)
    assert "Nothing left to gain this week" in out and "benchboss add" not in out
    assert max(cell_len(x.rstrip()) for x in out.splitlines()) <= 46


def test_json_lists_the_game_days(session):
    data = screen.load(session)
    for pk, row in zip(data.picks, screen.to_json(data), strict=True):
        assert len(row["game_days"]) == row["games_left"]
        days = [dt.date.fromisoformat(d) for d in row["game_days"]]
        assert all(session.calendar.plays(pk.player.pro_team_id, session.calendar.period_of(d))
                   for d in days)
        if days:
            assert days[0] >= dt.date.fromisoformat(row["best_pickup_day"])


# --- the app -----------------------------------------------------------------------------------

def test_app_trash_screen_redraws_on_theme_change_and_keeps_the_menu_keys():
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(140, 44)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("f")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.current == "trash"
            width = app._width()
            out, colors = render(app.query_one("#body", Static).content, width)
            assert out.startswith("Best trash") and DARK.accent in colors
            assert max(cell_len(x.rstrip()) for x in out.splitlines()) <= width
            await pilot.press("ctrl+t")
            await pilot.pause()
            _, colors = render(app.query_one("#body", Static).content, width)
            assert LIGHT.accent in colors and DARK.accent not in colors
            await pilot.press("s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.current != "trash"

    asyncio.run(run())

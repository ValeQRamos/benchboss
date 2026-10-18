"""The pixel ball, checked at every width (1.0.4).

In 1.0.2 the top-left corner of the app drew a 4x2 pixel ball in one text row, and it looked
squashed. Since 1.0.3 the top bar shows a round glyph and the dashboard header the 15x15
ball (15 cells, 8 rows). These tests keep it whole: never cut, never squeezed, and simply
left out when the screen is too narrow for it.
"""

import asyncio
import io

import pytest
from rich.console import Console
from textual.widgets import Static

from benchboss.config import Config
from benchboss.ui import dashboard, logo
from benchboss.ui.app import Benchboss
from benchboss.ui.theme import DARK, LIGHT

HALF_BLOCKS = set("▀▄")


def lines_of(renderable, width: int) -> list[str]:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text().splitlines()


def ball_rows(pal) -> list[str]:
    return logo.ball(pal).plain.split("\n")


def find_ball(lines: list[str], rows: list[str]) -> tuple[int, int] | None:
    """(row, column) where the ball's 8 rows sit one under the other, else None."""
    for r, line in enumerate(lines):
        col = line.find(rows[0])
        while col >= 0:
            below = lines[r:r + len(rows)]
            if len(below) == len(rows) and all(x[col:col + len(y)] == y for x, y in zip(below, rows, strict=True)):
                return r, col
            col = line.find(rows[0], col + 1)
    return None


@pytest.fixture(scope="module")
def dash():
    from benchboss.demo import demo_session

    return dashboard.collect(demo_session())


@pytest.mark.parametrize("pal", [DARK, LIGHT], ids=["dark", "light"])
@pytest.mark.parametrize("width", [72, 73, 80, 91, 92, 120, 149, 150, 200, 260])
def test_header_ball_is_whole_at_every_width_from_the_minimum(dash, pal, width):
    assert width >= dashboard.LOGO_MIN
    lines = lines_of(dashboard.header(dash, pal, width), width)
    rows = ball_rows(pal)
    assert len(rows) == logo.BALL_HEIGHT
    # the ball's rows are the header's first rows, flush left, cell for cell
    assert [line[:logo.BALL_WIDTH] for line in lines[:logo.BALL_HEIGHT]] == rows
    assert all(len(line) <= width for line in lines)
    assert dash.league.me.name.upper() in "\n".join(lines)


@pytest.mark.parametrize("pal", [DARK, LIGHT], ids=["dark", "light"])
def test_header_ball_is_whole_or_absent_at_every_single_width(dash, pal):
    """Every width from 20 to 260, not just the usual ones: the ball is cell for cell
    logo.ball() from LOGO_MIN up, and gone below it; no line is ever wider than the screen."""
    rows = ball_rows(pal)
    for width in range(20, 261):
        lines = lines_of(dashboard.header(dash, pal, width), width)
        assert all(len(line) <= width for line in lines), width
        if width >= dashboard.LOGO_MIN:
            assert [line[:logo.BALL_WIDTH] for line in lines[:logo.BALL_HEIGHT]] == rows, width
        else:
            assert not HALF_BLOCKS & set("\n".join(lines)), width


@pytest.mark.parametrize("width", [40, 46, 60, 71])
def test_header_drops_the_ball_below_the_minimum(dash, width):
    assert width < dashboard.LOGO_MIN
    text = "\n".join(lines_of(dashboard.header(dash, DARK, width), width))
    assert not HALF_BLOCKS & set(text) and "█" not in text
    assert dash.league.me.name.upper()[:10] in text  # the team is still there


def test_the_top_bar_mark_is_one_round_cell():
    mark = logo.mark(DARK)
    assert mark.plain == logo.MARK == "●" and mark.cell_len == 1
    # not the 1.0.2 row of half blocks
    assert not HALF_BLOCKS & set(mark.plain)


async def _screen_lines(app) -> list[str]:
    await app.workers.wait_for_complete()
    for _ in range(3):
        await asyncio.sleep(0.05)
    strips = app.screen._compositor.render_strips()
    return [strip.text for strip in strips]


@pytest.mark.parametrize("size", [(120, 40), (150, 54)])
def test_app_ball_is_whole_with_and_without_the_menu(size):
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=size) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            rows = ball_rows(app.pal)
            assert not app.query_one("#menu").has_class("hidden")
            with_menu = find_ball(await _screen_lines(app), rows)
            await pilot.press("m")
            await pilot.pause()
            assert app.query_one("#menu").has_class("hidden")
            without = find_ball(await _screen_lines(app), rows)
            assert with_menu is not None and without is not None
            # the same rows; only the menu's width moves it right
            assert with_menu[0] == without[0] and with_menu[1] > without[1]
            top = app.query_one("#top", Static).content
            assert logo.MARK in top.plain and not HALF_BLOCKS & set(top.plain)

    asyncio.run(run())


def test_app_leaves_the_ball_out_on_a_narrow_window():
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(60, 40)) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            lines = await _screen_lines(app)
            assert find_ball(lines, ball_rows(app.pal)) is None
            assert not any(ball_rows(app.pal)[3] in line for line in lines)

    asyncio.run(run())

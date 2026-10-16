"""1.0.2: the pixel ball, the bigger news card, the dashboard header and the week view."""

import asyncio
import datetime as dt
import importlib.util
import io
import re
import struct
import zlib
from pathlib import Path

import pytest
from rich.cells import cell_len
from rich.console import Console
from textual.widgets import Static

from benchboss.config import Config
from benchboss.core.lineup import DayPlan
from benchboss.news import NewsItem
from benchboss.service import periods_for
from benchboss.ui import dashboard, logo, views
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import plan as plan_screen
from benchboss.ui.theme import DARK, LIGHT

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = [46, 80, 120, 160]
# emoji and pictographs; ★ (U+2605) is one of the glyphs the app uses on purpose
EMOJI = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in
                                  ((0x1F000, 0x1FFFF), (0x2600, 0x2604), (0x2606, 0x27BF))) + "]")


def text_of(renderable, width: int) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def fits(text: str, width: int) -> bool:
    return max(cell_len(line.rstrip()) for line in text.splitlines()) <= width


# --- the pixel ball ---------------------------------------------------------------------------

@pytest.mark.parametrize("pal", [DARK, LIGHT])
def test_logo_sizes_and_blocks(pal):
    ball = logo.ball(pal)
    lines = ball.plain.split("\n")
    assert len(lines) == logo.BALL_HEIGHT == 5
    assert {cell_len(x) for x in lines} == {logo.BALL_WIDTH}
    assert 10 <= logo.BALL_WIDTH <= 11
    mark = logo.mark(pal)
    assert "\n" not in mark.plain and 3 <= cell_len(mark.plain) <= 4
    for t in (ball, mark):
        assert set(t.plain) <= {" ", "▀", "▄", "█", "\n"}
    assert pal.accent in logo.colors(pal).values()


@pytest.mark.parametrize("design", [logo.BALL, logo.MARK])
def test_logo_leaves_the_background_alone_outside_the_ball(design):
    out = logo.draw(design, DARK)
    rows = list(design) + (["." * len(design[0])] if len(design) % 2 else [])
    styles = []
    for i, ch in enumerate(out.plain):
        if ch != "\n":
            styles.append(out.get_style_at_offset(Console(), i))
    pairs = [(rows[r][c], rows[r + 1][c]) for r in range(0, len(rows), 2) for c in range(len(rows[0]))]
    assert len(pairs) == len(styles)
    for (top, bottom), style in zip(pairs, styles, strict=True):
        if "." in (top, bottom):
            assert style.bgcolor is None
        if top == bottom == ".":
            assert style.color is None


def test_top_bar_has_the_pixel_mark_and_no_emoji():
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            top = app.query_one("#top", Static).content
            assert logo.mark(app.pal).plain in top.plain
            assert "benchboss" in top.plain and not EMOJI.search(top.plain)

    asyncio.run(run())


def test_make_logo_writes_the_committed_png(tmp_path):
    spec = importlib.util.spec_from_file_location("make_logo", ROOT / "tools" / "make_logo.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    data = tool.png(tool.rgba(logo.BALL, 16))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, depth, kind = struct.unpack(">IIBB", data[16:26])
    assert (width, height, depth, kind) == (16 * logo.BALL_WIDTH, 16 * len(logo.BALL), 8, 6)
    raw = zlib.decompress(data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8])
    assert raw[1:5] == b"\x00\x00\x00\x00"  # the top left corner is transparent
    assert (ROOT / "docs" / "images" / "logo.png").read_bytes() == data


# --- the dashboard ------------------------------------------------------------------------------

LONG = ("ZQ{i} is listed as questionable for Thursday's game against Boston because of a sore "
        "left ankle, and the team plans to update his status after the morning shootaround once "
        "the medical staff has looked at him again, which usually happens about two hours before "
        "the opening tip in this building END{i}")
SPIN = "SPIN{i} He tweaked the ankle in the third quarter but returned."


@pytest.fixture
def busy(session):
    """The demo league with ten news items (two about watch-list free agents) and odds."""
    raw = session.data["league"]
    me = next(t for t in raw["teams"] if t["id"] == session.data["my_team_id"])
    fa = [p["id"] for p in session.data["free_agents"][:2]]
    me["watchList"] = fa
    me["currentSimulationResults"] = {"playoffPct": 0.64}
    roster = [s.player for s in session.league(refresh=True).me.roster]
    names = {p.id: p.name for p in roster}
    names.update({x["id"]: x["player"]["fullName"] for x in session.data["free_agents"][:2]})
    people = [roster[0].id, fa[0], roster[1].id, roster[2].id, fa[1]] + [p.id for p in roster[3:8]]
    now = dt.datetime.combine(session.today, dt.time(19), tzinfo=dt.timezone.utc)

    def news(ids, days=5):
        items = [NewsItem(i, now - dt.timedelta(hours=2 + 5 * i),
                          f"{names[pid].split()[-1]} " + LONG.format(i=i), SPIN.format(i=i),
                          "Demo", "Rotowire", "", {pid})
                 for i, pid in enumerate(people) if pid in ids]
        assert days == dashboard.NEWS_DAYS
        return items

    session.news = news
    return session


@pytest.mark.parametrize("width,count", [(46, 4), (120, 8), (160, 8)])
def test_news_count_and_wrapping(busy, width, count):
    d = dashboard.collect(busy)
    assert len(d.news) == dashboard.NEWS_MAX
    out = text_of(dashboard.render(d, DARK, width), width)
    assert fits(out, width)
    shown = sorted({int(x) for x in re.findall(r"ZQ(\d+)", out)})
    assert shown == list(range(count))
    # a long headline wraps to two lines and then stops with an ellipsis
    first = out.splitlines().index(next(x for x in out.splitlines() if "ZQ0" in x))
    assert "…" in "\n".join(out.splitlines()[first:first + 2]) or "END0" in out
    assert "END0" not in out if width < 160 else True
    # the spin shows under the headline only when the news card spans the screen
    assert ("SPIN0" in out) == (width >= dashboard.WIDE)


def test_news_spans_the_full_width_on_wide_layouts(busy):
    out = text_of(dashboard.render(dashboard.collect(busy), DARK, 120), 120)
    news_top = next(x for x in out.splitlines() if "LATEST NEWS" in x)
    assert news_top.startswith("╭") and cell_len(news_top.rstrip()) == 120


def test_watch_list_news_gets_a_dim_star(busy):
    d = dashboard.collect(busy)
    assert d.watch and all(i in d.names for i in d.watch)
    card = dashboard.news_card(d, DARK, limit=8)
    out = text_of(card, 120)
    starred = [x for x in out.splitlines() if "★" in x]
    assert len(starred) == 2 and "ZQ1" in starred[0] and "ZQ4" in starred[1]
    assert all("★" not in x for x in out.splitlines() if "ZQ0" in x)
    assert "watch list" in text_of(dashboard.render(d, DARK, 120), 120)
    flags = [n["watch_list"] for n in d.to_dict()["news"]]
    assert flags.count(True) == 2


def test_header_has_logo_odds_and_clock(busy):
    d = dashboard.collect(busy)
    wide = text_of(dashboard.header(d, DARK, 120), 120)
    assert "64% playoff odds" in wide and "3:30 pm" in wide and "2nd of 10" in wide
    assert logo.ball(DARK).plain.split("\n")[0] in wide
    narrow = text_of(dashboard.header(d, DARK, 46), 46)
    assert "▄██" not in narrow and "MONSTARS" in narrow and fits(narrow, 46)
    d.league.me.playoff_pct = None
    assert "playoff odds" not in text_of(dashboard.header(d, DARK, 120), 120)
    data = d.to_dict()
    assert data["place"] == 2 and "playoff_pct" in data


def test_dashboard_without_news_or_watch_list(session):
    d = dashboard.collect(session)
    assert d.watch == set() and len(d.news) <= dashboard.NEWS_MAX
    d.news = []
    for width in WIDTHS:
        out = text_of(dashboard.render(d, DARK, width), width)
        assert fits(out, width) and "LATEST NEWS" not in out and "★" not in out


@pytest.mark.parametrize("width", [92, 120, 149, 150, 200])
def test_columns_stay_inside_the_width_and_keep_the_matchup_first(session, width):
    out = text_of(dashboard.render(dashboard.collect(session), DARK, width), width)
    assert fits(out, width)
    lines = out.splitlines()
    week = next(i for i, x in enumerate(lines) if "WEEK 3" in x)
    roster = next(i for i, x in enumerate(lines) if "ROSTER" in x)
    assert lines[week].startswith("╭") and week < roster


# --- the week view ------------------------------------------------------------------------------

def week_plans(session):
    periods = [p for p in periods_for(session, "week") if p >= session.league().scoring_period]
    return session.plan_days(periods)


def test_plan_explains_the_injury_discount(session):
    out = text_of(views.plan(week_plans(session), session.calendar, DARK, 120), 120)
    assert "Coby White     DTD: 32.9 × 75% = 24.7, below Scotty Pippen Jr. 30.6" in out
    assert "Pascal Siakam       BE → PF   41.1" in out
    assert out.splitlines()[0].startswith("18 moves on 4 of 5 days")
    assert "Thu Nov 5   no games for your players" in out
    assert "No game" in out and "Lineup" in out and "Bench" in out


def test_plan_narrow_splits_the_reason_and_fits(session):
    plans = week_plans(session)
    out = text_of(views.plan(plans, session.calendar, DARK, 46), 46)
    assert fits(out, 46)
    lines = out.splitlines()
    i = next(n for n, x in enumerate(lines) if "C. White" in x and "DTD" in x)
    assert "24.7" in lines[i] and "below S. Pippen Jr. 30.6" in lines[i + 1]


@pytest.mark.parametrize("width", WIDTHS)
def test_plan_without_a_width_fits_the_console(session, width):
    out = text_of(views.plan(week_plans(session), session.calendar, DARK), width)
    assert fits(out, width) and "Wed Nov 4" in out


def test_one_quiet_day_and_no_moves(session):
    plans = week_plans(session)
    quiet = [p for p in plans if not p.changed]
    assert quiet
    out = text_of(views.plan(quiet, session.calendar, DARK, 100), 100)
    assert out.startswith("No moves needed")
    gain = plan_screen.gain(DayPlan(1), session.calendar)
    assert gain == 0.0


def test_gain_is_the_points_the_moves_add(session):
    wed = week_plans(session)[0]
    values = {p.id: v for p, _, v in wed.starters}
    ins = sum(values[m.player.id] for m in wed.moves if m.from_slot == 12)
    assert plan_screen.gain(wed, session.calendar) < ins
    assert plan_screen.gain(wed, session.calendar) > 0


def test_plan_screen_title_in_the_app(session):
    app = Benchboss(Config(), demo=True, session=session)
    draw, pending = app._build("week")
    out = text_of(draw(DARK, 110), 110)
    assert out.startswith("Optimize") and "Wed Nov 4 to Sun Nov 8" in out.splitlines()[0]
    assert pending and "Press Apply" in out
    draw, _ = app._build("today")
    assert "Optimize  ·  Today  ·  Wed Nov 4" in text_of(draw(DARK, 110), 110)


# --- both themes, every width ---------------------------------------------------------------------

@pytest.mark.parametrize("pal", [DARK, LIGHT])
@pytest.mark.parametrize("width", WIDTHS)
def test_both_themes_render_cleanly(busy, pal, width):
    d = dashboard.collect(busy)
    board = text_of(dashboard.render(d, pal, width), width)
    week = text_of(views.plan(week_plans(busy), busy.calendar, pal, width), width)
    for out in (board, week):
        assert fits(out, width) and not EMOJI.search(out)
    console = Console(width=width, record=True, file=io.StringIO(), color_system="truecolor")
    console.print(dashboard.render(d, pal, width))
    html = console.export_html(inline_styles=True)
    assert pal.accent.lower() in html.lower()

"""The dashboard: one screen with everything that matters this week.

``collect`` talks to ESPN (each section fails on its own, so one bad call never blanks the
screen) and ``render`` turns the result into Rich renderables that adapt to the width: a
single column for a narrow side panel, two or three columns on a wide terminal with the news
across the bottom.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from itertools import product

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Table
from rich.text import Text

from benchboss.core.activity import Activity, most_and_least
from benchboss.core.projection import MatchupOutlook
from benchboss.core.trash import TrashPick
from benchboss.errors import BenchbossError
from benchboss.espn.constants import BENCH, IR
from benchboss.espn.models import League, Player
from benchboss.inbox import Alert
from benchboss.text import surname
from benchboss.ui import logo
from benchboss.ui.common import day_label, meter, odds_color, pct, player_cell, rost_cell
from benchboss.ui.theme import Palette

NEWS_DAYS = 3     # how far back the news card looks
NEWS_MAX = 8      # items on a wide screen; the side panel shows fewer
WIDE = 92         # from here on the cards sit side by side and the news spans the bottom
THREE = 150       # from here on there are three columns
LOGO_MIN = 72     # narrower than this the header drops the pixel ball
LOGO_GAP = 4      # columns between the ball and the team name


@dataclass
class Dashboard:
    league: League
    today: dt.date
    now: dt.datetime
    today_period: int
    week: tuple[dt.date, dt.date] | None = None
    days_to_start: int = 0
    in_season: bool = True    # today is a day of the NBA regular season
    outlook: MatchupOutlook | None = None
    activity: list[Activity] = field(default_factory=list)
    trash: list[TrashPick] = field(default_factory=list)
    trending: list[Player] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    news: list = field(default_factory=list)
    plays_today: set[int] = field(default_factory=set)
    opponents_today: dict[int, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    calendar: object = None
    watch: set[int] = field(default_factory=set)      # watch list ids that are not on the roster
    names: dict[int, str] = field(default_factory=dict)  # player id -> name, for the news

    def place(self) -> int | None:
        return next((i + 1 for i, t in enumerate(self.league.standings())
                     if t.id == self.league.my_team_id), None)

    def watched(self, item) -> bool:
        """A news item about a watch-list player and none of yours (it gets the star)."""
        mine = {s.player.id for s in self.league.me.roster}
        return bool(item.player_ids & self.watch) and not item.player_ids & mine

    def to_dict(self) -> dict:
        me = self.league.me
        names = {**self.names, **{s.player.id: s.player.name for s in me.roster}}
        return {
            "team": me.name, "league": self.league.name, "record": me.record,
            "place": self.place(), "playoff_pct": me.playoff_pct,
            "date": self.today.isoformat(),
            "week": [d.isoformat() for d in self.week] if self.week else None,
            "matchup": self.outlook.to_dict() if self.outlook else None,
            "roster": [{"slot": s.slot, "plays_today": s.player.id in self.plays_today,
                        **s.player.to_dict()} for s in me.roster],
            "activity": [a.to_dict() for a in self.activity],
            "trash": [t.to_dict(self.calendar) for t in self.trash],
            "trending": [p.to_dict() for p in self.trending],
            "alerts": [a.to_dict() for a in self.alerts],
            "news": [{**n.to_dict(names), "watch_list": self.watched(n)} for n in self.news],
            "standings": [{"rank": i + 1, "team": t.name, "record": t.record,
                           "points_for": round(t.points_for, 1)}
                          for i, t in enumerate(self.league.standings())],
            "errors": self.errors,
        }


def _try(d: Dashboard, label: str, fn, default):
    try:
        return fn()
    except BenchbossError as e:
        d.errors.append(f"{label}: {e}")
    except Exception as e:  # keep the screen alive whatever happens
        d.errors.append(f"{label}: {type(e).__name__}: {e}")
    return default


def collect(session, with_trash: bool = True, with_alerts: bool = True,
            with_trending: bool = True, with_news: bool = True) -> Dashboard:
    league = session.league(refresh=True)
    cal = session.calendar
    d = Dashboard(league, session.today, session.now, session.today_period, calendar=cal)
    periods = _try(d, "schedule", session.matchup_periods, [])
    if periods:
        d.week = (cal.date_of(periods[0]), cal.date_of(periods[-1]))
    d.days_to_start = max(0, (cal.day_one - session.today).days)
    d.outlook = _try(d, "matchup", session.outlook, None)
    d.activity = _try(d, "activity", session.activity, [])
    d.in_season = session.in_season
    day = cal.period_of(session.today)  # not clamped: before or after the season nobody plays
    for s in league.me.roster if d.in_season else ():
        g = cal.game(s.player.pro_team_id, day)
        if g:
            d.plays_today.add(s.player.id)
            d.opponents_today[s.player.id] = g.opponent(s.player.pro_team_id)
    if with_trash:
        d.trash = _try(d, "trash", lambda: session.trash(n=3), [])
    if with_trending:
        d.trending = _try(d, "trending", lambda: session.trending(3), [])
    if with_news:
        _collect_news(d, session)
    if with_alerts:
        from benchboss import inbox

        # spins stay out of the inbox card: the news card already shows them, starred
        d.alerts = _try(d, "alerts", lambda: inbox.alerts(session, include_spins=False), [])
    return d


def _collect_news(d: Dashboard, session) -> None:
    """News on the roster and on the watch list, newest first, NEWS_MAX at most."""
    mine = [s.player.id for s in d.league.me.roster]
    d.watch = {i for i in d.league.me.watch_list if i not in set(mine)}
    ids = mine + sorted(d.watch)
    d.news = _try(d, "news", lambda: session.news(ids, NEWS_DAYS)[:NEWS_MAX], [])
    d.names = {s.player.id: s.player.name for t in d.league.teams.values() for s in t.roster}
    missing = {i for n in d.news for i in n.player_ids if i in d.watch and i not in d.names}
    if missing:  # watch-list free agents: one more read for their names
        pool = _try(d, "watch list", lambda: session.player_pool("watch"), [])
        d.names.update({p.id: p.name for p in pool})


# --- rendering ------------------------------------------------------------------------------------

def _panel(body: RenderableType, title: str, pal: Palette, note: str = "") -> Panel:
    return Panel(body, title=f"[bold {pal.dim}] {title} [/]", title_align="left",
                 subtitle=f"[{pal.dim}] {note} [/]" if note else None, subtitle_align="right",
                 box=box.ROUNDED, border_style=pal.border, padding=(0, 1), expand=True)


def _ordinal(n) -> str:
    if not isinstance(n, int):
        return str(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _dot(pal: Palette) -> tuple[str, str]:
    return ("  ·  ", pal.border)


def header(d: Dashboard, pal: Palette, width: int = 120) -> RenderableType:
    """The pixel ball (when it fits), then the team, the league, the record and the clock."""
    me = d.league.me
    teams = len(d.league.teams)
    place = d.place()
    clock = f"{d.now:%I:%M %p}".lstrip("0").lower()
    info = Table.grid(expand=True, padding=(0, 2))
    info.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    info.add_column(justify="right", no_wrap=True)
    info.add_row(Text(me.name.upper(), style=f"bold {pal.accent}"), Text(clock, style=f"bold {pal.text}"))
    info.add_row(Text(d.league.name, style=pal.dim), Text(day_label(d.today), style=pal.dim))
    # the clock column (and the 2 spaces before it) sits on the right of every row, so this
    # line gets what is left
    room = (width - (logo.BALL_WIDTH + LOGO_GAP if width >= LOGO_MIN else 0)
            - max(len(clock), len(day_label(d.today))) - 2)
    dot = _dot(pal) if room >= 60 else (" · ", pal.border)
    line = Text(me.record, style=pal.text)
    extras = [(f"{_ordinal(place)} of {teams}", pal.text) if place else None,
              (f"projected {_ordinal(me.projected_rank)}", pal.dim) if me.projected_rank else None,
              (f"streak {me.streak}", pal.dim) if me.streak else None]
    for part in filter(None, extras):  # whatever does not fit is left out, never cut
        piece = Text.assemble(dot, part)
        if line.cell_len + piece.cell_len > room:
            break
        line.append_text(piece)
    info.add_row(line, "")
    if me.playoff_pct is not None:  # ESPN's number; the Playoff race (y) runs its own
        odds = me.playoff_pct
        color = odds_color(odds, pal)
        line = Text.assemble((pct(odds), color), (" ESPN playoff odds", pal.dim))
        bar = min(12, room - line.cell_len - 2)
        if bar >= 4:  # a shorter bar when the line is short of room, none rather than a stub
            line.append("  ")
            line.append_text(meter(odds, bar, pal, color))
        info.add_row(line, "")
    if width < LOGO_MIN:
        return info
    outer = Table.grid(expand=True, padding=(0, LOGO_GAP, 0, 0))
    outer.add_column(width=logo.BALL_WIDTH, no_wrap=True)
    outer.add_column(ratio=1, vertical="middle")
    outer.add_row(logo.ball(pal), info)
    return outer


def matchup_card(d: Dashboard, pal: Palette) -> Panel:
    rows: list[RenderableType] = []
    o = d.outlook
    note = f"{day_label(d.week[0])} to {day_label(d.week[1])}" if d.week else ""
    if d.days_to_start:
        rows.append(Text(f"Season tips off in {d.days_to_start} day{'s' * (d.days_to_start != 1)}",
                         style=pal.accent))
    if o and o.opponent:
        me, op = o.me, o.opponent
        board = Table.grid(expand=True, padding=(0, 0, 0, 2))
        board.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        board.add_column(justify="right", no_wrap=True)
        board.add_column(justify="right", no_wrap=True)
        board.add_column(justify="right", no_wrap=True)
        board.add_row("", Text("Score", style=pal.dim), Text("Proj.", style=pal.dim),
                      Text("Left", style=pal.dim))
        score = pal.good if me.points > op.points else pal.bad if me.points < op.points else pal.text
        board.add_row(Text(me.team.name, style=pal.accent),
                      Text(f"{me.points:,.1f}", style=f"bold {score}"),
                      Text(f"{me.projected:,.0f}", style=pal.text), Text(str(me.games_left), style=pal.text))
        board.add_row(Text(op.team.name, style=pal.text), Text(f"{op.points:,.1f}", style=pal.text),
                      Text(f"{op.projected:,.0f}", style=pal.dim), Text(str(op.games_left), style=pal.dim))
        rows.append(board)
        total = me.points + op.points
        share = me.points / total if total else 0.5
        bar = Table.grid(expand=True)
        bar.add_column(ratio=max(1, round(share * 100)))
        bar.add_column(ratio=max(1, round((1 - share) * 100)))
        lead = pal.good if me.points > op.points else pal.bad if me.points < op.points else pal.dim
        bar.add_row(Text("━" * 200, style=lead, overflow="crop", no_wrap=True),
                    Text("━" * 200, style=pal.border, overflow="crop", no_wrap=True))
        rows.append(bar)
        rows.append(_verdict(me.points - op.points, me.projected - op.projected, pal))
    elif o:
        rows.append(Text("No opponent this week (bye or playoffs)", style=pal.dim))
    title = f"WEEK {o.matchup_id}" if o else "THIS WEEK"
    return _panel(Group(*rows) if rows else Text("-", style=pal.dim), title, pal, note)


def _verdict(now: float, final: float, pal: Palette) -> Text:
    """ "Up 18.2 now, projected to lose by 114": the score in plain words."""
    out = Text()
    if abs(now) < 0.05:
        out.append("Tied now", style=pal.text)
    else:
        out.append(f"{'Up' if now > 0 else 'Down'} {abs(now):,.1f}", style=pal.good if now > 0 else pal.bad)
        out.append(" now", style=pal.dim)
    out.append(", projected to ", style=pal.dim)
    if abs(final) < 0.5:
        out.append("finish even", style=pal.text)
    else:
        out.append(f"{'win' if final > 0 else 'lose'} by {abs(final):,.0f}",
                   style=pal.good if final > 0 else pal.bad)
    return out


def roster_card(d: Dashboard, pal: Palette) -> Panel:
    me = d.league.me
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(no_wrap=True, width=2)
    t.add_column(no_wrap=True, width=1)
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    t.add_column(no_wrap=True, width=5, justify="right")
    order = sorted(me.roster, key=lambda s: (s.slot_id + 100 if s.slot_id in (BENCH, IR) else s.slot_id,
                                             -s.player.proj))
    playing = 0
    for s in order:
        p = s.player
        bench = not s.is_starting
        today = p.id in d.plays_today
        playing += today and not bench
        t.add_row(Text(s.slot, style=pal.dim), Text("●" if today else " ", style=pal.good),
                  player_cell(p, pal, short=True, style=pal.dim if bench else pal.text),
                  Text(f"{p.proj:.1f}" if p.proj else "", style=pal.dim if bench else pal.text))
    note = f"{playing} play today" if d.in_season else "proj. pts"
    return _panel(t, "ROSTER", pal, note)


def activity_card(d: Dashboard, pal: Palette, n: int = 3) -> Panel:
    if not d.activity:
        return _panel(Text("No schedule yet", style=pal.dim), "WORKLOAD THIS WEEK", pal)
    most, least = most_and_least(d.activity, n)
    if most[0].games == least[0].games:
        n_games = most[0].games
        return _panel(Text(f"Everyone on your roster plays {n_games} game{'s' * (n_games != 1)}",
                           style=pal.text), "WORKLOAD THIS WEEK", pal)
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    t.add_column(no_wrap=True, justify="right")

    def rows(title, acts, color):
        t.add_row(Text(title, style=f"bold {color}"), "")
        for a in acts:
            left = f" ({a.games_left} left)" if a.games_left != a.games else ""
            t.add_row(Text.assemble((a.player.short_name, pal.text), (f" {a.player.pro_team}", pal.dim)),
                      Text.assemble((f"{a.games} games", color), (left, pal.dim)))

    rows("Most games", most, pal.good)
    rows("Fewest games", least, pal.warn)
    return _panel(t, "WORKLOAD THIS WEEK", pal)


def standings_card(d: Dashboard, pal: Palette) -> Panel:
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(width=2, justify="right", style=pal.dim)
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    t.add_column(no_wrap=True, justify="right", style=pal.dim)
    for i, team in enumerate(d.league.standings()):
        mine = team.id == d.league.my_team_id
        t.add_row(str(i + 1), Text(team.name, style=f"bold {pal.accent}" if mine else pal.text),
                  team.record)
    return _panel(t, "LEAGUE", pal)


def trash_card(d: Dashboard, pal: Palette) -> Panel | None:
    picks = [pick for pick in d.trash if round(pick.net) > 0]  # late on Sunday nobody helps
    if not picks:
        return None
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    t.add_column(no_wrap=True, justify="right")
    for pick in picks:
        p = pick.player
        label = Text.assemble((p.short_name, pal.text), (f" {p.pro_team}", pal.dim),
                              (" (W)" if pick.on_waivers else "", pal.warn))
        t.add_row(label,
                  Text.assemble((f"{pick.net:+.0f} pts", f"bold {pal.good}"),
                                (f" · {pick.games_left} game{'' if pick.games_left == 1 else 's'}", pal.dim)))
    return _panel(t, "BEST TRASH THIS WEEK", pal, "points added if you grab him")


def trending_card(d: Dashboard, pal: Palette) -> Panel | None:
    if not d.trending:
        return None
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    t.add_column(no_wrap=True, justify="right")
    for p in d.trending:
        t.add_row(Text.assemble((p.short_name, pal.text), (f" {p.pro_team}", pal.dim)),
                  rost_cell(p, pal))
    return _panel(t, "RISING ON WAIVERS", pal, "% rostered, change in a week")


def alerts_card(d: Dashboard, pal: Palette) -> Panel | None:
    if not d.alerts:
        return None
    rows = [Text.assemble(("● " if a.urgent else "· ", pal.accent if a.urgent else pal.dim),
                          (a.text, pal.text)) for a in d.alerts]
    return _panel(Group(*rows), "INBOX", pal)


# --- news -----------------------------------------------------------------------------------------

class Clamp:
    """Text wrapped to the width it is given and cut to ``lines`` lines, the last one ending
    in an ellipsis when something was left out."""

    def __init__(self, text: Text, lines: int = 2):
        self.text = text
        self.lines = max(1, lines)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = max(1, options.max_width)
        wrapped = list(self.text.wrap(console, width, overflow="fold"))
        if len(wrapped) > self.lines:
            wrapped = wrapped[: self.lines]
            last = wrapped[-1]
            last.rstrip()
            if last.cell_len > width - 1:
                last.truncate(width - 1)
                last.rstrip()
            last.append("…", style=self.text.style)
        for line in wrapped:
            line.end = "\n"
            yield line

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, options, self.text)


def _ago(now: dt.datetime, then: dt.datetime) -> str:
    minutes = max(0, int((now - then).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h" if hours < 48 else f"{hours // 24}d"


def _short(name: str) -> str:
    parts = name.split()
    return name if len(parts) < 2 else f"{parts[0][0]}. {' '.join(parts[1:])}"


def news_limit(width: int) -> int:
    """How many news items fit: about 4 on the 46 column side panel, NEWS_MAX when wide."""
    return 4 if width < 60 else 6 if width < WIDE else NEWS_MAX


def news_card(d: Dashboard, pal: Palette, hint: str = "benchboss news for more", *,
              limit: int = NEWS_MAX, spin_lines: int = 0) -> Panel | None:
    """The latest news on your players (and your watch list, marked with a dim star).
    Headlines wrap to two lines at most; ``spin_lines`` > 0 adds the analysis under each."""
    if not d.news:
        return None
    names = {**d.names, **{s.player.id: s.player.name for s in d.league.me.roster}}
    items = d.news[:limit]
    starred = any(d.watched(n) for n in items)
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(no_wrap=True, justify="right", width=3)
    if starred:
        t.add_column(no_wrap=True, width=1)
    t.add_column(ratio=1)
    now = d.now.astimezone()
    for n in items:
        who = [_short(names[p]) for p in sorted(n.player_ids) if p in names]
        last = [surname(w) for w in who]
        headline = n.headline.strip()
        # RotoWire headlines start with the last name; only prefix when it is missing
        if who and not any(x in headline[:60] for x in last):
            line = Text.assemble((", ".join(who), "bold"), " ", headline, style=pal.text)
        else:
            line = Text(headline, style=pal.text)
            if last and headline.startswith(last[0]):
                line.stylize("bold", 0, len(last[0]))
        body: RenderableType = Clamp(line, 2)
        spin = " ".join((n.spin or "").split())
        if spin_lines and spin:
            body = Group(body, Clamp(Text(spin, style=pal.dim), spin_lines))
        cells: list[RenderableType] = [Text(_ago(now, n.published), style=pal.dim)]
        if starred:
            cells.append(Text("★" if d.watched(n) else " ", style=pal.dim))
        t.add_row(*cells, body)
    note = f"last {NEWS_DAYS} days · {hint}" if hint else f"last {NEWS_DAYS} days"
    return _panel(t, "LATEST NEWS", pal, note)


# --- the whole screen -----------------------------------------------------------------------------

class Columns:
    """Cards in side by side columns of about the same height.

    ``first`` always heads the first column. Every other card keeps its order but may land
    in any column: the split with the shortest tallest column wins (measured at render
    time, so it holds for whatever width the console gives). On a tie: leave the first
    column alone, then keep the cards in reading order (left to right), then even out the
    other columns.
    """

    def __init__(self, first: list[RenderableType], rest: list[RenderableType],
                 ratios: tuple[int, ...], gap: int = 1):
        self.first, self.rest, self.ratios, self.gap = first, rest, ratios, gap

    def widths(self, total: int) -> list[int]:
        avail = max(len(self.ratios), total - self.gap * (len(self.ratios) - 1))
        out = [avail * r // sum(self.ratios) for r in self.ratios]
        out[0] += avail - sum(out)
        return out

    def split(self, console: Console, options: ConsoleOptions) -> list[list[RenderableType]]:
        widths = self.widths(options.max_width)

        def tall(card, w: int) -> int:
            return len(console.render_lines(card, options.update(width=w, height=None), pad=False))

        n = len(widths)
        base = [sum(tall(c, widths[0]) for c in self.first)] + [0] * (n - 1)
        sizes = [[tall(c, w) for w in widths] for c in self.rest]
        best = None
        for pick in product(range(n), repeat=len(self.rest)):
            h = list(base)
            for card, col in enumerate(pick):
                h[col] += sizes[card][col]
            out_of_order = sum(1 for a, b in zip(pick, pick[1:], strict=False) if b < a)
            key = (max(h), sum(1 for col in pick if col == 0), out_of_order,
                   sum(x * x for x in h), pick)
            if best is None or key < best[0]:
                best = (key, pick)
        cols: list[list[RenderableType]] = [list(self.first)] + [[] for _ in range(n - 1)]
        for card, col in zip(self.rest, best[1] if best else (), strict=False):
            cols[col].append(card)
        return cols

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        widths = self.widths(options.max_width)
        cols = self.split(console, options)
        rendered = [console.render_lines(Group(*col), options.update(width=w, height=None), pad=True)
                    if col else [] for col, w in zip(cols, widths, strict=True)]
        height = max((len(r) for r in rendered), default=0)
        gap = Segment(" " * self.gap)
        for i in range(height):
            for j, (lines, w) in enumerate(zip(rendered, widths, strict=True)):
                if j:
                    yield gap
                if i < len(lines):
                    yield from lines[i]
                else:
                    yield Segment(" " * w)
            yield Segment.line()

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement(options.max_width, options.max_width)


def render(d: Dashboard, pal: Palette, width: int,
           news_hint: str = "benchboss news for more") -> RenderableType:
    """``news_hint`` is the subtitle of the news card: the app passes its own key for it."""
    wide = width >= WIDE
    limit = news_limit(width)
    news = news_card(d, pal, news_hint, limit=limit,
                     spin_lines=(2 if width >= 130 else 1) if wide else 0)
    left = [matchup_card(d, pal), roster_card(d, pal)]
    right = [c for c in (alerts_card(d, pal), activity_card(d, pal), None if wide else news,
                         trash_card(d, pal), trending_card(d, pal), standings_card(d, pal))
             if c is not None]
    parts: list[RenderableType] = [header(d, pal, width), Text("")]
    if not wide:
        parts += left + right
    else:
        parts.append(Columns(left, right, (5, 4, 4) if width >= THREE else (1, 1)))
        if news is not None:
            parts.append(news)
    for e in d.errors:
        parts.append(Text(e, style=pal.dim))
    starred = news is not None and any(d.watched(n) for n in d.news[:limit])
    parts.append(_footer(pal, width, starred))
    return Group(*parts)


def _footer(pal: Palette, width: int, watch: bool) -> Text:
    """The legend under the cards; items that do not fit the width are left out."""
    items = [(("● ", pal.good), ("plays today", pal.dim))]
    if watch:
        items.append((("★ ", pal.dim), ("watch list", pal.dim)))
    items.append((("proj", f"bold {pal.dim}"), (" ESPN projection per game", pal.dim)))
    out = Text()
    for item in items:
        piece = Text.assemble(*((_dot(pal),) if out else ()), *item)
        if out.cell_len + piece.cell_len > width:
            break
        out.append_text(piece)
    return out

"""The dashboard: one screen with everything that matters this week.

``collect`` talks to ESPN (each section fails on its own, so one bad call never blanks the
screen) and ``render`` turns the result into Rich renderables that adapt to the width: a
single column for a narrow side panel, two or three columns on a wide terminal.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from benchboss.core.activity import Activity, most_and_least
from benchboss.core.projection import MatchupOutlook
from benchboss.core.trash import TrashPick
from benchboss.errors import BenchbossError
from benchboss.espn.constants import BENCH, IR
from benchboss.espn.models import League, Player
from benchboss.inbox import Alert
from benchboss.ui.theme import Palette


@dataclass
class Dashboard:
    league: League
    today: dt.date
    now: dt.datetime
    today_period: int
    week: tuple[dt.date, dt.date] | None = None
    days_to_start: int = 0
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

    def to_dict(self) -> dict:
        me = self.league.me
        return {
            "team": me.name, "league": self.league.name, "record": me.record,
            "date": self.today.isoformat(),
            "week": [d.isoformat() for d in self.week] if self.week else None,
            "matchup": self.outlook.to_dict() if self.outlook else None,
            "roster": [{"slot": s.slot, "plays_today": s.player.id in self.plays_today,
                        **s.player.to_dict()} for s in me.roster],
            "activity": [a.to_dict() for a in self.activity],
            "trash": [t.to_dict(self.calendar) for t in self.trash],
            "trending": [p.to_dict() for p in self.trending],
            "alerts": [a.to_dict() for a in self.alerts],
            "news": [n.to_dict({s.player.id: s.player.name for s in me.roster}) for n in self.news],
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
    for s in league.me.roster:
        g = cal.game(s.player.pro_team_id, d.today_period) if d.days_to_start == 0 else None
        if g:
            d.plays_today.add(s.player.id)
            d.opponents_today[s.player.id] = g.opponent(s.player.pro_team_id)
    if with_trash:
        d.trash = _try(d, "trash", lambda: session.trash(n=3), [])
    if with_trending:
        d.trending = _try(d, "trending", lambda: session.trending(3), [])
    if with_news:
        ids = [s.player.id for s in league.me.roster]
        d.news = _try(d, "news", lambda: session.news(ids, 2)[:3], [])
    if with_alerts:
        from benchboss import inbox

        d.alerts = _try(d, "alerts", lambda: inbox.alerts(session), [])
    return d


# --- rendering ------------------------------------------------------------------------------------

def _panel(body: RenderableType, title: str, pal: Palette, note: str = "") -> Panel:
    return Panel(body, title=f"[bold {pal.dim}] {title} [/]", title_align="left",
                 subtitle=f"[{pal.dim}] {note} [/]" if note else None, subtitle_align="right",
                 box=box.ROUNDED, border_style=pal.border, padding=(0, 1), expand=True)


def _short_date(d: dt.date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def header(d: Dashboard, pal: Palette) -> RenderableType:
    me = d.league.me
    standings = d.league.standings()
    place = next((i + 1 for i, t in enumerate(standings) if t.id == me.id), "?")
    t = Table.grid(expand=True)
    t.add_column(ratio=1)
    t.add_column(justify="right")
    clock = f"{d.now:%I:%M %p}".lstrip("0").lower()
    t.add_row(Text(me.name.upper(), style=f"bold {pal.accent}"), Text(clock, style=f"bold {pal.text}"))
    t.add_row(Text(d.league.name, style=pal.dim), "")
    line = f"{me.record} · {_ordinal(place)} of {len(standings)}"
    if me.projected_rank:
        line += f" · projected {_ordinal(me.projected_rank)}"
    t.add_row(Text(line, style=pal.text), "")
    return t


def _ordinal(n) -> str:
    if not isinstance(n, int):
        return str(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def matchup_card(d: Dashboard, pal: Palette) -> Panel:
    rows: list[RenderableType] = []
    o = d.outlook
    if d.week:
        rows.append(Text(f"{_short_date(d.week[0])} to {_short_date(d.week[1])}", style=pal.dim))
    if d.days_to_start:
        rows.append(Text(f"Season tips off in {d.days_to_start} day{'s' * (d.days_to_start != 1)}",
                         style=pal.accent))
    if o and o.opponent:
        me, op = o.me, o.opponent
        rows.append(Text.assemble(("vs ", pal.text), (op.team.name, f"bold {pal.text}")))
        color = pal.good if me.points > op.points else pal.bad if me.points < op.points else pal.dim
        rows.append(Text.assemble((f"You {me.points:,.1f}", f"bold {color}"), ("  ·  ", pal.dim),
                                  (f"{op.points:,.1f} Them", pal.text)))
        total = me.points + op.points
        share = me.points / total if total else 0.5
        bar = Table.grid(expand=True)
        bar.add_column(ratio=max(1, round(share * 100)))
        bar.add_column(ratio=max(1, round((1 - share) * 100)))
        lead = pal.good if me.points >= op.points else pal.accent
        bar.add_row(Text("━" * 200, style=lead, overflow="crop", no_wrap=True),
                    Text("━" * 200, style=pal.border, overflow="crop", no_wrap=True))
        rows.append(bar)
        stats = Table.grid(expand=True, padding=(0, 1))
        stats.add_column(style=pal.dim, no_wrap=True)
        stats.add_column(justify="right", no_wrap=True)
        for label, a, b, fmt in (("proj. final", me.projected, op.projected, "{:,.0f}"),
                                 ("games left", me.games_left, op.games_left, "{}")):
            c = pal.good if a > b else pal.bad if a < b else pal.text
            stats.add_row(label, Text.assemble((f"you {fmt.format(a)}", f"bold {c}"), (" · ", pal.dim),
                                               (f"{fmt.format(b)} them", pal.text)))
        rows.append(Text(""))
        rows.append(stats)
    elif o:
        rows.append(Text("No opponent this week (bye or playoffs)", style=pal.dim))
    title = f"WEEK {o.matchup_id}" if o else "THIS WEEK"
    return _panel(Group(*rows) if rows else Text("-", style=pal.dim), title, pal)


def roster_card(d: Dashboard, pal: Palette) -> Panel:
    me = d.league.me
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(no_wrap=True, width=3)
    t.add_column(no_wrap=True, width=1)
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    t.add_column(no_wrap=True, width=3)
    t.add_column(no_wrap=True, width=4, justify="right")
    t.add_column(no_wrap=True, width=5, justify="right")
    order = sorted(me.roster, key=lambda s: (s.slot_id + 100 if s.slot_id in (BENCH, IR) else s.slot_id,
                                             -s.player.proj))
    playing = 0
    for s in order:
        p = s.player
        bench = not s.is_starting
        today = p.id in d.plays_today
        playing += today and not bench
        inj_color = pal.bad if p.injury in ("OUT", "SUSP", "IR") else pal.warn
        t.add_row(Text(s.slot, style=pal.dim), Text("●" if today else " ", style=pal.good),
                  Text(p.short_name, style=pal.dim if bench else pal.text),
                  Text(p.pro_team, style=pal.dim), Text(p.injury, style=inj_color),
                  Text(f"{p.proj:5.1f}" if p.proj else "", style=pal.dim if bench else pal.text))
    note = f"{playing} play today" if not d.days_to_start else "proj. pts"
    return _panel(t, "ROSTER", pal, note)


def activity_card(d: Dashboard, pal: Palette, n: int = 3) -> Panel:
    most, least = most_and_least(d.activity, n)
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    t.add_column(no_wrap=True, justify="right")

    def rows(title, acts, color):
        t.add_row(Text(title, style=f"bold {color}"), "")
        for a in acts:
            left = f" ({a.games_left} left)" if a.games_left != a.games else ""
            t.add_row(Text(f"{a.player.short_name} {a.player.pro_team}", style=pal.text),
                      Text.assemble((f"{a.games} games", f"bold {color}"), (left, pal.dim)))

    if not d.activity:
        return _panel(Text("No schedule yet", style=pal.dim), "WORKLOAD THIS WEEK", pal)
    if most[0].games == least[0].games:
        n_games = most[0].games
        return _panel(Text(f"Everyone on your roster plays {n_games} game{'s' * (n_games != 1)}",
                           style=pal.text), "WORKLOAD THIS WEEK", pal)
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
        label = f"{p.short_name} {p.pro_team}" + (" (W)" if pick.on_waivers else "")
        t.add_row(Text(label, style=pal.text),
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
        t.add_row(Text(f"{p.short_name} {p.pro_team}", style=pal.text),
                  Text(f"{p.owned_change:+.1f}%", style=pal.good if p.owned_change >= 0 else pal.bad))
    return _panel(t, "RISING ON WAIVERS", pal)


def alerts_card(d: Dashboard, pal: Palette) -> Panel | None:
    if not d.alerts:
        return None
    rows = [Text.assemble(("● " if a.urgent else "· ", pal.accent if a.urgent else pal.dim),
                          (a.text, pal.text)) for a in d.alerts]
    return _panel(Group(*rows), "INBOX", pal)


def news_card(d: Dashboard, pal: Palette, hint: str = "benchboss news for more") -> Panel | None:
    if not d.news:
        return None
    names = {s.player.id: s.player.short_name for s in d.league.me.roster}
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(no_wrap=True)
    t.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    now = d.now.astimezone() if d.now.tzinfo else d.now.astimezone()
    for n in d.news:
        hours = max(0, int((now - n.published).total_seconds() // 3600))
        ago = f"{hours}h" if hours < 48 else f"{hours // 24}d"
        who = [names.get(p, "?") for p in sorted(n.player_ids)]
        last = [w.split()[-1] for w in who]
        # RotoWire headlines start with the last name; only prefix when it is missing
        line = (Text(n.headline, style=pal.text) if any(x in n.headline[:60] for x in last)
                else Text.assemble((", ".join(who) + " ", f"bold {pal.text}"), (n.headline, pal.text)))
        if last and n.headline.startswith(last[0]):
            line.stylize("bold", 0, len(last[0]))
        t.add_row(Text(f"{ago:>3}", style=pal.dim), line)
    return _panel(t, "LATEST NEWS", pal, hint)


def render(d: Dashboard, pal: Palette, width: int,
           news_hint: str = "benchboss news for more") -> RenderableType:
    """``news_hint`` is the subtitle of the news card: the app passes its own key for it."""
    left = [matchup_card(d, pal), roster_card(d, pal)]
    right = [c for c in (alerts_card(d, pal), activity_card(d, pal), news_card(d, pal, news_hint),
                         trash_card(d, pal), trending_card(d, pal), standings_card(d, pal))
             if c is not None]
    footer = Text.assemble(("● ", pal.good), ("plays today · proj = ESPN projection", pal.dim))
    parts: list[RenderableType] = [header(d, pal), Text("")]
    if width < 92:
        parts += left + right
    else:
        grid = Table.grid(expand=True, padding=(0, 1))
        if width >= 150:
            third = [c for c in right if c is not None]
            mid, side = third[: len(third) // 2], third[len(third) // 2:]
            grid.add_column(ratio=5)
            grid.add_column(ratio=4)
            grid.add_column(ratio=4)
            grid.add_row(Group(*left), Group(*mid), Group(*side))
        else:
            grid.add_column(ratio=1)
            grid.add_column(ratio=1)
            grid.add_row(Group(*left), Group(*right))
        parts.append(grid)
    for e in d.errors:
        parts.append(Text(e, style=pal.dim))
    parts.append(footer)
    return Group(*parts)

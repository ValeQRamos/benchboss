"""Workload: games per player this matchup week, day by day."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType
from rich.text import Text

from benchboss.core.activity import Activity
from benchboss.core.calendar import SeasonCalendar
from benchboss.ui.common import table
from benchboss.ui.theme import Palette

TITLE = "Workload"
VIEWS: tuple[tuple[str, str], ...] = ()


@dataclass
class WorkloadData:
    acts: list[Activity]
    calendar: SeasonCalendar
    periods: list[int]
    today: int          # today's scoring period, NOT clamped: outside the season no day is today


def load(session) -> WorkloadData:
    return WorkloadData(session.activity(), session.calendar, session.matchup_periods(),
                        session.calendar.period_of(session.today))


def draw(data: WorkloadData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    return activity(data.acts, data.calendar, data.periods, data.today, pal)


def activity(acts: list[Activity], cal: SeasonCalendar, periods: list[int], today_period: int,
             pal: Palette) -> RenderableType:
    t = table(pal, "Games this matchup week")
    t.add_column("Player")
    t.add_column("G", justify="right")
    t.add_column("Left", justify="right")
    for sp in periods:
        d = cal.date_of(sp)
        head = f"{d:%a}\n{d.day}"
        t.add_column(head, justify="center", header_style=f"bold {pal.accent}" if sp == today_period else None)
    for a in acts:
        cells = []
        for sp, opp in zip(periods, a.schedule, strict=False):
            style = pal.dim if sp < today_period else pal.text
            cells.append(Text(opp.replace("vs ", "").replace("@ ", "@") if opp else "·",
                              style=style if opp else pal.border))
        color = pal.good if a.games >= 4 else pal.warn if a.games <= 2 else pal.text
        t.add_row(f"{a.player.name} ({a.player.pro_team})", Text(str(a.games), style=f"bold {color}"),
                  str(a.games_left), *cells)
    t.caption = "Opponent per day (@ = away). Volume wins in daily leagues: favor 4-game weeks."
    return t


def to_json(data: WorkloadData) -> list[dict]:
    return [a.to_dict() for a in data.acts]

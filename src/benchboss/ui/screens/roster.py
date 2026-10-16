"""Roster: your players with slots, injuries, averages and projections."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import RenderableType
from rich.text import Text

from benchboss.espn.constants import BENCH, IR
from benchboss.espn.models import League
from benchboss.ui.common import injury, num, table
from benchboss.ui.theme import Palette

TITLE = "Roster"
VIEWS: tuple[tuple[str, str], ...] = ()


@dataclass
class RosterData:
    league: League
    plays_today: set[int] = field(default_factory=set)


def load(session) -> RosterData:
    lg, cal = session.league(), session.calendar
    day = cal.period_of(session.today)  # not clamped: before or after the season nobody plays
    in_season = 1 <= day <= cal.final_period
    today = {s.player.id for s in lg.me.roster if in_season and cal.plays(s.player.pro_team_id, day)}
    return RosterData(lg, today)


def draw(data: RosterData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    me = data.league.me
    t = table(pal, f"{me.name}  ·  {me.record}")
    for col, kw in (("Slot", {}), ("Player", {}), ("Pos", {}), ("Team", {}), ("Inj", {}),
                    ("Avg", {"justify": "right"}), ("L15", {"justify": "right"}),
                    ("Proj", {"justify": "right"}), ("Today", {"justify": "center"})):
        t.add_column(col, **kw)
    order = sorted(me.roster, key=lambda s: (s.slot_id + 100 if s.slot_id in (BENCH, IR) else s.slot_id,
                                             -s.player.proj))
    for s in order:
        p = s.player
        style = pal.dim if not s.is_starting else pal.text
        avg = num(p.avg) + ("*" if p.avg_is_last_season else "")
        t.add_row(Text(s.slot, style=pal.dim), Text(p.name, style=style), p.positions, p.pro_team,
                  injury(p, pal), avg, num(p.last15), Text(num(p.proj), style=style),
                  Text("●", style=pal.good) if p.id in data.plays_today else "")
    t.caption = "Avg = season average (* last season) · L15 = last 15 days · Proj = ESPN projection"
    return t


def to_json(data: RosterData) -> list[dict]:
    return [{"slot": s.slot, "plays_today": s.player.id in data.plays_today, **s.player.to_dict()}
            for s in data.league.me.roster]

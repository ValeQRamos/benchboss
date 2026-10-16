"""Standings: the league table."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from benchboss.espn.models import League
from benchboss.ui.common import table
from benchboss.ui.theme import Palette

TITLE = "Standings"
VIEWS: tuple[tuple[str, str], ...] = ()


def load(session) -> League:
    return session.league()


def draw(league: League, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    t = table(pal, league.name)
    for col, kw in (("#", {"justify": "right"}), ("Team", {}), ("Manager", {}),
                    ("Record", {}), ("PF", {"justify": "right"})):
        t.add_column(col, **kw)
    for i, team in enumerate(league.standings()):
        mine = team.id == league.my_team_id
        t.add_row(str(i + 1), Text(team.name, style=f"bold {pal.accent}" if mine else pal.text),
                  team.owner_name, team.record, f"{team.points_for:,.1f}")
    return t


def to_json(league: League) -> list[dict]:
    return [{"rank": i + 1, "team": t.name, "manager": t.owner_name, "record": t.record,
             "points_for": t.points_for} for i, t in enumerate(league.standings())]

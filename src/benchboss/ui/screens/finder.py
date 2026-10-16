"""Player finder: every player in one table with every stat split, and your watch list.

Placeholder until the 1.0.2 finder lands: a plain table of the pool.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType

from benchboss.espn.models import Player
from benchboss.ui import views
from benchboss.ui.theme import Palette

TITLE = "Player finder"
VIEWS: tuple[tuple[str, str], ...] = ()
SOURCES = {"fa": "Free agents", "rostered": "On a team", "all": "Everyone", "watch": "Watch list"}


@dataclass
class FinderData:
    players: list[Player]
    source: str = "fa"
    watch: tuple[int, ...] = ()


def load(session, source: str = "fa", position: str | None = None, sort: str = "proj",
         query: str | None = None, n: int = 100) -> FinderData:
    players = session.player_pool(source, position, n, sort, query)
    return FinderData(players, source, session.watch_list())


def draw(data: FinderData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    return views.free_agents(data.players, pal, SOURCES.get(data.source, TITLE))


def to_json(data: FinderData) -> list[dict]:
    return [{**p.to_full_dict(), "watched": p.id in data.watch} for p in data.players]

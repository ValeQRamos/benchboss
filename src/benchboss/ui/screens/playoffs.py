"""Playoff race: odds, who is in or out, and what-if scenarios for the weeks left.

Placeholder until the 1.0.2 playoff screen lands.
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from benchboss.ui.theme import Palette

TITLE = "Playoff race"
VIEWS: tuple[tuple[str, str], ...] = ()


def load(session, picks: dict[int, int] | None = None, sims: int = 5000):
    return session.playoff_race(picks, sims)


def draw(data, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    return Text(str(data), style=pal.text)


def to_json(data):
    return data

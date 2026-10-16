"""Optimize: the best lineup for one day or every day left in the matchup week."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import DayPlan
from benchboss.espn.constants import SLOT
from benchboss.ui.common import day_label
from benchboss.ui.theme import Palette


def plan(plans: list[DayPlan], cal: SeasonCalendar, pal: Palette) -> RenderableType:
    parts: list[RenderableType] = []
    for p in plans:
        head = Text.assemble((day_label(cal.date_of(p.period)), f"bold {pal.accent}"),
                             (f"   projected {p.projected:.1f} pts", pal.dim))
        parts.append(head)
        if p.moves:
            for m in p.moves:
                parts.append(Text.assemble(("  ↳ ", pal.dim), (m.player.name, pal.text),
                                           (f"  {SLOT.get(m.from_slot)} → {SLOT.get(m.to_slot)}", pal.info)))
        else:
            parts.append(Text("  already optimal", style=pal.good))
        if p.bench:
            bench = ", ".join(f"{pl.name} ({why})" for pl, why in p.bench)
            parts.append(Text(f"  bench: {bench}", style=pal.dim))
    return Group(*parts)

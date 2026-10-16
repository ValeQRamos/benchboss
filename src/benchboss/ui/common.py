"""Small drawing helpers shared by the views, the screens and the dashboard."""

from __future__ import annotations

import datetime as dt

from rich import box
from rich.table import Table
from rich.text import Text

from benchboss.espn.models import Player
from benchboss.ui.theme import Palette


def table(pal: Palette, title: str | None = None, caption: str | None = None) -> Table:
    return Table(title=title, caption=caption, box=box.SIMPLE_HEAD, header_style=f"bold {pal.dim}",
                 title_style=f"bold {pal.accent}", title_justify="left",
                 caption_style=pal.dim, caption_justify="left", border_style=pal.border,
                 pad_edge=False, expand=False)


def day_label(d: dt.date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def num(v, fmt="{:.1f}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "-"


def injury(p: Player, pal: Palette) -> Text:
    return Text(p.injury, style=pal.bad if p.injury in ("OUT", "SUSP", "IR") else pal.warn)

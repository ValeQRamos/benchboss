"""Player news: RotoWire and ESPN items ("spins") on your roster and on your watch list.

Follows the screen protocol but is not in SCREENS: the app builds it in its own "news"
branch (which adds the AI briefing tip) and ``benchboss news`` prints one section of it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.constrain import Constrain
from rich.table import Table
from rich.text import Text

from benchboss.errors import BenchbossError
from benchboss.espn.models import Player
from benchboss.news import NewsItem
from benchboss.ui.common import player_cell, title
from benchboss.ui.theme import Palette

TITLE = "Player news"
VIEWS: tuple[tuple[str, str], ...] = ()
DAYS = 5
LABELS = {"roster": "Your roster", "watch": "Watch list", "players": "Players"}
EMPTY_WATCH = "Your watch list is empty. Add players in the Player finder or with:"
WATCH_ADD = 'benchboss watch add "Player"'
SEP = "  ·  "
MEASURE = 96  # the longest line of news text: wider is hard to read


@dataclass
class Section:
    key: str                     # roster, watch or players (the ones you named)
    players: list[Player]
    items: list[NewsItem] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key)


@dataclass
class NewsData:
    sections: list[Section]
    days: int
    now: dt.datetime
    tip: str = ""                # one dim line under the news (the app's AI briefing hint)

    @property
    def names(self) -> dict[int, str]:
        return {p.id: p.name for s in self.sections for p in s.players}


def watch_players(session) -> list[Player]:
    """The players on your ESPN watch list, in the order of the list.

    One player read with every split; if that fails, names only (from the rosters or one
    lookup), so the news still has someone to be about.
    """
    ids = list(session.watch_list())
    if not ids:
        return []
    try:
        found = {p.id: p for p in session.player_pool("watch")}
    except BenchbossError:
        found = {}
    missing = [i for i in ids if i not in found]
    if missing:
        from benchboss.inbox import player_names

        names = player_names(session, missing)
        found.update((i, Player(i, names[i])) for i in missing if i in names)
    return [found[i] for i in ids if i in found]


def sections(session, which: Iterable[str] = ("roster", "watch"),
             players: list[Player] | None = None) -> list[Section]:
    """The sections to show, with their players (no news yet). ``players`` (the ones named
    on the command line) come first as their own section."""
    out = [Section("players", list(players))] if players is not None else []
    for key in which:
        if key == "roster":
            out.append(Section("roster", [s.player for s in session.league().me.roster]))
        elif key == "watch":
            out.append(Section("watch", watch_players(session)))
        else:
            raise BenchbossError(f"unknown news section '{key}' (roster, watch)")
    return out


def load(session, days: int = DAYS, which: Iterable[str] = ("roster", "watch"),
         players: list[Player] | None = None, tip: str = "") -> NewsData:
    """News from the last ``days`` days for each section, in one request to the feed."""
    secs = sections(session, which, players)
    ids = list(dict.fromkeys(p.id for s in secs for p in s.players))
    items = session.news(ids, days) if ids else []
    for s in secs:
        mine = {p.id for p in s.players}
        s.items = [i for i in items if i.player_ids & mine]
    return NewsData(secs, days, session.now, tip)


def to_json(data: NewsData) -> list[dict]:
    names = data.names
    return [{**i.to_dict(names), "section": s.key} for s in data.sections for i in s.items]


# --- drawing --------------------------------------------------------------------------------------

def draw(data: NewsData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    room = max(10, min(MEASURE, width - 5))  # the text column: the age and its gap take 5
    metas = [[_meta(item, sec, data, pal) for item in sec.items] for sec in data.sections]
    # the time and the source drop for every item at once, like columns, so the lines read
    # alike; an item whose names alone fill the line does not take them from the others
    fits = [_fits(names, extras, room) for row in metas for names, extras in row]
    keep = min([n for n in fits if n], default=0)
    total = len({i.id for s in data.sections for i in s.items})
    parts: list[RenderableType] = [
        title(TITLE, pal, f"last {_days(data.days)}",
              f"{total} item{'s' * (total != 1)}" if total else "nothing new")]
    for sec, row in zip(data.sections, metas, strict=True):
        parts += [Text(""), _heading(sec, pal, min(width, MEASURE + 5)),
                  _body(sec, row, data, pal, room, keep)]
    if data.tip:
        parts += [Text(""), Text(data.tip, style=pal.dim)]
    return Constrain(Group(*parts), MEASURE + 5)


def _days(n: int) -> str:
    return "24 hours" if n == 1 else f"{n} days"


def _heading(sec: Section, pal: Palette, width: int) -> Text:
    """ "★ Watch list  2 ─────────": the label, how many items, a thin rule to the text's edge."""
    out = Text()
    if sec.key == "watch":
        out.append("★ ", style=pal.accent)
    out.append(sec.label, style=f"bold {pal.text}")
    if sec.items:
        out.append(f"  {len(sec.items)}", style=pal.dim)
    fill = width - cell_len(out.plain) - 1
    if fill >= 3:
        out.append(" " + "─" * fill, style=pal.border)
    return out


def _body(sec: Section, metas: list[tuple[Text, list[str]]], data: NewsData, pal: Palette,
          room: int, keep: int) -> RenderableType:
    if not sec.players and sec.key == "watch":
        # the command on a line of its own, so it never breaks in two
        return Group(Text(EMPTY_WATCH, style=pal.dim), Text(WATCH_ADD, style=pal.text))
    if not sec.players:
        return Text("No players.", style=pal.dim)
    if not sec.items:
        return Text(f"Nothing in the last {_days(data.days)}.", style=pal.dim)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", no_wrap=True, min_width=3)
    grid.add_column(max_width=room)
    for n, (item, (names, extras)) in enumerate(zip(sec.items, metas, strict=True)):
        if n:
            grid.add_row("", "")
        line = names.copy()
        for extra in extras[:min(keep, _fits(names, extras, room))]:
            if line:
                line.append(SEP, style=pal.border)
            line.append(extra, style=pal.dim)
        age = data.now - item.published
        grid.add_row(Text(_ago(age), style=pal.text if age < dt.timedelta(days=1) else pal.dim),
                     Group(line, Text(item.headline, style=pal.text), *_spin(item, pal)))
    return grid


def _meta(item: NewsItem, sec: Section, data: NewsData, pal: Palette) -> tuple[Text, list[str]]:
    """Who the item is about ("Egor Demin BKN DTD", this section's players first) and what may
    follow on the same line: the time and the source."""
    who = {p.id: p for p in sec.players}
    names = data.names
    out = Text()
    for pid in sorted(item.player_ids, key=lambda p: (p not in who, p)):
        p = who.get(pid)
        # no NBA team when we only know the name (the watch list fallback) or he has none
        cell = (player_cell(p, pal, team=p.pro_team_id > 0, style=f"bold {pal.text}") if p
                else Text(names[pid], style=pal.text) if pid in names else None)
        if cell is None:
            continue
        if out:
            out.append(", ", style=pal.dim)
        out.append_text(cell)
    when = item.published.astimezone(data.now.tzinfo)
    hour = when.hour % 12 or 12
    return out, [f"{when:%a} {hour}:{when:%M} {when:%p}", item.source]


def _fits(names: Text, extras: list[str], room: int) -> int:
    """How many of ``extras`` fit after ``names`` on one line of ``room`` cells."""
    used, n = cell_len(names.plain), 0
    for extra in extras:
        used += (len(SEP) if used else 0) + cell_len(extra)
        if not extra or used > room:
            break
        n += 1
    return n


def _spin(item: NewsItem, pal: Palette) -> list[RenderableType]:
    """RotoWire's analysis, "Spin" in a gutter so the text wraps under itself."""
    if not item.spin:
        return []
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column()
    grid.add_row(Text("Spin", style=f"bold {pal.dim}"), Text(item.spin, style=pal.dim))
    return [grid]


def _ago(age: dt.timedelta) -> str:
    minutes = max(0, int(age.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes}m" if minutes else "now"
    if minutes < 48 * 60:  # like the dashboard's news card
        return f"{minutes // 60}h"
    return f"{minutes // (24 * 60)}d"

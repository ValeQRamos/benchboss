"""Player news: RotoWire and ESPN items ("spins") on your roster and on your watch list, and
the latest news on any NBA player you name.

Follows the screen protocol but is not in SCREENS: the app builds it in its own "news"
branch (which adds the AI briefing tip) and ``benchboss news`` prints one section of it.

Every download goes through ``Session.news`` (a window of days) or ``Session.latest_news``
(the newest items), which both end in ``news.fetch``.
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
from benchboss.news import LATEST, NewsItem
from benchboss.text import EXACT, INSIDE, confident
from benchboss.ui.common import player_cell, rostered, title
from benchboss.ui.theme import Palette

TITLE = "Player news"
VIEWS: tuple[tuple[str, str], ...] = ()
DAYS = 5
LABELS = {"roster": "Your roster", "watch": "Watch list", "players": "Players"}
EMPTY_WATCH = "Your watch list is empty. Add players in the Player finder or with:"
WATCH_ADD = 'benchboss watch add "Player"'
SEP = "  ·  "
MEASURE = 96  # the longest line of news text: wider is hard to read

PICKS = 8                                        # players a search offers to pick from
UNAVAILABLE = "News is not available right now"


@dataclass
class Section:
    key: str                     # roster, watch or players (the ones you named or searched)
    players: list[Player]
    items: list[NewsItem] = field(default_factory=list)
    error: str = ""              # the feed did not answer (the app shows it in place)
    more: bool = False           # latest items: there are older ones

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key)


@dataclass
class NewsData:
    sections: list[Section]
    days: int | None             # None: the latest items whatever their date
    now: dt.datetime
    tip: str = ""                # one dim line under the news (the app's AI briefing hint)

    @property
    def names(self) -> dict[int, str]:
        return {p.id: p.name for s in self.sections for p in s.players}


@dataclass
class Found:
    """What a search found: the best matches first (text.rank)."""
    query: str
    players: list[Player]
    sure: bool = False           # the first one is clearly the one meant (text.confident)
    exact: bool = False          # ... and it is the exact name
    owners: dict[int, str] = field(default_factory=dict)  # player id -> owner_of

    @property
    def best(self) -> Player | None:
        return self.players[0] if self.sure and self.players else None


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


def load_tab(session, tab: str = "roster", days: int = DAYS, tip: str = "") -> NewsData:
    """One tab of the app's news screen. A feed that does not answer leaves the reason in
    the section (the tab says so in place); a league that cannot be read raises."""
    secs = sections(session, (tab,))
    ids = [p.id for p in secs[0].players]
    try:
        secs[0].items = session.news(ids, days) if ids else []
    except BenchbossError as e:
        secs[0].error = f"{UNAVAILABLE}: {e}"
    return NewsData(secs, days, session.now, tip)


def load_latest(session, players: list[Player], n: int = LATEST, offset: int = 0,
                catch: bool = False) -> NewsData:
    """The newest ``n`` items on each player whatever their date (after the newest
    ``offset``), in one section. ``catch``: a feed error goes in the section instead of
    raising (the app)."""
    sec = Section("players", list(players))
    items: dict[int, NewsItem] = {}
    try:
        for p in players:
            got = session.latest_news(p.id, n + 1, offset)  # one more says if there are more
            sec.more = sec.more or len(got) > n
            for item in got[:n]:
                if item.id in items:
                    items[item.id].player_ids |= item.player_ids
                else:
                    items[item.id] = item
    except BenchbossError as e:
        if not catch:
            raise
        sec.error = f"{UNAVAILABLE}: {e}"
    sec.items = sorted(items.values(), key=lambda x: x.published, reverse=True)
    return NewsData([sec], None, session.now)


def find(session, query: str, n: int = PICKS) -> Found:
    """Any NBA player by name for reading his news (Session.search_players): typos and
    partial names are fine. ``sure`` when one match is clearly the one meant."""
    ranked = session.search_players(query, n)
    if ranked and ranked[0][0] >= INSIDE:  # a real match: near spellings are only noise
        ranked = [(score, p) for score, p in ranked if score >= INSIDE]
    return Found(query, [p for _, p in ranked], confident(ranked),
                 bool(ranked) and ranked[0][0] >= EXACT)


def owner_of(session, p: Player) -> str:
    """Who has him in your league: a team's abbreviation, else FA (or Waivers)."""
    lg = session.league()
    for t in lg.teams.values():
        if any(s.player.id == p.id for s in t.roster):
            return (t.abbrev or "").strip() or t.name
    return "Waivers" if p.status == "WAIVERS" else "FA"


def refreshed(session, p: Player) -> Player:
    """The player as the league has him, else one fresh read (injury, team, % rostered);
    the player as given when that read fails."""
    lg = session.league()
    for t in lg.teams.values():
        for s in t.roster:
            if s.player.id == p.id:
                return s.player
    from benchboss.actions import refresh_player

    try:
        return refresh_player(session, p.id)
    except BenchbossError:
        return p


def candidate(p: Player, owner: str) -> str:
    """One line of the pick list: "Ben Simmons SAC PG · FA · 12%"."""
    parts = [p.name]
    if p.pro_team_id > 0:
        parts[0] += f" {p.pro_team}"
    if p.positions or p.position_id:
        parts[0] += f" {(p.positions or p.position).split('/')[0]}"
    parts += [owner, f"{rostered(p.owned)}%"]
    return " · ".join(x for x in parts if x)


def to_json(data: NewsData) -> list[dict]:
    names = data.names
    return [{**i.to_dict(names), "player_ids": sorted(i.player_ids), "section": s.key}
            for s in data.sections for i in s.items]


# --- drawing --------------------------------------------------------------------------------------

def draw(data: NewsData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    total = len({i.id for s in data.sections for i in s.items})
    head = title(TITLE, pal, _window(data.days),
                 f"{total} item{'s' * (total != 1)}" if total else "nothing new")
    return Constrain(Group(head, body(data, pal, width)), MEASURE + 5)


def body(data: NewsData, pal: Palette, width: int, headings: bool = True) -> RenderableType:
    """Everything under the title: each section (with its heading) and the tip."""
    room = max(10, min(MEASURE, width - 5))  # the text column: the age and its gap take 5
    metas = [[_meta(item, sec, data, pal) for item in sec.items] for sec in data.sections]
    # the time and the source drop for every item at once, like columns, so the lines read
    # alike; an item whose names alone fill the line does not take them from the others
    fits = [_fits(names, extras, room) for row in metas for names, extras in row]
    keep = min([n for n in fits if n], default=0)
    parts: list[RenderableType] = []
    for sec, row in zip(data.sections, metas, strict=True):
        if headings:
            parts += [Text(""), _heading(sec, pal, min(width, MEASURE + 5))]
        elif parts:
            parts.append(Text(""))
        parts.append(_body(sec, row, data, pal, room, keep))
    if data.tip:
        parts += [Text(""), Text(data.tip, style=pal.dim)]
    return Constrain(Group(*parts), MEASURE + 5)


def player_header(p: Player, owner: str, pal: Palette, width: int) -> Text:
    """ "Ben Simmons SAC OUT  ·  PG  ·  FA  ·  12% rostered", cut to fit ``width``."""
    out = player_cell(p, pal, team=p.pro_team_id > 0, style=f"bold {pal.text}")
    extras = [(p.positions or (p.position if p.position_id else "")), owner,
              f"{rostered(p.owned)}% rostered"]
    for extra in extras:
        if extra and out.cell_len + len(SEP) + cell_len(extra) <= width:
            out.append(SEP, style=pal.border)
            out.append(extra, style=pal.accent if owner and extra == owner and owner != "FA"
                       else pal.dim)
    return out


def _window(days: int | None) -> str:
    return "latest news" if days is None else f"last {_days(days)}"


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
    if sec.error and not sec.items:
        return Text(sec.error, style=pal.warn)
    if not sec.players and sec.key == "watch":
        # the command on a line of its own, so it never breaks in two
        return Group(Text(EMPTY_WATCH, style=pal.dim), Text(WATCH_ADD, style=pal.text))
    if not sec.players:
        return Text("No players.", style=pal.dim)
    if not sec.items:
        if data.days is None:
            return Text("No news yet.", style=pal.dim)
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
    if sec.error:  # older items did not come
        return Group(grid, Text(""), Text(sec.error, style=pal.warn))
    return grid


def _meta(item: NewsItem, sec: Section, data: NewsData, pal: Palette) -> tuple[Text, list[str]]:
    """Who the item is about ("Egor Demin BKN DTD", this section's players first) and what may
    follow on the same line: the time (the date when it is more than a few days old) and the
    source."""
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
    if data.now - item.published > dt.timedelta(days=6):  # a weekday alone would be unclear
        return out, [f"{when:%b} {when.day}", item.source]
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

"""Player news: RotoWire and ESPN items ("spins") on your roster and on your watch list, and
the latest news on any NBA player you search for.

Follows the screen protocol but is not in SCREENS: the app builds it in its own "news"
branch (which adds the AI briefing tip) and mounts ``NewsView``: two tabs (1 Roster, 2 Watch
list) with a window of days, and a search (/) for any player's latest items whatever their
date. ``benchboss news`` prints one section with ``draw``.

Every download goes through ``Session.news`` (a window of days) or ``Session.latest_news``
(the newest items), which both end in ``news.fetch``.
"""

from __future__ import annotations

import datetime as dt
import weakref
from collections.abc import Iterable
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.constrain import Constrain
from rich.table import Table
from rich.text import Text
from textual import work
from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from benchboss.errors import BenchbossError
from benchboss.espn.models import Player
from benchboss.news import LATEST, NewsItem
from benchboss.text import EXACT, INSIDE, confident, surname
from benchboss.ui.common import fit_title, legend, player_cell, rostered, title
from benchboss.ui.layout import KeyItem
from benchboss.ui.theme import DARK, Palette

TITLE = "Player news"
VIEWS: tuple[tuple[str, str], ...] = ()
DAYS = 5
LABELS = {"roster": "Your roster", "watch": "Watch list", "players": "Players"}
EMPTY_WATCH = "Your watch list is empty. Add players in the Player finder or with:"
WATCH_ADD = 'benchboss watch add "Player"'
SEP = "  ·  "
MEASURE = 96  # the longest line of news text: wider is hard to read

TABS = ("roster", "watch")                       # keys 1 and 2 in the app
TAB_LABEL = {"roster": "Roster", "watch": "Watch list"}
TAB_SHORT = {"roster": "Roster", "watch": "Watch"}
DAY_CHOICES = (1, 3, 5, 7, 14, 30)               # the window [ and ] step through
PICKS = 8                                        # players a search offers to pick from
SEARCH_WIDTH = 28                                # the app's search box (less when narrow)
SEARCH_MIN = 10
UNAVAILABLE = "News is not available right now"
NO_MATCH = "No NBA player matches"


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


# --- the app widget -------------------------------------------------------------------------------

# Where the news screen was last in each running app (tab, window, search), so n (or r)
# comes back to the same place.
_MEMORY: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

# The text color on the accent pill of the selected tab, per palette (as in the finder)
_ON_ACCENT = {"dark": "#141518", "light": "#ffffff"}

Region = tuple[int, int, str]  # (start, end, tab) in cells on the tab line


def remembered_tab(app) -> tuple[str, int]:
    """The tab and window of days the news screen showed last in this app."""
    mem = _MEMORY.get(app) or {}
    tab = mem.get("tab") if mem.get("tab") in TABS else "roster"
    days = mem.get("days") if mem.get("days") in DAY_CHOICES else DAYS
    return tab, days


class _Tabs(Static):
    """The tab line; a click on a tab opens it (a click on the search pill does nothing)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.regions: list[Region] = []

    def show(self, text: Text, regions: list[Region]) -> None:
        self.regions = regions
        self.update(text)

    def on_click(self, event) -> None:
        offset = event.get_content_offset(self)
        if offset is None or offset.y != 0:
            return
        hit = next((r for r in self.regions if r[0] <= offset.x < r[1]), None)
        view = next((a for a in self.ancestors if isinstance(a, NewsView)), None)
        if hit is not None and view is not None and hit[2] in TABS:
            event.stop()
            view.action_tab(hit[2])
            view.focus()


class NewsView(Vertical):
    """The interactive news screen. It binds 1 2 / [ ] + . escape backspace j k space and
    nothing else, so the app's one-key menu keeps working while the news has the focus.

    Modes: "tab" (a tab's news over a window of days), "picks" (a search that matched
    several players: pick one) and "search" (one player's latest items)."""

    DEFAULT_CSS = """
    NewsView { height: 1fr; }
    NewsView #news-title { height: 1; }
    NewsView #news-top { height: 1; margin-top: 1; }
    NewsView #news-tabs { width: 1fr; height: 1; }
    NewsView #news-search { width: 28; height: 1; border: none; padding: 0 1;
                            background: $surface; color: $foreground; }
    NewsView #news-search:focus { border: none; background: $panel; }
    NewsView #news-picks { height: auto; max-height: 10; margin-top: 1; display: none;
                           border: none; background: $surface; padding: 0 1; }
    NewsView #news-picks.open { display: block; }
    NewsView #news-body { height: 1fr; margin-top: 1; background: $background; }
    NewsView #news-hint { height: 1; margin-top: 1; }
    NewsView #news-hint.hidden { display: none; }
    """

    BINDINGS = [
        Binding("1", "tab('roster')", "Roster", show=False),
        Binding("2", "tab('watch')", "Watch list", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("left_square_bracket", "days(-1)", "Fewer days", show=False),
        Binding("right_square_bracket", "days(1)", "More days", show=False),
        Binding("plus,full_stop", "more", "More", show=False),
        Binding("escape", "back", "Back", show=False),
        Binding("backspace", "leave_search", "Back", show=False),
        Binding("j", "scroll(1)", "Down", show=False),
        Binding("k", "scroll(-1)", "Up", show=False),
        Binding("space", "page", "Page down", show=False),
    ]

    def __init__(self, data: NewsData, app) -> None:
        super().__init__()
        self.session = app.session
        self._owner_app = app
        self.tip = data.tip
        sec = data.sections[0] if data.sections else Section("roster", [])
        self.tab = sec.key if sec.key in TABS else "roster"
        self.days = data.days if data.days in DAY_CHOICES else DAYS
        self.cache: dict[tuple[str, int], NewsData] = {(self.tab, self.days): data}
        self.mode = "tab"
        self.query_text = ""
        self.found: Found | None = None
        self.player: Player | None = None   # the player searched for
        self.owner = ""
        self.shown: NewsData | None = None  # his latest items
        self.fetching = False
        self.message = ""                   # a search with no match, or what went wrong
        self._gen = 0
        self._names_asked = False
        mem = _MEMORY.get(app) or {}
        self._restore = mem.get("player") if mem.get("mode") == "search" else None
        if self._restore:
            self.query_text = mem.get("query") or ""

    # --- layout ------------------------------------------------------------------------------------

    def compose(self):
        yield Static(id="news-title")
        with Horizontal(id="news-top"):
            yield _Tabs(id="news-tabs")
            yield Input(placeholder="/ search any player", id="news-search")
        yield OptionList(id="news-picks")
        with VerticalScroll(id="news-body"):
            yield Static(id="news-text")
        yield Static(id="news-hint")

    def _live(self) -> bool:
        """Whether the app still shows this screen (a menu key can take it off while a
        callback is on its way; its parts may be gone already)."""
        return self.is_attached and getattr(self._owner_app, "_panel_widget", self) is self

    def on_mount(self) -> None:
        if not self._live():
            return
        self.watch(self.app, "theme", lambda: self._render_all(), init=False)
        if self._restore:
            pid, name = self._restore
            self._restore = None
            self.query_one("#news-search", Input).value = self.query_text
            self._open_player(Player(pid, name))
            return
        self._remember()
        self._render_all()

    def focus(self, scroll_visible: bool = True):
        if self._live():
            picks = self.query_one("#news-picks", OptionList)
            target = picks if self.mode == "picks" else self.query_one("#news-body")
            target.focus(scroll_visible)
        return self

    def on_resize(self) -> None:
        if self._live():
            self._render_all()

    @property
    def pal(self) -> Palette:
        return getattr(self._owner_app, "pal", DARK)

    @property
    def _width(self) -> int:
        return max(20, self.size.width or 100)

    def _remember(self) -> None:
        player = (self.player.id, self.player.name) if self.player is not None else None
        _MEMORY[self._owner_app] = {"tab": self.tab, "days": self.days, "mode": self.mode,
                                    "query": self.query_text, "player": player}

    # --- drawing -----------------------------------------------------------------------------------

    def _render_all(self) -> None:
        if not self._live():
            return
        self._render_header()
        self._render_body()
        self._render_hint()

    def _current(self) -> NewsData | None:
        if self.mode == "tab":
            return self.cache.get((self.tab, self.days))
        return self.shown if self.mode == "search" else None

    def _render_header(self) -> None:
        pal, width = self.pal, self._width
        data = self._current()
        items = len(data.sections[0].items) if data and data.sections else 0
        count = ("Loading..." if self.fetching else
                 f"{items} item{'s' * (items != 1)}" if items else
                 "nothing new" if data is not None and self.mode == "tab" else "")
        if self.mode == "tab":
            window = _window(self.days)
            tries = ((TAB_LABEL[self.tab], window, count), (window, count), (count,))
        elif self.mode == "picks" and self.found is not None:
            n = len(self.found.players)
            tries = ((f"{n} players match '{self.query_text}'",), (f"{n} matches",))
        else:
            who = self.player.name if self.player is not None else f"'{self.query_text}'"
            tries = ((who, "latest news", count), (who, count), (count,))
        self.query_one("#news-title", Static).update(fit_title(TITLE, pal, width, *tries))
        tabs, regions, search = self._tabs(pal, width)
        self.query_one("#news-tabs", _Tabs).show(tabs, regions)
        self.query_one("#news-search", Input).styles.width = max(SEARCH_MIN, search)

    def _tabs(self, pal: Palette, width: int) -> tuple[Text, list[Region], int]:
        """ "1 Roster  2 Watch list  / Ben Simmons", the current one a pill; shorter labels
        when they and the search box do not fit. Returns the line, where each tab is and
        the width left for the search box."""
        searching = self.mode != "tab"
        name = (self.player.name if self.player is not None else self.query_text) or "search"
        digits = {k: TAB_SHORT[k] if k == self.tab and not searching else "" for k in TABS}
        tries = ((TAB_LABEL, name, SEARCH_WIDTH), (TAB_SHORT, name, SEARCH_MIN),
                 (TAB_SHORT, surname(name), SEARCH_MIN), (digits, surname(name), SEARCH_MIN),
                 (digits, "", SEARCH_MIN))
        pill = f"bold {_ON_ACCENT.get(pal.name, '#ffffff')} on {pal.accent}"
        for labels, who, search in tries:
            out, regions = Text(), []
            for i, key in enumerate(TABS):
                start = out.cell_len
                if key == self.tab and not searching:
                    out.append(f" {i + 1} {labels[key]} ", style=pill)
                else:
                    out.append(f" {i + 1}", style=f"bold {pal.dim}")
                    out.append(f" {labels[key]} " if labels[key] else " ", style=pal.text)
                regions.append((start, out.cell_len, key))
                out.append(" ")
            if searching:
                out.append(f" / {who} " if who else " / ", style=pill)
                out.append(" ")
            if out.cell_len + search <= width:
                break
        return out, regions, min(SEARCH_WIDTH, width - out.cell_len)

    def _render_body(self) -> None:
        pal = self.pal
        width = max(20, self._width - 3)  # the scrollbar and a gap before it
        picks = self.query_one("#news-picks", OptionList)
        picks.set_class(self.mode == "picks", "open")
        if self.mode == "picks":
            self._fill_picks(picks)
            n = len(self.found.players) if self.found else 0
            text = Text(f"'{self.query_text}' matches {n} players: pick one with the arrows "
                        "and enter, or esc to go back.", style=pal.dim)
        elif self.mode == "search" and self.message and self.shown is None:
            # no match is an answer; a feed or a search that failed is a warning
            text = Text(self.message, style=pal.dim if self.message.startswith(NO_MATCH)
                        else pal.warn)
        elif self.mode == "search":
            parts: list[RenderableType] = []
            if self.player is not None:
                parts += [player_header(self.player, self.owner, pal, width), Text("")]
            if self.shown is not None:
                parts.append(body(self.shown, pal, width, headings=False))
                if self.shown.sections[0].more:
                    parts += [Text(""), Text("Press . for older news.", style=pal.dim)]
            elif self.fetching:
                parts.append(Text("Loading...", style=pal.dim))
            text = Group(*parts)
        else:
            data = self.cache.get((self.tab, self.days))
            if data is None:
                text = Text(self.message or "Loading...",
                            style=pal.warn if self.message else pal.dim)
            else:
                shown = NewsData(data.sections, data.days, data.now,
                                 self.tip if self.tab == "roster" else "")
                text = body(shown, pal, width, headings=False)
        self.query_one("#news-text", Static).update(text)

    def _fill_picks(self, picks: OptionList) -> None:
        if self.found is None:
            return
        ids = [str(p.id) for p in self.found.players]
        if [o.id for o in picks.options] == ids:
            return
        picks.clear_options()
        picks.add_options([Option(candidate(p, self.found.owners.get(p.id, "")), id=str(p.id))
                           for p in self.found.players])
        picks.highlighted = 0 if ids else None

    def _render_hint(self) -> None:
        hint = self.query_one("#news-hint", Static)
        compact = bool(getattr(self._owner_app, "compact", False))
        hint.set_class(compact, "hidden")  # the compact layout has its own key bar
        pal, width = self.pal, self._width
        if self.mode == "picks":
            items = [("enter", "pick"), ("esc", "back"), ("/", "search again")]
        elif self.mode == "search":
            more = self.shown is not None and self.shown.sections[0].more
            items = ([(".", "older news")] if more else []) + [
                ("esc", "back to the tabs"), ("/", "search again"), ("1 2", "tabs")]
        else:
            items = [("1 2", "tabs"), ("/", "search any player"), ("[ ]", "days"),
                     ("j k", "scroll")]
        out = Text()
        for i in range(len(items), 0, -1):
            out = legend(pal, *items[:i])
            if out.cell_len <= width:
                break
        hint.update(out)

    def key_items(self) -> list[KeyItem]:
        """This screen's keys for the compact key bar (the app adds menu, refresh, quit).
        The actions are this view's own (run with the view as the namespace)."""
        if self.mode == "picks":
            return [KeyItem("⏎", "pick", "", 10), KeyItem("esc", "back", "back", 20),
                    KeyItem("/", "search", "search", 30)]
        if self.mode == "search":
            more = self.shown is not None and self.shown.sections[0].more
            return ([KeyItem(".", "older", "more", 10)] if more else []) + [
                KeyItem("esc", "back", "back", 20), KeyItem("/", "search", "search", 30),
                KeyItem("1-2", "tabs", "", 40)]
        return [KeyItem("1-2", "tabs", "", 10), KeyItem("/", "search", "search", 20),
                KeyItem(".", "days", "more", 30)]

    # --- actions -----------------------------------------------------------------------------------

    def action_tab(self, tab: str) -> None:
        if tab not in TABS or (tab == self.tab and self.mode == "tab"):
            return
        self.tab = tab
        self._to_tabs()

    def _to_tabs(self) -> None:
        """Show the current tab (from the cache, else fetched), leaving any search."""
        cached = self.cache.get((self.tab, self.days))
        if cached is not None and cached.sections[0].error:
            del self.cache[(self.tab, self.days)]  # the feed was down: ask again
        self.mode = "tab"
        self.message = ""
        self._gen += 1  # a search still on its way is not wanted any more
        self.fetching = (self.tab, self.days) not in self.cache
        search = self.query_one("#news-search", Input)
        if not search.has_focus:
            search.value = ""
        self._remember()
        self._render_all()
        if self.query_one("#news-picks", OptionList).has_focus:
            self.query_one("#news-body").focus()
        if self.fetching:
            self._fetch_tab(self._gen, self.tab, self.days)

    def action_days(self, step: int) -> None:
        if self.mode != "tab":
            return  # a search shows the latest items, whatever their date
        i = DAY_CHOICES.index(self.days) if self.days in DAY_CHOICES else DAY_CHOICES.index(DAYS)
        days = DAY_CHOICES[max(0, min(len(DAY_CHOICES) - 1, i + step))]
        if days != self.days:
            self.days = days
            self._to_tabs()

    def action_more(self) -> None:
        """. or +: older news on the player searched for; on a tab, the next window of days
        (after the longest it goes back to the shortest)."""
        if self.mode == "tab":
            i = DAY_CHOICES.index(self.days) if self.days in DAY_CHOICES else 0
            self.days = DAY_CHOICES[(i + 1) % len(DAY_CHOICES)]
            self._to_tabs()
        elif (self.mode == "search" and self.player is not None and self.shown is not None
              and self.shown.sections[0].more and not self.fetching):
            self._gen += 1
            self.fetching = True
            self._render_all()
            self._fetch_player(self._gen, self.player, len(self.shown.sections[0].items))

    def action_search(self) -> None:
        search = self.query_one("#news-search", Input)
        search.focus()
        if not self._names_asked:
            self._names_asked = True
            self._fetch_names()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        query = event.value.strip()
        self.query_one("#news-body").focus()
        if not query:
            if self.mode != "tab":
                self._to_tabs()
            return
        self.query_text = query
        self.mode = "search"
        self.player, self.owner, self.shown, self.found = None, "", None, None
        self.message = ""
        self.fetching = True
        self._gen += 1
        self._remember()
        self._render_all()
        self._search(self._gen, query)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self.found is None or event.option.id is None:
            return
        p = next((x for x in self.found.players if str(x.id) == event.option.id), None)
        if p is not None:
            self._open_player(p)

    def _open_player(self, p: Player) -> None:
        self.mode = "search"
        self.player, self.owner, self.shown = p, "", None
        self.message = ""
        self.fetching = True
        self._gen += 1
        self._remember()
        self._render_all()
        self.query_one("#news-body").focus()
        self._fetch_player(self._gen, p, 0)

    def action_back(self) -> None:
        """escape: leave the search box, then the pick list, then the search."""
        search = self.query_one("#news-search", Input)
        if search.has_focus:
            search.value = self.query_text if self.mode != "tab" else ""
            self.focus()
            return
        if self.mode == "picks":
            self.query_text = ""
            self._to_tabs()
            return
        if self.mode == "search":
            self._to_tabs()
            return
        raise SkipAction()

    def action_leave_search(self) -> None:
        """backspace (the search box keeps its own): back to the tabs."""
        if self.mode == "tab":
            raise SkipAction()
        self._to_tabs()

    def action_scroll(self, step: int) -> None:
        picks = self.query_one("#news-picks", OptionList)
        if picks.has_focus:
            (picks.action_cursor_down if step > 0 else picks.action_cursor_up)()
            return
        scroll = self.query_one("#news-body", VerticalScroll)
        (scroll.scroll_down if step > 0 else scroll.scroll_up)()

    def action_page(self) -> None:
        self.query_one("#news-body", VerticalScroll).scroll_page_down()

    # --- fetching ----------------------------------------------------------------------------------

    def _reply(self, method, *args) -> None:
        """Hand a worker's result to the UI thread, unless the worker was cancelled."""
        if not get_current_worker().is_cancelled:
            self._owner_app.call_from_thread(method, *args)

    @work(thread=True, exclusive=True, group="news-view")
    def _fetch_tab(self, gen: int, tab: str, days: int) -> None:
        data, err = None, ""
        try:
            data = load_tab(self.session, tab, days)
        except BenchbossError as e:
            err = str(e)
        except Exception as e:  # never let a bad payload kill the app
            err = f"{type(e).__name__}: {e}"
        self._reply(self._tab_loaded, gen, tab, days, data, err)

    def _tab_loaded(self, gen: int, tab: str, days: int, data: NewsData | None,
                    err: str) -> None:
        if data is not None:
            self.cache[(tab, days)] = data  # kept even when late; _to_tabs retries errors
        if gen != self._gen or not self._live():
            return
        self.fetching = False
        self.message = err
        self._render_all()

    @work(thread=True, exclusive=True, group="news-view")
    def _search(self, gen: int, query: str) -> None:
        found, player, owner, shown, err = None, None, "", None, ""
        try:
            found = find(self.session, query)
            found.owners = {p.id: owner_of(self.session, p) for p in found.players}
            if found.best is not None:
                player = refreshed(self.session, found.best)
                owner = owner_of(self.session, player)
                shown = load_latest(self.session, [player], LATEST, catch=True)
        except BenchbossError as e:
            err = str(e)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        self._reply(self._searched, gen, query, found, player, owner, shown, err)

    def _searched(self, gen: int, query: str, found: Found | None, player: Player | None,
                  owner: str, shown: NewsData | None, err: str) -> None:
        if gen != self._gen or not self._live():
            return
        self.fetching = False
        self.found = found
        if err or found is None:
            self.message = f"Search failed: {err}" if err else ""
        elif not found.players:
            self.message = f"{NO_MATCH} '{query}'."
        elif player is None:
            self.mode = "picks"
        else:
            self.player, self.owner, self.shown = player, owner, shown
        self._remember()
        self._render_all()
        self.focus()

    @work(thread=True, exclusive=True, group="news-view")
    def _fetch_player(self, gen: int, player: Player, offset: int) -> None:
        owner, shown, err = "", None, ""
        try:
            if not offset:
                player = refreshed(self.session, player)
                owner = owner_of(self.session, player)
            shown = load_latest(self.session, [player], LATEST, offset, catch=True)
        except BenchbossError as e:
            err = str(e)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        self._reply(self._player_loaded, gen, player, owner, offset, shown, err)

    def _player_loaded(self, gen: int, player: Player, owner: str, offset: int,
                       shown: NewsData | None, err: str) -> None:
        if gen != self._gen or not self._live():
            return
        self.fetching = False
        if err or shown is None:
            if offset and self.shown is not None:
                self.shown.sections[0].error = f"{UNAVAILABLE}: {err}"
            else:
                self.message = f"{UNAVAILABLE}: {err}"
            self._render_all()
            return
        if offset and self.shown is not None:  # older items go under the ones on screen
            sec, new = self.shown.sections[0], shown.sections[0]
            seen = {i.id for i in sec.items}
            sec.items += [i for i in new.items if i.id not in seen]
            sec.more, sec.error = new.more, new.error
        else:
            self.player, self.owner, self.shown = player, owner, shown
        self._remember()
        self._render_all()

    @work(thread=True, exclusive=True, group="news-names")
    def _fetch_names(self) -> None:
        """Every NBA player's name for the search box's suggestions, most rostered first.
        Quiet when ESPN's list does not answer: the search still works without it."""
        try:
            players = sorted(self.session.nba_players(), key=lambda p: -p.owned)
        except Exception:
            return
        self._reply(self._names_loaded, [p.name for p in players])

    def _names_loaded(self, names: list[str]) -> None:
        if self._live() and names:
            from textual.suggester import SuggestFromList

            self.query_one("#news-search", Input).suggester = SuggestFromList(
                names, case_sensitive=False)


def widget(data: NewsData, app) -> NewsView:
    return NewsView(data, app)

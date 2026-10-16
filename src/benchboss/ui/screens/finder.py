"""Player finder: every player in one table with every stat split, and your ESPN watch list.

The CLI prints ``draw`` (``benchboss players``, ``benchboss watch``). The app mounts
``FinderView`` instead: pool tabs (1 2 3 4), a position filter ([ ]), the stat split (v), a
search box (/), a table you sort by clicking a header or with < and >, a detail card with
news (enter), and the watch-list star (space).
"""

from __future__ import annotations

import datetime as dt
import io
import threading
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from rich.console import Console, Group, RenderableType
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Input, Static
from textual.worker import get_current_worker

from benchboss.errors import BenchbossError
from benchboss.espn.constants import SPLIT_LABEL, SPLIT_SHORT, SPLITS
from benchboss.espn.models import Player, StatLine
from benchboss.ui.common import (
    legend,
    player_cell,
    rost_cell,
    rostered,
    shooting_pct,
    table,
    title,
)
from benchboss.ui.theme import DARK, Palette

TITLE = "Player finder"
SPLIT_KEYS = tuple(SPLITS)                       # season l7 l15 l30 proj last
VIEWS: tuple[tuple[str, str], ...] = tuple((k, SPLIT_LABEL[k]) for k in SPLIT_KEYS)
SOURCES = {"fa": "Free agents", "rostered": "On a team", "watch": "Watch list", "all": "Everyone"}
TABS = ("fa", "rostered", "watch", "all")       # keys 1 2 3 4 in the app
POSITIONS = (None, "PG", "SG", "SF", "PF", "C", "G", "F")
DEFAULT_SPLIT = "proj"
POOL_SIZE = 150                                 # players fetched per pool in the app
SEARCH_WIDTH = 28                               # the app's search box (less on a narrow window)
SEARCH_MIN = 10                                 # ... but never less than this
NEWS_DAYS = 7
RECENT = ("l7", "l15", "l30")                   # colored hot or cold against the season

# The selector says "Season"; the column says "Avg" (constants.SPLIT_SHORT).
SPLIT_PICK = {k: ("Season" if k == "season" else SPLIT_SHORT[k]) for k in SPLIT_KEYS}


# Box score columns for the selected split: (key, header, value from a StatLine, format).
BOX: tuple[tuple[str, str, Callable[[StatLine], float | None], Callable[[float], str]], ...] = (
    ("gp", "GP", lambda s: float(s.gp) if s.gp else None, lambda v: f"{v:.0f}"),
    ("min", "MIN", lambda s: s.mpg, lambda v: f"{v:.1f}"),
    ("pts", "PTS", lambda s: s.pts, lambda v: f"{v:.1f}"),
    ("reb", "REB", lambda s: s.reb, lambda v: f"{v:.1f}"),
    ("ast", "AST", lambda s: s.ast, lambda v: f"{v:.1f}"),
    ("stl", "STL", lambda s: s.stl, lambda v: f"{v:.1f}"),
    ("blk", "BLK", lambda s: s.blk, lambda v: f"{v:.1f}"),
    ("tpm", "3PM", lambda s: s.tpm, lambda v: f"{v:.1f}"),
    ("to", "TO", lambda s: s.to, lambda v: f"{v:.1f}"),
    ("fgp", "FG%", lambda s: s.fg_pct, shooting_pct),
    ("ftp", "FT%", lambda s: s.ft_pct, shooting_pct),
)
BOX_KEYS = tuple(k for k, *_ in BOX)
_BOX = {k: (head, value, fmt) for k, head, value, fmt in BOX}
COUNTS = ("pts", "reb", "ast", "stl", "blk", "tpm", "to")

# Every column of the app's table, left to right (also the order < and > walk through).
COLUMNS = ("star", "name", "pos", "owner", "own", "start", *SPLIT_KEYS, *BOX_KEYS)
HEADERS = {"star": "★", "name": "Player", "pos": "Pos", "owner": "Owner", "own": "Rost%",
           "start": "Start%", **{k: SPLIT_SHORT[k] for k in SPLIT_KEYS},
           **{k: head for k, (head, _, _) in _BOX.items()}}
TEXT_COLUMNS = ("name", "pos", "owner")         # sorted A to Z first; the rest highest first
# What the title says for each sort key: every column, plus the change in % rostered (--sort).
SORT_LABEL = {**HEADERS, "change": "Rost% change", "star": "watch list"}


@dataclass
class FinderData:
    players: list[Player]
    source: str = "fa"
    watch: tuple[int, ...] = ()
    position: str | None = None
    sort: str = DEFAULT_SPLIT
    query: str | None = None
    n: int = 100
    teams: dict[int, tuple[str, str]] = field(default_factory=dict)   # id -> (abbrev, name)
    my_team_id: int = 0


def load(session, source: str = "fa", position: str | None = None, sort: str = DEFAULT_SPLIT,
         query: str | None = None, n: int = 100) -> FinderData:
    """One pool of players with every split. ``source``: fa, rostered, all or watch."""
    players = session.player_pool(source, position, n, sort, query)
    lg = session.league()
    teams = {t.id: (_abbrev(t.abbrev, t.name), t.name) for t in lg.teams.values()}
    return FinderData(players, source, tuple(session.watch_list()), position, sort, query, n,
                      teams, lg.my_team_id)


def _abbrev(abbrev: str, name: str) -> str:
    return (abbrev or "").strip() or name[:4].upper()


# --- values and cells shared by the CLI table and the app -------------------------------------------

def owner_label(p: Player, data: FinderData) -> str:
    if p.on_team_id and p.on_team_id in data.teams:
        return data.teams[p.on_team_id][0]
    return "W" if p.status == "WAIVERS" else "FA"


def owner_name(p: Player, data: FinderData) -> str | None:
    team = data.teams.get(p.on_team_id) if p.on_team_id else None
    return team[1] if team else None


def box_value(line: StatLine | None, key: str) -> float | None:
    """One box score number of a split. ESPN leaves out the stats that are zero (a center's
    3PM in his projection), so in a split with a box score a missing count is 0."""
    if line is None:
        return None
    v = _BOX[key][1](line)
    return 0.0 if v is None and key in COUNTS and line.avg else v


def sort_value(p: Player, key: str, split: str, data: FinderData, watch: Iterable[int] = ()):
    """What column ``key`` sorts by for player ``p`` (None sorts last either way)."""
    if key in SPLITS:
        return p.fpts(key)
    if key in _BOX:
        return box_value(p.split(split), key)
    return {"own": lambda: p.owned, "change": lambda: p.owned_change, "start": lambda: p.started,
            "star": lambda: 1.0 if p.id in watch else 0.0, "name": lambda: p.name.lower(),
            "pos": lambda: p.positions or None, "owner": lambda: owner_label(p, data)}[key]()


def ordered(players: list[Player], key: str, desc: bool, split: str, data: FinderData,
            watch: Iterable[int] = ()) -> list[Player]:
    """Players sorted by one column; ties keep ESPN's order, missing values go last."""
    if key not in SORT_LABEL:
        key = DEFAULT_SPLIT
    watch = set(watch)
    vals = [(sort_value(p, key, split, data, watch), i, p) for i, p in enumerate(players)]
    have = sorted((v for v in vals if v[0] is not None), key=lambda v: (v[0], -v[1] if desc else v[1]),
                  reverse=desc)
    return [p for _, _, p in have] + [p for v, _, p in vals if v is None]


def default_desc(key: str) -> bool:
    return key not in TEXT_COLUMNS


def start_cell(p: Player, pal: Palette) -> Text:
    return Text(rostered(p.started), style=pal.dim, justify="right")


def owner_cell(p: Player, data: FinderData, pal: Palette) -> Text:
    label = owner_label(p, data)
    if p.on_team_id and p.on_team_id == data.my_team_id:
        return Text(label, style=f"bold {pal.accent}")
    if label == "W":
        return Text(label, style=pal.warn)
    return Text(label, style=pal.dim if label == "FA" else pal.text)


def star_cell(watched: bool, pal: Palette) -> Text:
    return Text("★" if watched else "", style=pal.accent)


def _trend(p: Player, key: str, pal: Palette) -> str | None:
    """good or bad when a recent split runs well above or below the season (or projection)."""
    if key not in RECENT:
        return None
    v, base = p.fpts(key), p.fpts("season") or p.fpts("proj")
    if v is None or not base:
        return None
    if v >= base * 1.15 and v - base >= 2:
        return pal.good
    if v <= base * 0.85 and base - v >= 2:
        return pal.bad
    return None


def split_cell(p: Player, key: str, selected: str, pal: Palette) -> Text:
    v = p.fpts(key)
    if v is None:
        return Text("-", style=pal.border, justify="right")
    trend = _trend(p, key, pal)
    if key == selected:
        return Text(f"{v:.1f}", style=f"bold {trend or pal.text}", justify="right")
    return Text(f"{v:.1f}", style=trend or pal.dim, justify="right")


def box_cell(p: Player, key: str, split: str, pal: Palette) -> Text:
    v = box_value(p.split(split), key)
    if v is None:
        return Text("-", style=pal.border, justify="right")
    return Text(_BOX[key][2](v), style=pal.text, justify="right")


def cell(p: Player, key: str, split: str, data: FinderData, watch, pal: Palette) -> Text:
    if key == "star":
        return star_cell(p.id in watch, pal)
    if key == "name":
        return player_cell(p, pal)
    if key == "pos":
        return Text(p.positions or p.position, style=pal.dim)
    if key == "owner":
        return owner_cell(p, data, pal)
    if key == "own":
        return rost_cell(p, pal)
    if key == "start":
        return start_cell(p, pal)
    if key in SPLITS:
        return split_cell(p, key, split, pal)
    return box_cell(p, key, split, pal)


def has_split(players: list[Player], key: str) -> bool:
    return any(key in p.stats for p in players)


def empty_message(data: FinderData, pal: Palette, app: bool = False) -> Text:
    """What to say when there is nobody to show."""
    where = SOURCES.get(data.source, "this pool")
    if data.query:
        tip = ("Press 4 to search everyone, or escape to clear the search." if app
               else "Try --from all, or a shorter name.")
        return Text.assemble((f'No players match "{data.query}" in {where}', pal.text),
                             (f"{' at ' + data.position if data.position else ''}. ", pal.text),
                             (tip, pal.dim))
    if data.source == "watch" and not data.position:
        how = ("Press 1 or 4, highlight a player and press space to add him." if app
               else 'Add one with: benchboss watch add "NAME" (or press space in the app, p).')
        return Text.assemble(("Your watch list is empty. ", pal.text), (how, pal.dim))
    pos = f" at {data.position}" if data.position else ""
    return Text(f"No players in {where}{pos}.", style=pal.text)


def _fits(renderable, width: int) -> bool:
    console = Console(width=max(width, 1) + 200, file=io.StringIO(), color_system=None)
    return Measurement.get(console, console.options, renderable).maximum <= width


def _view_key(view: int) -> str:
    return VIEWS[view][0] if 0 <= view < len(VIEWS) else DEFAULT_SPLIT


# --- the CLI drawing -----------------------------------------------------------------------------------

def draw(data: FinderData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    split = _view_key(view)
    sort = data.sort if data.sort in SORT_LABEL else DEFAULT_SPLIT
    head = fit_title(pal, width, SOURCES.get(data.source, ""), data.position, data.query,
                     SORT_LABEL[sort])
    if not data.players:
        return Group(head, Text(""), empty_message(data, pal))
    watch = set(data.watch)
    rows = ordered(data.players, sort, default_desc(sort), split, data, watch)
    keep, short = _static_columns(rows, data, split, sort, watch, width, pal)
    t = _static_table(rows, keep, data, split, watch, pal, short)
    caption = _caption(rows, keep, split, pal, width)
    return Group(head, t, caption) if caption.plain else Group(head, t)


def fit_title(pal: Palette, width: int, source: str, position: str | None, query: str | None,
              sort_label: str, count: str = "", status: str = "") -> Text:
    """ "Player finder · Free agents · C · "jok" · sorted by Proj", shortened to fit."""
    q = f'"{query}"' if query else ""
    base = [source, position or "", q]
    tries = ([*base, count, f"sorted by {sort_label}", status],
             [*base, f"sorted by {sort_label}", status], [*base, f"by {sort_label}", status],
             [*base, status], [source, status], [source])
    for ctx in tries:
        out = title(TITLE, pal, *ctx)
        if out.cell_len <= width:
            return out
    return out


def _static_columns(rows, data, split, sort, watch, width, pal) -> tuple[list[str], bool]:
    """The columns that fit ``width``, and whether names go short ("J. Butler").

    An Owner column that only says FA goes first, then the box score (from the right),
    Start%, Prev, L30, L15, L7, Pos and Avg. Then names go short, then Rost% and Owner (the
    one that says less in this pool first) and the star; names go back to full length as
    soon as a drop makes room. The selected split and the sort column always stay."""
    sel = {split, sort}
    owners = {owner_label(p, data) for p in rows}
    # the star says nothing on the watch list itself, nor Owner when everyone is a free agent
    starred = data.source != "watch" and watch & {p.id for p in rows}
    cols = [c for c in COLUMNS if (c != "star" or starred) and (c != "owner" or owners != {"FA"})]
    # a split nobody has data for (the preseason: only Proj and Prev) is only noise
    cols = [c for c in cols if c not in SPLITS or c in sel or has_split(rows, c)]
    # on a team, who has him says more than % rostered (nearly 100 for most); in free
    # agency it is the other way round
    last = ("own", "owner") if data.source in ("rostered", "all") else ("owner", "own")
    drops = [*reversed(BOX_KEYS), "start", "last", "l30", "l15", "l7", "pos", "season",
             "short", last[0], "star", last[1]]
    # measure on the rows with the widest cells (long names, injury tags, dual positions)
    widest = sorted(rows, key=lambda p: -(len(p.name) + len(p.injury) * 2 + len(p.positions)))
    sample = list({p.id: p for p in rows[:20] + widest[:20]}.values())

    def fits(short: bool) -> bool:
        return _fits(_static_table(sample, cols, data, split, watch, pal, short), width)

    short = False
    for c in (None, *drops):
        if c == "short":
            short = True
        elif c in cols and c not in sel:
            cols.remove(c)
        if fits(False):
            return cols, False
        if short and fits(True):
            return cols, True
    return cols, short


def _static_table(rows, cols, data, split, watch, pal, short: bool = False) -> Table:
    t = table(pal)
    t.collapse_padding = True
    for c in cols:
        head = HEADERS[c]
        if c == "name":
            t.add_column(head, no_wrap=True, overflow="ellipsis", min_width=8)
        elif c == "star":
            t.add_column(head, header_style=pal.accent, no_wrap=True, width=1)
        elif c in TEXT_COLUMNS or c == "own":  # Rost% heads its number, not the change after it
            t.add_column(head, no_wrap=True)
        elif c == split:
            t.add_column(head, justify="right", no_wrap=True, header_style=f"bold {pal.accent}")
        else:
            t.add_column(head, justify="right", no_wrap=True)
    for p in rows:
        t.add_row(*(player_cell(p, pal, short=True) if c == "name" and short
                    else cell(p, c, split, data, watch, pal) for c in cols))
    return t


def _caption(rows, cols, split, pal, width) -> Text:
    items = []
    if "star" in cols:
        items.append(("★", "watch list"))
    if "own" in cols:
        items.append(("Rost%", "of ESPN leagues, ▲▼ change"))
    if any(c in BOX_KEYS for c in cols):
        items.append(("Box score", f"{SPLIT_LABEL[split]}, per game"))
    if not has_split(rows, split):
        items.insert(0, (f"No {SPLIT_LABEL[split]} stats yet", ""))
    if any(_trend(p, k, pal) for p in rows for k in RECENT if k in cols):
        items.append(("green / red", "hot / cold vs the season"))
    out = Text()
    for i in range(len(items), 0, -1):  # as many as fit on one line
        out = legend(pal, *items[:i])
        if out.cell_len <= width:
            break
    return out


def to_json(data: FinderData) -> list[dict]:
    sort = data.sort if data.sort in SORT_LABEL else DEFAULT_SPLIT
    watch = set(data.watch)
    rows = ordered(data.players, sort, default_desc(sort), DEFAULT_SPLIT, data, watch)
    return [{**p.to_full_dict(), "watched": p.id in watch, "owner": owner_name(p, data)}
            for p in rows]


# --- the detail card (app) -------------------------------------------------------------------------

def _status_words(p: Player) -> str:
    raw = (p.injury_status or "").upper()
    if raw in ("", "ACTIVE", "NORMAL"):
        return "Healthy"
    return raw.replace("_", " ").capitalize()


def _ago(when: dt.datetime, now: dt.datetime) -> str:
    secs = (now - when).total_seconds()
    if secs < 3600:
        return f"{max(1, int(secs // 60))} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    local = when.astimezone(now.tzinfo) if now.tzinfo else when
    return f"{local:%b} {local.day}"


def detail(p: Player, data: FinderData, split: str, watched: bool, pal: Palette, width: int,
           news: list | None, now: dt.datetime | None, news_error: str = "") -> RenderableType:
    """The card under the table: who he is, every split with its box score, and the news."""
    head = Text()
    if watched:
        head.append("★ ", style=pal.accent)
    head.append(p.name, style=f"bold {pal.text}")
    head.append(f"  {p.pro_team}", style=pal.dim)
    head.append(f"  {p.positions or p.position}", style=pal.dim)
    team = owner_name(p, data)
    if team:
        mine = p.on_team_id == data.my_team_id
        head.append(f"  ·  {team}{' (you)' if mine else ''}", style=pal.accent if mine else pal.text)
    else:
        head.append("  ·  On waivers" if p.status == "WAIVERS" else "  ·  Free agent",
                    style=pal.warn if p.status == "WAIVERS" else pal.text)

    facts = Text()
    status = _status_words(p)
    facts.append(status, style=pal.good if status == "Healthy" else
                 (pal.bad if p.injury in ("OUT", "SUSP", "IR") else pal.warn))
    facts.append("  ·  ", style=pal.border)
    facts.append("Rostered ", style=pal.dim)
    facts.append(f"{rostered(p.owned)}%", style=pal.text)
    if abs(p.owned_change) >= 0.05:
        up = p.owned_change > 0
        facts.append(f" {'▲' if up else '▼'}{abs(p.owned_change):.1f}", style=pal.good if up else pal.bad)
    facts.append("  ·  ", style=pal.border)
    facts.append("Started ", style=pal.dim)
    facts.append(f"{rostered(p.started)}%", style=pal.text)
    if p.adp:
        facts.append("  ·  ", style=pal.border)
        facts.append("ADP ", style=pal.dim)
        facts.append(f"{p.adp:.1f}", style=pal.text)

    t = table(pal)
    t.show_edge = False
    t.add_column("Split", no_wrap=True)
    t.add_column("FPTS", justify="right", no_wrap=True)
    for _key, h, _, _ in BOX:
        t.add_column(h, justify="right", no_wrap=True)
    for k in SPLIT_KEYS:
        line = p.split(k)
        sel = k == split
        label = Text(SPLIT_LABEL[k], style=f"bold {pal.accent}" if sel else pal.dim)
        if line is None:
            t.add_row(label, Text("-", style=pal.border), *(Text("-", style=pal.border) for _ in BOX))
            continue
        cells = []
        for key, _h, _, fmt in BOX:
            v = box_value(line, key)
            cells.append(Text("-", style=pal.border) if v is None else
                         Text(fmt(v), style=pal.text if sel else pal.dim))
        t.add_row(label, Text(f"{line.fpts:.1f}", style=f"bold {pal.text}" if sel else pal.text),
                  *cells)
    while len(t.columns) > 3 and not _fits(t, width):
        t.columns.pop()

    parts: list[RenderableType] = [head, facts, Text(""), t, Text("")]
    parts.append(Text(f"News, last {NEWS_DAYS} days", style=f"bold {pal.dim}"))
    if news is None:
        parts.append(Text("Loading...", style=pal.dim))
    elif news_error:
        parts.append(Text(news_error, style=pal.dim))
    elif not news:
        parts.append(Text("Nothing new.", style=pal.dim))
    else:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True, justify="right")
        grid.add_column(ratio=1)
        for item in news[:3]:
            story = Text(item.headline, style=pal.text)
            if item.spin:
                story.append("\n" + item.spin, style=pal.dim)
            grid.add_row(Text(_ago(item.published, now) if now else "", style=pal.dim), story)
        parts.append(grid)
    if p.outlook and not news:
        parts += [Text(""), Text("Outlook", style=f"bold {pal.dim}"),
                  Text(p.outlook[:400] + ("..." if len(p.outlook) > 400 else ""), style=pal.dim)]
    return Group(*parts)


# --- the app widget -------------------------------------------------------------------------------------

# What the finder showed last in each running app, so p (or r) comes back to the same view.
_MEMORY: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

# The text color on the accent pill of the selected tab, per palette
_ON_ACCENT = {"dark": "#141518", "light": "#ffffff"}


Region = tuple[int, int, int, str, str]  # (line, start, end, kind, value), in cells


class _Bar(Static):
    """Header lines whose labels can be clicked (tabs, positions, splits)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.regions: list[Region] = []

    def show(self, text: Text, regions: list[Region]) -> None:
        self.regions = regions
        self.update(text)

    def on_click(self, event) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        hit = next((r for r in self.regions if r[0] == offset.y and r[1] <= offset.x < r[2]), None)
        finder = next((a for a in self.ancestors if isinstance(a, FinderView)), None)
        if hit is not None and finder is not None:
            event.stop()
            finder.pick(hit[3], hit[4])


class _Detail(VerticalScroll, can_focus=False):
    pass


class FinderView(Vertical):
    """The interactive finder. It binds 1 2 3 4 / [ ] < > v space * enter escape and nothing
    else, so the app's one-key menu keeps working while the table has the focus."""

    DEFAULT_CSS = """
    FinderView { height: 1fr; }
    FinderView #finder-title { height: 1; }
    FinderView #finder-top { height: 1; margin-top: 1; }
    FinderView #finder-tabs { width: 1fr; height: 1; }
    FinderView #finder-search { width: 28; height: 1; border: none; padding: 0 1;
                                background: $surface; color: $foreground; }
    FinderView #finder-search:focus { border: none; background: $panel; }
    FinderView #finder-filters { height: auto; margin-top: 1; }
    FinderView #finder-message { height: auto; margin-top: 1; display: none; }
    FinderView #finder-message.visible { display: block; }
    FinderView DataTable { height: 1fr; margin-top: 1; background: $background; }
    FinderView DataTable > .datatable--fixed { background: $surface; }
    FinderView #finder-detail { height: auto; max-height: 50%; display: none;
                                border-top: solid $accent; padding: 1 1 0 1; }
    FinderView #finder-detail.open { display: block; }
    FinderView #finder-hint { height: 1; margin-top: 1; }
    """

    BINDINGS = [
        Binding("1", "pool('fa')", "Free agents", show=False),
        Binding("2", "pool('rostered')", "On a team", show=False),
        Binding("3", "pool('watch')", "Watch list", show=False),
        Binding("4", "pool('all')", "Everyone", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("left_square_bracket", "position(-1)", "Position", show=False),
        Binding("right_square_bracket", "position(1)", "Position", show=False),
        Binding("less_than_sign", "sort_by(-1)", "Sort", show=False),
        Binding("greater_than_sign", "sort_by(1)", "Sort", show=False),
        Binding("v", "next_split", "Stats", show=False),
        Binding("space,asterisk", "toggle_watch", "Watch", show=False),
        Binding("enter", "details", "Details", show=False),
        Binding("escape", "back", "Back", show=False),
    ]

    def __init__(self, data: FinderData, app) -> None:
        super().__init__()
        self.data = data
        self.session = app.session
        self._owner_app = app
        self.source = data.source if data.source in SOURCES else "fa"
        self.position = data.position
        self.query_text = data.query
        self.split = data.sort if data.sort in SPLITS else DEFAULT_SPLIT
        self.sort_key = self.split
        self.sort_desc = True
        self.players: list[Player] = list(data.players)
        self.limit = data.n
        self.watched: set[int] = set(data.watch)
        self.loading = False
        self.error = ""
        self.detail_id: int | None = None
        self._news: dict[int, list] = {}
        self._news_errors: dict[int, str] = {}
        self._gen = 0
        self._watch_lock = threading.Lock()
        self._refetch_timer = None
        self._news_timer = None
        self._restore = None
        mem = _MEMORY.get(app)
        if mem:
            self.split, self.sort_key, self.sort_desc = mem["split"], mem["sort"], mem["desc"]
            if (mem["source"], mem["position"], mem["query"]) != (self.source, self.position,
                                                                 self.query_text):
                self._restore = mem
                self.source, self.position, self.query_text = (mem["source"], mem["position"],
                                                               mem["query"])
        self._sync_app_view()

    # --- layout ------------------------------------------------------------------------------------

    def compose(self):
        yield Static(id="finder-title")
        with Horizontal(id="finder-top"):
            yield _Bar(id="finder-tabs")
            yield Input(placeholder="/ search players", id="finder-search")
        yield _Bar(id="finder-filters")
        yield Static(id="finder-message")
        yield DataTable(id="finder-table", zebra_stripes=True, cursor_type="row", fixed_columns=2)
        with _Detail(id="finder-detail"):
            yield Static(id="finder-card")
        yield Static(id="finder-hint")

    def on_mount(self) -> None:
        self.watch(self.app, "theme", self._theme_changed, init=False)
        if self.query_text:
            self.query_one("#finder-search", Input).value = self.query_text
        if self._restore is not None:
            self._refetch()
        else:
            self._render_header()
            self._render_table(show=self.split)
            if self._fetch_sort() != self.data.sort:  # the pool came ranked by another sort
                self._maybe_refetch_sorted()

    def focus(self, scroll_visible: bool = True):
        self.query_one(DataTable).focus(scroll_visible)
        return self

    def on_resize(self) -> None:
        self._render_header()
        if self.detail_id is not None:
            self._render_detail()

    @property
    def pal(self) -> Palette:
        return getattr(self._owner_app, "pal", DARK)

    def _theme_changed(self) -> None:
        self._render_all()

    def _sync_app_view(self, announce: bool = False) -> None:
        """Keep the app's view index (its status line says "Projected · v for Last season")
        on the split shown here."""
        from benchboss.ui.screens import SCREENS

        views = getattr(self._owner_app, "views", None)
        sid = next((k for k, m in SCREENS.items() if m.__name__ == __name__), None)
        if isinstance(views, dict) and sid:
            views[sid] = SPLIT_KEYS.index(self.split)
            status = getattr(self._owner_app, "_status_views", None)
            if announce and callable(status) and getattr(self._owner_app, "current", None) == sid:
                status()

    def _remember(self) -> None:
        _MEMORY[self._owner_app] = {"source": self.source, "position": self.position,
                                    "query": self.query_text, "split": self.split,
                                    "sort": self.sort_key, "desc": self.sort_desc}

    # --- drawing -----------------------------------------------------------------------------------

    def _view_data(self) -> FinderData:
        d = self.data
        return FinderData(self.players, self.source, tuple(self.watched), self.position, self.sort_key,
                          self.query_text, self.limit, d.teams, d.my_team_id)

    def _render_all(self) -> None:
        self._render_header()
        self._render_table()
        self._render_detail()

    def _render_header(self) -> None:
        pal = self.pal
        width = max(20, self.size.width or 100)
        count = "" if self.loading else (f"{len(self.players)} player{'s' * (len(self.players) != 1)}"
                                         if self.players else "")
        order = "▼" if self.sort_desc else "▲"
        self.query_one("#finder-title", Static).update(fit_title(
            pal, width, SOURCES[self.source], self.position, self.query_text,
            f"{SORT_LABEL.get(self.sort_key, self.sort_key)} {order}", count,
            "Loading..." if self.loading else ""))
        tabs, regions = self._tabs(pal, width)
        self.query_one("#finder-tabs", _Bar).show(tabs, regions)
        self.query_one("#finder-search", Input).styles.width = max(SEARCH_MIN, min(SEARCH_WIDTH,
                                                                                   width - tabs.cell_len))
        self.query_one("#finder-filters", _Bar).show(*self._filters(pal, width))
        self._render_hint()

    def _render_hint(self) -> None:
        width = max(20, self.size.width or 100)
        self.query_one("#finder-hint", Static).update(self._hint(self.pal, width))

    def _tabs(self, pal: Palette, width: int) -> tuple[Text, list[Region]]:
        """ "1 Free agents  2 On a team  3 Watch list  4 Everyone", the current one a pill;
        short names when the long ones and the search box do not fit, and only the digits of
        the other pools when the short names and the smallest search box do not either."""
        short = {"fa": "FA", "rostered": "Teams", "watch": "Watch", "all": "All"}
        digits = {k: v if k == self.source else "" for k, v in short.items()}
        for names, search in ((SOURCES, SEARCH_WIDTH), (short, SEARCH_MIN), (digits, 0)):
            out, regions = Text(), []
            for i, key in enumerate(TABS):
                start = out.cell_len
                if key == self.source:
                    out.append(f" {i + 1} {names[key]} ",
                               style=f"bold {_ON_ACCENT.get(pal.name, '#ffffff')} on {pal.accent}")
                else:
                    out.append(f" {i + 1}", style=f"bold {pal.dim}")
                    out.append(f" {names[key]} " if names[key] else " ", style=pal.text)
                regions.append((0, start, out.cell_len, "pool", key))
                out.append(" ")
            if out.cell_len + search <= width:
                break
        return out, regions

    def _filters(self, pal: Palette, width: int) -> tuple[Text, list[Region]]:
        """ "Pos All PG SG ...    Stats Season L7 ...", the current ones in accent. On a narrow
        window the splits go on a second line."""
        def part(head: str, options: list[tuple[str, str, str]], kind: str):
            out, regions = Text(), []
            out.append(head, style=f"bold {pal.dim}")
            for value, label, style in options:
                start = out.cell_len
                out.append(f" {label} ", style=style)
                regions.append((start, out.cell_len, kind, value))
            return out, regions

        def look(on: bool, empty: bool = False) -> str:
            return f"bold {pal.accent}" if on else (pal.border if empty else pal.dim)

        positions = [(p or "All", p or "All", look(p == self.position)) for p in POSITIONS]
        # a split nobody has numbers for yet (the preseason) is drawn faint
        splits = [(k, SPLIT_PICK[k], look(k == self.split, bool(self.players)
                                          and not has_split(self.players, k)))
                  for k in SPLIT_KEYS]
        pos, pos_at = part("Pos ", positions, "pos")
        stats, stats_at = part("Stats ", splits, "split")
        gap = " " * 4
        if pos.cell_len + len(gap) + stats.cell_len <= width:
            hints = pos.cell_len + len(gap) + stats.cell_len + 6 <= width
            if hints:
                pos.append(" [ ]", style=pal.border)
                stats.append(" v", style=pal.border)
            shift = pos.cell_len + len(gap)
            return (Text.assemble(pos, gap, stats),
                    [(0, *r) for r in pos_at] + [(0, a + shift, b + shift, k, v) for a, b, k, v in stats_at])
        pos, pos_at = part("Pos   ", positions, "pos")  # lined up with "Stats "
        for line, hint in ((pos, " [ ]"), (stats, " v")):
            if line.cell_len + len(hint) <= width:
                line.append(hint, style=pal.border)
        return Text.assemble(pos, "\n", stats), [(0, *r) for r in pos_at] + [(1, *r) for r in stats_at]

    def _hint(self, pal: Palette, width: int) -> Text:
        current = self._current()
        watched = current is not None and current.id in self.watched
        card = ("esc", "close card") if self.detail_id is not None else ("enter", "details")
        items = [("space", "unwatch" if watched else "watch"), card, ("/", "search"),
                 ("1-4", "pool"), ("[ ]", "position"), ("v", "stats"), ("< >", "sort")]
        out = Text()
        for i in range(len(items), 0, -1):
            out = legend(pal, *items[:i])
            if out.cell_len <= width:
                break
        return out

    def _columns(self) -> list[str]:
        """Every column, except splits nobody has numbers for (the preseason)."""
        keep = {self.split, self.sort_key, DEFAULT_SPLIT}
        return [c for c in COLUMNS if c not in SPLITS or c in keep or has_split(self.players, c)]

    def _render_table(self, keep_id: int | None = None, show: str | None = None) -> None:
        """Rebuild the table: same player under the cursor, same horizontal scroll, and the
        column ``show`` (the split or the sort just picked) scrolled into view."""
        pal = self.pal
        t = self.query_one(DataTable)
        if keep_id is None:
            keep_id = self._current_id()
        data = self._view_data()
        scroll_x = t.scroll_x
        t.clear(columns=True)
        t.show_header = bool(self.players)  # an empty pool shows its message, not bare headers
        cols = self._columns()
        for c in cols:
            label = HEADERS[c]
            style = f"bold {pal.accent}" if c == self.split else ""
            if c == self.sort_key:
                label = f"{label} {'▼' if self.sort_desc else '▲'}"
                style = style or f"bold {pal.text}"
            justify = "left" if c in TEXT_COLUMNS or c in ("star", "own") else "right"
            t.add_column(Text(label, style=style, justify=justify), key=c)
        rows = ordered(self.players, self.sort_key, self.sort_desc, self.split, data, self.watched)
        seen: set[int] = set()
        for p in rows:
            if p.id in seen:
                continue
            seen.add(p.id)
            t.add_row(*(cell(p, c, self.split, data, self.watched, pal) for c in cols), key=str(p.id))
        if keep_id is not None and str(keep_id) in t.rows:
            t.move_cursor(row=t.get_row_index(str(keep_id)))
        self.call_after_refresh(self._scroll_columns, scroll_x, show)
        message: Text | None = None
        if self.loading and not self.players:
            message = Text("Loading...", style=pal.dim)
        elif self.error:
            message = Text(self.error, style=pal.bad)
        elif not self.players:
            message = empty_message(data, pal, app=True)
        elif not has_split(self.players, self.split):
            message = Text(f"No {SPLIT_LABEL[self.split]} stats yet. Press v for another split.",
                           style=pal.dim)
        msg = self.query_one("#finder-message", Static)
        msg.update(message or "")
        msg.set_class(message is not None, "visible")

    def _scroll_columns(self, scroll_x: float, show: str | None) -> None:
        """Put the horizontal scroll back, then bring column ``show`` into view (the fixed
        columns, star and Player, never scroll). The scrolled part starts on a whole column,
        so no stray half of one sits next to the names."""
        if not self.is_attached:
            return
        t = self.query_one(DataTable)
        x = scroll_x
        keys = [c.key.value for c in t.ordered_columns]
        widths = [c.get_render_width(t) for c in t.ordered_columns]
        fixed = sum(widths[:t.fixed_columns])
        if show in keys:
            i = keys.index(show)
            left, right = sum(widths[:i]), sum(widths[:i + 1])
            view = t.scrollable_content_region.width
            if right > x + view:
                x = right - view
            if left < x + fixed:
                x = left - fixed
        starts = [sum(widths[:j]) - fixed for j in range(t.fixed_columns, len(widths))]
        x = next((s for s in starts if s >= x), x)
        t.scroll_to(x=max(0, x), animate=False)

    def _render_detail(self) -> None:
        p = self._player(self.detail_id)
        self.detail_id = p.id if p else None
        self.query_one("#finder-detail").set_class(p is not None, "open")
        self._render_hint()  # enter details, or esc close card
        if p is None:
            return
        width = max(30, (self.size.width or 100) - 4)
        now = getattr(self.session, "now", None)
        card = detail(p, self._view_data(), self.split, p.id in self.watched, self.pal, width,
                      self._news.get(p.id), now, self._news_errors.get(p.id, ""))
        self.query_one("#finder-card", Static).update(card)

    # --- helpers -----------------------------------------------------------------------------------

    def _player(self, pid: int | None) -> Player | None:
        if pid is None:
            return None
        return next((p for p in self.players if p.id == pid), None)

    def _current_id(self) -> int | None:
        t = self.query_one(DataTable)
        if not t.row_count:
            return None
        try:
            key = t.ordered_rows[t.cursor_row].key.value
        except IndexError:
            return None
        return int(key) if key is not None else None

    def _current(self) -> Player | None:
        try:
            return self._player(self._current_id())
        except Exception:
            return None

    # --- actions -----------------------------------------------------------------------------------

    def pick(self, kind: str, value: str) -> None:
        """A click on a tab, a position or a split in the header."""
        if kind == "pool":
            self.action_pool(value)
        elif kind == "pos":
            self._set_position(None if value == "All" else value)
        elif kind == "split":
            self._set_split(value)
        self.focus()

    def action_pool(self, source: str) -> None:
        if source == self.source or source not in SOURCES:
            return
        self.source = source
        self.detail_id = None
        self._refetch()

    def action_position(self, step: int) -> None:
        i = POSITIONS.index(self.position) if self.position in POSITIONS else 0
        self._set_position(POSITIONS[(i + step) % len(POSITIONS)])

    def _set_position(self, position: str | None) -> None:
        if position == self.position:
            return
        self.position = position
        self._refetch()

    def action_next_split(self) -> None:
        """v: the next split with numbers (in the preseason only Proj and Prev have any)."""
        i = SPLIT_KEYS.index(self.split)
        for k in SPLIT_KEYS[i + 1:] + SPLIT_KEYS[:i]:
            if k == DEFAULT_SPLIT or not self.players or has_split(self.players, k):
                self._set_split(k)
                return

    def _set_split(self, split: str) -> None:
        if split == self.split or split not in SPLITS:
            return
        if self.sort_key == self.split:  # the default sort follows the split
            self.sort_key, self.sort_desc = split, True
        self.split = split
        self._remember()
        self._sync_app_view(announce=True)
        self._render_header()
        self._render_table(show=split)
        self._render_detail()
        self._maybe_refetch_sorted()

    def action_sort_by(self, step: int) -> None:
        cols = self._columns()
        i = cols.index(self.sort_key) if self.sort_key in cols else 0
        self._sort(cols[(i + step) % len(cols)])

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        event.stop()
        key = event.column_key.value
        if key == self.sort_key:
            self.sort_desc = not self.sort_desc
            self._remember()
            self._render_all()
        elif key:
            self._sort(key)

    def _sort(self, key: str) -> None:
        self.sort_key, self.sort_desc = key, default_desc(key)
        self._remember()
        self._render_header()
        self._render_table(show=key)
        self._maybe_refetch_sorted()

    def action_search(self) -> None:
        self.query_one("#finder-search", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        query = event.value.strip() or None
        self.query_one(DataTable).focus()
        if query != self.query_text:
            self.query_text = query
            self._refetch()

    def action_back(self) -> None:
        """escape: leave the search box, else close the card, else clear the search."""
        search = self.query_one("#finder-search", Input)
        if search.has_focus:
            search.value = ""
            self.query_one(DataTable).focus()
            if self.query_text:
                self.query_text = None
                self._refetch()
            return
        if self.detail_id is not None:
            self.detail_id = None
            self._render_detail()
            return
        if self.query_text:
            search.value = ""
            self.query_text = None
            self._refetch()

    def action_details(self) -> None:
        p = self._current()
        if p is not None:
            self._open_detail(p)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        pid = int(event.row_key.value) if event.row_key.value is not None else None
        if pid is not None and pid == self.detail_id:
            self.detail_id = None  # enter on the open card closes it
            self._render_detail()
            return
        p = self._player(pid)
        if p is not None:
            self._open_detail(p)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self._render_hint()
        if self.detail_id is None or event.row_key.value is None:
            return
        p = self._player(int(event.row_key.value))
        if p is not None and p.id != self.detail_id:
            self._open_detail(p, wait=0.3)  # browsing with the card open: the news follows

    def _open_detail(self, p: Player, wait: float = 0.0) -> None:
        self.detail_id = p.id
        self._render_detail()
        if self._news_timer is not None:
            self._news_timer.stop()
            self._news_timer = None
        if p.id in self._news:
            return
        if wait:
            self._news_timer = self.set_timer(wait, lambda: self._fetch_news(p.id))
        else:
            self._fetch_news(p.id)

    def action_toggle_watch(self) -> None:
        p = self._current()
        if p is None:
            return
        on = p.id not in self.watched
        # The watch list is the one write the app makes without an Apply step, on purpose: it
        # is private (nobody else in the league sees it), instant and reversible with the same
        # key, like the star in the ESPN app. The star changes now; ESPN is told in a worker
        # thread and the star rolls back if ESPN says no.
        self._set_star(p.id, on)
        verb = "Added" if on else "Removed"
        self.app.notify(f"{verb} {p.name} {'to' if on else 'from'} your watch list",
                        title="Watch list", timeout=4)
        self._send_watch(p.id, self.app)

    def _set_star(self, pid: int, on: bool) -> None:
        if on:
            self.watched.add(pid)
        else:
            self.watched.discard(pid)
        if not self.is_attached:
            return
        t = self.query_one(DataTable)
        if str(pid) in t.rows and "star" in t.columns:
            t.update_cell(str(pid), "star", star_cell(on, self.pal))
        self._render_hint()
        if self.detail_id == pid:
            self._render_detail()

    @work(thread=True, group="finder-watch")
    def _send_watch(self, pid: int, app) -> None:
        # ESPN gets the whole list, so one change at a time; and the star as it is now, not
        # as it was at the key press, so quick presses end where the star ends
        try:
            with self._watch_lock:
                on = pid in self.watched
                ids = self.session.set_watched(pid, on)
        except Exception as e:  # roll back the star and say why
            msg = str(e) if isinstance(e, BenchbossError) else f"{type(e).__name__}: {e}"
            app.call_from_thread(self._set_star, pid, not on)
            app.call_from_thread(app.notify, f"Could not update your watch list: {msg}",
                                 title="Watch list", severity="error", timeout=8)
            return
        app.call_from_thread(self._watch_saved, pid, on, tuple(ids))

    def _watch_saved(self, pid: int, on: bool, ids: tuple[int, ...]) -> None:
        if (pid in ids) != on:  # ESPN kept the old state: show what it has
            self._set_star(pid, pid in ids)

    # --- fetching ----------------------------------------------------------------------------------

    def _fetch_sort(self) -> str:
        return self.sort_key if self.sort_key in SPLITS or self.sort_key == "own" else self.split

    def _maybe_refetch_sorted(self) -> None:
        """ESPN sends the top players by one sort: when the pool was cut there, a new sort
        may bring in players who were not sent. Ask again, quietly, after a short pause."""
        if len(self.players) < self.limit or self.source == "watch":
            return
        if self._refetch_timer is not None:
            self._refetch_timer.stop()
        self._refetch_timer = self.set_timer(0.4, lambda: self._refetch(quiet=True))

    def _refetch(self, quiet: bool = False) -> None:
        self._remember()
        self._gen += 1
        self.loading = True
        self.error = ""
        self.limit = POOL_SIZE
        if not quiet:
            self.players = []
            self.detail_id = None
        self._render_all()
        self._fetch(self._gen, self.source, self.position, self._fetch_sort(), self.query_text)

    @work(thread=True, exclusive=True, group="finder-pool")
    def _fetch(self, gen: int, source: str, position: str | None, sort: str,
               query: str | None) -> None:
        players, err = [], ""
        try:
            players = self.session.player_pool(source, position, POOL_SIZE, sort, query)
        except BenchbossError as e:
            err = str(e)
        except Exception as e:  # never let a bad payload kill the app
            err = f"{type(e).__name__}: {e}"
        if get_current_worker().is_cancelled:
            return
        self._owner_app.call_from_thread(self._fetched, gen, players, err)

    def _fetched(self, gen: int, players: list[Player], err: str) -> None:
        if gen != self._gen or not self.is_attached:
            return  # a newer request is on its way, or the finder is gone
        keep = self._current_id()
        self.loading = False
        self.error = err
        if not err:
            self.players = players
        self._render_header()
        self._render_table(keep_id=keep, show=self.split if self.sort_key == self.split else None)
        self._render_detail()

    @work(thread=True, exclusive=True, group="finder-news")
    def _fetch_news(self, pid: int) -> None:
        try:
            items, err = self.session.news([pid], NEWS_DAYS), ""
        except Exception as e:  # the card still shows the stats
            items, err = [], "News is not available right now."
            if isinstance(e, BenchbossError):
                err = f"News is not available right now: {e}"
        if get_current_worker().is_cancelled:
            return
        self._owner_app.call_from_thread(self._news_loaded, pid, items, err)

    def _news_loaded(self, pid: int, items: list, err: str) -> None:
        self._news[pid] = items
        if err:
            self._news_errors[pid] = err
        if self.is_attached and self.detail_id == pid:
            self._render_detail()


def widget(data: FinderData, app) -> FinderView:
    return FinderView(data, app)

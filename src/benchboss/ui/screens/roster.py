"""Roster: your players by lineup slot, with every stat split ESPN keeps.

One table: starters in slot order, then the bench, then IR. Fantasy points per game for
every split side by side (Avg L7 L15 L30 Proj Prev), then the per-game box score of the
split the view selects (v in the app, --view in the CLI), then ownership in ESPN leagues.
A narrow screen loses the secondary columns first and only then shortens the names.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from rich import box
from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.table import Table
from rich.text import Text

from benchboss.espn.constants import AST, BENCH, BLK, IR, PTS, REB, SLOT, SPLIT_SHORT, STL, TO, TPM
from benchboss.espn.models import League, Player, RosterSpot, StatLine, Team
from benchboss.ui.common import legend, num, player_cell, rost_cell, scale, shooting_pct, title
from benchboss.ui.theme import Palette

TITLE = "Roster"
VIEWS: tuple[tuple[str, str], ...] = (("season", "Season"), ("l7", "Last 7"), ("l15", "Last 15"),
                                      ("l30", "Last 30"), ("proj", "Projected"),
                                      ("last", "Last season"))
SPLITS = tuple(k for k, _ in VIEWS)
LONG = {"season": "This season", "l7": "Last 7 days", "l15": "Last 15 days", "l30": "Last 30 days",
        "proj": "Projected", "last": "Last season"}

GAP = 2        # columns between two table columns
BLOCK_GAP = 2  # extra columns between two blocks (who, fantasy points, box score, ownership)
TREND = 0.10   # L7 is "clearly" above or below the season average past 10% (and 3 points)

# What goes first when the screen is too narrow, in order. "splits" is every split column
# but the selected one, Avg and Proj; "base" is Avg (or Prev before any game is played).
DROPS: tuple[tuple[str, ...], ...] = (
    ("rost",),
    ("fg", "ft", "to", "3pm"),
    ("gp", "min", "stl", "blk"),
    ("splits",),
    ("pos",),
    ("pts", "reb", "ast"),
    ("base",),
    ("today",),
)
# Then the names: full with the NBA team, short with the team, short alone.
NAMES = ((False, True), (True, True), (True, False))

BOX = box.Box(  # SIMPLE_HEAD, plus a thin dashed rule between starters, bench and IR
    "    \n"
    "    \n"
    " ── \n"
    "    \n"
    " ┄┄ \n"
    " ── \n"
    "    \n"
    "    \n"
)


@dataclass
class RosterData:
    league: League
    plays_today: set[int] = field(default_factory=set)
    opponents: dict[int, str] = field(default_factory=dict)  # player id -> "LAC" or "@BOS" today
    in_season: bool = True
    marked: dict[int, str] = field(default_factory=dict)  # player id -> auto-swap mark mode


def load(session) -> RosterData:
    lg, cal = session.league(), session.calendar
    day = cal.period_of(session.today)  # not clamped: before or after the season nobody plays
    in_season = 1 <= day <= cal.final_period
    opponents = {}
    for s in lg.me.roster if in_season else ():
        game = cal.game(s.player.pro_team_id, day)
        if game:
            opponents[s.player.id] = _opponent(game.opponent(s.player.pro_team_id))
    from benchboss.marks import MarkStore  # a local file: never fails the roster

    marked = {pid: m.mode for pid, m in MarkStore(session).load().marks.items()}
    return RosterData(lg, set(opponents), opponents, in_season, marked)


def _opponent(text: str) -> str:
    """ "vs LAC" -> "LAC", "@ BOS" -> "@BOS"."""
    return text.replace("vs ", "").replace("@ ", "@")


# --- rows ---------------------------------------------------------------------------------------

@dataclass
class _Row:
    slot: str
    spot: RosterSpot | None = None  # None: an empty starting slot

    @property
    def player(self) -> Player | None:
        return self.spot.player if self.spot else None


def _sections(league: League) -> list[list[_Row]]:
    """Starters in slot order (an empty slot gets its own row), then the bench, then IR."""
    me = league.me
    by_proj = sorted(me.roster, key=lambda s: -s.player.proj)
    starters: list[_Row] = []
    for sid in sorted((set(league.slot_counts) | {s.slot_id for s in me.roster}) - {BENCH, IR}):
        here = [_Row(s.slot, s) for s in by_proj if s.slot_id == sid]
        empty = max(0, league.slot_counts.get(sid, 0) - len(here))
        starters += here + [_Row(SLOT.get(sid, str(sid))) for _ in range(empty)]
    bench = [_Row(s.slot, s) for s in by_proj if s.slot_id == BENCH]
    ir = [_Row(s.slot, s) for s in by_proj if s.slot_id == IR]
    return [rows for rows in (starters, bench, ir) if rows]


def _trend(p: Player) -> int:
    """+1 when the last 7 days are clearly above the season average, -1 clearly below."""
    week, season = p.split("l7"), p.fpts("season")
    if week is None or season is None or week.gp < 2:
        return 0
    diff = week.fpts - season
    if abs(diff) < max(3.0, TREND * abs(season)):
        return 0
    return 1 if diff > 0 else -1


# --- columns ------------------------------------------------------------------------------------

@dataclass
class _Col:
    key: str
    header: str
    cells: list[Text]
    block: str                    # who, fpts, box, own
    justify: str = "right"
    header_style: str | None = None

    @property
    def width(self) -> int:
        return max([cell_len(self.header)] + [c.cell_len for c in self.cells])


@dataclass
class _Layout:
    """Everything that decides which columns the table shows."""
    sel: str                      # the split whose box score is shown and highlighted
    base: str                     # season, or last before any game
    hidden: set[str]              # column keys left out
    short: bool = False
    team: bool = True


# the counting stats of the box score: (column key, header, stat id, its leader is colored)
BOX_STATS = (("pts", "PTS", PTS, True), ("reb", "REB", REB, True), ("ast", "AST", AST, True),
             ("stl", "STL", STL, True), ("blk", "BLK", BLK, True), ("3pm", "3PM", TPM, True),
             ("to", "TO", TO, False))


def _count(stat: int) -> Callable[[StatLine], float | None]:
    """A counting stat per game. ESPN leaves zeros out of the projections (a center with no
    threes has no 3PM key), so a split with a box score reads a missing stat as 0."""
    return lambda s: s.avg.get(stat, 0.0) if s.avg else None


def _columns(rows: list[_Row], data: RosterData, lay: _Layout, pal: Palette) -> list[_Col]:
    """The visible columns for one layout, cells in row order."""
    players = [r.player for r in rows]
    blank = Text("")
    cols: list[_Col] = []

    def add(key: str, header: str, block: str, cells: Iterable[Text], **kw) -> None:
        if key not in lay.hidden:
            cols.append(_Col(key, header, list(cells), block, **kw))

    def each(fn: Callable[[Player], Text]) -> list[Text]:
        return [fn(p) if p else blank for p in players]

    add("slot", "Slot", "who", [Text(r.slot, style=pal.dim) for r in rows], justify="left")
    add("player", "Player", "who",
        [player_cell(r.player, pal, short=lay.short, team=lay.team,
                     style=pal.dim if r.spot.slot_id == IR else None).append(*{
                         "auto": (" ✓", pal.good), "notify": (" !", pal.warn)}.get(
                         data.marked.get(r.player.id), ("",)))
         if r.player else Text("Empty", style=f"italic {pal.dim}") for r in rows],
        justify="left")
    add("pos", "Pos", "who", each(lambda p: Text(p.positions, style=pal.dim)), justify="left")
    add("today", "Today", "who", each(lambda p: _today(p, data, pal)))

    # fantasy points per game, every split; the trend arrow rides on L7 (or on Avg without it),
    # in front of the number: right-justified cells lose trailing spaces, so an arrow after
    # the number would push the decimal points out of line
    shown = [k for k in SPLITS if _split_visible(k, lay)]
    arrow_on = "l7" if "l7" in shown else "season" if "season" in shown else None
    for k in shown:
        style = f"bold {pal.text}" if k == lay.sel else pal.dim

        def cell(p: Player, k=k, style=style) -> Text:
            v = p.fpts(k)
            out = Text(num(v), style=style if v is not None else pal.border)
            t = _trend(p) if k == arrow_on else 0
            if t:
                out = Text.assemble(("▲" if t > 0 else "▼", pal.good if t > 0 else pal.bad), out)
            return out

        add(f"fp_{k}", SPLIT_SHORT[k], "fpts", each(cell),
            header_style=f"bold {pal.accent}" if k == lay.sel else None)

    # the box score of the selected split
    lines = [p.split(lay.sel) if p else None for p in players]
    present = [ln for ln in lines if ln is not None]

    def stat(key: str, header: str, get: Callable[[StatLine], float | None],
             fmt: Callable[[float], str] = num, lead: bool = False) -> None:
        pool = [get(ln) for ln in present]

        def one(ln: StatLine | None) -> Text:
            if ln is None:
                return Text("-", style=pal.border)
            v = get(ln)
            if v is None:
                return Text("-", style=pal.border)
            return Text(fmt(v), style=_leader(v, pool, pal) if lead else pal.text)

        add(key, header, "box",
            [one(ln) if p else blank for ln, p in zip(lines, players, strict=True)])

    stat("gp", "GP", lambda s: s.gp or None, "{:.0f}".format)
    stat("min", "MIN", lambda s: s.mpg)
    for key, header, stat_id, lead in BOX_STATS:
        stat(key, header, _count(stat_id), lead=lead)
    stat("fg", "FG%", lambda s: s.fg_pct, shooting_pct)
    stat("ft", "FT%", lambda s: s.ft_pct, shooting_pct)

    # ownership across ESPN leagues, the same cell as every other screen ("46 ▲1.7")
    add("rost", "Rost%", "own", each(lambda p: rost_cell(p, pal)), justify="left")
    return cols


def _split_visible(k: str, lay: _Layout) -> bool:
    if f"fp_{k}" in lay.hidden:
        return False
    if k in (lay.sel, "proj"):
        return True
    if k == lay.base:
        return "base" not in lay.hidden
    return "splits" not in lay.hidden


def _leader(v: float, pool: list[float | None], pal: Palette) -> str:
    """The roster's best value in a column stands out, nothing else: a handful of colored
    numbers on the whole screen, so each one means something. ``scale`` keeps a flat column
    (everyone at 0.0 blocks) or a tiny roster plain."""
    best = max((x for x in pool if x is not None), default=None)
    return pal.good if v == best and scale(v, pool, pal) == pal.good else pal.text


def _today(p: Player, data: RosterData, pal: Palette) -> Text:
    opp = data.opponents.get(p.id) or ("●" if p.id in data.plays_today else "")
    if not opp:
        return Text("·", style=pal.border)
    return Text(opp, style=pal.dim if p.injury in ("OUT", "SUSP", "IR") else pal.text)


def _widths(cols: list[_Col]) -> list[int]:
    """Content width of each column, with the extra gap in front of each new block."""
    out = []
    for i, c in enumerate(cols):
        out.append(c.width + (BLOCK_GAP if i and c.block != cols[i - 1].block else 0))
    return out


def _total(widths: list[int]) -> int:
    return sum(widths) + GAP * (len(widths) - 1)


def _layouts(sel: str, base: str, hidden: set[str]):
    """Every layout from the widest to the narrowest (see DROPS and NAMES)."""
    gone = set(hidden)
    yield _Layout(sel, base, set(gone))
    for step in DROPS:
        gone |= set(step)
        yield _Layout(sel, base, set(gone))
    for short, team in NAMES[1:]:
        yield _Layout(sel, base, set(gone), short=short, team=team)


def _fit(rows: list[_Row], data: RosterData, sel: str, base: str, hidden: set[str], pal: Palette,
         width: int) -> tuple[list[_Col], list[int], _Layout]:
    for lay in _layouts(sel, base, hidden):
        cols = _columns(rows, data, lay, pal)
        widths = _widths(cols)
        if _total(widths) <= width:
            return cols, widths, lay
    # narrower than the narrowest layout: the player column gives way (ellipsis)
    i = next(i for i, c in enumerate(cols) if c.key == "player")
    widths[i] = max(4, widths[i] - (_total(widths) - width))
    return cols, widths, lay


# --- drawing ------------------------------------------------------------------------------------

class RosterTable(Table):
    """The roster table, with its title line above and its legend below drawn at the full
    width given (a Table title or caption would wrap at the table's own width)."""

    def __init__(self, *args, above: Iterable[RenderableType] = (),
                 below: Iterable[RenderableType] = (), **kwargs):
        super().__init__(*args, **kwargs)
        self.above = list(above)
        self.below = list(below)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from self.above
        yield from super().__rich_console__(console, options)
        yield from self.below


def _group_line(cols: list[_Col], widths: list[int], lay: _Layout, pal: Palette) -> Text | None:
    """ "──── Fantasy points per game ────" over each block of numbers."""
    labels = {"fpts": ("Fantasy points per game", "Fantasy pts per game", "FPTS per game",
                       "FPTS"),
              "box": (f"{LONG[lay.sel]}, per game", f"{dict(VIEWS)[lay.sel]}, per game",
                      f"{SPLIT_SHORT[lay.sel]} per game", "Per game")}
    out, x, i = Text(), 0, 0
    while i < len(cols):
        j = i
        while j + 1 < len(cols) and cols[j + 1].block == cols[i].block:
            j += 1
        start = x + (widths[i] - cols[i].width)  # skip the block gap
        end = x + sum(widths[i:j + 1]) + GAP * (j - i)
        span = end - start
        # " label " with at least two dashes on each side, or no label over this block
        label = next((t for t in labels.get(cols[i].block, ()) if cell_len(t) + 6 <= span), None)
        if label:
            out.append(" " * (start - out.cell_len))
            left = (span - cell_len(label) - 2) // 2
            right = span - cell_len(label) - 2 - left
            out.append("─" * left, style=pal.border)
            out.append(f" {label} ", style=pal.accent if cols[i].block == "box" else pal.dim)
            out.append("─" * right, style=pal.border)
        x = end + GAP
        i = j + 1
    return out if out.cell_len else None


def _legend(cols: list[_Col], pal: Palette, width: int) -> Text:
    """The abbreviations on screen, in column order. When they do not fit on one line the
    most familiar ones go first (Proj, then Avg and the windows), the trend arrows last."""
    keys = {c.key for c in cols}
    items: list[tuple[int, str, str]] = []  # (keep priority, key, meaning)
    if "fp_season" in keys:
        items.append((1, "Avg", "this season"))
    windows = [k for k in ("l7", "l15", "l30") if f"fp_{k}" in keys]
    if windows:
        items.append((1, " ".join(SPLIT_SHORT[k] for k in windows),
                      f"last {', '.join(k[1:] for k in windows)} days"))
    if "fp_proj" in keys:
        items.append((0, "Proj", "ESPN projection"))
    if "fp_last" in keys:
        items.append((2, "Prev", "last season"))
    if any(c.plain.startswith(("▲", "▼")) for col in cols for c in col.cells):
        week = "L7" if "fp_l7" in keys else "last 7 days"
        items.append((4, "▲▼", f"{week} well above or below Avg"))
    if "rost" in keys:
        items.append((3, "Rost%", "of ESPN leagues, ▲▼ change in a week"))
    while items and legend(pal, *[i[1:] for i in items]).cell_len > width:
        items.remove(min(items))
    return legend(pal, *[i[1:] for i in items])


def _title(me: Team, want: str, sel: str, played: bool, pal: Palette, width: int) -> Text:
    """ "Roster · Monstars 2-0 · Last 7 days", shortened until it fits on one line. When the
    selected split has no data (the preseason) it says what is shown instead."""
    team = f"{me.name} {me.record}"
    if sel == want:
        tries = [(team, LONG[want]), (me.name, LONG[want]), (LONG[want],)]
    else:
        why = ("no projections" if want == "proj" else "no stats last season" if want == "last"
               else "no recent games" if played else "no games yet")
        instead = "projections" if sel == "proj" else LONG[sel].lower()
        note = f"{why}, showing {instead}"
        tries = [(team, LONG[want], note), (team, note), (team, why), (me.name, why), (why,)]
    for parts in tries:
        line = title(TITLE, pal, *parts)
        if line.cell_len <= width:
            return line
    return line


def draw(data: RosterData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    me = data.league.me
    want = VIEWS[view % len(VIEWS)][0]
    sections = _sections(data.league)
    rows = [r for sec in sections for r in sec]
    players = [r.player for r in rows if r.player]
    if not players:  # before the draft
        return Group(_title(me, want, want, False, pal, width), Text(""),
                     Text("No players yet.", style=pal.dim))
    has = {k: any(p.split(k) for p in players) for k in SPLITS}
    # a split nobody has data for shows the closest one that has some: in the preseason
    # (only proj and last exist) that is the projection
    sel = want if has[want] else next((k for k in ("season", "proj", "last") if has[k]), want)
    base = "season" if has["season"] else "last"
    hidden = {f"fp_{k}" for k in SPLITS if not has[k] and k != sel}
    if not data.in_season:
        hidden.add("today")
    cols, widths, lay = _fit(rows, data, sel, base, hidden, pal, width)

    head: list[RenderableType] = [_title(me, want, sel, has["season"], pal, width), Text("")]
    groups = _group_line(cols, widths, lay, pal)
    if groups is not None:
        head.append(groups)
    t = RosterTable(box=BOX, show_edge=False, padding=(0, 1, 0, 0), pad_edge=False,
                    header_style=f"bold {pal.dim}", border_style=pal.border, expand=False,
                    above=head,
                    below=[Text(""), _legend(cols, pal, min(width, max(30, _total(widths))))])
    for c, w in zip(cols, widths, strict=True):
        t.add_column(c.header, justify=c.justify, header_style=c.header_style, width=w,
                     no_wrap=True, overflow="ellipsis")
    i = 0
    for n, sec in enumerate(sections):
        for r in range(len(sec)):  # a thin rule after the starters and after the bench
            last_of_section = r == len(sec) - 1 and n < len(sections) - 1
            t.add_row(*(c.cells[i] for c in cols), end_section=last_of_section)
            i += 1
    return t


def to_json(data: RosterData) -> list[dict]:
    return [{"slot": r.slot, "plays_today": r.player.id in data.plays_today,
             "opponent_today": data.opponents.get(r.player.id),
             "autoswap": data.marked.get(r.player.id), **r.player.to_full_dict()}
            for sec in _sections(data.league) for r in sec if r.player]

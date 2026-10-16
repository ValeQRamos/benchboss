"""Workload: every player's games this matchup week, day by day, and which ones you keep.

A game only scores when the player is in your lineup that day, so the grid marks the games
he spends on your bench, and the footer counts how many of your players play each day
against your starting spots (more games than spots means games lost to the bench).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from rich import box
from rich.cells import cell_len
from rich.console import Console, Group, RenderableType
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from benchboss.core import activity as activity_mod
from benchboss.core.activity import Activity
from benchboss.core.calendar import SeasonCalendar
from benchboss.errors import BenchbossError
from benchboss.espn.constants import SLOT
from benchboss.ui.common import legend, player_cell, table, title
from benchboss.ui.theme import Palette

TITLE = "Workload"
VIEWS: tuple[tuple[str, str], ...] = (("lineup", "By lineup"), ("games", "Most games"))

# A game he spends on your bench is dim and in parentheses, "(LAC)"; with no room for the
# opponents the cells turn into dots: ● a game in your lineup, ○ on your bench.
PLAYS, BENCHED, NO_GAME = "●", "○", "·"

# SIMPLE_HEAD plus a rule above the footer, so the "Games" counts sit under a thin line
_HEAD_FOOT = box.Box("    \n    \n ── \n    \n    \n ── \n    \n    \n")


@dataclass
class WorkloadData:
    acts: list[Activity]
    calendar: SeasonCalendar
    periods: list[int]
    today: int               # today's scoring period, NOT clamped: outside the season no day is today
    starter_slots: int = 0   # starting spots per day (0 = unknown: the footer shows plain counts)
    matchup: int = 0         # matchup week number, for the title
    lineups_known: bool = False  # the daily lineups were read (bench games can be marked)
    lineup_error: str = ""   # why they could not be read

    def per_day(self) -> list[int]:
        return activity_mod.games_per_day(self.acts, len(self.periods))


def load(session) -> WorkloadData:
    lg, cal = session.league(), session.calendar
    periods = session.matchup_periods()
    today = cal.period_of(session.today)
    lineups, error = None, ""
    if periods:
        try:
            lineups = session.lineups(periods)
        except BenchbossError as e:
            error = str(e)
    # games left count from the real day: before the season every game is still ahead
    acts = activity_mod.roster_activity(lg.me, cal, periods, today, lineups=lineups,
                                        include_ir=True)
    return WorkloadData(acts, cal, periods, today, lg.starter_slots, lg.current_matchup,
                        lineups is not None, error)


def to_json(data: WorkloadData) -> list[dict]:
    out = []
    for a in _ordered(data.acts, grouped=True):
        days = []
        for i, sp in enumerate(data.periods):
            slot = a.slot_on(i)
            days.append({"date": data.calendar.date_of(sp).isoformat(),
                         "opponent": _short(a.schedule[i]) if i < len(a.schedule) else "",
                         "slot": _slot_name(slot),
                         "starting": a.starting(i) if data.lineups_known else None})
        out.append({"name": a.player.name, "team": a.player.pro_team,
                    "positions": a.player.positions, "slot": _slot_name(a.slot_id),
                    "games": a.games,
                    "games_in_lineup": a.games_in_lineup if data.lineups_known else None,
                    "games_left": a.games_left, "schedule": days})
    return out


# --- layout ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Layout:
    pos: bool = True        # the Pos column
    slot: bool = True       # the Slot column
    short: bool = False     # "A. Edwards" instead of "Anthony Edwards"
    team: bool = True       # the NBA team after the name
    glyphs: bool = False    # day cells as ● ○ · instead of opponents
    gap: int = 3            # columns between columns: 3, 2 or 1
    snug: bool = False      # with gap 1: one space after the names instead of two
    strip: bool = False     # every day in one column, one glyph per day, no daily counts


# Widest first. Pos goes first, then Slot, then long names, then the NBA team after the
# name; only then do the opponents turn into dots. When even the dots do not fit (the
# two-week All-Star matchup, or a very narrow screen) the days fold into one strip.
# G, In and Left always show.
_LAYOUTS = (
    _Layout(),
    _Layout(gap=2),
    _Layout(pos=False, gap=2),
    _Layout(pos=False, slot=False, gap=2),
    _Layout(pos=False, slot=False, short=True, gap=2),
    _Layout(pos=False, slot=False, short=True, team=False, gap=2),
    _Layout(pos=False, slot=False, short=True, team=False, gap=1),
    _Layout(pos=False, slot=False, short=True, glyphs=True, gap=2),
    _Layout(pos=False, slot=False, short=True, glyphs=True, gap=1),
    _Layout(pos=False, slot=False, short=True, team=False, glyphs=True, gap=1),
    _Layout(pos=False, slot=False, short=True, team=False, glyphs=True, gap=1, snug=True),
    _Layout(pos=False, slot=False, short=True, glyphs=True, gap=2, strip=True),
    _Layout(pos=False, slot=False, short=True, team=False, glyphs=True, gap=1, strip=True),
)


def draw(data: WorkloadData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    if not data.acts:
        return Group(_title(data, pal), Text(""),
                     Text("No players on your roster yet.", style=pal.dim))
    grouped = view == 0
    for lay in _LAYOUTS:
        t = _table(data, pal, lay, grouped)
        if _measure(t) <= width:
            break
    else:  # still too wide: the names give way, never the days or the counts
        t.columns[0].min_width = None
        if _measure(t) > width:
            t.columns[0].max_width = max(6, width - (_measure(t) - _measure_column(t, 0)))
            t.columns[0].overflow = "ellipsis"
    parts: list[RenderableType] = [_title(data, pal), Text(""), t, Text("")]
    parts += _legend(data, pal, lay, min(width, max(_measure(t), 40)))  # as wide as the table
    return Group(*parts)


def _ordered(acts: list[Activity], grouped: bool) -> list[Activity]:
    if grouped:
        return [a for group in activity_mod.by_lineup(acts) for a in group]
    return sorted(acts, key=lambda a: (a.on_ir, *activity_mod.by_games(a)))


# --- the table ------------------------------------------------------------------------------------

def _table(data: WorkloadData, pal: Palette, lay: _Layout, grouped: bool) -> Table:
    t = table(pal)
    t.box = _HEAD_FOOT
    t.show_edge = False   # flush left with the title and the legend
    t.show_footer = True
    t.footer_style = pal.dim
    if lay.gap == 2:
        t.collapse_padding = True
    elif lay.gap == 1:
        t.padding = (0, 0)
    right = {"justify": "right", "no_wrap": True}
    active = [a for a in data.acts if not a.on_ir]

    t.add_column("Player", footer=Text("Games", style=f"bold {pal.dim}"), no_wrap=True)
    if lay.pos:
        t.add_column("Pos", no_wrap=True)
    if lay.slot:
        t.add_column("Slot", no_wrap=True)
    per_day = data.per_day()
    heads = [_day_head(data, sp, lay, pal) for sp in data.periods]
    feet = [_day_foot(data, per_day[i], sp, lay, pal) for i, sp in enumerate(data.periods)]
    if lay.strip:
        t.add_column(Text("").join(heads), no_wrap=True)
    else:
        for sp, head, foot in zip(data.periods, heads, feet, strict=True):
            t.add_column(head, footer=foot, justify="center" if lay.glyphs else "left",
                         no_wrap=True,
                         header_style=f"bold {pal.accent}" if sp == data.today else None)
    t.add_column("G", footer=str(sum(a.games for a in active)), **right)
    gin = sum(a.games_in_lineup or 0 for a in active)
    t.add_column("In", footer=Text(str(gin), style=pal.text) if data.lineups_known else "-", **right)
    t.add_column("Left", footer=str(sum(a.games_left for a in active)), **right)

    if grouped:  # starters, bench, IR, with a blank line between them
        groups = [g for g in activity_mod.by_lineup(data.acts) if g]
    else:
        groups = [_ordered(data.acts, grouped=False)]
    rows = [[_row(a, data, pal, lay) for a in group] for group in groups]
    if not lay.glyphs:
        first = 1 + lay.pos + lay.slot
        for i in range(len(data.periods)):
            least = max(cell_len(x) for x in (*heads[i].plain.split("\n"), feet[i].plain))
            _align([r[first + i] for group in rows for r in group], least)
    if lay.gap == 1 and not lay.snug:  # keep two spaces between the names and the first day
        t.columns[0].min_width = 1 + max([len("Player"), *(r[0].cell_len for g in rows for r in g)])
    for gi, group in enumerate(rows):
        for ri, row in enumerate(group):
            t.add_row(*row, end_section=ri == len(group) - 1 and gi < len(rows) - 1)
    return t


def _align(cells: list[Text], least: int) -> None:
    """Line up one day of opponents: the team codes right aligned in a block centered under
    the header, so "@" and "(" stick out on the left and ")" on the right; the no-game dot
    sits under the middle letter.

    Rich strips trailing spaces when it centers or right-aligns a cell, so the column is
    left aligned and the cells are padded here.
    """
    paren = any(c.plain.startswith("(") for c in cells)
    games = [c for c in cells if c.plain != NO_GAME]
    for c in games:
        if paren and not c.plain.startswith("("):
            c.append(" ")
    block = max((c.cell_len for c in games), default=0)
    width = max(least, block)
    offset = (width - block) // 2
    for c in games:
        c.pad_left(offset + block - c.cell_len)
    dot = offset + block - (3 if paren else 2) if games else (width - 1) // 2
    for c in cells:
        if c.plain == NO_GAME:
            c.pad_left(max(0, dot))


def _day_head(data: WorkloadData, sp: int, lay: _Layout, pal: Palette) -> Text:
    d = data.calendar.date_of(sp)
    head = f"{d:%a}"[0] if lay.strip else f"{d:%a}"[: 2 if lay.glyphs else 3] + f"\n{d.day}"
    if sp == data.today:
        return Text(head, style=f"bold {pal.accent}", justify="center")
    if sp < data.today:
        return Text(head, style=f"not bold {pal.dim}", justify="center")
    return Text(head, justify="center")


def _day_foot(data: WorkloadData, n: int, sp: int, lay: _Layout, pal: Palette) -> Text:
    spots = data.starter_slots
    if spots and n > spots:
        return Text(str(n) if lay.glyphs else f"{n}/{spots}", style=pal.warn, justify="center")
    return Text(str(n), style=pal.dim if sp < data.today or not n else pal.text, justify="center")


def _row(a: Activity, data: WorkloadData, pal: Palette, lay: _Layout) -> list:
    p, ir = a.player, a.on_ir
    cells: list = [player_cell(p, pal, short=lay.short, team=lay.team,
                               style=pal.dim if ir else None)]
    if lay.pos:
        cells.append(Text(p.positions, style=pal.dim))
    if lay.slot:
        cells.append(Text(_slot_name(a.slot_id) or "", style=pal.text if a.is_starting else pal.dim))
    days = [_day_cell(a, i, sp, data, pal, lay) for i, sp in enumerate(data.periods)]
    cells += [Text("").join(days)] if lay.strip else days
    games = pal.dim if ir else pal.good if a.games >= 4 else pal.warn if a.games <= 2 else pal.text
    cells.append(Text(str(a.games), style=games))
    gin = a.games_in_lineup if data.lineups_known else None
    cells.append(Text("-" if gin is None else str(gin), style=pal.dim if ir or not gin else pal.text))
    cells.append(Text(str(a.games_left), style=pal.dim if ir or not a.games_left else pal.text))
    return cells


def _day_cell(a: Activity, i: int, sp: int, data: WorkloadData, pal: Palette, lay: _Layout) -> Text:
    opp = a.schedule[i] if i < len(a.schedule) else ""
    if not opp:
        return Text(NO_GAME, style=pal.border)
    label = PLAYS if lay.glyphs else _short(opp)
    if data.lineups_known and a.benched(i):
        return Text(BENCHED if lay.glyphs else f"({label})", style=pal.dim)
    if a.on_ir or (data.lineups_known and not a.starting(i)):
        return Text(label, style=pal.dim)  # on IR, or not on your roster that day
    if sp < data.today:
        return Text(label, style=pal.dim)
    return Text(label, style=f"bold {pal.text}" if sp == data.today else pal.text)


# --- title and legend -----------------------------------------------------------------------------

def _title(data: WorkloadData, pal: Palette) -> Text:
    span = ""
    if data.periods:
        a, b = data.calendar.date_of(data.periods[0]), data.calendar.date_of(data.periods[-1])
        end = f"{b.day}" if (a.year, a.month) == (b.year, b.month) else f"{b:%b} {b.day}"
        span = f"{a:%b} {a.day} to {end}"
    return title(TITLE, pal, f"Week {data.matchup}" if data.matchup else "", span)


def _legend(data: WorkloadData, pal: Palette, lay: _Layout, width: int) -> list[Text]:
    known = data.lineups_known
    items: list[tuple[str, str, str | None]] = []
    if lay.glyphs:
        items.append((PLAYS, "in your lineup" if known else "game", None))
    else:
        items.append(("@LAC", "away", None))
    if known:
        items.append((BENCHED if lay.glyphs else "(LAC)", "on your bench", None))
    items += [("In", "games in your lineup", None), ("Left", "from today on", None)]
    spots, most = data.starter_slots, max(data.per_day(), default=0)
    if spots and most > spots and not lay.strip:
        key = str(most) if lay.glyphs else f"{most}/{spots}"
        items.append((key, f"games, more than your {spots} spots" if lay.glyphs
                      else "more games than starting spots", pal.warn))
    lines = _pack(items, pal, width)
    if data.lineup_error:  # two lines, so a narrow screen wraps each one cleanly
        why = data.lineup_error.rstrip(".")
        lines += [Text("Bench games are not marked: your daily lineups did not load.",
                       style=pal.dim),
                  Text(f"{why[:1].upper()}{why[1:]}.", style=pal.dim)]
    return lines


def _pack(items: list[tuple[str, str, str | None]], pal: Palette, width: int) -> list[Text]:
    """The legend in as few lines as fit ``width``, breaking only between items."""
    lines: list[Text] = []
    line = Text()
    for key, meaning, color in items:
        part = legend(pal, (key, meaning))
        if color:
            part.stylize(f"bold {color}", 0, len(key))
        if line and line.cell_len + 5 + part.cell_len > width:
            lines.append(line)
            line = Text()
        if line:
            line.append("  ·  ", style=pal.border)
        line.append_text(part)
    if line:
        lines.append(line)
    return lines


# --- helpers --------------------------------------------------------------------------------------

def _short(opp: str) -> str:
    """ "vs LAC" -> "LAC", "@ BOS" -> "@BOS"."""
    return opp.replace("vs ", "").replace("@ ", "@")


def _slot_name(slot: int | None) -> str | None:
    return None if slot is None else SLOT.get(slot, str(slot))


_CONSOLE = Console(width=1000, file=io.StringIO(), color_system=None)


def _measure(t: Table) -> int:
    return Measurement.get(_CONSOLE, _CONSOLE.options, t).maximum


def _measure_column(t: Table, index: int) -> int:
    col = t.columns[index]
    return max(Measurement.get(_CONSOLE, _CONSOLE.options, c).maximum
               for c in (col.header, col.footer, *col.cells))


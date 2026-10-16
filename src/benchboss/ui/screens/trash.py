"""Best trash: free agents ranked by the points they add this matchup week."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.constrain import Constrain
from rich.text import Text

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.trash import TrashPick
from benchboss.ui.common import day_label, num, player_cell, table, title
from benchboss.ui.theme import Palette

TITLE = "Best trash"
VIEWS: tuple[tuple[str, str], ...] = ()

GAME, NO_GAME, TIPPED = "●", "·", "○"   # the games strip: one glyph per day
WIDE = 110                               # below this the position and ownership columns go
HINT = 'benchboss add "Player" --drop "Player"'


@dataclass
class TrashData:
    picks: list[TrashPick]
    calendar: SeasonCalendar


def load(session, n: int = 12, position: str | None = None) -> TrashData:
    return TrashData(session.trash(n=n, position=position, pool=max(60, n * 4)), session.calendar)


def draw(data: TrashData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    """The table, then a dim hint on how to grab one from a terminal."""
    shown = trash(data.picks, data.calendar, pal, width)
    if not week_span(data.picks):
        return shown
    lead = "Grab one from a terminal:"
    sep = " " if cell_len(lead) + 1 + cell_len(HINT) <= width else "\n"
    return Group(shown, Text(f"\n{lead}{sep}{HINT}", style=pal.dim))


def to_json(data: TrashData) -> list[dict]:
    return [p.to_dict(data.calendar) for p in data.picks]


# --- pieces ------------------------------------------------------------------------------------

def week_span(picks: list[TrashPick]) -> list[int]:
    """The days the list covers: the first day anyone can be grabbed through Sunday."""
    days = {d for pk in picks for d in pk.gain_by_day}
    return list(range(min(days), max(days) + 1)) if days else []


def games_strip(pk: TrashPick, span: list[int], cal: SeasonCalendar, pal: Palette,
                spaced: bool = False) -> Text:
    """One glyph per day of ``span``: blank before the grab day, then ● for a game he plays for
    you and · for a day off. The grab day is drawn in the accent color; ○ is a game today that
    has already tipped off (it does not count). ``spaced`` puts a space between the days so
    they line up under the day initials ("W T F S S")."""
    mine = set(pk.game_days(cal))
    out = Text(no_wrap=True)
    for i, d in enumerate(span):
        if spaced and i:
            out.append(" ")
        if pk.best_day is None or d < pk.best_day:
            out.append(" ")
            continue
        plays = cal.plays(pk.player.pro_team_id, d)
        glyph = GAME if d in mine else TIPPED if plays else NO_GAME
        style = pal.accent if d == pk.best_day else pal.text if d in mine else pal.dim
        out.append(glyph, style=style)
    return out


def strip_header(span: list[int], cal: SeasonCalendar, spaced: bool) -> str:
    """ "W T F S S" over a spaced strip; a compact strip is just "Games"."""
    return " ".join(f"{cal.date_of(d):%a}"[0] for d in span) if spaced else "Games"


def _span_label(span: list[int], cal: SeasonCalendar, short: bool) -> str:
    first, last = cal.date_of(span[0]), cal.date_of(span[-1])
    if short:
        end = str(last.day) if last.month == first.month else f"{last:%b} {last.day}"
        return f"{first:%b} {first.day}" + (f" to {end}" if last != first else "")
    return day_label(first) + (f" to {day_label(last)}" if last != first else "")


def heading(span: list[int], cal: SeasonCalendar, pal: Palette, width: int) -> Text:
    """ "Best trash · Wed Nov 4 to Sun Nov 8 · points added if you grab him", shortened to fit."""
    tries: list[tuple[str, ...]] = [()]
    if span:
        full, short = _span_label(span, cal, False), _span_label(span, cal, True)
        tries = [(full, "points added if you grab him"), (full,), (short,), ()]
    for ctx in tries:
        line = title(TITLE, pal, *ctx)
        if line.cell_len <= width:
            return line
    return line


def _name(pk: TrashPick, pal: Palette, short: bool, waivers: bool, room: int = 0) -> Text:
    """The player cell. Wider than ``room``, the name is cut and the team, injury and "(W)"
    after it stay: "S. Gilgeous-Al… OKC OUT"."""
    name = pk.player.short_name if short else pk.player.name
    cell = player_cell(pk.player, pal, short=short)
    if waivers and pk.on_waivers:
        cell.append(" (W)", style=pal.warn)
    over = cell.cell_len - room if room else 0
    if over > 0 and len(name) > over + 1:
        head = cell[:len(name) - over - 1]
        head.rstrip()
        cell = Text.assemble(head, ("…", pal.text), cell[len(name):])
    return cell


def _grab(pk: TrashPick, cal: SeasonCalendar, pal: Palette, short: bool) -> Text:
    if pk.best_day is None:
        return Text("-", style=pal.dim)
    d = cal.date_of(pk.best_day)
    out = Text(f"{d:%a} {d.day}" if short else day_label(d), style=pal.text)
    if pk.on_waivers:
        out.append(" (W)", style=pal.warn)
    return out


def _drop(pk: TrashPick, pal: Palette, short: bool) -> Text:
    if pk.drop is None:
        return Text("-" if pk.needs_drop else "open spot", style=pal.dim)
    out = Text(pk.drop.short_name if short else pk.drop.name, style=pal.dim)
    if pk.drop_projects_higher:
        out.append("*", style=pal.warn)
    return out


def _owned(pk: TrashPick, pal: Palette, digits: int) -> Text:
    """ "12.8 ▲": % rostered with a small arrow when it moved. Left justified and padded by
    hand, so the numbers line up whether or not a row has an arrow."""
    change = pk.player.owned_change
    arrow = (" ▲", pal.good) if change >= 0.1 else (" ▼", pal.bad) if change <= -0.1 else ("  ", "")
    return Text.assemble((f"{pk.player.owned:>{digits}.1f}", pal.dim), arrow, justify="left")


def _net(pk: TrashPick, pal: Palette) -> Text:
    return Text(f"{pk.net:+.1f}", style=f"bold {pal.good}" if pk.net > 0 else pal.dim)


Meaning = str | tuple[str, ...]   # a tuple holds shorter wordings for narrow tables, longest first


def _caption(items: list[tuple[str | Text, Meaning]], pal: Palette, width: int) -> Text:
    """The legend, packed into lines no wider than ``width``, breaking between items. Each
    item takes the longest of its wordings that fits on one line."""
    out, line = Text(), 0
    for key, meaning in items:
        if isinstance(key, str):
            key = Text(key, style=f"bold {pal.dim}")
        lead = key.cell_len + 1 if key else 0
        if isinstance(meaning, tuple):
            meaning = next((m for m in meaning if lead + cell_len(m) <= width), meaning[-1])
        size = lead + cell_len(meaning)
        if line and line + 5 + size > width:
            out.append("\n")
            line = 0
        elif line:
            out.append("  ·  ", style=pal.border)
            line += 5
        if key:
            out.append_text(key)
            out.append(" ")
        out.append(meaning, style=pal.dim)
        line += size
    return out


# --- the table ---------------------------------------------------------------------------------

COLUMNS = ("#", "Player", "Pos", "Games", "G", "Grab", "+Pts", "Drop", "Net", "Proj", "Own%")
RIGHT = ("#", "Games", "G", "+Pts", "Net", "Proj", "Own%")   # the strip ends on Sunday


class _Layout:
    """The columns that show and how compact they are, for one list of picks."""

    def __init__(self, picks: list[TrashPick], span: list[int], cal: SeasonCalendar, pal: Palette):
        self.picks, self.span, self.cal, self.pal = picks, span, cal, pal
        self.keys = list(COLUMNS)
        self.short_grab = self.short_drop = False
        self.spaced = True   # the games strip, one space between days
        self.digits = max(len(f"{pk.player.owned:.1f}") for pk in picks)
        self._made: dict[tuple, tuple[list, int]] = {}

    def header(self, key: str) -> str:
        return strip_header(self.span, self.cal, self.spaced) if key == "Games" else key

    def column(self, key: str) -> tuple[list, int]:
        """The cells of one column (not Player) and its width, built once per variant."""
        variant = (key, {"Grab": self.short_grab, "Drop": self.short_drop,
                         "Games": self.spaced}.get(key))
        if variant not in self._made:
            got = self._build(key)
            self._made[variant] = (got, max([cell_len(self.header(key))] + [_len(c) for c in got]))
        return self._made[variant]

    def _build(self, key: str) -> list:
        picks, pal = self.picks, self.pal
        if key == "#":
            return [Text(str(i), style=pal.dim) for i in range(1, len(picks) + 1)]
        if key == "Pos":
            return [Text(pk.player.positions, style=pal.dim) for pk in picks]
        if key == "Games":
            return [games_strip(pk, self.span, self.cal, pal, self.spaced) for pk in picks]
        if key == "G":
            return [str(pk.games_left) for pk in picks]
        if key == "Grab":
            return [_grab(pk, self.cal, pal, self.short_grab) for pk in picks]
        if key == "+Pts":
            return [f"{pk.gain:.1f}" for pk in picks]
        if key == "Drop":
            return [_drop(pk, pal, self.short_drop) for pk in picks]
        if key == "Net":
            return [_net(pk, pal) for pk in picks]
        if key == "Proj":
            return [Text(num(pk.player.proj), style=pal.dim) for pk in picks]
        return [_owned(pk, pal, self.digits) for pk in picks]  # Own%

    def names(self, short: bool, room: int = 0) -> list[Text]:
        return [_name(pk, self.pal, short, "Grab" not in self.keys, room) for pk in self.picks]

    def widest(self, short: bool) -> int:
        return max(c.cell_len for c in self.names(short))

    def typical(self) -> int:
        """The width four short names in five fit in, so one long name does not cost every
        row a column."""
        widths = sorted(c.cell_len for c in self.names(True))
        return widths[(4 * len(widths) + 4) // 5 - 1]

    def need(self, player: int) -> int:
        """Columns the table takes with the player column ``player`` wide: one space of
        padding inside each column (none at the outer edges), one edge space on each side
        and one divider between columns."""
        return (player + sum(self.column(k)[1] for k in self.keys if k != "Player")
                + 3 * len(self.keys) - 1)


def _len(cell) -> int:
    return cell.cell_len if isinstance(cell, Text) else cell_len(cell)


def trash(picks: list[TrashPick], cal: SeasonCalendar, pal: Palette,
          width: int = 120) -> RenderableType:
    """The title line and the free agents by net points added this week, fitted to ``width``.

    Columns: rank, player (with NBA team and injury), position, a games strip from the grab
    day to Sunday, G, grab day, +Pts, the suggested drop, Net, projection and % rostered.
    Below 110 columns (or when the full table is wider than ``width``) the position and
    ownership columns go. If that is still too wide, the games strip loses the spaces between
    days, the grab day gets shorter, the Drop column goes when it is the same player on every
    row (the caption names him), then Proj and +Pts go. Only after those secondary columns are
    gone do the names shorten ("J. Kuminga MIN", on every row), then the drop names, then the
    Drop, Grab (the strip still shows the grab day, and a waiver claim gets "(W)" after his
    name), # and strip columns go, until four names in five fit. Last of all the longer
    names are cut, keeping their team and injury. Net and G, the columns the list is ranked
    by, always show.
    """
    span = week_span(picks)
    head = heading(span, cal, pal, width)
    if not picks or not span:
        note = ("No free agents to show." if not picks else
                "Nothing left to gain this week: no free agent can still play a game for you.")
        return Group(head, Text(""), Constrain(Text(note, style=pal.dim), width))

    lay = _Layout(picks, span, cal, pal)
    drops = {pk.drop.name for pk in picks if pk.drop}
    if width < WIDE or lay.need(lay.widest(False)) > width:
        lay.keys = [k for k in lay.keys if k not in ("Pos", "Own%")]
    # secondary columns go before any name gets shorter
    for step in ("compact strip", "short grab", "same drop", "Proj", "+Pts"):
        if lay.need(lay.widest(False)) <= width:
            break
        if step == "compact strip":
            lay.spaced = False
        elif step == "short grab":
            lay.short_grab = True
        elif step == "same drop":
            if len(drops) <= 1:
                lay.keys.remove("Drop")
        else:
            lay.keys.remove(step)
    # then the names shorten and the primary columns go; Net and G never do
    for step in ("short drop", "Drop", "Grab", "#", "Games"):
        if lay.need(lay.typical()) <= width:
            break
        if step == "short drop":
            lay.short_drop = True
        elif step in lay.keys:
            lay.keys.remove(step)

    room = max(6, width - lay.need(0))
    short = lay.widest(False) > room
    t = table(pal)
    for key in lay.keys:
        extra = {"overflow": "ellipsis", "max_width": room} if key == "Player" else {}
        t.add_column(lay.header(key), no_wrap=True, justify="right" if key in RIGHT else "left",
                     **extra)
    columns = [lay.names(short, room) if k == "Player" else lay.column(k)[0] for k in lay.keys]
    for row in zip(*columns, strict=True):
        t.add_row(*row)
    tipped = "Games" in lay.keys and any(TIPPED in c.plain for c in lay.column("Games")[0])
    t.caption = _caption(_legend(picks, lay.keys, drops, pal, tipped), pal,
                         lay.need(min(room, lay.widest(short))))
    return Group(head, t)


def _legend(picks: list[TrashPick], keys: list[str], drops: set[str], pal: Palette,
            tipped: bool) -> list[tuple[str | Text, Meaning]]:
    """(key, meaning) pairs for the caption; an empty key is a plain note."""
    items: list[tuple[str | Text, Meaning]] = []
    added = ("points over your weakest starter", "points added")
    if "+Pts" in keys:
        items.append(("+Pts", "over your weakest starter"))
        added = ("+Pts",)
    if drops:
        net = tuple(f"{a} minus the drop's points" for a in added) + (f"{added[-1]} minus the drop's",)
    else:
        net = tuple(f"{a}, no drop needed" for a in added)
    items.append(("Net", net))
    items.append(("G", "games he plays for you"))
    if "Games" in keys and "Grab" not in keys:
        items.append((Text(GAME, style=pal.accent), "grab day"))
    if tipped:
        items.append((Text(TIPPED, style=pal.dim), "already tipped off"))
    flagged = sum(1 for pk in picks if pk.drop_projects_higher)
    every = flagged == sum(1 for pk in picks if pk.drop)
    if "Drop" in keys:
        if flagged:
            items.append(("*", "drop scores more per game: a one-week stream"))
    elif len(drops) == 1:
        items.append(("", f"{next(iter(drops))} is the suggested drop"))
        if flagged:
            than = "all" if every else "some"
            items.append(("", (f"He scores more per game than {than} of these: one-week streams",
                               f"He scores more per game than {than} of these",
                               f"He outscores {than} of these per game")))
    elif flagged:
        items.append(("", ("Every drop scores more per game: one-week streams",
                           "Drops score more per game: one-week streams",
                           "Every drop scores more per game") if every else
                          ("Some drops score more per game: one-week streams",
                           "Some drops score more per game")))
    if any(pk.on_waivers for pk in picks):
        items.append(("(W)", ("on waivers, yours from the grab day", "on waivers")))
    return items

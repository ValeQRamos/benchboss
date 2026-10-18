"""Optimize: the best lineup for one day or every day left in the matchup week.

Each day reads top to bottom: a header (the date, who plays, the projected points), the
moves, the lineup they leave, then the bench and why each player sits there, with the
injury math spelled out when he is hurt (constants.INJURY_FACTOR: DTD and Q count 75%,
D 25%, OUT nothing). When several days are shown, a summary goes on top and a day with
nothing to change folds into one quiet line.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import DayPlan, Move, plan_gain
from benchboss.espn.constants import BENCH, INJURY_FACTOR, IR, SLOT
from benchboss.espn.models import Player
from benchboss.text import surname
from benchboss.ui.common import day_label
from benchboss.ui.theme import Palette

WIDE = 64      # from this width on, Moves / Lineup / Bench get their own column
LABEL_W = 9    # that column: " Moves" plus room


def plan(plans: list[DayPlan], cal: SeasonCalendar, pal: Palette,
         width: int | None = None) -> RenderableType:
    """The plan for ``plans``. Without ``width`` it lays itself out for the width of the
    console it is printed on (the CLI); the app passes the width it has."""
    if width is None:
        return _Fit(plans, cal, pal)
    return draw(plans, cal, pal, width)


class _Fit:
    def __init__(self, plans: list[DayPlan], cal: SeasonCalendar, pal: Palette):
        self.plans, self.cal, self.pal = plans, cal, pal

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield draw(self.plans, self.cal, self.pal, options.max_width)

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement(options.max_width, options.max_width)


def draw(plans: list[DayPlan], cal: SeasonCalendar, pal: Palette, width: int) -> RenderableType:
    # one name column for the moves of every day, so the arrows line up down the week
    name_w = max((len(m.player.name) for p in plans for m in p.moves), default=0)
    if len(plans) == 1:  # the day header already says everything a summary would
        p = plans[0]
        if not playing(p, cal):
            return day_header(p, cal, pal, width)
        return Group(day_header(p, cal, pal, width), day_body(p, cal, pal, width, name_w))
    parts: list[RenderableType] = [summary(plans, cal, pal, width)]
    quiet = False
    for p in plans:
        if not p.changed:
            if not quiet:
                parts.append(Text(""))
            parts.append(quiet_day(p, cal, pal, width))
            quiet = True
            continue
        quiet = False
        parts += [Text(""), day_header(p, cal, pal, width), day_body(p, cal, pal, width, name_w)]
    return Group(*parts)


# --- numbers ----------------------------------------------------------------------------------

gain = plan_gain  # lives in core.lineup, so the monitor can use it without the UI


def playing(p: DayPlan, cal: SeasonCalendar) -> int:
    """Players on the roster (IR aside) whose team plays that day."""
    everyone = [pl for pl, _, _ in p.starters] + [pl for pl, _ in p.bench]
    return sum(1 for pl in everyone if cal.plays(pl.pro_team_id, p.period))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' * (n != 1)}"


def _sep(pal: Palette, width: int) -> tuple[str, str]:
    return ("  ·  " if width >= WIDE else " · ", pal.border)


def _pts(v: float) -> str:
    return f"{v:,.1f}"


def _first_fit(width: int, *variants: Text) -> Text:
    """The first of ``variants`` (longest first) that fits on one line; the last one when
    none does. A header or a summary never wraps in the middle of a phrase."""
    return next((v for v in variants if v.cell_len <= width), variants[-1])


def _shown(pl: Player, value: float) -> float:
    """The number printed for ``pl`` on a day. A hurt player's comes from his rounded
    projection, so "32.9 × 75% = 24.7" adds up and he shows 24.7 everywhere that day."""
    factor = INJURY_FACTOR.get(pl.injury_status or "", 1.0)
    return round(round(pl.proj, 1) * factor, 1) if value and factor < 1 else value


# --- the summary and the day headers ------------------------------------------------------------

def summary(plans: list[DayPlan], cal: SeasonCalendar, pal: Palette, width: int = 100) -> Text:
    """ "6 moves on 4 of 5 days · projected 1,062.1 pts · +95.0 from the moves"."""
    moves = sum(len(p.moves) for p in plans)
    days = sum(1 for p in plans if p.changed)
    total = sum(p.projected for p in plans)
    added = sum(gain(p, cal) for p in plans)
    out = Text()
    if not moves:
        out.append("No moves needed", style=f"bold {pal.good}")
    elif len(plans) == 1:
        out.append(_plural(moves, "move"), style=f"bold {pal.text}")
    else:
        out.append(f"{_plural(moves, 'move')} on {days} of {_plural(len(plans), 'day')}",
                   style=f"bold {pal.text}")
    gained = round(added, 1) > 0
    rest = Text(f"projected {_pts(total)} pts", style=pal.dim)
    short = Text(f"proj {_pts(total)}", style=pal.dim)
    if gained:
        rest.append_text(Text.assemble(_sep(pal, width), (f"+{_pts(added)}", pal.good),
                                       (" from the moves", pal.dim)))
        short.append_text(Text.assemble((" · ", pal.border), (f"+{_pts(added)}", pal.good)))
    if out.cell_len + 5 + rest.cell_len <= width:
        out.append_text(Text.assemble(_sep(pal, width), rest))
        return out
    # on a line of its own, as one piece: "proj 1,062.1 · +95.0" rather than a phrase cut in two
    out.append("\n")
    out.append_text(_first_fit(width, rest, short))
    return out


def day_header(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int = 100) -> Text:
    """ "Wed Nov 4   13 of your players play · projected 382.0 · +30.9"."""
    n = playing(p, cal)
    day = Text(day_label(cal.date_of(p.period)), style=f"bold {pal.text}")
    dot = (" · ", pal.border)
    if not n:
        return _first_fit(width, Text.assemble(day, "   ", ("no games for your players", pal.dim)),
                          Text.assemble(day, dot, ("no games", pal.dim)), day)
    g = gain(p, cal)
    sep = _sep(pal, width)

    def plus(between: tuple[str, str]) -> Text:
        return Text.assemble(between, (f"+{_pts(g)}", pal.good)) if round(g, 1) > 0 else Text()

    # measured, longest first: "13 of your players play · projected 382.0 · +30.9" from WIDE
    # columns on, then "13 play · proj 382.0 · +30.9", "Wed Nov 4 · 13 play · +30.9"
    tries = [Text.assemble(day, "   ", (f"{n} play", pal.dim), sep,
                           (f"proj {_pts(p.projected)}", pal.dim), plus(sep)),
             Text.assemble(day, dot, (f"{n} play", pal.dim), plus(dot)),
             Text.assemble(day, plus(dot))]
    if width >= WIDE:
        tries.insert(0, Text.assemble(day, "   ", (f"{n} of your players play", pal.dim), sep,
                                      (f"projected {_pts(p.projected)}", pal.dim), plus(sep)))
    return _first_fit(width, *tries)


def quiet_day(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int = 100) -> Text:
    """One dim line for a day that needs no move."""
    n = playing(p, cal)
    day = Text(day_label(cal.date_of(p.period)), style=pal.dim)
    if not n:
        return _first_fit(width, Text.assemble(day, "   ", ("no games for your players", pal.dim)),
                          Text.assemble(day, (" · ", pal.border), ("no games", pal.dim)), day)
    full = Text.assemble(day, "   ", ("no changes", pal.dim), _sep(pal, width),
                         (f"{n} play", pal.dim), _sep(pal, width),
                         (f"proj {_pts(p.projected)}", pal.dim))
    return _first_fit(width, full,
                      Text.assemble(day, "   ", ("no changes", pal.dim), (" · ", pal.border),
                                    (f"{n} play", pal.dim)),
                      Text.assemble(day, (" · ", pal.border), ("no changes", pal.dim)))


# --- one day ----------------------------------------------------------------------------------

def day_body(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int,
             name_w: int = 0) -> RenderableType:
    """Moves, lineup and bench of one day, under labels in their own column when it fits.
    ``name_w`` is the width of the movers' names (the longest of every day shown)."""
    wide = width >= WIDE
    inner = width - (LABEL_W + 1 if wide else 2)
    sections: list[tuple[str, RenderableType]] = []
    if p.moves:
        sections.append(("Moves", moves(p, pal, inner, name_w)))
    if p.starters:
        sections.append(("Lineup", lineup(p, cal, pal, inner)))
    if p.bench:
        sections.append(("Bench", bench(p, cal, pal, inner)))
    grid = Table.grid()
    if wide:
        grid.add_column(width=LABEL_W, no_wrap=True)
        grid.add_column(width=1)
        grid.add_column(max_width=inner)
        for label, body in sections:
            grid.add_row(Text(f" {label}", style=pal.dim), "", body)
        return grid
    grid.add_column(width=2)
    grid.add_column(max_width=inner)
    for label, body in sections:
        if label != "Moves":
            grid.add_row("", Text(label, style=pal.dim))
        grid.add_row("", body)
    return grid


def _order(m: Move) -> tuple[int, str]:
    """Players coming into the lineup first, then slot changes, then the ones going out."""
    if m.from_slot in (BENCH, IR):
        return 0, m.player.name
    if m.to_slot in (BENCH, IR):
        return 2, m.player.name
    return 1, m.player.name


def _swaps(ordered: list[Move]) -> list[tuple[Move | None, Move | None]]:
    """Rows of (move into a slot, move to the bench): each player going to the bench sits
    next to the one who takes his slot."""
    benched = [m for m in ordered if m.to_slot in (BENCH, IR)]
    rows: list[tuple[Move | None, Move | None]] = []
    for m in ordered:
        if m.to_slot in (BENCH, IR):
            continue
        partner = next((o for o in benched if o.from_slot == m.to_slot), None)
        if partner is not None:
            benched.remove(partner)
        rows.append((m, partner))
    return rows + [(None, o) for o in benched]


def moves(p: DayPlan, pal: Palette, width: int, name_w: int = 0) -> Table:
    """ "Pascal Siakam   BE → PF   41.1": who moves, from which slot to which, and what he
    projects in his new slot. When the width allows, each player going to the bench sits on
    the right of the one who takes his slot, so the row reads as the swap it is."""
    values = {pl.id: v for pl, _, v in p.starters}
    ordered = sorted(p.moves, key=_order)
    # a row is the name, "   BE → PF" (10) and "   41.1" (7); short names when full ones
    # leave no room for that, and a name that still does not fit is cut, never the slots
    full = max([len(m.player.name) for m in ordered] + [name_w])
    short = full + 17 > width
    longest = max(len(m.player.short_name) for m in ordered) if short else full
    name_col = max(1, min(longest, width - 17))

    def cells(m: Move | None) -> list[Text]:
        if m is None:
            return [Text(""), Text(""), Text("")]
        value = values.get(m.player.id) if m.to_slot not in (BENCH, IR) else None
        name = m.player.short_name if short else m.player.name
        return [Text(name, style=pal.text),
                Text.assemble(("   ", ""), (f"{SLOT.get(m.from_slot, '?'):<2}", pal.info),
                              (" → ", pal.dim), (f"{SLOT.get(m.to_slot, '?'):<2}", pal.info)),
                Text(f"   {_shown(m.player, value):.1f}" if value is not None else "",
                     style=pal.dim)]

    rows = _swaps(ordered)
    # the right side has no points and starts 5 spaces after the left one
    pair = any(a and b for a, b in rows) and (longest + 17) + 5 + (longest + 10) <= width
    t = Table.grid()
    for col in ([name_col, name_col + 5] if pair else [name_col]):
        t.add_column(no_wrap=True, overflow="ellipsis", width=col)
        t.add_column(no_wrap=True)
        t.add_column(no_wrap=True)
    if not pair:
        for m in ordered:
            t.add_row(*cells(m))
        return t
    for into, benched in rows:
        right = cells(benched)
        right[0] = Text.assemble(("     ", ""), right[0])
        t.add_row(*cells(into), *right)
    return t


def lineup(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int) -> Table:
    """The starters as a grid of "PG  L. Ball  46.4" cells, as many across as fit. A starter
    with no game that day (nobody better could take his slot) shows dim with a dash."""
    starters = sorted(p.starters, key=lambda x: (x[1], -x[2]))
    narrow = width < 60
    names = [surname(pl.name) if narrow else pl.short_name for pl, _, _ in starters]
    name_w = max((len(n) for n in names), default=4)
    gap = 2 if narrow else 3  # two across from 35 columns on a phone
    cell = 2 + 1 + name_w + 1 + 4
    across = max(1, min(len(starters), (width + gap) // (cell + gap)))
    t = Table.grid()
    for _ in range(across):
        t.add_column(no_wrap=True)
        t.add_column(no_wrap=True, overflow="ellipsis")
        t.add_column(no_wrap=True, justify="right")
    moved_in = {m.player.id for m in p.moves if m.from_slot in (BENCH, IR)}
    for start in range(0, len(starters), across):
        cells: list[Text] = []
        for i, ((pl, slot, value), name) in enumerate(zip(starters[start:start + across],
                                                         names[start:start + across], strict=True)):
            idle = not cal.plays(pl.pro_team_id, p.period)
            color = pal.dim if idle else pal.info if pl.id in moved_in else pal.text
            cells += [Text(f"{' ' * gap if i else ''}{SLOT.get(slot, '?'):<2} ", style=pal.dim),
                      Text(f"{name:<{name_w}} ", style=color),
                      Text("  -" if idle else f"{_shown(pl, value):.1f}", style=pal.dim)]
        cells += [Text("")] * (3 * across - len(cells))
        t.add_row(*cells)
    return t


def bench(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int) -> RenderableType:
    """Who sits and why. Players with no game go on one line at the end. When one reason is
    too long for the width, every comparison moves to its own line, so the rows keep one
    rhythm; when even that is too wide (a phone), each reason goes under its name, indented,
    so the injury math never breaks across lines."""
    narrow = width < 60
    t = Table.grid()

    def name(pl: Player) -> str:
        return pl.short_name if narrow else pl.name

    sitting = [(pl, why) for pl, why in p.bench if why != "no game"]
    idle = [name(pl) for pl, why in p.bench if why == "no game"]
    name_w = max((len(name(pl)) for pl, _ in sitting), default=0) + 2
    lines = [reason(pl, why, p, cal, pal, narrow) for pl, why in sitting]

    def widest(texts: list[Text]) -> int:
        return max((cell_len(x) for line in texts for x in line.plain.split("\n")), default=0)

    if name_w + widest(lines) > width:
        lines = [reason(pl, why, p, cal, pal, narrow, split=True) for pl, why in sitting]
    if name_w + widest(lines) > width:
        stacked = Text(no_wrap=True, overflow="ellipsis")
        for (pl, _), line in zip(sitting, lines, strict=True):
            stacked.append(f"{name(pl)}\n", style=pal.text)
            for part in line.split("\n"):
                stacked.append_text(Text.assemble("  ", part, "\n"))
        stacked.rstrip()
        if not idle:
            return stacked
        return Group(stacked, Text.assemble(("No game: ", pal.dim), (", ".join(idle), pal.dim)))
    t.add_column(no_wrap=True)
    t.add_column(ratio=1)
    for (pl, _), line in zip(sitting, lines, strict=True):
        t.add_row(Text(f"{name(pl)}  ", style=pal.text), line)
    if idle:
        t.add_row(Text("No game  ", style=pal.dim), Text(", ".join(idle), style=pal.dim))
    return t


def reason(pl: Player, why: str, p: DayPlan, cal: SeasonCalendar, pal: Palette,
           narrow: bool = False, split: bool = False) -> Text:
    """Why ``pl`` sits this day, in plain words with the numbers:
    "DTD: 32.9 × 75% = 24.7, below Scotty Pippen Jr. 30.6" (``split`` puts the comparison
    on a second line)."""
    if why == "locked":
        return Text("locked, his game has started", style=pal.dim)
    if pl.id in p.frozen and why == p.frozen[pl.id]:
        return Text(_frozen(why), style=pal.dim)
    factor = INJURY_FACTOR.get(pl.injury_status or "", 1.0)
    if factor == 0:
        return Text(pl.injury or "out", style=pal.bad)
    value = _shown(pl, pl.proj)
    out = Text()
    if factor < 1:
        out.append(pl.injury or "hurt", style=pal.warn)
        out.append(f": {pl.proj:.1f} × {factor:.0%} = {value:.1f}", style=pal.dim)
    else:
        out.append(f"proj {value:.1f}", style=pal.dim)
    rival = _weakest_starter(pl, p)
    if rival is not None:
        other, other_value = rival
        name = other.short_name if narrow else other.name
        shown = round(_shown(other, other_value), 1)
        word = "below" if round(value, 1) < shown else "same as"
        out.append(f"{chr(10) if split else ', '}{word} {name} {shown:.1f}", style=pal.dim)
    return out


def _frozen(why: str) -> str:
    """A frozen bench player's reason, short: "locked, tipped 7:00 PM"."""
    if why.startswith("tipped "):
        return f"locked, {why}"
    if why.startswith("starts "):
        return f"{why}, too close to change"
    return {"unknown status": "no status from ESPN, left as is",
            "tip time TBD": "tip time not set, left as is",
            "game does not lock": "his game does not lock, left as is",
            "no clock": "left as is"}.get(why, why)


def _weakest_starter(pl: Player, p: DayPlan) -> tuple[Player, float] | None:
    """The starter with the lowest projection in a slot ``pl`` could fill. Frozen starters
    (locked, or their game is about to start) do not count: they keep their slot whatever
    they project."""
    slots = set(pl.eligible_slots)
    fits = [(other, v) for other, slot, v in p.starters
            if slot in slots and v and not other.locked and other.id not in p.frozen]
    return min(fits, key=lambda x: x[1]) if fits else None


__all__ = ["draw", "gain", "plan", "reason"]

"""Optimize: the best lineup for one day or every day left in the matchup week.

Each day reads top to bottom: a header (the date, who plays, the projected points), the
moves, the lineup they leave, then the bench and why each player sits there, with the
injury math spelled out when he is hurt (constants.INJURY_FACTOR: DTD and Q count 75%,
D 25%, OUT nothing). When several days are shown, a day with nothing to change folds into
one quiet line.
"""

from __future__ import annotations

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import DayPlan, Move, day_value
from benchboss.espn.constants import BENCH, INJURY_FACTOR, IR, SLOT
from benchboss.espn.models import Player
from benchboss.ui.common import day_label
from benchboss.ui.theme import Palette

WIDE = 64      # from this width on, Moves / Lineup / Bench get their own column
LABEL_W = 9    # that column: " Moves" plus room
SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}


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
    parts: list[RenderableType] = [summary(plans, cal, pal, width)]
    fold = len(plans) > 1
    quiet = False
    for p in plans:
        if fold and not p.changed:
            if not quiet:
                parts.append(Text(""))
            parts.append(quiet_day(p, cal, pal, width))
            quiet = True
            continue
        quiet = False
        parts += [Text(""), day_header(p, cal, pal, width), day_body(p, cal, pal, width)]
    return Group(*parts)


# --- numbers ----------------------------------------------------------------------------------

def gain(p: DayPlan, cal: SeasonCalendar) -> float:
    """Projected points the moves add that day: who comes in minus who goes out."""
    values = {pl.id: v for pl, _, v in p.starters}
    out = 0.0
    for m in p.moves:
        starts_now = m.from_slot not in (BENCH, IR)
        starts_after = m.to_slot not in (BENCH, IR)
        if starts_after and not starts_now:
            out += values.get(m.player.id, day_value(m.player, p.period, cal))
        elif starts_now and not starts_after:
            out -= day_value(m.player, p.period, cal)
    return out


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
    rest = Text.assemble((f"projected {_pts(total)} pts", pal.dim))
    if round(added, 1) > 0:
        rest.append_text(Text.assemble(_sep(pal, width), (f"+{_pts(added)}", pal.good),
                                       (" from the moves", pal.dim)))
    if out.cell_len + 5 + rest.cell_len <= width:
        out.append_text(Text.assemble(_sep(pal, width), rest))
    else:
        out.append("\n")
        out.append_text(rest)
    return out


def day_header(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int = 100) -> Text:
    """ "Wed Nov 4   13 of your players play · projected 382.0 · +30.9"."""
    n = playing(p, cal)
    out = Text.assemble((day_label(cal.date_of(p.period)), f"bold {pal.text}"))
    out.append("   ")
    if not n:
        out.append("no games for your players", style=pal.dim)
        return out
    wide = width >= WIDE
    out.append(f"{n} of your players play" if wide else f"{n} play", style=pal.dim)
    out.append_text(Text.assemble(_sep(pal, width),
                                  (f"projected {_pts(p.projected)}" if wide
                                   else f"proj {_pts(p.projected)}", pal.dim)))
    g = gain(p, cal)
    if round(g, 1) > 0:
        out.append_text(Text.assemble(_sep(pal, width), (f"+{_pts(g)}", pal.good)))
    return out


def quiet_day(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int = 100) -> Text:
    """One dim line for a day that needs no move."""
    n = playing(p, cal)
    out = Text.assemble((day_label(cal.date_of(p.period)), pal.dim))
    out.append("   ")
    if not n:
        out.append("no games for your players", style=pal.dim)
        return out
    out.append("no changes", style=pal.dim)
    out.append_text(Text.assemble(_sep(pal, width), (f"{n} play", pal.dim), _sep(pal, width),
                                  (f"proj {_pts(p.projected)}", pal.dim)))
    return out


# --- one day ----------------------------------------------------------------------------------

def _surname(name: str) -> str:
    parts = [x for x in name.split() if x.lower() not in SUFFIXES]
    return parts[-1] if parts else name


def day_body(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int) -> RenderableType:
    """Moves, lineup and bench of one day, under labels in their own column when it fits."""
    wide = width >= WIDE
    inner = width - (LABEL_W + 1 if wide else 2)
    sections: list[tuple[str, RenderableType]] = []
    if p.moves:
        sections.append(("Moves", moves(p, pal, inner)))
    if p.starters:
        sections.append(("Lineup", lineup(p, pal, inner)))
    if p.bench:
        sections.append(("Bench", bench(p, cal, pal, inner)))
    grid = Table.grid()
    if wide:
        grid.add_column(width=LABEL_W, no_wrap=True)
        grid.add_column(width=1)
        grid.add_column(max_width=inner)
        for i, (label, body) in enumerate(sections):
            if i:
                grid.add_row("", "", "")
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


def moves(p: DayPlan, pal: Palette, width: int) -> Table:
    """ "Pascal Siakam   BE → PF   41.1": who moves, from which slot to which, and what he
    projects in his new slot. When the width allows, the players going to the bench get a
    column of their own on the right, so each row reads like a swap."""
    narrow = width < 44
    values = {pl.id: v for pl, _, v in p.starters}
    ordered = sorted(p.moves, key=_order)

    def cells(m: Move | None) -> list[Text]:
        if m is None:
            return [Text(""), Text(""), Text("")]
        coming = m.to_slot not in (BENCH, IR)
        value = values.get(m.player.id) if coming else None
        name = m.player.short_name if narrow else m.player.name
        return [Text(name, style=pal.text),
                Text.assemble(("   ", ""), (f"{SLOT.get(m.from_slot, '?'):<2}", pal.info),
                              (" → ", pal.dim), (f"{SLOT.get(m.to_slot, '?'):<2}", pal.info)),
                Text(f"   {value:.1f}" if value is not None else "", style=pal.dim)]

    out = [m for m in ordered if m.to_slot in (BENCH, IR)]
    stay = [m for m in ordered if m.to_slot not in (BENCH, IR)]
    longest = max((len(m.player.name) for m in ordered), default=0)
    pair = bool(out and stay) and 2 * longest + 2 * 10 + 7 + 5 <= width
    t = Table.grid()
    for _ in range(2 if pair else 1):
        t.add_column(no_wrap=True, overflow="ellipsis")
        t.add_column(no_wrap=True)
        t.add_column(no_wrap=True)
    if not pair:
        for m in ordered:
            t.add_row(*cells(m))
        return t
    for i in range(max(len(stay), len(out))):
        left = cells(stay[i] if i < len(stay) else None)
        right = cells(out[i] if i < len(out) else None)
        right[0] = Text.assemble(("     ", ""), right[0])
        t.add_row(*left, *right)
    return t


def lineup(p: DayPlan, pal: Palette, width: int) -> Table:
    """The starters as a grid of "PG  L. Ball  46.4" cells, as many across as fit. A starter
    with no game that day (he cannot be moved out) shows dim with a dash."""
    starters = sorted(p.starters, key=lambda x: (x[1], -x[2]))
    narrow = width < 60
    names = [_surname(pl.name) if narrow else pl.short_name for pl, _, _ in starters]
    name_w = max((len(n) for n in names), default=4)
    gap = 3
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
            idle = not value
            color = pal.dim if idle else pal.info if pl.id in moved_in else pal.text
            cells += [Text(f"{' ' * gap if i else ''}{SLOT.get(slot, '?'):<2} ", style=pal.dim),
                      Text(f"{name:<{name_w}} ", style=color),
                      Text("  -" if idle else f"{value:.1f}", style=pal.dim)]
        cells += [Text("")] * (3 * across - len(cells))
        t.add_row(*cells)
    return t


def bench(p: DayPlan, cal: SeasonCalendar, pal: Palette, width: int) -> Table:
    """Who sits and why. Players with no game go on one line at the end."""
    narrow = width < 60
    t = Table.grid()
    t.add_column(no_wrap=True)
    t.add_column(ratio=1)
    idle: list[str] = []
    sitting = [(pl, why) for pl, why in p.bench if why != "no game"]
    name_w = max((len(pl.short_name if narrow else pl.name) for pl, _ in sitting), default=0) + 2
    for pl, why in p.bench:
        name = pl.short_name if narrow else pl.name
        if why == "no game":
            idle.append(name)
            continue
        line = reason(pl, why, p, cal, pal, narrow)
        compared = any(w in line.plain for w in (", below ", ", same as "))
        if compared and name_w + line.cell_len > width:
            line = reason(pl, why, p, cal, pal, narrow, split=True)
        t.add_row(Text(f"{name}  ", style=pal.text), line)
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
    factor = INJURY_FACTOR.get(pl.injury_status or "", 1.0)
    if factor == 0:
        return Text(pl.injury or "out", style=pal.bad)
    proj = round(pl.proj, 1)
    value = round(proj * factor, 1)
    out = Text()
    if factor < 1:
        out.append(pl.injury or "hurt", style=pal.warn)
        out.append(f": {proj:.1f} × {factor:.0%} = {value:.1f}", style=pal.dim)
    else:
        out.append(f"proj {value:.1f}", style=pal.dim)
    rival = _weakest_starter(pl, p)
    if rival is not None:
        other, other_value = rival
        name = other.short_name if narrow else other.name
        word = "below" if value < round(other_value, 1) else "same as"
        out.append(f"{chr(10) if split else ', '}{word} {name} {other_value:.1f}", style=pal.dim)
    return out


def _weakest_starter(pl: Player, p: DayPlan) -> tuple[Player, float] | None:
    """The starter with the lowest projection in a slot ``pl`` could fill."""
    slots = set(pl.eligible_slots)
    fits = [(other, v) for other, slot, v in p.starters if slot in slots and v]
    return min(fits, key=lambda x: x[1]) if fits else None


__all__ = ["draw", "gain", "plan", "reason"]

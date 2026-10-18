"""Rich renderables shared by the CLI and the TUI.

The screens with their own module (roster, standings, workload, trash, plan, finder,
playoffs) live in ui/screens; the functions here with those names are thin wrappers kept
for older callers.
"""

from __future__ import annotations

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from benchboss.core.trades import TradeIdea
from benchboss.espn.constants import POSITION
from benchboss.espn.models import League, Player
from benchboss.inbox import Alert
from benchboss.ui.common import fit_title, rost_cell
from benchboss.ui.common import injury as _inj
from benchboss.ui.common import num as _num
from benchboss.ui.common import table as _table
from benchboss.ui.screens.plan import plan
from benchboss.ui.theme import Palette

__all__ = ["activity", "alerts", "free_agents", "needs", "plan", "roster", "standings",
           "trades", "trash"]


def roster(league: League, pal: Palette, plays_today: set[int] | None = None) -> RenderableType:
    from benchboss.ui.screens import roster as screen

    return screen.draw(screen.RosterData(league, set(plays_today or ())), pal)


def standings(league: League, pal: Palette) -> RenderableType:
    from benchboss.ui.screens import standings as screen

    return screen.draw(league, pal)


def activity(acts, cal, periods: list[int], today_period: int, pal: Palette) -> RenderableType:
    from benchboss.ui.screens import workload as screen

    return screen.draw(screen.WorkloadData(acts, cal, periods, today_period), pal)


def trash(picks, cal, pal: Palette, width: int = 120) -> RenderableType:
    from benchboss.ui.screens import trash as screen

    return screen.trash(picks, cal, pal, width)

def trades(ideas: list[TradeIdea], pal: Palette, need: str | None = None,
           league: League | None = None, width: int | None = None) -> RenderableType:
    """The trade ideas, numbered. Without ``width`` they lay themselves out for the console
    they are printed on (the CLI); the app passes the width it has."""
    if not ideas:
        if need:
            full = _at_position_limit(league, need) if league else None
            if full:
                count, limit = full
                return Text(f"You already have {count} {need.upper()} and this league allows at most "
                            f"{limit}, so no trade can bring you another. Drop one or trade one away "
                            "first.", style=pal.dim)
            return Text(f"No fair 1-for-1 deal brings you a {need.upper()} right now. Try a lower "
                        "--fairness, or `benchboss trades --needs` to see who is deep there.",
                        style=pal.dim)
        return Text("No fair 1-for-1 fits right now. Try --need C (or PG, SG, SF, PF) or a lower "
                    "--fairness.", style=pal.dim)
    if width is None:
        return _TradesFit(ideas, pal)
    return _trades(ideas, pal, width)


INDENT = 3  # the deal and the message sit under the partner's name


def _trades(ideas: list[TradeIdea], pal: Palette, width: int) -> RenderableType:
    """The deal stays on one line when it fits; else "give", "get" and "fairness" get a line
    each, so a name never breaks between first and last. The partner line is cut, not
    wrapped."""
    parts: list[RenderableType] = []
    for i, t in enumerate(ideas, 1):
        parts.append(Text.assemble((f"{i}. {t.partner.name}", f"bold {pal.accent}"),
                                   (f"  ({t.partner.owner_name})" if t.partner.owner_name else "", pal.dim),
                                   no_wrap=True, overflow="ellipsis"))
        give = Text.assemble(("give ", pal.dim), (f"{t.give.name} ", pal.text),
                             (f"{t.give_pos} {t.give.proj:.1f}", pal.dim))
        get = Text.assemble(("get ", pal.dim), (f"{t.get.name} ", pal.text),
                            (f"{t.get_pos} {t.get.proj:.1f}", pal.dim))
        fair = Text(f"fairness {t.fairness:.0%}", style=pal.good)
        deal = Text.assemble(give, "   ", get, "   ", fair)
        lines = [deal] if INDENT + deal.cell_len <= width else [give, get, fair]
        for line in lines:
            line.no_wrap, line.overflow = True, "ellipsis"
        # the deal and the message wrap under their own indent, not back at column 0
        for line in (*lines, Text(f"\"{t.message()}\"", style=pal.dim)):
            parts.append(Padding(line, (0, 0, 0, INDENT), expand=False))
    return Group(*parts)


class _TradesFit:
    def __init__(self, ideas: list[TradeIdea], pal: Palette):
        self.ideas, self.pal = ideas, pal

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield _trades(self.ideas, self.pal, options.max_width)

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement(options.max_width, options.max_width)


def _at_position_limit(league: League, need: str) -> tuple[int, int] | None:
    """(players you have, league limit) when the position is already full, else None."""
    pos = next((k for k, v in POSITION.items() if v == need.upper()), None)
    limit = league.position_limits.get(pos, -1) if pos is not None else -1
    if limit is None or limit < 0:
        return None
    count = sum(1 for s in league.me.roster if s.player.position_id == pos)
    return (count, limit) if count >= limit else None


def needs(balance: dict[str, dict[str, float]], my_team: str, pal: Palette,
          width: int = 120) -> RenderableType:
    positions = ["PG", "SG", "SF", "PF", "C"]
    head = fit_title("Positional balance", pal, width,
                     ("vs league average", "proj. pts per game"), ("vs league average",))
    shown = {p: [_signed(b[p]) for b in balance.values()] for p in positions}
    # what the numbers take: their widths, one edge space on each side, 3 between columns
    numbers = sum(max([len(p)] + [len(v) for v in shown[p]]) for p in positions)
    t = _table(pal)
    # a long team name is cut, never wrapped onto a second row, and never cuts the numbers
    t.add_column("Team", no_wrap=True, overflow="ellipsis",
                 max_width=max(6, width - numbers - 2 - 3 * len(positions)))
    for p in positions:
        t.add_column(p, justify="right", no_wrap=True)
    for team, b in balance.items():
        cells = [Text(_signed(b[p]), style=pal.good if b[p] > 5 else pal.bad if b[p] < -5 else pal.dim)
                 for p in positions]
        t.add_row(Text(team, style=f"bold {pal.accent}" if team == my_team else pal.text), *cells)
    return Group(head, t)


def _signed(v: float) -> str:
    """ "+9", "-17", and "0" for anything that rounds to zero (never "-0")."""
    r = round(v)
    return f"{r:+d}" if r else "0"


def alerts(items: list[Alert], pal: Palette) -> RenderableType:
    if not items:
        return Text("Nothing new: no trade offers, pending claims, unread messages or watch list "
                    "news.", style=pal.dim)
    grid = Table.grid(padding=(0, 1))  # a long alert wraps under its text, not under the mark
    grid.add_column(no_wrap=True)
    grid.add_column()
    for a in items:
        text = Text(a.text, style=pal.text)
        prefix = "Watch list · "
        if a.kind == "spin" and a.text.startswith(prefix):
            text.stylize(pal.dim, 0, len(prefix))
            text.stylize("bold", len(prefix), len(prefix) + len(a.player))
            mark = Text("★", style=pal.accent)
        else:
            mark = Text("●" if a.urgent else "·", style=pal.accent if a.urgent else pal.dim)
        grid.add_row(mark, text)
    return grid


def free_agents(players: list[Player], pal: Palette, title: str) -> RenderableType:
    t = _table(pal, title)
    for col, kw in (("Player", {}), ("Pos", {}), ("Team", {}), ("Inj", {}), ("Rost%", {}),
                    ("Avg", {"justify": "right"}), ("L15", {"justify": "right"}),
                    ("Proj", {"justify": "right"}), ("", {})):
        t.add_column(col, **kw)
    for p in players:
        t.add_row(p.name, p.positions, p.pro_team, _inj(p, pal), rost_cell(p, pal),
                  _num(p.avg) + ("*" if p.avg_is_last_season else ""), _num(p.last15), _num(p.proj),
                  Text("waivers", style=pal.warn) if p.status == "WAIVERS" else "")
    return t

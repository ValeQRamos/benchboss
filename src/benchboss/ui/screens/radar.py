"""Trash radar: who just played his way onto your list.

Box scores of the games that just ended say who had a big night, who played far more minutes
than usual and who started from the bench. ESPN's stat splits, which catch up by the next
morning, add a week of more minutes, a week of better form and a rise in % rostered. Only free
agents (and players on waivers) show. ``benchboss radar`` prints the same table.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.text import Text

from benchboss.core import radar as core
from benchboss.core.radar import Pick
from benchboss.ui.common import fit_title, player_cell, rost_cell, table
from benchboss.ui.theme import Palette

TITLE = "Trash radar"
VIEWS: tuple[tuple[str, str], ...] = ()
MAX_DAYS = 7
WIDE = 80          # from this width the last game and the % rostered columns show
HINT = 'benchboss add "Player" --drop "Player"'
HINT_LINES = ('benchboss add "Player"', '  --drop "Player"')  # on a phone


@dataclass
class RadarData:
    picks: list[Pick]
    days: int
    games: int = 0         # box score lines read


def load(session, n: int = 15, days: int = 2) -> RadarData:
    days = max(1, min(days, MAX_DAYS))
    lines = session.box_lines(days)
    lg = session.league()
    rostered = {sp.player.id for t in lg.teams.values() for sp in t.roster}
    ids = core.candidates(lines, rostered, lg.scoring)
    players = session.players_with_splits(ids) if ids else []
    # without box scores yet (the day's games have not ended) the splits can still speak:
    # ask for the free agents ESPN says are rising
    if not players:
        players = session.player_pool("fa", None, 60, "change")
    return RadarData(core.build(lines, players, lg.scoring)[:n], days, len(lines))


def to_json(data: RadarData) -> list[dict]:
    return [p.to_dict() for p in data.picks]


def _last_game(pick: Pick, pal: Palette) -> Text:
    ln = pick.line
    if ln is None:
        return Text("-", style=pal.border)
    return Text(f"{ln.day:%a} {pick.fpts or 0.0:.1f} fp {ln.minutes:.0f}m"
                + (" S" if ln.starter else ""), style=pal.text)


def _why(pick: Pick, pal: Palette) -> Text:
    out = Text()
    for i, r in enumerate(pick.reasons):
        if i:
            out.append("\n")
        out.append(f"{r.label}: ", style=f"bold {pal.accent if r.fast else pal.dim}")
        out.append(r.text, style=pal.text if r.fast else pal.dim)
    return out


def draw(data: RadarData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    span = "last night" if data.days == 1 else f"last {data.days} days"
    head = fit_title(TITLE, pal, width, (span, "box scores and stat splits"), (span,))
    if not data.picks:
        return Group(head, Text(""), Text("Nobody stands out yet. Box scores of the games that "
                                          "ended show up here within minutes.", style=pal.dim))
    wide = width >= WIDE
    t = table(pal)
    t.add_column("Player", no_wrap=True, overflow="ellipsis", max_width=max(16, width // 3))
    t.add_column("Why", overflow="fold")
    if wide:
        t.add_column("Last game", no_wrap=True)
        t.add_column("Rost%", no_wrap=True)
    for pk in data.picks:
        row = [player_cell(pk.player, pal, team=wide, short=not wide), _why(pk, pal)]
        if wide:
            row += [_last_game(pk, pal), rost_cell(pk.player, pal)]
        t.add_row(*row)
    legend = Text("Orange: from the box score of a game that just ended. Grey: the stat splits, "
                  "which catch up by morning.", style=pal.dim)
    lead = "Grab one:"
    sep = " " if len(lead) + 1 + len(HINT) <= width else "\n"
    hint = HINT if sep == " " else "\n".join(HINT_LINES)
    return Group(head, Text(""), t, legend, Text(f"\n{lead}{sep}{hint}", style=pal.dim))

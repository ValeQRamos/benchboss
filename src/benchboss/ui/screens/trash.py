"""Best trash: free agents ranked by the points they add this matchup week."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.text import Text

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.trash import TrashPick
from benchboss.ui.common import day_label, injury, num, table
from benchboss.ui.theme import Palette

TITLE = "Best trash"
VIEWS: tuple[tuple[str, str], ...] = ()


@dataclass
class TrashData:
    picks: list[TrashPick]
    calendar: SeasonCalendar


def load(session, n: int = 12, position: str | None = None) -> TrashData:
    return TrashData(session.trash(n=n, position=position, pool=max(60, n * 4)), session.calendar)


def draw(data: TrashData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    return Group(trash(data.picks, data.calendar, pal, width),
                 Text("\nGrab one from a terminal: benchboss add \"Player\" --drop \"Player\"",
                      style=pal.dim))


def to_json(data: TrashData) -> list[dict]:
    return [p.to_dict(data.calendar) for p in data.picks]


def trash(picks: list[TrashPick], cal: SeasonCalendar, pal: Palette,
          width: int = 120) -> RenderableType:
    """Free agents by net points added this week, fitted to ``width`` columns.

    Below 110 columns (or when the full table is wider than ``width``) the NBA team and the
    injury fold into the player name and the position and ownership columns go. If that is
    still too wide, the grab day gets shorter, then the Drop column goes (the drop is named
    in the caption when it is the same player on every row), then Proj, +Pts and #, and only
    then long names are cut. Net and G, the columns the list is ranked by, always show in full.
    """
    drops = {pk.drop.name for pk in picks if pk.drop}
    right = {"justify": "right"}

    def grab(pk: TrashPick, short: bool) -> str:
        if not pk.best_day:
            text = "-"
        else:
            d = cal.date_of(pk.best_day)
            text = f"{d:%a} {d.day}" if short else day_label(d)
        return text + (" (W)" if pk.on_waivers else "")

    def columns(compact: bool) -> dict[str, tuple[dict, list]]:
        names = []
        for pk in picks:
            name = Text(pk.player.name, style=pal.text)
            if compact:
                name.append(f" {pk.player.pro_team}", style=pal.dim)
                if pk.player.injury:
                    name.append(f" {pk.player.injury}", style=pal.warn)
            names.append(name)
        cols: dict[str, tuple[dict, list]] = {
            "#": (right, [str(i) for i in range(1, len(picks) + 1)]),
            "Player": ({"overflow": "ellipsis"}, names)}
        if not compact:
            cols["Pos"] = ({}, [pk.player.positions for pk in picks])
            cols["Team"] = ({}, [pk.player.pro_team for pk in picks])
            cols["Inj"] = ({}, [injury(pk.player, pal) for pk in picks])
        cols["Proj"] = (right, [num(pk.player.proj) for pk in picks])
        cols["G"] = (right, [str(pk.games_left) for pk in picks])
        cols["Grab"] = ({}, [grab(pk, False) for pk in picks])
        cols["+Pts"] = (right, [f"{pk.gain:.1f}" for pk in picks])
        cols["Drop"] = ({"overflow": "ellipsis"},
                        [Text((pk.drop.name + ("*" if pk.drop_projects_higher else ""))
                              if pk.drop else "-", style=pal.dim) for pk in picks])
        cols["Net"] = (right, [Text(f"{pk.net:+.1f}", style=f"bold {pal.good}" if pk.net > 0 else pal.dim)
                             for pk in picks])
        if not compact:
            cols["Own%"] = (right, [f"{pk.player.owned:.1f}" for pk in picks])
        return cols

    def size(head: str, cells: list) -> int:
        return max([cell_len(head)] + [c.cell_len if isinstance(c, Text) else cell_len(c) for c in cells])

    def need(cols: dict, player: int) -> int:
        # every column is padded by one space on each side except at the outer edges, plus
        # one edge space on each side and one divider between columns
        return player + sum(size(k, v[1]) for k, v in cols.items() if k != "Player") + 3 * len(cols) - 1

    cols = columns(compact=False)
    if width < 110 or need(cols, size("Player", cols["Player"][1])) > width:
        cols = columns(compact=True)
    full = size("Player", cols["Player"][1])
    if need(cols, full) > width:
        cols["Grab"] = ({}, [grab(pk, True) for pk in picks])
    if need(cols, full) > width and len(drops) <= 1:
        cols.pop("Drop")
    for key in ("Proj", "+Pts", "Drop", "#"):
        if need(cols, min(full, 16)) <= width:
            break
        cols.pop(key, None)

    t = table(pal, "Most valuable trash this week")
    room = width - need(cols, 0)
    for head, (kw, _) in cols.items():
        extra = {"max_width": max(6, room)} if head == "Player" and room < full else {}
        t.add_column(head, no_wrap=True, **kw, **extra)
    for i in range(len(picks)):
        t.add_row(*[cells[i] for _, cells in cols.values()])

    who = "the suggested drop"
    if "Drop" not in cols and len(drops) == 1:
        who = f"{next(iter(drops))}, the suggested drop,"
    gain = "points he adds over your weakest starter on the days he plays, from the grab day to Sunday"
    if "+Pts" in cols:
        caption = f"+Pts = {gain}. Net subtracts what {who} would have scored."
    else:
        caption = f"Net = {gain}, minus what {who} would have scored."
    caption += " G = games he can still play for you."
    if any(pk.drop_projects_higher for pk in picks):
        caption += (" * = the drop scores more per game than the pickup: a one-week stream, not an upgrade."
                    if "Drop" in cols else
                    " Some picks mean dropping a player who scores more per game: one-week streams.")
    t.caption = caption
    return t

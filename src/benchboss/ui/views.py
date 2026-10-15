"""Rich renderables for every command. Shared by the CLI and the TUI."""

from __future__ import annotations

import datetime as dt

from rich import box
from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from benchboss.core.activity import Activity
from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import DayPlan
from benchboss.core.trades import TradeIdea
from benchboss.core.trash import TrashPick
from benchboss.espn.constants import BENCH, IR, POSITION, SLOT
from benchboss.espn.models import League, Player
from benchboss.inbox import Alert
from benchboss.news import NewsItem
from benchboss.ui.theme import Palette


def _table(pal: Palette, title: str | None = None, caption: str | None = None) -> Table:
    return Table(title=title, caption=caption, box=box.SIMPLE_HEAD, header_style=f"bold {pal.dim}",
                 title_style=f"bold {pal.accent}", title_justify="left",
                 caption_style=pal.dim, caption_justify="left", border_style=pal.border,
                 pad_edge=False, expand=False)


def _day(d: dt.date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def _num(v, fmt="{:.1f}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "-"


def _inj(p: Player, pal: Palette) -> Text:
    return Text(p.injury, style=pal.bad if p.injury in ("OUT", "SUSP", "IR") else pal.warn)


def roster(league: League, pal: Palette, plays_today: set[int] | None = None) -> RenderableType:
    me = league.me
    t = _table(pal, f"{me.name}  ·  {me.record}")
    for col, kw in (("Slot", {}), ("Player", {}), ("Pos", {}), ("Team", {}), ("Inj", {}),
                    ("Avg", {"justify": "right"}), ("L15", {"justify": "right"}),
                    ("Proj", {"justify": "right"}), ("Today", {"justify": "center"})):
        t.add_column(col, **kw)
    order = sorted(me.roster, key=lambda s: (s.slot_id + 100 if s.slot_id in (BENCH, IR) else s.slot_id,
                                             -s.player.proj))
    for s in order:
        p = s.player
        style = pal.dim if not s.is_starting else pal.text
        avg = _num(p.avg) + ("*" if p.avg_is_last_season else "")
        t.add_row(Text(s.slot, style=pal.dim), Text(p.name, style=style), p.positions, p.pro_team,
                  _inj(p, pal), avg, _num(p.last15), Text(_num(p.proj), style=style),
                  Text("●", style=pal.good) if plays_today and p.id in plays_today else "")
    t.caption = "Avg = season average (* last season) · L15 = last 15 days · Proj = ESPN projection"
    return t


def standings(league: League, pal: Palette) -> RenderableType:
    t = _table(pal, league.name)
    for col, kw in (("#", {"justify": "right"}), ("Team", {}), ("Manager", {}),
                    ("Record", {}), ("PF", {"justify": "right"})):
        t.add_column(col, **kw)
    for i, team in enumerate(league.standings()):
        mine = team.id == league.my_team_id
        t.add_row(str(i + 1), Text(team.name, style=f"bold {pal.accent}" if mine else pal.text),
                  team.owner_name, team.record, f"{team.points_for:,.1f}")
    return t


def activity(acts: list[Activity], cal: SeasonCalendar, periods: list[int], today_period: int,
             pal: Palette) -> RenderableType:
    t = _table(pal, "Games this matchup week")
    t.add_column("Player")
    t.add_column("G", justify="right")
    t.add_column("Left", justify="right")
    for sp in periods:
        d = cal.date_of(sp)
        head = f"{d:%a}\n{d.day}"
        t.add_column(head, justify="center", header_style=f"bold {pal.accent}" if sp == today_period else None)
    for a in acts:
        cells = []
        for sp, opp in zip(periods, a.schedule, strict=False):
            style = pal.dim if sp < today_period else pal.text
            cells.append(Text(opp.replace("vs ", "").replace("@ ", "@") if opp else "·",
                              style=style if opp else pal.border))
        color = pal.good if a.games >= 4 else pal.warn if a.games <= 2 else pal.text
        t.add_row(f"{a.player.name} ({a.player.pro_team})", Text(str(a.games), style=f"bold {color}"),
                  str(a.games_left), *cells)
    t.caption = "Opponent per day (@ = away). Volume wins in daily leagues: favor 4-game weeks."
    return t


def plan(plans: list[DayPlan], cal: SeasonCalendar, pal: Palette) -> RenderableType:
    parts: list[RenderableType] = []
    for p in plans:
        head = Text.assemble((_day(cal.date_of(p.period)), f"bold {pal.accent}"),
                             (f"   projected {p.projected:.1f} pts", pal.dim))
        parts.append(head)
        if p.moves:
            for m in p.moves:
                parts.append(Text.assemble(("  ↳ ", pal.dim), (m.player.name, pal.text),
                                           (f"  {SLOT.get(m.from_slot)} → {SLOT.get(m.to_slot)}", pal.info)))
        else:
            parts.append(Text("  already optimal", style=pal.good))
        if p.bench:
            bench = ", ".join(f"{pl.name} ({why})" for pl, why in p.bench)
            parts.append(Text(f"  bench: {bench}", style=pal.dim))
    return Group(*parts)


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
    num = {"justify": "right"}

    def grab(pk: TrashPick, short: bool) -> str:
        if not pk.best_day:
            text = "-"
        else:
            d = cal.date_of(pk.best_day)
            text = f"{d:%a} {d.day}" if short else _day(d)
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
            "#": (num, [str(i) for i in range(1, len(picks) + 1)]),
            "Player": ({"overflow": "ellipsis"}, names)}
        if not compact:
            cols["Pos"] = ({}, [pk.player.positions for pk in picks])
            cols["Team"] = ({}, [pk.player.pro_team for pk in picks])
            cols["Inj"] = ({}, [_inj(pk.player, pal) for pk in picks])
        cols["Proj"] = (num, [_num(pk.player.proj) for pk in picks])
        cols["G"] = (num, [str(pk.games_left) for pk in picks])
        cols["Grab"] = ({}, [grab(pk, False) for pk in picks])
        cols["+Pts"] = (num, [f"{pk.gain:.1f}" for pk in picks])
        cols["Drop"] = ({"overflow": "ellipsis"},
                        [Text((pk.drop.name + ("*" if pk.drop_projects_higher else ""))
                              if pk.drop else "-", style=pal.dim) for pk in picks])
        cols["Net"] = (num, [Text(f"{pk.net:+.1f}", style=f"bold {pal.good}" if pk.net > 0 else pal.dim)
                             for pk in picks])
        if not compact:
            cols["Own%"] = (num, [f"{pk.player.owned:.1f}" for pk in picks])
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

    t = _table(pal, "Most valuable trash this week")
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


def trades(ideas: list[TradeIdea], pal: Palette, need: str | None = None,
           league: League | None = None) -> RenderableType:
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
    parts: list[RenderableType] = []
    for i, t in enumerate(ideas, 1):
        parts.append(Text.assemble((f"{i}. {t.partner.name}", f"bold {pal.accent}"),
                                   (f"  ({t.partner.owner_name})" if t.partner.owner_name else "", pal.dim)))
        parts.append(Text.assemble(("   give ", pal.dim), (f"{t.give.name} ", pal.text),
                                   (f"{t.give_pos} {t.give.proj:.1f}", pal.dim),
                                   ("   get ", pal.dim), (f"{t.get.name} ", pal.text),
                                   (f"{t.get_pos} {t.get.proj:.1f}", pal.dim),
                                   (f"   fairness {t.fairness:.0%}", pal.good)))
        parts.append(Text(f"   \"{t.message()}\"", style=pal.dim))
    return Group(*parts)


def _at_position_limit(league: League, need: str) -> tuple[int, int] | None:
    """(players you have, league limit) when the position is already full, else None."""
    pos = next((k for k, v in POSITION.items() if v == need.upper()), None)
    limit = league.position_limits.get(pos, -1) if pos is not None else -1
    if limit is None or limit < 0:
        return None
    count = sum(1 for s in league.me.roster if s.player.position_id == pos)
    return (count, limit) if count >= limit else None


def needs(balance: dict[str, dict[str, float]], my_team: str, pal: Palette) -> RenderableType:
    positions = ["PG", "SG", "SF", "PF", "C"]
    t = _table(pal, "Positional balance vs league average (proj. pts per game)")
    t.add_column("Team")
    for p in positions:
        t.add_column(p, justify="right")
    for team, b in balance.items():
        cells = [Text(f"{b[p]:+.0f}", style=pal.good if b[p] > 5 else pal.bad if b[p] < -5 else pal.dim)
                 for p in positions]
        t.add_row(Text(team, style=f"bold {pal.accent}" if team == my_team else pal.text), *cells)
    return t


def news(items: list[NewsItem], names: dict[int, str], pal: Palette, days: int) -> RenderableType:
    if not items:
        return Text(f"No news in the last {days} days.", style=pal.dim)
    parts: list[RenderableType] = []
    for it in items:
        local = it.published.astimezone()
        who = ", ".join(names.get(p, str(p)) for p in sorted(it.player_ids))
        parts.append(Text.assemble((who, f"bold {pal.accent}"), (f"  {local:%a %b %d %I:%M %p}", pal.dim),
                                   (f"  {it.source}", pal.dim)))
        parts.append(Text(it.headline, style=pal.text))
        if it.spin:
            parts.append(Text.assemble(("Spin: ", f"bold {pal.dim}"), (it.spin, pal.dim)))
        parts.append(Text(""))
    return Group(*parts)


def alerts(items: list[Alert], pal: Palette) -> RenderableType:
    if not items:
        return Text("Nothing new: no trade offers, pending claims or unread messages.", style=pal.dim)
    return Group(*[Text.assemble(("● " if a.urgent else "· ", pal.accent if a.urgent else pal.dim),
                                 (a.text, pal.text)) for a in items])


def free_agents(players: list[Player], pal: Palette, title: str) -> RenderableType:
    t = _table(pal, title)
    for col, kw in (("Player", {}), ("Pos", {}), ("Team", {}), ("Inj", {}),
                    ("Own%", {"justify": "right"}), ("Δ%", {"justify": "right"}),
                    ("Avg", {"justify": "right"}), ("L15", {"justify": "right"}),
                    ("Proj", {"justify": "right"}), ("", {})):
        t.add_column(col, **kw)
    for p in players:
        t.add_row(p.name, p.positions, p.pro_team, _inj(p, pal), f"{p.owned:.1f}",
                  Text(f"{p.owned_change:+.1f}", style=pal.good if p.owned_change > 0 else pal.dim),
                  _num(p.avg) + ("*" if p.avg_is_last_season else ""), _num(p.last15), _num(p.proj),
                  Text("waivers", style=pal.warn) if p.status == "WAIVERS" else "")
    return t

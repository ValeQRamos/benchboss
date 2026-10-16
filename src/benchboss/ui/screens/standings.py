"""Standings: the league table, the divisions and every team's moves.

Three views (v cycles them in the app, ``--view`` picks one on the CLI):

- league: ESPN's seed order with the record, points for and against, the difference, the
  streak and ESPN's playoff odds. A dashed rule marks the playoff line.
- divisions: one table per division, by record, with the division record, games back
  within the division and ESPN's odds to win it.
- moves: the waiver order (1st claims first) and each team's adds, drops and trades.

Every table sheds secondary columns as the width shrinks (Manager first, then the meters,
then Strk and Pct), then rounds points and tightens the spacing, and only then cuts team
names, so the league table keeps W-L, PF, PA and Diff down to about 30 columns. Before the
first results (the preseason, or week 1 in progress) everybody is 0-0: the numbers read "-"
and a line says why.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, replace

from rich import box
from rich.cells import cell_len
from rich.console import Console, Group, RenderableType
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from benchboss.espn.models import League, Team
from benchboss.ui.common import legend, meter, odds_color, table, title
from benchboss.ui.theme import Palette

TITLE = "Standings"
VIEWS: tuple[tuple[str, str], ...] = (("league", "League"), ("divisions", "Divisions"),
                                      ("moves", "Moves"))

# ESPN's clinch flags (Team.clinch) -> (the tag after the team name, what it means)
CLINCH = {"PLAYOFFS": ("x", "clinched playoffs"), "DIVISION": ("y", "clinched division"),
          "BYE": ("z", "clinched bye"), "TOP_SEED": ("*", "clinched top seed"),
          "ELIMINATED": ("e", "eliminated")}

LINE = "╌"   # the playoff line
METER = 10   # cells in an odds or activity meter
MIN_NAME = 8  # team names are never cut shorter than this; a key column goes first

# common.table's look (SIMPLE_HEAD) plus a dashed rule between sections: the playoff line
BOX = box.Box("    \n"
              "    \n"
              " ── \n"
              "    \n"
              f" {LINE}{LINE} \n"
              "    \n"
              "    \n"
              "    \n")


def load(session) -> League:
    return session.league()


def draw(league: League, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    key = VIEWS[view % len(VIEWS)][0]
    if key == "divisions":
        return _divisions(league, pal, width)
    if key == "moves":
        return _moves(league, pal, width)
    return _league(league, pal, width)


def to_json(league: League) -> list[dict]:
    divs = _division_names(league)
    return [{"rank": i + 1, "team": t.name, "manager": t.owner_name, "record": t.record,
             "wins": t.wins, "losses": t.losses, "ties": t.ties,
             "win_pct": round(win_pct(t), 3), "games_back": t.games_back,
             "points_for": round(t.points_for, 1), "points_against": round(t.points_against, 1),
             "point_diff": round(t.point_diff, 1), "streak": t.streak or None,
             "playoff_pct": None if t.playoff_pct is None else round(t.playoff_pct, 4),
             "clinch": t.clinch or None, "division": divs.get(t.division_id),
             "division_record": _record(t.division_record),
             "waiver_rank": t.waiver_rank, "acquisitions": t.acquisitions, "drops": t.drops,
             "trades": t.trades}
            for i, t in enumerate(league.standings())]


# --- numbers ------------------------------------------------------------------------------------

def win_pct(t: Team) -> float:
    """Wins plus half the ties over games played; 0 before the first result."""
    return (t.wins + t.ties / 2) / t.games if t.games else 0.0


def division_gb(leader: Team, t: Team) -> float:
    return max(0.0, ((leader.wins - t.wins) + (t.losses - leader.losses)) / 2)


def _record(wlt: tuple[int, int, int]) -> str:
    w, lo, ti = wlt
    return f"{w}-{lo}" + (f"-{ti}" if ti else "")


def _pct3(t: Team) -> str:
    """".750" the baseball way, "1.000" for an unbeaten team, "-" before the first result."""
    if not t.games:
        return "-"
    shown = f"{win_pct(t):.3f}"
    return shown[1:] if shown.startswith("0") else shown


def _gb(gb: float) -> str:
    return "-" if gb <= 0 else f"{gb:.1f}"


def _points(v: float, digits: int) -> str:
    """digits: 1 = "3,218.8", 0 = "3,219", -1 = "3219" (the narrowest)."""
    return f"{v:.0f}" if digits < 0 else f"{v:,.{digits}f}"


def _odds(v: float | None) -> str:
    if v is None:
        return "-"
    if 0 < v < 0.005:
        return "<1%"
    if 0.995 <= v < 1:
        return ">99%"
    return f"{v * 100:.0f}%"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _clinch(t: Team) -> tuple[str, str] | None:
    flag = (t.clinch or "").upper()
    for key in ("ELIMINATED", "TOP_SEED", "BYE", "DIVISION", "PLAYOFF"):
        if key in flag:
            return CLINCH["PLAYOFFS" if key == "PLAYOFF" else key]
    return None


def _clinch_legend(teams) -> list[tuple[str, str]]:
    seen = {tag for tag in (_clinch(t) for t in teams) if tag}
    return [tag for tag in CLINCH.values() if tag in seen]


def _division_names(league: League) -> dict[int | None, str]:
    names = {k: v for k, v in league.divisions.items() if v}
    for t in league.teams.values():
        if t.division_id is not None and t.division_id not in names:
            names[t.division_id] = f"Division {t.division_id + 1}"
    return names


def _no_results(league: League) -> bool:
    return not any(t.games or t.points_for for t in league.teams.values())


# --- cells --------------------------------------------------------------------------------------

def _team_cell(t: Team, league: League, pal: Palette, clinch: bool = True,
               width: int | None = None) -> Text:
    """The name (yours in bold accent), then ESPN's clinch tag. ``width`` cuts the name with
    an ellipsis but keeps the tag, which the legend explains."""
    mine = t.id == league.my_team_id
    tag = _clinch(t) if clinch else None
    suffix = f" {tag[0]}" if tag else ""
    out = Text(t.name, style=f"bold {pal.accent}" if mine else pal.text, no_wrap=True,
               overflow="ellipsis")
    if width is not None:
        out.truncate(max(1, width - len(suffix)), overflow="ellipsis")
    if tag:
        out.append(suffix, style=f"bold {pal.bad if tag[0] == 'e' else pal.good}")
    return out


def _rank_cell(label: str, t: Team, league: League, pal: Palette) -> Text:
    return Text(label, style=pal.accent if t.id == league.my_team_id else pal.dim)


def _points_cell(t: Team, v: float, pal: Palette, digits: int) -> Text:
    if not t.games and not v:
        return Text("-", style=pal.dim)
    return Text(_points(v, digits), style=pal.text)


def _diff_cell(t: Team, pal: Palette, digits: int) -> Text:
    if not t.games and not t.points_for:
        return Text("-", style=pal.dim)
    v = t.point_diff
    shown = _points(abs(v), digits)
    if not float(shown.replace(",", "")):
        return Text(shown, style=pal.dim)
    return Text(("+" if v > 0 else "-") + shown, style=pal.good if v > 0 else pal.bad)


def _streak_cell(t: Team, pal: Palette) -> Text:
    s = t.streak
    if not s:
        return Text("-", style=pal.dim)
    color = {"W": pal.good, "L": pal.bad}.get(s[0], pal.dim)
    return Text(s, style=f"bold {color}" if t.streak_length >= 3 else color)


def _odds_color(v: float | None, pal: Palette) -> str:
    return pal.dim if v is None else odds_color(v, pal)


def _odds_cell(v: float | None, pal: Palette, bar: bool) -> Text:
    out = Text(f"{_odds(v):>4}" if bar else _odds(v), style=pal.text if v is not None else pal.dim)
    if bar:
        out.append(" ")
        out.append_text(meter(v, METER, pal, _odds_color(v, pal)))
    return out


# --- layout -------------------------------------------------------------------------------------

@dataclass
class Col:
    head: str
    cells: list
    justify: str = "left"
    # the one column cut when nothing else can go (team names): its cells at a given width
    cut: Callable[[int], list] | None = None
    head_style: str | None = None
    key: str = ""               # columns with the same key line up across tables

    def __post_init__(self):
        self.key = self.key or self.head


def _cell_len(cell) -> int:
    return cell.cell_len if isinstance(cell, Text) else cell_len(str(cell))


def _natural(renderable) -> int:
    """The width a renderable takes when nothing limits it."""
    console = Console(width=1000, file=io.StringIO())
    return Measurement.get(console, console.options, renderable).maximum


def _make(pal: Palette, cols: list[Col], line_after: int | None = None, tight: bool = False,
          widths: dict[str, int] | None = None, squeeze: int | None = None) -> Table:
    """A table in the common look. ``tight``: two spaces between columns and no edge, for
    narrow screens. ``widths``: minimum widths by column key, so stacked tables line up.
    ``squeeze``: cut the team names (the ``cut`` column) until the table fits that width."""
    widths = widths or {}
    t = _table(pal, cols, line_after, tight, widths)
    flex = next((i for i, c in enumerate(cols) if c.cut), None)
    excess = _natural(t) - squeeze if squeeze is not None else 0
    if excess > 0 and flex is not None:
        c = cols[flex]
        full = max([widths.get(c.key, 0), cell_len(c.head)] + [_cell_len(x) for x in c.cells])
        w = max(4, full - excess)
        t = _table(pal, [*cols[:flex], replace(c, cells=c.cut(w)), *cols[flex + 1:]],
                   line_after, tight, widths)
        t.columns[flex].width, t.columns[flex].min_width = w, None
    return t


def _table(pal: Palette, cols: list[Col], line_after: int | None, tight: bool,
           widths: dict[str, int]) -> Table:
    t = table(pal)
    t.box = BOX
    if tight:
        t.collapse_padding, t.show_edge = True, False
    for c in cols:
        # the cut column cuts its header too (a long division name) instead of wrapping it
        head = Text(c.head, no_wrap=True, overflow="ellipsis") if c.cut else c.head
        t.add_column(head, justify=c.justify, no_wrap=not c.cut, header_style=c.head_style,
                     min_width=widths.get(c.key))
    for i in range(len(cols[0].cells) if cols else 0):
        t.add_row(*[c.cells[i] for c in cols], end_section=line_after is not None and i == line_after)
    return t


def _shared_widths(groups: list[list[Col]]) -> dict[str, int]:
    widths: dict[str, int] = {}
    for cols in groups:
        for c in cols:
            widths[c.key] = max([widths.get(c.key, 0), cell_len(c.head)] + [_cell_len(x) for x in c.cells])
    return widths


def _fit(width: int, levels: list[dict], build: Callable[..., list[Table]],
         last_resort: tuple[dict, ...] = ()) -> tuple[list[Table], dict]:
    """The tables of the first level that fits ``width``. When none does, the last level with
    team names cut (never below MIN_NAME), then the ``last_resort`` steps, which drop key
    columns on screens too narrow for them."""
    for lv in levels:
        tables = build(lv, None)
        if all(_natural(t) <= width for t in tables):
            return tables, lv
    lv = levels[-1]
    for step in ({}, *last_resort):
        lv = {**lv, **step}
        tables = build(lv, width)
        if all(_natural(t) <= width and all((c.width or MIN_NAME) >= MIN_NAME for c in t.columns)
               for t in tables):
            break
    return tables, lv


def _levels(*steps: dict, **start) -> list[dict]:
    """Each level is the previous one with ``step`` applied: what to drop or tighten next."""
    out = [dict(start)]
    for step in steps:
        out.append({**out[-1], **step})
    return out


def _title(league: League, pal: Palette, width: int, *context: str) -> Text:
    """The title line, dropping context from the end until it fits."""
    parts = [p for p in context if p]
    name = league.name or TITLE
    out = title(name, pal, *parts)
    while out.cell_len > width and parts:
        parts.pop()
        out = title(name, pal, *parts)
    out.no_wrap, out.overflow = True, "ellipsis"
    if out.cell_len > width:
        out.truncate(width, overflow="ellipsis")
    return out


def _legend(pal: Palette, groups: list[list[tuple[str, str]]], width: int) -> Text:
    """The legend as dim lines that break between items, never inside one. Each group of
    items starts on a line of its own."""
    lines: list[list[tuple[str, str]]] = []
    for items in groups:
        start = len(lines)
        for item in items:
            if len(lines) > start and legend(pal, *lines[-1], item).cell_len <= width:
                lines[-1].append(item)
            else:
                lines.append([item])
    return Text("\n").join(legend(pal, *line) for line in lines)


def _week(league: League) -> str:
    weeks, cur = league.regular_season_weeks, league.current_matchup
    if weeks and cur > weeks:
        return "playoffs"
    return f"week {cur} of {weeks}" if weeks else f"week {cur}"


def _screen(league: League, pal: Palette, width: int, head: Text, tables: list[Table],
            *legends: list[tuple[str, str]], results: bool = True) -> Group:
    parts: list[RenderableType] = [head]
    for t in tables:
        # a table with its edge brings a blank line above and below; a tight one gets them here
        parts += [t] if t.show_edge else [Text(""), t]
    if tables and not tables[-1].show_edge:
        parts.append(Text(""))
    if results and _no_results(league):
        note = "No results yet: records and points fill in when the first matchup ends."
        parts.append(Text(note if len(note) <= width else "No results yet.", style=pal.dim))
    if any(legends):
        parts.append(_legend(pal, [g for g in legends if g], width))
    return Group(*parts)


# --- league view --------------------------------------------------------------------------------

def _league(league: League, pal: Palette, width: int) -> Group:
    teams = league.standings()
    odds = any(t.playoff_pct is not None for t in teams)
    line = league.playoff_teams - 1 if 0 < league.playoff_teams < len(teams) else None
    right = "right"

    def columns(manager: bool, bar: bool, strk: bool, pct: bool, gb: bool, chances: bool,
                digits: int, tight: bool, pf: bool, pa: bool) -> list[Col]:
        cols = [Col("#", [_rank_cell(str(i + 1), t, league, pal) for i, t in enumerate(teams)], right),
                Col("Team", [_team_cell(t, league, pal) for t in teams],
                    cut=lambda w: [_team_cell(t, league, pal, width=w) for t in teams])]
        if manager:
            cols.append(Col("Manager", [Text(t.owner_name, style=pal.dim) for t in teams]))
        cols.append(Col("W-L-T" if any(t.ties for t in teams) else "W-L",
                        [Text(t.record, style=f"bold {pal.text}") for t in teams], right))
        if pct:
            cols.append(Col("Pct", [Text(_pct3(t), style=pal.dim) for t in teams], right))
        if gb:
            cols.append(Col("GB", [Text(_gb(t.games_back), style=pal.dim) for t in teams], right))
        if pf:
            cols.append(Col("PF", [_points_cell(t, t.points_for, pal, digits) for t in teams], right))
        if pa:
            cols.append(Col("PA", [_points_cell(t, t.points_against, pal, digits) for t in teams],
                            right))
        cols.append(Col("Diff", [_diff_cell(t, pal, digits) for t in teams], right))
        if strk:
            cols.append(Col("Strk", [_streak_cell(t, pal) for t in teams], right))
        if chances and odds:
            cols.append(Col("Playoffs", [_odds_cell(t.playoff_pct, pal, bar) for t in teams],
                            "left" if bar else right))
        return cols

    levels = _levels(dict(manager=False), dict(bar=False), dict(strk=False, pct=False),
                     dict(gb=False), dict(chances=False), dict(digits=0), dict(tight=True),
                     dict(digits=-1),
                     manager=True, bar=True, strk=True, pct=True, gb=True, chances=True,
                     digits=1, tight=False, pf=True, pa=True)
    tables, lv = _fit(width, levels, lambda lv, squeeze: [
        _make(pal, columns(**lv), line, lv["tight"], squeeze=squeeze)],
        last_resort=(dict(pa=False), dict(pf=False)))

    cut = f"top {league.playoff_teams} make the playoffs" if line is not None else ""
    head = _title(league, pal, width, _week(league), cut)
    items = [item for item, on in ((("PF", "points for"), lv["pf"]),
                                   (("PA", "points against"), lv["pa"])) if on]
    if lv["gb"]:
        items.append(("GB", "games back"))
    if lv["chances"] and odds:
        items.append(("Playoffs", "ESPN's odds"))
    if line is not None:
        items.append((LINE * 2, "playoff line"))
    return _screen(league, pal, width, head, tables, items, _clinch_legend(teams))


# --- divisions view -----------------------------------------------------------------------------

def _divisions(league: League, pal: Palette, width: int) -> Group:
    standings = league.standings()
    order = {t.id: i for i, t in enumerate(standings)}
    names = _division_names(league)
    groups: dict[int | None, list[Team]] = {}
    for t in standings:
        groups.setdefault(t.division_id, []).append(t)
    for teams in groups.values():
        teams.sort(key=lambda t: (-win_pct(t), -t.wins, order[t.id]))
    keys = sorted(groups, key=lambda k: (k is None, k if k is not None else 0))
    odds = any(t.division_win_pct is not None for t in standings)
    ties = any(t.ties for t in standings)
    right = "right"

    def columns(teams: list[Team], name: str, manager: bool, bar: bool, points: bool, strk: bool,
                chances: bool, digits: int, tight: bool, diff: bool, gb: bool) -> list[Col]:
        lead = teams[0]
        cols = [Col("#", [_rank_cell(str(i + 1), t, league, pal) for i, t in enumerate(teams)], right),
                Col(name, [_team_cell(t, league, pal) for t in teams],
                    cut=lambda w: [_team_cell(t, league, pal, width=w) for t in teams],
                    head_style=f"bold {pal.text}", key="team")]
        if manager:
            cols.append(Col("Manager", [Text(t.owner_name, style=pal.dim) for t in teams]))
        cols.append(Col("W-L-T" if ties else "W-L", [Text(t.record, style=f"bold {pal.text}")
                                                     for t in teams], right, key="record"))
        if gb:
            cols.append(Col("GB", [Text(_gb(division_gb(lead, t)), style=pal.dim) for t in teams],
                            right))
        cols += [Col("Div", [Text(_record(t.division_record),
                                  style=pal.text if sum(t.division_record) else pal.dim)
                             for t in teams], right)]
        if points:  # PF and PA go together: one without the other reads as a mistake
            cols += [Col("PF", [_points_cell(t, t.points_for, pal, digits) for t in teams], right),
                     Col("PA", [_points_cell(t, t.points_against, pal, digits) for t in teams],
                         right)]
        if diff:
            cols.append(Col("Diff", [_diff_cell(t, pal, digits) for t in teams], right))
        if strk:
            cols.append(Col("Strk", [_streak_cell(t, pal) for t in teams], right))
        if chances and odds:
            cols.append(Col("Win div", [_odds_cell(t.division_win_pct, pal, bar) for t in teams],
                            "left" if bar else right))
        return cols

    def build(lv: dict, squeeze: int | None) -> list[Table]:
        per = [columns(groups[k], names[k] if k is not None else
                       "League" if len(keys) == 1 else "No division", **lv) for k in keys]
        widths = _shared_widths(per)  # one width per column, so the stacked tables line up
        return [_make(pal, cols, tight=lv["tight"], widths=widths, squeeze=squeeze) for cols in per]

    # PF and PA are on the League view; here the race (GB, Div, Diff, Strk, odds) comes first
    levels = _levels(dict(manager=False), dict(bar=False), dict(points=False), dict(strk=False),
                     dict(chances=False), dict(digits=0), dict(tight=True),
                     manager=True, bar=True, points=True, strk=True, chances=True,
                     digits=1, tight=False, diff=True, gb=True)
    tables, lv = _fit(width, levels, build, last_resort=(dict(diff=False), dict(gb=False)))

    head = _title(league, pal, width, "Divisions", _week(league),
                  "" if any(k is not None for k in keys) else "no divisions in this league")
    items = [("GB", "games back in the division")] if lv["gb"] else []
    items.append(("Div", "record against the division"))
    if lv["chances"] and odds:
        items.append(("Win div", "ESPN's odds to win it"))
    return _screen(league, pal, width, head, tables, items, _clinch_legend(standings))


# --- moves view ---------------------------------------------------------------------------------

def _moves(league: League, pal: Palette, width: int) -> Group:
    order = {t.id: i for i, t in enumerate(league.standings())}
    teams = sorted(league.teams.values(),
                   key=lambda t: (t.waiver_rank is None, t.waiver_rank or 0, order[t.id]))
    most = max([t.acquisitions for t in teams] + [0])
    right = "right"

    def count(n: int, style: str) -> Text:
        return Text(str(n), style=style if n else pal.dim)

    def columns(manager: bool, bar: bool, tight: bool, drops: bool, trades: bool) -> list[Col]:
        cols = [Col("Waiver", [_rank_cell(_ordinal(t.waiver_rank) if t.waiver_rank else "-", t,
                                          league, pal) for t in teams], right),
                Col("Team", [_team_cell(t, league, pal, clinch=False) for t in teams],
                    cut=lambda w: [_team_cell(t, league, pal, False, w) for t in teams])]
        if manager:
            cols.append(Col("Manager", [Text(t.owner_name, style=pal.dim) for t in teams]))
        cols.append(Col("Adds", [count(t.acquisitions, f"bold {pal.text}") for t in teams], right))
        if drops:
            cols.append(Col("Drops", [count(t.drops, pal.text) for t in teams], right))
        if trades:
            cols.append(Col("Trades", [count(t.trades, pal.text) for t in teams], right))
        if bar:
            cols.append(Col("Activity", [meter(t.acquisitions / most if most else 0.0, METER, pal,
                                               pal.info) for t in teams]))
        return cols

    # drops mostly mirror adds (a full roster drops one to add one), so they go before names are cut
    levels = _levels(dict(manager=False), dict(bar=False), dict(tight=True), dict(drops=False),
                     manager=True, bar=most > 0, tight=False, drops=True, trades=True)
    tables, lv = _fit(width, levels, lambda lv, squeeze: [
        _make(pal, columns(**lv), tight=lv["tight"], squeeze=squeeze)],
        last_resort=(dict(trades=False),))

    adds = sum(t.acquisitions for t in teams)
    trades = (sum(t.trades for t in teams) + 1) // 2  # a trade counts once for each team
    kind = {"WAIVERS_TRADITIONAL": "traditional waivers", "FAAB": "budget waivers"}.get(
        league.acquisition_type, "")
    so_far = (f"{adds} add{'s' * (adds != 1)} and {trades} trade{'s' * (trades != 1)} so far"
              if adds or trades else "no moves yet")
    head = _title(league, pal, width, "Moves", so_far, kind)
    items = [("Waiver", "claim order, 1st picks first")]
    if lv["bar"]:
        items.append(("Activity", "adds, the busiest team fills the bar"))
    return _screen(league, pal, width, head, tables, items, results=False)

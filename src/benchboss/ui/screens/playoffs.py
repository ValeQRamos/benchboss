"""Playoff race: odds, who is in or out, and what-if scenarios for the weeks left.

The CLI prints one of two views (``benchboss playoffs --view odds|games``). The app mounts a
scenario builder instead: the matchups still to play on one side, the odds on the other.
Pick a winner with the arrow keys and the season is simulated again with that result fixed
(core.playoffs.race); a +/- column shows what your picks changed.
"""

from __future__ import annotations

import time
from functools import partial

from rich.box import Box
from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.containers import Container
from textual.widget import Widget
from textual.worker import get_current_worker

from benchboss.core.playoffs import Game, Race
from benchboss.errors import BenchbossError
from benchboss.ui.common import legend, meter, table, title
from benchboss.ui.theme import DARK, Palette

TITLE = "Playoff race"
VIEWS: tuple[tuple[str, str], ...] = (("odds", "Odds"), ("games", "Games left"))
FINAL_WEEKS = 5          # the "last 5 matches" of issue #1: the stretch the games view opens on
SCENARIO_SIMS = 2000     # simulated seasons per re-run in the scenario builder
DEBOUNCE = 0.12          # seconds the builder waits for more key presses before simulating
TIEBREAK = {"H2H_RECORD": "head-to-head record", "TOTAL_POINTS_SCORED": "points for",
            "INTRA_DIVISION_RECORD": "division record", "TOTAL_POINTS_AGAINST": "points against"}
CURSOR_BG = {"dark": "#30323a", "light": "#e3e7ec"}
TIGHT = "tight"          # a key in the fitted columns' options: collapse the padding between columns
GAMES_MIN = 5            # rows the builder keeps for the games list (its CSS min-height)

# common.table's look (a thin rule under the header), plus a dashed rule under a row that
# ends a section: the playoff line
_RACE_BOX = Box("    \n    \n ── \n    \n ╌╌ \n ── \n    \n    \n")


# --- data ---------------------------------------------------------------------------------------

def load(session, picks: dict[int, int] | None = None, sims: int = 5000) -> Race:
    """The race with ``picks`` fixed. With picks, the same race without them rides along as
    ``race.baseline`` (same simulated seasons), so the screen can show what they change."""
    race = session.playoff_race(picks or {}, sims)
    if picks:
        race.baseline = session.playoff_race({}, sims)
    return race


def to_json(race: Race) -> dict:
    out = race.to_dict()
    base = race.baseline
    if base is not None:
        for row, o in zip(out["teams"], race.teams, strict=True):
            before = base.odds(o.team.id)
            row["playoffs_without_picks"] = None if before is None else round(before.playoffs, 4)
    return out


def draw(race: Race, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    if view % len(VIEWS) == 1:
        return games_view(race, pal, width)
    return odds_view(race, pal, width)


def widget(race: Race, app) -> Widget:
    return PlayoffBuilder(race, app.session)


# --- formatting helpers -------------------------------------------------------------------------

def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _share(p: float, certain: bool = False) -> str:
    """A share as a percentage, never "0%" or "100%" unless it is certain."""
    if certain:
        return "100%" if p >= 1 else "0%" if p <= 0 else f"{p * 100:.0f}%"
    if p < 0.01:   # 0.5% would round to "0%"
        return "<1%"
    if p > 0.99:
        return ">99%"
    return f"{p * 100:.0f}%"


def _divisions(race: Race) -> bool:
    return len({o.team.division_id for o in race.teams} - {None}) > 1


def _div_short(name: str | None) -> str:
    """ "Eastern Division" -> "Eastern", "Division 2" -> "Div 2"."""
    if not name:
        return "-"
    words = [w for w in name.split() if w.lower() not in ("division", "div", "conference", "the")]
    text = " ".join(words) or name
    if len(text) <= 2:
        return f"Div {text}"
    return text if len(text) <= 9 else text.split()[0][:9]


def _names(race: Race) -> dict[int, str]:
    return {o.team.id: o.team.name for o in race.teams}


def _fit_line(pal: Palette, width: int, *variants: list[str]) -> Text:
    """The screen title with the first context variant that fits on one line."""
    for parts in variants:
        line = title(TITLE, pal, *parts)
        if line.cell_len <= width:
            return line
    return title(TITLE, pal, *variants[-1][:1])


def context(race: Race) -> list[list[str]]:
    """Context variants for the title line, longest first."""
    picks = _plural(len(race.picks), "pick") if race.picks else ""
    over = not race.games
    sims = "regular season over" if over else f"{race.sims:,} simulated seasons"
    short = "season over" if over else f"{race.sims:,} sims"
    if not race.playoff_teams:
        return [["no playoff spots set", sims, picks], ["no playoff spots", short, picks]]
    spots = _plural(race.playoff_teams, "spot")
    div = "division winners seeded first" if _divisions(race) else ""
    return [[spots, div, sims, picks], [spots, sims, picks], [spots, short, picks],
            [spots, picks or short]]


def _legend_lines(pal: Palette, items: list[tuple[str, str]], width: int) -> Text:
    """legend() items packed into as few lines as fit ``width``, never splitting an item."""
    lines: list[list[tuple[str, str]]] = [[]]
    for item in items:
        trial = legend(pal, *lines[-1], item)
        if lines[-1] and trial.cell_len > width:
            lines.append([item])
        else:
            lines[-1].append(item)
    return Text("\n").join(legend(pal, *line) for line in lines if line)


# --- odds ---------------------------------------------------------------------------------------

def odds_view(race: Race, pal: Palette, width: int) -> RenderableType:
    parts: list[RenderableType] = [_fit_line(pal, width, *context(race))]
    note = _note(race)
    if note:
        parts += [Text(""), Text(note, style=pal.dim)]
    cols, tight = fit_columns(race, pal, width)
    parts.append(odds_table(race, pal, cols, tight))  # its blank top and bottom lines space it out
    foot = odds_legend(race, pal, width, cols)
    if foot.plain:
        parts.append(foot)
    return Group(*parts)


def _note(race: Race) -> str:
    if not race.playoff_teams:
        return "No playoff spots are set in this league yet: projected records only."
    if not race.games:
        return "The regular season is over: the playoff field is set."
    return ""


def rows_in_view(race: Race, k: int) -> list[int]:
    """The ``k`` rows to show when not every team fits: yours, then the ones nearest the
    playoff line (the top of the table when there is no line)."""
    count = len(race.teams)
    if k >= count:
        return list(range(count))
    cut = race.playoff_teams - 0.5
    order = sorted(range(count), key=lambda i: (race.teams[i].team.id != race.me, abs(i - cut), i))
    return sorted(order[:max(1, k)])


def _columns(race: Race, pal: Palette, opt: dict, base: Race | None) -> list[tuple[str, dict, list]]:
    """The odds table's columns for the options in ``opt``: (header, column kwargs, cells)."""
    right = {"justify": "right"}
    rows = race.teams
    n = race.playoff_teams
    over = not race.games  # every result is in: the shares are certain

    def odds_cell(o, p: float) -> Text:
        if o.status == "eliminated" or (over and p <= 0):
            return Text("-", style=pal.border)
        return Text(_share(p, over), style=pal.text if p >= 0.05 else pal.dim)

    cols: list[tuple[str, dict, list]] = []
    if opt["rank"]:
        cols.append(("#", right, [Text(str(i + 1), style=pal.dim) for i in range(len(rows))]))
    team_cells = []
    for o in rows:
        style = (f"bold {pal.accent}" if o.team.id == race.me else
                 pal.dim if o.status == "eliminated" else pal.text)
        team_cells.append(Text(o.team.name, style=style))
    cols.append(("Team", {"overflow": "ellipsis", "max_width": opt["team"]}, team_cells))
    if opt["div"]:
        cols.append(("Div", {}, [Text(_div_short(race.divisions.get(o.team.division_id)),
                                      style=pal.dim) for o in rows]))
    cols.append(("W-L", {}, [Text(o.record, style=pal.text) for o in rows]))
    if opt["proj"] == "record":
        cols.append(("Proj", right, [Text(f"{o.proj_wins:.1f}-{o.proj_losses:.1f}", style=pal.dim)
                                     for o in rows]))
    elif opt["proj"] == "wins":
        cols.append(("Proj W", right, [Text(f"{o.proj_wins:.1f}", style=pal.dim) for o in rows]))
    if n:
        cells = []
        for o in rows:
            certain = bool(o.status)
            color = pal.good if o.status == "clinched" else pal.dim if o.status else pal.text
            share = Text(_share(o.playoffs, certain).rjust(4), style=f"bold {color}")
            if opt["bar"]:
                bar = meter(o.playoffs, 10, pal, pal.accent if o.team.id == race.me else pal.info)
                share = Text.assemble(share, " ", bar)
            cells.append(share)
        cols.append(("Playoffs", {} if opt["bar"] else right, cells))
        if base is not None:
            cells = []
            for o in rows:
                before = base.odds(o.team.id)
                d = round((o.playoffs - before.playoffs) * 100) if before else 0
                cells.append(Text(f"{d:+d}", style=f"bold {pal.good if d > 0 else pal.bad}")
                             if d else Text("·", style=pal.border))
            cols.append(("+/-", right, cells))
        if opt["seeds"]:
            for i in range(n):
                cells = [odds_cell(o, o.seeds[i] if i < len(o.seeds) else 0.0) for o in rows]
                cols.append((_ordinal(i + 1), right, cells))
        if opt["title"]:
            cols.append(("Div title", right, [odds_cell(o, o.division) for o in rows]))
        if opt["status"]:
            cols.append(("", {}, [Text("clinched", style=pal.good) if o.status == "clinched" else
                                  Text("out", style=pal.bad) if o.status == "eliminated" else Text("")
                                  for o in rows]))
        if opt["espn"]:
            cols.append(("ESPN", right, [Text("-" if o.espn is None else _share(o.espn), style=pal.dim)
                                         for o in rows]))
    return cols


def _need(cols: list[tuple[str, dict, list]], tight: bool = False) -> int:
    """Columns the table takes: one edge space each side, one divider and two pad spaces
    between columns (common.table: SIMPLE_HEAD, no padding at the edges); one pad space
    when ``tight`` (collapsed padding)."""
    total = sum(max([cell_len(head)] + [c.cell_len for c in cells]) for head, _, cells in cols)
    return total + (2 * len(cols) if tight else 3 * len(cols) - 1)


def fit_columns(race: Race, pal: Palette, width: int, base: Race | None = None
                ) -> tuple[list[tuple[str, dict, list]], bool]:
    """The odds table's columns fitted to ``width``, and whether they need the tight
    spacing: secondary columns go first (ESPN, the bars, the division, the seed odds, the
    division title), then the gaps between columns narrow, then the projected record and the
    rank go, and only then long team names are cut. ``base``: the race without picks, for
    the +/- column (race.baseline by default)."""
    base = base if base is not None else race.baseline
    if not race.picks:
        base = None
    rows = race.teams
    n = race.playoff_teams
    opt = {"rank": True, "team": None, "div": _divisions(race), TIGHT: False,
           "proj": "record" if race.games else None, "bar": True,
           "seeds": bool(n), "title": bool(n) and _divisions(race),
           "status": any(o.status for o in rows),
           "espn": not race.picks and any(o.espn is not None for o in rows)}
    full = dict(opt)
    steps = [("espn", False), ("bar", False), ("div", False), ("seeds", False), ("title", False),
             (TIGHT, True), ("proj", "wins"), ("rank", False), ("proj", None)]
    cols = _columns(race, pal, opt, base)
    names = max(cell_len(o.team.name) for o in rows) if rows else 4
    for key, value in steps:
        if _need(cols, tight=opt[TIGHT]) <= width:
            break
        if opt[key] != value and (key != "proj" or opt["proj"]):
            opt[key] = value
            cols = _columns(race, pal, opt, base)
    # something dropped may fit again once a wider column has gone (the seeds, say): bring
    # things back in the reverse order, most important first
    for key, _ in reversed(steps):
        for value in [full[key], "wins"] if key == "proj" else [full[key]]:
            if value == opt[key]:
                break
            trial_opt = {**opt, key: value}
            trial = _columns(race, pal, trial_opt, base)
            if _need(trial, tight=trial_opt[TIGHT]) <= width:
                opt, cols = trial_opt, trial
                break
    if _need(cols, tight=opt[TIGHT]) > width:
        opt["team"] = max(6, names - (_need(cols, tight=opt[TIGHT]) - width))
        cols = _columns(race, pal, opt, base)
    return cols, opt[TIGHT]


def odds_table(race: Race, pal: Palette, cols: list[tuple[str, dict, list]],
               tight: bool = False, rows: list[int] | None = None) -> Table:
    """The teams in race.teams order (only the indexes in ``rows`` when given), with the
    playoff line under the last spot."""
    n = race.playoff_teams
    shown = list(range(len(race.teams))) if rows is None else rows
    t = table(pal)
    t.box = _RACE_BOX
    t.collapse_padding = tight
    for head, kw, _ in cols:
        t.add_column(head, no_wrap=True, **kw)
    for j, i in enumerate(shown):
        line = i < n and j + 1 < len(shown) and shown[j + 1] >= n
        t.add_row(*[cells[i] for _, _, cells in cols], end_section=line)
    return t


def odds_legend(race: Race, pal: Palette, width: int, cols: list[tuple[str, dict, list]]) -> Text:
    shown = [head for head, _, _ in cols]
    items: list[tuple[str, str]] = []
    n = race.playoff_teams
    if n and len(race.teams) > n:
        items.append(("╌╌", f"playoff line, top {n} get in"))
    if "Proj" in shown:
        items.append(("Proj", "average final record"))
    elif "Proj W" in shown:
        items.append(("Proj W", "average final wins"))
    if "+/-" in shown:
        items.append(("+/-", "change in playoff odds from your picks"))
    if "1st" in shown:
        items.append((f"1st-{_ordinal(n)}", "seed odds"))
    if "ESPN" in shown:
        items.append(("ESPN", "ESPN's own odds, for reference"))
    if n and race.seeding_rule in TIEBREAK:
        items.append(("Ties", f"broken by {TIEBREAK[race.seeding_rule]}"))
    return _legend_lines(pal, items, width)


# --- games left ---------------------------------------------------------------------------------

def final_weeks(race: Race) -> list[int]:
    """The weeks of the final stretch (the last FINAL_WEEKS regular-season weeks) still open."""
    if not race.weeks_left:
        return []
    last = max(race.weeks_left)
    return [w for w in race.weeks_left if w > last - FINAL_WEEKS]


def _week_label(race: Race, week: int, games: list[Game]) -> str:
    last = max(race.weeks_left)
    if any(g.live for g in games):
        return "this week"
    if week == race.weeks_left[0]:
        return "next up"
    if week == last:
        return "last week of the regular season"
    if week > last - FINAL_WEEKS:
        return f"{last - week + 1} to go"
    return ""


def _week_head(race: Race, week: int, games: list[Game], pal: Palette, width: int) -> Text:
    out = Text(f"Week {week}", style=f"bold {pal.text}")
    label = _week_label(race, week, games)
    if label == "last week of the regular season" and width < 46:
        label = "last week"
    if label:
        out.append("  ·  ", style=pal.border)
        out.append(label, style=pal.dim)
    return out


def _cut(name: str, size: int) -> str:
    return name if cell_len(name) <= size else name[:max(1, size - 1)] + "…"


def _layout(race: Race, games: list[Game], width: int, lead: int) -> tuple[int, bool]:
    """(name width, compact) for game rows: "Home  58%  vs  42%  Away" fitted to ``width``
    after ``lead`` columns of cursor or indent."""
    names = _names(race)
    longest = max((cell_len(names.get(t, "")) for g in games for t in (g.home, g.away)), default=8)
    if (width - lead - 20) // 2 >= longest:
        return longest, False
    # tighter spacing before cutting names
    return max(4, min(longest, (width - lead - 14) // 2)), True


def game_row(race: Race, g: Game, pal: Palette, size: int, compact: bool, *,
             pick: int | None = None, tag: bool = True, room: int = 0) -> Text:
    """ "Monstars  58%  vs  42%  Tune Squad": home team right aligned against the middle.

    ``pick``: the winner you picked (the scenario builder passes its own picks); by default
    the game's own picked winner. ``room``: columns left for a tag after the away team.
    """
    names = _names(race)
    winner = pick if pick is not None else (g.winner if g.picked else None)
    p_home = race.home_win.get(g.id, 0.5)
    gap = " " if compact else "  "

    def name_style(tid: int) -> str:
        if winner is not None:
            return f"bold {pal.good}" if tid == winner else pal.dim
        return f"bold {pal.accent}" if tid == race.me else pal.text

    def share(tid: int, p: float) -> Text:
        if winner is not None:
            return Text("W" if tid == winner else "L",
                        style=f"bold {pal.good}" if tid == winner else pal.dim)
        favored = p > 0.5 or (p == 0.5 and tid == g.home)
        return Text(_share(p), style=pal.text if favored else pal.dim)

    home = _cut(names.get(g.home, str(g.home)), size)
    away = _cut(names.get(g.away, str(g.away)), size)
    # the away side's own share, not 1 - p_home: a simulated tie is neither team's win
    left, right = share(g.home, p_home), share(g.away, race.away_win.get(g.id, 1 - p_home))
    out = Text(" " * (size - cell_len(home)))
    out.append(home, style=name_style(g.home))
    out.append(gap + " " * (4 - left.cell_len))
    out.append_text(left)
    out.append(" vs " if compact else "  vs  ", style=pal.border)
    out.append_text(right)
    out.append(" " * (4 - right.cell_len) + gap)
    out.append(away, style=name_style(g.away))
    if tag:
        label = ""
        if winner is not None:
            label = "picked"
        elif g.live and (g.home_points or g.away_points):
            label = f"live {g.home_points:.1f}-{g.away_points:.1f}"
            if room < len(label) + 3:
                label = f"live {g.home_points:.0f}-{g.away_points:.0f}"
        if label and room >= len(label) + 3:
            out.append(" " * (size - cell_len(away) + 3))
            out.append(label, style=pal.dim)
    return out


def _span(weeks: list[int]) -> str:
    """[4, 5, 7, 8, 9] -> "weeks 4, 5 and 7 to 9" (a picked week can sit in the middle)."""
    runs: list[list[int]] = []
    for w in weeks:
        if runs and w == runs[-1][1] + 1:
            runs[-1][1] = w
        else:
            runs.append([w, w])
    parts = [str(a) if a == b else f"{a}, {b}" if b == a + 1 else f"{a} to {b}" for a, b in runs]
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return ("week " if len(weeks) == 1 else "weeks ") + text


def _by_week(games: list[Game]) -> dict[int, list[Game]]:
    out: dict[int, list[Game]] = {}
    for g in sorted(games, key=lambda g: g.week):
        out.setdefault(g.week, []).append(g)
    return out


def games_view(race: Race, pal: Palette, width: int) -> RenderableType:
    head = _fit_line(pal, width, *[["Games left", *c] for c in context(race)])
    if not race.games:
        return Group(head, Text(""), Text("The regular season is over: no games left to pick.",
                                          style=pal.dim))
    weeks = _by_week(race.games)
    shown = set(final_weeks(race)) | {race.weeks_left[0]} | {g.week for g in race.games if g.picked}
    hidden = [w for w in weeks if w not in shown]
    size, compact = _layout(race, race.games, width, 2)
    row_width = 2 + 2 * size + (14 if compact else 20)
    parts: list[RenderableType] = [head]
    for week, games in weeks.items():
        if week not in shown:
            continue
        parts += [Text(""), _week_head(race, week, games, pal, width)]
        for g in games:
            row = game_row(race, g, pal, size, compact, room=width - row_width)
            parts.append(Text("  ") + row)
    parts.append(Text(""))
    if hidden:
        parts += [Text(f"{_plural(len(hidden), 'earlier week')} hidden ({_span(hidden)}).", style=pal.dim),
                  Text("Pick any game in the app (y), or here with --pick \"Winner>Loser@WEEK\".",
                       style=pal.dim)]
    items = [("%", "share of simulated seasons each side wins")]
    if any(g.picked for g in race.games):
        items.append(("W", "the winner you picked"))
    parts.append(_legend_lines(pal, items, width))
    return Group(*parts)


# --- the scenario builder (app) -----------------------------------------------------------------

class _Pane(Widget):
    """A part of the builder that draws itself from the builder's state at its own size."""

    def __init__(self, builder: PlayoffBuilder, draw, **kw):
        super().__init__(**kw)
        self.builder = builder
        self._draw = draw

    def render(self) -> RenderableType:
        return self._draw(self.builder.pal, max(10, self.size.width), self.size.height)


class PlayoffBuilder(Widget, can_focus=True):
    """Pick winners for the games left and watch the odds move.

    up/down (or j/k) move between games, page up/down between weeks; left/right (or h/l) pick
    the home or the away team (the same side again clears it); backspace or 0 clears the
    game, c clears every pick; e jumps to the final weeks, b back to the next week. Each
    change simulates the season again in a worker thread; only the last run is shown.
    """

    DEFAULT_CSS = """
    PlayoffBuilder { height: 1fr; }
    PlayoffBuilder #pb-head { height: auto; margin-bottom: 1; }
    PlayoffBuilder #pb-split { height: 1fr; layout: horizontal; }
    PlayoffBuilder #pb-games { width: 60; height: 1fr; min-height: 5; }
    PlayoffBuilder #pb-odds { width: 1fr; height: 1fr; padding: 0 0 0 4; }
    PlayoffBuilder.-stacked #pb-split { layout: vertical; }
    PlayoffBuilder.-stacked #pb-games { width: 1fr; }
    PlayoffBuilder.-stacked #pb-odds { height: auto; padding: 1 0 0 0; }
    PlayoffBuilder #pb-foot { height: auto; margin-top: 1; }
    """
    BINDINGS = [
        Binding("up,k", "move(-1)", "Previous game", show=False),
        Binding("down,j", "move(1)", "Next game", show=False),
        Binding("pageup", "week(-1)", "Previous week", show=False),
        Binding("pagedown", "week(1)", "Next week", show=False),
        Binding("left,h", "pick('home')", "Home wins", show=False),
        Binding("right,l", "pick('away')", "Away wins", show=False),
        Binding("backspace,0", "clear", "Clear pick", show=False),
        Binding("c", "clear_all", "Clear all picks", show=False),
        Binding("e", "final", "Final weeks", show=False),
        Binding("b", "next_week", "Next week", show=False),
    ]
    STACK_BELOW = 124  # columns: below this the odds go under the games
    SHORT_BELOW = {True: 36, False: 24}  # rows (stacked or not): below this the odds go compact

    def __init__(self, race: Race, session, **kw):
        super().__init__(**kw)
        self.initial = race          # what the screen loaded, no picks
        self.race = race             # what is on screen
        self.base: Race | None = None  # no picks, SCENARIO_SIMS seasons: what the +/- compares to
        self.session = session
        self.games = sorted(race.games, key=lambda g: g.week)
        self.picks: dict[int, int] = {}
        self.cursor = 0
        if self.games:
            self.cursor = self._landing(self.games[0].week)
        self.busy = False
        self.error = ""
        self.short = False           # a short window: no odds legend, no blank table edges
        self._token = 0
        self._top = 0                # first line of the games list on screen
        self._snap = False           # the next draw puts the cursor's week at the top

    # --- layout ---

    @property
    def pal(self) -> Palette:
        return getattr(self.app, "pal", DARK)

    def compose(self):
        yield _Pane(self, self._draw_head, id="pb-head")
        with Container(id="pb-split"):
            yield _Pane(self, self._draw_games, id="pb-games")
            yield _Pane(self, self._draw_odds, id="pb-odds")
        yield _Pane(self, self._draw_foot, id="pb-foot")

    def on_mount(self) -> None:
        self.watch(self.app, "theme", lambda _: self.repaint(), init=False)
        self._fit()
        # the app sets its own status line right after it mounts this widget, and Mount runs
        # after that, so the line can change now: no frame shows the app's line, and nothing
        # waits for a screen refresh that a slow machine may not have drawn yet
        self._status_line()

    def on_resize(self) -> None:
        self._fit()

    def _fit(self) -> None:
        width = self.size.width
        if not width:
            return
        stacked = width < self.STACK_BELOW
        self.set_class(stacked, "-stacked")
        self.short = self.size.height < self.SHORT_BELOW[stacked]
        games = self.query_one("#pb-games")
        if stacked:
            games.styles.width = "1fr"
        else:
            size, compact = _layout(self.race, self.games, 64, 2)
            row = 2 + 2 * size + (14 if compact else 20)
            games.styles.width = min(max(44, row + 9), width // 2)  # 9: room for the "picked" tag
        self.repaint()

    def _status_line(self) -> None:
        """The app's status bar offers v for the next view, but the builder shows the games and
        the odds at once (v does nothing here), so it gets its own line."""
        for status in self.app.query("#status"):
            status.update(Text("Scenario builder · r refresh · ctrl+t light/dark · q quit",
                               style=self.pal.dim))

    def repaint(self) -> None:
        for pane in self.query(_Pane):
            pane.refresh(layout=True)

    # --- drawing ---

    def _draw_head(self, pal: Palette, width: int, height: int) -> RenderableType:
        busy = "   simulating..."
        line = _fit_line(pal, width - (len(busy) if self.busy else 0), *context(self.race))
        if self.busy:
            line.append(busy, style=pal.dim)
        return line

    def _height(self, renderable: RenderableType, width: int) -> int:
        console = self.app.console
        return len(console.render_lines(renderable, console.options.update_width(width), pad=False))

    def _odds_room(self, height: int) -> int:
        """Lines the odds can take: the pane's own height side by side; stacked (the pane grows
        with its content) what is left under the title, GAMES_MIN rows of games and the keys."""
        if not self.has_class("-stacked") or not self.size.height:
            return height
        keys = self._height(self._draw_foot(self.pal, self.size.width, 0), self.size.width)
        # the title and its margin, the keys and their margin, the odds' top padding
        return self.size.height - 2 - (keys + 1) - GAMES_MIN - 1

    def _draw_odds(self, pal: Palette, width: int, height: int) -> RenderableType:
        text = _note(self.race)
        note = [Text(text, style=pal.dim)] if text else []
        base = self.base if self.picks else None
        room = self._odds_room(height)
        if not self.short:
            cols, tight = fit_columns(self.race, pal, width, base=base)
            out = Group(*note, odds_table(self.race, pal, cols, tight))  # blank lines above and below
            foot = odds_legend(self.race, pal, width, cols)
            if foot.plain:
                out.renderables.append(foot)
            if self._height(out, width) <= room:
                return out
        # no edge spaces and no blank lines around the table, no legend: every row counts, and
        # when even that is too tall, only the rows that fit (yours and the playoff bubble)
        cols, tight = fit_columns(self.race, pal, width + 2, base=base)
        head = [*note, Text("")] if note else []
        t = odds_table(self.race, pal, cols, tight)
        t.show_edge = False
        extra = self._height(Group(*head, t), width) - room
        if extra > 0:
            t = odds_table(self.race, pal, cols, tight, rows_in_view(self.race, len(self.race.teams) - extra))
            t.show_edge = False
        return Group(*head, t)

    def _draw_foot(self, pal: Palette, width: int, height: int) -> RenderableType:
        keys = [("↑↓", "game"), ("←→", "pick the winner"), ("0", "clear"), ("c", "clear all"),
                ("e", f"final {FINAL_WEEKS} weeks"), ("b", "next week")]
        if not self.games:
            keys = []
        brief = [("↑↓", "game"), ("←→", "pick"), ("0", "clear"), ("c", "clear all"),
                 ("e", "final weeks"), ("b", "next week")]
        if self.short and keys and "\n" not in _legend_lines(pal, brief, width).plain:
            keys = brief  # one line instead of two
        out = _legend_lines(pal, keys, width)
        tail = Text()
        if self.picks:
            tail.append(_plural(len(self.picks), "pick"), style=f"bold {pal.accent}")
        elif self.games:
            tail.append("no picks yet", style=pal.dim)
        if self.error:
            tail.append(("   " if tail.plain else "") + self.error, style=pal.bad)
        if not tail.plain:
            return out
        if not out.plain:
            return tail
        last = out.plain.split("\n")[-1]
        if cell_len(last) + 5 + tail.cell_len <= width:  # the count fits after the keys
            return Text.assemble(out, Text("  ·  ", style=pal.border), tail)
        return Text("\n").join([out, tail])

    def _lines(self, pal: Palette, width: int) -> tuple[list[Text], list[int], dict[int, int]]:
        """Every line of the games list, the line of each game (same order as self.games), and
        for each game line the line of its week heading."""
        if not self.games:
            return [Text("The regular season is over: no games left to pick.", style=pal.dim)], [], {}
        size, compact = _layout(self.race, self.games, width, 2)
        row_width = 2 + 2 * size + (14 if compact else 20)
        lines: list[Text] = []
        at: list[int] = []
        head_of: dict[int, int] = {}
        index = 0
        for week, games in _by_week(self.games).items():
            if lines:
                lines.append(Text(""))
            heading = len(lines)
            lines.append(_week_head(self.race, week, games, pal, width))
            for g in games:
                row = game_row(self.race, g, pal, size, compact, pick=self.picks.get(g.id),
                               room=width - row_width)
                if index == self.cursor:
                    line = Text("▸ ", style=f"bold {pal.accent}") + row
                    line.pad_right(max(0, width - line.cell_len))
                    line.stylize(f"on {CURSOR_BG.get(pal.name, CURSOR_BG['dark'])}")
                else:
                    line = Text("  ") + row
                at.append(len(lines))
                head_of[len(lines)] = heading
                lines.append(line)
                index += 1
        return lines, at, head_of

    def _draw_games(self, pal: Palette, width: int, height: int) -> RenderableType:
        """The window of the games list that keeps the cursor in view. A jump puts the week at
        the top; a week scrolled into keeps its heading pinned on the first row; a heading
        never sits alone on the last row."""
        lines, at, head_of = self._lines(pal, width)
        height = max(1, height)
        if not at:
            return Text("\n").join(lines[:height])
        line = at[self.cursor]
        heading = head_of[line]
        if self._snap:
            self._top = heading
        elif heading < self._top and heading == line - 1:
            self._top = heading  # a week's first game brings its heading along
        elif line <= self._top:
            self._top = line - 1  # the row above goes under the pinned heading
        if line >= self._top + height:
            self._top = line - height + 1
        self._snap = False
        headings = set(head_of.values())
        if self._top not in headings:
            # no blank rows under the end of the list, unless that keeps a week at the top
            # (e lands on the final weeks: they start the window, not a scrap of the week before)
            self._top = min(self._top, len(lines) - height)
        self._top = max(0, self._top)
        window = lines[self._top:self._top + height]
        top_head = head_of.get(self._top)
        if top_head is not None and top_head != self._top and line != self._top and height > 2:
            window[0] = lines[top_head]
        while len(window) > 1 and (not window[-1].plain or self._top + len(window) - 1 in headings):
            window.pop()
        return Text("\n").join(window)

    # --- moving ---

    def current(self) -> Game | None:
        return self.games[self.cursor] if self.games else None

    def _landing(self, week: int) -> int:
        """The index of your game in ``week`` (or that week's first game)."""
        idx = [i for i, g in enumerate(self.games) if g.week == week]
        if not idx:
            return self.cursor
        mine = [i for i in idx if self.race.me in (self.games[i].home, self.games[i].away)]
        return (mine or idx)[0]

    def _go(self, index: int, jump: bool = False) -> None:
        if self.games:
            self.cursor = max(0, min(len(self.games) - 1, index))
            self._snap = jump
            for pane in self.query("#pb-games"):
                pane.refresh()

    def action_move(self, step: int) -> None:
        self._go(self.cursor + step)

    def action_week(self, step: int) -> None:
        if not self.games:
            return
        weeks = sorted({g.week for g in self.games})
        now = weeks.index(self.games[self.cursor].week)
        target = weeks[max(0, min(len(weeks) - 1, now + step))]
        self._go(next(i for i, g in enumerate(self.games) if g.week == target), jump=True)

    def action_final(self) -> None:
        stretch = final_weeks(self.initial)
        if stretch:
            self._go(self._landing(stretch[0]), jump=True)

    def action_next_week(self) -> None:
        if self.games:
            self._go(self._landing(self.games[0].week), jump=True)

    # --- picking ---

    def action_pick(self, side: str) -> None:
        g = self.current()
        if g is None:
            return
        winner = g.home if side == "home" else g.away
        if self.picks.get(g.id) == winner:
            del self.picks[g.id]
        else:
            self.picks[g.id] = winner
        self._rerun()

    def action_clear(self) -> None:
        g = self.current()
        if g is not None and g.id in self.picks:
            del self.picks[g.id]
            self._rerun()

    def action_clear_all(self) -> None:
        if self.picks:
            self.picks.clear()
            self._rerun()

    def _rerun(self) -> None:
        self._token += 1
        self.error = ""
        if not self.picks:
            # back to what the screen loaded: nothing to simulate
            self.workers.cancel_group(self, "playoff-race")
            self.busy = False
            self.race = self.initial
        else:
            self.busy = True
            self.run_worker(partial(self._simulate, dict(self.picks), self._token), thread=True,
                            exclusive=True, group="playoff-race")
        self.repaint()

    def _simulate(self, picks: dict[int, int], token: int) -> None:
        """Worker thread: the race with these picks, and once the same race without picks."""
        worker = get_current_worker()
        time.sleep(DEBOUNCE)  # a newer key press cancels this run before it starts
        if worker.is_cancelled:
            return
        race, err = None, ""
        try:
            if self.base is None:
                self.base = self.session.playoff_race({}, SCENARIO_SIMS)
            if worker.is_cancelled:
                return
            race = self.session.playoff_race(picks, SCENARIO_SIMS)
        except BenchbossError as e:
            err = str(e)
        except Exception as e:  # a bad payload must not kill the app
            err = f"{type(e).__name__}: {e}"
        if worker.is_cancelled:
            return
        self.app.call_from_thread(self._done, token, race, err)

    def _done(self, token: int, race: Race | None, err: str) -> None:
        if token != self._token or not self.is_mounted:
            return
        self.busy = False
        if race is not None:
            race.baseline = self.base
            self.race = race
        self.error = err
        self.repaint()


__all__ = ["TITLE", "VIEWS", "PlayoffBuilder", "draw", "load", "to_json", "widget"]

"""Auto-swap: arm players who might turn healthy before their game.

One row per roster player: the mark (✓ auto, ! alert only), his status, today's tip and
what benchboss would do if he turned healthy now (core.autoswap.describe). The top line
says whether the monitor runs. ``benchboss autoswap list`` prints the same table.

In the app (key u) the screen binds only these keys: up down j k to move; enter on an
unarmed row shows the preview in a confirm line and a second enter, at least
CONFIRM_DELAY seconds later, arms him (anything else cancels); enter, backspace or delete
on an armed row disarms at once; ! arms or disarms alert-only (no confirmation, it never
changes the lineup); escape cancels the confirm line, else goes back to the menu. Arming
only writes the local marks file: the monitor (``benchboss monitor``) is what acts on it.
The app itself never changes a lineup on its own and never sends notifications.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import time
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.constrain import Constrain
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from benchboss import lineup_log
from benchboss import monitor as monitor_mod
from benchboss.core import autoswap as core
from benchboss.core.calendar import clock
from benchboss.core.lineup import LOCK_MARGIN
from benchboss.errors import BenchbossError
from benchboss.espn.constants import IR, status_class
from benchboss.espn.models import Player
from benchboss.marks import Mark, MarkStore, week_end
from benchboss.text import surname
from benchboss.ui.common import fit_title, legend, player_cell, table
from benchboss.ui.layout import KeyItem
from benchboss.ui.theme import DARK, Palette

TITLE = "Auto-swap"
VIEWS: tuple[tuple[str, str], ...] = ()
CONFIRM_DELAY = 0.6  # seconds between the two presses of enter that arm a player
EVENTS_SHOWN = 5
MARK = {"auto": "✓", "notify": "!"}

_clock = time.monotonic  # tests replace it


@dataclass
class Row:
    player: Player
    slot: str
    preview: core.Preview
    mark: Mark | None = None
    held: bool = False  # the monitor rests his mark today (someone changed his spot)

    @property
    def plays(self) -> bool:
        return self.preview.kind not in ("no_game", "started", "ir", "gone")


@dataclass
class AutoswapData:
    rows: list[Row]
    paused: bool = False
    error: str = ""                       # the marks file could not be read
    monitor: dict = field(default_factory=dict)  # monitor.heartbeat()
    events: list[dict] = field(default_factory=list)  # today's records, oldest first
    in_season: bool = True
    today: dt.date | None = None
    until: dt.date | None = None          # the default expiry of a new mark
    now: dt.datetime | None = None
    demo: bool = False


def load(session) -> AutoswapData:
    lg, cal = session.league(), session.calendar
    period = cal.period_of(session.today)
    in_season = 1 <= period <= cal.final_period
    roster = monitor_mod.base_roster(session, period) if in_season else list(lg.me.roster)
    marks = MarkStore(session).load()
    state = monitor_mod.read_state(session)
    held = {int(k) for k, v in state.get("held", {}).items() if v == session.today.isoformat()}
    now, tz = session.now, session.now.tzinfo
    rows = []
    for spot in roster:
        p = spot.player
        game = cal.game(p.pro_team_id, period) if in_season else None
        plan = None
        if game is not None and spot.slot_id != IR and not p.locked and \
                game.start > now + LOCK_MARGIN:
            plan = core.preview_flip(roster, lg.slot_counts, period, cal, p.id, now)
        pv = core.describe(roster, plan, p.id, cal, period if in_season else 0, now, tz)
        rows.append(Row(p, spot.slot, pv, marks.get(p.id), p.id in held))
    rows.sort(key=lambda r: (not r.plays, r.slot == "IR",
                             status_class(r.player.injury_status) == "ok",
                             r.preview.tip or now, r.player.name))
    day = session.today.isoformat()
    events = [r for r in lineup_log.read_local(session, months=1)
              if str(r.get("at", "")).startswith(day)
              and r.get("event") in ("autoswap", "flip", "verify", "arm", "disarm", "pause",
                                     "resume")]
    return AutoswapData(rows, marks.paused, marks.error, monitor_mod.heartbeat(session),
                        events, in_season, session.today, week_end(session), now, session.demo)


# --- cells -------------------------------------------------------------------------------------

def mark_cell(mark: Mark | None, held: bool, pal: Palette) -> Text:
    if mark is None:
        return Text("·", style=pal.border)
    style = pal.dim if held else pal.good if mark.auto else pal.warn
    return Text(MARK.get(mark.mode, "?"), style=f"bold {style}")


def tip_cell(row: Row, data: AutoswapData, pal: Palette, wide: bool) -> Text:
    tip = row.preview.tip
    if tip is None:
        return Text("-", style=pal.border)
    when = clock(tip, data.now.tzinfo if data.now else None)
    if row.preview.kind == "started":
        return Text(when, style=pal.dim)
    if wide and data.now:
        left = int((tip - data.now).total_seconds() // 60)
        return Text.assemble((when, pal.text), (f" in {left // 60}h {left % 60:02d}m", pal.dim))
    return Text(when, style=pal.text)


def plan_words(row: Row, short_names: bool, narrow: bool = False) -> str:
    """What benchboss would do if he turned healthy, in a table cell. ``narrow`` (a phone):
    "G for Pippen +5.1", since the app's table cuts a cell instead of wrapping it."""
    pv = row.preview
    if pv.kind == "starts":
        b = pv.swap.benched
        if narrow:
            return f"{pv.swap.slot}" + (f" for {surname(b.name)}" if b else "") + \
                f" {pv.swap.gain:+.1f}"
        who = (b.short_name if short_names else b.name) if b else ""
        text = f"starts at {pv.swap.slot}" + (f", benches {who}" if who else "")
        return f"{text} ({pv.swap.gain:+.1f})"
    return {"starting": "already starts", "sits": "stays on the bench",
            "small": f"only {pv.swap.gain:+.1f}: no change", "no_game": "no game today",
            "started": "his game started", "ir": "on IR", "gone": "not on your roster"
            }.get(pv.kind, pv.kind)


def plan_cell(row: Row, pal: Palette, short_names: bool, narrow: bool = False) -> Text:
    words = plan_words(row, short_names, narrow)
    if row.held:
        return Text("resting today" if narrow else "resting today: someone changed his spot",
                    style=pal.dim)
    style = pal.text if row.preview.kind == "starts" else pal.dim
    return Text(words, style=style)


def status_line(data: AutoswapData, pal: Palette) -> Text:
    """The monitor, and whether auto-swap is paused or the marks file is damaged."""
    if data.error:
        return Text(f"{data.error}. No player is armed: benchboss autoswap clear starts over.",
                    style=pal.bad)
    mon = data.monitor or {}
    text = mon.get("text") or "monitor not running: benchboss monitor"
    out = Text(text, style=pal.good if mon.get("running") else pal.warn)
    if data.paused:
        out.append("  ·  paused: benchboss autoswap resume", style=pal.warn)
    return out


# --- the static drawing (benchboss autoswap list) ------------------------------------------------

def draw(data: AutoswapData, pal: Palette, width: int = 120, view: int = 0) -> RenderableType:
    armed = sum(1 for r in data.rows if r.mark)
    count = f"{armed} armed" if armed else "nobody armed"
    until = f"marks last until {data.until:%a %b} {data.until.day}" if data.until else ""
    head = fit_title(TITLE, pal, width, (count, "trial mode" if not _live(data) else "live",
                                         until), (count, until), (count,))
    parts: list[RenderableType] = [head, Text(""), _fit(status_line(data, pal), width)]
    if data.demo:
        parts.append(_fit(Text("Demo: the lineup is the one Optimize would set this morning.",
                               style=pal.dim), width))
    if not data.in_season:
        parts += [Text(""), Text("No games today: the fantasy season is not on.",
                                 style=pal.dim)]
    t = _table(data, pal, width)
    parts += [Text(""), Constrain(t, width)]
    parts.append(_fit(legend(pal, ("✓", "auto-swap"), ("!", "alert only"),
                             ("If healthy", "what benchboss would do now")), width))
    if data.events:
        parts += [Text(""), Text("Today", style=f"bold {pal.dim}")]
        for rec in data.events[-EVENTS_SHOWN:]:
            parts.append(_fit(event_line(rec, data, pal), width))
    parts += [Text(""), _fit(Text('Arm one: benchboss autoswap add "Player" (or press u in '
                                  "the app)", style=pal.dim), width)]
    return Group(*parts)


def _live(data: AutoswapData) -> bool:
    return (data.monitor or {}).get("mode") == "live"


def _fit(text: Text, width: int) -> Text:
    text = text.copy()
    text.truncate(width, overflow="ellipsis")
    return text


def columns(width: int) -> list[str]:
    """The columns that fit: a narrow screen drops the countdown, then Slot, then Tip, and
    keeps Player and If healthy (a phone over SSH is 40 to 46 columns)."""
    cols = ["mark", "player"]
    if width >= 60:
        cols.append("slot")
    if width >= 50:
        cols.append("tip")
    return cols + ["plan"]


TINY = 42  # columns of the screen: under this (a 40-column phone) players go by surname

HEADERS = {"mark": "", "player": "Player", "slot": "Slot", "tip": "Tip", "plan": "If healthy"}


def cells(r: Row, data: AutoswapData, pal: Palette, width: int) -> list[Text]:
    narrow = width < 60
    style = pal.dim if not r.plays else None
    if width < TINY:  # a phone with the keyboard up: "Daniels DTD"
        name = player_cell(r.player, pal, team=False, style=style)
        name = Text(surname(r.player.name), style=style or pal.text) + \
            name[len(r.player.name):]
    else:
        name = player_cell(r.player, pal, short=narrow, team=not narrow, style=style)
    out = {"mark": mark_cell(r.mark, r.held, pal),
           "player": name,
           "slot": Text(r.slot, style=pal.dim),
           "tip": tip_cell(r, data, pal, wide=width >= 100),
           "plan": plan_cell(r, pal, short_names=width < 100, narrow=narrow)}
    return [out[k] for k in columns(width)]


def _table(data: AutoswapData, pal: Palette, width: int) -> Table:
    t = table(pal)
    for key in columns(width):
        if key == "plan":
            t.add_column(HEADERS[key], overflow="fold")
        else:
            t.add_column(HEADERS[key], no_wrap=True, overflow="ellipsis",
                         justify="right" if key == "tip" else "left",
                         max_width=max(15, width * 2 // 5) if key == "player" else None)
    for r in data.rows:
        t.add_row(*cells(r, data, pal, width))
    return t


def event_line(rec: dict, data: AutoswapData, pal: Palette) -> Text:
    when = ""
    with contextlib.suppress(ValueError, TypeError):
        at = dt.datetime.fromisoformat(rec["at"])
        when = clock(at, data.now.tzinfo if data.now else None)
    style = pal.bad if rec.get("outcome") in monitor_mod.URGENT_OUTCOMES else pal.text
    text = rec.get("text") or _event_text(rec)
    return Text.assemble((f"{when:>8}  ", pal.dim), (text, style))


def _event_text(rec: dict) -> str:
    ev, who = rec.get("event"), rec.get("player") or ""
    if ev == "arm":
        return f"armed {who} ({'alert only' if rec.get('mark') == 'notify' else 'auto-swap'})"
    if ev == "disarm":
        return f"disarmed {who}" if who else "disarmed everyone"
    return {"pause": "paused", "resume": "resumed"}.get(ev, str(ev))


def to_json(data: AutoswapData) -> dict:
    return {
        "paused": data.paused, "error": data.error or None, "monitor": data.monitor,
        "until_default": data.until.isoformat() if data.until else None,
        "players": [{
            "player_id": r.player.id, "player": r.player.name, "team": r.player.pro_team,
            "status": r.player.injury_status if r.player.injury_known else None,
            "slot": r.slot, "armed": r.mark.mode if r.mark else None,
            "until": r.mark.until if r.mark else None, "resting_today": r.held,
            "tip": r.preview.tip.isoformat() if r.preview.tip else None,
            "if_healthy": r.preview.to_dict()} for r in data.rows],
        "today": data.events,
    }


# --- the widget --------------------------------------------------------------------------------

class AutoswapView(Vertical):
    """The interactive screen. It binds up down j k enter backspace delete ! escape and
    nothing else, so the app's one-key menu keeps working while the table has the focus."""

    DEFAULT_CSS = """
    AutoswapView { height: 1fr; }
    AutoswapView #as-title { height: 1; }
    AutoswapView #as-monitor { height: auto; margin-top: 1; }
    AutoswapView DataTable { height: 1fr; min-height: 5; margin-top: 1; background: $background; }
    AutoswapView #as-confirm { height: auto; margin-top: 1; display: none; }
    AutoswapView #as-confirm.open { display: block; }
    AutoswapView #as-hint { height: auto; margin-top: 1; }
    """

    BINDINGS = [
        Binding("j", "move(1)", "Down", show=False),
        Binding("k", "move(-1)", "Up", show=False),
        Binding("backspace,delete", "disarm", "Disarm", show=False),
        Binding("exclamation_mark", "notify_only", "Alert only", show=False),
        Binding("escape", "back", "Back", show=False),
    ]

    def __init__(self, data: AutoswapData, app) -> None:
        super().__init__()
        self.data = data
        self.session = app.session
        self._owner_app = app
        self.confirm: tuple[int, float] | None = None  # (player id, when the first enter came)

    def compose(self):
        yield Static(id="as-title")
        yield Static(id="as-monitor")
        yield DataTable(id="as-table", zebra_stripes=True, cursor_type="row")
        yield Static(id="as-confirm")
        yield Static(id="as-hint")

    def _live(self) -> bool:
        return self.is_attached and getattr(self._owner_app, "_panel_widget", self) is self

    @property
    def pal(self) -> Palette:
        return getattr(self._owner_app, "pal", DARK)

    def on_mount(self) -> None:
        if not self._live():
            return
        self.watch(self.app, "theme", lambda: self._render_all(), init=False)
        self._render_all()

    def on_resize(self) -> None:
        if self._live():
            self._render_all()

    def focus(self, scroll_visible: bool = True):
        if self._live():
            self.query_one(DataTable).focus(scroll_visible)
        return self

    def key_items(self) -> list[KeyItem]:
        row = self._row()
        armed = row is not None and row.mark is not None
        return [KeyItem("⏎", "disarm" if armed else "arm", priority=10),
                KeyItem("!", "alert only", priority=20),
                KeyItem("⌫", "disarm", priority=30),
                KeyItem("esc", "back", priority=40)]

    # --- drawing -------------------------------------------------------------------------------

    def _width(self) -> int:
        return max(20, self.size.width or 100)

    def _render_all(self, keep: int | None = None) -> None:
        if not self._live():
            return
        pal, width = self.pal, self._width()
        armed = sum(1 for r in self.data.rows if r.mark)
        count = f"{armed} armed" if armed else "nobody armed"
        self.query_one("#as-title", Static).update(
            fit_title(TITLE, pal, width, (count, "arming changes nothing on ESPN by itself"),
                      (count,)))
        line = status_line(self.data, pal)
        if self.data.demo:
            line.append("  ·  demo: the lineup Optimize would set this morning", style=pal.dim)
        self.query_one("#as-monitor", Static).update(line)
        self._render_table(keep)
        self._render_confirm()
        self._render_hint()

    def _render_table(self, keep: int | None = None) -> None:
        t = self.query_one(DataTable)
        pal, width = self.pal, self._width()
        # a phone: a one-column scrollbar, like the app's own, so the cells keep their room
        t.styles.scrollbar_size_vertical = 1 if getattr(self._owner_app, "compact", False) else 2
        keep = keep if keep is not None else (self._row().player.id if self._row() else None)
        cols = columns(width)
        body = [cells(r, self.data, pal, width) for r in self.data.rows]
        t.clear(columns=True)
        for i, key in enumerate(cols):
            # widths given up front: a width left to the table is measured on its next idle,
            # and when arming redraws the table a frame drawn before that kept the header
            # widths in Textual's row cache ("Dyson", "7:0", no mark)
            room = max([cell_len(HEADERS[key]), *(row[i].cell_len for row in body)])
            t.add_column(HEADERS[key], key=key, width=room)
        for r, row in zip(self.data.rows, body, strict=True):
            t.add_row(*row, key=str(r.player.id))
        if keep is not None and str(keep) in t.rows:
            t.move_cursor(row=t.get_row_index(str(keep)))

    def _render_confirm(self) -> None:
        box = self.query_one("#as-confirm", Static)
        row = self._row()
        if self.confirm is None or row is None or row.player.id != self.confirm[0]:
            box.remove_class("open")
            return
        pal = self.pal
        box.update(Text.assemble(
            (f"Arm auto-swap for {row.player.name}? ", f"bold {pal.accent}"),
            (row.preview.text, pal.text),
            ("\nPress enter again to arm him, any other key cancels.", pal.dim)))
        box.add_class("open")

    def _render_hint(self) -> None:
        pal = self.pal
        row = self._row()
        armed = row is not None and row.mark is not None
        compact = bool(getattr(self._owner_app, "compact", False))
        items = [("enter", "disarm" if armed else "arm"), ("!", "alert only"),
                 ("backspace", "disarm"), ("esc", "back")]
        hint = Text() if compact else legend(pal, *items)  # a phone has the key bar for these
        if not (self.data.monitor or {}).get("running"):
            hint.append(("" if compact else "  ·  ") + "marks act only while benchboss monitor "
                        "runs", style=pal.warn)
        self.query_one("#as-hint", Static).update(hint)
        refresh = getattr(self._owner_app, "refresh_keys", None)
        if callable(refresh):  # enter reads "arm" or "disarm" for the row on show
            refresh()

    # --- rows ----------------------------------------------------------------------------------

    def _row(self) -> Row | None:
        if not self.is_attached or not self.query(DataTable):
            return None
        t = self.query_one(DataTable)
        if not t.row_count:
            return None
        with contextlib.suppress(Exception):
            key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            return next((r for r in self.data.rows if str(r.player.id) == key), None)
        return None

    def _cancel(self) -> None:
        if self.confirm is not None:
            self.confirm = None
            self._render_confirm()

    def on_key(self, event) -> None:
        # anything but enter cancels the confirm line, and the key still does its own job
        # (escape cancels in action_back, so that it does not also leave the screen)
        if self.confirm is not None and event.key not in ("enter", "escape"):
            self._cancel()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        if self.confirm is not None and str(self.confirm[0]) != event.row_key.value:
            self._cancel()
        self._render_hint()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """enter: arm (two steps) an unarmed player, disarm an armed one at once."""
        event.stop()
        row = next((r for r in self.data.rows if str(r.player.id) == event.row_key.value), None)
        if row is None:
            return
        if row.mark is not None:
            self._disarm(row)
            return
        if row.preview.kind in ("ir", "gone"):
            self.app.notify(f"{row.player.name}: {row.preview.text}", title="Auto-swap",
                            timeout=6)
            return
        now = _clock()
        if self.confirm is None or self.confirm[0] != row.player.id:
            self.confirm = (row.player.id, now)
            self._render_confirm()
            return
        if now - self.confirm[1] < CONFIRM_DELAY:
            return  # a double press or a key repeat: wait for a deliberate second enter
        self.confirm = None
        self._arm(row, "auto")

    def action_move(self, step: int) -> None:
        t = self.query_one(DataTable)
        if t.row_count:
            t.move_cursor(row=max(0, min(t.row_count - 1, t.cursor_row + step)))

    def action_disarm(self) -> None:
        row = self._row()
        if row is not None and row.mark is not None:
            self._disarm(row)

    def action_notify_only(self) -> None:
        """!: alert only (never changes the lineup, so no confirmation). On a player armed
        in auto mode it lowers him to alert only; on an alert-only one it disarms."""
        self._cancel()
        row = self._row()
        if row is None:
            return
        if row.mark is not None and not row.mark.auto:
            self._disarm(row)
            return
        if row.preview.kind in ("ir", "gone"):
            self.app.notify(f"{row.player.name}: {row.preview.text}", title="Auto-swap",
                            timeout=6)
            return
        self._arm(row, "notify")

    def action_back(self) -> None:
        if self.confirm is not None:
            self._cancel()
            return
        app = self._owner_app
        menu = next(iter(app.query("#menu")), None) if hasattr(app, "query") else None
        if menu is None:
            return
        if menu.has_class("hidden") and hasattr(app, "action_toggle_menu"):
            app.action_toggle_menu()
        else:
            menu.focus()

    # --- writes to the marks file (local; nothing goes to ESPN) ----------------------------------

    def _arm(self, row: Row, mode: str) -> None:
        try:
            row.mark = MarkStore(self.session).arm(row.player, mode, origin="tui")
        except BenchbossError as e:
            self.app.notify(f"Could not arm {row.player.name}: {e}", title="Auto-swap",
                            severity="error", timeout=8)
            return
        if mode == "auto":
            text = f"Auto-swap armed for {row.player.name}. {row.preview.text}"
        else:
            text = (f"Alert only for {row.player.name}: benchboss tells you when he turns "
                    "healthy and changes nothing.")
        if not (self.data.monitor or {}).get("running"):
            text += " It works while benchboss monitor runs."
        self.app.notify(text, title="Auto-swap", timeout=8, markup=False)
        self._render_all(keep=row.player.id)

    def _disarm(self, row: Row) -> None:
        self._cancel()
        try:
            MarkStore(self.session).disarm(row.player.id, origin="tui")
        except BenchbossError as e:
            self.app.notify(f"Could not disarm {row.player.name}: {e}", title="Auto-swap",
                            severity="error", timeout=8)
            return
        row.mark = None
        self.app.notify(f"Auto-swap is off for {row.player.name}.", title="Auto-swap", timeout=5,
                        markup=False)
        self._render_all(keep=row.player.id)


def widget(data: AutoswapData, app) -> AutoswapView:
    return AutoswapView(data, app)


__all__ = ["AutoswapData", "AutoswapView", "CONFIRM_DELAY", "Row", "TITLE", "VIEWS", "draw",
           "load", "to_json", "widget"]

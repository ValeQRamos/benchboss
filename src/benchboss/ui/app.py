"""The interactive app: a menu on the left, the selected screen on the right.

Every menu entry has a one-key shortcut. Reads run in a background thread so the interface
never freezes; writes (lineup moves) always show the plan first and wait for an explicit
"Apply".
"""

from __future__ import annotations

import contextlib
import os

from rich.console import Group, RenderableType
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.theme import Theme
from textual.widgets import Button, Footer, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from benchboss import __version__
from benchboss import config as config_mod
from benchboss.errors import BenchbossError
from benchboss.ui import dashboard, views
from benchboss.ui.theme import DARK, LIGHT, palette

THEMES = {
    "dark": Theme(name="benchboss-dark", primary=DARK.accent, secondary=DARK.info,
                  accent=DARK.accent, warning=DARK.warn, error=DARK.bad, success=DARK.good,
                  foreground=DARK.text, background="#141518", surface="#1b1c20",
                  panel="#24262b", dark=True),
    "light": Theme(name="benchboss-light", primary=LIGHT.accent, secondary=LIGHT.info,
                   accent=LIGHT.accent, warning=LIGHT.warn, error=LIGHT.bad, success=LIGHT.good,
                   foreground=LIGHT.text, background="#fbfbfa", surface="#f2f2f0",
                   panel="#e8e8e5", dark=False),
}

MENU = [
    ("dash", "Dashboard", "d"),
    ("today", "Optimize today", "t"),
    ("week", "Optimize week", "w"),
    ("activity", "Workload", "a"),
    ("trash", "Best trash", "f"),
    ("news", "Player news", "n"),
    ("trades", "Trade finder", "x"),
    ("inbox", "Inbox", "i"),
    ("standings", "Standings", "s"),
    ("roster", "Roster", "o"),
]


class Benchboss(App):
    TITLE = "benchboss"
    ENABLE_COMMAND_PALETTE = False  # ctrl+p belongs to VS Code (Quick Open); every action has a key
    CSS = """
    Screen { layout: vertical; }
    #top { height: 1; padding: 0 1; background: $panel; color: $foreground; }
    #main { height: 1fr; }
    #menu { width: 26; height: 1fr; border: none; padding: 1 0; background: $surface; }
    #menu > .option-list--option { padding: 0 2; }
    #content { padding: 1 2; }
    #body { width: 1fr; }
    #actions { height: auto; margin-top: 1; display: none; }
    #actions.visible { display: block; }
    #actions Button { margin-right: 2; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [Binding(key, f"show('{sid}')", label, show=sid in ("dash", "today", "week", "trash"))
                for sid, label, key in MENU] + [
        Binding("g", "show('ainews')", "AI news", show=False),
        Binding("r", "reload", "Refresh"),
        Binding("ctrl+t", "toggle_theme", "Light/Dark"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, cfg: config_mod.Config | None = None, demo: bool = False, session=None):
        super().__init__()
        self.cfg = cfg or config_mod.load()
        self.demo = demo
        self._session = session
        self.current = "dash"
        self.pending: dict | None = None  # the plan on screen that Apply would send
        self._last: tuple | None = None  # (kind, data) of the last screen, re-rendered on resize

    # --- layout --------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(id="top")
        with Horizontal(id="main"):
            yield OptionList(*[Option(f"{label}  [dim]{key}[/]", id=sid) for sid, label, key in MENU],
                             id="menu")
            with VerticalScroll(id="content"):
                yield Static(id="body")
                with Horizontal(id="actions"):
                    yield Button("Apply", id="apply", variant="primary")
                    yield Button("Cancel", id="cancel")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        for t in THEMES.values():
            self.register_theme(t)
        self.theme = THEMES[self.cfg.theme].name
        self.query_one("#menu", OptionList).focus()
        self._top()
        self.action_show("dash")
        self.set_interval(60, self._auto_refresh)

    @property
    def pal(self):
        return palette(self.cfg.theme)

    @property
    def session(self):
        if self._session is None:
            if self.demo:
                from benchboss.demo import demo_session

                self._session = demo_session(self.cfg)
            else:
                from benchboss.service import Session

                self._session = Session(self.cfg)
        return self._session

    def _top(self, extra: str = "") -> None:
        name = self.cfg.team_name
        if not name and self._session is not None and getattr(self._session, "_league", None):
            name = self._session._league.me.name
        left = Text.assemble(("🏀 benchboss", f"bold {self.pal.accent}"), (f"  {__version__}", self.pal.dim),
                             (f"   {name}" if name else "", self.pal.text),
                             ("   demo data" if self.demo else "", self.pal.warn), (extra, self.pal.dim))
        self.query_one("#top", Static).update(left)

    def _status(self, text: str) -> None:
        self.query_one("#status", Static).update(Text(text, style=self.pal.dim))

    def _show(self, renderable: RenderableType, actions: bool = False) -> None:
        self.query_one("#body", Static).update(renderable)
        self.query_one("#actions").set_class(actions, "visible")

    def _width(self) -> int:
        return max(40, self.query_one("#content").size.width - 4)

    # --- navigation ----------------------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_show(event.option.id)

    def action_show(self, sid: str) -> None:
        self.current = sid
        self.pending = None
        menu = self.query_one("#menu", OptionList)
        idx = next((i for i, (s, _, _) in enumerate(MENU) if s == sid), None)
        if idx is not None and menu.highlighted != idx:
            menu.highlighted = idx
        self._show(Text("Loading...", style=self.pal.dim))
        self._status("talking to ESPN..." if not self.demo else "demo data")
        self.load(sid)

    def action_reload(self) -> None:
        if self._session is not None and hasattr(self._session, "_league"):
            self._session._league = None
        self.action_show(self.current)

    def action_toggle_theme(self) -> None:
        self.cfg.theme = "light" if self.cfg.theme == "dark" else "dark"
        self.theme = THEMES[self.cfg.theme].name
        if not self.demo:
            with contextlib.suppress(OSError):
                config_mod.save(self.cfg)
        self._top()
        self._rerender()

    def _auto_refresh(self) -> None:
        if self.current == "dash":
            self.load("dash")

    def on_resize(self) -> None:
        self._rerender()

    def _rerender(self) -> None:
        if self._last and self._last[0] == "dash":
            self._show(dashboard.render(self._last[1], self.pal, self._width()))

    # --- data ----------------------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="load")
    def load(self, sid: str) -> None:
        pending = None
        try:
            renderable, actions, pending = self._build(sid)
        except BenchbossError as e:
            renderable, actions = self._error(e), False
        except Exception as e:  # never let a bad payload kill the app
            renderable, actions = self._error(f"{type(e).__name__}: {e}"), False
        if get_current_worker().is_cancelled:
            return  # the user already moved to another screen
        self.call_from_thread(self._finish, sid, renderable, actions, pending)

    def _finish(self, sid: str, renderable: RenderableType, actions: bool, pending) -> None:
        """Runs on the UI thread: only the screen the user is looking at gets drawn, and only
        the plan that is drawn can be applied."""
        if self.current != sid:
            return
        self.pending = pending
        self._top()
        self._show(renderable, actions)
        self._status("demo data · nothing is sent to ESPN" if self.demo
                     else "r refresh · ctrl+t light/dark · q quit")

    def _error(self, e) -> RenderableType:
        msg = str(e)
        hint = ""
        if "benchboss setup" in msg or "benchboss login" in msg:
            hint = "\n\nOpen a terminal and run the command above, then press r."
        return Text(f"{msg}{hint}", style=self.pal.bad)

    def _build(self, sid: str) -> tuple[RenderableType, bool, dict | None]:
        s, pal = self.session, self.pal
        if sid == "dash":
            d = dashboard.collect(s)
            self._last = ("dash", d)
            return dashboard.render(d, pal, self._width()), False, None
        if sid in ("today", "week"):
            from benchboss.service import periods_for

            periods = [p for p in periods_for(s, sid) if p >= s.league().scoring_period]
            plans = s.plan_days(periods)
            todo = [p for p in plans if p.changed]
            head = Text(("Today" if sid == "today" else "Rest of the matchup week") + "\n",
                        style=f"bold {pal.accent}")
            body = views.plan(plans, s.calendar, pal)
            if not todo:
                return Group(head, body, Text("\n✓ Already optimal. Nothing to do.", style=pal.good)), False, None
            moves = sum(len(p.moves) for p in todo)
            note = Text(f"\n{moves} move{'s' * (moves != 1)} on {len(todo)} day"
                        f"{'s' * (len(todo) != 1)}. Press Apply to send them to ESPN.", style=pal.text)
            pending = {"periods": [p.period for p in plans], "day": s.today, "kind": sid}
            return Group(head, body, note), True, pending
        if sid == "activity":
            return views.activity(s.activity(), s.calendar, s.matchup_periods(), s.today_period, pal), False, None
        if sid == "trash":
            hint = Text("\nGrab one from a terminal: benchboss add \"Player\" --drop \"Player\"",
                        style=pal.dim)
            return Group(views.trash(s.trash(n=12), s.calendar, pal, self._width()), hint), False, None
        if sid in ("news", "ainews"):
            from benchboss import news as news_mod

            lg = s.league()
            roster = [x.player for x in lg.me.roster]
            if sid == "ainews":
                if self.demo:
                    raise BenchbossError("the AI briefing is not available with demo data")
                return Group(Text("AI briefing (Claude with web search), last 5 days\n",
                                  style=f"bold {pal.accent}"),
                             Text(news_mod.ai_digest(roster, 5), style=pal.text)), False, None
            names = {p.id: p.name for p in roster}
            items = s.news([p.id for p in roster], 5)
            tip = ("Press g for an AI briefing with web search (sends your players' names to the "
                   "Anthropic API)." if news_mod.ai_available() and not self.demo else
                   "Want more? Set ANTHROPIC_API_KEY and press g for an AI briefing, or ask "
                   "Copilot Chat for news on your players (player-news skill).")
            return Group(Text("News and spins on your players, last 5 days\n", style=f"bold {pal.accent}"),
                         views.news(items, names, pal, 5), Text(tip, style=pal.dim)), False, None
        if sid == "trades":
            from benchboss.core import trades as trades_mod

            lg = s.league()
            ideas = trades_mod.find_trades(lg, limit=8)
            bal = trades_mod.describe_needs(lg)
            hint = Text("\nSend one from a terminal: benchboss trade --give \"A\" --get \"B\" --msg \"...\"",
                        style=pal.dim)
            return Group(Text("Trade ideas\n", style=f"bold {pal.accent}"), views.trades(ideas, pal),
                         Text(""), views.needs(bal, lg.me.name, pal), hint), False, None
        if sid == "inbox":
            from benchboss import inbox

            return views.alerts(inbox.alerts(s), pal), False, None
        if sid == "standings":
            return views.standings(s.league(), pal), False, None
        if sid == "roster":
            lg = s.league()
            today = {x.player.id for x in lg.me.roster if s.calendar.plays(x.player.pro_team_id, s.today_period)}
            return views.roster(lg, pal, today), False, None
        raise BenchbossError(f"unknown screen {sid}")

    # --- writes --------------------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.pending = None
            self._show(Text("Cancelled. Nothing was sent.", style=self.pal.dim))
        elif event.button.id == "apply" and self.pending:
            pending, self.pending = self.pending, None
            self.query_one("#actions").set_class(False, "visible")
            self._status("sending to ESPN...")
            self.apply(pending)

    @work(thread=True, exclusive=True, group="write")
    def apply(self, pending: dict) -> None:
        s = self.session
        span = "day" if pending["kind"] == "today" else "week"
        if s.today != pending["day"]:
            msg = "The fantasy day changed since this plan was made. Press t or w to rebuild it."
            self.call_from_thread(self._show, Text(msg, style=self.pal.warn))
            self.call_from_thread(self._status, "nothing was sent")
            return
        if self.demo:
            plans = s.plan_days(pending["periods"])
            moves = sum(len(p.moves) for p in plans)
            days = sum(1 for p in plans if p.changed)
            msg = (f"Your {span} is set: {moves} move{'s' * (moves != 1)} across {days} "
                   f"day{'s' * (days != 1)}. (Demo: nothing was sent.)")
            self.call_from_thread(self.notify, msg, title="Done", timeout=8)
            self.call_from_thread(self._show, Text("✓ " + msg, style=f"bold {self.pal.good}"))
            self.call_from_thread(self._status, "")
            return
        try:
            results = s.apply_days(pending["periods"])
        except BenchbossError as e:
            results, fatal = [], str(e)
        else:
            fatal = ""
        days, moves, lines, errors = 0, 0, [], [fatal] if fatal else []
        for r in results:
            label = f"{s.calendar.date_of(r.plan.period):%a %b %d}"
            if r.error:
                errors.append(f"{label}: {r.error}")
            elif r.status != "ALREADY_OPTIMAL":
                days += 1
                moves += len(r.plan.moves)
                lines.append(f"{label}: ESPN: {r.status}")
        if errors:
            msg = "Not everything was sent:\n" + "\n".join(errors + lines)
            self.call_from_thread(self.notify, "\n".join(errors), title="Not everything was sent",
                                  severity="error", timeout=12)
            self.call_from_thread(self._show, Text(msg, style=self.pal.bad))
        else:
            msg = f"Your {span} is set: {moves} move{'s' * (moves != 1)} across {days} day{'s' * (days != 1)}."
            self.call_from_thread(self.notify, msg, title="Done", timeout=8)
            self.call_from_thread(self._show, Group(Text("✓ " + msg, style=f"bold {self.pal.good}"),
                                                    Text("\n".join(lines), style=self.pal.dim)))
        self.call_from_thread(self._status, "")


def run(cfg: config_mod.Config | None = None, demo: bool = False) -> None:
    cfg = cfg or config_mod.load()
    if not demo and not cfg.league_id and not os.environ.get("BENCHBOSS_LEAGUE_ID"):
        raise BenchbossError("no league configured yet: run `benchboss setup` "
                             "(or try `benchboss --demo` to look around)")
    Benchboss(cfg, demo=demo).run()


__all__ = ["Benchboss", "run", "Vertical"]

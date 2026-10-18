"""The interactive app: a menu on the left, the selected screen on the right.

Every menu entry has a one-key shortcut. Reads run in a background thread so the interface
never freezes; writes (lineup moves) always show the plan first and wait for an explicit
"Apply".
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import Button, Footer, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from benchboss import __version__
from benchboss import config as config_mod
from benchboss.errors import BenchbossError
from benchboss.ui import common, dashboard, views
from benchboss.ui.screens import SCREENS
from benchboss.ui.theme import DARK, LIGHT, Palette, palette

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
    ("autoswap", "Auto-swap", "u"),
    ("activity", "Workload", "a"),
    ("trash", "Best trash", "f"),
    ("players", "Player finder", "p"),
    ("news", "Player news", "n"),
    ("trades", "Trade finder", "x"),
    ("inbox", "Inbox", "i"),
    ("standings", "Standings", "s"),
    ("playoffs", "Playoff race", "y"),
    ("roster", "Roster", "o"),
]
PLANS = ("today", "week")  # the screens that can send moves to ESPN
MENU_WIDTH = 26  # the width of #menu in the CSS below
NARROW = 110  # below this many columns the menu hides itself (m shows it again)

# Draws a screen from data already loaded: (palette, width) -> renderable. Kept so a resize
# or a theme change can draw the screen again without asking ESPN.
Draw = Callable[[Palette, int], RenderableType]
SPIN_CHECK = 300  # seconds between checks for new spins on watch-list players


@dataclass
class Mount:
    """An interactive screen: a Textual widget shown in place of the static drawing."""
    make: Callable[[], Widget]


class Benchboss(App):
    TITLE = "benchboss"
    ENABLE_COMMAND_PALETTE = False  # ctrl+p belongs to VS Code (Quick Open); every action has a key
    CSS = """
    Screen { layout: vertical; }
    #top { height: 1; padding: 0 1; background: $panel; color: $foreground; }
    #main { height: 1fr; }
    #menu { width: 26; height: 1fr; border: none; padding: 1 0; background: $surface; }
    #menu.hidden { display: none; }
    #menu > .option-list--option { padding: 0 2; }
    #content { padding: 1 2; }
    #content.hidden { display: none; }
    #panel { width: 1fr; height: 1fr; padding: 1 2; display: none; }
    #panel.visible { display: block; }
    #body { width: 1fr; }
    #actions { dock: bottom; height: auto; padding-top: 1; background: $background; display: none; }
    #actions.visible { display: block; }
    #actions Button { margin-right: 2; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [Binding(key, f"show('{sid}')", label, show=sid in ("dash", "today", "week", "trash"))
                for sid, label, key in MENU] + [
        Binding("g", "show('ainews')", "AI news", show=False),
        Binding("v", "cycle_view", "Next view", show=False),
        Binding("m", "toggle_menu", "Menu"),
        Binding("r", "reload", "Refresh"),
        Binding("ctrl+t", "toggle_theme", "Light/Dark"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, cfg: config_mod.Config | None = None, demo: bool = False, session=None):
        super().__init__()
        self.cfg = cfg or config_mod.load()
        self.demo = demo
        self._session = session
        self._own_session = session is None  # r may rebuild it with fresh cookies and config
        self.current = "dash"
        self.pending: dict | None = None  # the plan on screen that Apply would send
        self._last: tuple[str, Draw] | None = None  # (screen, draw) of what is on screen
        self._narrow: bool | None = None
        self._panel_widget: Widget | None = None  # the interactive screen on #panel, if any
        self.views: dict[str, int] = {}  # screen id -> index into its module's VIEWS

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
            yield Vertical(id="panel")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        for t in THEMES.values():
            self.register_theme(t)
        self.theme = THEMES[self.cfg.theme].name
        self._fit_menu()  # also gives the focus to the menu, or to the screen when it is hidden
        self._top()
        self.action_show("dash")
        # not "_auto_refresh": Textual keeps its own attribute by that name on every node
        self.set_interval(60, self._refresh_dashboard)
        self.set_timer(20, self.check_spins)
        self.set_interval(SPIN_CHECK, self.check_spins)

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
        from benchboss.ui import logo

        name = self.cfg.team_name
        if not name and self._session is not None and getattr(self._session, "_league", None):
            name = self._session._league.me.name
        left = Text.assemble(logo.mark(self.pal), (" benchboss", f"bold {self.pal.accent}"),
                             (f"  {__version__}", self.pal.dim),
                             (f"   {name}" if name else "", self.pal.text),
                             ("   demo data" if self.demo else "", self.pal.warn), (extra, self.pal.dim))
        self.query_one("#top", Static).update(left)

    def _status(self, text: str) -> None:
        # a worker can finish while the app shuts down, after the status line is gone
        for status in self.query("#status").results(Static):
            status.update(Text(text, style=self.pal.dim))

    def _show(self, renderable: RenderableType, actions: bool = False) -> None:
        self._unmount_panel()
        self.query_one("#body", Static).update(renderable)
        self._set_actions(actions)

    def _mount_panel(self, mount: Mount) -> None:
        """Show an interactive screen: its widget replaces the static drawing."""
        self._set_actions(False)
        panel = self.query_one("#panel")
        panel.remove_children()
        widget = mount.make()
        self._panel_widget = widget
        panel.mount(widget)
        panel.add_class("visible")
        self.query_one("#content").add_class("hidden")
        self.call_after_refresh(self._focus_panel, widget)

    def _focus_panel(self, widget: Widget) -> None:
        """Give the keys to an interactive screen once it is drawn, unless a key pressed in
        the meantime already took it off the screen (its parts may be gone by now)."""
        if widget is self._panel_widget:
            widget.focus()

    def _unmount_panel(self) -> None:
        panel = self.query_one("#panel")
        self._panel_widget = None
        if panel.has_class("visible"):
            panel.remove_class("visible")
            panel.remove_children()
            self.query_one("#content").remove_class("hidden")
            if self.focused is None:
                self._focus_home()

    def _set_actions(self, visible: bool) -> None:
        self.query_one("#actions").set_class(visible, "visible")
        if not visible:
            self.pending = None  # only a plan on screen, with its Apply button, can be sent
            if isinstance(self.focused, Button):  # a hidden button must not keep the focus
                self._focus_home()

    def _focus_home(self) -> None:
        menu = self.query_one("#menu", OptionList)
        if not menu.has_class("hidden"):
            menu.focus()
        elif self._panel_widget is not None:
            self._panel_widget.focus()  # #panel itself cannot take the focus
        else:
            self.query_one("#content").focus()

    def _present(self, draw: Draw | Mount, pending: dict | None = None) -> None:
        """Draw a screen on the UI thread. A plan that can be applied gets the Apply button and
        is never drawn again in place (a theme change rebuilds it); anything else is kept so a
        resize or a theme change can draw it again from the same data. An interactive screen
        (Mount) gets its widget mounted instead."""
        if isinstance(draw, Mount):
            self._last = None
            self.pending = None
            self._mount_panel(draw)
            return
        self._last = None if pending else (self.current, draw)
        self._show(draw(self.pal, self._width()), actions=bool(pending))
        self.pending = pending

    def _width(self) -> int:
        """Columns the screen can use: the window minus the menu, the padding and the scrollbar."""
        menu = 0 if self.query_one("#menu").has_class("hidden") else MENU_WIDTH
        return max(20, self.size.width - menu - 6)

    def _set_menu(self, visible: bool, focus: bool = True) -> None:
        menu = self.query_one("#menu", OptionList)
        menu.set_class(not visible, "hidden")
        if visible:
            if focus:
                menu.focus()
        elif self.focused is None or self.focused is menu:  # a hidden menu must not keep the keys
            self._focus_home()

    def _fit_menu(self) -> None:
        """Hide the menu on a narrow window so the tables keep their columns; m shows it."""
        narrow = self.size.width < NARROW
        if narrow != self._narrow:  # only when the width crosses the line, so m sticks
            self._narrow = narrow
            # an interactive screen keeps the keys when a wider window brings the menu back
            self._set_menu(not narrow, focus=self._panel_widget is None)

    # --- navigation ----------------------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_show(event.option.id)

    def action_show(self, sid: str) -> None:
        self.current = sid
        self.pending = None
        self._last = None
        # the screen being left goes first, so the keys never go back to it
        self._show(Text("Loading...", style=self.pal.dim))
        if self._narrow:
            self._set_menu(False)  # on a narrow window the menu closes once you pick a screen
        menu = self.query_one("#menu", OptionList)
        idx = next((i for i, (s, _, _) in enumerate(MENU) if s == sid), None)
        if idx is not None and menu.highlighted != idx:
            menu.highlighted = idx
        self._status("talking to ESPN..." if not self.demo else "demo data")
        self.load(sid)

    def action_cycle_view(self) -> None:
        """v: the next view of the current screen (Season, Last 7... on the roster)."""
        module = SCREENS.get(self.current)
        views_ = getattr(module, "VIEWS", ()) if module else ()
        if not views_ or self._last is None or self._last[0] != self.current:
            return
        i = (self.views.get(self.current, 0) + 1) % len(views_)
        self.views[self.current] = i
        self._rerender()
        self._status_views()

    def _status_views(self) -> None:
        module = SCREENS.get(self.current)
        views_ = getattr(module, "VIEWS", ()) if module else ()
        if views_:
            i = self.views.get(self.current, 0) % len(views_)
            # an interactive screen may skip some views (the finder skips splits with no numbers)
            following = getattr(self._panel_widget, "next_view", None)
            nxt = views_[(following() if callable(following) else i + 1) % len(views_)][1]
            self._status(f"{views_[i][1]} · v for {nxt} · r refresh · ctrl+t light/dark · q quit")

    def action_toggle_menu(self) -> None:
        self._set_menu(self.query_one("#menu").has_class("hidden"))
        self._rerender()

    def action_reload(self) -> None:
        if self._own_session and not self.demo:
            # read the cookies and config again: `benchboss login` or `setup` may have run in
            # another terminal since the app started
            theme = self.cfg.theme
            with contextlib.suppress(BenchbossError):
                self.cfg = config_mod.load()
            self.cfg.theme = theme
            self._session = None
        elif self._session is not None and hasattr(self._session, "_league"):
            self._session._league = None
        self.action_show(self.current)

    def action_toggle_theme(self) -> None:
        self.cfg.theme = "light" if self.cfg.theme == "dark" else "dark"
        self.theme = THEMES[self.cfg.theme].name
        if not self.demo:
            with contextlib.suppress(OSError):
                config_mod.save_theme(self.cfg.theme)  # only the theme, never env overrides
        self._top()
        if self.pending:
            self.action_show(self.current)  # a plan that can be applied is rebuilt, not redrawn
        else:
            self._rerender()

    def _refresh_dashboard(self) -> None:
        if self.current == "dash":
            self.load("dash")

    def on_resize(self) -> None:
        # Textual stores the new size in its own handler, which runs after this one, so
        # self.size is still the old size here: fit and draw once that handler is done
        self.call_later(self._resized)

    def _resized(self) -> None:
        if not self.query("#menu"):
            return  # the window can report its size before the widgets exist
        self._fit_menu()
        self._rerender()

    def _rerender(self) -> None:
        """Draw the current screen again (new width or palette) from the data already loaded."""
        if self._last and self._last[0] == self.current:
            self._show(self._last[1](self.pal, self._width()))

    # --- data ----------------------------------------------------------------------------------

    @work(thread=True, exclusive=True, group="load")
    def load(self, sid: str) -> None:
        try:
            draw, pending = self._build(sid)
        except BenchbossError as e:
            draw, pending = self._error(e), None
        except Exception as e:  # never let a bad payload kill the app
            draw, pending = self._error(f"{type(e).__name__}: {e}"), None
        if get_current_worker().is_cancelled:
            return  # the user already moved to another screen
        self.call_from_thread(self._finish, sid, draw, pending)

    def _finish(self, sid: str, draw: Draw | Mount, pending: dict | None) -> None:
        """Runs on the UI thread: only the screen the user is looking at gets drawn, and only
        the plan that is drawn can be applied."""
        if self.current != sid:
            return
        self._top()
        self._present(draw, pending)
        self._status("demo data · nothing is sent to ESPN" if self.demo
                     else "r refresh · ctrl+t light/dark · q quit")
        self._status_views()

    # --- watch list spins -------------------------------------------------------------------------

    def check_spins(self) -> None:
        if self._session is not None or self.demo:
            self._check_spins()

    @work(thread=True, exclusive=True, group="spins", exit_on_error=False)
    def _check_spins(self) -> None:
        """Toast every new spin on a watch-list player, each one once (inbox.toast_spins
        remembers what was toasted, apart from what was read: a toast nobody noticed leaves
        the news in the Inbox). A burst shows the newest few and one line for the rest.
        Errors stay quiet: this runs in the background and the user did not ask for it."""
        from benchboss import inbox

        most = 4  # toasts per check; one more counts the rest
        try:
            items = inbox.toast_spins(self.session)
            toasts = [f"{who}: {item.headline}" for who, item in items[:most]]
            if len(items) > most:
                toasts.append(f"{len(items) - most} more on your watch list: press n for "
                              "Player news.")
            for text in toasts:
                self.call_from_thread(self.notify, text, title="Watch list news", timeout=12,
                                      markup=False)
        except Exception:  # never bother the user, never take the app down
            return

    @staticmethod
    def _error(e) -> Draw:
        msg = str(e)
        if "benchboss setup" in msg or "benchboss login" in msg:
            msg += "\n\nOpen a terminal and run the command above, then press r."
        return lambda pal, w: Text(msg, style=pal.bad)

    def _build(self, sid: str) -> tuple[Draw, dict | None]:
        """Read what a screen needs (in a worker thread). Returns how to draw it, and the plan
        Apply would send when the screen is a plan with moves to make."""
        s = self.session
        module = SCREENS.get(sid)
        if module is not None:
            data = module.load(s)
            if hasattr(module, "widget"):
                return Mount(lambda: module.widget(data, self)), None
            return (lambda pal, w: module.draw(data, pal, w, self.views.get(sid, 0))), None
        if sid == "dash":
            d = dashboard.collect(s)
            return (lambda pal, w: dashboard.render(d, pal, w, news_hint="n for more")), None
        if sid in PLANS:
            return self._build_plan(s, sid)
        if sid in ("news", "ainews"):
            from benchboss import news as news_mod
            from benchboss.ui.common import fit_title
            from benchboss.ui.screens import news as news_screen

            if sid == "ainews":
                if self.demo:
                    raise BenchbossError("the AI briefing is not available with demo data")
                roster = [x.player for x in s.league().me.roster]
                text = news_mod.ai_digest(roster, 5)
                return (lambda pal, w: Group(
                    fit_title("AI briefing", pal, w, ("Claude with web search", "last 5 days"),
                              ("last 5 days",)), Text(""),
                    Text(text, style=pal.text))), None
            tip = ("Press g for an AI briefing with web search (sends your players' names to the "
                   "Anthropic API)." if news_mod.ai_available() and not self.demo else
                   "Want more? Set ANTHROPIC_API_KEY and press g for an AI briefing, or ask "
                   "Copilot Chat for news on your players (player-news skill).")
            data = news_screen.load(s, news_screen.DAYS, ("roster", "watch"), tip=tip)
            return (lambda pal, w: news_screen.draw(data, pal, w)), None
        if sid == "trades":
            from benchboss.core import trades as trades_mod

            lg = s.league()
            ideas = trades_mod.find_trades(lg, limit=8)
            bal = trades_mod.describe_needs(lg)
            return (lambda pal, w: Group(
                common.fit_title("Trade finder", pal, w, ("fair 1-for-1 deals that fix a position",)),
                Text(""),
                views.trades(ideas, pal), Text(""), views.needs(bal, lg.me.name, pal, w),
                Text("\nSend one from a terminal: benchboss trade --give \"A\" --get \"B\" --msg \"...\"",
                     style=pal.dim))), None
        if sid == "inbox":
            from benchboss import inbox

            items = inbox.alerts(s)
            urgent = sum(1 for a in items if a.urgent)
            note = (f"{urgent} need{'s' * (urgent == 1)} you" if urgent else "") if items else ""
            about = "trade offers, claims, messages and watch list news"
            return (lambda pal, w: Group(
                common.fit_title("Inbox", pal, w, (about, note), (note,)),  # the count stays longest
                Text(""), views.alerts(items, pal))), None
        raise BenchbossError(f"unknown screen {sid}")

    def _build_plan(self, s, sid: str) -> tuple[Draw, dict | None]:
        from benchboss.service import periods_for

        cal = s.calendar
        day = cal.period_of(s.today)
        if sid == "today" and day < 1:
            start = cal.date_of(1)
            msg = (f"The season starts {start:%a %b} {start.day}, so there is no lineup to set "
                   "today. Press w to set your lineup for the first week.")
            return (lambda pal, w: Text(msg, style=pal.text)), None
        if sid == "today" and day > cal.final_period:
            return (lambda pal, w: Text("The fantasy season is over.", style=pal.text)), None
        periods = [p for p in periods_for(s, sid) if p >= s.league().scoring_period]
        plans = s.plan_days(periods)
        todo = [p for p in plans if p.changed]
        moves = sum(len(p.moves) for p in todo)
        title = "Today" if sid == "today" else "Rest of the matchup week"

        def draw(pal: Palette, width: int) -> RenderableType:
            from benchboss.ui.common import day_label, fit_title

            span = ""
            if plans:
                first, last = cal.date_of(plans[0].period), cal.date_of(plans[-1].period)
                span = day_label(first) if first == last else f"{day_label(first)} to {day_label(last)}"
            head = fit_title("Optimize", pal, width, (title, span), (title,))  # "Optimize · Today · Wed Nov 4"
            body = views.plan(plans, cal, pal, width)
            if not todo:
                return Group(head, Text(""), body,
                             Text("\n✓ Already optimal. Nothing to do.", style=pal.good))
            return Group(head, Text(""), body,
                         Text(f"\n{moves} move{'s' * (moves != 1)} on {len(todo)} day"
                              f"{'s' * (len(todo) != 1)}. Press Apply to send them to ESPN.",
                              style=pal.text))

        pending = {"periods": [p.period for p in plans], "day": s.today, "kind": sid} if todo else None
        return draw, pending

    # --- writes --------------------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self.query_one("#actions").has_class("visible"):
            return  # a hidden button never acts, even if it still had the focus
        if event.button.id == "cancel":
            self._present(lambda pal, w: Text("Cancelled. Nothing was sent.", style=pal.dim))
        elif event.button.id == "apply":
            pending = self.pending
            if not pending or pending["kind"] != self.current or self.current not in PLANS:
                return
            if self._session is None or self._session.today != pending["day"]:
                self._present(lambda pal, w: Text("The fantasy day changed since this plan was made. "
                                                  "Press t or w to rebuild it.", style=pal.warn))
                self._status("nothing was sent")
                return
            self._set_actions(False)
            self._status("sending to ESPN...")
            self.apply(pending)

    @work(thread=True, exclusive=True, group="write")
    def apply(self, pending: dict) -> None:
        s = self.session
        span = "day" if pending["kind"] == "today" else "week"
        if s.today != pending["day"]:
            msg = "The fantasy day changed since this plan was made. Press t or w to rebuild it."
            self.call_from_thread(self._present, lambda pal, w: Text(msg, style=pal.warn))
            self.call_from_thread(self._status, "nothing was sent")
            return
        if self.demo:
            plans = s.plan_days(pending["periods"])
            moves = sum(len(p.moves) for p in plans)
            days = sum(1 for p in plans if p.changed)
            msg = (f"Your {span} is set: {moves} move{'s' * (moves != 1)} across {days} "
                   f"day{'s' * (days != 1)}. (Demo: nothing was sent.)")
            self.call_from_thread(self.notify, msg, title="Done", timeout=8)
            self.call_from_thread(self._present, lambda pal, w: Text("✓ " + msg, style=f"bold {pal.good}"))
            self.call_from_thread(self._status, "")
            return
        try:
            results = s.apply_days(pending["periods"])
        except BenchbossError as e:
            results, fatal = [], str(e)
        else:
            fatal = ""
        finally:
            s._league = None  # the lineup changed on ESPN: the next screen reads it again
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
            self.call_from_thread(self._present, lambda pal, w: Text(msg, style=pal.bad))
        else:
            msg = f"Your {span} is set: {moves} move{'s' * (moves != 1)} across {days} day{'s' * (days != 1)}."
            done = "\n".join(lines)
            self.call_from_thread(self.notify, msg, title="Done", timeout=8)
            self.call_from_thread(self._present, lambda pal, w: Group(
                Text("✓ " + msg, style=f"bold {pal.good}"), Text(done, style=pal.dim)))
        self.call_from_thread(self._status, "")


def run(cfg: config_mod.Config | None = None, demo: bool = False) -> None:
    cfg = cfg or config_mod.load()
    if not demo and not cfg.league_id and not os.environ.get("BENCHBOSS_LEAGUE_ID"):
        raise BenchbossError("no league configured yet: run `benchboss setup` "
                             "(or try `benchboss --demo` to look around)")
    Benchboss(cfg, demo=demo).run()


__all__ = ["Benchboss", "run", "Vertical"]

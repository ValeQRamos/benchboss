"""Settings (key e). One tab for now, Alerts: what the monitor notifies you about, and the ntfy
push to your phone.

App only, so it has no ``draw`` or ``to_json``: it edits settings and reads nothing from ESPN.
The topic, the server and the token go to ``notify.env`` (private, 0600) and "ntfy" joins
``notify.backends`` in config.json, the same as ``BENCHBOSS_NTFY_*`` and ``--notify ntfy``.
The boxes under "Notify me about" (notify.CATEGORIES) save at once to ``notify.alerts`` in
config.json and apply to every backend. Test sends one note with what is in the boxes, saved
or not. Nothing is saved or sent in the demo. A running ``benchboss monitor`` reads the
settings when it starts.

Keys: tab and shift+tab move between the boxes and buttons, space toggles a category, enter in
a box saves, escape goes back to the menu. Letters type into the box, so the menu keys wait
until you leave it. Copy puts the topic on the clipboard, since the mouse belongs to the app.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass, field

from rich.text import Text
from textual import work
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Static, TabbedContent, TabPane

from benchboss import config as config_mod
from benchboss import notify
from benchboss.errors import BenchbossError
from benchboss.ui.common import fit_title, legend
from benchboss.ui.layout import KeyItem
from benchboss.ui.theme import DARK, Palette

TITLE = "Settings"
VIEWS: tuple[tuple[str, str], ...] = ()
NTFY_VARS = (notify.ENV_NTFY_TOPIC, notify.ENV_NTFY_TOKEN, notify.ENV_NTFY_SERVER)
DEMO = "Demo: nothing is saved or sent."


@dataclass
class SettingsData:
    topic: str = ""
    server: str = ""
    token: str = ""
    enabled: bool = False                    # "ntfy" is in the backends the monitor uses
    backends: list[str] = field(default_factory=list)
    env: tuple[str, ...] = ()                # ntfy variables in the environment: they win
    alerts: tuple[str, ...] = notify.CATEGORY_KEYS  # the categories switched on
    demo: bool = False


def backends_of(saved: dict) -> list[str]:
    """The backends the monitor uses: the saved ones, else the default for this system."""
    names = saved.get("backends")
    if isinstance(names, list) and names:
        return [str(n).strip().lower() for n in names]
    return list(notify.default_backends())


def set_backend(saved: dict, on: bool) -> dict:
    """The ``notify`` setting with ntfy added to (or taken off) the backends, the rest kept."""
    names = [n for n in backends_of(saved) if n != "ntfy"]
    return {**saved, "backends": names + ["ntfy"] if on else names}


def set_alerts(saved: dict, keys: list[str]) -> dict:
    """The ``notify`` setting with the categories switched on set to ``keys``, the rest kept."""
    return {**saved, "alerts": [k for k in notify.CATEGORY_KEYS if k in keys]}


def load(session) -> SettingsData:
    sec = notify.secrets()
    names = backends_of(session.cfg.notify)
    alerts = tuple(k for k in notify.CATEGORY_KEYS if k in notify.categories(session.cfg.notify))
    return SettingsData(sec.get(notify.ENV_NTFY_TOPIC, ""), sec.get(notify.ENV_NTFY_SERVER, ""),
                        sec.get(notify.ENV_NTFY_TOKEN, ""), "ntfy" in names, names,
                        tuple(v for v in NTFY_VARS if os.environ.get(v)), alerts, session.demo)


def status_line(data: SettingsData, pal: Palette) -> Text:
    if data.enabled and data.topic:
        out = Text(f"ntfy is on. The monitor sends alerts to: {', '.join(data.backends)}.",
                   style=pal.good)
    elif data.enabled:
        out = Text("ntfy is on but has no topic yet, so nothing is sent.", style=pal.warn)
    else:
        out = Text(f"ntfy is off. The monitor sends alerts to: {', '.join(data.backends)}.",
                   style=pal.dim)
    if data.env:
        out.append(f"\n{', '.join(data.env)} is set in the environment and wins over what "
                   "you save here.", style=pal.warn)
    if not data.alerts:
        out.append("\nEvery category below is off, so the monitor sends nothing.", style=pal.warn)
    return out


def category_label(key: str, compact: bool) -> str:
    """"Lineup changes: auto-swap starts or benches a player", or just the name on a phone."""
    _, label, about = next(c for c in notify.CATEGORIES if c[0] == key)
    return label if compact else f"{label}: {about}"


class SettingsView(VerticalScroll):
    """The interactive screen: tabs, and on the Alerts tab three boxes, five buttons and one
    check box per alert category."""

    DEFAULT_CSS = """
    SettingsView { height: 1fr; }
    SettingsView #st-title { height: 1; }
    SettingsView TabbedContent { height: auto; margin-top: 1; }
    SettingsView ContentSwitcher { height: auto; }
    SettingsView TabPane { height: auto; padding: 0; }
    SettingsView #st-status { height: auto; }
    SettingsView .st-label { height: 1; margin-top: 1; color: $text-muted; }
    SettingsView Input { height: 1; border: none; padding: 0 1; background: $surface;
                         color: $foreground; }
    SettingsView Input:focus { border: none; background: $panel; }
    SettingsView Checkbox { height: 1; border: none; padding: 0 1; background: transparent; }
    SettingsView #st-buttons { height: auto; margin-top: 1; }
    SettingsView Button { margin-right: 1; min-width: 8; }
    SettingsView #st-message { height: auto; margin-top: 1; }
    SettingsView #st-hint { height: auto; margin-top: 1; }
    Screen.-compact SettingsView Button { height: 1; min-width: 6; border: none !important; }
    """

    BINDINGS = [("escape", "back", "Back")]
    SCOPED_CSS = False  # the compact rule starts at Screen, outside this widget

    def __init__(self, data: SettingsData, app) -> None:
        super().__init__()
        self.data = data
        self._owner_app = app
        self.message: tuple[str, str] = ("", "dim")  # (text, "good" | "bad" | "dim")

    def compose(self):
        d = self.data
        compact = bool(getattr(self._owner_app, "compact", False))
        yield Static(id="st-title")
        with TabbedContent(id="st-tabs"), TabPane("Alerts", id="st-alerts"):
            yield Static(id="st-status")
            yield Static("ntfy topic (subscribe to it in the app)", classes="st-label")
            yield Input(d.topic, placeholder="benchboss-...", id="st-topic")
            yield Static("Server (empty for ntfy.sh)", classes="st-label")
            yield Input(d.server, placeholder=notify.NTFY_SERVER, id="st-server")
            yield Static("Token (empty unless the topic is private)", classes="st-label")
            yield Input(d.token, password=True, placeholder="tk_...", id="st-token")
            with Horizontal(id="st-buttons"):
                yield Button("Save", id="st-save", variant="primary")
                yield Button("Test", id="st-test")
                yield Button("New", id="st-new")
                yield Button("Copy", id="st-copy")
                yield Button("Off", id="st-off")
            yield Static(id="st-message")
            yield Static("Notify me about", classes="st-label")
            for key in notify.CATEGORY_KEYS:
                yield Checkbox(category_label(key, compact), key in d.alerts, id=f"st-cat-{key}")
        yield Static(id="st-hint")

    @property
    def pal(self) -> Palette:
        return getattr(self._owner_app, "pal", DARK)

    def _live(self) -> bool:
        return self.is_attached and getattr(self._owner_app, "_panel_widget", self) is self

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
            topic = next(iter(self.query("#st-topic")), None)
            if topic is not None:
                topic.focus(scroll_visible)
            else:  # the tab's boxes are mounted a moment after the view
                self.call_after_refresh(self.focus)
        return self

    def key_items(self) -> list[KeyItem]:
        return [KeyItem("tab", "next", priority=10), KeyItem("space", "toggle", priority=15),
                KeyItem("⏎", "save", priority=20), KeyItem("esc", "back", priority=30)]

    # --- drawing -------------------------------------------------------------------------------

    def _render_all(self) -> None:
        if not self._live():
            return
        pal, width = self.pal, max(20, self.size.width or 100)
        compact = bool(getattr(self._owner_app, "compact", False))
        self.query_one("#st-title", Static).update(
            fit_title(TITLE, pal, width, ("alerts and ntfy",), ()))
        self.query_one("#st-status", Static).update(status_line(self.data, pal))
        for key in notify.CATEGORY_KEYS:
            self.query_one(f"#st-cat-{key}", Checkbox).label = category_label(key, compact)
        self._render_message()
        hint = Text() if compact else legend(
            pal, ("tab", "next"), ("space", "toggle"), ("enter", "save"), ("esc", "back"))
        if not compact:
            hint.append("  ·  a running monitor reads this when it starts", style=pal.dim)
        self.query_one("#st-hint", Static).update(hint)
        refresh = getattr(self._owner_app, "refresh_keys", None)
        if callable(refresh):
            refresh()

    def _say(self, text: str, kind: str = "dim") -> None:
        self.message = (text, kind)
        self._render_message()

    def _render_message(self) -> None:
        pal = self.pal
        text, kind = self.message
        style = {"good": pal.good, "bad": pal.bad}.get(kind, pal.dim)
        self.query_one("#st-message", Static).update(Text(text, style=style))

    # --- actions -------------------------------------------------------------------------------

    def _fields(self) -> tuple[str, str, str]:
        return (self.query_one("#st-topic", Input).value, self.query_one("#st-token", Input).value,
                self.query_one("#st-server", Input).value)

    def _checked(self) -> tuple[str, str, str] | None:
        """The boxes, checked; None (with the reason on screen) when they cannot be used or
        this is the demo."""
        if self.data.demo:
            self._say(DEMO)
            return None
        if not self.query_one("#st-topic", Input).value.strip():
            self._say("Enter a topic first (New topic makes one).", "bad")
            return None
        try:
            return notify.check_ntfy(*self._fields())
        except notify.NotifyError as e:
            self._say(str(e), "bad")
            return None

    def _save_notify(self, saved: dict) -> None:
        """Write the ``notify`` setting to config.json and to the running app's config."""
        if config_mod.save_field("notify", saved) is None:
            raise BenchbossError("config.json is not valid JSON: fix it, then try again")
        self._owner_app.cfg.notify = saved

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """A category switched on or off: saved at once (the demo only remembers it)."""
        event.stop()
        keys = [k for k in notify.CATEGORY_KEYS
                if self.query_one(f"#st-cat-{k}", Checkbox).value]
        if tuple(keys) == self.data.alerts:
            return
        if not self.data.demo:
            try:
                self._save_notify(set_alerts(self._owner_app.cfg.notify, keys))
            except (BenchbossError, OSError) as e:
                self._say(f"Not saved: {e}", "bad")
                return
        self.data.alerts = tuple(keys)
        self._render_all()
        self._say(DEMO if self.data.demo else "Saved. Restart benchboss monitor to use it.",
                  "dim" if self.data.demo else "good")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        {"st-save": self.action_save, "st-test": self.action_test, "st-new": self.action_new,
         "st-copy": self.action_copy, "st-off": self.action_off}[event.button.id]()

    def action_save(self) -> None:
        values = self._checked()
        if values is None:
            return
        topic, token, server = values
        saved = set_backend(self._owner_app.cfg.notify, True)
        try:
            notify.save_ntfy(topic, token, server)
            self._save_notify(saved)
        except (BenchbossError, OSError) as e:
            self._say(f"Not saved: {e}", "bad")
            return
        self.data.topic, self.data.token, self.data.server = topic, token, server
        self.data.enabled, self.data.backends = True, backends_of(saved)
        self._render_all()
        self._say(f"Saved. Subscribe to {topic} in the ntfy app, press Test, and restart "
                  "benchboss monitor to use it.", "good")

    def action_new(self) -> None:
        if self.data.demo:
            self._say(DEMO)
            return
        self.query_one("#st-topic", Input).value = notify.new_topic()
        self._say("A new topic is in the box. Press Save, then subscribe to it in the ntfy app.")

    def action_copy(self) -> None:
        """The terminal's own selection does not work while the app has the mouse."""
        topic = self.query_one("#st-topic", Input).value.strip()
        if not topic:
            self._say("There is no topic to copy.", "bad")
            return
        self._owner_app.copy_to_clipboard(topic)  # OSC 52: the terminal must allow it
        if sys.platform == "darwin":
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(["pbcopy"], input=topic.encode(), timeout=5, check=False)
        self._say(f"Copied {topic}", "good")

    def action_off(self) -> None:
        if self.data.demo:
            self._say(DEMO)
            return
        saved = set_backend(self._owner_app.cfg.notify, False)
        try:
            self._save_notify(saved)
        except (BenchbossError, OSError) as e:
            self._say(f"Not changed: {e}", "bad")
            return
        self.data.enabled, self.data.backends = False, backends_of(saved)
        self._render_all()
        self._say("ntfy is off. Your topic is still saved.", "good")

    def action_test(self) -> None:
        values = self._checked()
        if values is None:
            return
        self.query_one("#st-test", Button).disabled = True
        self._say("Sending a test note...")
        self._send_test(*values)

    @work(thread=True, exclusive=True, group="ntfy-test", exit_on_error=False)
    def _send_test(self, topic: str, token: str, server: str) -> None:
        note = notify.Note("benchboss", "Test note from benchboss: alerts work (Nikola Jokić).",
                           "normal", "test")
        backend = notify.NtfyBackend(topic, token, server or notify.NTFY_SERVER)
        receipt = notify.send(note, [backend])[0]
        self.app.call_from_thread(self._tested, receipt)

    def _tested(self, receipt: str) -> None:
        if not self._live():
            return
        self.query_one("#st-test", Button).disabled = False
        ok = receipt.endswith("sent")
        self._say(receipt if not ok else "ntfy: sent. Check your phone.", "good" if ok else "bad")

    def action_back(self) -> None:
        app = self._owner_app
        menu = next(iter(app.query("#menu")), None) if hasattr(app, "query") else None
        if menu is None:
            return
        if menu.has_class("hidden") and hasattr(app, "action_toggle_menu"):
            app.action_toggle_menu()
        else:
            menu.focus()


def widget(data: SettingsData, app) -> SettingsView:
    return SettingsView(data, app)


__all__ = ["SettingsData", "SettingsView", "TITLE", "VIEWS", "backends_of", "category_label",
           "load", "set_alerts", "set_backend", "status_line", "widget"]

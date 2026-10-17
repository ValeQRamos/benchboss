"""First-run setup inside the web app: cookies, league and team.

``benchboss setup`` needs a real terminal for its hidden prompts, which a browser session does
not have. This screen does the same steps with password fields, and the app shows it only in a
web session (``benchboss.web.in_web_session``)."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from benchboss import config as config_mod
from benchboss import credentials
from benchboss import setup as setup_mod
from benchboss.errors import AuthError, BenchbossError

INTRO = ("Connect your ESPN account.\n\nbenchboss reads your league with the two cookies your "
         "browser uses on espn.com. In Chrome: espn.com > DevTools > Application > Cookies > "
         "https://www.espn.com, copy the values of espn_s2 and SWID. They are kept on this "
         "server, in a file only its user can read.")


class SetupScreen(ModalScreen[bool]):
    """Dismisses with True once the cookies and the league are saved."""

    DEFAULT_CSS = """
    SetupScreen { align: center middle; }
    #setup { width: 76; max-width: 96%; height: auto; max-height: 96%; padding: 1 2;
             border: round $accent; background: $surface; }
    #setup Input { margin-top: 1; }
    #setup OptionList { height: auto; max-height: 12; margin-top: 1; }
    #setup Button { margin-top: 1; }
    #msg { margin-top: 1; }
    """

    def __init__(self, cfg: config_mod.Config) -> None:
        super().__init__()
        self.cfg = cfg
        self._cookies: tuple[str, str] | None = None
        self._conn: setup_mod.Connection | None = None
        self._leagues: list[dict] = []
        self._stage = "cookies"  # cookies, league_id (typed), league (picked), team (picked)
        self._season = config_mod.current_season()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="setup"):
            yield Static(INTRO, markup=False)
            yield Input(password=True, placeholder="espn_s2", id="s2")
            yield Input(password=True, placeholder="SWID", id="swid")
            yield Input(placeholder="League URL or id (fantasy.espn.com/basketball/league?leagueId=...)",
                        id="league")
            yield OptionList(id="choices")
            yield Static("", id="msg", markup=False)
            yield Button("Continue", id="go", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#league").display = False
        self.query_one("#choices").display = False
        self.query_one("#s2").focus()

    # --- input -------------------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "s2":
            self.query_one("#swid").focus()
        else:
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go":
            self._submit()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()  # the app's own handler would take this for a menu entry
        kind, _, value = (event.option.id or "").partition(":")
        if kind == "league" and self._cookies:
            lg = self._leagues[int(value)]
            self._connect(lg["league_id"], lg["season"] or self._season, lg["team_id"])
        elif kind == "team" and self._conn:
            self._conn.team_id = int(value)
            self._conn.team_name = next(n for i, n, _ in self._conn.teams if i == int(value))
            self._save()

    def _submit(self) -> None:
        if self._stage == "cookies":
            s2 = self.query_one("#s2", Input).value
            swid = self.query_one("#swid", Input).value
            if not s2.strip() or not swid.strip():
                return self._say("Both values are needed.")
            self._busy("Checking with ESPN...")
            self._discover(s2, swid)
        elif self._stage == "league_id":
            try:
                league_id = setup_mod.parse_league_id(self.query_one("#league", Input).value)
            except BenchbossError as e:
                return self._say(str(e))
            self._connect(league_id, self._season, None)

    # --- steps (ESPN calls run in a worker thread) ---------------------------------------------

    @work(thread=True, exclusive=True, group="setup")
    def _discover(self, s2: str, swid: str) -> None:
        cookies = (s2.strip().strip('"'), credentials.normalize_swid(swid))
        try:
            leagues = setup_mod.find_leagues(cookies)
        except AuthError as e:
            self.app.call_from_thread(self._fail, str(e))
            return
        except BenchbossError:
            leagues = []  # like the terminal wizard: ask for the league instead
        self.app.call_from_thread(self._leagues_found, cookies, leagues)

    def _leagues_found(self, cookies: tuple[str, str], leagues: list[dict]) -> None:
        self._cookies = cookies
        self._leagues = leagues
        if len(leagues) == 1:
            lg = leagues[0]
            self._connect(lg["league_id"], lg["season"] or self._season, lg["team_id"])
        elif leagues:
            self._stage = "league"
            self._choose("Which league?", [
                Option(f"{lg['league_name']}  {lg['season']} · id {lg['league_id']}", id=f"league:{i}")
                for i, lg in enumerate(leagues)])
        else:
            self._stage = "league_id"
            self._idle("Could not list your leagues. Paste the league URL or id.")
            box = self.query_one("#league", Input)
            box.display = True
            box.focus()

    @work(thread=True, exclusive=True, group="setup")
    def _connect(self, league_id: int, season: int, team_id: int | None) -> None:
        self.app.call_from_thread(self._busy, "Reading your league...")
        try:
            conn = setup_mod.connect(self._cookies, league_id, season, team_id)
        except BenchbossError as e:
            self.app.call_from_thread(self._fail, str(e))
            return
        self.app.call_from_thread(self._connected, conn)

    def _connected(self, conn: setup_mod.Connection) -> None:
        self._conn = conn
        if conn.team_id is None:
            self._stage = "team"
            self._choose(f"{conn.league_name}: which team is yours?", [
                Option(f"{name}  {owner}", id=f"team:{tid}") for tid, name, owner in conn.teams])
        else:
            self._save()

    def _save(self) -> None:
        try:
            setup_mod.save(self.cfg, self._cookies, self._conn)
        except (BenchbossError, OSError) as e:
            return self._fail(f"could not save: {e}")
        self.dismiss(True)

    # --- what is on screen ---------------------------------------------------------------------

    def _say(self, text: str) -> None:
        self.query_one("#msg", Static).update(text)

    def _busy(self, text: str) -> None:
        self._say(text)
        self.query_one("#go", Button).disabled = True

    def _idle(self, text: str = "") -> None:
        self._say(text)
        self.query_one("#go", Button).disabled = False

    def _fail(self, text: str) -> None:
        self._stage = "cookies"
        self.query_one("#choices").display = False
        self._idle(text)

    def _choose(self, prompt: str, options: list[Option]) -> None:
        self._say(prompt)
        choices = self.query_one("#choices", OptionList)
        choices.clear_options()
        choices.add_options(options)
        choices.display = True
        choices.focus()
        self.query_one("#go", Button).disabled = True

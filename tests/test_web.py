"""benchboss web, login --to and the web-mode setup screen. No network, no keychain, no ssh."""

import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from benchboss import cli, credentials, web
from benchboss import config as config_mod
from benchboss import setup as setup_mod
from benchboss.config import Config
from benchboss.errors import AuthError, BenchbossError
from benchboss.ui import app as app_mod
from benchboss.ui.app import Benchboss
from benchboss.ui.web_setup import SetupScreen

WEB_DRIVER = "textual.drivers.web_driver:WebDriver"


def exit_code(*argv) -> int:
    with pytest.raises(SystemExit) as e:
        cli.main(list(argv))
    return e.value.code


# --- web session helpers -------------------------------------------------------------------------

def test_a_web_session_is_told_by_the_driver_textual_serve_sets(monkeypatch):
    assert web.in_web_session() is False
    monkeypatch.setenv("TEXTUAL_DRIVER", WEB_DRIVER)
    assert web.in_web_session() is True
    monkeypatch.setenv("TEXTUAL_DRIVER", "textual.drivers.linux_driver:LinuxDriver")
    assert web.in_web_session() is False


def test_the_session_command_runs_this_install_as_the_app():
    cmd = web.session_command()
    assert cmd.endswith("-m benchboss app")
    assert cmd.startswith(sys.executable) or sys.executable in cmd
    assert web.session_command(demo=True, theme="light").endswith("--demo --theme light app")


def test_the_app_starts_without_a_terminal_only_in_a_web_session(monkeypatch):
    started = []
    monkeypatch.setattr(cli, "cmd_app", lambda c: started.append(1))
    assert exit_code("--demo") == 2 and started == []  # pytest has no terminal
    monkeypatch.setenv("TEXTUAL_DRIVER", WEB_DRIVER)
    cli.main(["--demo"])
    assert started == [1]


# --- benchboss web -------------------------------------------------------------------------------

@pytest.fixture
def serve(monkeypatch):
    calls = []

    class Server:
        def __init__(self, command, host, port, title, public_url):
            calls.append({"command": command, "host": host, "port": port, "url": public_url})

        def serve(self):
            calls.append("served")

    monkeypatch.setitem(sys.modules, "textual_serve", types.ModuleType("textual_serve"))
    module = types.ModuleType("textual_serve.server")
    module.Server = Server
    monkeypatch.setitem(sys.modules, "textual_serve.server", module)
    return calls


def test_web_listens_on_localhost_by_default(serve):
    cli.main(["--demo", "web"])
    assert serve[0]["host"] == "127.0.0.1" and serve[0]["port"] == 8000
    assert serve[0]["url"] is None
    assert serve[0]["command"].endswith("--demo app")
    assert serve[1] == "served"


def test_web_takes_the_public_address_behind_a_proxy(serve):
    cli.main(["web", "--port", "9001", "--url", "https://bb.example.test"])
    assert serve[0]["port"] == 9001 and serve[0]["url"] == "https://bb.example.test"
    assert "--demo" not in serve[0]["command"]


def test_web_refuses_an_address_other_computers_can_reach(serve, capsys):
    assert exit_code("web", "--host", "0.0.0.0") == 1
    assert serve == []
    assert "--allow-remote" in capsys.readouterr().err
    cli.main(["web", "--host", "0.0.0.0", "--allow-remote"])
    assert serve[0]["host"] == "0.0.0.0"


def test_web_says_how_to_install_the_extra(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "textual_serve", None)
    monkeypatch.setitem(sys.modules, "textual_serve.server", None)
    assert exit_code("--demo", "web") == 1
    assert "textual-serve" in capsys.readouterr().err


# --- benchboss login --to ------------------------------------------------------------------------

@pytest.fixture
def ssh(monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    credentials.store("S2-SECRET-VALUE", "{SWID-SECRET}")
    return calls


def test_login_to_sends_the_cookies_on_stdin_and_never_in_the_command(ssh, capsys):
    cli.main(["login", "--to", "bb@box.test", "--identity", "/keys/k", "--ssh-port", "2222", "--yes"])
    argv, kw = ssh[0]
    assert argv[:6] == ["ssh", "-p", "2222", "-i", "/keys/k", "bb@box.test"]
    assert "credentials.json" in argv[-1] and "chmod 600" in argv[-1]
    assert "SECRET" not in " ".join(argv)
    assert json.loads(kw["input"]) == {"espn_s2": "S2-SECRET-VALUE", "SWID": "{SWID-SECRET}"}
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err
    assert "Cookies sent to bb@box.test" in out.out


def test_login_to_dry_run_sends_nothing(ssh, capsys):
    cli.main(["login", "--to", "box.test", "--dry-run"])
    assert ssh == []
    assert "Dry run" in capsys.readouterr().out


def test_login_to_asks_before_sending(ssh):
    assert exit_code("login", "--to", "box.test") == 10  # no terminal, no --yes
    assert ssh == []


@pytest.mark.parametrize("target", ["-oProxyCommand=evil", "bb@host;reboot", "a b"])
def test_login_to_rejects_a_target_that_is_not_a_host(ssh, target):
    assert exit_code("login", f"--to={target}", "--yes") == 2
    assert ssh == []


def test_login_to_shows_what_ssh_said_when_it_fails(ssh, monkeypatch, capsys):
    def refused(argv, **kw):
        return SimpleNamespace(returncode=255, stdout="", stderr="Permission denied (publickey).\n")

    monkeypatch.setattr(cli.subprocess, "run", refused)
    assert exit_code("login", "--to", "box.test", "--yes") == 1
    err = capsys.readouterr().err
    assert "Permission denied" in err and "SECRET" not in err


def test_login_to_needs_cookies_to_send(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")  # no Chrome import to fall back on
    assert exit_code("login", "--to", "box.test", "--yes") == 2


# --- setup helpers -------------------------------------------------------------------------------

def _league(owner):
    teams = {1: SimpleNamespace(id=1, name="Mine", owner_name="me", owner_ids=["{ME}"]),
             2: SimpleNamespace(id=2, name="Theirs", owner_name="you", owner_ids=[owner])}
    return SimpleNamespace(name="The League", teams=teams, my_team_id=1, me=teams[1])


@pytest.fixture
def espn(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def league(self, *views):
            return {}

    monkeypatch.setattr(setup_mod, "Client", FakeClient)
    monkeypatch.setattr(setup_mod, "parse_league", lambda raw, team_id, swid, strict=False: _league("{YOU}"))


def test_connect_finds_your_team_by_your_swid(espn):
    conn = setup_mod.connect(("s2", "{ME}"), 7, 2027)
    assert (conn.team_id, conn.team_name, conn.league_name) == (1, "Mine", "The League")


def test_connect_offers_the_teams_when_none_is_yours(espn):
    conn = setup_mod.connect(("s2", "{STRANGER}"), 7, 2027)
    assert conn.team_id is None and conn.team_name == ""
    assert [t[0] for t in conn.teams] == [1, 2]


def test_find_leagues_prefers_the_current_season(monkeypatch):
    now = config_mod.current_season()
    found = [{"league_id": 1, "season": now - 1}, {"league_id": 2, "season": now}]
    monkeypatch.setattr(setup_mod, "discover", lambda cookies: found)
    assert [lg["league_id"] for lg in setup_mod.find_leagues(("s", "w"))] == [2]
    monkeypatch.setattr(setup_mod, "discover", lambda cookies: found[:1])
    assert [lg["league_id"] for lg in setup_mod.find_leagues(("s", "w"))] == [1]


def test_save_writes_the_cookies_and_the_league():
    cfg = Config()
    conn = setup_mod.Connection(7, config_mod.current_season(), "The League", 2, "Mine", [])
    setup_mod.save(cfg, ("s2-value", "{SWID}"), conn)
    assert credentials.get() == ("s2-value", "{SWID}")
    saved = config_mod.load()
    assert (saved.league_id, saved.team_id, saved.team_name) == (7, 2, "Mine")
    assert saved.season is None  # follows the league into next season


# --- the setup screen in a web session -----------------------------------------------------------

LEAGUE = {"league_id": 7, "league_name": "The League", "team_id": 2, "season": 2027}


def conn(team_id=2):
    return setup_mod.Connection(7, 2027, "The League", team_id, "Mine" if team_id else "",
                                [(2, "Mine", "me"), (3, "Theirs", "you")])


def web_app(monkeypatch):
    monkeypatch.setenv("TEXTUAL_DRIVER", WEB_DRIVER)
    app = Benchboss(Config())
    shown = []
    app.action_show = shown.append  # the dashboard would call ESPN
    return app, shown


async def settle(pilot, app):
    for _ in range(4):
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)


async def enter_cookies(pilot, app):
    app.screen.query_one("#s2").value = "S2-VALUE"
    app.screen.query_one("#swid").value = "{SWID}"
    app.screen.query_one("#swid").focus()
    await pilot.press("enter")
    await settle(pilot, app)


def test_only_a_web_session_without_setup_asks_for_it(monkeypatch):
    app = Benchboss(Config())
    assert app._needs_web_setup() is False  # a terminal has `benchboss setup`
    monkeypatch.setenv("TEXTUAL_DRIVER", WEB_DRIVER)
    assert app._needs_web_setup() is True
    assert Benchboss(Config(), demo=True)._needs_web_setup() is False
    credentials.store("s2", "{SWID}")
    assert Benchboss(Config(league_id=7), demo=False)._needs_web_setup() is False
    assert Benchboss(Config(league_id=None))._needs_web_setup() is True  # cookies, no league


def test_run_waits_for_the_screen_in_a_web_session(monkeypatch):
    monkeypatch.setattr(app_mod.Benchboss, "run", lambda self, *a, **k: None)
    with pytest.raises(BenchbossError, match="no league configured"):
        app_mod.run(Config())
    monkeypatch.setenv("TEXTUAL_DRIVER", WEB_DRIVER)
    app_mod.run(Config())  # no error: the setup screen asks


def test_setup_saves_one_league_without_asking_which(monkeypatch):
    monkeypatch.setattr(setup_mod, "find_leagues", lambda cookies: [LEAGUE])
    monkeypatch.setattr(setup_mod, "connect", lambda cookies, lid, season, team_id=None: conn(2))
    app, shown = web_app(monkeypatch)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SetupScreen)
            await enter_cookies(pilot, app)
            assert not isinstance(app.screen, SetupScreen)
            assert shown == ["dash"]

    asyncio.run(scenario())
    assert credentials.get() == ("S2-VALUE", "{SWID}")
    saved = config_mod.load()
    assert (saved.league_id, saved.team_id) == (7, 2)


def test_setup_asks_which_team_when_none_is_yours(monkeypatch):
    monkeypatch.setattr(setup_mod, "find_leagues", lambda cookies: [LEAGUE])
    monkeypatch.setattr(setup_mod, "connect", lambda cookies, lid, season, team_id=None: conn(None))
    app, shown = web_app(monkeypatch)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            await enter_cookies(pilot, app)
            assert isinstance(app.screen, SetupScreen)  # waiting for the team
            await pilot.press("down", "down", "enter")  # the second team
            await settle(pilot, app)
            assert shown == ["dash"]

    asyncio.run(scenario())
    assert config_mod.load().team_id == 3


def test_setup_asks_which_league_when_there_are_several(monkeypatch):
    other = {**LEAGUE, "league_id": 8, "league_name": "Other"}
    monkeypatch.setattr(setup_mod, "find_leagues", lambda cookies: [LEAGUE, other])
    seen = []

    def connect(cookies, lid, season, team_id=None):
        seen.append(lid)
        return conn(2)

    monkeypatch.setattr(setup_mod, "connect", connect)
    app, shown = web_app(monkeypatch)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            await enter_cookies(pilot, app)
            await pilot.press("down", "down", "enter")  # the second league
            await settle(pilot, app)
            assert shown == ["dash"]

    asyncio.run(scenario())
    assert seen == [8]


def test_setup_keeps_the_screen_and_saves_nothing_when_espn_rejects_the_cookies(monkeypatch):
    def rejected(cookies):
        raise AuthError("ESPN rejected the cookies")

    monkeypatch.setattr(setup_mod, "find_leagues", rejected)
    app, shown = web_app(monkeypatch)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            await enter_cookies(pilot, app)
            assert isinstance(app.screen, SetupScreen)
            assert app.screen.query_one("#go").disabled is False  # try again
            assert shown == []

    asyncio.run(scenario())
    assert credentials.get() is None
    assert not (config_mod.config_dir() / "config.json").exists()


def test_setup_asks_for_the_league_when_the_list_is_unavailable(monkeypatch):
    def down(cookies):
        raise BenchbossError("could not list")

    monkeypatch.setattr(setup_mod, "find_leagues", down)
    got = []

    def connect(cookies, lid, season, team_id=None):
        got.append(lid)
        return conn(2)

    monkeypatch.setattr(setup_mod, "connect", connect)
    app, shown = web_app(monkeypatch)

    async def scenario():
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            await enter_cookies(pilot, app)
            box = app.screen.query_one("#league")
            assert box.display is True
            box.value = "https://fantasy.espn.com/basketball/league?leagueId=4242"
            box.focus()
            await pilot.press("enter")
            await settle(pilot, app)
            assert shown == ["dash"]

    asyncio.run(scenario())
    assert got == [4242]

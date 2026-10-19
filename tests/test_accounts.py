"""Accounts for benchboss web: the store, the sign in with many people, one folder each, the
benchboss users command. No network: GitHub is faked and no real server starts."""

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("aiohttp")

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request  # noqa: E402

from benchboss import cli, credentials, weblogin  # noqa: E402
from benchboss import config as config_mod  # noqa: E402
from benchboss.accounts import Accounts  # noqa: E402
from benchboss.errors import BenchbossError  # noqa: E402
from benchboss.weblogin import Auth, AuthConfig  # noqa: E402

KEY = b"k" * 32
ALICE = "alice password 123"
BOB = "bob password 4567"
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="needs Unix file modes")


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def accounts(tmp_path, clock):
    acc = Accounts(tmp_path / "svc", now=clock)
    acc.add("alice", ALICE)
    acc.add("bob", BOB, github="BobHub")
    return acc


# --- the store -----------------------------------------------------------------------------------

def test_a_password_is_checked_and_never_kept_as_text(accounts):
    assert accounts.check("alice", ALICE) == "alice"
    assert accounts.check("alice", BOB) is None
    assert accounts.check("nobody", ALICE) is None
    assert ALICE.encode() not in accounts.path.read_bytes()


@POSIX
def test_the_file_and_each_folder_are_private(accounts):
    assert accounts.path.stat().st_mode & 0o777 == 0o600
    assert accounts.home("alice").is_dir() and accounts.home("alice").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("name", ["", "a", "Alice", "al ice", "../root", "1abc", "a" * 17, "al/ice"])
def test_a_name_that_could_leave_the_users_folder_is_refused(accounts, name):
    with pytest.raises(BenchbossError):
        accounts.add(name, ALICE)
    with pytest.raises(BenchbossError):
        accounts.home(name)


def test_a_short_password_a_repeat_name_and_a_shared_github_name_are_refused(accounts):
    with pytest.raises(BenchbossError, match="characters"):
        accounts.add("carol", "short")
    with pytest.raises(BenchbossError, match="already exists"):
        accounts.add("alice", ALICE)
    with pytest.raises(BenchbossError, match="already belongs"):
        accounts.add("carol", ALICE, github="bobhub")
    assert [p.name for p in accounts.everyone()] == ["alice", "bob"]


def test_github_names_are_matched_by_login_or_id_ignoring_case(accounts):
    assert accounts.by_github("BOBHUB", 1) == "bob"
    accounts.set_github("alice", "583231")
    assert accounts.by_github("whoever", 583231) == "alice"
    assert accounts.by_github("nobody", 2) is None
    accounts.set_github("alice", None)
    assert accounts.by_github("whoever", 583231) is None


def test_a_new_password_or_a_removal_ends_the_open_sign_ins(accounts, clock):
    issued = clock.t
    assert accounts.session_ok("alice", issued)
    clock.t += 10
    accounts.set_password("alice", "another password 1")
    assert not accounts.session_ok("alice", issued)
    assert accounts.session_ok("alice", clock.t)
    assert accounts.check("alice", "another password 1") == "alice"
    assert accounts.check("alice", ALICE) is None
    accounts.remove("bob")
    assert not accounts.session_ok("bob", clock.t + 1)


def test_removing_deletes_the_folder_unless_asked_to_keep_it(accounts):
    for name in ("alice", "bob"):
        (accounts.home(name) / "credentials.json").write_text("{}")
    accounts.remove("alice")
    assert not accounts.home("alice").exists()
    accounts.remove("bob", keep_data=True)
    assert (accounts.home("bob") / "credentials.json").exists()
    with pytest.raises(BenchbossError, match="no account"):
        accounts.remove("alice")


def test_importing_copies_the_settings_but_not_the_servers_own_files(accounts, tmp_path):
    src = tmp_path / "old"
    (src / "leagues" / "1").mkdir(parents=True)
    (src / "credentials.json").write_text('{"espn_s2": "x"}')
    (src / "leagues" / "1" / "marks.json").write_text("{}")
    (src / "web-secret").write_text("do not copy")
    (src / "cache").mkdir()
    (src / "cache" / "x").write_text("x")
    accounts.import_home("alice", src)
    home = accounts.home("alice")
    assert (home / "credentials.json").exists() and (home / "leagues" / "1" / "marks.json").exists()
    assert not (home / "web-secret").exists() and not (home / "cache").exists()
    with pytest.raises(BenchbossError, match="not a folder"):
        accounts.import_home("alice", tmp_path / "missing")


# --- signing in with many people -----------------------------------------------------------------

def make(accounts, clock, exchange=None, **cfg):
    async def no_exchange(*a):
        raise AssertionError("GitHub must not be called")

    return Auth(AuthConfig(secret=KEY, accounts=accounts, **cfg), exchange=exchange or no_exchange,
                now=clock, fail_delay=0)


async def started(auth):
    app = web.Application()

    async def who(request):
        return web.Response(text="the app")

    app.router.add_get("/", who)
    auth.install(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def sign_in(client, user, password):
    return await client.post("/login", data={"username": user, "password": password},
                             allow_redirects=False)


def test_each_person_signs_in_with_their_own_password(accounts, clock):
    async def go():
        client = await started(make(accounts, clock))
        assert (await sign_in(client, "alice", BOB)).status == 401
        assert (await sign_in(client, "carol", ALICE)).status == 401
        r = await sign_in(client, " Alice ", ALICE)  # the name is not case or space sensitive
        assert r.status == 303 and await (await client.get("/")).text() == "the app"
        await client.close()

    run(go())


def test_the_session_names_the_person_and_dies_with_the_account(accounts, clock):
    async def go():
        auth = make(accounts, clock)
        client = await started(auth)
        await sign_in(client, "bob", BOB)
        assert (await client.get("/")).status == 200
        accounts.remove("bob")
        assert (await client.get("/")).status == 401
        await client.close()

    run(go())


def test_a_password_change_signs_that_person_out_but_not_the_others(accounts, clock):
    async def go():
        auth = make(accounts, clock)
        a, b = await started(auth), await started(auth)
        await sign_in(a, "alice", ALICE)
        await sign_in(b, "bob", BOB)
        clock.t += 5
        accounts.set_password("alice", "another password 1")
        assert (await a.get("/")).status == 401
        assert (await b.get("/")).status == 200
        await a.close()
        await b.close()

    run(go())


def test_the_old_single_owner_cookie_does_not_work_with_accounts(accounts, clock):
    old = weblogin._sign(KEY, {"u": "owner", "via": "password", "exp": clock.t + 100})

    async def go():
        client = await started(make(accounts, clock))
        assert (await client.get("/", cookies={weblogin.COOKIE: old})).status == 401
        await client.close()

    run(go())


def test_github_signs_in_as_the_person_it_is_linked_to(accounts, clock):
    async def exchange(client_id, secret, code, redirect):
        return "BobHub", 7

    auth = make(accounts, clock, exchange=exchange, github_client_id="id", github_secret="s",
                public_url="http://bb.test")

    async def go():
        client = await started(auth)
        assert "GitHub" in await (await client.get("/login")).text()
        r = await client.get("/login/github", allow_redirects=False)
        state = r.headers["Location"].split("state=")[1].split("&")[0]
        r = await client.get("/login/github/callback", params={"code": "c", "state": state},
                             allow_redirects=False)
        assert r.status == 303
        data = weblogin._verify(KEY, r.cookies[weblogin.COOKIE].value, clock.t)
        assert data["u"] == "bob" and data["via"] == "github"
        await client.close()

    run(go())


def test_github_refuses_someone_nobody_linked(accounts, clock):
    async def exchange(*a):
        return "stranger", 99

    auth = make(accounts, clock, exchange=exchange, github_client_id="id", github_secret="s",
                public_url="http://bb.test")

    async def go():
        client = await started(auth)
        r = await client.get("/login/github", allow_redirects=False)
        state = r.headers["Location"].split("state=")[1].split("&")[0]
        r = await client.get("/login/github/callback", params={"code": "c", "state": state})
        assert r.status == 403 and (await client.get("/")).status == 401
        await client.close()

    run(go())


# --- each person's app --------------------------------------------------------------------------

class FakeServer:
    """What textual-serve's Server gives us: a command and a websocket handler that starts it."""

    def __init__(self, command, host=None, port=None, title=None, public_url=None):
        self.command = command
        self.started = []
        self.gate = None

    async def handle_websocket(self, request):
        self.started.append(self.command)
        if self.gate:
            await self.gate.wait()
        return web.Response(text="ws")


def request_as(name, clock):
    token = weblogin._sign(KEY, {"u": name, "iat": clock.t, "exp": clock.t + 3600})
    return make_mocked_request("GET", "/ws", headers={"Cookie": f"{weblogin.COOKIE}={token}"})


def test_each_persons_app_starts_in_their_own_folder_without_the_servers_secrets(accounts, clock):
    async def go():
        server = weblogin.login_server(FakeServer, make(accounts, clock))("benchboss app")
        assert server.command == "benchboss app"  # outside a session: the plain command
        await server.handle_websocket(request_as("alice", clock))
        await server.handle_websocket(request_as("bob", clock))
        a, b = server.started
        assert f"BENCHBOSS_HOME={accounts.home('alice')}" in a and "benchboss app" in a
        assert f"BENCHBOSS_HOME={accounts.home('bob')}" in b and str(accounts.home("alice")) not in b
        for secret in weblogin.NOT_INHERITED:
            assert f"-u {secret}" in a
        assert "BENCHBOSS_NO_KEYRING=1" in a
        assert server.command == "benchboss app"

    run(go())


def test_open_tabs_are_capped_in_total_and_per_person(accounts, clock):
    async def go():
        server = weblogin.login_server(FakeServer, make(accounts, clock), max_sessions=3,
                                       per_user=2)("benchboss app")
        server.gate = asyncio.Event()
        tasks = [asyncio.create_task(server.handle_websocket(request_as(n, clock)))
                 for n in ("alice", "alice", "bob")]
        await asyncio.sleep(0)
        assert len(server.started) == 3
        refused = await server.handle_websocket(request_as("bob", clock))  # three are open
        assert refused.status == 503 and refused.headers["Retry-After"] == "30"
        server.gate.set()
        await asyncio.gather(*tasks)
        assert server._open == {}  # every tab counted out again

        server.gate = asyncio.Event()
        tasks = [asyncio.create_task(server.handle_websocket(request_as("alice", clock)))
                 for _ in range(2)]
        await asyncio.sleep(0)
        assert (await server.handle_websocket(request_as("alice", clock))).status == 503
        assert len(server.started) == 5
        server.gate.set()
        await asyncio.gather(*tasks)

    run(go())


# --- benchboss users and benchboss web --accounts -------------------------------------------------

def users(*argv) -> int:
    with pytest.raises(SystemExit) as e:
        cli.main(["users", *argv])
    return e.value.code


def test_users_add_shows_a_new_password_once_and_it_works(capsys):
    cli.main(["users", "add", "alice", "--github", "AliceHub"])
    out = capsys.readouterr().out
    password = next(line.split()[1] for line in out.splitlines() if line.strip().startswith("password"))
    acc = Accounts(config_mod.config_dir())
    assert acc.check("alice", password) == "alice" and acc.by_github("alicehub", 0) == "alice"
    cli.main(["users", "list"])
    assert "alice" in capsys.readouterr().out
    cli.main(["--json", "users", "list"])
    row = json.loads(capsys.readouterr().out)[0]
    assert row["name"] == "alice" and row["github"] == "alicehub" and row["cookies"] is False
    assert password not in json.dumps(row)


def test_users_add_can_take_the_password_from_a_file_and_print_nothing_secret(tmp_path, capsys):
    f = tmp_path / "pw"
    f.write_text(ALICE + "\n")
    cli.main(["users", "add", "alice", "--password-file", str(f)])
    out = capsys.readouterr().out
    assert ALICE not in out and "password" not in out.replace("Added alice.", "")
    assert Accounts(config_mod.config_dir()).check("alice", ALICE) == "alice"


def test_users_password_github_and_remove(tmp_path, capsys):
    cli.main(["users", "add", "alice", "--password-file", _pw(tmp_path)])
    cli.main(["users", "password", "alice", "--password-file", _pw(tmp_path, "second password 99")])
    acc = Accounts(config_mod.config_dir())
    assert acc.check("alice", "second password 99") == "alice"
    cli.main(["users", "github", "alice", "--github", "me"])
    assert acc.by_github("me", 0) == "alice"
    cli.main(["users", "github", "alice"])
    assert acc.by_github("me", 0) is None
    home = acc.home("alice")
    assert home.exists()
    cli.main(["--yes", "users", "remove", "alice"])
    assert not home.exists() and acc.everyone() == []
    assert "Removed alice" in capsys.readouterr().out


def test_users_remove_without_a_yes_changes_nothing(tmp_path):
    cli.main(["users", "add", "alice", "--password-file", _pw(tmp_path)])
    assert users("remove", "alice") == 10
    assert Accounts(config_mod.config_dir()).exists("alice")


def test_users_import_brings_the_cookies_and_keeps_the_password(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "credentials.json").write_text('{"espn_s2": "x", "SWID": "{y}"}')
    cli.main(["users", "import", "vale", "--from", str(old), "--password-file", _pw(tmp_path)])
    acc = Accounts(config_mod.config_dir())
    assert acc.check("vale", ALICE) == "vale"
    assert (acc.home("vale") / "credentials.json").exists()
    assert users("import", "bob") == 2  # no --from
    assert not acc.exists("bob")
    assert users("import", "bob", "--from", str(tmp_path / "missing")) == 1
    assert not acc.exists("bob")  # a failed copy leaves no half made account


def test_users_needs_a_name_and_refuses_a_bad_one(capsys):
    assert users("add") == 2
    assert users("add", "../x") == 1
    assert users("password", "nobody", "--password-file", "/nonexistent") == 1


def test_an_apps_credentials_stay_in_its_own_folder(accounts, monkeypatch):
    monkeypatch.setenv("BENCHBOSS_HOME", str(accounts.home("alice")))
    credentials.store("s2-alice", "{AAAA}")
    monkeypatch.setenv("BENCHBOSS_HOME", str(accounts.home("bob")))
    assert credentials.get() is None
    credentials.store("s2-bob", "{BBBB}")
    monkeypatch.setenv("BENCHBOSS_HOME", str(accounts.home("alice")))
    assert credentials.get() == ("s2-alice", "{AAAA}")


def test_no_keyring_is_obeyed(monkeypatch):
    monkeypatch.undo()  # the autouse fixture stubs _keyring; this test needs the real one
    monkeypatch.setenv("BENCHBOSS_NO_KEYRING", "1")
    assert credentials._keyring() is None


def _pw(tmp_path: Path, text: str = ALICE) -> str:
    f = tmp_path / f"pw-{len(text)}"
    f.write_text(text + "\n")
    return str(f)


@pytest.fixture
def serve(monkeypatch):
    calls = []

    class Server:
        def __init__(self, command, host, port, title, public_url):
            calls.append({"command": command})

        def serve(self):
            calls.append("served")

    monkeypatch.setitem(sys.modules, "textual_serve", types.ModuleType("textual_serve"))
    module = types.ModuleType("textual_serve.server")
    module.Server = Server
    monkeypatch.setitem(sys.modules, "textual_serve.server", module)
    return calls


def test_web_with_accounts_starts_and_says_so(serve, capsys):
    cli.main(["--demo", "web", "--accounts"])
    err = capsys.readouterr().err
    assert serve[-1] == "served" and "(accounts)" in err and "no accounts yet" in err
    assert (config_mod.config_dir() / "accounts.db").exists()
    assert (config_mod.config_dir() / "web-secret").exists()


def test_web_with_accounts_refuses_the_single_owner_options(serve, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--demo", "web", "--accounts", "--password-file", _pw(tmp_path)])
    assert e.value.code == 1 and "drop --password-file" in " ".join(capsys.readouterr().err.split())
    assert serve == []


def test_web_with_accounts_and_github_needs_all_its_parts(serve, monkeypatch, capsys):
    monkeypatch.setenv("BENCHBOSS_GITHUB_CLIENT_SECRET", "s")
    with pytest.raises(SystemExit) as e:
        cli.main(["--demo", "web", "--accounts", "--github-client-id", "id"])  # no --url
    assert e.value.code == 1 and "GitHub sign in needs" in capsys.readouterr().err
    cli.main(["--demo", "web", "--accounts", "--github-client-id", "id", "--url", "https://x.test"])
    assert serve[-1] == "served"


def test_session_limits_need_a_sign_in(serve, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--demo", "web", "--max-sessions", "4"])
    assert e.value.code == 1 and "need a sign in" in " ".join(capsys.readouterr().err.split())
    assert serve == []
    cli.main(["--demo", "web", "--accounts", "--max-sessions", "4", "--max-per-user", "2"])
    assert serve[-1] == "served"

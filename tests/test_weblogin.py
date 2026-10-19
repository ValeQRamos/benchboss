"""The web sign in: password form, GitHub, sessions, limits. No network: GitHub is faked."""

import asyncio
import re
import sys
import types
import urllib.parse

import pytest

pytest.importorskip("aiohttp")

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from benchboss import cli, weblogin  # noqa: E402
from benchboss.weblogin import Auth, AuthConfig, LoginError  # noqa: E402

KEY = b"k" * 32
PASSWORD = "correct horse battery"
HTML = {"Accept": "text/html"}


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def make(clock=None, exchange=None, **cfg):
    cfg.setdefault("password", PASSWORD)
    return Auth(AuthConfig(secret=KEY, **cfg), exchange=exchange or _no_exchange,
                now=clock or Clock(), fail_delay=0)


async def _no_exchange(*a):
    raise AssertionError("GitHub must not be called")


async def started(auth):
    app = web.Application()

    async def home(request):
        return web.Response(text="the app")

    app.router.add_get("/", home)
    app.router.add_get("/ws", home)
    auth.install(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def cookie(resp, name=weblogin.COOKIE):
    return resp.cookies.get(name)


async def sign_in(client, password=PASSWORD, user="owner", **headers):
    return await client.post("/login", data={"username": user, "password": password},
                             allow_redirects=False, headers=headers)


# --- who gets in ---------------------------------------------------------------------------------

def test_nothing_is_served_before_sign_in():
    async def go():
        client = await started(make())
        r = await client.get("/", headers=HTML, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/login"
        r = await client.get("/")  # not a page: the websocket, files
        assert r.status == 401 and "the app" not in await r.text()
        assert (await client.get("/ws")).status == 401
        await client.close()

    run(go())


def test_the_login_page_is_in_the_apps_style_and_loads_nothing_from_outside():
    async def go():
        client = await started(make(github_client_id="id", github_secret="s",
                                    github_users=frozenset({"me"}), public_url="http://x.test"))
        r = await client.get("/login")
        page = await r.text()
        assert r.status == 200 and r.content_type == "text/html"
        assert "benchboss" in page and "Sign in with GitHub" in page and 'type="password"' in page
        assert "#ee7d32" in page and "#141518" in page  # the app's accent and background
        assert "<rect" in page  # the pixel ball
        assert not re.search(r"(src|href)=[\"']https?://", page)
        assert "default-src 'none'" in r.headers["Content-Security-Policy"]
        assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Frame-Options"] == "DENY"
        await client.close()

    run(go())


def test_no_github_button_unless_it_is_set_up():
    async def go():
        client = await started(make())
        assert "GitHub" not in await (await client.get("/login")).text()
        assert (await client.get("/login/github")).status == 404
        await client.close()

    run(go())


def test_the_password_signs_you_in_and_the_session_lasts_until_logout():
    async def go():
        client = await started(make())
        r = await sign_in(client)
        assert r.status == 303 and r.headers["Location"] == "/"
        c = cookie(r)
        assert c["httponly"] and c["samesite"] == "Lax" and c["max-age"] == str(12 * 3600)
        assert await (await client.get("/")).text() == "the app"
        assert (await client.get("/login", allow_redirects=False)).status == 303  # already in
        r = await client.get("/logout", allow_redirects=False)
        assert r.status == 303 and r.headers["Location"] == "/login"
        assert (await client.get("/", headers=HTML, allow_redirects=False)).status == 302
        await client.close()

    run(go())


def test_a_wrong_password_or_user_is_refused_with_the_same_message():
    async def go():
        client = await started(make())
        for user, password in (("owner", "nope"), ("someone", PASSWORD), ("", "")):
            r = await sign_in(client, password, user)
            assert r.status == 401 and cookie(r) is None
            assert "Wrong username or password." in await r.text()
        assert (await client.get("/", headers=HTML, allow_redirects=False)).status == 302
        await client.close()

    run(go())


def test_five_wrong_passwords_lock_the_address_out_for_a_while():
    clock = Clock()

    async def go():
        client = await started(make(clock))
        for _ in range(weblogin.WRONG_LIMIT):
            assert (await sign_in(client, "nope")).status == 401
        r = await sign_in(client)  # the right one does not help now
        assert r.status == 429 and int(r.headers["Retry-After"]) > 0 and cookie(r) is None
        clock.t += weblogin.WRONG_WINDOW + 1
        assert (await sign_in(client)).status == 303
        await client.close()

    run(go())


def test_the_lockout_is_per_address_when_a_proxy_forwards_it():
    async def go():
        client = await started(make())
        for _ in range(weblogin.WRONG_LIMIT):
            await sign_in(client, "nope", **{"X-Forwarded-For": "203.0.113.5"})
        assert (await sign_in(client, **{"X-Forwarded-For": "203.0.113.5"})).status == 429
        assert (await sign_in(client, **{"X-Forwarded-For": "198.51.100.9"})).status == 303
        await client.close()

    run(go())


def test_a_session_that_expired_or_was_forged_is_not_accepted():
    clock = Clock()

    async def go():
        client = await started(make(clock, session_hours=1))
        await sign_in(client)
        assert (await client.get("/")).status == 200
        clock.t += 3601
        assert (await client.get("/")).status == 401  # expired
        fake = weblogin._sign(b"x" * 32, {"u": "owner", "exp": clock.t + 999})
        r = await client.get("/", cookies={weblogin.COOKIE: fake})
        assert r.status == 401  # signed with another key
        good = weblogin._sign(KEY, {"u": "owner", "exp": clock.t + 999})
        r = await client.get("/", cookies={weblogin.COOKIE: good[:-2] + "xx"})
        assert r.status == 401  # tampered
        r = await client.get("/", cookies={weblogin.COOKIE: good})
        assert r.status == 200
        await client.close()

    run(go())


def test_the_cookie_is_secure_when_the_public_address_is_https():
    async def go():
        client = await started(make(public_url="https://bb.example.test"))
        assert cookie(await sign_in(client))["secure"]
        await client.close()

    run(go())


def test_a_form_or_websocket_from_another_site_is_refused():
    async def go():
        client = await started(make(public_url="http://bb.example.test"))
        r = await sign_in(client, Origin="https://evil.example")
        assert r.status == 403 and cookie(r) is None
        await sign_in(client, Origin="http://bb.example.test")
        r = await client.get("/ws", headers={"Origin": "https://evil.example"})
        assert r.status == 403
        r = await client.get("/ws", headers={"Origin": "http://bb.example.test"})
        assert r.status == 200
        await client.close()

    run(go())


def test_a_browser_that_says_same_origin_gets_in_even_when_origin_is_null():
    """Browsers send `Origin: null` on same-origin forms under some referrer policies."""
    async def go():
        client = await started(make(public_url="https://bb.example.test"))
        r = await sign_in(client, **{"Sec-Fetch-Site": "same-origin", "Origin": "null"})
        assert r.status == 303 and cookie(r)
        await client.close()

    run(go())


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_the_browsers_own_cross_site_verdict_is_final(site):
    async def go():
        client = await started(make(public_url="http://bb.example.test"))
        r = await sign_in(client, **{"Sec-Fetch-Site": site, "Origin": "http://bb.example.test"})
        assert r.status == 403 and cookie(r) is None
        await client.close()

    run(go())


def test_an_origin_of_null_without_sec_fetch_site_is_refused():
    async def go():
        client = await started(make(public_url="http://bb.example.test"))
        assert (await sign_in(client, Origin="null")).status == 403
        await client.close()

    run(go())


def test_the_proxys_forwarded_host_counts_as_our_address():
    async def go():
        client = await started(make())  # no public address configured
        r = await sign_in(client, **{"Origin": "https://bb.example.test",
                                     "X-Forwarded-Host": "bb.example.test"})
        assert r.status == 303
        r = await sign_in(client, **{"Origin": "https://evil.example",
                                     "X-Forwarded-Host": "bb.example.test"})
        assert r.status == 403
        await client.close()

    run(go())


def test_the_login_page_does_not_ask_browsers_to_hide_the_origin():
    async def go():
        client = await started(make())
        r = await client.get("/login")
        assert r.headers["Referrer-Policy"] == "same-origin"
        await client.close()

    run(go())


# --- GitHub --------------------------------------------------------------------------------------

def github(users=("octocat",), **kw):
    seen = []

    async def exchange(client_id, secret, code, redirect):
        seen.append((client_id, secret, code, redirect))
        if code == "boom":
            raise LoginError("no token")
        return "Octocat", 583231

    auth = make(exchange=exchange, password=None, github_client_id="the-id", github_secret="the-secret",
                github_users=frozenset(users), public_url="http://bb.example.test", **kw)
    return auth, seen


async def start_github(client):
    r = await client.get("/login/github", allow_redirects=False)
    assert r.status == 303
    location = urllib.parse.urlparse(r.headers["Location"])
    return r, urllib.parse.parse_qs(location.query), location


def test_github_sign_in_lets_in_a_listed_user():
    auth, seen = github()

    async def go():
        client = await started(auth)
        r, query, location = await start_github(client)
        assert f"{location.scheme}://{location.netloc}{location.path}" == weblogin.GITHUB_AUTHORIZE
        assert query["client_id"] == ["the-id"]
        assert query["redirect_uri"] == ["http://bb.example.test/login/github/callback"]
        assert cookie(r, weblogin.STATE_COOKIE)["httponly"]
        r = await client.get("/login/github/callback",
                             params={"code": "abc", "state": query["state"][0]}, allow_redirects=False)
        assert r.status == 303 and r.headers["Location"] == "/" and cookie(r)
        assert await (await client.get("/")).text() == "the app"
        await client.close()

    run(go())
    assert seen == [("the-id", "the-secret", "abc", "http://bb.example.test/login/github/callback")]


def test_github_sign_in_also_takes_the_numeric_id_and_ignores_case():
    for users in (("583231",), ("OCTOCAT".lower(),)):
        auth, _ = github(users)

        async def go(auth=auth):
            client = await started(auth)
            _, query, _ = await start_github(client)
            r = await client.get("/login/github/callback",
                                 params={"code": "abc", "state": query["state"][0]},
                                 allow_redirects=False)
            assert r.status == 303
            await client.close()

        run(go())


def test_github_sign_in_refuses_a_user_who_is_not_listed():
    auth, _ = github(users=("someone-else",))

    async def go():
        client = await started(auth)
        _, query, _ = await start_github(client)
        r = await client.get("/login/github/callback",
                             params={"code": "abc", "state": query["state"][0]})
        assert r.status == 403 and "Octocat is not allowed here." in await r.text()
        assert (await client.get("/")).status == 401
        await client.close()

    run(go())


@pytest.mark.parametrize("params", [{"code": "abc", "state": "wrong"}, {"code": "abc"}, {"state": "x"}, {}])
def test_github_callback_needs_the_state_it_started_with(params):
    auth, seen = github()

    async def go():
        client = await started(auth)
        await start_github(client)
        r = await client.get("/login/github/callback", params=params)
        assert r.status == 400 and (await client.get("/")).status == 401
        await client.close()

    run(go())
    assert seen == []  # GitHub is not asked about a callback that does not match


def test_github_callback_without_starting_is_refused():
    auth, seen = github()

    async def go():
        client = await started(auth)
        r = await client.get("/login/github/callback", params={"code": "abc", "state": "x"})
        assert r.status == 400
        await client.close()

    run(go())
    assert seen == []


def test_github_trouble_shows_a_message_and_signs_nobody_in():
    auth, _ = github()

    async def go():
        client = await started(auth)
        _, query, _ = await start_github(client)
        r = await client.get("/login/github/callback",
                             params={"code": "boom", "state": query["state"][0]})
        assert r.status == 502 and (await client.get("/")).status == 401
        await client.close()

    run(go())


# --- the signing key and the command line --------------------------------------------------------

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="needs Unix file modes")


@POSIX
def test_the_signing_key_is_made_once_and_kept_private(tmp_path):
    path = tmp_path / "sub" / "web-secret"
    first = weblogin.load_secret(path)
    assert len(first) == 32 and weblogin.load_secret(path) == first
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_bytes(b"short")
    assert weblogin.load_secret(path) != b"short"  # too short to trust: replaced


@pytest.fixture
def serve(monkeypatch):
    calls = []

    class Server:
        def __init__(self, command, host, port, title, public_url):
            calls.append({"host": host, "url": public_url})

        def serve(self):
            calls.append("served")

    monkeypatch.setitem(sys.modules, "textual_serve", types.ModuleType("textual_serve"))
    module = types.ModuleType("textual_serve.server")
    module.Server = Server
    monkeypatch.setitem(sys.modules, "textual_serve.server", module)
    return calls


def code(*argv) -> int:
    with pytest.raises(SystemExit) as e:
        cli.main(list(argv))
    return e.value.code


def pw(tmp_path, text=PASSWORD, mode=0o600):
    f = tmp_path / "pw"
    f.write_text(text + "\n")
    f.chmod(mode)
    return str(f)


@POSIX
def test_web_starts_with_a_password_file(serve, tmp_path, capsys):
    cli.main(["--demo", "web", "--password-file", pw(tmp_path)])
    assert serve[-1] == "served"
    assert "(password)" in capsys.readouterr().err
    assert (cli.config_mod.config_dir() / "web-secret").stat().st_mode & 0o777 == 0o600


def test_web_without_a_sign_in_option_says_so(serve, capsys):
    cli.main(["--demo", "web"])
    assert "(no sign in)" in capsys.readouterr().err


@POSIX
def test_web_refuses_a_password_file_other_users_can_read(serve, tmp_path, capsys):
    assert code("--demo", "web", "--password-file", pw(tmp_path, mode=0o644)) == 1
    assert "chmod 600" in capsys.readouterr().err and serve == []


def test_web_refuses_a_short_or_missing_password(serve, tmp_path, capsys):
    assert code("--demo", "web", "--password-file", pw(tmp_path, "short")) == 1
    assert "12 characters" in capsys.readouterr().err
    assert code("--demo", "web", "--password-file", str(tmp_path / "missing")) == 1
    assert serve == []


@pytest.mark.parametrize("args, env", [
    (["--github-client-id", "id", "--github-users", "me"], {}),                  # no secret
    (["--github-users", "me", "--url", "https://x.test"], {"S": "s"}),            # no client id
    (["--github-client-id", "id", "--url", "https://x.test"], {"S": "s"}),        # nobody listed
    (["--github-client-id", "id", "--github-users", "me"], {"S": "s"}),           # no address
])
def test_web_github_needs_all_its_parts(serve, monkeypatch, capsys, args, env):
    if "S" in env:
        monkeypatch.setenv("BENCHBOSS_GITHUB_CLIENT_SECRET", env["S"])
    assert code("--demo", "web", *args) == 1
    assert "GitHub sign in needs" in capsys.readouterr().err and serve == []


def test_web_starts_with_github(serve, monkeypatch, capsys):
    monkeypatch.setenv("BENCHBOSS_GITHUB_CLIENT_SECRET", "s")
    cli.main(["--demo", "web", "--github-client-id", "id", "--github-users", "Me, other",
              "--url", "https://bb.example.test"])
    assert serve[-1] == "served" and "(GitHub)" in capsys.readouterr().err

"""Sign in for ``benchboss web``: a page in the app's style, a signed session cookie, GitHub
sign in for the users you list, and a limit on wrong passwords.

It sits in front of the whole web app (the page, the websocket and the files), so the app
itself never starts for someone who is not signed in. Needs aiohttp, which comes with the
``web`` extra (textual-serve).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from aiohttp import ClientError, ClientSession, ClientTimeout, web

from benchboss import __version__
from benchboss.ui import logo
from benchboss.ui.app import THEMES
from benchboss.ui.theme import DARK, LIGHT

COOKIE = "bb_session"
STATE_COOKIE = "bb_oauth"
PUBLIC = ("/login", "/login/github", "/login/github/callback", "/logout")
WRONG_LIMIT = 5      # wrong passwords from one address ...
WRONG_WINDOW = 600   # ... within this many seconds lock it out until the oldest one ages out
GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"

PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
}


class LoginError(Exception):
    """GitHub did not give an identity."""


@dataclass
class AuthConfig:
    secret: bytes                      # signs the session cookie
    password: str | None = None        # None: no password form
    user: str = "owner"
    github_client_id: str = ""
    github_secret: str = ""
    github_users: frozenset[str] = field(default_factory=frozenset)  # lowercase logins or ids
    public_url: str = ""               # where people type the address; needed for GitHub
    session_hours: float = 12

    @property
    def github(self) -> bool:
        return bool(self.github_client_id and self.github_secret and self.github_users)


Exchange = Callable[[str, str, str, str], Awaitable[tuple[str, int]]]


async def github_identity(client_id: str, client_secret: str, code: str,
                          redirect_uri: str) -> tuple[str, int]:
    """Trade the code GitHub sent back for who signed in: (login, numeric id)."""
    async with ClientSession(timeout=ClientTimeout(total=15)) as http:
        async with http.post(GITHUB_TOKEN, headers={"Accept": "application/json"},
                             data={"client_id": client_id, "client_secret": client_secret,
                                   "code": code, "redirect_uri": redirect_uri}) as r:
            token = (await r.json()).get("access_token")
        if not token:
            raise LoginError("GitHub gave no access token")
        async with http.get(GITHUB_USER, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "User-Agent": f"benchboss/{__version__}"}) as r:
            who = await r.json()
    return str(who["login"]), int(who["id"])


def load_secret(path: Path) -> bytes:
    """The signing key, made on first use (0600) so sessions survive a restart."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = b""
    if len(data) >= 32:
        return data
    data = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
    return data


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _sign(key: bytes, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_b64(hmac.new(key, body.encode(), hashlib.sha256).digest())}"


def _verify(key: bytes, token: str, now: float) -> dict | None:
    try:
        body, mac = token.split(".")
        if not hmac.compare_digest(mac, _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    if not isinstance(data, dict) or float(data.get("exp", 0)) < now:
        return None
    return data


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(a.encode()).digest(),
                               hashlib.sha256(b.encode()).digest())


def _client_ip(request: web.Request) -> str:
    peer = request.remote or ""
    forwarded = request.headers.get("X-Forwarded-For", "")
    # the proxy on this machine puts the real address first; anyone else's header is ignored
    return forwarded.split(",")[0].strip() if peer in ("127.0.0.1", "::1") and forwarded else peer


class Auth:
    def __init__(self, cfg: AuthConfig, exchange: Exchange = github_identity,
                 now: Callable[[], float] = time.time, fail_delay: float = 0.5) -> None:
        self.cfg = cfg
        self.exchange = exchange
        self.now = now
        self.fail_delay = fail_delay
        self._fails: dict[str, list[float]] = {}
        self._secure = cfg.public_url.startswith("https://")
        self._callback = cfg.public_url.rstrip("/") + "/login/github/callback"

    # --- wiring --------------------------------------------------------------------------------

    def install(self, app: web.Application) -> None:
        app.middlewares.append(self.middleware)
        app.router.add_get("/login", self.login_page)
        app.router.add_post("/login", self.login_submit)
        app.router.add_get("/login/github", self.github_start)
        app.router.add_get("/login/github/callback", self.github_callback)
        app.router.add_get("/logout", self.logout)

    @web.middleware
    async def middleware(self, request: web.Request, handler):
        if request.path in PUBLIC:
            return await handler(request)
        if self.session(request) is None:
            if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
                raise web.HTTPFound("/login")
            return web.Response(status=401, text="Sign in at /login\n")
        if request.path == "/ws" and not self._same_origin(request):
            return web.Response(status=403, text="Wrong origin\n")
        return await handler(request)

    def session(self, request: web.Request) -> dict | None:
        return _verify(self.cfg.secret, request.cookies.get(COOKIE, ""), self.now())

    def _same_origin(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin")
        if not origin:
            return True
        allowed = {request.host, urllib.parse.urlparse(self.cfg.public_url).netloc}
        return urllib.parse.urlparse(origin).netloc in allowed

    # --- pages ---------------------------------------------------------------------------------

    def _page(self, error: str = "", status: int = 200, headers: dict | None = None) -> web.Response:
        text = render_page(password=bool(self.cfg.password), github=self.cfg.github, error=error,
                           hours=self.cfg.session_hours)
        return web.Response(text=text, status=status, content_type="text/html",
                            headers={**PAGE_HEADERS, **(headers or {})})

    @staticmethod
    def _redirect(where: str) -> web.Response:
        return web.Response(status=303, headers={"Location": where, "Cache-Control": "no-store"})

    def _start(self, user: str, via: str) -> web.Response:
        hours = self.cfg.session_hours
        token = _sign(self.cfg.secret, {"u": user, "via": via, "exp": self.now() + hours * 3600})
        resp = self._redirect("/")
        resp.set_cookie(COOKIE, token, max_age=int(hours * 3600), httponly=True,
                        secure=self._secure, samesite="Lax", path="/")
        return resp

    async def login_page(self, request: web.Request) -> web.Response:
        if self.session(request):
            return self._redirect("/")
        return self._page()

    async def logout(self, request: web.Request) -> web.Response:
        resp = self._redirect("/login")
        resp.del_cookie(COOKIE, path="/")
        return resp

    # --- password ------------------------------------------------------------------------------

    def _wait(self, ip: str) -> int:
        """Seconds until this address may try again (0: it may try now)."""
        now = self.now()
        recent = [t for t in self._fails.get(ip, []) if now - t < WRONG_WINDOW]
        if recent:
            self._fails[ip] = recent
        else:
            self._fails.pop(ip, None)
        return int(WRONG_WINDOW - (now - recent[0])) + 1 if len(recent) >= WRONG_LIMIT else 0

    async def login_submit(self, request: web.Request) -> web.Response:
        if not self.cfg.password:
            raise web.HTTPNotFound()
        if not self._same_origin(request):
            return self._page("That form came from another site.", status=403)
        ip = _client_ip(request)
        wait = self._wait(ip)
        if wait:
            return self._page(f"Too many tries. Wait {wait // 60 + 1} minutes.", status=429,
                              headers={"Retry-After": str(wait)})
        form = await request.post()
        user_ok = _same(str(form.get("username", "")), self.cfg.user)
        pass_ok = _same(str(form.get("password", "")), self.cfg.password)
        if not (user_ok and pass_ok):
            self._fails.setdefault(ip, []).append(self.now())
            await asyncio.sleep(self.fail_delay)
            return self._page("Wrong username or password.", status=401)
        self._fails.pop(ip, None)
        return self._start(self.cfg.user, "password")

    # --- GitHub --------------------------------------------------------------------------------

    async def github_start(self, request: web.Request) -> web.Response:
        if not self.cfg.github:
            raise web.HTTPNotFound()
        state = secrets.token_urlsafe(24)
        query = urllib.parse.urlencode({"client_id": self.cfg.github_client_id, "state": state,
                                        "redirect_uri": self._callback, "allow_signup": "false"})
        resp = self._redirect(f"{GITHUB_AUTHORIZE}?{query}")
        resp.set_cookie(STATE_COOKIE, _sign(self.cfg.secret, {"state": state, "exp": self.now() + 600}),
                        max_age=600, httponly=True, secure=self._secure, samesite="Lax",
                        path="/login/github")
        return resp

    async def github_callback(self, request: web.Request) -> web.Response:
        if not self.cfg.github:
            raise web.HTTPNotFound()
        saved = _verify(self.cfg.secret, request.cookies.get(STATE_COOKIE, ""), self.now())
        state, code = request.query.get("state", ""), request.query.get("code", "")
        if not saved or not code or not hmac.compare_digest(str(saved.get("state")), state):
            return self._page("Sign in with GitHub did not complete. Try again.", status=400)
        try:
            login, uid = await self.exchange(self.cfg.github_client_id, self.cfg.github_secret,
                                             code, self._callback)
        except (LoginError, ClientError, TimeoutError, KeyError, ValueError):
            return self._page("GitHub did not answer. Try again.", status=502)
        if login.lower() not in self.cfg.github_users and str(uid) not in self.cfg.github_users:
            return self._page(f"{login} is not allowed here.", status=403)
        resp = self._start(login, "github")
        resp.del_cookie(STATE_COOKIE, path="/login/github")
        return resp


def login_server(server_class, auth: Auth):
    """A textual-serve Server with the sign in in front of everything it serves."""

    class LoginServer(server_class):
        async def _make_app(self):
            app = await super()._make_app()
            auth.install(app)
            return app

    return LoginServer


# --- the page -------------------------------------------------------------------------------------

def _ball() -> str:
    rects = []
    for y, row in enumerate(logo.BALL):
        x = 0
        while x < len(row):
            c, n = row[x], 1
            while x + n < len(row) and row[x + n] == c:
                n += 1
            if c != ".":
                rects.append(f'<rect class="{c}" x="{x}" y="{y}" width="{n}" height="1"/>')
            x += n
    return ('<svg viewBox="0 0 15 15" width="75" height="75" shape-rendering="crispEdges" '
            'aria-hidden="true">' + "".join(rects) + "</svg>")


def _vars(pal, theme) -> str:
    c = logo.colors(pal)
    return (f"--bg:{theme.background};--surface:{theme.surface};--text:{pal.text};--dim:{pal.dim};"
            f"--border:{pal.border};--accent:{pal.accent};--bad:{pal.bad};"
            f"--O:{c['O']};--H:{c['H']};--D:{c['D']};--S:{c['S']};--ink:{theme.background}")


CSS = f"""
:root{{{_vars(DARK, THEMES["dark"])}}}
@media (prefers-color-scheme: light){{:root{{{_vars(LIGHT, THEMES["light"])}}}}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--bg);color:var(--text);
font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}}
main{{width:min(92vw,360px);padding:28px;background:var(--surface);border:1px solid var(--border);
border-radius:6px}}
.brand{{display:flex;align-items:center;gap:16px;margin-bottom:22px}}
.brand svg .O{{fill:var(--O)}}.brand svg .H{{fill:var(--H)}}
.brand svg .D{{fill:var(--D)}}.brand svg .S{{fill:var(--S)}}
h1{{margin:0;font-size:20px;color:var(--accent)}}
.dim{{color:var(--dim)}}
label{{display:block;margin:14px 0 4px;color:var(--dim);font-size:12px}}
input{{width:100%;padding:10px 12px;background:var(--bg);color:var(--text);
border:1px solid var(--border);border-radius:4px;font:inherit}}
input:focus{{outline:none;border-color:var(--accent)}}
button,a.btn{{display:block;width:100%;margin-top:18px;padding:10px 12px;border-radius:4px;
font:inherit;font-weight:bold;text-align:center;text-decoration:none;cursor:pointer}}
button{{background:var(--accent);color:var(--ink);border:1px solid var(--accent)}}
a.btn{{background:transparent;color:var(--text);border:1px solid var(--border)}}
button:hover,a.btn:hover{{filter:brightness(1.12)}}
.or{{margin:18px 0 0;text-align:center;color:var(--dim);font-size:12px}}
.err{{margin:0 0 4px;color:var(--bad)}}
footer{{margin-top:22px;font-size:12px;color:var(--dim)}}
"""


def render_page(*, password: bool, github: bool, error: str = "", hours: float = 12) -> str:
    parts = [f'<div class="brand">{_ball()}<div><h1>benchboss</h1>'
             f'<div class="dim">{html.escape(__version__)}</div></div></div>']
    if error:
        parts.append(f'<p class="err" role="alert">{html.escape(error)}</p>')
    if password:
        parts.append(
            '<form method="post" action="/login">'
            '<label for="u">username</label>'
            '<input id="u" name="username" autocomplete="username" autocapitalize="none" '
            'autofocus required>'
            '<label for="p">password</label>'
            '<input id="p" name="password" type="password" autocomplete="current-password" required>'
            '<button type="submit">Sign in</button></form>')
    if github:
        if password:
            parts.append('<p class="or">or</p>')
        parts.append('<a class="btn" href="/login/github">Sign in with GitHub</a>')
    parts.append(f'<footer>Your session lasts {hours:g} hours.</footer>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex"><title>benchboss</title>'
            f'<style>{CSS}</style></head><body><main>{"".join(parts)}</main></body></html>')

"""Thin HTTP client for ESPN's unofficial Fantasy Basketball API.

Hosts (all under /apis/v3/games/fba):
  lm-api-reads          GET league and season data ("views")
  lm-api-writes         POST transactions (lineup moves, adds, drops, trades) and team
                        fields (the watch list)
  lm-api-communication  league chat and direct messages
Private leagues need the espn_s2 and SWID cookies of a member. Public NBA data (news,
injuries) comes from site.api.espn.com and needs no cookies.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.client import HTTPException  # not `import http.client`: http() below shadows it
from typing import Any

from benchboss import __version__
from benchboss.errors import AuthError, EspnError, NetworkError

READS = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
WRITES = "https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba"
COMM = "https://lm-api-communication.fantasy.espn.com/apis/v3/games/fba"
SITE = "https://site.api.espn.com/apis"
USER_AGENT = f"benchboss/{__version__} (+https://github.com/ValeQRamos/benchboss)"


def _ssl_context() -> ssl.SSLContext:
    # The system roots (and SSL_CERT_FILE / SSL_CERT_DIR) keep working behind corporate proxies;
    # certifi is added on top because python.org builds on macOS ship without root certificates.
    ctx = ssl.create_default_context()
    with contextlib.suppress(ImportError, OSError):
        import certifi

        ctx.load_verify_locations(certifi.where())
    return ctx


_SSL = _ssl_context()

# What a connection that breaks off after the request went out raises: urllib wraps none of
# these (RemoteDisconnected, IncompleteRead, ConnectionResetError, ssl.SSLError, a cut-off
# gzip body). HTTPError, URLError and TimeoutError are OSErrors too, so catch them first.
_DROPPED = (HTTPException, OSError, EOFError, zlib.error)


def http(url: str, *, params=None, headers=None, body=None, cookies=None, timeout=30) -> Any:
    """GET (or POST when ``body`` is given) and decode JSON. Raises BenchbossError subclasses."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    h = {"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": USER_AGENT}
    if cookies:
        h["Cookie"] = f"espn_s2={cookies[0]}; SWID={cookies[1]}"
    h.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    # once a write is on its way, a broken answer does not tell whether ESPN applied it
    unknown = "; it may or may not have gone through, check before retrying" if data else ""
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            status = r.status
            raw = _gunzip(r.read())
    except urllib.error.HTTPError as e:
        try:
            raw = _gunzip(e.read())
        except _DROPPED:
            raw = b""
        msg = _error_message(raw)
        if e.code == 401:
            raise AuthError("ESPN rejected the cookies (expired, or not a member of this league): "
                            "run `benchboss login` again") from e
        raise EspnError(e.code, msg) from e
    except urllib.error.URLError as e:
        raise NetworkError(f"could not reach ESPN ({e.reason})") from e
    except TimeoutError as e:
        raise NetworkError(f"ESPN did not answer in time{unknown}") from e
    except _DROPPED as e:
        raise NetworkError(f"the connection to ESPN dropped{unknown} ({type(e).__name__})") from e
    try:
        return json.loads(raw) if raw else {}
    except ValueError as e:
        raise EspnError(status, "the answer is not JSON (maintenance page or captive portal?)"
                        + unknown) from e


def _gunzip(raw: bytes) -> bytes:
    # ESPN gzips some bodies (always on errors) even when the client did not ask for it
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


def _error_message(raw: bytes) -> str:
    try:
        j = json.loads(raw)
    except ValueError:
        return raw[:300].decode(errors="replace") or "no details"
    msgs = j.get("messages") or [d.get("message", "") for d in j.get("details") or []]
    return "; ".join(m for m in msgs if m) or json.dumps(j)[:300]


class Client:
    """Bound to one league and season. ``cookies`` is (espn_s2, SWID)."""

    def __init__(self, league_id: int, season: int, cookies: tuple[str, str] | None):
        self.league_id = league_id
        self.season = season
        self.cookies = cookies

    @property
    def swid(self) -> str:
        if not self.cookies:
            raise AuthError("no ESPN cookies found: run `benchboss login`")
        return self.cookies[1]

    def _league_path(self) -> str:
        return f"/seasons/{self.season}/segments/0/leagues/{self.league_id}"

    # --- reads ---------------------------------------------------------------------------------

    def league(self, *views: str, scoring_period: int | None = None,
               fantasy_filter: dict | None = None, params: list | None = None) -> dict:
        p = [("view", v) for v in views]
        if scoring_period:
            p.append(("scoringPeriodId", scoring_period))
        p += params or []
        headers = {"x-fantasy-filter": json.dumps(fantasy_filter)} if fantasy_filter else None
        return http(READS + self._league_path(), params=p, headers=headers, cookies=self.cookies)

    def season_data(self, *views: str) -> dict:
        """Season-wide data shared by every league (pro team schedules, game settings)."""
        return http(f"{READS}/seasons/{self.season}", params=[("view", v) for v in views],
                    cookies=self.cookies)

    def players(self, fantasy_filter: dict, scoring_period: int | None = None) -> list:
        """kona_player_info: the player pool, filtered and sorted by the x-fantasy-filter."""
        data = self.league("kona_player_info", scoring_period=scoring_period,
                           fantasy_filter={"players": fantasy_filter})
        return data.get("players", [])

    # --- writes --------------------------------------------------------------------------------

    def transaction(self, body: dict) -> dict:
        return http(WRITES + self._league_path() + "/transactions/", body=body,
                    cookies=self.cookies)

    def update_team(self, team_id: int, body: dict) -> dict:
        """Change fields of a team, for example {"watchList": [player ids]} (docs/api/04,
        section 13). Only the fields in ``body`` change (the web app sends one at a time).
        What ESPN answers is unverified; callers read the team from it when it is one."""
        return http(WRITES + self._league_path() + f"/teams/{team_id}", body=body,
                    cookies=self.cookies)

    # --- chat ----------------------------------------------------------------------------------

    def comm(self, path: str = "", *, params=None, fantasy_filter=None, body=None) -> Any:
        p = list(params or []) + [("platform", "chat")]
        if body is not None:
            p.append(("source", self.swid))
        headers = {"X-Fantasy-Filter": json.dumps(fantasy_filter)} if fantasy_filter else None
        return http(COMM + self._league_path() + "/communication/" + path, params=p,
                    headers=headers, body=body, cookies=self.cookies)

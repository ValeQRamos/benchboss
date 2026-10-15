"""Thin HTTP client for ESPN's unofficial Fantasy Basketball API.

Hosts (all under /apis/v3/games/fba):
  lm-api-reads          GET league and season data ("views")
  lm-api-writes         POST transactions (lineup moves, adds, drops, trades)
  lm-api-communication  league chat and direct messages
Private leagues need the espn_s2 and SWID cookies of a member. Public NBA data (news,
injuries) comes from site.api.espn.com and needs no cookies.
"""

from __future__ import annotations

import gzip
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from benchboss import __version__
from benchboss.errors import AuthError, EspnError, NetworkError

READS = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
WRITES = "https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba"
COMM = "https://lm-api-communication.fantasy.espn.com/apis/v3/games/fba"
SITE = "https://site.api.espn.com/apis"
USER_AGENT = f"benchboss/{__version__} (+https://github.com/ValeQRamos/benchboss)"


def _ssl_context() -> ssl.SSLContext:
    # python.org builds of Python on macOS ship without root certificates: use certifi.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()


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
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            raw = _gunzip(r.read())
    except urllib.error.HTTPError as e:
        raw = _gunzip(e.read())
        msg = _error_message(raw)
        if e.code == 401:
            raise AuthError("ESPN rejected the cookies (expired, or not a member of this league): "
                            "run `benchboss login` again") from e
        raise EspnError(e.code, msg) from e
    except urllib.error.URLError as e:
        raise NetworkError(f"could not reach ESPN ({e.reason})") from e
    except TimeoutError as e:
        raise NetworkError("ESPN did not answer in time") from e
    return json.loads(raw) if raw else {}


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

    # --- chat ----------------------------------------------------------------------------------

    def comm(self, path: str = "", *, params=None, fantasy_filter=None, body=None) -> Any:
        p = list(params or []) + [("platform", "chat")]
        if body is not None:
            p.append(("source", self.swid))
        headers = {"X-Fantasy-Filter": json.dumps(fantasy_filter)} if fantasy_filter else None
        return http(COMM + self._league_path() + "/communication/" + path, params=p,
                    headers=headers, body=body, cookies=self.cookies)


def player_news(player_id: int, limit: int = 10) -> list[dict]:
    """Public fantasy news feed for one player (Rotowire blurbs and ESPN media). No cookies."""
    url = f"{SITE}/fantasy/v2/games/fba/news/players"
    data = http(url, params=[("playerId", player_id), ("limit", limit)])
    return data.get("feed", [])

"""Player news ("spins") from ESPN's public fantasy feed, plus an optional AI digest.

The feed mixes RotoWire blurbs (a one-line ``headline`` plus the analysis ESPN labels
"Spin") with ESPN stories and video. It is public, needs no cookies and accepts many
players per request (repeat ``playerId``).

Every news download goes through ``fetch`` and, below it, ``_get_feed``: the only line that
talks to the network. Another way to reach the feed (a different host, headers or a proxy
for servers where the public API does not answer) replaces ``_get_feed`` and nothing else.
Tests fake the feed by patching ``_get_feed``.

The AI digest is optional: with ``ANTHROPIC_API_KEY`` set, Claude searches the web for the
latest on your players and writes a short fantasy-focused briefing.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from benchboss.errors import BenchbossError
from benchboss.espn.client import _DROPPED, _SSL, SITE, http
from benchboss.espn.models import Player

FEED = f"{SITE}/fantasy/v2/games/fba/news/players"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"


@dataclass
class NewsItem:
    id: int
    published: dt.datetime
    headline: str
    spin: str = ""
    source: str = "ESPN"           # RotoWire or ESPN
    kind: str = ""                 # Rotowire, Story, Media
    link: str = ""
    player_ids: set[int] = field(default_factory=set)

    def to_dict(self, names: dict[int, str] | None = None) -> dict:
        return {"published": self.published.isoformat(), "source": self.source,
                "kind": self.kind, "headline": self.headline, "spin": self.spin or None,
                "link": self.link or None,
                "players": [(names or {}).get(p, p) for p in sorted(self.player_ids)]}


def _parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


BATCH = 50          # player ids per request: the URL length caps one at about 100
LATEST = 10         # items a named player shows when no window is asked for
LATEST_LIMIT = 200  # the most items one latest() request asks the feed for
MAX_PAGES = 10      # pages one batch may take to cover a window of days (2,000 items at 200)


def _get_feed(params: list[tuple[str, object]]) -> dict:
    """One request to the news feed: ``params`` are the query (playerId repeated, days,
    limit, offset). The seam for another transport; keep its signature and return the feed
    JSON."""
    return http(FEED, params=params)


def _parse_item(raw: dict) -> NewsItem:
    """One feed item. RotoWire's analysis (``story``) becomes the spin."""
    kind = raw.get("type", "")
    rotowire = kind == "Rotowire"
    web = ((raw.get("links") or {}).get("web") or {}).get("href", "")
    return NewsItem(
        id=raw.get("id"), published=_parse_time(raw.get("published") or "1970-01-01T00:00:00Z"),
        headline=(raw.get("headline") or raw.get("title") or "").strip(),
        spin=(raw.get("story") or "").strip() if rotowire else "",
        source="RotoWire" if rotowire else "ESPN", kind=kind, link=web,
        player_ids={raw.get("playerId")})


def fetch(player_ids: list[int], days: int | None = 5, limit: int = 200,
          include_media: bool = False, *, offset: int = 0) -> list[NewsItem]:
    """News on these players, newest first, deduplicated across players.

    ``days``: only the last ``days`` days (counted back from now); None asks for the newest
    items whatever their date. ``limit`` and ``offset`` page the feed (per request of
    ``BATCH`` players). Video items (Media) are left out unless ``include_media``.

    The feed sends the newest ``limit`` items and video counts toward that, so a window of
    days (with no ``offset`` given) keeps asking for the next page until one comes back
    short or reaches past the window, up to MAX_PAGES pages per batch: a long window is
    never cut at the first ``limit`` items. ``days=None`` or an ``offset`` is one request
    per batch: the caller pages."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
              if days is not None else None)
    items: dict[int, NewsItem] = {}
    for i in range(0, len(player_ids), BATCH):
        chunk = player_ids[i:i + BATCH]
        at = offset
        for _ in range(MAX_PAGES if cutoff is not None and not offset else 1):
            params: list[tuple[str, object]] = [("playerId", pid) for pid in chunk]
            if days is not None:
                params.append(("days", days))
            params.append(("limit", limit))
            if at:
                params.append(("offset", at))
            page = _get_feed(params).get("feed") or []
            for raw in page:
                if raw.get("type") == "Media" and not include_media:
                    continue
                nid = raw.get("id")
                if nid in items:  # one item about several players comes once for each of them
                    items[nid].player_ids.add(raw.get("playerId"))
                    continue
                items[nid] = _parse_item(raw)
            if not page or len(page) < limit or cutoff is None or _oldest(page) < cutoff:
                break
            at += limit
    found = sorted(items.values(), key=lambda x: x.published, reverse=True)
    if cutoff is None:
        return found
    return [x for x in found if x.published >= cutoff]


def _oldest(page: list[dict]) -> dt.datetime:
    """The oldest ``published`` in one page of the feed (Media included)."""
    return min(_parse_time(raw.get("published") or "1970-01-01T00:00:00Z") for raw in page)


def latest(player_id: int, n: int = LATEST, offset: int = 0) -> list[NewsItem]:
    """The newest ``n`` items on one player whatever their date, after skipping the newest
    ``offset`` (so ``offset=10`` is the second page of ten).

    The feed counts video items too, and those are left out, so one request asks for about
    twice what it keeps; a player whose news is mostly video gets a second, bigger request
    (up to ``LATEST_LIMIT`` items)."""
    want = offset + n
    limit = min(LATEST_LIMIT, 2 * want + 10)
    while True:
        got = fetch([player_id], days=None, limit=limit, include_media=True)
        items = [x for x in got if x.kind != "Media"]
        if len(items) >= want or len(got) < limit or limit >= LATEST_LIMIT:
            return items[offset:want]
        limit = min(LATEST_LIMIT, 2 * limit)


# --- optional AI digest ---------------------------------------------------------------------------

def ai_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def ai_digest(players: list[Player], days: int = 5, model: str | None = None,
              timeout: int = 120) -> str:
    """Ask Claude (with web search) for a fantasy briefing on these players."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise BenchbossError("set ANTHROPIC_API_KEY to use the AI digest "
                             "(or ask GitHub Copilot for news on your players)")
    roster = "\n".join(f"- {p.name} ({p.pro_team}, {p.positions})" for p in players)
    prompt = (
        f"You are a fantasy basketball analyst. Search the web for news from the last {days} "
        f"days about each player below: injuries, minutes, role changes, trades, rest days, "
        f"and performances. Then write a briefing for an ESPN head-to-head points league "
        f"manager: one short line per player with the news and what it means for fantasy "
        f"(start, sit, hold, sell, watch), most important first. Skip players with no news "
        f"and say so in one final line. Plain text, no markdown tables.\n\nPlayers:\n{roster}")
    body = {"model": model or os.environ.get("BENCHBOSS_AI_MODEL", DEFAULT_MODEL),
            "max_tokens": 1500,
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(
        ANTHROPIC_URL, data=json.dumps(body).encode(), method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode(errors="replace")
        raise BenchbossError(f"Anthropic API {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise BenchbossError(f"could not reach the Anthropic API ({e.reason})") from e
    except TimeoutError as e:
        raise BenchbossError("the Anthropic API did not answer in time") from e
    except (*_DROPPED, ValueError) as e:
        raise BenchbossError("the answer from the Anthropic API was cut off or garbled "
                             f"({type(e).__name__})") from e
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return text.strip() or "(no answer)"

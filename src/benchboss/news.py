"""Player news ("spins") from ESPN's public fantasy feed, plus an optional AI digest.

The feed mixes RotoWire blurbs (a one-line ``headline`` plus the analysis ESPN labels
"Spin") with ESPN stories and video. It is public, needs no cookies and accepts many
players per request (repeat ``playerId``).

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
from benchboss.espn.client import _SSL, SITE, http
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


def fetch(player_ids: list[int], days: int = 5, limit: int = 200,
          include_media: bool = False) -> list[NewsItem]:
    """Newest first, deduplicated across players."""
    items: dict[int, NewsItem] = {}
    for i in range(0, len(player_ids), 50):  # URL length caps a request at about 100 ids
        chunk = player_ids[i:i + 50]
        params = [("playerId", pid) for pid in chunk] + [("days", days), ("limit", limit)]
        for raw in http(FEED, params=params).get("feed", []):
            kind = raw.get("type", "")
            if kind == "Media" and not include_media:
                continue
            nid = raw.get("id")
            if nid in items:
                items[nid].player_ids.add(raw.get("playerId"))
                continue
            rotowire = kind == "Rotowire"
            web = ((raw.get("links") or {}).get("web") or {}).get("href", "")
            items[nid] = NewsItem(
                id=nid, published=_parse_time(raw.get("published", "1970-01-01T00:00:00Z")),
                headline=(raw.get("headline") or raw.get("title") or "").strip(),
                spin=(raw.get("story") or "").strip() if rotowire else "",
                source="RotoWire" if rotowire else "ESPN", kind=kind, link=web,
                player_ids={raw.get("playerId")})
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days + 1)
    return sorted((x for x in items.values() if x.published >= cutoff),
                  key=lambda x: x.published, reverse=True)


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
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return text.strip() or "(no answer)"

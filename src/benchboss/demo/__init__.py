"""Demo mode: a fictional league frozen on a Wednesday of matchup week 3.

Real NBA players, projections and schedule; invented league, team and manager names and
synthetic scores. Nothing is ever sent to ESPN. Used by ``--demo``, the tests and the README
screenshots.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
from functools import cached_property
from importlib import resources

from benchboss import config as config_mod
from benchboss.core.calendar import SeasonCalendar
from benchboss.errors import BenchbossError
from benchboss.espn.constants import SLOT_ID
from benchboss.news import NewsItem
from benchboss.service import Session


def load() -> dict:
    raw = resources.files(__package__).joinpath("data.json.gz").read_bytes()
    return json.loads(gzip.decompress(raw))


DEMO_CHAT = "demo-league-chat"


class DemoClient:
    """Answers like ``espn.client.Client`` from the bundled dataset; refuses every write."""

    def __init__(self, data: dict):
        self.data = data
        self.league_id = data["league"]["id"]
        self.season = data["league"]["seasonId"]
        self.cookies = ("demo", data["swid"])

    @property
    def swid(self) -> str:
        return self.data["swid"]

    def league(self, *views, scoring_period=None, fantasy_filter=None, params=None) -> dict:
        if "kona_player_info" in views:
            return {"players": self.players((fantasy_filter or {}).get("players", {}))}
        return self.data["league"]

    def season_data(self, *views) -> dict:
        return self.data["schedule"]

    def players(self, flt: dict, scoring_period=None) -> list:
        if flt.get("limit") and not any(k.startswith("sort") for k in flt):
            # ESPN answers 400 FILTER_LIMIT_MISSING_SORT; fail the same way so tests catch it
            raise BenchbossError("ESPN 400: Filter: Limit request must be accompanied by a sort")
        pool = self.data["trending"] if "sortPercChanged" in flt else self.data["free_agents"]
        ids = (flt.get("filterIds") or {}).get("value")
        if ids:
            everyone = pool + [e["playerPoolEntry"] for t in self.data["league"]["teams"]
                               for e in t["roster"]["entries"]]
            return [x for x in everyone if x["id"] in ids]
        name = ((flt.get("filterName") or {}).get("value") or "").lower()
        slots = (flt.get("filterSlotIds") or {}).get("value")
        out = [x for x in pool
               if (not name or name in x["player"]["fullName"].lower())
               and (not slots or set(slots) & set(x["player"].get("eligibleSlots") or []))]
        return out[: flt.get("limit") or 50]

    def transaction(self, body: dict) -> dict:
        raise BenchbossError("demo mode: nothing is sent to ESPN")

    def comm(self, path="", *, params=None, fantasy_filter=None, body=None):
        if body is not None:
            raise BenchbossError("demo mode: nothing is sent to ESPN")
        if path == f"topics/{DEMO_CHAT}":
            newest = sorted(self.chat(), key=lambda m: -m["date"])
            return {"messages": newest[: (fantasy_filter or {}).get("limit") or 15]}
        return {"topics": [{"id": DEMO_CHAT, "type": "CHAT_ALL_MEMBERS", "unreadMessageCount": 0}]}

    def chat(self) -> list[dict]:
        """A few league chat messages from the fictional managers, plus a waiver report."""
        lg = self.data["league"]
        noon = dt.datetime.combine(dt.date.fromisoformat(self.data["today"]), dt.time(12),
                                   tzinfo=dt.timezone(dt.timedelta(hours=-5)))
        team = lg["teams"][4]
        claimed = team["roster"]["entries"][-1]["playerId"]
        dropped = self.data["free_agents"][5]["id"]

        def at(hours: float) -> int:
            return int((noon - dt.timedelta(hours=hours)).timestamp() * 1000)

        return [
            {"id": "demo-1", "author": lg["members"][1]["id"], "messageTypeId": 0, "date": at(30),
             "content": "Anyone selling a center? Taking offers all week."},
            {"id": "demo-2", "author": "LM", "messageTypeId": 273, "date": at(8),
             "attributes": {"team1": str(team["id"]), "team1addP1": str(claimed),
                            "team1dropP1": str(dropped)}},
            {"id": "demo-3", "author": lg["members"][2]["id"], "messageTypeId": 0, "date": at(5),
             "content": "Waivers cleared. Good luck this week, everyone."},
        ]


_NEWS = [
    (0, 3, "posted a season-high in assists in Tuesday's win and looked fully healthy.",
     "His usage keeps climbing with the second unit struggling. Locked-in starter."),
    (1, 20, "is listed as questionable for Thursday with left ankle soreness.",
     "He went through shootaround Wednesday. Monitor before lineups lock."),
    (4, 30, "grabbed 15 rebounds and blocked four shots in 31 minutes on Monday.",
     "The frontcourt minutes are his alone while the backup center is out."),
    (6, 45, "will move into the starting lineup this week, his coach said.",
     "A role bump like this is worth acting on in deeper formats."),
]


class DemoSession(Session):
    def __init__(self, cfg: config_mod.Config | None = None):
        data = load()
        today = dt.date.fromisoformat(data["today"])
        cfg = cfg or config_mod.Config()
        cfg = config_mod.Config(league_id=data["league"]["id"], team_id=data["my_team_id"],
                                season=data["league"]["seasonId"], theme=cfg.theme)
        eastern = dt.timezone(dt.timedelta(hours=-5))
        super().__init__(cfg, DemoClient(data), today=today,
                         now=dt.datetime.combine(today, dt.time(15, 30), tzinfo=eastern))
        self.data = data

    @property
    def demo(self) -> bool:
        return True

    @cached_property
    def calendar(self) -> SeasonCalendar:
        return SeasonCalendar.from_raw(self.data["schedule"])

    def roster_on(self, period: int):
        return self.league().me.roster

    def news(self, player_ids, days=5):
        roster = [s.player for s in self.league().me.roster]
        now = dt.datetime.combine(self.today, dt.time(14, 0), tzinfo=dt.timezone.utc)
        items = []
        for i, (idx, hours, headline, spin) in enumerate(_NEWS):
            if idx < len(roster) and roster[idx].id in player_ids:
                last = roster[idx].name.split()[-1]
                items.append(NewsItem(i, now - dt.timedelta(hours=hours), f"{last} {headline}",
                                      spin, "Demo", "Rotowire", "", {roster[idx].id}))
        return items


def demo_session(cfg: config_mod.Config | None = None) -> DemoSession:
    return DemoSession(cfg)


__all__ = ["DemoSession", "demo_session", "load", "SLOT_ID"]

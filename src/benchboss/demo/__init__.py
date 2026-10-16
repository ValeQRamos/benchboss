"""Demo mode: a fictional league frozen on a Wednesday of matchup week 3.

Real NBA players, projections and schedule; invented league, team and manager names and
synthetic scores. Nothing is ever sent to ESPN. Used by ``--demo``, the tests and the README
screenshots. The dataset comes from tools/make_demo.py and tools/enrich_demo.py.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import unicodedata
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
REFUSED = "demo mode: nothing is sent to ESPN"
STATUSES = ("FREEAGENT", "WAIVERS", "ONTEAM")


def _fold(s: str) -> str:
    """Lowercase without accents, so "jokic" finds "Jokić" as it does on ESPN."""
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).lower()


def _name_matches(player: dict, query: str) -> bool:
    """ESPN's ``filterName``: the start of the first, last or full name, case and accent
    insensitive ("jok", "nik", "nikola jok", "Jokić"); never the middle of a name ("okic"
    finds nobody, "alexander" finds Alexander-Walker but not Gilgeous-Alexander)."""
    return any(_fold(player.get(k) or "").startswith(query)
               for k in ("firstName", "lastName", "fullName"))


def _values(flt: dict, key: str) -> list | None:
    """``{"value": [...]}`` or ``{"value": x}`` as a list; None when the filter is absent."""
    f = flt.get(key)
    v = f.get("value") if isinstance(f, dict) else None
    if v is None:
        return None
    return list(v) if isinstance(v, (list, tuple, set)) else [v]


def _last_name(name: str) -> str:
    parts = name.split()
    while len(parts) > 1 and parts[-1].rstrip(".") in ("Jr", "Sr", "II", "III", "IV"):
        parts.pop()
    return parts[-1]


def _sort_value(name: str, spec: dict):
    """What one kona_player_info sort orders by; None for a sort the demo does not know."""
    if name == "sortPercOwned":
        return lambda x: (x["player"].get("ownership") or {}).get("percentOwned")
    if name == "sortPercChanged":
        return lambda x: (x["player"].get("ownership") or {}).get("percentChange")
    if name in ("sortAppliedStatAverage", "sortAppliedStatTotal"):
        field = "appliedAverage" if name == "sortAppliedStatAverage" else "appliedTotal"
        split = str(spec.get("value") or "")
        return lambda x: next((s.get(field) for s in x["player"].get("stats") or []
                               if s.get("id") == split), None)
    return None


class DemoClient:
    """Answers like ``espn.client.Client`` from the bundled dataset; refuses every write
    except the demo user's own watch list, which changes in memory only."""

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

    def pool(self) -> list[dict]:
        """Every player once, like ESPN's whole league pool: rostered players (``status``
        ONTEAM, with ``onTeamId``), then free agents."""
        seen, out = set(), []
        rostered = [e["playerPoolEntry"] for t in self.data["league"]["teams"]
                    for e in t["roster"]["entries"]]
        for x in rostered + self.data["free_agents"] + self.data["trending"]:
            if x["id"] not in seen:
                seen.add(x["id"])
                out.append(x)
        return out

    def players(self, flt: dict, scoring_period=None) -> list:
        """kona_player_info. Filters: ``filterStatus`` (any of FREEAGENT, WAIVERS, ONTEAM;
        absent = everyone), ``filterIds``, ``filterName`` (the start of a first, last or full
        name), ``filterSlotIds``. Sorts by ``sortPriority``: ``sortPercOwned``,
        ``sortPercChanged``, ``sortAppliedStatAverage`` and ``sortAppliedStatTotal`` with
        ``value`` a split id such as "002027" (descending unless ``sortAsc``; players without
        the value go last). ``limit`` (0 = all) and ``offset`` page the result."""
        sorts = sorted(((k, v if isinstance(v, dict) else {}) for k, v in flt.items()
                        if k.startswith("sort")), key=lambda kv: kv[1].get("sortPriority", 99))
        if flt.get("limit") and not sorts:
            # ESPN answers 400 FILTER_LIMIT_MISSING_SORT; fail the same way so tests catch it
            raise BenchbossError("ESPN 400: Filter: Limit request must be accompanied by a sort")
        statuses = _values(flt, "filterStatus")
        ids = _values(flt, "filterIds")
        ids = None if ids is None else set(ids)
        name = _fold(str((flt.get("filterName") or {}).get("value") or ""))
        slots = set(_values(flt, "filterSlotIds") or ())
        out = [x for x in self.pool()
               if (statuses is None or x.get("status") in statuses)
               and (ids is None or x["id"] in ids)
               and (not name or _name_matches(x["player"], name))
               and (not slots or slots & set(x["player"].get("eligibleSlots") or []))]
        for sort, spec in reversed(sorts):  # stable sorts, the main one (priority 1) last
            value = _sort_value(sort, spec)
            if value is None:
                continue
            have = [x for x in out if value(x) is not None]
            have.sort(key=value, reverse=not spec.get("sortAsc"))
            out = have + [x for x in out if value(x) is None]
        limit = flt.get("limit") or 0
        if limit > 0:
            offset = max(0, flt.get("offset") or 0)
            out = out[offset:offset + limit]
        return out

    def transaction(self, body: dict) -> dict:
        raise BenchbossError(REFUSED)

    def update_team(self, team_id: int, body: dict) -> dict:
        """ESPN's POST .../teams/{teamId}. Only ``{"watchList": [player ids]}`` for the demo
        user's team is accepted; it replaces the list in memory and returns the team."""
        me = self.data["my_team_id"]
        ids = body.get("watchList") if isinstance(body, dict) and set(body) == {"watchList"} else None
        if (team_id != me or not isinstance(ids, list)
                or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
            raise BenchbossError(REFUSED)
        team = next(t for t in self.data["league"]["teams"] if t["id"] == me)
        team["watchList"] = list(dict.fromkeys(ids))
        return team

    def comm(self, path="", *, params=None, fantasy_filter=None, body=None):
        if body is not None:
            raise BenchbossError(REFUSED)
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


# (roster index, hours before 2 pm UTC on the demo day, headline after the last name, spin)
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
# the same for players on the demo watch list (index into the dataset's watchList)
_WATCH_NEWS = [
    (1, 10, "is seeing more minutes with the second unit and has looked comfortable running "
            "the offense.",
     "His ownership is climbing for a reason. Worth a speculative add in deeper leagues "
     "while the role lasts."),
    (2, 16, "practiced in full Tuesday and is expected to be available Wednesday.",
     "He has been efficient in limited minutes. A fine streamer if you need games this week."),
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
        me = next(t for t in data["league"]["teams"] if t["id"] == data["my_team_id"])
        self._watched = list(me.get("watchList") or [])  # as shipped, before any edit
        # the news seen stays in memory: the frozen demo shows the same alerts on every run
        # and never writes to your config folder
        self.seen_news = {}

    @property
    def demo(self) -> bool:
        return True

    @cached_property
    def calendar(self) -> SeasonCalendar:
        return SeasonCalendar.from_raw(self.data["schedule"])

    def roster_on(self, period: int):
        """The demo's lineup on a day. Days already played get the lineup a manager who set
        it every morning would have had (whoever had a game played), so the week shows a few
        bench games rather than one lineup copied to every day. Today and later carry today's
        lineup, as ESPN does when nothing is saved for a day."""
        from benchboss.core.lineup import best_lineup, day_value
        from benchboss.espn.constants import BENCH, IR
        from benchboss.espn.models import RosterSpot

        lg = self.league()
        roster = lg.me.roster
        if period >= self.today_period:
            return roster
        pool = [s for s in roster if s.slot_id != IR]
        values = [day_value(s.player, period, self.calendar) for s in pool]
        assign = best_lineup(pool, lg.slot_counts, values)
        return ([RosterSpot(s.player, assign.get(i, BENCH)) for i, s in enumerate(pool)]
                + [s for s in roster if s.slot_id == IR])

    def news(self, player_ids, days=5):
        """RotoWire-style items for 4 roster players and 2 watch-list players, newest first,
        only for the ids asked for and only from the last ``days`` days of the demo clock."""
        roster = [(s.player.id, s.player.name) for s in self.league().me.roster]
        names = {x["id"]: x["player"]["fullName"]
                 for x in self.data["free_agents"] + self.data["trending"]}
        watched = [(pid, names[pid]) for pid in self._watched if pid in names]
        now = dt.datetime.combine(self.today, dt.time(14, 0), tzinfo=dt.timezone.utc)
        cutoff = self.now - dt.timedelta(days=days)
        items = []
        for i, (who, (idx, hours, headline, spin)) in enumerate(
                [(roster, n) for n in _NEWS] + [(watched, n) for n in _WATCH_NEWS]):
            if idx >= len(who) or who[idx][0] not in player_ids:
                continue
            pid, name = who[idx]
            published = now - dt.timedelta(hours=hours)
            if published >= cutoff:
                items.append(NewsItem(i, published, f"{_last_name(name)} {headline}", spin,
                                      "Demo", "Rotowire", "", {pid}))
        return sorted(items, key=lambda x: x.published, reverse=True)


def demo_session(cfg: config_mod.Config | None = None) -> DemoSession:
    return DemoSession(cfg)


__all__ = ["DemoClient", "DemoSession", "demo_session", "load", "SLOT_ID"]

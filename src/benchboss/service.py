"""High-level facade used by the CLI and the TUI.

A ``Session`` knows the league, caches what ESPN sends (in memory, and on disk for the NBA
schedule) and exposes every feature as a method that returns plain Python objects.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from benchboss import config as config_mod
from benchboss import credentials
from benchboss.core import activity as activity_mod
from benchboss.core import trades as trades_mod
from benchboss.core import trash as trash_mod
from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import DayPlan, plan_day
from benchboss.core.projection import MatchupOutlook, matchup_outlook
from benchboss.errors import BenchbossError
from benchboss.espn.client import Client
from benchboss.espn.constants import SLOT_ID, SPLITS, split_ids
from benchboss.espn.models import League, Player, parse_league, parse_player, parse_team

# mStandings adds ESPN's playoff simulation (currentSimulationResults) and clinch flags
LEAGUE_VIEWS = ("mRoster", "mTeam", "mSettings", "mMatchupScore", "mStatus", "mStandings")

# The player finder's pools (kona_player_info filterStatus; "watch" is your watch list)
POOLS = {"fa": ["FREEAGENT", "WAIVERS"], "rostered": ["ONTEAM"], "all": None, "watch": None}

# ESPN's web app refuses a 51st watch-list player (maxWatchListPlayers in its bundle)
WATCH_LIST_MAX = 50
WATCH_LIST_FULL = (f"your watch list is full (ESPN allows {WATCH_LIST_MAX} players): "
                   "take one off first")


def eastern() -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:  # no tz database (rare on Windows): standard time is close enough
        return dt.timezone(dt.timedelta(hours=-5))


class DiskCache:
    def __init__(self, folder: Path):
        self.folder = folder

    def get(self, name: str, ttl: float):
        path = self.folder / f"{name}.json"
        try:
            if time.time() - path.stat().st_mtime < ttl:
                return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
        return None

    def put(self, name: str, data) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / f"{name}.json.tmp"
            tmp.write_text(json.dumps(data))
            tmp.replace(self.folder / f"{name}.json")
        except OSError:
            pass


@dataclass
class OptimizeResult:
    plan: DayPlan
    status: str = ""        # ESPN status, e.g. EXECUTED; "" when nothing was sent
    error: str = ""


class Session:
    def __init__(self, cfg: config_mod.Config | None = None, client: Client | None = None,
                 today: dt.date | None = None, now: dt.datetime | None = None):
        self.cfg = cfg or config_mod.load()
        if client is None:
            self.cfg.require_league()
            client = Client(self.cfg.league_id, self.cfg.effective_season, credentials.require())
        self.client = client
        self._today = today
        self._now = now
        self.cache = DiskCache(config_mod.cache_dir() / f"{client.league_id}-{client.season}")
        self._league: League | None = None
        self._league_raw: dict | None = None
        self._lineups: dict[int, dict[int, int]] = {}

    @property
    def demo(self) -> bool:
        return False

    # --- time ----------------------------------------------------------------------------------

    @property
    def now(self) -> dt.datetime:
        """Current time, timezone aware."""
        return self._now or dt.datetime.now().astimezone()

    @property
    def today(self) -> dt.date:
        """ESPN's fantasy day, which runs from 3 am to 3 am US Eastern, wherever you are."""
        if self._today:
            return self._today
        return (self.now.astimezone(eastern()) - dt.timedelta(hours=3)).date()

    @property
    def today_period(self) -> int:
        """Today's scoring period, clamped to the season (opening day before the season)."""
        return self.calendar.today_period(self.today)

    @property
    def in_season(self) -> bool:
        return 1 <= self.calendar.period_of(self.today) <= self.calendar.final_period

    def current_period(self) -> int:
        """ESPN's current scoring period, read fresh (it decides ROSTER versus FUTURE_ROSTER)."""
        status = self.client.league("mStatus").get("status") or {}
        return status.get("latestScoringPeriod") or self.league().scoring_period

    # --- data ----------------------------------------------------------------------------------

    @cached_property
    def calendar(self) -> SeasonCalendar:
        raw = self.cache.get("nba-schedule", 86400)
        if raw is None:
            raw = self.client.season_data("proTeamSchedules_wl")
            self.cache.put("nba-schedule", raw)
        return SeasonCalendar.from_raw(raw)

    def league(self, refresh: bool = False) -> League:
        if self._league is None or refresh:
            self._lineups = {}
            raw = self.client.league(*LEAGUE_VIEWS)
            self._league_raw = raw
            swid = self.client.cookies[1] if self.client.cookies else None
            lg = parse_league(raw, self.cfg.team_id, swid)
            if lg.teams and lg.my_team_id not in lg.teams:
                from benchboss.errors import ConfigError

                raise ConfigError(f"team {lg.my_team_id} is not in this league: fix "
                                  "BENCHBOSS_TEAM_ID or run `benchboss setup`")
            self._league = lg
        return self._league

    @property
    def league_raw(self) -> dict:
        self.league()
        return self._league_raw or {}

    def roster_on(self, period: int):
        """My roster as it stands on a given day (future days carry pending lineup moves)."""
        raw = self.client.league("mRoster", "mTeam", scoring_period=period)
        lg = self.league()
        for t in raw.get("teams") or []:
            if t["id"] == lg.my_team_id:
                return parse_team(t, lg.season, lg.members).roster
        raise BenchbossError(f"team {lg.my_team_id} not found in league {lg.id}")

    def free_agents(self, n: int = 50, position: str | None = None,
                    sort: str = "sortPercOwned") -> list[Player]:
        lg = self.league()
        flt: dict = {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "limit": n,
                     sort: {"sortPriority": 1, "sortAsc": False}, **self._with_stats()}
        if position:
            flt["filterSlotIds"] = {"value": [_slot_id(position)]}
        return [parse_player(x, lg.season) for x in self.client.players(flt, lg.scoring_period)]

    def _with_stats(self) -> dict:
        """The filter part that makes ESPN send every split in constants.SPLITS."""
        return {"filterStatsForTopScoringPeriodIds": {
            "value": 2, "additionalValue": split_ids(self.league().season)}}

    def player_pool(self, source: str = "fa", position: str | None = None, n: int = 100,
                    sort: str = "proj", query: str | None = None,
                    watched: Iterable[int] | None = None) -> list[Player]:
        """Players for the finder, with every stat split.

        ``source``: "fa" (free agents and waivers), "rostered" (on a team in this league),
        "all", or "watch" (your ESPN watch list). ``sort`` picks which ``n`` players ESPN sends:
        a split key (proj, season, l7, l15, l30, last) ranks by fantasy points per game in
        that split, "own" by % rostered, "change" by the change in % rostered. Callers sort
        the result again however they like. ``watched`` replaces the saved watch list for
        "watch": the finder passes its stars, some of them still on their way to ESPN.
        """
        if source not in POOLS:
            raise BenchbossError(f"unknown player pool '{source}' (fa, rostered, all, watch)")
        lg = self.league()
        flt: dict = {"limit": n, **self._with_stats()}
        if source == "watch":
            ids = list(self.watch_list() if watched is None else watched)
            if not ids:
                return []
            flt["filterIds"] = {"value": ids}
            flt["limit"] = len(ids)
        elif POOLS[source]:
            flt["filterStatus"] = {"value": POOLS[source]}
        if sort == "own":
            flt["sortPercOwned"] = {"sortPriority": 1, "sortAsc": False}
        elif sort == "change":
            flt["sortPercChanged"] = {"sortPriority": 1, "sortAsc": False}
        else:
            ids = dict(zip(SPLITS, split_ids(lg.season), strict=True))
            if sort not in ids:
                raise BenchbossError(f"unknown sort '{sort}' (proj season l7 l15 l30 last own change)")
            flt["sortAppliedStatAverage"] = {"sortPriority": 1, "sortAsc": False, "value": ids[sort]}
        if position:
            flt["filterSlotIds"] = {"value": [_slot_id(position)]}
        if query:
            flt["filterName"] = {"value": query}
        return [parse_player(x, lg.season) for x in self.client.players(flt, lg.scoring_period)]

    # --- watch list ------------------------------------------------------------------------------

    def watch_list(self) -> tuple[int, ...]:
        """Player ids on your ESPN watch list (the "Watch List" of the ESPN app)."""
        return self.league().me.watch_list

    def set_watched(self, player_id: int, watched: bool) -> tuple[int, ...]:
        """Add a player to your ESPN watch list or take him off; returns the new list.

        The list is read fresh first (it may have changed in the ESPN app) and ESPN gets the
        whole new list, which is how its web app does it. Like the web app, an add to a full
        list (``WATCH_LIST_MAX``) is refused without sending anything.
        """
        lg = self.league()
        raw = self.client.league("mTeam")
        mine = next((t for t in raw.get("teams") or [] if t.get("id") == lg.my_team_id), {})
        ids = [int(x) for x in mine.get("watchList") or []]
        if watched == (player_id in ids):
            lg.me.watch_list = tuple(ids)
            return lg.me.watch_list
        if watched and len(ids) >= WATCH_LIST_MAX:
            lg.me.watch_list = tuple(ids)
            raise BenchbossError(WATCH_LIST_FULL)
        ids = ids + [player_id] if watched else [x for x in ids if x != player_id]
        team = self.client.update_team(lg.my_team_id, {"watchList": ids})
        got = team.get("watchList") if isinstance(team, dict) else None
        lg.me.watch_list = tuple(int(x) for x in got) if got is not None else tuple(ids)
        return lg.me.watch_list

    def lineups(self, periods: list[int]) -> dict[int, dict[int, int]]:
        """Your lineup on each of these days: period -> {player id: slot id}.

        One ESPN read per day, in parallel, kept for the life of the session. Future days
        include the moves already saved for them.
        """
        from concurrent.futures import ThreadPoolExecutor

        todo = [p for p in dict.fromkeys(periods) if p not in self._lineups]
        if todo:
            with ThreadPoolExecutor(max_workers=min(7, len(todo))) as pool:
                rosters = list(pool.map(self.roster_on, todo))
            for p, roster in zip(todo, rosters, strict=True):
                self._lineups[p] = {s.player.id: s.slot_id for s in roster}
        return {p: self._lineups[p] for p in periods}

    def trending(self, n: int = 10) -> list[Player]:
        return self.free_agents(n, sort="sortPercChanged")

    def find_player(self, name: str) -> Player:
        """A player on any roster in the league, or else in the free-agent pool."""
        from benchboss.text import match_one

        lg = self.league()
        rostered = [sp.player for t in lg.teams.values() for sp in t.roster]
        try:
            return match_one(rostered, name, lambda p: p.name, where="any roster")
        except BenchbossError:
            hits = self.client.players({"filterName": {"value": name}, "limit": 10,
                                        "sortPercOwned": {"sortPriority": 1, "sortAsc": False}},
                                       lg.scoring_period)
            pool = [parse_player(x, lg.season) for x in hits]
            return match_one(pool, name, lambda p: p.name, where="your league or free agency")

    def news(self, player_ids: list[int], days: int = 5):
        from benchboss import news

        return news.fetch(player_ids, days)

    def playoff_race(self, picks: dict[int, int] | None = None, sims: int = 5000):
        """Playoff odds and who is in or out, with the results you pick fixed (see
        core.playoffs.race: ``picks`` maps a matchup id to the team id you say wins it)."""
        from benchboss.core import playoffs
        from benchboss.core.projection import week_projection

        lg, cal = self.league(), self.calendar
        weeks = range(1, playoffs.regular_season_weeks(lg) + 1)
        days = {w: len(cal.matchup_periods(w, lg.matchup_periods)) for w in weeks}
        current = cal.matchup_periods(lg.current_matchup, lg.matchup_periods)
        today = self.today_period
        done = sum(1 for p in current if p < today) if self.in_season else 0
        progress = done / len(current) if current else 0.0
        ahead = [p for p in range(today, today + 14) if p <= cal.final_period]
        daily = {}
        for tid, team in lg.teams.items():
            pts, _ = week_projection(team, ahead, cal, lg.starter_slots)
            daily[tid] = pts / len(ahead) if ahead else 0.0
        return playoffs.race(lg, picks or {}, sims=sims, daily=daily, days_by_week=days,
                             week_progress=progress)

    # --- features ------------------------------------------------------------------------------

    def matchup_periods(self) -> list[int]:
        lg = self.league()
        return self.calendar.matchup_periods(lg.current_matchup, lg.matchup_periods)

    def outlook(self) -> MatchupOutlook:
        return matchup_outlook(self.league(), self.calendar, self.today_period, self.now)

    def activity(self) -> list[activity_mod.Activity]:
        return activity_mod.roster_activity(self.league().me, self.calendar,
                                            self.matchup_periods(), self.today_period)

    def trash(self, n: int = 10, position: str | None = None, pool: int = 60) -> list[trash_mod.TrashPick]:
        lg = self.league()
        fas = self.free_agents(pool, position)
        waiver_days = max(1, round(lg.waiver_hours / 24)) if lg.waiver_hours else 1
        # before the season today_period is opening night, but waivers clear from the real day
        waiver_days = max(0, self.calendar.period_of(self.today) + waiver_days - self.today_period)
        picks = trash_mod.scout(fas, lg.me, self.calendar, self.matchup_periods(),
                                self.today_period, lg.starter_slots, waiver_days, self.now,
                                slot_counts=lg.slot_counts, roster_lock=lg.roster_lock_type,
                                position_limits=lg.position_limits)
        return picks[:n]

    def trades(self, need: str | None = None, partner: str | None = None,
               n: int = 10) -> list[trades_mod.TradeIdea]:
        lg = self.league()
        pid = None
        if partner:
            from benchboss.text import match_one

            pid = match_one(lg.teams.values(), partner,
                            lambda t: f"{t.name} {t.owner_name}", where="this league").id
        return trades_mod.find_trades(lg, need=need, partner_id=pid, limit=n)

    def plan_days(self, periods: list[int]) -> list[DayPlan]:
        """Preview: the best lineup for each day (sends nothing).

        On ESPN a move carries forward to the next days that have no change of their own, so
        a day whose lineup matches the day before is planned from the lineup the day before
        ends up with. That is what apply_days finds when it re-reads the day.
        """
        lg = self.league()
        current = lg.scoring_period
        plans = []
        prev = None  # (period, lineup on ESPN, lineup after its moves) of the day before
        for sp in periods:
            roster = lg.me.roster if sp == current else self.roster_on(sp)
            on_espn = {s.player.id: s.slot_id for s in roster}
            if prev and prev[0] == sp - 1 and prev[1] == on_espn:
                roster = [replace(s, slot_id=prev[2][s.player.id]) for s in roster]
            plan = plan_day(roster, lg.slot_counts, sp, self.calendar)
            after = {s.player.id: s.slot_id for s in roster}
            after.update((m.player.id, m.to_slot) for m in plan.moves)
            prev = (sp, on_espn, after)
            plans.append(plan)
        return plans

    def apply_days(self, periods: list[int]) -> list[OptimizeResult]:
        """Send the best lineup for every day in order.

        Every day is re-read right before it is planned, because moves on one day carry
        forward to the next ones: a day that looked fine in the preview can need moves after
        an earlier day changes, and the other way around. There is one result per day, also
        when a day fails, so the caller can tell which days were sent.
        """
        current = self.current_period()
        return [self.apply_plan(sp, current) for sp in sorted(periods)]

    def apply_plan(self, period: int, current: int | None = None) -> OptimizeResult:
        """Re-read one day and send what it still needs. ESPN errors end up in the result."""
        lg = self.league()
        try:
            current = current or self.current_period()
            roster = self.roster_on(period)
        except BenchbossError as e:
            return OptimizeResult(DayPlan(period), error=f"could not read the lineup: {e}")
        plan = plan_day(roster, lg.slot_counts, period, self.calendar)
        if period < current:
            return OptimizeResult(plan, error="that day is already over on ESPN")
        if not plan.changed:
            return OptimizeResult(plan, status="ALREADY_OPTIMAL")
        kind = "ROSTER" if period == current else "FUTURE_ROSTER"
        from benchboss.actions import send

        try:
            status = send(self, kind, plan.items(), period)
        except BenchbossError as e:
            return OptimizeResult(plan, error=str(e))
        if status.startswith("FAILED"):
            return OptimizeResult(plan, status=status, error=f"ESPN answered {status}")
        return OptimizeResult(plan, status=status)


def _slot_id(position: str) -> int:
    pos = position.upper()
    if pos not in SLOT_ID:
        raise BenchbossError(f"unknown position '{position}' (PG SG SF PF C G F UT)")
    return SLOT_ID[pos]


def periods_for(session: Session, when: str) -> list[int]:
    """'today', 'tomorrow', 'week' (rest of the matchup week), 'MM-DD' or 'YYYY-MM-DD'."""
    cal = session.calendar
    today = session.today_period
    w = (when or "today").lower()
    if w in ("today", "tomorrow"):
        day = session.today + dt.timedelta(days=0 if w == "today" else 1)
        sp = cal.period_of(day)
        if sp < 1:
            start = cal.date_of(1)
            raise BenchbossError(f"{w} is before the season, which starts {start:%a %b} "
                                 f"{start.day}: use `week` or a date like {start:%m-%d}")
        if sp > cal.final_period:
            raise BenchbossError(f"{w} is after the end of the fantasy season")
        return [sp]
    if w in ("week", "rest-of-week"):
        return [p for p in session.matchup_periods() if p >= today]
    try:
        if w.count("-") == 2:
            day = dt.date.fromisoformat(w)
        else:
            mo, da = (int(x) for x in w.split("-"))
            season = session.league().season
            day = dt.date(season - 1 if mo >= 8 else season, mo, da)
    except ValueError as e:
        raise BenchbossError(f"'{when}' is not a day: use today, tomorrow, week, 11-04 or 2026-11-04") from e
    sp = cal.period_of(day)
    if sp < 1 or sp > cal.final_period:
        raise BenchbossError(f"{day.isoformat()} is outside the fantasy season")
    return [sp]

"""Typed views over ESPN's JSON. Parsing is lenient: missing fields get safe defaults."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchboss.espn.constants import (
    BENCH,
    INJURY_TAG,
    IR,
    POSITION,
    POSITION_SLOTS,
    PRO_TEAM,
    SLOT,
    SOURCE_ACTUAL,
    SOURCE_PROJECTED,
    SPLIT_LAST15,
    SPLIT_SEASON,
    stat_key,
)


@dataclass
class Player:
    id: int
    name: str
    pro_team_id: int = 0
    position_id: int = 0
    eligible_slots: tuple[int, ...] = ()
    injury_status: str = "ACTIVE"
    proj: float = 0.0            # projected fantasy points per game (best estimate available)
    avg: float | None = None     # season average (this season, or last season if none yet)
    avg_is_last_season: bool = False
    last15: float | None = None
    owned: float = 0.0           # % of ESPN leagues
    owned_change: float = 0.0
    status: str = ""             # FREEAGENT, WAIVERS, ONTEAM
    on_team_id: int = 0
    outlook: str = ""
    last_news: int | None = None  # epoch ms
    locked: bool = False         # lineup locked: his game for the day has started

    @property
    def pro_team(self) -> str:
        return PRO_TEAM.get(self.pro_team_id, "?")

    @property
    def position(self) -> str:
        return POSITION.get(self.position_id, "?")

    @property
    def positions(self) -> str:
        return "/".join(SLOT[s] for s in self.eligible_slots if s in POSITION_SLOTS)

    @property
    def injury(self) -> str:
        return INJURY_TAG.get(self.injury_status or "", (self.injury_status or "")[:4])

    @property
    def short_name(self) -> str:
        parts = self.name.split()
        return self.name if len(parts) < 2 else f"{parts[0][0]}. {' '.join(parts[1:])}"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "team": self.pro_team,
                "positions": self.positions, "injury": self.injury or None,
                "proj": round(self.proj, 1), "avg": None if self.avg is None else round(self.avg, 1),
                "last15": None if self.last15 is None else round(self.last15, 1),
                "owned": round(self.owned, 1), "owned_change": round(self.owned_change, 2),
                "status": self.status or None}


@dataclass
class RosterSpot:
    player: Player
    slot_id: int

    @property
    def slot(self) -> str:
        return SLOT.get(self.slot_id, str(self.slot_id))

    @property
    def is_starting(self) -> bool:
        return self.slot_id not in (BENCH, IR)


@dataclass
class Team:
    id: int
    name: str
    abbrev: str = ""
    owner_ids: tuple[str, ...] = ()
    owner_name: str = ""
    wins: int = 0
    losses: int = 0
    ties: int = 0
    seed: int | None = None
    points_for: float = 0.0
    projected_rank: int | None = None
    roster: list[RosterSpot] = field(default_factory=list)

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")

    def find(self, query: str) -> RosterSpot:
        from benchboss.text import match_one

        return match_one(self.roster, query, lambda s: s.player.name, where="your roster")


@dataclass
class MatchupSide:
    team_id: int | None
    points: float = 0.0
    points_by_period: dict[int, float] = field(default_factory=dict)


@dataclass
class Matchup:
    period: int
    home: MatchupSide
    away: MatchupSide

    def side_of(self, team_id: int) -> tuple[MatchupSide, MatchupSide] | None:
        if self.home.team_id == team_id:
            return self.home, self.away
        if self.away.team_id == team_id:
            return self.away, self.home
        return None


@dataclass
class League:
    id: int
    season: int
    name: str
    my_team_id: int
    scoring_period: int
    current_matchup: int
    first_scoring_period: int
    final_scoring_period: int
    slot_counts: dict[int, int]
    position_limits: dict[int, int]
    matchup_periods: dict[int, list[int]]
    teams: dict[int, Team]
    members: dict[str, str]
    matchups: list[Matchup]
    scoring_type: str = "H2H_POINTS"
    acquisition_type: str = ""
    waiver_hours: int = 0

    @property
    def me(self) -> Team:
        return self.teams[self.my_team_id]

    @property
    def starter_slots(self) -> int:
        return sum(n for s, n in self.slot_counts.items() if s not in (BENCH, IR))

    def matchup_for(self, team_id: int, period: int | None = None) -> Matchup | None:
        period = period or self.current_matchup
        for m in self.matchups:
            if m.period == period and m.side_of(team_id):
                return m
        return None

    def standings(self) -> list[Team]:
        return sorted(self.teams.values(),
                      key=lambda t: (t.seed or 99, -t.wins, -t.points_for))


# --- parsing ------------------------------------------------------------------------------------

def _stat(p: dict, source: int, split: int, season: int):
    key = stat_key(source, split, season)
    for st in p.get("stats") or []:
        if st.get("id") == key:
            # in the preseason ESPN sends the split with zeros: that means "no data yet"
            return st.get("appliedAverage") if st.get("appliedTotal") else None
    return None


def parse_player(entry: dict, season: int) -> Player:
    """Accepts a roster entry, a playerPoolEntry or a kona_player_info item."""
    pool = entry.get("playerPoolEntry") or entry
    p = pool.get("player") or {}
    avg = _stat(p, SOURCE_ACTUAL, SPLIT_SEASON, season)
    last_season = False
    if avg is None:
        avg = _stat(p, SOURCE_ACTUAL, SPLIT_SEASON, season - 1)
        last_season = avg is not None
    proj = _stat(p, SOURCE_PROJECTED, SPLIT_SEASON, season)
    if proj is None:
        proj = avg or 0.0
    own = p.get("ownership") or {}
    return Player(
        id=p.get("id") or pool.get("id") or entry.get("playerId") or 0,
        name=p.get("fullName", "?"),
        pro_team_id=p.get("proTeamId") or 0,
        position_id=p.get("defaultPositionId") or 0,
        eligible_slots=tuple(p.get("eligibleSlots") or ()),
        injury_status=p.get("injuryStatus") or "ACTIVE",
        proj=float(proj or 0.0),
        avg=avg,
        avg_is_last_season=last_season,
        last15=_stat(p, SOURCE_ACTUAL, SPLIT_LAST15, season),
        owned=float(own.get("percentOwned") or 0.0),
        owned_change=float(own.get("percentChange") or 0.0),
        status=pool.get("status") or entry.get("status") or "",
        on_team_id=pool.get("onTeamId") or 0,
        outlook=p.get("seasonOutlook") or "",
        last_news=p.get("lastNewsDate"),
        locked=bool(pool.get("lineupLocked")),
    )


def team_name(t: dict) -> str:
    return (t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip()
            or t.get("abbrev") or f"Team {t.get('id')}")


def parse_team(t: dict, season: int, members: dict[str, str]) -> Team:
    rec = (t.get("record") or {}).get("overall") or {}
    owners = tuple(t.get("owners") or ())
    roster = [RosterSpot(parse_player(e, season), e.get("lineupSlotId", BENCH))
              for e in (t.get("roster") or {}).get("entries") or []]
    return Team(
        id=t["id"], name=team_name(t), abbrev=t.get("abbrev", ""), owner_ids=owners,
        owner_name=members.get(owners[0], "") if owners else "",
        wins=rec.get("wins", 0), losses=rec.get("losses", 0), ties=rec.get("ties", 0),
        seed=t.get("playoffSeed"), points_for=float(rec.get("pointsFor") or 0.0),
        projected_rank=t.get("currentProjectedRank"), roster=roster)


def _side(s: dict | None) -> MatchupSide:
    s = s or {}
    pts = s.get("totalPointsLive")
    if pts is None:
        pts = s.get("totalPoints")
    by = {int(k): float(v or 0) for k, v in (s.get("pointsByScoringPeriod") or {}).items()}
    return MatchupSide(team_id=s.get("teamId"), points=float(pts or 0.0), points_by_period=by)


def parse_league(raw: dict, my_team_id: int | None, swid: str | None = None,
                 strict: bool = True) -> League:
    """``strict``: refuse to guess which team is mine when neither the config nor the
    cookies say so (a wrong guess would send lineup moves to someone else's team)."""
    season = raw.get("seasonId")
    settings = raw.get("settings") or {}
    status = raw.get("status") or {}
    members = {m["id"]: (f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
                         or m.get("displayName", "")) for m in raw.get("members") or []}
    teams = {t["id"]: parse_team(t, season, members) for t in raw.get("teams") or []}
    if my_team_id is None and swid:
        my_team_id = next((t.id for t in teams.values() if swid in t.owner_ids), None)
    if my_team_id is None:
        if strict:
            from benchboss.errors import ConfigError

            raise ConfigError("could not tell which team is yours: run `benchboss setup` "
                              "or set BENCHBOSS_TEAM_ID")
        my_team_id = min(teams) if teams else 0
    roster_settings = settings.get("rosterSettings") or {}
    sched = settings.get("scheduleSettings") or {}
    acq = settings.get("acquisitionSettings") or {}
    return League(
        id=raw.get("id"), season=season, name=settings.get("name", ""),
        my_team_id=my_team_id,
        scoring_period=status.get("latestScoringPeriod") or raw.get("scoringPeriodId") or 1,
        current_matchup=status.get("currentMatchupPeriod") or 1,
        first_scoring_period=status.get("firstScoringPeriod") or 1,
        final_scoring_period=status.get("finalScoringPeriod") or 0,
        slot_counts={int(k): v for k, v in (roster_settings.get("lineupSlotCounts") or {}).items() if v},
        position_limits={int(k): v for k, v in (roster_settings.get("positionLimits") or {}).items()},
        matchup_periods={int(k): v for k, v in (sched.get("matchupPeriods") or {}).items()},
        teams=teams, members=members,
        matchups=[Matchup(g.get("matchupPeriodId", 0), _side(g.get("home")), _side(g.get("away")))
                  for g in raw.get("schedule") or []],
        scoring_type=(settings.get("scoringSettings") or {}).get("scoringType", ""),
        acquisition_type=acq.get("acquisitionType", ""),
        waiver_hours=acq.get("waiverHours") or 0,
    )

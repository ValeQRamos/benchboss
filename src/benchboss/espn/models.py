"""Typed views over ESPN's JSON. Parsing is lenient: missing fields get safe defaults."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchboss.espn.constants import (
    AST,
    BENCH,
    BLK,
    FG_PCT,
    FGA,
    FGM,
    FT_PCT,
    FTA,
    FTM,
    GP,
    INJURY_TAG,
    IR,
    MIN,
    POSITION,
    POSITION_SLOTS,
    PRO_TEAM,
    PTS,
    REB,
    SLOT,
    SPLITS,
    STAT,
    STL,
    TO,
    TPM,
    stat_key,
)


@dataclass
class StatLine:
    """One stat split of one player (season, last 7 days, projection...).

    ``fpts`` is fantasy points per game in this league's scoring (ESPN's appliedAverage),
    ``avg`` the box score per game and ``totals`` the box score added up, both keyed by stat
    id (see constants: PTS, REB, AST...). Percentages are fractions, MIN is per game.
    """
    fpts: float
    total: float = 0.0
    gp: int = 0
    avg: dict[int, float] = field(default_factory=dict)
    totals: dict[int, float] = field(default_factory=dict)

    def get(self, stat: int) -> float | None:
        return self.avg.get(stat)

    @property
    def pts(self) -> float | None:
        return self.avg.get(PTS)

    @property
    def reb(self) -> float | None:
        return self.avg.get(REB)

    @property
    def ast(self) -> float | None:
        return self.avg.get(AST)

    @property
    def stl(self) -> float | None:
        return self.avg.get(STL)

    @property
    def blk(self) -> float | None:
        return self.avg.get(BLK)

    @property
    def tpm(self) -> float | None:
        return self.avg.get(TPM)

    @property
    def to(self) -> float | None:
        return self.avg.get(TO)

    @property
    def mpg(self) -> float | None:
        return self.avg.get(MIN)

    @property
    def fg_pct(self) -> float | None:
        return _pct(self.totals, FGM, FGA, self.avg.get(FG_PCT))

    @property
    def ft_pct(self) -> float | None:
        return _pct(self.totals, FTM, FTA, self.avg.get(FT_PCT))

    def to_dict(self) -> dict:
        box = {STAT.get(k, str(k)): round(v, 3 if "%" in STAT.get(k, "") else 1)
               for k, v in sorted(self.avg.items()) if k in STAT}
        return {"fpts": round(self.fpts, 1), "total": round(self.total, 1), "gp": self.gp,
                "per_game": box}


def _pct(totals: dict[int, float], made: int, att: int, fallback: float | None) -> float | None:
    if totals.get(att):
        return totals.get(made, 0.0) / totals[att]
    return fallback


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
    started: float = 0.0         # % of ESPN leagues that start him
    adp: float | None = None     # average draft position
    droppable: bool = True
    stats: dict[str, StatLine] = field(default_factory=dict)  # keys of constants.SPLITS

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

    def split(self, key: str) -> StatLine | None:
        """A stat split by key (season, l7, l15, l30, proj, last), or None without data."""
        return self.stats.get(key)

    def fpts(self, key: str) -> float | None:
        """Fantasy points per game for a split, or None without data."""
        line = self.stats.get(key)
        return line.fpts if line else None

    @property
    def last7(self) -> float | None:
        return self.fpts("l7")

    @property
    def last30(self) -> float | None:
        return self.fpts("l30")

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

    def to_full_dict(self) -> dict:
        """to_dict plus % started and every stat split with its box score."""
        return {**self.to_dict(), "last7": _r(self.last7), "last30": _r(self.last30),
                "started": round(self.started, 1), "on_team_id": self.on_team_id or None,
                "stats": {k: v.to_dict() for k, v in self.stats.items()}}


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


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
    points_against: float = 0.0
    win_pct: float = 0.0
    games_back: float = 0.0
    streak_type: str = ""        # WIN, LOSS, TIE (NONE before the first result)
    streak_length: int = 0
    division_id: int | None = None
    division_record: tuple[int, int, int] = (0, 0, 0)   # wins, losses, ties
    waiver_rank: int | None = None
    acquisitions: int = 0
    drops: int = 0
    trades: int = 0
    playoff_pct: float | None = None       # ESPN's season simulation, 0..1
    division_win_pct: float | None = None
    clinch: str = ""             # PLAYOFFS, DIVISION, BYE, TOP_SEED, ELIMINATED or ""
    watch_list: tuple[int, ...] = ()       # only filled in for your own team

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def point_diff(self) -> float:
        return self.points_for - self.points_against

    @property
    def streak(self) -> str:
        """W3, L1, T1, or "" before the first result."""
        tag = {"WIN": "W", "LOSS": "L", "TIE": "T"}.get(self.streak_type, "")
        return f"{tag}{self.streak_length}" if tag and self.streak_length else ""

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
    period: int                  # the matchup period (week), not a scoring period
    home: MatchupSide
    away: MatchupSide
    winner: str = "UNDECIDED"    # HOME, AWAY, TIE or UNDECIDED
    playoff_tier: str = "NONE"   # NONE in the regular season

    @property
    def decided(self) -> bool:
        return self.winner in ("HOME", "AWAY", "TIE")

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
    roster_lock_type: str = ""   # rosterSettings.rosterLocktimeType, e.g. FIRSTGAME_SCORINGPERIOD
    playoff_teams: int = 0       # scheduleSettings.playoffTeamCount
    regular_season_weeks: int = 0  # scheduleSettings.matchupPeriodCount
    seeding_rule: str = ""       # scheduleSettings.playoffSeedingRule: tiebreaker, e.g. H2H_RECORD
    divisions: dict[int, str] = field(default_factory=dict)
    scoring: dict[int, float] = field(default_factory=dict)  # stat id -> fantasy points

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

def _splits(p: dict, season: int) -> dict[str, StatLine]:
    """Every split in SPLITS that has data. A split ESPN sends with zeros (the preseason,
    or a player who has not played in that window) means "no data yet" and is left out."""
    by_id = {st.get("id"): st for st in p.get("stats") or []}
    out = {}
    for key, (src, split, back) in SPLITS.items():
        st = by_id.get(stat_key(src, split, season - back))
        if not st or not st.get("appliedTotal"):
            continue
        avg = {int(k): float(v) for k, v in (st.get("averageStats") or {}).items() if v is not None}
        tot = {int(k): float(v) for k, v in (st.get("stats") or {}).items() if v is not None}
        gp = int(tot.get(GP) or avg.get(GP) or 0)
        out[key] = StatLine(float(st.get("appliedAverage") or 0.0), float(st.get("appliedTotal") or 0.0),
                            gp, avg, tot)
    return out


def parse_player(entry: dict, season: int) -> Player:
    """Accepts a roster entry, a playerPoolEntry or a kona_player_info item."""
    pool = entry.get("playerPoolEntry") or entry
    p = pool.get("player") or {}
    stats = _splits(p, season)
    avg = stats["season"].fpts if "season" in stats else None
    last_season = False
    if avg is None and "last" in stats:
        avg, last_season = stats["last"].fpts, True
    proj = stats["proj"].fpts if "proj" in stats else None
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
        last15=stats["l15"].fpts if "l15" in stats else None,
        owned=float(own.get("percentOwned") or 0.0),
        owned_change=float(own.get("percentChange") or 0.0),
        status=pool.get("status") or entry.get("status") or "",
        on_team_id=pool.get("onTeamId") or 0,
        outlook=p.get("seasonOutlook") or "",
        last_news=p.get("lastNewsDate"),
        locked=bool(pool.get("lineupLocked")),
        started=float(own.get("percentStarted") or 0.0),
        adp=own.get("averageDraftPosition"),
        droppable=p.get("droppable", True) is not False,
        stats=stats,
    )


def team_name(t: dict) -> str:
    return (t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip()
            or t.get("abbrev") or f"Team {t.get('id')}")


def parse_team(t: dict, season: int, members: dict[str, str]) -> Team:
    record = t.get("record") or {}
    rec = record.get("overall") or {}
    div = record.get("division") or {}
    owners = tuple(t.get("owners") or ())
    roster = [RosterSpot(parse_player(e, season), e.get("lineupSlotId", BENCH))
              for e in (t.get("roster") or {}).get("entries") or []]
    moves = t.get("transactionCounter") or {}
    sim = t.get("currentSimulationResults") or {}
    clinch = t.get("playoffClinchType") or sim.get("playoffClinchType") or ""
    return Team(
        id=t["id"], name=team_name(t), abbrev=t.get("abbrev", ""), owner_ids=owners,
        owner_name=members.get(owners[0], "") if owners else "",
        wins=rec.get("wins", 0), losses=rec.get("losses", 0), ties=rec.get("ties", 0),
        seed=t.get("playoffSeed"), points_for=float(rec.get("pointsFor") or 0.0),
        projected_rank=t.get("currentProjectedRank"), roster=roster,
        points_against=float(rec.get("pointsAgainst") or 0.0),
        win_pct=float(rec.get("percentage") or 0.0),
        games_back=float(rec.get("gamesBack") or 0.0),
        streak_type=rec.get("streakType") or "", streak_length=rec.get("streakLength") or 0,
        division_id=t.get("divisionId"),
        division_record=(div.get("wins", 0), div.get("losses", 0), div.get("ties", 0)),
        waiver_rank=t.get("waiverRank"),
        acquisitions=moves.get("acquisitions") or 0, drops=moves.get("drops") or 0,
        trades=moves.get("trades") or 0,
        playoff_pct=sim.get("playoffPct"), division_win_pct=sim.get("divisionWinPct"),
        clinch="" if clinch in ("UNKNOWN", "NONE") else clinch,
        watch_list=tuple(t.get("watchList") or ()))


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
        matchups=[Matchup(g.get("matchupPeriodId", 0), _side(g.get("home")), _side(g.get("away")),
                          winner=g.get("winner") or "UNDECIDED",
                          playoff_tier=g.get("playoffTierType") or "NONE")
                  for g in raw.get("schedule") or []],
        scoring_type=(settings.get("scoringSettings") or {}).get("scoringType", ""),
        acquisition_type=acq.get("acquisitionType", ""),
        waiver_hours=acq.get("waiverHours") or 0,
        roster_lock_type=roster_settings.get("rosterLocktimeType") or "",
        playoff_teams=sched.get("playoffTeamCount") or 0,
        regular_season_weeks=sched.get("matchupPeriodCount") or 0,
        seeding_rule=sched.get("playoffSeedingRule") or "",
        divisions={d["id"]: d.get("name", "") for d in sched.get("divisions") or [] if "id" in d},
        scoring={i["statId"]: float(i.get("points") or 0.0)
                 for i in (settings.get("scoringSettings") or {}).get("scoringItems") or []
                 if "statId" in i},
    )

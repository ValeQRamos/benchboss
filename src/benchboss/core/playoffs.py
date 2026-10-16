"""Playoff race: who gets in, how likely, and what-if scenarios for the weeks left.

How ESPN fills the bracket: ``playoffTeamCount`` teams make it, ranked by record. In a league
with divisions the division winners are seeded first. Ties go to the league's tiebreaker
(``scheduleSettings.playoffSeedingRule``) and then, as ESPN's settings page says, to
head-to-head record, points for, division record, points against and finally a coin flip.

``race`` plays the rest of the regular season ``sims`` times. A team's score in a week is
drawn around what it is expected to score that week: its points per day so far, blended
with what its roster projects, times the days in that week, with a spread of about 12%
(typical for weekly fantasy scores). A week that is in progress keeps the live score and
only simulates the days left, around what each roster projects for its own games left that
week (the projected final of the matchup card). Results you pick (``picks``: matchup id ->
winning team id) are fixed in every simulation; that is how the scenarios work.

"Clinched" and "eliminated" are certain, not simulated: clinched means no combination of
the results not yet picked can keep the team out, eliminated means none can get it in. Both
use conservative bounds, so a team can be safe in every simulation and still read as alive.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field

from benchboss.errors import BenchbossError
from benchboss.espn.constants import IR
from benchboss.espn.models import League, Matchup, Team
from benchboss.text import match_one

SPREAD = 0.12          # weekly score standard deviation, as a share of the expected score
TEAM_SPREAD = 0.05     # how far a team's level can drift over the season (trades, injuries)
NEAR_WEEKS = 2         # this week and next use the injury-aware projection; later, healthy
PRIOR_DAYS = 21        # how many days of real results it takes to outweigh the projection
GAMES_PER_DAY = 0.5    # an NBA player plays about every other day
BENCH_LOSS = 0.92      # share of those games that fit in the starting slots


@dataclass
class Game:
    """One regular-season matchup."""
    id: int
    week: int
    home: int
    away: int
    home_points: float = 0.0
    away_points: float = 0.0
    winner: int | None = None   # team id; 0 for a tie; None while undecided
    picked: bool = False        # the winner comes from your scenario, not from ESPN
    live: bool = False          # this week is being played right now

    @property
    def decided(self) -> bool:
        return self.winner is not None


@dataclass
class TeamOdds:
    team: Team
    wins: int
    losses: int
    ties: int
    points_for: float
    proj_wins: float = 0.0        # average final wins over the simulations
    proj_losses: float = 0.0
    playoffs: float = 0.0         # share of simulations in which the team makes it
    seeds: list[float] = field(default_factory=list)   # share per seed, 1st first
    division: float = 0.0         # share of simulations winning the division
    status: str = ""              # clinched, eliminated or "" (still alive)
    espn: float | None = None     # ESPN's own playoff odds (before any pick)
    weekly: float = 0.0           # expected points in a 7-day week

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")

    @property
    def mean_seed(self) -> float:
        """Average seed, counting a miss as one past the last seed."""
        n = len(self.seeds)
        return sum((i + 1) * p for i, p in enumerate(self.seeds)) + (n + 1) * (1 - sum(self.seeds))


@dataclass
class Race:
    teams: list[TeamOdds]          # best projected seed first
    games: list[Game]              # regular-season games not played yet (picked ones included)
    home_win: dict[int, float]     # game id -> share of simulations the home team won
    playoff_teams: int
    divisions: dict[int, str]
    picks: dict[int, int]
    sims: int
    weeks_left: list[int]
    seeding_rule: str = ""
    me: int | None = None          # your team id
    baseline: Race | None = None   # the same race without the picks, when the caller ran it

    def odds(self, team_id: int) -> TeamOdds | None:
        return next((t for t in self.teams if t.team.id == team_id), None)

    def to_dict(self) -> dict:
        names = {t.team.id: t.team.name for t in self.teams}
        return {
            "playoff_teams": self.playoff_teams, "sims": self.sims,
            "seeding_rule": self.seeding_rule, "weeks_left": self.weeks_left,
            "picks": [{"matchup": gid, "winner": names.get(w, w)} for gid, w in self.picks.items()],
            "teams": [{
                "team": t.team.name, "manager": t.team.owner_name,
                "division": self.divisions.get(t.team.division_id) if t.team.division_id is not None else None,
                "record": t.record, "points_for": round(t.points_for, 1),
                "projected_record": f"{t.proj_wins:.1f}-{t.proj_losses:.1f}",
                "playoffs": round(t.playoffs, 4), "division_title": round(t.division, 4),
                "seeds": [round(s, 4) for s in t.seeds], "status": t.status or None,
                "espn_playoffs": None if t.espn is None else round(t.espn, 4),
                "expected_weekly_points": round(t.weekly, 1)} for t in self.teams],
            "games": [{"matchup": g.id, "week": g.week, "home": names.get(g.home, g.home),
                       "away": names.get(g.away, g.away),
                       "home_win": round(self.home_win.get(g.id, 0.5), 4),
                       "picked_winner": names.get(g.winner) if g.picked else None,
                       "live": g.live} for g in self.games],
        }


# --- schedule -----------------------------------------------------------------------------------

def regular_season_weeks(league: League) -> int:
    if league.regular_season_weeks:
        return league.regular_season_weeks
    weeks = [m.period for m in league.matchups if m.playoff_tier in ("NONE", "")]
    return max(weeks) if weeks else 0


def season_games(league: League) -> list[Game]:
    """Every regular-season matchup between two real teams, with ESPN's results."""
    last = regular_season_weeks(league)
    out, seen = [], set()
    for i, m in enumerate(league.matchups):
        if m.period > last or m.home.team_id not in league.teams or m.away.team_id not in league.teams:
            continue
        gid = m.id if m.id and m.id not in seen else 100000 + i  # ids are missing in old payloads
        seen.add(gid)
        out.append(_game(m, gid, league.current_matchup))
    return out


def _game(m: Matchup, gid: int, current: int) -> Game:
    winner = {"HOME": m.home.team_id, "AWAY": m.away.team_id, "TIE": 0}.get(m.winner)
    if winner is None and m.period < current and (m.home.points or m.away.points):
        # a past week without ESPN's verdict: the points decide it
        hp, ap = m.home.points, m.away.points
        winner = m.home.team_id if hp > ap else m.away.team_id if ap > hp else 0
    return Game(gid, m.period, m.home.team_id, m.away.team_id, m.home.points, m.away.points,
                winner=winner, live=winner is None and m.period == current)


def parse_picks(league: League, specs: list[str]) -> dict[int, int]:
    """'Winner>Loser' or 'Winner>Loser@WEEK' (team or manager names) -> {matchup id: winner}.

    Without @WEEK it is the next game between the two that is not decided yet.
    """
    teams = list(league.teams.values())
    open_games = [g for g in season_games(league) if not g.decided]
    picks: dict[int, int] = {}
    for spec in specs:
        text, _, week = spec.partition("@")
        a, sep, b = text.partition(">")
        if not sep or not a.strip() or not b.strip():
            raise BenchbossError(f"'{spec}' is not a pick: write it as \"Winner>Loser\" "
                                 "(optionally \"@WEEK\" at the end)")
        win = match_one(teams, a.strip(), _label, where="this league", kind="teams")
        lose = match_one(teams, b.strip(), _label, where="this league", kind="teams")
        if win.id == lose.id:
            raise BenchbossError(f"'{spec}': a team cannot play itself")
        games = [g for g in open_games if {g.home, g.away} == {win.id, lose.id}]
        if week.strip():
            if not week.strip().isdigit():
                raise BenchbossError(f"'{spec}': the week after @ must be a number")
            games = [g for g in games if g.week == int(week)]
        if not games:
            when = f" in week {week.strip()}" if week.strip() else ""
            raise BenchbossError(f"{win.name} and {lose.name} have no game left to pick{when}")
        game = min(games, key=lambda g: g.week)
        picks[game.id] = win.id
    return picks


def _label(t: Team) -> str:
    return f"{t.name} {t.owner_name}"


# --- the simulation -----------------------------------------------------------------------------

def projected_daily(team: Team) -> float:
    """A rough points-per-day for a roster when the caller has no schedule-based estimate."""
    total = sum(s.player.proj for s in team.roster if s.slot_id != IR)
    return total * GAMES_PER_DAY * BENCH_LOSS


def race(league: League, picks: dict[int, int] | None = None, sims: int = 5000, *,
         daily: dict[int, float] | None = None, days_by_week: dict[int, int] | None = None,
         week_progress: float = 0.0, live_left: dict[int, float] | None = None,
         seed: int | None = 0) -> Race:
    """Simulate the rest of the regular season.

    ``daily``: expected points per day for each team id over the next days, from its roster,
    the NBA schedule and today's injuries (the service builds it). It sets the level for this
    week and the next; later weeks use the roster's healthy projection, because a player out
    today is not out all season. ``days_by_week``: days in each matchup week (7 when missing);
    ``week_progress``: the share of the current week already played (0..1).
    ``live_left``: points each team id is expected to add in the week in progress, from its
    roster and its games left that week (core.projection.week_projection over the days left,
    as the matchup card projects them). A games-left gap decides a week, and a rate per day
    averaged over other days hides it; without ``live_left`` the week in progress uses the
    same rate as the next one.

    Each simulated season also moves every team's level a little (TEAM_SPREAD) for all the
    weeks ahead: trades, injuries and waiver luck make a team better or worse for a stretch,
    not just for one week, and without it the odds of the best rosters come out too sure.
    """
    picks = dict(picks or {})
    games = season_games(league)
    by_id = {g.id: g for g in games}
    for gid, winner in picks.items():
        g = by_id.get(gid)
        if g is None:
            raise BenchbossError(f"matchup {gid} is not a regular-season game of this league")
        if winner not in (g.home, g.away):
            raise BenchbossError(f"matchup {gid} is between other teams")
        if g.decided and not g.picked:
            raise BenchbossError(f"matchup {gid} is already decided on ESPN")
        g.winner, g.picked = winner, True
    teams = league.teams
    days = days_by_week or {}
    progress = max(0.0, min(1.0, week_progress))

    # expected points per day: real results so far blended with the roster's projection
    played_days: dict[int, float] = defaultdict(float)
    scored: dict[int, float] = defaultdict(float)
    for g in games:
        if g.decided and not g.picked or g.live:
            d = days.get(g.week, 7) * (progress if g.live else 1.0)
            for tid, pts in ((g.home, g.home_points), (g.away, g.away_points)):
                played_days[tid] += d
                scored[tid] += pts
    near_day, per_day = {}, {}
    for tid, t in teams.items():
        healthy = projected_daily(t)
        near = (daily or {}).get(tid) or healthy
        n = played_days[tid]
        w = n / (n + PRIOR_DAYS)
        actual = scored[tid] / n if n else 0.0
        near_day[tid] = w * actual + (1 - w) * near
        per_day[tid] = w * actual + (1 - w) * healthy
    last_near = league.current_matchup + NEAR_WEEKS - 1

    base = _standing_base(league, games)
    # picked games are simulated too, for their points; only the winner is fixed
    open_games = [g for g in games if not g.decided or g.picked]
    rng = random.Random(seed)
    n_seeds = league.playoff_teams or 0
    made = defaultdict(int)
    seed_count = {tid: [0] * n_seeds for tid in teams}
    div_count = defaultdict(int)
    wins_sum = defaultdict(float)
    losses_sum = defaultdict(float)
    home_wins = defaultdict(int)
    runs = max(1, sims)
    for _ in range(runs):
        st = {tid: list(v) for tid, v in base.items()}   # wins, losses, ties, pf, pa
        h2h = defaultdict(float)
        level = {tid: rng.gauss(1.0, TEAM_SPREAD) for tid in teams}
        for g in open_games:
            rate = near_day if g.week <= last_near else per_day
            mh = rate[g.home] * days.get(g.week, 7) * level[g.home]
            ma = rate[g.away] * days.get(g.week, 7) * level[g.away]
            left = 1 - progress if g.live else 1.0
            eh, ea = mh * left, ma * left
            if g.live and live_left:   # the days left on each roster's own schedule
                eh = live_left[g.home] * level[g.home] if g.home in live_left else eh
                ea = live_left[g.away] * level[g.away] if g.away in live_left else ea
            hp = g.home_points + rng.gauss(eh, mh * SPREAD * left ** 0.5)
            ap = g.away_points + rng.gauss(ea, ma * SPREAD * left ** 0.5)
            if g.picked and (g.winner == g.home) != (hp > ap):
                hp, ap = ap, hp  # keep the points in line with the result you picked
            win = g.winner if g.picked else (g.home if hp > ap else g.away if ap > hp else 0)
            if win == g.home:
                home_wins[g.id] += 1
            _record(st, h2h, g.home, g.away, hp, ap, win)
        order, champs = seed_order(league, st, _merge_h2h(base_h2h(games), h2h), rng)
        for i, tid in enumerate(order[:n_seeds]):
            made[tid] += 1
            seed_count[tid][i] += 1
        for tid in champs:
            div_count[tid] += 1
        for tid, v in st.items():
            wins_sum[tid] += v[0]
            losses_sum[tid] += v[1]

    clinched, eliminated = certainties(league, games)
    if n_seeds and not open_games:
        # nothing left to play: only a coin flip on a perfect tie is random, so a team in (or
        # out) in every simulation is certain; the bounds above miss ties broken by points
        clinched |= {tid for tid in teams if made[tid] == runs}
        eliminated |= {tid for tid in teams if made[tid] == 0}
    odds = []
    for tid, t in teams.items():
        w, lo, ti, pf, _ = base[tid]
        odds.append(TeamOdds(
            t, int(w), int(lo), int(ti), pf, proj_wins=wins_sum[tid] / runs,
            proj_losses=losses_sum[tid] / runs, playoffs=made[tid] / runs,
            seeds=[c / runs for c in seed_count[tid]], division=div_count[tid] / runs,
            status="clinched" if tid in clinched else "eliminated" if tid in eliminated else "",
            espn=t.playoff_pct, weekly=per_day[tid] * 7))
    odds.sort(key=lambda o: (o.mean_seed, -o.playoffs, -o.proj_wins, o.team.id))
    weeks_left = sorted({g.week for g in open_games})
    return Race(odds, open_games, {g.id: home_wins[g.id] / runs for g in open_games},
                n_seeds, league.divisions, picks, runs, weeks_left, league.seeding_rule,
                me=league.my_team_id)


def _standing_base(league: League, games: list[Game]) -> dict[int, list[float]]:
    """wins, losses, ties, points for, points against from the games ESPN has decided."""
    st = {tid: [0.0, 0.0, 0.0, 0.0, 0.0] for tid in league.teams}
    for g in games:
        if g.decided and not g.picked:
            _record(st, None, g.home, g.away, g.home_points, g.away_points, g.winner)
    return st


def base_h2h(games: list[Game]) -> dict[tuple[int, int], float]:
    h2h: dict[tuple[int, int], float] = defaultdict(float)
    for g in games:
        if g.decided and not g.picked:
            _h2h(h2h, g.home, g.away, g.winner)
    return h2h


def _merge_h2h(a: dict, b: dict) -> dict:
    out = defaultdict(float, a)
    for k, v in b.items():
        out[k] += v
    return out


def _record(st, h2h, home, away, hp, ap, winner) -> None:
    st[home][3] += hp
    st[home][4] += ap
    st[away][3] += ap
    st[away][4] += hp
    if winner == home:
        st[home][0] += 1
        st[away][1] += 1
    elif winner == away:
        st[away][0] += 1
        st[home][1] += 1
    else:
        st[home][2] += 1
        st[away][2] += 1
    if h2h is not None:
        _h2h(h2h, home, away, winner)


def _h2h(h2h, home, away, winner) -> None:
    """h2h[(a, b)] = a's wins against b (a tie counts half for both)."""
    if winner == home:
        h2h[(home, away)] += 1
    elif winner == away:
        h2h[(away, home)] += 1
    else:
        h2h[(home, away)] += 0.5
        h2h[(away, home)] += 0.5


def _pct(v) -> float:
    games = v[0] + v[1] + v[2]
    return (v[0] + 0.5 * v[2]) / games if games else 0.0


def seed_order(league: League, st: dict[int, list[float]], h2h, rng: random.Random | None = None
               ) -> tuple[list[int], list[int]]:
    """Every team in seed order (division winners first when there are divisions), and the
    division winners. ``st``: team id -> [wins, losses, ties, points for, points against]."""
    rng = rng or random.Random(0)
    divs: dict[int | None, list[int]] = defaultdict(list)
    for tid, t in league.teams.items():
        divs[t.division_id].append(tid)
    flip = {tid: rng.random() for tid in st}

    def div_pct(tid) -> float:
        rivals = set(divs[league.teams[tid].division_id]) - {tid}
        won = sum(h2h.get((tid, r), 0.0) for r in rivals)
        lost = sum(h2h.get((r, tid), 0.0) for r in rivals)
        return won / (won + lost) if won + lost else 0.0

    def rank(tids: list[int]) -> list[int]:
        def key(tid):
            others = [x for x in tids if x != tid and _pct(st[x]) == _pct(st[tid])]
            won = sum(h2h.get((tid, o), 0.0) for o in others)
            lost = sum(h2h.get((o, tid), 0.0) for o in others)
            head = won / (won + lost) if won + lost else 0.5
            rule = {"H2H_RECORD": head, "TOTAL_POINTS_SCORED": st[tid][3],
                    "INTRA_DIVISION_RECORD": div_pct(tid),
                    "TOTAL_POINTS_AGAINST": st[tid][4]}.get(league.seeding_rule, head)
            return (-_pct(st[tid]), -rule, -head, -st[tid][3], -div_pct(tid), -st[tid][4], flip[tid])
        return sorted(tids, key=key)

    if len(divs) > 1 and all(k is not None for k in divs):
        champs = rank([rank(members)[0] for members in divs.values()])
        rest = rank([tid for tid in st if tid not in champs])
        return champs + rest, champs
    return rank(list(st)), []


def certainties(league: League, games: list[Game]) -> tuple[set[int], set[int]]:
    """(clinched, eliminated) team ids, certain whatever happens in the games not decided.

    Bounds on each team's final win share: the minimum loses every open game, the maximum
    wins them all. A team is out when at least ``playoff_teams`` others are sure to finish
    above its best case and it cannot win its division; it is in when it is sure to win its
    division, or when too few teams can reach its worst case to push it out (counting one
    possible division winner from below for every other division).
    """
    n = league.playoff_teams
    if not n:
        return set(), set()
    lo, hi = {}, {}
    base = _standing_base(league, games)
    open_count: dict[int, int] = defaultdict(int)
    for g in games:
        if g.picked:
            _record(base, None, g.home, g.away, 1.0 if g.winner == g.home else 0.0,
                    1.0 if g.winner == g.away else 0.0, g.winner)
        elif not g.decided:
            open_count[g.home] += 1
            open_count[g.away] += 1
    for tid, (w, lo_, ti, _, _) in base.items():
        k = open_count[tid]
        total = w + lo_ + ti + k
        lo[tid] = (w + 0.5 * ti) / total if total else 0.0
        hi[tid] = (w + k + 0.5 * ti) / total if total else 0.0
    division = {tid: t.division_id for tid, t in league.teams.items()}
    n_divs = len({d for d in division.values() if d is not None})
    other_divs = max(0, n_divs - 1) if n_divs > 1 else 0
    clinched, eliminated = set(), set()
    for tid in league.teams:
        rivals = [r for r in league.teams if r != tid and division[r] == division[tid]]
        others = [r for r in league.teams if r != tid]
        wins_division = n_divs > 1 and bool(rivals) and all(lo[tid] > hi[r] for r in rivals)
        can_be_passed = sum(1 for r in others if hi[r] >= lo[tid]) + other_divs
        if wins_division or can_be_passed < n:
            clinched.add(tid)
        can_win_div = n_divs > 1 and not any(lo[r] > hi[tid] for r in rivals)
        if sum(1 for r in others if lo[r] > hi[tid]) >= n and not can_win_div:
            eliminated.add(tid)
    return clinched, eliminated

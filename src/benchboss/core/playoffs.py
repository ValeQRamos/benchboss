"""Playoff race: who gets in, how likely, and what-if scenarios for the weeks left.

How ESPN fills the bracket: ``playoffTeamCount`` teams make it, ranked by record. In a league
with divisions the division winners are seeded first. Ties go to the league's tiebreaker
(``scheduleSettings.playoffSeedingRule``) and then, as ESPN's settings page says, to
head-to-head record, points for, division record, points against and finally a coin flip.
ESPN works the seeds out on its servers (the web app only sorts teams by
``teams[].playoffSeed``), so two details come from the settings page and have not been
checked against a real tie: more points against ranks first, and the division winners take
the top seeds even with a worse record.

``race`` plays the rest of the regular season ``sims`` times. A team's score in a week is
drawn around what it is expected to score that week: its points per day so far, blended
with what its roster projects, times the days in that week, with a spread of about 12%
(typical for weekly fantasy scores). A week that is in progress keeps the live score and
only simulates what is still to come: the days left and today's games that have not tipped
off. Two teams with nothing projected (empty rosters before the draft) play a coin flip, not
a 0-0 tie. Results you pick (``picks``: matchup id -> winning team id) are fixed in every
simulation; that is how the scenarios work.

Every count of simulated seasons is ``SIMS``: the first view, every pick in the app and the
CLI. The random draws are the same for every game whether it is picked or not (the coin of
a 0-0 game is drawn every time), so a race with picks plays the same seasons as the race
without them, and only what the picks change moves (``rerun``).

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

SIMS = 5000            # simulated seasons, everywhere: one count, so the +/- of a pick is real
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
    teams: list[TeamOdds]          # best playoff odds first, then best projected seed
    games: list[Game]              # regular-season games not played yet (picked ones included)
    home_win: dict[int, float]     # game id -> share of simulations the home team won
    away_win: dict[int, float]     # game id -> share the away team won (the rest are ties)
    playoff_teams: int
    divisions: dict[int, str]
    picks: dict[int, int]
    sims: int
    weeks_left: list[int]
    seeding_rule: str = ""
    me: int | None = None          # your team id
    baseline: Race | None = None   # the same race without the picks, when the caller ran it
    # what ``race`` was called with, so ``rerun`` can play the same seasons with other picks
    league: League | None = field(default=None, repr=False, compare=False)
    inputs: dict = field(default_factory=dict, repr=False, compare=False)

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
                       "away_win": round(self.away_win.get(g.id, 0.5), 4),
                       "picked_winner": names.get(g.winner) if g.picked else None,
                       "live": g.live} for g in self.games],
        }


# --- schedule -----------------------------------------------------------------------------------

def regular_season_weeks(league: League) -> int:
    if league.regular_season_weeks:
        return league.regular_season_weeks
    weeks = [m.period for m in league.matchups if m.playoff_tier in ("NONE", "")]
    return max(weeks) if weeks else 0


def season_games(league: League, in_season: bool = True) -> list[Game]:
    """Every regular-season matchup between two real teams, with ESPN's results.

    ``in_season``: the NBA season is under way. Before opening night ESPN's current matchup
    is already week 1, but no game of it is live yet.
    """
    last = regular_season_weeks(league)
    out, seen = [], set()
    for i, m in enumerate(league.matchups):
        if m.period > last or m.home.team_id not in league.teams or m.away.team_id not in league.teams:
            continue
        gid = m.id if m.id and m.id not in seen else 100000 + i  # ids are missing in old payloads
        seen.add(gid)
        out.append(_game(m, gid, league.current_matchup, in_season))
    return out


def _game(m: Matchup, gid: int, current: int, in_season: bool = True) -> Game:
    winner = {"HOME": m.home.team_id, "AWAY": m.away.team_id, "TIE": 0}.get(m.winner)
    if winner is None and m.period < current and (m.home.points or m.away.points):
        # a past week without ESPN's verdict: the points decide it
        hp, ap = m.home.points, m.away.points
        winner = m.home.team_id if hp > ap else m.away.team_id if ap > hp else 0
    return Game(gid, m.period, m.home.team_id, m.away.team_id, m.home.points, m.away.points,
                winner=winner, live=in_season and winner is None and m.period == current)


def parse_picks(league: League, specs: list[str]) -> dict[int, int]:
    """'Winner>Loser' or 'Winner>Loser@WEEK' (team or manager names) -> {matchup id: winner}.

    Without @WEEK it is the next game between the two that is not decided yet and not
    picked by an earlier spec, so "A>B" twice means A wins their next two games. A spec
    that would change an earlier pick of the same game is an error.
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
        free = [g for g in games if g.id not in picks]
        if not free:
            when = f" in week {week.strip()}" if week.strip() else ""
            if games:  # an earlier spec took it: one result per game, never overwritten
                raise BenchbossError(f"'{spec}': the game{'s' * (len(games) > 1)} between "
                                     f"{win.name} and {lose.name}{when} "
                                     f"{'are' if len(games) > 1 else 'is'} already picked")
            raise BenchbossError(f"{win.name} and {lose.name} have no game left to pick{when}")
        game = min(free, key=lambda g: g.week)
        picks[game.id] = win.id
    return picks


def _label(t: Team) -> str:
    return f"{t.name} {t.owner_name}"


# --- the simulation -----------------------------------------------------------------------------

def projected_daily(team: Team, spots: int | None = None) -> float:
    """A rough healthy points-per-day for a roster, for the weeks past the near term.

    Injuries are temporary, so a player on IR counts too: when he comes back he takes one of
    the ``spots`` active roster spots (every slot but IR) from the weakest player. Without
    ``spots`` it keeps as many players as are off IR now.
    """
    keep = spots or sum(1 for s in team.roster if s.slot_id != IR)
    best = sorted((s.player.proj for s in team.roster), reverse=True)[:keep]
    return sum(best) * GAMES_PER_DAY * BENCH_LOSS


def race(league: League, picks: dict[int, int] | None = None, sims: int = SIMS, *,
         daily: dict[int, float] | None = None, days_by_week: dict[int, int] | None = None,
         week_progress: float = 0.0, live_left: dict[int, float] | None = None,
         in_season: bool = True, seed: int | None = 0) -> Race:
    """Simulate the rest of the regular season.

    ``daily``: expected points per day for each team id over the next days, from its roster,
    the NBA schedule and today's injuries (the service builds it). It sets the level for this
    week and the next; later weeks use the roster's healthy projection (``projected_daily``,
    IR included), because a player out
    today is not out all season. ``days_by_week``: days in each matchup week (7 when missing);
    ``week_progress``: the share of the current week already played (0..1), today counting
    for the share of its games that have tipped off, since their points are in the live score.
    ``live_left``: the points each team id is still expected to add to this week's live
    score (the days left and today's games not tipped off yet, as the matchup projection
    counts them). Without it the live week draws its level times the share of the week left.
    ``in_season``: the NBA season is under way (before it, no week is live).

    Each simulated season also moves every team's level a little (TEAM_SPREAD) for all the
    weeks ahead: trades, injuries and waiver luck make a team better or worse for a stretch,
    not just for one week, and without it the odds of the best rosters come out too sure.

    Every game takes the same draws whether it is picked or not, so with the same ``seed``
    and ``sims`` a race with picks plays the same seasons as the race without them.
    """
    inputs = {"daily": daily, "days_by_week": days_by_week, "week_progress": week_progress,
              "live_left": live_left, "in_season": in_season, "seed": seed}
    picks = dict(picks or {})
    games = season_games(league, in_season)
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
    spots = sum(n for slot, n in league.slot_counts.items() if slot != IR)
    for tid, t in teams.items():
        healthy = projected_daily(t, spots)
        near = (daily or {}).get(tid) or healthy
        n = played_days[tid]
        w = n / (n + PRIOR_DAYS)
        actual = scored[tid] / n if n else 0.0
        near_day[tid] = w * actual + (1 - w) * near
        per_day[tid] = w * actual + (1 - w) * healthy
    last_near = league.current_matchup + NEAR_WEEKS - 1

    base = _standing_base(league, games)
    known_h2h = base_h2h(games)   # the games ESPN decided: the same in every simulation
    # picked games are simulated too, for their points; only the winner is fixed
    open_games = [g for g in games if not g.decided or g.picked]
    # each game's expected points before the season's level: its rate times its days
    plan = []
    for g in open_games:
        rate = near_day if g.week <= last_near else per_day
        week_days = days.get(g.week, 7)
        plan.append((g, rate[g.home] * week_days, rate[g.away] * week_days))
    rng = random.Random(seed)
    n_seeds = league.playoff_teams or 0
    made = defaultdict(int)
    seed_count = {tid: [0] * n_seeds for tid in teams}
    div_count = defaultdict(int)
    wins_sum = defaultdict(float)
    losses_sum = defaultdict(float)
    home_wins = defaultdict(int)
    away_wins = defaultdict(int)
    runs = max(1, sims)
    gauss, coin_flip = rng.gauss, rng.random
    for _ in range(runs):
        st = {tid: list(v) for tid, v in base.items()}   # wins, losses, ties, pf, pa
        h2h = defaultdict(float, known_h2h)
        level = {tid: gauss(1.0, TEAM_SPREAD) for tid in teams}
        for g, home_rate, away_rate in plan:
            home, away = g.home, g.away
            mh = home_rate * level[home]
            ma = away_rate * level[away]
            rest_h, rest_a = mh, ma
            if g.live:  # only what is still to come: the live score holds the rest
                rest_h = _live_rest(home, mh, progress, live_left, level)
                rest_a = _live_rest(away, ma, progress, live_left, level)
            # points drawn around what is still to come of a week expected to bring mh (ma):
            # the days score independently, so the spread grows with the square root of the
            # part left, SPREAD of the whole week and none once nothing is left
            hp = g.home_points + gauss(rest_h, SPREAD * max(0.0, mh * rest_h) ** 0.5)
            ap = g.away_points + gauss(rest_a, SPREAD * max(0.0, ma * rest_a) ** 0.5)
            # drawn for every game, used or not: picking a game never shifts the draws of
            # the games after it, so a pick only moves what it changes
            coin = coin_flip()
            if g.picked:
                win = g.winner
                if (win == home) != (hp > ap):
                    hp, ap = ap, hp  # keep the points in line with the result you picked
            elif hp != ap:
                win = home if hp > ap else away
            elif mh or ma:
                win = 0  # a real tie
            else:  # nothing projected for either team: no reason to favor one, nor a 0-0 tie
                win = home if coin < 0.5 else away
            if win == home:
                home_wins[g.id] += 1
            elif win == away:
                away_wins[g.id] += 1
            _record(st, h2h, home, away, hp, ap, win)
        order, champs = seed_order(league, st, h2h, rng)
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
    # by playoff odds, not mean seed: a team that either wins its division or misses can
    # have a better mean seed than a wildcard that is far likelier to get in
    odds.sort(key=lambda o: (-o.playoffs, o.mean_seed, -o.proj_wins, o.team.id))
    weeks_left = sorted({g.week for g in open_games})
    return Race(odds, open_games, {g.id: home_wins[g.id] / runs for g in open_games},
                {g.id: away_wins[g.id] / runs for g in open_games},
                n_seeds, league.divisions, picks, runs, weeks_left, league.seeding_rule,
                me=league.my_team_id, league=league, inputs=inputs)


def rerun(base: Race, picks: dict[int, int] | None = None) -> Race:
    """``base`` again with ``picks`` fixed: the same league, inputs, seed and number of
    seasons, so every difference from ``base`` comes from the picks. The result carries
    ``base`` as its baseline (``base`` itself when it has no picks of its own)."""
    if base.league is None:
        raise BenchbossError("this playoff race cannot be replayed: it has no league")
    out = race(base.league, picks, base.sims, **base.inputs)
    out.baseline = base.baseline if base.picks else base
    return out


def _live_rest(tid: int, week: float, progress: float, live_left: dict[int, float] | None,
               level: dict[int, float]) -> float:
    """Points a team is still expected to add to the live week: the matchup projection's
    (``live_left``) when the caller has it, else the week's share that is left."""
    if live_left is not None and tid in live_left:
        return live_left[tid] * level[tid]
    return week * (1 - progress)


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

    def tie_key(tid, tied: list[int]):
        """The tiebreakers among ``tied`` (the teams with tid's win share): the league's rule,
        head-to-head (the combined record against the others), points for, division record,
        points against (more ranks first) and the coin flip."""
        won = sum(h2h.get((tid, o), 0.0) for o in tied if o != tid)
        lost = sum(h2h.get((o, tid), 0.0) for o in tied if o != tid)
        head = won / (won + lost) if won + lost else 0.5
        rule = {"H2H_RECORD": head, "TOTAL_POINTS_SCORED": st[tid][3],
                "INTRA_DIVISION_RECORD": div_pct(tid),
                "TOTAL_POINTS_AGAINST": st[tid][4]}.get(league.seeding_rule, head)
        return (-rule, -head, -st[tid][3], -div_pct(tid), -st[tid][4], flip[tid])

    def rank(tids: list[int]) -> list[int]:
        # by win share; the tiebreakers only run inside a group of teams that share one
        # (the same order as sorting every team by the whole chain, much faster)
        share = {tid: _pct(st[tid]) for tid in tids}
        ordered = sorted(tids, key=share.__getitem__, reverse=True)
        out: list[int] = []
        i = 0
        while i < len(ordered):
            j = i + 1
            while j < len(ordered) and share[ordered[j]] == share[ordered[i]]:
                j += 1
            group = ordered[i:j]
            out += group if len(group) == 1 else sorted(group, key=lambda t: tie_key(t, group))
            i = j
        return out

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

    A division title only guarantees a spot when there are at least as many spots as
    divisions. With fewer (3 divisions, 2 spots), only the best division winners get in, as
    ``seed_order`` seeds them: a team in when it is sure to win its division and fewer than
    ``playoff_teams`` other divisions can produce a winner at or above its worst case; out
    when it cannot win its division, or when enough other divisions are sure to have a
    winner above its best case.
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
    members: dict[int | None, list[int]] = defaultdict(list)
    for tid, d in division.items():
        members[d].append(tid)
    # the same test seed_order uses to seed the division winners first
    seeded = len(members) > 1 and None not in members
    n_divs = len(members) if seeded else 0
    other_divs = n_divs - 1 if seeded else 0
    only_winners = seeded and n < n_divs   # fewer spots than divisions
    clinched, eliminated = set(), set()
    for tid in league.teams:
        rivals = [r for r in members[division[tid]] if r != tid]
        others = [r for r in league.teams if r != tid]
        sure_div = seeded and bool(rivals) and all(lo[tid] > hi[r] for r in rivals)
        can_win_div = seeded and not any(lo[r] > hi[tid] for r in rivals)
        if only_winners:
            divs = [m for d, m in members.items() if d != division[tid]]
            reach = sum(1 for m in divs if any(hi[r] >= lo[tid] for r in m))
            above = sum(1 for m in divs if max(lo[r] for r in m) > hi[tid])
            if sure_div and reach < n:
                clinched.add(tid)
            if not can_win_div or above >= n:
                eliminated.add(tid)
            continue
        can_be_passed = sum(1 for r in others if hi[r] >= lo[tid]) + other_divs
        if sure_div or can_be_passed < n:
            clinched.add(tid)
        if sum(1 for r in others if lo[r] > hi[tid]) >= n and not can_win_div:
            eliminated.add(tid)
    return clinched, eliminated

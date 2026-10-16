"""Who plays the most (and least) this matchup week, and which of those games you keep.

In daily-lineup leagues games played is volume: a player with four games this week is worth
far more than one with two, even at a lower average. A game only counts when the player is
in your lineup that day, so the workload also tracks the slot he had (or has saved) on every
day of the week.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchboss.core.calendar import SeasonCalendar
from benchboss.espn.constants import BENCH, INJURY_FACTOR, IR
from benchboss.espn.models import Player, Team


@dataclass
class Activity:
    player: Player
    games: int          # games in the whole matchup week
    games_left: int     # games from today on
    schedule: list[str]  # one entry per day: "vs LAC", "@ BOS" or ""
    slot_id: int | None = None  # today's lineup slot (BENCH, IR or a starting slot)
    # one entry per day: his lineup slot that day, None when he was not on your roster.
    # The whole list is None when the lineups are unknown (the read failed or was skipped).
    lineup: list[int | None] | None = None
    gone: bool = False  # no longer on your roster (dropped or traded away this week)

    @property
    def on_ir(self) -> bool:
        return self.slot_id == IR

    @property
    def is_starting(self) -> bool:
        return self.slot_id is not None and self.slot_id not in (BENCH, IR)

    @property
    def out(self) -> bool:
        """Out (OUT, suspended: constants.INJURY_FACTOR 0), so his games are not games he
        can play for you. ESPN only gives today's status, so it holds for the whole week."""
        return INJURY_FACTOR.get(self.player.injury_status or "", 1.0) == 0

    def starting(self, day: int) -> bool | None:
        """In your lineup on day ``day`` (index into the week)? None when the lineups are
        unknown. A day he was not on your roster counts as not starting."""
        if self.lineup is None:
            return None
        slot = self.lineup[day] if day < len(self.lineup) else None
        return slot is not None and slot not in (BENCH, IR)

    def benched(self, day: int) -> bool:
        """He has a game that day but sits on your bench: a game you lose (not when he is out)."""
        return (not self.out and day < len(self.schedule) and bool(self.schedule[day])
                and self.slot_on(day) == BENCH)

    def slot_on(self, day: int) -> int | None:
        if self.lineup is None or day >= len(self.lineup):
            return None
        return self.lineup[day]

    @property
    def games_in_lineup(self) -> int | None:
        """Games he plays in one of your starting slots this week (None when unknown)."""
        if self.lineup is None:
            return None
        return sum(1 for i, opp in enumerate(self.schedule) if opp and self.starting(i))

    def to_dict(self) -> dict:
        return {"player": self.player.name, "team": self.player.pro_team,
                "games": self.games, "games_left": self.games_left,
                "schedule": self.schedule}


def roster_activity(team: Team, cal: SeasonCalendar, periods: list[int], today_period: int,
                    lineups: dict[int, dict[int, int]] | None = None,
                    include_ir: bool = False, former: list[Player] = ()) -> list[Activity]:
    """Every rostered player, most games first, then by projection.

    ``lineups`` (period -> {player id: slot id}, see Session.lineups) fills in each player's
    slot on every day of the week. IR players are left out unless ``include_ir``. ``former``
    players (on the roster earlier in the week, gone now) come last, marked ``gone``, with
    only the games of the days they were yours.
    """
    out = []
    for spot in team.roster:
        if spot.slot_id == IR and not include_ir:
            continue
        p = spot.player
        sched = []
        for sp in periods:
            g = cal.game(p.pro_team_id, sp)
            sched.append(g.opponent(p.pro_team_id) if g else "")
        lineup = None if lineups is None else [(lineups.get(sp) or {}).get(p.id) for sp in periods]
        out.append(Activity(p, cal.games_in(p.pro_team_id, periods),
                            cal.games_in(p.pro_team_id, [x for x in periods if x >= today_period]),
                            sched, spot.slot_id, lineup))
    out.sort(key=by_games)
    if lineups is None:
        return out
    for p in former:
        lineup = [(lineups.get(sp) or {}).get(p.id) for sp in periods]
        days = [i for i, slot in enumerate(lineup) if slot is not None]
        if not days:
            continue
        sched = []
        for i, sp in enumerate(periods):
            g = cal.game(p.pro_team_id, sp) if i in days else None
            sched.append(g.opponent(p.pro_team_id) if g else "")
        out.append(Activity(p, sum(1 for x in sched if x), 0, sched, None, lineup, gone=True))
    return out


def by_games(a: Activity) -> tuple:
    """Sort key: most games this week first, then most left, then the best projection."""
    return (-a.games, -a.games_left, -a.player.proj)


def by_lineup(acts: list[Activity]) -> tuple[list[Activity], list[Activity], list[Activity]]:
    """(starters in today's slot order, bench, IR), the best projection first within a slot."""
    starters = sorted((a for a in acts if a.is_starting),
                      key=lambda a: (a.slot_id, -a.player.proj))
    bench = sorted((a for a in acts if not a.is_starting and not a.on_ir and not a.gone),
                   key=lambda a: -a.player.proj)
    ir = sorted((a for a in acts if a.on_ir), key=lambda a: -a.player.proj)
    return starters, bench, ir


def games_per_day(acts: list[Activity], days: int) -> list[int]:
    """How many of your players have a game on each day of the week.

    IR players and players who are out (``Activity.out``) do not count (they cannot play for
    you), nor does anyone on a day he was not on your roster when the lineups are known.
    """
    out = []
    for i in range(days):
        n = 0
        for a in acts:
            if a.out or i >= len(a.schedule) or not a.schedule[i]:
                continue
            slot = a.slot_id if a.lineup is None else a.slot_on(i)
            if slot is not None and slot != IR:
                n += 1
        out.append(n)
    return out


def most_and_least(acts: list[Activity], n: int = 3) -> tuple[list[Activity], list[Activity]]:
    if not acts:
        return [], []
    most = acts[:n]
    least = sorted(acts, key=lambda a: (a.games, a.games_left, a.player.proj))[:n]
    return most, least

"""Who plays the most (and least) this matchup week.

In daily-lineup leagues games played is volume: a player with four games this week is worth
far more than one with two, even at a lower average.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchboss.core.calendar import SeasonCalendar
from benchboss.espn.constants import IR
from benchboss.espn.models import Player, Team


@dataclass
class Activity:
    player: Player
    games: int          # games in the whole matchup week
    games_left: int     # games from today on
    schedule: list[str]  # one entry per day: "vs LAC", "@ BOS" or ""

    def to_dict(self) -> dict:
        return {"player": self.player.name, "team": self.player.pro_team,
                "games": self.games, "games_left": self.games_left,
                "schedule": self.schedule}


def roster_activity(team: Team, cal: SeasonCalendar, periods: list[int],
                    today_period: int) -> list[Activity]:
    """Every rostered player (IR excluded), most games first, then by projection."""
    out = []
    for spot in team.roster:
        if spot.slot_id == IR:
            continue
        p = spot.player
        sched = []
        for sp in periods:
            g = cal.game(p.pro_team_id, sp)
            sched.append(g.opponent(p.pro_team_id) if g else "")
        out.append(Activity(p, cal.games_in(p.pro_team_id, periods),
                            cal.games_in(p.pro_team_id, [x for x in periods if x >= today_period]),
                            sched))
    out.sort(key=lambda a: (-a.games, -a.games_left, -a.player.proj))
    return out


def most_and_least(acts: list[Activity], n: int = 3) -> tuple[list[Activity], list[Activity]]:
    if not acts:
        return [], []
    most = acts[:n]
    least = sorted(acts, key=lambda a: (a.games, a.games_left, a.player.proj))[:n]
    return most, least

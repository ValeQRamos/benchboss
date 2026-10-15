"""Trash scout: which free agents are worth grabbing *this week*.

"Trash" is what the free-agent pool is lovingly called. A free agent is only as good as the
points he adds to your lineup on the days he plays, so for every candidate we simulate the
rest of the matchup week:

* each remaining day, his expected points count only if they beat the weakest starter you
  would otherwise play that day (or fill an empty slot);
* the gain is computed for every possible pickup day, because a player picked up on
  Wednesday misses Monday and Tuesday;
* players on waivers cannot help until their waiver period clears;
* the suggested drop is the rostered player whose loss costs the least over the same days.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import day_value
from benchboss.core.projection import not_started
from benchboss.espn.constants import IR
from benchboss.espn.models import Player, Team


@dataclass
class TrashPick:
    player: Player
    games_left: int
    gain_by_day: dict[int, float] = field(default_factory=dict)  # pickup period -> points added
    best_day: int | None = None
    gain: float = 0.0          # points added if picked up on best_day
    drop: Player | None = None
    drop_cost: float = 0.0     # points lost this week by dropping ``drop``
    on_waivers: bool = False

    @property
    def net(self) -> float:
        return self.gain - self.drop_cost

    def to_dict(self, cal: SeasonCalendar | None = None) -> dict:
        best = None
        if self.best_day is not None:
            best = cal.date_of(self.best_day).isoformat() if cal else self.best_day
        return {"player": self.player.to_dict(), "games_left": self.games_left,
                "best_pickup_day": best, "week_gain": round(self.gain, 1),
                "drop": self.drop.name if self.drop else None,
                "drop_cost": round(self.drop_cost, 1), "net_gain": round(self.net, 1),
                "on_waivers": self.on_waivers}


def _day_tables(team: Team, cal: SeasonCalendar, periods: list[int]) -> dict[int, list[tuple[float, int]]]:
    """period -> sorted [(value, player id)] of my players with a game that day."""
    out = {}
    for sp in periods:
        vals = [(day_value(s.player, sp, cal), s.player.id) for s in team.roster
                if s.slot_id != IR and cal.plays(s.player.pro_team_id, sp)]
        out[sp] = sorted(vals, reverse=True)
    return out


def _cutoff(table: list[tuple[float, int]], starters: int, skip: int | None = None) -> float:
    vals = [v for v, pid in table if pid != skip]
    return vals[starters - 1] if len(vals) >= starters else 0.0


def _contribution(pid: int, table: list[tuple[float, int]], starters: int) -> float:
    """Points lost on one day if player ``pid`` were gone."""
    vals = [v for v, _ in table]
    ids = [p for _, p in table]
    if pid not in ids or ids.index(pid) >= starters:
        return 0.0
    replacement = vals[starters] if len(vals) > starters else 0.0
    return max(0.0, vals[ids.index(pid)] - replacement)


def weakest_link(team: Team, cal: SeasonCalendar, periods: list[int], starters: int) -> tuple[Player | None, float]:
    """The rostered player whose loss costs the fewest points over ``periods``."""
    tables = _day_tables(team, cal, periods)
    best: tuple[float, float, Player] | None = None
    for s in team.roster:
        if s.slot_id == IR:
            continue
        cost = sum(_contribution(s.player.id, tables[sp], starters) for sp in periods)
        key = (cost, s.player.proj)
        if best is None or key < best[:2]:
            best = (cost, s.player.proj, s.player)
    return (best[2], best[0]) if best else (None, 0.0)


def scout(free_agents: list[Player], team: Team, cal: SeasonCalendar, periods: list[int],
          today_period: int, starters: int, waiver_days: int = 1,
          now: dt.datetime | None = None) -> list[TrashPick]:
    """Rank free agents by net points added from their best pickup day to the end of the week.

    ``now`` (timezone aware) makes today count only for free agents whose game has not tipped
    off yet. The best day maximizes gain minus drop cost; ties go to the earlier day, because
    waiting risks losing the player to someone else.
    """
    remaining = [p for p in periods if p >= today_period]
    tables = _day_tables(team, cal, remaining)
    drop, _ = weakest_link(team, cal, remaining, starters)
    drop_cost = {d: sum(_contribution(drop.id, tables[sp], starters) for sp in remaining if sp >= d)
                 for d in remaining} if drop else {}
    picks = []
    for fa in free_agents:
        on_waivers = fa.status == "WAIVERS"
        first = today_period + (waiver_days if on_waivers else 0)
        gains: dict[int, float] = {}
        for d in [p for p in remaining if p >= first]:
            g = 0.0
            for sp in [p for p in remaining if p >= d]:
                if not cal.plays(fa.pro_team_id, sp):
                    continue
                if sp == today_period and not not_started(cal, fa.pro_team_id, sp, now):
                    continue
                cut = _cutoff(tables[sp], starters, skip=drop.id if drop else None)
                g += max(0.0, day_value(fa, sp, cal) - cut)
            gains[d] = g
        playable = [sp for sp in remaining if sp >= first and cal.plays(fa.pro_team_id, sp)
                    and (sp != today_period or not_started(cal, fa.pro_team_id, sp, now))]
        pick = TrashPick(fa, len(playable), gains, on_waivers=on_waivers)
        if gains:
            pick.best_day = max(gains, key=lambda d: (gains[d] - drop_cost.get(d, 0.0), -d))
            pick.gain = gains[pick.best_day]
            if drop:
                pick.drop = drop
                pick.drop_cost = drop_cost.get(pick.best_day, 0.0)
        picks.append(pick)
    picks.sort(key=lambda p: (-p.net, -p.player.proj))
    return picks

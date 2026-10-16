"""Trash scout: which free agents are worth grabbing *this week*.

"Trash" is what the free-agent pool is lovingly called. A free agent is only as good as the
points he adds to your lineup on the days he plays, so for every candidate we simulate the
rest of the matchup week:

* each remaining day, his expected points count only if they beat the weakest starter you
  would otherwise play that day (or fill an empty slot);
* the gain is computed for every possible pickup day, because a player picked up on
  Wednesday misses Monday and Tuesday;
* players on waivers cannot help until their waiver period clears, and in leagues whose
  rosters lock at the day's first tip-off an add made after it only counts from tomorrow;
* the suggested drop is the rostered player whose loss costs the least over the same days,
  among those projected below the free agent (never a better player for a streamer) and
  within the league's position limits. With an open roster spot nobody has to go.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import day_value
from benchboss.core.projection import not_started
from benchboss.espn.constants import IR, ROSTER_LOCK_FIRST_GAME
from benchboss.espn.models import Player, Team


@dataclass
class TrashPick:
    player: Player
    games_left: int            # games from best_day on in which he adds points (game_days)
    gain_by_day: dict[int, float] = field(default_factory=dict)  # pickup period -> points added
    best_day: int | None = None
    gain: float = 0.0          # points added if picked up on best_day
    drop: Player | None = None
    drop_cost: float = 0.0     # points lost this week by dropping ``drop``
    on_waivers: bool = False
    needs_drop: bool = True    # no open spot, so someone has to go
    drop_projects_higher: bool = False  # the drop scores more per game: a one-week stream
    # every day he has a game that still counts (not tipped off yet) -> points he adds that
    # day; 0 when he is no better than your weakest starter, so he would sit on your bench
    added: dict[int, float] = field(default_factory=dict)

    @property
    def net(self) -> float:
        return self.gain - self.drop_cost

    def _from_grab(self) -> list[int]:
        return [] if self.best_day is None else sorted(d for d in self.added if d >= self.best_day)

    def game_days(self) -> list[int]:
        """The days he plays for you, from the grab day to the end of the week: ``games_left``
        of them, the games in which he adds points."""
        return [d for d in self._from_grab() if self.added[d] > 0]

    def bench_days(self) -> list[int]:
        """The days from the grab day on when he has a game but adds nothing: he would sit
        on your bench."""
        return [d for d in self._from_grab() if self.added[d] <= 0]

    def to_dict(self, cal: SeasonCalendar | None = None) -> dict:
        best = None
        if self.best_day is not None:
            best = cal.date_of(self.best_day).isoformat() if cal else self.best_day
        days = None
        if cal is not None:
            days = [cal.date_of(d).isoformat() for d in self.game_days()]
        return {"player": self.player.to_dict(), "games_left": self.games_left,
                "game_days": days,
                "best_pickup_day": best, "week_gain": round(self.gain, 1),
                "drop": self.drop.name if self.drop else None,
                "drop_cost": round(self.drop_cost, 1), "net_gain": round(self.net, 1),
                "on_waivers": self.on_waivers, "needs_drop": self.needs_drop,
                "drop_projects_higher": self.drop_projects_higher}


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


def weakest_link(team: Team, cal: SeasonCalendar, periods: list[int], starters: int,
                 allowed: Callable[[Player], bool] | None = None,
                 tables: dict[int, list[tuple[float, int]]] | None = None,
                 ) -> tuple[Player | None, float]:
    """The rostered player whose loss costs the fewest points over ``periods``.

    ``allowed`` limits the choice (None comes back when nobody passes it).
    """
    tables = tables or _day_tables(team, cal, periods)
    best: tuple[float, float, Player] | None = None
    for s in team.roster:
        if s.slot_id == IR or (allowed is not None and not allowed(s.player)):
            continue
        cost = sum(_contribution(s.player.id, tables[sp], starters) for sp in periods)
        key = (cost, s.player.proj)
        if best is None or key < best[:2]:
            best = (cost, s.player.proj, s.player)
    return (best[2], best[0]) if best else (None, 0.0)


def roster_has_room(team: Team, slot_counts: dict[int, int]) -> bool:
    """True when fewer players than the active spots (starters plus bench) are rostered."""
    active = sum(1 for s in team.roster if s.slot_id != IR)
    return active < sum(n for sl, n in slot_counts.items() if sl != IR)


def fits_limits(team: Team, limits: dict[int, int] | None, add: Player,
                drop: Player | None = None) -> bool:
    """True when adding ``add`` (and releasing ``drop``) keeps the league's position limits,
    for example at most four players whose default position is C."""
    limit = (limits or {}).get(add.position_id, -1)
    if limit is None or limit < 0 or (drop is not None and drop.position_id == add.position_id):
        return True
    return sum(1 for s in team.roster if s.player.position_id == add.position_id) < limit


def scout(free_agents: list[Player], team: Team, cal: SeasonCalendar, periods: list[int],
          today_period: int, starters: int, waiver_days: int = 1,
          now: dt.datetime | None = None, slot_counts: dict[int, int] | None = None,
          roster_lock: str = "", position_limits: dict[int, int] | None = None,
          ) -> list[TrashPick]:
    """Rank free agents by net points added from their best pickup day to the end of the week.

    ``now`` (timezone aware) makes today count only for free agents whose game has not tipped
    off yet; with ``roster_lock`` FIRSTGAME_SCORINGPERIOD, today stops counting for everyone
    once the day's first game has tipped off. ``slot_counts`` lets an open roster spot skip
    the drop, and ``position_limits`` keeps the suggested drop legal. The drop is the
    cheapest one this week among players projected lower than the free agent; when nobody
    projects lower it is the lowest projected player who can legally go, and the pick is
    flagged ``drop_projects_higher`` (a one-week stream, not an upgrade). The best day
    maximizes gain minus drop cost; ties go to the earlier day, because waiting risks losing
    the player to someone else.
    """
    remaining = [p for p in periods if p >= today_period]
    tables = _day_tables(team, cal, remaining)
    tip = cal.first_tip(today_period)
    locked_today = (roster_lock == ROSTER_LOCK_FIRST_GAME and now is not None
                    and tip is not None and now >= tip)
    full = slot_counts is None or not roster_has_room(team, slot_counts)
    picks = []
    for fa in free_agents:
        on_waivers = fa.status == "WAIVERS"
        first = today_period + max(waiver_days if on_waivers else 0, 1 if locked_today else 0)
        days = [p for p in remaining if p >= first]
        needs_drop = full or not fits_limits(team, position_limits, fa)
        drop, higher = None, False
        if needs_drop:
            drop, _ = weakest_link(
                team, cal, days, starters, tables=tables,
                allowed=lambda y, fa=fa: (y.proj < fa.proj
                                          and fits_limits(team, position_limits, fa, y)))
            if drop is None:
                legal = [s.player for s in team.roster if s.slot_id != IR
                         and fits_limits(team, position_limits, fa, s.player)]
                drop = min(legal, key=lambda y: y.proj, default=None)
                higher = drop is not None
        skip = drop.id if drop else None
        playable = [sp for sp in days if cal.plays(fa.pro_team_id, sp)
                    and (sp != today_period or not_started(cal, fa.pro_team_id, sp, now))]
        added = {sp: max(0.0, day_value(fa, sp, cal) - _cutoff(tables[sp], starters, skip))
                 for sp in playable}
        lost = {sp: _contribution(drop.id, tables[sp], starters) for sp in days} if drop else {}
        gains = {d: sum((v for sp, v in added.items() if sp >= d), 0.0) for d in days}
        drop_cost = {d: sum((v for sp, v in lost.items() if sp >= d), 0.0) for d in days}
        pick = TrashPick(fa, 0, gains, on_waivers=on_waivers, needs_drop=needs_drop,
                         drop_projects_higher=higher, added=added)
        if gains:
            pick.best_day = max(gains, key=lambda d: (gains[d] - drop_cost.get(d, 0.0), -d))
            pick.gain = gains[pick.best_day]
            pick.games_left = len(pick.game_days())  # a game on your bench adds no volume
            pick.drop = drop
            pick.drop_cost = drop_cost.get(pick.best_day, 0.0)
        picks.append(pick)
    picks.sort(key=lambda p: (-p.net, -p.player.proj))
    return picks

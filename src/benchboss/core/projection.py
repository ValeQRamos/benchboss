"""Matchup outlook: live score plus a projection for the days that are left."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from benchboss.core.calendar import SeasonCalendar
from benchboss.core.lineup import day_value
from benchboss.espn.constants import IR
from benchboss.espn.models import League, Team


def not_started(cal: SeasonCalendar, pro_team_id: int, period: int,
                now: dt.datetime | None) -> bool:
    """True when the team's game that day has not tipped off yet (or we do not know the time)."""
    g = cal.game(pro_team_id, period)
    return g is not None and (now is None or g.start > now)


def week_projection(team: Team, periods: list[int], cal: SeasonCalendar, starters: int,
                    today_period: int | None = None,
                    now: dt.datetime | None = None) -> tuple[float, int]:
    """Points and games still to come from ``team`` over ``periods``.

    Each day the ``starters`` best players with a game play (a close, fast approximation of
    the real lineup that ignores position slots). On ``today_period`` only games that have not
    tipped off yet count, because the rest is already in the live score. Players projected at
    zero (out, suspended) do not count as games. Returns (points, games).
    """
    total, games = 0.0, 0
    for sp in periods:
        vals = []
        for s in team.roster:
            p = s.player
            if s.slot_id == IR or not cal.plays(p.pro_team_id, sp):
                continue
            if sp == today_period and not not_started(cal, p.pro_team_id, sp, now):
                continue
            vals.append(day_value(p, sp, cal))
        top = sorted(vals, reverse=True)[:starters]
        total += sum(top)
        games += sum(1 for v in top if v > 0)
    return total, games


@dataclass
class SideOutlook:
    team: Team
    points: float
    projected: float
    games_left: int


@dataclass
class MatchupOutlook:
    matchup_id: int
    periods: list[int]
    remaining: list[int]
    me: SideOutlook
    opponent: SideOutlook | None

    @property
    def leading(self) -> bool:
        return bool(self.opponent) and self.me.points > self.opponent.points

    @property
    def projected_win(self) -> bool:
        return bool(self.opponent) and self.me.projected > self.opponent.projected

    def to_dict(self) -> dict:
        def side(s: SideOutlook | None):
            if not s:
                return None
            return {"team": s.team.name, "points": round(s.points, 1),
                    "projected_final": round(s.projected, 1), "games_left": s.games_left}
        return {"matchup": self.matchup_id, "days": len(self.periods),
                "days_left": len(self.remaining), "me": side(self.me),
                "opponent": side(self.opponent)}


def matchup_outlook(league: League, cal: SeasonCalendar, today_period: int,
                    now: dt.datetime | None = None) -> MatchupOutlook:
    """``now`` (timezone aware) drops today's games that already tipped off: their points are
    in the live score. Without it every game of today counts as still to come."""
    mid = league.current_matchup
    periods = cal.matchup_periods(mid, league.matchup_periods)
    remaining = [p for p in periods if p >= today_period]
    m = league.matchup_for(league.my_team_id, mid)
    sides = m.side_of(league.my_team_id) if m else None
    mine_pts = sides[0].points if sides else 0.0
    me_proj, me_games = week_projection(league.me, remaining, cal, league.starter_slots,
                                        today_period, now)
    me = SideOutlook(league.me, mine_pts, mine_pts + me_proj, me_games)
    opp = None
    if sides and sides[1].team_id in league.teams:
        t = league.teams[sides[1].team_id]
        p, g = week_projection(t, remaining, cal, league.starter_slots, today_period, now)
        opp = SideOutlook(t, sides[1].points, sides[1].points + p, g)
    return MatchupOutlook(mid, periods, remaining, me, opp)

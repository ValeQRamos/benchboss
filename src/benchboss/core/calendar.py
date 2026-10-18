"""The season calendar: scoring periods (days), matchup weeks and NBA games.

ESPN basketball scores by day: scoring period 1 is the first day of the NBA regular season,
2 the next calendar day, and so on. Head-to-head matchups group those days into weeks: the
first runs from opening night to the first Sunday, the rest run Monday to Sunday, and the
week that contains the All-Star break is merged with the next one. The league setting
``scheduleSettings.matchupPeriods`` maps each matchup id to the calendar weeks it covers.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from benchboss.espn.constants import PRO_TEAM

_ET = dt.timezone(dt.timedelta(hours=-5))


@dataclass(frozen=True)
class Game:
    period: int
    start: dt.datetime           # the scheduled tip-off; format it with clock(), never directly
    home_id: int
    away_id: int
    tbd: bool = False            # startTimeTBD: the time is a placeholder
    valid_for_locking: bool = True  # validForLocking: ESPN locks lineups by this game

    def opponent(self, team_id: int) -> str:
        other = self.away_id if team_id == self.home_id else self.home_id
        return ("vs " if team_id == self.home_id else "@ ") + PRO_TEAM.get(other, "?")


def clock(when: dt.datetime, tz: dt.tzinfo | None = None) -> str:
    """ "7:00 PM": a tip time on the clock of ``tz`` (pass ``session.now.tzinfo``; None means
    this computer's zone). Game.start keeps a fixed UTC-5 offset: right for comparing times,
    an hour early on a clock during daylight saving time, so never format it directly."""
    local = when.astimezone(tz) if tz else when.astimezone()
    return f"{local:%I:%M %p}".lstrip("0")


class SeasonCalendar:
    def __init__(self, day_one: dt.date, games: dict[int, dict[int, Game]], final_period: int):
        self.day_one = day_one
        self.games = games              # pro team id -> {scoring period -> Game}
        self.final_period = final_period
        self._weeks: list[tuple[dt.date, dt.date]] | None = None

    @classmethod
    def from_raw(cls, raw: dict, final_period: int | None = None) -> SeasonCalendar:
        """Build from the season view ``proTeamSchedules_wl``."""
        games: dict[int, dict[int, Game]] = {}
        first: list[int] = []
        last = 0
        for team in (raw.get("settings") or {}).get("proTeams") or []:
            for items in (team.get("proGamesByScoringPeriod") or {}).values():
                for g in items:
                    sp = g["scoringPeriodId"]
                    start = dt.datetime.fromtimestamp(g["date"] / 1000, tz=_ET)
                    games.setdefault(team["id"], {})[sp] = Game(
                        sp, start, g.get("homeProTeamId", 0), g.get("awayProTeamId", 0),
                        tbd=bool(g.get("startTimeTBD")),
                        valid_for_locking=g.get("validForLocking") is not False)
                    last = max(last, sp)
                    if sp == 1:
                        first.append(g["date"])
        if not first:
            raise ValueError("the NBA schedule has no games on scoring period 1")
        day_one = dt.datetime.fromtimestamp(min(first) / 1000, tz=_ET).date()
        return cls(day_one, games, final_period or last)

    # --- days ----------------------------------------------------------------------------------

    def date_of(self, period: int) -> dt.date:
        return self.day_one + dt.timedelta(days=period - 1)

    def period_of(self, day: dt.date) -> int:
        return (day - self.day_one).days + 1

    def today_period(self, today: dt.date | None = None) -> int:
        """Scoring period for today, clamped to the season."""
        sp = self.period_of(today or dt.date.today())
        return max(1, min(sp, self.final_period))

    def plays(self, pro_team_id: int, period: int) -> bool:
        return period in self.games.get(pro_team_id, {})

    def game(self, pro_team_id: int, period: int) -> Game | None:
        return self.games.get(pro_team_id, {}).get(period)

    def first_tip(self, period: int) -> dt.datetime | None:
        """Start time of the first NBA game of a day (None when nobody plays)."""
        starts = [t[period].start for t in self.games.values() if period in t]
        return min(starts) if starts else None

    def games_in(self, pro_team_id: int, periods) -> int:
        g = self.games.get(pro_team_id, {})
        return sum(1 for p in periods if p in g)

    # --- weeks ---------------------------------------------------------------------------------

    def weeks(self) -> list[tuple[dt.date, dt.date]]:
        """Calendar weeks in matchup-id order, with the All-Star week merged into the next."""
        if self._weeks is not None:
            return self._weeks
        last_day = self.date_of(self.final_period)
        cal: list[list[dt.date]] = []
        start = self.day_one
        while start <= last_day:
            end = min(last_day, start + dt.timedelta(days=6 - start.weekday()))
            cal.append([start, end])
            start = end + dt.timedelta(days=1)
        any_game = {p for team in self.games.values() for p in team}
        streak, cut = 0, None
        for sp in range(1, self.final_period + 1):
            day = self.date_of(sp)
            streak = 0 if sp in any_game else streak + 1
            if streak == 3 and day.month in (1, 2, 3):  # 3+ days with no NBA = All-Star break
                cut = day - dt.timedelta(days=2)
                break
        if cut:
            i = next(i for i, (a, b) in enumerate(cal) if a <= cut <= b)
            if i + 1 < len(cal):
                cal[i][1] = cal[i + 1][1]
                del cal[i + 1]
        self._weeks = [(a, b) for a, b in cal]
        return self._weeks

    def matchup_periods(self, matchup_id: int, mapping: dict[int, list[int]] | None = None) -> list[int]:
        """Scoring periods (days) covered by a head-to-head matchup."""
        weeks = self.weeks()
        ids = (mapping or {}).get(matchup_id) or [matchup_id]
        spans = [weeks[i - 1] for i in ids if 0 < i <= len(weeks)]
        if not spans:
            return []
        start, end = spans[0][0], spans[-1][1]
        return list(range(self.period_of(start), self.period_of(end) + 1))

    def matchup_of(self, period: int, mapping: dict[int, list[int]] | None = None) -> int:
        """Matchup id that contains a scoring period."""
        for mid in sorted(mapping or {}) or range(1, len(self.weeks()) + 1):
            if period in self.matchup_periods(mid, mapping):
                return mid
        return 0

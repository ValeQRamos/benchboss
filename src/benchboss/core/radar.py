"""The trash radar: who just played his way onto your list. Pure logic, no I/O.

Fast signals come from the box scores of games that just ended (boxscores.Line): a big night,
a jump in minutes, a start from the bench. Slow ones come from ESPN's stat splits, which
catch up by the next morning: a week of more minutes, a week of better form, a rise in % rostered.
Every signal adds a weight; a player with none is left out.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from benchboss.boxscores import Line
from benchboss.espn.constants import GS
from benchboss.espn.models import Player

MIN_MINUTES = 12      # a cameo says nothing: lines under this are never candidates
BIG_MINUTES = 15      # a big night needs real minutes (garbage time scores too)
BIG_RATIO = 1.5       # ... and fantasy points this many times his average
BIG_FLOOR = 20.0      # ... and at least this many
JUMP_MINUTES = 8.0    # minutes above his season average that count as a bigger role
JUMP_FLOOR = 22.0     # ... and at least this many
STARTS_BELOW = 0.5    # a start counts when he starts under this share of his games
TREND_MINUTES = 5.0   # last 7 days: minutes above his season average
FORM_RATIO, FORM_GAIN = 1.25, 4.0   # last 7 days: points per game above his season average
RISING = 5.0          # % rostered gained in a week
CANDIDATES = 100      # players fetched from ESPN at most

LABEL = {"big_night": "Big night", "started": "Started", "minutes": "More minutes",
         "trend": "Role growing", "form": "Hot week", "rising": "Rising"}
WEIGHT = {"big_night": 3.0, "started": 3.0, "minutes": 3.0, "trend": 2.0, "form": 1.0,
          "rising": 1.0}
FAST = ("big_night", "started", "minutes")   # from last night's box score


@dataclass
class Reason:
    kind: str
    text: str

    @property
    def label(self) -> str:
        return LABEL[self.kind]

    @property
    def weight(self) -> float:
        return WEIGHT[self.kind]

    @property
    def fast(self) -> bool:
        return self.kind in FAST


@dataclass
class Pick:
    player: Player
    reasons: list[Reason] = field(default_factory=list)
    line: Line | None = None      # the newest game he played in the box scores read
    fpts: float | None = None     # his fantasy points in it

    @property
    def score(self) -> float:
        return sum(r.weight for r in self.reasons)

    def to_dict(self) -> dict:
        p = self.player
        out = {"id": p.id, "name": p.name, "team": p.pro_team, "positions": p.positions or p.position,
               "status": p.status, "injury": p.injury or None, "owned": round(p.owned, 1),
               "owned_change": round(p.owned_change, 2), "score": self.score,
               "reasons": [{"kind": r.kind, "label": r.label, "text": r.text, "fast": r.fast}
                           for r in self.reasons],
               "last_game": None}
        if self.line is not None:
            ln = self.line
            out["last_game"] = {"day": ln.day.isoformat(), "minutes": round(ln.minutes, 1),
                                "started": ln.starter, "fpts": round(self.fpts or 0.0, 1)}
        return out


def candidates(lines: Iterable[Line], rostered: set[int], scoring: dict[int, float],
               limit: int = CANDIDATES) -> list[int]:
    """The players worth asking ESPN about: not on a team in this league, with real minutes in
    a game, best fantasy night first."""
    best: dict[int, float] = {}
    for ln in lines:
        if ln.player_id not in rostered and ln.minutes >= MIN_MINUTES:
            best[ln.player_id] = max(best.get(ln.player_id, 0.0), ln.fpts(scoring))
    return sorted(best, key=lambda pid: -best[pid])[:limit]


def _starts(season) -> float | None:
    """The share of his games he started this season, None without the numbers."""
    if season is None or not season.gp:
        return None
    started = season.totals.get(GS)
    if started is None and season.avg.get(GS) is not None:
        started = season.avg[GS] * season.gp
    return None if started is None else started / season.gp


def _fast(p: Player, mine: list[Line],
          scoring: dict[int, float]) -> tuple[list[Reason], Line | None, float | None]:
    """What the box scores say, from his newest game (starts, minutes) and his best one."""
    if not mine:
        return [], None, None
    newest = max(mine, key=lambda ln: ln.day)
    best = max(mine, key=lambda ln: ln.fpts(scoring))
    season = p.split("season")
    average = (season.fpts if season else None) or p.avg or 0.0
    mpg = season.mpg if season else None
    reasons = []
    f = best.fpts(scoring)
    if best.minutes >= BIG_MINUTES and f >= max(BIG_FLOOR, BIG_RATIO * average):
        reasons.append(Reason("big_night", f"{f:.1f} fpts in {best.minutes:.0f} min"
                              + (f" (averages {average:.1f})" if average else "")))
    if newest.starter:
        share = _starts(season)
        if share is not None and share < STARTS_BELOW:
            reasons.append(Reason("started", f"in the lineup, though he starts only {share:.0%} "
                                              "of the time"))
    if mpg and newest.minutes >= max(JUMP_FLOOR, mpg + JUMP_MINUTES):
        reasons.append(Reason("minutes", f"{newest.minutes:.0f} min (averages {mpg:.0f})"))
    return reasons, newest, newest.fpts(scoring)


def _slow(p: Player) -> list[Reason]:
    """What the stat splits say: the last 7 days against the season, and the ownership trend."""
    reasons = []
    season, l7 = p.split("season"), p.split("l7")
    if season and l7 and l7.gp >= 2:
        if l7.mpg and season.mpg and l7.mpg - season.mpg >= TREND_MINUTES:
            reasons.append(Reason("trend", f"{l7.mpg:.0f} min a game this week, {season.mpg:.0f} "
                                           "all season"))
        if l7.fpts >= season.fpts * FORM_RATIO and l7.fpts - season.fpts >= FORM_GAIN:
            reasons.append(Reason("form", f"{l7.fpts:.1f} fpts a game this week, "
                                          f"{season.fpts:.1f} all season"))
    if p.owned_change >= RISING:
        reasons.append(Reason("rising", f"+{p.owned_change:.1f}% rostered this week"))
    return reasons


def build(lines: Iterable[Line], players: Iterable[Player], scoring: dict[int, float]) -> list[Pick]:
    """The free agents with a signal, strongest first (ties: the best fantasy night, then the
    biggest rise in ownership)."""
    by_player: dict[int, list[Line]] = {}
    for ln in lines:
        by_player.setdefault(ln.player_id, []).append(ln)
    picks = []
    for p in players:
        if p.status not in ("FREEAGENT", "WAIVERS"):
            continue
        reasons, line, fpts = _fast(p, by_player.get(p.id, []), scoring)
        pick = Pick(p, reasons + _slow(p), line, fpts)
        if pick.reasons:
            picks.append(pick)
    return sorted(picks, key=lambda k: (-k.score, -(k.fpts or 0.0), -k.player.owned_change))

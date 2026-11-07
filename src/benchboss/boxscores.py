"""Box scores of finished NBA games, from ESPN's public scoreboard and game summary.

No cookies. A player's id here is his fantasy id, so a line joins straight onto a Player. Every
request goes through ``_get``: another host, a proxy or a fixture replaces that one function
and nothing else. The radar (core/radar.py) reads these the morning after, or minutes after
the final buzzer: the box score is on the summary as soon as the game ends.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from benchboss.espn.client import http
from benchboss.espn.constants import (
    AST,
    BLK,
    DD,
    DREB,
    FGA,
    FGM,
    FTA,
    FTM,
    MIN,
    OREB,
    PTS,
    REB,
    STL,
    TD,
    TO,
    TPA,
    TPM,
)

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
PF = 9  # personal fouls: not in constants, ESPN's own stat id
COUNTS = {"PTS": PTS, "REB": REB, "AST": AST, "STL": STL, "BLK": BLK, "TO": TO, "OREB": OREB,
          "DREB": DREB, "PF": PF}
MADE = {"FG": (FGM, FGA), "3PT": (TPM, TPA), "FT": (FTM, FTA)}  # "7-12" -> made, attempted
THREADS = 4


def _get(path: str, **params) -> dict:
    """The one request to ESPN's public NBA feed."""
    return http(f"{SITE}/{path}", params=params or None)


@dataclass(frozen=True)
class Line:
    """One player's game: minutes, whether he started, and the box score keyed by the fantasy
    stat ids of espn/constants (PTS, REB, FGM...)."""
    player_id: int
    name: str
    team: str       # the NBA team's abbreviation, as the scoreboard spells it
    game_id: str
    day: dt.date
    starter: bool
    stats: dict[int, float] = field(default_factory=dict)

    @property
    def minutes(self) -> float:
        return self.stats.get(MIN, 0.0)

    def fpts(self, scoring: dict[int, float]) -> float:
        """Fantasy points in this league's scoring (``League.scoring``: stat id -> points)."""
        return sum(v * scoring.get(k, 0.0) for k, v in self.stats.items())


def finished_games(day: dt.date) -> list[str]:
    """The ids of the games that ended on ``day`` (a date on the Eastern clock)."""
    events = _get("scoreboard", dates=day.strftime("%Y%m%d")).get("events") or []
    return [str(e["id"]) for e in events
            if ((e.get("status") or {}).get("type") or {}).get("completed")]


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _stats(labels: list[str], values: list[str]) -> dict[int, float] | None:
    """The stat ids of one row of the box score; None for a player with no minutes."""
    row = dict(zip(labels, values, strict=False))
    minutes = _num(row.get("MIN"))
    if minutes <= 0:
        return None
    out = {MIN: minutes}
    for label, stat in COUNTS.items():
        out[stat] = _num(row.get(label))
    for label, (made, attempted) in MADE.items():
        m, _, a = str(row.get(label) or "0-0").partition("-")
        out[made], out[attempted] = _num(m), _num(a)
    big = sum(1 for stat in (PTS, REB, AST, STL, BLK) if out[stat] >= 10)
    out[DD], out[TD] = float(big >= 2), float(big >= 3)
    return out


def parse_summary(summary: dict, game_id: str, day: dt.date) -> list[Line]:
    """Every player who played in a game's summary. Players who did not play, and rows ESPN
    has not filled in yet, are left out."""
    out = []
    for team in (summary.get("boxscore") or {}).get("players") or []:
        abbrev = (team.get("team") or {}).get("abbreviation", "")
        for group in team.get("statistics") or []:
            labels = group.get("labels") or []
            for a in group.get("athletes") or []:
                athlete = a.get("athlete") or {}
                stats = None if a.get("didNotPlay") else _stats(labels, a.get("stats") or [])
                try:
                    pid = int(athlete["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if stats is not None:
                    out.append(Line(pid, athlete.get("displayName", ""), abbrev, game_id, day,
                                    bool(a.get("starter")), stats))
    return out


def day_lines(day: dt.date) -> list[Line]:
    """The lines of every game that ended on ``day``, one summary request per game."""
    ids = finished_games(day)
    if not ids:
        return []
    with ThreadPoolExecutor(min(THREADS, len(ids))) as pool:
        summaries = list(pool.map(lambda gid: _get("summary", event=gid), ids))
    return [ln for gid, s in zip(ids, summaries, strict=True) for ln in parse_summary(s, gid, day)]


__all__ = ["Line", "day_lines", "finished_games", "parse_summary"]

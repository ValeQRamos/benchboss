"""Auto-swap marks: the players you checked so benchboss starts them when they turn healthy.

One file per league, store.marks_path(league id) (leagues/<id>/marks.json; in memory for
the demo, Session.local_state):

    {"v": 1, "league": 12345, "season": 2027, "paused": false,
     "marks": {"<player id>": {"name": "Dyson Daniels", "mode": "auto",
                               "added": "2026-10-20T15:02:11-05:00", "until": "2026-10-25",
                               "baseline": "DAY_TO_DAY", "origin": "tui"}}}

    mode      "auto" (start him when he turns healthy, benching the lowest valued starter
              whose game has not started) or "notify" (tell me, change nothing)
    until     the last day the mark is active: the end of the matchup week by default,
              today with ``--today``; expired marks are dropped
    baseline  his status when he was marked: the first read compares against it
    origin    "cli" or "tui"

A file for another season counts as no marks. A missing file is no marks; a damaged one
is no marks too (fail closed) and the monitor says so. Every change is a fresh read, one
change and a write, inside store.locked, and goes to the lineup log ("arm", "disarm",
"pause", "resume"). Arming needs the user's yes (the CLI asks, the app asks for a second
enter); disarming, clearing and pausing never ask, because they lower the risk, and they
work with ESPN down (nothing here reads ESPN).

    MarkStore(session)
        .load() -> Marks          fresh read; .marks {id: Mark}, .paused, .error
        .arm(player, mode="auto", until=None, origin="cli") -> Mark
        .disarm(player_id, origin="cli") -> bool
        .clear(origin="cli") -> int
        .set_paused(paused, origin="cli") -> None
"""

from __future__ import annotations

import contextlib
import datetime as dt
import shutil
from dataclasses import dataclass, field

from benchboss import lineup_log, store
from benchboss.core.autoswap import known_status
from benchboss.errors import BenchbossError
from benchboss.espn.models import Player

VERSION = 1
MODES = ("auto", "notify")
ORIGINS = ("cli", "tui")


@dataclass
class Mark:
    player_id: int
    name: str
    mode: str = "auto"
    added: str = ""      # ISO time
    until: str = ""      # ISO date: the last day it counts
    baseline: str = ""   # his status when he was marked
    origin: str = "cli"

    @property
    def auto(self) -> bool:
        return self.mode == "auto"

    def active_on(self, day: dt.date) -> bool:
        return not self.until or self.until >= day.isoformat()

    def to_dict(self) -> dict:
        return {"name": self.name, "mode": self.mode, "added": self.added, "until": self.until,
                "baseline": self.baseline, "origin": self.origin}

    @classmethod
    def from_dict(cls, pid: int, d: dict) -> Mark:
        mode = d.get("mode") if d.get("mode") in MODES else "notify"  # unknown: never writes
        return cls(pid, str(d.get("name") or pid), mode, str(d.get("added") or ""),
                   str(d.get("until") or ""), str(d.get("baseline") or ""),
                   str(d.get("origin") or "cli"))


@dataclass
class Marks:
    marks: dict[int, Mark] = field(default_factory=dict)
    paused: bool = False
    error: str = ""  # the file could not be read: no marks at all (fail closed)

    def get(self, pid: int) -> Mark | None:
        return self.marks.get(pid)

    def auto_ids(self) -> set[int]:
        return {pid for pid, m in self.marks.items() if m.auto}

    def notify_ids(self) -> set[int]:
        return {pid for pid, m in self.marks.items() if not m.auto}


def week_end(session) -> dt.date:
    """The last day of the current matchup week (today when the season is over)."""
    today = session.today
    with contextlib.suppress(BenchbossError, ValueError):
        periods = session.matchup_periods()
        if periods:
            return max(today, session.calendar.date_of(max(periods)))
    return today


class MarkStore:
    def __init__(self, session):
        self.session = session
        self.league_id = session.client.league_id
        self.season = session.client.season
        self.path = store.marks_path(self.league_id)
        self.memory = session.local_state

    def _fresh(self) -> dict:
        return {"v": VERSION, "league": self.league_id, "season": self.season, "paused": False,
                "marks": {}}

    def _read(self) -> tuple[dict, str]:
        """The file as a dict and "" , or a fresh dict and why the file cannot be used."""
        try:
            raw = store.read_json(self.path, None, memory=self.memory)
        except BenchbossError as e:
            return self._fresh(), str(e)
        if raw is None:
            return self._fresh(), ""
        if not isinstance(raw, dict) or not isinstance(raw.get("marks"), dict):
            return self._fresh(), f"{self.path} is damaged (no marks in it)"
        if raw.get("league") != self.league_id or raw.get("season") != self.season:
            return self._fresh(), ""  # another league or season: no marks here
        return raw, ""

    def _parse(self, raw: dict) -> dict[int, Mark]:
        today = self.session.today
        out = {}
        for key, d in raw.get("marks", {}).items():
            if not str(key).isdigit() or not isinstance(d, dict):
                continue
            m = Mark.from_dict(int(key), d)
            if m.active_on(today):
                out[m.player_id] = m
        return out

    def load(self) -> Marks:
        raw, err = self._read()
        if err:
            return Marks({}, False, err)
        return Marks(self._parse(raw), raw.get("paused") is True)

    def _change(self, fn, *, reset_damaged: bool = False):
        """Read fresh, apply ``fn(raw)``, drop expired marks, write; all under the lock."""
        with store.locked(self.path, memory=self.memory):
            raw, err = self._read()
            if err and not reset_damaged:
                raise BenchbossError(f"{err}: fix the file, or run `benchboss autoswap clear` "
                                     "to start over")
            if err and self.memory is None:  # keep the damaged file for whoever wants it
                with contextlib.suppress(OSError):
                    shutil.copyfile(self.path, self.path.with_name(self.path.name + ".damaged"))
            result = fn(raw)
            raw["marks"] = {str(pid): m.to_dict() for pid, m in self._parse(raw).items()}
            raw.update(v=VERSION, league=self.league_id, season=self.season)
            store.write_json(self.path, raw, memory=self.memory)
        return result

    def _log(self, origin: str, event: str, **fields) -> None:
        # the change is made; a log that cannot be written must not undo or block it
        with contextlib.suppress(BenchbossError):
            lineup_log.append_local(self.session, origin, event, "attended", **fields)

    def arm(self, player: Player, mode: str = "auto", until: dt.date | None = None,
            origin: str = "cli") -> Mark:
        """Mark ``player`` (on your roster, checked by the caller). Arming in "auto" mode is
        the user's yes for that player's automatic change: callers ask first."""
        if mode not in MODES:
            raise BenchbossError(f"unknown auto-swap mode '{mode}' ({', '.join(MODES)})")
        if origin not in ORIGINS:
            raise BenchbossError(f"unknown origin '{origin}'")
        end = until or week_end(self.session)
        mark = Mark(player.id, player.name, mode,
                    self.session.now.isoformat(timespec="seconds"), end.isoformat(),
                    known_status(player) or "", origin)
        self._change(lambda raw: raw["marks"].__setitem__(str(player.id), mark.to_dict()))
        self._log(origin, "arm", player_id=player.id, player=player.name, mark=mode,
                  until=mark.until, baseline=mark.baseline or None)
        return mark

    def disarm(self, player_id: int, origin: str = "cli") -> bool:
        """Take one mark off. False when there was none (or the file is damaged: no marks)."""
        raw, err = self._read()
        if err or str(player_id) not in raw.get("marks", {}):
            return False

        def drop(raw: dict) -> Mark | None:
            d = raw["marks"].pop(str(player_id), None)
            return Mark.from_dict(player_id, d) if isinstance(d, dict) else None

        gone = self._change(drop)
        if gone is not None:
            self._log(origin, "disarm", player_id=player_id, player=gone.name)
        return gone is not None

    def clear(self, origin: str = "cli") -> int:
        """Take every mark off; also starts over from a damaged file."""
        def drop(raw: dict) -> int:
            n = len(raw["marks"])
            raw["marks"] = {}
            return n

        n = self._change(drop, reset_damaged=True)
        self._log(origin, "disarm", player_id=None, player=None, cleared=n)
        return n

    def set_paused(self, paused: bool, origin: str = "cli") -> None:
        """Pause (no automatic change at all) or resume. Pausing works on a damaged file too."""
        self._change(lambda raw: raw.__setitem__("paused", bool(paused)), reset_damaged=paused)
        self._log(origin, "pause" if paused else "resume")


__all__ = ["MODES", "ORIGINS", "Mark", "MarkStore", "Marks", "VERSION", "week_end"]

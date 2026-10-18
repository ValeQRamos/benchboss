"""``benchboss monitor``: the one background process. It watches marked and watch-list
players, makes the auto-swap changes (or, in trial mode, says what it would have done),
and sends the notifications.

Modes: trial (the default: reads, plans, notifies "benchboss would have started X for Y",
writes nothing to ESPN), live (``--live`` plus ``--yes`` or a yes at the prompt: sends the
change through Session.apply_plan), dry run (``--dry-run``: prints only; no notification,
no state, no log, no lease).

One monitor per league: the lease store.lease_path(league id) is created with
O_CREAT|O_EXCL and holds {"owner", "pid", "host", "since", "expires"}; it is renewed every
60 s and taken over only when it expired or its process is gone. Before every POST the
monitor checks the lease is still its own.

Its state, store.monitor_path(league id), is written only by the lease holder and read by
the app (the Auto-swap screen, the Inbox):

    {"v": 1, "league": 12345,
     "heartbeat": {"pid", "host", "version", "mode", "started", "last_tick", "next_tick",
                   "last_error", "auth_wait"},
     "day": "2026-10-20",
     "status": {"<player id>": "DAY_TO_DAY"},
     "edges": {"<player id>": 2},
     "acted": {"2026-10-20:<player id>:2": {"at", "outcome"}},
     "moved": {"<player id>": {"count": 1, "to": "G", "benched": <player id>}},
     "intents": {"<intent id>": {"at", "period", "items", "outcome"}},
     "counters": {"writes": 0, "failures": 0},
     "notified": {"<note key>": "<at>"},
     "alerts": [{"key", "kind", "player_id", "player", "text", "at", "urgent"}],
     "pending": {"<player id>": {"edge", "at", "old", "new"}},
     "held": {"<player id>": "2026-10-20"},
     "lineup": {"<player id>": <slot id>},
     "last_write": "<at>"}

    run(once) -> int                          the exit code for --once
    tick(now) -> list[event dicts]            one read, flips, actions

How one tick goes:

1. On a new fantasy day the per-day parts reset (acted, moved, intents, counters,
   notified, pending, held, lineup) and the league is read again; otherwise every 30 min.
2. Tracked players: armed marks (auto and notify), the ESPN watch list, and the players the
   monitor started today (they are guarded until their tip). No one tracked, no read.
3. One read (Session.player_snapshot). A bad read (core.autoswap.bad_read) changes nothing.
4. Flips (core.autoswap.detect_flips) against the stored statuses; a marked player seen
   for the first time compares against his mark's baseline, anyone else is silent.
   Each flip bumps that player's edge counter, which is what dedupes actions.
5. An auto mark that turns healthy becomes pending. A pending flip acts only when the poll
   shows it AND apply_plan's own fresh roster read shows the same healthy status; until
   then it waits, up to 3 minutes before his tip.
6. Trial: apply_plan(send=False) and the note "Trial run: benchboss would have...". Live:
   the same plan first (send=False), then the lease, the marks (a disarm or a pause always
   wins), the caps and the day are checked again, the intent is saved, and apply_plan
   sends. A plan that moves anyone but the healthy player and one starter, or touches a
   player who is locked, tipped or about to, or whose game time is not set, is refused
   (G5, G1) in trial and live alike. A send is verified with a fresh roster read at least
   20 s later; an UNKNOWN outcome is resent at most once, only when that read shows nothing
   applied, the tip is still outside the margin, and the lease and the marks still allow it.
   FAILED and REFUSED are never retried; a read that fails (or a 401) leaves the flip
   pending.
7. A notify mark or a watch-list player who turns healthy makes an alert and a note.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace

from benchboss import __version__, lineup_log, notify, store
from benchboss.core import autoswap as core
from benchboss.core.calendar import clock
from benchboss.core.lineup import LOCK_MARGIN, MIN_GAIN_AUTO
from benchboss.errors import (
    AuthError,
    BenchbossError,
    ConfigError,
    EspnError,
    NetworkError,
)
from benchboss.espn.constants import IR, LINEUP_LOCK_INDIVIDUAL, SLOT, status_class
from benchboss.marks import MarkStore

VERSION = 1
LEASE_TTL = 180.0       # seconds a lease lasts without a renewal
LEASE_RENEW = 60.0      # seconds between renewals (and the longest sleep)
VERIFY_AFTER = 20.0     # seconds between a send and the read that checks it
MAX_WRITES = 6          # automatic writes a day
MAX_MOVES_PER_PLAYER = 2  # automatic moves of one player a day
WRITE_SPACING = 60.0    # seconds between two writes, unless a tip is near
NEAR_TIP = dt.timedelta(minutes=2)
MAX_FAILURES = 2        # FAILED or REFUSED answers in a day before the rest of it is trial
ALERTS_KEEP = 100
LEAGUE_REFRESH = 1800.0  # seconds between full league reads (roster, watch list)
AUTH_RETRY = 600.0      # seconds between tries while the cookies do not work
AUTH_CONFIRM = dt.timedelta(minutes=30)  # near an armed tip, a 401 is read twice
BACKOFF = (30.0, 60.0, 120.0, 240.0)
URGENT_OUTCOMES = {"FAILED", "REFUSED", "UNKNOWN"}
HEALTHY = "ok"


class MonitorBusy(BenchbossError):
    """Another monitor holds this league's lease."""


# --- the lease ---------------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return True  # os.kill(pid, 0) would end the process on Windows: trust the expiry
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _host() -> str:
    return socket.gethostname().split(".")[0] or "this computer"


class Lease:
    """One monitor per league (see the module docstring)."""

    def __init__(self, league_id: int, *, memory: dict | None = None,
                 clock: Callable[[], float] = time.time, host: str | None = None,
                 pid: int | None = None):
        self.path = store.lease_path(league_id)
        self.memory = memory
        self.clock = clock
        self.host = host or _host()
        self.pid = os.getpid() if pid is None else pid
        self.owner = uuid.uuid4().hex
        self.since = self.clock()

    def _info(self) -> dict:
        now = self.clock()
        return {"owner": self.owner, "pid": self.pid, "host": self.host,
                "since": _iso(self.since), "expires": _iso(now + LEASE_TTL)}

    def read(self) -> dict | None:
        try:
            info = store.read_json(self.path, None, memory=self.memory)
        except BenchbossError:
            return None
        return info if isinstance(info, dict) else None

    def _create(self) -> bool:
        if self.memory is not None:
            with store.locked(self.path, memory=self.memory):
                if self.read() is not None:
                    return False
                store.write_json(self.path, self._info(), memory=self.memory)
                return True
        store.private_dir(self.path.parent)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
        except OSError as e:
            raise BenchbossError(f"could not create {self.path} ({e})") from e
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._info()))
        return True

    def alive(self, info: dict | None) -> bool:
        """Whether the holder in ``info`` still counts: not expired, and on this computer
        its process still runs."""
        if not info:
            return False
        try:
            expires = dt.datetime.fromisoformat(str(info.get("expires"))).timestamp()
        except ValueError:
            return False
        if expires <= self.clock():
            return False
        if info.get("host") == self.host and isinstance(info.get("pid"), int):
            return _pid_alive(info["pid"])
        return True

    def acquire(self) -> None:
        if self._create():
            return
        with store.locked(self.path, memory=self.memory):
            info = self.read()
            if info and info.get("owner") != self.owner and self.alive(info):
                raise MonitorBusy(
                    f"another monitor is running for this league (pid {info.get('pid')} on "
                    f"{info.get('host')}): stop it first, there is only one per league")
            store.write_json(self.path, self._info(), memory=self.memory)

    def held(self) -> bool:
        """Fencing: true only while the file still names this monitor."""
        info = self.read()
        return bool(info) and info.get("owner") == self.owner

    def renew(self) -> bool:
        """Push the expiry out. False only when the file names another monitor; a lock
        that is busy for a moment keeps the lease (the next renewal tries again)."""
        try:
            with store.locked(self.path, memory=self.memory):
                if not self.held():
                    return False
                store.write_json(self.path, self._info(), memory=self.memory)
                return True
        except BenchbossError:
            return self.held()

    def release(self) -> None:
        with contextlib.suppress(BenchbossError), store.locked(self.path, memory=self.memory):
            if not self.held():
                return
            if self.memory is not None:
                self.memory.pop(str(self.path), None)
            else:
                with contextlib.suppress(OSError):
                    self.path.unlink()


def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


# --- state -------------------------------------------------------------------------------------

PER_DAY = ("acted", "moved", "intents", "notified", "pending", "held", "lineup")


def fresh_state(league_id: int) -> dict:
    return {"v": VERSION, "league": league_id, "heartbeat": {}, "day": "", "status": {},
            "edges": {}, "acted": {}, "moved": {}, "intents": {},
            "counters": {"writes": 0, "failures": 0}, "notified": {}, "alerts": [],
            "pending": {}, "held": {}, "lineup": {}, "last_write": ""}


def read_state(session) -> dict:
    """The monitor's state for the app and the CLI: never raises (a missing or damaged
    file reads as a monitor that never ran)."""
    league_id = session.client.league_id
    try:
        raw = store.read_json(store.monitor_path(league_id), None, memory=session.local_state)
    except BenchbossError:
        raw = None
    state = fresh_state(league_id)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in state and isinstance(value, type(state[key])):
                state[key] = value
    return state


def read_lease(session) -> dict | None:
    try:
        info = store.read_json(store.lease_path(session.client.league_id), None,
                               memory=session.local_state)
    except BenchbossError:
        return None
    return info if isinstance(info, dict) else None


def heartbeat(session) -> dict:
    """Whether a monitor runs for this league, for ``autoswap list`` and the screen:
    {"running", "mode", "host", "checked" (seconds ago or None), "text"}."""
    state, lease = read_state(session), read_lease(session)
    hb = state.get("heartbeat") or {}
    now = time.time()
    running = False
    if lease:
        with contextlib.suppress(ValueError):
            running = dt.datetime.fromisoformat(str(lease.get("expires"))).timestamp() > now
    checked = None
    with contextlib.suppress(KeyError, ValueError, TypeError):
        checked = max(0, round(now - dt.datetime.fromisoformat(hb["last_tick"]).timestamp()))
    mode = hb.get("mode") or "trial"
    host = (lease or {}).get("host") or hb.get("host") or ""
    if running:
        ago = "not yet" if checked is None else f"{_ago(checked)} ago"
        text = f"monitor running in {mode} mode on {host}, checked {ago}"
        if hb.get("auth_wait"):
            text += " (waiting for a new login: run benchboss login)"
    else:
        text = "monitor not running: benchboss monitor"
    return {"running": running, "mode": mode if running else None, "host": host or None,
            "checked": checked, "text": text}


def _ago(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{round(s / 60)} min"
    return f"{round(s / 3600)} h"


def base_roster(session, period: int):
    """The lineup auto-swap plans from: the one saved on ESPN for that day (in the demo, the
    one Optimize would set, see DemoSession.autoswap_lineup)."""
    lineup = getattr(session, "autoswap_lineup", None)
    if session.demo and callable(lineup):
        return lineup(period)
    return session.roster_on(period)


def live_refusal(session) -> str:
    """Why live mode cannot write in this league right now ("" when it can)."""
    if session.demo:
        return "demo mode never writes to ESPN"
    lg = session.league()
    if lg.lineup_lock_type != LINEUP_LOCK_INDIVIDUAL:
        kind = lg.lineup_lock_type or "unknown"
        return (f"this league locks lineups by {kind}, not at each player's own tip: "
                "auto-swap only writes where every player locks at his own game")
    cal = session.calendar
    if not 1 <= cal.period_of(session.today) <= cal.final_period:
        return "the fantasy season is not on, so there is no lineup to change"
    return ""


# --- the monitor -------------------------------------------------------------------------------

class Monitor:
    """``session_factory`` makes a Session (again after a day change or a new login).
    ``emit`` gets every event record (the lineup log shape); ``say`` a readable line."""

    def __init__(self, session_factory: Callable[[], object], *, live: bool = False,
                 dry_run: bool = False, backends: Iterable[notify.Backend] = (),
                 simulate: dict[str, str] | None = None,
                 emit: Callable[[dict], None] | None = None,
                 say: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], object] | None = None, host: str | None = None):
        if live and simulate and not dry_run:  # a pretend status must never reach ESPN
            raise BenchbossError("--simulate works in trial mode or with --dry-run, never live")
        self.factory = session_factory
        self.live = live and not dry_run
        self.dry_run = dry_run
        self.backends = list(backends)
        self.simulate = {k: v.upper() for k, v in (simulate or {}).items()}
        self.emit = emit or (lambda rec: None)
        self.say = say or (lambda text: None)
        self.clock = clock
        self.stop = threading.Event()
        # the default sleep ends early on SIGTERM or Ctrl-C (stop is set)
        self.sleep = sleep or self.stop.wait
        self.host = host or _host()
        self.session = None
        self.lease: Lease | None = None
        self.state: dict = {}
        self.once = False
        self.code = 0          # the exit code --once reports
        self.tips: list[dt.datetime] = []
        self._sim_ids: dict[int, str] = {}
        self._sim_auto: set[int] = set()  # demo: armed for this run only, never saved
        self._real: dict[int, str] = {}  # statuses as read, before --simulate
        self._restore: list = []
        self._league_read = 0.0
        self._errors = 0
        self._auth_checked = False
        self._start_noted = False
        self._started = False  # the lease is ours and the state is loaded

    # --- setup ---------------------------------------------------------------------------------

    @property
    def mode(self) -> str:
        return "live" if self.live else "trial"

    def start(self) -> None:
        """Make the session, take the lease (not in a dry run) and load the state."""
        s = self.session = self.factory()
        refused = live_refusal(s) if self.live else ""
        if refused and self.once:
            raise BenchbossError(f"live mode refused: {refused}")
        if refused and "season" in refused:
            self.say(f"live mode: {refused} yet; it writes once there are games to set")
            refused = ""
        elif refused:  # the loop goes on in trial mode: no restart loop, and no write
            self.live = False
        if not self.dry_run:
            self.lease = Lease(s.client.league_id, memory=s.local_state, clock=self.clock,
                               host=self.host)
            self.lease.acquire()
        self.state = read_state(s)
        self._overrides()
        hb = self.state["heartbeat"]
        hb.update(pid=os.getpid(), host=self.host, version=__version__, mode=self.mode,
                  started=self._now_iso(), last_error="", auth_wait=False)
        if not self.once:  # cron runs --once every few minutes: no start and stop lines
            self._record("start", version=__version__,
                         backends=[b.name for b in self.backends], dry_run=self.dry_run,
                         simulate=sorted(self.simulate) or None,
                         text=f"monitor started in {self.mode} mode" +
                              (" (dry run: nothing is saved or sent)" if self.dry_run else ""))
        self._started = True
        if refused:
            self.say(f"live mode refused: {refused}. Running in trial mode.")
            self._note("Auto-swap stays in trial", f"Live mode refused: {refused}.", "urgent",
                       "refused")
        self._save()

    def close(self, code: int = 0) -> None:
        self._restore_overrides()
        if self.session is None or not self._started:
            return  # never touch the files of a monitor that holds the lease
        self._started = False
        if not self.once:
            with contextlib.suppress(BenchbossError):
                self._record("stop", code=code, text="monitor stopped")
        self._save()
        if self.lease is not None:
            self.lease.release()

    def _overrides(self) -> None:
        """--simulate statuses on every read, and in the demo the lineup Optimize would set
        (core of the demo: see DemoSession.autoswap_lineup)."""
        s = self.session
        if not self.simulate and not s.demo:
            return
        real = s.roster_on
        base = getattr(s, "autoswap_lineup", None) if s.demo else None

        def roster_on(period: int):
            today = s.calendar.period_of(s.today)
            roster = base(period) if base and period == today else real(period)
            return self._apply(roster)

        self._restore.append((s, "roster_on", s.__dict__.get("roster_on")))
        s.roster_on = roster_on

    def _apply(self, roster):
        if not self._sim_ids:
            return roster
        return [replace(sp, player=self._sim(sp.player)) for sp in roster]

    def _sim(self, p):
        status = self._sim_ids.get(p.id)
        if status is None:
            return p
        return replace(p, injury_status=status, injury_known=True)

    def _resolve_simulate(self, players) -> None:
        """--simulate "Name=STATUS": the names, among the roster and the players read."""
        if not self.simulate or self._sim_ids:
            return
        from benchboss.text import match_one

        pool = {sp.player.id: sp.player for sp in self.session.league().me.roster}
        for p in players:
            pool.setdefault(p.id, p)
        for name, status in self.simulate.items():
            p = match_one(list(pool.values()), name, lambda x: x.name,
                          where="your roster or watch list")
            self._sim_ids[p.id] = status
        if self.session.demo:  # the demo starts with no marks: the roster players named
            marks = MarkStore(self.session).load()  # count as armed for this run (unsaved)
            roster = {sp.player.id: sp.player for sp in self.session.league().me.roster}
            for pid in self._sim_ids:
                if pid in roster and pid not in marks.marks:
                    self._sim_auto.add(pid)
                    self.say(f"demo: {roster[pid].name} counts as armed for this run")

    # --- helpers -------------------------------------------------------------------------------

    def _now(self) -> dt.datetime:
        return self.session.now

    def _now_iso(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _secrets(self) -> tuple[str, ...]:
        return store.session_secrets(self.session)

    def _record(self, event: str, **fields) -> dict:
        rec = lineup_log.record_local(self.session, "monitor", event, self.mode, **fields)
        if not self.dry_run:
            store.append_jsonl(lineup_log.path_for(self.session.now), rec,
                               memory=self.session.local_state)
        self.emit(rec)
        return rec

    def _save(self) -> bool:
        """Write the state (the lease holder only). False when it could not be written: the
        monitor says so once, and never sends a change it could not record first."""
        if self.dry_run or self.session is None or not self._started:
            return False
        if self.lease is not None and not self.lease.held():
            return False
        clean = json.loads(store.redact(json.dumps(self.state, default=str), self._secrets()))
        try:
            store.write_json(store.monitor_path(self.session.client.league_id), clean,
                             memory=self.session.local_state)
        except BenchbossError as e:
            if "state-save" not in self.state["notified"]:
                self.state["notified"]["state-save"] = self._now_iso()
                self.say(str(e))
                notify.send(notify.Note("benchboss monitor", f"benchboss cannot save its state "
                                        f"({e}); auto-swap sends nothing until it can.",
                                        "urgent"), self.backends)
            return False
        return True

    def _note(self, title: str, body: str, priority: str = "normal", key: str = "") -> None:
        """Send one notification (once per key per day); never in a dry run."""
        if key and key in self.state["notified"]:
            return
        if key:
            self.state["notified"][key] = self._now_iso()
        if self.dry_run:
            return
        secrets = self._secrets()
        note = notify.Note(store.redact(title, secrets), store.redact(body, secrets),
                           priority, key)
        for receipt in notify.send(note, self.backends):
            if "failed" in receipt:
                self.say(f"notification {receipt}")

    def _alert(self, kind: str, pid: int | None, name: str, text: str, urgent: bool,
               key: str) -> None:
        alerts = [a for a in self.state["alerts"] if a.get("key") != key]
        alerts.append({"key": key, "kind": kind, "player_id": pid, "player": name,
                       "text": store.redact(text, self._secrets()), "at": self._now_iso(),
                       "urgent": urgent})
        self.state["alerts"] = alerts[-ALERTS_KEEP:]

    def _worse(self, code: int) -> None:
        """Keep the most serious exit code: auth, then refused, then a guard."""
        rank = {0: 0, 1: 1, 5: 2, 4: 3, 3: 4}
        if rank.get(code, 1) > rank.get(self.code, 1):
            self.code = code

    # --- one tick ------------------------------------------------------------------------------

    def _roll_day(self) -> None:
        s = self.session
        day = s.today.isoformat()
        if self.state["day"] == day:
            return
        if self.state["day"] and not s.demo and self.factory is not None:
            with contextlib.suppress(BenchbossError):
                fresh = self.factory()  # a new day: a fresh calendar and league
                self._restore_overrides()
                self.session = s = fresh
                self._overrides()
        for key in PER_DAY:
            self.state[key] = {}
        self.state["counters"] = {"writes": 0, "failures": 0}
        self.state["last_write"] = ""
        self.state["day"] = day
        self._league_read = 0.0

    def _restore_overrides(self) -> None:
        for obj, name, value in reversed(self._restore):
            if value is None:
                with contextlib.suppress(AttributeError):
                    delattr(obj, name)
            else:
                setattr(obj, name, value)
        self._restore = []

    def tick(self) -> list[dict]:
        """One round: read, compare, act. Returns the event records it made."""
        out: list[dict] = []
        emit = self.emit
        self.emit = lambda rec: (out.append(rec), emit(rec))
        try:
            self._tick()
        finally:
            self.emit = emit
        self.state["heartbeat"].update(last_tick=self._now_iso(), auth_wait=False)
        self._save()
        return out

    def _tick(self) -> None:
        self._roll_day()  # may bring a fresh session on a new day
        s = self.session
        if self.clock() - self._league_read > LEAGUE_REFRESH:
            s.league(refresh=self._league_read > 0)
            self._league_read = self.clock()
        lg, cal = s.league(), s.calendar
        now = self._now()
        period = cal.period_of(s.today)
        in_season = 1 <= period <= cal.final_period
        marks = MarkStore(s).load()
        if marks.error:
            self._note("Auto-swap is off", f"{marks.error}. No player is armed until it is "
                       "fixed or cleared (benchboss autoswap clear).", "urgent", "marks-damaged")
            self.say(marks.error)
        roster = {sp.player.id: sp for sp in lg.me.roster}
        auto = {pid for pid in marks.auto_ids() if pid in roster and roster[pid].slot_id != IR}
        notify_only = marks.notify_ids()
        watch = set(lg.me.watch_list)
        moved = {int(k) for k, v in self.state["moved"].items() if v.get("to")}
        tracked = auto | notify_only | watch | moved | set(self._sim_ids)
        if self.simulate and not self._sim_ids:
            self._resolve_simulate([sp.player for sp in roster.values()])
        auto |= self._sim_auto
        tracked |= auto | set(self._sim_ids)
        if not tracked:
            self.tips = []
            self.say("nobody to watch: arm a player (benchboss autoswap add) or star one on "
                     "your ESPN watch list")
            return
        players = self._snapshot(tracked)
        before = {int(k): v for k, v in self.state["status"].items()}
        reason = core.bad_read(players, tracked, before)
        if reason:
            self._record("error", text=f"bad read, nothing changed: {reason}")
            return
        for pid, m in marks.marks.items():
            if pid not in before and status_class(m.baseline) != "unknown":
                before[pid] = m.baseline
        for pid in self._sim_ids:
            if pid not in before and self._real.get(pid):
                before[pid] = self._real[pid]
        flips = core.detect_flips(before, players, cal, period, now) if in_season else []
        known = core.remember(before, players)
        self.state["status"] = {str(pid): st for pid, st in known.items() if pid in tracked}
        by_id = {p.id: p for p in players}
        self.tips = [g.start for pid in auto | notify_only | moved if pid in by_id
                     for g in [cal.game(by_id[pid].pro_team_id, period)] if g and in_season]
        tz = now.tzinfo
        for f in flips:
            edge = int(self.state["edges"].get(str(f.player_id), 0)) + 1
            self.state["edges"][str(f.player_id)] = edge
            self._record("flip", trigger=f.to_dict(), edge=edge,
                         text=f"{f.name}: {core.tag(f.old)} to {core.tag(f.new)}")
            pid = f.player_id
            if pid in auto and f.cleared and not marks.paused:
                self.state["pending"][str(pid)] = {"edge": edge, "at": self._now_iso(),
                                                   "old": f.old, "new": f.new}
            elif pid in auto and not f.cleared:
                self.state["pending"].pop(str(pid), None)
            if pid in moved and f.new in core.REVERT_STATUSES and f.tip and not f.started:
                self._revert(f, edge, period)
            if f.cleared and (pid not in auto or marks.paused):
                self._healthy(f, edge, today=period)
        for key in list(self.state["pending"]):
            p = by_id.get(int(key))
            if p is None or int(key) not in auto:  # disarmed, lowered to alert only, or gone
                self.state["pending"].pop(key, None)
                continue
            self._try_start(p, self.state["pending"][key], period, marks.paused)
        n = len(players)
        changes = len(flips)
        self.say(f"{clock(now, tz)}  checked {n} player{'s' * (n != 1)}: "
                 + (f"{changes} status change{'s' * (changes != 1)}" if changes else "no change"))

    def _snapshot(self, ids: set[int]):
        players = self.session.player_snapshot(ids)
        self._real = {p.id: core.known_status(p) or "" for p in players}
        return [self._sim(p) for p in players]

    # --- healthy alerts ------------------------------------------------------------------------

    def _healthy(self, f: core.Flip, edge: int, today: int) -> None:
        tz = self._now().tzinfo
        text = core.healthy_text(f, tz)
        urgent = f.tip is not None and not f.started
        key = f"healthy:{self.state['day']}:{f.player_id}:{edge}"
        self._alert("healthy", f.player_id, f.name, text, urgent, key)
        self._note("Healthy", text, "urgent" if urgent else "normal", key)

    # --- starting a player who turned healthy ----------------------------------------------------

    def _try_start(self, p, pending: dict, period: int, paused: bool) -> None:
        pid, edge = p.id, int(pending.get("edge") or 0)
        key = f"{self.state['day']}:{pid}:{edge}"
        drop = lambda: self.state["pending"].pop(str(pid), None)  # noqa: E731
        if key in self.state["acted"]:
            drop()
            return
        now = self._now()
        if paused:
            drop()
            self.say(f"auto-swap is paused: {p.name} turned healthy, nothing changed")
            return
        if self.state["held"].get(str(pid)) == self.state["day"]:
            drop()
            return
        if core.known_status(p) is None or status_class(p.injury_status) != HEALTHY:
            drop()  # not healthy any more by this read
            return
        game = self.session.calendar.game(p.pro_team_id, period)
        if game is None or game.start - LOCK_MARGIN <= now:
            drop()
            self.state["acted"][key] = {"at": self._now_iso(), "outcome": "TOO_LATE"}
            if game is not None:
                text = (f"{p.name} turned healthy too close to his {clock(game.start, now.tzinfo)} "
                        "tip: benchboss left your lineup alone.")
                self._alert("autoswap", pid, p.name, text, False, f"late:{key}")
                self._note("Auto-swap", text, "normal", f"late:{key}")
            return
        self._attempt(p, edge, period, frozenset({pid}), game.start, revert=False)

    def _revert(self, f: core.Flip, edge: int, period: int) -> None:
        """A player the monitor started turned OUT, SUSPENSION or DOUBTFUL before his tip:
        the same scoped plan puts him back on the bench (and the starter he replaced back in)."""
        moved = self.state["moved"].get(str(f.player_id)) or {}
        movable = {f.player_id} | ({moved["benched"]} if moved.get("benched") else set())
        p = next((sp.player for sp in self.session.league().me.roster
                  if sp.player.id == f.player_id), None)
        if p is None or f.tip is None or f.tip - LOCK_MARGIN <= self._now():
            return
        self._attempt(replace(p, injury_status=f.new), edge, period, frozenset(movable), f.tip,
                      revert=True)

    def _forced_trial(self, pid: int, tip: dt.datetime, revert: bool = False) -> str:
        """Why this change stays a trial run in live mode ("" when it may be sent). Putting
        back a player the monitor started is not held back by the daily count."""
        if not self.live:
            return ""
        refusal = live_refusal(self.session)
        if refusal:
            return refusal
        c = self.state["counters"]
        if c.get("failures", 0) >= MAX_FAILURES:
            return "ESPN refused two changes today, so the rest of the day is a trial run"
        if c.get("writes", 0) >= MAX_WRITES and not revert:
            return f"{MAX_WRITES} automatic changes today already"
        if int((self.state["moved"].get(str(pid)) or {}).get("count", 0)) >= MAX_MOVES_PER_PLAYER:
            return f"he was moved {MAX_MOVES_PER_PLAYER} times today already"
        return ""

    def _spacing_wait(self, tip: dt.datetime) -> bool:
        last = self.state.get("last_write")
        if not last:
            return False
        with contextlib.suppress(ValueError):
            gone = (self._now() - dt.datetime.fromisoformat(last)).total_seconds()
            return gone < WRITE_SPACING and tip - self._now() > NEAR_TIP
        return False

    def _attempt(self, p, edge: int, period: int, movable: frozenset[int],
                 tip: dt.datetime, revert: bool) -> None:
        s, cal = self.session, self.session.calendar
        pid = p.id
        key = f"{self.state['day']}:{pid}:{edge}"
        opts = core.auto_options(self._now(), movable)
        forced = self._forced_trial(pid, tip, revert)
        if forced:
            self._note("Auto-swap stays in trial", forced, "normal", f"forced:{forced}")
        live = self.live and not forced
        if live and not revert and self._spacing_wait(tip):
            return  # the next tick tries again
        writer = "cli" if self.dry_run else "monitor"  # apply_plan logs nothing for a dry run
        r0 = s.apply_plan(period, opts=opts, send=False, writer=writer)
        trigger = core.player_in(r0.plan, pid)
        if r0.outcome in ("ERROR", "AUTH"):  # a read that failed decides nothing
            if r0.outcome == "AUTH":
                self._worse(3)
            self._record("error", trigger={"player_id": pid, "player": p.name},
                         text=f"could not read the lineup for {p.name}: {r0.error}")
            return  # stays pending
        if r0.outcome in ("WOULD_SEND", "ALREADY_OPTIMAL", "BELOW_MIN_GAIN") and (
                trigger is None or core.known_status(trigger) is None
                or (trigger.injury_status not in core.REVERT_STATUSES if revert
                    else status_class(trigger.injury_status) != HEALTHY)):
            if not revert:
                self.say(f"{p.name}: the roster read does not show him healthy yet, waiting")
            return  # two reads must agree before anything happens
        before = core.lineup_before(r0.plan)
        if self._human_touched(before, movable, key):
            return
        self.state["lineup"].update({str(k): v for k, v in before.items() if k in movable})
        swap = core.swap_of(r0.plan, pid, cal)
        gain = swap.gain
        outcome = r0.outcome
        guards = [getattr(v, "code", str(v)) for v in r0.guards if getattr(v, "fatal", True)]
        frozen = core.frozen_moves(r0.plan, cal, self._now()) if r0.plan.moves else []
        scope = core.out_of_scope(before, r0.plan, movable) if r0.plan.moves else []
        problems = frozen + scope
        if outcome == "WOULD_SEND" and problems:
            outcome = "NOT_SENT"
            guards = guards + [g for g, hit in (("G1", frozen), ("G5", scope))
                               if hit and g not in guards]
        if outcome == "WOULD_SEND" and not revert and gain < MIN_GAIN_AUTO:
            outcome = "BELOW_MIN_GAIN"
        if outcome != "WOULD_SEND":
            self._settle(p, key, edge, r0, outcome, swap, guards, problems, revert, None)
            return
        if not live:
            self._settle(p, key, edge, r0, "WOULD_SEND", swap, [], [], revert, None,
                         forced=forced)
            return
        self._send(p, key, edge, period, opts, r0, swap, revert, tip)

    def _human_touched(self, before: dict[int, int], movable: Iterable[int], key: str) -> bool:
        """Someone else changed the slot of an armed player since the monitor's last read:
        his mark rests for the rest of the day."""
        last = self.state["lineup"]
        for pid in movable:
            if str(pid) in last and pid in before and int(last[str(pid)]) != before[pid]:
                mark = MarkStore(self.session).load().get(pid)
                name = mark.name if mark else str(pid)
                self.state["held"][str(pid)] = self.state["day"]
                self.state["pending"].pop(str(pid), None)
                text = (f"Someone changed {name}'s lineup spot since benchboss last looked, so "
                        "auto-swap leaves him alone for the rest of the day.")
                self._alert("autoswap", pid, name, text, False, f"held:{key}")
                self._note("Auto-swap paused for today", text, "normal", f"held:{key}")
                self._record("autoswap", trigger={"player_id": pid, "player": name},
                             outcome="NOT_SENT", guards=[], text=text, moves=[])
                return True
        return False

    def _moves(self, plan) -> list[dict]:
        return [{"player_id": m.player.id, "player": m.player.name,
                 "from": SLOT.get(m.from_slot, str(m.from_slot)),
                 "to": SLOT.get(m.to_slot, str(m.to_slot))} for m in plan.moves]

    def _trigger(self, p, tip: dt.datetime | None) -> dict:
        pending = self.state["pending"].get(str(p.id)) or {}
        return {"player_id": p.id, "player": p.name, "old": pending.get("old"),
                "new": p.injury_status if p.injury_known else None,
                "tip": tip.isoformat() if tip else None}

    def _settle(self, p, key: str, edge: int, r, outcome: str, swap: core.Swap, guards: list,
                problems: list[str], revert: bool, intent: str | None, *, forced: str = "",
                status: str = "", error: str = "") -> None:
        """Record what happened to one flip, say it and close it."""
        cal = self.session.calendar
        game = cal.game(p.pro_team_id, r.plan.period)
        tip = game.start if game else None
        name = p.name
        if outcome == "WOULD_SEND":
            if revert:
                text = (f"Trial run: {name} is {core.tag(p.injury_status)} again, benchboss "
                        "would have put him back on the bench. Nothing was sent.")
            else:
                text = core.trial_text(name, swap)
            if forced:
                text += f" (live mode is on, but {forced}.)"
        elif outcome == "EXECUTED":
            text = (f"Auto-swap: {name} is {core.tag(p.injury_status)} again, back on the bench. "
                    f"ESPN: {status or 'EXECUTED'}" if revert else
                    core.live_text(name, swap, status or "EXECUTED"))
            text += " Tomorrow starts from this lineup: run benchboss optimize tomorrow."
        elif outcome == "ALREADY_OPTIMAL":
            text = (f"{name} is healthy and already where he should be: nothing to change."
                    if not revert else f"{name} is already on the bench.")
        elif outcome == "BELOW_MIN_GAIN":
            text = (f"{name} is healthy, but starting him adds only {swap.gain:+.1f} "
                    f"(under {MIN_GAIN_AUTO:.1f}): nothing changed.")
        elif outcome == "NOT_SENT":
            why = "; ".join(problems) or "; ".join(guards) or r.error or "a safety check"
            text = f"benchboss did not change your lineup for {name}: {why}. Nothing was sent."
        elif outcome == "UNKNOWN":
            text = (f"Auto-swap for {name}: ESPN did not confirm the change. Check your lineup "
                    "in the ESPN app.")
        else:  # FAILED, REFUSED, AUTH, ERROR
            text = (f"Auto-swap for {name} did not go through: {error or status or outcome}. "
                    "benchboss will not try again today.")
        trigger = self._trigger(p, tip)
        self.state["acted"][key] = {"at": self._now_iso(), "outcome": outcome}
        self.state["pending"].pop(str(p.id), None)
        urgent = outcome in URGENT_OUTCOMES or outcome == "NOT_SENT"
        gain = round(swap.gain, 1)
        projected_after = round(r.plan.projected, 1)
        before = r.plan.projected_before or (r.plan.projected - swap.gain)
        self._record("autoswap", period=r.plan.period,
                     date=cal.date_of(r.plan.period).isoformat(), kind=r.kind or "ROSTER",
                     trigger=trigger, moves=self._moves(r.plan),
                     projected_before=round(before, 1), projected_after=projected_after,
                     gain=gain, outcome=outcome, status=status or None, error=error or None,
                     guards=guards, intent=intent, edge=edge, text=text)
        if not revert or outcome not in ("ALREADY_OPTIMAL", "BELOW_MIN_GAIN"):
            self._alert("autoswap", p.id, name, text, urgent, f"autoswap:{key}")
            prio = "urgent" if urgent else "info" if outcome in ("ALREADY_OPTIMAL",
                                                                 "BELOW_MIN_GAIN") else "normal"
            self._note("Auto-swap", text, prio, f"autoswap:{key}")
        if outcome == "NOT_SENT" and (guards or problems):
            self._worse(5)

    def _send(self, p, key: str, edge: int, period: int, opts, r0, swap: core.Swap,
              revert: bool, tip: dt.datetime) -> None:
        """Live: fence, re-check, save the intent, send, verify."""
        s = self.session
        if self.lease is None or not self.lease.held():
            self.say("another monitor took this league over: this one stops writing")
            self._record("error", text="the lease is gone: another monitor runs this league, "
                                       "so this one stopped writing")
            self.live = False
            self.stop.set()
            return
        marks = MarkStore(s).load()  # a disarm or a pause made a moment ago always wins
        if marks.paused or marks.error or (not revert and p.id not in marks.auto_ids()):
            self.state["pending"].pop(str(p.id), None)
            self.say(f"{p.name} was disarmed or auto-swap was paused: nothing sent")
            return
        try:
            strict = s.current_period(strict=True)
        except BenchbossError as e:
            self._settle(p, key, edge, r0, "NOT_SENT", swap, ["G9"], [str(e)], revert, None)
            return
        if strict != period or r0.kind not in ("", "ROSTER"):
            self._settle(p, key, edge, r0, "NOT_SENT", swap, ["G9"],
                         ["ESPN's day is not today"], revert, None)
            return
        intent = uuid.uuid4().hex[:12]
        self.state["intents"][intent] = {"at": self._now_iso(), "period": period,
                                         "items": r0.plan.items(), "trigger": p.id,
                                         "outcome": None, "resent": 0}
        c = self.state["counters"]
        c["writes"] = c.get("writes", 0) + 1
        moved = self.state["moved"].setdefault(str(p.id), {"count": 0})
        moved["count"] = int(moved.get("count", 0)) + 1
        self.state["last_write"] = self._now_iso()
        if not self._save():  # write-ahead: a restart now cannot send it twice or lose counts
            self._settle(p, key, edge, r0, "NOT_SENT", swap, [],
                         ["benchboss could not save what it was about to send"], revert, intent)
            return
        r1 = s.apply_plan(period, opts=opts, send=True, writer="monitor")
        outcome = r1.outcome
        if outcome == "ERROR" and r1.kind:
            outcome = "UNKNOWN"  # the POST went out and the answer was lost
        self.state["intents"][intent]["outcome"] = outcome
        self._save()
        if outcome in ("ERROR", "AUTH"):  # the lineup could not be read again, or ESPN
            # turned the cookies down (a 401 applies nothing): nothing was sent
            if outcome == "AUTH":
                self._worse(3)
            self._record("error", trigger={"player_id": p.id, "player": p.name}, intent=intent,
                         text=f"nothing sent for {p.name}: {r1.error}")
            return  # stays pending; the counts already went up, which only makes it safer
        if outcome in ("EXECUTED", "UNKNOWN"):
            outcome = self._verify(p, r1, intent, outcome, opts, period, tip, revert)
        r = r1 if r1.plan.moves or not r0.plan.moves else replace(r1, plan=r0.plan)
        swap = core.swap_of(r.plan, p.id, s.calendar) if r.plan.moves else swap
        if outcome == "EXECUTED":  # what the next look at the lineup should find
            self.state["lineup"].update({str(m.player.id): m.to_slot for m in r.plan.moves})
        if outcome == "EXECUTED" and not revert:
            moved.update(to=swap.slot, benched=swap.benched.id if swap.benched else None)
        elif outcome == "EXECUTED" and revert:
            moved.update(to=None, benched=None)  # back on the bench; the count stays
        if outcome in ("FAILED", "REFUSED"):
            c["failures"] = c.get("failures", 0) + 1
            self._worse(4)
            if c["failures"] == MAX_FAILURES:
                self._note("Auto-swap", "ESPN refused two automatic changes today: benchboss "
                           "only says what it would do for the rest of the day.", "urgent",
                           "breaker")
        elif outcome == "UNKNOWN":
            self._worse(4)
        elif outcome == "AUTH":
            self._worse(3)
        guards = [getattr(v, "code", str(v)) for v in r1.guards if getattr(v, "fatal", True)]
        self.state["intents"][intent]["outcome"] = outcome
        self._settle(p, key, edge, r, outcome, swap, guards, [], revert, intent,
                     status=r1.status, error=r1.error)

    def _may_resend(self, p, revert: bool) -> bool:
        """The checks before a second POST, as before the first: the lease is still ours,
        and no disarm or pause came in meanwhile."""
        if self.lease is None or not self.lease.held():
            return False
        marks = MarkStore(self.session).load()
        return not (marks.paused or marks.error or (not revert and p.id not in marks.auto_ids()))

    def _verify(self, p, r, intent: str, outcome: str, opts, period: int,
                tip: dt.datetime, revert: bool = False) -> str:
        """Read the lineup again at least VERIFY_AFTER seconds after the send. An UNKNOWN
        send that shows nothing applied is sent once more, while the tip allows it."""
        s = self.session
        for attempt in range(2):
            self.sleep(VERIFY_AFTER)
            try:
                lineup = {sp.player.id: sp.slot_id for sp in s.roster_on(period)}
            except BenchbossError as e:
                self._record("verify", intent=intent, result="error",
                             text=f"could not read the lineup to check the change: {e}")
                return outcome
            want = {m.player.id: m.to_slot for m in r.plan.moves}
            was = {m.player.id: m.from_slot for m in r.plan.moves}
            done = [pid for pid, slot in want.items() if lineup.get(pid) == slot]
            untouched = [pid for pid, slot in was.items() if lineup.get(pid) == slot]
            result = ("ok" if len(done) == len(want) else
                      "not applied" if len(untouched) == len(was) else "partly applied")
            self.state["lineup"].update({str(k): v for k, v in lineup.items()})
            self._record("verify", intent=intent, result=result,
                         text=f"checked the lineup after the change: {result}")
            if result == "ok":
                return "EXECUTED"
            if outcome == "EXECUTED":
                self._note("Auto-swap", f"ESPN answered EXECUTED for {p.name}, but your lineup "
                           f"does not show it ({result}). Check it in the ESPN app.", "urgent",
                           f"verify:{intent}")
                return outcome
            # UNKNOWN: resend once, only when nothing was applied and there is time
            intent_rec = self.state["intents"][intent]
            if (attempt or result != "not applied" or intent_rec.get("resent")
                    or tip - LOCK_MARGIN <= self._now() or not self._may_resend(p, revert)):
                return "UNKNOWN"
            intent_rec["resent"] = 1
            if not self._save():  # the resend is recorded before it goes, like the send
                return "UNKNOWN"
            again = s.apply_plan(period, opts=opts, send=True, writer="monitor")
            if again.outcome == "ALREADY_OPTIMAL":
                continue  # the first send landed after all: the next read says so
            if again.outcome in ("FAILED", "REFUSED"):
                return again.outcome
            if again.outcome == "EXECUTED" or again.outcome == "UNKNOWN" or (
                    again.outcome == "ERROR" and again.kind):
                outcome = "EXECUTED" if again.outcome == "EXECUTED" else "UNKNOWN"
            else:  # nothing went out this time (a read failed, a 401, a guard): the first
                return "UNKNOWN"  # send stays unknown
            if again.plan.moves:
                r = again
        return outcome

    # --- the loop ------------------------------------------------------------------------------

    def run(self, once: bool = False) -> int:
        """Run until stopped (or one round with ``once``); returns the exit code."""
        previous = self._signals()
        self.once = once
        code = 0
        try:
            self._start_safely(once)
            if self.session is None:
                return self.code or 1
            if once:
                self._round()
                code = self.code
                return code
            next_at = last = self.clock()
            while not self.stop.is_set():
                now = self.clock()
                # the loop wakes at least every LEASE_RENEW seconds; a longer gap means the
                # computer slept, so everything is checked again right away
                if now - last > 3 * LEASE_RENEW:
                    self.say(f"woke after {round((now - last) / 60)} min: checking now")
                    next_at = now
                last = now
                if now >= next_at:
                    wait = self._round()
                    next_at = self.clock() + wait
                    self.state["heartbeat"]["next_tick"] = _iso(next_at)
                    self._save()
                if self.lease is not None and not self.lease.renew():
                    self.say("the lease is gone: another monitor runs this league; stopping")
                    self.stop.set()
                    break
                if not self.stop.is_set():
                    self.sleep(max(1.0, min(LEASE_RENEW, next_at - self.clock())))
            return code
        except KeyboardInterrupt:
            code = 130
            return code
        finally:
            self.close(code)
            self._signals(previous)

    def _start_safely(self, once: bool) -> None:
        """Make the session and take the lease. In the loop, missing cookies or settings
        wait and retry (one note a day) instead of exiting, so launchd or systemd never
        restart it in a loop."""
        while not self.stop.is_set():
            try:
                self.start()
                return
            except (AuthError, ConfigError) as e:
                if once:
                    raise
                self.say(f"{e} (trying again in {round(AUTH_RETRY / 60)} min)")
                self._quiet_note(e)
                self.sleep(AUTH_RETRY)

    def _quiet_note(self, e: Exception) -> None:
        """A note before the state exists (no league yet): once per process."""
        if self._start_noted or self.dry_run:
            return
        self._start_noted = True
        text = ("benchboss cannot read your league: run benchboss login" if isinstance(e, AuthError)
                else f"benchboss is not set up: {e}")
        notify.send(notify.Note("benchboss monitor", text, "urgent", "start"), self.backends)

    def _round(self) -> float:
        """One tick with every error handled; returns the seconds to the next one."""
        now = self._now()
        try:
            self.tick()
            self._errors = 0
            self._auth_checked = False
            self.state["heartbeat"]["last_error"] = ""
            return core.next_poll(now, self.tips)
        except AuthError as e:
            if self._confirm_auth():
                return self._round()
            self._worse(3)
            self.state["heartbeat"].update(auth_wait=True, last_error=str(e))
            self._record("error", text=f"cookies rejected: {e}")
            self._note("benchboss monitor", "benchboss cannot read your league: run "
                       "benchboss login", "urgent", "auth")
            self._save()
            with contextlib.suppress(AuthError, ConfigError, BenchbossError):
                fresh = self.factory()  # `benchboss login` in another terminal fixes it
                self._restore_overrides()
                self.session = fresh
                self._overrides()
            return AUTH_RETRY
        except (NetworkError, EspnError) as e:
            self._errors += 1
            self._worse(1)
            blocked = isinstance(e, EspnError) and e.status in (403, 429)
            self.state["heartbeat"]["last_error"] = str(e)
            self._record("error", text=f"ESPN: {e}")
            soon = [t for t in self.tips if t > now]
            if blocked:
                self._note("benchboss monitor", "ESPN is blocking this machine's reads; "
                           "benchboss slows down and keeps trying.", "urgent", "blocked")
            elif soon and min(soon) - now < AUTH_CONFIRM:
                self._note("benchboss monitor", f"ESPN cannot be reached ({e}); an armed "
                           "player's game is near. benchboss keeps trying.", "urgent", "network")
            self._save()
            wait = BACKOFF[min(self._errors, len(BACKOFF)) - 1]
            if soon:
                wait = min(wait, max(15.0, (min(soon) - now).total_seconds() / 2))
            return wait
        except BenchbossError as e:
            self._errors += 1
            self._worse(1)
            self.state["heartbeat"]["last_error"] = str(e)
            self._record("error", text=str(e))
            self._save()
            return BACKOFF[min(self._errors, len(BACKOFF)) - 1]

    def _confirm_auth(self) -> bool:
        """Near an armed tip one 401 is not enough: read again 20 s later."""
        now = self._now()
        if self._auth_checked:
            self._auth_checked = False
            return False
        if not any(now < t < now + AUTH_CONFIRM for t in self.tips):
            return False
        self._auth_checked = True
        self.sleep(VERIFY_AFTER)
        return True

    def _signals(self, previous=None):
        """SIGTERM (launchd, systemd) ends the loop after the current tick."""
        if threading.current_thread() is not threading.main_thread():
            return None
        if not hasattr(signal, "SIGTERM"):
            return None
        if previous is not None:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signal.SIGTERM, previous)
            return None
        with contextlib.suppress(ValueError, OSError):
            return signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        return None


__all__ = ["Lease", "Monitor", "MonitorBusy", "base_roster", "heartbeat", "live_refusal",
           "read_lease", "read_state"]

"""The lineup log: one JSON line for every lineup change benchboss makes or considers.

Every writer uses it: Apply in the app ("tui"), ``benchboss optimize`` ("cli") and the
monitor ("monitor"), including its trial runs, the marks it is given and the status
changes it sees. ``benchboss autoswap log`` reads it back. It lives in
``logs/lineup-YYYY-MM.jsonl`` in the config folder (store.logs_dir), one file per month,
shared by every league (each record names its league). The demo keeps it in memory.

Every record has the keys in REQUIRED:

    v        record version (VERSION)
    at       ISO time with offset, from the session clock
    league   league id                team   your team id
    writer   one of WRITERS           event  one of EVENTS
    mode     one of MODES: "attended" (a person pressed Apply or answered yes), "trial"
             (the monitor planned it and sent nothing) or "live" (the monitor sent it)

and then the fields of its event (see EVENTS). Lineup changes ("apply", "autoswap") carry:
period, date, kind (ROSTER or FUTURE_ROSTER), moves [{player_id, player, from, to}] with
slot names, projected_before, projected_after, gain, outcome (service.Outcome), status
(ESPN's), error, guards [codes], and for "autoswap" the trigger {player_id, player, old,
new, tip} and intent (the id saved before the POST). Never cookies, member ids or
creationInfo: ``append`` passes every line through store.redact.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from benchboss import store
from benchboss.errors import BenchbossError

VERSION = 1
WRITERS = ("cli", "tui", "monitor")
MODES = ("attended", "trial", "live")
EVENTS = {
    "apply": "a lineup change sent by a person (Apply in the app, optimize in the CLI)",
    "autoswap": "the monitor's plan for a player who turned healthy: sent, or what it would send",
    "verify": "the monitor's check, after a write, that ESPN shows the new lineup",
    "flip": "a status change on a marked or watch-list player",
    "arm": "a player marked for auto-swap",
    "disarm": "a mark taken off",
    "pause": "auto-swap paused",
    "resume": "auto-swap resumed",
    "start": "the monitor started (version, mode, notification backends by name)",
    "stop": "the monitor stopped",
    "error": "something the monitor could not do (ESPN down, cookies expired)",
}
REQUIRED = ("v", "at", "league", "team", "writer", "event", "mode")


def path_for(when: dt.datetime) -> Path:
    return store.logs_dir() / f"lineup-{when:%Y-%m}.jsonl"


def record(session, writer: str, event: str, mode: str, **fields) -> dict:
    """A log record with the required keys filled from ``session`` (nothing is written)."""
    if writer not in WRITERS or event not in EVENTS or mode not in MODES:
        raise BenchbossError(f"bad lineup log record: writer={writer} event={event} mode={mode}")
    lg = session.league()
    return {"v": VERSION, "at": session.now.isoformat(timespec="seconds"), "league": lg.id,
            "team": lg.my_team_id, "writer": writer, "event": event, "mode": mode, **fields}


def append(session, writer: str, event: str, mode: str, **fields) -> dict:
    """Write one record (redacted) and return it as written."""
    rec = record(session, writer, event, mode, **fields)
    clean = json.loads(store.redact(json.dumps(rec, ensure_ascii=False, default=str),
                                    store.session_secrets(session)))
    store.append_jsonl(path_for(session.now), clean, memory=session.local_state)
    return clean


def read(session, months: int = 2) -> list[dict]:
    """This league's records from the last ``months`` monthly files, in the order they were
    written (oldest first)."""
    lg = session.league()
    first = session.now.date().replace(day=1)
    days, out = [], []
    for _ in range(max(1, months)):
        days.append(first)
        first = (first - dt.timedelta(days=1)).replace(day=1)
    for day in reversed(days):
        when = dt.datetime.combine(day, dt.time())
        out += [r for r in store.read_jsonl(path_for(when), memory=session.local_state)
                if r.get("league") == lg.id]
    return out


__all__ = ["EVENTS", "MODES", "REQUIRED", "VERSION", "WRITERS", "append", "path_for", "read",
           "record"]

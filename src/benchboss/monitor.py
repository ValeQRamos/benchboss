"""``benchboss monitor``: the one background process. It watches marked and watch-list
players, makes the auto-swap changes (or, in trial mode, says what it would have done),
and sends the notifications.

Built by the auto-swap package. The names below are the contract other code relies on.

Modes: trial (the default: reads, plans, notifies "benchboss would have started X for Y",
writes nothing to ESPN), live (``--live`` plus ``--yes`` or a yes at the prompt: sends the
change through Session.apply_plan), dry run (``--dry-run``: prints only; no notification,
no state, no log).

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
     "moved": {"<player id>": {"count": 1, "to": "G"}},
     "intents": {"<intent id>": {"at", "period", "items", "outcome"}},
     "counters": {"writes": 0, "failures": 0},
     "notified": {"<note key>": "<at>"},
     "alerts": [{"key", "kind", "player_id", "player", "text", "at", "urgent"}]}

    run(session, *, mode, once, notify, simulate, out) -> int   the exit code for --once
    tick(session, state, now) -> list[event dicts]              one read, flips, actions
"""

from __future__ import annotations

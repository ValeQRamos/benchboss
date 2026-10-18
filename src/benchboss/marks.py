"""Auto-swap marks: the players you checked so benchboss starts them when they turn healthy.

Built by the auto-swap package. The names below are the contract other code relies on.

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
"pause", "resume").

    MarkStore(session)
        .load() -> Marks          fresh read; .marks {id: Mark}, .paused, .error
        .arm(player, mode="auto", until=None, origin="cli") -> Mark
        .disarm(player_id, origin="cli") -> bool
        .clear(origin="cli") -> int
        .set_paused(paused, origin="cli") -> None
"""

from __future__ import annotations

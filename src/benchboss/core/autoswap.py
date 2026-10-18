"""Auto-swap logic with no I/O: who turned healthy, when to look again, what would change.

Built by the auto-swap package. The names below are the contract other code relies on.

    Flip(player_id, name, old, new, kind, tip)
        a status change between two reads. ``kind`` from the classes in espn.constants
        (status_class): "cleared" (risk or out to ok), "returning" (out to risk),
        "ruled_out" (ok or risk to out), "flagged" (ok to risk). A change inside one class
        is no flip. An unknown status (Player.injury_known False, or not in KNOWN_STATUSES)
        never makes a flip and never replaces the stored status.

    detect_flips(before, players, cal, period, now) -> list[Flip]
        ``before`` maps player id to the last known status; a player seen for the first
        time is recorded silently (no flip). ``tip`` is his game's start that day or None.

    next_poll(now, tips) -> float
        seconds until the next read, from the earliest untipped game among ``tips``:
        more than 6 h away 1800, 2 to 6 h 600, 45 min to 2 h 180, 10 to 45 min 60,
        under 10 min 30; plus or minus 10 percent; no game left today 1800.

    preview_flip(roster, slot_counts, period, cal, player_id, now) -> DayPlan
        the plan if ``player_id`` were healthy now: plan_day with his status set to ACTIVE
        and PlanOptions(now=now, movable=frozenset({player_id}), auto=True). The screen,
        ``benchboss autoswap add`` and the monitor's trial line all show this plan.
"""

from __future__ import annotations

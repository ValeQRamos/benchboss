"""Safety checks on a lineup plan before it is sent. Pure: no I/O.

``check(before, plan, slot_counts, cal, opts)`` returns every Violation it finds. A fatal
one stops the send: the CLI raises errors.GuardRefused (exit code 5), the monitor logs the
codes and notifies, and the result's outcome is service.Outcome.NOT_SENT. Attended sends
(Apply, ``benchboss optimize``) run the structural checks; automatic ones (``opts.auto``)
run all of them.

Codes (CODES has the text for each):

    G1  a move touches a frozen player (ESPN's lock, or his tip time plus the margin)
    G2  a move goes into or out of IR
    G3  a player lands in a slot he is not eligible for, or a slot ends over its count
    G4  a player who cannot score that day starts while one who can sits in a slot he fits
    G5  outside the scope guard: someone other than opts.movable, or more starters than
        opts.displace, changes between bench and lineup (automatic only)
    G6  the plan lowers the day's projection (automatic only)
    G7  more moves than MAX_MOVES, or more than MAX_BENCHED healthy starters with a game
        benched in one run: a broken read, not a decision (automatic only)
    G8  the data looks wrong: a player with an unknown status, or several players with a game
        and no projection (automatic only)
    G9  the day is not ESPN's today (automatic only: Session.current_period(strict=True))
"""

from __future__ import annotations

from dataclasses import dataclass

CODES = {
    "G1": "moves a player whose game has started or is about to",
    "G2": "moves a player into or out of IR",
    "G3": "puts a player in a slot he cannot fill",
    "G4": "starts a player who cannot score while one who can sits",
    "G5": "changes players outside the auto-swap scope",
    "G6": "lowers the day's projection",
    "G7": "changes more players than one run should",
    "G8": "the data from ESPN looks incomplete",
    "G9": "the day is not ESPN's current day",
}
AUTO_ONLY = frozenset({"G5", "G6", "G7", "G8", "G9"})
MAX_MOVES = 12
MAX_BENCHED = 3


@dataclass(frozen=True)
class Violation:
    code: str              # a key of CODES
    message: str           # one line for a person: "Dyson Daniels tipped at 7:00 PM"
    player_id: int | None = None
    fatal: bool = True


def check(before, plan, slot_counts, cal, opts=None) -> list[Violation]:
    """Every violation in ``plan`` (a core.lineup.DayPlan) against the roster it was planned
    from (``before``, list of RosterSpot). Implemented by the optimizer package."""
    raise NotImplementedError


__all__ = ["AUTO_ONLY", "CODES", "MAX_BENCHED", "MAX_MOVES", "Violation", "check"]

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
    G9  the day is not ESPN's today (automatic only: Session.current_period(strict=True)),
        the season is not on, or the league does not lock each player at his own tip-off.
        ``check`` cannot see ESPN's day; ``day_check`` does that part and the caller
        (Session.apply_plan) adds its violations to those of ``check``.

Every check is on the plan as it would be sent, against the roster it was planned from, so it
also catches a solver bug or a broken read, not only a bad decision.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass

from benchboss.espn.constants import BENCH, IR, LINEUP_LOCK_INDIVIDUAL, SLOT, status_class

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
# More players than this with a game and no projection, or with no injury status, in one
# read: ESPN sent part of the data, so an automatic run sends nothing.
MAX_UNPROJECTED = 2
MAX_UNKNOWN = 2


@dataclass(frozen=True)
class Violation:
    code: str              # a key of CODES
    message: str           # one line for a person: "Dyson Daniels tipped at 7:00 PM"
    player_id: int | None = None
    fatal: bool = True

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "player_id": self.player_id,
                "fatal": self.fatal}


def check(before, plan, slot_counts, cal, opts=None) -> list[Violation]:
    """Every violation in ``plan`` (a core.lineup.DayPlan) against the roster it was planned
    from (``before``, list of RosterSpot). G1 to G4 always; G5 to G8 when ``opts.auto``."""
    from benchboss.core.lineup import can_score, frozen_reasons, frozen_text, status_known

    out: list[Violation] = []
    period = plan.period
    where = {s.player.id: s for s in before}
    frozen = {**frozen_reasons(before, period, cal, opts), **plan.frozen}
    after = {pid: s.slot_id for pid, s in where.items()}
    seen: set[int] = set()
    for m in plan.moves:
        pl, pid = m.player, m.player.id
        spot = where.get(pid)
        if spot is None:
            out.append(Violation("G3", f"{pl.name} is not on your roster", pid))
            continue
        if pid in seen:
            out.append(Violation("G3", f"{pl.name} is moved twice", pid))
        elif spot.slot_id != m.from_slot:
            out.append(Violation("G3", f"{pl.name} is at {_slot(spot.slot_id)} on ESPN, "
                                       f"not {_slot(m.from_slot)}", pid))
        seen.add(pid)
        if pid in frozen:
            out.append(Violation("G1", f"{pl.name} cannot move: {frozen_text(frozen[pid])}", pid))
        if IR in (m.from_slot, m.to_slot):
            way = "out of" if m.from_slot == IR else "into"
            out.append(Violation("G2", f"{pl.name} would move {way} IR", pid))
        if m.to_slot not in (BENCH, IR) and (m.to_slot not in pl.eligible_slots
                                             or slot_counts.get(m.to_slot, 0) <= 0):
            out.append(Violation("G3", f"{pl.name} cannot play {_slot(m.to_slot)}", pid))
        if m.to_slot not in (BENCH, IR) and not can_score(pl, period, cal):
            why = "has no game" if not cal.plays(pl.pro_team_id, period) else f"is {pl.injury}"
            out.append(Violation("G4", f"{pl.name} would start but {why}", pid))
        after[pid] = m.to_slot
    for slot, n in sorted(Counter(s for s in after.values() if s not in (BENCH, IR)).items()):
        if n > slot_counts.get(slot, 0):
            out.append(Violation("G3", f"{n} players would be at {_slot(slot)}, which has room "
                                       f"for {slot_counts.get(slot, 0)}"))
    # nobody who can score is benched while a starter who cannot keeps a slot he fits
    idle = [(pid, slot) for pid, slot in after.items() if slot not in (BENCH, IR)
            and pid not in frozen and not can_score(where[pid].player, period, cal)]
    for m in plan.moves:
        if (m.to_slot == BENCH and m.from_slot not in (BENCH, IR) and m.player.id in where
                and can_score(m.player, period, cal)):
            for pid, slot in idle:
                if slot in m.player.eligible_slots:
                    out.append(Violation("G4", f"{m.player.name} would sit while "
                                               f"{where[pid].player.name} starts at "
                                               f"{_slot(slot)} and cannot score", m.player.id))
                    break
    if opts is None or not opts.auto:
        return out
    # --- automatic runs only -------------------------------------------------------------------
    entering = [m for m in plan.moves if m.from_slot in (BENCH, IR) and m.to_slot not in (BENCH, IR)]
    benched = [m for m in plan.moves if m.from_slot not in (BENCH, IR) and m.to_slot in (BENCH, IR)]
    if opts.movable is not None:
        for m in entering:
            if m.player.id not in opts.movable:
                out.append(Violation("G5", f"{m.player.name} would start, but auto-swap was "
                                           "not set up for him", m.player.id))
        comers = sum(1 for m in entering if m.player.id in opts.movable)
        displaced = [m for m in benched if m.player.id not in opts.movable]
        if len(displaced) > opts.displace * comers:
            names = ", ".join(m.player.name for m in displaced)
            out.append(Violation("G5", f"would bench {names} for {comers} player(s) coming in"))
    if plan.projected < plan.projected_before - 1e-6:
        out.append(Violation("G6", f"projects {plan.projected:.1f}, down from "
                                   f"{plan.projected_before:.1f}"))
    if len(plan.moves) > MAX_MOVES:
        out.append(Violation("G7", f"{len(plan.moves)} moves in one run (at most {MAX_MOVES})"))
    healthy = [m for m in benched if status_known(m.player)
               and status_class(m.player.injury_status) == "ok"
               and cal.plays(m.player.pro_team_id, period)]
    if len(healthy) > MAX_BENCHED:
        out.append(Violation("G7", f"would bench {len(healthy)} healthy starters with a game "
                                   f"(at most {MAX_BENCHED})"))
    for m in plan.moves:
        if not status_known(m.player):
            out.append(Violation("G8", f"ESPN sent no injury status for {m.player.name}",
                                 m.player.id))
    active = [s.player for s in before if s.slot_id != IR]
    unprojected = [p for p in active if not p.proj and can_score(p, period, cal)]
    if len(unprojected) > MAX_UNPROJECTED:
        out.append(Violation("G8", f"{len(unprojected)} players with a game have no projection"))
    unknown = [p for p in active if not status_known(p)]
    if len(unknown) > MAX_UNKNOWN:
        out.append(Violation("G8", f"ESPN sent no injury status for {len(unknown)} players"))
    return out


def day_check(period: int, *, espn_day: int | None, today_period: int, in_season: bool,
              lock_type: str, cal=None) -> list[Violation]:
    """G9 for an automatic change of ``period``: it must be ESPN's current day
    (``espn_day``, status.latestScoringPeriod read just now) and today on this computer's
    clock (``today_period``), in season, in a league that locks each player at his tip-off."""
    def day(p: int) -> str:
        if cal is None:
            return f"day {p}"
        d: dt.date = cal.date_of(p)
        return f"{d:%a %b} {d.day}"

    out = []
    if not in_season:
        out.append(Violation("G9", "the fantasy season is not on, so nothing changes on its own"))
    if espn_day is None:
        out.append(Violation("G9", "ESPN did not say which day it is"))
    elif espn_day != today_period:
        out.append(Violation("G9", f"ESPN is on {day(espn_day)} but this computer's clock says "
                                   f"{day(today_period)}"))
    elif period != espn_day:
        out.append(Violation("G9", f"{day(period)} is not today on ESPN ({day(espn_day)})"))
    if lock_type != LINEUP_LOCK_INDIVIDUAL:
        out.append(Violation("G9", "this league does not lock each player at his own tip-off, "
                                   "so automatic changes are off"))
    return out


def _slot(slot: int) -> str:
    return SLOT.get(slot, str(slot))


__all__ = ["AUTO_ONLY", "CODES", "MAX_BENCHED", "MAX_MOVES", "MAX_UNKNOWN", "MAX_UNPROJECTED",
           "Violation", "check", "day_check"]

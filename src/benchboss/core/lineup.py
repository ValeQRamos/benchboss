"""Daily lineup optimizer.

For one scoring period (day) it starts the players with a game and the best projection and
benches everyone who is resting, OUT, suspended or simply projects less. Doubtful players
count 25% of their projection, day-to-day and questionable 75%. The assignment is solved
exactly with a dynamic program over (slot, set of used players), so position slots, combo
slots (G, F) and utility slots are filled optimally.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from benchboss.core.calendar import SeasonCalendar
from benchboss.espn.constants import BENCH, INJURY_FACTOR, IR, SLOT
from benchboss.espn.models import Player, RosterSpot

# A player whose game starts within this margin counts as locked, even while ESPN's
# lineupLocked flag still says false. One value for every caller (Optimize, the monitor).
LOCK_MARGIN = dt.timedelta(minutes=3)
# The smallest gain (projected points that day) an automatic change must bring to be sent.
MIN_GAIN_AUTO = 1.0


def day_value(p: Player, period: int, cal: SeasonCalendar) -> float:
    """Expected fantasy points from this player on this day (0 when he has no game)."""
    if not cal.plays(p.pro_team_id, period):
        return 0.0
    return p.proj * INJURY_FACTOR.get(p.injury_status or "", 1.0)


def best_lineup(pool: list[RosterSpot], slot_counts: dict[int, int],
                values: list[float], can_play: list[bool] | None = None) -> dict[int, int]:
    """Index into ``pool`` -> starting slot id, maximizing the sum of ``values``.

    Ties keep players where they already are (a tiny bonus), so a "no-op" day stays a no-op.
    A player who plays but has no projection yet still beats an empty slot. ``can_play``
    (one flag per player) marks who can score that day at all: the others are worth nothing,
    so they are never moved into a slot, only left where they already are.
    """
    slots = [s for s, n in sorted(slot_counts.items()) if s not in (BENCH, IR) for _ in range(n)]
    elig = [set(spot.player.eligible_slots) for spot in pool]
    worth = [values[i] or (1e-3 if can_play is None or can_play[i] else 0.0)
             for i in range(len(pool))]
    best: dict[int, tuple[float, tuple]] = {0: (0.0, ())}
    for sl in slots:
        nxt: dict[int, tuple[float, tuple]] = {}
        for mask, (val, picks) in best.items():
            options = [(None, 0.0)] + [
                (i, worth[i] + (1e-6 if pool[i].slot_id == sl else 0.0))
                for i in range(len(pool)) if not mask >> i & 1 and sl in elig[i]
                and (worth[i] > 0 or pool[i].slot_id == sl)]
            for i, v in options:
                m2 = mask if i is None else mask | 1 << i
                cand = (val + v, picks + ((i, sl),))
                if m2 not in nxt or cand[0] > nxt[m2][0]:
                    nxt[m2] = cand
        best = nxt
    _, picks = max(best.values(), key=lambda x: x[0])
    return {i: sl for i, sl in picks if i is not None}


@dataclass
class Move:
    player: Player
    from_slot: int
    to_slot: int

    def item(self) -> dict:
        return {"playerId": self.player.id, "type": "LINEUP",
                "fromLineupSlotId": self.from_slot, "toLineupSlotId": self.to_slot}

    def __str__(self) -> str:
        return f"{self.player.name} {SLOT.get(self.from_slot)} -> {SLOT.get(self.to_slot)}"


@dataclass(frozen=True)
class PlanOptions:
    """How ``plan_day`` may change a day. ``None`` (no options) keeps the 1.0.3 behavior.

    now          freeze every player whose game starts at or before ``now + lock_margin``
                 (he keeps his slot and is never moved), on top of ESPN's lineupLocked flag
    lock_margin  see LOCK_MARGIN
    movable      the scope guard for automatic changes: None lets the optimizer move anyone;
                 a set of player ids lets only them change between bench and lineup, plus at
                 most ``displace`` starters each, the lowest valued unlocked starters they can
                 replace (directly or through slot shuffles among starters). Nobody else
                 changes between bench and lineup.
    displace     see movable
    min_gain     a plan that gains less than this is not sent (Outcome.BELOW_MIN_GAIN)
    auto         an unattended run: every guard in core/guard.py applies, ESPN's day must be
                 today (Session.current_period(strict=True)), a player with an unknown status
                 or a TBD tip time is frozen, and only ROSTER (today) is ever sent
    """
    now: dt.datetime | None = None
    lock_margin: dt.timedelta = LOCK_MARGIN
    movable: frozenset[int] | None = None
    displace: int = 1
    min_gain: float = 0.0
    auto: bool = False


@dataclass
class DayPlan:
    period: int
    moves: list[Move] = field(default_factory=list)
    starters: list[tuple[Player, int, float]] = field(default_factory=list)  # player, slot, value
    bench: list[tuple[Player, str]] = field(default_factory=list)            # player, reason
    projected: float = 0.0
    projected_before: float = 0.0  # the same day as the lineup stands, before the moves
    frozen: dict[int, str] = field(default_factory=dict)  # player id -> "locked", "tipped 7:00 PM"
    notes: list[str] = field(default_factory=list)        # one line each, shown under the plan

    @property
    def changed(self) -> bool:
        return bool(self.moves)

    def items(self) -> list[dict]:
        return [m.item() for m in self.moves]


def plan_day(roster: list[RosterSpot], slot_counts: dict[int, int], period: int,
             cal: SeasonCalendar, opts: PlanOptions | None = None) -> DayPlan:
    """Best lineup for one day.

    Players whose lineup is locked (their game has started; ESPN locks each player at his own
    tip-off) stay exactly where they are: they keep their slot and are never moved, so a
    late run only rearranges players who can still be changed. ``opts`` (PlanOptions) adds
    the freeze by tip time, the scope guard and the rules for unattended runs; without it
    the plan is exactly what 1.0.3 made.
    """
    plan = DayPlan(period)
    active = [s for s in roster if s.slot_id != IR]
    locked = [s for s in active if s.player.locked]
    pool = [s for s in active if not s.player.locked]
    counts = dict(slot_counts)
    for s in locked:
        value = day_value(s.player, period, cal)
        if s.is_starting:
            counts[s.slot_id] = max(0, counts.get(s.slot_id, 0) - 1)
            plan.starters.append((s.player, s.slot_id, value))
            plan.projected += value
        else:
            plan.bench.append((s.player, "locked"))
    values = [day_value(s.player, period, cal) for s in pool]
    can_play = [cal.plays(s.player.pro_team_id, period)
                and INJURY_FACTOR.get(s.player.injury_status or "", 1.0) > 0 for s in pool]
    assign = best_lineup(pool, counts, values, can_play)
    for i, spot in enumerate(pool):
        target = assign.get(i, BENCH)
        if spot.slot_id != target:
            plan.moves.append(Move(spot.player, spot.slot_id, target))
        if i in assign:
            plan.starters.append((spot.player, target, values[i]))
            plan.projected += values[i]
        else:
            plan.bench.append((spot.player, _bench_reason(spot.player, period, cal)))
    plan.starters.sort(key=lambda x: (x[1], -x[2]))
    return plan


def plan_gain(p: DayPlan, cal: SeasonCalendar) -> float:
    """Projected points the moves add that day: who comes in minus who goes out."""
    values = {pl.id: v for pl, _, v in p.starters}
    out = 0.0
    for m in p.moves:
        starts_now = m.from_slot not in (BENCH, IR)
        starts_after = m.to_slot not in (BENCH, IR)
        if starts_after and not starts_now:
            out += values.get(m.player.id, day_value(m.player, p.period, cal))
        elif starts_now and not starts_after:
            out -= day_value(m.player, p.period, cal)
    return out


def _bench_reason(p: Player, period: int, cal: SeasonCalendar) -> str:
    if not cal.plays(p.pro_team_id, period):
        return "no game"
    if INJURY_FACTOR.get(p.injury_status or "", 1.0) == 0:
        return p.injury
    tag = f"{p.injury} " if p.injury else ""
    return f"{tag}proj {p.proj:.1f}"

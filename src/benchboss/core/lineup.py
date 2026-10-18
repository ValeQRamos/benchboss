"""Daily lineup optimizer.

For one scoring period (day) it starts the players with a game and the best projection and
benches everyone who is resting, OUT, suspended or simply projects less. Doubtful players
count 25% of their projection, day-to-day and questionable 75%. The assignment is solved
exactly with a dynamic program over (slot, set of used players), so position slots, combo
slots (G, F) and utility slots are filled optimally.

Some players are frozen: they keep their slot and are never moved. ESPN's lineupLocked flag
and the IR slot always freeze a player. With PlanOptions a player also freezes from
``LOCK_MARGIN`` before his tip-off, whatever the flag says (it can be minutes old), and an
unattended run (``auto``) freezes anyone whose injury status ESPN did not send or whose tip
time is not set. Ties: the higher total first, then players staying in their slot; what is
still tied after that goes to the first player in ESPN's roster order (what 1.0.3 did, so
Optimize shows the same plans), or in an unattended run to the lower player id, so that the
order ESPN lists the roster in never changes what is sent.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from benchboss.core.calendar import SeasonCalendar, clock
from benchboss.espn.constants import BENCH, INJURY_FACTOR, IR, SLOT, status_class
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


def can_score(p: Player, period: int, cal: SeasonCalendar) -> bool:
    """He has a game that day and a status that lets him play (OUT, SUSP and the leaves do not)."""
    return cal.plays(p.pro_team_id, period) and INJURY_FACTOR.get(p.injury_status or "", 1.0) > 0


def status_known(p: Player) -> bool:
    """ESPN sent an injury status and it is one benchboss knows. An unknown one is never
    read as healthy by anything that acts on its own."""
    return p.injury_known and status_class(p.injury_status) != "unknown"


def best_lineup(pool: list[RosterSpot], slot_counts: dict[int, int],
                values: list[float], can_play: list[bool] | None = None, *,
                bench_only: list[bool] | None = None, must_start: list[bool] | None = None,
                displace: int = 1, stable: bool = False) -> dict[int, int]:
    """Index into ``pool`` -> starting slot id, maximizing the sum of ``values``.

    Ties keep players where they already are (a tiny bonus), so a "no-op" day stays a no-op.
    A player who plays but has no projection yet still beats an empty slot. ``can_play``
    (one flag per player) marks who can score that day at all: the others are worth nothing,
    so they are never moved into a slot, only left where they already are. An exact tie
    left after that goes to the first player in ``pool``, or with ``stable`` to the lower
    player id, so that the order of ``pool`` never changes the answer.

    ``bench_only`` and ``must_start`` (one flag per player) are the scope guard of an
    automatic change: a bench_only player never takes a starting slot, and a must_start
    starter keeps one (any slot he can fill) unless he is one of at most ``displace``
    starters benched for each other bench player who comes in.
    """
    n = len(pool)
    order = sorted(range(n), key=lambda i: pool[i].player.id) if stable else list(range(n))
    slots = [s for s, c in sorted(slot_counts.items()) if s not in (BENCH, IR) for _ in range(c)]
    elig = [set(pool[i].player.eligible_slots) for i in order]
    here = [pool[i].slot_id for i in order]
    worth = [values[i] or (1e-3 if can_play is None or can_play[i] else 0.0) for i in order]
    blocked = [bool(bench_only and bench_only[i]) for i in order]
    best: dict[int, tuple[float, tuple]] = {0: (0.0, ())}
    for sl in slots:
        nxt: dict[int, tuple[float, tuple]] = {}
        for mask, (val, picks) in best.items():
            options = [(None, 0.0)] + [
                (k, worth[k] + (1e-6 if here[k] == sl else 0.0))
                for k in range(n) if not mask >> k & 1 and sl in elig[k] and not blocked[k]
                and (worth[k] > 0 or here[k] == sl)]
            for k, v in options:
                m2 = mask if k is None else mask | 1 << k
                cand = (val + v, picks + ((k, sl),))
                if m2 not in nxt or cand[0] > nxt[m2][0]:
                    nxt[m2] = cand
        best = nxt
    finals = list(best.items())
    if must_start is not None:
        keep = sum(1 << k for k in range(n) if must_start[order[k]])
        comers = sum(1 << k for k in range(n) if not blocked[k] and here[k] in (BENCH, IR))
        finals = [(m, x) for m, x in finals
                  if bin(keep & ~m).count("1") <= displace * bin(comers & m).count("1")]
        if not finals:  # cannot happen with a lineup ESPN accepted; change nothing then
            return {i: s.slot_id for i, s in enumerate(pool) if s.is_starting}
    _, picks = max((x for _, x in finals), key=lambda x: x[0])
    return {order[k]: sl for k, sl in picks if k is not None}


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
                 (he keeps his slot and is never moved), on top of ESPN's lineupLocked flag.
                 Timezone aware; Optimize in the app and the CLI pass the session clock.
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
                 or a TBD tip time is frozen, and only ROSTER (today) is ever sent. Without
                 ``now`` every player with a game that day is frozen.
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


def frozen_reasons(roster: list[RosterSpot], period: int, cal: SeasonCalendar,
                   opts: PlanOptions | None = None) -> dict[int, str]:
    """Player id -> why nobody may move him that day: "IR", "locked" (ESPN's flag),
    "tipped 7:00 PM" or "starts 7:00 PM" (``opts.now`` plus the margin reached his tip), and
    for ``opts.auto`` also "unknown status", "tip time TBD", "game does not lock" and
    "no clock". Players not in the result may move."""
    out: dict[int, str] = {}
    now = opts.now if opts else None
    if now is not None and now.tzinfo is None:
        now = now.astimezone()  # a naive time is this computer's
    for s in roster:
        p = s.player
        if s.slot_id == IR:
            out[p.id] = "IR"
        elif p.locked:
            out[p.id] = "locked"
        elif opts is not None:
            game = cal.game(p.pro_team_id, period)
            if game is not None and now is not None and game.start <= now + opts.lock_margin:
                word = "tipped" if game.start <= now else "starts"
                out[p.id] = f"{word} {clock(game.start, now.tzinfo)}"
            elif not opts.auto:
                continue
            elif not status_known(p):
                out[p.id] = "unknown status"
            elif game is None:
                continue
            elif now is None:
                out[p.id] = "no clock"
            elif game.tbd:
                out[p.id] = "tip time TBD"
            elif not game.valid_for_locking:
                out[p.id] = "game does not lock"
    return out


def plan_day(roster: list[RosterSpot], slot_counts: dict[int, int], period: int,
             cal: SeasonCalendar, opts: PlanOptions | None = None) -> DayPlan:
    """Best lineup for one day.

    Frozen players (``frozen_reasons``: ESPN's lock flag, IR, and with ``opts`` the tip time
    plus the margin) stay exactly where they are: they keep their slot and are never moved,
    so a late run only rearranges players who can still be changed. ``opts`` (PlanOptions)
    adds the freeze by tip time, the scope guard and the rules for unattended runs; without
    it the plan is exactly what 1.0.3 made.
    """
    plan = DayPlan(period)
    plan.frozen = frozen_reasons(roster, period, cal, opts)
    active = [s for s in roster if s.slot_id != IR]
    plan.projected_before = sum(day_value(s.player, period, cal) for s in active if s.is_starting)
    fixed = [s for s in active if s.player.id in plan.frozen]
    pool = [s for s in active if s.player.id not in plan.frozen]
    counts = dict(slot_counts)
    for s in fixed:
        value = day_value(s.player, period, cal)
        if s.is_starting:
            counts[s.slot_id] = max(0, counts.get(s.slot_id, 0) - 1)
            plan.starters.append((s.player, s.slot_id, value))
            plan.projected += value
        else:
            why = plan.frozen[s.player.id]
            if why != "locked" and not cal.plays(s.player.pro_team_id, period):
                why = "no game"
            plan.bench.append((s.player, why))
    movable = opts.movable if opts else None
    bench_only = must_start = None
    if movable is not None:
        bench_only = [s.player.id not in movable and not s.is_starting for s in pool]
        must_start = [s.player.id not in movable and s.is_starting for s in pool]
    values = [day_value(s.player, period, cal) for s in pool]
    can_play = [can_score(s.player, period, cal) for s in pool]
    assign = best_lineup(pool, counts, values, can_play, bench_only=bench_only,
                         must_start=must_start, displace=opts.displace if opts else 1,
                         stable=bool(opts and opts.auto))
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
    if opts is not None:
        plan.notes = _notes(roster, plan, period, cal, opts)
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


def frozen_text(why: str) -> str:
    """A frozen reason (``frozen_reasons``) as words: "his game tipped at 7:00 PM"."""
    if why.startswith("tipped "):
        return f"his game tipped at {why[7:]}"
    if why.startswith("starts "):
        return f"his game starts at {why[7:]}, too close to change"
    return {"IR": "he is on IR", "locked": "his game has started",
            "unknown status": "ESPN sent no injury status for him",
            "tip time TBD": "his tip time is not set yet",
            "game does not lock": "ESPN does not lock lineups by his game",
            "no clock": "there was no clock to check his tip time"}.get(why, why)


def _notes(roster: list[RosterSpot], plan: DayPlan, period: int, cal: SeasonCalendar,
           opts: PlanOptions) -> list[str]:
    """One plain line for each thing an unattended caller should know: a player left alone
    because ESPN sent no status, and for each movable player why he did not move."""
    notes = []
    moved = {m.player.id for m in plan.moves}
    starting = {pl.id for pl, _, _ in plan.starters}
    for s in roster:
        p, why = s.player, plan.frozen.get(s.player.id)
        if opts.movable is None or p.id not in opts.movable:
            if why == "unknown status":
                notes.append(f"ESPN sent no injury status for {p.name}: he stays where he is.")
        elif why:
            notes.append(f"{p.name} is not moved: {frozen_text(why)}.")
        elif p.id in moved or p.id in starting:
            continue
        elif not cal.plays(p.pro_team_id, period):
            notes.append(f"{p.name} has no game that day.")
        elif not can_score(p, period, cal):
            notes.append(f"{p.name} is {p.injury or 'out'}, so he stays on the bench.")
        else:
            notes.append(f"{p.name} stays on the bench: no starter he can replace projects less.")
    return notes

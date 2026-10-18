"""Auto-swap logic with no I/O: who turned healthy, when to look again, what would change.

The monitor (monitor.py), the Auto-swap screen and ``benchboss autoswap`` all use this.

    Flip(player_id, name, old, new, kind, tip, started)
        a status change between two reads. ``kind`` from the classes in espn.constants
        (status_class): "cleared" (risk or out to ok), "returning" (out to risk),
        "ruled_out" (ok or risk to out), "flagged" (ok to risk). A change inside one class
        is no flip. An unknown status (Player.injury_known False, or not in KNOWN_STATUSES)
        never makes a flip and never replaces the stored status.

    detect_flips(before, players, cal, period, now) -> list[Flip]
        ``before`` maps player id to the last known status; a player seen for the first
        time is recorded silently (no flip). ``tip`` is his game's start that day or None,
        ``started`` whether that tip is at or before ``now``.

    next_poll(now, tips) -> float
        seconds until the next read, from the earliest untipped game among ``tips``:
        more than 6 h away 1800, 2 to 6 h 600, 45 min to 2 h 180, 10 to 45 min 60,
        under 10 min 30; plus or minus 10 percent; no game left today 1800.

    preview_flip(roster, slot_counts, period, cal, player_id, now) -> DayPlan
        the plan if ``player_id`` were healthy now: plan_day with his status set to ACTIVE
        and PlanOptions(now=now, movable=frozenset({player_id}), auto=True). The screen,
        ``benchboss autoswap add`` and the monitor's trial line all show this plan.

    describe(roster, plan, player_id, cal, period, now) -> Preview
        that plan in words, for the confirmation ("If he turns healthy before his 7:00 PM
        tip, benchboss starts him at G and benches Scotty Pippen Jr.").

    out_of_scope(before, plan, movable, displace) -> list[str]
        the monitor's own check that an automatic plan only moves the player who turned
        healthy and the one starter he displaces (core/guard.py G5 says the same; this one
        runs even when the guards are not there).

    frozen_moves(plan, cal, now) -> list[str]
        the monitor's own check that an automatic plan never moves a player whose lineup is
        locked, whose game starts within LOCK_MARGIN (or started), or whose game time ESPN
        has not set (core/guard.py G1 says the same).
"""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from benchboss.core.calendar import SeasonCalendar, clock
from benchboss.core.lineup import (
    LOCK_MARGIN,
    MIN_GAIN_AUTO,
    DayPlan,
    PlanOptions,
    plan_day,
    plan_gain,
)
from benchboss.espn.constants import (
    BENCH,
    INJURY_TAG,
    IR,
    KNOWN_STATUSES,
    OUT_STATUSES,
    SLOT,
    status_class,
)
from benchboss.espn.models import Player, RosterSpot

# (class before, class after) -> flip kind
FLIP_KINDS = {("risk", "ok"): "cleared", ("out", "ok"): "cleared", ("out", "risk"): "returning",
              ("ok", "out"): "ruled_out", ("risk", "out"): "ruled_out", ("ok", "risk"): "flagged"}
# a player the monitor started who turns one of these before his tip goes back to the bench
REVERT_STATUSES = OUT_STATUSES | {"DOUBTFUL"}
MAX_MOVES = 12  # more moves than this in one automatic plan means a broken read (guard G7)

# How long to wait between reads, by the time left to the earliest armed tip
CADENCE = ((dt.timedelta(hours=6), 1800.0), (dt.timedelta(hours=2), 600.0),
           (dt.timedelta(minutes=45), 180.0), (dt.timedelta(minutes=10), 60.0),
           (dt.timedelta(0), 30.0))
IDLE = 1800.0  # no armed game left today
JITTER = 0.10


@dataclass(frozen=True)
class Flip:
    player_id: int
    name: str
    old: str
    new: str
    kind: str                       # cleared, returning, ruled_out, flagged
    tip: dt.datetime | None = None  # his game's start that day
    started: bool = False           # the tip is at or before the time of the read

    @property
    def cleared(self) -> bool:
        return self.kind == "cleared"

    def to_dict(self) -> dict:
        return {"player_id": self.player_id, "player": self.name, "old": self.old,
                "new": self.new, "kind": self.kind,
                "tip": self.tip.isoformat() if self.tip else None}


def known_status(p: Player) -> str | None:
    """His status when ESPN sent one we know, else None (unknown is never healthy)."""
    if not p.injury_known or p.injury_status not in KNOWN_STATUSES:
        return None
    return p.injury_status


def flip_kind(old: str | None, new: str | None) -> str | None:
    """The kind of change from ``old`` to ``new``, or None (same class, or unknown)."""
    return FLIP_KINDS.get((status_class(old), status_class(new)))


def detect_flips(before: Mapping[int, str], players: Iterable[Player], cal: SeasonCalendar,
                 period: int, now: dt.datetime) -> list[Flip]:
    """Every flip between ``before`` and this read. First sight is silent."""
    out = []
    for p in players:
        new, old = known_status(p), before.get(p.id)
        kind = flip_kind(old, new) if new and old else None
        if kind is None:
            continue
        game = cal.game(p.pro_team_id, period) if period >= 1 else None
        tip = game.start if game else None
        out.append(Flip(p.id, p.name, old, new, kind, tip, tip is not None and tip <= now))
    return out


def remember(before: Mapping[int, str], players: Iterable[Player]) -> dict[int, str]:
    """``before`` updated with this read: a known status replaces the old one, an unknown
    one keeps it."""
    out = dict(before)
    for p in players:
        st = known_status(p)
        if st:
            out[p.id] = st
    return out


def bad_read(players: list[Player], asked: Iterable[int], before: Mapping[int, str]) -> str:
    """Why a read must not be trusted ("" when it is fine): ESPN sent nobody back, or two
    or more players we had a status for came back without one. A bad read changes nothing:
    no stored status, no flip, no write."""
    asked = list(asked)
    if asked and not players:
        return "ESPN sent none of the players asked for"
    lost = [p.name for p in players if p.id in before and known_status(p) is None]
    if len(lost) >= 2:
        return f"ESPN sent no injury status for {len(lost)} players ({', '.join(lost[:3])})"
    return ""


def next_poll(now: dt.datetime, tips: Iterable[dt.datetime | None], *, jitter: float = JITTER,
              rng: random.Random | None = None) -> float:
    """Seconds to the next read (see CADENCE), with ``jitter`` so reads do not line up."""
    ahead = [t for t in tips if t is not None and t > now]
    base = IDLE
    if ahead:
        left = min(ahead) - now
        base = next(s for limit, s in CADENCE if left > limit or limit == dt.timedelta(0))
    r = rng or random
    return base * (1 + r.uniform(-jitter, jitter))


# --- plans -------------------------------------------------------------------------------------

def as_healthy(roster: list[RosterSpot], player_id: int, status: str = "ACTIVE") -> list[RosterSpot]:
    """``roster`` with one player's status replaced (the others are the same objects)."""
    return [replace(s, player=replace(s.player, injury_status=status, injury_known=True))
            if s.player.id == player_id else s for s in roster]


def auto_options(now: dt.datetime | None, player_ids: Iterable[int]) -> PlanOptions:
    """The options of every automatic plan: freeze by tip time, only these players and one
    displaced starter each, the minimum gain, every guard."""
    return PlanOptions(now=now, movable=frozenset(player_ids), min_gain=MIN_GAIN_AUTO, auto=True)


def preview_flip(roster: list[RosterSpot], slot_counts: dict[int, int], period: int,
                 cal: SeasonCalendar, player_id: int, now: dt.datetime | None) -> DayPlan:
    """The plan if ``player_id`` turned healthy now."""
    return plan_day(as_healthy(roster, player_id), slot_counts, period, cal,
                    auto_options(now, {player_id}))


@dataclass(frozen=True)
class Swap:
    """What an automatic plan does for the player who turned healthy."""
    slot: str = ""                 # where he starts ("G"), "" when he does not move in
    benched: Player | None = None  # the starter who goes to the bench for him
    others: tuple[str, ...] = ()   # every other move ("Brandon Miller SF -> F")
    gain: float = 0.0

    @property
    def starts(self) -> bool:
        return bool(self.slot)

    def phrase(self, name: str, past: bool = False) -> str:
        """ "started Dyson Daniels at G and benched Scotty Pippen Jr." (or "starts ...")."""
        start, bench = ("started", "benched") if past else ("starts", "benches")
        text = f"{start} {name} at {self.slot}"
        if self.benched is not None:
            text += f" and {bench} {self.benched.name}"
        return text


def swap_of(plan: DayPlan, player_id: int, cal: SeasonCalendar) -> Swap:
    """The plan's moves seen from the player who turned healthy."""
    slot, benched, others = "", None, []
    for m in plan.moves:
        if m.player.id == player_id and m.to_slot not in (BENCH, IR) and m.from_slot in (BENCH, IR):
            slot = SLOT.get(m.to_slot, str(m.to_slot))
        elif m.from_slot not in (BENCH, IR) and m.to_slot == BENCH and benched is None:
            benched = m.player
        else:
            others.append(str(m))
    return Swap(slot, benched, tuple(others), plan_gain(plan, cal))


def player_in(plan: DayPlan, player_id: int) -> Player | None:
    """The player as the plan's own roster read saw him."""
    for p, _, _ in plan.starters:
        if p.id == player_id:
            return p
    for p, _ in plan.bench:
        if p.id == player_id:
            return p
    return next((m.player for m in plan.moves if m.player.id == player_id), None)


def lineup_before(plan: DayPlan) -> dict[int, int]:
    """player id -> slot id as the lineup stood before the plan's moves (IR not included)."""
    out = {p.id: slot for p, slot, _ in plan.starters}
    out.update((p.id, BENCH) for p, _ in plan.bench)
    out.update((m.player.id, m.from_slot) for m in plan.moves)
    return out


def out_of_scope(before: Mapping[int, int], plan: DayPlan, movable: Iterable[int],
                 displace: int = 1) -> list[str]:
    """Why an automatic plan moves more than it may (an empty list when it is fine): someone
    other than ``movable`` starts, more than ``displace`` starters each go to the bench, a
    move touches IR, or there are more than MAX_MOVES moves. ``before`` maps player id to
    slot id as the lineup stood (``lineup_before``)."""
    movable = set(movable)
    names = {m.player.id: m.player.name for m in plan.moves}
    after = dict(before)
    out = []
    for m in plan.moves:
        if IR in (m.from_slot, m.to_slot) or before.get(m.player.id) == IR:
            out.append(f"{m.player.name} would move into or out of IR")
        after[m.player.id] = m.to_slot
    if len(plan.moves) > MAX_MOVES:
        out.append(f"{len(plan.moves)} moves in one run")

    def starts(s: int | None) -> bool:
        return s is not None and s not in (BENCH, IR)

    started = [pid for pid in after if starts(after[pid]) and not starts(before.get(pid))]
    benched = [pid for pid in after if starts(before.get(pid)) and not starts(after[pid])]
    for pid in started:
        if pid not in movable:
            out.append(f"{names.get(pid, pid)} would start without being armed")
    extra = [pid for pid in benched if pid not in movable]
    if len(extra) > displace * max(1, len(movable)):
        out.append("more starters would go to the bench than one per armed player: "
                   + ", ".join(str(names.get(p, p)) for p in extra))
    return out


def frozen_moves(plan: DayPlan, cal: SeasonCalendar, now: dt.datetime | None) -> list[str]:
    """Why an automatic plan touches a player it must leave alone (an empty list when it
    does not): ESPN locked him, his game starts within LOCK_MARGIN of ``now`` or already
    started, or ESPN has not set his game time yet. A player with no game that day may move
    (benching him is what makes room)."""
    out = []
    tz = now.tzinfo if now is not None else None
    for m in plan.moves:
        p = m.player
        game = cal.game(p.pro_team_id, plan.period) if plan.period >= 1 else None
        if p.locked:
            out.append(f"{p.name} is locked on ESPN")
        elif game is not None and (game.tbd or not game.valid_for_locking):
            out.append(f"ESPN has not set the time of {p.name}'s game")
        elif game is not None and now is not None and game.start <= now + LOCK_MARGIN:
            out.append(f"{p.name}'s game starts at {clock(game.start, tz)}")
    return out


# --- words -------------------------------------------------------------------------------------

def tag(status: str | None) -> str:
    """ "DTD", "OUT", "Q"; "healthy" for ACTIVE, NORMAL and PROBABLE; "unknown" else."""
    if status_class(status) == "ok":
        return "healthy"
    return INJURY_TAG.get(status or "", "") or "unknown"


@dataclass(frozen=True)
class Preview:
    """The plan for one roster player, in words (``line``)."""
    player_id: int
    name: str
    kind: str          # starts, starting, sits, small, no_game, started, ir, gone
    swap: Swap = field(default_factory=Swap)
    tip: dt.datetime | None = None
    status: str = ""   # his status now
    text: str = ""     # one sentence: what benchboss would do

    @property
    def would_change(self) -> bool:
        return self.kind == "starts"

    def to_dict(self) -> dict:
        b = self.swap.benched
        return {"kind": self.kind, "text": self.text, "slot": self.swap.slot or None,
                "benches": b.name if b else None, "benches_id": b.id if b else None,
                "gain": round(self.swap.gain, 1), "other_moves": list(self.swap.others)}


def describe(roster: list[RosterSpot], plan: DayPlan | None, player_id: int,
             cal: SeasonCalendar, period: int, now: dt.datetime,
             tz: dt.tzinfo | None = None) -> Preview:
    """What arming ``player_id`` would do, from ``plan`` (``preview_flip``). ``tz`` is the
    clock tip times are written in (pass ``session.now.tzinfo``)."""
    spot = next((s for s in roster if s.player.id == player_id), None)
    if spot is None:
        return Preview(player_id, str(player_id), "gone", text="He is not on your roster.")
    p = spot.player
    game = cal.game(p.pro_team_id, period) if period >= 1 else None
    tip = game.start if game else None
    status = p.injury_status if p.injury_known else ""
    base = {"player_id": p.id, "name": p.name, "tip": tip, "status": status}
    if spot.slot_id == IR:
        return Preview(**base, kind="ir", text="He is on IR: auto-swap only works from your "
                                               "bench or lineup.")
    if game is None:
        return Preview(**base, kind="no_game", text="No game today.")
    when = clock(tip, tz)
    if p.locked or tip <= now + LOCK_MARGIN:
        return Preview(**base, kind="started", text=f"His game started at {when}: too late today.")
    healthy_now = status_class(status) == "ok"
    lead = (f"He is healthy now. If he is listed as hurt and then turns healthy again before "
            f"his {when} tip, benchboss" if healthy_now else
            f"If he turns healthy before his {when} tip, benchboss")
    swap = swap_of(plan, p.id, cal) if plan is not None else Swap()
    if swap.starts and swap.gain < MIN_GAIN_AUTO:
        return Preview(**base, kind="small", swap=swap,
                       text=f"Starting him would add only {swap.gain:+.1f}, under the "
                            f"{MIN_GAIN_AUTO:.1f} minimum: nothing would change.")
    if swap.starts:
        return Preview(**base, kind="starts", swap=swap,
                       text=f"{lead} {swap.phrase('him')} ({swap.gain:+.1f}).")
    if spot.is_starting:
        return Preview(**base, kind="starting", swap=swap,
                       text=f"He already starts at {spot.slot}: nothing to change.")
    return Preview(**base, kind="sits", swap=swap,
                   text="He would stay on the bench: every starter he can replace projects "
                        "more.")


def trial_text(name: str, swap: Swap) -> str:
    """The trial-mode note: what benchboss would have done, and that nothing was sent."""
    return (f"Trial run: benchboss would have {swap.phrase(name, past=True)} "
            f"({swap.gain:+.1f}). Nothing was sent.")


def live_text(name: str, swap: Swap, status: str) -> str:
    text = f"Auto-swap: started {name} at {swap.slot}"
    if swap.benched is not None:
        text += f", benched {swap.benched.name}"
    return f"{text}{'' if text.endswith('.') else '.'} ESPN: {status}"  # "Pippen Jr." ends it


def healthy_text(flip: Flip, tz: dt.tzinfo | None = None) -> str:
    """ "Ausar Thompson is healthy (was OUT). Tips 7:00 PM." """
    head = f"{flip.name} is healthy (was {tag(flip.old)})."
    if flip.tip is None:
        return f"{head} No game today."
    if flip.started:
        return f"{head} His game started at {clock(flip.tip, tz)}."
    return f"{head} Tips {clock(flip.tip, tz)}."


__all__ = ["CADENCE", "FLIP_KINDS", "Flip", "IDLE", "Preview", "REVERT_STATUSES", "Swap",
           "as_healthy", "auto_options", "bad_read", "describe", "detect_flips", "flip_kind",
           "frozen_moves", "healthy_text", "known_status", "lineup_before", "live_text", "next_poll",
           "out_of_scope", "player_in", "preview_flip", "remember", "swap_of", "tag",
           "trial_text"]

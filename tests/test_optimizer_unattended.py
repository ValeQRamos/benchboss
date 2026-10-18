"""The optimizer that can run unattended (1.0.4): freeze by tip time, the scope guard,
deterministic ties, the safety checks (core/guard.py), the minimum gain, ESPN's day, what
happened to a write (Outcome) and the lineup log. All offline, on the demo league."""

from __future__ import annotations

import datetime as dt
import io
import json
import random
from dataclasses import replace

import pytest
from rich.console import Console

from benchboss import actions, lineup_log
from benchboss.cli import main
from benchboss.core import guard
from benchboss.core.lineup import (
    MIN_GAIN_AUTO,
    DayPlan,
    Move,
    PlanOptions,
    day_value,
    frozen_reasons,
    plan_day,
    plan_gain,
)
from benchboss.demo import DemoClient, DemoSession, demo_session
from benchboss.errors import AuthError, BenchbossError, EspnError, GuardRefused, NetworkError
from benchboss.espn.constants import BENCH, INJURY_FACTOR, IR, LINEUP_LOCK_INDIVIDUAL, SLOT_ID
from benchboss.espn.models import RosterSpot
from benchboss.service import Outcome, periods_for
from benchboss.ui import views
from benchboss.ui.theme import DARK

G, UT, PG = SLOT_ID["G"], SLOT_ID["UT"], SLOT_ID["PG"]


def text_of(renderable, width: int = 120) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def at(session, hour: int, minute: int = 0) -> dt.datetime:
    """The demo day (Wed Nov 4) at this time, on the demo clock's zone."""
    return dt.datetime.combine(session.today, dt.time(hour, minute), tzinfo=session.now.tzinfo)


def by_name(roster, name: str) -> RosterSpot:
    return next(s for s in roster if s.player.name == name)


def with_status(roster, name: str, status: str) -> list[RosterSpot]:
    return [replace(s, player=replace(s.player, injury_status=status))
            if s.player.name == name else s for s in roster]


def optimized(session) -> list[RosterSpot]:
    """Today's demo roster after Optimize today was applied (Daniels, White and Harris sit,
    Pippen plays G): the lineup an auto-swap starts from."""
    lg = session.league()
    plan = plan_day(lg.me.roster, lg.slot_counts, session.today_period, session.calendar)
    to = {m.player.id: m.to_slot for m in plan.moves}
    return [replace(s, slot_id=to.get(s.player.id, s.slot_id)) for s in lg.me.roster]


def auto_opts(session, *names, roster=None, **kw) -> PlanOptions:
    roster = roster or session.league().me.roster
    ids = frozenset(by_name(roster, n).player.id for n in names)
    return PlanOptions(now=kw.pop("now", session.now), movable=ids, min_gain=MIN_GAIN_AUTO,
                       auto=True, **kw)


def moves(plan) -> list[str]:
    return [str(m) for m in plan.moves]


# --- 1.0.3, the reference: attended plans must not change --------------------------------------

def _legacy_best(pool, slot_counts, values, can_play):
    """best_lineup exactly as 1.0.3 shipped it."""
    slots = [s for s, n in sorted(slot_counts.items()) if s not in (BENCH, IR) for _ in range(n)]
    elig = [set(spot.player.eligible_slots) for spot in pool]
    worth = [values[i] or (1e-3 if can_play[i] else 0.0) for i in range(len(pool))]
    best = {0: (0.0, ())}
    for sl in slots:
        nxt = {}
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


def _legacy_plan(roster, slot_counts, period, cal):
    """plan_day exactly as 1.0.3 shipped it: (moves, projected, bench reasons)."""
    active = [s for s in roster if s.slot_id != IR]
    locked = [s for s in active if s.player.locked]
    pool = [s for s in active if not s.player.locked]
    counts, projected, out, bench = dict(slot_counts), 0.0, [], []
    for s in locked:
        if s.is_starting:
            counts[s.slot_id] = max(0, counts.get(s.slot_id, 0) - 1)
            projected += day_value(s.player, period, cal)
        else:
            bench.append((s.player.id, "locked"))
    values = [day_value(s.player, period, cal) for s in pool]
    can_play = [cal.plays(s.player.pro_team_id, period)
                and INJURY_FACTOR.get(s.player.injury_status or "", 1.0) > 0 for s in pool]
    assign = _legacy_best(pool, counts, values, can_play)
    for i, s in enumerate(pool):
        target = assign.get(i, BENCH)
        if s.slot_id != target:
            out.append((s.player.id, s.slot_id, target))
        if i in assign:
            projected += values[i]
        else:
            bench.append((s.player.id, ""))
    return out, projected, bench


def test_attended_plans_are_the_103_plans_for_every_team_and_day(session):
    lg, cal, today = session.league(), session.calendar, session.today_period
    opts = PlanOptions(now=session.now)  # what Optimize in the app and the CLI pass
    checked = 0
    for team in lg.teams.values():
        for sp in range(today, min(today + 14, cal.final_period + 1)):
            old_moves, old_projected, _ = _legacy_plan(team.roster, lg.slot_counts, sp, cal)
            for plan in (plan_day(team.roster, lg.slot_counts, sp, cal),
                         plan_day(team.roster, lg.slot_counts, sp, cal, opts)):
                assert [(m.player.id, m.from_slot, m.to_slot) for m in plan.moves] == old_moves
                assert plan.projected == pytest.approx(old_projected, abs=1e-9)
            checked += 1
    assert checked == 140


def test_a_locked_player_still_reads_locked_without_options(session):
    lg = session.league()
    roster = [replace(s, player=replace(s.player, locked=True))
              if s.player.name == "Pascal Siakam" else s for s in lg.me.roster]
    plan = plan_day(roster, lg.slot_counts, session.today_period + 2, session.calendar)
    old_moves, _, old_bench = _legacy_plan(roster, lg.slot_counts, session.today_period + 2,
                                           session.calendar)
    assert [(m.player.id, m.from_slot, m.to_slot) for m in plan.moves] == old_moves
    siakam = by_name(roster, "Pascal Siakam").player
    assert (siakam.id, "locked") in old_bench and (siakam, "locked") in plan.bench
    assert plan.frozen == {siakam.id: "locked"}


@pytest.mark.parametrize("width", [120, 46])
def test_the_week_screen_reads_the_same_with_the_clock(session, width):
    periods = [p for p in periods_for(session, "week") if p >= session.league().scoring_period]
    old = text_of(views.plan(session.plan_days(periods), session.calendar, DARK, width), width)
    new = text_of(views.plan(session.plan_days(periods, PlanOptions(now=session.now)),
                             session.calendar, DARK, width), width)
    assert new == old


# --- freeze by tip time ---------------------------------------------------------------------------

SEVEN_PM = ("Jalen Duren", "Dyson Daniels", "AJ Dybantsa", "Alex Sarr")


def test_players_whose_game_tipped_are_never_moved(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    plan = plan_day(lg.me.roster, lg.slot_counts, sp, cal, PlanOptions(now=at(session, 19, 15)))
    frozen = {lg.me.find(n).player.id for n in SEVEN_PM}
    assert {k for k, v in plan.frozen.items() if v == "tipped 7:00 PM"} == frozen
    assert not [m for m in plan.moves if m.player.id in frozen]
    assert "Dyson Daniels G -> BE" in moves(plan_day(lg.me.roster, lg.slot_counts, sp, cal))
    assert len(plan.starters) == lg.starter_slots and plan.changed  # the rest is still set
    assert not [v for v in guard.check(lg.me.roster, plan, lg.slot_counts, cal,
                                       PlanOptions(now=at(session, 19, 15))) if v.fatal]


def test_the_margin_freezes_a_game_about_to_start(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    daniels = lg.me.find("Dyson Daniels").player.id
    close = plan_day(lg.me.roster, lg.slot_counts, sp, cal, PlanOptions(now=at(session, 18, 58)))
    assert close.frozen[daniels] == "starts 7:00 PM"
    early = plan_day(lg.me.roster, lg.slot_counts, sp, cal, PlanOptions(now=at(session, 18, 56)))
    assert daniels not in early.frozen and "Dyson Daniels G -> BE" in moves(early)


def test_espn_lock_flag_wins_over_a_later_tip(session):
    lg, cal = session.league(), session.calendar
    roster = [replace(s, player=replace(s.player, locked=True))
              if s.player.name == "Scotty Pippen Jr." else s for s in lg.me.roster]
    plan = plan_day(roster, lg.slot_counts, session.today_period, cal,
                    PlanOptions(now=session.now))
    pippen = lg.me.find("Scotty Pippen Jr.").player.id
    assert plan.frozen[pippen] == "locked" and pippen not in {m.player.id for m in plan.moves}


def test_ir_is_frozen_and_never_a_target(session):
    lg, cal = session.league(), session.calendar
    roster = [replace(s, slot_id=IR) if s.player.name == "Pascal Siakam" else s
              for s in lg.me.roster]
    siakam = lg.me.find("Pascal Siakam").player.id
    plan = plan_day(roster, lg.slot_counts, session.today_period, cal, PlanOptions(now=session.now))
    assert plan.frozen[siakam] == "IR"
    assert all(m.player.id != siakam and IR not in (m.from_slot, m.to_slot) for m in plan.moves)


def test_unknown_status_and_unsure_tips_freeze_only_unattended_runs(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster = [replace(s, player=replace(s.player, injury_known=False))
              if s.player.name == "Dyson Daniels" else s for s in lg.me.roster]
    daniels = lg.me.find("Dyson Daniels").player.id
    attended = plan_day(roster, lg.slot_counts, sp, cal, PlanOptions(now=session.now))
    assert daniels not in attended.frozen
    auto = plan_day(roster, lg.slot_counts, sp, cal, PlanOptions(now=session.now, auto=True))
    assert auto.frozen[daniels] == "unknown status"
    assert daniels not in {m.player.id for m in auto.moves}
    assert "ESPN sent no injury status for Dyson Daniels: he stays where he is." in auto.notes
    odd = replace(lg.me.roster[0].player, injury_status="FIFTEEN_DAY_DL")
    assert frozen_reasons([RosterSpot(odd, BENCH)], sp, cal,
                          PlanOptions(now=session.now, auto=True)) == {odd.id: "unknown status"}
    # a tip time ESPN has not set, or a game it does not lock by, freezes the player too
    pippen = lg.me.find("Scotty Pippen Jr.").player
    game = cal.game(pippen.pro_team_id, sp)
    cal.games[pippen.pro_team_id][sp] = replace(game, tbd=True)
    try:
        auto = PlanOptions(now=session.now, auto=True)
        assert frozen_reasons(lg.me.roster, sp, cal, auto)[pippen.id] == "tip time TBD"
        cal.games[pippen.pro_team_id][sp] = replace(game, valid_for_locking=False)
        assert frozen_reasons(lg.me.roster, sp, cal, auto)[pippen.id] == "game does not lock"
        assert pippen.id not in frozen_reasons(lg.me.roster, sp, cal, PlanOptions(now=session.now))
    finally:
        cal.games[pippen.pro_team_id][sp] = game


def test_an_unattended_run_without_a_clock_moves_nobody_who_plays(session):
    lg, cal = session.league(), session.calendar
    plan = plan_day(lg.me.roster, lg.slot_counts, session.today_period, cal, PlanOptions(auto=True))
    assert not plan.moves and set(plan.frozen.values()) == {"no clock"}


# --- the scope guard: what an automatic change may touch ---------------------------------------

def test_the_demo_auto_swap_is_exactly_one_in_one_out(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster = with_status(optimized(session), "Dyson Daniels", "ACTIVE")
    plan = plan_day(roster, lg.slot_counts, sp, cal, auto_opts(session, "Dyson Daniels"))
    assert moves(plan) == ["Dyson Daniels BE -> G", "Scotty Pippen Jr. G -> BE"]
    assert round(plan.projected_before, 1) == 382.0 and round(plan.projected, 1) == 387.0
    assert round(plan_gain(plan, cal), 1) == 5.1 and plan.notes == []
    assert not [v for v in guard.check(roster, plan, lg.slot_counts, cal,
                                       auto_opts(session, "Dyson Daniels")) if v.fatal]


def test_the_scope_never_pulls_in_someone_who_was_not_marked(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster = with_status(with_status(optimized(session), "Dyson Daniels", "ACTIVE"),
                         "Coby White", "ACTIVE")
    full = plan_day(roster, lg.slot_counts, sp, cal)
    assert moves(full) == ["Dyson Daniels BE -> G", "Scotty Pippen Jr. G -> BE"]
    # only Coby White is marked: he comes in, and Dyson Daniels (better, not marked) stays out
    scoped = plan_day(roster, lg.slot_counts, sp, cal, auto_opts(session, "Coby White"))
    assert moves(scoped) == ["Coby White BE -> G", "Scotty Pippen Jr. G -> BE"]
    # both marked: one starter goes out for each one who comes in, never a second one for
    # Coby White, who projects less than every other starter
    both = plan_day(roster, lg.slot_counts, sp, cal,
                    auto_opts(session, "Coby White", "Dyson Daniels"))
    assert moves(both) == moves(full)


def test_a_marked_player_who_projects_less_than_every_starter_stays_out(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster = with_status(optimized(session), "Tobias Harris", "ACTIVE")
    plan = plan_day(roster, lg.slot_counts, sp, cal, auto_opts(session, "Tobias Harris"))
    assert not plan.moves  # 30.1 against Pippen's 30.6
    assert plan.notes == ["Tobias Harris stays on the bench: no starter he can replace "
                          "projects less."]


def test_a_marked_player_whose_game_tipped_is_left_alone(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster = with_status(optimized(session), "Dyson Daniels", "ACTIVE")
    plan = plan_day(roster, lg.slot_counts, sp, cal,
                    auto_opts(session, "Dyson Daniels", now=at(session, 19, 15)))
    assert not plan.moves
    assert plan.notes == ["Dyson Daniels is not moved: his game tipped at 7:00 PM."]


def test_unattended_ties_do_not_depend_on_roster_order(session):
    lg, cal = session.league(), session.calendar
    rng = random.Random(4)
    opts = PlanOptions(now=session.now, auto=True)
    for team in lg.teams.values():
        for sp in (session.today_period, session.today_period + 2, session.today_period + 4):
            first = plan_day(team.roster, lg.slot_counts, sp, cal, opts)
            for _ in range(3):
                shuffled = list(team.roster)
                rng.shuffle(shuffled)
                again = plan_day(shuffled, lg.slot_counts, sp, cal, opts)
                assert sorted(moves(again)) == sorted(moves(first))
            to = {m.player.id: m.to_slot for m in first.moves}
            done = [replace(s, slot_id=to.get(s.player.id, s.slot_id)) for s in team.roster]
            assert not plan_day(done, lg.slot_counts, sp, cal, opts).moves  # no flip-flop


# --- the safety checks ---------------------------------------------------------------------------

def _plan(roster, period, *move_list) -> DayPlan:
    plan = DayPlan(period, moves=list(move_list))
    plan.projected = plan.projected_before = 100.0
    return plan


def codes(found) -> set[str]:
    return {v.code for v in found if v.fatal}


def test_each_bad_plan_is_caught(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster, counts = lg.me.roster, lg.slot_counts
    attended = PlanOptions(now=session.now)
    spot = by_name(roster, "Pascal Siakam")             # bench, PF/F/UT, 8:00 PM
    gobert = by_name(roster, "Rudy Gobert")             # UT, C only
    daniels = by_name(roster, "Dyson Daniels")          # G, 7:00 PM
    cases = {
        "G3": Move(spot.player, BENCH, PG),                         # not his position
        "G2": Move(spot.player, BENCH, IR),
    }
    for code, move in cases.items():
        assert code in codes(guard.check(roster, _plan(roster, sp, move), counts, cal, attended))
    # a slot over its count
    assert "G3" in codes(guard.check(roster, _plan(roster, sp, Move(spot.player, BENCH, UT)),
                                     counts, cal, attended))
    # a stale from-slot
    assert "G3" in codes(guard.check(roster, _plan(roster, sp, Move(gobert.player, BENCH, UT)),
                                     counts, cal, attended))
    # a frozen player
    late = PlanOptions(now=at(session, 19, 5))
    found = guard.check(roster, _plan(roster, sp, Move(daniels.player, G, BENCH)), counts, cal, late)
    assert "G1" in codes(found)
    assert any(v.message == "Dyson Daniels cannot move: his game tipped at 7:00 PM" for v in found)
    # nobody with no game, or OUT, is moved into a slot
    idle_day = next(p for p in range(sp, sp + 7) if not cal.plays(spot.player.pro_team_id, p)
                    and cal.first_tip(p))
    assert "G4" in codes(guard.check(roster, _plan(roster, idle_day, Move(spot.player, BENCH, SLOT_ID["PF"]),
                                                   Move(by_name(roster, "Tobias Harris").player,
                                                        SLOT_ID["PF"], BENCH)),
                                     counts, cal, attended))
    out = with_status(roster, "Pascal Siakam", "OUT")
    plan = _plan(out, sp, Move(by_name(out, "Pascal Siakam").player, BENCH, SLOT_ID["PF"]),
                 Move(by_name(out, "Tobias Harris").player, SLOT_ID["PF"], BENCH))
    assert "G4" in codes(guard.check(out, plan, counts, cal, attended))


def test_benching_a_scorer_while_an_idle_starter_keeps_his_slot_is_caught(session):
    lg, cal = session.league(), session.calendar
    roster = lg.me.roster
    gobert = by_name(roster, "Rudy Gobert")
    sp = next(p for p in range(session.today_period, session.today_period + 7)
              if not cal.plays(gobert.player.pro_team_id, p) and cal.first_tip(p)
              and cal.plays(by_name(roster, "Alex Sarr").player.pro_team_id, p))
    plan = _plan(roster, sp, Move(by_name(roster, "Alex Sarr").player, UT, BENCH))
    found = guard.check(roster, plan, lg.slot_counts, cal, PlanOptions(now=session.now))
    assert "G4" in codes(found)


def test_unattended_checks_run_only_for_unattended_plans(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    roster = optimized(session)
    starters = [s for s in roster if s.is_starting and s.player.injury_status == "ACTIVE"]
    benched = [Move(s.player, s.slot_id, BENCH) for s in starters[:4]]
    plan = _plan(roster, sp, *benched)
    plan.projected = 50.0
    auto = PlanOptions(now=session.now, auto=True)
    assert not codes(guard.check(roster, plan, lg.slot_counts, cal, PlanOptions(now=session.now)))
    assert {"G6", "G7"} <= codes(guard.check(roster, plan, lg.slot_counts, cal, auto))
    scoped = auto_opts(session, "Dyson Daniels", roster=roster)
    assert "G5" in codes(guard.check(roster, plan, lg.slot_counts, cal, scoped))
    outsider = _plan(roster, sp, Move(by_name(roster, "Coby White").player, BENCH, UT),
                     Move(by_name(roster, "Alex Sarr").player, UT, BENCH))
    assert "G5" in codes(guard.check(roster, outsider, lg.slot_counts, cal, scoped))
    many = _plan(roster, sp, *[Move(s.player, s.slot_id, s.slot_id) for s in roster])
    assert "G7" in codes(guard.check(roster, many, lg.slot_counts, cal, auto))


def test_broken_reads_are_caught(session):
    lg, cal, sp = session.league(), session.calendar, session.today_period
    auto = PlanOptions(now=session.now, auto=True)
    zeroed = [replace(s, player=replace(s.player, proj=0.0)) for s in lg.me.roster]
    found = guard.check(zeroed, plan_day(zeroed, lg.slot_counts, sp, cal, auto), lg.slot_counts,
                        cal, auto)
    assert any(v.code == "G8" and "have no projection" in v.message for v in found)
    unknown = [replace(s, player=replace(s.player, injury_known=False)) for s in lg.me.roster]
    found = guard.check(unknown, plan_day(unknown, lg.slot_counts, sp, cal, auto),
                        lg.slot_counts, cal, auto)
    assert any(v.code == "G8" and "no injury status" in v.message for v in found)
    one = with_status(lg.me.roster, "Coby White", "ACTIVE")
    one = [replace(s, player=replace(s.player, proj=0.0)) if s.player.name == "Coby White" else s
           for s in one]
    assert not codes(guard.check(one, plan_day(one, lg.slot_counts, sp, cal, auto),
                                 lg.slot_counts, cal, auto))


def test_every_real_plan_passes_the_checks(session):
    lg, cal = session.league(), session.calendar
    for opts in (PlanOptions(now=session.now), PlanOptions(now=at(session, 20, 10), auto=True)):
        for team in lg.teams.values():
            for sp in range(session.today_period, session.today_period + 5):
                plan = plan_day(team.roster, lg.slot_counts, sp, cal, opts)
                assert not [v for v in guard.check(team.roster, plan, lg.slot_counts, cal, opts)
                            if v.fatal], (team.id, sp)
                assert plan.projected >= plan.projected_before - 1e-6


def test_the_day_check(session):
    cal, sp = session.calendar, session.today_period

    def day(**kw):
        args = dict(espn_day=sp, today_period=sp, in_season=True,
                    lock_type=LINEUP_LOCK_INDIVIDUAL, cal=cal)
        args.update(kw)
        return [v.message for v in guard.day_check(args.pop("period", sp), **args)]

    assert day() == []
    assert day(espn_day=sp - 1) == ["ESPN is on Tue Nov 3 but this computer's clock says Wed Nov 4"]
    assert day(period=sp + 1) == ["Thu Nov 5 is not today on ESPN (Wed Nov 4)"]
    assert day(espn_day=None) == ["ESPN did not say which day it is"]
    assert len(day(in_season=False)) == 1 and len(day(lock_type="")) == 1
    assert all(v.code == "G9" for v in guard.day_check(sp, espn_day=None, today_period=sp,
                                                       in_season=False, lock_type=""))


# --- the write path ---------------------------------------------------------------------------------

class Espn:
    """The demo session's ESPN for one write: a roster, a day, and a recorder of POSTs."""

    def __init__(self, session, monkeypatch, roster, answer=None, day=None):
        self.sent: list[dict] = []
        self.answer = {"status": "EXECUTED"} if answer is None else answer
        self.day = session.today_period if day is None else day  # 0: ESPN sent no day
        monkeypatch.setattr(session, "roster_on", lambda period: roster)
        monkeypatch.setattr(session, "current_period", self.current_period)
        monkeypatch.setattr(session.client, "transaction", self.transaction)

    def current_period(self, strict=False):
        if not self.day and strict:
            raise GuardRefused("ESPN did not say which day it is (no latestScoringPeriod)")
        return self.day

    def transaction(self, body):
        self.sent.append(body)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_an_automatic_swap_is_sent_as_roster_and_logged(session, monkeypatch):
    roster = with_status(optimized(session), "Dyson Daniels", "ACTIVE")
    espn = Espn(session, monkeypatch, roster)
    r = session.apply_plan(session.today_period, opts=auto_opts(session, "Dyson Daniels"),
                           writer="monitor", note={"trigger": {"player": "Dyson Daniels"},
                                                   "writer": "robot"})
    assert r.outcome == Outcome.EXECUTED and r.kind == "ROSTER" and r.status == "EXECUTED"
    assert [it["playerId"] for it in espn.sent[0]["items"]] == [
        by_name(roster, "Dyson Daniels").player.id, by_name(roster, "Scotty Pippen Jr.").player.id]
    rec = lineup_log.read(session)[-1]
    assert rec["writer"] == "monitor" and rec["event"] == "autoswap" and rec["mode"] == "live"
    assert rec["outcome"] == "EXECUTED" and rec["gain"] == 5.1 and rec["kind"] == "ROSTER"
    assert rec["moves"][0] == {"player_id": by_name(roster, "Dyson Daniels").player.id,
                               "player": "Dyson Daniels", "from": "BE", "to": "G"}
    assert rec["trigger"] == {"player": "Dyson Daniels"}


def test_a_trial_plans_and_logs_without_sending(session, monkeypatch):
    roster = with_status(optimized(session), "Dyson Daniels", "ACTIVE")
    espn = Espn(session, monkeypatch, roster)
    r = session.apply_plan(session.today_period, opts=auto_opts(session, "Dyson Daniels"),
                           send=False, writer="monitor")
    assert r.outcome == Outcome.WOULD_SEND and not espn.sent
    assert lineup_log.read(session)[-1]["mode"] == "trial"


def test_below_the_minimum_gain_nothing_is_sent(session, monkeypatch):
    roster = with_status(optimized(session), "Dyson Daniels", "ACTIVE")
    espn = Espn(session, monkeypatch, roster)
    opts = replace(auto_opts(session, "Dyson Daniels"), min_gain=6.0)
    r = session.apply_plan(session.today_period, opts=opts, writer="monitor")
    assert r.outcome == Outcome.BELOW_MIN_GAIN and not espn.sent and r.plan.moves
    # a person who asks gets even a small gain sent
    r = session.apply_plan(session.today_period, opts=PlanOptions(now=session.now))
    assert r.outcome == Outcome.EXECUTED and espn.sent


@pytest.mark.parametrize("day, why", [
    (15, "ESPN is on Tue Nov 3"),                 # this computer's clock is a day ahead
    (0, "ESPN did not say which day it is"),      # no latestScoringPeriod: strict refuses
])
def test_an_automatic_change_needs_espn_to_agree_on_the_day(session, monkeypatch, day, why):
    roster = with_status(optimized(session), "Dyson Daniels", "ACTIVE")
    espn = Espn(session, monkeypatch, roster, day=day)
    r = session.apply_plan(session.today_period, opts=auto_opts(session, "Dyson Daniels"),
                           writer="monitor")
    assert r.outcome == Outcome.NOT_SENT and not espn.sent
    assert [v.code for v in r.guards if v.fatal] == ["G9"] and why in r.error


def test_an_automatic_change_needs_a_league_that_locks_by_game(session, monkeypatch):
    espn = Espn(session, monkeypatch, with_status(optimized(session), "Dyson Daniels", "ACTIVE"))
    session.league().lineup_lock_type = "DAILY"
    r = session.apply_plan(session.today_period, opts=auto_opts(session, "Dyson Daniels"),
                           writer="monitor")
    assert r.outcome == Outcome.NOT_SENT and not espn.sent and "G9" in codes(r.guards)


def test_a_broken_read_is_refused_and_nothing_is_sent(session, monkeypatch):
    zeroed = [replace(s, player=replace(s.player, proj=0.0, injury_status="ACTIVE"))
              for s in optimized(session)]
    espn = Espn(session, monkeypatch, zeroed)
    r = session.apply_plan(session.today_period, opts=PlanOptions(now=session.now, auto=True),
                           writer="monitor")
    assert r.outcome == Outcome.NOT_SENT and not espn.sent and "G8" in codes(r.guards)
    assert r.error.startswith("not sent: ")


def test_before_send_can_stop_the_post(session, monkeypatch):
    espn = Espn(session, monkeypatch, with_status(optimized(session), "Dyson Daniels", "ACTIVE"))
    seen = []

    def stop(plan):
        seen.append(moves(plan))
        return "the mark was taken off"

    r = session.apply_plan(session.today_period, opts=auto_opts(session, "Dyson Daniels"),
                           writer="monitor", before_send=stop)
    assert r.outcome == Outcome.NOT_SENT and r.error == "the mark was taken off" and not espn.sent
    assert seen == [["Dyson Daniels BE -> G", "Scotty Pippen Jr. G -> BE"]]

    def cannot_save(plan):
        raise BenchbossError("could not save monitor.json")

    r = session.apply_plan(session.today_period, opts=auto_opts(session, "Dyson Daniels"),
                           writer="monitor", before_send=cannot_save)
    assert r.outcome == Outcome.NOT_SENT and "monitor.json" in r.error and not espn.sent
    r = session.apply_plan(session.today_period, opts=auto_opts(session, "Dyson Daniels"),
                           writer="monitor", before_send=lambda plan: None)
    assert r.outcome == Outcome.EXECUTED and espn.sent


@pytest.mark.parametrize("answer, outcome, status", [
    ({"status": "EXECUTED"}, Outcome.EXECUTED, "EXECUTED"),
    ({"transaction": {"status": "EXECUTED"}}, Outcome.EXECUTED, "EXECUTED"),
    ({"status": "FAILED_LINEUPLOCK"}, Outcome.FAILED, "FAILED_LINEUPLOCK"),
    ({}, Outcome.UNKNOWN, "UNKNOWN"),
    ({"status": "done, probably"}, Outcome.UNKNOWN, "UNKNOWN"),
    ({"status": "PENDING"}, Outcome.UNKNOWN, "PENDING"),
    (AuthError("cookies expired"), Outcome.AUTH, ""),
    (EspnError(409, "lineup locked"), Outcome.REFUSED, ""),
    (EspnError(503, "busy"), Outcome.UNKNOWN, ""),
    (EspnError(200, "the answer is not JSON"), Outcome.UNKNOWN, ""),
    (NetworkError("the connection to ESPN dropped"), Outcome.UNKNOWN, ""),
    (BenchbossError("something else"), Outcome.ERROR, ""),
])
def test_every_answer_is_classified(session, monkeypatch, answer, outcome, status):
    roster = [replace(s, slot_id=BENCH) for s in session.league().me.roster]
    Espn(session, monkeypatch, roster, answer=answer)
    r = session.apply_plan(session.today_period)
    assert r.outcome == outcome and r.status == status
    assert bool(r.error) == (outcome != Outcome.EXECUTED)
    assert "{" not in r.status


def test_send_never_returns_raw_json(session, monkeypatch):
    monkeypatch.setattr(session.client, "transaction",
                        lambda body: {"id": "abc", "items": [{"x": 1}]})
    assert actions.send(session, "ROSTER", [], session.today_period) == actions.UNKNOWN_STATUS
    monkeypatch.setattr(session.client, "transaction", lambda body: ["odd"])
    assert actions.send(session, "ROSTER", [], session.today_period) == "UNKNOWN"
    monkeypatch.setattr(session.client, "transaction", lambda body: {"status": "EXECUTED"})
    assert actions.send(session, "ROSTER", [], session.today_period) == "EXECUTED"


def test_attended_sends_are_logged_on_disk_without_cookies(session, monkeypatch):
    session.local_state = None  # a real session's files, under the test's BENCHBOSS_HOME
    roster = [replace(s, slot_id=BENCH) for s in session.league().me.roster]
    Espn(session, monkeypatch, roster)
    r = session.apply_plan(session.today_period, opts=PlanOptions(now=session.now), writer="tui")
    assert r.outcome == Outcome.EXECUTED
    path = lineup_log.path_for(session.now)
    text = path.read_text()
    assert session.client.swid not in text
    rec = json.loads(text.splitlines()[-1])
    assert rec["writer"] == "tui" and rec["event"] == "apply" and rec["mode"] == "attended"
    assert rec["outcome"] == "EXECUTED" and len(rec["moves"]) == len(r.plan.moves)
    # nothing to send: nothing logged for a person, a record for the monitor
    monkeypatch.setattr(session, "roster_on", lambda period: optimized(session))
    session.apply_plan(session.today_period, opts=PlanOptions(now=session.now), writer="tui")
    assert len(path.read_text().splitlines()) == 1


def test_the_demo_writes_nothing_to_disk(session, monkeypatch):
    from benchboss import config as config_mod

    Espn(session, monkeypatch, [replace(s, slot_id=BENCH) for s in session.league().me.roster])
    session.apply_plan(session.today_period, opts=PlanOptions(now=session.now))
    assert lineup_log.read(session) and not config_mod.config_dir().exists()


def test_a_log_that_cannot_be_written_never_changes_the_result(session, monkeypatch):
    Espn(session, monkeypatch, [replace(s, slot_id=BENCH) for s in session.league().me.roster])

    def broken(*a, **kw):
        raise BenchbossError("disk full")

    monkeypatch.setattr(lineup_log, "append", broken)
    r = session.apply_plan(session.today_period)
    assert r.outcome == Outcome.EXECUTED and "Could not write the lineup log (disk full)." in r.plan.notes


def test_the_schedule_is_read_again_for_automatic_changes(session, monkeypatch):
    from benchboss.service import Session

    reads = []

    class Client:
        league_id, season, cookies = session.client.league_id, session.client.season, None

        def season_data(self, *views):
            reads.append(views)
            return session.data["schedule"]

    real = Session(session.cfg, client=Client())
    first = real.fresh_calendar(3600)
    assert real.fresh_calendar(3600) is first and len(reads) == 1
    assert real.calendar is first
    assert real.fresh_calendar(0) is not first and len(reads) == 2
    assert session.fresh_calendar(0) is session.calendar  # the demo's never changes


# --- the CLI and the app ------------------------------------------------------------------------

def test_cli_exits_5_when_a_safety_check_refuses(monkeypatch, capsys):
    monkeypatch.setattr(DemoClient, "transaction", lambda self, body: {"status": "EXECUTED"})
    monkeypatch.setattr(guard, "check", lambda *a, **kw: [
        guard.Violation("G1", "Dyson Daniels cannot move: his game tipped at 7:00 PM", 1)])
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--yes", "optimize", "today", "-q"])
    out, err = capsys.readouterr()
    assert e.value.code == 5 and "ESPN: EXECUTED" not in out
    assert "Dyson Daniels cannot move: his game tipped at 7:00 PM (G1)" in " ".join(err.split())
    assert "a safety check stopped them; nothing was changed" in " ".join(err.split())
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--json", "--yes", "optimize", "today"])
    assert e.value.code == 5
    day = json.loads(capsys.readouterr().out)[0]
    assert day["outcome"] == "NOT_SENT" and day["guards"][0]["code"] == "G1"


def test_cli_json_lists_frozen_players(monkeypatch, capsys):
    eastern = dt.timezone(dt.timedelta(hours=-5))  # the demo clock's zone
    monkeypatch.setattr(DemoSession, "now", property(
        lambda self: dt.datetime.combine(self.today, dt.time(19, 15), tzinfo=eastern)))
    main(["--demo", "--json", "optimize", "today", "--dry-run"])
    day = json.loads(capsys.readouterr().out)[0]
    assert {"player": "Dyson Daniels", "reason": "tipped 7:00 PM"} in day["frozen"]
    assert not any("Dyson Daniels" in m for m in day["moves"])


def test_cli_text_is_unchanged_before_the_first_tip(monkeypatch, capsys):
    monkeypatch.setattr(DemoClient, "transaction", lambda self, body: {"status": "EXECUTED"})
    main(["--demo", "--yes", "optimize", "today", "-q"])
    out = capsys.readouterr().out
    assert "ESPN: EXECUTED" in out and "Your lineup for today is set: 6 moves." in out


def test_app_plan_after_a_tip_leaves_the_tipped_players(monkeypatch):
    from benchboss.config import Config
    from benchboss.ui.app import Benchboss

    s = demo_session()
    s._now = at(s, 20, 15)
    app = Benchboss(Config(), demo=True, session=s)
    draw, pending = app._build("today")
    out = text_of(draw(DARK, 120), 120)
    assert "locked, tipped 8:00 PM" in out
    assert not any("Siakam" in x and "→" in x for x in out.splitlines())
    plans = s.plan_days([s.today_period], PlanOptions(now=s.now))
    assert all(m.player.name != "Pascal Siakam" for m in plans[0].moves)
    assert pending is None or pending["periods"] == [s.today_period]


def test_app_apply_sends_with_the_clock_and_says_tui():
    import asyncio

    from benchboss.config import Config
    from benchboss.ui.app import Benchboss

    s = demo_session()
    calls = []

    def apply_days(periods, opts=None, writer="cli"):
        calls.append((periods, opts, writer))
        return []

    s.apply_days = apply_days
    app = Benchboss(Config(), demo=False, session=s)

    async def run():
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.press("t")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#apply").press()
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(run())
    periods, opts, writer = calls[0]
    assert periods == [s.today_period] and writer == "tui"
    assert opts.now == s.now and not opts.auto and opts.movable is None and opts.min_gain == 0


def test_missing_latest_period_is_a_guard_refusal_in_strict_mode(session, monkeypatch):
    monkeypatch.setattr(session.client, "league", lambda *v, **kw: {"status": {}})
    with pytest.raises(GuardRefused):
        session.current_period(strict=True)
    monkeypatch.setattr(session.client, "league",
                        lambda *v, **kw: {"status": {"latestScoringPeriod": "16"}})
    with pytest.raises(GuardRefused):
        session.current_period(strict=True)
    assert session.current_period() == "16"  # outside automatic writes nothing changes


def test_a_player_list_order_never_changes_frozen_or_notes(session):
    lg, cal = session.league(), session.calendar
    roster = with_status(optimized(session), "Dyson Daniels", "ACTIVE")
    opts = auto_opts(session, "Dyson Daniels", "Tobias Harris", now=at(session, 19, 15))
    a = plan_day(roster, lg.slot_counts, session.today_period, cal, opts)
    b = plan_day(list(reversed(roster)), lg.slot_counts, session.today_period, cal, opts)
    assert a.frozen == b.frozen and sorted(a.notes) == sorted(b.notes) and moves(a) == moves(b) == []

"""Auto-swap logic with no I/O (core/autoswap.py): flips, cadence, previews, scope, words."""

import datetime as dt
import random
from dataclasses import replace

import pytest

from benchboss.core import autoswap as core
from benchboss.core.lineup import LOCK_MARGIN, MIN_GAIN_AUTO, DayPlan, Move
from benchboss.espn.constants import BENCH, SLOT_ID
from benchboss.espn.models import Player

ET = dt.timezone(dt.timedelta(hours=-5))
NOW = dt.datetime(2026, 11, 4, 15, 30, tzinfo=ET)


def player(pid=1, name="Nikola Jokić", status="ACTIVE", known=True, team=7):
    return Player(pid, name, pro_team_id=team, injury_status=status, injury_known=known)


def demo(session):
    """The demo's lineup as Optimize would set it today, the calendar, today's period."""
    period = session.today_period
    return session.autoswap_lineup(period), session.calendar, period


def spot_of(roster, name):
    return next(s for s in roster if s.player.name == name)


# --- flips -------------------------------------------------------------------------------------

@pytest.mark.parametrize("old, new, kind", [
    ("DAY_TO_DAY", "ACTIVE", "cleared"),
    ("OUT", "PROBABLE", "cleared"),
    ("QUESTIONABLE", "NORMAL", "cleared"),
    ("OUT", "DAY_TO_DAY", "returning"),
    ("ACTIVE", "OUT", "ruled_out"),
    ("DOUBTFUL", "SUSPENSION", "ruled_out"),
    ("ACTIVE", "QUESTIONABLE", "flagged"),
    ("DAY_TO_DAY", "QUESTIONABLE", None),   # same class: only the stored status changes
    ("ACTIVE", "PROBABLE", None),
    ("DAY_TO_DAY", "FIFTEEN_DAY_DL", None),  # unknown is never a flip
    (None, "ACTIVE", None),
])
def test_flip_kinds_follow_the_status_classes(old, new, kind):
    assert core.flip_kind(old, new) == kind


def test_detect_flips_is_silent_on_first_sight_and_carries_the_tip(session):
    roster, cal, period = demo(session)
    daniels = replace(spot_of(roster, "Dyson Daniels").player, injury_status="ACTIVE")
    stranger = player(99, status="ACTIVE")
    flips = core.detect_flips({daniels.id: "DAY_TO_DAY"}, [daniels, stranger], cal, period, NOW)
    assert [(f.name, f.old, f.new, f.kind) for f in flips] == [
        ("Dyson Daniels", "DAY_TO_DAY", "ACTIVE", "cleared")]
    f = flips[0]
    assert f.cleared and f.tip == cal.game(daniels.pro_team_id, period).start
    assert not f.started
    later = core.detect_flips({daniels.id: "DAY_TO_DAY"}, [daniels], cal, period,
                              f.tip + dt.timedelta(minutes=1))
    assert later[0].started


def test_an_unknown_status_never_flips_and_never_replaces_the_stored_one():
    before = {1: "OUT"}
    missing = player(1, status="ACTIVE", known=False)  # ESPN sent no injuryStatus
    assert core.known_status(missing) is None
    assert core.detect_flips(before, [missing], None, 0, NOW) == []
    assert core.remember(before, [missing]) == {1: "OUT"}
    assert core.remember(before, [player(1, status="DAY_TO_DAY")]) == {1: "DAY_TO_DAY"}


def test_a_bad_read_changes_nothing():
    before = {1: "OUT", 2: "DAY_TO_DAY", 3: "ACTIVE"}
    assert core.bad_read([], [1, 2], before)
    lost = [player(1, known=False), player(2, known=False), player(3)]
    assert "2 players" in core.bad_read(lost, [1, 2, 3], before)
    assert core.bad_read([player(1, known=False), player(3)], [1, 3], before) == ""
    assert core.bad_read([], [], before) == ""


# --- cadence -----------------------------------------------------------------------------------

@pytest.mark.parametrize("ahead, seconds", [
    (dt.timedelta(hours=8), 1800), (dt.timedelta(hours=3), 600), (dt.timedelta(hours=1), 180),
    (dt.timedelta(minutes=20), 60), (dt.timedelta(minutes=5), 30), (None, 1800),
])
def test_next_poll_tightens_near_the_tip(ahead, seconds):
    tips = [NOW + ahead] if ahead else []
    assert core.next_poll(NOW, tips, jitter=0) == seconds


def test_next_poll_skips_tipped_games_and_jitters_within_ten_percent():
    tips = [NOW - dt.timedelta(minutes=5), NOW + dt.timedelta(minutes=30), None]
    assert core.next_poll(NOW, tips, jitter=0) == 60
    rng = random.Random(7)
    waits = [core.next_poll(NOW, tips, rng=rng) for _ in range(200)]
    assert min(waits) >= 54 and max(waits) <= 66 and len(set(waits)) > 100


# --- previews ----------------------------------------------------------------------------------

def test_the_chat_example_starts_daniels_and_benches_pippen(session):
    """Vale's example: Dyson Daniels turns healthy, Scotty Pippen Jr. (the worst starter
    whose game has not started) goes to the bench, and nothing else moves."""
    roster, cal, period = demo(session)
    daniels = spot_of(roster, "Dyson Daniels").player
    plan = core.preview_flip(roster, session.league().slot_counts, period, cal, daniels.id, NOW)
    assert [str(m) for m in plan.moves] == ["Dyson Daniels BE -> G",
                                            "Scotty Pippen Jr. G -> BE"]
    swap = core.swap_of(plan, daniels.id, cal)
    assert swap.slot == "G" and swap.benched.name == "Scotty Pippen Jr." and not swap.others
    assert swap.gain == pytest.approx(5.1, abs=0.05)
    assert round(plan.projected, 1) == 387.0
    before = core.lineup_before(plan)
    assert before[daniels.id] == BENCH and before[swap.benched.id] == SLOT_ID["G"]
    assert core.out_of_scope(before, plan, {daniels.id}) == []


def test_describe_says_what_arming_would_do(session):
    roster, cal, period = demo(session)
    lg = session.league()

    def describe(name, now=NOW, roster=roster):
        pid = spot_of(roster, name).player.id
        plan = core.preview_flip(roster, lg.slot_counts, period, cal, pid, now)
        return core.describe(roster, plan, pid, cal, period, now, ET)

    pv = describe("Dyson Daniels")
    assert pv.kind == "starts" and pv.would_change
    assert pv.text == ("If he turns healthy before his 7:00 PM tip, benchboss starts him at G "
                       "and benches Scotty Pippen Jr. (+5.1).")
    assert pv.to_dict()["benches"] == "Scotty Pippen Jr." and pv.to_dict()["slot"] == "G"
    assert describe("Tobias Harris").kind == "sits"
    assert describe("LaMelo Ball").kind == "starting"
    tip = cal.game(spot_of(roster, "Dyson Daniels").player.pro_team_id, period).start
    late = describe("Dyson Daniels", now=tip - LOCK_MARGIN + dt.timedelta(seconds=1))
    assert late.kind == "started" and "7:00 PM" in late.text
    # a tiny gain is not worth an automatic change
    close = [replace(s, player=replace(s.player, proj=31.0)) if s.player.name == "Dyson Daniels"
             else s for s in roster]
    small = describe("Dyson Daniels", roster=close)
    assert small.kind == "small" and f"{MIN_GAIN_AUTO:.1f} minimum" in small.text
    # IR, no game, not on the roster
    ir = [replace(s, slot_id=SLOT_ID["IR"]) if s.player.name == "Tobias Harris" else s
          for s in roster]
    harris = spot_of(ir, "Tobias Harris").player.id
    assert core.describe(ir, None, harris, cal, period, NOW).kind == "ir"
    assert core.describe(roster, None, harris, cal, 0, NOW).kind == "no_game"
    assert core.describe(roster, None, 12345, cal, period, NOW).kind == "gone"


def test_out_of_scope_catches_a_plan_that_moves_more_than_one_swap():
    a, b, c, d = (player(i, f"P{i}") for i in range(1, 5))
    before = {1: BENCH, 2: SLOT_ID["G"], 3: BENCH, 4: SLOT_ID["UT"]}
    ok = DayPlan(1, moves=[Move(a, BENCH, SLOT_ID["G"]), Move(b, SLOT_ID["G"], BENCH)])
    assert core.out_of_scope(before, ok, {1}) == []
    extra_start = DayPlan(1, moves=ok.moves + [Move(c, BENCH, SLOT_ID["UT"]),
                                               Move(d, SLOT_ID["UT"], BENCH)])
    problems = core.out_of_scope(before, extra_start, {1})
    assert any("P3 would start" in p for p in problems)
    assert any("more starters would go to the bench" in p for p in problems)
    ir = DayPlan(1, moves=[Move(a, SLOT_ID["IR"], SLOT_ID["G"])])
    assert any("IR" in p for p in core.out_of_scope({1: SLOT_ID["IR"]}, ir, {1}))
    many = DayPlan(1, moves=[Move(a, SLOT_ID["G"], SLOT_ID["UT"])] * (core.MAX_MOVES + 1))
    assert any("moves in one run" in p for p in core.out_of_scope(before, many, {1}))


# --- words -------------------------------------------------------------------------------------

def test_the_notes_read_naturally_and_keep_accents():
    jokic, doncic = player(1, "Nikola Jokić"), player(2, "Luka Dončić")
    swap = core.Swap("C", doncic, (), 4.96)
    assert core.trial_text(jokic.name, swap) == (
        "Trial run: benchboss would have started Nikola Jokić at C and benched Luka Dončić "
        "(+5.0). Nothing was sent.")
    assert core.live_text(jokic.name, swap, "EXECUTED") == (
        "Auto-swap: started Nikola Jokić at C, benched Luka Dončić. ESPN: EXECUTED")
    assert core.live_text(jokic.name, core.Swap("UT"), "EXECUTED") == (
        "Auto-swap: started Nikola Jokić at UT. ESPN: EXECUTED")
    tip = dt.datetime(2026, 10, 20, 23, 0, tzinfo=dt.timezone.utc)
    flip = core.Flip(1, "Ausar Thompson", "OUT", "ACTIVE", "cleared", tip)
    eastern = dt.timezone(dt.timedelta(hours=-4))  # daylight saving time: 7:00 PM, not 6:00
    assert core.healthy_text(flip, eastern) == "Ausar Thompson is healthy (was OUT). Tips 7:00 PM."
    assert "No game today" in core.healthy_text(replace(flip, tip=None), eastern)
    assert "started at 7:00 PM" in core.healthy_text(replace(flip, started=True), eastern)
    assert core.tag("DAY_TO_DAY") == "DTD" and core.tag("PROBABLE") == "healthy"
    assert core.tag(None) == "unknown"

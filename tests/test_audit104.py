"""Regression tests for the 1.0.4 review: reverts that lag or skip a flip, a failed save that
counted a write, the heartbeat of `monitor --once`, news windows longer than one page, and a
rename Windows blocks for a moment.

Nothing reaches ESPN: the monitor runs on ``LiveDemo`` with ``FakeEspn`` (see test_monitor.py)
and the news feed is faked at ``news._get_feed``."""

import datetime as dt

import pytest

from benchboss import monitor as mon
from benchboss.core.lineup import DayPlan
from benchboss.espn.constants import BENCH, SLOT_ID
from benchboss.service import OptimizeResult
from test_monitor import (
    FakeEspn,
    LiveDemo,
    Notes,
    armed,
    later,
    monitor,
    optimized,
    player,
    set_status,
    slot,
)


@pytest.fixture
def live():
    return optimized(LiveDemo())


def started(live, espn=None):
    """Arm Dyson Daniels and let a live round start him at G for Scotty Pippen Jr."""
    armed(live)
    espn = espn or FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    monitor(live, live=True).run(once=True)
    assert slot(live, "Dyson Daniels") == SLOT_ID["G"] and len(espn.bodies) == 1
    later(live)
    return espn


def pool_status(live, name, status):
    """Only the player poll changes; the roster read still shows the old status."""
    for x in live.client.pool():
        if x["player"]["fullName"] == name:
            x["player"]["injuryStatus"] = status


# --- a revert is not lost when the roster read lags or fails ------------------------------------

def test_a_revert_waits_for_a_lagging_roster_read_then_goes_through(live):
    espn = started(live)
    pool_status(live, "Dyson Daniels", "OUT")  # the poll says OUT, the roster read not yet
    records = []
    monitor(live, live=True, records=records).run(once=True)
    assert [r["event"] for r in records] == ["flip"] and len(espn.bodies) == 1
    set_status(live, "Dyson Daniels", "OUT")  # now both reads agree
    later(live)
    records = []
    monitor(live, live=True, records=records).run(once=True)
    assert len(espn.bodies) == 2
    assert slot(live, "Dyson Daniels") == BENCH and slot(live, "Scotty Pippen Jr.") == SLOT_ID["G"]
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "EXECUTED" and "back on the bench" in swap["text"]


def test_a_revert_after_a_failed_lineup_read_is_tried_on_the_next_read(live, monkeypatch):
    espn = started(live)
    set_status(live, "Dyson Daniels", "OUT")
    real, calls = live.apply_plan, []

    def flaky(period, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            return OptimizeResult(DayPlan(period), error="could not read the lineup: network down",
                                  outcome="ERROR")
        return real(period, *a, **k)

    monkeypatch.setattr(live, "apply_plan", flaky)
    records = []
    monitor(live, live=True, records=records).run(once=True)
    assert [r["event"] for r in records] == ["flip", "error"] and len(espn.bodies) == 1
    later(live)
    records = []
    monitor(live, live=True, records=records).run(once=True)
    assert len(espn.bodies) == 2 and slot(live, "Dyson Daniels") == BENCH
    assert next(r for r in records if r["event"] == "autoswap")["outcome"] == "EXECUTED"


@pytest.mark.parametrize("first", ["QUESTIONABLE", "DAY_TO_DAY"])
def test_risk_then_doubtful_sends_him_back_too(live, first):
    """DTD or Q to DOUBTFUL stays inside one status class, so it is no flip."""
    espn = started(live)
    set_status(live, "Dyson Daniels", first)
    monitor(live, live=True).run(once=True)
    assert len(espn.bodies) == 1 and slot(live, "Dyson Daniels") == SLOT_ID["G"]
    set_status(live, "Dyson Daniels", "DOUBTFUL")
    later(live)
    monitor(live, live=True).run(once=True)
    assert len(espn.bodies) == 2 and slot(live, "Dyson Daniels") == BENCH
    assert mon.read_state(live)["moved"][str(player(live, "Dyson Daniels").id)]["to"] is None
    later(live)
    monitor(live, live=True).run(once=True)  # settled: nothing more
    assert len(espn.bodies) == 2


def test_a_revert_with_nobody_to_take_his_spot_says_so(live):
    espn = started(live)
    set_status(live, "Scotty Pippen Jr.", "OUT")  # the starter he replaced is out too
    set_status(live, "Dyson Daniels", "OUT")
    notes, records = Notes(), []
    monitor(live, live=True, notes=notes, records=records).run(once=True)
    assert len(espn.bodies) == 1 and slot(live, "Dyson Daniels") == SLOT_ID["G"]
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "ALREADY_OPTIMAL" and "still in your lineup" in swap["text"]
    assert any(n.priority == "urgent" and "still in your lineup" in n.body for n in notes.notes)
    alert = mon.read_state(live)["alerts"][-1]
    assert alert["urgent"] and "still in your lineup" in alert["text"]


def test_a_revert_too_close_to_his_tip_says_so(live, monkeypatch):
    espn = started(live)
    tip = live.calendar.game(player(live, "Dyson Daniels").pro_team_id, live.today_period).start
    monkeypatch.setattr(live, "_now", tip - dt.timedelta(minutes=2))
    set_status(live, "Dyson Daniels", "OUT")
    notes = Notes()
    monitor(live, live=True, notes=notes).run(once=True)
    assert len(espn.bodies) == 1
    (late,) = [n for n in notes.notes if "too close" in n.body]
    assert late.priority == "urgent" and "Dyson Daniels is OUT" in late.body

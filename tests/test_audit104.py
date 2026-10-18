"""Regression tests for the 1.0.4 review: reverts that lag or skip a flip, a failed save that
counted a write, the heartbeat of `monitor --once`, news windows longer than one page, and a
rename Windows blocks for a moment.

Nothing reaches ESPN: the monitor runs on ``LiveDemo`` with ``FakeEspn`` (see test_monitor.py)
and the news feed is faked at ``news._get_feed``."""

import datetime as dt

import pytest

from benchboss import monitor as mon
from benchboss import news, store
from benchboss.core.lineup import DayPlan
from benchboss.errors import BenchbossError
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


# --- a save that fails before a send counts nothing ----------------------------------------------

def test_a_send_stopped_by_a_failed_save_counts_no_write_and_no_move(live, monkeypatch):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real_plan, real_write = live.apply_plan, store.write_json
    broken = []

    def plan(*a, **k):
        if k.get("send") is False:
            broken.append(1)  # the disk fills up right after the pre-flight
        return real_plan(*a, **k)

    def write(path, data, **k):
        if broken and path.name == "monitor.json":
            raise BenchbossError(f"could not save {path} (No space left on device)")
        return real_write(path, data, **k)

    monkeypatch.setattr(live, "apply_plan", plan)
    monkeypatch.setattr(mon.store, "write_json", write)
    m = monitor(live, live=True)
    m.start()
    m.tick()
    assert espn.bodies == []
    broken.clear()  # the disk works again later in the same process
    monkeypatch.setattr(live, "apply_plan", real_plan)
    later(live)
    m.tick()
    m.close()
    state = mon.read_state(live)
    pid = str(player(live, "Dyson Daniels").id)
    assert state["counters"]["writes"] == 0 and state["intents"] == {}
    assert int((state["moved"].get(pid) or {}).get("count", 0)) == 0
    assert state["last_write"] == "" and espn.bodies == []


# --- the heartbeat of `monitor --once` ------------------------------------------------------------

def _heartbeat_at(live, monkeypatch, seconds_after_tick):
    with monkeypatch.context() as m:
        m.setattr(mon.time, "time", lambda: live.now.timestamp() + seconds_after_tick)
        return mon.heartbeat(live)


def test_a_recent_once_round_counts_as_a_running_monitor(live, monkeypatch):
    armed(live)
    assert monitor(live).run(once=True) == 0
    assert mon.read_lease(live) is None  # --once gives the lease back
    hb = _heartbeat_at(live, monkeypatch, 120)
    assert hb["running"] and hb["mode"] == "trial" and hb["checked"] == 120
    assert "--once" in hb["text"] and hb["text"].startswith("monitor running in trial mode")
    stale = _heartbeat_at(live, monkeypatch, mon.ONCE_FRESH + 60)
    assert not stale["running"] and stale["text"] == "monitor not running: benchboss monitor"


def test_a_stopped_loop_monitor_is_not_running(live, monkeypatch):
    m = monitor(live)
    m.start()
    m.tick()
    m.close()
    hb = _heartbeat_at(live, monkeypatch, 5)
    assert not hb["running"] and hb["mode"] is None


# --- news windows longer than one page ------------------------------------------------------------

NOW = dt.datetime.now(dt.timezone.utc)


def _row(nid, hours, kind="Rotowire"):
    stamp = (NOW - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": nid, "type": kind, "playerId": 7, "published": stamp, "headline": f"item {nid}"}


class PagedFeed:
    """ESPN's rules: newest first, days, limit and offset."""

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda x: x["published"], reverse=True)
        self.calls = []

    def __call__(self, params):
        self.calls.append(dict(params))
        q = dict(params)
        rows = self.rows
        if "days" in q:
            cutoff = NOW - dt.timedelta(days=q["days"])
            rows = [x for x in rows if news._parse_time(x["published"]) >= cutoff]
        at = q.get("offset", 0)
        return {"feed": rows[at:at + q["limit"]]}


def test_a_long_window_pages_past_the_first_limit(monkeypatch):
    # 30 days of news at 10 items a day (one in ten a video): 300 items, more than one page
    rows = [_row(n, n * 2.4, "Media" if n % 10 == 0 else "Rotowire") for n in range(1, 301)]
    rows.append(_row(999, 24 * 40))  # outside the window
    feed = PagedFeed(rows)
    monkeypatch.setattr(news, "_get_feed", feed)
    items = news.fetch([7], days=30)
    assert len(items) == 270 and 999 not in {x.id for x in items}
    assert [c.get("offset", 0) for c in feed.calls] == [0, 200]
    oldest = min(x.published for x in items)
    assert NOW - oldest > dt.timedelta(days=29)


def test_a_short_window_is_still_one_request(monkeypatch):
    feed = PagedFeed([_row(n, n) for n in range(1, 30)])
    monkeypatch.setattr(news, "_get_feed", feed)
    assert len(news.fetch([7], days=1)) == 23 and len(feed.calls) == 1
    feed.calls.clear()
    news.fetch([7], days=None, limit=10)  # latest mode: the caller pages
    news.fetch([7], days=30, limit=5, offset=5)  # an explicit offset: the caller pages
    assert len(feed.calls) == 2

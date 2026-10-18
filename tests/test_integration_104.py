"""Where the 1.0.4 packages meet: the monitor (auto-swap) on the optimizer's write path.

The monitor plans and sends through Session.apply_plan. It writes its own lineup-log record
for each decision, so apply_plan logs nothing for it (``log=False``), and it fences the POST
with apply_plan's ``before_send`` hook, after the last fresh read of the roster. ESPN is never
called: ``LiveDemo`` is the demo league with a fake transaction (see test_monitor.py)."""

import json

import pytest

from benchboss import lineup_log
from benchboss import monitor as mon
from benchboss.cli import main
from benchboss.core.autoswap import auto_options
from benchboss.demo import DemoClient
from benchboss.marks import MarkStore
from benchboss.service import Outcome
from test_monitor import FakeEspn, LiveDemo, armed, monitor, optimized, player, set_status


def _live():
    return optimized(LiveDemo())


def test_apply_plan_can_leave_the_log_to_its_caller(session):
    daniels = player(session, "Dyson Daniels")
    set_status(session, "Dyson Daniels", "ACTIVE")
    opts = auto_options(session.now, [daniels.id])
    r = session.apply_plan(session.today_period, opts=opts, send=False, writer="monitor",
                           log=False)
    assert r.outcome in (Outcome.WOULD_SEND, Outcome.ALREADY_OPTIMAL, Outcome.BELOW_MIN_GAIN)
    assert lineup_log.read_local(session) == []
    session.apply_plan(session.today_period, opts=opts, send=False, writer="monitor")
    assert [x["event"] for x in lineup_log.read_local(session)] == ["autoswap"]


def test_a_trial_run_is_one_record_in_the_lineup_log(session):
    armed(session)
    monitor(session, simulate={"dyson daniels": "ACTIVE"}).run(once=True)
    events = [r["event"] for r in lineup_log.read_local(session)]
    assert events.count("autoswap") == 1 and events[-2:] == ["flip", "autoswap"]


def test_a_live_change_is_one_record_plus_its_check():
    live = armed(_live())
    live.client.transaction = FakeEspn(live)
    set_status(live, "Dyson Daniels", "ACTIVE")
    assert monitor(live, live=True).run(once=True) == 0
    rows = [r for r in lineup_log.read_local(live) if r["event"] in ("autoswap", "verify")]
    assert [r["event"] for r in rows] == ["verify", "autoswap"]
    assert rows[-1]["outcome"] == "EXECUTED" and rows[-1]["mode"] == "live"
    assert rows[-1]["intent"] in mon.read_state(live)["intents"]


def test_a_disarm_during_the_last_read_before_the_post_wins(monkeypatch):
    """The monitor checks the marks, then apply_plan reads the roster once more before the
    POST. A disarm in that moment still stops the send: before_send checks again."""
    live = armed(_live())
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real_apply, real_roster = live.apply_plan, live.roster_on

    def apply(*a, **k):
        if k.get("send"):
            def roster_on(period):
                MarkStore(live).disarm(player(live, "Dyson Daniels").id)
                return real_roster(period)

            monkeypatch.setattr(live, "roster_on", roster_on)
        return real_apply(*a, **k)

    monkeypatch.setattr(live, "apply_plan", apply)
    assert monitor(live, live=True).run(once=True) == 0
    assert espn.bodies == []
    state = mon.read_state(live)
    assert state["intents"] == {} and state["counters"].get("writes", 0) == 0
    assert not any(r["event"] == "autoswap" and r.get("outcome") == "EXECUTED"
                   for r in lineup_log.read_local(live))


def test_the_intent_holds_the_moves_that_actually_go_out():
    live = armed(_live())
    seen = []

    def check(body):
        (intent,) = mon.read_state(live)["intents"].values()
        seen.append(sorted((i["playerId"], i["toLineupSlotId"]) for i in intent["items"]))
        assert seen[-1] == sorted((i["playerId"], i["toLineupSlotId"]) for i in body["items"])

    live.client.transaction = FakeEspn(live, check=check)
    set_status(live, "Dyson Daniels", "ACTIVE")
    assert monitor(live, live=True).run(once=True) == 0
    assert len(seen) == 1 and len(seen[0]) == 2


def test_a_dry_run_on_a_real_league_writes_no_log_line():
    live = armed(_live())  # arming writes its own "arm" line
    before = lineup_log.read_local(live)
    set_status(live, "Dyson Daniels", "ACTIVE")
    monitor(live, dry_run=True).run(once=True)
    assert lineup_log.read_local(live) == before


# --- add, drop and trade when ESPN's answer has no status -----------------------------------------

def test_a_write_with_no_status_in_the_answer_exits_4_and_says_to_check(monkeypatch, capsys):
    """actions.send no longer passes raw JSON off as a status (optimizer package): an answer
    without one is UNKNOWN. add, drop and trade must not call that a success."""
    monkeypatch.setattr(DemoClient, "transaction", lambda self, body: {"id": "abc"})
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--yes", "drop", "Scotty Pippen Jr."])
    out, err = capsys.readouterr()
    assert e.value.code == 4 and "ESPN: UNKNOWN" in out
    assert "check the league on ESPN before trying again" in " ".join(err.split())
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--json", "--yes", "drop", "Scotty Pippen Jr."])
    out, _ = capsys.readouterr()
    data = json.loads(out)
    assert e.value.code == 4 and data["sent"] and data["status"] == "UNKNOWN"
    assert data["error"].startswith("ESPN's answer had no status")


# --- monitor --simulate on a watch-list player ----------------------------------------------------

def test_simulate_finds_a_watch_list_player(session):
    """`monitor --once --dry-run --simulate "Myles Turner=ACTIVE"` on the demo: he is on the
    watch list, not the roster, and the run says he turned healthy (and sends nothing)."""
    records = []
    m = monitor(session, records=records, dry_run=True, simulate={"Myles Turner": "ACTIVE"})
    assert m.run(once=True) == 0
    assert not any(r["event"] == "error" for r in records), records
    (flip,) = [r for r in records if r["event"] == "flip"]
    assert flip["trigger"]["player"] == "Myles Turner" and flip["trigger"]["new"] == "ACTIVE"


# --- the auto-swap screen in the compact layout (the phone work meets the auto-swap screen) ------

@pytest.mark.parametrize("size", [(46, 30), (40, 18)])
def test_auto_swap_on_a_phone_fits_its_cells_and_the_key_bar_follows_the_row(monkeypatch, size):
    """On a phone the table cuts a cell instead of wrapping it, so the plan reads
    "G for Pippen +5.1" and every cell fits its column (also with the keyboard up and a
    scrollbar), and enter in the key bar says arm or disarm for the row on show."""
    from textual.widgets import DataTable

    from benchboss.ui.screens import autoswap as screen
    from test_autoswap_tui import DANIELS, drive, marks, open_screen

    now = [100.0]
    monkeypatch.setattr(screen, "_clock", lambda: now[0])

    def enter_label(app):
        return next(item.label for item, _ in app.key_entries() if item.key == "⏎")

    async def scenario(pilot, app):
        view = await open_screen(pilot, app)
        assert app.compact
        t = view.query_one(DataTable)
        plan = t.get_cell(str(DANIELS), "plan")
        assert plan.plain == "G for Pippen +5.1"
        used = sum(c.get_render_width(t) for c in t.columns.values())
        assert used + t.styles.scrollbar_size_vertical <= t.size.width
        for key, col in t.columns.items():
            room = col.get_render_width(t) - 2 * t.cell_padding
            assert all(t.get_cell(k, key).cell_len <= room for k in t.rows)
        assert enter_label(app) == "arm"
        await pilot.press("enter")
        now[0] += 1
        await pilot.press("enter")
        await pilot.pause()
        assert marks(app) == {DANIELS: "auto"} and enter_label(app) == "disarm"

    drive(scenario, size=size)

"""The monitor (monitor.py): trial runs, the live path and its guards, the lease, alerts.

Live writes never reach ESPN here: ``LiveDemo`` is the demo league with ``demo`` off and a
fake ``client.transaction`` that applies the moves in memory (or loses them, or refuses)."""

import datetime as dt
import json
import subprocess
import sys
from dataclasses import replace

import pytest

from benchboss import inbox, lineup_log, notify, store
from benchboss import monitor as mon
from benchboss.core.lineup import plan_day
from benchboss.demo import DemoSession
from benchboss.errors import AuthError, BenchbossError, NetworkError
from benchboss.espn.constants import BENCH, IR, SLOT_ID
from benchboss.marks import MarkStore
from benchboss.service import OptimizeResult


class LiveDemo(DemoSession):
    """The demo league as if it were a real one (so live mode is allowed)."""

    @property
    def demo(self) -> bool:
        return False


class Notes(notify.Backend):
    name = "test"

    def __init__(self):
        self.notes = []

    def send(self, note):
        self.notes.append(note)
        return "test: sent"


class FakeEspn:
    """client.transaction. Each answer: "EXECUTED" (applied), "lost-after" (applied, then the
    connection drops), "lost-before" (dropped, nothing applied), "FAILED_..." (refused), or a
    dict (applied, returned as ESPN's body)."""

    def __init__(self, session, *answers, check=None):
        self.session, self.answers, self.bodies, self.check = session, list(answers), [], check

    def __call__(self, body):
        if self.check:
            self.check(body)
        self.bodies.append(body)
        answer = self.answers.pop(0) if self.answers else "EXECUTED"
        if answer in ("EXECUTED", "lost-after") or isinstance(answer, dict):
            spots = {sp.player.id: sp for sp in self.session.league().me.roster}
            for item in body["items"]:
                spots[item["playerId"]].slot_id = item["toLineupSlotId"]
        if answer in ("lost-after", "lost-before"):
            raise NetworkError("the connection to ESPN dropped; it may or may not have gone "
                               "through, check before retrying (RemoteDisconnected)")
        if isinstance(answer, dict):
            return answer
        return {"status": answer}


def optimized(session):
    """Set the lineup Optimize would set this morning (Daniels, White, Harris on the bench)."""
    lg = session.league()
    plan = plan_day(lg.me.roster, lg.slot_counts, session.today_period, session.calendar)
    to = {m.player.id: m.to_slot for m in plan.moves}
    for sp in lg.me.roster:
        sp.slot_id = to.get(sp.player.id, sp.slot_id)
    return session


def set_status(session, name, status):
    """ESPN changes a player's status: the player pool and the roster read both say so."""
    for x in session.client.pool():
        if x["player"]["fullName"] == name:
            x["player"]["injuryStatus"] = status
    for sp in session.league().me.roster:
        if sp.player.name == name:
            sp.player = replace(sp.player, injury_status=status, injury_known=True)


def later(session, minutes=5):
    """Move the frozen demo clock on (writes are 60 s apart)."""
    session._now = session.now + dt.timedelta(minutes=minutes)


def player(session, name):
    return next(sp.player for sp in session.league().me.roster if sp.player.name == name)


def slot(session, name):
    return next(sp.slot_id for sp in session.league().me.roster if sp.player.name == name)


def monitor(session, *, live=False, notes=None, records=None, **kw):
    kw.setdefault("sleep", lambda s: None)
    return mon.Monitor(lambda: session, live=live, backends=[notes or Notes()],
                       emit=(records.append if records is not None else None), **kw)


@pytest.fixture
def live():
    return optimized(LiveDemo())


def armed(session, name="Dyson Daniels", mode="auto"):
    MarkStore(session).arm(player(session, name), mode)
    return session


# --- trial mode on the demo ----------------------------------------------------------------------

def test_trial_run_says_what_it_would_do_and_sends_nothing(session, monkeypatch):
    def no_writes(body):
        raise AssertionError("trial mode sent a transaction")

    monkeypatch.setattr(session.client, "transaction", no_writes)
    notes, records = Notes(), []
    m = monitor(session, notes=notes, records=records, simulate={"dyson daniels": "ACTIVE"})
    assert m.run(once=True) == 0
    flip, swap = [r for r in records if r["event"] in ("flip", "autoswap")]
    assert flip["trigger"]["old"] == "DAY_TO_DAY" and flip["trigger"]["new"] == "ACTIVE"
    assert swap["mode"] == "trial" and swap["outcome"] == "WOULD_SEND"
    assert [(x["player"], x["from"], x["to"]) for x in swap["moves"]] == [
        ("Dyson Daniels", "BE", "G"), ("Scotty Pippen Jr.", "G", "BE")]
    assert swap["text"] == ("Trial run: benchboss would have started Dyson Daniels at G and "
                            "benched Scotty Pippen Jr. (+5.1). Nothing was sent.")
    assert swap["projected_after"] == 387.0 and swap["gain"] == 5.1
    assert all(k in swap for k in lineup_log.REQUIRED) and swap["kind"] == "ROSTER"
    assert [n.body for n in notes.notes] == [swap["text"]]
    # the app's Inbox shows it (from the state file), and the log has it
    kinds = [(a.kind, a.urgent) for a in inbox.alerts(session, include_chat=False,
                                                       include_spins=False)]
    assert ("autoswap", False) in kinds
    assert [r["event"] for r in lineup_log.read_local(session)][-2:] == ["flip", "autoswap"]


def test_a_flip_acts_once(session):
    notes = Notes()
    monitor(session, notes=notes, simulate={"Dyson Daniels": "ACTIVE"}).run(once=True)
    records = []
    monitor(session, notes=notes, records=records,
            simulate={"Dyson Daniels": "ACTIVE"}).run(once=True)
    assert [r for r in records if r["event"] in ("flip", "autoswap")] == []
    assert len(notes.notes) == 1


def test_a_dry_run_saves_sends_and_logs_nothing(session):
    notes, records = Notes(), []
    m = monitor(session, notes=notes, records=records, dry_run=True,
                simulate={"Dyson Daniels": "ACTIVE"})
    assert m.run(once=True) == 0
    assert any(r["event"] == "autoswap" for r in records)
    assert notes.notes == []
    keys = set(session.local_state)
    assert not any("monitor" in k or "lineup-" in k for k in keys), keys


def test_first_sight_is_silent_then_a_watch_list_player_who_turns_healthy_alerts(live):
    notes = Notes()
    turner = 3133628  # Myles Turner, DAY_TO_DAY on the demo watch list
    assert monitor(live, notes=notes).run(once=True) == 0
    assert notes.notes == [] and mon.read_state(live)["status"][str(turner)] == "DAY_TO_DAY"
    for x in live.client.pool():
        if x["id"] == turner:
            x["player"]["injuryStatus"] = "ACTIVE"
    monitor(live, notes=notes).run(once=True)
    (note,) = notes.notes
    assert note.title == "Healthy" and note.priority == "urgent"
    assert note.body.startswith("Myles Turner is healthy (was DTD). Tips ")
    alerts = inbox.monitor_alerts(live)
    assert [(a.kind, a.player, a.urgent) for a in alerts] == [("healthy", "Myles Turner", True)]
    assert alerts[0].to_dict()["at"]


def test_a_notify_only_mark_alerts_and_never_plans(live, monkeypatch):
    armed(live, "Dyson Daniels", "notify")
    calls = []
    real = live.apply_plan
    monkeypatch.setattr(live, "apply_plan", lambda *a, **k: calls.append(k) or real(*a, **k))
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes = Notes()
    monitor(live, live=True, notes=notes).run(once=True)
    assert calls == [] and [n.title for n in notes.notes] == ["Healthy"]


def test_a_bad_read_changes_nothing(live, monkeypatch):
    armed(live)
    real = live.player_snapshot
    monitor(live).run(once=True)
    before = mon.read_state(live)["status"]

    def blank(ids):
        return [replace(p, injury_status="ACTIVE", injury_known=False) for p in real(ids)]

    monkeypatch.setattr(live, "player_snapshot", blank)
    records = []
    monitor(live, live=True, records=records).run(once=True)
    assert [r["event"] for r in records] == ["error"] and "bad read" in records[0]["text"]
    assert mon.read_state(live)["status"] == before


# --- live mode -----------------------------------------------------------------------------------

def test_live_sends_once_verifies_and_reports(live):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes, records, sleeps = Notes(), [], []
    m = monitor(live, live=True, notes=notes, records=records, sleep=sleeps.append)
    assert m.run(once=True) == 0
    (body,) = espn.bodies
    assert body["type"] == "ROSTER" and body["scoringPeriodId"] == live.today_period
    assert sorted((i["playerId"], i["toLineupSlotId"]) for i in body["items"]) == sorted(
        [(player(live, "Dyson Daniels").id, SLOT_ID["G"]),
         (player(live, "Scotty Pippen Jr.").id, BENCH)])
    assert sleeps == [mon.VERIFY_AFTER]
    verify = next(r for r in records if r["event"] == "verify")
    swap = next(r for r in records if r["event"] == "autoswap")
    assert verify["result"] == "ok" and swap["mode"] == "live" and swap["outcome"] == "EXECUTED"
    assert swap["text"].startswith("Auto-swap: started Dyson Daniels at G, benched Scotty "
                                   "Pippen Jr. ESPN: EXECUTED")
    assert "benchboss optimize tomorrow" in swap["text"]
    state = mon.read_state(live)
    (intent,) = state["intents"].values()
    assert intent["outcome"] == "EXECUTED" and swap["intent"] in state["intents"]
    assert state["counters"] == {"writes": 1, "failures": 0}
    assert state["moved"][str(player(live, "Dyson Daniels").id)]["benched"] == \
        player(live, "Scotty Pippen Jr.").id
    assert notes.notes[-1].body == swap["text"]
    # the next round has nothing to do
    monitor(live, live=True).run(once=True)
    assert len(espn.bodies) == 1


def test_the_intent_is_saved_before_the_post(live):
    armed(live)
    seen = []

    def check(body):
        state = mon.read_state(live)
        seen.append([(i["outcome"], i["items"]) for i in state["intents"].values()])

    live.client.transaction = FakeEspn(live, check=check)
    set_status(live, "Dyson Daniels", "ACTIVE")
    monitor(live, live=True).run(once=True)
    (intents,) = seen
    assert len(intents) == 1 and intents[0][0] is None and len(intents[0][1]) == 2


def test_two_reads_must_agree_before_a_write(live, monkeypatch):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    for x in live.client.pool():  # the poll says healthy, the roster read does not yet
        if x["player"]["fullName"] == "Dyson Daniels":
            x["player"]["injuryStatus"] = "ACTIVE"
    monitor(live, live=True).run(once=True)
    assert espn.bodies == []
    assert str(player(live, "Dyson Daniels").id) in mon.read_state(live)["pending"]
    set_status(live, "Dyson Daniels", "ACTIVE")  # now the roster agrees
    monitor(live, live=True).run(once=True)
    assert len(espn.bodies) == 1


def test_a_lost_answer_that_went_through_is_not_sent_again(live):
    armed(live)
    espn = FakeEspn(live, "lost-after")
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    records = []
    assert monitor(live, live=True, records=records).run(once=True) == 0
    assert len(espn.bodies) == 1
    assert next(r for r in records if r["event"] == "autoswap")["outcome"] == "EXECUTED"


def test_a_lost_write_is_resent_once_and_then_left_alone(live):
    armed(live)
    espn = FakeEspn(live, "lost-before", "EXECUTED")
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    assert monitor(live, live=True).run(once=True) == 0
    assert len(espn.bodies) == 2 and slot(live, "Dyson Daniels") == SLOT_ID["G"]


def test_a_write_that_never_lands_is_reported_not_retried_forever(live):
    armed(live)
    espn = FakeEspn(live, "lost-before", "lost-before", "lost-before")
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes, records = Notes(), []
    assert monitor(live, live=True, notes=notes, records=records).run(once=True) == 4
    assert len(espn.bodies) == 2  # the first send and one resend, never a third
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "UNKNOWN" and notes.notes[-1].priority == "urgent"
    monitor(live, live=True).run(once=True)
    assert len(espn.bodies) == 2


def test_failed_is_never_retried_and_two_failures_end_the_day_in_trial(live):
    armed(live)
    armed(live, "Coby White")
    espn = FakeEspn(live, "FAILED_LINEUPLOCK", "FAILED_LINEUPLOCK")
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes = Notes()
    assert monitor(live, live=True, notes=notes).run(once=True) == 4
    assert len(espn.bodies) == 1
    monitor(live, live=True, notes=notes).run(once=True)
    assert len(espn.bodies) == 1  # no retry
    set_status(live, "Dyson Daniels", "DAY_TO_DAY")  # one healthy bench player at a time
    set_status(live, "Coby White", "ACTIVE")
    later(live)
    assert monitor(live, live=True, notes=notes).run(once=True) == 4
    assert len(espn.bodies) == 2
    assert mon.read_state(live)["counters"]["failures"] == 2
    assert any("rest of the day" in n.body for n in notes.notes)
    # Daniels turns healthy again: a new change, but only a trial run for the rest of the day
    set_status(live, "Coby White", "DAY_TO_DAY")
    set_status(live, "Dyson Daniels", "ACTIVE")
    later(live)
    records = []
    assert monitor(live, live=True, notes=notes, records=records).run(once=True) == 0
    assert len(espn.bodies) == 2
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "WOULD_SEND" and "refused two changes today" in swap["text"]


def test_a_disarm_or_a_pause_made_a_moment_ago_wins(live, monkeypatch):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real = live.apply_plan

    def disarm_first(*a, **k):
        if k.get("send") is False:
            MarkStore(live).disarm(player(live, "Dyson Daniels").id)
        return real(*a, **k)

    monkeypatch.setattr(live, "apply_plan", disarm_first)
    monitor(live, live=True).run(once=True)
    assert espn.bodies == []
    monkeypatch.setattr(live, "apply_plan", real)
    armed(live)
    MarkStore(live).set_paused(True)
    monitor(live, live=True).run(once=True)
    assert espn.bodies == []


def test_a_monitor_that_lost_its_lease_stops_writing(live, monkeypatch):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real = live.apply_plan

    def taken_over(*a, **k):
        other = mon.Lease(live.client.league_id, memory=live.local_state, host="mac-mini")
        store.write_json(other.path, other._info(), memory=live.local_state)
        return real(*a, **k)

    monkeypatch.setattr(live, "apply_plan", taken_over)
    records = []
    m = monitor(live, live=True, records=records)
    m.run(once=True)
    assert espn.bodies == [] and m.stop.is_set()
    assert any("lease" in r.get("text", "") for r in records)


def test_caps_and_spacing(live):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    m = monitor(live, live=True)
    m.start()
    m._roll_day()
    m.state["counters"]["writes"] = mon.MAX_WRITES
    records = []
    m.emit = records.append
    m.tick()
    m.close()
    assert espn.bodies == []
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "WOULD_SEND" and "6 automatic changes today" in swap["text"]
    # a write a moment ago, with the tip hours away: wait for the next round
    m = monitor(live, live=True)
    m.start()
    m._roll_day()
    m.state["acted"] = {}
    m.state["counters"]["writes"] = 1
    m.state["last_write"] = live.now.isoformat()
    m.state["pending"][str(player(live, "Dyson Daniels").id)] = {"edge": 9, "old": "DAY_TO_DAY"}
    m.tick()
    assert espn.bodies == [] and str(player(live, "Dyson Daniels").id) in m.state["pending"]
    m.close()


def test_someone_else_moving_an_armed_player_rests_his_mark_for_the_day(live):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    pid = str(player(live, "Dyson Daniels").id)
    m = monitor(live, live=True)
    m.start()
    m._roll_day()
    m.state["lineup"][pid] = SLOT_ID["G"]  # the monitor last saw him at G; now he is on BE
    m._save()
    m.close()
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes = Notes()
    monitor(live, live=True, notes=notes).run(once=True)
    assert espn.bodies == []
    assert mon.read_state(live)["held"][pid] == live.today.isoformat()
    assert "leaves him alone" in notes.notes[-1].body


def test_too_close_to_the_tip_changes_nothing(live, monkeypatch):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    tip = live.calendar.game(player(live, "Dyson Daniels").pro_team_id, live.today_period).start
    monkeypatch.setattr(live, "_now", tip - dt.timedelta(minutes=2))
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes = Notes()
    monitor(live, live=True, notes=notes).run(once=True)
    assert espn.bodies == [] and "too close to his" in notes.notes[-1].body


def test_a_player_it_started_who_is_ruled_out_goes_back_to_the_bench(live):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    monitor(live, live=True).run(once=True)
    assert slot(live, "Dyson Daniels") == SLOT_ID["G"]
    set_status(live, "Dyson Daniels", "OUT")
    records = []
    monitor(live, live=True, records=records).run(once=True)
    assert len(espn.bodies) == 2
    assert slot(live, "Dyson Daniels") == BENCH and slot(live, "Scotty Pippen Jr.") == SLOT_ID["G"]
    swap = [r for r in records if r["event"] == "autoswap"][-1]
    assert swap["outcome"] == "EXECUTED" and "back on the bench" in swap["text"]


def test_the_guard_refuses_a_plan_that_moves_too_much(live, monkeypatch):
    """The monitor's own scope check (guard G5's twin) stops a plan that starts players
    nobody armed: exit code 5, nothing sent."""
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real = live.apply_plan

    def too_much(period, *a, **k):
        r = real(period, *a, **k)
        if k.get("send") is False and r.plan.moves:
            siakam = next(sp for sp in live.league().me.roster if sp.player.name == "Pascal Siakam")
            harris = player(live, "Tobias Harris")
            from benchboss.core.lineup import Move

            r.plan.moves += [Move(siakam.player, siakam.slot_id, BENCH),
                             Move(harris, BENCH, siakam.slot_id)]
        return r

    monkeypatch.setattr(live, "apply_plan", too_much)
    records, notes = [], Notes()
    assert monitor(live, live=True, records=records, notes=notes).run(once=True) == 5
    assert espn.bodies == []
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "NOT_SENT" and "G5" in swap["guards"]
    assert notes.notes[-1].priority == "urgent"


def test_the_day_must_be_espns_today(live, monkeypatch):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    monkeypatch.setattr(live, "current_period",
                        lambda strict=False: live.today_period - 1 if strict else live.today_period)
    records = []
    assert monitor(live, live=True, records=records).run(once=True) == 5
    assert espn.bodies == []
    assert next(r for r in records if r["event"] == "autoswap")["guards"] == ["G9"]


def test_live_is_refused_where_lineups_do_not_lock_per_game(live):
    live.league().lineup_lock_type = "DAILY"
    with pytest.raises(BenchbossError, match="live mode refused"):
        monitor(live, live=True).run(once=True)
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes = Notes()
    m = monitor(live, live=True, notes=notes)
    m.start()  # the loop does not exit: it runs in trial mode and says so
    assert m.mode == "trial" and notes.notes[0].priority == "urgent"
    m.tick()
    m.close()
    assert espn.bodies == []


def test_the_demo_never_writes(session):
    with pytest.raises(BenchbossError, match="demo mode never writes"):
        monitor(session, live=True).run(once=True)


# --- errors and the loop -------------------------------------------------------------------------

def test_expired_cookies_exit_3_once_and_wait_in_the_loop(live, monkeypatch):
    armed(live)

    def expired(ids):
        raise AuthError("ESPN rejected the cookies")

    monkeypatch.setattr(live, "player_snapshot", expired)
    notes = Notes()
    assert monitor(live, notes=notes).run(once=True) == 3
    assert [n.body for n in notes.notes] == ["benchboss cannot read your league: run benchboss "
                                             "login"]
    sleeps = []
    m = monitor(live, notes=notes, sleep=lambda s: sleeps.append(s) or (
        len(sleeps) >= 3 and m.stop.set()))
    assert m.run() == 0  # stopped from outside, never by the error
    assert len(sleeps) >= 3 and mon.read_state(live)["heartbeat"]["auth_wait"] is True


def test_espn_down_is_a_backoff_not_a_crash(live, monkeypatch):
    armed(live)

    def down(ids):
        raise NetworkError("could not reach ESPN (timed out)")

    monkeypatch.setattr(live, "player_snapshot", down)
    records = []
    m = monitor(live, records=records)
    assert m.run(once=True) == 1
    assert records[-1]["event"] == "error" and "could not reach ESPN" in records[-1]["text"]
    m = monitor(live)
    m.start()
    assert m._round() == mon.BACKOFF[0]
    assert m._round() == mon.BACKOFF[1]
    m.close()


def test_missing_cookies_at_start_wait_in_the_loop(live):
    calls, notes = [], Notes()

    def factory():
        calls.append(1)
        if len(calls) == 1:
            raise AuthError("no ESPN cookies found: run `benchboss login`")
        return live

    m = mon.Monitor(factory, backends=[notes], sleep=lambda s: None)
    m._start_safely(once=False)
    assert m.session is live and len(calls) == 2
    assert "run benchboss login" in notes.notes[0].body
    m.close()
    with pytest.raises(AuthError):
        mon.Monitor(lambda: (_ for _ in ()).throw(AuthError("x")), backends=[]).run(once=True)


def test_the_log_state_and_notes_never_carry_the_swid(live):
    armed(live)
    swid = live.client.swid
    espn = FakeEspn(live, {"memberId": swid, "creationInfo": {"source": swid}})
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes, records = Notes(), []
    monitor(live, live=True, notes=notes, records=records).run(once=True)
    assert len(espn.bodies) == 1
    blobs = [json.dumps(records), json.dumps(lineup_log.read_local(live)),
             json.dumps(mon.read_state(live)), json.dumps([n.body for n in notes.notes])]
    for blob in blobs:
        assert swid not in blob and swid.strip("{}") not in blob


# --- the lease and the heartbeat -----------------------------------------------------------------

def test_one_monitor_per_league(live):
    first = mon.Lease(live.client.league_id, memory=live.local_state)
    first.acquire()
    with pytest.raises(mon.MonitorBusy, match="only one per league"):
        mon.Lease(live.client.league_id, memory=live.local_state, host="mac-mini").acquire()
    with pytest.raises(mon.MonitorBusy):
        monitor(live).run(once=True)
    assert first.renew() and first.held()
    first.release()
    assert mon.read_lease(live) is None
    monitor(live).run(once=True)


def test_an_expired_lease_is_taken_over_and_the_old_one_knows(live):
    old = mon.Lease(live.client.league_id, memory=live.local_state, host="mac-mini",
                    clock=lambda: 1000.0)
    old.acquire()  # expired long ago
    new = mon.Lease(live.client.league_id, memory=live.local_state)
    new.acquire()
    assert new.held() and not old.held() and not old.renew()


@pytest.mark.skipif(sys.platform == "win32", reason="pid checks are off on Windows")
def test_a_lease_left_by_a_dead_process_on_this_computer_is_taken_over(tmp_path):
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                          capture_output=True, text=True, check=True)
    dead = int(done.stdout)
    stale = mon.Lease(42, pid=dead, host="here")
    stale.acquire()
    if store.lease_path(42).exists():
        assert store.lease_path(42).stat().st_mode & 0o777 == 0o600
    fresh = mon.Lease(42, host="here")
    fresh.acquire()
    assert fresh.held()
    busy = mon.Lease(42, host="elsewhere")
    with pytest.raises(mon.MonitorBusy):
        busy.acquire()


def test_heartbeat_says_whether_the_monitor_runs(live):
    assert mon.heartbeat(live)["text"] == "monitor not running: benchboss monitor"
    lease = mon.Lease(live.client.league_id, memory=live.local_state, host="mac-mini")
    lease.acquire()
    state = mon.fresh_state(live.client.league_id)
    ago = dt.datetime.now().astimezone() - dt.timedelta(seconds=40)
    state["heartbeat"] = {"mode": "trial", "host": "mac-mini",
                          "last_tick": ago.isoformat(timespec="seconds")}
    store.write_json(store.monitor_path(live.client.league_id), state, memory=live.local_state)
    hb = mon.heartbeat(live)
    assert hb["running"] and hb["host"] == "mac-mini" and 39 <= hb["checked"] <= 45
    assert hb["text"].startswith("monitor running in trial mode on mac-mini, checked 4")


def test_a_damaged_state_file_reads_as_a_monitor_that_never_ran(live):
    store.write_json(store.monitor_path(live.client.league_id), ["nope"],
                     memory=live.local_state)
    assert mon.read_state(live)["alerts"] == []
    assert inbox.monitor_alerts(live) == []


def test_the_monitor_tracks_nobody_without_marks_or_a_watch_list(live, monkeypatch):
    live.league().me.watch_list = ()
    calls = []
    monkeypatch.setattr(live, "player_snapshot", lambda ids: calls.append(ids) or [])
    assert monitor(live).run(once=True) == 0
    assert calls == []


def test_ir_players_are_never_armed_targets(live, monkeypatch):
    harris = next(sp for sp in live.league().me.roster if sp.player.name == "Tobias Harris")
    MarkStore(live).arm(harris.player)
    harris.slot_id = IR
    calls = []
    real = live.apply_plan
    monkeypatch.setattr(live, "apply_plan", lambda *a, **k: calls.append(1) or real(*a, **k))
    set_status(live, "Tobias Harris", "ACTIVE")
    monitor(live, live=True).run(once=True)
    assert calls == []


def test_apply_plan_outcomes_reach_the_record(live, monkeypatch):
    """Whatever apply_plan answers (here a refused write), the monitor records the outcome and
    counts it as a failure, without parsing any error text."""
    armed(live)
    set_status(live, "Dyson Daniels", "ACTIVE")
    real = live.apply_plan

    def refused(period, *a, **k):
        r = real(period, *a, send=False, **{x: v for x, v in k.items() if x != "send"})
        if k.get("send") is False:
            return r
        return OptimizeResult(r.plan, status="", error="ESPN 409: no", outcome="REFUSED",
                              kind="ROSTER")

    monkeypatch.setattr(live, "apply_plan", refused)
    records = []
    assert monitor(live, live=True, records=records).run(once=True) == 4
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "REFUSED" and mon.read_state(live)["counters"]["failures"] == 1


def test_a_monitor_that_finds_the_lease_taken_leaves_the_files_alone(live):
    first = monitor(live)
    first.start()
    first.state["alerts"].append({"key": "k", "kind": "healthy", "text": "kept"})
    first._save()
    with pytest.raises(mon.MonitorBusy):
        monitor(live).run(once=True)
    assert mon.read_state(live)["alerts"][-1]["text"] == "kept"
    assert first.lease.held()
    first.close()


def test_a_start_and_a_revert_use_up_the_two_moves_of_the_day(live):
    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    monitor(live, live=True).run(once=True)
    set_status(live, "Dyson Daniels", "OUT")
    later(live)
    monitor(live, live=True).run(once=True)
    assert len(espn.bodies) == 2
    moved = mon.read_state(live)["moved"][str(player(live, "Dyson Daniels").id)]
    assert moved["count"] == 2 and moved["to"] is None
    set_status(live, "Dyson Daniels", "ACTIVE")  # healthy again: a third move is too many
    later(live)
    records = []
    monitor(live, live=True, records=records).run(once=True)
    assert len(espn.bodies) == 2
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "WOULD_SEND" and "moved 2 times today" in swap["text"]


def test_a_paused_auto_mark_still_says_he_is_healthy(live):
    armed(live)
    MarkStore(live).set_paused(True)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    notes = Notes()
    monitor(live, live=True, notes=notes).run(once=True)
    assert espn.bodies == [] and [n.title for n in notes.notes] == ["Healthy"]


def test_nothing_is_sent_when_the_intent_cannot_be_saved(live, monkeypatch):
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
    notes, records = Notes(), []
    monitor(live, live=True, notes=notes, records=records).run(once=True)
    assert espn.bodies == []
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "NOT_SENT" and "could not save" in swap["text"]
    assert any("cannot save its state" in n.body for n in notes.notes)


# --- self-check: the gaps found after the build ----------------------------------------------------

def test_a_pending_flip_ends_when_the_mark_is_lowered_to_an_alert(live):
    """A flip that waited for the roster read to agree is dropped once the player is no longer
    armed for auto-swap, even when the monitor still watches him."""
    armed(live)
    for x in live.client.pool():  # the poll says healthy, the roster read does not yet
        if x["player"]["fullName"] == "Dyson Daniels":
            x["player"]["injuryStatus"] = "ACTIVE"
    monitor(live).run(once=True)
    pid = str(player(live, "Dyson Daniels").id)
    assert pid in mon.read_state(live)["pending"]
    armed(live, mode="notify")
    set_status(live, "Dyson Daniels", "ACTIVE")  # now the roster agrees
    later(live)
    notes, records = Notes(), []
    monitor(live, notes=notes, records=records).run(once=True)
    assert pid not in mon.read_state(live)["pending"]
    assert not [r for r in records if r["event"] == "autoswap"] and notes.notes == []


def test_a_pause_while_the_change_is_checked_stops_the_resend(live):
    armed(live)
    espn = FakeEspn(live, "lost-before", "EXECUTED")
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    records = []
    m = monitor(live, live=True, records=records,
                sleep=lambda s: MarkStore(live).set_paused(True))
    assert m.run(once=True) == 4
    assert len(espn.bodies) == 1
    assert next(r for r in records if r["event"] == "autoswap")["outcome"] == "UNKNOWN"


def test_a_stale_check_after_a_lost_answer_never_sends_twice(live, monkeypatch):
    """ESPN applied the change but the answer was lost, and the first check still reads the
    old lineup: the resend finds nothing to do, the next check sees the change."""
    armed(live)
    stale = []
    espn = FakeEspn(live, "lost-after",
                    check=lambda body: stale.append([replace(sp) for sp in live.league().me.roster]))
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real, served = live.roster_on, []

    def roster_on(period):
        if espn.bodies and not served:
            served.append(1)
            return stale[0]
        return real(period)

    monkeypatch.setattr(live, "roster_on", roster_on)
    records = []
    assert monitor(live, live=True, records=records).run(once=True) == 0
    assert len(espn.bodies) == 1
    assert [r["result"] for r in records if r["event"] == "verify"] == ["not applied", "ok"]
    assert next(r for r in records if r["event"] == "autoswap")["outcome"] == "EXECUTED"
    assert mon.read_state(live)["moved"][str(player(live, "Dyson Daniels").id)]["to"] == "G"


def test_cookies_turned_down_on_the_lineup_read_keep_the_flip_waiting(live, monkeypatch):
    from benchboss.core.lineup import DayPlan

    armed(live)
    set_status(live, "Dyson Daniels", "ACTIVE")
    monkeypatch.setattr(live, "apply_plan", lambda period, *a, **k: OptimizeResult(
        DayPlan(period), error="could not read the lineup: ESPN 401", outcome="AUTH"))
    records = []
    assert monitor(live, live=True, records=records).run(once=True) == 3
    state = mon.read_state(live)
    assert str(player(live, "Dyson Daniels").id) in state["pending"] and not state["acted"]
    assert not [r for r in records if r["event"] == "autoswap"]


def test_a_pretend_status_never_goes_live(live):
    with pytest.raises(BenchbossError, match="never live"):
        monitor(live, live=True, simulate={"Dyson Daniels": "ACTIVE"})
    assert monitor(live, live=True, dry_run=True, simulate={"Dyson Daniels": "ACTIVE"}).mode == "trial"


def test_a_plan_that_moves_a_started_player_is_refused(live, monkeypatch):
    """The monitor's own twin of guard G1: nothing is sent when the plan touches a player
    whose game started (here ESPN already locked the starter who would sit)."""
    from benchboss.core.lineup import Move

    armed(live)
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real = live.apply_plan

    def started(period, *a, **k):
        r = real(period, *a, **k)
        if k.get("send") is False and r.plan.moves:
            m = r.plan.moves[-1]  # Scotty Pippen Jr. G -> BE
            r.plan.moves[-1] = Move(replace(m.player, locked=True), m.from_slot, m.to_slot)
        return r

    monkeypatch.setattr(live, "apply_plan", started)
    records = []
    assert monitor(live, live=True, records=records).run(once=True) == 5
    assert espn.bodies == []
    swap = next(r for r in records if r["event"] == "autoswap")
    assert swap["outcome"] == "NOT_SENT" and swap["guards"] == ["G1"]
    assert "Scotty Pippen Jr. is locked on ESPN" in swap["text"]


def test_a_resend_that_could_not_read_the_lineup_leaves_the_change_unknown(live, monkeypatch):
    from benchboss.core.lineup import DayPlan

    armed(live)
    espn = FakeEspn(live, "lost-before")
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    real, sends = live.apply_plan, []

    def plan(period, *a, **k):
        if k.get("send") is not False:
            sends.append(1)
            if len(sends) == 2:  # the resend: ESPN does not answer the read before it
                return OptimizeResult(DayPlan(period), error="could not read the lineup",
                                      outcome="ERROR")
        return real(period, *a, **k)

    monkeypatch.setattr(live, "apply_plan", plan)
    records = []
    assert monitor(live, live=True, records=records).run(once=True) == 4
    assert len(espn.bodies) == 1 and len(sends) == 2
    assert next(r for r in records if r["event"] == "autoswap")["outcome"] == "UNKNOWN"

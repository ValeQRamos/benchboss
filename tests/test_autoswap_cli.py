"""The CLI contract of `benchboss autoswap` and `benchboss monitor`: flags, questions, exit
codes, JSON shapes, demo behavior."""

import json

import pytest

from benchboss import cli, lineup_log
from benchboss import monitor as mon
from benchboss.cli import main
from benchboss.espn.constants import IR
from benchboss.marks import MarkStore
from test_monitor import FakeEspn, LiveDemo, optimized, set_status


def run(argv, capsys):
    """(exit code, stdout, stderr) of one command."""
    try:
        main(argv)
        code = 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def live(monkeypatch):
    """A league that behaves like a real one (LiveDemo): the CLI's session for every command."""
    s = optimized(LiveDemo())
    monkeypatch.setattr(cli.Ctx, "session", property(lambda self: s))
    return s


# --- benchboss monitor --------------------------------------------------------------------------

def test_demo_monitor_prints_the_chat_example_and_sends_nothing(capsys, session, monkeypatch):
    code, out, _ = run(["--demo", "monitor", "--once", "--simulate", "Dyson Daniels=ACTIVE"],
                       capsys)
    assert code == 0
    assert "Trial run: benchboss would have started Dyson Daniels at G and benched Scotty" in \
        " ".join(out.split())
    assert "Nothing was sent." in out


def test_monitor_json_is_one_record_per_line(capsys):
    code, out, _ = run(["--demo", "monitor", "--once", "--dry-run", "--json", "--simulate",
                        "Dyson Daniels=active"], capsys)
    assert code == 0
    recs = [json.loads(ln) for ln in out.splitlines()]
    assert [r["event"] for r in recs] == ["flip", "autoswap"]
    assert all(r["writer"] == "monitor" and r["mode"] == "trial" for r in recs)
    assert recs[1]["moves"][0] == {"player_id": recs[1]["trigger"]["player_id"],
                                   "player": "Dyson Daniels", "from": "BE", "to": "G"}


@pytest.mark.parametrize("argv, code, words", [
    (["--demo", "monitor"], 2, "add --once"),
    (["--demo", "monitor", "--once", "--live"], 1, "demo mode never writes"),
    (["--demo", "monitor", "--once", "--live", "--dry-run"], 2, "pick one"),
    (["--demo", "monitor", "--once", "--live", "--simulate", "Dyson Daniels=ACTIVE"], 2,
     "never with --live"),
    (["--demo", "monitor", "--once", "--simulate", "Dyson Daniels=HEALTHY"], 2, "STATUS one of"),
    (["--demo", "monitor", "--once", "--notify", "ntfy"], 1, "BENCHBOSS_NTFY_TOPIC"),
    (["--demo", "monitor", "--once", "--notify", "pager"], 1, "unknown notification backend"),
])
def test_monitor_refuses_bad_combinations(argv, code, words, capsys):
    got, out, err = run(argv, capsys)
    assert got == code and words in " ".join((out + err).split())


def test_notify_test_sends_one_note_and_prints_receipts(capsys):
    code, out, _ = run(["--demo", "monitor", "--notify-test", "--notify", "log"], capsys)
    assert code == 0 and "log: written" in out and "Nikola Jokić" in out


def test_live_needs_a_yes(live, capsys):
    code, _, err = run(["monitor", "--once", "--live", "--json"], capsys)
    assert code == 10 and "NOT DONE" in err
    code, _, err = run(["monitor", "--once", "--live"], capsys)  # no terminal to ask
    assert code == 10


def test_live_once_with_yes_writes_through_apply_plan(live, capsys, monkeypatch):
    monkeypatch.setattr(mon, "VERIFY_AFTER", 0)
    MarkStore(live).arm(next(sp.player for sp in live.league().me.roster
                             if sp.player.name == "Dyson Daniels"))
    espn = FakeEspn(live)
    live.client.transaction = espn
    set_status(live, "Dyson Daniels", "ACTIVE")
    code, out, _ = run(["monitor", "--once", "--live", "--yes", "--notify", "log"], capsys)
    assert code == 0 and len(espn.bodies) == 1
    assert "Auto-swap: started Dyson Daniels at G, benched Scotty Pippen Jr. ESPN: EXECUTED" in \
        " ".join(out.split())


def test_live_refused_where_lineups_lock_daily(live, capsys):
    live.league().lineup_lock_type = "DAILY"
    code, _, err = run(["monitor", "--once", "--live", "--yes", "--notify", "log"], capsys)
    assert code == 1 and "live mode refused" in err


def test_monitor_once_reports_expired_cookies_with_exit_3(live, capsys, monkeypatch):
    from benchboss.errors import AuthError

    MarkStore(live).arm(next(sp.player for sp in live.league().me.roster
                             if sp.player.name == "Dyson Daniels"))

    def expired(ids):
        raise AuthError("ESPN rejected the cookies")

    monkeypatch.setattr(live, "player_snapshot", expired)
    code, _, _ = run(["monitor", "--once", "--notify", "log"], capsys)
    assert code == 3


# --- benchboss autoswap -------------------------------------------------------------------------

def test_list_shows_every_player_and_what_would_happen(capsys):
    code, out, _ = run(["--demo", "autoswap"], capsys)
    assert code == 0 and "Dyson Daniels" in out and "starts at G" in out
    assert "monitor not running: benchboss monitor" in out
    code, out, _ = run(["--demo", "autoswap", "list", "--json"], capsys)
    data = json.loads(out)
    assert set(data) == {"paused", "error", "monitor", "until_default", "players", "today"}
    daniels = next(p for p in data["players"] if p["player"] == "Dyson Daniels")
    assert daniels["status"] == "DAY_TO_DAY" and daniels["armed"] is None
    assert daniels["if_healthy"]["benches"] == "Scotty Pippen Jr."
    assert daniels["tip"] == "2026-11-04T19:00:00-05:00"


def test_add_previews_and_the_demo_refuses_to_arm(capsys):
    code, out, _ = run(["--demo", "autoswap", "add", "Dyson Daniels", "--dry-run"], capsys)
    assert code == 0 and "starts him at G and benches Scotty Pippen Jr." in " ".join(out.split())
    assert "Dry run: nothing was armed." in out
    code, out, _ = run(["--demo", "autoswap", "add", "Daniels", "--dry-run", "--json"], capsys)
    data = json.loads(out)
    assert data["armed"] is False and data["dry_run"] and data["until"] == "2026-11-08"
    code, _, err = run(["--demo", "autoswap", "add", "Dyson Daniels", "--yes"], capsys)
    assert code == 1 and "press u" in " ".join(err.split())


def test_add_asks_and_yes_arms(live, capsys):
    code, out, err = run(["autoswap", "add", "Dyson Daniels", "--json"], capsys)
    assert code == 10 and json.loads(out)["armed"] is False and "NOT DONE" in err
    assert MarkStore(live).load().marks == {}
    code, _, _ = run(["autoswap", "add", "Dyson Daniels"], capsys)  # no terminal: not armed
    assert code == 10 and MarkStore(live).load().marks == {}
    code, out, _ = run(["autoswap", "add", "Dyson Daniels", "--yes", "--today"], capsys)
    assert code == 0 and "Armed Dyson Daniels" in out
    (mark,) = MarkStore(live).load().marks.values()
    assert mark.mode == "auto" and mark.until == live.today.isoformat() and mark.origin == "cli"
    assert [r["event"] for r in lineup_log.read_local(live)] == ["arm"]


def test_the_question_names_who_goes_to_the_bench(live, monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli.Console, "input", lambda self, q: asked.append(q) or "y")
    code, _, _ = run(["autoswap", "add", "Dyson Daniels"], capsys)
    assert code == 0 and MarkStore(live).load().auto_ids()
    (question,) = asked
    assert "Arm auto-swap for Dyson Daniels?" in question
    assert "benches Scotty Pippen Jr." in question


def test_notify_only_needs_no_question(live, capsys):
    code, out, _ = run(["autoswap", "add", "Coby White", "--notify-only"], capsys)
    assert code == 0 and "Alert on for Coby White" in out
    assert MarkStore(live).load().notify_ids()


def test_ir_and_strangers_cannot_be_armed(live, capsys):
    harris = next(sp for sp in live.league().me.roster if sp.player.name == "Tobias Harris")
    harris.slot_id = IR
    code, _, err = run(["autoswap", "add", "Tobias Harris", "--yes"], capsys)
    assert code == 1 and "on IR" in err
    code, _, err = run(["autoswap", "add", "Nikola Jokić", "--yes"], capsys)
    assert code == 1 and "your roster" in err


def test_remove_clear_pause_resume_and_log(live, capsys):
    run(["autoswap", "add", "Dyson Daniels", "--yes"], capsys)
    run(["autoswap", "add", "Coby White", "--notify-only"], capsys)
    code, out, _ = run(["autoswap", "remove", "daniels", "--json"], capsys)
    assert code == 0 and json.loads(out) == {"player": "Dyson Daniels",
                                             "player_id": json.loads(out)["player_id"],
                                             "removed": True}
    code, out, _ = run(["autoswap", "remove", "Coby White"], capsys)
    assert "Auto-swap is off for Coby White." in out
    run(["autoswap", "add", "Dyson Daniels", "--yes"], capsys)
    code, out, _ = run(["autoswap", "clear"], capsys)
    assert "Took 1 mark off." in out
    code, out, _ = run(["autoswap", "pause"], capsys)
    assert code == 0 and "paused" in out and MarkStore(live).load().paused
    code, out, _ = run(["autoswap", "resume", "--json"], capsys)
    assert json.loads(out) == {"paused": False}
    code, out, _ = run(["autoswap", "log", "--json", "-n", "3"], capsys)
    assert [r["event"] for r in json.loads(out)] == ["disarm", "pause", "resume"]
    code, out, _ = run(["autoswap", "log"], capsys)
    assert code == 0 and "resumed" in out


@pytest.mark.parametrize("argv", [
    ["--demo", "autoswap", "list", "Dyson Daniels"],
    ["--demo", "autoswap", "add"],
    ["--demo", "autoswap", "remove"],
    ["--demo", "autoswap", "pause", "--today"],
    ["--demo", "autoswap", "clear", "--dry-run"],
])
def test_bad_autoswap_usage_exits_2(argv, capsys):
    code, _, _ = run(argv, capsys)
    assert code == 2

"""Regression tests for the 1.0.1 fixes in the CLI, config and setup (all offline, demo data)."""

import argparse
import datetime as dt
import io
import json
import sys
import types

import pytest

from benchboss import cli, credentials, inbox
from benchboss import config as config_mod
from benchboss import demo as demo_mod
from benchboss import setup as setup_mod
from benchboss.cli import build_parser, main
from benchboss.demo import DemoClient
from benchboss.errors import AuthError, BenchbossError
from benchboss.service import Session


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    """Never reach the real keychain from these tests."""
    monkeypatch.setattr(credentials, "_keyring", lambda: None)


def flat(text: str) -> str:
    """Rich wraps long lines; compare messages with the line breaks taken out."""
    return " ".join(text.split())


def run(capsys, *args):
    main(list(args))
    return capsys.readouterr().out


def exit_code(*args) -> int:
    with pytest.raises(SystemExit) as e:
        main(list(args))
    return e.value.code


def espn_answers(monkeypatch, *answers):
    """Make the demo client answer writes in order: a dict, or an exception to raise."""
    sent = []
    queue = list(answers)

    def transaction(self, body):
        sent.append(body)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(DemoClient, "transaction", transaction)
    return sent


# --- F12 / F21: a FAILED_* status is a failed write -----------------------------------------------

def test_drop_with_failed_status_exits_4(monkeypatch, capsys):
    espn_answers(monkeypatch, {"status": "FAILED_ROSTERLOCK"})
    assert exit_code("--demo", "--yes", "drop", "Coby White") == 4
    out = capsys.readouterr()
    assert "ESPN: FAILED_ROSTERLOCK" in out.out
    assert "FAILED_ROSTERLOCK" in out.err


def test_add_with_failed_status_exits_4(monkeypatch, capsys):
    espn_answers(monkeypatch, {"status": "FAILED_UNDROPPABLEPLAYER"})
    fa = demo_mod.load()["free_agents"][0]["player"]["fullName"]
    assert exit_code("--demo", "--yes", "add", fa, "--drop", "Coby White") == 4
    assert "FAILED_UNDROPPABLEPLAYER" in capsys.readouterr().out


def test_executed_write_exits_0(monkeypatch, capsys):
    espn_answers(monkeypatch, {"status": "EXECUTED"})
    assert "ESPN: EXECUTED" in run(capsys, "--demo", "--yes", "drop", "Coby White")


# --- F20 / F14: writes keep the --json contract ---------------------------------------------------

def test_optimize_json_without_yes_is_not_confirmed(capsys):
    assert exit_code("--demo", "--json", "optimize", "week") == 10
    plan = json.loads(capsys.readouterr().out)
    assert any(day["moves"] for day in plan)


def test_optimize_json_dry_run_exits_0(capsys):
    plan = json.loads(run(capsys, "--demo", "--json", "optimize", "week", "--dry-run"))
    assert {"date", "moves", "projected"} <= set(plan[0])


def test_optimize_json_yes_prints_json_results(monkeypatch, capsys):
    espn_answers(monkeypatch, {"status": "EXECUTED"})
    days = json.loads(run(capsys, "--demo", "--json", "--yes", "optimize", "week"))
    assert {d["status"] for d in days} == {"EXECUTED", "ALREADY_OPTIMAL"}
    assert all(d["error"] is None for d in days)


def test_optimize_json_yes_failure_is_still_json(capsys):
    assert exit_code("--demo", "--json", "--yes", "optimize", "week") == 4
    days = json.loads(capsys.readouterr().out)
    assert any(d["error"] for d in days)


def test_write_json_without_yes_is_not_confirmed(capsys):
    assert exit_code("--demo", "--json", "drop", "Coby White") == 10
    data = json.loads(capsys.readouterr().out)
    assert data["sent"] is False and data["summary"] == "Drop: Coby White"


def test_write_json_dry_run_and_failure(monkeypatch, capsys):
    data = json.loads(run(capsys, "--demo", "--json", "drop", "Coby White", "--dry-run"))
    assert data["dry_run"] is True and data["sent"] is False
    espn_answers(monkeypatch, {"status": "FAILED_ROSTERLOCK"})
    assert exit_code("--demo", "--json", "--yes", "drop", "Coby White") == 4
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "FAILED_ROSTERLOCK" and data["error"]


# --- F26 / F68 / F30: optimize messages -----------------------------------------------------------

def test_optimize_failure_message_when_nothing_was_set(capsys):
    assert exit_code("--demo", "--yes", "optimize", "week", "-q") == 4
    err = capsys.readouterr().err
    assert "nothing was changed" in flat(err) and "the others were sent" not in flat(err)


def test_optimize_failure_message_when_some_days_were_set(monkeypatch, capsys):
    espn_answers(monkeypatch, {"status": "EXECUTED"}, BenchbossError("ESPN 409: locked"))
    assert exit_code("--demo", "--yes", "optimize", "week", "-q") == 4
    assert "2 day(s) were not set; 1 other day(s) were set" in flat(capsys.readouterr().err)


def test_optimize_one_day_message_names_the_day(capsys):
    out = run(capsys, "--demo", "optimize", "11-08", "--dry-run", "-q")
    assert "already optimal for Sun Nov 8." in out
    assert "for day." not in out


def test_optimize_messages_after_apply(monkeypatch, capsys):
    espn_answers(monkeypatch, {"status": "EXECUTED"})
    assert "Your lineup for today is set: 6 moves." in run(capsys, "--demo", "--yes", "optimize", "today", "-q")
    assert "Your week is set:" in run(capsys, "--demo", "--yes", "optimize", "week", "-q")


# --- F5 / F19: nobody plays "today" before or after the season ------------------------------------

@pytest.mark.parametrize("when", ["preseason", "after"])
def test_roster_plays_today_only_in_season(monkeypatch, capsys, when):
    real = demo_mod.demo_session

    def shifted(cfg=None):
        s = real(cfg)
        cal = s.calendar
        s._today = (cal.date_of(1) - dt.timedelta(days=5) if when == "preseason"
                    else cal.date_of(cal.final_period) + dt.timedelta(days=3))
        s._now = dt.datetime.combine(s._today, dt.time(12), tzinfo=dt.timezone(dt.timedelta(hours=-5)))
        return s

    monkeypatch.setattr(demo_mod, "demo_session", shifted)
    rows = json.loads(run(capsys, "--demo", "--json", "roster"))
    assert rows and not any(r["plays_today"] for r in rows)


def test_roster_plays_today_in_season(capsys):
    rows = json.loads(run(capsys, "--demo", "--json", "roster"))
    assert any(r["plays_today"] for r in rows)


# --- F25: a console that cannot show every character does not crash -------------------------------

def test_cp1252_stdout_does_not_crash(monkeypatch):
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    main(["--demo", "roster"])
    out.flush()
    assert b"Monstars" in raw.getvalue()


# --- F24: no app without a terminal ---------------------------------------------------------------

@pytest.mark.parametrize("args", [[], ["--demo"], ["--json"], ["app", "--demo"]])
def test_app_without_a_terminal_is_a_usage_error(capsys, args):
    assert exit_code(*args) == 2
    assert "benchboss" in capsys.readouterr().err


# --- F28 / F48: friendly errors instead of tracebacks ---------------------------------------------

def test_login_without_input_is_cancelled(monkeypatch, capsys):
    def no_input(prompt=""):
        raise EOFError

    monkeypatch.setattr("getpass.getpass", no_input)
    assert exit_code("login", "--manual") == 130
    assert "cancelled" in capsys.readouterr().err


def test_bad_number_in_env_is_a_config_error(monkeypatch, capsys):
    monkeypatch.setenv("BENCHBOSS_TEAM_ID", "abc")
    assert exit_code("status", "--offline") == 1
    assert "BENCHBOSS_TEAM_ID must be a whole number" in flat(capsys.readouterr().err)


def test_config_that_is_not_an_object(capsys):
    path = config_mod.Config().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]")
    assert exit_code("status", "--offline") == 1
    assert "must hold a JSON object" in flat(capsys.readouterr().err)
    # the demo league does not need the config at all
    assert json.loads(run(capsys, "--demo", "--json", "standings"))


# --- F67 / F27: status and account commands -------------------------------------------------------

def test_demo_never_touches_the_account(monkeypatch, capsys):
    def touched(*a, **k):
        raise AssertionError("the real account was touched")

    for name in ("get", "require", "store", "clear", "from_chrome"):
        monkeypatch.setattr(credentials, name, touched)
    monkeypatch.setattr(config_mod, "save", touched)
    for args in (["logout"], ["login", "--manual"], ["login", "--chrome"], ["setup"]):
        assert exit_code("--demo", *args) == 1
        assert "demo mode" in capsys.readouterr().err
    path = config_mod.Config().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"league_id": 999, "team_id": 4}))
    data = json.loads(run(capsys, "--demo", "--json", "status"))
    assert data["demo"] is True and data["config"] is None
    assert data["league_id"] == demo_mod.load()["league"]["id"]


def test_status_json_keeps_the_connection_error(monkeypatch, capsys):
    monkeypatch.setattr(credentials, "get", lambda: ("s2", "{SWID}"))
    monkeypatch.setenv("BENCHBOSS_LEAGUE_ID", "12345")

    def expired(self, refresh=False):
        raise AuthError("ESPN 401: cookies expired")

    monkeypatch.setattr(Session, "league", expired)
    data = json.loads(run(capsys, "--json", "status"))
    assert data["connected"] is False
    assert data["error_code"] == 3 and "expired" in data["error"]


# --- F18: an empty chat message is never posted ---------------------------------------------------

def test_whitespace_chat_message_is_refused(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(inbox, "send", lambda *a, **k: sent.append(a) or "sent")
    assert exit_code("--demo", "--yes", "chat", "   ") == 1
    assert "empty" in capsys.readouterr().err
    assert not sent


# --- F30: trade partner matching and help text ----------------------------------------------------

def test_trades_with_own_team_is_an_error(capsys):
    assert exit_code("--demo", "trades", "--with", "Monstars") == 1
    assert "your own team" in capsys.readouterr().err


def test_trades_with_ambiguous_name_lists_teams(capsys):
    assert exit_code("--demo", "trades", "--with", "r") == 1
    err = capsys.readouterr().err
    assert "matches several teams" in flat(err) and "Monstars" not in err


def test_every_option_has_help():
    ap = build_parser()
    sub = next(a for a in ap._actions if isinstance(a, argparse._SubParsersAction))
    for name, p in sub.choices.items():
        for a in p._actions:
            assert a.help, f"{name} {a.dest} has no help text"


# --- F72: counts must be 1 or more ----------------------------------------------------------------

@pytest.mark.parametrize("args", [["trash", "-n", "0"], ["fa", "-n", "-3"], ["trending", "-n", "x"],
                                  ["trades", "-n", "0"], ["chat", "-n", "0"], ["news", "--days", "0"]])
def test_counts_must_be_positive(capsys, args):
    assert exit_code("--demo", *args) == 2


# --- F41: the watch view says when the dashboard does not fit -------------------------------------

def test_fit_height_cuts_and_says_more_below(session):
    from rich.console import Console
    from rich.text import Text

    from benchboss.ui import dashboard
    from benchboss.ui.theme import palette

    pal = palette("dark")
    con = Console(width=46, height=30, file=io.StringIO())
    board = dashboard.render(dashboard.collect(session), pal, 46)
    lines = con.render_lines(cli._fit_height(con, board, 30, pal), con.options, pad=False)
    assert len(lines) <= 30
    assert "more below" in "".join(seg.text for seg in lines[-1])
    small = Text("fits")
    assert cli._fit_height(con, small, 30, pal) is small


# --- F16 / F17 / F51: setup -------------------------------------------------------------------------

class FakeClient:
    def __init__(self, league_id, season, cookies):
        self.season = season

    def league(self, *views):
        return demo_mod.load()["league"]


@pytest.fixture
def wizard(monkeypatch):
    """Run `benchboss setup` with scripted answers and a fake ESPN; returns the prompts asked."""
    asked = []
    state = {"answers": iter(())}

    def ask(c, prompt, default=""):
        asked.append(prompt)
        return next(state["answers"]) or default

    monkeypatch.setattr(setup_mod, "_ask", ask)
    monkeypatch.setattr(setup_mod, "Client", FakeClient)
    monkeypatch.setattr(config_mod, "current_season", lambda today=None: 2027)
    monkeypatch.setattr(credentials, "get", lambda: ("s2", "{NOT-AN-OWNER}"))

    def start(answers, leagues=()):
        state["answers"] = iter(answers)
        monkeypatch.setattr(setup_mod, "discover", lambda cookies: list(leagues))
        main(["setup"])
        return json.loads(config_mod.Config().path.read_text())

    start.asked = asked
    return start


def test_setup_asks_again_for_a_bad_league_number(wizard):
    leagues = [{"league_id": 424242, "league_name": "A", "team_id": 1, "season": 2027},
               {"league_id": 424242, "league_name": "B", "team_id": 2, "season": 2027}]
    cfg = wizard(["B", "7", "2", "d"], leagues)
    assert wizard.asked.count("Which one?") == 3
    assert cfg["team_id"] == 2
    assert cfg["season"] is None  # the current season is not pinned (F17)


def test_setup_asks_again_for_a_bad_team(wizard):
    cfg = wizard(["424242", "Monstars", "99", "3", "l"])
    assert wizard.asked.count("Which team is yours (number)?") == 3
    assert cfg["team_id"] == 3 and cfg["theme"] == "light"


def test_setup_pins_an_older_season_and_says_so(wizard, monkeypatch, capsys):
    monkeypatch.setattr(config_mod, "current_season", lambda today=None: 2028)
    cfg = wizard(["d"], [{"league_id": 424242, "league_name": "A", "team_id": 1, "season": 2027}])
    assert cfg["season"] == 2027
    assert "2026-27 season" in flat(capsys.readouterr().out)


def test_setup_falls_back_to_paste_when_chrome_fails(wizard, monkeypatch, capsys):
    stored = []
    monkeypatch.setattr(setup_mod, "sys", types.SimpleNamespace(platform="darwin", stdin=sys.stdin))
    monkeypatch.setattr(credentials, "get", lambda: None)

    def no_chrome():
        raise AuthError("no ESPN session found in Chrome")

    monkeypatch.setattr(credentials, "from_chrome", no_chrome)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": {"espn_s2: ": "s2", "SWID: ": "{S}"}[prompt])
    monkeypatch.setattr(credentials, "store", lambda s2, swid: stored.append((s2, swid)) or "a test store")
    monkeypatch.setattr(credentials, "require", lambda: ("s2", "{S}"))
    cfg = wizard(["c", "d"], [{"league_id": 424242, "league_name": "A", "team_id": 1, "season": 2027}])
    assert stored == [("s2", "{S}")]
    assert "Paste them instead" in flat(capsys.readouterr().out)
    assert cfg["team_id"] == 1

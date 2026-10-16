"""Regression tests for the 1.0.2 audit: privacy, safety and repo hygiene.

The demo is frozen and writes nothing (no seen-news.json, nothing "sent" by `watch`), the
docs and agent files say what 1.0.2 writes and keeps, and the watch list keeps ESPN's cap.
"""

import asyncio
import contextlib
import io
import json
import re
from pathlib import Path

import pytest

import benchboss
from benchboss import config as config_mod
from benchboss import inbox
from benchboss.cli import build_parser, main
from benchboss.config import Config
from benchboss.demo import REFUSED, DemoClient, demo_session
from benchboss.errors import BenchbossError
from benchboss.service import WATCH_LIST_MAX
from benchboss.ui.app import Benchboss

ROOT = Path(__file__).resolve().parents[1]
SPINS = ["Egor Demin", "Dereck Lively II"]  # the two watch-list players with demo news


def repo_text(rel: str) -> str:
    """A file from the repository; tests that need one skip when run from an sdist."""
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} is not part of this checkout")
    return path.read_text(encoding="utf-8")


def run(capsys, *args) -> str:
    main(list(args))
    return capsys.readouterr().out


def exit_code(*args) -> int:
    with pytest.raises(SystemExit) as e:
        main(list(args))
    return e.value.code


def seen_file() -> Path:
    return config_mod.config_dir() / inbox.SEEN_FILE


# --- privacy-2: the demo keeps the seen news in memory --------------------------------------------

def test_demo_spins_are_seen_once_per_session_and_never_saved():
    s = demo_session()
    assert [who for who, _ in inbox.watch_spins(s, mark_seen=True)] == SPINS
    assert inbox.watch_spins(s, mark_seen=True) == []  # this session remembers them
    assert not config_mod.config_dir().exists()        # nothing written, not even the folder
    again = demo_session()                              # the next run of the frozen demo
    assert [who for who, _ in inbox.watch_spins(again)] == SPINS


def test_demo_app_toasts_the_spins_on_every_run_and_writes_nothing():
    toasts = []

    def run_app():
        app = Benchboss(Config(), demo=True)
        app.notify = lambda message, **kw: toasts.append(message)

        async def go():
            async with app.run_test(size=(140, 44)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                for _ in range(2):  # the second check of the same run finds nothing new
                    app.check_spins()
                    await app.workers.wait_for_complete()
                    await pilot.pause()

        asyncio.run(go())

    run_app()
    assert [t.split(":")[0] for t in toasts] == SPINS
    run_app()
    assert [t.split(":")[0] for t in toasts] == SPINS * 2
    assert not seen_file().exists()


def test_demo_alerts_mark_read_says_it_is_not_saved(capsys):
    out = run(capsys, "--demo", "alerts", "--mark-read")
    assert "Marked 2 watch list items as read." in out
    assert "Demo mode does not save it" in out
    assert not seen_file().exists()
    assert "Watch list · Egor Demin" in run(capsys, "--demo", "alerts")  # still there
    data = json.loads(run(capsys, "--demo", "--json", "alerts", "--mark-read"))
    assert len([a for a in data if a["kind"] == "spin"]) == 2
    assert not seen_file().exists()


def test_a_real_session_still_saves_what_was_seen(session, monkeypatch):
    session.seen_news = None  # the demo data, kept on disk like a real league
    assert len(inbox.watch_spins(session, mark_seen=True)) == 2
    assert len(json.loads(seen_file().read_text())[str(session.client.league_id)]["news"]) == 2
    again = demo_session()
    again.seen_news = None
    assert inbox.watch_spins(again) == []  # the next run reads the file


# --- privacy-5: `--demo watch add/remove --yes` is refused like every other demo write -----------

def test_demo_watch_add_yes_is_refused_and_sends_nothing(capsys, monkeypatch):
    def sent(self, team_id, body):
        raise AssertionError("the CLI must not hand a demo write to the client")

    monkeypatch.setattr(DemoClient, "update_team", sent)
    assert exit_code("--demo", "watch", "add", "Jokic", "--yes") == 1
    out = capsys.readouterr()
    assert "watch list" in out.out and REFUSED in out.err and "ESPN:" not in out.out
    assert exit_code("--demo", "--json", "watch", "remove", "Egor Demin", "--yes") == 1
    data = json.loads(capsys.readouterr().out)
    assert data["sent"] is False and data["status"] is None and data["error"] == REFUSED
    # same as the other writes in the demo
    assert exit_code("--demo", "--json", "drop", "Coby White", "--yes") == 1
    assert json.loads(capsys.readouterr().out)["error"] == REFUSED


def test_demo_watch_preview_and_unconfirmed_runs_are_unchanged(capsys):
    data = json.loads(run(capsys, "--demo", "--json", "watch", "add", "Jokic", "--dry-run"))
    assert data["dry_run"] is True and data["sent"] is False and "Jokic" in data["summary"]
    out = run(capsys, "--demo", "watch", "add", "Jokic")
    assert "demo mode: nothing is sent to ESPN" in out and "ESPN:" not in out
    assert len(json.loads(run(capsys, "--demo", "--json", "watch"))) == 4


def test_the_demo_app_star_still_works_in_memory():
    """The finder's star in the demo goes through the session, not the CLI refusal."""
    s = demo_session()
    pid = s.data["free_agents"][7]["id"]
    assert pid in s.set_watched(pid, True)
    assert pid not in s.set_watched(pid, False)


# --- hygiene-2: ESPN's cap of 50 watch-list players -----------------------------------------------

def test_a_51st_watch_list_player_is_refused_before_anything_is_sent(monkeypatch):
    s = demo_session()
    me = next(t for t in s.data["league"]["teams"] if t["id"] == s.data["my_team_id"])
    full = list(range(1, WATCH_LIST_MAX + 1))
    me["watchList"] = list(full)  # the list as ESPN has it now (another client filled it)
    pid = s.data["free_agents"][7]["id"]
    real = DemoClient.update_team
    monkeypatch.setattr(DemoClient, "update_team",
                        lambda self, *a: pytest.fail("a 51st player was sent"))
    with pytest.raises(BenchbossError, match=f"full .*{WATCH_LIST_MAX}"):
        s.set_watched(pid, True)
    assert s.watch_list() == tuple(full)  # the fresh list, unchanged
    monkeypatch.setattr(DemoClient, "update_team", real)
    assert len(s.set_watched(1, False)) == WATCH_LIST_MAX - 1  # taking one off still works
    assert pid in s.set_watched(pid, True)                     # and then there is room


def test_espn_web_app_cap_is_the_one_documented():
    text = repo_text("docs/api/04-writes-transactions.md")
    assert "maxWatchListPlayers" in text and f"`{WATCH_LIST_MAX}`" in text


# --- hygiene-2: the new endpoint and field are documented ------------------------------------------

def test_watch_list_endpoint_is_in_the_api_reference():
    writes = repo_text("docs/api/04-writes-transactions.md")
    assert "## 13. Watch list" in writes
    assert "{WRITES}/teams/{teamId}" in writes and '{"watchList": [' in writes
    index = repo_text("docs/api/README.md")
    assert '`{W}/teams/{teamId}` with `{"watchList": [ids]}`' in index
    assert "04-writes-transactions.md#13-watch-list-post-teamsteamid" in index
    assert "`teams[].watchList`" in repo_text("docs/api/01-league-views.md")


# --- privacy-3 / hygiene-1: what 1.0.2 writes and keeps is in the docs and the changelog -----------

def test_readme_privacy_section_names_the_watch_list_exception():
    text = repo_text("README.md")
    section = text.split("## Privacy and safety", 1)[1].split("\n## ", 1)[0]
    assert "Demo mode cannot write at all" not in section
    assert "watch list" in section and "benchboss watch add|remove" in section
    assert inbox.SEEN_FILE in section


def test_configuration_doc_lists_the_seen_news_file():
    text = repo_text("docs/configuration.md")
    assert "keeps two things" not in text
    files = text.split("## Files", 1)[1].split("\n## ", 1)[0]
    assert f"`{inbox.SEEN_FILE}`" in files and f"{inbox.SEEN_KEEP}" in files


def test_changelog_describes_the_release():
    text = repo_text("CHANGELOG.md")
    entry = text.split(f"## [{benchboss.__version__}]", 1)[1].split("\n## [", 1)[0]
    assert "Work in progress" not in entry
    assert "### Added" in entry and "### Changed" in entry
    for needle in (inbox.SEEN_FILE, "benchboss watch add|remove", "without", "--mark-read",
                   "benchboss players", "benchboss playoffs"):
        assert needle in entry, needle
    assert "\u2014" not in entry and "\u2013" not in entry


# --- privacy-4: agent instructions and VS Code auto-approve know the 1.0.2 commands --------------

def _auto_approve():
    raw = repo_text(".vscode/settings.json")
    rules = json.loads("\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("//")))
    compiled = [(re.compile(key[1:-1]), value)
                for key, value in rules["chat.tools.terminal.autoApprove"].items()]

    def auto(cmd: str) -> bool:
        hits = [value for rx, value in compiled if rx.search(cmd)]
        return bool(hits) and all(hits)  # a false rule always wins

    return auto


@pytest.mark.parametrize("cmd", [
    "benchboss players --json",
    "benchboss players --json --from watch --pos C -n 10",
    "benchboss playoffs --json",
    'benchboss playoffs --json --pick "Monstars>Tune Squad@12"',
    "benchboss watch",
    "benchboss watch --json",
    "benchboss watch list --json",
    "benchboss news --watch --json",
    "benchboss news --json --watch --days 3",
    "benchboss alerts --json",
    'benchboss watch add "Egor Demin" --dry-run',
    'benchboss watch remove "Egor Demin" --json --dry-run',
])
def test_vscode_auto_approves_the_new_reads_and_previews(cmd):
    assert _auto_approve()(cmd)


@pytest.mark.parametrize("cmd", [
    "benchboss alerts --mark-read",
    "benchboss alerts --json --mark-read",
    'benchboss watch add "Egor Demin"',
    'benchboss watch add "Egor Demin" --yes',
    'benchboss watch remove "Egor Demin" -y',
    'benchboss watch add "Egor Demin" --dry-run --yes',
    "benchboss dash --watch",
    "benchboss dash --json --watch 30",
    "benchboss dash --wat",
])
def test_vscode_asks_for_watch_writes_mark_read_and_the_live_dashboard(cmd):
    assert not _auto_approve()(cmd)


def test_vscode_asks_for_every_spelling_of_mark_read():
    auto = _auto_approve()
    option = "--mark-read"
    for spelling in [option[:k] for k in range(3, len(option) + 1)]:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                args = build_parser().parse_args(["alerts", spelling])
        except SystemExit:
            continue  # the parser refuses this spelling, so it cannot run anything
        if args.mark_read:
            assert not auto(f"benchboss alerts {spelling}"), spelling


def test_agent_files_list_the_watch_list_write():
    agents = repo_text("AGENTS.md")
    writes = agents.split("### Writes need", 1)[1].split("### Exit codes", 1)[0]
    assert '`benchboss watch add "Player" --yes`' in writes
    assert '`benchboss watch remove "Player" --yes`' in writes
    reads = agents.split("### Always use `--json`", 1)[1].split("### Writes need", 1)[0]
    for cmd in ("players", "watch", "playoffs", "news"):
        assert f"`benchboss {cmd} --json" in reads, cmd
    assert "`benchboss alerts --mark-read` only when the user asks" in reads
    copilot = repo_text(".github/copilot-instructions.md")
    assert '`watch add "Player"`' in copilot and '`watch remove "Player"`' in copilot
    assert "`players`" in copilot and "`playoffs`" in copilot and "--mark-read" in copilot
    assert "`watch add`" in repo_text(".github/agents/benchboss.agent.md")


def test_every_command_is_in_agents_md():
    """A new command must be classified for agents (a read or a write)."""
    agents = repo_text("AGENTS.md")
    sub = next(a for a in build_parser()._actions if a.dest == "cmd")
    human_only = {"app", "setup", "login", "logout", "doctor"}  # interactive or account
    missing = [c for c in sub.choices if c not in human_only and f"benchboss {c}" not in agents]
    assert not missing

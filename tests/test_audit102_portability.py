"""Regression tests for the 1.0.2 audit: portability, packaging and tests."""

import argparse
import ast
import asyncio
import importlib.util
import json
import re
import threading
from pathlib import Path

import pytest

from benchboss import credentials
from benchboss.cli import build_parser, main
from benchboss.config import Config
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import playoffs

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
REAL_KEYRING = credentials._keyring  # conftest swaps it out before every test


def repo_file(rel: str) -> Path:
    """A file from the repository; tests that need one skip when run from an sdist."""
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} is not part of this checkout")
    return path


# --- tests run from the sdist -------------------------------------------------------------------

def sdist_tops() -> set[str]:
    """The top-level files and folders the sdist ships: pyproject's include list, and
    pyproject.toml itself (hatchling always adds it)."""
    text = repo_file("pyproject.toml").read_text(encoding="utf-8")
    block = text.split("[tool.hatch.build.targets.sdist]", 1)[1].split("\n[", 1)[0]
    include = re.search(r"include\s*=\s*\[(.*?)\]", block, flags=re.S)[1]
    return {path.split("/")[0] for path in re.findall(r'"([^"]+)"', include)} | {"pyproject.toml"}


def test_tests_read_files_the_sdist_leaves_out_only_through_repo_file():
    shipped = sdist_tops()
    assert {"src", "tests"} <= shipped and "tools" not in shipped and "docs" not in shipped
    for path in sorted(TESTS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                    and isinstance(node.left, ast.Name) and node.left.id == "ROOT"
                    and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)):
                top = node.right.value.split("/")[0]
                assert top in shipped, (f"{path.name}:{node.lineno} reads {top}/, which the sdist "
                                        "does not ship: use repo_file()")


def test_the_logo_test_skips_where_tools_and_docs_are_missing(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("sdist_dashboard_plan",
                                                  TESTS / "test_dashboard_plan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)  # an unpacked sdist: no tools/, no docs/
    with pytest.raises(pytest.skip.Exception, match="not part of this checkout"):
        module.test_make_logo_writes_the_committed_png()


# --- the scenario builder on a slow machine -----------------------------------------------------

async def settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def in_the_builder(scenario):
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(140, 44)) as pilot:
            await settle(pilot)
            await pilot.press("y")
            await settle(pilot)
            await scenario(app, pilot, app.query_one(playoffs.PlayoffBuilder))

    asyncio.run(run())


def status_of(app) -> str:
    return str(app.query_one("#status").content)


def test_the_builder_status_line_is_in_place_when_it_mounts():
    """The app writes its own status line right after it mounts the builder; the builder's
    Mount handler replaces it at once instead of after a later refresh, which a busy CI runner
    may not have drawn yet when the test (or the user) looks."""

    async def scenario(app, pilot, builder):
        assert "Scenario builder" in status_of(app)
        app._status_views()  # the line the app leaves on the bar before Mount runs
        assert "Scenario builder" not in status_of(app)
        builder.on_mount()
        assert "Scenario builder" in status_of(app)

    in_the_builder(scenario)


def test_the_builder_says_simulating_until_the_race_is_back(monkeypatch):
    """The simulation waits on an event the test holds, so "simulating..." is checked while it
    runs however slow the machine is (a fast run used to finish before the test looked)."""
    gate = threading.Event()

    async def scenario(app, pilot, builder):
        race = builder.session.playoff_race

        def held(*args, **kwargs):
            gate.wait(30)
            return race(*args, **kwargs)

        monkeypatch.setattr(builder.session, "playoff_race", held)
        try:
            await pilot.press("right")
            assert builder.busy
            assert "simulating..." in builder._draw_head(builder.pal, 140, 1).plain
        finally:
            gate.set()
        await settle(pilot)
        assert not builder.busy
        assert "simulating..." not in builder._draw_head(builder.pal, 140, 1).plain
        assert builder.picks and builder.race.picks == builder.picks

    in_the_builder(scenario)


# --- the keychain stays out of the test run -----------------------------------------------------

def test_status_never_reaches_the_os_keychain(monkeypatch, capsys):
    import keyring

    calls = []
    for name in ("get_keyring", "get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, lambda *a, _name=name, **k: calls.append(_name))
    main(["status", "--offline"])
    assert "cookies" in capsys.readouterr().out
    assert calls == []


def test_the_real_lookup_still_treats_the_null_backend_as_no_keychain(monkeypatch):
    """conftest stubs credentials._keyring for every test; the real one still has to say "no
    keychain" for keyring's null backend, so the cookies go to the 0600 file instead."""
    import keyring.core

    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    monkeypatch.setattr(keyring.core, "_keyring_backend", None)  # pick up the env var
    assert REAL_KEYRING() is None


# --- release notes and agent docs ---------------------------------------------------------------

FOR_HUMANS = {"app", "setup", "login", "logout", "doctor"}  # interactive or account commands


def commands() -> dict[str, argparse.ArgumentParser]:
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return dict(sub.choices)


def test_the_newest_changelog_entry_has_release_notes():
    text = repo_file("CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.split(r"^## ", text, flags=re.M)[1]
    assert "work in progress" not in newest.lower()
    assert re.search(r"^### Added$", newest, flags=re.M)


def test_agent_docs_and_readme_list_every_command_and_every_write():
    agents = repo_file("AGENTS.md").read_text(encoding="utf-8")
    copilot = repo_file(".github/copilot-instructions.md").read_text(encoding="utf-8")
    readme = repo_file("README.md").read_text(encoding="utf-8")
    agents_writes = agents.split("### Writes need", 1)[1].split("### Exit codes", 1)[0]
    copilot_writes = copilot.split("- Writes change the real league", 1)[1].split("\n- ", 1)[0]
    for name, parser in commands().items():
        if name in FOR_HUMANS:
            continue
        cli, word = rf"benchboss {name}\b", rf"`{name}\b"
        assert re.search(cli, agents), f"AGENTS.md does not mention benchboss {name}"
        assert re.search(word, copilot), f"copilot-instructions.md does not mention {name}"
        assert re.search(cli, readme) or re.search(word, readme), f"README misses {name}"
        if "--dry-run" in parser._option_string_actions:  # a write
            assert re.search(cli, agents_writes), f"AGENTS.md: {name} is not in the writes table"
            assert re.search(word, copilot_writes), f"copilot-instructions.md: {name} is a write"


def auto_approved(cmd: str) -> bool:
    """What the repo's VS Code settings let Copilot run without asking (a false rule wins)."""
    raw = repo_file(".vscode/settings.json").read_text(encoding="utf-8")
    rules = json.loads("\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("//")))
    hits = [value for key, value in rules["chat.tools.terminal.autoApprove"].items()
            if re.search(key[1:-1], cmd)]
    return bool(hits) and all(hits)


@pytest.mark.parametrize("cmd, auto", [
    ("benchboss players --json --from watch --pos C", True),
    ('benchboss playoffs --json --pick "Monstars>Tune Squad@5"', True),
    ("benchboss watch", True),
    ("benchboss watch list --json", True),
    ("benchboss alerts --json --mark-read", True),
    ('benchboss watch add "Egor Demin" --dry-run', True),
    ('benchboss watch remove "Egor Demin" --dry-run --json', True),
    ('benchboss watch add "Egor Demin"', False),
    ('benchboss watch remove "Egor Demin" --yes', False),
    ('benchboss watch add "Egor Demin" --dry-run -y', False),
])
def test_vscode_runs_the_new_reads_and_asks_for_watch_list_writes(cmd, auto):
    assert auto_approved(cmd) is auto

"""Regression tests for the 1.0.1 packaging, install and docs fixes."""

import contextlib
import io
import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import benchboss
from benchboss.cli import build_parser, main
from benchboss.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]


def repo_file(rel: str) -> Path:
    """A file from the repository; tests that need one skip when run from an sdist."""
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} is not part of this checkout")
    return path


# --- release metadata ---------------------------------------------------------------------------

def test_version_matches_the_changelog(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"benchboss {benchboss.__version__}"
    text = repo_file("CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^## \[([^\]]+)\]", text, flags=re.M)
    # the newest entry is the version the code reports; the first release is listed as 1.0.0
    assert versions[0] == benchboss.__version__
    assert "1.0.0" in versions and "0.1.0" not in versions
    assert "\u2014" not in text and "\u2013" not in text


def test_pyproject_metadata():
    text = repo_file("pyproject.toml").read_text(encoding="utf-8")
    assert "Development Status :: 5 - Production/Stable" in text
    # hatchling 1.25 fails on the PEP 639 license-files list; 1.27 is the safe floor
    floor = re.search(r'"hatchling>=(\d+)\.(\d+)', text)
    assert floor and (int(floor[1]), int(floor[2])) >= (1, 27)


# --- README install commands --------------------------------------------------------------------

def test_readme_install_commands_do_not_need_git():
    text = repo_file("README.md").read_text(encoding="utf-8")
    assert "git+https://" not in text
    assert "archive/refs/heads/main.zip" in text
    windows = text.split("**Windows** (PowerShell):", 1)[1].split("```", 2)[1]
    lines = [ln for ln in windows.splitlines() if ln.strip() and ln.strip() != "powershell"]
    path_line = next(i for i, ln in enumerate(lines) if ln.startswith("$env:Path"))
    install_line = next(i for i, ln in enumerate(lines) if ln.startswith("uv tool install"))
    assert path_line < install_line


# --- install.sh ---------------------------------------------------------------------------------

needs_sh = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"),
                              reason="install.sh is for macOS and Linux")


def _executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _run_installer(tmp_path: Path, curl_body: str, extra_env: dict | None = None,
                   piped: bool = False):
    if shutil.which("uv", path="/usr/bin:/bin"):
        pytest.skip("uv is installed system wide, so the installer would not download it")
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    _executable(bin_dir / "curl", curl_body)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", **(extra_env or {})}
    script = repo_file("install.sh")
    if piped:  # curl ... | sh: the script itself arrives on stdin
        return subprocess.run(["sh"], input=script.read_text(), env=env, capture_output=True,
                              text=True, timeout=60)
    return subprocess.run(["sh", str(script)], env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


@needs_sh
def test_install_sh_stops_when_uv_cannot_be_downloaded(tmp_path):
    r = _run_installer(tmp_path, "#!/bin/sh\necho 'curl: (6) Could not resolve host' >&2\nexit 6\n")
    assert r.returncode == 1
    assert "could not download uv" in r.stderr
    assert "Installing benchboss" not in r.stdout
    assert "not found" not in r.stderr


@needs_sh
@pytest.mark.parametrize("var, piped", [("UV_INSTALL_DIR", False), ("XDG_BIN_HOME", False),
                                        ("UV_INSTALL_DIR", True)])
def test_install_sh_finds_uv_in_a_custom_folder(tmp_path, var, piped):
    log = tmp_path / "uv.log"
    fake_uv = _executable(tmp_path / "fake-uv", f'#!/bin/sh\necho "$*" >> "{log}"\n')
    target = tmp_path / "custom-bin"
    # the downloaded "installer" puts uv in the folder the real one would use for this
    # variable; it also reads stdin, which must not swallow the rest of a piped install.sh
    installer = f'cat >/dev/null\nmkdir -p "{target}" && cp "{fake_uv}" "{target}/uv"\n'
    curl = ("#!/bin/sh\nout=''\nwhile [ $# -gt 0 ]; do\n"
            '  if [ "$1" = "-o" ]; then out="$2"; shift; fi\n  shift\ndone\n'
            f"cat > \"$out\" <<'EOF'\n{installer}EOF\n")
    r = _run_installer(tmp_path, curl, {var: str(target)}, piped=piped)
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines()
    install = next(c for c in calls if c.startswith("tool install"))
    assert "--python >=3.10" in install
    assert install.endswith("benchboss @ https://github.com/ValeQRamos/benchboss/archive/refs/heads/main.zip")


# --- bug reports must not ask for private data --------------------------------------------------

def test_bug_report_does_not_ask_for_status_output():
    template = repo_file(".github/ISSUE_TEMPLATE/bug_report.yml").read_text(encoding="utf-8")
    assert "label: benchboss status --offline" not in template
    assert "benchboss --version" in template
    assert "league id" in template
    contributing = repo_file("CONTRIBUTING.md").read_text(encoding="utf-8")
    reporting = contributing.split("## Reporting bugs", 1)[1].split("\n## ", 1)[0]
    assert "benchboss --version" in reporting
    assert "league id" in reporting


# --- configuration docs and a team id from another league ---------------------------------------

def test_configuration_doc_explains_a_saved_season():
    text = repo_file("docs/configuration.md").read_text(encoding="utf-8")
    assert "Leave it\n  out and benchboss picks the current season" not in text
    assert "never changes on its own" in text
    assert "override just the" not in text


def test_team_id_from_another_league_is_a_clear_error(session):
    session.cfg.team_id = 99  # not a team of the demo league
    with pytest.raises(ConfigError, match="team 99 is not in this league"):
        session.league(refresh=True)
    session.cfg.team_id = session.data["my_team_id"]
    assert session.league(refresh=True).me.id == session.data["my_team_id"]


# --- VS Code auto-approve rules -----------------------------------------------------------------

def _auto_approve():
    raw = repo_file(".vscode/settings.json").read_text(encoding="utf-8")
    rules = json.loads("\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("//")))
    rules = rules["chat.tools.terminal.autoApprove"]
    compiled = [(re.compile(key[1:-1]), value) for key, value in rules.items()]

    def auto(cmd: str) -> bool:
        hits = [value for rx, value in compiled if rx.search(cmd)]
        return bool(hits) and all(hits)  # a false rule always wins

    return auto


AUTO = [
    "benchboss status --json",
    "benchboss dash --json",
    "benchboss trash --json -n 10",
    "benchboss news --json --days 5",
    "benchboss news --json --watch --days 5",
    "benchboss trades --json --with Monstars",
    "benchboss chat --json",
    "benchboss chat --json --to Monstars",
    "benchboss chat -n 5",
    "benchboss optimize week --dry-run --json",
    'benchboss add "Egor Demin" --drop "Coby White" --dry-run',
    'benchboss drop "Coby White" --dry-run',
    'benchboss trade --give "A" --get "B" --msg "hi" --dry-run',
    'benchboss chat "good game" --dry-run',
]

ASK = [
    "benchboss",
    "benchboss app",
    "benchboss news --ai",
    "benchboss news --days 5 --ai",
    "benchboss dash --watch",
    "benchboss dash --watch 30",
    "benchboss optimize week",
    "benchboss optimize week --yes",
    "benchboss optimize week -y",
    "benchboss optimize week -qy",
    "benchboss optimize week --dry-run --yes",
    "benchboss optimize week --dry-run -y",
    'benchboss drop "Coby White" -y',
    'benchboss add "Egor Demin" --dry-run -y',
    'benchboss chat "good game"',
    'benchboss chat "good game" --yes',
    "benchboss login",
    "benchboss logout",
    "benchboss setup",
]


@pytest.mark.parametrize("cmd", AUTO)
def test_vscode_auto_approves_reads_and_previews(cmd):
    assert _auto_approve()(cmd)


@pytest.mark.parametrize("cmd", ASK)
def test_vscode_asks_for_writes_paid_and_endless_commands(cmd):
    assert not _auto_approve()(cmd)


@pytest.mark.parametrize("cmd, option, dest", [("optimize week", "--yes", "yes"),
                                               ("dash", "--watch", "watch"),
                                               ("news", "--ai", "ai")])
def test_vscode_asks_for_every_spelling_the_parser_accepts(cmd, option, dest):
    auto = _auto_approve()
    spellings = [option[:k] for k in range(3, len(option) + 1)]
    if dest == "yes":
        spellings += ["-y", "-qy", "-yq"]
    for spelling in spellings:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                args = build_parser().parse_args([*cmd.split(), spelling])
        except SystemExit:
            continue  # the parser refuses this spelling, so it cannot run anything
        if getattr(args, dest, None):
            assert not auto(f"benchboss {cmd} {spelling}"), spelling


def test_repo_text_has_no_long_dashes():
    for rel in ("README.md", "CONTRIBUTING.md", "AGENTS.md", "docs/configuration.md",
                "docs/vscode.md", "install.sh", ".vscode/settings.json",
                ".github/copilot-instructions.md", ".github/ISSUE_TEMPLATE/bug_report.yml"):
        path = ROOT / rel
        if path.exists():
            text = path.read_text(encoding="utf-8")
            assert "\u2014" not in text and "\u2013" not in text, rel


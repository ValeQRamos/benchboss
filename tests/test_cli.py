import json

import pytest

from benchboss.cli import main


def run(capsys, *args):
    main(list(args))
    return capsys.readouterr().out


@pytest.mark.parametrize("cmd", ["dash", "roster", "standings", "matchup", "activity", "trash",
                                 "trades", "alerts", "news", "fa", "trending"])
def test_read_commands_emit_json(capsys, cmd):
    data = json.loads(run(capsys, "--demo", "--json", cmd))
    assert data is not None


def test_flags_work_after_the_command(capsys):
    data = json.loads(run(capsys, "trash", "--demo", "--json", "-n", "3"))
    assert len(data) == 3


def test_optimize_dry_run_sends_nothing(capsys):
    out = run(capsys, "--demo", "optimize", "week", "--dry-run")
    assert "Wed Nov 4" in out


def test_demo_refuses_writes(capsys):
    with pytest.raises(SystemExit):
        main(["--demo", "--yes", "drop", "Scotty Pippen Jr."])
    assert "demo mode" in capsys.readouterr().err


def test_status_offline(capsys):
    out = run(capsys, "status", "--offline")
    assert "cookies" in out

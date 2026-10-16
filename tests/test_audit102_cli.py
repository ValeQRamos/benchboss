"""Regression tests for the 1.0.2 audit fixes: the CLI and its JSON contract.

All on the demo league (Wed 2026-11-04, week 3); nothing is sent to ESPN. Every test gets its
own BENCHBOSS_HOME (conftest).
"""

import argparse
import asyncio
import datetime as dt
import io
import json
import re
from pathlib import Path

import pytest
from rich.console import Console

from benchboss import config as config_mod
from benchboss import inbox
from benchboss.cli import build_parser, main
from benchboss.config import Config
from benchboss.core import playoffs as core
from benchboss.demo import demo_session
from benchboss.errors import BenchbossError
from benchboss.espn.constants import GP, PTS
from benchboss.espn.models import StatLine
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import playoffs
from benchboss.ui.theme import DARK

ROOT = Path(__file__).resolve().parents[1]


def run(capsys, *args) -> str:
    main(list(args))
    return capsys.readouterr().out


def text_of(renderable, width: int = 120) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def repo_file(rel: str) -> Path:
    """A file from the repository; tests that need one skip when run from an sdist."""
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} is not part of this checkout")
    return path


# --- cli-1: activity --json keeps the 1.0.1 keys and agrees with dash --json ----------------------

def test_activity_json_keeps_the_101_shape_and_matches_dash(capsys):
    rows = json.loads(run(capsys, "--demo", "--json", "activity"))
    dash = json.loads(run(capsys, "--demo", "--json", "dash"))["activity"]
    assert rows and dash
    by_player = {r["player"]: r for r in rows}
    for d in dash:  # every key dash prints, with the same value, in activity too
        r = by_player[d["player"]]
        assert {k: r[k] for k in d} == d
    first = rows[0]
    assert {"player", "team", "games", "games_left", "schedule"} <= set(first)
    assert all(isinstance(x, str) for x in first["schedule"])  # "vs MIL", "@ HOU" or ""
    assert any(x.startswith(("vs ", "@ ")) for x in first["schedule"])
    order = [(r["games"], r["games_left"]) for r in rows]
    assert order == sorted(order, reverse=True)  # most games first, as in 1.0.1
    # what 1.0.2 adds comes on top, under its own keys
    assert len(first["days"]) == len(first["schedule"])
    assert set(first["days"][0]) == {"date", "opponent", "slot", "starting"}
    assert {"positions", "slot", "games_in_lineup"} <= set(first)


# --- cli-2: watch add/remove find the player you mean -----------------------------------------------

def test_watch_add_with_a_name_that_fits_two_players_is_ambiguous(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--json", "watch", "add", "Allen", "--dry-run"])
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "matches several players" in err and "Jarrett Allen" in err and "Grayson Allen" in err
    out = json.loads(run(capsys, "--demo", "--json", "watch", "add", "Jarrett Allen", "--dry-run"))
    assert out["summary"].startswith("Add Jarrett Allen") and out["sent"] is False


def test_watch_remove_looks_at_the_watch_list_first(capsys):
    s = demo_session()
    grayson = next(p for p in s.player_pool("watch") if p.name == "Grayson Allen")
    assert grayson.id in s.watch_list()
    out = json.loads(run(capsys, "--demo", "--json", "watch", "remove", "Allen", "--dry-run"))
    assert out["summary"].startswith("Take Grayson Allen") and out["sent"] is False
    # a player who is not on the list still says so, with exit 0
    out = json.loads(run(capsys, "--demo", "--json", "watch", "remove", "Jarrett Allen"))
    assert out["summary"] == "Jarrett Allen is not on your watch list: nothing to do."


# --- cli-3: two picks for the same two teams -------------------------------------------------------

def test_picks_for_the_same_pair_take_their_games_in_order():
    lg = demo_session().league()
    ids = {t.name: t.id for t in lg.teams.values()}
    games = {g.id: g for g in core.season_games(lg)}
    pair = sorted(g.week for g in games.values()
                  if not g.decided and {g.home, g.away} == {ids["Monstars"], ids["Tune Squad"]})
    assert len(pair) == 2

    def weeks(picks):
        return sorted((games[gid].week, winner) for gid, winner in picks.items())

    split = core.parse_picks(lg, ["Monstars>Tune Squad", "Tune Squad>Monstars"])
    assert weeks(split) == [(pair[0], ids["Monstars"]), (pair[1], ids["Tune Squad"])]
    both = core.parse_picks(lg, ["Monstars>Tune Squad", "Monstars>Tune Squad"])
    assert weeks(both) == [(pair[0], ids["Monstars"]), (pair[1], ids["Monstars"])]
    later_first = core.parse_picks(lg, [f"Monstars>Tune Squad@{pair[1]}", "Tune Squad>Monstars"])
    assert weeks(later_first) == [(pair[0], ids["Tune Squad"]), (pair[1], ids["Monstars"])]
    with pytest.raises(BenchbossError, match="already picked"):
        core.parse_picks(lg, ["Monstars>Tune Squad"] * 3)
    with pytest.raises(BenchbossError, match="already picked"):  # never a silent overwrite
        core.parse_picks(lg, ["Monstars>Tune Squad", f"Tune Squad>Monstars@{pair[0]}"])


def test_cli_playoffs_keeps_both_picks(capsys):
    data = json.loads(run(capsys, "--demo", "--json", "playoffs", "--sims", "30",
                          "--pick", "Monstars>Tune Squad", "--pick", "Tune Squad>Monstars"))
    assert sorted(p["winner"] for p in data["picks"]) == ["Monstars", "Tune Squad"]
    assert len({p["matchup"] for p in data["picks"]}) == 2


# --- cli-5: bad usage exits 2 ----------------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ["players", "--view", "own"], ["roster", "--view", "l99"], ["standings", "--view", "nope"],
    ["activity", "--view", "nope"], ["playoffs", "--view", "nope"], ["watch", "add"],
    ["watch", "remove"], ["watch", "list", "Egor Demin"], ["news", "--watch", "Egor Demin"]])
def test_bad_usage_exits_2(capsys, argv):
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--json", *argv])
    assert e.value.code == 2
    out = capsys.readouterr()
    assert out.out == "" and f"usage: benchboss {argv[0]}" in out.err


def test_a_good_view_still_works(capsys):
    assert "Divisions" in run(capsys, "--demo", "standings", "--view", "divisions")
    assert json.loads(run(capsys, "--demo", "--json", "players", "--view", "l7", "-n", "3"))


# --- cli-7: per_game holds per-game numbers only ---------------------------------------------------

def test_per_game_leaves_out_the_games_count(capsys):
    line = StatLine(30.0, 240.0, 8, avg={GP: 8.0, PTS: 21.5})
    assert line.to_dict() == {"fpts": 30.0, "total": 240.0, "gp": 8, "per_game": {"PTS": 21.5}}
    rows = json.loads(run(capsys, "--demo", "--json", "roster"))
    splits = [s for r in rows for s in r["stats"].values()]
    assert splits and all("GP" not in s["per_game"] for s in splits)
    assert any(s["gp"] > 0 and "PTS" in s["per_game"] for s in splits)


# --- cli-8: nothing is live before opening night ---------------------------------------------------

def preseason():
    """The demo league as it looks the Friday before opening night (Tue 2026-10-20)."""
    s = demo_session()
    s._today = dt.date(2026, 10, 16)
    lg = s.league()
    lg.current_matchup = 1
    for m in lg.matchups:
        m.winner, m.home.points, m.away.points = "UNDECIDED", 0.0, 0.0
    return s


def test_no_game_is_live_before_the_season():
    s = preseason()
    assert not s.in_season
    race = s.playoff_race(sims=50)
    assert race.weeks_left[0] == 1
    assert not any(g.live for g in race.games)
    assert not any(g["live"] for g in race.to_dict()["games"])
    out = text_of(playoffs.draw(race, DARK, 120, 1), 120)
    assert "Week 1" in out and "this week" not in out
    assert not any(g.live for g in core.race(s.league(), sims=10, in_season=False).games)


def test_the_current_week_is_live_during_the_season():
    s = demo_session()
    race = s.playoff_race(sims=50)
    live = {g.week for g in race.games if g.live}
    assert live == {s.league().current_matchup}


# --- cli-9: the demo keeps the news seen in memory ---------------------------------------------------

def test_demo_alerts_mark_read_does_not_touch_the_config_folder(capsys):
    out = run(capsys, "--demo", "alerts", "--mark-read")
    assert "Marked 2 watch list items as read." in out
    assert not (config_mod.config_dir() / inbox.SEEN_FILE).exists()
    again = json.loads(run(capsys, "--demo", "--json", "alerts"))  # the demo is frozen
    assert len([a for a in again if a["kind"] == "spin"]) == 2


def test_a_demo_session_remembers_the_news_seen_until_it_ends():
    s = demo_session()
    assert len(inbox.watch_spins(s, mark_seen=True)) == 2
    assert inbox.watch_spins(s) == []
    assert len(inbox.watch_spins(demo_session())) == 2
    assert not (config_mod.config_dir() / inbox.SEEN_FILE).exists()


def test_each_run_of_the_demo_app_shows_the_spins_again():
    counts = []
    for _ in range(2):
        app = Benchboss(Config(), demo=True)
        toasts = []
        app.notify = lambda message, toasts=toasts, **kw: toasts.append(message)

        async def go(app=app):
            async with app.run_test(size=(140, 44)) as pilot:
                await app.workers.wait_for_complete()
                app.check_spins()
                await app.workers.wait_for_complete()
                await pilot.pause()

        asyncio.run(go())
        counts.append(len(toasts))
    assert counts == [2, 2]
    assert not (config_mod.config_dir() / inbox.SEEN_FILE).exists()


# --- cli-4: the agent instructions and the API docs know about the watch list ------------------------

def test_every_write_command_is_in_the_agent_write_lists():
    """A command with --dry-run writes to ESPN: AGENTS.md's write table and the Copilot rules
    must name it, so an agent asks before running it."""
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    writes = sorted(name for name, p in sub.choices.items()
                    if any("--dry-run" in a.option_strings for a in p._actions))
    assert "watch" in writes
    agents = repo_file("AGENTS.md").read_text(encoding="utf-8")
    table = agents.split("### Writes need", 1)[1].split("###", 1)[0]
    copilot = repo_file(".github/copilot-instructions.md").read_text(encoding="utf-8")
    rule = copilot.split("Writes change the real league", 1)[1].split("\n- ", 1)[0]
    for name in writes:
        assert f"benchboss {name} " in table, name
        assert f"`{name}" in rule, name
    assert "watch add" in rule and "watch remove" in rule
    assert "watch add" in table and "watch remove" in table


def test_vscode_lets_the_agent_read_the_new_commands_but_asks_before_watch_writes():
    raw = repo_file(".vscode/settings.json").read_text(encoding="utf-8")
    rules = json.loads("\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("//")))
    compiled = [(re.compile(k[1:-1]), v) for k, v in rules["chat.tools.terminal.autoApprove"].items()]

    def auto(cmd: str) -> bool:
        hits = [v for rx, v in compiled if rx.search(cmd)]
        return bool(hits) and all(hits)  # a false rule always wins

    for cmd in ("benchboss players --json --from watch", "benchboss playoffs --json",
                'benchboss playoffs --json --pick "Monstars>Tune Squad"', "benchboss watch",
                "benchboss watch --json", "benchboss watch list --json",
                'benchboss watch add "Egor Demin" --dry-run',
                'benchboss watch remove "Egor Demin" --dry-run --json'):
        assert auto(cmd), cmd
    for cmd in ('benchboss watch add "Egor Demin"', 'benchboss watch remove "Egor Demin" --json',
                'benchboss watch add "Egor Demin" --yes', 'benchboss watch add "Egor Demin" -y',
                'benchboss watch remove "Egor Demin" --dry-run --yes'):
        assert not auto(cmd), cmd


def test_the_watch_list_endpoint_is_documented():
    api = repo_file("docs/api/04-writes-transactions.md").read_text(encoding="utf-8")
    assert '{"watchList":' in api and "## 13. Watch list" in api
    index = repo_file("docs/api/README.md").read_text(encoding="utf-8")
    assert "04-writes-transactions.md#13-watch-list" in index

"""1.0.2 audit fixes, ESPN I/O, service and state: the finder's Watch list tab, the demo
client acting like ESPN (name search, sort by % change), watch-list spins for a player
just starred, and the watch-list write (the 50-player cap, ESPN's answer checked)."""

import asyncio
import datetime as dt
import json
import time

import pytest
from textual.widgets import DataTable

from benchboss import config as config_mod
from benchboss import inbox
from benchboss.cli import main
from benchboss.config import Config
from benchboss.demo import DemoClient, DemoSession, demo_session, load
from benchboss.errors import BenchbossError
from benchboss.news import NewsItem
from benchboss.service import WATCH_LIST_MAX, Session
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import finder
from benchboss.ui.theme import DARK

DEMIN = 5175643  # on the demo watch list
BUTLER = "Jimmy Butler III"  # a demo free agent, not on the watch list


async def settle(pilot):
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


@pytest.fixture
def session():
    """A demo session that keeps the news seen on disk, like a real league."""
    s = demo_session()
    s.seen_news = None
    return s


def rows(view) -> list:
    t = view.query_one(DataTable)
    by_id = {p.id: p for p in view.players}
    return [by_id[int(r.key.value)] for r in t.ordered_rows]


def seen_file() -> dict:
    return json.loads((config_mod.config_dir() / "seen-news.json").read_text())


def item(nid: int, hours: float, s, who: int) -> NewsItem:
    return NewsItem(nid, s.now - dt.timedelta(hours=hours), f"news {nid}", "the spin",
                    "RotoWire", "Rotowire", "", {who})


def feed(s, items: list[NewsItem]) -> None:
    s.news = lambda ids, days=5: sorted((i for i in items if i.player_ids & set(ids)),
                                        key=lambda i: i.published, reverse=True)


def free_agent_off_the_list(s) -> int:
    return next(x["id"] for x in s.data["free_agents"] if x["id"] not in s.watch_list())


# --- espn-1: the Watch list tab lists the stars as shown ------------------------------------------

def test_watch_tab_lists_stars_still_on_their_way_to_espn(monkeypatch):
    """Star three free agents and take one star off, then press 3 before ESPN has answered:
    the tab has the three and not the one (it used to show ESPN's list as it was)."""
    real = DemoClient.update_team

    def slow(self, team_id, body):
        time.sleep(0.3)  # ESPN's round trip; the writes queue up one after the other
        return real(self, team_id, body)

    monkeypatch.setattr(DemoClient, "update_team", slow)
    app = Benchboss(Config(), demo=True)

    async def run():
        async with app.run_test(size=(150, 48)) as pilot:
            await settle(pilot)
            await pilot.press("p")
            await settle(pilot)
            view = app.query_one(finder.FinderView)
            t = view.query_one(DataTable)
            starred = [p for p in rows(view) if p.id not in view.watched][:3]
            unstarred = next(p for p in rows(view) if p.id in view.watched)
            for p in [*starred, unstarred]:
                t.move_cursor(row=t.get_row_index(str(p.id)))
                await pilot.pause()
                await pilot.press("space")
            await pilot.press("3")
            await settle(pilot)
            shown = {p.id for p in rows(view)}
            assert {p.id for p in starred} <= shown
            assert unstarred.id not in shown
            assert set(app.session.watch_list()) == view.watched == shown
    asyncio.run(run())


def test_player_pool_watch_uses_the_ids_it_is_given(session):
    fa = free_agent_off_the_list(session)
    assert [p.id for p in session.player_pool("watch", watched=[fa])] == [fa]
    assert session.player_pool("watch", watched=()) == []
    assert len(session.player_pool("watch")) == 4  # the saved list when none is given


# --- espn-2: the demo matches the start of a name, like ESPN --------------------------------------

@pytest.fixture(scope="module")
def client():
    return DemoClient(load())


def names(client, query: str) -> list[str]:
    return [x["player"]["fullName"] for x in client.players({"filterName": {"value": query}})]


@pytest.mark.parametrize("query, who", [
    ("jok", "Nikola Jokic"), ("NIK", "Nikola Jokic"), ("nikola jok", "Nikola Jokic"),
    ("Jokić", "Nikola Jokic"), ("shai g", "Shai Gilgeous-Alexander"),
    ("antetok", "Giannis Antetokounmpo"), ("butler", BUTLER)])
def test_demo_name_search_matches_the_start_of_a_name(client, query, who):
    assert who in names(client, query)


@pytest.mark.parametrize("query", ["okic", "kic", "ntetokoun", "iii", "utler"])
def test_demo_name_search_never_matches_the_middle_of_a_name(client, query):
    assert names(client, query) == []


def test_demo_name_search_is_on_first_last_or_full_name(client):
    # ESPN finds Alexander-Walker (his last name starts so) but not Gilgeous-Alexander
    assert names(client, "alexander") == ["Nickeil Alexander-Walker"]


def test_watch_add_by_the_middle_of_a_name_fails_like_on_espn(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--demo", "watch", "add", "utler", "--dry-run"])
    assert e.value.code == 1
    assert "not in your league or free agency" in capsys.readouterr().err


def test_no_match_hint_asks_for_the_start_of_a_name(session):
    def tip(source: str, app: bool) -> str:
        data = finder.load(session, source=source, query="okic")
        assert not data.players
        return finder.empty_message(data, DARK, app=app).plain

    cli_fa, cli_all = tip("fa", False), tip("all", False)
    assert "start of a first or last name" in cli_fa and "--from all" in cli_fa
    assert "start of a first or last name" in cli_all and "--from all" not in cli_all
    app_fa, app_all = tip("fa", True), tip("all", True)
    assert "start of a first or last name" in app_fa and "press 4" in app_fa
    assert "press 4" not in app_all and "escape" in app_all


# --- espn-3: the demo sorts the pool asked for by % change ----------------------------------------

def test_demo_sort_by_change_sorts_the_pool_asked_for(session):
    fa = session.player_pool("fa", n=60, sort="change")
    assert len(fa) == 60 and not any(p.on_team_id for p in fa)
    change = [p.owned_change for p in fa]
    assert change == sorted(change, reverse=True)
    everyone = session.player_pool("all", n=60, sort="change")
    assert len(everyone) == 60 and any(p.on_team_id for p in everyone)
    # the trending command still lists the risers the demo was built with
    assert [p.id for p in session.trending(10)] == [x["id"] for x in session.data["trending"][:10]]


# --- espn-4: a player just starred does not bring his old news as new -----------------------------

def test_a_newly_watched_player_brings_only_his_recent_news(session):
    feed(session, [])
    assert inbox.watch_spins(session, mark_seen=True) == []  # the first check
    fa = free_agent_off_the_list(session)
    session.set_watched(fa, True)
    feed(session, [item(1, 60, session, fa), item(2, 2, session, fa),
                   item(3, 40, session, DEMIN)])
    # his news from 2.5 days ago counts as seen; his recent news and old unseen news on a
    # player watched before (the app was closed for a while) are new
    assert [i.id for _, i in inbox.watch_spins(session, mark_seen=True)] == [2, 3]
    assert inbox.watch_spins(session) == []
    entry = seen_file()[str(session.client.league_id)]
    assert sorted(entry["news"]) == [1, 2, 3] and fa in entry["players"]
    # taken off and starred again later: new to the list again
    session.set_watched(fa, False)
    assert inbox.watch_spins(session, mark_seen=True) == []
    assert fa not in seen_file()[str(session.client.league_id)]["players"]
    feed(session, [item(4, 30, session, fa)])
    session.set_watched(fa, True)
    assert inbox.watch_spins(session, mark_seen=True) == []


def test_without_mark_seen_a_new_player_is_not_recorded(session):
    feed(session, [])
    inbox.watch_spins(session, mark_seen=True)
    fa = free_agent_off_the_list(session)
    session.set_watched(fa, True)
    feed(session, [item(1, 60, session, fa)])
    assert inbox.watch_spins(session) == []
    assert fa not in seen_file()[str(session.client.league_id)]["players"]
    assert inbox.watch_spins(session) == []  # still new to the list, still old news


def test_the_first_seen_file_format_still_counts(session):
    """The file used to keep only the news ids: they still count as seen, and the players
    on the list then count as watched before."""
    key = str(session.client.league_id)
    path = config_mod.config_dir() / "seen-news.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: [111]}))
    feed(session, [item(111, 1, session, DEMIN), item(112, 40, session, DEMIN)])
    assert [i.id for _, i in inbox.watch_spins(session, mark_seen=True)] == [112]
    assert seen_file()[key] == {"news": [111, 112], "players": list(session.watch_list())}


# --- espn-5: the watch-list write -----------------------------------------------------------------

def test_a_full_watch_list_refuses_an_add_without_sending(session, monkeypatch):
    team = next(t for t in session.data["league"]["teams"] if t["id"] == session.data["my_team_id"])
    full = [x["id"] for x in session.data["free_agents"][:WATCH_LIST_MAX]]
    team["watchList"] = list(full)
    sent = []
    real = session.client.update_team

    def spy(team_id, body):
        sent.append(body)
        return real(team_id, body)

    monkeypatch.setattr(session.client, "update_team", spy)
    extra = session.data["free_agents"][WATCH_LIST_MAX]["id"]
    with pytest.raises(BenchbossError, match=f"full .*{WATCH_LIST_MAX} players"):
        session.set_watched(extra, True)
    assert sent == [] and len(session.watch_list()) == WATCH_LIST_MAX
    assert session.set_watched(full[0], False) == tuple(full[1:])  # taking one off still works
    assert sent == [{"watchList": full[1:]}]


def test_watch_add_says_the_list_is_full_before_asking(capsys, monkeypatch):
    monkeypatch.setattr(Session, "watch_list", lambda self: tuple(range(1, WATCH_LIST_MAX + 1)))
    with pytest.raises(SystemExit) as e:
        main(["--demo", "watch", "add", BUTLER, "--dry-run"])
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "watch list is full" in captured.err and "Dry run" not in captured.out


def test_watch_add_checks_the_list_espn_sends_back(capsys, monkeypatch):
    # the demo refuses CLI writes; here its client stands in for ESPN
    monkeypatch.setattr(DemoSession, "demo", property(lambda self: False))
    main(["--demo", "watch", "add", BUTLER, "--yes"])
    assert "ESPN: watch list has 5 players" in capsys.readouterr().out

    def keep(self, team_id, body):  # ESPN answers with the list it had
        return next(t for t in self.data["league"]["teams"] if t["id"] == team_id)

    monkeypatch.setattr(DemoClient, "update_team", keep)
    with pytest.raises(SystemExit) as e:
        main(["--demo", "watch", "add", BUTLER, "--yes"])
    assert e.value.code == 4
    out = capsys.readouterr().out
    assert f"ESPN: FAILED: {BUTLER} is not on the list ESPN sent back" in out
    with pytest.raises(SystemExit):
        main(["--demo", "--json", "watch", "add", BUTLER, "--yes"])
    result = json.loads(capsys.readouterr().out)
    assert result["sent"] and result["status"].startswith("FAILED") and result["error"]

"""1.0.4 news: the latest items on any player, search by name, and the tabbed news screen.

Every download goes through ``news._get_feed``; these tests fake it there (or fake
``Session.news`` / ``Session.latest_news``), so nothing reaches ESPN.
"""

import asyncio
import datetime as dt
import io
import json

import pytest
from rich.cells import cell_len
from rich.console import Console
from textual.widgets import Input, OptionList, Static

from benchboss import news, text
from benchboss.cli import main
from benchboss.config import Config
from benchboss.demo import demo_session
from benchboss.espn.models import Player
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import news as screen
from benchboss.ui.theme import DARK, LIGHT

NOW = dt.datetime.now(dt.timezone.utc)


def raw_item(nid: int, hours: float, pid: int = 7, kind: str = "Rotowire", **extra) -> dict:
    stamp = (NOW - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": nid, "type": kind, "playerId": pid, "published": stamp,
            "headline": f"item {nid}", "story": f"spin {nid}", **extra}


class Feed:
    """A fake news feed: answers ``items`` (newest first) for the players asked for, honoring
    days, limit and offset like ESPN, and keeps every query it got."""

    def __init__(self, items: list[dict]):
        self.items = sorted(items, key=lambda x: x["published"], reverse=True)
        self.calls: list[list] = []

    def __call__(self, params):
        self.calls.append(list(params))
        q = dict(params)
        ids = {v for k, v in params if k == "playerId"}
        rows = [x for x in self.items if x["playerId"] in ids]
        if "days" in q:
            cutoff = NOW - dt.timedelta(days=q["days"])
            rows = [x for x in rows if news._parse_time(x["published"]) >= cutoff]
        offset = q.get("offset", 0)
        return {"feed": rows[offset:offset + q.get("limit", 50)]}


@pytest.fixture
def feed(monkeypatch):
    def install(items):
        f = Feed(items)
        monkeypatch.setattr(news, "_get_feed", f)
        return f
    return install


# --- news.fetch and news.latest -------------------------------------------------------------------

def test_latest_mode_sends_no_days_and_keeps_old_items(feed):
    f = feed([raw_item(1, 2), raw_item(2, 24 * 40), raw_item(3, 24 * 400)])
    items = news.fetch([7], days=None, limit=10)
    assert [x.id for x in items] == [1, 2, 3]
    assert "days" not in dict(f.calls[0]) and ("limit", 10) in f.calls[0]
    assert "offset" not in dict(f.calls[0])  # only sent when asked for


def test_a_window_still_cuts_at_now_minus_days(feed):
    feed([raw_item(1, 30), raw_item(2, 60)])
    assert [x.headline for x in news.fetch([7], days=2)] == ["item 1"]


def test_offset_reaches_the_feed(feed):
    f = feed([raw_item(n, n) for n in range(1, 8)])
    items = news.fetch([7], days=None, limit=3, offset=3)
    assert ("offset", 3) in f.calls[0] and [x.id for x in items] == [4, 5, 6]


def test_many_players_go_in_batches_and_shared_items_merge(feed):
    rows = [raw_item(1000 + pid, pid / 10, pid) for pid in range(1, 121)]
    rows += [raw_item(5, 1, 3), raw_item(5, 1, 75), raw_item(5, 1, 110)]  # one item, 3 players
    f = feed(rows)
    items = news.fetch(list(range(1, 121)), days=1)
    assert len(f.calls) == 3 == -(-120 // news.BATCH)
    assert [len([k for k, _ in c if k == "playerId"]) for c in f.calls] == [50, 50, 20]
    shared = next(x for x in items if x.id == 5)
    assert shared.player_ids == {3, 75, 110}
    assert len(items) == 121


def test_video_items_are_left_out_unless_asked_for(feed):
    feed([raw_item(1, 1), raw_item(2, 2, kind="Media"), raw_item(3, 3, kind="Story",
                                                             links={"web": {"href": "u"}})])
    assert [x.id for x in news.fetch([7], days=None)] == [1, 3]
    got = news.fetch([7], days=None, include_media=True)
    assert [x.id for x in got] == [1, 2, 3]
    rotowire, story = got[0], got[2]
    assert rotowire.spin == "spin 1" and rotowire.source == "RotoWire"
    assert story.spin == "" and story.source == "ESPN" and story.link == "u"


def test_latest_pages_by_items_kept_and_skips_video(feed):
    rows = []
    for n in range(1, 31):  # every third item is a video
        rows.append(raw_item(n, n * 24, kind="Media" if n % 3 == 0 else "Rotowire"))
    f = feed(rows)
    first = news.latest(7, 10)
    assert len(first) == 10 and all(x.kind == "Rotowire" for x in first)
    assert dict(f.calls[0])["limit"] == 30 and "days" not in dict(f.calls[0])
    second = news.latest(7, 10, offset=10)
    assert {x.id for x in first}.isdisjoint({x.id for x in second}) and len(second) == 10
    assert first[-1].published > second[0].published
    assert news.latest(7, 10, offset=20) == []  # 20 Rotowire items in all
    assert dict(f.calls[-1])["limit"] <= news.LATEST_LIMIT


def test_latest_asks_again_when_most_of_the_news_is_video(feed):
    rows = [raw_item(n, n, kind="Rotowire" if n % 5 == 0 else "Media") for n in range(1, 101)]
    f = feed(rows)  # one item in five is text: the first request keeps only 6 of 30
    got = news.latest(7, 10)
    assert [x.id for x in got] == list(range(5, 55, 5))
    assert [dict(c)["limit"] for c in f.calls] == [30, 60]
    f.calls.clear()
    assert len(news.latest(7, 10, offset=15)) == 5  # only 20 in all: stops at the end
    assert [dict(c)["limit"] for c in f.calls] == [60, 120]
    f.calls.clear()
    feed([raw_item(n, n, kind="Media") for n in range(1, 400)])
    assert news.latest(7, 10) == []  # all video: gives up at LATEST_LIMIT


# --- text.rank and text.confident ------------------------------------------------------------------

POOL = [Player(1, "Ben Simmons", 1, owned=12.0), Player(2, "Anfernee Simons", 2, owned=40.0),
        Player(3, "Jeremiah Simmons", 0, owned=0.1), Player(4, "Kobi Simmons", 3, owned=0.4),
        Player(5, "Nikola Jokić", 4, owned=100.0), Player(6, "Nikola Jović", 5, owned=3.0),
        Player(7, "Nikola Vučević", 6, owned=88.0), Player(8, "Anthony Edwards", 7, owned=99.9),
        Player(9, "Justin Edwards", 8, owned=1.0), Player(10, "LaMelo Ball", 9, owned=99.0),
        Player(11, "Shai Gilgeous-Alexander", 10, owned=100.0),
        Player(12, "Nickeil Alexander-Walker", 11, owned=20.0)]


def ranked(query):
    return text.rank(POOL, query, lambda p: p.name, lambda p: (p.owned, p.pro_team_id > 0))


@pytest.mark.parametrize("query, first, sure", [
    ("ben simmons", "Ben Simmons", True),
    ("Ben Simons", "Ben Simmons", True),        # a typo
    ("jokic", "Nikola Jokić", True),            # accents fold
    ("JOKIĆ", "Nikola Jokić", True),
    ("lamelo", "LaMelo Ball", True),
    ("shai", "Shai Gilgeous-Alexander", True),
    ("a edwards", "Anthony Edwards", True),     # first initial and last name
    ("okic", "Nikola Jokić", True),             # inside the name
    ("simmons", "Ben Simmons", False),          # three of them: the most rostered first
    ("nikola", "Nikola Jokić", False),
    ("edwrds", "Anthony Edwards", False),       # a typo that fits two players alike
])
def test_rank_and_confident(query, first, sure):
    r = ranked(query)
    assert r[0][1].name == first
    assert text.confident(r) is sure


def test_rank_scores_and_order():
    assert ranked("ben simmons")[0][0] == text.EXACT
    assert ranked("ben sim")[0][0] == text.PREFIX
    assert [p.name for _, p in ranked("simmons")] == ["Ben Simmons", "Kobi Simmons",
                                                      "Jeremiah Simmons", "Anfernee Simons"]
    assert ranked("simmons")[-1][0] < text.INSIDE  # Simons is only a near spelling
    assert "Shai Gilgeous-Alexander" in [p.name for _, p in ranked("alexander")]
    assert ranked("") == [] and ranked("zzzz") == [] and ranked("  ") == []
    assert len(text.rank(POOL, "i", lambda p: p.name, n=3)) == 3
    assert not text.confident([])


def test_rank_without_a_weight_keeps_the_given_order_for_ties():
    r = text.rank(POOL, "nikola", lambda p: p.name)
    assert [p.id for _, p in r] == [5, 6, 7]


def test_match_one_for_writes_does_not_guess():
    with pytest.raises(Exception, match="is not in"):
        text.match_one(POOL, "Ben Simons", lambda p: p.name, where="the pool")


# --- the player list, search and latest news on the session ------------------------------------------

class ListClient:
    """Only what Session.nba_players needs from a client: players_wl, counted."""
    league_id, season, cookies = 12345, 2027, None

    def __init__(self, rows=None, error=None):
        self.rows = rows if rows is not None else [
            {"id": 3907387, "fullName": "Ben Simmons", "proTeamId": 23,
             "ownership": {"percentOwned": 12.0}, "lastNewsDate": 1762256400000},
            {"id": 3136195, "fullName": "Nikola Jokić", "proTeamId": 7,
             "ownership": {"percentOwned": 100.0}}]
        self.error = error
        self.calls = 0

    def player_universe(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


def list_session(client):
    from benchboss.config import Config
    from benchboss.service import Session

    return Session(Config(league_id=12345, team_id=1, season=2027), client=client)


def test_nba_players_are_read_once_and_kept_on_disk(tmp_path):
    from benchboss import config as config_mod

    client = ListClient()
    s = list_session(client)
    players = s.nba_players()
    assert [p.name for p in players] == ["Ben Simmons", "Nikola Jokić"]
    assert players[0].owned == 12.0 and players[0].last_news == 1762256400000
    assert not players[0].injury_known  # the list has no injury status: never "healthy"
    assert s.nba_players() is players and client.calls == 1
    saved = config_mod.cache_dir() / "12345-2027" / "nba-players.json"
    assert saved.exists()
    again = list_session(client)  # a new session (the next run) reads the file
    assert [p.id for p in again.nba_players()] == [3907387, 3136195] and client.calls == 1
    third = list_session(client)
    third.nba_players(max_age=0)  # too old: asked again
    assert client.calls == 2


def test_an_empty_or_failed_list_is_not_saved():
    from benchboss import config as config_mod
    from benchboss.errors import NetworkError

    s = list_session(ListClient(rows=[]))
    assert s.nba_players() == []
    assert not (config_mod.cache_dir() / "12345-2027" / "nba-players.json").exists()
    with pytest.raises(NetworkError):
        list_session(ListClient(error=NetworkError("offline"))).nba_players()


def test_the_player_list_is_public(monkeypatch):
    from benchboss.espn import client as client_mod

    seen = {}

    def http(url, **kw):
        seen.update(url=url, **kw)
        return [{"id": 1, "fullName": "A B"}]

    monkeypatch.setattr(client_mod, "http", http)
    c = client_mod.Client(12345, 2027, ("s2", "{swid}"))
    assert c.player_universe() == [{"id": 1, "fullName": "A B"}]
    assert seen["url"].endswith("/seasons/2027/players") and not seen.get("cookies")
    assert ("view", "players_wl") in seen["params"]
    assert '"filterActive"' in seen["headers"]["x-fantasy-filter"]
    monkeypatch.setattr(client_mod, "http", lambda url, **kw: {"oops": 1})
    assert c.player_universe() == []


def test_session_latest_news_goes_through_the_feed(feed):
    f = feed([raw_item(n, n * 24, pid=3907387) for n in range(1, 15)])
    s = list_session(ListClient())
    got = s.latest_news(3907387, 3, 2)
    assert [x.id for x in got] == [3, 4, 5] and len(f.calls) == 1


def test_search_finds_free_agents_and_league_players(session):
    found = session.search_players("ben simons")
    assert found[0][1].name == "Ben Simmons" and text.confident(found)
    daniels = session.search_players("dyson daniels")[0][1]
    assert daniels.status == "ONTEAM" and daniels.injury == "DTD"  # as the league has him


def test_search_without_the_player_list_uses_rosters_and_espns_name_filter(session, monkeypatch):
    from benchboss.errors import NetworkError

    def down(*a, **k):
        raise NetworkError("offline")

    monkeypatch.setattr(session, "nba_players", down)
    assert session.search_players("dyson")[0][1].name == "Dyson Daniels"  # on a roster
    assert session.search_players("ben simmons")[0][1].name == "Ben Simmons"  # ESPN's filter
    assert session.search_players("zzzz") == []


def test_search_asks_espn_when_the_list_has_nobody(session, monkeypatch):
    monkeypatch.setattr(session, "nba_players", lambda *a: [])
    assert session.search_players("egor")[0][1].name == "Egor Demin"


# --- the demo league -------------------------------------------------------------------------------

BEN = 3907387  # Ben Simmons, a free agent in the demo with news for the search


def test_demo_player_list(session):
    players = session.nba_players()
    assert len(players) == len(session.client.pool()) == 210
    assert not any(p.stats for p in players)
    with_news = {p.id for p in players if p.last_news}
    assert BEN in with_news and len(with_news) == 7
    assert session.cache.get("nba-players", 10**9) is None  # never written to disk


def test_demo_latest_news_has_no_window(session):
    items = session.latest_news(BEN)
    assert len(items) == 3 and items[0].headline.startswith("Simmons handed out")
    assert (session.now - items[-1].published).days >= 19
    assert [x.id for x in session.latest_news(BEN, 1, 1)] == [items[1].id]
    assert session.latest_news(BEN, 10, 3) == []
    assert len(session.news([BEN], 5)) == 1  # a window still cuts
    roster = [s.player.id for s in session.league().me.roster]
    assert len(session.news(roster + list(session.watch_list()), 5)) == 6  # the tabs as before


# --- the news screen's data and drawing ------------------------------------------------------------


def text_of(renderable, width: int = 120) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def ben(session) -> Player:
    return screen.find(session, "Ben Simmons").best


def test_find_picks_one_player_or_offers_several(session):
    sure = screen.find(session, "ben simmons")
    assert sure.best.name == "Ben Simmons" and sure.exact
    typo = screen.find(session, "ben simons")
    assert typo.best.name == "Ben Simmons" and not typo.exact
    several = screen.find(session, "jalen")
    assert several.best is None and not several.sure and len(several.players) == 6
    assert all("Jalen" in p.name for p in several.players)  # near spellings dropped
    assert screen.find(session, "zzzz").players == []


def test_owner_and_fresh_status(session):
    daniels = screen.find(session, "dyson daniels").best
    assert screen.owner_of(session, daniels) == "MONS"
    b = ben(session)
    assert screen.owner_of(session, b) == "FA" and not b.injury_known
    fresh = screen.refreshed(session, b)
    assert fresh.injury_known and fresh.status == "FREEAGENT"  # one kona read
    assert screen.refreshed(session, daniels) is daniels  # rostered: no read
    assert screen.candidate(fresh, "FA").startswith("Ben Simmons SAC PG · FA · ")


def test_latest_news_section(session):
    b = ben(session)
    data = screen.load_latest(session, [b], 2)
    sec = data.sections[0]
    assert data.days is None and sec.key == "players" and sec.more
    assert len(sec.items) == 2
    rest = screen.load_latest(session, [b], 2, offset=2).sections[0]
    assert len(rest.items) == 1 and not rest.more
    nothing = screen.load_latest(session, [screen.find(session, "jalen duren").best])
    assert nothing.sections[0].items == []


def test_latest_news_errors_raise_or_stay_in_place(session, monkeypatch):
    from benchboss.errors import NetworkError

    def down(*a, **k):
        raise NetworkError("could not reach ESPN (offline)")

    monkeypatch.setattr(session, "latest_news", down)
    with pytest.raises(NetworkError):
        screen.load_latest(session, [ben(session)])
    sec = screen.load_latest(session, [ben(session)], catch=True).sections[0]
    assert sec.error.startswith(screen.UNAVAILABLE) and "offline" in sec.error
    assert screen.UNAVAILABLE in text_of(screen.draw(screen.load_latest(
        session, [ben(session)], catch=True), DARK))


@pytest.mark.parametrize("width", [40, 46, 60, 80, 120, 150])
@pytest.mark.parametrize("pal", [DARK, LIGHT])
def test_latest_news_draws_dates_and_fits(session, width, pal):
    data = screen.load_latest(session, [screen.refreshed(session, ben(session))])
    out = text_of(screen.draw(data, pal, width), width)
    assert all(cell_len(line.rstrip()) <= width for line in out.splitlines())
    words = " ".join(out.split())
    assert "Player news · latest news · 3 items" in words or width < 60
    assert "Simmons went through a full practice" in words
    if width >= 60:
        assert "Oct 16" in out and "Oct 27" in out  # older than a few days: the date
        assert "Tue 3:00 AM" in out                 # recent: the weekday and time


def test_a_named_player_without_news_says_so(session):
    data = screen.load_latest(session, [screen.find(session, "jalen duren").best])
    out = text_of(screen.draw(data, DARK))
    assert "No news yet." in out and "nothing new" in out


def test_tab_data_keeps_a_feed_error_in_place(session, monkeypatch):
    from benchboss.errors import NetworkError

    def down(*a, **k):
        raise NetworkError("could not reach ESPN (offline)")

    monkeypatch.setattr(session, "news", down)
    data = screen.load_tab(session, "watch", 3)
    assert data.days == 3 and data.sections[0].key == "watch" and data.sections[0].error
    assert len(data.sections[0].players) == 4
    out = text_of(screen.body(data, DARK, 80, headings=False), 80)
    assert "News is not available right now" in out and "Watch list" not in out


def test_json_adds_player_ids(session):
    data = screen.load(session, 5, ("watch",))
    rows = screen.to_json(data)
    assert [r["player_ids"] for r in rows] == [[5175643], [4683688]]
    assert {"published", "source", "kind", "headline", "spin", "link", "players",
            "section"} <= set(rows[0])


# --- benchboss news -------------------------------------------------------------------------------


def run(capsys, *args):
    main(list(args))
    return capsys.readouterr()


def exit_code(capsys, *args) -> tuple[int, str]:
    with pytest.raises(SystemExit) as e:
        main(list(args))
    return e.value.code, capsys.readouterr().err


def test_cli_named_player_shows_his_latest_news(capsys):
    got = run(capsys, "--demo", "--json", "news", "Ben Simmons")
    rows = json.loads(got.out)
    assert len(rows) == 3 and {r["section"] for r in rows} == {"players"}
    assert rows[0]["players"] == ["Ben Simmons"] and rows[0]["player_ids"] == [BEN]
    assert got.err == ""  # the exact name: no note
    assert len(json.loads(run(capsys, "--demo", "--json", "news", "Ben Simmons", "-n", "1").out)) == 1
    out = run(capsys, "--demo", "news", "Ben Simmons").out
    assert "latest news" in out and "Oct 16" in out


def test_cli_days_keeps_the_window_for_a_named_player(capsys):
    rows = json.loads(run(capsys, "--demo", "--json", "news", "Ben Simmons", "--days", "5").out)
    assert len(rows) == 1
    out = run(capsys, "--demo", "news", "--days", "1", "Ben Simmons").out
    assert "Nothing in the last 24 hours." in out


def test_cli_close_spelling_gets_a_note(capsys):
    got = run(capsys, "--demo", "news", "demn")
    assert "Showing Egor Demin, the closest match to 'demn'." in got.err
    assert "Demin is seeing more minutes" in got.out
    got = run(capsys, "--demo", "--json", "news", "ben simons")
    assert json.loads(got.out)[0]["players"] == ["Ben Simmons"]  # the JSON stays clean
    assert "closest match" in got.err


def test_cli_name_for_several_players_is_a_usage_error(capsys):
    code, err = exit_code(capsys, "--demo", "news", "jalen")
    assert code == 2 and "'jalen' matches several players" in err
    assert "Jalen Duren (DET, MONS, " in err and "Jalen Suggs (ORL, FA, " in err


def test_cli_no_such_player(capsys):
    code, err = exit_code(capsys, "--demo", "news", "zzzz")
    assert code == 1 and "no NBA player matches 'zzzz'" in err


@pytest.mark.parametrize("args, says", [
    (["-n", "3"], "-n is for the players you name"),
    (["--watch", "-n", "3"], "-n is for the players you name"),
    (["Ben Simmons", "-n", "3", "--days", "5"], "use one or the other"),
    (["--watch", "Ben Simmons"], "not both"),
    (["Ben Simmons", "-n", "0"], "must be 1 or more"),
])
def test_cli_news_usage_errors(capsys, args, says):
    code, err = exit_code(capsys, "--demo", "news", *args)
    assert code == 2 and says in err


def test_cli_roster_and_watch_keep_their_window(capsys):
    rows = json.loads(run(capsys, "--demo", "--json", "news").out)
    assert len(rows) == 4 and {r["section"] for r in rows} == {"roster"}
    assert len(json.loads(run(capsys, "--demo", "--json", "news", "--days", "1").out)) < 4
    assert len(json.loads(run(capsys, "--demo", "--json", "news", "--watch").out)) == 2


def test_cli_ai_with_a_named_player_uses_five_days(capsys, monkeypatch):
    from benchboss import news as news_mod

    calls = []
    monkeypatch.setattr(news_mod, "ai_digest",
                        lambda players, days: calls.append(([p.name for p in players], days))
                        or "briefing")
    assert json.loads(run(capsys, "--demo", "--json", "news", "Ben Simmons", "--ai").out) == {
        "digest": "briefing"}
    assert calls == [(["Ben Simmons"], 5)]


def test_writes_still_need_the_exact_player(session):
    from benchboss.errors import BenchbossError

    with pytest.raises(BenchbossError):
        session.find_player("ben simons")  # add, drop, trade and watch never guess


# --- the app's news screen ----------------------------------------------------------------------------


async def settle(pilot):
    for _ in range(3):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


def drive(scenario, size=(140, 44), app=None):
    """Run ``scenario(pilot, app)`` on the demo app, starting on the news screen."""
    app = app or Benchboss(Config(), demo=True)

    async def go():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await pilot.press("n")
            await settle(pilot)
            await scenario(pilot, app)
    asyncio.run(go())
    assert app.return_code in (None, 0)
    return app


def view_of(app) -> screen.NewsView:
    return app.query_one(screen.NewsView)


def shown(app, part: str = "text") -> str:
    widget = view_of(app).query_one(f"#news-{part}", Static)
    return " ".join(text_of(widget.content, 200).split())


def counting(session, name: str) -> list:
    """Count the calls to one of the session's news methods (they still answer)."""
    real, calls = getattr(session, name), []

    def wrapper(*a, **k):
        calls.append(a)
        return real(*a, **k)

    setattr(session, name, wrapper)
    return calls


async def type_in(pilot, text: str):
    for ch in text:
        await pilot.press("space" if ch == " " else ch)


async def search(pilot, query: str):
    await pilot.press("slash")
    await type_in(pilot, query)
    await pilot.press("enter")
    await settle(pilot)


def test_tabs_load_once_and_switch_from_memory():
    s = demo_session()
    calls = counting(s, "news")
    app = Benchboss(Config(), demo=True, session=s)

    async def scenario(pilot, app):
        base = len(calls)  # the dashboard reads news too
        assert app.current == "news" and calls[-1][1] == 5
        assert "Roster · last 5 days · 4 items" in shown(app, "title")
        assert "Edwards posted" in shown(app) and "Press g" not in shown(app)
        assert "ANTHROPIC_API_KEY" in shown(app)  # the AI tip under the roster tab
        await pilot.press("2")
        await settle(pilot)
        assert "Watch list · last 5 days · 2 items" in shown(app, "title")
        assert "Demin is seeing more minutes" in shown(app) and "ANTHROPIC" not in shown(app)
        await pilot.press("1")
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)
        assert len(calls) == base + 1  # each tab read once
        await pilot.press("ctrl+t")
        await settle(pilot)
        assert len(calls) == base + 1 and "Demin is seeing" in shown(app)

    drive(scenario, app=app)


def test_the_window_of_days():
    s = demo_session()
    calls = counting(s, "news")
    app = Benchboss(Config(), demo=True, session=s)

    async def scenario(pilot, app):
        base = len(calls)
        await pilot.press("right_square_bracket")
        await settle(pilot)
        assert "last 7 days" in shown(app, "title") and calls[-1][1] == 7
        assert len(calls) == base + 1
        await pilot.press("left_square_bracket")
        await pilot.press("left_square_bracket")
        await settle(pilot)
        assert "last 3 days" in shown(app, "title") and len(calls) == base + 2  # 5 was kept
        for _ in range(4):
            await pilot.press("left_square_bracket")
        await settle(pilot)
        assert "last 24 hours" in shown(app, "title")
        view = view_of(app)
        for want in (3, 5, 7, 14, 30, 1):  # . goes up and wraps (a key a phone reaches)
            await pilot.press("full_stop")
            await settle(pilot)
            assert view.days == want
        await pilot.press("plus")
        await settle(pilot)
        assert view.days == 3

    drive(scenario, app=app)


def test_search_a_close_spelling_and_go_back():
    async def scenario(pilot, app):
        await search(pilot, "ben simons")
        view = view_of(app)
        assert view.mode == "search" and view.player.name == "Ben Simmons"
        assert "Ben Simmons · latest news · 3 items" in shown(app, "title")
        assert "/ Ben Simmons" in shown(app, "tabs")
        body = shown(app)
        assert body.startswith("Ben Simmons SAC DTD · PG · FA · ")  # the fresh header
        assert "Oct 16" in body and "older news" not in body
        assert app.focused is view.query_one("#news-body")
        await pilot.press("escape")
        await settle(pilot)
        assert view.mode == "tab" and "Roster · last 5 days" in shown(app, "title")
        assert view.query_one(Input).value == ""

    drive(scenario)


def test_a_name_for_several_players_opens_a_pick_list():
    async def scenario(pilot, app):
        await search(pilot, "jalen")
        view = view_of(app)
        picks = view.query_one(OptionList)
        assert view.mode == "picks" and picks.has_class("open") and app.focused is picks
        assert picks.option_count == 6 and "6 players match 'jalen'" in shown(app, "title")
        assert "Jalen Duren DET C · MONS · " in str(picks.get_option_at_index(3).prompt)
        await pilot.press("j")  # j and k move in the list too
        await pilot.press("down")
        await pilot.press("k")
        await pilot.press("enter")
        await settle(pilot)
        assert view.mode == "search" and view.player.name == "Jalen Johnson"
        assert "No news yet." in shown(app) and not picks.has_class("open")
        await search(pilot, "jalen")
        await pilot.press("escape")
        await settle(pilot)
        assert view.mode == "tab" and "Roster" in shown(app, "title")

    drive(scenario)


def test_backspace_and_tabs_leave_a_search():
    async def scenario(pilot, app):
        view = view_of(app)
        await search(pilot, "ben simmons")
        await pilot.press("backspace")
        await settle(pilot)
        assert view.mode == "tab"
        await search(pilot, "ben simmons")
        await pilot.press("2")
        await settle(pilot)
        assert view.mode == "tab" and view.tab == "watch"
        await pilot.press("backspace")  # nothing to leave: nothing happens
        await pilot.press("escape")
        await settle(pilot)
        assert app.current == "news" and view.tab == "watch"

    drive(scenario)


def test_no_match_says_so():
    async def scenario(pilot, app):
        await search(pilot, "zzzz")
        assert "No NBA player matches 'zzzz'." in shown(app)

    drive(scenario)


def test_more_brings_older_news_ten_at_a_time():
    s = demo_session()
    base = s.now
    many = [news.NewsItem(500 + i, base - dt.timedelta(days=i), f"old item {i}", "", "Demo",
                          "Rotowire", "", {BEN}) for i in range(25)]
    asked = []

    def latest(pid, n=10, offset=0):
        asked.append((pid, n, offset))
        return many[offset:offset + n]

    s.latest_news = latest
    app = Benchboss(Config(), demo=True, session=s)

    async def scenario(pilot, app):
        await search(pilot, "ben simmons")
        view = view_of(app)
        assert len(view.shown.sections[0].items) == 10 and "Press . for older news." in shown(app)
        assert [k.key for k in view.key_items()][0] == "."
        await pilot.press("full_stop")
        await settle(pilot)
        assert len(view.shown.sections[0].items) == 20
        await pilot.press("plus")
        await settle(pilot)
        assert len(view.shown.sections[0].items) == 25 and not view.shown.sections[0].more
        assert "older news" not in shown(app) and "older" not in shown(app, "hint")
        await pilot.press("full_stop")
        await settle(pilot)
        assert asked == [(BEN, 11, 0), (BEN, 11, 10), (BEN, 11, 20)]
        assert "old item 24" in shown(app) and "25 items" in shown(app, "title")

    drive(scenario, app=app)


def test_typing_in_the_search_box_never_changes_screens():
    async def scenario(pilot, app):
        view = view_of(app)
        await pilot.press("slash")
        assert app.focused is view.query_one(Input)
        await type_in(pilot, "dnfp1/")
        await settle(pilot)
        assert app.current == "news" and view.query_one(Input).value == "dnfp1/"
        assert view.tab == "roster" and view.mode == "tab"
        await pilot.press("escape")  # leaves the box and clears what was typed
        await settle(pilot)
        assert app.focused is view.query_one("#news-body") and view.query_one(Input).value == ""
        await pilot.press("f")
        await settle(pilot)
        assert app.current == "trash"
        await pilot.press("n")
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        assert app.current == "players"

    drive(scenario)


def test_the_screen_comes_back_where_it_was():
    async def scenario(pilot, app):
        await pilot.press("2")
        await pilot.press("right_square_bracket")
        await settle(pilot)
        await pilot.press("d")
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        view = view_of(app)
        assert (view.tab, view.days, view.mode) == ("watch", 7, "tab")
        assert "Watch list · last 7 days" in shown(app, "title")
        await search(pilot, "ben simons")
        await pilot.press("d")
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        view = view_of(app)
        assert view.mode == "search" and view.player.name == "Ben Simmons"
        assert view.query_one(Input).value == "ben simons" and "3 items" in shown(app, "title")
        await pilot.press("escape")
        await settle(pilot)
        assert view.tab == "watch" and view.days == 7  # the tab it came from

    drive(scenario)


def test_refresh_reads_again_and_keeps_the_tab():
    s = demo_session()
    calls = counting(s, "news")
    app = Benchboss(Config(), demo=True, session=s)

    async def scenario(pilot, app):
        await pilot.press("2")
        await settle(pilot)
        base = len(calls)
        await pilot.press("r")
        await settle(pilot)
        assert len(calls) == base + 1 and calls[-1][0] == list(s.watch_list())
        assert view_of(app).tab == "watch"

    drive(scenario, app=app)


def test_a_feed_that_is_down_shows_in_place_and_is_asked_again():
    from benchboss.errors import NetworkError

    s = demo_session()
    real = s.news
    state = {"down": True}

    def flaky(ids, days=5):
        if state["down"]:
            raise NetworkError("could not reach ESPN (offline)")
        return real(ids, days)

    s.news = flaky
    app = Benchboss(Config(), demo=True, session=s)

    async def scenario(pilot, app):
        assert "News is not available right now: could not reach ESPN" in shown(app)
        assert "Roster" in shown(app, "tabs")  # the screen itself is up
        state["down"] = False
        await pilot.press("2")
        await settle(pilot)
        assert "Demin is seeing" in shown(app)
        await pilot.press("1")
        await settle(pilot)
        assert "Edwards posted" in shown(app)  # asked again, not the error from the cache

    drive(scenario, app=app)


@pytest.mark.parametrize("error", ["network", "bug"])
def test_a_failing_search_never_takes_the_app_down(error):
    from benchboss.errors import NetworkError

    s = demo_session()

    def broken(*a, **k):
        raise NetworkError("offline") if error == "network" else RuntimeError("boom")

    s.search_players = broken
    app = Benchboss(Config(), demo=True, session=s)

    async def scenario(pilot, app):
        await search(pilot, "ben simmons")
        assert app.is_running and "Search failed:" in shown(app)
        assert ("offline" if error == "network" else "RuntimeError: boom") in shown(app)
        await pilot.press("escape")
        await settle(pilot)
        assert "Edwards posted" in shown(app)

    drive(scenario, app=app)


def test_late_answers_on_a_screen_that_was_left_do_nothing():
    async def scenario(pilot, app):
        view = view_of(app)
        app.action_show("dash")
        assert not view._live()
        late = (lambda: view._tab_loaded(view._gen, "watch", 5, None, "late"),
                lambda: view._searched(view._gen, "x", None, None, "", None, "late"),
                lambda: view._player_loaded(view._gen, Player(1, "A B"), "", 0, None, "late"),
                lambda: view._names_loaded(["A B"]), lambda: view.focus(), view._render_all)
        for call in late:
            call()
        await settle(pilot)
        for call in late:
            call()
        assert app.current == "dash" and app.focused is not None and app.focused.is_attached

    drive(scenario)


def test_an_older_answer_does_not_replace_a_newer_screen():
    async def scenario(pilot, app):
        view = view_of(app)
        old = view._gen
        await pilot.press("2")
        await settle(pilot)
        view._searched(old, "ben", screen.Found("ben", []), None, "", None, "")
        assert view.mode == "tab" and "Watch list" in shown(app, "title")

    drive(scenario)


def test_the_search_box_suggests_names():
    async def scenario(pilot, app):
        view = view_of(app)
        assert view.query_one(Input).suggester is None  # nothing read until / is pressed
        await pilot.press("slash")
        await settle(pilot)
        suggester = view.query_one(Input).suggester
        assert suggester is not None
        assert await suggester.get_suggestion("ben s") == "Ben Simmons"

    drive(scenario)


def test_a_click_on_a_tab_opens_it():
    async def scenario(pilot, app):
        view = view_of(app)
        start, _, tab = next(r for r in view.query_one("#news-tabs").regions if r[2] == "watch")
        await pilot.click("#news-tabs", offset=(start + 2, 0))
        await settle(pilot)
        assert view.tab == "watch"

    drive(scenario)


def test_key_items_follow_the_mode():
    async def scenario(pilot, app):
        view = view_of(app)
        keys = [k.key for k in view.key_items()]
        assert keys == ["1-2", "/", "."]
        await search(pilot, "jalen")
        assert [k.key for k in view.key_items()] == ["⏎", "esc", "/"]
        await pilot.press("enter")
        await settle(pilot)
        assert [k.key for k in view.key_items()] == ["esc", "/", "1-2"]
        from benchboss.ui.layout import KeyItem

        menu_letters = set("dtwafpnxisyougvmrq")
        for mode_items in (view.key_items(),):
            assert all(isinstance(k, KeyItem) and k.key not in menu_letters for k in mode_items)

    drive(scenario)


def test_the_widget_binds_no_menu_letter():
    letters = set("dtwafpnxisyougvmrq")
    keys = {k for b in screen.NewsView.BINDINGS for k in b.key.split(",")}
    assert not keys & letters


@pytest.mark.parametrize("width", [46, 80, 120, 160])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_screen_fits_every_width(width, theme):
    app = Benchboss(Config(theme=theme), demo=True)

    async def scenario(pilot, app):
        view = view_of(app)

        def fits():
            w = view.size.width
            title = view.query_one("#news-title", Static).content
            tabs = view.query_one("#news-tabs", Static).content
            box = view.query_one(Input).styles.width.value
            assert title.cell_len <= w and "\n" not in title.plain
            assert tabs.cell_len + box <= w, (tabs.plain, box, w)
            hint = view.query_one("#news-hint", Static).content
            assert hint.cell_len <= w

        fits()
        await pilot.press("2")
        await settle(pilot)
        fits()
        await search(pilot, "ben simmons")
        fits()
        await search(pilot, "jalen")
        fits()

    drive(scenario, size=(width, 40), app=app)

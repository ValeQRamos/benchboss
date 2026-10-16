"""Alerts on every spin for watch-list players, and watch-list news (1.0.2).

The demo league has a 4-player watch list and two news items on it, 16 and 22 hours old on
the demo clock (Wed 2026-11-04 3:30 pm Eastern). Every test gets its own BENCHBOSS_HOME
(conftest), so the seen file starts empty. The demo keeps what you have seen in memory, so
these tests use demo sessions set to keep it in the seen file, as a real league does.
"""

import asyncio
import datetime as dt
import io
import json

import pytest
from rich.cells import cell_len
from rich.console import Console
from textual.widgets import Static

from benchboss import config as config_mod
from benchboss import demo as demo_mod
from benchboss import inbox
from benchboss.cli import main
from benchboss.config import Config
from benchboss.demo import DemoSession, demo_session
from benchboss.errors import BenchbossError, NetworkError
from benchboss.news import NewsItem
from benchboss.ui import views
from benchboss.ui.app import Benchboss
from benchboss.ui.screens import news as news_screen
from benchboss.ui.theme import DARK, LIGHT

DEMIN, LIVELY = 5175643, 4683688  # the two watch-list players with demo news


def on_disk(cfg=None) -> DemoSession:
    """A demo session that keeps the news seen in seen-news.json, like a real league."""
    s = demo_session(cfg)
    s.seen_news = None
    return s


@pytest.fixture
def session():
    return on_disk()


@pytest.fixture
def disk_demo(monkeypatch):
    """benchboss --demo (CLI and app) with the news seen on disk, so it lasts between runs."""
    monkeypatch.setattr(demo_mod, "demo_session", on_disk)


def seen_file() -> dict:
    return json.loads((config_mod.config_dir() / "seen-news.json").read_text())


def seen_news(s) -> list:
    """The news ids the seen file has for the demo league."""
    return seen_file()[str(s.client.league_id)]["news"]


def item(nid: int, hours: float, s, who: int = DEMIN, headline: str = "") -> NewsItem:
    return NewsItem(nid, s.now - dt.timedelta(hours=hours), headline or f"news {nid}",
                    "the spin", "RotoWire", "Rotowire", "", {who})


def feed(s, items: list[NewsItem]) -> None:
    """The news feed answers ``items`` (only the ones on the players asked for)."""
    s.news = lambda ids, days=5: sorted((i for i in items if i.player_ids & set(ids)),
                                        key=lambda i: i.published, reverse=True)


def text_of(renderable, width: int = 120) -> str:
    console = Console(width=width, record=True, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def run(capsys, *args) -> str:
    main(list(args))
    return capsys.readouterr().out


# --- watch_spins -----------------------------------------------------------------------------------

def test_demo_spins_show_once_with_mark_seen(session):
    first = inbox.watch_spins(session, mark_seen=True)
    assert [who for who, _ in first] == ["Egor Demin", "Dereck Lively II"]  # newest first
    assert first[0][1].headline.startswith("Demin is seeing more minutes")
    assert inbox.watch_spins(session) == []
    assert inbox.watch_spins(on_disk(), mark_seen=True) == []  # remembered on disk
    assert sorted(seen_news(session)) == sorted(i.id for _, i in first)


def test_without_mark_seen_nothing_is_recorded(session):
    assert len(inbox.watch_spins(session)) == 2
    assert len(inbox.watch_spins(session)) == 2
    assert not (config_mod.config_dir() / "seen-news.json").exists()


def test_first_run_hides_news_older_than_a_day(session):
    feed(session, [item(1, 2, session), item(2, 23, session), item(3, 30, session),
                   item(4, 60, session)])
    assert [i.id for _, i in inbox.watch_spins(session, mark_seen=True)] == [1, 2]
    # the old ones were recorded too, so they never show up later
    assert sorted(seen_news(session)) == [1, 2, 3, 4]
    assert inbox.watch_spins(session) == []
    feed(session, [item(5, 0.5, session), item(1, 2, session), item(3, 30, session)])
    assert [i.id for _, i in inbox.watch_spins(session, mark_seen=True)] == [5]
    assert inbox.watch_spins(session) == []


def test_after_the_first_run_older_news_is_new_too(session):
    """Only the very first check hides news older than a day: after that, anything not seen
    yet shows (say the app was closed for two days)."""
    feed(session, [])
    assert inbox.watch_spins(session, mark_seen=True) == []
    assert seen_file() == {str(session.client.league_id): {
        "news": [], "players": list(session.watch_list())}}
    feed(session, [item(7, 40, session)])
    assert [i.id for _, i in inbox.watch_spins(session)] == [7]


def test_the_seen_file_is_per_league_and_capped(session):
    key = str(session.client.league_id)
    path = config_mod.config_dir() / "seen-news.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"999": [1, 2, 3], key: list(range(1000, 1600))}))
    feed(session, [item(1, 1, session), item(2, 2, session)])  # league 999 saw ids 1 and 2
    assert [i.id for _, i in inbox.watch_spins(session, mark_seen=True)] == [1, 2]
    book = seen_file()
    assert book["999"] == [1, 2, 3]
    assert len(book[key]["news"]) == inbox.SEEN_KEEP == 500
    assert book[key]["news"][-2:] == [2, 1]  # oldest first: the newest stay at the end
    assert book[key]["news"][0] == 1102      # the oldest ids were dropped
    assert not list(path.parent.glob("*.tmp"))


def test_a_broken_seen_file_counts_as_a_first_run(session):
    path = config_mod.config_dir() / "seen-news.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert len(inbox.watch_spins(session, mark_seen=True)) == 2
    assert len(seen_news(session)) == 2


def test_an_empty_watch_list_has_no_spins(session):
    session.league().me.watch_list = ()
    session.news = lambda ids, days=5: pytest.fail("no watch list, no news request")
    assert inbox.watch_spins(session, mark_seen=True) == []
    assert not (config_mod.config_dir() / "seen-news.json").exists()


def test_spins_name_only_the_watched_players(session):
    both = NewsItem(9, session.now, "trade talk", "", "ESPN", "Story", "",
                    {DEMIN, session.league().me.roster[0].player.id})
    feed(session, [both])
    assert inbox.watch_spins(session) == [("Egor Demin", both)]


def test_errors_propagate_from_watch_spins(session):
    def down(ids, days=5):
        raise NetworkError("could not reach ESPN (offline)")

    session.news = down
    with pytest.raises(BenchbossError, match="offline"):
        inbox.watch_spins(session)


# --- alerts ----------------------------------------------------------------------------------------

def test_alerts_list_spins_after_the_rest_without_marking_them(session):
    alerts = inbox.alerts(session)
    kinds = [a.kind for a in alerts]
    assert kinds[0] == "trade_offer" and kinds[-2:] == ["spin", "spin"]
    spin = alerts[-2]
    assert spin.text.startswith("Watch list · Egor Demin: Demin is seeing")
    assert not spin.urgent
    d = spin.to_dict()
    assert d["kind"] == "spin" and d["player"] == "Egor Demin"
    assert d["headline"].startswith("Demin is seeing") and d["published"].startswith("2026-11-04")
    assert "player" not in alerts[0].to_dict()
    assert [a.kind for a in inbox.alerts(session)] == kinds  # listing does not mark them seen
    assert [a.kind for a in inbox.alerts(session, include_spins=False)] == kinds[:-2]


def test_alerts_survive_a_news_outage(session):
    def down(ids, days=5):
        raise NetworkError("could not reach ESPN (offline)")

    session.news = down
    assert [a.kind for a in inbox.alerts(session)] == ["trade_offer"]


def test_alerts_view_marks_spins_with_a_star():
    s = demo_session()
    out = text_of(views.alerts(inbox.alerts(s), DARK), 60)
    assert "★ Watch list · Egor Demin: Demin is seeing" in out
    assert all(cell_len(line) <= 60 for line in out.splitlines())
    assert "watch list news" in text_of(views.alerts([], LIGHT))


# --- CLI ---------------------------------------------------------------------------------------------

def test_cli_alerts_json_has_spins(capsys):
    data = json.loads(run(capsys, "--demo", "--json", "alerts"))
    spins = [a for a in data if a["kind"] == "spin"]
    assert [a["player"] for a in spins] == ["Egor Demin", "Dereck Lively II"]
    assert all(a["headline"] and a["urgent"] is False for a in spins)
    assert data[0]["kind"] == "trade_offer"


def test_cli_alerts_mark_read(capsys, disk_demo):
    out = run(capsys, "--demo", "alerts")
    assert "★ Watch list · Egor Demin" in out and "--mark-read" in out
    out = run(capsys, "--demo", "alerts", "--mark-read")
    assert "Marked 2 watch list items as read." in out
    out = run(capsys, "--demo", "alerts")
    assert "Watch list" not in out and "Trade offer" in out
    assert not [a for a in json.loads(run(capsys, "--demo", "--json", "alerts"))
                if a["kind"] == "spin"]


def test_cli_alerts_mark_read_with_nothing_new(capsys, disk_demo):
    run(capsys, "--demo", "alerts", "--mark-read")
    out = run(capsys, "--demo", "alerts", "--mark-read")
    assert "No new watch list news to mark as read." in out and "Trade offer" in out
    assert "--mark-read marks" not in run(capsys, "--demo", "alerts")


def test_cli_alerts_mark_read_json(capsys, disk_demo):
    data = json.loads(run(capsys, "--demo", "--json", "alerts", "--mark-read"))
    assert len([a for a in data if a["kind"] == "spin"]) == 2
    assert len(seen_file()["424242"]) == 2


def test_cli_alerts_warns_when_the_news_is_down(capsys, monkeypatch):
    def down(self, ids, days=5):
        raise NetworkError("could not reach ESPN (offline)")

    monkeypatch.setattr(DemoSession, "news", down)
    main(["--demo", "alerts"])
    out, err = capsys.readouterr()
    assert "Trade offer" in out and "not available right now" in err


def test_cli_news_watch(capsys):
    data = json.loads(run(capsys, "--demo", "--json", "news", "--watch"))
    assert [d["players"] for d in data] == [["Egor Demin"], ["Dereck Lively II"]]
    assert {d["section"] for d in data} == {"watch"}
    out = run(capsys, "--demo", "news", "--watch")
    assert "★ Watch list" in out and "Demin is seeing more minutes" in out
    assert "Your roster" not in out and "Edwards" not in out


def test_cli_news_roster_is_unchanged(capsys):
    data = json.loads(run(capsys, "--demo", "--json", "news"))
    assert len(data) == 4 and {d["section"] for d in data} == {"roster"}
    assert {"published", "source", "kind", "headline", "spin", "link", "players"} <= set(data[0])
    out = run(capsys, "--demo", "news")
    assert "Your roster" in out and "Watch list" not in out


def test_cli_news_watch_with_an_empty_watch_list(capsys, monkeypatch):
    monkeypatch.setattr(DemoSession, "watch_list", lambda self: ())
    out = run(capsys, "--demo", "news", "--watch")
    assert "Your watch list is empty" in out and 'benchboss watch add "Player"' in out
    assert json.loads(run(capsys, "--demo", "--json", "news", "--watch")) == []
    with pytest.raises(SystemExit) as e:
        main(["--demo", "news", "--watch", "--ai"])
    assert e.value.code == 1 and "watch list is empty" in capsys.readouterr().err


def test_cli_news_watch_and_names_do_not_mix(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--demo", "news", "--watch", "Egor Demin"])
    assert e.value.code == 2 and "not both" in capsys.readouterr().err


# --- the news screen ---------------------------------------------------------------------------------

@pytest.mark.parametrize("width", [46, 80, 120, 160])
@pytest.mark.parametrize("pal", [DARK, LIGHT])
def test_news_screen_fits_and_has_both_sections(width, pal):
    data = news_screen.load(demo_session(), 5, tip="Press g for an AI briefing.")
    out = text_of(news_screen.draw(data, pal, width), width)
    assert all(cell_len(line.rstrip()) <= width for line in out.splitlines())
    assert out.index("Your roster") < out.index("★ Watch list") < out.index("Press g")
    assert "Player news  ·  last 5 days  ·  6 items" in out
    assert "Lively practiced in full Tuesday" in out


def test_news_screen_when_there_is_no_news_or_no_watch_list():
    s = demo_session()
    s.news = lambda ids, days=5: []  # the preseason: nobody has news yet
    out = text_of(news_screen.draw(news_screen.load(s), DARK))
    assert out.count("Nothing in the last 5 days.") == 2 and "nothing new" in out
    s = demo_session()
    s.league().me.watch_list = ()
    out = text_of(news_screen.draw(news_screen.load(s), LIGHT), 46)
    assert "Your roster  4" in out and "Your watch list is empty" in out
    assert 'benchboss watch add "Player"' in out.replace("\n", " ")


def test_news_screen_drops_the_time_and_source_for_every_item_at_once():
    """At 46 columns some names leave room for the source and some do not: none get it, so
    the lines read alike. The tip wraps at the same edge as the news on a wide screen."""
    data = news_screen.load(demo_session(), 5, tip="Press g for an AI briefing. " * 6)
    narrow = text_of(news_screen.draw(data, DARK, 46), 46)
    assert "Demo" not in narrow and narrow.count(" AM") + narrow.count(" PM") == 6
    assert text_of(news_screen.draw(data, DARK, 80), 80).count("·  Demo") == 6
    wide = text_of(news_screen.draw(data, LIGHT, 200), 200)
    assert max(cell_len(line.rstrip()) for line in wide.splitlines()) <= news_screen.MEASURE + 5


def test_news_screen_names_the_watched_players_even_without_stats(monkeypatch):
    s = demo_session()

    def down(*a, **k):
        raise NetworkError("could not reach ESPN (offline)")

    monkeypatch.setattr(s, "player_pool", down)
    data = news_screen.load(s, 5, ("watch",))
    players = data.sections[0].players
    assert [p.name for p in players] == [p.name for p in news_screen.watch_players(demo_session())]
    assert len(players) == 4 and not any(p.stats for p in players)  # names only
    assert len(data.sections[0].items) == 2
    out = text_of(news_screen.draw(data, DARK, 80), 80)
    assert "Egor Demin  ·  Tue" in out and " FA " not in out  # no made-up NBA team


# --- the app -----------------------------------------------------------------------------------------

def body_text(app) -> str:
    return text_of(app.query_one("#body", Static).content, 120)


def drive(app, scenario, size=(140, 44)):
    async def go():
        async with app.run_test(size=size) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await scenario(pilot)
    asyncio.run(go())


def test_app_news_screen_shows_roster_and_watch_list():
    app = Benchboss(Config(), demo=True)

    async def scenario(pilot):
        await pilot.press("n")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out = body_text(app)
        assert app.current == "news"
        assert out.index("Your roster") < out.index("★ Watch list")
        assert "Demin is seeing more minutes" in out and "Edwards posted" in out
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert "★ Watch list" in body_text(app)  # redrawn from the same data

    drive(app, scenario)


def test_app_toasts_each_demo_spin_once(disk_demo):
    app = Benchboss(Config(), demo=True)
    toasts = []
    app.notify = lambda message, **kw: toasts.append((message, kw.get("title")))

    async def scenario(pilot):
        app.check_spins()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [t for t in toasts] == [
            ("Egor Demin: Demin is seeing more minutes with the second unit and has looked "
             "comfortable running the offense.", "Watch list news"),
            ("Dereck Lively II: Lively practiced in full Tuesday and is expected to be "
             "available Wednesday.", "Watch list news")]
        app.check_spins()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(toasts) == 2  # never again

    drive(app, scenario)
    toasts.clear()
    again = Benchboss(Config(), demo=True)  # the next run of the app remembers them too
    again.notify = lambda message, **kw: toasts.append(message)

    async def later(pilot):
        again.check_spins()
        await again.workers.wait_for_complete()
        await pilot.pause()
        assert toasts == []

    drive(again, later)


def test_app_sums_up_a_burst_of_spins():
    s = demo_session()
    feed(s, [item(i, i / 10, s, headline=f"headline {i}") for i in range(1, 8)])
    app = Benchboss(Config(), demo=True, session=s)
    toasts = []
    app.notify = lambda message, **kw: toasts.append(message)

    async def scenario(pilot):
        app.check_spins()
        await app.workers.wait_for_complete()
        await pilot.pause()

    drive(app, scenario)
    assert toasts[:4] == [f"Egor Demin: headline {i}" for i in range(1, 5)]
    assert toasts[4:] == ["3 more on your watch list: press n for Player news."]


@pytest.mark.parametrize("error", [NetworkError("could not reach ESPN"), RuntimeError("boom")])
def test_a_failing_background_check_does_not_crash_the_app(monkeypatch, error):
    def broken(session, mark_seen=False):
        raise error

    monkeypatch.setattr(inbox, "watch_spins", broken)
    app = Benchboss(Config(), demo=True)
    toasts = []
    app.notify = lambda message, **kw: toasts.append(message)

    async def scenario(pilot):
        app.check_spins()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.is_running and toasts == []
        await pilot.press("n")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.current == "news" and "Watch list" in body_text(app)

    drive(app, scenario)
    assert app.return_code in (None, 0)


def test_a_failing_toast_does_not_crash_the_app():
    app = Benchboss(Config(), demo=True)

    def broken(*a, **k):
        raise RuntimeError("the screen is gone")

    app.notify = broken

    async def scenario(pilot):
        app.check_spins()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.is_running

    drive(app, scenario)
    assert app.return_code in (None, 0)

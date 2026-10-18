"""1.0.4 news: the latest items on any player, search by name, and the tabbed news screen.

Every download goes through ``news._get_feed``; these tests fake it there (or fake
``Session.news`` / ``Session.latest_news``), so nothing reaches ESPN.
"""

import datetime as dt

import pytest

from benchboss import news, text
from benchboss.espn.models import Player

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

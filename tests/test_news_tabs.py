"""1.0.4 news: the latest items on any player, search by name, and the tabbed news screen.

Every download goes through ``news._get_feed``; these tests fake it there (or fake
``Session.news`` / ``Session.latest_news``), so nothing reaches ESPN.
"""

import datetime as dt

import pytest

from benchboss import news

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

"""The public news feed: site.web.api.espn.com first, site.api.espn.com when that fails."""

import datetime as dt

import pytest

from benchboss import news
from benchboss.errors import EspnError, NetworkError
from benchboss.espn import client

WEB = "https://site.web.api.espn.com/apis/fantasy/v2/games/fba/news/players"
OLD = "https://site.api.espn.com/apis/fantasy/v2/games/fba/news/players"


def feed():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return {"feed": [{"id": 1, "type": "Rotowire", "playerId": 7, "published": now,
                      "headline": "Out tonight", "story": "Rest day."}]}


@pytest.fixture
def answers(monkeypatch):
    """Each call to ``client.http`` gets the next answer (an exception is raised)."""
    queue, calls = [], []

    def http(url, **kw):
        calls.append(url)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(client, "http", http)
    return queue, calls


def test_news_comes_from_the_web_host_and_needs_no_fallback(answers):
    queue, calls = answers
    queue.append(feed())
    items = news.fetch([7], days=5)
    assert calls == [WEB]
    assert [i.headline for i in items] == ["Out tonight"]


def test_news_falls_back_to_the_old_host_when_the_web_host_refuses(answers):
    queue, calls = answers
    queue += [EspnError(403, "Access Denied"), feed()]
    assert [i.headline for i in news.fetch([7], days=5)] == ["Out tonight"]
    assert calls == [WEB, OLD]


def test_news_falls_back_when_the_web_host_cannot_be_reached(answers):
    queue, calls = answers
    queue += [NetworkError("could not reach ESPN"), feed()]
    assert len(news.fetch([7], days=5)) == 1
    assert calls == [WEB, OLD]


def test_when_both_hosts_fail_the_first_error_is_the_one_shown(answers):
    queue, calls = answers
    queue += [EspnError(503, "maintenance"), EspnError(403, "Access Denied")]
    with pytest.raises(EspnError, match="503"):
        news.fetch([7], days=5)
    assert calls == [WEB, OLD]


def test_one_player_news_uses_the_same_hosts(answers):
    queue, calls = answers
    queue += [EspnError(403, "Access Denied"), feed()]
    assert news.latest(7)[0].headline == "Out tonight"
    assert calls == [WEB, OLD]

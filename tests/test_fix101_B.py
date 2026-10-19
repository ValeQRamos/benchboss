"""Regression tests for the 1.0.1 fixes in the network and service layer.

Everything runs offline: urllib.request.urlopen is replaced by fakes, and the league is the demo.
"""

import asyncio
import datetime as dt
import gzip
import io
import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import replace
from http.client import IncompleteRead, RemoteDisconnected

import pytest

from benchboss import inbox, news
from benchboss.cli import main
from benchboss.config import Config
from benchboss.core.lineup import plan_day
from benchboss.demo import DemoClient, DemoSession
from benchboss.errors import BenchbossError, EspnError, NetworkError
from benchboss.espn import client
from benchboss.espn.constants import BENCH
from benchboss.service import periods_for

URL = "https://example.invalid/apis/v3/games/fba/test"


class FakeResponse:
    def __init__(self, body: bytes = b"", status: int = 200, error: BaseException | None = None):
        self.body, self.status, self.error = body, status, error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        if self.error:
            raise self.error
        return self.body


def answer(monkeypatch, *outcomes, then=None):
    """Make urlopen return (or raise) each outcome in turn, then ``then`` for good."""
    queue = list(outcomes)
    calls = []

    def urlopen(req, timeout=None, context=None):
        calls.append(req)
        r = queue.pop(0) if queue else then
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return calls


EXECUTED = FakeResponse(b'{"status": "EXECUTED"}')


# --- F10: a connection that breaks off is a BenchbossError -------------------------------------

@pytest.mark.parametrize("failure", [
    RemoteDisconnected("Remote end closed connection without response"),
    ConnectionResetError(54, "Connection reset by peer"),
    ssl.SSLError("record layer failure"),
])
def test_dropped_connection_is_a_network_error(monkeypatch, failure):
    answer(monkeypatch, failure)
    with pytest.raises(NetworkError, match="the connection to ESPN dropped") as e:
        client.http(URL)
    assert "may or may not" not in str(e.value)  # a read changes nothing


def test_cut_off_body_on_a_write_says_the_outcome_is_unknown(monkeypatch):
    answer(monkeypatch, FakeResponse(error=IncompleteRead(b"x" * 16, 984)))
    with pytest.raises(NetworkError, match="may or may not have gone through"):
        client.http(URL, body={"type": "ROSTER"})


def test_cut_off_gzip_body_is_a_network_error(monkeypatch):
    answer(monkeypatch, FakeResponse(gzip.compress(b'{"status": "EXECUTED"}' * 20)[:20]))
    with pytest.raises(NetworkError):
        client.http(URL)


def test_read_timeout_on_a_write_says_the_outcome_is_unknown(monkeypatch):
    answer(monkeypatch, FakeResponse(error=TimeoutError("timed out")))
    with pytest.raises(NetworkError, match="did not answer in time; it may or may not"):
        client.http(URL, body={"type": "ROSTER"})


def test_non_json_answer_is_an_espn_error(monkeypatch):
    answer(monkeypatch, FakeResponse(b"<html><body>Down for maintenance</body></html>"))
    with pytest.raises(EspnError, match="not JSON") as e:
        client.http(URL)
    assert e.value.status == 200


def test_error_status_with_a_broken_body_keeps_the_status(monkeypatch):
    class Broken(urllib.error.HTTPError):
        def read(self, *a):
            raise IncompleteRead(b"")

    answer(monkeypatch, Broken(URL, 503, "Service Unavailable", {}, io.BytesIO()))
    with pytest.raises(EspnError) as e:
        client.http(URL)
    assert e.value.status == 503


def _writes_over_http(monkeypatch):
    """Demo writes go through the real http() (whose urlopen the test fakes)."""
    monkeypatch.setattr(DemoClient, "transaction",
                        lambda self, body: client.http(URL + "/transactions/", body=body))


def test_optimize_survives_a_dropped_connection(monkeypatch, capsys):
    _writes_over_http(monkeypatch)
    calls = answer(monkeypatch, RemoteDisconnected("closed"), then=EXECUTED)
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--yes", "optimize", "week"])
    out, err = capsys.readouterr()
    assert e.value.code == 4
    assert calls
    assert out.count("ESPN: EXECUTED") == len(calls) - 1  # every other day sent is listed
    assert "connection to ESPN dropped; it may or may not have gone through" in " ".join(err.split())
    assert "Traceback" not in err


def test_app_survives_a_dropped_connection_during_apply(monkeypatch):
    from benchboss.ui.app import Benchboss

    _writes_over_http(monkeypatch)
    calls = answer(monkeypatch, RemoteDisconnected("closed"), then=EXECUTED)

    async def scenario():
        app = Benchboss(Config(), demo=False, session=DemoSession())
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(2)
            await pilot.press("w")
            await pilot.pause(2)
            app.query_one("#apply").scroll_visible(animate=False)  # the week plan is tall
            await pilot.pause()
            await pilot.click("#apply")
            await pilot.pause(2)
            assert calls
            assert app.is_running and app.return_code is None
    asyncio.run(scenario())


# --- F11: a failed read on a later day keeps the days already sent ------------------------------

def _fail_read(monkeypatch, period, after=0):
    """Reading ``period`` times out once it was read ``after`` times (the preview reads it once)."""
    real = DemoSession.roster_on
    reads = []

    def roster_on(self, sp):
        if sp == period and reads.count(sp) >= after:
            raise NetworkError("ESPN did not answer in time")
        reads.append(sp)
        return real(self, sp)

    monkeypatch.setattr(DemoSession, "roster_on", roster_on)


def test_apply_days_returns_every_day_when_a_read_fails(session, monkeypatch):
    sent = []
    monkeypatch.setattr(DemoClient, "transaction",
                        lambda self, body: sent.append(body["scoringPeriodId"]) or {"status": "EXECUTED"})
    periods = periods_for(session, "week")
    bad = periods[3]
    _fail_read(monkeypatch, bad)
    results = session.apply_days(periods)
    assert [r.plan.period for r in results] == periods
    failed = results[periods.index(bad)]
    assert failed.error == "could not read the lineup: ESPN did not answer in time"
    assert not failed.status and bad not in sent
    assert sent and sent == [r.plan.period for r in results if r.status == "EXECUTED"]


def test_optimize_lists_the_days_sent_when_a_later_read_fails(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(DemoClient, "transaction",
                        lambda self, body: sent.append(body["scoringPeriodId"]) or {"status": "EXECUTED"})
    _fail_read(monkeypatch, periods_for(DemoSession(), "week")[3], after=1)
    with pytest.raises(SystemExit) as e:
        main(["--demo", "--yes", "optimize", "week"])
    out, err = capsys.readouterr()
    assert e.value.code == 4  # part of a write, not a plain error
    assert sent and out.count("ESPN: EXECUTED") == len(sent)
    assert "could not read the lineup: ESPN did not answer in time" in " ".join(err.split())


# --- F40: the week preview carries each day's moves forward, like ESPN ---------------------------

class CarryForwardEspn:
    """Lineups the way ESPN keeps them: a day's change carries to later days with none of their own."""

    def __init__(self, session):
        self.base = list(session.league().me.roster)
        self.own: dict[int, dict[int, int]] = {}
        self.sent: dict[int, list[tuple]] = {}

    def slots(self, period: int) -> dict[int, int]:
        days = [p for p in self.own if p <= period]
        return dict(self.own[max(days)]) if days else {s.player.id: s.slot_id for s in self.base}

    def roster_on(self, period: int):
        slots = self.slots(period)
        return [replace(s, slot_id=slots[s.player.id]) for s in self.base]

    def transaction(self, body: dict) -> dict:
        period = body["scoringPeriodId"]
        slots = self.slots(period)
        for it in body["items"]:
            assert slots[it["playerId"]] == it["fromLineupSlotId"]
            slots[it["playerId"]] = it["toLineupSlotId"]
        self.own[period] = slots
        self.sent[period] = [(it["playerId"], it["fromLineupSlotId"], it["toLineupSlotId"])
                             for it in body["items"]]
        return {"status": "EXECUTED"}


def test_week_preview_matches_what_apply_sends(session, monkeypatch):
    espn = CarryForwardEspn(session)
    monkeypatch.setattr(session, "roster_on", espn.roster_on)
    monkeypatch.setattr(session.client, "transaction", espn.transaction)
    periods = periods_for(session, "week")
    preview = {p.period: [(m.player.id, m.from_slot, m.to_slot) for m in p.moves]
               for p in session.plan_days(periods) if p.moves}
    results = session.apply_days(periods)
    assert not [r.error for r in results if r.error]
    assert preview and espn.sent == preview


def test_preview_does_not_carry_over_a_day_with_its_own_change(session, monkeypatch):
    espn = CarryForwardEspn(session)
    monkeypatch.setattr(session, "roster_on", espn.roster_on)
    periods = periods_for(session, "week")
    day2 = periods[1]
    own = espn.slots(day2)
    for s in [s for s in espn.base if s.is_starting][:2]:
        own[s.player.id] = BENCH  # the second day has a change of its own
    espn.own[day2] = own
    lg = session.league()
    alone = plan_day(espn.roster_on(day2), lg.slot_counts, day2, session.calendar)
    plans = {p.period: p for p in session.plan_days(periods)}
    assert [str(m) for m in plans[day2].moves] == [str(m) for m in alone.moves]


# --- F13: names for players on no roster -------------------------------------------------------

def test_pending_claim_names_the_free_agent(session):
    lg = session.league()
    fa = session.client.data["free_agents"][0]
    mine = lg.me.roster[-1].player
    session.client.data["league"]["pendingTransactions"] = [{
        "type": "WAIVER", "status": "PENDING", "teamId": lg.my_team_id,
        "items": [{"playerId": fa["id"], "type": "ADD", "toTeamId": lg.my_team_id},
                  {"playerId": mine.id, "type": "DROP", "fromTeamId": lg.my_team_id}]}]
    claims = [a.text for a in inbox.alerts(session, include_chat=False) if a.kind == "waiver"]
    assert claims == [f"Pending claim: {fa['player']['fullName']} (drop {mine.name})"]


def test_waiver_report_card_names_dropped_players_in_one_lookup(session, monkeypatch):
    lg = session.league()
    other = next(t for t in lg.teams.values() if t.id != lg.my_team_id)
    fa = session.client.data["free_agents"][1]
    card = {"messageTypeId": 273, "author": "LM", "date": 0,
            "attributes": {"team1": str(other.id), "team1addP1": str(other.roster[0].player.id),
                           "team1dropP1": str(fa["id"]), "team1dropP2": "999999999"}}
    real, lookups = session.client.players, []
    monkeypatch.setattr(session.client, "players",
                        lambda flt, sp=None: lookups.append(flt) or real(flt, sp))
    for _ in range(3):
        _, who, text = inbox.format_message(card, {}, session)
    assert who == "ESPN"
    assert text == (f"[waiver report] {other.name} gets {other.roster[0].player.name} and drops "
                    f"{fa['player']['fullName']}, player 999999999")
    assert len(lookups) == 1


def test_names_fall_back_to_ids_when_the_lookup_fails(session, monkeypatch):
    def down(flt, sp=None):
        raise NetworkError("ESPN did not answer in time")

    monkeypatch.setattr(session.client, "players", down)
    assert 123 not in inbox.player_names(session, [123])


# --- F29: a league without a chat topic yet, and the demo chat ---------------------------------

def test_demo_chat_reads(capsys):
    main(["--demo", "chat"])
    out = capsys.readouterr().out
    assert "league chat" in out and "[waiver report]" in out
    main(["--demo", "--json", "chat"])
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 3
    assert not [r for r in rows if re.search(r"player \d+", r["text"])]


def test_no_league_chat_topic_reads_as_empty(session, monkeypatch, capsys):
    monkeypatch.setattr(DemoClient, "comm", lambda self, path="", **kw: {"topics": []})
    assert inbox.thread(session, None) == (None, "league chat")
    main(["--demo", "chat"])
    assert "(no messages yet)" in capsys.readouterr().out
    with pytest.raises(BenchbossError, match="no chat topic yet"):
        inbox.send(session, "hello")


def test_blank_message_is_never_sent(session):
    with pytest.raises(BenchbossError, match="empty"):
        inbox.send(session, "   ")


# --- F46: the TLS context keeps the system roots and adds certifi ------------------------------

TEST_ROOT_CA = """-----BEGIN CERTIFICATE-----
MIIBmjCCAT+gAwIBAgIUMPawwxu+4MfuuvA62LlWLXy2HygwCgYIKoZIzj0EAwIw
ITEfMB0GA1UEAwwWYmVuY2hib3NzIHRlc3Qgcm9vdCBDQTAgFw0yNjEwMTUxNzI5
NDNaGA8yMTI2MDkyMTE3Mjk0M1owITEfMB0GA1UEAwwWYmVuY2hib3NzIHRlc3Qg
cm9vdCBDQTBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABBRJ3EAuWWFNjcT2PzYi
sIPH6Xsp3c1KRP3CAPNFx1iUa1icXg14VBW8sa/FWc54xjCpGcf0CFGgxvdePVIU
AIGjUzBRMB0GA1UdDgQWBBS9saJD+X3urnBpMwagkzQUBK4JkDAfBgNVHSMEGDAW
gBS9saJD+X3urnBpMwagkzQUBK4JkDAPBgNVHRMBAf8EBTADAQH/MAoGCCqGSM49
BAMCA0kAMEYCIQD5vGoP2rA+6qvFS0Fj1noySbVGCTNdh6wSg57mdDeTCgIhAM6I
QrOy1+Pa4eyQM9cAET/G3lFytfh0nClyoAPUVtL0
-----END CERTIFICATE-----
"""


def _cas(ctx: ssl.SSLContext) -> set:
    return {(c["serialNumber"], repr(c["subject"])) for c in ctx.get_ca_certs()}


def test_tls_context_keeps_system_roots_and_adds_certifi(tmp_path, monkeypatch):
    import certifi

    pem = tmp_path / "corp-root.pem"
    pem.write_text(TEST_ROOT_CA)
    monkeypatch.setenv("SSL_CERT_FILE", str(pem))
    ours = _cas(client._ssl_context())
    assert _cas(ssl.create_default_context()) <= ours            # OS store and SSL_CERT_FILE
    assert _cas(ssl.create_default_context(cafile=certifi.where())) <= ours


# --- F71: news --days N means the last N days -------------------------------------------------

def test_news_days_means_the_last_n_days(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)

    def item(nid, hours):
        stamp = (now - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"id": nid, "type": "Rotowire", "playerId": 7, "published": stamp,
                "headline": f"{hours} hours ago"}

    monkeypatch.setattr(client, "http", lambda url, params=None: {"feed": [item(1, 30), item(2, 60)]})
    assert [x.headline for x in news.fetch([7], days=2)] == ["30 hours ago"]

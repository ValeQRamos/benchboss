"""League chat, direct messages and alerts (trade offers, accepted trades, waiver claims,
news on your watch-list players).

ESPN's in-app chat lives on lm-api-communication. The league chat is one topic of type
CHAT_ALL_MEMBERS (the older CHAT type is a legacy topic the app never shows); each direct
message thread is a CHAT_DIRECT_MESSAGE topic whose ``viewableBy`` lists the two member ids. Sending is POST topics/{id}/messages/ with {author, content, messageTypeId: 0};
a brand-new DM is POST topics/ with {messages, subject, type, viewableBy}.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from benchboss import config as config_mod
from benchboss.errors import BenchbossError
from benchboss.text import norm

if TYPE_CHECKING:
    from benchboss.news import NewsItem

DM = "CHAT_DIRECT_MESSAGE"
LEAGUE_CHAT = "CHAT_ALL_MEMBERS"
MESSAGE_KIND = {188: "[lineup move]", 239: "[roster drop]", 259: "[sticker]", 260: "[GIF]",
                264: "[player added]", 265: "[player dropped]", 266: "[add and drop]",
                267: "[weekly recap]", 268: "[weekly recap]", 269: "[weekly recap]",
                271: "[trade proposal]", 272: "[trade accepted]", 273: "[waiver report]",
                279: "[video]", 281: "[league recap]", 283: "[image]"}


@dataclass
class Alert:
    kind: str       # trade_offer, trade_sent, trade_accepted, waiver, dm, spin
    text: str
    urgent: bool = False
    news: NewsItem | None = None  # a spin alert's news item
    player: str = ""              # a spin alert's watch-list player(s)

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "text": self.text, "urgent": self.urgent}
        if self.news is not None:
            n = self.news
            out.update(player=self.player, headline=n.headline, spin=n.spin or None,
                       published=n.published.isoformat(), source=n.source,
                       link=n.link or None, news_id=n.id)
        return out


def people(session) -> dict[str, str]:
    """member id -> 'First Last (Team)'."""
    lg = session.league()
    team_of = {o: t.name for t in lg.teams.values() for o in t.owner_ids}
    return {mid: name + (f" ({team_of[mid]})" if mid in team_of else "")
            for mid, name in lg.members.items()}


def topics(session) -> list[dict]:
    flt = {"topics": {"filterType": {"value": [LEAGUE_CHAT, DM]}}}
    return session.client.comm(params=[("view", "chat_conversations")],
                                fantasy_filter=flt).get("topics", [])


def messages(session, topic_id: str, n: int = 15) -> list[dict]:
    flt = {"limit": n, "offset": 0, "sortDate": {"sortAsc": False, "sortPriority": 1}}
    r = session.client.comm(f"topics/{topic_id}", params=[("view", "chat_conversation")],
                            fantasy_filter=flt)
    return sorted(r.get("messages") or [], key=lambda m: m.get("date", 0))


def resolve_member(session, query: str) -> str:
    me = session.client.swid
    ppl = people(session)
    q = norm(query)
    hits = [mid for mid, name in ppl.items() if mid != me and q in norm(name)]
    if len(hits) != 1:
        raise BenchbossError(f"'{query}' " + ("is nobody in this league" if not hits else
                                              "matches several people: " + ", ".join(ppl[h] for h in hits)))
    return hits[0]


def thread(session, with_member: str | None) -> tuple[str | None, str]:
    """(topic id or None, label) for the league chat or the DM with a member id.

    None means nobody has written there yet.
    """
    me = session.client.swid
    ts = topics(session)
    if with_member:
        tid = next((t["id"] for t in ts if t.get("type") == DM
                    and set(t.get("viewableBy") or []) == {me, with_member}), None)
        return tid, f"DM with {people(session).get(with_member, with_member)}"
    tid = next((t["id"] for t in ts if t.get("type") == LEAGUE_CHAT), None)
    return tid, "league chat"


_looked_up: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def player_names(session, ids) -> dict[int, str]:
    """Player id -> name for rostered players plus ``ids``.

    Players on no roster (a pending waiver claim, someone dropped in a waiver report) are
    looked up on ESPN in one request and remembered for the session; an id ESPN does not
    know stays out of the map.
    """
    lg = session.league()
    names = {s.player.id: s.player.name for t in lg.teams.values() for s in t.roster}
    known = _looked_up.setdefault(session, {})
    missing = sorted({int(i) for i in ids} - names.keys() - known.keys())
    if missing:
        with contextlib.suppress(BenchbossError):  # names are a nicety: keep the ids then
            hits = session.client.players({"filterIds": {"value": missing}}, lg.scoring_period)
            found = {x.get("id"): (x.get("player") or {}).get("fullName") for x in hits}
            known.update((i, found.get(i)) for i in missing)
    names.update((i, n) for i, n in known.items() if n)
    return names


def _card(m: dict, session) -> str:
    """Readable text for ESPN bot cards (trades, waiver reports) from their ``attributes``.

    Keys look like team1addP1: side 1 or 2, add or drop, P = player id, then an index.
    """
    attrs = m.get("attributes") or {}
    kind = m.get("messageTypeId")
    label = MESSAGE_KIND.get(kind, f"[message type {kind}]")
    if not attrs or session is None:
        return label
    lg = session.league()
    names = player_names(session, [v for k, v in attrs.items()
                                   if ("addP" in k or "dropP" in k) and str(v).isdigit()])
    sides = []
    for side in ("1", "2"):
        tid = attrs.get(f"team{side}")
        if not tid:
            continue
        team = lg.teams.get(int(tid)).name if tid.isdigit() and int(tid) in lg.teams else f"team {tid}"
        adds = [names.get(int(v), f"player {v}") for k, v in sorted(attrs.items())
                if k.startswith(f"team{side}addP") and str(v).isdigit()]
        drops = [names.get(int(v), f"player {v}") for k, v in sorted(attrs.items())
                 if k.startswith(f"team{side}dropP") and str(v).isdigit()]
        part = team
        if adds:
            part += " gets " + ", ".join(adds)
        if drops:
            part += (" and" if adds else "") + " drops " + ", ".join(drops)
        sides.append(part)
    return f"{label} " + "; ".join(sides) if sides else label


def iso_date(m: dict) -> str:
    return dt.datetime.fromtimestamp(m.get("date", 0) / 1000, tz=dt.timezone.utc).isoformat()


def format_message(m: dict, ppl: dict[str, str], session=None) -> tuple[str, str, str]:
    """(when, who, text)"""
    t = dt.datetime.fromtimestamp(m.get("date", 0) / 1000)
    when = t.strftime("%a %b %d %I:%M %p").replace(" 0", " ")
    kind = m.get("messageTypeId")
    text = m.get("content") if kind in (0, 270, 280) else _card(m, session)
    who = "ESPN" if m.get("author") == "LM" else ppl.get(m.get("author"), "someone")
    return when, who, text or ""


def send(session, text: str, to_member: str | None = None) -> str:
    if not text.strip():
        raise BenchbossError("the message is empty")
    me = session.client.swid
    tid, label = thread(session, to_member)
    if not tid and not to_member:
        raise BenchbossError("this league has no chat topic yet: post the first message on ESPN")
    msg = {"author": me, "content": text.strip(), "messageTypeId": 0}
    if tid:
        r = session.client.comm(f"topics/{tid}/messages/", body=msg)
        r = r[0] if isinstance(r, list) and r else r
        return f"sent to {label} (message {r.get('id', '?')})"
    r = session.client.comm("topics/", body={"messages": [msg], "subject": "DM", "type": DM,
                                             "viewableBy": [to_member, me]})
    return f"sent, new {label} (topic {r.get('id', '?')})"


def pending_transactions(session) -> list[dict]:
    """Pending trades and claims that involve my team (view mPendingTransactions)."""
    me = session.league().my_team_id
    raw = session.client.league("mPendingTransactions")
    txs = raw.get("pendingTransactions")
    if txs is None:  # the key is absent when nothing is pending; older payloads nest it per team
        txs = next((t.get("pendingTransactions") or [] for t in raw.get("teams") or []
                    if t.get("id") == me), [])
    return [tx for tx in txs if tx.get("teamId") == me or any(
        me in (i.get("fromTeamId"), i.get("toTeamId")) for i in tx.get("items") or [])]


def alerts(session, include_chat: bool = True, include_spins: bool = True) -> list[Alert]:
    """Trade offers, claims and unread DMs, then news on watch-list players you have not
    seen yet (``spin_alerts``; listing them does not mark them seen). The news feed is a
    nicety here: when it cannot be reached, the other alerts still come back."""
    lg = session.league()
    me = lg.my_team_id
    pending = pending_transactions(session)
    names = player_names(session, [i["playerId"] for tx in pending for i in tx.get("items") or []
                                   if str(i.get("playerId", "")).isdigit()])
    out: list[Alert] = []
    for tx in pending:
        kind, status = tx.get("type", ""), tx.get("status", "")
        items = tx.get("items") or []
        give = [names.get(i["playerId"], str(i["playerId"])) for i in items if i.get("fromTeamId") == me]
        get = [names.get(i["playerId"], str(i["playerId"])) for i in items if i.get("toTeamId") == me]
        other = next((i.get("toTeamId") if i.get("fromTeamId") == me else i.get("fromTeamId")
                      for i in items if me in (i.get("fromTeamId"), i.get("toTeamId"))), None)
        partner = lg.teams[other].name if other in lg.teams else "another team"
        deal = f"you give {', '.join(give) or 'nothing'}, you get {', '.join(get) or 'nothing'}"
        if kind == "TRADE_PROPOSAL" and tx.get("teamId") != me:
            out.append(Alert("trade_offer", f"Trade offer from {partner}: {deal}", urgent=True))
        elif kind == "TRADE_PROPOSAL":
            out.append(Alert("trade_sent", f"Your offer to {partner} is waiting: {deal}"))
        elif kind == "TRADE_ACCEPT" and status == "PENDING":
            when = dt.datetime.fromtimestamp((tx.get("processDate") or 0) / 1000)
            out.append(Alert("trade_accepted",
                             f"Trade with {partner} accepted, processes {when:%a %b %d %I:%M %p}: {deal}"))
        elif kind in ("WAIVER", "FREEAGENT"):
            out.append(Alert("waiver", f"Pending claim: {', '.join(get) or '?'}"
                             + (f" (drop {', '.join(give)})" if give else "")))
    if include_chat:
        ppl = people(session)
        swid = session.client.swid
        for t in topics(session):
            unread = t.get("unreadMessageCount") or 0
            if t.get("type") == DM and unread:
                who = ", ".join(ppl.get(x, "someone") for x in t.get("viewableBy") or [] if x != swid)
                out.append(Alert("dm", f"{unread} unread message{'s' * (unread > 1)} from {who}",
                                 urgent=True))
    if include_spins:
        with contextlib.suppress(BenchbossError):
            out += spin_alerts(session)
    return out


# --- watch list spins -----------------------------------------------------------------------------

SEEN_FILE = "seen-news.json"  # {"<league id>": {"news": [ids, oldest first], "players": [ids]}}
SEEN_KEEP = 500               # news ids remembered per league
SPIN_DAYS = 3                 # how far back watch_spins looks
FIRST_RUN_HOURS = 24          # for a player new to the watch list, older news counts as seen

_seen_lock = threading.Lock()  # the app checks in a worker thread while screens read


def seen_path() -> Path:
    return config_mod.config_dir() / SEEN_FILE


def _read_seen() -> dict:
    """The seen file as a dict; a missing, unreadable or broken file reads as empty."""
    try:
        raw = json.loads(seen_path().read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_seen(book: dict) -> None:
    """Write the seen file atomically (a temp file, then a rename), like config.save."""
    path = seen_path()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(book) + "\n")
        tmp.replace(path)
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise BenchbossError(f"could not save the news you have seen to {path} ({e})") from e


def watch_spins(session, mark_seen: bool = False) -> list[tuple[str, NewsItem]]:
    """News ("spins") on your watch-list players that you have not seen yet, newest first,
    as (player name, NewsItem).

    What you have seen is kept per league in ``seen-news.json`` in the config folder: the
    newest ``SEEN_KEEP`` news ids, and the watch list as it was at the last recorded check.
    News on a player new to the list (every player, the first time a league is checked)
    older than ``FIRST_RUN_HOURS`` counts as seen, so neither a new install nor a player
    you just starred brings days of old news. Anything else not seen yet is new, however
    old (say the app was closed for two days). ``mark_seen=True`` records what this call
    returns, that older news and the list. ESPN errors propagate as BenchbossError.
    """
    watched = list(session.watch_list())
    if not watched:
        return []
    items = session.news(watched, SPIN_DAYS)
    key = str(session.client.league_id)
    with _seen_lock:
        book = _read_seen()
        entry = book.get(key)
        if isinstance(entry, list):  # the first format kept only the news ids
            entry = {"news": entry, "players": watched}
        if not isinstance(entry, dict):
            entry = {}
        news, players = entry.get("news"), entry.get("players")
        known = list(news) if isinstance(news, list) else []
        before = {x for x in players if isinstance(x, int)} if isinstance(players, list) else set()
        added = set(watched) - before
        if added:  # their older news counts as seen, unless it is on a player watched before
            cutoff = session.now - dt.timedelta(hours=FIRST_RUN_HOURS)
            known += [i.id for i in sorted(items, key=lambda i: i.published)
                      if i.published < cutoff and i.player_ids & set(watched) <= added]
        seen = {str(x) for x in known}
        new = sorted((i for i in items if str(i.id) not in seen),
                     key=lambda i: i.published, reverse=True)
        if mark_seen and (new or set(watched) != before):
            # oldest first, so the cap drops the oldest; ids compare as text, kept as given
            record = known + [i.id for i in reversed(new)]
            book[key] = {"news": list({str(x): x for x in record}.values())[-SEEN_KEEP:],
                         "players": watched}
            _write_seen(book)
    if not new:
        return []
    ids = set(watched)
    names = player_names(session, ids)
    out = []
    for item in new:
        who = [names.get(p, f"player {p}") for p in sorted(item.player_ids) if p in ids]
        out.append((", ".join(who) or "a watch-list player", item))
    return out


def spin_alerts(session, mark_seen: bool = False) -> list[Alert]:
    """One alert per unseen spin on a watch-list player (see ``watch_spins``), not urgent."""
    return [Alert("spin", f"Watch list · {who}: {item.headline}", news=item, player=who)
            for who, item in watch_spins(session, mark_seen)]

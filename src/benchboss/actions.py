"""Everything that changes your league on ESPN. Every function here is a real write.

The CLI and the TUI always show what will happen and ask before calling these, unless the
user passes ``--yes``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from benchboss.errors import BenchbossError, ConfigError
from benchboss.espn.models import Player, Team, parse_player
from benchboss.text import match_one, norm

# What send() returns when ESPN's answer has no status it uses (an upper-case word). ESPN has
# no status by that name, so it never hides a real one.
UNKNOWN_STATUS = "UNKNOWN"


def send(session, kind: str, items: list[dict], period: int, extra: dict | None = None) -> str:
    """POST one transaction; returns ESPN's status (EXECUTED, PENDING, FAILED_LINEUPLOCK, ...)
    or UNKNOWN_STATUS when the answer carries none: then nobody knows whether it went
    through. Never a piece of the raw answer."""
    lg = session.league()
    if session.client.swid not in lg.me.owner_ids:
        raise ConfigError(f"your ESPN account does not manage {lg.me.name}: run `benchboss setup` "
                          "or fix BENCHBOSS_TEAM_ID")
    body = {"isLeagueManager": False, "teamId": lg.my_team_id, "type": kind,
            "memberId": session.client.swid, "scoringPeriodId": period,
            "executionType": "EXECUTE", "items": items}
    body.update(extra or {})
    r = session.client.transaction(body)
    status = None
    if isinstance(r, dict):
        inner = r.get("transaction")
        status = r.get("status") or (inner.get("status") if isinstance(inner, dict) else None)
    if isinstance(status, str) and re.fullmatch(r"[A-Z_]+", status):
        return status
    return UNKNOWN_STATUS


@dataclass
class Pending:
    """A write that is ready to go: ``summary`` is what the user confirms."""
    summary: str
    kind: str
    items: list[dict]
    period: int
    extra: dict | None = None

    def run(self, session) -> str:
        return send(session, self.kind, self.items, self.period, self.extra)


def _find_free_agent(session, name: str) -> dict:
    lg = session.league()
    hits = session.client.players({"filterName": {"value": name},
                                   "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                                   "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                                   "limit": 10}, lg.scoring_period)
    exact = [x for x in hits if norm(x["player"]["fullName"]) == norm(name)]
    hits = exact if len(exact) == 1 else hits
    if not hits:
        raise BenchbossError(f"'{name}' is not a free agent or on waivers")
    if len(hits) > 1:
        raise BenchbossError(f"'{name}' matches several players: "
                             + ", ".join(x["player"]["fullName"] for x in hits))
    return hits[0]


def prepare_add(session, name: str, drop: str | None = None, bid: int | None = None) -> Pending:
    lg = session.league()
    x = _find_free_agent(session, name)
    kind = "WAIVER" if x.get("status") == "WAIVERS" else "FREEAGENT"
    if bid is not None and not lg.uses_faab:
        raise BenchbossError("your league has no waiver budget: leave out --bid")
    if kind == "WAIVER" and lg.uses_faab and (bid is None or bid < lg.minimum_bid):
        raise BenchbossError(f"{x['player']['fullName']} is on waivers and your league bids for "
                             f"them: add --bid N (at least {max(lg.minimum_bid, 0)})")
    items = [{"playerId": x["id"], "type": "ADD", "toTeamId": lg.my_team_id}]
    summary = f"{'Waiver claim' if kind == 'WAIVER' else 'Add'}: {x['player']['fullName']}"
    if drop:
        spot = lg.me.find(drop)
        items.append({"playerId": spot.player.id, "type": "DROP", "fromTeamId": lg.my_team_id})
        summary += f"   drop: {spot.player.name}"
    return Pending(summary, kind, items, lg.scoring_period, {"bidAmount": bid})


def prepare_drop(session, name: str) -> Pending:
    lg = session.league()
    spot = lg.me.find(name)
    return Pending(f"Drop: {spot.player.name}", "ROSTER",
                   [{"playerId": spot.player.id, "type": "DROP", "fromTeamId": lg.my_team_id}],
                   lg.scoring_period)


def _find_theirs(lg, name: str) -> tuple[Team, Player]:
    pairs = [(t, s.player) for t in lg.teams.values() if t.id != lg.my_team_id for s in t.roster]
    t, p = match_one(pairs, name, lambda tp: tp[1].name, where="any other roster")
    return t, p


def prepare_trade(session, give: list[str], get: list[str], message: str = "") -> Pending:
    lg = session.league()
    mine = [lg.me.find(q).player for q in give]
    theirs = [_find_theirs(lg, q) for q in get]
    partners = {t.id for t, _ in theirs}
    if len(partners) != 1:
        raise BenchbossError("everything you ask for must come from one team")
    to = partners.pop()
    items = ([{"playerId": p.id, "type": "TRADE", "fromTeamId": lg.my_team_id, "toTeamId": to}
              for p in mine] +
             [{"playerId": p.id, "type": "TRADE", "fromTeamId": to, "toTeamId": lg.my_team_id}
              for _, p in theirs])
    summary = (f"Trade offer to {lg.teams[to].name}: give {', '.join(p.name for p in mine)}, "
               f"get {', '.join(p.name for _, p in theirs)}")
    if message:
        summary += f"\nmessage: {message}"
    return Pending(summary, "TRADE_PROPOSAL", items, lg.scoring_period, {"comment": message or ""})


def refresh_player(session, player_id: int) -> Player:
    lg = session.league()
    hits = session.client.players({"filterIds": {"value": [player_id]}}, lg.scoring_period)
    if not hits:
        raise BenchbossError(f"player {player_id} not found")
    return parse_player(hits[0], lg.season)

"""Trade finder: fair 1-for-1 deals that fix a positional hole on both sides.

For every team we build a positional profile: the projected points per game it has at PG,
SG, SF, PF and C (a multi-position player counts a share at each position). Comparing each
team with the league average shows its surplus and its needs. A suggestion pairs a player
from a position where you are deep and they are thin with one from a position where they are
deep and you are thin, at a similar value, and respects the league's position limits
(for example, no more than four centers).
"""

from __future__ import annotations

from dataclasses import dataclass

from benchboss.espn.constants import IR, POSITION, POSITION_SLOTS, POSITION_TO_SLOT, SLOT
from benchboss.espn.models import League, Player, Team

POSITIONS = [SLOT[s] for s in POSITION_SLOTS]  # PG SG SF PF C


def profile(team: Team) -> dict[str, float]:
    out = dict.fromkeys(POSITIONS, 0.0)
    for s in team.roster:
        if s.slot_id == IR:
            continue
        pos = [SLOT[x] for x in s.player.eligible_slots if x in POSITION_SLOTS]
        for p in pos:
            out[p] += s.player.proj / len(pos)
    return out


def league_profiles(league: League) -> tuple[dict[int, dict[str, float]], dict[str, float]]:
    profiles = {tid: profile(t) for tid, t in league.teams.items()}
    n = max(1, len(profiles))
    avg = {p: sum(pr[p] for pr in profiles.values()) / n for p in POSITIONS}
    return profiles, avg


def balance(prof: dict[str, float], avg: dict[str, float]) -> dict[str, float]:
    """Positive = surplus over the league average, negative = need."""
    return {p: prof[p] - avg[p] for p in POSITIONS}


@dataclass
class TradeIdea:
    partner: Team
    give: Player
    get: Player
    give_pos: str
    get_pos: str
    fairness: float   # 1.0 = identical projected value
    score: float
    they_need_give: bool = True   # partner is below the league average at give_pos
    they_deep_get: bool = True    # partner is above the league average at get_pos
    i_need_get: bool = True       # I am below the league average at get_pos

    def message(self) -> str:
        """A short pitch that only claims what the numbers support."""
        owner = self.partner.owner_name.split()[0] if self.partner.owner_name else "there"
        reasons = []
        if self.they_need_give:
            reasons.append(f"you could use help at {self.give_pos}")
        if self.they_deep_get:
            reasons.append(f"you are deep at {self.get_pos}")
        why = (" and ".join(reasons) + ". ") if reasons else ""
        why = why[:1].upper() + why[1:]
        mine = f"I need a {self.get_pos}. " if self.i_need_get else ""
        return (f"Hey {owner}! {why}{mine}{self.give.name} for {self.get.name} is close in "
                f"value and helps both of us. Interested?").replace("! . ", "! ")

    def to_dict(self) -> dict:
        return {"partner": self.partner.name, "owner": self.partner.owner_name,
                "give": self.give.to_dict(), "get": self.get.to_dict(),
                "give_pos": self.give_pos, "get_pos": self.get_pos,
                "fairness": round(self.fairness, 3), "score": round(self.score, 2),
                "message": self.message()}


def _primary(p: Player) -> str | None:
    slot = POSITION_TO_SLOT.get(p.position_id)
    return SLOT[slot] if slot is not None else None


def _count_position(team: Team, position_id: int) -> int:
    return sum(1 for s in team.roster if s.player.position_id == position_id)


def _within_limits(league: League, team: Team, out: Player, incoming: Player) -> bool:
    limit = league.position_limits.get(incoming.position_id, -1)
    if limit is None or limit < 0 or incoming.position_id == out.position_id:
        return True
    return _count_position(team, incoming.position_id) + 1 <= limit


def find_trades(league: League, need: str | None = None, partner_id: int | None = None,
                min_fairness: float = 0.85, limit: int = 10) -> list[TradeIdea]:
    profiles, avg = league_profiles(league)
    me = league.me
    mine = balance(profiles[me.id], avg)
    ideas: list[TradeIdea] = []
    for tid, team in league.teams.items():
        if tid == me.id or (partner_id and tid != partner_id):
            continue
        theirs = balance(profiles[tid], avg)
        for gs in me.roster:
            give = gs.player
            gp = _primary(give)
            if gs.slot_id == IR or not gp or mine[gp] <= 0 or theirs[gp] >= 0:
                continue
            for ts in team.roster:
                get = ts.player
                tp = _primary(get)
                if ts.slot_id == IR or not tp or tp == gp:
                    continue
                if need and tp != need.upper():
                    continue
                if not need and (mine[tp] >= 0 or theirs[tp] <= 0):
                    continue
                hi = max(give.proj, get.proj)
                if hi <= 0:
                    continue
                fair = 1 - abs(give.proj - get.proj) / hi
                if fair < min_fairness:
                    continue
                if not (_within_limits(league, me, give, get) and
                        _within_limits(league, team, get, give)):
                    continue
                fit = (-mine[tp] if mine[tp] < 0 else 0) + (-theirs[gp] if theirs[gp] < 0 else 0)
                scale = max(1.0, sum(avg.values()) / len(avg))
                score = fair * 10 + 5 * fit / scale + (get.proj - give.proj) / 10
                ideas.append(TradeIdea(team, give, get, gp, tp, fair, score,
                                       they_need_give=theirs[gp] < 0, they_deep_get=theirs[tp] > 0,
                                       i_need_get=mine[tp] < 0))
    ideas.sort(key=lambda t: -t.score)
    out: list[TradeIdea] = []
    for t in ideas:  # keep the list varied: two ideas per partner, two per player you give
        if sum(x.partner.id == t.partner.id for x in out) >= 2:
            continue
        if sum(x.give.id == t.give.id for x in out) >= 2:
            continue
        out.append(t)
        if len(out) >= limit:
            break
    return out


def describe_needs(league: League) -> dict[str, dict[str, float]]:
    """Team name -> positional balance (for the trade screen and --json)."""
    profiles, avg = league_profiles(league)
    return {league.teams[tid].name: {k: round(v, 1) for k, v in balance(pr, avg).items()}
            for tid, pr in profiles.items()}


__all__ = ["POSITIONS", "POSITION", "TradeIdea", "find_trades", "describe_needs", "profile"]

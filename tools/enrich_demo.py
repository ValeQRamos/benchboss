"""Enrich the demo dataset (src/benchboss/demo/data.json.gz) for the stats and standings screens.

tools/make_demo.py keeps only ``appliedAverage``/``appliedTotal`` per stat split. This script
reads the dataset, adds the rest in ESPN's raw shapes and writes it back:

- Every player object (rosters, free agents, trending): last season's actual box score
  (``002026``) and this season's ESPN projection (``102027``) with ``averageStats`` and
  ``stats``, plus fresh ``ownership``, ``jersey`` and ``droppable``. These are real: they are
  fetched once from ESPN (the stats are public; any league's cookies work) and cached in
  tools/.demo-cache/players.json, so later runs work offline. The demo's points per game do
  not move: the lineup and trash tests depend on them (see ``real_split``).
- Every player with a projection: a synthesized 2027 game log for the games his NBA team
  played before the demo day (period 16), written as the season, last 7, last 15 and last 30
  day splits (``002027``, ``012027``, ``022027``, ``032027``).
- The league: a proper double round robin for the weeks still to play (make_demo.py repeats
  one set of pairs from week 10 on), matchup ids and winners, two divisions, full records
  (overall, home, away, division; from the decided weeks 1 and 2) with points against, games
  back and streaks, waiver order, transaction counters, playoff odds from a seeded Monte Carlo
  (``currentSimulationResults``) and a watch list on the demo user's team.

    python tools/enrich_demo.py              # offline once tools/.demo-cache/players.json exists
    python tools/enrich_demo.py --refetch    # ask ESPN again (needs `benchboss setup` done)

The output depends only on the input file, the cache and fixed seeds: running it twice in a
row gives a byte-identical file.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import itertools
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/benchboss/demo/data.json.gz"
CACHE = ROOT / "tools/.demo-cache/players.json"
SEED = 2027
SEASON = 2027
LAST = SEASON - 1
SIMS = 10_000

# ESPN basketball stat ids kept on every split. Percentages are fractions; in averageStats 40
# is minutes per game, 41 games started per game and 42 games played (ESPN's own convention).
STAT_IDS = ("0", "1", "2", "3", "4", "5", "6", "9", "11", "13", "14", "15", "16", "17", "18",
            "19", "20", "21", "37", "38", "40", "41", "42")
PCT = {"19": ("13", "14"), "20": ("15", "16"), "21": ("17", "18")}  # made / attempted
HEADER = ("id", "seasonId", "statSourceId", "statSplitTypeId", "scoringPeriodId")


# --- ESPN fetch (once, cached) -------------------------------------------------------------------

def all_players(data: dict) -> list[dict]:
    """Every player object in the dataset, copies included."""
    out = [e["playerPoolEntry"]["player"] for t in data["league"]["teams"]
           for e in t["roster"]["entries"]]
    return out + [x["player"] for x in data["free_agents"] + data["trending"]]


def fetch(ids: list[int]) -> dict[str, dict]:
    """kona_player_info for these ids: last season, projection, ownership. Never logs cookies."""
    sys.path.insert(0, str(ROOT / "src"))
    from benchboss.service import Session

    client = Session().client
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        flt = {"filterIds": {"value": chunk}, "limit": len(chunk),
               "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
               "filterStatsForTopScoringPeriodIds": {
                   "value": 2, "additionalValue": [f"00{LAST}", f"10{SEASON}"]}}
        for x in client.players(flt, 1):
            out[str(x["id"])] = x["player"]  # the player only: no league-specific wrapper fields
    return out


def load_cache(ids: list[int], refetch: bool) -> dict[str, dict]:
    if refetch or not CACHE.exists():
        players = fetch(ids)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"fetched": dt.date.today().isoformat(), "players": players},
                                    sort_keys=True))
        print(f"fetched {len(players)} of {len(ids)} players from ESPN into {CACHE}")
    players = json.loads(CACHE.read_text())["players"]
    missing = [i for i in ids if str(i) not in players]
    if missing:
        print(f"warning: no ESPN data for {len(missing)} players: {missing}")
    return players


# --- stat splits ---------------------------------------------------------------------------------

def scoring(data: dict) -> dict[str, float]:
    items = data["league"]["settings"]["scoringSettings"]["scoringItems"]
    return {str(it["statId"]): float(it["points"]) for it in items}


def fpts(stats: dict, points: dict[str, float]) -> float:
    return sum(pts * float(stats.get(sid, 0.0)) for sid, pts in points.items())


def header(source: int, split: int, season: int) -> dict:
    return {"id": f"{source}{split}{season}", "seasonId": season, "statSourceId": source,
            "statSplitTypeId": split, "scoringPeriodId": 0}


def trim(d: dict | None) -> dict:
    d = d or {}
    return {k: d[k] for k in STAT_IDS if k in d}


def real_split(demo: dict, got: dict | None, source: int, season: int,
               points: dict[str, float]) -> dict:
    """``002026`` or ``102027``: the demo's points per game plus ESPN's box score.

    The demo keeps its ``appliedAverage``/``appliedTotal`` (projections drive the lineup and
    trash tests). ESPN's ``averageStats`` are kept as fetched when the league scoring applied to
    them lands within 0.5 of the demo's points per game (true for every player at build time:
    the projections had not moved). Otherwise every counting stat, minutes included, is scaled
    by the same factor (percentages keep their value) and the totals are rebuilt with the
    demo's games, so the box score always adds up to the demo's points.
    """
    avg_pts, total = demo.get("appliedAverage") or 0.0, demo.get("appliedTotal") or 0.0
    out = {**header(source, 0, season), "appliedAverage": avg_pts, "appliedTotal": total,
           "averageStats": {}, "stats": {}}
    avg, tot = trim((got or {}).get("averageStats")), trim((got or {}).get("stats"))
    if not total or not avg:
        return out
    applied = fpts(avg, points)
    if abs(applied - avg_pts) > 0.5 and applied > 0:
        r = avg_pts / applied
        gp = round(total / avg_pts)
        avg = {k: v if k in PCT or k in ("41", "42") else round(v * r, 4) for k, v in avg.items()}
        avg["42"] = float(gp)
        tot = {k: v if k in PCT else float(round(avg[k] * gp)) for k, v in avg.items()}
        tot["42"] = float(gp)
        print(f"  {demo['id']}: box score scaled by {r:.3f} ({applied:.2f} -> {avg_pts:.2f} "
              "points per game)")
    out["averageStats"], out["stats"] = avg, tot
    return out


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 40:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def binom(rng: random.Random, n: int, p: float) -> int:
    p = min(max(p, 0.0), 1.0)
    return sum(rng.random() < p for _ in range(n))


def clip(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


def box_score(rng: random.Random, proj: dict, form: float, shape: dict) -> dict:
    """One game around the projection. Shots are drawn make by make, so FGM <= FGA,
    3PM <= 3PA <= FGA, FTM <= FTA and PTS = 2 * FGM + 3PM + FTM hold exactly."""
    def a(k):
        return float(proj.get(k, 0.0))

    mpg = a("40") or 20.0
    mins = int(clip(round(mpg * clip(rng.gauss(1.0, 0.15), 0.5, 1.4)), 1, 48))
    s = mins / mpg * form
    heat = clip(rng.gauss(1.0, 0.08), 0.75, 1.25)  # a hot or cold shooting night
    fga = poisson(rng, a("14") * s)
    tpa = binom(rng, fga, a("18") / a("14") if a("14") else 0.0)
    p3 = a("21") or (a("17") / a("18") if a("18") else 0.35)
    p2 = (a("13") - a("17")) / (a("14") - a("18")) if a("14") > a("18") else 0.5
    tpm = binom(rng, tpa, p3 * heat)
    fgm = tpm + binom(rng, fga - tpa, p2 * heat)
    fta = poisson(rng, a("16") * s)
    ftm = binom(rng, fta, a("20") or 0.75)
    reb = poisson(rng, a("6") * s)
    oreb = binom(rng, reb, shape["oreb"])
    ast, stl, blk, to = (poisson(rng, a(k) * s) for k in ("3", "2", "1", "11"))
    pf = min(6, poisson(rng, shape["pf"] * mins / mpg))
    pts = 2 * fgm + tpm + ftm
    tens = sum(v >= 10 for v in (pts, reb, ast, stl, blk))
    return {"0": pts, "1": blk, "2": stl, "3": ast, "4": oreb, "5": reb - oreb, "6": reb, "9": pf,
            "11": to, "13": fgm, "14": fga, "15": ftm, "16": fta, "17": tpm, "18": tpa,
            "37": int(tens >= 2), "38": int(tens >= 3), "40": mins,
            "41": int(rng.random() < shape["gs"]), "42": 1}


def player_shape(proj: dict, last: dict, position: int) -> dict:
    """What the projection lacks (offensive boards, fouls, starts), from last season."""
    mpg = float(proj.get("40") or 20.0)
    if last.get("6"):
        oreb = last.get("4", 0.0) / last["6"]
    else:
        oreb = {5: 0.25, 4: 0.2}.get(position, 0.12)
    pf = last.get("9") if last.get("42") else 2.0 * mpg / 30
    gs = last.get("41") if last.get("42") else (0.9 if mpg >= 28 else 0.4 if mpg >= 22 else 0.05)
    return {"oreb": clip(oreb, 0.03, 0.5), "pf": pf or 1.0, "gs": clip(gs or 0.0, 0.0, 1.0)}


def window_split(split: int, games: list[dict], points: dict[str, float]) -> dict:
    out = header(0, split, SEASON)
    if not games:  # ESPN's "no data": zero points and empty stats
        return {**out, "appliedAverage": 0.0, "appliedTotal": 0.0, "averageStats": {}, "stats": {}}
    gp = len(games)
    tot = {k: sum(g[k] for g in games) for k in STAT_IDS if k not in PCT}
    for k, (made, att) in PCT.items():
        tot[k] = tot[made] / tot[att] if tot[att] else 0.0
    stats = {k: round(float(tot[k]), 4) for k in STAT_IDS}
    avg = {k: (stats[k] if k in PCT or k == "42" else round(tot[k] / gp, 4)) for k in STAT_IDS}
    total = fpts(stats, points)
    return {**out, "appliedAverage": total / gp, "appliedTotal": total, "averageStats": avg,
            "stats": stats}


def synthesize(p: dict, proj: dict, last: dict, team_games: list[int], today_sp: int,
               points: dict[str, float]) -> list[dict]:
    """The four 2027 splits from a seeded game log through yesterday."""
    rng = random.Random(f"{SEED}-log-{p['id']}")
    if p.get("injuryStatus") == "OUT":  # hurt in the first days, has sat since
        played = team_games[:rng.randint(0, 3)]
    else:
        played = [sp for sp in team_games if rng.random() >= 0.05]
    target = fpts(proj, points)
    shape = player_shape(proj, last, p.get("defaultPositionId") or 0)
    log: list[tuple[int, dict]] = []
    for _ in range(200):  # a hot or cold start, but within 25% of the projection
        form = clip(rng.gauss(1.0, 0.07), 0.85, 1.15)
        log = [(sp, box_score(rng, proj, form, shape)) for sp in played]
        if not log or not target:
            break
        got = sum(fpts({k: float(v) for k, v in g.items()}, points) for _, g in log) / len(log)
        if abs(got / target - 1) <= 0.25:
            break
    windows = ((0, 1), (1, today_sp - 7), (2, today_sp - 15), (3, today_sp - 30))
    return [window_split(split, [g for sp, g in log if sp >= first], points)
            for split, first in windows]


def enrich_players(data: dict, cache: dict[str, dict]) -> None:
    points = scoring(data)
    today_sp = data["league"]["scoringPeriodId"]
    games = {t["id"]: sorted(int(sp) for sp in t["proGamesByScoringPeriod"] if int(sp) < today_sp)
             for t in data["schedule"]["settings"]["proTeams"]}
    done: dict[int, list[dict]] = {}
    for p in all_players(data):
        pid = p["id"]
        got = cache.get(str(pid)) or {}
        if pid not in done:
            have = {s["id"]: s for s in p.get("stats") or []}
            fetched = {s.get("id"): s for s in got.get("stats") or []}
            stats = [real_split(have[sid], fetched.get(sid), src, season, points)
                     for sid, src, season in ((f"00{LAST}", 0, LAST), (f"10{SEASON}", 1, SEASON))
                     if sid in have]
            proj = next((s["averageStats"] for s in stats if s["statSourceId"] == 1), {})
            last = next((s["averageStats"] for s in stats if s["statSourceId"] == 0), {})
            team_games = games.get(p.get("proTeamId") or 0, []) if proj else []
            done[pid] = stats + synthesize(p, proj, last, team_games, today_sp, points)
        p["stats"] = json.loads(json.dumps(done[pid]))  # every copy equal, none shared
        if got.get("ownership"):
            p["ownership"] = got["ownership"]
        for k in ("jersey", "droppable"):
            if k in got:
                p[k] = got[k]
    # pools in ESPN's order for their sort: free agents by ownership, trending by change
    data["free_agents"].sort(key=lambda x: -x["player"]["ownership"]["percentOwned"])
    data["trending"].sort(key=lambda x: -x["player"]["ownership"]["percentChange"])


# --- league: schedule, records, odds -------------------------------------------------------------

def proj_of(p: dict) -> float:
    return next((s.get("appliedAverage") or 0.0 for s in p.get("stats") or []
                 if s.get("id") == f"10{SEASON}"), 0.0)


def strength(team: dict) -> float:
    """Sum of the 10 best projections: a team's expected output on a full slate."""
    projs = sorted((proj_of(e["playerPoolEntry"]["player"]) for e in team["roster"]["entries"]),
                   reverse=True)
    return sum(projs[:10])


def streak(outcomes: list[str]) -> tuple[str, int]:
    if not outcomes:
        return "NONE", 0
    last, n = outcomes[-1], 0
    for o in reversed(outcomes):
        if o != last:
            break
        n += 1
    return {"W": "WIN", "L": "LOSS", "T": "TIE"}[last], n


def record_block(games: list[tuple[float, float, str]]) -> dict:
    w = sum(o == "W" for _, _, o in games)
    lo = sum(o == "L" for _, _, o in games)
    t = sum(o == "T" for _, _, o in games)
    pf = pa = 0.0
    for f, a, _ in games:  # rounded as it accumulates, like make_demo.py's pointsFor
        pf, pa = round(pf + f, 1), round(pa + a, 1)
    kind, n = streak([o for _, _, o in games])
    return {"wins": w, "losses": lo, "ties": t,
            "percentage": round((w + t / 2) / len(games), 4) if games else 0.0,
            "pointsFor": pf, "pointsAgainst": pa, "gamesBack": 0.0,
            "streakLength": n, "streakType": kind}


def games_back(blocks: list[dict]) -> None:
    if not blocks:
        return
    lead = max(blocks, key=lambda b: (b["wins"] - b["losses"], b["pointsFor"]))
    for b in blocks:
        b["gamesBack"] = max(0.0, ((lead["wins"] - b["wins"]) + (b["losses"] - lead["losses"])) / 2)


def round_robin(lg: dict) -> None:
    """Re-pair the weeks after the current one. make_demo.py's rotation wraps after week 9
    (the same five pairs every week from week 10 on). Weeks 1-9 are rounds 1-9 of a proper
    round robin; weeks 10-18 repeat them with home and away swapped and weeks 19-20 repeat
    rounds 1-2. Weeks up to the current one stay exactly as they are."""
    current = lg["status"]["currentMatchupPeriod"]
    weeks = lg["settings"]["scheduleSettings"]["matchupPeriodCount"]
    teams = sorted(t["id"] for t in lg["teams"])
    n = len(teams) - 1
    rounds = {r: [(g["home"]["teamId"], g["away"]["teamId"]) for g in lg["schedule"]
                  if g["matchupPeriodId"] == r] for r in range(1, n + 1)}
    pairs = {frozenset(p) for r in rounds.values() for p in r}
    if len(pairs) != len(teams) * n // 2 or any(sorted(x for p in r for x in p) != teams
                                                 for r in rounds.values()):
        raise SystemExit(f"weeks 1-{n} of the schedule are not a round robin")

    def side(tid: int) -> dict:
        return {"teamId": tid, "totalPoints": 0, "totalPointsLive": 0, "pointsByScoringPeriod": {}}

    kept = [g for g in lg["schedule"] if g["matchupPeriodId"] <= current]
    for w in range(current + 1, weeks + 1):
        swap = (w - 1) // n % 2 == 1
        for h, a in rounds[(w - 1) % n + 1]:
            h, a = (a, h) if swap else (h, a)
            kept.append({"matchupPeriodId": w, "home": side(h), "away": side(a)})
    lg["schedule"] = kept


def enrich_schedule(lg: dict) -> dict[int, list[tuple[int, str, int, float, float, str]]]:
    """Fixed pairings, ids, winners and tiers on every matchup; returns each team's decided
    games (weeks before the current one) in order as (week, HOME or AWAY, opponent, points
    for, points against, W/L/T)."""
    round_robin(lg)
    current = lg["status"]["currentMatchupPeriod"]
    played: dict[int, list] = collections.defaultdict(list)
    for i, g in enumerate(lg["schedule"]):
        h, a = g["home"], g["away"]
        week = g["matchupPeriodId"]
        winner = "UNDECIDED"
        if week < current:
            hp, ap = h["totalPoints"], a["totalPoints"]
            winner = "HOME" if hp > ap else "AWAY" if ap > hp else "TIE"
            ho = {"HOME": "W", "AWAY": "L", "TIE": "T"}[winner]
            ao = {"W": "L", "L": "W", "T": "T"}[ho]
            played[h["teamId"]].append((week, "HOME", a["teamId"], hp, ap, ho))
            played[a["teamId"]].append((week, "AWAY", h["teamId"], ap, hp, ao))
        lg["schedule"][i] = {"id": i + 1, "matchupPeriodId": week, "playoffTierType": "NONE",
                             "winner": winner, "home": h, "away": a}
    return played


def assign_divisions(lg: dict, power: dict[int, float]) -> dict[int, int]:
    """East (0) and West (1), five teams each. The two strongest teams and the two weakest
    are split up, and about 4 of the 10 matchups played so far are division games (a real
    10-team schedule has 4 of 9 opponents in the division); then the closest total strength."""
    teams = sorted(power)
    ranked = sorted(teams, key=lambda t: (-power[t], t))
    pairs = [(g["home"]["teamId"], g["away"]["teamId"]) for g in lg["schedule"]
             if g["winner"] != "UNDECIDED"]
    best = None
    for east in itertools.combinations(teams, 5):
        e = set(east)
        if ranked[0] not in e or ranked[1] in e or (ranked[-1] in e) == (ranked[-2] in e):
            continue
        rivals = sum((h in e) == (a in e) for h, a in pairs)
        gap = abs(sum(power[t] for t in teams if t in e) - sum(power[t] for t in teams if t not in e))
        key = (abs(rivals - 4), round(gap, 6), east)
        best = key if best is None else min(best, key)
    return {t: 0 if t in best[2] else 1 for t in teams}


def simulate(lg: dict, power: dict[int, float], division: dict[int, int],
             played: dict[int, list], today: dt.date) -> dict[int, dict]:
    """Seeded Monte Carlo of the rest of the regular season (current week included)."""
    rng = random.Random(f"{SEED}-sim")
    current = lg["status"]["currentMatchupPeriod"]
    weeks = lg["settings"]["scheduleSettings"]["matchupPeriodCount"]
    full = [g for g in lg["schedule"] if g["matchupPeriodId"] == current - 1]
    per_point = sum(g[s]["totalPoints"] / power[g[s]["teamId"]] for g in full
                    for s in ("home", "away")) / (2 * len(full))
    days_left = 7 - today.weekday()
    teams = sorted(power)
    base = {t: (sum(1 for x in played[t] if x[5] == "W"), sum(1 for x in played[t] if x[5] == "L"),
                sum(x[3] for x in played[t]), sum(x[4] for x in played[t]),
                [x[5] for x in played[t]]) for t in teams}
    rest = [g for g in lg["schedule"] if current <= g["matchupPeriodId"] <= weeks]
    in_playoffs = collections.Counter()
    won_division = collections.Counter()
    rank_sum = collections.Counter()
    records = {t: collections.Counter() for t in teams}
    finals: dict[int, dict] = {t: collections.defaultdict(collections.Counter) for t in teams}
    pf_sum, pa_sum = collections.Counter(), collections.Counter()
    for _ in range(SIMS):
        form = {t: power[t] * clip(rng.gauss(1.0, 0.04), 0.85, 1.15) for t in teams}
        w = {t: base[t][0] for t in teams}
        lo = {t: base[t][1] for t in teams}
        pf = {t: base[t][2] for t in teams}
        pa = {t: base[t][3] for t in teams}
        seq = {t: list(base[t][4]) for t in teams}
        for g in rest:
            score = {}
            for side in ("home", "away"):
                tid = g[side]["teamId"]
                if g["matchupPeriodId"] == current:
                    mean = form[tid] * per_point * days_left / 7
                    score[tid] = g[side]["totalPoints"] + rng.gauss(mean, 0.09 * mean)
                else:
                    mean = form[tid] * per_point
                    score[tid] = rng.gauss(mean, 0.09 * mean)
            h, a = g["home"]["teamId"], g["away"]["teamId"]
            win, lose = (h, a) if score[h] > score[a] else (a, h)
            w[win] += 1
            lo[lose] += 1
            seq[win].append("W")
            seq[lose].append("L")
            for t, o in ((h, a), (a, h)):
                pf[t] += score[t]
                pa[t] += score[o]
        order = sorted(teams, key=lambda t: (-w[t], -pf[t]))
        leaders = [next(t for t in order if division[t] == d) for d in (0, 1)]
        field = leaders + [t for t in order if t not in leaders][:2]
        for i, t in enumerate(order, 1):
            rank_sum[t] += i
            records[t][(w[t], lo[t])] += 1
            finals[t][(w[t], lo[t])][streak(seq[t])] += 1
            pf_sum[t] += pf[t]
            pa_sum[t] += pa[t]
        in_playoffs.update(field)
        won_division.update(leaders)
    rank = {t: i for i, t in enumerate(sorted(teams, key=lambda t: (rank_sum[t], t)), 1)}
    mode = {t: records[t].most_common(1)[0][0] for t in teams}
    best = max(mode.values(), key=lambda r: r[0] - r[1])
    out = {}
    for t in teams:
        mw, ml = mode[t]
        kind, n = finals[t][mode[t]].most_common(1)[0][0]
        out[t] = {
            "playoffPct": round(in_playoffs[t] / SIMS, 4),
            "divisionWinPct": round(won_division[t] / SIMS, 4),
            "rank": rank[t],
            "modeRecord": {"wins": mw, "losses": ml, "ties": 0,
                           "percentage": round(mw / (mw + ml), 4),
                           "pointsFor": round(pf_sum[t] / SIMS, 1),
                           "pointsAgainst": round(pa_sum[t] / SIMS, 1),
                           "gamesBack": ((best[0] - mw) + (ml - best[1])) / 2,
                           "streakLength": n, "streakType": kind},
            "playoffClinchType": "UNKNOWN",
        }
    return out


def transaction_counter(team_id: int, waiver_claim: bool) -> dict:
    """At most one pickup per matchup week so far (small numbers, early season)."""
    rng = random.Random(f"{SEED}-tx-{team_id}")
    weeks = [w for w in (1, 2, 3) if rng.random() < 0.45 or (w == 3 and waiver_claim)]
    return {"acquisitions": len(weeks), "drops": len(weeks), "trades": 0,
            "moveToActive": rng.randint(6, 30), "moveToIR": 0, "acquisitionBudgetSpent": 0,
            "misc": 0, "paid": 0.0, "teamCharges": 0.0,
            "matchupAcquisitionTotals": {str(w): 1 for w in weeks}}


def watch_list(data: dict) -> list[int]:
    """Four free agents: the most owned, the fastest riser and two deep cuts."""
    fas = [x["player"] for x in data["free_agents"]]
    ok = [p for p in fas if p.get("injuryStatus") != "OUT" and p.get("proTeamId") and proj_of(p)]
    top = ok[0]
    rising = max((p for p in ok if p["id"] != top["id"]),
                 key=lambda p: (p["ownership"]["percentChange"], proj_of(p)))
    deep = sorted((p for p in ok if p["id"] not in (top["id"], rising["id"])
                   and p["ownership"]["percentOwned"] < 10), key=lambda p: (-proj_of(p), p["id"]))
    return [top["id"], rising["id"]] + [p["id"] for p in deep[:2]]


def enrich_league(data: dict) -> None:
    lg = data["league"]
    teams = {t["id"]: t for t in lg["teams"]}
    power = {tid: strength(t) for tid, t in teams.items()}
    played = enrich_schedule(lg)
    division = assign_divisions(lg, power)

    blocks: dict[str, dict[int, dict]] = {k: {} for k in ("overall", "home", "away", "division")}
    for tid in teams:
        games = played[tid]
        blocks["overall"][tid] = record_block([(f, a, o) for _, _, _, f, a, o in games])
        for side in ("HOME", "AWAY"):
            blocks[side.lower()][tid] = record_block([(f, a, o) for _, s, _, f, a, o in games
                                                      if s == side])
        blocks["division"][tid] = record_block([(f, a, o) for _, _, opp, f, a, o in games
                                                if division[opp] == division[tid]])
    for kind in ("overall", "home", "away"):
        games_back(list(blocks[kind].values()))
    for d in (0, 1):
        games_back([b for tid, b in blocks["division"].items() if division[tid] == d])

    odds = simulate(lg, power, division, played, dt.date.fromisoformat(data["today"]))
    worst_first = sorted(teams, key=lambda t: (blocks["overall"][t]["wins"],
                                               blocks["overall"][t]["pointsFor"], t))
    claimer = lg["teams"][4]["id"]  # the waiver report in the demo league chat
    for tid, t in teams.items():
        old = t["record"]["overall"]
        new = blocks["overall"][tid]
        if (old["wins"], old["losses"], old["pointsFor"]) != (new["wins"], new["losses"],
                                                              new["pointsFor"]):
            raise SystemExit(f"team {tid}: the schedule does not add up to its record {old}")
        t["divisionId"] = division[tid]
        t["record"] = {k: blocks[k][tid] for k in ("overall", "home", "away", "division")}
        t["waiverRank"] = worst_first.index(tid) + 1
        t["transactionCounter"] = transaction_counter(tid, tid == claimer)
        t["playoffClinchType"] = "UNKNOWN"
        t["currentSimulationResults"] = odds[tid]
        t.pop("watchList", None)
    teams[data["my_team_id"]]["watchList"] = watch_list(data)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refetch", action="store_true", help="fetch the players from ESPN again")
    args = ap.parse_args(argv)
    data = json.loads(gzip.decompress(DATA.read_bytes()))
    before = DATA.stat().st_size
    ids = sorted({p["id"] for p in all_players(data)})
    enrich_players(data, load_cache(ids, args.refetch))
    enrich_league(data)
    raw = json.dumps(data, separators=(",", ":")).encode()
    DATA.write_bytes(gzip.compress(raw, 9, mtime=0))  # mtime 0: the same input, the same bytes
    print(f"wrote {DATA} ({before // 1024} KB -> {DATA.stat().st_size // 1024} KB, "
          f"{len(ids)} players)")


if __name__ == "__main__":
    main()

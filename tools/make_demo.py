"""Build the anonymized demo dataset shipped in src/benchboss/demo/data.json.gz.

Input: raw ESPN payloads saved from a real league (league views, season schedule, free
agents). Output: the same structures with fictional league, team and manager names, ids
replaced, and synthetic scores so the demo looks like a live mid-season week.

    python tools/make_demo.py league.json schedule.json free_agents.json trending.json

Player names, NBA teams, projections and the NBA schedule are public data and are kept.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import random
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/benchboss/demo/data.json.gz"
DEMO_TODAY = dt.date(2026, 11, 4)      # Wednesday of matchup week 3
DEMO_LEAGUE_ID = 424242
DEMO_SWID = "{00000000-0000-4000-8000-000000000001}"
TEAM_NAMES = ["Monstars", "Tune Squad", "Pick and Roll Pros", "Fast Break Cartel", "Swish Kebab",
              "The Alley Oops", "Brick City", "Full Court Press", "Splash Mountain", "Rim Rockers"]
MANAGERS = ["Alex Rivera", "Jordan Lee", "Sam Patel", "Chris Moreno", "Taylor Kim", "Drew Garza",
            "Morgan Cruz", "Jamie Ortiz", "Casey Nguyen", "Riley Santos"]
KEEP_STATS = ("002026", "002027", "012027", "022027", "102027")


def trim_player(p: dict, season_avg: bool = True) -> dict:
    keep = ("id", "fullName", "firstName", "lastName", "proTeamId", "defaultPositionId",
            "eligibleSlots", "injuryStatus", "injured", "ownership", "active")
    out = {k: p[k] for k in keep if k in p}
    out["stats"] = [{k: s.get(k) for k in ("id", "appliedAverage", "appliedTotal")}
                    for s in p.get("stats") or [] if s.get("id") in KEEP_STATS]
    return out


def main(league_path, schedule_path, fa_path, trending_path):
    rnd = random.Random(2027)
    league = json.loads(Path(league_path).read_text())
    sched = json.loads(Path(schedule_path).read_text())
    fas = json.loads(Path(fa_path).read_text())["players"]
    trending = json.loads(Path(trending_path).read_text())["players"]

    # --- schedule: only what the calendar needs
    teams_out = []
    for t in sched["settings"]["proTeams"]:
        games = {sp: [{k: g[k] for k in ("date", "homeProTeamId", "awayProTeamId", "scoringPeriodId", "id")}
                      for g in items] for sp, items in (t.get("proGamesByScoringPeriod") or {}).items()}
        teams_out.append({"id": t["id"], "abbrev": t["abbrev"], "proGamesByScoringPeriod": games})
    schedule = {"settings": {"proTeams": teams_out}}

    games_by_team: dict[int, set[int]] = {t["id"]: {int(sp) for sp in t["proGamesByScoringPeriod"]}
                                          for t in teams_out}
    first = min(g["date"] for t in teams_out for items in t["proGamesByScoringPeriod"].values()
                for g in items if g["scoringPeriodId"] == 1)
    day_one = dt.datetime.fromtimestamp(first / 1000, tz=dt.timezone(dt.timedelta(hours=-5))).date()
    today_sp = (DEMO_TODAY - day_one).days + 1

    # --- league: rename everything, keep rosters and settings
    me_old = 3  # the team whose cookies recorded the data becomes "Monstars", team 1
    ordered = sorted(league["teams"], key=lambda t: (t["id"] != me_old, t["id"]))
    id_map = {t["id"]: i + 1 for i, t in enumerate(ordered)}
    members, teams = [], []
    for idx, t in enumerate(ordered):
        new_id = idx + 1
        mid = DEMO_SWID if idx == 0 else f"{{00000000-0000-4000-8000-{new_id + 1:012d}}}"
        first, last = MANAGERS[idx].split()
        members.append({"id": mid, "firstName": first, "lastName": last, "displayName": MANAGERS[idx]})
        entries = [{"playerId": e["playerId"], "lineupSlotId": e["lineupSlotId"],
                    "playerPoolEntry": {"id": e["playerId"], "onTeamId": new_id, "status": "ONTEAM",
                                        "player": trim_player(e["playerPoolEntry"]["player"])}}
                   for e in t["roster"]["entries"]]
        teams.append({"id": new_id, "name": TEAM_NAMES[idx], "abbrev": TEAM_NAMES[idx][:4].upper(),
                      "owners": [mid], "playoffSeed": None, "currentProjectedRank": None,
                      "record": {"overall": {"wins": 0, "losses": 0, "ties": 0, "pointsFor": 0.0}},
                      "roster": {"entries": entries}})
    my_id = id_map[me_old]

    def proj(p):
        for s in p["stats"]:
            if s["id"] == "102027":
                return s["appliedAverage"] or 0
        return 0

    def day_points(team, sp):
        vals = sorted((proj(e["playerPoolEntry"]["player"]) * rnd.uniform(0.6, 1.4)
                       for e in team["roster"]["entries"]
                       if e["lineupSlotId"] != 13 and sp in games_by_team.get(
                           e["playerPoolEntry"]["player"]["proTeamId"], ())), reverse=True)
        return round(sum(vals[:10]), 1)

    # matchup weeks 1..3 (week 1 = opening day to first Sunday, then Monday to Sunday)
    weeks, start = [], day_one
    while len(weeks) < 20:
        end = start + dt.timedelta(days=6 - start.weekday())
        weeks.append(((start - day_one).days + 1, (end - day_one).days + 1))
        start = end + dt.timedelta(days=1)
    order = sorted(id_map.values())
    schedule_games = []
    for w in range(1, 21):
        r = (w - 1) % (len(order) - 1)  # a round robin repeats after n - 1 weeks
        rot = order[:1] + order[1:][r:] + order[1:][:r]
        pairs = [(rot[i], rot[-1 - i]) for i in range(len(rot) // 2)]
        if (w - 1) // (len(order) - 1) % 2:
            pairs = [(b, a) for a, b in pairs]  # the second time around, swap home and away
        a, b = weeks[w - 1]
        for home, away in pairs:
            sides = {}
            for side, tid in (("home", home), ("away", away)):
                team = next(t for t in teams if t["id"] == tid)
                by = {}
                if w <= 3:
                    for sp in range(a, min(b, today_sp - 1) + 1):
                        by[str(sp)] = day_points(team, sp)
                total = round(sum(by.values()), 1)
                sides[side] = {"teamId": tid, "totalPoints": total, "totalPointsLive": total,
                               "pointsByScoringPeriod": by}
            schedule_games.append({"matchupPeriodId": w, **sides})
            if w < 3:
                h, aw = sides["home"], sides["away"]
                for me_side, other in ((h, aw), (aw, h)):
                    rec = next(t for t in teams if t["id"] == me_side["teamId"])["record"]["overall"]
                    rec["pointsFor"] = round(rec["pointsFor"] + me_side["totalPoints"], 1)
                    if me_side["totalPoints"] > other["totalPoints"]:
                        rec["wins"] += 1
                    else:
                        rec["losses"] += 1
    ranked = sorted(teams, key=lambda t: (-t["record"]["overall"]["wins"], -t["record"]["overall"]["pointsFor"]))
    for i, t in enumerate(ranked, 1):
        t["playoffSeed"] = i
        t["currentProjectedRank"] = max(1, min(10, i + rnd.choice([-1, 0, 0, 1])))

    # a pending trade offer to make the inbox card come alive
    me = next(t for t in teams if t["id"] == my_id)
    rival = next(t for t in teams if t["id"] != my_id)
    give = me["roster"]["entries"][-1]["playerId"]
    get = rival["roster"]["entries"][-2]["playerId"]
    me["pendingTransactions"] = [{
        "type": "TRADE_PROPOSAL", "status": "PENDING", "teamId": rival["id"],
        "items": [{"playerId": give, "type": "TRADE", "fromTeamId": my_id, "toTeamId": rival["id"]},
                  {"playerId": get, "type": "TRADE", "fromTeamId": rival["id"], "toTeamId": my_id}]}]

    s = league["settings"]
    demo_league = {
        "id": DEMO_LEAGUE_ID, "seasonId": league["seasonId"], "scoringPeriodId": today_sp,
        "status": {"currentMatchupPeriod": 3, "firstScoringPeriod": 1, "latestScoringPeriod": today_sp,
                   "finalScoringPeriod": league["status"]["finalScoringPeriod"]},
        "settings": {"name": "Demo Hoops League", "size": 10,
                     "rosterSettings": s["rosterSettings"], "scheduleSettings": s["scheduleSettings"],
                     "scoringSettings": s["scoringSettings"], "acquisitionSettings": s["acquisitionSettings"]},
        "members": members, "teams": teams, "schedule": schedule_games,
    }

    def pool(items):
        return [{"id": x["id"], "status": x.get("status", "FREEAGENT"), "onTeamId": 0,
                 "player": trim_player(x["player"])} for x in items]

    data = {"today": DEMO_TODAY.isoformat(), "my_team_id": my_id, "swid": DEMO_SWID,
            "league": demo_league, "schedule": schedule, "free_agents": pool(fas),
            "trending": pool(trending)}
    OUT.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), 9))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB), today = scoring period {today_sp}")


if __name__ == "__main__":
    main(*sys.argv[1:5])

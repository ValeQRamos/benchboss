"""The demo dataset carries ESPN's raw shapes for stats, standings, odds and the watch list,
and the numbers add up (built by tools/enrich_demo.py). Also the demo client's player
filters, watch list writes and news."""

import pytest

from benchboss.demo import DemoClient, demo_session, load
from benchboss.errors import BenchbossError

WINDOWS = {"002027": 0, "012027": 1, "022027": 2, "032027": 3}
KEYS = {"id", "seasonId", "statSourceId", "statSplitTypeId", "scoringPeriodId",
        "appliedAverage", "appliedTotal", "averageStats", "stats"}
OWNERSHIP = {"percentOwned", "percentChange", "percentStarted", "averageDraftPosition",
             "auctionValueAverage", "auctionValueAverageChange"}


@pytest.fixture(scope="module")
def data():
    return load()


def everyone(data):
    """Every player object in the dataset, copies included."""
    out = [e["playerPoolEntry"]["player"] for t in data["league"]["teams"]
           for e in t["roster"]["entries"]]
    return out + [x["player"] for x in data["free_agents"] + data["trending"]]


def unique(data):
    return list({p["id"]: p for p in everyone(data)}.values())


def splits(p):
    return {s["id"]: s for s in p["stats"]}


def points(data):
    items = data["league"]["settings"]["scoringSettings"]["scoringItems"]
    return {str(i["statId"]): i["points"] for i in items}


def fpts(stats, pts):
    return sum(v * stats.get(k, 0.0) for k, v in pts.items())


def team_games(data, pro_team, first, last):
    for t in data["schedule"]["settings"]["proTeams"]:
        if t["id"] == pro_team:
            return sum(first <= int(sp) <= last for sp in t["proGamesByScoringPeriod"])
    return 0


# --- player stats ---------------------------------------------------------------------------------

def test_every_player_has_every_split_in_espn_shape(data):
    for p in everyone(data):
        s = splits(p)
        assert set(WINDOWS) <= set(s), p["fullName"]
        for sid, st in s.items():
            assert set(st) == KEYS, (p["fullName"], sid)
            assert st["id"] == f"{st['statSourceId']}{st['statSplitTypeId']}{st['seasonId']}"
            assert st["scoringPeriodId"] == 0
        for sid, split in WINDOWS.items():
            assert s[sid]["statSourceId"] == 0 and s[sid]["statSplitTypeId"] == split
            assert s[sid]["seasonId"] == 2027


def test_last_season_and_projection_box_scores_match_their_points(data):
    pts = points(data)
    checked = 0
    for p in unique(data):
        for sid in ("002026", "102027"):
            st = splits(p).get(sid)
            if not st or not st["appliedTotal"]:
                continue
            avg, tot = st["averageStats"], st["stats"]
            assert avg and tot, (p["fullName"], sid)
            assert abs(fpts(avg, pts) - st["appliedAverage"]) <= 0.5, (p["fullName"], sid)
            assert avg["42"] == tot["42"] > 0
            assert st["appliedTotal"] == pytest.approx(st["appliedAverage"] * tot["42"], abs=0.5)
            assert all(0 <= avg[k] <= 1 for k in ("19", "20", "21") if k in avg)
            checked += 1
    assert checked > 300


def test_projections_and_last_season_did_not_move(data):
    """They drive the lineup and trash tests: enriching must not change them."""
    edwards = next(p for p in everyone(data) if p["fullName"] == "Anthony Edwards")
    s = splits(edwards)
    assert (s["102027"]["appliedAverage"], s["102027"]["appliedTotal"]) == (47.25, 3402.0)
    assert s["002026"]["appliedTotal"] == 2780.0
    assert s["002026"]["averageStats"]["0"] == pytest.approx(1757 / 61)


def test_synthesized_box_scores_add_up(data):
    pts = points(data)
    played = 0
    for p in unique(data):
        for sid in WINDOWS:
            st = splits(p)[sid]
            tot, avg = st["stats"], st["averageStats"]
            if not tot:
                continue
            gp = tot["42"]
            played += 1
            assert gp == avg["42"] >= 1
            assert st["appliedTotal"] == pytest.approx(fpts(tot, pts))
            assert st["appliedAverage"] == pytest.approx(st["appliedTotal"] / gp)
            assert tot["13"] <= tot["14"] and tot["15"] <= tot["16"]
            assert tot["17"] <= tot["18"] <= tot["14"] and tot["17"] <= tot["13"]
            assert tot["6"] == tot["4"] + tot["5"]
            assert tot["0"] == 2 * tot["13"] + tot["17"] + tot["15"]
            assert tot["19"] == pytest.approx(tot["13"] / tot["14"] if tot["14"] else 0, abs=1e-4)
            assert tot["20"] == pytest.approx(tot["15"] / tot["16"] if tot["16"] else 0, abs=1e-4)
            assert tot["21"] == pytest.approx(tot["17"] / tot["18"] if tot["18"] else 0, abs=1e-4)
            assert tot["38"] <= tot["37"] <= gp and tot["41"] <= gp
            assert gp <= tot["40"] <= 48 * gp
            assert avg["0"] == pytest.approx(tot["0"] / gp, abs=1e-3)
            assert avg["40"] == pytest.approx(tot["40"] / gp, abs=1e-3)
            assert avg["19"] == tot["19"]
    assert played > 500


def test_windows_nest_and_fit_the_nba_schedule(data):
    today = data["league"]["scoringPeriodId"]
    for p in unique(data):
        s = splits(p)
        gp = {sid: s[sid]["stats"].get("42", 0) for sid in WINDOWS}
        assert gp["012027"] <= gp["022027"] <= gp["032027"]
        # two weeks into the season, the 15 and 30 day windows are the whole season
        assert s["002027"] == {**s["022027"], "id": "002027", "statSplitTypeId": 0}
        assert s["032027"] == {**s["022027"], "id": "032027", "statSplitTypeId": 3}
        team = p.get("proTeamId") or 0
        assert gp["002027"] <= team_games(data, team, 1, today - 1)
        assert gp["012027"] <= team_games(data, team, today - 7, today - 1)


def test_season_lands_near_the_projection(data):
    near = 0
    for p in unique(data):
        s = splits(p)
        if "102027" in s and s["002027"]["appliedTotal"]:
            ratio = s["002027"]["appliedAverage"] / s["102027"]["appliedAverage"]
            assert 0.75 <= ratio <= 1.25, p["fullName"]
            near += 1
    assert near > 180


def test_no_games_means_a_zero_split(data):
    zero = [p for p in unique(data) if not splits(p)["002027"]["appliedTotal"]]
    assert zero
    for p in zero:
        for sid in WINDOWS:
            st = splits(p)[sid]
            assert st["appliedTotal"] == 0 and st["appliedAverage"] == 0
            assert st["stats"] == {} and st["averageStats"] == {}
    unsigned = [p for p in unique(data) if not p.get("proTeamId")]
    assert unsigned and all(p in zero for p in unsigned)
    out = [p for p in unique(data) if p.get("injuryStatus") == "OUT"]
    assert out and all(not splits(p)["012027"]["appliedTotal"] for p in out)


def test_copies_of_a_player_agree(data):
    seen = {}
    for p in everyone(data):
        if p["id"] in seen:
            assert p["stats"] == seen[p["id"]]["stats"]
            assert p["ownership"] == seen[p["id"]]["ownership"]
        seen[p["id"]] = p


def test_ownership_jersey_and_droppable(data):
    for p in everyone(data):
        assert set(p["ownership"]) >= OWNERSHIP, p["fullName"]
        assert isinstance(p.get("jersey", ""), str)
        assert isinstance(p.get("droppable", True), bool)
    assert sum("jersey" in p for p in everyone(data)) > 200


def test_pools_are_in_espn_sort_order(data):
    owned = [x["player"]["ownership"]["percentOwned"] for x in data["free_agents"]]
    assert owned == sorted(owned, reverse=True)
    change = [x["player"]["ownership"]["percentChange"] for x in data["trending"]]
    assert change == sorted(change, reverse=True)


# --- league -------------------------------------------------------------------------------------

def test_schedule_has_ids_winners_and_tiers(data):
    lg = data["league"]
    current = lg["status"]["currentMatchupPeriod"]
    assert [g["id"] for g in lg["schedule"]] == list(range(1, len(lg["schedule"]) + 1))
    for g in lg["schedule"]:
        assert g["playoffTierType"] == "NONE"
        h, a = g["home"]["totalPoints"], g["away"]["totalPoints"]
        if g["matchupPeriodId"] < current:
            assert g["winner"] == ("HOME" if h > a else "AWAY" if a > h else "TIE")
        else:
            assert g["winner"] == "UNDECIDED"


def test_schedule_is_a_double_round_robin(data):
    lg = data["league"]
    teams = sorted(t["id"] for t in lg["teams"])
    weeks = {}
    for g in lg["schedule"]:
        weeks.setdefault(g["matchupPeriodId"], []).append((g["home"]["teamId"], g["away"]["teamId"]))
    assert sorted(weeks) == list(range(1, 21))
    for pairs in weeks.values():  # everybody plays exactly once a week
        assert sorted(x for p in pairs for x in p) == teams
    first = [p for w in range(1, 10) for p in weeks[w]]
    assert len({frozenset(p) for p in first}) == 45  # rounds 1-9 meet every pair once
    for w in range(10, 19):
        assert weeks[w] == [(a, h) for h, a in weeks[w - 9]]  # then again, home and away swapped
    assert weeks[19] == weeks[1] and weeks[20] == weeks[2]
    played = [g for g in lg["schedule"] if g["matchupPeriodId"] <= 3]
    assert all(g["home"]["pointsByScoringPeriod"] for g in played)
    assert not any(g["home"]["totalPoints"] for g in lg["schedule"] if g["matchupPeriodId"] > 3)


def test_records_add_up(data):
    lg = data["league"]
    div = {t["id"]: t["divisionId"] for t in lg["teams"]}
    assert sorted(div.values()) == [0] * 5 + [1] * 5
    assert {d["id"] for d in lg["settings"]["scheduleSettings"]["divisions"]} == {0, 1}
    games = {t: [] for t in div}  # (opponent, home?, points for, against, outcome)
    for g in lg["schedule"]:
        if g["winner"] == "UNDECIDED":
            continue
        h, a = g["home"], g["away"]
        for me, other, home in ((h, a, True), (a, h, False)):
            out = "T" if g["winner"] == "TIE" else "W" if (g["winner"] == "HOME") == home else "L"
            games[me["teamId"]].append((other["teamId"], home, me["totalPoints"],
                                        other["totalPoints"], out))
    for t in lg["teams"]:
        rec = t["record"]
        for kind, mine in (("overall", games[t["id"]]),
                           ("home", [x for x in games[t["id"]] if x[1]]),
                           ("away", [x for x in games[t["id"]] if not x[1]]),
                           ("division", [x for x in games[t["id"]] if div[x[0]] == div[t["id"]]])):
            r = rec[kind]
            assert r["wins"] == sum(x[4] == "W" for x in mine)
            assert r["losses"] == sum(x[4] == "L" for x in mine)
            assert r["pointsFor"] == pytest.approx(sum(x[2] for x in mine), abs=0.2)
            assert r["pointsAgainst"] == pytest.approx(sum(x[3] for x in mine), abs=0.2)
            n = r["wins"] + r["losses"] + r["ties"]
            assert r["percentage"] == pytest.approx((r["wins"] + r["ties"] / 2) / n if n else 0)
            if mine:
                last = mine[-1][4]
                assert r["streakType"] == {"W": "WIN", "L": "LOSS", "T": "TIE"}[last]
                assert 1 <= r["streakLength"] <= len(mine)
            else:
                assert (r["streakType"], r["streakLength"]) == ("NONE", 0)
    overall = [t["record"]["overall"] for t in lg["teams"]]
    assert sum(r["pointsFor"] for r in overall) == pytest.approx(sum(r["pointsAgainst"] for r in overall))
    lead = max(overall, key=lambda r: r["wins"] - r["losses"])
    for r in overall:
        assert r["gamesBack"] == ((lead["wins"] - r["wins"]) + (r["losses"] - lead["losses"])) / 2
    assert any(t["record"]["division"]["wins"] for t in lg["teams"])


def test_waiver_order_and_transaction_counters(data):
    teams = data["league"]["teams"]
    assert sorted(t["waiverRank"] for t in teams) == list(range(1, 11))
    by_rank = sorted(teams, key=lambda t: t["waiverRank"])
    wins = [t["record"]["overall"]["wins"] for t in by_rank]
    assert wins == sorted(wins)  # worst record picks first
    for t in teams:
        tc = t["transactionCounter"]
        assert set(tc) == {"acquisitions", "drops", "trades", "moveToActive", "moveToIR",
                           "acquisitionBudgetSpent", "misc", "paid", "teamCharges",
                           "matchupAcquisitionTotals"}
        assert tc["acquisitions"] == sum(tc["matchupAcquisitionTotals"].values())
        assert tc["drops"] == tc["acquisitions"]  # every roster still has 13 players
        assert t["playoffClinchType"] == "UNKNOWN"


def test_playoff_odds(data):
    lg = data["league"]
    weeks = lg["settings"]["scheduleSettings"]["matchupPeriodCount"]
    sims = [t["currentSimulationResults"] for t in lg["teams"]]
    assert sum(s["playoffPct"] for s in sims) == pytest.approx(
        lg["settings"]["scheduleSettings"]["playoffTeamCount"], abs=0.01)
    assert sum(s["divisionWinPct"] for s in sims) == pytest.approx(2.0, abs=0.01)
    assert sorted(s["rank"] for s in sims) == list(range(1, 11))
    for t, s in zip(lg["teams"], sims, strict=True):
        assert 0 <= s["divisionWinPct"] <= s["playoffPct"] <= 1
        assert s["playoffClinchType"] == "UNKNOWN"
        m = s["modeRecord"]
        assert m["wins"] + m["losses"] + m["ties"] == weeks
        assert m["wins"] >= t["record"]["overall"]["wins"]
        assert m["streakType"] in ("WIN", "LOSS") and m["streakLength"] >= 1
        assert m["pointsFor"] > t["record"]["overall"]["pointsFor"]
    assert min(s["modeRecord"]["gamesBack"] for s in sims) == 0


def test_watch_list_is_on_my_team_only(data):
    me = data["my_team_id"]
    fas = {x["id"] for x in data["free_agents"]}
    for t in data["league"]["teams"]:
        if t["id"] == me:
            assert len(t["watchList"]) == len(set(t["watchList"])) == 4
            assert set(t["watchList"]) <= fas
        else:
            assert "watchList" not in t


def test_pending_trade_is_kept(data):
    me = next(t for t in data["league"]["teams"] if t["id"] == data["my_team_id"])
    assert me["pendingTransactions"][0]["type"] == "TRADE_PROPOSAL"


# --- demo client ----------------------------------------------------------------------------------

@pytest.fixture
def client():
    return DemoClient(load())


def test_filter_status(client):
    rostered = client.players({"filterStatus": {"value": ["ONTEAM"]}})
    assert len(rostered) == 130
    assert all(x["status"] == "ONTEAM" and x["onTeamId"] for x in rostered)
    free = client.players({"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}})
    assert {x["id"] for x in free} == {x["id"] for x in client.data["free_agents"]}
    assert len(client.players({})) == len(unique(client.data)) == 210
    both = client.players({"filterStatus": {"value": ["ONTEAM", "FREEAGENT"]}})
    assert len(both) == 210


def test_filter_ids_name_and_slots(client):
    mine = client.data["league"]["teams"][0]["roster"]["entries"][0]["playerId"]
    fa = client.data["free_agents"][0]["id"]
    assert {x["id"] for x in client.players({"filterIds": {"value": [mine, fa, 999]}})} == {mine, fa}
    hits = client.players({"filterName": {"value": "JOKIC"}})
    assert [x["player"]["fullName"] for x in hits] == ["Nikola Jokic"]
    assert client.players({"filterName": {"value": "ntetokoun"}})
    centers = client.players({"filterSlotIds": {"value": [4]}, "filterStatus": {"value": ["ONTEAM"]}})
    assert centers and all(4 in x["player"]["eligibleSlots"] for x in centers)


def test_sort_by_applied_stat(client):
    flt = {"filterStatus": {"value": ["FREEAGENT"]}, "limit": 10,
           "sortAppliedStatAverage": {"sortPriority": 1, "sortAsc": False, "value": "002027"}}
    top = client.players(flt)
    vals = [splits(x["player"])["002027"]["appliedAverage"] for x in top]
    assert len(top) == 10 and vals == sorted(vals, reverse=True)
    best = max(splits(x["player"])["002027"]["appliedAverage"] for x in client.data["free_agents"])
    assert vals[0] == best
    flt["sortAppliedStatAverage"]["sortAsc"] = True
    low = [splits(x["player"])["002027"]["appliedAverage"] for x in client.players(flt)]
    assert low == sorted(low)
    total = client.players({"limit": 3, "sortAppliedStatTotal": {"sortAsc": False, "value": "102027"}})
    tot = [splits(x["player"])["102027"]["appliedTotal"] for x in total]
    assert tot == sorted(tot, reverse=True) and total[0]["status"] == "ONTEAM"


def test_players_without_the_sorted_split_go_last(client):
    rookies = [x for x in client.data["free_agents"] if "102027" not in splits(x["player"])]
    assert rookies
    ranked = client.players({"filterStatus": {"value": ["FREEAGENT"]},
                             "sortAppliedStatAverage": {"sortAsc": True, "value": "102027"}})
    assert {x["id"] for x in ranked[-len(rookies):]} == {x["id"] for x in rookies}


def test_limit_offset_and_sorts(client):
    flt = {"filterStatus": {"value": ["FREEAGENT"]}, "limit": 5,
           "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}
    first = client.players(flt)
    second = client.players({**flt, "offset": 5})
    assert first[0] is client.data["free_agents"][0]
    assert not {x["id"] for x in first} & {x["id"] for x in second}
    assert len(client.players({**flt, "limit": 0})) == len(client.data["free_agents"])
    with pytest.raises(BenchbossError, match="must be accompanied by a sort"):
        client.players({"filterStatus": {"value": ["FREEAGENT"]}, "limit": 5})
    rising = client.players({"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "limit": 5,
                             "sortPercChanged": {"sortPriority": 1, "sortAsc": False}})
    assert [x["id"] for x in rising] == [x["id"] for x in client.data["trending"][:5]]


# --- watch list writes and news ---------------------------------------------------------------

def test_update_team_changes_only_my_watch_list(client):
    me = client.data["my_team_id"]
    new = [client.data["free_agents"][3]["id"], client.data["free_agents"][9]["id"]]
    team = client.update_team(me, {"watchList": new})
    assert team["id"] == me and team["watchList"] == new and "roster" in team
    assert next(t for t in client.data["league"]["teams"] if t["id"] == me)["watchList"] == new
    assert client.update_team(me, {"watchList": []})["watchList"] == []
    other = next(t["id"] for t in client.data["league"]["teams"] if t["id"] != me)
    for team_id, body in ((other, {"watchList": new}), (me, {"watchList": new, "name": "x"}),
                          (me, {"name": "x"}), (me, {"watchList": ["1"]}),
                          (me, {"watchList": [True]}), (me, {"watchList": 5})):
        with pytest.raises(BenchbossError, match="demo mode"):
            client.update_team(team_id, body)


def test_session_sees_the_new_watch_list():
    s = demo_session()
    me = s.league().my_team_id
    pid = s.data["free_agents"][7]["id"]
    s.client.update_team(me, {"watchList": [pid]})
    raw = next(t for t in s.league_raw["teams"] if t["id"] == me)
    assert raw["watchList"] == [pid]


def test_news_for_roster_and_watch_list():
    s = demo_session()
    roster = [sp.player.id for sp in s.league().me.roster]
    watched = next(t for t in s.data["league"]["teams"] if t["id"] == s.data["my_team_id"])["watchList"]
    both = s.news(roster + watched, 5)
    assert len(both) == 6 and len({n.id for n in both}) == 6
    assert [n.published for n in both] == sorted((n.published for n in both), reverse=True)
    assert len(s.news(roster, 5)) == 4
    mine = s.news(watched, 5)
    assert len(mine) == 2 and all(n.player_ids <= set(watched) for n in mine)
    assert all(0 < (s.now - n.published).total_seconds() < 2 * 86400 for n in mine)
    assert all(n.spin and n.kind == "Rotowire" for n in mine)
    assert len(s.news(roster + watched, 1)) < 6

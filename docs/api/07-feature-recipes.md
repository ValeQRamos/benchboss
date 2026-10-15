# 07. Feature recipes: the exact calls and the math behind each product feature

This document turns the endpoint catalog of documents 01 to 06 into eight concrete recipes: (a) live matchup dashboard, (b) most and least active players, (c) lineup optimizer, (d) roster news, (e) free-agent pickup ranking, (f) trade finder, (g) alerts and (h) first-run setup.
Each recipe lists the requests (method, URL, params, header filter), the response paths it reads, the computation, the gotchas and a live result obtained on Thu Oct 15, 2026 (preseason of the 2027 season, `latestScoringPeriod` 1) or, where preseason data cannot answer, on the completed 2026 season of the same league.
Live results are computed from the reference league's data with ESPN's preseason projections; they illustrate the method and are not predictions.

Verification legend:

- **VERIFIED (live)**: seen in a live GET response on 2026-10-15.
- **VERIFIED (live, 2026)**: seen live on the completed 2026 season of the same league (`seasons/2026/...`), used when preseason data is empty.
- **VERIFIED (bundle)**: read in ESPN's JS, kona build `7411ee0540f4-1.517` (`main-f2aedb781c45b792f61b.js`) or community chat `1.0.67` (`chat-7847ae3f.js`).
- **UNVERIFIED**: inference, product choice or not observable before games start.

Only GET requests were sent. No write endpoint was called. Write bodies referenced below are documented in 04.

Placeholders: `{L}` = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}`, `{G}` = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}`, `{me}` = my team id, `{opp}` = opponent team id, `{SWID}` = the SWID cookie value including braces. Example numbers use team ids only (3 = my team, 14 = the matchup 1 opponent); player names are public NBA data.

---

## Quick reference

| Method | URL / view | Purpose | Auth | Status |
|---|---|---|---|---|
| GET | `{L}?view=mMatchupScore&view=mBoxscore&scoringPeriodId={today}` + `{"schedule":{"filterCurrentMatchupPeriod":{"value":true},"filterTeamIds":{"value":[{me}]}}}` | Live matchup row, opponent id, live totals, per-day points (15,343 B) | espn_s2 | VERIFIED (live) |
| GET | `{L}?view=mRoster&forTeamId={me}&forTeamId={opp}&scoringPeriodId={d}` | Both lineups as set for day d, with player projections | espn_s2 | VERIFIED (live): `forTeamId` is repeatable |
| GET | `{L}?view=mMatchupScore&scoringPeriodId={d}` + `filterCurrentMatchupPeriod` + `filterTeamIds` | Probe: is day d inside the current matchup? (`rosterForCurrentScoringPeriod` present or not) | espn_s2 | VERIFIED (live): day 6 present, day 7 absent |
| GET | `{G}?view=proTeamSchedules_wl` | Every NBA game by team and scoring period; first tip-off of each day | none | VERIFIED (live) |
| GET | `https://site.api.espn.com/apis/fantasy/v2/games/fba/games?dates={YYYYMMDD}[-{YYYYMMDD}]` | Live NBA game state (`pre`/`in`/`post`, `percentComplete`) | none | VERIFIED (live): 43 games for Oct 20 to 25, 0 for a preseason day |
| GET | `{L}/teams/{me}/recommendations?view=recommend&recommendationTypeId=LINEUP[&lineupScoringPeriodId={d}]` | ESPN's own lineup suggestion for today or a future day | espn_s2 | VERIFIED (live) |
| GET | `{L}?view=kona_player_info&scoringPeriodId={today}` + FA filter with `sortAppliedStatTotal` | Free agent and waiver pool with projections | espn_s2 | VERIFIED (live) |
| GET | `{L}?view=kona_playercard` + `{"players":{"filterIds":{"value":[...]}}}` | `injuryDetails.expectedReturnDate` for injured players | espn_s2 | VERIFIED (live) |
| GET | `https://site.api.espn.com/apis/fantasy/v2/games/fba/news/players?playerId={id}&playerId={id}...&days=5&limit=200` | Roster news of the last 5 days | none | VERIFIED (live) |
| GET | `{L}?view=mRoster` (all teams) and `{L}?view=mTeam` | All rosters, trade blocks, owners | espn_s2 | VERIFIED (live) |
| GET | `{L}?view=mPendingTransactions` | Accepted trades in review; expected to hold incoming offers | espn_s2 | VERIFIED (live) for review state; incoming offers UNVERIFIED |
| GET | `{L}?view=mTransactions2&scoringPeriodId={d}` + `{"transactions":{"filterType":{"value":[...]}}}` | Trade, waiver and add/drop records of day d | espn_s2 | VERIFIED (live, 2026): per-day; preseason returns everything |
| GET | `{L}?view=chat_conversations` (filter, if any, as `{"communication":{"topics":{...}}}`) | Unread counts per DM and league chat | espn_s2 | VERIFIED (live) |
| GET | `https://lm-api-reads.fantasy.espn.com/apis/v3/communication/lastReadByMember?view=chat_unreads&platform=chat` | Cheapest "anything unread" flag, per league season | espn_s2 | VERIFIED (live) on the reads host |
| GET | `{L}/communication/?view=kona_league_communication` + topics filter | Activity feed (adds, drops, trades) | espn_s2 | VERIFIED (live) |
| GET | `https://fan.api.espn.com/apis/v2/fans/{SWID url-encoded}?displayHiddenPrefs=true&context=fantasy&useCookieAuth=true&source=fantasyapp-ios&featureFlags=challengeEntries` | The user's leagues, teams and seasons (first-run discovery) | cookies optional (see h) | VERIFIED (live + bundle) |
| GET | `https://lm-api-reads.fantasy.espn.com/apis/v3/games/{game}` | `currentSeasonId` and current scoring period per game (`{game}` = `fba`, `ffl`, `flb`, `fhl` or `wfba`) | none | VERIFIED (live) |
| GET | `{L}` (no view) | Cookie validation and "my team" via `teams[].owners` | espn_s2 | VERIFIED (live) |
| POST | `lm-api-writes .../transactions/` (`ROSTER`, `FUTURE_ROSTER`, `FREEAGENT`, `WAIVER`, `TRADE_PROPOSAL`) | The writes these features end in | espn_s2 + SWID | Documented in 04; not executed here |

---

## 1. Shared building blocks

### 1.1 "Today" and the current matchup

- ESPN day: `scoringPeriodId = (America/New_York date of (now - 3 h)) - season_day_1 + 1`; day 1 of 2027 = Tue Oct 20, 2026. Day boundaries are 03:00 ET (bundle constants, 05 section 1.3). VERIFIED (bundle + live).
- Online source of truth: `status.latestScoringPeriod` (any league view with `mStatus` or `mSettings`), plus the `X-Fantasy-Server-Time` response header for the clock (VERIFIED live: `Thu, 15 Oct 2026 15:30:37 GMT`). Public fallback: `GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba` -> `currentSeason.currentScoringPeriod.id` (VERIFIED live: 1).
- Days of the current matchup: from the bundle weekly table plus `settings.scheduleSettings.matchupPeriods` (05 section 1.4), or, without the bundle, with the server probe below. VERIFIED (live).

```
GET {L}?view=mMatchupScore&scoringPeriodId={d}
x-fantasy-filter: {"schedule":{"filterCurrentMatchupPeriod":{"value":true},"filterTeamIds":{"value":[{me}]}}}
-> day d belongs to the current matchup iff my side carries "rosterForCurrentScoringPeriod"
```

Live: day 6 -> present, day 7 -> absent (matchup 1 = days 1 to 6). A binary search over `today .. today + 14` finds the last day in at most 4 calls. VERIFIED (live).

### 1.2 Schedule index

From `{G}?view=proTeamSchedules_wl` (public, 423 KB, cache 1 day): `plays[proTeamId] = {scoringPeriodId, ...}`, `tip[proTeamId][sp] = game.date (epoch ms)`, `first_tip[sp] = min(game.date for all games of sp)`. At most one game per team per day (VERIFIED live). Off days: 15, 38, 46 to 53, 66, 123 to 128, 173 (VERIFIED live, 01).

### 1.3 Player value per game

- `proj_ppg(p)` = `appliedAverage` of the stat entry with `statSourceId 1`, `statSplitTypeId 0`, current season (`id "10{season}"`), when its `appliedTotal > 0`; fallback: last season actual (`"00{season-1}"`). VERIFIED (live: entries present for every rostered player).
- `health(p)`: a simple product rule `OUT, SUSPENSION, INJURY_RESERVE = 0; DOUBTFUL = 0.25; DAY_TO_DAY, QUESTIONABLE = 0.75; else 1` (a product choice, UNVERIFIED as a predictor). Better for multi-day horizons: 0 before `injuryDetails.expectedReturnDate` (`kona_playercard`, `[year, 1-based month, day]`), 1 after it. VERIFIED (live) that the field exists (`Dyson Daniels: DAY_TO_DAY, [2026, 10, 16], type Rest`).
- `value(p, d) = proj_ppg(p) * health(p, d)` if `d in plays[p.proTeamId]` else 0.
- Projected games played: `stats["42"]` of the projection entry (VERIFIED live: Edwards 72, Ball 68, Siakam 74 of 80 scheduled).

### 1.4 Daily lineup solver

`best_lineup(pool, counts, vals)` (dynamic programming over starting slots with a player bitmask) maximizes the sum of `vals` over the starting slots of `settings.rosterSettings.lineupSlotCounts` (PG, SG, SF, PF, C, G, F, UTIL x3 here) using `player.eligibleSlots`. Restrict `pool` to non-IR players **with a game that day** before calling it; zero-value players only fill empty slots.

Live validation (VERIFIED live): for days 1, 2, 4, 5 and 6 of matchup 1, the set of my players **with a game** that the solver starts was identical to the set ESPN's own suggestion starts (`recommendations` GET, section c). On day 3 none of my players had a game.

`day_value(team, d) = best_lineup value over that pool`; `day_games(team, d) = number of starters with a game in that solution`.

---

## (a) Dashboard: live score, projected final, games left per side

### Requests

1. Matchup row (one call, 15,343 B in preseason). VERIFIED (live).

```
GET {L}?view=mMatchupScore&view=mBoxscore&scoringPeriodId={today}
x-fantasy-filter: {"schedule":{"filterCurrentMatchupPeriod":{"value":true},"filterTeamIds":{"value":[{me}]}}}
```

Read: `schedule[0].matchupPeriodId`, `home/away.teamId` (the other side is `{opp}`), `totalPointsLive` (fallback `totalPoints`), `pointsByScoringPeriod{sp: pts}`, `rosterForCurrentScoringPeriod.entries[]{lineupSlotId, playerId, playerPoolEntry.appliedStatTotal, playerPoolEntry.player}` (today's lineup and points, starters are `lineupSlotId not in (12, 13)`). VERIFIED (live; per-day points shape VERIFIED live, 2026, in 05).

2. Lineups as set for every remaining day, both teams in one call per day. VERIFIED (live).

```
GET {L}?view=mRoster&forTeamId={me}&forTeamId={opp}&scoringPeriodId={d}      for d in remaining days
```

Read: `teams[].roster.entries[]{playerId, lineupSlotId, playerPoolEntry.lineupLocked, playerPoolEntry.player{proTeamId, eligibleSlots, injuryStatus, stats[]}}`. Lineups really differ per day: my team had 5 distinct lineups over days 1 to 6 (set ahead with `FUTURE_ROSTER`), the opponent one. VERIFIED (live).

3. Schedule index (1.2), cached daily.

4. Live NBA state for today, public, about 1 call per minute while games run. VERIFIED (live).

```
GET https://site.api.espn.com/apis/fantasy/v2/games/fba/games?dates={YYYYMMDD of today, Eastern}
```

Read: `events[]{id, date, status ("pre"|"in"|"post"), percentComplete, competitors[]{id (= proTeamId), homeAway, score}}`. Join to fantasy players by `competitors[].id == player.proTeamId` (VERIFIED live: `"8"` = DET).

Optional and cheap: the fan API entry (section h) carries `lineup.proGameToNumPlayersStarting{gameId: n}` (VERIFIED live: two entries on day 1, one starter in each of the two games my players play) and `currentLineup{playerId: lineupSlotId}`.

### Computation

```
live(side)         = side.totalPointsLive  (fallback totalPoints)
today_left(side)   = sum over today's starters of value(p, today) * f(game state)
                     f = 1 (pre), 1 - percentComplete/100 (in), 0 (post)          # mirrors ESPN's generic live code (05 8.2)
future(side, mode) = sum over remaining days d > today of
                     mode "as set":   sum value(p, d) for p in that day's starters (request 2)
                     mode "optimal":  day_value(side, d)  (solver, 1.4)
projected_final    = live + today_left + future
games_left(side)   = raw:      sum over d >= today of non-IR players with a game on d (minus today's started games)
                     as set:   starters with a game, per request 2
                     usable:   day_games(side, d) from the solver, capped by starting slots (10 here)
```

Show "as set" for the opponent (what they will score if they do nothing) and both modes for my team (the gap is what optimizing is worth).

### Live result (matchup 1, team 3 vs team 14, all 6 days remaining, preseason projections)

| Side | Live | Projected final as set | Projected final optimal | Starter games as set | Usable games (optimal) | Raw roster games | Cap |
|---|---|---|---|---|---|---|---|
| team 3 | 0.0 | 1159.3 | 1267.2 | 32 | 35 | 39 | 60 |
| team 14 | 0.0 | 1031.1 | 1186.5 | 29 | 35 | 37 | 60 |

VERIFIED (live data, computed with the formulas above). The values are only as good as ESPN's season projections.

### Gotchas

- ESPN sends no matchup projection for basketball (`totalProjectedPoints` never present, `hasGameStatProjections: false`, 05 section 8). VERIFIED (live + bundle).
- Day totals count starters only; per-player `appliedStatTotal` counts bench and IR too (05 section 3.4). VERIFIED (live, 2026).
- Use `lineupLocked` (or the game's `status != "pre"`) to freeze today's started players; the optimal mode must not move them. Field VERIFIED (live), in-season values UNVERIFIED.
- `totalPointsLive` freshness during games is UNVERIFIED until opening night (05 open question 1); cross-check with `sum(pointsByScoringPeriod) + today's starters`.

---

## (b) Most active and least active players this week

### Requests

Rosters (`{L}?view=mRoster`, all teams: 770,693 B plain, about 149 KB gzip, or `forTeamId` repeated for a subset), the schedule index (1.2) and the matchup days (1.1). VERIFIED (live).

### Computation

```
remaining = [d for d in matchup_days if d >= today]
games_left(p) = count(d in remaining if d in plays[p.proTeamId])
                - (1 if today in plays[p.proTeamId] and tip[p.proTeamId][today] <= now else 0)
rank: games_left desc, then games_left * proj_ppg desc        (most active)
      games_left asc, then proj_ppg desc                       (least active, i.e. bench or stream candidates)
```

Scope switch: my roster, my opponent, the whole league, or free agents (use the pool from section e).

### Live result (matchup 1, days 1 to 6)

- My 13 players: all 3 games each (13 x 3). VERIFIED (live).
- All 130 rostered players in the league: 22 with 2 games, 103 with 3, 5 with 4. VERIFIED (live).
- Day-level spread is the real signal in this week: day 1 has 6 NBA teams playing, day 3 only 4 (CLE, DEN, OKC, PHI), day 4 has 24. VERIFIED (live). Full-season min and max per matchup: 05 section 9.2.

### Gotchas

- Games in the NBA Cup knockout window (days 46 to 53) are not in the feed yet; weeks 7 and 8 will change. VERIFIED (live), timing UNVERIFIED.
- A player's game counts for "this week" only if it falls inside the matchup's scoring periods; the All-Star matchup (18) has 14 days. VERIFIED (bundle + live).

---

## (c) Lineup optimization: today and the rest of the week

### Requests per day d (ascending, today first)

```
GET  {L}?view=mRoster&forTeamId={me}&scoringPeriodId={d}                         lineup of day d, lock flags
GET  {L}/teams/{me}/recommendations?view=recommend&recommendationTypeId=LINEUP&lineupScoringPeriodId={d}
                                                                                 optional cross-check (ESPN's suggestion)
POST lm-api-writes .../transactions/  type ROSTER (d == status.latestScoringPeriod) or FUTURE_ROSTER (d > latestScoringPeriod)
     items [{"playerId", "type": "LINEUP", "fromLineupSlotId", "toLineupSlotId"}]  write: needs the user's OK (body in 04 section 3)
```

The recommendation GET: VERIFIED (live). Without `lineupScoringPeriodId` it returns a `ROSTER` transaction for today; with `lineupScoringPeriodId=d` a `FUTURE_ROSTER` for day d; `restOfWeek=true` changed nothing on the GET; `scoringPeriodId=d` instead returns 409 `RECOMMENDATION_INVALID_SCORINGPERIOD`. `currentProjectedPoints` and `newProjectedPoints` were 0.0 in preseason.

### Algorithm

```
for d in remaining days of the matchup:
    entries = mRoster(d)                                   # re-read: FUTURE_ROSTER moves carry forward
    fixed   = entries with lineupLocked, or whose game on d has status != "pre", or lineupSlotId == 13 (IR)
    counts' = lineupSlotCounts minus the starting slots held by fixed entries
    pool    = the other non-IR entries; vals = value(p, d)
    target  = best_lineup(pool, counts', vals)             # 1.4
    items   = LINEUP moves for entries whose slot differs (bench = 12)
    show plan; on OK send it; type ROSTER for today, FUTURE_ROSTER for later days
```

Hold locked players fixed: moving a player whose game has started fails with `FAILED_LINEUPLOCK` (VERIFIED (bundle) status name), so never treat every non-IR player as movable.

### Validation

Set of starters with a game, this solver vs ESPN's suggestion, matchup 1: day 1 equal, day 2 equal (11 players with a game, 10 start), day 4 equal (13 with a game), day 5 equal (6), day 6 equal (7). VERIFIED (live). Differences appear only among players without a game (ESPN fills empty slots by season projection; this solver by a 1e-3 placeholder value).

### Gotchas

- Order matters: a `FUTURE_ROSTER` for day d also shapes later days until they get their own move; always send in ascending order and re-plan each day after the previous one is sent (observed in earlier client runs). UNVERIFIED as a server rule beyond observed behavior.
- `ROSTER` for a day other than today is rejected with 409 (earlier client runs; UNVERIFIED here because no write was sent).
- ESPN's Quick Lineup POST (`teams/{id}/recommendations?...&restOfWeek=`) exists (VERIFIED bundle) but was not executed; the app should keep its own transparent plan.

---

## (d) Player news for my roster, last 5 days

### Request

```
GET https://site.api.espn.com/apis/fantasy/v2/games/fba/news/players
    ?playerId={id1}&playerId={id2}...&playerId={id13}&days=5&limit=200
Accept-Encoding: gzip           (no cookies)
```

Live result (VERIFIED live, 11:33 ET): HTTP 200, 41 items (39 unique `id`s; duplicates are items tagged to two of my players), types Rotowire 23, Media 17, Story 1; 9 of 13 players had news; oldest item 2026-10-10 00:24 ET, which matches the documented cutoff "midnight US Eastern of today minus 5" (03). Every Rotowire item had a `story` (the "Spin").

### Computation

```
items = dedupe by id (keep the set of playerIds per item); sort by published desc
group by playerId -> show headline (Rotowire: the blurb), story (Rotowire: "Spin"), published (ISO UTC, render in local time)
badge: player.injuryStatus (league view) + injuryDetails.type/expectedReturnDate (kona_playercard)
refresh trigger: any roster player's lastNewsDate > last fetch time (lags at least 55 min, so also poll every 10 to 15 min)
```

Injury join (VERIFIED live): `GET {L}?view=kona_playercard` with `{"players":{"filterIds":{"value":[roster ids]}}}` returned 13 players; the 3 DAY_TO_DAY ones carried `injuryDetails` (`Rest` with return 2026-10-16, `Calf` 2026-10-21, `Calf` 2026-10-20). The public `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries` report adds body part and blurbs league-wide (03 section 5).

### Gotchas

- The v3 path honours only one `playerId` (VERIFIED live again); the v2 path takes up to about 105 ids before the URL gets too long (03).
- Error bodies from `site.api.espn.com` can be gzip even when not requested (03). The 400 for a comma-separated list was re-confirmed.

---

## (e) Free-agent pickups ranked by points added this week

### Requests

```
GET {L}?view=kona_player_info&scoringPeriodId={today}
x-fantasy-filter: {"players":{
  "filterStatus":{"value":["FREEAGENT","WAIVERS"]},
  "sortAppliedStatTotal":{"sortPriority":1,"sortAsc":false,"value":"10{season}"},
  "limit":150,
  "filterStatsForTopScoringPeriodIds":{"value":1,"additionalValue":["00{season}","10{season}","02{season}","00{season-1}"]}}}
```

VERIFIED (live): 150 players, 628,985 B plain, `X-Fantasy-Filter-Player-Count: 965`. Read `players[]{id, status (FREEAGENT|WAIVERS), waiverProcessDate (WAIVERS only; field VERIFIED bundle, not seen live because nobody is on waivers in preseason), player{fullName, proTeamId, defaultPositionId, eligibleSlots, injuryStatus, droppable, stats[]}}`.

Plus: my roster (`mRoster&forTeamId={me}`), `settings.rosterSettings.positionLimits` (`{"5": 4}` = at most 4 players whose default position is C), the schedule index, the matchup days.

### When does a pickup start counting

Status: VERIFIED (live, 2026 season of the reference league).

- `FREEAGENT` add sent **before the first tip-off of the scoring period**: the player is on that day's roster (25 of 25 sampled adds, checked with `mRoster&forTeamId={team}&scoringPeriodId={d}`).
- Add sent **after the first tip-off**: the record still says `scoringPeriodId = d`, but the player appears on the roster only from day d+1 (24 of 25; the 25th was gone by d+1).
- This is `rosterLocktimeType: FIRSTGAME_SCORINGPERIOD`. The player still needs a starting slot; the 599 executed 2026 adds stored `toLineupSlotId` 12 (bench) 411 times, 11 (UTIL) 112 times and another starting slot 76 times (who picks the slot is UNVERIFIED), so run recipe (c) right after an add.
- `WAIVERS` players are claims, not adds: 2026 claims were processed daily between 07:00 and 09:30 UTC (03:00 to 05:30 ET, the start of an ESPN day), 3.6 to 24.3 h after the claim, and 19 of 22 landed on the bench. So a claimed player counts from the day of `waiverProcessDate` (UNVERIFIED live for 2027) and needs the morning lineup run.
- The acquisition limit did not bind in 2026 (up to 5 adds per team per day, 9 per week; no `FAILED_MATCHUPACQUISITIONLIMIT`). VERIFIED (live, 2026).

### Computation

```
start = today if now < first_tip[today] else today + 1          # FREEAGENT
start = espn_day(waiverProcessDate)                             # WAIVERS
days  = [d for d in matchup_days if d >= start]
base  = sum(day_value(my_pool, d) for d in days)                # my_pool = non-IR roster
for each free agent x:
    for each drop candidate y in droppable non-IR roster (cheapest 3 by their own rest-of-week value):
        skip if x.defaultPositionId == 5 and y.defaultPositionId != 5 and centers_on_roster >= positionLimits["5"]
        gain(x, y) = sum(day_value(my_pool - y + x, d) for d in days) - base
    score(x) = max over y of gain(x, y); keep the y that achieves it
rank by score desc; show score, status, games in `days`, proj_ppg, suggested drop
```

The marginal formulation matters. Live result for matchup 1 (all 6 days, before day 1's first tip):

| Rank | Free agent | Status | Games | proj_ppg | Points added | Suggested drop |
|---|---|---|---|---|---|---|
| 1 | Cason Wallace | FREEAGENT | 3 | 24.1 | 47.7 | Coby White |
| 2 | Anfernee Simons | FREEAGENT | 4 | 23.4 | 45.5 | Coby White |
| 3 | Egor Demin | FREEAGENT | 3 | 30.0 | 38.7 | Coby White |
| 4 | Jared McCain | FREEAGENT | 3 | 20.2 | 35.9 | Coby White |
| 5 | Peyton Watson | FREEAGENT | 2 | 29.3 | 33.9 | Coby White |

VERIFIED (live data, computed). Why the marginal formulation matters, per day (VERIFIED, same data): Cason Wallace plays on days 1, 3 and 6, when only 2, 0 and 7 of my players have a game, so each of his games fills an empty starting slot (+24.1 each); dropping Coby White costs White's day 5 game (-24.6); net +47.7. A naive `proj_ppg x games` ranking (without the health factor) puts Jimmy Butler III first (38.8 x 3 = 116.4), but he is `OUT`, so his real gain is negative (he only removes the dropped player's game).

### Gotchas and performance

- The prototype (150 free agents x 3 drops x 6 days, plus recipe f) took 26 s of CPU in pure Python. For the TUI: compute in a worker thread, compute `base` once per day, and prune with the upper bound `sum(value(x, d) for d in days)`: stop when the bound falls below the current 10th best score. UNVERIFIED speedup, straightforward.
- Roster size: if non-IR players already fill starters plus bench (13 here), every add needs a drop; ESPN signals `TRAN_ROSTER_LIMIT_EXCEEDED_*` otherwise (04). Respect `player.droppable == false` (undroppable list).
- Use `injuryDetails.expectedReturnDate` for multi-day health instead of a flat DTD factor (1.3).

---

## (f) Trade finder: positional surplus, needs and a fair-value suggestion

### Requests

```
GET {L}?view=mRoster                      all rosters with projections (770,693 B, gzip about 149 KB)
GET {L}?view=mTeam                        teams[].tradeBlock.players {playerId: NORMAL|ON_THE_BLOCK|UNTOUCHABLE}, owners
GET {L}?view=mSettings                    lineupSlotCounts, positionLimits, tradeSettings.deadlineDate
FA pool from (e)                          replacement level per position
{G}?view=proTeamSchedules_wl              rest-of-season games per NBA team
```

All VERIFIED (live). Lock flags per player: `playerPoolEntry.tradeLocked` and `entries[].pendingTransactionIds` (VERIFIED live keys).

### Computation

```
1. Slot strength. For each team, solve best_lineup on an "everyone plays" day with vals = proj_ppg * health.
   slot_value[team][s] for the dedicated slots s in PG, SG, SF, PF, C.
   league_median[s] = median over teams.
2. Needs.   need[team][s]  = league_median[s] - slot_value[team][s]   (positive = weak spot)
3. Surplus. bench[team]    = players not in the team's optimal 10, with their eligible positions and values.
4. Fair value (rest of season, above replacement):
   ros_games(p)  = remaining scheduled games of p.proTeamId * (projected GP / scheduled team games)
   repl[pos]     = proj_ppg of the best free agent whose default position is pos
   vor(p)        = max(0, proj_ppg(p) - repl[p.defaultPosition]) * ros_games(p)
5. Candidates for rival R: my players eligible at a position where need[R] > 0 and that I can spare
   (bench or surplus at that position), for R's players eligible where need[me] > 0 and that sit on R's bench.
   Keep pairs with |vor(give) - vor(get)| <= 10% of the larger (product choice, UNVERIFIED as "fair").
6. Validity before proposing: after the swap, count(defaultPositionId == 5) <= positionLimits["5"] on both teams;
   no tradeLocked or pending players; now < tradeSettings.deadlineDate; skip players flagged UNTOUCHABLE.
7. The proposal itself is a TRADE_PROPOSAL write (04 section 7.1), only with the user's OK.
```

### Live result (preseason projections)

- League median of the dedicated slot (fantasy points per game): PG 45.3, SG 36.8, SF 35.7, PF 40.5, C 35.3. VERIFIED (live data, computed).
- Biggest needs: team 16 SG (15.7 below median), team 10 SF (11.1), team 13 PF (8.3), team 1 C (8.1). My team has no slot below the median; its best bench pieces are guards (Dyson Daniels 26.7, Coby White 24.6 ppg after the health factor).
- Example match the recipe surfaces (VERIFIED, same data): team 16 needs guards (SG 15.7, PG 7.1 below median) and has two strong bench bigs, John Collins (31.8, default PF, eligible PF and C) and Jakob Poeltl (31.7, default C). Team 1 needs a center (C 8.1 below median) and has a spare guard, Ryan Rollins (23.9, PG/SG). But team 1 already holds 4 players whose default position is C, so it cannot take Poeltl without sending a center back, while Collins does not count toward the cap. The validity step is what turns "Poeltl for Rollins" into "Collins for Rollins plus value".
- Centers by team (limit 4): teams 1 and 15 are at 4 and cannot take a center without sending one; my team has 3. VERIFIED (live).
- Replacement level (best free agent ppg by default position): PG 30.0, SG 30.2, SF 38.8, PF 28.5, C 30.3. VERIFIED (live data).
- Trade blocks in use: team 6 (1 UNTOUCHABLE) and team 14 (1 UNTOUCHABLE, 1 ON_THE_BLOCK, 1 NORMAL). VERIFIED (live).

### Gotchas

- A trade that breaks the position cap is rejected by ESPN (409 in earlier client runs, `TRAN_ROSTER_POSITION_LIMIT_EXCEEDED` in the bundle). Check locally first. Bundle detail type VERIFIED; HTTP status UNVERIFIED here.
- Preseason projections drive everything here; in-season, blend with recent form (`"02{season}"` L15 `appliedAverage` when `stats["42"] >= 3`) as 02 section 10 suggests.
- Player names are public, team names and owners are not: the UI may show them, logs and fixtures must not.

---

## (g) Alerts: trades sent to me, unread DMs, waiver results

### Trades

Primary (expected) source, cheap:

```
GET {L}?view=mPendingTransactions        key "pendingTransactions" absent when nothing is pending (VERIFIED live)
```

The web's trade review page looks incoming offers up here (VERIFIED bundle). Live today it only ever showed an accepted trade in review (01 section 12.1); a live incoming offer has not been observed, so treat this as UNVERIFIED and back it up with the log:

```
GET {L}?view=mTransactions2&scoringPeriodId={d}      for d in today and the previous 2 days (expiry is 48 h by default)
x-fantasy-filter: {"transactions":{"filterType":{"value":["TRADE_PROPOSAL","TRADE_ACCEPT","TRADE_DECLINE","TRADE_VETO","TRADE_UPHOLD"]}}}

open_offers = proposals P with
    P.type == "TRADE_PROPOSAL" and P.executionType == "EXECUTE"
    and P.teamId != {me} and any item with toTeamId == {me} or fromTeamId == {me}
    and P.expirationDate > now
    and no row R with R.relatedTransactionId == P.id     # CANCEL (withdrawn), TRADE_DECLINE, TRADE_ACCEPT resolve it
```

VERIFIED (live) on the records of 2026-10-15: all three `PENDING` proposals resolve this way (one withdrawn by team 10 one minute after creation, one declined by team 2, one accepted by team 1 and processed at `processDate`, 2026-10-15 15:02 UTC). Proposals between two other teams are not returned (04). The per-day `scoringPeriodId` rule is VERIFIED (live, 2026); in the 2027 preseason the parameter is ignored and the whole log comes back.

Secondary signal: a type 271 card (author `LM`, `attributes.tId` = proposal id) lands in the DM topic with the proposer (04 section 10, VERIFIED live).

### Unread DMs and league chat

```
GET {L}?view=chat_conversations                                         8,348 B, all topic types
GET {L}?view=chat_conversations  + {"communication":{"topics":{"filterType":{"value":["CHAT_ALL_MEMBERS","CHAT_DIRECT_MESSAGE"]}}}}
                                                                        3,691 B, only the 5 chat topics
```

VERIFIED (live): DM topics carry `id, type, dateEdited, unreadMessageCount, lastRead{memberId: ms}, viewableBy[]`, and the caller's SWID is in both `lastRead` and `viewableBy`, so counts are per caller. A bare `{"topics": ...}` filter on this path returns 400 (it works only on `{L}/communication/`). Activity topics also report unread counts (34 activity topics plus the legacy `CHAT` topic were unread today, out of 40 topics, while all 4 DMs and the league chat were at 0); filter by type for the alert.

Cheapest poll (VERIFIED live, served by both `lm-api-reads` and `lm-api-communication`):

```
GET https://lm-api-reads.fantasy.espn.com/apis/v3/communication/lastReadByMember?view=chat_unreads&platform=chat
-> {"lastReadByGroup": {"{leagueId}.{gameId}.{seasonId}": {"lastMessageDate": ms, "unread": bool, "lastReadByTopic": {"{topicId}": {"unread": bool}}}}}
```

Poll it every minute; when `unread` flips or `lastMessageDate` grows, fetch `chat_conversations` for counts. Reading never marks anything as read (marking read is a separate POST, 04).

### Waiver results

```
GET {L}?view=mStatus                                   status.waiverLastExecutionDate (epoch ms): new run since last check?
GET {L}?view=mTransactions2&scoringPeriodId={today}
x-fantasy-filter: {"transactions":{"filterType":{"value":["WAIVER","WAIVER_ERROR"]}}}
keep executionType == "PROCESS": status EXECUTED (claim won) or FAILED_* (claim lost, e.g. FAILED_INVALIDPLAYERSOURCE)
```

VERIFIED (live, 2026): 22 `EXECUTED` and 11 `FAILED_INVALIDPLAYERSOURCE` process rows, no `WAIVER_ERROR` rows, runs daily between 07:00 and 09:30 UTC. League-wide context: the activity feed (`{L}/communication/?view=kona_league_communication` with `filterIncludeMessageTypeIds [180, 181]`, VERIFIED live) and the type 273 "Waiver Wire Report" chat card (04).

### Cadence

`mPendingTransactions` and `chat_unreads` every 1 to 5 minutes with `If-None-Match` (304 has an empty body, VERIFIED live); `mTransactions2` for waivers once after 09:30 UTC; everything paused when the user is not running the app, except an optional scheduled job.

---

## (h) First-run setup for a new user

### Step 1: credentials

The user pastes `espn_s2` and `SWID` (06 section 4.3). Reads need only `espn_s2`; writes and chat also need the SWID (VERIFIED live: SWID only -> 401, espn_s2 only -> 200).

### Step 2: discover leagues and team ids from the cookies

```
GET https://fan.api.espn.com/apis/v2/fans/{SWID, url-encoded}?displayHiddenPrefs=true&context=fantasy&useCookieAuth=true&source=fantasyapp-ios&featureFlags=challengeEntries
Cookie: espn_s2=...; SWID=...
```

This is the exact path the ESPN chat app uses (VERIFIED bundle `chat-7847ae3f.js`: resource `preferences` on host `fan.api.espn.com`, `withCredentials`). Live: 200, 7,119 B. VERIFIED (live).

| Path | Type | Meaning |
|---|---|---|
| `preferences[]` | list | Keep items with `type.code == "fantasy"` (`typeId` 9, "Fantasy League Manager") |
| `preferences[].metaData.entry.gameId` | int | 1 ffl, 2 flb, 3 fba, 4 fhl, 5 wfba (VERIFIED live via `games/{abbrev}` ids) |
| `...entry.seasonId` | int | `2027` |
| `...entry.entryId` | int | **teamId** (`3`) |
| `...entry.groups[0].groupId` | int | **leagueId** |
| `...entry.groups[0].groupName`, `groupSize`, `groupManager`, `draftTypeName` | str, int, bool, str | league name, 10, false, `"Snake"` |
| `...entry.entryMetadata.teamName`, `teamAbbrev`, `scoringTypeName` | str | team name, abbrev, `"H2H_POINTS"` |
| `...entry.entryURL` | str | `https://fantasy.espn.com/basketball/team?leagueId=..&seasonId=..&teamId=..` |
| `...entry.currentLineup` | {playerId: lineupSlotId} | Today's slots (only with cookies) |
| `...entry.lineup.proGameToNumPlayersStarting` | {gameId: int} | My starters per NBA game today (only with cookies) |
| `preferences[].metaData.inSeason`, `isLive`, `currentScoringPeriodId` | bool, bool, int | `true`, `false`, `1` (`inSeason` was already true in preseason) |
| `fantasyData.leaguesBySportLeague` | {NFL, MLB, NBA, NHL, WNBA: int} | League counts per sport |

Variants (VERIFIED live): `?context=fantasy` alone returns only the fantasy preference; no query returns 4 preference types (`teams`, `fantasy`, `players`, `sports`); the extra display parameters (`displayEvents`, `displayNow`, `displayRecs`) add a 142,855 B `recommendations` block that setup does not need. The SWID may be lowercase; the braces must be URL-encoded (`%7B...%7D`); without braces the API returns 404 and with raw braces Tomcat returns an HTML 400.

Privacy finding (VERIFIED live): the same request **without any cookie** still returned 200 with the user's league id, team id, league name and team name; cookies add `profile.email`, `profile.firstName`, `profile.lastName`, `profile.userName`, `currentLineup` and `lineup`. A SWID is visible to every league mate (`members[].id`), so the app must never print it, log this response, or ship it in fixtures.

### Step 3: choose and confirm

```
candidates = fantasy entries with gameId == 3 (fba), newest seasonId first; ask the user if more than one
GET {L for that season and leagueId} (no view)          VERIFIED (live): 2,043 B
confirm: SWID (case-insensitive) is in teams[].owners of team entryId   (01 section 3)
GET {L}?view=mSettings                                   league name, scoring type, slots: show and save
```

Season auto-detection: `GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba` -> `currentSeasonId` (public; VERIFIED live: fba 2027 with current scoring period 1; ffl 2026, flb 2026, fhl 2027, wfba 2026). Prefer the newest `seasonId` among the user's fba entries and fall back to `currentSeasonId`. Off-season detection: `status.latestScoringPeriod > status.finalScoringPeriod` (05).

Fallbacks: the keys of `lastReadByMember?view=chat_unreads` (`{leagueId}.{gameId}.{seasonId}`, VERIFIED live, includes past seasons with chat activity), or a league URL pasted by the user (`leagueId=` query parameter).

### Gotchas

- A 401 on step 3 with a valid fan API answer means the league is private and the `espn_s2` value is wrong or expired (`AUTH_LEAGUE_NOT_VISIBLE`).
- Public leagues answer step 3 without cookies; the app can offer a read-only mode for them (UNVERIFIED for a real public league; `leaguedefaults/1` is the only public league object tested, 01 section 17).
- Do not hard-code `segments/0`, slot counts or scoring weights: read them from `mSettings` for each league (VERIFIED: they are league settings).

---

## Open questions

1. Do live incoming trade offers appear in `mPendingTransactions` (as the web's trade review page expects), and with which `type` (`TRADE_PROPOSAL`)? No open offer existed during the probes.
2. In-season 2027, does `mTransactions2` require `scoringPeriodId` per day like the completed 2026 season, or keep returning the whole log like the preseason? Check on Wed Oct 21, 2026 with `scoringPeriodId` 1 and 2.
3. Does `status.transactionScoringPeriod` move to `latestScoringPeriod + 1` after the day's first tip-off? That would give the pickup start day without a schedule lookup.
4. Who chooses the `toLineupSlotId` of an `ADD` item (2026 adds landed in starting slots about 160 times): the client, or the server filling an open slot?
5. Is `waiverProcessDate` present on `WAIVERS` players in `kona_player_info`, and is it the 07:00 to 09:30 UTC run time? No player was on waivers in preseason.
6. What do `matchupAcquisitionLimit: 1.0`, `matchupLimitPerScoringPeriod: true`, `waiverProcessDays: ["SUNDAY"]` and `waiverProcessHour: 8` actually control, given that none of them matched 2026 behavior?
7. Do `lineupLocked` flags flip at each player's tip-off in-season (expected from `lineupLocktimeType: INDIVIDUAL_GAME`)? Needed to freeze players in recipes (a) and (c).
8. Can the free agent ranking run fast enough for the TUI with the proposed pruning, or does it need a smaller candidate set (for example the top 60 by `proj_ppg x games`)?
9. Is a fairness band of 10 percent of rest-of-season value over replacement a good default for trade suggestions, and should it weigh positional scarcity (center cap) explicitly?
10. Should the fan API's no-cookie exposure of league ids and team names be mentioned in the README's security section (it is ESPN behavior, not the app's)?

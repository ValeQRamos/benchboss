# 05. Matchups, live scoring, schedule math and projections

Covers the league `schedule[]` (matchups and scores), the views that decorate it (`mMatchupScore`, `mScoreboard`, `mBoxscore`, `mMatchup`, `mMatchupScoreLite`), and the params and filters that shape it.
Explains the calendar model (scoring period = one day, weekly periods, matchup periods), how to map any date to a scoring period and matchup, the NBA schedule feeds, and the public live game status feeds.
ESPN exposes no matchup projection for basketball: the app must build its own. A verified recipe and a precomputed games per week table are included.

Probed on 2026-10-15 (preseason, `scoringPeriodId` 1) against the reference league (season 2027), plus the completed 2026 season of the same league for in-season shapes. ESPN front-end bundle: kona build `7411ee0540f4-1.517` (`main-f2aedb781c45b792f61b.js`, `page/basketball/league.js`).

Status legend: **VERIFIED** = seen in a live response or in ESPN's own JS bundle (source cited). **UNVERIFIED** = inferred, from memory or third-party code, or not observable before games start.

---

## Quick reference

| Method | URL / view | Purpose | Auth | Status |
|---|---|---|---|---|
| GET | `{LEAGUE}?view=mMatchupScore` | All matchups with `totalPoints`; current matchup also gets live fields and day roster | cookies | VERIFIED |
| GET | `{LEAGUE}?view=mMatchupScoreLite` | All matchups, only `teamId` + `totalPoints` per side | cookies | VERIFIED |
| GET | `{LEAGUE}?view=mScoreboard` | Adds player identity to day rosters, `teams[]`, `scoreByStat`; omits `matchupPeriodId` | cookies | VERIFIED |
| GET | `{LEAGUE}?view=mBoxscore` | Adds player identity, `rosterForMatchupPeriod` (with `scoringPeriodId`), `teams[]` | cookies | VERIFIED |
| GET | `{LEAGUE}?view=mMatchup` | Adds `gamesPlayed`, rich roster entries, `teams[].roster` | cookies | VERIFIED |
| GET | `{LEAGUE}?view=mStatus` | `currentMatchupPeriod`, `latestScoringPeriod`, `finalScoringPeriod`, `standingsUpdateDate` | cookies | VERIFIED |
| GET | `{LEAGUE}?view=mSettings` | `scheduleSettings.matchupPeriods`, `periodTypeId`, playoff and scoring settings | cookies | VERIFIED |
| param | `scoringPeriodId=N` | Selects the day for day rosters and player stats | n/a | VERIFIED |
| param | `matchupPeriodId=N` | No effect (ignored by the server) | n/a | VERIFIED |
| header | `x-fantasy-filter: {"schedule":{"filterMatchupPeriodIds":{"value":[N]}}}` | Only matchups of period N | n/a | VERIFIED (bundle + live) |
| header | `x-fantasy-filter: {"schedule":{"filterCurrentMatchupPeriod":{"value":true}}}` | Only the current matchup period | n/a | VERIFIED (bundle + live) |
| header | `x-fantasy-filter: {"schedule":{"filterTeamIds":{"value":[3]}}}` | Only matchups of these teams (combinable) | n/a | VERIFIED (live only, not in bundle) |
| GET | `{SEASON}?view=proTeamSchedules_wl` | Every NBA game by team and scoring period | public | VERIFIED |
| GET | `{SEASON}?view=proTeamSchedules` | Same games plus scores and game state fields | public | VERIFIED |
| GET | `{SEASON}` and `{SEASON}?view=kona_game_state` | Season dates, current scoring period, game flags | public | VERIFIED |
| GET | `.../seasons/2026/segments/0/leagues/{id}?view=...` | Previous season, same views | cookies | VERIFIED |
| GET | `https://site.api.espn.com/apis/fantasy/v2/games/fba/games?dates=YYYYMMDD[-YYYYMMDD]` | Live NBA game status as used by the fantasy web app | public | VERIFIED |
| GET | `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` | Full public NBA scoreboard | public | VERIFIED |
| static | kona `main.js` constants `scoringPeriods[]`, `segments[].periodTypes[]` | Authoritative day and week calendar | public | VERIFIED |
| field | `totalProjectedPoints`, `totalProjectedPointsLive`, `winProbability` on matchup sides | Read by the web client; never observed for `fba` | cookies | UNVERIFIED |

Base URLs used below:

```
{READS}  = https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba
{LEAGUE} = {READS}/seasons/{season}/segments/0/leagues/{leagueId}
{SEASON} = {READS}/seasons/{season}       # examples use 2027
```

All requests are `GET` with `Accept: application/json`. League endpoints need the `espn_s2` and `SWID` cookies (without them: `HTTP 401`, VERIFIED). Season and site endpoints are public (VERIFIED with no cookies). League responses carry `X-Fantasy-Server-Time` (RFC 1123 date) and `Cache-Control: must-revalidate`, `Expires: -1` (VERIFIED); the web client uses the server time to correct the local clock (VERIFIED in `main.js`).

---

## 1. The calendar model

### 1.1 Three units

| Unit | Meaning in this league | Source |
|---|---|---|
| Scoring period (`scoringPeriodId`) | One day. Lineups are set and scored per day. 1 to 174 for the season, 175 is the post-season bucket. | VERIFIED (bundle `constants.scoringPeriods`, league `status.finalScoringPeriod` = 174) |
| Week (period of `periodTypeId` 2) | A run of scoring periods. 24 weeks plus a 1 day week 25. Week 18 is 14 days (All-Star). | VERIFIED (bundle `segments[0].periodTypes[id=2].periods`) |
| Matchup period (`matchupPeriodId`) | One H2H round. Maps to one or more weeks via `scheduleSettings.matchupPeriods`. | VERIFIED (`mSettings`) |

`settings.scheduleSettings` (VERIFIED, `mSettings`):

```json
{
  "matchupPeriodCount": 20,
  "matchupPeriodLength": 1,
  "periodTypeId": 2,
  "playoffMatchupPeriodLength": 2,
  "playoffTeamCount": 4,
  "playoffSeedingRule": "H2H_RECORD",
  "playoffReseed": false,
  "variablePlayoffMatchupPeriodLength": false,
  "consolationLadderDisabled": false,
  "divisions": [{"id": 0, "name": "East", "size": 5}, {"id": 1, "name": "West", "size": 5}],
  "matchupPeriods": {"1": [1], "2": [2], "...": "...", "20": [20], "21": [21, 22], "22": [23, 24]}
}
```

`matchupPeriods` maps a matchup period id to a list of **week ids** (not scoring periods). Regular season = matchups 1 to 20 (`matchupPeriodCount`); playoffs = 21 and 22, two weeks each.

### 1.2 Where the week boundaries come from

The API does not return week boundaries. ESPN's web client gets them from constants compiled into `main.js` (VERIFIED, kona 1.517):

- `constants.scoringPeriods[]`: `{id, startDate, endDate, preSeason, postSeason}` with epoch ms.
- `constants.segments[0].periodTypes[]`: `{id, daily, weekly, seasonLong, periods: [{id, scoringPeriodStart, scoringPeriodEnd}]}`. `periodTypes[id=2]` is the weekly table.

The client maps a scoring period to a matchup like this (VERIFIED, `league.js` function using `scheduleSettings.matchupPeriods`): find the weekly period whose `[scoringPeriodStart, scoringPeriodEnd]` contains the day, then find the matchup whose list contains that week id.

The bundle holds several sports' tables; the basketball one is the only one whose season-long period ends at 174. Extract the tables with a regular expression over the bundle text; never execute the bundle.

### 1.3 Day boundaries: 03:00 Eastern, not midnight

Every `scoringPeriods[n]` runs from 03:00 America/New_York to 03:00 the next day (VERIFIED, bundle constants; for example period 2 = 2026-10-21 03:00 EDT to 2026-10-22 03:00 EDT). Period 1 starts 2026-05-27 03:00 EDT, so the whole preseason is scoring period 1 (VERIFIED: league `scoringPeriodId` = 1 today).

Consequences:

- A West Coast game that ends after midnight still belongs to the previous scoring period.
- For a user on US Central time the ESPN day changes at 02:00 local time. Computing "today" from the local calendar date is wrong between midnight and 02:00.
- Every NBA game in `proTeamSchedules` has `scoringPeriodId == (Eastern calendar date of tip-off) - 2026-10-20 + 1`. Checked on all 1200 scheduled games, 0 mismatches (VERIFIED).

### 1.4 The 2027 season calendar

Season day 1 = Tuesday 2026-10-20. Scoring period `n` = 2026-10-20 + (n - 1) days.

| Matchup | Weeks | Scoring periods | Dates (2026 to 2027) | Days | Type |
|---|---|---|---|---|---|
| 1 | [1] | 1 to 6 | Tue Oct 20 to Sun Oct 25 | 6 | regular |
| 2 | [2] | 7 to 13 | Mon Oct 26 to Sun Nov 1 | 7 | regular |
| 3 | [3] | 14 to 20 | Mon Nov 2 to Sun Nov 8 | 7 | regular |
| 4 | [4] | 21 to 27 | Mon Nov 9 to Sun Nov 15 | 7 | regular |
| 5 | [5] | 28 to 34 | Mon Nov 16 to Sun Nov 22 | 7 | regular |
| 6 | [6] | 35 to 41 | Mon Nov 23 to Sun Nov 29 | 7 | regular |
| 7 | [7] | 42 to 48 | Mon Nov 30 to Sun Dec 6 | 7 | regular |
| 8 | [8] | 49 to 55 | Mon Dec 7 to Sun Dec 13 | 7 | regular |
| 9 | [9] | 56 to 62 | Mon Dec 14 to Sun Dec 20 | 7 | regular |
| 10 | [10] | 63 to 69 | Mon Dec 21 to Sun Dec 27 | 7 | regular |
| 11 | [11] | 70 to 76 | Mon Dec 28 to Sun Jan 3 | 7 | regular |
| 12 | [12] | 77 to 83 | Mon Jan 4 to Sun Jan 10 | 7 | regular |
| 13 | [13] | 84 to 90 | Mon Jan 11 to Sun Jan 17 | 7 | regular |
| 14 | [14] | 91 to 97 | Mon Jan 18 to Sun Jan 24 | 7 | regular |
| 15 | [15] | 98 to 104 | Mon Jan 25 to Sun Jan 31 | 7 | regular |
| 16 | [16] | 105 to 111 | Mon Feb 1 to Sun Feb 7 | 7 | regular |
| 17 | [17] | 112 to 118 | Mon Feb 8 to Sun Feb 14 | 7 | regular |
| 18 | [18] | 119 to 132 | Mon Feb 15 to Sun Feb 28 | 14 | regular (All-Star double week) |
| 19 | [19] | 133 to 139 | Mon Mar 1 to Sun Mar 7 | 7 | regular |
| 20 | [20] | 140 to 146 | Mon Mar 8 to Sun Mar 14 | 7 | regular (last) |
| 21 | [21, 22] | 147 to 160 | Mon Mar 15 to Sun Mar 28 | 14 | playoff round 1 |
| 22 | [23, 24] | 161 to 174 | Mon Mar 29 to Sun Apr 11 | 14 | final round |

Week 25 (scoring period 175, Mon Apr 12 onward) is the post-season bucket and belongs to no matchup.

Server-side confirmation (VERIFIED, live): when `scoringPeriodId=N` is passed, `rosterForCurrentScoringPeriod` is attached only to the matchup that contains day N (see section 4.1). Probing boundary days with `filterMatchupPeriodIds` 2 to 20 and `filterTeamIds [3]` returned: 6 (Oct 25) -> none (matchup 1), 7 -> 2, 13 -> 2, 14 -> 3, 118 (Feb 14) -> 17, 119 (Feb 15) -> 18, 125 -> 18, 126 (Feb 22) -> 18, 132 (Feb 28) -> 18, 133 (Mar 1) -> 19, 146 -> 20, 147 -> none (playoffs not generated yet).

### 1.5 Gotchas

- **The double week moves every season.** In the 2026 season of this same league, matchup 17 was the 14 day week (scoring periods 112 to 125) and matchup 18 was 7 days (VERIFIED from 2026 `pointsByScoringPeriod` keys). Never hard-code "matchup 18".
- A date heuristic (week 1 runs to the first Sunday, then Monday to Sunday, and the week where a 3+ day NBA gap starts between January and March is merged with the next one) reproduces the 2027 table exactly (all 24 weeks VERIFIED against the bundle table) and also explains the 2026 table. It is still a heuristic: the 8 day December NBA Cup gap (section 6.3) would break it if the month guard were removed.
- `status.currentMatchupPeriod` is 1 during the preseason (VERIFIED). Use the date math, not `currentMatchupPeriod`, to label "this week" before day 1.
- Off-season detection used by the web client: `status.latestScoringPeriod > status.finalScoringPeriod` or `seasonId < currentSeason` (VERIFIED, `main.js`). The completed 2026 season reports `latestScoringPeriod` 175, `finalScoringPeriod` 174, `currentMatchupPeriod` 22 (VERIFIED).

### 1.6 How the app should map dates

1. Primary: load the weekly table (bundle constants, cached per season) and `scheduleSettings.matchupPeriods`. `sp = (eastern_date(now - 3h) - day1).days + 1`, clamped to [1, 175]. Matchup = the key whose week list contains the week that contains `sp`.
2. Fallback when the bundle is unavailable: the date heuristic of section 1.5, then validate it once per day by requesting `mMatchupScore` with `scoringPeriodId` = first day of the computed week plus `filterTeamIds [{me}]`, and checking which matchup gets `rosterForCurrentScoringPeriod`.
3. Use ESPN's own `scoringPeriodId` (top level of any league response) as the source of truth for "today" when online.

---

## 2. League status: `view=mStatus`

**Request** (VERIFIED): `GET {LEAGUE}?view=mStatus` (about 1 KB).

**Response, relevant paths** (VERIFIED):

| Path | Type | Example | Notes |
|---|---|---|---|
| `scoringPeriodId` | int | 1 | ESPN "today" (or the echoed `scoringPeriodId` param on other views) |
| `status.currentMatchupPeriod` | int | 1 | 1 in preseason |
| `status.latestScoringPeriod` | int | 1 | last day with processed stats; drives the client live formula |
| `status.firstScoringPeriod` / `finalScoringPeriod` | int | 1 / 174 | |
| `status.transactionScoringPeriod` | int | 1 | |
| `status.standingsUpdateDate` | int (epoch ms) | 1791860708619 | nightly standings job time (2026-10-13 03:05 UTC here) |
| `status.waiverProcessStatus` | object | `{"2026-10-14T07:39:06.423+00:00": 1}` | keys are ISO timestamps |
| `status.creationInfo.source`, `status.lastUpdateInfo` | str | `{SWID}`, `NightlyLeagueUpdateTaskProcessor` | `creationInfo.source` is a member SWID: never log it |

The `status` block is also included (without `creationInfo`/`lastUpdateInfo`) by `mMatchupScore`, `mBoxscore`, `mMatchup` and `mSettings` (VERIFIED), so a separate `mStatus` call is rarely needed.

---

## 3. `schedule[]` entry reference

One entry per matchup and pair of teams. 10 teams -> 5 entries per matchup period, 100 entries for matchups 1 to 20 today (VERIFIED). Playoff entries (21, 22) do not exist yet in preseason (VERIFIED, filter returns 0); in the completed 2026 season there were 110 entries, 5 per playoff period, with `playoffTierType` in `WINNERS_BRACKET`, `WINNERS_CONSOLATION_LADDER`, `LOSERS_CONSOLATION_LADDER` (VERIFIED).

### 3.1 Entry level

| Path | Type | Example | Status |
|---|---|---|---|
| `id` | int | 2 | VERIFIED |
| `matchupPeriodId` | int | 1 | VERIFIED (absent with `mScoreboard` alone) |
| `playoffTierType` | str | `NONE` | VERIFIED |
| `winner` | str | `UNDECIDED`, `HOME`, `AWAY` (and presumably `TIE`) | VERIFIED for the first three; `winner` matched the higher `totalPoints` in all 110 entries of 2026 |
| `home`, `away` | object | see 3.2 | VERIFIED (no bye entries in this league) |

### 3.2 Side level (`home` / `away`)

| Path | Type | Present when | Meaning | Status |
|---|---|---|---|---|
| `teamId` | int | always | fantasy team id (ids here: 1, 2, 3, 6, 10, 11, 13, 14, 15, 16; not contiguous) | VERIFIED |
| `totalPoints` | float | always | official matchup points: `sum(pointsByScoringPeriod) + adjustment` | VERIFIED (2026: 0 mismatches in 220 sides) |
| `totalPointsLive` | float | current matchup only | live total; equals `totalPoints` after the matchup closes | VERIFIED (presence); live freshness UNVERIFIED |
| `adjustment` | float | most views | manual LM adjustment | VERIFIED |
| `tiebreak` | float | most views | | VERIFIED |
| `eliminationMatchupPeriod` | int | most views | 0 = not eliminated | VERIFIED |
| `pointsByScoringPeriod` | `{ "<sp>": float }` | current and past matchups | starters' points per day; keys are every scoring period of the matchup so far, days without games are 0.0 | VERIFIED (2026 keys = exact day ranges per matchup) |
| `cumulativeScore` | object | always | `wins`, `losses`, `ties` (0 in points leagues), `statBySlot` (null), `scoreByStat` (with `mScoreboard`/`mBoxscore`/`mMatchup` or `scoringPeriodId`) | VERIFIED |
| `cumulativeScore.scoreByStat.<statId>` | `{score, rank, result, ineligible}` | as above | `score` = raw stat total of starters for the matchup; `sum(score * points)` = `totalPoints` | VERIFIED (2026 matchup 8: 1025.0 = 1025.0) |
| `cumulativeScoreLive` | object | current matchup only | live version of `cumulativeScore` | VERIFIED (presence) |
| `rosterForCurrentScoringPeriod` | `{appliedStatTotal, entries[]}` | current matchup, or the matchup containing `scoringPeriodId` | lineup and stats for one day | VERIFIED |
| `rosterForMatchupPeriod` | `{appliedStatTotal, entries[]}` | with `mBoxscore`/`mScoreboard`/`mMatchup` | per player totals for the whole matchup | VERIFIED |
| `rosterForMatchupPeriodDelayed` | `{appliedStatTotal, entries[]}` | current matchup, `mMatchupScore`/`mBoxscore` | matchup totals as of the last standings run (empty preseason) | VERIFIED (presence); in-season content UNVERIFIED |
| `gamesPlayed` | int | `mMatchup` only | always 0 in this league, even in completed 2026 matchups | VERIFIED |
| `totalProjectedPoints`, `totalProjectedPointsLive`, `winProbability`, `adjustmentReason`, `eliminationProbabilityStatus` | number / str | never observed | read by the web client model (`main.js`); not present in any `fba` response, 2027 preseason or 2026 completed | UNVERIFIED |

Trimmed real example (`view=mMatchupScore&view=mBoxscore&scoringPeriodId=1`, filtered to matchup 1 and the caller's team; VERIFIED):

```json
{
  "id": 2, "matchupPeriodId": 1, "playoffTierType": "NONE", "winner": "UNDECIDED",
  "home": {
    "teamId": 3, "totalPoints": 0.0, "totalPointsLive": 0.0,
    "adjustment": 0.0, "tiebreak": 0.0, "eliminationMatchupPeriod": 0,
    "pointsByScoringPeriod": {"1": 0.0},
    "cumulativeScore": {"wins": 0, "losses": 0, "ties": 0, "statBySlot": null,
      "scoreByStat": {"0": {"score": 0.0, "rank": 0.0, "result": null, "ineligible": false}, "...": "11 scoring stat ids"}},
    "cumulativeScoreLive": {"wins": 0, "losses": 0, "ties": 0, "statBySlot": null, "scoreByStat": "same shape"},
    "rosterForCurrentScoringPeriod": {"appliedStatTotal": 0.0, "entries": "[13 entries]"},
    "rosterForMatchupPeriod": {"appliedStatTotal": null, "entries": []},
    "rosterForMatchupPeriodDelayed": {"appliedStatTotal": null, "entries": []}
  },
  "away": {"teamId": 14, "...": "same shape"}
}
```

### 3.3 Roster entries inside a side

`rosterForCurrentScoringPeriod.entries[]` (one day):

| Path | Type | Notes | Status |
|---|---|---|---|
| `lineupSlotId` | int | slot that day (12 = bench, 13 = IR) | VERIFIED |
| `playerId` | int | **absent with `mMatchupScore` alone** | VERIFIED |
| `playerPoolEntry.appliedStatTotal` | float | player's fantasy points that day, **counted even on bench/IR** | VERIFIED |
| `playerPoolEntry.player.{id, fullName, firstName, lastName, proTeamId, defaultPositionId, eligibleSlots[], universeId}` | | added by `mBoxscore`, `mScoreboard`, `mMatchup` | VERIFIED |
| `playerPoolEntry.player.{injured, injuryStatus, active, jersey}`, `entry.injuryStatus`, `entry.status`, `playerPoolEntry.{onTeamId, status}` | | added by `mScoreboard`, `mMatchup` | VERIFIED |
| `playerPoolEntry.{lineupLocked, rosterLocked, tradeLocked, keeperValue}`, `player.{droppable, lastNewsDate}`, `entry.{acquisitionDate, acquisitionType, pendingTransactionIds}` | | added by `mMatchup` | VERIFIED |
| `playerPoolEntry.player.stats[]` | list | the day's stat line, see below | VERIFIED (2026) |

Day stat line (VERIFIED, 2026 season, `scoringPeriodId=50`):

```json
{"id": "05401809834", "externalId": "401809834", "statSourceId": 0, "statSplitTypeId": 5,
 "scoringPeriodId": 50, "seasonId": 2026, "proTeamId": 28,
 "stats": {"0": 13.0, "1": 0.0, "2": 2.0, "3": 4.0, "...": "45 keys"},
 "appliedStats": {"0": 13.0, "1": 0.0, "2": 8.0, "3": 8.0, "17": 1.0, "16": 0.0, "...": "scoring ids only"},
 "appliedTotal": 25.0}
```

- `statSourceId` 0 = actual, `statSplitTypeId` 5 = single scoring period. `id` = `"0" + "5" + <NBA game id>`; `externalId` = the NBA game id, which equals the `proTeamSchedules` game `id` and the site API event `id` (VERIFIED).
- `appliedStats[statId] = stats[statId] * scoringItems[statId].points`; `appliedTotal = sum(appliedStats)` (VERIFIED: 2 steals -> 8.0 at 4 points, 4 assists -> 8.0 at 2 points).
- Players without a game that day have `stats: []` (VERIFIED).

`rosterForMatchupPeriod.entries[]` (whole matchup, VERIFIED 2026): same entry shape, but `lineupSlotId` is 0 for everybody (not meaningful), one stat line with `id: "05null"`, `scoringPeriodId: 0`, `statSplitTypeId: 5`, and `rosterForMatchupPeriod.appliedStatTotal` equals the side's `totalPoints` (1025.0 = 1025.0). Use it for "top scorers this matchup".

### 3.4 Starters only

`rosterForCurrentScoringPeriod.appliedStatTotal` and `pointsByScoringPeriod[sp]` count **starters only** (VERIFIED, 2026 day 170: a side with 24 points on IR and another with 44 bench points still had day totals equal to the starters' sum, 153.0 and 110.0). Per player `playerPoolEntry.appliedStatTotal` ignores the slot. Always filter `lineupSlotId not in (12, 13)` when summing.

### 3.5 Stat ids used by this league's scoring

`settings.scoringSettings.scoringItems` (VERIFIED, `mSettings`): `{statId: points}` = `0: +1, 1: +4, 2: +4, 3: +2, 6: +1, 11: -2, 13: +2, 14: -1, 15: +1, 16: -1, 17: +1`.

Names: 0 PTS, 1 BLK, 2 STL, 3 AST, 6 REB, 11 TO, 13 FGM, 14 FGA, 15 FTM, 16 FTA, 17 3PM (VERIFIED, `main.js` stat table; for example `apiIdentifier:"offensive.fieldGoalsAttempted",description:"Field Goals Attempted",displayAbbrev:"FGA",id:14`). The full stat map is in 02, section 5.

---

## 4. Views, params and filters

### 4.1 What each view adds

All rows are VERIFIED from live 2027 responses (sizes are for all 100 matchups, preseason, without `scoringPeriodId`):

| View | Size | Top level | Per entry and side |
|---|---|---|---|
| `mMatchupScoreLite` | small | `schedule`, `status`, `scoringPeriodId` | `id`, `matchupPeriodId`, `winner`, sides with only `teamId`, `totalPoints`. Used by the web client for the whole league schedule (`main.js`). |
| `mMatchupScore` | 52 KB | + `status` | full side fields (3.2); current matchup adds `totalPointsLive`, `cumulativeScoreLive`, `pointsByScoringPeriod`, `rosterForCurrentScoringPeriod` (entries = `lineupSlotId` + stats only), `rosterForMatchupPeriodDelayed` |
| `mScoreboard` | 102 KB | + `teams[]` (`id, abbrev, name, logo, divisionId, record.overall, rankCalculatedFinal`), `settings` subset (`scheduleSettings.matchupPeriods/divisions/periodTypeId`, `scoringItems`), `status` subset (4 keys) | **no `matchupPeriodId`**, no live fields; player identity and injury in `rosterForCurrentScoringPeriod`; `rosterForMatchupPeriod` (current matchup, empty in preseason); `scoreByStat` for the current matchup |
| `mBoxscore` | 81 KB | + `teams[]`, `settings` subset, `status` | player identity in day rosters; `rosterForMatchupPeriod` and `rosterForMatchupPeriodDelayed` on the current matchup only |
| `mMatchup` | 207 KB | + `teams[].roster` (full rosters) | `gamesPlayed`, rich roster entries (locks, keeper, acquisition) |

`teams[].name` and `abbrev` are member-chosen strings; render them, do not log them with member ids.

### 4.2 `scoringPeriodId`

- Echoed as top-level `scoringPeriodId` (VERIFIED).
- Moves `rosterForCurrentScoringPeriod` to the matchup containing that day (VERIFIED: with `scoringPeriodId=8` and `filterMatchupPeriodIds [1, 2]`, matchup 2 gets it and the current matchup 1 loses it). Live fields (`totalPointsLive`, `cumulativeScoreLive`, `pointsByScoringPeriod`) stay on the **current** matchup (VERIFIED).
- With `mMatchup` or `mBoxscore`, it fills player `stats[]` (VERIFIED, 2026 history). In the 2027 preseason, `mMatchup` + `scoringPeriodId` adds season splits to `teams[].roster` players: `(source 0, split 0/1/2/3)` = season, last 7, last 15, last 30 days, `(1, 0)` = ESPN season projection, plus previous season `(0, 0, 2026)` and `(1, 0, 2026)` (VERIFIED). The payload grows from 207 KB to 775 KB.
- Days in the past are fully readable: `mBoxscore` + `scoringPeriodId=N` returns that day's lineup and stat lines (VERIFIED, 2026 days 50 and 170).

### 4.3 `x-fantasy-filter` for `schedule`

| Filter | Effect | Status |
|---|---|---|
| `{"schedule":{"filterMatchupPeriodIds":{"value":[N, ...]}}}` | only those matchup periods | VERIFIED (bundle `main.js` + live) |
| `{"schedule":{"filterCurrentMatchupPeriod":{"value":true}}}` | only the current period | VERIFIED (bundle `league.js` + live) |
| `{"schedule":{"filterTeamIds":{"value":[3]}}}` | only matchups of those teams (20 entries for team 3) | VERIFIED live; not used by the web client |
| combinations of the above | AND | VERIFIED (`filterCurrentMatchupPeriod` + `filterTeamIds` -> 1 entry, 15 KB) |

The plain query param `matchupPeriodId=N` is **ignored** (VERIFIED: identical 100 entry payload). Some third-party libraries pass it; do not rely on it.

### 4.4 Calls made by ESPN's own web app

- League home and scoreboard page (VERIFIED, `league.js`): views `modular, mNav, mMatchupScore, mScoreboard, mStatus, mSettings, mTeam, mPendingTransactions` with `filterCurrentMatchupPeriod`.
- Matchup detail (VERIFIED, `main.js`): views `mMatchup, mMatchupScore`, param `scoringPeriodId`, filter `filterMatchupPeriodIds [N]`.
- Whole schedule (VERIFIED, `main.js`): `mMatchupScoreLite`.

### 4.5 Previous seasons

`GET {READS}/seasons/2026/segments/0/leagues/{leagueId}?view=...` works with the same views (VERIFIED). `GET {READS}/leagueHistory/{leagueId}?view=mMatchupScore&seasonId=2026` also works and returns a JSON **array** with one league object (VERIFIED). `status.previousSeasons` = `[2023, 2024, 2025, 2026]` (VERIFIED).

---

## 5. Live scoring

### 5.1 How ESPN's client computes a live total

From `main.js` (VERIFIED), for a side in the current matchup on the latest scoring period:

```
liveTotalPoints = points of starters today, from rosterForCurrentScoringPeriod player stats
if standingsRunForCurrentPeriod:            # status.standingsUpdateDate > start of day latestScoringPeriod
    total = totalPoints + liveTotalPoints
else:
    total = rosterForMatchupPeriodDelayed.appliedStatTotal + adjustment + homeTeamBonus + liveTotalPoints
otherwise (any other matchup or day):
    total = totalPointsLive ?? totalPoints ?? 0
```

`homeTeamBonus` comes from `scoringSettings.homeTeamBonus` (0 here, VERIFIED). For multi-week matchups the client also shows per week subtotals by summing `pointsByScoringPeriod` over the week's day range (VERIFIED, `league.js`).

### 5.2 Recommended approach for the app

1. One request per refresh: `GET {LEAGUE}?view=mMatchupScore&view=mBoxscore&scoringPeriodId={today}` with `x-fantasy-filter: {"schedule":{"filterCurrentMatchupPeriod":{"value":true},"filterTeamIds":{"value":[3]}}}` (15 KB preseason, VERIFIED). Add `mScoreboard` only if injury status per entry is needed.
2. Score: prefer `totalPointsLive`; cross-check with `sum(pointsByScoringPeriod[d] for d < today) + adjustment + today_starters` where `today_starters = sum(entry.playerPoolEntry.appliedStatTotal for starters)`. If the two disagree, display `totalPointsLive` and mark the score as "updating" instead of picking one silently.
3. "Top scorers this matchup": `rosterForMatchupPeriod.entries[]` sorted by `appliedStatTotal`.
4. "Category breakdown": `cumulativeScore.scoreByStat` times `scoringItems` points.
5. Refresh cadence: every 60 s while any rostered player's game is `in` (section 7), every 15 min otherwise. Stay under 1 request per second.

---

## 6. NBA schedule (season endpoint)

### 6.1 Request

```
GET {SEASON}?view=proTeamSchedules_wl     # 423 KB, public
GET {SEASON}?view=proTeamSchedules        # 924 KB, public, same games plus game state
```

Both VERIFIED with and without cookies. The web client calls `proTeamSchedules_wl` once per season and caches it (VERIFIED, `main.js`).

### 6.2 Response

| Path | Type | Example | Status |
|---|---|---|---|
| `settings.proTeams[]` | list (31 items, id 0 = `FA`) | | VERIFIED |
| `settings.proTeams[].{id, abbrev, location, name, byeWeek, universeId}` | | `11, "IND", "Indiana", "Pacers", 0, 1` | VERIFIED |
| `settings.proTeams[].{color, alternateColor}` | str | only in `proTeamSchedules` | VERIFIED |
| `settings.proTeams[].proGamesByScoringPeriod` | `{ "<sp>": [game] }` | | VERIFIED |
| game `{id, date, scoringPeriodId, homeProTeamId, awayProTeamId, startTimeTBD, statsOfficial, validForLocking}` | | `401909839, 1792627200000, 2, 3, 11, false, false, true` | VERIFIED |
| game extra fields in `proTeamSchedules` | `homeScore, awayScore, inProgress, percentComplete, canceled, postponed, suspended, detail, indoor, snow, wind` | `detail: "10/21 - 8:00 PM EDT"` | VERIFIED (presence); live update cadence UNVERIFIED |
| `settings.seasonTransitionSettings.allStarGameDate` | epoch ms | 2027-02-21 | VERIFIED |
| `settings.playerOwnershipSettings.{firstGameDate, lastGameDate}` | epoch ms | 2026-10-20, 2027-04-11 | VERIFIED |
| `settings.statSettings.hasGameStatProjections` (`kona_game_state`) | bool | `false` | VERIFIED |

Bare `GET {SEASON}` returns `currentScoringPeriod.id` (1), `startDate`, `endDate` (VERIFIED).

### 6.3 Gotchas

- **Only 1200 of 1230 games are scheduled**: exactly 80 per team (VERIFIED). The public NBA scoreboard lists NBA Cup knockout games with TBD teams on Dec 4 and 5 (quarterfinals), Dec 8 (semifinal) and Dec 11 (championship) (VERIFIED). The fantasy schedule has no games at all from Dec 4 to Dec 11 (scoring periods 46 to 53). The 2 missing games per team should appear once the Cup group stage ends (UNVERIFIED timing). Matchups 7 and 8 are therefore provisional.
- Other league-wide off days (VERIFIED): Nov 3 (sp 15), Nov 26 (38), Dec 24 (66), Feb 19 to Feb 24 (123 to 128, All-Star break), Apr 10 (173).
- Abbreviations are ESPN's: `NY, GS, SA, NO, UTAH, WSH` (VERIFIED), not the common `NYK, GSW, SAS, NOP, UTA, WAS`. Key everything by `proTeamId` and render the abbreviation from the API.
- `proTeamId` equals the ESPN site API team id, and game `id` equals the site API event id (VERIFIED, opening night).
- The web client drops empty `proGamesByScoringPeriod` arrays before use (VERIFIED, `main.js`); do the same.
- At most 1 game per team per day (VERIFIED).

---

## 7. Live NBA game status

### 7.1 Fantasy games feed (what ESPN fantasy itself uses)

The fantasy web client builds its live "pro games" from this feed (VERIFIED, `main.js`: path `fantasy/v2/games/{uri_site_api}/games` on `https://site.api.espn.com/apis/`, params `dates`, `pbpOnly`, `seasontype`; response header `x-fantasy-game-count`; default date computed in America/Los_Angeles).

```
GET https://site.api.espn.com/apis/fantasy/v2/games/fba/games?dates=20261020
GET https://site.api.espn.com/apis/fantasy/v2/games/fba/games?dates=20261020-20261025
```

Public, no cookies, `Cache-Control: max-age=36` (VERIFIED; a later request at 2026-10-15 15:31 UTC returned `max-age=1`, so the value varies and should not be hard-coded). The range form returned 43 games for Oct 20 to 25, matching the 43 games of matchup 1 (VERIFIED). Preseason games are excluded: `dates=20261015` returned 0 events while the public scoreboard lists 2 preseason games that day (VERIFIED).

Response (VERIFIED):

```json
{"events": [{
  "id": "401909088", "competitionId": "401909088",
  "date": "2026-10-20T19:00:00Z", "timeValid": true,
  "status": "pre", "period": 0, "clock": "0.0", "percentComplete": 0,
  "summary": "10/20 - 3:00 PM EDT",
  "fullStatus": {"clock": 0.0, "displayClock": "0.0", "period": 0,
    "type": {"id": "1", "name": "STATUS_SCHEDULED", "state": "pre", "completed": false,
             "detail": "Tue, October 20th at 3:00 PM EDT", "shortDetail": "10/20 - 3:00 PM EDT"}},
  "competitors": [{"id": "8", "abbreviation": "DET", "homeAway": "home", "score": "", "winner": false,
                   "record": "...", "name": "Pistons", "type": "team", "lineup": [], "active": [], "inactive": []}],
  "lastPlay": {}, "odds": "...", "broadcasts": "...", "venue": "...", "fantasySource": {"id": "3", "state": "full"}
}], "statistics": []}
```

`status` values: `pre`, `in`, `post` (`pre`/`post` VERIFIED; `in` UNVERIFIED until games are live). A finished game: `status "post"`, `period 4`, `percentComplete 100`, `fullStatus.type.name "STATUS_FINAL"`, numeric `score` (VERIFIED, 2026-04-10).

### 7.2 Public NBA scoreboard (richer, heavier)

```
GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD
```

Public, `Cache-Control: max-age=3` (VERIFIED). `events[].{id, date, season.{year,type,slug}, status.{clock, displayClock, period, type.{name,state,completed,shortDetail}}, competitions[0].competitors[].{homeAway, team.{id,abbreviation}, score, winner, linescores, leaders}}` (VERIFIED). Includes preseason (`season.slug: "preseason"`) and NBA Cup notes (`competitions[0].notes[].headline`). The bundle also defines this path with a 10 s TTL (VERIFIED). Without `dates`, the default day lags (at 11:00 ET on Oct 15 it returned Oct 14, VERIFIED): always pass `dates`.

### 7.3 Gotchas

- `dates` is the US Eastern calendar date: a 9:30 PM EDT game appears under its Eastern date even though `date` is `...T01:30Z` the next day (VERIFIED). This matches ESPN's scoring period day except between 00:00 and 03:00 ET.
- Join to fantasy data by `event.id == game id` and `competitor.id == proTeamId`.
- Use the fantasy feed for the dashboard (one 30 to 300 KB call for a whole week); use the site scoreboard only for extras such as linescores.

---

## 8. Projections

### 8.1 What ESPN provides for basketball

| Item | Where | Status |
|---|---|---|
| Season projection per player: `stats[]` entry with `statSourceId 1`, `statSplitTypeId 0`, `seasonId 2027`; `appliedAverage` = projected fantasy points per game, `appliedTotal` = season total | `kona_player_info`, `mRoster`, `mMatchup` + `scoringPeriodId` | VERIFIED |
| Per game or per day projections | `kona_game_state.settings.statSettings.hasGameStatProjections` = `false`; no `(source 1, split 1/5, scoringPeriodId N)` lines seen | VERIFIED absent |
| Matchup projected totals (`totalProjectedPoints`, `totalProjectedPointsLive`) and `winProbability` | the web client reads them from the side object, but only computes `totalProjectedPointsLive` itself when `supportsScoringPeriodProjections`, which is `"FFL" === abbreviation` (football only) | VERIFIED in `main.js`/`league.js`; never present in any `fba` response (UNVERIFIED whether the server ever sends them in-season) |

Conclusion: the app must compute its own projected final score.

### 8.2 Recommended projected final

A simple estimate takes, for each remaining day, the top N players with a game (N = number of starting slots) times projection times injury factor. Two weaknesses: it ignores slot eligibility (a day with 5 guards and 0 centers cannot fill C), and it decides "today counts or not" by an 18:00 local cutoff.

```
projected_final(side) =
    live_total(side)                                     # section 5.2
  + today_remaining(side)
  + sum over remaining days d after today in the matchup of best_lineup_value(side, d)

best_lineup_value(side, d):
    pool   = roster players not on IR whose proTeamId plays on d   (proTeamSchedules)
    value  = proj_ppg(player) * injury_factor(player)
    return the optimal slot assignment value                       (slot solver, 07 section 1.4)

today_remaining(side), per starter with a game today (fantasy games feed, section 7.1):
    pre  -> proj_ppg * injury_factor
    in   -> proj_ppg * (1 - percentComplete / 100)                  (live points already in live_total)
    post -> 0
```

- `proj_ppg` = season projection `appliedAverage` (source 1, split 0), falling back to last season's actual average.
- `lineupLocktimeType` is `INDIVIDUAL_GAME` (VERIFIED, `mSettings`): players lock at their own tip-off, so use actual lineups for players already locked and the optimal lineup only for the rest (approximation: use the optimal lineup for days after today).
- The remaining fraction formula mirrors ESPN's own generic code (`1 - percentComplete / C` for in-progress games, 0 after, 1 before; VERIFIED in `main.js`).
- Do the same for the opponent; "games" counter = number of filled starter slots across remaining days.

---

## 9. Games per team per matchup week

### 9.1 Data shape

Computed from `proTeamSchedules` + the bundle weekly table + `scheduleSettings.matchupPeriods` (VERIFIED computation). A convenient cache shape:

```json
{"ATL": {"1": 3, "2": 4, "...": "...", "22": 7}, "BKN": {"...": "..."}}
```

Keys: ESPN abbreviations (30 teams, `FA` excluded); inner keys: `matchupPeriodId` 1 to 22 (21 and 22 are two-week playoff matchups). Useful companion metadata: `abbrevToProTeamId`, date ranges, and per matchup min and max with the teams at each. Totals: 80 games per team, 1200 games overall (matches the schedule).

### 9.2 Min and max per matchup

| Matchup | Dates | NBA games | Min | Max | Note |
|---|---|---|---|---|---|
| 1 | Oct 20 to Oct 25 | 43 | 2 | 4 | 6 days; only PHI has 4 |
| 2 | Oct 26 to Nov 1 | 49 | 2 | 4 | only PHX has 2 |
| 3 | Nov 2 to Nov 8 | 54 | 3 | 4 | |
| 4 | Nov 9 to Nov 15 | 51 | 2 | 4 | |
| 5 | Nov 16 to Nov 22 | 51 | 2 | 4 | |
| 6 | Nov 23 to Nov 29 | 48 | 2 | 4 | |
| 7 | Nov 30 to Dec 6 | 29 | 1 | 2 | provisional (NBA Cup) |
| 8 | Dec 7 to Dec 13 | 14 | 0 | 1 | provisional (NBA Cup); DAL and LAL have 0 |
| 9 | Dec 14 to Dec 20 | 55 | 2 | 4 | |
| 10 | Dec 21 to Dec 27 | 53 | 2 | 4 | |
| 11 | Dec 28 to Jan 3 | 52 | 2 | 4 | |
| 12 | Jan 4 to Jan 10 | 54 | 3 | 5 | CHI has 5 |
| 13 | Jan 11 to Jan 17 | 52 | 2 | 5 | DEN has 5 |
| 14 | Jan 18 to Jan 24 | 52 | 2 | 4 | |
| 15 | Jan 25 to Jan 31 | 54 | 3 | 4 | |
| 16 | Feb 1 to Feb 7 | 54 | 3 | 4 | |
| 17 | Feb 8 to Feb 14 | 53 | 2 | 5 | POR has 5 |
| 18 | Feb 15 to Feb 28 | 62 | 3 | 5 | 14 days, 6 without NBA games |
| 19 | Mar 1 to Mar 7 | 49 | 2 | 4 | |
| 20 | Mar 8 to Mar 14 | 53 | 3 | 4 | |
| 21 | Mar 15 to Mar 28 | 106 | 5 | 8 | playoffs, 2 weeks |
| 22 | Mar 29 to Apr 11 | 112 | 6 | 8 | final, 2 weeks |

Validation for the "most active / least active players this week" widget: in regular weeks the spread is 2 to 4 games, sometimes 3 to 5, so a per player games count is a meaningful signal (a 4 game player is worth roughly double a 2 game player in a weekly H2H points matchup). Spread in the two-week playoff matchups is 5 to 8.

### 9.3 How the widget should work

- "This week" = the current matchup's scoring periods (section 1.6). For each rostered player: `games_left = count(d in [today..end] if proTeamId plays on d)`, and during the day subtract games already started or finished (section 7.1).
- Rank by `games_left`, break ties by `games_left * proj_ppg`. Show free agents with `max` games for streaming suggestions.
- Recompute from the cached schedule daily (a 1 day cache is enough); regenerate the table once the NBA Cup games are added in December.

---

## 10. How the app should use all this (summary)

| Need | Call | Cache |
|---|---|---|
| Season calendar (days, weeks) | bundle constants, fallback date heuristic validated by a probe | per season |
| Matchup to weeks | `mSettings` `scheduleSettings.matchupPeriods` | per day |
| NBA schedule | `{SEASON}?view=proTeamSchedules_wl` (public) | 1 day |
| The user's live matchup | `mMatchupScore` + `mBoxscore` + `scoringPeriodId` + `filterCurrentMatchupPeriod` + `filterTeamIds` | 60 s during games, 15 min otherwise |
| Whole league scoreboard | `mMatchupScore` + `mScoreboard` (or `mTeam`) + `filterCurrentMatchupPeriod` | 5 min |
| Season schedule and results | `mMatchupScoreLite` | 1 hour |
| Live NBA game state | `site.api.espn.com/apis/fantasy/v2/games/fba/games?dates=` | 30 s during games |
| Past day boxscore | `mBoxscore` + `scoringPeriodId=N` + filters | forever once the day is official |

Never log `teams[].name` together with member ids, nor `status.creationInfo.source` (a SWID).

---

## Open questions

1. Does `totalPointsLive` update during live games for `fba`, or only when stats are processed? Check on opening night (Tue Oct 20, 2026) by polling every 60 s and comparing with the summed day stat lines.
2. Does the server ever send `totalProjectedPoints`, `totalProjectedPointsLive` or `winProbability` for basketball in-season (none seen in the 2027 preseason or the completed 2026 season)?
3. What does `rosterForMatchupPeriodDelayed` contain in-season, and how often is `status.standingsUpdateDate` refreshed (nightly only)?
4. When will ESPN add the 30 NBA Cup dependent games to `proTeamSchedules`, and will matchups 7 and 8 change materially?
5. Do the game state fields of `proTeamSchedules` (`inProgress`, `homeScore`, `percentComplete`) update live, and with what cache lifetime?
6. Is `pointsByScoringPeriod[today]` updated live, or only after the nightly job?
7. When are the playoff `schedule[]` entries (matchups 21 and 22) created: right after matchup 20 ends (Sun Mar 14, 2027)?
8. `gamesPlayed` is always 0 here: is it only populated in leagues with a games played limit?
9. The fantasy games feed defaults its date to America/Los_Angeles: confirm which date a 10:30 PM PT game falls under when `dates` is given explicitly.

# 02. Players, stats and projections

**Summary.** Player data comes from the league endpoint with `view=kona_player_info` (search, free agents, ownership, season stats and projections) or `view=kona_playercard` (adds game log detail, `injuryDetails`, transactions), both driven by a JSON `x-fantasy-filter` header whose grammar is documented and live-tested below.
Every stat block is a `stats[]` entry keyed by `{source}{split}{season}` (season and window splits) or `{source}5{gameId}` (one game, `scoringPeriodId` = day); `appliedTotal` is already scored with the league's `scoringItems`, and the NBA statId map is verified from ESPN's own bundle.
Per-day (per-game) projections are consumed by ESPN's web client but are **not observable in preseason** (checked 2026-10-15); the app should use the season projection per game times scheduled games from `proTeamSchedules_wl` until the in-season check in "Per-day projections" passes.

Verification legend: **VERIFIED (live)** means seen in a live response on 2026-10-15 for the reference league (2027 preseason, or its completed 2026 season where noted). **VERIFIED (bundle)** means read in ESPN's own JS (`main.js` of build `kona/7411ee0540f4-1.517`, and its page bundles). **UNVERIFIED** means from memory, third-party code, or inference; treat as a hypothesis.

## Quick reference

| Method | URL / view | Purpose | Auth | Status |
|---|---|---|---|---|
| GET | `{LEAGUE}?view=kona_player_info&scoringPeriodId={sp}` + `x-fantasy-filter` | Player pool: search, free agents, ownership, stats, projections | espn_s2 + SWID cookies (private league; 401 without) | VERIFIED (live) |
| GET | `{LEAGUE}?view=kona_playercard&scoringPeriodId={sp}` + filter | Player card: same as above plus `injuryDetails`, `transactions`, `appliedStatTotal`, `appliedStats` | Cookies | VERIFIED (live) |
| GET | `{LEAGUE}?view=kona_player_info&view=mStatRatings` + filter with `sortRating` | Player Rater ratings per split (`ratings` on each entry) | Cookies | VERIFIED (live) |
| GET | `{GAME}/segments/0/leaguedefaults/{formatId}?view=kona_player_info` | Same player pool without a league, ESPN default scoring, full game log by default | None | VERIFIED (live) |
| GET | `{GAME}/players?view=players_wl&scoringPeriodId=0` + `{"filterActive":{"value":true}}` | Lightweight universe of active NBA players (ids, names, positions, team, ownership) | None | VERIFIED (live) |
| GET | `{GAME}?view=proTeamSchedules_wl` | NBA schedule keyed by scoring period (day), per pro team | None | VERIFIED (live) |
| GET | `{GAME}` (no view) | Season root: `currentScoringPeriod.id`, start/end dates | None | VERIFIED (live) |
| GET | `{LEAGUE}?view=mSettings` | `scoringSettings.scoringItems` (points per statId), `scheduleSettings.matchupPeriods` | Cookies | VERIFIED (live) |
| GET | `{GAME}/players?view=mStatCorrections` + filter | Stat corrections for a day | None | Responds 200 (empty list for 2026 day 150); payload shape UNVERIFIED |
| GET | `https://site.api.espn.com/apis/fantasy/v3/games/fba/news/players?playerId={id}&days=30` | Player news shown in the card (not part of kona views); prefer the v2 path, see 03 | None | VERIFIED (bundle); live shape in 03 |
| GET | `kona_player_info` + `filterStatsForCurrentSeasonScoringPeriodId` + `filterStatsForSourceIds:[1]` | Per-day projected points for future days | Cookies | UNVERIFIED (none exist preseason) |

`{LEAGUE}` = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}`
`{GAME}` = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}`

Examples use `{season}` = 2027.

---

## 1. Request conventions

- **Host:** reads go to `lm-api-reads.fantasy.espn.com`. Writes (`lm-api-writes`) are out of scope here.
- **Auth:** private leagues need cookies `espn_s2` and `SWID`. Without them the league path returns `401 {"messages":["You are not authorized to view this League."]}` (VERIFIED, live). Game level paths (`{GAME}`, `/players`, `leaguedefaults`, `proTeamSchedules_wl`) work without cookies (VERIFIED, live).
- **Filter header:** `x-fantasy-filter: <JSON>`. The web client sends `X-Fantasy-Filter` (VERIFIED, bundle); header names are case-insensitive, lowercase works (VERIFIED, live).
- **Response header:** `X-Fantasy-Filter-Player-Count` = total players matching the filter before `limit`/`offset` (VERIFIED, live: `filterName "james"` returned 10 rows with count 11). The web client reads it for pagination (VERIFIED, bundle: `parseInt(p["x-fantasy-filter-player-count"])`).
- **Compression:** sending `Accept-Encoding: gzip` returns gzip (VERIFIED, live: full pool 3.34 MB decoded, 425 KB on the wire). Python `urllib` does not decompress automatically.
- **Query params:** `view` (repeatable), `scoringPeriodId` (day number; see section 6). The web client also sends `cacheBust` occasionally (VERIFIED, bundle); not required.
- **Rate:** about 0.6 s between calls was fine for 80+ calls (VERIFIED, live). A full pool pull (1095 players, default stats) took about 0.7 s.

---

## 2. `kona_player_info` (league player pool)

### Request

```
GET {LEAGUE}?view=kona_player_info&scoringPeriodId=1
Cookie: espn_s2=<ESPN_S2>; SWID=<SWID>
x-fantasy-filter: {"players":{
  "filterStatus":{"value":["FREEAGENT","WAIVERS"]},
  "filterSlotIds":{"value":[4]},
  "sortPercOwned":{"sortPriority":1,"sortAsc":false},
  "limit":50,"offset":0,
  "filterStatsForTopScoringPeriodIds":{"value":2,"additionalValue":["002027","102027","022027","002026"]}
}}
```

`scoringPeriodId` effect (VERIFIED, live, 2026 data): it adds that day's game entry (split 5) to each player's `stats[]` by default. `scoringPeriodId=0`, `=5` or omitted on 2027 preseason returned the same seven season entries. It does **not** shift the last 7/15/30 windows (section 4.4).

### Response shape

Status: VERIFIED (live).

`players[]` is a list of pool entries:

| Path | Type | Example | Notes |
|---|---|---|---|
| `id` | int | `5104157` | Same as `player.id` |
| `status` | str | `"ONTEAM"` | `FREEAGENT`, `WAIVERS`, `ONTEAM` |
| `onTeamId` | int | `2` | Fantasy team id; `0` when not rostered |
| `lineupLocked`, `rosterLocked`, `tradeLocked` | bool | `false` | |
| `draftAuctionValue`, `keeperValue`, `keeperValueFuture` | int | `0`, `1`, `1` | |
| `droppedByEliminatedTeam` | bool | `false` | Elimination format leagues |
| `ratings` | object | see section 7 | Only with extra view `mStatRatings` |
| `waiverProcessDate` | int (ms) | | Read by the web model (VERIFIED, bundle); not seen live (no player on waivers today) |
| `player.id` | int | `5104157` | |
| `player.fullName`, `firstName`, `lastName` | str | `"Victor Wembanyama"` | |
| `player.proTeamId` | int | `24` | See section 9.4 (24 = SA) |
| `player.defaultPositionId` | int | `5` | Position ids, section 9.1 (5 = C) |
| `player.eligibleSlots` | int[] | `[4,9,10,11,12,13]` | Lineup slot ids, section 9.2 |
| `player.injuryStatus` | str | `"ACTIVE"` | Section 9.3 |
| `player.injured` | bool | `false` | `true` only for OUT-type statuses |
| `player.active` | bool | `true` | |
| `player.droppable` | bool | `false` | `false` = on the league's undroppable list (`rosterSettings.isUsingUndroppableList: true`) |
| `player.jersey` | str | `"1"` | |
| `player.lastNewsDate` | int (ms) | `1792035062000` | 2026-10-14 23:31 ET |
| `player.seasonOutlook` | str | `"Wembanyama made a leap in Year 3 ..."` | Long text, preseason blurb |
| `player.draftRanksByRankType` | object | `{"STANDARD":{"auctionValue":60,"published":false,"rank":4,"rankSourceId":0,"rankType":"STANDARD","slotId":0},"ROTO":{...}}` | `STANDARD` is the points ranking |
| `player.ownership.percentOwned` | float | `99.93` | ESPN-wide % rostered (UI "% ROSTERED"), not this league |
| `player.ownership.percentChange` | float | `0.0` | Change in %ROST **over the last week** (VERIFIED, bundle UI string: "Plus/Minus shows the change in %ROST over the last week") |
| `player.ownership.percentStarted` | float | `99.53` | ESPN-wide % started |
| `player.ownership.averageDraftPosition`, `averageDraftPositionPercentChange` | float | `3.08`, `0.0` | |
| `player.ownership.auctionValueAverage`, `auctionValueAverageChange` | float | `82.22`, `0.75` | |
| `player.ownership.date` | int (ms) | `1792074627901` | Snapshot time, 2026-10-15 10:30 ET |
| `player.ownership.activityLevel`, `leagueType` | null, int | `null`, `0` | |
| `player.stats[]` | list | section 4 | Controlled by `filterStatsFor*` |
| `player.rankings` | object | | Read by the web model (VERIFIED, bundle) but **absent** live in preseason even with `filterRanksFor*` (UNVERIFIED shape) |

Fields present in the web model but not seen live: `lastVideoDate`, `proGamePlayerDetail`, `gamesPlayedByPosition`, `outlooks.outlooksByWeek` (VERIFIED, bundle; `outlooksByWeek` is used for football weekly outlooks).

---

## 3. The `x-fantasy-filter` grammar

### 3.1 Envelope and value shapes

- Top level: an object whose only allowed keys are `players`, `transactions`, `communication`, `schedule` (VERIFIED, live: error `Unrecognized field "bogusTop" ... (4 known properties: "players", "transactions", "communication", "schedule")`). Player filters go under `players`; sending them bare returns 400.
- Filter keys take `{"value": X}`; some also take `additionalValue`. Array-valued keys must receive arrays: `{"filterIds":{"value":5104157}}` returns `400 Cannot deserialize value of type java.util.ArrayList<java.lang.Integer>` (VERIFIED, live).
- The web client normalizes filters before sending (VERIFIED, bundle function `Vn`): `limit` and `offset` pass through raw; arrays become `{value: [...]}`; scalars become `{value: [x]}` for the array keys `filterExternalIds, filterIds, filterPositionIds, filterProTeamIds, filterSlotIds, filterStatsForContainerIds, filterStatsForExternalIds, filterStatsForScoringPeriodIds, filterStatsForSourceIds, filterStatsForSplitTypeIds, filterRanksForScoringPeriodIds, filterRanksForSourceIds, filterRanksForSplitTypeIds`, and `{value: x}` otherwise. It strips `filterStatus: {"value":"TODAY"}`, `filterPlaying` and `statParams` before sending (client-only keys).
- **Unknown keys inside `players` are silently ignored** (VERIFIED, live: `filterFooBar` returned 200). A typo therefore widens the result instead of failing.
- Sort keys take `{"sortPriority": n, "sortAsc": bool}` plus `value` / `additionalValue` for parametrized sorts. A sort without `sortPriority` returns `400 Filter: Sort missing priority` (`FILTER_MISSING_PRIORITY`). Lower `sortPriority` is applied first (VERIFIED, live: `sortDraftRanks` priority 1 + `sortPercOwned` priority 2 ordered by rank).

### 3.2 Paging

| Key | Behavior | Status |
|---|---|---|
| `limit` | Max rows. **Requires at least one sort**, otherwise `400 Filter: Limit request must be accompanied by a sort` (`FILTER_LIMIT_MISSING_SORT`). `limit: 0` with a sort returned all 965 rows. Values up to 1200 accepted (all 965 free agents returned with `limit: 1000`). | VERIFIED (live) |
| `offset` | Skips rows; pages are disjoint (`offset 0` vs `5`, no overlap). **Ignored when `limit` is absent** (`offset: 960` alone returned 965 rows). | VERIFIED (live) |
| (none) | No `limit` and no sort returns every match (965 free agents). | VERIFIED (live) |
| Web default | The web client caps `limit` at 50 unless `filterIds` is present and pages with `offset = (page-1)*50`; this is client-side only. | VERIFIED (bundle) |

### 3.3 Player filters

| Key | Value | Live result | Status |
|---|---|---|---|
| `filterStatus` | `["FREEAGENT","WAIVERS","ONTEAM"]` any subset | FREEAGENT: 965, WAIVERS: 0 (preseason), ONTEAM: 130 (10 teams x 13), all three: 1095. Omitted = 1095 (whole league pool). | VERIFIED (live) |
| `filterSlotIds` | lineup slot ids `[4]` | Only players whose `eligibleSlots` contain the slot: C 156, PG 198, G 466, UTIL 965 free agents. Note: **slot** ids, not position ids. | VERIFIED (live) |
| `filterIds` | player ids `[5104157, 3112335, 999999999]` | Returns the known ids, unknown ids dropped silently; count 2. No sort or limit needed. | VERIFIED (live) |
| `filterName` | string | Case and accent insensitive **prefix** match on first name, last name or full name: `wemb`, `WEMBANYAMA`, `Victor W`, `Jokić` match; `banya` (substring) and `Wembanyama Victor` do not; `o'neale` matches Royce O'Neale; `jr` matched only Jrue Holiday (suffixes not indexed). Combine with `filterStatus` to restrict. | VERIFIED (live) |
| `filterProTeamIds` | `[24]` | 31 SA players, all with `proTeamId` 24. | VERIFIED (live) |
| `filterInjured` | `true` / `false` | `true`: 26 players, all `injured:true` (`OUT`). `false`: 1069, includes `DAY_TO_DAY`. | VERIFIED (live) |
| `filterActive` | `true` / `false` | `true`: 1095 (same as no filter). `false`: 0 in league context. | VERIFIED (live) |
| `filterExcludeIds` | ids | Removes them (1095 to 1093). | VERIFIED (live) |
| `filterStatsForTopScoringPeriodIds` | `{"value": N, "additionalValue": [ids]}` | See 3.5. `value` must be > 0 (`400 Filter: Value is invalid, must be > 0`). | VERIFIED (live) |
| `filterStatsForCurrentSeasonScoringPeriodId` | `{"value":[sp,...]}` | Returns only per-game entries for those days (both sources unless restricted). Replaces the default stat set (season entries disappear). | VERIFIED (live, 2026) |
| `filterStatsForSplitTypeIds` | `[0..5]` | AND filter over the default stat set: `[1]` kept only `012027`; `[0]` kept the four season entries. | VERIFIED (live) |
| `filterStatsForSourceIds` | `[0]`, `[1]`, `[0,1]` | AND filter: `[1]` kept `102027`, `102026`. | VERIFIED (live) |
| `filterStatsForExternalIds` | `[2026, 2027]` | AND filter on `externalId` (season id for season and window entries): `[2026]` kept `002026`, `102026`. The FBA projections page sends `[season-1, season]` with sources `[0,1]`. | VERIFIED (live + bundle) |
| `filterRanksForScoringPeriodIds`, `filterRanksForRankTypes`, `filterRanksForSlotIds` | `[sp]`, `["STANDARD"]`, slot ids | Accepted (200) but no `player.rankings` returned in preseason. The web players page sends `filterRanksForScoringPeriodIds:[today]` and `filterRanksForRankTypes:[league rank type]`. | Accepted live; output UNVERIFIED |
| `filterStatsForScoringPeriodIds`, `filterStatsForContainerIds`, `filterPositionIds`, `filterExternalIds`, `filterStatMinimum`, `filterStatMaximum`, `filterDroppedByEliminatedTeam`, `filterRanksForSourceIds`, `filterRanksForSplitTypeIds` | | Present in bundles. `filterStatsForScoringPeriodIds:[1..7]` returned 200 with zero stats preseason. Others not exercised. | VERIFIED (bundle), behavior UNVERIFIED |

### 3.4 Sort keys

Web client builder (VERIFIED, bundle `players_add.js`, function `ut`): `source`, `split`, `season`, `sp` below are the stat-entry components from section 4.

| Key | Shape | Live check | Status |
|---|---|---|---|
| `sortPercOwned` | `{sortPriority, sortAsc}` | Desc: Wembanyama, Jokic, SGA ... Asc: 0.0 owned first. Default sort of the web players page. | VERIFIED (live) |
| `sortPercChanged` | same | Desc FA: Aday Mara +1.29, Egor Demin +1.15. Asc: Anfernee Simons -0.99. Suits a "trending" list. | VERIFIED (live) |
| `sortPercStarted` | same | Desc: Wembanyama 99.53. | VERIFIED (live) |
| `sortDraftRanks` | `{sortPriority, sortAsc:true, value:"STANDARD"}` (or `"ROTO"`) | STANDARD: Jokic 1, SGA 2, Doncic 3, Wembanyama 4. Web default is priority 100 as a tiebreaker. | VERIFIED (live) |
| `sortAppliedStatTotal` | `value: "{source}{split}{season}"` | `"102027"` (projected season, league scoring): Jokic 4838, SGA 4320, Doncic 4123. `"002026"`: Jokic 4310. | VERIFIED (live) |
| `sortAppliedStatAverage` | same `value` | `"002026"`: Jokic 66.31; `"102027"`: Jokic 67.19. | VERIFIED (live) |
| `sortAppliedStatTotalForScoringPeriodId` | `value: sp` | 2026 day 172: Amen Thompson 80, Wembanyama 77, LeBron 73. | VERIFIED (live, 2026) |
| `sortStatId` | `value: statId, additionalValue: "{source}{split}{season}{sp or ''}"` | BLK (`1`) on `"002026"`: Wembanyama 197, Jay Huff 154. | VERIFIED (live) |
| `sortAverageStatId` | same as `sortStatId` | | VERIFIED (bundle) |
| `sortStatIdForScoringPeriodId` | `value: statId, additionalValue: sp` | | VERIFIED (bundle) |
| `sortAppliedStatTotalProjection` (UI name) | Sent as `sortAppliedStatTotal` with `value "{source}{split}{season}{sp}"` | Suggests ids of the form `1{split}{season}{sp}`; not observed live | VERIFIED (bundle), output UNVERIFIED |
| `sortRating` | `value: splitTypeId`, optional `additionalValue: statId` | Used with view `mStatRatings` (section 7). | VERIFIED (live) |
| `sortRatingPositional`, `sortRanks` (`value: rankSourceId`), `sortAdp`, `sortAdpPerc`, `sortAverageAuction`, `sortAverageAuctionPerc`, `sortOpponentVsPositionRank` (`value: sp`), `sortName` (priority 3) | | | VERIFIED (bundle) |

### 3.5 `filterStatsForTopScoringPeriodIds` in detail

- `value: N` adds the player's **last N game entries** (split 5, source 0) of the latest season that has games. In preseason that is the end of 2026 (days 174, 172, 170 ...). (VERIFIED, live)
- `additionalValue` adds specific non-game entries by id, for example `["002027","102027","022027","002026"]`. Unknown or empty ids are skipped. (VERIFIED, live)
- When this key is present it **replaces** the default stat set: only the N games plus the listed ids come back. Without any stats filter, `kona_player_info` returns seven season entries (`002026, 032027, 022027, 012027, 002027, 102027, 102026` in preseason). (VERIFIED, live)
- The web client always sends it unless `filterStatsForCurrentSeasonScoringPeriodId` is present (the two are treated as mutually exclusive) with `value = config.defaultTopScoringPeriodsCount` and `additionalValue` built as: for every non-game split `"0{split}{season}"`, plus `"10{season}"`, plus `"00{season-1}"` before the season starts. Only football adds `"1{gameSplit}{season}{sp}"` (weekly projection). (VERIFIED, bundle function `lr`)

### 3.6 Error catalogue

Status: all entries VERIFIED (live).

| HTTP | `details[].type` / message | Cause |
|---|---|---|
| 400 | `FILTER_LIMIT_MISSING_SORT`, "Limit request must be accompanied by a sort" | `limit` without a sort key |
| 400 | `FILTER_MISSING_PRIORITY`, "Sort missing priority" | Sort object without `sortPriority` |
| 400 | `FILTER_INVALID_VALUE`, "Value is invalid, must be > 0" | `filterStatsForTopScoringPeriodIds.value` = 0 |
| 400 | "Invalid parameter for 'LeagueFilterParams'." with a Jackson `cause` | Bad JSON, unknown top-level key, scalar where an array is required |
| 401 | "You are not authorized to view this League." | Missing or expired cookies |

---

## 4. Decoding `player.stats[]`

### 4.1 Entry id format

Status: VERIFIED (live and bundle).

| Kind | `id` pattern | Example | `scoringPeriodId` | `externalId` |
|---|---|---|---|---|
| Season or window | `{statSourceId}{statSplitTypeId}{seasonId}` | `102027` = projected, season, 2027 | `0` | `"2027"` |
| One game | `{statSourceId}5{gameId}` | `05401811035` = actual, game 401811035 | the day (172) | `"401811035"` (ESPN game id) |

The web client matches non-game entries by id and game entries by fields (`statSourceId`, `statSplitTypeId`, `scoringPeriodId`, `seasonId`), **summing** all entries that match (built for doubleheaders) (VERIFIED, bundle `c.stats`). Do the same: match by fields, not by id string.

### 4.2 Sources and split types

Status: VERIFIED (bundle `statSettings` for basketball).

| `statSourceId` | Meaning |
|---|---|
| 0 | Real (actual) |
| 1 | Projected |

| `statSplitTypeId` | abbrev | Meaning | Seen live |
|---|---|---|---|
| 0 | SEA | Season | yes |
| 1 | 7 | Last 7 days | yes |
| 2 | 15 | Last 15 days | yes |
| 3 | 30 | Last 30 days | yes |
| 4 | AVG | Average (UI label) | **never** returned, even when requested |
| 5 | G | Game (`gameSplit: true`) | yes |

### 4.3 Entry fields

Status: VERIFIED (live).

| Field | Type | Meaning |
|---|---|---|
| `stats` | `{statId: number}` | Raw totals for the entry (string keys `"0"`..`"44"`); empty `{}` when no data |
| `averageStats` | `{statId: number}` | Per-game averages; present on season and window entries that have games |
| `appliedTotal` | float | Fantasy points with **this league's** `scoringItems`: sum over items of `points * stats[statId]` (checked: projected `102027` for Wembanyama = 4054, game `05401811035` = 77, window `012026` = 111) |
| `appliedAverage` | float | `appliedTotal / stats["42"]` (GP). Checked on season, L7, L15, L30 and projection entries. Absent on game entries. |
| `appliedStats` | `{statId: points}` | Per-stat contribution to `appliedTotal` (for example `"14": -1253.0` for FGA). Present in `kona_playercard` and roster views (`mRoster`), **absent in `kona_player_info`** |
| `proTeamId` | int | Team for that game; `0` on season entries |
| `seasonId`, `scoringPeriodId`, `statSourceId`, `statSplitTypeId`, `externalId`, `id` | | See 4.1 |
| `appliedTotalCeiling`, `projectionAnalysis`, `variance` | | Read by the web client on projected game entries (VERIFIED, bundle); never seen live |

Example, projected season entry (trimmed, live):

```json
{"id":"102027","seasonId":2027,"scoringPeriodId":0,"statSourceId":1,"statSplitTypeId":0,"externalId":"2027",
 "appliedTotal":4054.0,"appliedAverage":60.507462686567166,
 "stats":{"0":1799.0,"1":235.0,"2":80.0,"3":241.0,"6":831.0,"11":194.0,"13":629.0,"14":1253.0,"15":392.0,"16":476.0,"17":149.0,"42":67.0},
 "appliedStats":{"0":1799.0,"1":940.0,"2":320.0,"3":482.0,"6":831.0,"11":-388.0,"13":1258.0,"14":-1253.0,"15":392.0,"16":-476.0,"17":149.0}}
```

Example, one game (trimmed, live):

```json
{"id":"05401811035","externalId":"401811035","seasonId":2026,"scoringPeriodId":172,"statSourceId":0,"statSplitTypeId":5,
 "proTeamId":24,"appliedTotal":77.0,"stats":{"0":40.0,"1":2.0,"3":5.0,"6":13.0,"13":14.0,"14":23.0,"40":26.0,"41":1.0,"42":1.0,"43":1.0}}
```

### 4.4 Gotchas

- **Preseason placeholders.** Current-season entries (`002027`, `012027`, `022027`, `032027`) exist with `appliedTotal: 0.0` and `stats: {}`. Treat `stats == {}` as "no data", not as zero points.
- **DNP games.** A team game the player missed appears as a split 5 entry with `stats: {}` and `appliedTotal: 0.0` (Wembanyama days 164, 170, 174). Count games played with `stats["42"]`, never with the number of entries.
- **Windows are anchored to the latest data**, not to the `scoringPeriodId` parameter: `012026` was identical with `scoringPeriodId=100` and `174`. To compute "last N days as of day X", sum game entries fetched with `filterStatsForCurrentSeasonScoringPeriodId`.
- **League scoring is applied server side** on league paths. `leaguedefaults` uses ESPN default scoring (game entries there had `appliedTotal: null` on the hockey analog). Never mix the two.
- **Previous season ids.** `00{season-1}` and `10{season-1}` stay available all season; windows of the previous season (`012026` and similar) only exist on the 2026 league path.

### 4.5 The box score of a split (`averageStats`)

Status: VERIFIED (live, 2026-10-16) unless marked. Checked on `002026` and `102027` entries from `kona_player_info`.

- A season or window entry with games carries `averageStats` (per game) next to `stats` (totals), keyed by the same stat ids (section 5). Entries without games have `{}` for both.
- Percentages (19 FG%, 20 FT%, 21 3P%) are fractions in both maps (`0.5689`), not 0 to 100.
- `averageStats["40"]` (MIN) is minutes per game (`34.85`); `stats["40"]` is total minutes (`2265.0`).
- `averageStats["42"]` (GP) is the **games count** (`65.0`), the same as `stats["42"]`, not a per-game value.
- A projection entry (`10{season}`) has a smaller set: 0, 1, 2, 3, 6, 11, 13 to 21, 23 to 36, 40, 42. No OREB, DREB, DD, TD or GS.
- A stat that is zero can be left out of the entry. 14 of the 60 best projected centers had no 17 (3PM) in their `102027` `averageStats`. Read a missing count as 0 when the entry has other stats.

Example, Nikola Jokic's last season (trimmed, values rounded):

```json
{"id":"002026","appliedTotal":4310.0,
 "averageStats":{"0":27.68,"19":0.5689,"20":0.8313,"21":0.3797,"40":34.85,"42":65.0},
 "stats":{"13":644.0,"14":1132.0,"19":0.5689,"40":2265.0,"42":65.0}}
```

What benchboss reads (`espn/constants.py`, `espn/models.py` `StatLine`):

| Split key | Entry id | Column |
|---|---|---|
| `season` | `00{season}` | Avg |
| `l7` | `01{season}` | L7 |
| `l15` | `02{season}` | L15 |
| `l30` | `03{season}` | L30 |
| `proj` | `10{season}` | Proj |
| `last` | `00{season-1}` | Prev |

It asks for all six with `filterStatsForTopScoringPeriodIds: {"value": 2, "additionalValue": [...]}`, which also brings the last two game entries (split 5); benchboss ignores those. For each split it keeps `appliedAverage` (fantasy points per game), `appliedTotal`, GP from `stats["42"]` and both maps. An entry with `appliedTotal` 0 counts as no data.

Stat ids it uses by name: 0 PTS, 1 BLK, 2 STL, 3 AST, 4 OREB, 5 DREB, 6 REB, 11 TO, 13 FGM, 14 FGA, 15 FTM, 16 FTA, 17 3PM, 18 3PA, 19 FG%, 20 FT%, 21 3P%, 37 DD, 38 TD, 40 MIN, 41 GS, 42 GP. The screens show GP, MIN, PTS, REB, AST, STL, BLK, 3PM, TO, FG% and FT%. FG% and FT% are recomputed from the made and attempted totals (13/14, 15/16) when there are attempts, so they match the counts; otherwise the fraction from `averageStats` is used. `--json` prints `averageStats` in `stats.<split>.per_game`, keyed by name, for every id the entry has between 0 and 21 or 37 and 42.

The player finder ranks a pool by a split with `sortAppliedStatAverage` and `value` set to the entry id (`"012027"` for the last 7 days), as in section 3.4.

---

## 5. NBA statId map

VERIFIED (bundle): `constants.statSettings.stats` for basketball. "Pts" is the value in **this league's** `scoringItems` (VERIFIED, live `mSettings`); blank means not scored.

| id | abbrev | description | Pts | | id | abbrev | description |
|---|---|---|---|---|---|---|---|
| 0 | PTS | Points | +1 | | 23 | FGMI | Field Goals Missed |
| 1 | BLK | Blocks | +4 | | 24 | FTMI | Free Throws Missed |
| 2 | STL | Steals | +4 | | 25 | TPMI | Three Pointers Missed |
| 3 | AST | Assists | +2 | | 26 | APG | Assists Per Game |
| 4 | OREB | Offensive Rebounds | | | 27 | BPG | Blocks Per Game |
| 5 | DREB | Defensive Rebounds | | | 28 | MPG | Minutes Per Game |
| 6 | REB | Rebounds | +1 | | 29 | PPG | Points Per Game |
| 7 | E | Ejections | | | 30 | RPG | Rebounds Per Game |
| 8 | FF | Flagrant Fouls | | | 31 | SPG | Steals Per Game |
| 9 | PF | Personal Fouls | | | 32 | TOPG | Turnovers Per Game |
| 10 | TF | Technical Fouls | | | 33 | TPG | Three Pointers Per Game |
| 11 | TO | Turnovers | -2 | | 34 | PPM | Points Per Minute |
| 12 | DQ | Disqualifications | | | 35 | ATR | Assist To Turnover Ratio |
| 13 | FGM | Field Goals Made | +2 | | 36 | STR | Steal To Turnover Ratio |
| 14 | FGA | Field Goals Attempted | -1 | | 37 | DD | Double Doubles |
| 15 | FTM | Free Throws Made | +1 | | 38 | TD | Triple Doubles |
| 16 | FTA | Free Throws Attempted | -1 | | 39 | QD | Quadruple Doubles |
| 17 | TPM (3PM) | Three Pointers Made | +1 | | 40 | MIN | Minutes |
| 18 | TPA (3PA) | Three Pointers Attempted | | | 41 | GS | Games Started |
| 19 | FGPCT | Field Goal % | | | 42 | GP | Games Played |
| 20 | FTPCT | Free Throw % | | | 43 | TW | Team Wins |
| 21 | TPPCT | Three Point % | | | 44 | FTAFGA | FTA per FGA |
| 22 | APCT | Adjusted FG % (eFG) | | | 45..56 | TSPCT, ASTR, TOR, USG, PPR, ORR, DRR, TMIN, TOREB, TDREB, OOREB, ODREB | Advanced and team stats, not seen live |

Gotchas: ids 19 to 36 and 44+ are derived (`derived: true`); never sum them across games, recompute from totals. Projection entries carry a subset (no 4, 5, 7 to 10, 12, 22, 37 to 39, 41, 43, 44). Live game entries for 2026 also matched the league scoring exactly (`appliedTotal` = recomputed sum).

---

## 6. Days, weeks and games per matchup

### 6.1 scoringPeriodId to date

Status: VERIFIED (live).

`scoringPeriodId` = (game date in **America/New_York**) minus 2026-10-20, plus 1. Day 1 = Tuesday 2026-10-20, day 174 = Sunday 2027-04-11 (`status.finalScoringPeriod: 174`). Checked against all 2400 team-game rows of `proTeamSchedules_wl`: 0 mismatches with Eastern dates, 1842 mismatches with UTC dates (night games cross UTC midnight). Never derive the day from UTC.

The season root gives the current day: `GET {GAME}` returns `currentScoringPeriod.id` (1 today, preseason). The league's `mStatus` has `latestScoringPeriod` and `transactionScoringPeriod` (both 1 today).

### 6.2 Matchup period to days

Status: VERIFIED (live + bundle).

`mSettings.scheduleSettings` has `periodTypeId: 2` and `matchupPeriods: {"1":[1],"2":[2],...,"20":[20],"21":[21,22],"22":[23,24]}`. The **values are week ids, not days**. Week ids map to days through the static table `constants.segments[0].periodTypes[id=2].periods` in ESPN's bundle (the web client resolves `league.periods` this way):

| Week | Days | Dates |
|---|---|---|
| 1 | 1 to 6 | 2026-10-20 to 2026-10-25 (6 days) |
| 2 to 17 | 7-day blocks, Monday to Sunday | week 2 = days 7 to 13 (2026-10-26 to 2026-11-01) ... week 17 = days 112 to 118 (2027-02-08 to 2027-02-14) |
| 18 | 119 to 132 | 2027-02-15 to 2027-02-28 (All-Star, 14 days) |
| 19 to 24 | 7-day blocks | week 19 = days 133 to 139 ... week 24 = days 168 to 174 (2027-04-05 to 2027-04-11) |
| 25 | 175 | 2027-04-12 (unused by this league) |

So matchup 18 is the double week, playoff round 1 (matchup 21) = days 147 to 160, round 2 (matchup 22) = days 161 to 174. `typeNames.periodTypes` = `TOTAL_SEASON, SCORING_PERIOD, WEEKLY` (VERIFIED, live). The table is a per-season constant of the web build; re-extract it each season (see 05, section 1.2). Fallback rule if the bundle changes: week 1 = opening day to the first Sunday, then Monday to Sunday, merging the All-Star break.

### 6.3 `proTeamSchedules_wl`

Status: VERIFIED (live, public).

```
GET {GAME}?view=proTeamSchedules_wl        (no cookies needed, about 420 KB)
```

`settings.proTeams[]`: `{id, abbrev, location, name, byeWeek, universeId, proGamesByScoringPeriod}`. `proGamesByScoringPeriod` is `{"<sp>": [game]}` with string keys; each game is `{id, date (ms UTC), scoringPeriodId, homeProTeamId, awayProTeamId, startTimeTBD, statsOfficial, validForLocking}`. Team `id 0` (`FA`) has no games.

Gotchas: today it lists **80 games per team (1200 unique), not 82**; two per team are still unscheduled (most likely NBA Cup knockout dates, UNVERIFIED), so refresh the cache daily. No team has two games on one day, but code should still handle a list per day.

Games per team (illustration, live): week 1 (days 1 to 6): 5 teams with 2 games, 24 with 3, 1 with 4. Week 2: 1 team with 2, 20 with 3, 9 with 4. Week 18: 3, 20 and 7 teams with 3, 4, 5 games.

### 6.4 Games remaining for a pickup on day X

```python
def games_left(sched, pro_team_id, week_days, from_day):
    """Games the NBA team plays in this matchup week on or after from_day."""
    t = next(t for t in sched["settings"]["proTeams"] if t["id"] == pro_team_id)
    by_day = t.get("proGamesByScoringPeriod") or {}
    return [g for d in week_days if d >= from_day for g in by_day.get(str(d), [])]
```

Then drop games already started at pickup time (`date` <= now) because lineups lock per game (`rosterSettings.lineupLocktimeType: "INDIVIDUAL_GAME"`). Whether a free agent added today can play today is governed by `rosterLocktimeType: "FIRSTGAME_SCORINGPERIOD"` and the transactions rules (see Open questions).

Observed behavior (VERIFIED live on the completed 2026 season of the reference league, same lock settings): 50 executed `FREEAGENT` adds were checked against `mRoster&forTeamId={team}&scoringPeriodId={d}` for the add day `d` and `d+1`. All 25 adds made **before the first NBA game of the scoring period** were on that day's roster; 24 of 25 adds made **after the first game had started** were not on day `d` and appeared on day `d+1` (the remaining one was gone by `d+1`). The transaction record keeps `scoringPeriodId = d` in both cases. So the pickup counts from today only if it is made before the day's first tip-off; otherwise from tomorrow.

---

## 7. `mStatRatings` (Player Rater)

```
GET {LEAGUE}?view=kona_player_info&view=mStatRatings&scoringPeriodId={sp}
x-fantasy-filter: {"players":{"filterSlotIds":{"value":[0,1,2,3,4,5,6,11]},
  "sortRating":{"sortAsc":false,"sortPriority":1,"value":0},"limit":50}}
```

VERIFIED (live): each entry gains `ratings`, keyed by split type id as a string (`"0"` season, `"1"` L7, `"2"` L15, `"3"` L30):

```json
"ratings":{"0":{"positionalRanking":1,"statCategoryRanking":1,"totalRanking":1,"totalRating":4310.0,
  "statRankings":[{"forStat":0,"ranking":0,"rating":1799.0},{"forStat":14,"ranking":0,"rating":-1132.0}]}}
```

In a points league `rating` is the league-scored points from that stat and `totalRating` = `appliedTotal` of the split (Jokic 2026: 4310). In 2027 preseason only `"0"` exists and it reflects **last season** (Wembanyama 3546 = his `002026` total). The web Player Rater sends exactly this view plus `sortRating` (VERIFIED, bundle `playerrater.js`).

---

## 8. `kona_playercard`

```
GET {LEAGUE}?view=kona_playercard&scoringPeriodId={sp}
x-fantasy-filter: {"players":{"filterIds":{"value":[5104157,3133628]},
  "filterStatsForTopScoringPeriodIds":{"value":15,"additionalValue":["002027","102027","002026","102026","012027","022027","032027"]}}}
```

The web card calls it with `filterIds` (one player) and `isPlayerCardModal` (VERIFIED, bundle). It also works in bulk with `filterStatus`, sorts and `limit` (VERIFIED, live: 25 injured free agents with `injuryDetails`).

Extra fields compared with `kona_player_info` (VERIFIED, live):

| Path | Example | Notes |
|---|---|---|
| `appliedStatTotal` (entry) | `0.0` | Preseason zero; likely season-to-date points (UNVERIFIED) |
| `transactions[]` (entry) | `{"type":"DRAFT","status":"EXECUTED","scoringPeriodId":1,"teamId":2,"items":[{"type":"DRAFT","playerId":5104157,"fromTeamId":0,"toTeamId":2,"toLineupSlotId":4,"overallPickNumber":2}],"proposedDate":1791860708514}` | This league's history for the player |
| `player.injuryDetails` | `{"expectedReturnDate":[2027,1,2],"outForSeason":false,"type":"Knee"}` | Only for injured players; date is `[year, month(1-12), day]` (the web converts it with `month-1`) |
| `player.laterality`, `stance` | `"NONE"` | Unused in basketball |
| `player.universeId`, `invalid` | `2`, `false` | |
| `stats[].appliedStats` | per-stat points | Not in `kona_player_info` |

**Game log:** the web derives it from `stats[]` entries with `seasonId` = current season (previous season before opening night), `statSourceId` 0, `statSplitTypeId` 5, sorted by `scoringPeriodId` descending (VERIFIED, bundle `gameLog`). Ask for it with `filterStatsForTopScoringPeriodIds.value = N`.

**News:** not in this view. The card fetches `fantasy/v3/games/fba/news/players` on `https://site.api.espn.com/apis/` with `playerId` and `days: 30`, and keeps items of type `Rotowire` as "latest news" (VERIFIED, bundle). Live shape: see 03.

**Outlooks:** `seasonOutlook` (string) is present in both views. `outlooks.outlooksByWeek` exists only for weekly sports (football); not seen for FBA.

---

## 9. Enumerations

### 9.1 Positions, `defaultPositionId`

Status: VERIFIED (bundle).

`1` PG, `2` SG, `3` SF, `4` PF, `5` C (`0` POS0 and `6` BE are internal). League `rosterSettings.positionLimits` is keyed by these ids: `{"5": 4}` = max 4 players whose default position is C (`0` and `-1` mean no limit).

### 9.2 Lineup slots, `eligibleSlots` and `lineupSlotId`

Status: VERIFIED (bundle).

| id | abbrev | positions | | id | abbrev | positions |
|---|---|---|---|---|---|---|
| 0 | PG | 1 | | 8 | G/F | 1,2,3,4 |
| 1 | SG | 2 | | 9 | PF/C | 4,5 |
| 2 | SF | 3 | | 10 | F/C | 3,4,5 |
| 3 | PF | 4 | | 11 | UTIL | 1 to 5 |
| 4 | C | 5 | | 12 | BE (bench) | 1 to 5 |
| 5 | G | 1,2 | | 13 | IR (`injuryRequired`) | 1 to 5 |
| 6 | F | 3,4 | | 14 | INV (invalid player) | none |
| 7 | SG/SF | 2,3 | | 15 | ALL (all players) | 1 to 5 |

This league uses PG, SG, SF, PF, C, G, F, UTIL x3, BE x3, IR x1 (`lineupSlotCounts`). Slot 15 is `ALL` ("All Players"), a filter value rather than a lineup slot.

### 9.3 Injury status

Status: VERIFIED (bundle `injuryStatusTypes`).

| name | id | `injured` |
|---|---|---|
| ACTIVE | 0 | false |
| PROBABLE | 1 | false |
| QUESTIONABLE | 2 | false |
| DOUBTFUL | 3 | false |
| OUT | 4 | true |
| INJURY_RESERVE | 5 | true |
| DAY_TO_DAY | 6 | false |
| SUSPENSION | 17 | false |
| BEREAVEMENT, PATERNITY | 15, 16 | true |
| FIFTEEN_DAY_DL, SIXTY_DAY_DL, SEVEN_DAY_DL, TEN_DAY_DL, RESERVE_RETIRED | 10, 11, 13, 14, 18 | other sports |

Live NBA values seen on `player.injuryStatus`: `ACTIVE`, `DAY_TO_DAY`, `OUT`. Roster entries (`mRoster`, `teams[].roster.entries[].injuryStatus`) carry a separate field that was `NORMAL` for all 130 entries, whatever the player's status (VERIFIED, live); always read the player's own `injuryStatus`. Roster entries also carry `rosterInjuryStatusTypes` `NORMAL, FUTURE_FROM_IR, FUTURE_TO_IR` (VERIFIED, live `typeNames`).

### 9.4 Pro teams

Status: VERIFIED (live `proTeamSchedules_wl`; ESPN abbreviations).

`0` FA, `1` ATL, `2` BOS, `3` NO, `4` CHI, `5` CLE, `6` DAL, `7` DEN, `8` DET, `9` GS, `10` HOU, `11` IND, `12` LAC, `13` LAL, `14` MIA, `15` MIL, `16` MIN, `17` BKN, `18` NY, `19` ORL, `20` PHI, `21` PHX, `22` POR, `23` SAC, `24` SA, `25` OKC, `26` UTAH, `27` WSH, `28` TOR, `29` MEM, `30` CHA.

### 9.5 Other enums

Status: VERIFIED (live `typeNames` in `proTeamSchedules_wl`).

`playerStatusTypes`: `FREEAGENT, ONTEAM, WAIVERS`. `rankTypes`: `STANDARD, PPR, ROTO, ELIMINATION, SUPERFLEX`. `playerOwnershipActivityLevels`: `ACTIVE_LAST_DAY, ACTIVE_LAST_7_DAYS, ACTIVE_LAST_15_DAYS`. The same response carries the full `transactionTypes`, `transactionStatusTypes` and `moveTypes` lists used by the transactions document.

---

## 10. Per-day projections

### What is verified

- ESPN's web client computes live matchup projections per starter as `livePoints + (1 - percentComplete) * projected`, where `projected` = sum of `stats[]` entries with `statSourceId` 1 (`STAT_SOURCE_PROJECTED`), `statSplitTypeId` 5 (the game split) and `scoringPeriodId` = that day; it also reads `appliedTotalCeiling`, `projectionAnalysis`, `variance` from them (VERIFIED, bundle function `x` in `main.js`). So per-game projections exist at least for the current day in-season.
- With a `scoringPeriodId` in the statParams the client defaults the split to the game split (VERIFIED, bundle).
- On 2026-10-15 **no such entries exist** for FBA: day 1 to 7 with any combination of `filterStatsForCurrentSeasonScoringPeriodId`, `filterStatsForScoringPeriodIds`, `filterStatsForSourceIds:[1]`, `filterStatsForSplitTypeIds:[5]`, or plain `scoringPeriodId=1..5` returned nothing beyond season entries (VERIFIED, live).
- They are **not retained** after the day: 2026 days 168 to 172 with `filterStatsForSourceIds:[1]` returned nothing, while actual game entries are kept (VERIFIED, live).
- The public `leaguedefaults` path does not expose them either, even for an in-season daily sport (NHL `fhl`, today and tomorrow, VERIFIED, live). A private league path in-season remains the only candidate.
- The FBA projections page in the web app does **not** request per-day projections (it uses season mode with `filterStatsForExternalIds`); the per-period mode is football only (VERIFIED, bundle `players_projections.js`).

### What to check on opening night

Status: UNVERIFIED until then.

Run on 2026-10-20 or later, with `D` = today's day and `W` = the remaining days of the week:

```
GET {LEAGUE}?view=kona_player_info&scoringPeriodId={D}
x-fantasy-filter: {"players":{"filterIds":{"value":[<ids>]},
  "filterStatsForCurrentSeasonScoringPeriodId":{"value":[W...]},
  "filterStatsForSourceIds":{"value":[1]},
  "filterStatsForSplitTypeIds":{"value":[5]}}}
```

Repeat once with `scoringPeriodId={D+1}` and no stats filter, and check `mRoster` with `scoringPeriodId={D+1}`. Record: whether entries appear for `D` only, for `D+1`, or for the whole week; their `id` format (expected `15{gameId}`); and whether `appliedTotal` is league-scored. Hypothesis (UNVERIFIED, memory): ESPN publishes game projections only a day or two ahead.

### Recommended estimator for the app

Until the check passes, estimate "points a pickup adds from day X to the end of the matchup week":

```
per_game = appliedAverage of the projected season entry (statSourceId 1, split 0, current season)
           optionally blended with recent form: appliedAverage of split 2 (L15) when stats["42"] >= 3
           fallback: previous season actual appliedAverage (split 0, source 0, season-1)
games    = games_left(schedule, proTeamId, week_days, X) minus games already started
health   = injury factor (OUT, SUSPENSION, INJURY_RESERVE 0; DOUBTFUL 0.25; DAY_TO_DAY, QUESTIONABLE 0.75; else 1),
           and 0 for days before injuryDetails.expectedReturnDate when present (kona_playercard)
value    = per_game * len(games) * health, counted only on days the player would actually start
```

When per-day projections become available, replace `per_game * games` with the sum of the projected game entries for the remaining days and keep the season-average estimate as the fallback for days without one.

---

## 11. How the app should use these endpoints

1. **One pool snapshot, cached.** Pull the whole league pool once (no `filterStatus`, `limit` 1100, `sortPercOwned`, gzip): about 425 KB on the wire, 0.7 s. Cache 30 to 60 minutes. Derive free agents, rostered players, trending and positional views locally instead of many small calls.
2. **Ask for the stats you need explicitly** with `filterStatsForTopScoringPeriodIds`: `value` = games for the recent log (5 to 10) and `additionalValue` = `["00{S}","10{S}","01{S}","02{S}","03{S}","00{S-1}"]`. Without it the default set changes with context.
3. **Search** with `filterName` (prefix) plus a sort and a `limit`. A `filterName` + `limit` filter without a sort returns `400 FILTER_LIMIT_MISSING_SORT`; add `"sortPercOwned":{"sortPriority":1,"sortAsc":false}`.
4. **Player detail** with `kona_playercard` for the handful of players on screen: `injuryDetails`, the game log and per-stat `appliedStats`.
5. **Schedule** from `proTeamSchedules_wl` (public, cache one day), week table from section 6.2, Eastern-time day mapping.
6. **Player Rater** with `mStatRatings` for positional ranks; in preseason it shows last season.
7. Treat all `appliedTotal` values from league paths as league-scored; recompute from `stats` with `scoringItems` only to explain a number to the user (the per-stat breakdown is `appliedStats` in `kona_playercard`).
8. Guard every parse: `stats == {}` means no data; DNP games are empty entries; unknown filter keys are ignored silently, so unit-test each filter you rely on.

---

## Open questions

1. Do per-game projections (source 1, split 5) exist for future days of the current week, or only for today? What is their `id` format, and are `appliedTotalCeiling`, `projectionAnalysis` and `variance` populated? Check on or after 2026-10-20 (section 10).
2. What is the `player.rankings` shape, and does it ever appear for FBA with `filterRanksForScoringPeriodIds` and `filterRanksForRankTypes`?
3. What does `appliedStatTotal` on `kona_playercard` entries hold in-season (season to date, or the requested `scoringPeriodId`)?
4. Why are only 80 of 82 games per team listed? Confirm the remaining two are NBA Cup knockout dates and when they are added.
5. Is `defaultTopScoringPeriodsCount` for FBA a fixed number? It is a config constant in the bundle (`o["i"]`), not resolved here.
6. Can a free agent added during a day play in that day's later games under `rosterLocktimeType: FIRSTGAME_SCORINGPERIOD`, and how does `matchupAcquisitionLimit: 1.0` (with `matchupLimitPerScoringPeriod: true`) cap pickups per matchup? Both change the "points from a pickup" estimate; they belong to the transactions document. Answer (VERIFIED live, 2026 season): no, an add made after the day's first tip-off joins the roster the next day (see 6.4); and the limit did not cap anything (up to 5 adds per team per day, 9 per week).
7. Is there an upper bound on `limit`? 1200 was accepted with 1095 players in the pool; larger pools (with `filterActive:false` at game level) were not tested.
8. `mStatCorrections` returned an empty list for 2026 day 150; its payload shape needs a day with a real correction.

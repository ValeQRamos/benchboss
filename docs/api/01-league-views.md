# 01. League views (lm-api-reads)

The league endpoint on `lm-api-reads` returns one JSON object whose content is chosen by repeatable `view` query parameters; 24 `m*` views and 10 kona/chat views were probed live, and their names were cross-checked against ESPN's own web bundles.
Every view is a GET. For a private league they need the ESPN session cookies (`espn_s2` is enough for reads; clients normally send `SWID` too), while the season, game, and `leaguedefaults` endpoints are public.
The key facts for a client are: how to find "my team" from the SWID, how scoring periods (days) map to matchup periods (weeks), which views are heavy, and that filtering is done with the `x-fantasy-filter` header, not with query parameters.

Verification legend used throughout:

- **VERIFIED (live)**: seen in a live response on Thu Oct 15, 2026 (2027 season preseason, scoring period 1) or in the completed 2026 season of the same league.
- **VERIFIED (bundle)**: seen in ESPN's web bundle, build `7411ee0540f4-1.517` (`main-f2aedb781c45b792f61b.js` and the `page/basketball/*.js` page bundles).
- **UNVERIFIED**: inference, memory, or third-party knowledge. Treat as a hypothesis.

Reference league: game `fba`, season 2027, a private 10-team `H2H_POINTS` league with team ids `1, 2, 3, 6, 10, 11, 13, 14, 15, 16`; team 3 is the caller's team in examples. Personal data (member names, display names, team names, SWIDs, GUIDs) is replaced with placeholders below.

---

## Quick reference

Base: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba`. `{L}` = `{base}/seasons/{season}/segments/0/leagues/{leagueId}`.
Sizes are uncompressed bytes for the reference league in preseason (in-season payloads grow with stats).

| Method | URL / view | Purpose | Auth | Status |
|---|---|---|---|---|
| GET | `{L}` (no view) | Minimal league: members, team ids/abbrevs/owners, league name (2 KB) | cookies | VERIFIED (live) |
| GET | `{L}?view=mStatus` | League status: current matchup period, first/final/latest scoring period, waiver run info (0.9 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mSettings` | All league settings: scoring, roster slots, schedule, waivers, trades, draft (4 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mTeam` | Teams (records, waiver rank, counters, trade block, pending tx) and full members (71 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mNav` | Light teams + members + a few settings flags, used by the site header (5 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mRoster` | Every team's roster with full player objects and stats (771 KB, 149 KB gzip) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mMatchupScoreLite` | Whole schedule, team ids and total points only (14 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mMatchupScore` | Schedule with scores, live totals, per-day points (52 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mMatchup` | Schedule with per-stat scores plus all rosters (207 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mScoreboard` | Scoreboard: scores, slim rosters, light teams and settings (102 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mBoxscore` | Box score: per-day and per-matchup roster stats for a scoring period (81 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mLiveScoring` | Live scoring marker on schedule (3 KB, nothing extra outside live games) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mTopPerformers` | Top performers per matchup (empty in preseason and for past periods) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mStandings` | Standings helpers incl. playoff odds simulation (17 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mProjectedPlayoffMatchups` | `projected` flag per matchup (5 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mPendingTransactions` | League pending transactions, for example trades in review (1.5 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mTransactions2` | Season transaction log incl. lineup moves, trades, waivers, draft (88 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mDraftDetail` | Draft picks and draft settings (37 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mKeeperRosters` | Rosters plus keeper strategy (767 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=mInvited` | Outstanding invites (1.4 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=modular`, `mSchedule`, `mPositionalRatings`, `mPositionalRatingsStats` | Recognized, but return only the envelope for this league | cookies | VERIFIED (live) |
| GET | `{L}?view=kona_player_info` + filter | Player search (free agents, waivers, by id) with stats | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=kona_playercard` + filter | One player plus his transaction history in this league | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=kona_playerAvailability` + filter | Ownership/lock state of one player plus slim league context | cookies | VERIFIED (live, bundle) |
| GET | `{L}?view=kona_league_communication` | All visible communication topics with messages (124 KB) | cookies | VERIFIED (live) |
| GET | `{L}?view=chat_conversations` | Topic index with `unreadMessageCount` and `lastRead` per member (8 KB) | cookies | VERIFIED (live) |
| GET | `{L}/communication/?view=kona_league_communication` + filter | Activity feed (transactions, settings, status topics), paged | cookies | VERIFIED (live, bundle) |
| GET | `{L}/communication/?view=kona_communication_league_index` | Topics grouped by type for the league home page | cookies | VERIFIED (live, bundle) |
| GET | `{L}/communication/?view=kona_league_messageboard` | Message board topics grouped by type | cookies | VERIFIED (live, bundle) |
| GET | `{L}/draftDetail?view=kona_draft_detail` | Draft detail object only (36 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{base}/leagueHistory/{leagueId}?view=kona_history_standings` | Final standings of every previous season (24 KB) | cookies | VERIFIED (live, bundle) |
| GET | `{base}/leagueHistory/{leagueId}?seasonId=Y&view=...` | Any league view for a past season (array of one) | cookies | VERIFIED (live, bundle) |
| GET | `{base}/seasons/{season}` | Season metadata incl. `currentScoringPeriod.id` (0.2 KB) | none | VERIFIED (live) |
| GET | `{base}/seasons/{season}?view=kona_game_state` | Game flags, draft lobby, stat settings (7 KB) | none | VERIFIED (live, bundle) |
| GET | `{base}/seasons/{season}?view=proTeamSchedules_wl` | NBA teams, every game by scoring period, all enum `typeNames` (423 KB) | none | VERIFIED (live, bundle) |
| GET | `{base}/seasons/{season}/players?scoringPeriodId=0&view=players_wl` | Light list of all players (263 KB) | none | VERIFIED (live, bundle) |
| GET | `{base}` and `{base}/seasons` | Game metadata, current season, list of seasons | none | VERIFIED (live) |
| GET | `{base}/seasons/{season}/segments/0/leaguedefaults/1?view=...` | Default league template (ROTO) usable without cookies | none | VERIFIED (live, bundle) |

---

## 1. Conventions shared by every league view

### 1.1 Request

```
GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}?view=A&view=B&scoringPeriodId=N
Cookie: espn_s2=<espn_s2>; SWID=<SWID>
Accept: application/json
Accept-Encoding: gzip            (optional, recommended)
x-fantasy-filter: {"schedule": {...}} | {"players": {...}} | {"transactions": {...}} | {"topics": {...}}   (optional)
If-None-Match: <ETag>            (optional, enables 304)
```

- `segments/0` is constant for fantasy basketball. VERIFIED (live, bundle)
- `view` may be repeated; the response is the union of what each view adds. VERIFIED (live)
- Query parameters the web client sends to this endpoint: `view`, `scoringPeriodId`, `matchupPeriodId`, `forTeamId`, `rosterForTeamId`, `inviteId`, `cacheBust`. VERIFIED (bundle; function `Ln`/`xn` in main.js)
  - `scoringPeriodId=N` selects the day for roster-like data (lineups, per-day stats). The top-level `scoringPeriodId` in the response echoes it. VERIFIED (live)
  - `forTeamId=T` (sent with `mRoster`) reduces `teams[]` to that single team; works together with `mTeam`. Does not filter `schedule`. VERIFIED (live). The parameter is repeatable: `forTeamId=3&forTeamId=14` returned exactly teams 3 and 14 (VERIFIED (live)), so "me plus my opponent" is one call.
  - `rosterForTeamId=T` keeps all teams but attaches `roster` only to team T. VERIFIED (live)
  - `matchupPeriodId=M` had no visible effect on `mMatchupScore` (still 100 matchups). Filter the schedule with the header instead. VERIFIED (live)
- Header name is case insensitive; the web sends both `x-fantasy-filter` and `X-Fantasy-Filter`. VERIFIED (bundle)

### 1.2 Filters (`x-fantasy-filter`)

The header holds one JSON object keyed by the collection it filters. VERIFIED (bundle; helper `Hn` wraps player filters in `{"players": ...}`; transactions in `{"transactions": ...}`)

| Collection | Filter | Effect | Status |
|---|---|---|---|
| `schedule` | `{"filterMatchupPeriodIds": {"value": [M, ...]}}` | Only those matchup periods (5 matchups each here) | VERIFIED (live, bundle) |
| `schedule` | `{"filterCurrentMatchupPeriod": {"value": true}}` | Only the current matchup period | VERIFIED (live, bundle) |
| `schedule` | `{"filterTeamIds": {"value": [T]}}` | Only matchups of team T (20 regular season rows) | VERIFIED (live) |
| `transactions` | `{"filterType": {"value": ["WAIVER", "WAIVER_ERROR"]}}` | Only those transaction types (web waiver report) | VERIFIED (live, bundle) |
| `players` | `filterStatus`, `filterIds`, `filterSlotIds`, `filterName`, `limit`, `sort*`, `filterStatsForTopScoringPeriodIds`, `filterRanksForSlotIds` | See the players document | VERIFIED (live, bundle) |
| `topics` | `filterType`, `limit`, `limitPerMessageSet`, `offset`, `sortMessageDate`, `filterIncludeMessageTypeIds`, `filterExcludeMessageTypeIds`, `filterMessageToAndFromIds`, `filterDateRange` (`{"value": startMs, "additionalValue": endMs}`), `sortFor` | Communication topics paging and filtering | VERIFIED (live) for `filterType`/`limit`/`sortMessageDate`, (bundle) for the rest |

Note (VERIFIED (live)): a bare `{"topics": ...}` filter is accepted only on the `{L}/communication/` path. On the league root path (`{L}?view=chat_conversations`) it returns HTTP 400 `Unrecognized field "topics"`; there it must be wrapped as `{"communication": {"topics": {...}}}` (that form returned only the 5 chat topics).

A `limit` without a sort fails with HTTP 400 `FILTER_LIMIT_MISSING_SORT` ("Filter: Limit request must be accompanied by a sort"). VERIFIED (live) The web caps `kona_player_info` pages at 50 players. VERIFIED (bundle; `Gn=50`)

### 1.3 Response headers worth reading

| Header | Example | Meaning | Status |
|---|---|---|---|
| `ETag` | `W/"0018865..."` | Weak ETag. Sending it back as `If-None-Match` returns **304 with an empty body**. | VERIFIED (live) |
| `Content-Encoding` | `gzip` | Sent when `Accept-Encoding: gzip` is present. `mRoster` drops from 771 KB to 149 KB. | VERIFIED (live) |
| `X-Fantasy-Filter-Player-Count` | `965` | Total players matching a player filter (for paging). Also present on `mRoster` (1095). | VERIFIED (live, bundle) |
| `X-Fantasy-Filter-Communication-Count` | `20` | Total topics matching a topics filter. | VERIFIED (live, bundle) |
| `X-Fantasy-Role` | `NONE` | Role of the caller; `NONE` for a regular team owner. Other values UNVERIFIED. | VERIFIED (live) |
| `X-Fantasy-Server-Time` | `Thu, 15 Oct 2026 15:03:15 GMT` | Server clock; useful to compute "today" in ESPN time. | VERIFIED (live) |
| `Polling-Interval` | `10` | Returned on `/communication/` calls. The web reads a `polling-interval` header to pace its chat-unread polling (VERIFIED (bundle)); the unit (seconds) is UNVERIFIED. | VERIFIED (live) |
| `Cache-Control` | `must-revalidate` | Plus `Pragma: no-cache`, `Expires: -1`. Responses are served through CloudFront. | VERIFIED (live) |
| `Vary` | `origin,x-fantasy-filter,accept-encoding` | The filter header is part of the cache key. | VERIFIED (live) |

### 1.4 Errors

| HTTP | Body `details[0].type` | When | Status |
|---|---|---|---|
| 401 | `AUTH_LEAGUE_NOT_VISIBLE` ("You are not authorized to view this League.") | Private league without valid cookies | VERIFIED (live) |
| 400 | `FILTER_LIMIT_MISSING_SORT` | `limit` in a filter without a `sort*` key | VERIFIED (live) |
| 400 | HTML (Tomcat "HTTP Status 400, Bad Request" error page, not JSON) | Malformed URL, for example a second `?` | VERIFIED (live) |
| any | `LEAGUE_NOT_FOUND_DELETED` | League deleted (web treats it specially) | VERIFIED (bundle) |

Error JSON shape: `{"messages": [str], "details": [{"message", "shortMessage", "resolution", "type", "metaData"}]}`. VERIFIED (live) Clients must not assume an error body is JSON.

### 1.5 The envelope and unknown views

- Any recognized view returns this envelope plus its own keys (680 bytes alone): VERIFIED (live)

```json
{
  "draftDetail": {"drafted": true, "inProgress": false},
  "gameId": 3,
  "id": 12345678,
  "scoringPeriodId": 1,
  "seasonId": 2027,
  "segmentId": 0,
  "status": { "...": "20 keys, see mStatus" }
}
```

- An **unknown view name** (tested `mBogusXyz`) is silently ignored and the server answers as if no view was given (the 2 KB default body of section 2). No error is raised, so a typo looks like success. VERIFIED (live)
- Keys whose collection is empty are often **omitted**, not sent as `[]` (for example `pendingTransactions` disappears once the last pending trade executes). VERIFIED (live)
- `mScoreboard` and `mTopPerformers` do not add `gameId`/`seasonId`/`segmentId` when requested alone. VERIFIED (live)

---

## 2. No view (default body)

**Request:** `GET {L}`

**Response (2,043 B):** VERIFIED (live)

| Path | Type | Example |
|---|---|---|
| `gameId` | int | `3` |
| `id` | int | league id |
| `scoringPeriodId` | int | `1` |
| `seasonId`, `segmentId` | int | `2027`, `0` |
| `settings.name` | str | `"<League name>"` |
| `status.currentMatchupPeriod` | int | `1` |
| `status.isActive` | bool | `true` |
| `status.latestScoringPeriod` | int | `1` |
| `members[]` | `{displayName: str, id: str, isLeagueManager: bool}` | `{"displayName": "<display name>", "id": "{SWID}", "isLeagueManager": false}` |
| `teams[]` | `{abbrev: str, id: int, owners: [str]}` | `{"abbrev": "ABC", "id": 3, "owners": ["{SWID}"]}` |

**How the app should use it:** cheapest authenticated call. Use it to validate cookies at login and to resolve "my team" (section 3).

---

## 3. Members and "my team"

- `members[].id` and `teams[].owners[]` hold member ids, which are SWIDs in the exact cookie format: uppercase GUID wrapped in braces, `{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`. VERIFIED (live; exact string match against the stored SWID cookie)
- `teams[].primaryOwner` (in `mTeam`) is also the SWID of the main owner. VERIFIED (live)
- Algorithm (VERIFIED (live) for this league, which has one owner per team):
  1. Read the SWID cookie (keep the braces).
  2. `GET {L}` (no view).
  3. `my_team = next(t for t in teams if SWID in t["owners"])`. Compare case-insensitively for safety.
  4. If no team matches, the user is not an owner in this league (or the cookie belongs to another account).
- Team ids are **not contiguous** (1, 2, 3, 6, 10, 11, 13, 14, 15, 16 here). Never index teams by position. VERIFIED (live)
- Member fields by view: VERIFIED (live)

| View | `members[]` keys |
|---|---|
| no view, `mStatCorrections` | `displayName`, `id`, `isLeagueManager` |
| `mTeam` | `displayName`, `firstName`, `id`, `lastName`, `notificationSettings[]` |
| `mNav` | `displayName`, `firstName`, `id`, `isLeagueCreator`, `isLeagueManager`, `lastName` |
| `mKeeperRosters` | `displayName`, `firstName`, `id`, `lastName` |
| `chat_conversations` | `displayName`, `firstName`, `fullName`, `id`, `lastName` |

- `members[].notificationSettings[]` items are `{enabled: bool, forId: int, id: str, type: str}` with types such as `TEAM_PLAYER_INJURY`, `TEAM_TRADE_OFFER`, `WAIVERS`; they are returned for every member, not only the caller. VERIFIED (live)

---

## 4. Scoring periods, matchup periods and dates

This is the most important mapping for a daily-lineup app.

- **Scoring period = one day.** Day boundaries are midnight US Pacific time, which is 03:00 US Eastern (07:00 UTC during daylight time, 08:00 UTC otherwise). VERIFIED (bundle; hardcoded scoring period table for FBA 2027 in main.js)
- Scoring period 1 is **Tue Oct 20, 2026**; scoring period N is Oct 20, 2026 plus (N minus 1) days; scoring period 174 is **Sun Apr 11, 2027**. 175 is the post-season bucket. VERIFIED (bundle, live) (`status.finalScoringPeriod = 174`, NBA games dated accordingly in `proTeamSchedules_wl`)
- `settings.scheduleSettings.matchupPeriods` maps **matchup period id to weekly period ids** (not to days). `periodTypeId: 2` is the `WEEKLY` period type. VERIFIED (live, bundle)
- The weekly period to scoring period ranges are not in any league response; the web reads them from its bundled constants (`segments[0].periodTypes`). VERIFIED (bundle) The app must either hardcode them per season or derive them from dates (weeks run Monday to Sunday; week 1 is short; the All-Star week is merged).

Resulting map for the 2027 season of the reference league (22 matchup periods: 20 regular + 2 playoff rounds of 2 weeks): VERIFIED (bundle, live)

| Matchup | Weekly periods | Scoring periods | First day | Last day | Days |
|---|---|---|---|---|---|
| 1 | 1 | 1 to 6 | Tue Oct 20, 2026 | Sun Oct 25, 2026 | 6 |
| 2 | 2 | 7 to 13 | Mon Oct 26, 2026 | Sun Nov 01, 2026 | 7 |
| 3 | 3 | 14 to 20 | Mon Nov 02, 2026 | Sun Nov 08, 2026 | 7 |
| 4 | 4 | 21 to 27 | Mon Nov 09, 2026 | Sun Nov 15, 2026 | 7 |
| 5 | 5 | 28 to 34 | Mon Nov 16, 2026 | Sun Nov 22, 2026 | 7 |
| 6 | 6 | 35 to 41 | Mon Nov 23, 2026 | Sun Nov 29, 2026 | 7 |
| 7 | 7 | 42 to 48 | Mon Nov 30, 2026 | Sun Dec 06, 2026 | 7 |
| 8 | 8 | 49 to 55 | Mon Dec 07, 2026 | Sun Dec 13, 2026 | 7 |
| 9 | 9 | 56 to 62 | Mon Dec 14, 2026 | Sun Dec 20, 2026 | 7 |
| 10 | 10 | 63 to 69 | Mon Dec 21, 2026 | Sun Dec 27, 2026 | 7 |
| 11 | 11 | 70 to 76 | Mon Dec 28, 2026 | Sun Jan 03, 2027 | 7 |
| 12 | 12 | 77 to 83 | Mon Jan 04, 2027 | Sun Jan 10, 2027 | 7 |
| 13 | 13 | 84 to 90 | Mon Jan 11, 2027 | Sun Jan 17, 2027 | 7 |
| 14 | 14 | 91 to 97 | Mon Jan 18, 2027 | Sun Jan 24, 2027 | 7 |
| 15 | 15 | 98 to 104 | Mon Jan 25, 2027 | Sun Jan 31, 2027 | 7 |
| 16 | 16 | 105 to 111 | Mon Feb 01, 2027 | Sun Feb 07, 2027 | 7 |
| 17 | 17 | 112 to 118 | Mon Feb 08, 2027 | Sun Feb 14, 2027 | 7 |
| 18 | 18 | 119 to 132 | Mon Feb 15, 2027 | Sun Feb 28, 2027 | 14 (All-Star) |
| 19 | 19 | 133 to 139 | Mon Mar 01, 2027 | Sun Mar 07, 2027 | 7 |
| 20 | 20 | 140 to 146 | Mon Mar 08, 2027 | Sun Mar 14, 2027 | 7 |
| 21 (playoffs round 1) | 21, 22 | 147 to 160 | Mon Mar 15, 2027 | Sun Mar 28, 2027 | 14 |
| 22 (playoffs final) | 23, 24 | 161 to 174 | Mon Mar 29, 2027 | Sun Apr 11, 2027 | 14 |

Gotchas:

- The league schedule has only 100 matchups (20 periods x 5) in preseason; playoff matchups appear later (the completed 2026 season has 110, with `playoffTierType: "WINNERS_BRACKET"` and others on periods 21 and 22). VERIFIED (live)
- An NBA-schedule cross-check is available: in `proTeamSchedules_wl`, each game's `scoringPeriodId` equals its dict key, and its `date` (ms epoch) falls inside that Pacific-time day. VERIFIED (live)
- Scoring periods with no NBA games in the current 2027 feed: 15 (Tue Nov 03), 38 (Thu Nov 26), 46 to 53 (Fri Dec 04 to Fri Dec 11), 66 (Thu Dec 24), 123 to 128 (Fri Feb 19 to Wed Feb 24), 173 (Sat Apr 10). Each team currently has 80 scheduled games, not 82. VERIFIED (live) Reading (UNVERIFIED): the December block and the 2 missing games are NBA Cup dates not yet published, and the February block is the All-Star break; expect the feed to change, so re-fetch it daily.

---

## 5. `mStatus`

**Request:** `GET {L}?view=mStatus` (903 B). VERIFIED (live, bundle)

**Response:** envelope where `status` has 22 keys (20 in every other view plus `creationInfo` and `lastUpdateInfo`).

| Path | Type | Example | Notes |
|---|---|---|---|
| `status.currentMatchupPeriod` | int | `1` | Drives "this week" |
| `status.firstScoringPeriod` / `finalScoringPeriod` | int | `1` / `174` | Season bounds in days |
| `status.latestScoringPeriod` | int | `1` | Current day (ESPN time) |
| `status.transactionScoringPeriod` | int | `1` | Day that new transactions apply to |
| `status.isActive`, `isExpired`, `isFull`, `isViewable`, `isToBeDeleted` | bool | `true, false, true, false, false` | `isViewable` is false even for members; meaning UNVERIFIED (probably public visibility) |
| `status.isPlayoffMatchupEdited`, `isWaiverOrderEdited` | bool | `false` | |
| `status.previousSeasons` | [int] | `[2023, 2024, 2025, 2026]` | Seasons available through league history |
| `status.activatedDate`, `standingsUpdateDate` | int (ms) | `1786395026878` | |
| `status.waiverLastExecutionDate` | int (ms) | `1792050543878` | Last waiver run (2026-10-15 07:49 UTC) |
| `status.waiverProcessStatus` | {ISO timestamp: int} | `{"2026-10-14T07:39:06.423+00:00": 1}` | Keyed by waiver run time; value meaning UNVERIFIED |
| `status.teamsJoined` | int | `10` | |
| `status.createdAsLeagueType`, `currentLeagueType` | int | `2`, `0` | Codes UNVERIFIED |
| `status.creationInfo` | `{clientAddress, platform, source}` | `{"platform": "cinco_19013", "source": "{SWID}"}` | Only in `mStatus` |
| `status.lastUpdateInfo` | same | `{"platform": "lm-processor", "source": "NightlyLeagueUpdateTaskProcessor"}` | Only in `mStatus` and `mTransactions2` |

**How the app should use it:** poll it (with `If-None-Match`) to know the current day and matchup; combine with `mSettings` for everything else. Writes take "today" from `status.latestScoringPeriod` (see 04, section 3).

---

## 6. `mSettings`

**Request:** `GET {L}?view=mSettings` (4,063 B). VERIFIED (live, bundle)

**Response:** envelope plus `settings` with: `acquisitionSettings`, `draftSettings`, `financeSettings`, `isAutoReactivate`, `isCustomizable`, `isPublic`, `name`, `restrictionType`, `rosterSettings`, `scheduleSettings`, `scoringSettings`, `size`, `tradeSettings`.

### 6.1 `settings.scoringSettings`

```json
{
  "scoringType": "H2H_POINTS",
  "playerRankType": "STANDARD",
  "allowOutOfPositionScoring": false,
  "homeTeamBonus": 0, "playoffHomeTeamBonus": 0,
  "matchupTieRule": "NONE", "matchupTieRuleBy": 0,
  "playoffMatchupTieRule": "NONE", "playoffMatchupTieRuleBy": 0,
  "scoringItems": [
    {"statId": 0, "points": 1.0, "isReverseItem": false, "leagueRanking": 0.0, "leagueTotal": 0.0}
  ]
}
```

Scoring items of the reference league (statId names VERIFIED (bundle) from the bundled basketball stat table, points VERIFIED (live)):

| statId | Abbrev | Stat | Points |
|---|---|---|---|
| 0 | PTS | Points | +1 |
| 1 | BLK | Blocks | +4 |
| 2 | STL | Steals | +4 |
| 3 | AST | Assists | +2 |
| 6 | REB | Rebounds | +1 |
| 11 | TO | Turnovers | -2 |
| 13 | FGM | Field goals made | +2 |
| 14 | FGA | Field goals attempted | -1 |
| 15 | FTM | Free throws made | +1 |
| 16 | FTA | Free throws attempted | -1 |
| 17 | TPM (3PM) | Three pointers made | +1 |

- Fantasy points for a stat line = sum over `scoringItems` of `stats[statId] * points`. ESPN already does this and returns `appliedStats`, `appliedTotal`, `appliedAverage` on player stat entries. VERIFIED (live)
- `isReverseItem` and `pointsOverrides` (seen in history) matter for category leagues and position-specific scoring; both are neutral here. Semantics UNVERIFIED.
- Other stat ids worth knowing (VERIFIED (bundle)): 4 OREB, 5 DREB, 7 Ejections, 8 Flagrant fouls, 9 PF, 10 Technical fouls, 12 DQ, 18 3PA, 19 FG%, 20 FT%, 21 3P%, 23 FG missed, 24 FT missed, 25 3P missed, 37 Double doubles, 38 Triple doubles, 39 Quadruple doubles, 40 MIN, 41 GS, 42 GP, 43 Team wins.

### 6.2 `settings.rosterSettings`

```json
{
  "lineupSlotCounts": {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 0, "8": 0, "9": 0, "10": 0, "11": 3, "12": 3, "13": 1, "14": 0},
  "positionLimits": {"0": 0, "1": -1, "2": -1, "3": -1, "4": -1, "5": 4},
  "lineupSlotStatLimits": {},
  "isBenchUnlimited": true,
  "isUsingUndroppableList": true,
  "lineupLocktimeType": "INDIVIDUAL_GAME",
  "rosterLocktimeType": "FIRSTGAME_SCORINGPERIOD",
  "moveLimit": -1,
  "autoPilotTypeSupported": "NONE",
  "universeIds": [0]
}
```

- `lineupSlotCounts` keys are lineup slot ids as strings; values are counts. VERIFIED (live)
- Lineup slot ids for basketball (VERIFIED (bundle), from the bundled FBA slot table):

| Id | Abbrev | Eligible positions | Starter |
|---|---|---|---|
| 0 | PG | PG | yes |
| 1 | SG | SG | yes |
| 2 | SF | SF | yes |
| 3 | PF | PF | yes |
| 4 | C | C | yes |
| 5 | G | PG, SG | yes |
| 6 | F | SF, PF | yes |
| 7 | SG/SF | SG, SF | yes |
| 8 | G/F | PG, SG, SF, PF | yes |
| 9 | PF/C | PF, C | yes |
| 10 | F/C | SF, PF, C | yes |
| 11 | UTIL | all | yes |
| 12 | BE (bench) | all | no |
| 13 | IR | all | no |
| 14 | INV | none | no |
| 15 | ALL | all | no |

- Position ids (`player.defaultPositionId`, `positionLimits` keys): 1 PG, 2 SG, 3 SF, 4 PF, 5 C. VERIFIED (bundle; bundled position table: Point Guard, Shooting Guard, Small Forward, Power Forward, Center) and (live; sample players). `-1` means no limit; the meaning of key `0` is UNVERIFIED. `"5": 4` is the "at most 4 centers" rule that makes ESPN reject trades and adds that would exceed it. VERIFIED (live; setting). The HTTP status of that rejection (409 in earlier client runs) is UNVERIFIED here.
- `isBenchUnlimited: true` coexists with a bench count of 3; how ESPN enforces roster size in that case is UNVERIFIED.
- `lineupLocktimeType: "INDIVIDUAL_GAME"`: each player locks at his own game start. `rosterLocktimeType: "FIRSTGAME_SCORINGPERIOD"`: roster adds/drops lock at the first game of the day. Enum values VERIFIED (live; `typeNames.locktimeTypes`); behavioral reading UNVERIFIED.

### 6.3 `settings.scheduleSettings`

```json
{
  "matchupPeriodCount": 20,
  "matchupPeriodLength": 1,
  "periodTypeId": 2,
  "playoffTeamCount": 4,
  "playoffMatchupPeriodLength": 2,
  "variablePlayoffMatchupPeriodLength": false,
  "playoffReseed": false,
  "playoffSeedingRule": "H2H_RECORD",
  "playoffSeedingRuleBy": 0,
  "consolationLadderDisabled": false,
  "divisions": [{"id": 0, "name": "East", "size": 5}, {"id": 1, "name": "West", "size": 5}],
  "matchupPeriods": {"1": [1], "2": [2], "...": "...", "20": [20], "21": [21, 22], "22": [23, 24]}
}
```

VERIFIED (live). See section 4 for how to turn `matchupPeriods` into days. `matchupPeriodCount` is the number of regular-season matchups; ids above it are playoffs. VERIFIED (bundle; `finalRegularSeasonMatchupPeriodId` reads `matchupPeriodCount`)

### 6.4 `settings.acquisitionSettings`

```json
{
  "acquisitionType": "WAIVERS_TRADITIONAL",
  "acquisitionLimit": -1,
  "matchupAcquisitionLimit": 1.0,
  "matchupLimitPerScoringPeriod": true,
  "acquisitionBudget": 100,
  "isUsingAcquisitionBudget": false,
  "minimumBid": 1,
  "waiverHours": 24,
  "waiverOrderReset": false,
  "waiverProcessDays": ["SUNDAY"],
  "waiverProcessHour": 8,
  "transactionLockingEnabled": true,
  "finalPlaceTransactionEligible": 3
}
```

VERIFIED (live). FAAB is off (`isUsingAcquisitionBudget: false`), so `bidAmount` is irrelevant for this league.

Observed behavior (VERIFIED (live), from the completed 2026 season of this league, which had identical `acquisitionSettings`): `matchupAcquisitionLimit: 1.0` does not mean one acquisition per day. Reading `mTransactions2` day by day for all 174 days of 2026 found free agent adds by one team in one scoring period of 1 (304 times), 2 (106), 3 (22), 4 (2) and 5 (1), up to 9 in one weekly matchup, and no `FAILED_MATCHUPACQUISITIONLIMIT` record. The limit is not binding in practice for this league; its exact semantics stay UNVERIFIED. Waiver claims were processed every day of the week (Mon 11, Tue 6, Thu 5, Fri 5, Wed 3, Sun 3 processed claims), always between 07:00 and 09:30 UTC (03:00 to 05:30 ET, the start of the ESPN day), not only on `waiverProcessDays: ["SUNDAY"]`.

### 6.5 `settings.tradeSettings`

```json
{"allowOutOfUniverse": false, "deadlineDate": 1803661200000, "max": -1, "revisionHours": 24, "vetoVotesRequired": 5}
```

VERIFIED (live). `deadlineDate` is Fri Feb 26, 2027 11:00 CT. `revisionHours: 24` matches the observed review window: an accepted trade had `processDate` exactly 24 h after `acceptedDate` and executed at that time. VERIFIED (live) `max: -1` means no trade limit (UNVERIFIED reading).

### 6.6 `settings.draftSettings`, `financeSettings`, others

- `draftSettings`: `{type: "SNAKE", date, availableDate, orderType: "DRAFT_START", pickOrder: [teamId, ...], timePerSelection: 60, auctionBudget: 200, keeperCount: 0, keeperCountFuture: 0, keeperOrderType: "TRADITIONAL", isTradingEnabled: false, leagueSubType: "NONE"}`. VERIFIED (live)
- `financeSettings`: entry fee and per-move fees, all 0 here. VERIFIED (live)
- `size: 10`, `isPublic: false`, `restrictionType: "NONE"`, `isAutoReactivate: true`. VERIFIED (live)

**How the app should use it:** fetch once per session (it rarely changes; use the ETag). Build the slot map, the scoring table, and the matchup-to-days map from it. Never hardcode the scoring weights.

---

## 7. `mTeam`

**Request:** `GET {L}?view=mTeam` (71,106 B; about 41 KB of that is the caller's own `draftStrategy.draftList`). VERIFIED (live, bundle)

**Response:** envelope + `members[]` (5 keys, section 3) + `teams[]` (26 or 27 keys):

| Path | Type | Example | Notes |
|---|---|---|---|
| `teams[].id` | int | `3` | Non-contiguous |
| `teams[].name`, `abbrev` | str | `"<Team name>"`, `"ABC"` | `name` is the full name; older code paths build it from `location` + `nickname` (not present in 2027 responses) |
| `teams[].logo`, `logoType` | str | URL, `"VECTOR"` / `"CUSTOM_UPLOAD"` | |
| `teams[].owners`, `primaryOwner` | [str], str | `["{SWID}"]` | Section 3 |
| `teams[].divisionId` | int | `0` | Matches `scheduleSettings.divisions[].id` |
| `teams[].record.{overall,home,away,division}` | object | `{wins, losses, ties, percentage, pointsFor, pointsAgainst, gamesBack, streakLength, streakType}` | `streakType` `"NONE"`/`"WIN"`/`"LOSS"` (latter two UNVERIFIED) |
| `teams[].playoffSeed` | int | `8` | Current seed; meaningful once games are played |
| `teams[].points`, `pointsAdjusted`, `pointsDelta` | float | `0.0` | |
| `teams[].rankCalculatedFinal`, `rankFinal` | int | `0` | Final rank after the season |
| `teams[].currentProjectedRank`, `draftDayProjectedRank` | int | `6` | ESPN projections |
| `teams[].waiverRank` | int | `3` | Waiver priority (1 = first) |
| `teams[].eliminated`, `eliminationMatchupPeriod` | bool, int | `false`, `0` | |
| `teams[].isActive`, `isTransactionLocked` | bool | `false` | |
| `teams[].valuesByStat` | {statId: float} | `{"0": 0.0, "1": 0.0, ...}` | Season totals for the scoring stats |
| `teams[].transactionCounter` | object | `{acquisitions, drops, trades, moveToActive, moveToIR, misc, acquisitionBudgetSpent, paid, teamCharges, matchupAcquisitionTotals: {matchupPeriodId: count}}` | `matchupAcquisitionTotals` keyed by matchup period (VERIFIED (live) in 2026) |
| `teams[].tradeBlock.players` | {playerId: str} | `{"4432166": "UNTOUCHABLE"}` | Values from `tradeBlockStatusTypes`: `NORMAL`, `ON_THE_BLOCK`, `UNTOUCHABLE`. Empty object when nothing is set |
| `teams[].watchList` | [int] | `[4432194, 4683634]` | Player ids on the caller's watch list (the star in the ESPN app). Only the caller's own team carries the key (1 of 10 teams on 2026-10-16); it is an empty list when nothing is watched. VERIFIED (live). Changed with `POST {WRITES}/teams/{teamId}`, see [04 §13](04-writes-transactions.md#13-watch-list-post-teamsteamid) |
| `teams[].pendingTransactions[]` | [transaction] | see section 12 | Only on teams involved, only while pending; key absent otherwise |
| `teams[].draftStrategy` | object | `{keeperPlayerIds: []}` for other teams | The caller's own team also gets `draftList[{playerId, auctionValue}]` (1,095 rows), `excludedPlayerIds`, `futureKeeperPlayerIds` |

**How the app should use it:** standings table, waiver order, trade block, transaction counters, and the owner-to-team map. Combine `mTeam` with `mRoster` and `forTeamId` for a single-team page. It does not include rosters.

---

## 8. `mNav`

**Request:** `GET {L}?view=mNav` (5,017 B). VERIFIED (live, bundle) The web's cached league loader appends `modular` and `mNav` to every view list it requests. VERIFIED (bundle)

**Response:** envelope (with `draftDetail.completeDate`) + `members[]` (6 keys incl. `isLeagueCreator`, `isLeagueManager`) + `teams[]` (`abbrev`, `id`, `logo`, `logoType`, `name`, `owners`) + `settings` (`name`, `isPublic`, `isCustomizable`, `acquisitionSettings.isUsingAcquisitionBudget`, `draftSettings.keeperCount`, `rosterSettings.isUsingUndroppableList`, `scoringSettings.scoringType`).

**How the app should use it:** the best light call for "team names + owner names + scoring type" (members have first and last names here, unlike the no-view body).

---

## 9. `mRoster`

**Request:** `GET {L}?view=mRoster[&scoringPeriodId=N][&forTeamId=T]`. VERIFIED (live, bundle)

| Variant | Size | Result |
|---|---|---|
| no params | 770,763 B (148,539 B gzip) | all 10 teams, current day |
| `forTeamId=3` | 76,817 B | `teams` has only team 3 |
| `rosterForTeamId=3` | 76,904 B | all teams listed, only team 3 has `roster` |
| `scoringPeriodId=5` | 769,148 B | lineups as they stand for day 5 (future lineups included) |

**Response:**

| Path | Type | Example | Notes |
|---|---|---|---|
| `teams[].roster.entries[]` | list | 13 per team | |
| `...entries[].playerId` | int | `4431678` | |
| `...entries[].lineupSlotId` | int | `0` | Section 6.2 |
| `...entries[].acquisitionType` | str | `"DRAFT"`, `"TRADE"`, `"ADD"` | |
| `...entries[].acquisitionDate` | int (ms) | `1791860708514` | |
| `...entries[].injuryStatus` | str | `"NORMAL"` | **Roster** injury status (`NORMAL`, `FUTURE_FROM_IR`, `FUTURE_TO_IR`), not the player's |
| `...entries[].status` | str | `"NORMAL"` | `rosterStatusTypes`: `NORMAL`, `FUTURE_ADD`, `FUTURE_DROP`, `TRADE_RESERVED` |
| `...entries[].pendingTransactionIds` | [str] or null | `["{GUID}"]` | Set while the player is in a pending trade |
| `...playerPoolEntry.id`, `onTeamId`, `status` | int, int, str | `4431678`, `1`, `"ONTEAM"` | |
| `...playerPoolEntry.lineupLocked`, `rosterLocked`, `tradeLocked` | bool | `false` | Use before proposing moves |
| `...playerPoolEntry.keeperValue`, `keeperValueFuture`, `appliedStatTotal` | int, int, float | | |
| `...playerPoolEntry.player` | object | 16 to 18 keys | `id, fullName, firstName, lastName, proTeamId, defaultPositionId, eligibleSlots[], injured, injuryStatus, active, droppable, lastNewsDate, ownership{percentOwned, percentChange, percentStarted, averageDraftPosition, auctionValueAverage}, draftRanksByRankType{STANDARD, ROTO}, seasonOutlook, stats[], universeId`, sometimes `proGamePlayerDetail{gameId: {starterStatus, lineupOrder}}` |
| `teams[].roster.appliedStatTotal` | float | `0.0` | |
| `teams[].roster.tradeReservedEntries` | int | `0` | |

Player `injuryStatus` values (`typeNames.injuryStatusTypes`): `ACTIVE, PROBABLE, QUESTIONABLE, DOUBTFUL, OUT, INJURY_RESERVE, DAY_TO_DAY, ..., SUSPENSION`. VERIFIED (live)

`player.stats[]` entries returned by default (VERIFIED (live)): id = `{statSourceId}{statSplitTypeId}{seasonId}`

| `id` | Source | Split | Meaning |
|---|---|---|---|
| `002027` | 0 real | 0 season | Season totals and averages |
| `012027` | 0 real | 1 | Last 7 days |
| `022027` | 0 real | 2 | Last 15 days |
| `032027` | 0 real | 3 | Last 30 days |
| `102027` | 1 projected | 0 season | ESPN season projection |
| `002026` / `102026` | | | Previous season real / projected |
| `05{gameId}` | 0 real | 5 game | One game; carries `scoringPeriodId` and `externalId` = NBA game id (in-season) |

Each entry has `stats{statId: value}`, `appliedStats{statId: points}`, `appliedTotal`, `appliedAverage`, `averageStats`, `scoringPeriodId`, `seasonId`, `proTeamId`, `externalId`. Split ids and names VERIFIED (bundle; `splitTypes`: 0 Season, 1 Last 7, 2 Last 15, 3 Last 30, 4 Average, 5 Game). In preseason the real 2027 splits (`002027`, `012027`, `022027`, `032027`) exist with `appliedTotal: 0.0` for all 130 rostered players, while `102027` carries projections (VERIFIED (live)); treat a zero total with no games as "no data".

Effect of `scoringPeriodId` (VERIFIED (live)):

- Lineup slots differ per day: future lineups set through `FUTURE_ROSTER` show up when you request that day, for every team.
- In the completed 2026 season, `scoringPeriodId=60` added `05{gameId}` game entries for the most recent game on or before that day (some players' entries carried `scoringPeriodId` 59), and `playerPoolEntry.appliedStatTotal` equaled that day's game points. Exact selection rule UNVERIFIED.

**How the app should use it:** use `forTeamId` for the user's roster (10x smaller), `scoringPeriodId` for any day other than today, and gzip. Fetch all rosters only when needed (trade search, league-wide views).

---

## 10. Schedule views (matchups)

All add `schedule[]`. Without a filter they return the whole season (100 rows here). Detailed sub-objects (`rosterForCurrentScoringPeriod`, `rosterForMatchupPeriod`, `pointsByScoringPeriod`, live totals) appear only on rows of the current matchup period, or of the period that contains the requested `scoringPeriodId`; other rows keep only scores. VERIFIED (live)

Schedule row ids: `schedule[].id` is a stable matchup id (1 to 100 regular season, 101+ playoffs). VERIFIED (live)

### 10.1 `mMatchupScoreLite`

Size: 13,560 B.

```json
{"id": 1, "matchupPeriodId": 1, "winner": "UNDECIDED",
 "home": {"teamId": 1, "totalPoints": 0.0},
 "away": {"teamId": 13, "totalPoints": 0.0}}
```

VERIFIED (live, bundle). `winner`: `HOME`, `AWAY`, `TIE`, `UNDECIDED`. A bye would have no `away` (UNVERIFIED; no byes in a 10-team league).

**Use:** the full season schedule (opponent per week) at minimal cost. Example: team 3 plays team 14 in matchup 1 (home), team 15 in matchup 2 (away), and so on.

### 10.2 `mMatchupScore`

Size: 52,082 B; 13,156 B with `filterCurrentMatchupPeriod`; 2,735 B for a future period.

Row keys: `id, matchupPeriodId, playoffTierType, winner, home, away`. Side keys (current period): VERIFIED (live)

| Path | Type | Notes |
|---|---|---|
| `teamId` | int | |
| `totalPoints` | float | Official total for the matchup so far |
| `totalPointsLive` | float | Live total including games in progress |
| `pointsByScoringPeriod` | {scoringPeriodId: float} | Points per day of the matchup (7 keys in a full week, 14 in double weeks) |
| `cumulativeScore` / `cumulativeScoreLive` | `{wins, losses, ties, statBySlot}` | Category counters; zero in points leagues |
| `adjustment`, `tiebreak` | float | Commissioner adjustment, tiebreak value |
| `eliminationMatchupPeriod` | int | |
| `rosterForCurrentScoringPeriod` | `{appliedStatTotal, entries[{lineupSlotId, playerPoolEntry{player{stats[]}}}]}` | Day roster; with `scoringPeriodId=N` its stats are for day N |
| `rosterForMatchupPeriodDelayed` | `{entries: []}` | Purpose UNVERIFIED |

`playoffTierType`: `NONE` in regular season; `WINNERS_BRACKET`, `WINNERS_CONSOLATION_LADDER`, `LOSERS_CONSOLATION_LADDER` in playoffs. VERIFIED (live)

Effect of `scoringPeriodId` (VERIFIED (live), 2026 season, matchup 9, day 60): with the parameter, every row of that period gets `rosterForCurrentScoringPeriod` with 14 entries and stats for day 60 only (`appliedStatTotal: 121.0`); without it, the past period has no roster object at all.

**Use:** the main "this week" call. Recommended: `view=mMatchupScore&view=mStatus` with `{"schedule": {"filterCurrentMatchupPeriod": {"value": true}}}`. Read `totalPointsLive` (fallback `totalPoints`) and `cumulativeScore`.

### 10.3 `mMatchup`

Size: 207,370 B.

Adds to each row `home/away.{cumulativeScore.scoreByStat{statId: {score, rank, result, ineligible}}, gamesPlayed, rosterForCurrentScoringPeriod (full entries), rosterForMatchupPeriod, rosterForMatchupPeriodDelayed, teamId, totalPoints}` and also adds `teams[].roster` for every team (like `mRoster` without stats). VERIFIED (live). The web pairs it with `mMatchupScore`, a `filterMatchupPeriodIds` filter, and `scoringPeriodId` (VERIFIED (bundle)); that combination was 775 KB here because of the rosters.

**Use:** per-stat breakdown of a matchup. Prefer `mBoxscore` for the box score page.

### 10.4 `mScoreboard`

Size: 102,349 B.

Rows: `id, winner, home, away` (no `matchupPeriodId`; combine with `mMatchupScore`). Current-period sides carry `rosterForCurrentScoringPeriod.entries[{injuryStatus, lineupSlotId, playerId, playerPoolEntry{appliedStatTotal, id, onTeamId, status, player{..., jersey, eligibleDateByPosition, stats}}, status}]`, `rosterForMatchupPeriod`, `totalPointsLive`. Adds slim `teams[]` (`abbrev, divisionId, id, logo, name, rankCalculatedFinal, record.overall{wins, losses, ties}`), `settings.scheduleSettings{divisions, matchupPeriods, periodTypeId}`, `settings.scoringSettings.scoringItems`, and a 4-key `status`. VERIFIED (live, bundle)

The web's league home page requests `modular, mNav, mMatchupScore, mScoreboard, mStatus, mSettings, mTeam, mPendingTransactions` with `filterCurrentMatchupPeriod` (152 KB). VERIFIED (live, bundle)

### 10.5 `mBoxscore`

Size: 80,785 B.

Rows: `id, matchupPeriodId, home, away`. Sides: `cumulativeScore` (with `scoreByStat`), `rosterForCurrentScoringPeriod`, `rosterForMatchupPeriod`, `rosterForMatchupPeriodDelayed`, `teamId`, `tiebreak`, `totalPoints`. Also adds `teams[]` (7 keys) and `settings` like `mScoreboard`. VERIFIED (live, bundle)

In-season shape (VERIFIED (live), 2026 season, `scoringPeriodId=60`, matchup 9):

- `rosterForCurrentScoringPeriod.entries[].playerPoolEntry.player.stats[]` = one entry per game that day: `{id: "05401810238", externalId: "401810238", statSplitTypeId: 5, scoringPeriodId: 60, stats{45 stat ids}, appliedStats{scoring stat ids}, appliedTotal}`.
- `rosterForMatchupPeriod.entries[].playerPoolEntry.{appliedStatTotal, player.stats[0]}` = the player's matchup-to-date totals (`id: "05null"`, `scoringPeriodId: 0`).
- `pointsByScoringPeriod` keyed by the 7 days of the matchup.

The web uses `mBoxscore, mMatchupScore, mRoster, mSettings, mStatus, mTeam` with `filterMatchupPeriodIds` or `filterCurrentMatchupPeriod`. VERIFIED (bundle)

**Use:** day-by-day box score for a matchup. Always send `scoringPeriodId` and a schedule filter.

### 10.6 `mLiveScoring`

Size: 2,948 B.

Outside live games it only adds `schedule[].matchupPeriodId` (both in preseason and for 2026 periods). VERIFIED (live) What it adds during live games is UNVERIFIED (expected: live point fields). The web uses it on the standings and team pages. VERIFIED (bundle)

### 10.7 `mTopPerformers`

Size: 2,604 B.

Returns only `schedule[{home: {rosterForMatchupPeriod: {entries: []}}, away: {...}}]` with no envelope. Entries are empty in preseason and for completed 2026 periods (sides were `{}`). VERIFIED (live) Contents during a live week UNVERIFIED. Used by the web scoreboard page. VERIFIED (bundle)

### 10.8 `mProjectedPlayoffMatchups`

Size: 4,748 B.

Adds `schedule[].{matchupPeriodId, projected: bool}`. All `false` in preseason. Combined with `mMatchupScore` on 2026 periods 21 and 22 it returned the 10 playoff rows with `playoffTierType` and `projected: false`. VERIFIED (live, bundle)

---

## 11. `mStandings`

Size: 16,950 B.

Adds `schedule[].{matchupPeriodId, home/away.{teamId, totalPoints, gamesPlayed}}` and `teams[].{id, playoffClinchType, currentSimulationResults}`. VERIFIED (live, bundle)

```json
{"id": 3, "playoffClinchType": "UNKNOWN",
 "currentSimulationResults": {"rank": 6, "playoffPct": 0.3825, "divisionWinPct": 0.1875,
   "playoffClinchType": "UNKNOWN",
   "modeRecord": {"wins": 10, "losses": 10, "ties": 0, "percentage": 0.0, "pointsFor": 0.0, "pointsAgainst": 0.0, "gamesBack": 0.0, "streakLength": 0, "streakType": "NONE"}}}
```

`currentSimulationResults` is ESPN's season simulation (playoff odds). It is present in preseason 2027 and absent for the completed 2026 season. VERIFIED (live) The web standings page sends `mLiveScoring, mMatchupScore, mRoster, mSettings, mStandings, mStatus, mTeam` with a players filter `filterStatsForSourceIds [0]` and a game split, plus an optional `filterMatchupPeriodIds`. VERIFIED (bundle)

Team fields, re-checked on 2026-10-16 (preseason, all 10 teams). VERIFIED (live) unless marked:

| Path | Type | Notes |
|---|---|---|
| `teams[].playoffClinchType` | str | `UNKNOWN` for every team in preseason. benchboss treats `UNKNOWN` and `NONE` as "no flag" and maps `PLAYOFFS`, `DIVISION`, `BYE`, `TOP_SEED` and `ELIMINATED` to tags; those five names were not seen live (UNVERIFIED) |
| `teams[].currentSimulationResults.playoffPct` | float 0..1 | Share of ESPN's simulated seasons in which the team makes the playoffs. Over all teams it adds up to the number of playoff spots (4.0 in a league with 4 spots) |
| `teams[].currentSimulationResults.divisionWinPct` | float 0..1 | Same for winning the division |
| `teams[].currentSimulationResults.rank` | int | A rank from the simulation; by its name the projected final rank (UNVERIFIED). benchboss does not read it |
| `teams[].currentSimulationResults.playoffClinchType` | str | Same values as the top-level field; benchboss reads the top-level one first |
| `teams[].currentSimulationResults.modeRecord` | object | `{wins, losses, ties, percentage, pointsFor, pointsAgainst, gamesBack, streakLength, streakType}`, the record shape of `mTeam`; by its name the most common simulated final record (UNVERIFIED) |

`mStandings` alone carries no `settings`; read `scheduleSettings.playoffTeamCount`, `playoffSeedingRule` and `divisions` from `mSettings`. benchboss 1.0.2 adds `mStandings` to its one league read (`mRoster, mTeam, mSettings, mMatchupScore, mStatus, mStandings`).

**Use:** playoff odds column in the standings view, clinch tags, and ESPN's number next to benchboss's own simulation on the playoff race screen.

---

## 12. Transactions

### 12.1 `mPendingTransactions`

Size: 1,500 B with one pending item, 680 B when none.

Adds top-level `pendingTransactions[]` (key omitted when empty). `mTeam` on its own also exposes the same items under `teams[].pendingTransactions` of each involved team. VERIFIED (live, bundle)

Example (trimmed, ids replaced): a trade both teams accepted, waiting for the review window:

```json
{"id": "{TX-GUID}", "type": "TRADE_ACCEPT", "status": "PENDING", "isPending": true,
 "teamId": 3, "memberId": "{SWID}", "executionType": "EXECUTE", "scoringPeriodId": 1,
 "proposedDate": 1791989961412, "acceptedDate": 1791990163580,
 "processDate": 1792076563580, "expirationDate": 1792162761437,
 "teamActions": {"3": "ACCEPTED", "1": "ACCEPTED"},
 "items": [
   {"type": "TRADE", "playerId": 5160992, "fromTeamId": 3, "toTeamId": 1, "fromLineupSlotId": 11, "toLineupSlotId": -1, "isKeeper": false, "overallPickNumber": 0, "acquisitionBudget": 0},
   {"type": "TRADE", "playerId": 2595516, "fromTeamId": 1, "toTeamId": 3, "fromLineupSlotId": 6, "toLineupSlotId": -1, "isKeeper": false, "overallPickNumber": 0, "acquisitionBudget": 0}],
 "bidAmount": 0, "rating": 0, "isActingAsTeamOwner": false, "isLeagueManager": false, "skipTransactionCounters": false, "subOrder": 0}
```

This trade executed at its `processDate` (2026-10-15 15:02 UTC) while the probes were running; the next `mPendingTransactions` call returned no `pendingTransactions` key. VERIFIED (live)

Open trade proposals (VERIFIED (live)): no open proposal existed while these probes ran. The three `TRADE_PROPOSAL` rows with `status: "PENDING"` in `mTransactions2` were all already resolved: one was withdrawn by its proposer (team 10) one minute after it was sent (a `TRADE_PROPOSAL` + `executionType: CANCEL` record points at it through `relatedTransactionId`), one was declined, and one was accepted and processed. `mTransactions2` never updates the original row, so `PENDING` there is stale. Whether a live incoming offer shows up in `mPendingTransactions` is still unobserved (the web trade review page expects it there, VERIFIED (bundle)).

### 12.2 `mTransactions2`

Size: 87,651 B, 174 rows.

Adds top-level `transactions[]` for the whole season so far, including other teams' lineup moves. In the 2027 preseason `scoringPeriodId` did not filter it (the full log came back for both 1 and 3). That is a preseason effect only (VERIFIED (live)): on the completed 2026 season the same view returns **only the rows of the requested `scoringPeriodId`** (day 59: 18 rows, day 61: 31, day 174: 51, all carrying that day's id) and **0 rows when the parameter is omitted** or is 0; `leagueHistory/{id}?seasonId=2026&view=mTransactions2` returned 0 rows with or without it. In-season 2027 behavior is UNVERIFIED until opening night; the app should always pass `scoringPeriodId` explicitly and fetch each day it needs. Filter by type with `{"transactions": {"filterType": {"value": [...]}}}` (WAIVER only: 1,506 B; trade types only: 8,186 B). VERIFIED (live, bundle)

Observed `(type, status)` counts: `DRAFT/EXECUTED 130`, `FUTURE_ROSTER/EXECUTED 21`, `ROSTER/EXECUTED 10`, `TRADE_PROPOSAL/PENDING 3`, `TRADE_PROPOSAL/CANCELED 3`, `TRADE_ACCEPT 3` (rows with no `status` and empty `items`, linked to their proposal through `relatedTransactionId`), `TRADE_DECLINE/EXECUTED 2`, `TRADE_VETO/EXECUTED 1`, `WAIVER/EXECUTED 1`. VERIFIED (live)

Row keys: `id, type, status, teamId, memberId, scoringPeriodId, proposedDate, processDate, expirationDate, executionType, isPending, items[], teamActions, relatedTransactionId, bidAmount, rating, isActingAsTeamOwner, isLeagueManager`. VERIFIED (live)

Item `type` values seen: `DRAFT`, `LINEUP`, `TRADE`, `ADD`, `DROP`. For `LINEUP` items `fromTeamId`/`toTeamId` are 0 and the slots carry the move. `memberId` is a SWID or a processor name (`NightlyLeagueUpdateTaskProcessor`, `TradeTaskProcessor`). VERIFIED (live)

Enums from `typeNames` (VERIFIED (live)):

- `transactionTypes`: `TRADE_DECLINE, TRADE_PROPOSAL, TRADE_ACCEPT, TRADE_UPHOLD, TRADE_VETO, WAIVER_ERROR, TRADE_ERROR, WAIVER, ROSTER, FUTURE_ROSTER, RETRO_ROSTER, FREEAGENT, DRAFT`
- `transactionStatusTypes`: `PENDING, EXECUTED, CANCELED, FAILED_*` (33 values incl. `FAILED_POSITIONLIMIT`, `FAILED_ROSTERLOCK`, `FAILED_LINEUPLOCK`, `FAILED_TRADELOCK`, `FAILED_MATCHUPACQUISITIONLIMIT`, `FAILED_UNDROPPABLEPLAYER`)
- `transactionTeamActionTypes`: `INVOLVED, ACCEPTED, APPROVED, VETOED, PROTESTED`
- `executionTypes`: `EXECUTE, CANCEL, PROCESS, ANALYZE`
- `moveTypes`: `NONE, LINEUP, ADD, DROP, TRADE, DRAFT, UNDRAFT, DRAFT_TRADE, ACQUISITION_BUDGET_TRADE, FUTURE_DRAFT_TRADE`

**How the app should use it:** detect incoming trade offers with the trade-type filter, then keep only `TRADE_PROPOSAL` rows with `executionType: EXECUTE` that involve the user's team, have `expirationDate` in the future, and have **no** other row whose `relatedTransactionId` points at them (a `CANCEL`, `TRADE_DECLINE` or `TRADE_ACCEPT` resolves them; `isPending: true` alone is stale, see 12.1). Show recent adds/drops with `{"filterType": {"value": ["WAIVER", "FREEAGENT"]}}`. Poll with the ETag.

---

## 13. Draft and keepers

- `mDraftDetail` (37,381 B): `draftDetail.{completeDate, drafted, inProgress, picks[]}` and `settings.draftSettings`. Pick: `{id, overallPickNumber, roundId, roundPickNumber, teamId, playerId, memberId, lineupSlotId, keeper, reservedForKeeper, bidAmount, nominatingTeamId, autoDraftTypeId, tradeLocked}`. VERIFIED (live, bundle)
- `{L}/draftDetail?view=kona_draft_detail` (36,413 B) returns the same draft detail object as the top level (no envelope). VERIFIED (live, bundle)
- `mKeeperRosters` (766,533 B): `members[]` (4 keys) and `teams[]` with `divisionId, draftStrategy, id, isActive, logo, logoType, name, owners, roster`. No envelope. Keepers are disabled in this league (`keeperCount: 0`). VERIFIED (live, bundle)

---

## 14. Other league views

- `mInvited` (1,420 B): `invited[{id, inviteType, isDeleted, teamId}]`, for example `{"inviteType": "COPY_TO_CLIPBOARD", "teamId": -1}`. VERIFIED (live, bundle)
- `modular`, `mSchedule`, `mPositionalRatings`, `mPositionalRatingsStats`: recognized (they return the 680 B envelope, unlike an unknown name) but add nothing for this league, in 2027 preseason and in the completed 2026 season (with `scoringPeriodId=100`). The web reads `positionAgainstOpponent.positionalRatings` from `mPositionalRatingsStats`. VERIFIED (live, bundle); when FBA fills it is UNVERIFIED.
- `mStatCorrections` and `kona_game_state` on the **league** path behave like the default body plus `teams[].name` (2,274 B); they are not league views. `mStatCorrections` belongs to `{base}/seasons/{season}/players/` with a players filter (VERIFIED (bundle)); `kona_game_state` belongs to the season endpoint (section 17).

---

## 15. Player views on the league path

Covered in depth by the players document; summary here.

| View | Filter | Returns | Status |
|---|---|---|---|
| `kona_player_info` | `{"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "limit": 50, "sortPercOwned": {"sortPriority": 1, "sortAsc": false}}}` | `players[{id, onTeamId, status, lineupLocked, rosterLocked, tradeLocked, keeperValue, keeperValueFuture, draftAuctionValue, droppedByEliminatedTeam, player{...}}]` with `ownership` including `percentChange`, `averageDraftPositionPercentChange`, `activityLevel`, `date` | VERIFIED (live, bundle) |
| `kona_playercard` | `{"players": {"filterIds": {"value": [playerId]}}}` | One player (21 player keys incl. `laterality`, `stance`, `invalid`) plus `transactions[]` for that player in this league | VERIFIED (live, bundle) |
| `kona_playerAvailability` | same `filterIds` | `players[{id, onTeamId, status, lineupLocked, rosterLocked, tradeLocked, player{7 keys}}]` plus slim `teams[{id, name, owners, waiverRank, transactionCounter}]`, `settings` (acquisition, trade, schedule) and `status.{latestScoringPeriod, transactionScoringPeriod}` | VERIFIED (live, bundle) |

The web adds `filterRanksForSlotIds` and a default `filterStatsForTopScoringPeriodIds` whose `additionalValue` lists `0{split}{season}` for each non-game split, `10{season}` (projection) and, in some cases, `00{season - 1}`; it caps `limit` at 50. VERIFIED (bundle) A filter of `{"value": 2, "additionalValue": ["002027", "102027", "022027", "002026"]}` returns exactly the last 2 games plus those four entries. VERIFIED (live) The `x-fantasy-filter-player-count` header gives the total for paging. VERIFIED (live)

---

## 16. Communication views readable from lm-api-reads

The web reads communication from `lm-api-communication` (host type `HOST_TYPE_COMMUNICATION_API`, path `{L}/communication/`). VERIFIED (bundle) The same GET views also answer on **lm-api-reads**, which lets a read-only client stay off the communication host. VERIFIED (live)

| Call | Size | Returns |
|---|---|---|
| `{L}?view=chat_conversations` | 8,221 B | `communication.topics[{id, type, dateEdited, unreadMessageCount, lastRead{memberId: ms}, viewableBy[], subject}]` + `members[{displayName, firstName, fullName, id, lastName}]` |
| `{L}?view=kona_league_communication` | 123,648 B | `communication.topics[]` with full `messages[]` for every topic the caller can see (league chat, the caller's DMs, activity) |
| `{L}?view=kona_communication_league_index` | 249,909 B | `communication.{topics[], topicsByType{TYPE: [...]}}` |
| `{L}/communication/?view=kona_league_communication` + topics filter | 4,343 B for 3 topics | `topics[]` (filtered and paged; `X-Fantasy-Filter-Communication-Count`, `Polling-Interval` headers) |
| `{L}/communication/?view=kona_communication_league_index` + filter | 52,120 B | `topics[]` + `topicsByType` |
| `{L}/communication/?view=kona_league_messageboard` + filter | 49,633 B | `topicsByType` |

Topic keys: `id, type, author, date, dateEdited, isDeleted, isEdited, creationInfo, lastUpdateInfo, targetId, totalMessageCount, viewableBy[], messages[]` (`subject: "DM"` on DMs, `for` on some). Message keys: `id, topicId, author, date, messageTypeId, content (text messages), from, to, for, targetId, isAlternateFormat, isDeleted, isEdited, creationInfo`. VERIFIED (live)

Topic types seen: `ACTIVITY_TRANSACTIONS` 20, `ACTIVITY_SETTINGS` 11, `CHAT_DIRECT_MESSAGE` 4, `ACTIVITY_STATUS` 3, `CHAT_ALL_MEMBERS` 1, `CHAT` 1. Full enum `topicTypes`: `NOTE, POLL, MSG_BOARD, CHAT, EMAIL, OTHER, ACTIVITY_TRANSACTIONS, ACTIVITY_SETTINGS, ACTIVITY_STATUS, ACTIVITY_SCHEDULE, MSG_BOARD_GROUP, MSG_BOARD_MATCHUP, REMINDER_ACTIVATE, REMINDER_SCHEDULE, CHAT_ALL_MEMBERS, CHAT_DIRECT_MESSAGE`. VERIFIED (live)

Activity message semantics (VERIFIED (live) by matching against `mTransactions2`): for transaction messages, `targetId` is the player id; for trade messages `from`/`to` are team ids; for `TRANSACTION_ROSTER` (188) `from`/`to` are lineup slot ids and `for` is the team id. The activity topic's own `targetId` varies: a transaction GUID (or the related proposal's GUID) on trade topics, the scoring period number on lineup (`188`) topics, and absent on some waiver topics.

`messageTypeId` values seen and their names (VERIFIED (bundle) from the bundled message type table unless noted):

| Id | Name | Topic type |
|---|---|---|
| 0 | `CUSTOM` (text message, has `content`) | chats, DMs |
| 106 | `DIVISION_MODIFY` | settings |
| 111 | `DRAFT_SETTINGS_DATE_CHANGE` | settings |
| 116 | `DRAFT_SETTINGS_TIME_PER_SELECTION_CHANGE` | settings |
| 119 / 120 | `DRAFT_STATUS_DRAFT_COMPLETE` / `DRAFT_STATUS_IN_PROGRESS` | status |
| 128 | `MEMBER_LEAVE` | settings |
| 160 | `STATUS_ACTIVATE` | status |
| 162 to 166 | `TEAM_ABBREV_CHANGE`, `TEAM_DIVISION_CHANGE`, `TEAM_NAME_CHANGE`, `TEAM_OWNER_DELETE`, `TEAM_OWNER_JOIN` | settings |
| 176 / 177 | `TRADE_SETTINGS_REVISION_HOURS_CHANGE` / `TRADE_SETTINGS_VOTES_REQ_CHANGE` | settings |
| 178 / 179 | `TRANSACTION_FREEAGENT_ADD` / `TRANSACTION_FREEAGENT_DROP` | (enum, not seen yet) |
| 180 / 181 | `TRANSACTION_WAIVER_ADD` / `TRANSACTION_WAIVER_DROP` | transactions |
| 188 | `TRANSACTION_ROSTER` | transactions |
| 224 | `TRANSACTION_TRADE_ACCEPT_TRADE` | transactions |
| 230 | `TRANSACTION_TRADE_PROPOSAL_TRADE` | transactions |
| 244 | `TRANSACTION_TRADE_PROCESSED_TRADE` | transactions |
| 252 | `TRANSACTION_LIKELY_TO_TRADE` | settings |
| 259, 260 | Sticker, GIF (not in the kona table; named in the community-chat bundle, see 04 section 10) | `CHAT_ALL_MEMBERS`, DMs |
| 271, 272, 273 | Trade proposal card, trade accepted card, Waiver Wire Report card (author `LM`; community-chat bundle, see 04 section 10) | DMs, `CHAT_ALL_MEMBERS` |

Unread summary (VERIFIED (live)): `GET https://lm-api-reads.fantasy.espn.com/apis/v3/communication/lastReadByMember?view=chat_unreads&platform=chat` also answers on the reads host (same body as on lm-api-communication): `lastReadByGroup` keyed `"{leagueId}.{gameId}.{seasonId}"` with `lastMessageDate`, `unread` and `lastReadByTopic`. It lists every league season the user has chat state in (here 2027 and 2024), so it is both the cheapest unread poll and a secondary league discovery source.

**How the app should use it:** use `chat_conversations` on lm-api-reads to count unread messages and new activity without loading message bodies; use the filtered `/communication/` call with `filterType: ["ACTIVITY_TRANSACTIONS"]` for a recent-activity feed. Treat everything here as private user data (DM contents are included in `kona_league_communication`). Sending messages is out of scope for this document (it is a write on `lm-api-communication`).

---

## 17. Season and game endpoints (no cookies needed)

| Call | Size | Top-level keys | Status |
|---|---|---|---|
| `GET {base}` | 391 B | `abbrev: "FBA"`, `id: 3`, `currentSeasonId: 2027`, `currentSeason{...}`, `name`, `proSportAbbrev: "NBA"`, `proSportName`, `active`, `display`, `displayOrder` | VERIFIED (live) |
| `GET {base}?view=kona_game_state` | 6,803 B | game metadata, but `currentSeason` holds only `{currentScoringPeriod, settings}` (the season `kona_game_state` payload) | VERIFIED (live) |
| `GET {base}/seasons` | 4,119 B | list of 20 seasons (2008 to 2027) `{id, abbrev, name, active, display, displayOrder, gameId, startDate, endDate, currentScoringPeriod{id}}` | VERIFIED (live) |
| `GET {base}/seasons/2027` | 203 B | `{abbrev: "FBA 2027", id: 2027, currentScoringPeriod: {id: 1}, startDate, endDate, ...}` | VERIFIED (live) |
| `GET {base}/seasons/2027?view=kona_game_state` | 6,615 B | `currentScoringPeriod`, `settings{allowLeagueCreation, clientFlags{17 string flags}, draftScheduleSettings, gameNotificationSettings, leagueCreationAddOns[], proScheduleAvailable, statSettings{hasGameStatProjections, showSeasonProjections}, teamAutoPilotSettings, types.teamAutoPilotTypes[]}` | VERIFIED (live, bundle) |
| `GET {base}/seasons/2027?view=proTeamSchedules_wl` | 423,065 B | `display`, `settings{proTeams[31], typeNames{32 enums}, playerOwnershipSettings{firstGameDate, lastGameDate, startDate}, gameNotificationSettings, defaultDraftPosition, ...}` | VERIFIED (live, bundle) |
| `GET {base}/seasons/2027/players?scoringPeriodId=0&view=players_wl` + `{"filterActive": {"value": true}}` | 262,820 B | bare list of 1,095 players `{id, fullName, firstName, lastName, proTeamId, defaultPositionId, eligibleSlots[], droppable, universeId, ownership{percentOwned}}` | VERIFIED (live, bundle) |
| `GET {base}/seasons/2027/segments/0/leaguedefaults/1?view=mSettings` | 3,753 B | default "FBA Rotisserie" league settings; `kona_player_info` also works here without cookies | VERIFIED (live, bundle) |

`proTeams[]`: `{id, abbrev, location, name, byeWeek, universeId, proGamesByScoringPeriod{scoringPeriodId: [game]}}`; game = `{id, date (ms), homeProTeamId, awayProTeamId, scoringPeriodId, startTimeTBD, statsOfficial, validForLocking}`. Id 0 is `FA` with no games. VERIFIED (live)

ESPN pro team ids and abbreviations (VERIFIED (live)); note ESPN's own short forms (`NO`, `NY`, `SA`, `UTAH`, `GS`, `WSH`):

| Id | Abbrev | Id | Abbrev | Id | Abbrev |
|---|---|---|---|---|---|
| 1 | ATL | 11 | IND | 21 | PHX |
| 2 | BOS | 12 | LAC | 22 | POR |
| 3 | NO | 13 | LAL | 23 | SAC |
| 4 | CHI | 14 | MIA | 24 | SA |
| 5 | CLE | 15 | MIL | 25 | OKC |
| 6 | DAL | 16 | MIN | 26 | UTAH |
| 7 | DEN | 17 | BKN | 27 | WSH |
| 8 | DET | 18 | NY | 28 | TOR |
| 9 | GS | 19 | ORL | 29 | MEM |
| 10 | HOU | 20 | PHI | 30 | CHA |

`typeNames` (32 enums) is the authoritative source for string enums: `acquisitionTypes, draftOrderTypes, draftTypes, executionTypes, injuryStatusTypes, inviteTypes, keeperOrderTypes, leagueSubTypes, locktimeTypes, logoTypes, matchupTieRuleTypes, messageTypes (196 names), moveTypes, notificationTypes, periodTypes, playerOwnershipActivityLevels, playerStatusTypes, playoffTierTypes, pollTypes, rankTypes, recordSeedingRuleTypes, restrictionTypes, resultTypes, rosterInjuryStatusTypes, rosterStatusTypes, scoringTypes, topicTypes, tradeBlockStatusTypes, transactionStatusTypes, transactionTeamActionTypes, transactionTypes, winnerTypes`. VERIFIED (live) `messageTypes` is a name list, not indexed by `messageTypeId`.

Gotchas:

- `seasons/{season}.startDate`/`endDate` are the fantasy product window (2026-06-11 to 2028-06-11), not the NBA season. Use `playerOwnershipSettings.firstGameDate`/`lastGameDate` (Tue Oct 20, 2026 and Sun Apr 11, 2027) or the game list. VERIFIED (live)
- `players_wl` with `limit` and no sort fails with `FILTER_LIMIT_MISSING_SORT`. VERIFIED (live)

**How the app should use it:** cache `proTeamSchedules_wl` for a day (it drives "who plays today" and games left this week); cache `seasons/{season}` to learn the current scoring period without auth.

---

## 18. League history

- `GET {base}/leagueHistory/{leagueId}?view=kona_history_standings` returns a **list**, one item per previous season (2023 to 2026 here): `{id, seasonId, scoringPeriodId, draftDetail.drafted, status{finalScoringPeriod, latestScoringPeriod}, settings{name, scheduleSettings.divisions, scoringSettings{scoringType, scoringItems[{statId, points, pointsOverrides}]}}, teams[{id, name, owners, divisionId, logo, logoType, playoffSeed, rankCalculatedFinal, rankFinal, pointsAdjusted, pointsDelta, record.overall{wins, losses, ties, percentage}, valuesByStat}]}`. VERIFIED (live, bundle)
- `GET {base}/leagueHistory/{leagueId}?seasonId=2026&view=mTeam` returns a list with one league object. The web routes requests for older seasons through this path (`leagueHistory/{id}` + `seasonId` param) and unwraps `[0]`. VERIFIED (live, bundle)
- `GET {base}/seasons/2026/segments/0/leagues/{leagueId}?view=...` also worked for 2026 (all views tested, including box scores with real stats). VERIFIED (live) The cutoff after which only `leagueHistory` works is UNVERIFIED.
- Team names change between seasons while `owners` (SWIDs) stay; use the owner id, not the name, to follow a manager across seasons. VERIFIED (live; same team id and owner, different name in 2023 and 2027). Whether team ids can change between seasons is UNVERIFIED.

---

## 19. Recommended call plan for the app

| Need | Call | Cache |
|---|---|---|
| Login check, my team | `GET {L}` (no view), match SWID in `teams[].owners` | session |
| Settings, slots, scoring, matchup map | `view=mSettings` | ETag, daily |
| Today and this week | `view=mStatus` + `view=mMatchupScore` + `{"schedule": {"filterCurrentMatchupPeriod": {"value": true}}}` | ETag, 30 s in live windows |
| My roster for a day | `view=mRoster&forTeamId={me}&scoringPeriodId={day}` with gzip | ETag, 1 to 5 min |
| Opponent roster for a day | same with the opponent's team id | as above |
| Box score for a day | `view=mBoxscore&view=mMatchupScore&scoringPeriodId={day}` + `filterMatchupPeriodIds` | ETag |
| Season schedule (opponents) | `view=mMatchupScoreLite` | daily |
| Standings and playoff odds | `view=mTeam&view=mStandings` | 5 min |
| Free agents / trending | `view=kona_player_info` + players filter (limit at most 50, with sort) | 30 min |
| Incoming trades, recent moves | `view=mTransactions2` + `transactions.filterType` | ETag, 1 to 5 min |
| Unread chat / activity counter | `view=chat_conversations` (on lm-api-reads) | ETag, 1 min |
| NBA games per day | season `view=proTeamSchedules_wl` | daily |

General rules: always send `Accept-Encoding: gzip` and `If-None-Match`; keep under about 2 requests per second; treat any 401 as expired cookies; never trust a 200 to mean the view name was valid (an unknown view returns the default body).

---

## Open questions

1. `mLiveScoring` and `mTopPerformers`: their payload during live games is unknown (both were empty in preseason and for completed 2026 periods). Re-probe on a game night after Oct 20, 2026.
2. `mPositionalRatings` / `mPositionalRatingsStats` returned nothing for FBA in both seasons. Is there a filter or season phase that fills `positionAgainstOpponent`?
3. Chat message types 259 to 294 are named only in the community-chat bundle (04 section 10); only 0, 260, 271, 272 and 273 were seen live, so the payloads of the others are unverified.
4. `totalPointsLive` differs from `totalPoints` on completed 2026 playoff rows (2954 vs 2870). Which one is authoritative after a period closes (bench points, stat corrections)?
5. With `mRoster&scoringPeriodId=N`, the selection rule for `05{gameId}` game stat entries (some carried `scoringPeriodId` N minus 1) needs a live in-season check.
6. Acquisition limit semantics: does `matchupAcquisitionLimit: 1` with `matchupLimitPerScoringPeriod: true` mean one add per day? How do `waiverProcessDays: ["SUNDAY"]` and `waiverProcessHour: 8` relate to the nightly waiver runs seen in `waiverProcessStatus`? Partial answer (VERIFIED (live), 2026 season): not one per day (up to 5 adds per team per day were executed), and waivers ran daily at 07:00 to 09:30 UTC. What the two settings actually control is still open.
7. `X-Fantasy-Role` values for league managers, and `status.isViewable` / `createdAsLeagueType` / `currentLeagueType` codes.
8. Pending trade offers to the user: confirm on a live offer whether they also appear in `mPendingTransactions` (only an accepted-in-review trade was observed there) or only in `mTransactions2`.
9. The weekly period table (week to scoring period ranges) is only available from the web bundle constants. Is there an API view that returns `segments[].periodTypes`, so the app does not need to hardcode it per season?
10. At which season does `seasons/{Y}/segments/0/leagues/{id}` stop working and `leagueHistory` become mandatory?
11. `rosterForMatchupPeriodDelayed` and `isBenchUnlimited: true` (with a bench count of 3) have unclear meaning.

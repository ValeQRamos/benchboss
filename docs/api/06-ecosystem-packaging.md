# 06. Prior art, stack and packaging

Summary (research date 2026-10-15, preseason of season 2027):
1. `cwendt94/espn-api` (v1.0.1, MIT) reads more views than the prototype CLI this project started from (box scores, activity, transactions, player cards, news, draft, message board) but writes nothing; the app keeps its own client and borrows its views, filters and stat maps (all checked live below).
2. Recommended stack: Textual 8.2.x (TUI), Rich (plain CLI output), Typer 0.27.x (subcommands), keyring (secrets), platformdirs (config), Python >= 3.11, shipped with `uv tool install git+https://...` (pipx as the alternative), PyPI and a Homebrew tap later, no npm wrapper.
3. For VS Code Copilot agent mode: `AGENTS.md` as the single source of truth, a short `.github/copilot-instructions.md`, `CLAUDE.md` that imports `@AGENTS.md`, workflows as Agent Skills in `.github/skills/`, an optional `.github/agents/*.agent.md`, a `--json` / `--dry-run` / `--yes` CLI contract, and no prompt files (they only run in the Local harness, which VS Code says will be removed).

Status legend: VERIFIED = seen in a live ESPN response on 2026-10-15, in a file fetched that day (PyPI JSON, official docs, upstream source), or in live records produced by the prototype CLI; the source is cited. UNVERIFIED = memory, third-party claims, or not checked on that date.

File and line references to `espn-api` point to upstream commit `c356d1a` (2026-10-09).

## Quick reference

ESPN endpoints and views that `espn-api` uses (all GET, all on read hosts). `{season}` = 2027, `{leagueId}` = the league id, `fba` = basketball.

| Method | URL / view | Purpose | Auth | Status |
|---|---|---|---|---|
| GET | `lm-api-reads.../games/fba/seasons/{season}/segments/0/leagues/{leagueId}?view=mTeam&view=mRoster&view=mMatchup&view=mSettings&view=mStandings` | League bootstrap (espn-api `get_league`) | espn_s2 for private leagues | VERIFIED (each view returned 200 on 2026-10-15) |
| GET | same URL `?view=mMatchup` | Full season schedule with both rosters per matchup | espn_s2 | VERIFIED (200, 100 matchups) |
| GET | same URL `?view=mMatchupScore&view=mScoreboard&scoringPeriodId={sp}` + header `x-fantasy-filter: {"schedule":{"filterMatchupPeriodIds":{"value":[N]}}}` | Box scores for one matchup period, per day | espn_s2 | VERIFIED (200, 5 matchups for period 1) |
| GET | same URL `?view=mTransactions2&scoringPeriodId={sp}` + filter `{"transactions":{"filterType":{"value":[...]}}}` | Transactions log, pending trade proposals, waiver results | espn_s2 | VERIFIED (200, 171 rows for sp 0) |
| GET | same URL `?view=mDraftDetail` | Draft picks, keepers, auction bids | espn_s2 | VERIFIED (200, 130 picks) |
| GET | same URL `?view=kona_player_info&scoringPeriodId={sp}` + `players` filter with `sortPercOwned` and `sortDraftRanks` | Free agents (espn-api flavour) | espn_s2 | VERIFIED (200) |
| GET | same URL `?view=kona_playercard` + filter `filterIds` + `filterStatsForTopScoringPeriodIds` | Player card: game log, outlook, ranks, ADP, transactions | espn_s2 | VERIFIED (200, 58 KB for one player) |
| GET | `lm-api-reads.../leagues/{leagueId}/communication/?view=kona_league_communication` + `topics` filter | Recent activity (adds, drops, trades, lineup moves) | espn_s2 | VERIFIED (200, 13 topics) |
| GET | `lm-api-reads.../leagues/{leagueId}/communication/?view=kona_league_messageboard` (optional `topicsByType` filter) | All message topics incl. league chat and DMs with `unreadMessageCount` | espn_s2 | VERIFIED (200, 6 topic types) |
| GET | `lm-api-reads.../games/fba/seasons/{season}/players?view=players_wl` + filter `{"filterActive":{"value":true}}` | Global player index (id, name, positions, ownership) | none | VERIFIED (200 without cookies, 1095 players) |
| GET | `lm-api-reads.../games/fba/seasons/{season}?view=proTeamSchedules_wl` | NBA schedule by scoring period | none | VERIFIED (live) |
| GET | `site.api.espn.com/apis/fantasy/v3/games/fba/news/players?playerId={id}` | Player news feed (headline, story, published); one player per call, prefer the v2 path (03) | none | VERIFIED (200 without cookies, 13 items) |
| GET | `lm-api-reads.../leagueHistory/{leagueId}?seasonId={year}` | Past seasons; espn-api also uses it as a 401 fallback | espn_s2 | VERIFIED (live) with a `view` (`kona_history_standings`, or `seasonId=2026&view=mTeam`); returns a list (01, section 18). The fallback logic is from espn-api `requests/espn_requests.py` |
| n/a | Power rankings | Computed client side (football only in espn-api) | n/a | VERIFIED (code read: `football/league.py:391`, `football/utils.py:57-76`) |

Ecosystem decisions (versions from PyPI JSON fetched 2026-10-15, VERIFIED unless noted):

| Area | Pick | Version to pin | Why |
|---|---|---|---|
| TUI | Textual | `textual>=8.2,<9` (8.2.8, 2026-06-30) | Sidebar, DataTable, workers, timers, themes incl. `ansi-dark`/`ansi-light` |
| Plain output | Rich | `rich>=14.2,<16` (15.0.0, 2026-04-12) | Textual itself requires `rich>=14.2.0` |
| Subcommands | Typer | `typer>=0.27,<0.28` (0.27.3, 2026-10-06) | Type hints, completion, Rich help; vendors Click since 0.26.0 |
| Secrets | keyring | `keyring>=25.6,<26` (25.7.0, 2025-11-16) | Keychain, Credential Locker, Secret Service |
| Paths | platformdirs | `platformdirs>=4.3,<5` (4.13.0 needs Python >= 3.11) | Config and cache dirs per OS; Textual already depends on it |
| TLS | certifi | `certifi` (2026.7.22) | python.org macOS builds ship no root CAs |
| Dev | textual-dev 1.8.0, pytest-textual-snapshot 1.1.0 | dev extras | Live CSS reload, screenshots, snapshot tests |
| Install | uv 0.13.1 (2026-10-14) / pipx 1.18.1 (2026-10-15) | user side | `uv tool install git+https://...` |

## 1. Prior art: `cwendt94/espn-api`

Facts (VERIFIED from the upstream source and the GitHub API on 2026-10-15): MIT license, 985 stars, 294 forks, 62 open issues, last push 2026-10-09, PyPI `espn-api` 1.0.1 (2026-10-09), Python >= 3.10, runtime deps pinned tightly: `requests>=2.34.0,<2.35.0`, `urllib3>=2.8.0,<3`, `idna>=3.15,<3.16` (`pyproject.toml`). Sports: nfl `ffl`, nba `fba`, nhl `fhl`, mlb `flb`, wnba `wfba` (`espn_api/requests/constant.py`). It is read only: there is no code path that POSTs to `lm-api-writes` (the only login code is commented out in `espn_requests.py:286-318` because ESPN requires reCAPTCHA).

Recommendation: do not depend on it (its exact pins on `requests` and `idna` would conflict with other dependencies, and it hides raw JSON that writes need). Use it as a map of views and filters, and credit it in the README "Acknowledgements".

### 1.1 Files and what each one does (basketball module)

| File | What it does |
|---|---|
| `espn_api/requests/espn_requests.py` | All HTTP: league endpoint, season endpoint, news endpoint, 401 fallback to `leagueHistory`, 404 on `/communication` mapped to empty topics |
| `espn_api/base_league.py` | Bootstrap (`status.currentMatchupPeriod`, `firstScoringPeriod`, `finalScoringPeriod`, `previousSeasons`), draft, teams, player index, pro schedule, trade back-fill from player cards |
| `espn_api/basketball/league.py` | `standings`, `scoreboard`, `recent_activity`, `transactions`, `free_agents`, `box_scores`, `player_info` |
| `espn_api/basketball/constant.py` | `POSITION_MAP`, `PRO_TEAM_MAP`, `STATS_MAP`, `STAT_ID_MAP`, `ACTIVITY_MAP`, `TRANSACTION_TYPES`, `NINE_CAT_STATS` |
| `espn_api/basketball/player.py` | Parses stat splits, `expectedReturnDate`, `positionalRanking`, news |
| `espn_api/basketball/box_score.py`, `box_player.py` | H2H points and H2H category box scores, per player points breakdown |
| `espn_api/basketball/activity.py`, `transaction.py` | Activity and transaction parsing |
| `espn_api/base_settings.py` | Settings fields (trade deadline, FAAB, waiver hour, tie rules, divisions) |
| `espn_api/utils/trade_fill.py` | Fills empty `TRADE_ACCEPT` rows from player cards, batch size 40 |

### 1.2 League bootstrap (`get_league`)

- Request: `GET {READS}/games/fba/seasons/{season}/segments/0/leagues/{leagueId}?view=mTeam&view=mRoster&view=mMatchup&view=mSettings&view=mStandings` with cookies `espn_s2` and `SWID` (`espn_requests.py:150-154`).
- Response (VERIFIED, live): top level `draftDetail{drafted:bool,inProgress:bool}`, `gameId:int (3)`, `id:int`, `schedule:list[100]`, `scoringPeriodId:int`, `seasonId:int`, `segmentId:int`, `settings:dict`, `status:dict`, `teams:list[10]`. Team keys with mStandings: `abbrev, currentSimulationResults, divisionId, id, logo, name, playoffClinchType, rankCalculatedFinal, record`.
- espn-api derived fields: `status.currentMatchupPeriod`, `status.firstScoringPeriod`, `status.finalScoringPeriod`, `status.previousSeasons` (`base_league.py:53-72`). It maps matchup period to scoring periods from `schedule[].home.pointsByScoringPeriod` keys (`basketball/league.py:53-66`).
- Gotchas: espn-api fetches `players_wl` for the whole league (about 1095 players, 263 KB) on every init just to build a name map. Cache that index for a day instead.
- App use: prefer focused calls (01, section 19) over this bootstrap. Adopt `currentSimulationResults` (playoff odds) and `playoffClinchType` for the standings screen; both appear only with `mStandings` (VERIFIED keys present, values not inspected).

### 1.3 Box scores (`box_scores`)

- Request (VERIFIED live): `GET {league}?view=mMatchupScore&view=mScoreboard&scoringPeriodId={sp}` with header `x-fantasy-filter: {"schedule":{"filterMatchupPeriodIds":{"value":[1]}}}` returned only the 5 matchups of period 1.
- Response per side (VERIFIED, live): `adjustment, cumulativeScore, cumulativeScoreLive{wins,losses,ties,scoreByStat,statBySlot}, eliminationMatchupPeriod, pointsByScoringPeriod{"1":0.0}, rosterForCurrentScoringPeriod{appliedStatTotal, entries[13]}, rosterForMatchupPeriod, rosterForMatchupPeriodDelayed, teamId, tiebreak, totalPoints, totalPointsLive`. Entry keys: `injuryStatus, lineupSlotId, playerId, playerPoolEntry{appliedStatTotal,id,onTeamId,player,status}, status`.
- espn-api logic (`basketball/box_score.py:37-65`): points leagues use `totalPointsLive` and `totalProjectedPointsLive` when summing the whole matchup, else `roster.appliedStatTotal`; per player breakdown comes from `stats[].appliedStats` (falls back to `stats`) keyed by stat id (`box_player.py:41-47`). It marks a game as played 3 hours after tip (`box_player.py:33-37`), which is a heuristic.
- Gotchas: in preseason `totalProjectedPointsLive` is absent and player `stats` lists are empty (VERIFIED). `scoringPeriodId` must match the day you want; espn-api resolves it from `matchup_ids`.
- App use: the "live matchup" screen: per player points today and for the week, with the opponent side. Poll at most every 60 s during games.

### 1.4 Recent activity (`recent_activity`)

- Request (VERIFIED live): `GET {league}/communication/?view=kona_league_communication` on the READ host with filter `{"topics":{"filterType":{"value":["ACTIVITY_TRANSACTIONS"]},"limit":25,"limitPerMessageSet":{"value":25},"offset":0,"sortMessageDate":{"sortPriority":1,"sortAsc":false},"sortFor":{"sortPriority":2,"sortAsc":false},"filterIncludeMessageTypeIds":{"value":[178,180,179,239,181,244,188]}}}` (`basketball/league.py:116-151`).
- Response (VERIFIED): `topics[]` with `author, creationInfo, date, dateEdited, id, isDeleted, isEdited, lastUpdateInfo, messages[], targetId, totalMessageCount, type ("ACTIVITY_TRANSACTIONS")`; message keys `author, creationInfo, date, from, id, isAlternateFormat, isDeleted, isEdited, messageTypeId, targetId (playerId), to, topicId`. Counts today: 188 x24, 244 x6, 180 x1, 181 x1.
- Message type ids (`basketball/constant.py:127-138`): 178 FA added, 180 waiver added, 179 / 181 / 239 dropped, 188 moved (lineup slot, `to` is a slot id), 244 traded (`from` is the team). VERIFIED that 188, 244, 180, 181 occur; their names are VERIFIED in ESPN's bundle (01, section 16; 04, section 9.3).
- App use: "Activity" screen and the alert feed. Read host only, so it is safe for agents.

### 1.5 Message board (`message_board`, football only in espn-api but works for fba)

- Request (VERIFIED live): `GET {league}/communication/?view=kona_league_messageboard` on the READ host. espn-api optionally adds `{"topicsByType":{"<TYPE>":{"sortMessageDate":{"sortPriority":1,"sortAsc":false}}}}` (`espn_requests.py:178-192`).
- Response (VERIFIED): `topicsByType` with keys `CHAT_DIRECT_MESSAGE (4 topics), CHAT_ALL_MEMBERS (1), ACTIVITY_TRANSACTIONS (20), ACTIVITY_STATUS (3), ACTIVITY_SETTINGS (11), CHAT (1)`. DM topics carry `unreadMessageCount`, `viewableBy`, `subject`; messages carry `isUnread`, `messageTypeId` (0 text, 259 sticker, 260 GIF, 271 trade proposal card, 272 trade accepted card, 273 waiver report card; see 04, section 10).
- App use: unread DM and trade alerts can be polled from the READ host, so the alert loop never needs `lm-api-communication`.

### 1.6 Transactions (`transactions`, offers report)

- Request (VERIFIED live): `GET {league}?view=mTransactions2&scoringPeriodId={sp}` with filter `{"transactions":{"filterType":{"value":["FREEAGENT","WAIVER","WAIVER_ERROR","TRADE_ACCEPT","DRAFT","ROSTER","FUTURE_ROSTER","TRADE_PROPOSAL"]}}}`. espn-api's allowed set: `DRAFT, TRADE_ACCEPT, WAIVER, TRADE_VETO, FUTURE_ROSTER, ROSTER, RETRO_ROSTER, TRADE_PROPOSAL, TRADE_UPHOLD, FREEAGENT, TRADE_DECLINE, WAIVER_ERROR, TRADE_ERROR` (`basketball/constant.py:140-154`).
- Response (VERIFIED, sp 0): `transactions[171]` grouped as DRAFT/EXECUTED 130, FUTURE_ROSTER/EXECUTED 21, ROSTER/EXECUTED 10, TRADE_PROPOSAL/CANCELED 3, TRADE_PROPOSAL/PENDING 3, TRADE_ACCEPT (no status) 3, WAIVER/EXECUTED 1. Keys on every row: `bidAmount, executionType, id, isActingAsTeamOwner, isLeagueManager, isPending, items, proposedDate, rating, scoringPeriodId, teamId, type`; sometimes `status, memberId, relatedTransactionId, processDate, expirationDate, teamActions`. Item keys: `fromLineupSlotId, fromTeamId, isKeeper, overallPickNumber, playerId, toLineupSlotId, toTeamId, type`.
- Pending proposals (VERIFIED): `type TRADE_PROPOSAL, status PENDING, expirationDate` set, `teamActions {"<proposingTeamId>": "ACCEPTED"}`, items with `type TRADE` in both directions. A `PENDING` status there does not mean the offer is open (VERIFIED live): the one such proposal to team 3 on 2026-10-15 (from team 10) had been withdrawn by its proposer one minute after it was sent; a `TRADE_PROPOSAL` row with `executionType: CANCEL` points at it through `relatedTransactionId`. `status: PENDING` on the original row is stale and never updated, so it is not an open offer. An alert must resolve each proposal through related rows (see 07, recipe (g)).
- Gotchas: espn-api notes that `TRADE_ACCEPT` rows for other teams' trades come with empty `items`; it back-fills from player cards (`base_league.py:273-317`). In the 2027 preseason every `scoringPeriodId` value (none, 0, 1, 2, 10) returned the same full log, including the draft (VERIFIED live); on the completed 2026 season the view returned only the requested day's rows (and 0 rows for none or 0).
- App use: an `activity --pending` command to list incoming and outgoing proposals with expiry, and waiver results (`WAIVER`, `WAIVER_ERROR`, espn-api `get_league_offers`).

### 1.7 Free agents (espn-api flavour)

- Request (VERIFIED live): the usual free agent `kona_player_info` call, plus `"filterSlotIds":{"value":[]}` and a secondary sort `"sortDraftRanks":{"sortPriority":100,"sortAsc":true,"value":"STANDARD"}` (`basketball/league.py:219-236`). Response `players[]` with `status` FREEAGENT or WAIVERS.
- App use: add the draft rank tiebreaker so players with 0.0 percent owned still sort sensibly in preseason.

### 1.8 Player card (`player_info`)

- Request (VERIFIED live): `GET {league}?view=kona_playercard` with filter `{"players":{"filterIds":{"value":[<ids>]},"filterStatsForTopScoringPeriodIds":{"value":<finalScoringPeriod>,"additionalValue":["00{season}","10{season}"]}}}` (`espn_requests.py:206-231`).
- Response (VERIFIED, one player): wrapper keys `appliedStatTotal, draftAuctionValue, droppedByEliminatedTeam, id, keeperValue, keeperValueFuture, lineupLocked, onTeamId, player, rosterLocked, status, tradeLocked, transactions`; player keys `active, defaultPositionId, draftRanksByRankType{STANDARD,ROTO:{rank,auctionValue,rankType}}, droppable, eligibleSlots, firstName, fullName, id, injured, injuryStatus, invalid, jersey, lastName, lastNewsDate, laterality, ownership{auctionValueAverage, auctionValueAverageChange, averageDraftPosition, averageDraftPositionPercentChange, percentChange, percentOwned, percentStarted}, proTeamId, seasonOutlook (about 500 chars), stance, stats[85], universeId`.
- Stats returned (VERIFIED): 82 per-game splits from last season (`statSourceId 0, statSplitTypeId 5`, `id "05" + NBA game id`, `externalId` = game id, `scoringPeriodId` = day), plus `002026`, `002027`, `102027`. Example (public data): last season average 55.5 fantasy points with this league's scoring, 31.1 PTS, 4.3 REB, 6.6 AST in 68 games and 33.3 MIN.
- Gotchas: about 58 KB per player; espn-api batches 40 ids (`utils/trade_fill.py:1`), batch limit UNVERIFIED. In preseason the `002027` split exists with `appliedTotal 0.0`; treat it as "no data".
- App use: player detail pane (outlook text, ADP, auction value, game log sparkline, recent transactions of that player).

### 1.9 Player index, news, draft, schedule

- `players_wl` (VERIFIED): `GET {READS}/games/fba/seasons/{season}/players?view=players_wl` with `x-fantasy-filter: {"filterActive":{"value":true}}`, works without cookies, returns a JSON list (1095) of `{defaultPositionId, droppable, eligibleSlots, firstName, fullName, id, lastName, ownership, proTeamId, universeId}`. Note the path segment `/players`: the same view on the bare season URL returns `{}` (VERIFIED, 2 bytes). Use: offline name search and fuzzy matching for `add`/`trade`.
- News (VERIFIED; v3 honours only one `playerId` per call, so use the v2 path with repeated `playerId` for a whole roster, see 03): `GET https://site.api.espn.com/apis/fantasy/v3/games/fba/news/players?playerId={id}`, no cookies, returns `news{feed[13], playerBets, resultsCount, resultsLimit, resultsOffset, status, timestamp}`; feed item keys `allowContentReactions, allowSearch, categorized, contentKey, dataSourceIdentifier, description, headline, id, images, isLiveBlog, lastModified, links, nowId, playerId, premium, published, story, type`. Use: injury news in the player pane and in a morning report.
- Draft (VERIFIED): `?view=mDraftDetail` returns `draftDetail{completeDate, drafted, inProgress, picks[130]}`, pick keys `autoDraftTypeId, bidAmount, id, keeper, lineupSlotId, memberId, nominatingTeamId, overallPickNumber, playerId, reservedForKeeper, roundId, roundPickNumber, teamId, tradeLocked`. Use: "draft recap" screen; low priority.
- Pro schedule (VERIFIED, live): `proTeamSchedules_wl` on the season URL. espn-api keys the result by `proTeamId` then scoring period string (`base_league.py:149-178`), the same index as 07, section 1.2.

### 1.10 Stat ids and constants

- Stat split id format (VERIFIED from live `stats[].id` plus `statSourceId`/`statSplitTypeId` fields): `{statSourceId}{statSplitTypeId}{externalId}`. Source 0 = actual, 1 = projection. Split 0 = season, 5 = single game (externalId = NBA game id). espn-api `STAT_ID_MAP` also lists `01` last 7, `02` last 15, `03` last 30 (`basketball/constant.py:119-125`); all three are VERIFIED live (02, section 4.2).
- `STATS_MAP` (`basketball/constant.py:70-117`), ids 0 to 45: 0 PTS, 1 BLK, 2 STL, 3 AST, 4 OREB, 5 DREB, 6 REB, 7 EJ, 8 FF, 9 PF, 10 TF, 11 TO, 12 DQ, 13 FGM, 14 FGA, 15 FTM, 16 FTA, 17 3PM, 18 3PA, 19 FG%, 20 FT%, 21 3PT%, 22 AFG%, 23 FGMI, 24 FTMI, 25 3PMI, 26 APG, 27 BPG, 28 MPG, 29 PPG, 30 RPG, 31 SPG, 32 TOPG, 33 3PG, 34 PPM, 35 A/TO, 36 STR, 37 DD, 38 TD, 39 QD, 40 MIN, 41 GS, 42 GP, 43 TW, 44 FTR, 45 unnamed. VERIFIED for 0, 3, 6, 40, 42 against public box score numbers; the league's scoring items use 0, 1, 2, 3, 6, 11, 13, 14, 15, 16, 17 (VERIFIED in `mSettings.scoringSettings.scoringItems`: PTS +1, BLK +4, STL +4, AST +2, REB +1, TO -2, FGM +2, FGA -1, FTM +1, FTA -1, 3PM +1).
- `POSITION_MAP` matches ESPN's lineup slot table (02, section 9.2) and adds 14 = "" (unused). `PRO_TEAM_MAP` uses PHL, PHO, WAS where ESPN's own API uses PHI, PHX, WSH (labels only; ids identical).
- Power rankings: football only, computed locally as 0.80 x two-step dominance + 0.15 x average score + 0.05 x average margin (`football/league.py:391-409`, `football/utils.py:57-76`). For H2H points basketball we can port it per matchup period.

### 1.11 What each side knows that the other does not

Covered by espn-api, not by the prototype CLI: box scores per day and per matchup (1.3), activity feed (1.4), message board read path (1.5), transactions and pending trades (1.6), player card with game logs, outlook and ADP (1.8), player news (1.9), draft (1.9), stat id map (1.10), power rankings formula (1.10), `leagueHistory` fallback for old seasons.

Covered by the prototype CLI, not by espn-api: every write (`ROSTER`, `FUTURE_ROSTER`, `FREEAGENT`, `WAIVER`, `TRADE_PROPOSAL` on `lm-api-writes`), chat send and DM creation on `lm-api-communication`, the rule that `ROSTER` only works for ESPN's current day (409 otherwise), the C position cap (409), the optimal lineup solver, macOS Chrome cookie import, and the per-day lineup semantics.

## 2. Building the terminal app in 2026

### 2.1 Libraries and versions

Status: VERIFIED (PyPI JSON, 2026-10-15).

| Package | Latest | Released | Python | Notes |
|---|---|---|---|---|
| textual | 8.2.8 | 2026-06-30 | >=3.9,<4 | deps: rich>=14.2.0, platformdirs<5,>=3.6.0, pygments, markdown-it-py[linkify], mdit-py-plugins, typing-extensions |
| rich | 15.0.0 | 2026-04-12 | >=3.9 | |
| typer | 0.27.3 | 2026-10-06 | >=3.10 | deps: shellingham, rich>=13.8.0, annotated-doc, colorama (Windows). "Since version 0.26.0, Typer has vendored Click" (PyPI description) |
| click | 8.5.0 | 2026-08-26 | >=3.10 | only if plain Click is chosen |
| cyclopts | 5.2.0 | 2026-10-06 | >=3.11 | alternative CLI framework, fast moving (5.0.0 on 2026-09-23) |
| keyring | 25.7.0 | 2025-11-16 | >=3.9 | |
| platformdirs | 4.13.0 | 2026-10-11 | >=3.11 | |
| httpx | 0.28.1 | 2024-12-06 | >=3.8 | still 0.x, slow cadence |
| requests | 2.34.2 | 2026-05-14 | >=3.10 | |
| textual-dev | 1.8.0 | 2025-10-11 | >=3.9 | `textual run --dev`, `--screenshot DELAY` |
| pytest-textual-snapshot | 1.1.0 | 2025-01-23 | >=3.8.1 | SVG snapshot tests |

Recommendation: `requires-python = ">=3.11"`; runtime deps `textual>=8.2,<9`, `typer>=0.27,<0.28`, `keyring>=25.6,<26`, `platformdirs>=4.3,<5`, `certifi`; optional extra `browser = ["cryptography"]` for macOS Chrome import. Keep HTTP on the standard library (`urllib.request` plus certifi) and run it in Textual thread workers; no async client is needed at this request volume.

Why Typer over argparse: free shell completion, Rich formatted help, `typer <module> utils docs --name <prog> --output docs/cli.md` generates the Markdown command reference for the README (VERIFIED in `typer/cli.py:278-310`). Pin the minor because Typer is still 0.x.

### 2.2 Textual features the app needs

Status: VERIFIED (Textual v8.2.8 source) unless noted.

- Widgets present in `textual.widgets`: `DataTable, OptionList, ListView, ContentSwitcher, TabbedContent, Tabs, Header, Footer, Sparkline, LoadingIndicator, RichLog, Markdown, Select, Input, Tree, ProgressBar, Digits, Tooltip, KeyPanel, HelpPanel`.
- Sidebar menu: `OptionList` (or `ListView`) docked left plus `ContentSwitcher` for the main pane (pattern; UNVERIFIED as an official recipe).
- `DataTable(zebra_stripes=..., cursor_type=..., fixed_columns=...)`, `add_columns`, `update_cell`, `sort` (`_data_table.py:417, 689-723, 871, 1738, 2592`).
- Live refresh: `set_interval` and `set_timer` on every widget/app (`message_pump.py:378, 418`); background HTTP with `@work(exclusive=True, thread=True)` (`_work_decorator.py:74-86`, parameters `name, group, exit_on_error, exclusive, description, thread`); toasts with `App.notify`.
- Themes (`theme.py:71-475`): `textual-dark`, `textual-light`, `nord`, `gruvbox`, `catppuccin-mocha`, `dracula`, `tokyo-night`, `monokai`, `flexoki`, `catppuccin-latte`, `catppuccin-frappe`, `catppuccin-macchiato`, `solarized-light`, `solarized-dark`, `rose-pine`, `rose-pine-moon`, `rose-pine-dawn`, `atom-one-dark`, `atom-one-light`, `ansi-dark`, `ansi-light`. Custom themes via `Theme(name, primary, secondary, accent, foreground, background, surface, panel, success, warning, error, dark, variables)` and `App.register_theme`, then `self.theme = "<name>"` (Textual design guide). Users switch themes from the command palette; `App.theme_changed_signal` lets us persist the choice (`app.py:805`).
- `ansi-dark` / `ansi-light` set `ansi=True` and use the terminal's own palette (`ansi_default` backgrounds), so the app blends with the VS Code theme; `App(ansi_color=...)` overrides it (`app.py:569-611`). FAQ: Textual normally emits 16.7 million colors and does not use the 16 themable ANSI colors unless that setting is on; transparency effects are lost when it is on.
- Screenshots: `App.save_screenshot()` / `export_screenshot()` (SVG, `app.py:1855-1918`) and `textual run --screenshot DELAY --screenshot-path --screenshot-filename` (textual-dev `cli.py:115-133`).
- Command palette key is configurable: `App.COMMAND_PALETTE_BINDING = "ctrl+p"` by default, plus `COMMAND_PALETTE_DISPLAY` and `ENABLE_COMMAND_PALETTE` (`app.py:427-444`).

### 2.3 VS Code integrated terminal and other terminals

- VS Code dispatches some shortcuts to itself before the terminal sees them: `terminal.integrated.commandsToSkipShell` holds "a hard-coded list of commands that are integral to the VS Code experience"; `terminal.integrated.sendKeybindingsToShell` sends most shortcuts to the shell instead; chords always skip the shell unless `terminal.integrated.allowChords` is disabled (VERIFIED, VS Code "Terminal advanced" docs).
- Consequence: Ctrl+P (Textual's palette) is Quick Open on Windows and Linux VS Code and is probably intercepted (UNVERIFIED); Ctrl+K starts chords on Windows/Linux. Design rule: every action gets a single key binding shown in the `Footer` (r refresh, t theme, / search, q quit, 1..8 for sidebar items), and the palette gets a second binding that is not a VS Code shortcut (for example F2 or `:`). Test with `textual keys` inside the VS Code terminal (VERIFIED tool name, Textual FAQ).
- Cmd and Option on macOS and the Windows key never reach a TUI (VERIFIED, Textual FAQ). Avoid them.
- Unicode: VS Code terminal supports "Unicode version 6 and 11 widths" and "Some emojis comprised of multiple characters may not render correctly" (VERIFIED). Use plain glyphs in tables (a dot for "plays today", text for injury tags), no emoji.
- macOS Terminal.app "is limited to 256 colors" and may render box characters poorly (VERIFIED, Textual FAQ); recommend iTerm2, Ghostty, WezTerm, Kitty or the VS Code terminal in the README.
- Rendering glitches in VS Code have been worked around by `"terminal.integrated.gpuAcceleration": "off"` (UNVERIFIED, user report microsoft/vscode#163936). Put it in the README FAQ.
- Text selection: Textual supports click and drag plus Ctrl+C in most widgets (VERIFIED, FAQ). Also offer `y` to copy the selected row as text via `App.copy_to_clipboard` (`app.py:1770`).

### 2.4 CLI contract that makes the tool agent friendly

These are recommendations (not ESPN facts):
- Every read command supports `--json` (stable keys, ISO dates, ids plus names) and exits 0; human output stays Rich tables.
- Every write command prints a plan and exits with a distinct code (for example 10 "dry run, nothing sent") unless `--yes` is present. Never call `input()` in agent paths: the VS Code agent runs commands in a real pty, so an interactive confirmation prompt would block waiting for keyboard input (a TTY check alone does not prevent this).
- Stable exit codes: 0 ok, 1 error, 2 usage, 3 auth (401), 4 ESPN rejected (409), 10 dry run.
- `doctor` / `auth status` print league name, team, season and whether cookies exist, never their values.
- Honour `NO_COLOR` and `--no-color` (Rich honours `NO_COLOR`, UNVERIFIED for 15.0.0).
- A `--demo` mode that loads bundled fixture JSON with fictional teams, for screenshots, VHS tapes, CI and contributors without an ESPN league.

## 3. Distribution: one command install on macOS with VS Code

| Option | Command | Pros | Cons | Status |
|---|---|---|---|---|
| uv tool from GitHub | `uv tool install git+https://github.com/<owner>/<repo>@v0.1.0` | Isolated env, puts the command on PATH, fast, can pin a tag or commit, `uv tool upgrade <name>`, `uv tool update-shell` fixes PATH, `--python 3.12` selects an interpreter | Needs uv first; git URL installs need `git` (Xcode CLT on macOS, UNVERIFIED) | VERIFIED (uv tools guide) |
| uvx (try without installing) | `uvx --from git+https://github.com/<owner>/<repo> <cmd>` | Zero footprint demo | Re-resolves each run | VERIFIED |
| pipx from GitHub | `pipx install git+https://github.com/<owner>/<repo>` | Familiar to Python users; pipx 1.18 "installs with uv when available and pip otherwise" | Needs pipx (`brew install pipx && pipx ensurepath`) | VERIFIED (pipx docs and PyPI description) |
| PyPI release | `uv tool install <pkg>` / `pipx install <pkg>` | Shortest command, version resolution, badges | Name squatting check, release workflow | recommendation |
| Homebrew tap | `brew install <owner>/tap/<formula>` (repo `<owner>/homebrew-tap`) | Native for Mac users | Formula must list every Python dependency as a `resource`, regenerate with `brew update-python-resources <formula>` on each release; uses `include Language::Python::Virtualenv` and `virtualenv_install_with_resources` | VERIFIED (Homebrew tap and language docs) |
| npm wrapper | `npx <pkg>` that shells to Python | None for this audience | Needs Node plus Python, postinstall scripts, two package managers to debug | rejected |

Bootstrap for a fresh Mac (VERIFIED uv installer commands): `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `brew install uv`), then the `uv tool install git+...` line. Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` or `winget install --id=astral-sh.uv -e`. uv downloads a managed Python when none is suitable (UNVERIFIED, from memory of uv docs).

Recommendation: README "Install" shows uv first, pipx second, both pinned to a release tag; publish to PyPI once the name is settled (trusted publishing from GitHub Actions, UNVERIFIED details); add a Homebrew tap only if users ask. Also ship a `.vscode/tasks.json` task "Open dashboard" that runs the TUI in a terminal panel.

## 4. Cookie storage and login

### 4.1 What ESPN needs

Status: VERIFIED (live, 2026-10-15, status codes only).

- Private league read with no cookies: 401. With `SWID` only: 401. With `espn_s2` only: 200. With both: 200. So reads need only `espn_s2`.
- `SWID` is still required for writes and chat: clients send it as `memberId` in transaction bodies and as `author`/`source` for chat (VERIFIED, bundle and live records; see 04).
- Shapes (VERIFIED on real values without printing them): `SWID` is a 38 character `{GUID}` with braces; `espn_s2` is about 348 characters, URL encoded (contains `%`), charset `[A-Za-z0-9%]`. Validation should accept SWID with or without braces and normalise to braces, and store `espn_s2` exactly as copied.

### 4.2 keyring versus a 0600 file

- keyring backends: macOS Keychain, Freedesktop Secret Service (needs `secretstorage`), KWallet, Windows Credential Locker; API `set_password`, `get_password` (None when missing), `delete_password`; null backend via `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` or `keyring --disable`; insecure backends moved to `keyrings.alt` (VERIFIED, keyring README).
- Caveat (VERIFIED quote): on macOS "Any Python script or application can access secrets created by `keyring`" from the same Python executable without a prompt. On headless Linux Secret Service needs a D-Bus session and an unlocked gnome-keyring.
- Recommendation: keyring first (service = app name, usernames `espn_s2` and `SWID`). If the active backend is the null/fail backend, fall back to `credentials.toml` in `platformdirs.user_config_dir(app)` created with `os.open(..., 0o600)` inside a 0700 directory, and say so on screen. Environment variables `ESPN_S2` / `ESPN_SWID` only for CI and headless use; document that an agent running in the same terminal inherits them.
- Migration: the prototype CLI stores the cookies in the macOS Keychain, accounts `espn_s2` and `SWID`, written by `/usr/bin/security`. keyring's macOS backend should find generic passwords by the same service and account (UNVERIFIED), but macOS may ask once because the item's access list trusts only `security` (UNVERIFIED). Plan: try keyring, and on failure ask the user to run `login` again.
- Windows Credential Locker blob limits were not checked; 348 bytes should fit (UNVERIFIED).

### 4.3 Safe paste flow (recommendation)

1. `login` is human only (AGENTS.md says so). It explains where to copy the values: browser DevTools, Application (Chrome/Edge) or Storage (Firefox/Safari), Cookies, `https://fantasy.espn.com`, rows `espn_s2` and `SWID`.
2. Read values with `getpass` (no echo), or let the user paste a whole `Cookie:` header or a DevTools "Copy as cURL" string and extract the two cookies locally. Never accept them as command arguments (shell history, process list).
3. Validate with one read (`mSettings` + `mTeam`), print league name and team name, then save. Never print, log or include values in errors or `--json`.
4. `logout` deletes them; `auth status` reports presence and last successful check only.

### 4.4 Reading cookies from browsers

- macOS Chrome (VERIFIED, working implementation in the prototype CLI): read `Chrome Safe Storage` from the login Keychain (`security find-generic-password -w -s "Chrome Safe Storage"`, triggers a macOS prompt), derive the key with PBKDF2-SHA1, salt `saltysalt`, 1003 iterations, 16 bytes; AES-128-CBC with IV of 16 spaces; values prefixed `v10`/`v11`; when the Cookies DB `meta.version >= 24` strip a 32 byte hash prefix; open SQLite read only with `immutable=1` so a running Chrome is fine. Same scheme should apply to Brave and Edge with their own "Safe Storage" item and profile folder (UNVERIFIED).
- Windows Chrome: Google added App-Bound Encryption for cookies on Windows in Chrome 127 (2024, "Improving the security of Chrome cookies on Windows", Google Security Blog, 2024-07-30, title and date seen, body not fetched). Cookies prefixed `v20` cannot be decrypted with user-level DPAPI; public bypasses rely on elevation or code injection and are the techniques infostealers use (UNVERIFIED details). Do not attempt it.
- Third-party libraries (VERIFIED PyPI): `browser-cookie3` 0.20.1, last release 2024-12-20, deps `lz4`, `pycryptodomex`, `jeepney` (Linux), `shadowcopy` (Windows); `pycookiecheat` 0.8.0 (2024-11-03) pins `cryptography==43.*` and `keyring==25.*` (conflict risk); `rookiepy` 0.5.6 (2024-11-01, Rust). None released after Chrome's v20 change became widespread; v20 support status UNVERIFIED.
- Firefox stores cookies unencrypted in `cookies.sqlite` and Safari needs Full Disk Access for its binary cookies (both UNVERIFIED).
- Recommendation: keep the macOS Chromium importer as `login --from-browser` behind the `browser` extra; everywhere else guide the paste flow. Treat imported cookies exactly like pasted ones (validate, then store in keyring).

## 5. Files that let AI agents operate the CLI

Context (VERIFIED, VS Code docs fetched as Markdown on 2026-10-15): VS Code now runs chat through "harnesses": Copilot (default, recommended), Local (VS Code built-in), Claude (Anthropic Agent SDK), Codex, and a Cloud target. "Selecting a Claude model in a Copilot harness session still uses the Copilot harness." A user who picks a Claude model in Copilot Chat agent mode is therefore on the Copilot harness, and the Copilot rules below apply.

### 5.1 Who reads what

| File | Copilot harness (VS Code) | Local harness | Claude Code / Claude harness | Others | Status |
|---|---|---|---|---|---|
| `AGENTS.md` (root) | yes, "recommended project instructions" | yes, `chat.useAgentsMdFile` (default true) | Claude Code reads it natively when no `CLAUDE.md` exists (v2.1.277+) | Codex, Cursor, Zed, Gemini CLI, Copilot coding agent, others (agents.md list) | VERIFIED |
| `.github/copilot-instructions.md` | yes, always on | yes, `github.copilot.chat.codeGeneration.useInstructionFiles` (default true) | no | Copilot CLI shares it | VERIFIED |
| `.github/instructions/**/*.instructions.md` | yes, front matter `name`, `description`, `applyTo` (glob) | yes | `.claude/rules/*.md` with `paths` instead | | VERIFIED |
| `CLAUDE.md` | no | yes, `chat.useClaudeMdFile` (default true) | yes; supports `@path` imports, max depth 4 hops | | VERIFIED |
| `.github/skills/<name>/SKILL.md` (also `.claude/skills/`, `.agents/skills/`) | yes, loaded on demand or as `/name` | yes | Claude Code reads `.claude/skills/` (UNVERIFIED for `.github/skills/`) | Copilot CLI, Copilot app, cloud agent, Codex (`.agents/skills`) | VERIFIED for VS Code |
| `.github/agents/*.agent.md` | yes (custom agents, formerly chat modes; rename `.chatmode.md` to `.agent.md`) | yes | `.claude/agents/*.md` Claude sub-agent format also read by VS Code | | VERIFIED |
| `.github/prompts/*.prompt.md` | no: "supported only in Local harness sessions" | yes | no | | VERIFIED |
| `llms.txt` | not read automatically | not read automatically | not read automatically | site convention for docs websites (llmstxt.org) | UNVERIFIED that any of these auto-load it |

Also VERIFIED: VS Code says the Local harness "and the Local agent will be removed in a future release" (`chat.agentSkillsLocations` row of the AI settings reference). So prompt files are a dead end; skills replace them and still appear as slash commands (`user-invocable` defaults to true).

### 5.2 Formats

`AGENTS.md`: plain Markdown, no required fields or front matter; nearest file in the tree wins (VERIFIED, agents.md). Claude Code guidance: keep under about 200 lines (VERIFIED, Claude Code memory docs).

`.github/copilot-instructions.md`: plain Markdown, always on. VS Code tips (VERIFIED): short self-contained statements, include the reason behind each rule, show preferred and avoided examples, focus on non-obvious rules.

`CLAUDE.md` (VERIFIED pattern from Claude Code docs, "Share one file with other coding tools"):

```markdown
@AGENTS.md

## Claude Code
(Claude-specific notes, if any)
```

Prefer the import over a symlink because Windows clones turn committed symlinks into one-line text files unless `core.symlinks` is on (VERIFIED). A committed `CLAUDE.md` also keeps working if a contributor adds a private `CLAUDE.local.md`, which would otherwise stop Claude Code from reading `AGENTS.md` (VERIFIED).

`SKILL.md` front matter (VERIFIED): `name` (required, lowercase letters, digits and hyphens, must equal the folder name, max 64 chars, invalid names fail silently), `description` (required, what and when, max 1024 chars), optional `argument-hint`, `user-invocable` (default true), `disable-model-invocation` (default false), `context: fork` (feature flagged). Reference bundled files with relative Markdown links so the agent loads them.

`.agent.md` front matter (VERIFIED): `description, name, argument-hint, tools, agents, model (string or ordered list), user-invocable, disable-model-invocation, infer (deprecated), target (vscode | github-copilot), mcp-servers, handoffs (label, agent, prompt, send, model), hooks (preview)`. Built-in tool names (VERIFIED tools reference): `execute/runInTerminal`, `execute/getTerminalOutput`, `read/readFile`, `read/terminalLastCommand`, `search` (set), `edit` (set), `web/fetch`, `todos`, `vscode/askQuestions`, `agent/runSubagent`. Model names use the form `Model Name (vendor)`, for example `Claude Sonnet 4.5 (copilot)` in the docs; exact strings for newer models are UNVERIFIED, so omit `model` and let the picker decide.

### 5.3 Terminal approvals for the agent

- `chat.tools.terminal.autoApprove` maps commands or `/regex/` to true (run without asking) or false (always ask); rules are checked per sub-command, `false` wins, object syntax with `matchCommandLine: true` checks the whole line; defaults already require approval for `rm, rmdir, del, kill, curl, wget, eval, chmod, chown, Remove-Item` (VERIFIED, approvals doc and AI settings reference).
- "Terminal auto-approval is a best-effort convenience, not a security boundary", and zsh is parsed with the bash grammar (VERIFIED).
- The setting is declared `restricted: true` in VS Code source (`terminalChatAgentToolsConfiguration.ts:126-127`, VERIFIED), which means workspace values only apply in a trusted workspace (meaning of `restricted` UNVERIFIED).
- Suggested workspace `.vscode/settings.json` (recommendation, adjust the command name):

```jsonc
{
  "chat.tools.terminal.autoApprove": {
    "/^fbb (info|roster|matchup|standings|fa|trending|activity|news|player|schedule|doctor)\\b/": true,
    "/--yes\\b/": false,
    "/^fbb (login|logout)\\b/": false
  }
}
```

### 5.4 Recommended repository layout for agents

```
AGENTS.md                         canonical: what the tool is, commands, safety protocol, JSON examples
CLAUDE.md                         "@AGENTS.md"
.github/copilot-instructions.md   10 to 20 lines: the non-negotiable rules + "Read AGENTS.md"
.github/skills/
  lineup-check/SKILL.md           daily lineup review (read, explain, propose, wait for OK, then --yes)
  waiver-scan/SKILL.md            free agents and trending vs the user's roster, with reasons
  trade-review/SKILL.md           evaluate incoming proposals (activity --pending), never accept alone
  weekly-report/SKILL.md          matchup outlook for the week
.github/agents/fantasy-gm.agent.md   tools: execute/runInTerminal, execute/getTerminalOutput, read, search, todos (no edit)
docs/cli.md                       generated by `typer ... utils docs`
.vscode/settings.json             optional auto-approve rules for read commands
.vscode/tasks.json                "Open dashboard"
```

What `AGENTS.md` must say (recommendation): install and verify (`<cmd> doctor`); that `login` is human only and secrets are never printed or pasted into chat; a table of commands split into READ (safe) and WRITE (needs explicit user approval in chat, run without `--yes` first to show the plan, then rerun with `--yes`); always use `--json` when parsing; date rules (one scoring period per day, matchup weeks end Sunday, compute dates from the system clock); error to action map (exit 3: ask the user to run `login`; exit 4: ESPN rejected, show the message); never edit source files when the task is operating the league. Keep the personal league facts (league id, team id, member names) out of the repo: they belong in the user config file or a gitignored `CLAUDE.local.md` / user-level instructions.

## 6. A top tier README for a terminal app

### 6.1 Three exemplary repos

Status: VERIFIED (READMEs read on 2026-10-15).

1. `tconbeer/harlequin` (6,462 stars, MIT, Python and Textual): PyPI, Python versions and "Runs on Linux | MacOS | Windows" badges; SVG hero exported from the app; install section that recommends `uv tool install harlequin` with the uv installer one-liners for POSIX and PowerShell; "Using Harlequin with Agents or in Scripts" section with a headless companion CLI and `--read-only` / `--timeout` guards. Closest model for us.
2. `jesseduffield/lazygit` (83,199 stars, MIT): elevator pitch, table of contents, feature list where each feature has its own GIF, per platform install matrix, Usage, Configuration, Contributing, FAQ, Alternatives.
3. `charmbracelet/vhs` (21,123 stars, MIT): light and dark logo via `#gh-dark-mode-only` / `#gh-light-mode-only` and `<picture>` with `prefers-color-scheme`, release and build badges, a hero GIF generated from a tape checked into the repo, full command reference. Honourable mention: `sharkdp/bat` for its Troubleshooting, Security vulnerabilities and "Project goals and alternatives" sections.

### 6.2 Recommended section order

1. Name, one line pitch, 3 to 5 badges (CI, Python versions, platforms, license, PyPI once published).
2. Hero: one GIF of the TUI (sidebar, roster, live matchup), light and dark variants via `<picture>`.
3. Disclaimer box: unofficial, not affiliated with ESPN, the API can change, you are responsible for your league's rules.
4. Features table (Screen or command, what it does, read or write).
5. Install (uv, pipx, from source), with the uv bootstrap one-liners.
6. Quick start: `login`, `doctor`, `roster`, `tui`, in 4 commands with expected output.
7. Screenshots (SVG from `save_screenshot`, generated in `--demo` mode).
8. Command reference (generated `docs/cli.md`, summarized as a table in the README).
9. Configuration (config path per OS from platformdirs, env vars, themes, refresh interval).
10. Using with AI agents (VS Code Copilot agent mode, Claude Code): points to `AGENTS.md`, explains the dry run and `--yes` contract and the auto-approve snippet.
11. Security and privacy: where cookies are stored, that they grant account access, never share them in issues, how to log out.
12. FAQ and troubleshooting (401, 409 position cap, 409 non-current day, VS Code keybindings, GPU acceleration, Terminal.app colors).
13. Contributing (dev setup with `uv sync`, tests, snapshot tests, `--demo`), Acknowledgements (espn-api), License, Contact.

### 6.3 Recording with VHS

Status: VERIFIED (VHS README).

- Install: `brew install vhs` (needs `ttyd` and `ffmpeg` on PATH). Render: `vhs demo.tape`. CI: `charmbracelet/vhs-action`. Golden text output (`Output golden.ascii`) doubles as an integration test.
- Commands: `Output demo.gif` (also `.mp4`, `.webm`, frames dir), `Require <program>`, `Set Shell|FontSize|FontFamily|Width|Height|Theme|Padding|TypingSpeed|WindowBar|BorderRadius|Framerate|PlaybackSpeed|LoopOffset|CursorBlink`, `Type "..."`, `Enter`, `Tab`, `Ctrl+<key>`, arrow keys, `Sleep 500ms`, `Wait /regex/` (default timeout 15 s), `Hide` / `Show`, `Screenshot`, `Env KEY "value"`, `Source other.tape`.
- Privacy rule: tapes must run with `Env <APP>_DEMO "1"` (fixtures with fictional teams), never against the real league, so the GIF shows no member names and CI needs no cookies.

Example tape (recommendation):

```
Output docs/media/demo.gif
Require fbb
Set FontSize 18
Set Width 1400
Set Height 800
Set Theme "Catppuccin Mocha"
Env FBB_DEMO "1"
Type "fbb roster"
Enter
Sleep 2s
Type "fbb tui"
Enter
Wait+Screen /Roster/
Sleep 1s
Type "2"
Sleep 2s
Type "q"
```

## Open questions

1. Product and command name: `espn` is generic and uses ESPN's trademark; pick a neutral package and command name (examples above use `fbb` as a placeholder) and add the "not affiliated" disclaimer.
2. Does keyring's macOS backend read Keychain items written by `/usr/bin/security` without a prompt, or should migration force a one-time `login`? Needs a hands-on macOS test (it may raise a Keychain dialog).
3. Exact model strings for the `.agent.md` `model` field (format `Model Name (copilot)`); safer to omit.
4. Skills location: `.github/skills/` (Copilot native) versus `.claude/skills/` (read by both VS Code and Claude Code). Confirm whether Claude Code reads `.github/skills/`.
5. Does `kona_playercard` cap the number of `filterIds` per request (espn-api uses batches of 40)?
6. Live payloads of chat message types other than 0, 260, 271, 272 and 273, and live `teamActions` values other than `ACCEPTED` (`APPROVED`, `VETOED` are known only from the bundle).
7. Is Ctrl+P actually intercepted by VS Code's terminal on macOS (Quick Open is Cmd+P there)? Verify with `textual keys` in the VS Code terminal on macOS and on Windows.
8. Scheduling a daily lineup job cross platform (launchd on macOS, Task Scheduler and systemd timers elsewhere): ship a `schedule install` command or only document it?
9. The prototype dashboard depends on a private rendering module; the public app must replace it with Textual and must not ship that dependency.
10. PyPI name availability and whether to publish there at v0.1 or stay git-only until the API surface settles.

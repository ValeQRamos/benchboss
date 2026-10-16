# ESPN Fantasy Basketball API reference

A field guide to the JSON services behind ESPN Fantasy Basketball (game code `fba`): league views, players and projections, news and injuries, transactions and chat, schedules and live scoring.

> **Unofficial.** ESPN does not document or support these endpoints for third parties. Everything here was observed from the outside and can change without notice. This project is not affiliated with or endorsed by ESPN. Use the API at a polite request rate, only on leagues you belong to, and within your league's rules.

## Contents

| Document | Covers |
|---|---|
| [01. League views](01-league-views.md) | Every `view` of the league endpoint on `lm-api-reads`: settings, teams, rosters, schedule views, standings, transactions, draft, league history, season and game endpoints, request and filter conventions. |
| [02. Players, stats and projections](02-players-projections.md) | `kona_player_info`, `kona_playercard`, Player Rater, the full `x-fantasy-filter` grammar (filters, sorts, paging), the `stats[]` entry format, the stat id map and projections. |
| [03. News, injuries and outlooks](03-news-injuries.md) | Public player news (RotoWire blurb and spin), injury details in the fantasy player object, the public NBA injury report, athlete, scoreboard and team endpoints, and how their ids join. |
| [04. Writes, transactions and communication](04-writes-transactions.md) | Every write the web client can send (lineup, adds, waivers, trades, votes, Quick Lineup), error types, how to detect pending activity, and the chat API. |
| [05. Matchups, schedule and scoring](05-matchup-schedule-scoring.md) | The calendar model (days, weeks, matchups), `schedule[]` fields, live scoring math, NBA schedule feeds, live game state, games per team per week. |
| [06. Prior art, stack and packaging](06-ecosystem-packaging.md) | What the `espn-api` Python package covers, library choices for a terminal app, cookie storage, distribution, and files that let AI coding agents operate the CLI. |
| [07. Feature recipes](07-feature-recipes.md) | The exact calls and the math for each product feature: live dashboard, schedule density, lineup optimizer, roster news, free-agent ranking, trade finder, alerts and first-run setup. |

## About this reference

### How it was built

- **Live read-only requests** made between 2026-10-12 and 2026-10-15 (preseason of the 2027 fantasy season, scoring period 1) against one private 10-team head-to-head points league, plus the completed 2026 season of the same league for in-season shapes.
- **ESPN's own web bundles**, downloaded as text and searched, never executed: the fantasy web app (kona build `7411ee0540f4-1.517`, `main-f2aedb781c45b792f61b.js` plus page bundles) and the league chat app (community-chat `1.0.67`, `chat-7847ae3f.js`).
- **No write was executed** to produce these documents. Write bodies come from the bundle and are cross-checked against the records that earlier writes left in the read API.

### Verification labels

Every claim carries one of these labels.

| Label | Meaning |
|---|---|
| VERIFIED (live) | Seen in a live response. |
| VERIFIED (bundle) | Read in ESPN's own JavaScript. |
| VERIFIED (live record) | The write was not sent for this reference, but a record it produced (by a non-browser client or by another league member) is visible in live read data. |
| UNVERIFIED | Inference, third-party code, memory, or not observable before the season starts. Treat as a hypothesis. |

### Examples and privacy

- Examples come from one private league. Member names, display names, team names, emails and SWIDs are replaced with placeholders (`<SWID>`, `{SWID}`, `"<Team name>"`, `"ABC"`). The league id is written as `{leagueId}`; `12345678` appears where a literal number is needed.
- Fantasy team ids (`1, 2, 3, 6, 10, 11, 13, 14, 15, 16`) are kept because they carry no personal data and show that team ids are not contiguous. Team 3 is the caller's team in examples.
- NBA player names and statistics are public data and are kept as real examples.
- Values tied to the 2027 season (dates, scoring period numbers, build ids) are snapshots. Re-check them each season.

## Base hosts

| Host | Base path | Used for | Auth | Docs |
|---|---|---|---|---|
| `lm-api-reads.fantasy.espn.com` | `/apis/v3/games/fba/...` | Every fantasy read: league views, players, season and NBA schedule, league history. Also answers the communication reads and the chat unread summary. | `espn_s2` for private leagues; game, season, player index and `leaguedefaults` paths are public | [01](01-league-views.md), [02](02-players-projections.md), [05](05-matchup-schedule-scoring.md) |
| `lm-api-writes.fantasy.espn.com` | Same league path | Every POST, PUT and DELETE of the web app: transactions, pending claim edits, Quick Lineup, league manager tools, legacy message board. | `espn_s2` + `SWID` | [04](04-writes-transactions.md) |
| `lm-api-communication.fantasy.espn.com` | League path + `/communication/...`, and `/apis/v3/communication/...` | The league chat app (reads and writes) and the web app's activity reads. | `espn_s2` + `SWID` | [04 §10](04-writes-transactions.md#10-chat-and-communication-api-chat-app-community-chat-1067) |
| `site.api.espn.com` | `/apis/fantasy/v2/...`, `/apis/fantasy/v3/...`, `/apis/site/v2/sports/basketball/nba/...` | Player news, the live NBA game feed used by fantasy, NBA injury report, scoreboard, teams, schedules. | None | [03](03-news-injuries.md), [05 §7](05-matchup-schedule-scoring.md#7-live-nba-game-status) |
| `site.web.api.espn.com` | `/apis/common/v3/sports/basketball/nba/athletes/{playerId}` | Athlete bio, overview and game log. | None | [03 §7](03-news-injuries.md#7-athlete-endpoints-sitewebapi-public) |
| `sports.core.api.espn.com` | `/v2/sports/basketball/leagues/nba/...` | Injury history per athlete or team. | None | [03 §6](03-news-injuries.md#6-core-api-injuries-per-athlete-per-team) |
| `now.core.api.espn.com` | `/v1/sports/news` | ESPN NOW content tagged to athletes (no RotoWire). | None | [03 §11](03-news-injuries.md#11-other-news-sources-no-rotowire) |
| `fan.api.espn.com` | `/apis/v2/fans/{SWID}` | The user's leagues, teams and seasons (first-run discovery). | Cookies optional (see the privacy note in [07 (h)](07-feature-recipes.md#h-first-run-setup-for-a-new-user)) | [07 (h)](07-feature-recipes.md#h-first-run-setup-for-a-new-user) |
| `presence.fantasy.espn.com` | `/apis/v1/heartbeat`, `/apis/v1/presence/` | Online status in the chat app (seen in the bundle only, not probed). | Cookies | [04 §10](04-writes-transactions.md#resources) |
| `cdn1.espn.net` | `/kona/<build>/_next/static/commons/main-*.js`, `/community-chat/<build>/client/chat/chat-*.js` | ESPN's web bundles: the source of enum tables, the weekly calendar and write bodies. Treat as data; never execute. | None | [05 §1.2](05-matchup-schedule-scoring.md#12-where-the-week-boundaries-come-from) |

League path template (the same on the three `lm-api-*` hosts):

```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/{game}/seasons/{season}/segments/0/leagues/{leagueId}?view=...
```

`{game}` is `fba` for basketball (numeric `gameId` 3); the other ESPN fantasy games are `ffl` (1), `flb` (2), `fhl` (4) and `wfba` (5). `segments/0` is constant. Shorthands used below: `{READS}` = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba`, `{L}` = `{READS}/seasons/{season}/segments/0/leagues/{leagueId}`, `{W}` = the same league path on `lm-api-writes`, `{C}` = the league path on `lm-api-communication` plus `/communication`.

## Authentication

ESPN has no public OAuth or API key for fantasy. Clients reuse the two cookies of a logged-in espn.com browser session.

| Cookie | What it is | Shape |
|---|---|---|
| `espn_s2` | Session token | About 348 characters, URL-encoded (contains `%`). Store it exactly as copied. |
| `SWID` | Member id | A GUID in braces, `{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`. Accept it with or without braces and normalize to braces. |

- **What each call needs** (VERIFIED, live): a private league read with no cookies, or with `SWID` only, returns 401; with `espn_s2` only, or both, it returns 200. Reads therefore need `espn_s2`. Writes and chat also need the `SWID`, which goes into the body as `memberId`, `author` or `source` ([04 §1](04-writes-transactions.md#1-request-envelope-shared-by-all-writes)).
- **Expired or wrong cookies** produce HTTP 401 with `details[0].type` = `AUTH_LEAGUE_NOT_VISIBLE` (league reads) or `AUTH_COMMUNICATION_NOT_VISIBLE` (communication host).
- **Public without cookies**: the game and season endpoints, `players_wl`, `proTeamSchedules_wl`, `leaguedefaults`, and every `site`, `site.web`, `sports.core` and `now.core` endpoint. Never send league cookies to hosts that do not need them.
- **No programmatic login.** Users copy the two cookies from their browser (DevTools, Application or Storage, Cookies, `https://fantasy.espn.com`). The `espn-api` package disabled its own login code because of reCAPTCHA. See [06 §4](06-ecosystem-packaging.md#4-cookie-storage-and-login) for a safe paste flow and storage in the OS keychain.
- **"My team"**: `GET {L}` with no view and match the `SWID` against `teams[].owners` (case-insensitive) ([01 §3](01-league-views.md#3-members-and-my-team)).

**Never commit cookies.** They grant access to the ESPN account. Do not print or log them, do not pass them as command-line arguments, do not include them in fixtures, screenshots, issue reports or `--json` output, and keep them out of version control (use the OS keychain, or a `0600` file in the user config directory). Treat the `SWID` as personal data too: every league mate can see it in `members[].id`, and the fan API returns the user's league and team names for a `SWID` even without cookies ([07 (h)](07-feature-recipes.md#h-first-run-setup-for-a-new-user)).

## Conventions

### Requests and responses

- **Views compose.** `view` may be repeated; the response is the union of what each view adds. An unknown view name is silently ignored and returns the default body with HTTP 200, so a typo looks like success ([01 §1.5](01-league-views.md#15-the-envelope-and-unknown-views)).
- **Filters live in a header, not in query parameters.** `x-fantasy-filter` carries one JSON object keyed by the collection it filters: `players`, `schedule`, `transactions` or `communication` (a bare `topics` key is accepted only on the `/communication/` path). Unknown keys inside a collection are ignored silently ([01 §1.2](01-league-views.md#12-filters-x-fantasy-filter), [02 §3](02-players-projections.md#3-the-x-fantasy-filter-grammar)).
- **`limit` requires a sort** with a `sortPriority`, otherwise HTTP 400 `FILTER_LIMIT_MISSING_SORT`. The total match count comes back in `X-Fantasy-Filter-Player-Count` or `X-Fantasy-Filter-Communication-Count`.
- **Ask for gzip and use ETags.** `Accept-Encoding: gzip` shrinks `mRoster` from 771 KB to 149 KB. Responses carry a weak `ETag`; sending it back as `If-None-Match` returns 304 with an empty body ([01 §1.3](01-league-views.md#13-response-headers-worth-reading)).
- **Errors** use `{"messages": [...], "details": [{"type", "message", "shortMessage", "resolution", "metaData"}]}` on the fantasy hosts. Some errors are HTML (malformed URLs) and `site.api.espn.com` may gzip error bodies even when gzip was not requested, so check before parsing JSON.
- **Empty collections are often omitted** rather than sent as `[]` (for example `pendingTransactions`).
- **Timestamps** on the fantasy hosts are epoch milliseconds (UTC). The public site APIs use three different string formats ([03 §7](03-news-injuries.md#7-athlete-endpoints-sitewebapi-public)).
- **Rate.** No limits are documented; about 2 requests per second caused no errors. Cache aggressively (settings daily, the NBA schedule daily, rosters for minutes).
- **Server clock.** `X-Fantasy-Server-Time` gives ESPN's time; use it to decide "today" when the local clock is off.

### Time: scoring periods and matchup periods

| Unit | Meaning | Where it comes from |
|---|---|---|
| `scoringPeriodId` | **One day.** Lineups are set and scored per day. Days start at 03:00 US Eastern (midnight US Pacific). | Bundle constants; `status.firstScoringPeriod` / `finalScoringPeriod` |
| Week (period type 2) | A run of days, Monday to Sunday, except a short first week and a merged All-Star week. | Bundle constants only; no API response returns them ([05 §1.2](05-matchup-schedule-scoring.md#12-where-the-week-boundaries-come-from)) |
| `matchupPeriodId` | **One head-to-head round.** Maps to one or more week ids through `settings.scheduleSettings.matchupPeriods` (values are week ids, not days). | `view=mSettings` |

For the 2027 season (VERIFIED, bundle and live): day 1 is Tue 2026-10-20, day N is 2026-10-20 plus N minus 1 days, day 174 is Sun 2027-04-11, and 175 is the post-season bucket. An NBA game belongs to the scoring period of its US Eastern calendar date (0 mismatches over 1,200 scheduled games); never derive the day from UTC. In the reference league, matchup 1 covers days 1 to 6, matchups 2 to 20 are one week each except matchup 18 (days 119 to 132, the two-week All-Star window), and the playoff rounds 21 and 22 cover two weeks each (days 147 to 160 and 161 to 174). The double week moves between seasons, so never hard-code it. Full tables: [01 §4](01-league-views.md#4-scoring-periods-matchup-periods-and-dates) and [05 §1.4](05-matchup-schedule-scoring.md#14-the-2027-season-calendar).

"Today" comes from `status.latestScoringPeriod` (any league read with `mStatus` or `mSettings`) or, without cookies, from `currentScoringPeriod.id` of `GET {READS}/seasons/{season}`. The top-level `scoringPeriodId` of a league response only echoes the query parameter.

### Stat entries

Player statistics arrive as `player.stats[]` entries ([02 §4](02-players-projections.md#4-decoding-playerstats)).

| Entry `id` | Example | Meaning |
|---|---|---|
| `{statSourceId}{statSplitTypeId}{seasonId}` | `002027` | Actual, full season 2027 |
| | `102027` | ESPN projection, full season 2027 |
| | `012027`, `022027`, `032027` | Actual, last 7, 15, 30 days |
| | `002026` | Actual, previous season |
| `{statSourceId}5{gameId}` | `05401811035` | Actual, one game (`scoringPeriodId` = that day, `externalId` = the NBA game id) |

- `statSourceId`: 0 actual, 1 projected. `statSplitTypeId`: 0 season, 1 last 7 days, 2 last 15, 3 last 30, 4 average (never returned), 5 one game.
- `stats` maps stat ids (as strings) to raw values. On league paths `appliedTotal`, `appliedAverage` and `appliedStats` are already scored with the league's `settings.scoringSettings.scoringItems`.
- `stats == {}` means "no data" (preseason placeholders, games the player missed), not zero points. Match entries by their fields rather than the id string, and sum entries of the same day.

Common stat ids (VERIFIED, bundle). The full map, including derived stats, is in [02 §5](02-players-projections.md#5-nba-statid-map).

| Id | Stat | Id | Stat | Id | Stat |
|---|---|---|---|---|---|
| 0 | PTS | 11 | TO | 19 | FG% |
| 1 | BLK | 13 | FGM | 20 | FT% |
| 2 | STL | 14 | FGA | 21 | 3P% |
| 3 | AST | 15 | FTM | 37 | Double doubles |
| 4 | OREB | 16 | FTA | 38 | Triple doubles |
| 5 | DREB | 17 | 3PM | 40 | MIN |
| 6 | REB | 18 | 3PA | 42 | GP |

### Ids

- Fantasy team ids are small integers but **not contiguous**; always key by id.
- Member ids are SWID strings with braces (`members[].id`, `teams[].owners[]`). Team names change between seasons; owners do not.
- Fantasy player ids are ESPN athlete ids, `proTeamId` is the ESPN site team id, and NBA game ids are site event ids, so joins with the public site APIs are direct ([03 §10](03-news-injuries.md#10-id-spaces)).

## Lookup tables

### Lineup slots (`lineupSlotId`, `eligibleSlots`, `lineupSlotCounts` keys)

VERIFIED (bundle, basketball slot table).

| Id | Abbrev | Name | Eligible positions | Starter |
|---|---|---|---|---|
| 0 | PG | Point Guard | PG | yes |
| 1 | SG | Shooting Guard | SG | yes |
| 2 | SF | Small Forward | SF | yes |
| 3 | PF | Power Forward | PF | yes |
| 4 | C | Center | C | yes |
| 5 | G | Guard | PG, SG | yes |
| 6 | F | Forward | SF, PF | yes |
| 7 | SG/SF | Shooting Guard/Small Forward | SG, SF | yes |
| 8 | G/F | Guard/Forward | PG, SG, SF, PF | yes |
| 9 | PF/C | Power Forward/Center | PF, C | yes |
| 10 | F/C | Forward/Center | SF, PF, C | yes |
| 11 | UTIL | Util | all | yes |
| 12 | BE | Bench | all | no |
| 13 | IR | Injured Reserve | all (requires an injury status) | no |
| 14 | INV | Invalid Player | none | no |
| 15 | ALL | All Players (filter value, not a lineup slot) | all | no |

Day totals count starters only: exclude slots 12 and 13 when summing ([05 §3.4](05-matchup-schedule-scoring.md#34-starters-only)).

### Positions (`player.defaultPositionId`, `rosterSettings.positionLimits` keys)

VERIFIED (bundle position table; live player samples).

| Id | Abbrev | Name |
|---|---|---|
| 1 | PG | Point Guard |
| 2 | SG | Shooting Guard |
| 3 | SF | Small Forward |
| 4 | PF | Power Forward |
| 5 | C | Center |

Ids 0 (`POS0`) and 6 (`BE`) exist in the table but are internal. In `positionLimits`, `-1` means no limit; `{"5": 4}` means at most four players whose default position is C, and ESPN rejects adds and trades that break it.

### Injury status (`player.injuryStatus`)

The API returns the **name**; the numeric id is ESPN's internal numbering. VERIFIED (bundle: ids, `injured` flags, UI abbreviations; live: `ACTIVE`, `DAY_TO_DAY` and `OUT` seen in preseason data).

| Name | Id | UI abbrev | `injured` | Notes |
|---|---|---|---|---|
| `ACTIVE` | 0 | (none) | false | Healthy |
| `PROBABLE` | 1 | P | false | |
| `QUESTIONABLE` | 2 | Q | false | |
| `DOUBTFUL` | 3 | D | false | |
| `OUT` | 4 | O | true | |
| `INJURY_RESERVE` | 5 | IR | true | |
| `DAY_TO_DAY` | 6 | DTD | false | Includes rest days in preseason (`injuryDetails.type` = `Rest`) |
| `BEREAVEMENT` | 15 | B | true | |
| `PATERNITY` | 16 | O | true | |
| `SUSPENSION` | 17 | SSPD | false | |
| `FIFTEEN_DAY_DL`, `SIXTY_DAY_DL`, `SEVEN_DAY_DL`, `TEN_DAY_DL`, `RESERVE_RETIRED` | 10, 11, 13, 14, 18 | IL15, IL60, IL7, IL10, (none) | true except `RESERVE_RETIRED` | Other sports |

- Roster entries carry a different field with the same name, `teams[].roster.entries[].injuryStatus` (`NORMAL`, `FUTURE_FROM_IR`, `FUTURE_TO_IR`). It does not reflect the player's health; always read `playerPoolEntry.player.injuryStatus`.
- Return dates and injury types are only in `player.injuryDetails` under `view=kona_playercard` ([03 §3](03-news-injuries.md#3-fantasy-player-object-injuries-outlook-lastnewsdate-private-league-views)). The public NBA injury report maps `DAY_TO_DAY` to `GTD` and `OUT` to `OUT`, and adds `OFS` (out for season).

### Pro teams (`player.proTeamId`, `proTeamSchedules_wl` teams)

VERIFIED (live `proTeamSchedules_wl` and `site.api.espn.com` team list: identical ids and abbreviations). ESPN uses `NO`, `GS`, `NY`, `SA`, `UTAH` and `WSH`, not `NOP`, `GSW`, `NYK`, `SAS`, `UTA` or `WAS`.

| Id | Abbrev | Team | Id | Abbrev | Team |
|---|---|---|---|---|---|
| 0 | FA | Free agent (no team, no games) | 16 | MIN | Minnesota Timberwolves |
| 1 | ATL | Atlanta Hawks | 17 | BKN | Brooklyn Nets |
| 2 | BOS | Boston Celtics | 18 | NY | New York Knicks |
| 3 | NO | New Orleans Pelicans | 19 | ORL | Orlando Magic |
| 4 | CHI | Chicago Bulls | 20 | PHI | Philadelphia 76ers |
| 5 | CLE | Cleveland Cavaliers | 21 | PHX | Phoenix Suns |
| 6 | DAL | Dallas Mavericks | 22 | POR | Portland Trail Blazers |
| 7 | DEN | Denver Nuggets | 23 | SAC | Sacramento Kings |
| 8 | DET | Detroit Pistons | 24 | SA | San Antonio Spurs |
| 9 | GS | Golden State Warriors | 25 | OKC | Oklahoma City Thunder |
| 10 | HOU | Houston Rockets | 26 | UTAH | Utah Jazz |
| 11 | IND | Indiana Pacers | 27 | WSH | Washington Wizards |
| 12 | LAC | LA Clippers | 28 | TOR | Toronto Raptors |
| 13 | LAL | Los Angeles Lakers | 29 | MEM | Memphis Grizzlies |
| 14 | MIA | Miami Heat | 30 | CHA | Charlotte Hornets |
| 15 | MIL | Milwaukee Bucks | | | |

### Other enums

The authoritative source for string enums is `settings.typeNames` in `GET {READS}/seasons/{season}?view=proTeamSchedules_wl` (32 lists, public; [01 §17](01-league-views.md#17-season-and-game-endpoints-no-cookies-needed)). The ones a client meets most often (VERIFIED, live):

| Enum | Values |
|---|---|
| Player pool status (`status`) | `FREEAGENT`, `ONTEAM`, `WAIVERS` |
| Roster entry status (`entries[].status`) | `NORMAL`, `FUTURE_ADD`, `FUTURE_DROP`, `TRADE_RESERVED` |
| Transaction type | `DRAFT`, `TRADE_ACCEPT`, `WAIVER`, `TRADE_VETO`, `FUTURE_ROSTER`, `ROSTER`, `RETRO_ROSTER`, `TRADE_PROPOSAL`, `TRADE_UPHOLD`, `FREEAGENT`, `TRADE_DECLINE`, `WAIVER_ERROR`, `TRADE_ERROR` |
| Transaction status | `PENDING`, `EXECUTED`, `CANCELED` and 30 `FAILED_*` values ([04 §2](04-writes-transactions.md#2-the-transaction-body)) |
| Lock time | `INDIVIDUAL_GAME`, `FIRSTGAME_SCORINGPERIOD`, `INDIVIDUAL_FIRSTGAME_WEEKLY`, `FIRSTGAME_WEEKLY` |
| Period type | `TOTAL_SEASON`, `SCORING_PERIOD`, `WEEKLY` |
| Matchup winner | `HOME`, `AWAY`, `TIE`, `UNDECIDED` |
| Playoff tier | `NONE`, `WINNERS_BRACKET`, `WINNERS_CONSOLATION_LADDER`, `LOSERS_CONSOLATION_LADDER` |
| Trade block | `NORMAL`, `ON_THE_BLOCK`, `UNTOUCHABLE` |

Communication message type ids (activity and chat cards) are listed in [01 §16](01-league-views.md#16-communication-views-readable-from-lm-api-reads), [04 §9.3](04-writes-transactions.md#93-recent-activity-kona_league_communication) and [04 §10](04-writes-transactions.md#message-types).

## Endpoint index

Every endpoint documented in this folder. Auth "cookies" means `espn_s2` for a private league (send `SWID` as well); "cookies + SWID" means the `SWID` is also required in the body or query.

### League reads (`lm-api-reads`, GET)

| Endpoint | Purpose | Auth | Status | Docs |
|---|---|---|---|---|
| `{L}` (no view) | Members, team ids and owners, league name; cheapest auth check | cookies | VERIFIED (live) | [01 §2](01-league-views.md#2-no-view-default-body) |
| `{L}?view=mStatus` | Current day and matchup, season bounds, waiver run time | cookies | VERIFIED (live, bundle) | [01 §5](01-league-views.md#5-mstatus), [05 §2](05-matchup-schedule-scoring.md#2-league-status-viewmstatus) |
| `{L}?view=mSettings` | Scoring items, roster slots, schedule, acquisition and trade settings | cookies | VERIFIED (live, bundle) | [01 §6](01-league-views.md#6-msettings) |
| `{L}?view=mTeam` | Records, waiver rank, transaction counters, trade block, members, your watch list | cookies | VERIFIED (live, bundle) | [01 §7](01-league-views.md#7-mteam) |
| `{L}?view=mNav` | Light teams and members | cookies | VERIFIED (live, bundle) | [01 §8](01-league-views.md#8-mnav) |
| `{L}?view=mRoster` (`forTeamId`, `rosterForTeamId`, `scoringPeriodId`) | Rosters for a day with full player objects | cookies | VERIFIED (live, bundle) | [01 §9](01-league-views.md#9-mroster) |
| `{L}?view=mMatchupScoreLite` | Whole season schedule, totals only | cookies | VERIFIED (live, bundle) | [01 §10.1](01-league-views.md#101-mmatchupscorelite) |
| `{L}?view=mMatchupScore` | Schedule with live totals and points per day | cookies | VERIFIED (live, bundle) | [01 §10.2](01-league-views.md#102-mmatchupscore), [05 §3](05-matchup-schedule-scoring.md#3-schedule-entry-reference) |
| `{L}?view=mMatchup` | Per-stat matchup scores plus all rosters | cookies | VERIFIED (live, bundle) | [01 §10.3](01-league-views.md#103-mmatchup) |
| `{L}?view=mScoreboard` | Scoreboard with slim rosters and teams | cookies | VERIFIED (live, bundle) | [01 §10.4](01-league-views.md#104-mscoreboard) |
| `{L}?view=mBoxscore` | Day and matchup box scores | cookies | VERIFIED (live, bundle) | [01 §10.5](01-league-views.md#105-mboxscore), [05 §4](05-matchup-schedule-scoring.md#4-views-params-and-filters) |
| `{L}?view=mLiveScoring`, `view=mTopPerformers` | Live markers and top performers | cookies | VERIFIED (live, bundle); in-game payload UNVERIFIED | [01 §10.6](01-league-views.md#106-mlivescoring), [01 §10.7](01-league-views.md#107-mtopperformers) |
| `{L}?view=mProjectedPlayoffMatchups` | `projected` flag per matchup | cookies | VERIFIED (live, bundle) | [01 §10.8](01-league-views.md#108-mprojectedplayoffmatchups) |
| `{L}?view=mStandings` | Standings helpers and playoff odds simulation | cookies | VERIFIED (live, bundle) | [01 §11](01-league-views.md#11-mstandings) |
| `{L}?view=mPendingTransactions` | Pending trades and waiver claims | cookies | VERIFIED (live, bundle) | [01 §12.1](01-league-views.md#121-mpendingtransactions), [04 §9.1](04-writes-transactions.md#91-viewmpendingtransactions-primary-source) |
| `{L}?view=mTransactions2` + `transactions` filter | Transaction log (per day in-season) | cookies | VERIFIED (live, bundle) | [01 §12.2](01-league-views.md#122-mtransactions2), [04 §9.2](04-writes-transactions.md#92-viewmtransactions2-history-with-caveats) |
| `{L}?view=mDraftDetail`, `{L}/draftDetail?view=kona_draft_detail` | Draft picks and settings | cookies | VERIFIED (live, bundle) | [01 §13](01-league-views.md#13-draft-and-keepers) |
| `{L}?view=mKeeperRosters` | Rosters plus keeper strategy | cookies | VERIFIED (live, bundle) | [01 §13](01-league-views.md#13-draft-and-keepers) |
| `{L}?view=mInvited`, `modular`, `mSchedule`, `mPositionalRatings`, `mPositionalRatingsStats` | Invites; the others are recognized but empty for basketball | cookies | VERIFIED (live, bundle) | [01 §14](01-league-views.md#14-other-league-views) |
| `{L}?view=kona_player_info` + `players` filter | Player search, free agents, ownership, stats, projections | cookies | VERIFIED (live, bundle) | [02 §2](02-players-projections.md#2-kona_player_info-league-player-pool), [02 §3](02-players-projections.md#3-the-x-fantasy-filter-grammar) |
| `{L}?view=kona_player_info&view=mStatRatings` + `sortRating` | Player Rater ratings per split | cookies | VERIFIED (live, bundle) | [02 §7](02-players-projections.md#7-mstatratings-player-rater) |
| `{L}?view=kona_playercard` + `filterIds` | Player card: injury details, game log, league transactions | cookies | VERIFIED (live, bundle) | [02 §8](02-players-projections.md#8-kona_playercard), [03 §3](03-news-injuries.md#3-fantasy-player-object-injuries-outlook-lastnewsdate-private-league-views) |
| `{L}?view=kona_playerAvailability` + `filterIds` | Ownership and lock state of one player | cookies | VERIFIED (live, bundle) | [01 §15](01-league-views.md#15-player-views-on-the-league-path) |
| `{L}?view=chat_conversations` | Chat and activity topics with unread counts | cookies | VERIFIED (live) | [01 §16](01-league-views.md#16-communication-views-readable-from-lm-api-reads), [07 (g)](07-feature-recipes.md#g-alerts-trades-sent-to-me-unread-dms-waiver-results) |
| `{L}?view=kona_league_communication`, `view=kona_communication_league_index` | All visible topics with messages | cookies | VERIFIED (live) | [01 §16](01-league-views.md#16-communication-views-readable-from-lm-api-reads) |
| `{L}/communication/?view=kona_league_communication` + `topics` filter | Recent activity feed, paged | cookies | VERIFIED (live, bundle) | [01 §16](01-league-views.md#16-communication-views-readable-from-lm-api-reads), [04 §9.3](04-writes-transactions.md#93-recent-activity-kona_league_communication) |
| `{L}/communication/?view=kona_league_messageboard` | Message board topics by type | cookies | VERIFIED (live, bundle) | [01 §16](01-league-views.md#16-communication-views-readable-from-lm-api-reads), [06 §1.5](06-ecosystem-packaging.md#15-message-board-message_board-football-only-in-espn-api-but-works-for-fba) |
| `{L}/teams/{teamId}/recommendations?view=recommend&recommendationTypeId=LINEUP` | ESPN's suggested lineup for today or a future day | cookies | VERIFIED (live) | [04 §4](04-writes-transactions.md#4-quick-lineup-espn-optimizer) |
| `https://lm-api-reads.fantasy.espn.com/apis/v3/communication/lastReadByMember?view=chat_unreads&platform=chat` | Unread flag per league season; cheapest chat poll | cookies | VERIFIED (live) | [01 §16](01-league-views.md#16-communication-views-readable-from-lm-api-reads), [07 (g)](07-feature-recipes.md#g-alerts-trades-sent-to-me-unread-dms-waiver-results) |

### History, game and season reads (`lm-api-reads`, GET)

| Endpoint | Purpose | Auth | Status | Docs |
|---|---|---|---|---|
| `{READS}/leagueHistory/{leagueId}?view=kona_history_standings` | Final standings of every previous season | cookies | VERIFIED (live, bundle) | [01 §18](01-league-views.md#18-league-history) |
| `{READS}/leagueHistory/{leagueId}?seasonId=Y&view=...`, `{READS}/seasons/Y/segments/0/leagues/{leagueId}?view=...` | Any league view for a past season | cookies | VERIFIED (live, bundle) | [01 §18](01-league-views.md#18-league-history), [05 §4.5](05-matchup-schedule-scoring.md#45-previous-seasons) |
| `{READS}`, `{READS}/seasons` | Game metadata, current season, list of seasons | none | VERIFIED (live) | [01 §17](01-league-views.md#17-season-and-game-endpoints-no-cookies-needed) |
| `{READS}/seasons/{season}` (optional `view=kona_game_state`) | Current scoring period, game flags, stat settings | none | VERIFIED (live, bundle) | [01 §17](01-league-views.md#17-season-and-game-endpoints-no-cookies-needed) |
| `{READS}/seasons/{season}?view=proTeamSchedules_wl` | NBA teams, every game by scoring period, all `typeNames` enums | none | VERIFIED (live, bundle) | [01 §17](01-league-views.md#17-season-and-game-endpoints-no-cookies-needed), [05 §6](05-matchup-schedule-scoring.md#6-nba-schedule-season-endpoint) |
| `{READS}/seasons/{season}?view=proTeamSchedules` | Same games plus scores and game state fields | none | VERIFIED (live) | [05 §6](05-matchup-schedule-scoring.md#6-nba-schedule-season-endpoint) |
| `{READS}/seasons/{season}/players?scoringPeriodId=0&view=players_wl` | Light index of all players, incl. `lastNewsDate` | none | VERIFIED (live, bundle) | [01 §17](01-league-views.md#17-season-and-game-endpoints-no-cookies-needed), [03 §4](03-news-injuries.md#4-public-player-pool-with-lastnewsdate-players_wl) |
| `{READS}/seasons/{season}/players?view=mStatCorrections` + filter | Stat corrections for a day | none | Responds 200; payload shape UNVERIFIED | [02 Quick reference](02-players-projections.md#quick-reference) |
| `{READS}/seasons/{season}/segments/0/leaguedefaults/1?view=...` | Default league template; public player pool with default scoring | none | VERIFIED (live, bundle) | [01 §17](01-league-views.md#17-season-and-game-endpoints-no-cookies-needed) |

### Writes (`lm-api-writes`)

None of these were executed for this reference. Bodies and rules are in [04](04-writes-transactions.md).

| Method | Endpoint | Purpose | Auth | Status | Docs |
|---|---|---|---|---|---|
| POST | `{W}/transactions/` type `ROSTER` / `FUTURE_ROSTER` | Lineup moves today / on a future day; plain drops | cookies + SWID | VERIFIED (bundle + live record) | [04 §3](04-writes-transactions.md#3-lineup-roster-and-future_roster) |
| POST | `{W}/transactions/` type `FREEAGENT` | Add a free agent, optionally with drops | cookies + SWID | VERIFIED (bundle) | [04 §5](04-writes-transactions.md#5-free-agents-freeagent) |
| POST | `{W}/transactions/` type `WAIVER` (`EXECUTE` or `CANCEL`) | Waiver claim with conditional drops; cancel a claim | cookies + SWID | VERIFIED (bundle) | [04 §6.1](04-writes-transactions.md#61-claim), [04 §6.2](04-writes-transactions.md#62-cancel-a-pending-claim) |
| POST | `{W}/teams/{teamId}/pendingTransactions/{txId}` | Change the bid of a pending claim | cookies + SWID | VERIFIED (bundle) | [04 §6.3](04-writes-transactions.md#63-change-the-bid-of-a-pending-claim) |
| POST | `{W}/teams/{teamId}/pendingTransactions` | Reorder pending claims | cookies + SWID | VERIFIED (bundle) | [04 §6.4](04-writes-transactions.md#64-reorder-pending-claims) |
| POST | `{W}/transactions/` type `TRADE_PROPOSAL` (`EXECUTE` or `CANCEL`) | Propose a trade; withdraw your own | cookies + SWID | VERIFIED (bundle + live record) | [04 §7.1](04-writes-transactions.md#71-propose-trade_proposal), [04 §7.2](04-writes-transactions.md#72-cancel-your-own-proposal) |
| POST | `{W}/transactions/` type `TRADE_ACCEPT` | Accept an offer | cookies + SWID | VERIFIED (bundle + live record) | [04 §7.3](04-writes-transactions.md#73-accept-trade_accept) |
| POST | `{W}/transactions/` type `TRADE_DECLINE` | Decline an offer (counter = decline, then a new proposal) | cookies + SWID | VERIFIED (bundle + live record) | [04 §7.4](04-writes-transactions.md#74-decline-and-counter-trade_decline) |
| POST | `{W}/transactions/` type `TRADE_VETO` / `TRADE_UPHOLD` | Member vote, or league manager review | cookies + SWID | VERIFIED (bundle + live record) | [04 §7.5](04-writes-transactions.md#75-votes-trade_veto-and-trade_uphold) |
| POST | `{W}/transactions/` type `DRAFT` | Offline draft entry and keepers (league manager) | league manager cookies | VERIFIED (bundle) | [04 §8](04-writes-transactions.md#8-draft-draft-lm-only) |
| POST | `{W}/teams/{teamId}/recommendations?lineupScoringPeriodId=&recommendationTypeId=LINEUP&restOfWeek=` | Apply ESPN's Quick Lineup | cookies + SWID | VERIFIED (bundle) | [04 §4](04-writes-transactions.md#4-quick-lineup-espn-optimizer) |
| POST | `{W}/teams?scoringPeriodId=0` | Waiver order and counters (league manager) | league manager cookies | VERIFIED (bundle) | [04 §6.6](04-writes-transactions.md#66-league-waiver-order-lm-only) |
| POST | `{W}/teams/{teamId}` body `{"watchList": [...]}` | Replace your watch list (at most 50 players) | cookies + SWID | VERIFIED (bundle) | [04 §13](04-writes-transactions.md#13-watch-list) |
| POST, DELETE | `{W}/communication/topics...` | Legacy message board, polls, league email, reminders | cookies + SWID | VERIFIED (bundle) | [04 §10](04-writes-transactions.md#kona-message-board-writes) |

### Chat (`lm-api-communication`)

The chat app appends `platform=chat` to every URL. Reads also answer on `lm-api-reads` ([01 §16](01-league-views.md#16-communication-views-readable-from-lm-api-reads)).

| Method | Endpoint | Purpose | Auth | Status | Docs |
|---|---|---|---|---|---|
| GET | `{C}/?view=chat_conversations` + `topics` filter | League chat and DM topics with unread counts | cookies | VERIFIED (live, bundle) | [04 §9.4](04-writes-transactions.md#94-chat-unread-counts), [04 §10](04-writes-transactions.md#resources) |
| GET | `{C}/topics/{topicId}?view=chat_conversation` | Messages of one topic, paged | cookies | VERIFIED (live, bundle) | [04 §10](04-writes-transactions.md#resources) |
| GET | `/apis/v3/communication/lastReadByMember?view=chat_unreads` | Unread flags for every league of the user | cookies | VERIFIED (live) | [04 §9.4](04-writes-transactions.md#94-chat-unread-counts) |
| POST | `{C}/topics/{topicId}/messages/?source={SWID}` | Send a message | cookies + SWID | VERIFIED (bundle + live record) | [04 §10](04-writes-transactions.md#resources) |
| POST | `{C}/topics/?source={SWID}` | Create a DM topic with its first message | cookies + SWID | VERIFIED (bundle + live record) | [04 §10](04-writes-transactions.md#resources) |
| POST | `{C}/topics/{topicId}/lastRead` | Mark a topic as read | cookies + SWID | VERIFIED (bundle) | [04 §10](04-writes-transactions.md#resources) |
| PUT, DELETE | `{C}/topics/{topicId}/messages/{messageId}/reactions/{reactionId}` | Add or remove a reaction | cookies + SWID | VERIFIED (bundle) | [04 §10](04-writes-transactions.md#resources) |
| PUT, DELETE | `{C}/topics/{topicId}/mutedBy` | Mute or unmute a topic | cookies + SWID | VERIFIED (bundle) | [04 §10](04-writes-transactions.md#resources) |
| POST | `/apis/v3/feedback` | Abuse report | cookies + SWID | VERIFIED (bundle) | [04 §10](04-writes-transactions.md#resources) |

### Public ESPN APIs (GET, no cookies)

| Endpoint | Purpose | Status | Docs |
|---|---|---|---|
| `https://site.api.espn.com/apis/fantasy/v2/games/fba/news/players?playerId=..&playerId=..` | Player news for many players (RotoWire blurb and spin, ESPN stories, video) | VERIFIED (live, bundle) | [03 §1](03-news-injuries.md#1-fantasy-player-news-v2-the-main-endpoint) |
| `https://site.api.espn.com/apis/fantasy/v3/games/fba/news/players?playerId=` | Player card variant; one player only | VERIFIED (live, bundle) | [03 §2](03-news-injuries.md#2-fantasy-player-news-v3-player-card-variant) |
| `https://site.api.espn.com/apis/fantasy/v2/games/fba/games?dates=YYYYMMDD[-YYYYMMDD]` | Live NBA game state used by fantasy (`pre`, `in`, `post`, `percentComplete`) | VERIFIED (live, bundle) | [05 §7.1](05-matchup-schedule-scoring.md#71-fantasy-games-feed-what-espn-fantasy-itself-uses) |
| `https://site.api.espn.com/apis/fantasy/v2/content?key=espn-en-fba-index` | Editorial modules (not news) | VERIFIED (live, bundle) | [03 §11](03-news-injuries.md#11-other-news-sources-no-rotowire) |
| `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries` | League-wide NBA injury report with return dates | VERIFIED (live) | [03 §5](03-news-injuries.md#5-nba-injury-report-league-wide-public) |
| `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` | Full NBA scoreboard for one Eastern day or a month | VERIFIED (live) | [03 §9](03-news-injuries.md#9-scoreboard-and-team-schedule), [05 §7.2](05-matchup-schedule-scoring.md#72-public-nba-scoreboard-richer-heavier) |
| `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams`, `.../teams/{teamId}/schedule`, `.../teams/{teamId}/roster` | Team list, team schedule, team roster with short injury notes | VERIFIED (live) | [03 §8](03-news-injuries.md#8-team-roster-summary-injuries), [03 §9](03-news-injuries.md#9-scoreboard-and-team-schedule) |
| `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}/injuries` | Returns `{}`; do not use | VERIFIED (live) | [03 §8](03-news-injuries.md#8-team-roster-summary-injuries) |
| `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news` | ESPN NBA articles (no RotoWire) | VERIFIED (live) | [03 §11](03-news-injuries.md#11-other-news-sources-no-rotowire) |
| `https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{playerId}` (+ `/overview`, `/gamelog`) | Athlete bio and injuries, fantasy summary, game log (`/news` is 404) | VERIFIED (live) | [03 §7](03-news-injuries.md#7-athlete-endpoints-sitewebapi-public) |
| `https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{season}/athletes/{playerId}/injuries`, `.../teams/{teamId}/injuries` | Injury history per athlete; team injuries as links | VERIFIED (live) | [03 §6](03-news-injuries.md#6-core-api-injuries-per-athlete-per-team) |
| `https://now.core.api.espn.com/v1/sports/news?athletes={playerId}` | ESPN NOW content tagged to an athlete | VERIFIED (live) | [03 §11](03-news-injuries.md#11-other-news-sources-no-rotowire) |
| `https://fan.api.espn.com/apis/v2/fans/{SWID}?displayHiddenPrefs=true&context=fantasy&useCookieAuth=true&source=fantasyapp-ios&featureFlags=challengeEntries` | The user's fantasy leagues, team ids and seasons (cookies add profile and lineup fields) | VERIFIED (live, bundle) | [07 (h)](07-feature-recipes.md#h-first-run-setup-for-a-new-user) |
| `https://presence.fantasy.espn.com/apis/v1/heartbeat`, `/apis/v1/presence/?memberId=` | Chat online status (cookies; not probed) | VERIFIED (bundle) | [04 §10](04-writes-transactions.md#resources) |

## Recipes

[07. Feature recipes](07-feature-recipes.md) turns the catalog into working features, each with requests, response paths, the computation, gotchas and a live result.

| Recipe | What it builds |
|---|---|
| [Shared building blocks](07-feature-recipes.md#1-shared-building-blocks) | "Today" and the current matchup, the NBA schedule index, per-game player value, the daily lineup solver. |
| [(a) Dashboard](07-feature-recipes.md#a-dashboard-live-score-projected-final-games-left-per-side) | Live score, projected final (as set and optimal) and games left for both sides of the current matchup. |
| [(b) Most and least active players](07-feature-recipes.md#b-most-active-and-least-active-players-this-week) | Games left this week per player for a roster, the opponent, the league or free agents. |
| [(c) Lineup optimization](07-feature-recipes.md#c-lineup-optimization-today-and-the-rest-of-the-week) | Day-by-day lineup plan, `ROSTER` and `FUTURE_ROSTER` moves, cross-checked against ESPN's own suggestion. |
| [(d) Roster news](07-feature-recipes.md#d-player-news-for-my-roster-last-5-days) | Recent news and spin for every rostered player in one public request, joined with injury details. |
| [(e) Free-agent pickups](07-feature-recipes.md#e-free-agent-pickups-ranked-by-points-added-this-week) | Free agents ranked by the points they add this week after the best drop, with pickup timing rules. |
| [(f) Trade finder](07-feature-recipes.md#f-trade-finder-positional-surplus-needs-and-a-fair-value-suggestion) | Positional needs and surplus per team, value over replacement, and trade validity checks (position cap, locks, deadline). |
| [(g) Alerts](07-feature-recipes.md#g-alerts-trades-sent-to-me-unread-dms-waiver-results) | Incoming trade offers, unread DMs and league chat, waiver results, with polling cadence. |
| [(h) First-run setup](07-feature-recipes.md#h-first-run-setup-for-a-new-user) | Discover the user's leagues and team from the cookies, confirm ownership, load settings. |

## Known gaps

These questions could not be answered before the regular season starts (Tue 2026-10-20). Each document ends with its own list of open questions.

- **Per-day projections.** ESPN's web client reads per-game projected stat lines, but none exist in preseason data, and `hasGameStatProjections` is `false` ([02 §10](02-players-projections.md#10-per-day-projections)). Until confirmed in-season, estimate with the season projection per game times scheduled games.
- **Matchup projections.** `totalProjectedPoints` and `winProbability` never appear for basketball; the app computes its own projected final ([05 §8](05-matchup-schedule-scoring.md#8-projections)).
- **Live freshness.** Whether `totalPointsLive` and `pointsByScoringPeriod[today]` update during games, and what `mLiveScoring` and `mTopPerformers` carry then ([05 open questions](05-matchup-schedule-scoring.md#open-questions)).
- **Incoming trade offers.** ESPN's trade review page expects them in `mPendingTransactions`, but no open offer existed during observation; a `PENDING` row in `mTransactions2` can be stale ([04 §9](04-writes-transactions.md#9-reading-pending-activity-alerts-no-writes)).
- **`mTransactions2` in-season.** It returned only the requested day on the completed 2026 season but the full log in the 2027 preseason.
- **Write responses.** The success body of `POST /transactions/` and the exact HTTP status of each rejection type are unverified ([04 open questions](04-writes-transactions.md#open-questions)).
- **NBA Cup dates.** Each team shows 80 of 82 games; the knockout games (Dec 4 to Dec 11) are not in the fantasy schedule yet, so matchups 7 and 8 are provisional ([05 §6.3](05-matchup-schedule-scoring.md#63-gotchas)).

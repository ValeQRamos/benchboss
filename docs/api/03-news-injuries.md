# 03. Player news, injuries and outlooks

ESPN serves fantasy player news (RotoWire blurb plus "spin", ESPN stories, video) from a **public** endpoint that needs no cookies, and it accepts many players per request.
Injury status lives in three places that agree with each other: the private fantasy player object (`injuryStatus`, plus `injuryDetails` only under `view=kona_playercard`), the public NBA injury report, and the public athlete endpoints.
Fantasy player ids, ESPN athlete ids, fantasy pro team ids and fantasy game ids are the same id spaces as the public site APIs, so every join below is a direct id match.

All observations were made on 2026-10-15 (NBA preseason, fantasy season 2027) against live responses. "VERIFIED (live)" means seen in a live response; "VERIFIED (bundle)" means seen in ESPN's own fantasy JS bundle `cdn1.espn.net/kona/7411ee0540f4-1.517/_next/static/commons/main-f2aedb781c45b792f61b.js`. Anything else is marked UNVERIFIED.

Placeholders: `{leagueId}`, `{season}` (2027), `{playerId}`, `{teamId}` (NBA team id 1..30), `{eventId}`.

**Two hosts, same data.** The `site.api.espn.com/apis/...` paths in this file also answer on `site.web.api.espn.com/apis/...`. Compared live on 2026-10-17: the injury report (1,012,614 bytes) and a 42-item news feed for four players were identical apart from the `timestamp` field. From a DigitalOcean server in New York, `site.api.espn.com` answered `403 Access Denied` (an HTML block page) while `site.web.api.espn.com` answered 200 JSON for the news feed, the injury report and the athlete endpoint (VERIFIED live). benchboss asks `site.web.api.espn.com` first for the news feed and falls back to `site.api.espn.com`. The scoreboard, schedule and live-games paths were not tested on the second host.

## Quick reference

| Method | URL / view | Purpose | Auth | Status |
|---|---|---|---|---|
| GET | `site.api.espn.com/apis/fantasy/v2/games/fba/news/players?playerId=..` | Player news feed (RotoWire blurb + spin, ESPN stories, video). Many players per call | None | VERIFIED (live, bundle) |
| GET | `site.api.espn.com/apis/fantasy/v3/games/fba/news/players?playerId=..` | Same feed wrapped in `{news}` plus a betting promo. What the ESPN player card calls. One player only | None | VERIFIED (live, bundle) |
| GET | `lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}?view=mRoster` | `injuryStatus`, `injured`, `lastNewsDate`, `seasonOutlook` per rostered player | Cookies | VERIFIED (live) |
| GET | same league URL `?view=kona_playercard` (alone with filter, or added to `mRoster`) | Adds `injuryDetails` (return date, type, out for season) | Cookies | VERIFIED (live, bundle) |
| GET | same league URL `?view=kona_player_info` | Same player fields as mRoster, no `injuryDetails` | Cookies | VERIFIED (live) |
| GET | `lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/players?view=players_wl` | Public player pool incl. `lastNewsDate` | None | VERIFIED (live) |
| GET | `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries` | League-wide NBA injury report with RotoWire comments and return dates | None | VERIFIED (live) |
| GET | `sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{season}/athletes/{playerId}/injuries` | One athlete's injury history, inline objects | None | VERIFIED (live) |
| GET | `sports.core.api.espn.com/v2/sports/basketball/leagues/nba/teams/{teamId}/injuries` | Team injuries as `$ref` links only | None | VERIFIED (live) |
| GET | `site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{playerId}` | Athlete bio, team, `injuries[]` when injured | None | VERIFIED (live) |
| GET | `.../athletes/{playerId}/overview` | Latest RotoWire item, ESPN fantasy summary, news, next or previous game | None | VERIFIED (live) |
| GET | `.../athletes/{playerId}/gamelog[?season=YYYY]` | Per-game box score lines | None | VERIFIED (live) |
| GET | `.../athletes/{playerId}/news` | Does not exist (404) | None | VERIFIED (live, negative) |
| GET | `site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}/roster` | Team roster with a short `injuries[]` per athlete | None | VERIFIED (live) |
| GET | `site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}/injuries` | Returns `{}`; do not use | None | VERIFIED (live, negative) |
| GET | `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` | Games of one US Eastern day (or a month with `YYYYMM`) | None | VERIFIED (live) |
| GET | `site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}/schedule[?season=&seasontype=]` | One team's schedule | None | VERIFIED (live) |
| GET | `site.api.espn.com/apis/site/v2/sports/basketball/nba/teams` | Team list (id mapping) | None | VERIFIED (live) |
| GET | `site.api.espn.com/apis/site/v2/sports/basketball/nba/news` | ESPN NBA articles (no RotoWire) | None | VERIFIED (live) |
| GET | `now.core.api.espn.com/v1/sports/news?athletes={playerId}` | ESPN NOW content tagged to an athlete (no RotoWire) | None | VERIFIED (live) |
| GET | `site.api.espn.com/apis/fantasy/v2/content?key=espn-en-fba-index` | Editorial module list, not news | None | VERIFIED (live, bundle) |
| GET | league-wide fantasy news (`fantasy/v2/games/fba/news`, `news/players` without `playerId`) | Not available: 404 / 500 | None | VERIFIED (live, negative) |

---

## 1. Fantasy player news, v2 (the main endpoint)

### Request

```
GET https://site.api.espn.com/apis/fantasy/v2/games/fba/news/players
    ?playerId=4594268&playerId=3032976&...   (repeat the key, one per player)
    &days=7                                  (optional)
    &limit=200                               (optional, default 50)
    &offset=0                                (optional)
Headers: Accept: application/json, Accept-Encoding: gzip (recommended), any User-Agent
Body: none
```

Parameters (all VERIFIED live unless noted):

| Param | Behavior |
|---|---|
| `playerId` | Required. Repeat it for several players. A comma list (`4594268,3032976`, raw or `%2C`) returns 400 `{"code":1,"detail":"general error: invalid URI"}`. Unknown numeric id returns 200 with an empty feed. Non-numeric returns the same 400. Missing returns 500 `{"code":1008,"detail":"script error: unexpected exception or error processing script"}` |
| `limit` | Default 50 (`resultsLimit: 50` when omitted). 200, 500 and 1000 were accepted; no maximum observed |
| `offset` | Works: `limit=5&offset=5` returned items 6 to 10 with `resultsOffset: 5` |
| `days` | Restricts to recent items. ESPN's own player card sends `days: 30` (VERIFIED bundle: `initVideo` calls the v3 function with `{days:Fa,playerId:o}`, `const Fa=30` in the same module). See the cutoff rule in Gotchas |
| `dates`, `startDate`, `type` | Ignored (same result as without them) |
| `teamId` | Not supported: 500 code 1008 |

Auth: none. The same request with and without cookies returned identical item ids (VERIFIED live). CORS is open (`access-control-allow-origin: *`).

Batch size: the limit is URL length, not id count. 105 ids (URL 1837 chars) returned 200; 108 ids (1888 chars) returned an HTML Tomcat "HTTP Status 400 Bad Request" page (not JSON). VERIFIED live. Batches of 50 ids (about 900 chars) are safe.

### Response shape

```
{
  timestamp:      string  ISO UTC, server time        "2026-10-15T14:47:55Z"
  status:         string  "success"
  resultsOffset:  int     echo of offset
  resultsLimit:   int     echo of limit (50 by default)
  resultsCount:   int     number of items in THIS page (== len(feed)), not a grand total
  feed: [ item, ... ]     sorted by published, newest first, all requested players merged
}
```

Common item fields (all types):

| Path | Type | Notes |
|---|---|---|
| `id` | int | Content id. Not unique inside one multi-player response (see Gotchas) |
| `nowId` | string | `"23-<id>"` for RotoWire, `"1-<id>"` for ESPN content |
| `contentKey`, `dataSourceIdentifier` | string | Internal keys |
| `type` | string | `Rotowire`, `Media`, `Story` seen live. The ESPN UI also accepts `HeadlineNews` (VERIFIED bundle); not seen in this feed's samples |
| `headline` | string | For RotoWire: the news blurb |
| `description` | string | For RotoWire: always equal to `headline` (346 of 346 items) |
| `published` | string | ISO UTC `"2026-10-15T03:45:02Z"`. Sort key |
| `lastModified` | string | Equal to `published` in all 409 sampled items |
| `categorized` | string | A few seconds to hours after `published` |
| `playerId` | int | The requested player this row belongs to |
| `images` | array | Empty for RotoWire |
| `links` | object | See per type |
| `premium` | bool | false in all samples |
| `allowSearch`, `allowContentReactions`, `isLiveBlog` | bool | |

`type: "Rotowire"` extra field:

| Path | Type | Notes |
|---|---|---|
| `story` | string | The analysis paragraph. ESPN labels it **"Spin: "** in the player card (VERIFIED bundle: `spinText:{id:"player_recent_news_spin",defaultMessage:"Spin: "}`, rendered from `e.story` when `type==="Rotowire"`). Plain text, no HTML |
| `links.mobile.href` | string | Legacy `http://m.espn.go.com/wireless/story?storyId=<id>`. No `links.web` for RotoWire |
| `links.api.self` | object | Empty `{}` |

`type: "Story"` extra fields: `title`, `linkText`, `byline`, `authors[]`, `originallyPosted`, `feedDisplayType`, `root` ("fba"), `section` ("Fantasy"), `related[]`, `story` (article body), `links.web.href` (espn.com article), sometimes `video[]`.

`type: "Media"` extra fields: `eventId` (int, same id space as scoreboard events), `eventIdStr`, `root` ("nba"), `section`, `video[]` (`id`, `headline`, `duration` seconds, `originalPublishDate`, `timeRestrictions`, `geoRestrictions`, ...), `links.web.href` (espn.com video page).

Trimmed real example (RotoWire):

```json
{
  "id": 53450546,
  "nowId": "23-53450546",
  "type": "Rotowire",
  "headline": "Edwards ended with 20 points (5-15 FG, 1-5 3Pt, 9-9 FT), three assists and two steals over 28 minutes in Wednesday's 128-106 preseason loss to the Pistons.",
  "description": "(same as headline)",
  "story": "Edwards had trouble finding the net Wednesday. However, he has been known to have occasional shooting slumps throughout his career, so his performance against Detroit shouldn't be a cause for concern. ...",
  "published": "2026-10-15T03:45:02Z",
  "lastModified": "2026-10-15T03:45:02Z",
  "categorized": "2026-10-15T03:45:10Z",
  "images": [],
  "links": {"api": {"self": {}}, "mobile": {"href": "http://m.espn.go.com/wireless/story?storyId=53450546"}},
  "premium": false,
  "playerId": 4594268
}
```

Volume seen (VERIFIED live, 13-player roster, 2026-10-15):

| Query | Items | Notes |
|---|---|---|
| `days=1` | 10 | |
| `days=7` | 54 | 10 of 13 players had news |
| no `days`, `limit=500` | 409 | 346 Rotowire, 32 Media, 31 Story; oldest 2025-04-25; 1.49 MB uncompressed |

History depth per player is uneven (13 to 46 items; oldest dates from 2025-04 to 2026-06). There is no fixed per-player cap, so treat this as a "recent news" feed, not an archive.

### Gotchas

- **Duplicates across players.** A game highlight tagged to two requested players appears twice with the same `id` and different `playerId` (10 duplicate ids out of 409 in the roster sample). Dedupe by `id` and keep a set of player ids per item.
- **`days` is not a rolling 24 h window.** The observed cutoff matches midnight US Eastern of (today minus N days). At 15:01Z on 2026-10-15 (11:01 EDT), `days=1` kept an item published 2026-10-15T00:09Z (Oct 14, 8:09 pm EDT) and dropped one from 2026-10-13T23:40Z. `days=2` kept a RotoWire item at 2026-10-13T04:00:08Z (00:00 EDT Oct 13) and dropped one at 03:25:37Z (23:25 EDT Oct 12). A Media item with `published` 05:28Z was dropped while its video `originalPublishDate` was 02:30Z (Oct 12 EDT), so Media seems filtered by the video date. The behavior is VERIFIED on these samples; the general rule is inferred.
- **Error bodies are gzip-compressed even when the client did not send `Accept-Encoding`.** Python `urllib` does not decompress them. Check for the magic bytes `1f 8b` before parsing. Success bodies are plain unless you ask for gzip.
- **Ask for gzip.** `days=7` for two players: 105 KB plain vs 16.6 KB gzip.
- `resultsCount` is the page size, so paginate until a page returns fewer than `limit` items.
- Caching: `cache-control: max-age=1` to `max-age=27` on v2 (essentially live). Errors: `max-age=5`.
- RotoWire items have no web link; do not render a "full story" link for them.
- The response carries a `link: <player.news.json#>; rel="describedby"` header, but that schema is not fetchable (404 at both obvious paths).

### How the app should use it

- **Roster news panel:** one request with the 13 roster ids, `days=7` (or `days=30` to match ESPN), `limit=200`, gzip. Dedupe by `id`, group by `playerId`, show RotoWire `headline` as the news and `story` as the spin, and label the source "RotoWire" or "ESPN" the way ESPN does.
- **League or waiver watch:** chunk ids into batches of 50 and merge client side.
- **Polling:** cheap and public. Every 10 to 15 minutes is plenty. Use `lastNewsDate` from the roster call as an extra trigger (section 3), but keep polling, because `lastNewsDate` lags.
- Never send the league cookies to this host; they are not needed.

---

## 2. Fantasy player news, v3 (player card variant)

### Request

```
GET https://site.api.espn.com/apis/fantasy/v3/games/fba/news/players?days=30&playerId=4594268
```

VERIFIED (bundle): the player card modal calls `ae(config, {days: 30, playerId})`, path `"fantasy/v3/games/".concat(e.uri_site_api,"/news/players")`, base `https://site.api.espn.com/apis/`, and reads `o.bets` and `o.news`. A sibling function calls the v2 path with arbitrary params.

### Response shape

```
{
  news: {
    timestamp, status, resultsOffset, resultsLimit, resultsCount,   same as v2
    feed: [ item, ... ],                                              same items as v2
    playerBets: { promotion{...}, seeMoreLink{...}, disclaimers{...} } betting promo text
  }
}
```

The top-level `bets` key the bundle reads was absent (null) in all samples.

### Gotchas

- **Only one player is honored.** `playerId=4594268&playerId=3032976` and the reverse order both returned only player 3032976's items (7 items vs 13 for 4594268 alone). VERIFIED live. Use v2 for multiple players.
- No `playerId` returns 500 `{"code":1020,"detail":"script error: invalid API definition class"}`.
- Cached longer: `max-age=171` to `300`.
- For one player, the `feed` ids were identical to v2 with the same `days`.

### How the app should use it

Do not. v2 returns the same items, supports many players and carries no betting promo.

---

## 3. Fantasy player object: injuries, outlook, lastNewsDate (private league views)

### Request

```
GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}
    ?view=mRoster                         roster players
    ?view=mRoster&view=kona_playercard    roster players + injuryDetails  (+38% bytes)
    ?view=kona_player_info&scoringPeriodId=N   with x-fantasy-filter (any player)
    ?view=kona_playercard&scoringPeriodId=N    with x-fantasy-filter (any player)
Headers: Cookie: espn_s2=..; SWID=..   (private league: 401 without them)
         x-fantasy-filter: {"players":{"filterIds":{"value":[3913176,4594268]}}}
```

Sizes (VERIFIED live, whole league, 130 rostered players): `mRoster` 770 KB, `mRoster&kona_playercard` 1.06 MB.

### Response shape (per player, `teams[].roster.entries[].playerPoolEntry.player` or `players[].player`)

| Path | Type | Notes |
|---|---|---|
| `injuryStatus` | string | Live values seen: `ACTIVE`, `DAY_TO_DAY`, `OUT`. The full enum (02, section 9.3) also has `PROBABLE`, `QUESTIONABLE`, `DOUBTFUL`, `INJURY_RESERVE`, `SUSPENSION` and others; they were not present in preseason data |
| `injured` | bool | true only for the `OUT` player in the sample |
| `injuryDetails` | object or absent | **Only with `view=kona_playercard`.** Present for all 43 non-ACTIVE rostered players |
| `injuryDetails.expectedReturnDate` | [int, int, int] | `[year, month, day]`, month is 1-based: `[2026, 11, 1]` matches the public report's `returnDate: "2026-11-01"` for the same player |
| `injuryDetails.outForSeason` | bool | |
| `injuryDetails.type` | string | `Rest` (28 of 43 in preseason), `Undisclosed`, `Calf`, `Hamstring`, `Achilles`, `Not Injury Related`, ... |
| `lastNewsDate` | int | Epoch ms. `1792035902000` = 2026-10-15T03:45:02Z |
| `seasonOutlook` | string | ESPN's preseason write-up. Present for 110 of 130 rostered players |
| `proGamePlayerDetail` | object | Seen on 5 players: `{"<eventId>": {"lineupOrder": null, "starterStatus": "NOTSTARTING"}}` |

`kona_playercard` also adds `invalid`, `jersey`, `laterality`, `stance` on the player, and `transactions[]` and `appliedStatTotal` on the entry. It has **no news fields** (VERIFIED live). Its `stats[]` include per-game splits with ids like `"05401811047"` (source 0, split 5, ESPN event id 401811047) and `externalId` = the event id.

Trimmed real example (`mRoster&kona_playercard`):

```json
{
  "id": 3913176, "fullName": "Brandon Ingram", "proTeamId": 12,
  "injuryStatus": "OUT", "injured": true,
  "injuryDetails": {"expectedReturnDate": [2026, 11, 1], "outForSeason": false, "type": "Achilles"},
  "lastNewsDate": 1790618463000,
  "seasonOutlook": "Ingram had surgery on his foot/heel during the offseason, ..."
}
```

### Gotchas

- **Roster entry `injuryStatus` is useless.** `teams[].roster.entries[].injuryStatus` was `"NORMAL"` for all 130 entries, including the DAY_TO_DAY and OUT players. Always read `playerPoolEntry.player.injuryStatus`.
- **`lastNewsDate` follows RotoWire only, and it lags.** It equals the `published` time of the newest RotoWire item for 12 of 13 roster players; newer Media or Story items do not move it. For the 13th, a RotoWire item published 14:06:00Z was still not reflected at 15:00:51Z (at least 55 minutes of lag), both in the league view and in the public `players_wl` view.
- **DAY_TO_DAY includes rest days.** In preseason most DTD flags are `type: "Rest"`, and a flag can linger for days (one player was still DTD on Oct 15 for a rest day noted on Oct 12).
- `kona_player_info` with `limit` requires a sort key: without one ESPN returns 400 `FILTER_LIMIT_MISSING_SORT` ("Filter: Limit request must be accompanied by a sort"). VERIFIED live, including for a `filterName` + `filterStatus` + `limit: 10` filter with no sort.
- Responses may carry `x-fantasy-filter-player-count` with the total match count (VERIFIED bundle, read as `p["x-fantasy-filter-player-count"]`).

### How the app should use it

- Fantasy `player.injuryStatus` is the value ESPN fantasy acts on, so it stays the source of truth for lineup decisions.
- Add `view=kona_playercard` to the roster call when the UI needs a return date or wants to tell rest from injury (`injuryDetails.type == "Rest"`).
- Show `seasonOutlook` in the player detail view.
- Use `lastNewsDate` as a cheap "something new" hint: if any roster `lastNewsDate` is newer than the last news fetch, refresh news now. Never treat it as complete.

---

## 4. Public player pool with lastNewsDate (`players_wl`)

```
GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/players?scoringPeriodId=0&view=players_wl
x-fantasy-filter: {"filterIds":{"value":[4433287,3913176]}}      (no "players" wrapper)
```

VERIFIED live without cookies. Returns a bare JSON array of `{id, fullName, firstName, lastName, proTeamId, defaultPositionId, eligibleSlots, droppable, lastNewsDate, ownership{percentOwned}, universeId}`. No `injuryStatus`.

Use: a no-auth way to check `lastNewsDate` for arbitrary players. Same lag as section 3.

---

## 5. NBA injury report (league-wide, public)

### Request

```
GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
Headers: Accept-Encoding: gzip (strongly recommended: 1.5 MB plain, 63 KB gzip)
```

### Response shape

```
{
  timestamp: string, status: "success",
  season: {year: 2027, type: 1, name: "Preseason", displayName: "2026-27"},
  injuries: [                          one entry per team that HAS injuries (29 teams on 2026-10-15)
    { id: "1", displayName: "Atlanta Hawks",
      injuries: [ injury, ... ] }
  ]
}
```

| Path (inside `injury`) | Type | Example / notes |
|---|---|---|
| `id` | string | `"534140"` injury id |
| `status` | string | `"Day-To-Day"` (113) or `"Out"` (22) |
| `date` | string | `"2026-10-12T21:36Z"` (minute precision) |
| `shortComment` | string | The RotoWire blurb (same text as the news `headline`) |
| `longComment` | string | The spin, sometimes lightly edited vs the news `story` |
| `type.name` / `type.abbreviation` | string | `INJURY_STATUS_DAYTODAY` / `DD`, `INJURY_STATUS_OUT` / `O` |
| `details.fantasyStatus.abbreviation` | string | `GTD`, `OUT`, `OFS` (out for season, 2 entries) |
| `details.type`, `.location`, `.detail`, `.side` | string | `"Knee"`, `"Leg"`, `"Tendinitis"`, `"Left"`; `detail` and `side` are optional |
| `details.returnDate` | string | `"2026-10-16"`; present on all 135 entries |
| `source.description` | string | `"basic/manual"` |
| `athlete.displayName`, `.firstName`, `.lastName`, `.shortName` | string | |
| `athlete.position.abbreviation` | string | `"G"` |
| `athlete.team.id` / `.abbreviation` | string | `"1"` / `"ATL"` |
| `athlete.links[].href` | string | `https://www.espn.com/nba/player/_/id/4585618/keshon-gilbert` (the athlete id is only here) |
| `athlete.notes.items[]` | array | `{id, type: "news", date, headline, text, source: "RotoWire", injury.$ref}` |
| `athlete.status.name` | string | `"Active"` |

### Gotchas

- **No `athlete.id` field.** Parse it from `athlete.links[].href` (`/id/(\d+)/`) or from `notes.items[].injury.$ref` (`/athletes/(\d+)/`).
- `$ref` links point to an internal host (`sports.core.api.espn.pvt`); rewrite to `sports.core.api.espn.com` before following.
- Teams without injuries are omitted, not listed as empty.
- **It agrees with fantasy.** For all 130 rostered players: 87 ACTIVE had no entry, 42 DAY_TO_DAY were `GTD`, 1 OUT was `OUT` (VERIFIED live). How fantasy shows `OFS` is UNVERIFIED (probably `OUT` with `outForSeason: true`).

### How the app should use it

This is the best single call for an "injury board": public, one request, gzip-small, with the blurb, the spin, the body part and a return date for every injured NBA player. Join to fantasy players by the parsed athlete id. It also suits a late-afternoon re-check before games, since it needs no cookies.

---

## 6. Core API injuries (per athlete, per team)

```
GET https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{season}/athletes/{playerId}/injuries
GET https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/teams/{teamId}/injuries
```

- Per athlete (VERIFIED live): `{count, pageIndex, pageSize: 25, pageCount, items: [ {$ref, id, longComment, shortComment, status, date, athlete{$ref}, team{$ref}, source, type, details{fantasyStatus, type, location, detail, side, returnDate}} ]}`. Items are inline, not just links. For an injury that started last season, the inner `$ref`s point to `seasons/2026` even when requested under 2027. Cache `max-age=900`.
- Per team (VERIFIED live): `items` hold only `{$ref}` links, so each needs a follow-up call. Cache `max-age=369`.
- An injury item URL under the wrong athlete returns 400 `{"error": ...}`.

Use: the per-athlete call for a player's injury history. Prefer section 5 for current status.

---

## 7. Athlete endpoints (site.web.api, public)

### 7.1 `GET https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{playerId}`

Top-level keys: `athlete`, `season`, `league`, `playerSwitcher`, `quicklinks`, `links`, `ticketsInfo`, `standings`, `videos`.

| Path | Type | Example |
|---|---|---|
| `athlete.id` | string | `"4594268"` (same as the fantasy player id) |
| `athlete.uid` | string | `"s:40~l:46~a:4594268"` |
| `athlete.fullName`, `.jersey`, `.age`, `.displayExperience` | mixed | `"Anthony Edwards"`, `"5"`, `25`, `"7th Season"` |
| `athlete.team.id` / `.abbreviation` | string | `"16"` / `"MIN"` |
| `athlete.status.name` | string | `"Active"` |
| `athlete.statsSummary.statistics[]` | array | last regular season averages with ranks |
| `athlete.injuries[]` | array | **Only present when injured** (absent for healthy players). `{longComment, shortComment, status, date ("2026-09-28T18:01:00.000+00:00"), type, details{fantasyStatus, type, location, detail, side, returnDate ("2026-11-01T00:00:00.000+00:00")}}` |

### 7.2 `GET .../athletes/{playerId}/overview`

Keys: `statistics`, `news[]`, `nextGame`, `gameLog`, `rotowire`, `awards`, `fantasy`.

| Path | Type | Example / notes |
|---|---|---|
| `rotowire.headline`, `.description`, `.story` | string | Newest RotoWire item, same text as the news feed |
| `rotowire.published` | string | `"Wed Oct 14 20:45:02 PDT 2026"` (Java `Date.toString` format, Pacific time) |
| `fantasy.draftRank`, `.positionRank`, `.percentOwned`, `.last7Days` | string | `"8"`, `"5"`, `"99.9"`, `"0.0"` (all strings, ESPN default scoring) |
| `fantasy.projection` | string | Same text as `seasonOutlook` |
| `news[]` | array | ESPN content (`Media`, `Story`, `HeadlineNews`) with `categories[]` (`type: athlete/team/...`, `athleteId`). No RotoWire |
| `nextGame.displayName` | string | Showed `"Previous Game"` the morning after a game; `nextGame.league.events[0]` carries the event (id, date, competitors, status, odds) |

### 7.3 `GET .../athletes/{playerId}/gamelog[?season=YYYY]`

Keys: `filters`, `labels[]` (`MIN, FG, FG%, 3PT, 3P%, FT, FT%, REB, AST, BLK, STL, PF, TO, PTS`), `names[]`, `displayNames[]`, `events{eventId: {gameDate, atVs, opponent, score, gameResult, homeTeamId, awayTeamId, eventNote, ...}}`, `seasonTypes[{displayName, categories[{displayName, events[{eventId, stats: [string, ...]}]}]}]`, `glossary`.

- Default season is the last completed one (2026 on 2026-10-15). `?season=2027` returned the 4 preseason games so far.
- `stats[]` are strings aligned with `labels`; made-attempted pairs look like `"9-26"`.

### 7.4 `GET .../athletes/{playerId}/news`

404 `{"code": 404}`. Use section 1 instead.

### Gotchas

- Three different date formats across these endpoints (ISO with `Z`, ISO with `.000+00:00`, and Java `Date.toString` with a US time zone). Parse each explicitly.
- Payloads are large (overview 249 KB, gamelog 728 KB plain); request gzip.

### How the app should use it

Player detail screen: `athlete` for the header and `injuries[]`, `overview.fantasy` and `overview.rotowire` for a compact summary, `gamelog?season={season}` for recent games. Section 1 stays the news source.

---

## 8. Team roster (summary injuries)

`GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}/roster` (VERIFIED live). Keys: `athletes[]`, `coach`, `season`, `status`, `team`, `timestamp`. Each athlete has `id` (string) and, when injured, `injuries: [{"status": "Out", "date": "2026-09-28T18:01Z"}]` (status and date only).

`.../teams/{teamId}/injuries` on the same host returned `{}` (VERIFIED live). Do not use it.

---

## 9. Scoreboard and team schedule

### Scoreboard

```
GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261020
GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=202610&limit=300
```

- `dates=YYYYMMDD` is a **US Eastern calendar day**: `dates=20261020` included OKC @ SA at `2026-10-21T01:30Z` (9:30 pm EDT Oct 20). VERIFIED live.
- `dates=YYYYMM` returns the whole month (155 events for October, 2026-10-03 to 2026-11-01 UTC).
- Range form `dates=20261020-20261025` (with or without `limit`) returned `{"code":400,"message":"Failed to get events endpoint."}` today. VERIFIED live.
- No `dates`: the "current" day. At 15:00Z on Oct 15 it still returned `day.date: "2026-10-14"`.

Event shape: `id` (string, `"401909090"`), `date` (ISO Z), `name`, `shortName` (`"OKC @ SA"`), `season`, `status.type{name: STATUS_SCHEDULED, state: pre|in|post, completed, detail, shortDetail: "10/20 - 9:30 PM EDT"}`, `competitions[0]{competitors[]{homeAway, team{id, abbreviation}, score, records[]}, odds[] (DraftKings: details, spread, overUnder), broadcasts[], venue, ...}`.

### Team schedule

```
GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}/schedule
GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{teamId}/schedule?season=2027&seasontype=2
```

- Default: the current season type (preseason now: 6 events).
- `season=2027&seasontype=2`: regular season, 80 events for MIN from 2026-10-21T23:30Z to 2027-04-12T00:30Z.
- Keys: `events[]`, `requestedSeason`, `season`, `status`, `team{id, abbreviation, displayName, recordSummary: "3-2", standingSummary}`, `timestamp`. Event: `id`, `date`, `name`, `shortName`, `seasonType`, `timeValid`, `competitions[0]{competitors[]{homeAway, team}, status, broadcasts[], venue, ...}`.

### How the app should use it

The fantasy view `proTeamSchedules_wl` already gives game days per scoring period. Use the scoreboard for live state, tip times, TV and scores; it joins directly on event id and team id (section 10).

---

## 10. Id spaces

Status: all rows VERIFIED (live).

| Fantasy | Public site APIs | Evidence |
|---|---|---|
| player `id` | athlete `id` | 4594268 Anthony Edwards, 3032976 Rudy Gobert, 4433621 Jalen Duren, 4869342 Dyson Daniels and 3913176 Brandon Ingram resolve to the same people on `athletes/{id}`; injury report ids match fantasy ids for all 43 injured rostered players |
| `proTeamId` 1..30 | team `id` 1..30 | Same numbers and the same abbreviations on both sides (`NO`, `GS`, `NY`, `SA`, `UTAH`, `WSH`; ESPN does not use `NOP`, `GSW`, `NYK`, `SAS`, `UTA`, `WAS`) |
| `proTeamSchedules_wl` game `id` | scoreboard / schedule event `id` | MIN at MIA: fantasy `id 401909091`, `scoringPeriodId 2`, `date 1792625400000` = site event `401909091` at `2026-10-21T23:30Z` |
| `stats[].externalId` | event `id` | `"401811047"` |
| news `Media.eventId` | event `id` | `401914125` DET at MIN |

---

## 11. Other news sources (no RotoWire)

- `GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=N` returns `{header: "NBA News", link, articles[]}` with ESPN `Story`, `Media` and `HeadlineNews`. `team={teamId}` changes the result; `player=` is ignored (byte-identical to the unfiltered response). VERIFIED live.
- `GET https://now.core.api.espn.com/v1/sports/news?...` (the ESPN NOW API behind `nowId`): public, `cache-control: no-store`, returns `{resultsCount, resultsLimit, resultsOffset, headlines[], breakingNews[], timestamp, status}`. `athletes={playerId}` filters correctly (10 of 10 items tagged with that athlete); `sport=basketball` narrows to basketball (NBA, WNBA, NCAA mixed); `league=nba`, `leagues=nba`, `type=Rotowire` and `contentorigin=rotowire` are ignored. Only `Story` and `HeadlineNews` were seen, never RotoWire. About 62 KB per item (621 KB for 10). VERIFIED live.
- `GET https://site.api.espn.com/apis/fantasy/v2/content?key=espn-en-fba-index`: `{items: [{id, headline: "Collection", type: "Module", fullURL, lastPublishedDate, ...}]}`, editorial modules for the fantasy front page. The bundle calls this path with keys like `espn-en-flb-index`. Not useful for player news.
- `nba.fba.news` in the bundle is a notification topic name in a config map (`{chat: "fantasy-chat", game: "nba.fba", news: "nba.fba.news"}`), not an HTTP path.

### League-wide fantasy news feed

Not found. `fantasy/v2/games/fba/news` is 404, `news/players` without `playerId` is 500, and v3 without `playerId` is 500. The NOW API and the NBA news endpoint carry ESPN content but no RotoWire items. Recommended substitute: section 1 in batches of 50 ids over the players you care about (rostered players plus top free agents), plus section 5 for every injured player in the NBA.

---

## Open questions

1. Exact `days` cutoff rule. Observations fit "midnight US Eastern of today minus N", with Media filtered by the video `originalPublishDate`. Needs samples taken just before and after midnight ET.
2. Which player v3 picks when several `playerId` values are sent. Both orders returned the lower id; it could be "lowest id" or "first after sorting".
3. How long `lastNewsDate` lags behind the feed. Observed at least 55 minutes; recheck later in the day.
4. History retention of the news feed: 13 to 46 items per player with oldest dates from 2025-04 to 2026-06. No rule found.
5. Regular season injury values: does fantasy `injuryStatus` use `QUESTIONABLE`, `PROBABLE`, `DOUBTFUL`, `SUSPENSION` in the NBA game, and how does site `OFS` map in fantasy? Only `ACTIVE`, `DAY_TO_DAY` and `OUT` exist in preseason data.
6. Whether the scoreboard date range form (`YYYYMMDD-YYYYMMDD`) is permanently broken or failed transiently on 2026-10-15.
7. The MIN regular season schedule lists 80 events instead of 82. Possibly unscheduled NBA Cup games (UNVERIFIED).
8. Rate limits on `site.api.espn.com`, `site.web.api.espn.com` and `now.core.api.espn.com`: none hit at about 2 requests per second, but no documented limit exists.
9. Whether `HeadlineNews` items ever appear in the fantasy news feed (the ESPN UI handles them; none seen in 409 roster items).

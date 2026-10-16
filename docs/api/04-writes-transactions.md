# 04. Write operations, transactions and league communication

Every write the ESPN web client can send for a Fantasy Basketball (`fba`) league, reconstructed from ESPN's own JavaScript bundles and cross-checked against live read-only responses; none of these writes was executed for this document.
All roster, lineup, waiver, trade and draft actions go through one endpoint (`POST .../transactions/`) with a typed body; a handful of side endpoints edit pending claims, waiver order and the Quick Lineup optimizer.
The second half covers how to detect incoming trades and claims without writing anything (`mPendingTransactions`, `mTransactions2`, `kona_league_communication`, chat unread counts) and documents the chat API, including the type 271 trade card.

## Sources and labels

| Label | Meaning |
|---|---|
| VERIFIED (bundle) | Read in ESPN's own bundle: kona web app build `7411ee0540f4-1.517` (`main-f2aedb781c45b792f61b.js` plus page bundles `team`, `team/trade`, `tradereview`, `rosterfix`, `recentactivity`, `league/waiverreport`, `league/waiverorder`, `league/transactioncounter`), or the community chat app build `927dc831b4be-1.0.67` (`chat-7847ae3f.js`). |
| VERIFIED (live) | Seen in a live GET response for the reference league, season 2027, on 2026-10-14 or 2026-10-15. |
| VERIFIED (live record) | The write itself was not executed for this document, but a record it produced (for example a transaction sent earlier by a non-browser client or by another league member) is visible in live read data. |
| UNVERIFIED | Inferred, seen in earlier client runs that were not repeated here, or general knowledge. Treat as a hypothesis. |

Bundles were fetched as data and searched as text; they were never executed.

## Quick reference

| Method | URL / view | Purpose | Auth | Status |
|---|---|---|---|---|
| POST | `{WRITES}/transactions/` type `ROSTER` | Lineup moves and plain drops for the current scoring period | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{WRITES}/transactions/` type `FUTURE_ROSTER` | Lineup moves for a future scoring period | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{WRITES}/transactions/` type `FREEAGENT` | Add a free agent (optionally with drops) | espn_s2 + SWID | VERIFIED (bundle) |
| POST | `{WRITES}/transactions/` type `WAIVER` | Waiver claim, with conditional drops and `bidAmount` | espn_s2 + SWID | VERIFIED (bundle) |
| POST | `{WRITES}/transactions/` type `WAIVER`, `executionType: CANCEL` | Cancel a pending waiver claim | espn_s2 + SWID | VERIFIED (bundle) |
| POST | `{WRITES}/teams/{teamId}/pendingTransactions/{txId}` | Change the bid of a pending claim | espn_s2 + SWID | VERIFIED (bundle) |
| POST | `{WRITES}/teams/{teamId}/pendingTransactions` | Reorder pending claims (`subOrder`) | espn_s2 + SWID | VERIFIED (bundle) |
| POST | `{WRITES}/transactions/` type `TRADE_PROPOSAL` | Propose a trade (players, picks, FAAB, drops) | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{WRITES}/transactions/` type `TRADE_PROPOSAL`, `executionType: CANCEL` | Withdraw your own proposal | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{WRITES}/transactions/` type `TRADE_ACCEPT` | Accept an offer | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{WRITES}/transactions/` type `TRADE_DECLINE` | Decline (with comment and "dealbreakers"); counter = decline then new proposal | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{WRITES}/transactions/` type `TRADE_VETO` / `TRADE_UPHOLD` | Member veto vote, or LM veto/approve | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{WRITES}/transactions/` type `DRAFT` | LM offline draft entry, keepers (`DRAFT`/`UNDRAFT` items) | LM cookies | VERIFIED (bundle) |
| POST | `{WRITES}/teams/{teamId}/recommendations?lineupScoringPeriodId=&recommendationTypeId=LINEUP&restOfWeek=` | ESPN "Quick Lineup" (server sets the optimal lineup) | espn_s2 + SWID | VERIFIED (bundle) |
| GET | `{READS}/teams/{teamId}/recommendations?recommendationTypeId=LINEUP&view=recommend` | Read ESPN's suggested lineup (no write) | espn_s2 + SWID | VERIFIED (live) |
| POST | `{WRITES}/teams?scoringPeriodId=0` | LM: set waiver order, transaction counters, team fields | LM cookies | VERIFIED (bundle) |
| POST | `{WRITES}/teams/{teamId}` body `{"watchList": [playerIds]}` | Replace your watch list (the star next to a player) | espn_s2 + SWID | VERIFIED (bundle) |
| GET | `{READS}?view=mPendingTransactions` | Pending trades and claims (source of truth for alerts) | espn_s2 + SWID | VERIFIED (live) |
| GET | `{READS}?view=mTransactions2` (+ `X-Fantasy-Filter: {"transactions":{...}}`) | Transaction log, filterable by type | espn_s2 + SWID | VERIFIED (live) |
| GET | `{COMM}/communication/?view=kona_league_communication` (+ filter) | Recent Activity topics (`ACTIVITY_TRANSACTIONS`, etc.) | espn_s2 + SWID | VERIFIED (live) |
| GET | `{COMM}/communication/?view=chat_conversations&platform=chat` | Topic list with `unreadMessageCount` | espn_s2 + SWID | VERIFIED (live) |
| GET | `{COMM}/communication/topics/{id}?view=chat_conversation&platform=chat` | Messages of one topic | espn_s2 + SWID | VERIFIED (live) |
| GET | `https://lm-api-communication.fantasy.espn.com/apis/v3/communication/lastReadByMember?view=chat_unreads&platform=chat` | Unread flags for every league of the user | espn_s2 + SWID | VERIFIED (live) |
| POST | `{COMM}/communication/topics/{id}/messages/?source={SWID}&platform=chat` | Send a chat message | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{COMM}/communication/topics/?source={SWID}&platform=chat` | Create a DM topic with its first message | espn_s2 + SWID | VERIFIED (bundle + live record) |
| POST | `{COMM}/communication/topics/{id}/lastRead?platform=chat` | Mark a topic as read | espn_s2 + SWID | VERIFIED (bundle) |
| PUT / DELETE | `{COMM}/communication/topics/{id}/messages/{msgId}/reactions/{reactionId}?platform=chat` | Add / remove a reaction | espn_s2 + SWID | VERIFIED (bundle) |
| PUT / DELETE | `{COMM}/communication/topics/{id}/mutedBy?platform=chat` | Mute / unmute a topic | espn_s2 + SWID | VERIFIED (bundle) |
| POST | `{WRITES}/communication/topics...` | Kona message board, polls, LM email, LM reminder (legacy web, not the chat) | espn_s2 + SWID | VERIFIED (bundle) |

Abbreviations used below:

- `{READS}` = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}`
- `{WRITES}` = `https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}`
- `{COMM}` = `https://lm-api-communication.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{leagueId}`

---

## 1. Request envelope shared by all writes

### Hosts

Status: VERIFIED (bundle).

The kona bundle maps host types to hosts:

| Host type constant | Production host | Used for |
|---|---|---|
| `HOST_TYPE_FANTASY_API` | `lm-api-reads.fantasy.espn.com` | every GET (default) |
| `HOST_TYPE_FANTASY_WRITE_API` | `lm-api-writes.fantasy.espn.com` | every POST, PUT and DELETE issued by the kona web app, including its message board |
| `HOST_TYPE_COMMUNICATION_API` | `lm-api-communication.fantasy.espn.com` | kona reads of `/communication/` (Recent Activity, message board topics) |
| `HOST_TYPE_BACKCHANNEL` | internal only | server-side rendering, not reachable |

The chat iframe (`chat.espn.com`) is a separate app and sends both reads and writes to `lm-api-communication`.

### Headers and query parameters

| Item | Web client value | Required? |
|---|---|---|
| `Cookie` | `espn_s2=<...>; SWID=<SWID>` (sent with `withCredentials: true`) | Yes for any private league (401 without). VERIFIED (live) |
| `Content-Type` | `application/json` | Yes for bodies. VERIFIED (bundle) |
| `Accept` | `application/json` | VERIFIED (bundle) |
| `X-Fantasy-Source` | `kona` | Not required: writes sent without it succeed. VERIFIED (live record) |
| `X-Fantasy-Platform` | `espn-fantasy-web` | Not required. ESPN stores it in `creationInfo.platform` (see gotcha). VERIFIED (bundle + live) |
| `?platformVersion=` | the build SHA, currently `7411ee0540f4d3fa37ae9b9b557490bbb512f9d8` | Added to every kona request, GET and POST. Not required. VERIFIED (bundle) |
| `?platform=chat` | appended by the chat app to every `*.fantasy.espn.com` URL | Sent by the chat client; the `kona_league_communication` read works without it. VERIFIED (bundle + live) |
| `?source=<SWID>` | on chat and message board writes | Sent by both web clients on topic and message creation. VERIFIED (bundle) |

Response headers the web client reads: `x-fantasy-role` (values `ADMIN`, `CUSTOMER_CARE`, `SUPER_USER` flag staff), `x-fantasy-server-time`, `x-fantasy-filter-communication-count`, `x-fantasy-filter-player-count`. VERIFIED (bundle).

### Error body

Status: VERIFIED (live and bundle).

Every 4xx from these services uses the same envelope:

```json
{
  "messages": ["You are not authorized to view this League."],
  "details": [
    {
      "message": "You are not authorized to view this League.",
      "shortMessage": "You are not authorized to view this League.",
      "resolution": null,
      "type": "AUTH_LEAGUE_NOT_VISIBLE",
      "metaData": null
    }
  ]
}
```

- 401 on `lm-api-reads` without cookies: `type: AUTH_LEAGUE_NOT_VISIBLE`. On `lm-api-communication`: `type: AUTH_COMMUNICATION_NOT_VISIBLE`, message "You are not authorized to view this communication group." VERIFIED (live).
- 400 on a bad `X-Fantasy-Filter`: `messages: ["Invalid parameter for 'LeagueFilterParams'."]` plus a `cause` string with the Jackson error, which conveniently lists valid enum values (see section 2). VERIFIED (live).
- 503: the web client treats it as "site in maintenance" and redirects. VERIFIED (bundle).
- Transaction errors: `saveTransaction` treats `status >= 400` as an error and reads `details[].type`, `details[].message`, `details[].resolution` and `details[0].metaData.teamid`. VERIFIED (bundle). The UI shows `message`, or `resolution` when a drop is required.

Transaction error `type` values referenced by the web client (VERIFIED, bundle):

| Group | `details[].type` | Web client behavior |
|---|---|---|
| Roster full, drop required | `TRAN_ROSTER_LIMIT_EXCEEDED_ONE`, `..._ONE_LM`, `..._PLURAL`, `..._PLURAL_LM` | sets `dropIsRequired`, sends the user to the roster fix page for team `metaData.teamid` |
| Roster full because of a pending trade | `TRAN_ROSTER_LIMIT_EXCEEDED_TRADE_RESERVED_ONE`, `..._PLURAL` | `dropIsRequiredForPendingTrade` |
| Position limit (for example max 4 C) | `TRAN_ROSTER_POSITION_LIMIT_EXCEEDED`, `..._LM` | `positionOrSlotLimitExceeded`; team page shows `resolution` |
| Slot limit | `TRAN_ROSTER_SLOT_LIMIT_EXCEEDED`, `..._LM` | `positionOrSlotLimitExceeded` |
| Client side exception | `EXCEPTION` | "Oops! Looks like something went wrong. Please try again" |

The HTTP status that carries these is not visible in the bundle (the client only checks `>= 400`). Earlier client runs recorded HTTP 409 for the position limit and for `ROSTER` sent to a non-current day; that is UNVERIFIED here because writes were not executed.

---

## 2. The transaction body

### Construction

Status: VERIFIED (bundle).

The kona `Transaction` model (`class b` in the bundle) serializes like this:

```js
get() {
  const e = { isLeagueManager, teamId, type };
  memberId        && (e.memberId = memberId);            // guest SWID
  scoringPeriodId && (e.scoringPeriodId = scoringPeriodId);
  executionType   && (e.executionType = executionType);  // defaults to "EXECUTE"
  items.length > 0 && (e.items = items);
  if (type === "WAIVER") { e.bidAmount = bidAmount; relatedTransactionId && (e.relatedTransactionId = ...); }
  if (type === "TRADE_PROPOSAL") e.expirationDate = expirationDate;
  if (type in ["TRADE_PROPOSAL", "TRADE_DECLINE", "TRADE_VETO"]) e.comment = comment;
  if ((type === "TRADE_PROPOSAL" && relatedTransactionId) ||
      type in ["TRADE_ACCEPT", "TRADE_DECLINE", "TRADE_UPHOLD", "TRADE_VETO"]) e.relatedTransactionId = ...;
  if (isLeagueManager) { e.isActingAsTeamOwner = ...; e.skipTransactionCounters = ...; }
  return e;
}
```

Keys whose value is `undefined` disappear in `JSON.stringify`; `null` is sent as `null`.

| Field | Type | Notes |
|---|---|---|
| `isLeagueManager` | bool | Always present. `true` only for LM actions. |
| `teamId` | int | Team performing the action (see each type). |
| `type` | string | Transaction type, see enum below. |
| `memberId` | string | Caller SWID in braces, `<SWID>`. Omitted for offline draft. |
| `scoringPeriodId` | int | `league.status.latestScoringPeriod`, or the target day for `FUTURE_ROSTER`. |
| `executionType` | string | `EXECUTE` (default) or `CANCEL`. |
| `items` | array | Omitted when empty. |
| `bidAmount` | int or null | `WAIVER` only. |
| `expirationDate` | ISO 8601 string or null | `TRADE_PROPOSAL` only. |
| `comment` | string | `TRADE_PROPOSAL`, `TRADE_DECLINE`, `TRADE_VETO`. |
| `relatedTransactionId` | UUID string | Target transaction for accept, decline, vote, cancel. |
| `isActingAsTeamOwner`, `skipTransactionCounters` | bool | Only when `isLeagueManager` is true. |

`createTransaction` also accepts an `analysis` argument that the model ignores, and `executionTypes` constants include `ANALYZE` (id 4); no caller uses it. VERIFIED (bundle).

### Enumerations

Transaction `type`, exact server enum (VERIFIED, live, from a deliberate 400 on a read filter):
`DRAFT, TRADE_ACCEPT, WAIVER, TRADE_VETO, FUTURE_ROSTER, ROSTER, RETRO_ROSTER, TRADE_PROPOSAL, TRADE_UPHOLD, FREEAGENT, TRADE_DECLINE, WAIVER_ERROR, TRADE_ERROR`.

Item `type` values (VERIFIED, bundle; `LINEUP`, `ADD`, `DROP`, `TRADE`, `DRAFT` also live): `LINEUP`, `ADD`, `DROP`, `TRADE`, `DRAFT`, `UNDRAFT`, `DRAFT_TRADE`, `ACQUISITION_BUDGET_TRADE`.

`executionType` (VERIFIED, bundle constants; `EXECUTE`, `CANCEL`, `PROCESS` live): `EXECUTE` (1), `CANCEL` (2), `PROCESS` (3, written by the server when it processes a waiver or an accepted trade), `ANALYZE` (4, unused).

Transaction `status` (VERIFIED, bundle constants `transactionStatusTypes`; `PENDING`, `EXECUTED`, `CANCELED` live):
`FAILED_UNKNOWN (-1), PENDING (0), EXECUTED (1), CANCELED (2), FAILED_POSITIONLIMIT (3), FAILED_TRADELOCK (4), FAILED_NOTCLEAREDWAIVERS (5), FAILED_ROSTERLOCK (6), FAILED_LINEUPLOCK (7), FAILED_TRADELIMIT (8), FAILED_ACQUISITIONLIMIT (9), FAILED_SLOTLIMIT (10), FAILED_INELIGIBLESLOT (11), FAILED_IRSLOT (12), FAILED_ROSTERLIMIT (13), FAILED_INVALIDPLAYERSOURCE (14), FAILED_TRANSVALIDATIONFAILED (15), FAILED_NOPERMISSION (16), FAILED_INVALIDROSTER (17), FAILED_CANCELTRANSACTION (18), FAILED_CANCELACCEPTEDTRADE (19), FAILED_UNDROPPABLEPLAYER (20), FAILED_BADUNIVERSE (21), FAILED_PLAYERALREADYDROPPED (22), FAILED_TRADEPLAYERTOIR (23), FAILED_DROPRESERVEDPLAYER (24), FAILED_MATCHUPACQUISITIONLIMIT (25), FAILED_AUCTIONBUDGETEXCEEDED (26), FAILED_PLAYERNOTONROSTER (27), FAILED_MINIMUMBID (28), FAILED_INVALID_FORMAT (29), FAILED_TRANSACTIONLOCKED (30), FAILED_TRADE_RESERVED (31)`.

`teamActions[teamId]` values: `ACCEPTED` (VERIFIED, live); `APPROVED` and `VETOED` mark a team that already voted (VERIFIED, bundle).

### Item builders

Status: VERIFIED (bundle).

| Builder | Output |
|---|---|
| add | `{"playerId": P, "type": "ADD", "toTeamId": T}` |
| drop | `{"playerId": P, "type": "DROP", "fromTeamId": T}` |
| lineup | `{"playerId": P, "type": "LINEUP", "fromLineupSlotId": A, "toLineupSlotId": B}` (no team ids) |
| trade player | `{"playerId": P, "type": "TRADE", "fromTeamId": X, "toTeamId": Y}`, one per player, both directions |
| trade pick | `{"overallPickNumber": N, "type": "DRAFT_TRADE", "fromTeamId": X, "toTeamId": Y}` |
| trade FAAB | `{"acquisitionBudget": amount, "fromTeamId": X, "toTeamId": Y, "type": "ACQUISITION_BUDGET_TRADE"}` |
| decline dealbreakers | `{"playerId": P}` (no type) and `{"overallPickNumber": N, "type": "DRAFT_TRADE"}` |
| keeper / offline draft | `{"overallPickNumber": N, "playerId": P, "type": "DRAFT" or "UNDRAFT"}` |

Stored items come back enriched with `fromLineupSlotId`, `toLineupSlotId` (-1 when not applicable), `isKeeper`, `overallPickNumber` (0) and `acquisitionBudget` (0). VERIFIED (live).

---

## 3. Lineup: `ROSTER` and `FUTURE_ROSTER`

**Request.** `POST {WRITES}/transactions/`

```json
{
  "isLeagueManager": false,
  "teamId": 3,
  "type": "ROSTER",
  "memberId": "<SWID>",
  "scoringPeriodId": 1,
  "executionType": "EXECUTE",
  "items": [
    {"playerId": 4431785, "type": "LINEUP", "fromLineupSlotId": 12, "toLineupSlotId": 11},
    {"playerId": 4395651, "type": "LINEUP", "fromLineupSlotId": 11, "toLineupSlotId": 12}
  ]
}
```

**Type selection (VERIFIED, bundle, `movePlayers`).** The web starts with `type = ROSTER` and `scoringPeriodId = league.status.latestScoringPeriod`. If the draft is complete or in progress and the requested period is greater than `latestScoringPeriod`, it switches to `FUTURE_ROSTER` with that period. Before the draft, everything is `ROSTER`.

**Plain drops (VERIFIED, bundle, `dropPlayers`).** A drop with no add is a `ROSTER` transaction with `DROP` items, not `FREEAGENT`. Drop plus lineup moves go in one `ROSTER` transaction (`dropAndMovePlayers`). VERIFIED (live record): the completed 2026 season of the reference league holds 129 `ROSTER` transactions with `DROP` items and **zero** `FREEAGENT` transactions whose items are only drops.

**Live records (VERIFIED, live record).** `mTransactions2` holds 10 `ROSTER` and 21 `FUTURE_ROSTER` records with status `EXECUTED`, including lineup moves sent by a non-browser client on 2026-10-12 and 2026-10-13. The matching activity messages use type 188 with `for = teamId`, `from = fromLineupSlotId`, `to = toLineupSlotId`, `targetId = playerId`.

**Gotchas.**
- `RETRO_ROSTER` exists in the server enum (LM retroactive lineup edits). No kona builder sends it. VERIFIED (live enum), usage UNVERIFIED.
- League settings (VERIFIED, live): `rosterSettings.lineupLocktimeType = INDIVIDUAL_GAME` (each player locks at his own tip-off), `rosterLocktimeType = FIRSTGAME_SCORINGPERIOD`, `moveLimit = -1`. Enum `locktimeTypes`: `INDIVIDUAL_GAME (0)`, `FIRSTGAME_SCORINGPERIOD (1)`, `INDIVIDUAL_FIRSTGAME_WEEKLY (2)`, `FIRSTGAME_WEEKLY (4)`. VERIFIED (bundle).
- Per player flags on `mRoster` entries (VERIFIED, live): `playerPoolEntry.lineupLocked`, `rosterLocked`, `tradeLocked` (all bool), plus `entry.pendingTransactionIds`. Team level: `teams[].isTransactionLocked`. Check them before building a move.
- Lock failures surface as status `FAILED_LINEUPLOCK` / `FAILED_ROSTERLOCK` and activity message types 195 / 194, UI text "Reason: Lineup locked." / "Reason: Roster locked.". VERIFIED (bundle).
- The top level `scoringPeriodId` of any league read echoes the `scoringPeriodId` query parameter (asked for 5, got 5 while `status.latestScoringPeriod` was 1). VERIFIED (live). Always take "today" from `status.latestScoringPeriod`.

**How the app should use it.** Plan one day at a time, take "today" from `status.latestScoringPeriod`, use `FUTURE_ROSTER` for later days, and re-read the roster for each day before sending (future moves carry forward). Skip players whose `lineupLocked` is true.

---

## 4. Quick Lineup (ESPN optimizer)

**Read suggestion (VERIFIED, live).** `GET {READS}/teams/3/recommendations?view=recommend&recommendationTypeId=LINEUP` returns:

```json
[
  {
    "recommendationType": "LINEUP",
    "currentProjectedPoints": 0.0, "newProjectedPoints": 0.0,
    "currentWinPct": 0.0, "newWinPct": 0.0,
    "currentWinPctVsOptimized": 0.0, "newWinPctVsOptimized": 0.0,
    "transaction": {
      "type": "ROSTER", "executionType": "EXECUTE", "teamId": 3, "scoringPeriodId": 1,
      "items": [{"playerId": 3149673, "type": "LINEUP", "fromLineupSlotId": 12, "toLineupSlotId": 3, "fromTeamId": 0, "toTeamId": 0}]
    }
  }
]
```

Per-day suggestions (VERIFIED live): the GET accepts `lineupScoringPeriodId={day}` and then returns the suggestion for that day as a `FUTURE_ROSTER` transaction (days 2 to 6 tested). `restOfWeek=true` did not change the GET answer. Passing `scoringPeriodId=3` instead returns HTTP 409 `RECOMMENDATION_INVALID_SCORINGPERIOD` ("League is not in the current scoring period"). For days 1, 2, 4, 5 and 6 of matchup 1 the set of starters **with a game that day** in ESPN's suggestion was identical to the one produced by an independent slot-assignment solver (07, section 1.4); the two only differ in which no-game players fill empty slots. `currentProjectedPoints`/`newProjectedPoints` were 0.0 in preseason.

**Apply (VERIFIED, bundle, never executed).** `POST {WRITES}/teams/{teamId}/recommendations?lineupScoringPeriodId={sp}&recommendationTypeId=LINEUP&restOfWeek={true|false}` with body `{}`. The response is an array of `{transaction}`; status below 300 is success. A second path (`executeLineupRecommendation`, used on the player add page) posts the recommended `transaction.items` as a normal transaction with the recommended `type` and `executionType`.

**Gotcha.** Activity topics created by this path appear with `creationInfo.source = "CPU_USER_INITIATED"` and platform `espn-fantasy-web` (seen live on another team's lineup moves; the link to Quick Lineup is an inference, UNVERIFIED).

**How the app should use it.** Optional: show ESPN's suggestion next to the app's own optimizer as a sanity check. Do not call the POST variant; the app should own the daily lineup and show its plan.

---

## 5. Free agents: `FREEAGENT`

**Request (VERIFIED, bundle, `addPlayers`).**

```json
{
  "isLeagueManager": false, "teamId": 3, "type": "FREEAGENT", "memberId": "<SWID>",
  "scoringPeriodId": 1, "executionType": "EXECUTE",
  "items": [
    {"playerId": 1111111, "type": "ADD", "toTeamId": 3},
    {"playerId": 2222222, "type": "DROP", "fromTeamId": 3}
  ]
}
```

**Gotchas.**
- The web uses `FREEAGENT` only when the player's status is `FREEAGENT`; for status `WAIVERS` it uses `WAIVER`. Player status enum: `FREEAGENT (1)`, `ONTEAM (2)`, `WAIVERS (3)`. VERIFIED (bundle).
- League limits (VERIFIED, live, `settings.acquisitionSettings`): `acquisitionType: WAIVERS_TRADITIONAL`, `acquisitionLimit: -1`, `matchupAcquisitionLimit: 1.0`, `matchupLimitPerScoringPeriod: true`, `transactionLockingEnabled: true`, `isUsingAcquisitionBudget: false`, `acquisitionBudget: 100`, `minimumBid: 1`, `waiverHours: 24`, `waiverProcessDays: ["SUNDAY"]`, `waiverProcessHour: 8`, `waiverOrderReset: false`. A violated acquisition limit surfaces as `FAILED_MATCHUPACQUISITIONLIMIT`. `matchupAcquisitionLimit: 1` with `matchupLimitPerScoringPeriod: true` does not mean one add per day (VERIFIED live record, 2026 season with identical settings): teams executed up to 5 `FREEAGENT` adds in one scoring period and up to 9 in one week, and no `FAILED_MATCHUPACQUISITIONLIMIT` exists in the 2026 log.
- Timing (VERIFIED live record, 2026): an add sent before the first NBA game of the scoring period puts the player on that day's roster; an add sent after the first tip-off keeps `scoringPeriodId` = today in the record but the player only appears on the roster from the next day (25 of 25 and 24 of 25 sampled adds). Stored `ADD` items carry a `toLineupSlotId` (2026, 599 executed adds: bench 12 in 411, UTIL 11 in 112, another starting slot in 76); whether the client or the server picks it is UNVERIFIED.
- Position cap (VERIFIED, live): `rosterSettings.positionLimits = {"5": 4}` (default position 5 = C, max 4). An add that breaks it returns a `TRAN_ROSTER_POSITION_LIMIT_EXCEEDED` detail.
- `player.droppable` (VERIFIED, live key) and `rosterSettings.isUsingUndroppableList: true`: dropping an undroppable player fails with `FAILED_UNDROPPABLEPLAYER`.

---

## 6. Waivers: claim, cancel, edit bid, reorder

### 6.1 Claim

Status: VERIFIED (bundle).

Same as `FREEAGENT` with `type: "WAIVER"`, an `ADD` item, optional `DROP` items (the UI calls them conditional drops: "Select any players to conditionally drop..."), and `bidAmount`:

```json
{
  "isLeagueManager": false, "teamId": 3, "type": "WAIVER", "memberId": "<SWID>",
  "scoringPeriodId": 1, "executionType": "EXECUTE",
  "items": [
    {"playerId": 1111111, "type": "ADD", "toTeamId": 3},
    {"playerId": 2222222, "type": "DROP", "fromTeamId": 3}
  ],
  "bidAmount": null
}
```

The roster fix page reads `bidAmount` from its URL (`?bidAmount=`) and passes `null` when absent, so a non-FAAB claim sends `"bidAmount": null`. In a FAAB league it is an integer at least `minimumBid`.

### 6.2 Cancel a pending claim

Status: VERIFIED (bundle, `cancelWaiverClaim`).

```json
{
  "isLeagueManager": false, "teamId": 3, "type": "WAIVER", "memberId": "<SWID>",
  "scoringPeriodId": 1, "executionType": "CANCEL",
  "relatedTransactionId": "<claimTxId>"
}
```

### 6.3 Change the bid of a pending claim

Status: VERIFIED (bundle, `updateTransaction`).

`POST {WRITES}/teams/{teamId}/pendingTransactions/{claimTxId}` with `{"bidAmount": 12}`. The service method is misleadingly named `updateTrade` in the bundle, but it is wired to the "Update Bid" control of pending claims.

### 6.4 Reorder pending claims

Status: VERIFIED (bundle, `reorderPendingTransactions`).

`POST {WRITES}/teams/{teamId}/pendingTransactions` with an array:

```json
[{"id": "<claimTxIdA>", "subOrder": 1}, {"id": "<claimTxIdB>", "subOrder": 2}]
```

The UI sorts pending claims by `bidAmount` descending then `subOrder` in FAAB leagues, by `subOrder` otherwise. Drag and drop is only offered among claims with the same bid.

### 6.5 What processing looks like

Status: VERIFIED (live record).

A processed claim is a new record: `type: WAIVER`, `executionType: PROCESS`, `status: EXECUTED`, `relatedTransactionId: <original claim id>`, `processDate`, items `ADD` (`fromTeamId: 0`, `toLineupSlotId: 12`) and `DROP` (`toTeamId: 0`). `WAIVER_ERROR` exists in the enum, but the whole 2026 season (read day by day, VERIFIED live record) has no `WAIVER_ERROR` row; failed claims were `type: WAIVER`, `executionType: PROCESS` with a `FAILED_*` status (11 rows, all `FAILED_INVALIDPLAYERSOURCE`), next to 22 `EXECUTED` ones, 15 `CANCEL` and 15 original `EXECUTE` claims (still `PENDING`, stale like trade proposals). Processing happened daily between 07:00 and 09:30 UTC; 19 of 22 successful claims landed on the bench (slot 12). Claim to process delay: 3.6 to 24.3 h in the 5 linked samples. The Waiver Report page reads `view=mTransactions2` with `X-Fantasy-Filter: {"transactions":{"filterType":{"value":["WAIVER","WAIVER_ERROR"]}}}` and keeps only `executionType == "PROCESS"`, grouped by `processDate` day.

### 6.6 League waiver order (LM only)

Status: VERIFIED (bundle).

`setWaiverRanks` sends `POST {WRITES}/teams?scoringPeriodId=0` with `[{"id": teamId, "waiverRank": 1}, ...]`. The same endpoint edits `transactionCounter` fields (transaction counter and budget summary pages) and `rankFinal`. Current order is `teams[].waiverRank` in `mTeam` (VERIFIED, live, 1 = first pick). `status.isWaiverOrderEdited` flags a manual edit. Not needed by a team-owner client.

---

## 7. Trades

### 7.1 Propose: `TRADE_PROPOSAL`

Status: VERIFIED (bundle, `proposeTrade`; live record).

```json
{
  "isLeagueManager": false,
  "teamId": 3,
  "type": "TRADE_PROPOSAL",
  "memberId": "<SWID>",
  "scoringPeriodId": 1,
  "executionType": "EXECUTE",
  "items": [
    {"playerId": 5160992, "type": "TRADE", "fromTeamId": 3, "toTeamId": 1},
    {"playerId": 2595516, "type": "TRADE", "fromTeamId": 1, "toTeamId": 3}
  ],
  "expirationDate": "2026-10-16T14:59:21.437Z",
  "comment": "optional note shown to the other owner"
}
```

- `teamId` is the proposer. Items cover both directions; add `DRAFT_TRADE` and `ACQUISITION_BUDGET_TRADE` items for picks and FAAB, and `DROP` items when the proposer must clear space (from `rosterfixTeamId` if the server named a team, else the proposer).
- `expirationDate`: the trade page always computes `moment().add(days, "days")` for regular owners (`days` default 2, choices 1 to 7) and `null` for an LM. A moment object serializes through `toJSON`, which is `toISOString()` (UTC, milliseconds, `Z`). VERIFIED (bundle).
- When `expirationDate` is omitted, the server stored exactly proposal time plus 48 h (`proposedDate 1791989961412`, `expirationDate 1792162761437`). VERIFIED (live record).
- On error with `dropIsRequired`, the UI routes to the roster fix page for `details[0].metaData.teamid`.

### 7.2 Cancel your own proposal

Status: VERIFIED (bundle + live record).

```json
{
  "isLeagueManager": false, "teamId": 3, "type": "TRADE_PROPOSAL", "memberId": "<SWID>",
  "scoringPeriodId": 1, "executionType": "CANCEL",
  "relatedTransactionId": "<proposalTxId>"
}
```

Live, a cancel shows up as a separate record: `type: TRADE_PROPOSAL`, `executionType: CANCEL`, `status: CANCELED`, `relatedTransactionId` pointing to the original. An already accepted offer cannot be canceled ("You cannot cancel this trade offer as it has already been accepted"; status `FAILED_CANCELACCEPTEDTRADE`).

### 7.3 Accept: `TRADE_ACCEPT`

Status: VERIFIED (bundle + live record).

```json
{
  "isLeagueManager": false, "teamId": 1, "type": "TRADE_ACCEPT", "memberId": "<SWID>",
  "scoringPeriodId": 1, "executionType": "EXECUTE",
  "relatedTransactionId": "<proposalTxId>",
  "items": [{"playerId": 3333333, "type": "DROP", "fromTeamId": 1}]
}
```

`teamId` is the accepting team; `items` only carries drops needed to make room. Live accept records have `items: []` and no `status`. After acceptance, `mPendingTransactions` shows the proposal transformed to `type: TRADE_ACCEPT`, `status: PENDING`, with `acceptedDate`, `processDate = acceptedDate + tradeSettings.revisionHours` (24 h here) and `teamActions` listing both teams as `ACCEPTED`. At `processDate` the server writes another `TRADE_ACCEPT` record with `executionType: PROCESS`, `status: EXECUTED`, `teamId` = proposer, and moves the players (`acquisitionType: TRADE` on the roster entries). Observed end to end on 2026-10-14 and 2026-10-15. VERIFIED (live).

### 7.4 Decline and counter: `TRADE_DECLINE`

Status: VERIFIED (bundle + live record).

```json
{
  "isLeagueManager": false, "teamId": 2, "type": "TRADE_DECLINE", "memberId": "<SWID>",
  "scoringPeriodId": 1, "executionType": "EXECUTE",
  "comment": "optional reason",
  "relatedTransactionId": "<proposalTxId>",
  "items": [{"playerId": 3064440}]
}
```

- `items` are optional "dealbreakers" ("Which players are causing you to decline this trade offer?"): bare `{playerId}` objects and `{overallPickNumber, type: "DRAFT_TRADE"}` for picks.
- There is no counter-offer endpoint. The "Decline & Counter" button (`TRADE_AND_COUNTER`) sends this same decline and then opens the trade page `/team/trade/?leagueId=..&seasonId=..&teamId=<proposer>&fromTeamId=<me>&step=1` to build a new `TRADE_PROPOSAL`.
- Live, a decline writes the `TRADE_DECLINE` record (no `items` key) and, at the same timestamp, a `TRADE_PROPOSAL` record with `executionType: CANCEL`, `status: CANCELED` for the proposer.

### 7.5 Votes: `TRADE_VETO` and `TRADE_UPHOLD`

Status: VERIFIED (bundle + live record).

```json
{
  "isLeagueManager": false, "teamId": 14, "type": "TRADE_VETO", "memberId": "<SWID>",
  "scoringPeriodId": 1, "executionType": "EXECUTE",
  "comment": "Reason for Veto",
  "relatedTransactionId": "<acceptedTradeTxId>"
}
```

- Member vote (action mode `vote`): `isLeagueManager: false`, `teamId` = the voter's team. `TRADE_UPHOLD` has the same shape without `comment`. A live member veto record exists (`teamId 14`, status `EXECUTED`).
- LM review (action mode `LMreview`): `isLeagueManager: true`, `teamId` = the proposing team, plus `isActingAsTeamOwner` and `skipTransactionCounters`.
- League settings (VERIFIED, live): `tradeSettings = {revisionHours: 24, vetoVotesRequired: 5, max: -1, allowOutOfUniverse: false, deadlineDate: 1803661200000}`. One member veto did not stop the trade it targeted; it processed at the end of the review window.

### 7.6 `TRADE_ERROR`

Server-side only: logged when an accepted trade fails at process time (for example "Trade Failed, a roster was locked at the time the trade was processed", status `FAILED_ROSTERLOCK` or `FAILED_TRADELOCK`). No client sends it. Enum value VERIFIED (live); semantics UNVERIFIED.

---

## 8. Draft (`DRAFT`, LM only)

`saveDraftedPlayers` (offline draft entry) posts `{"isLeagueManager": false, "teamId": T, "type": "DRAFT", "scoringPeriodId": 1, "executionType": "EXECUTE", "items": [...]}` without `memberId`. Keeper edits build `UNDRAFT` and `DRAFT` items with `overallPickNumber`. Live draft results are 130 `DRAFT` records with status `EXECUTED`. VERIFIED (bundle + live). Not needed by a team-owner client; the draft board itself uses `POST {WRITES}/../segments/{segmentId}/leagues/{id}/draftDetail` (VERIFIED, bundle, not documented further).

---

## 9. Reading pending activity (alerts, no writes)

### 9.1 `view=mPendingTransactions` (primary source)

**Request.** `GET {READS}?view=mPendingTransactions`. VERIFIED (live).

**Response.**

```json
{
  "id": 12345678, "seasonId": 2027, "scoringPeriodId": 1,
  "status": {"latestScoringPeriod": 1, "transactionScoringPeriod": 1, "waiverLastExecutionDate": 1792050543878, "...": "..."},
  "pendingTransactions": [
    {
      "id": "<txId>",
      "type": "TRADE_ACCEPT",
      "status": "PENDING",
      "isPending": true,
      "executionType": "EXECUTE",
      "teamId": 3,
      "memberId": "<SWID>",
      "proposedDate": 1791989961412,
      "acceptedDate": 1791990163580,
      "processDate": 1792076563580,
      "expirationDate": 1792162761437,
      "bidAmount": 0,
      "rating": 0,
      "scoringPeriodId": 1,
      "isActingAsTeamOwner": false,
      "isLeagueManager": false,
      "teamActions": {"3": "ACCEPTED", "1": "ACCEPTED"},
      "items": [
        {"playerId": 5160992, "type": "TRADE", "fromTeamId": 3, "toTeamId": 1,
         "fromLineupSlotId": 11, "toLineupSlotId": -1, "isKeeper": false,
         "overallPickNumber": 0, "acquisitionBudget": 0}
      ]
    }
  ]
}
```

**Gotchas.**
- When nothing is pending the `pendingTransactions` key is absent, not an empty list. VERIFIED (live).
- The trade review page loads this view and looks up the offer by `transactionId` from its URL, so incoming `TRADE_PROPOSAL` offers are expected here. VERIFIED (bundle). Pending waiver claims (`type: WAIVER`, with `bidAmount` and `subOrder`) also come from this view. VERIFIED (bundle); no live sample yet.
- The web filters this list client side: a transaction concerns team T when `teamId == T` or any item has `fromTeamId == T` or `toTeamId == T`; asking for `TRADE_PROPOSAL` also returns `TRADE_ACCEPT`. VERIFIED (bundle).
- Timestamps are epoch milliseconds (UTC).

### 9.2 `view=mTransactions2` (history, with caveats)

**Request.** `GET {READS}?view=mTransactions2`, optional header `X-Fantasy-Filter: {"transactions":{"filterType":{"value":["TRADE_PROPOSAL","TRADE_ACCEPT","TRADE_DECLINE","TRADE_VETO","TRADE_UPHOLD"]}}}`. VERIFIED (live). Used by the Waiver Report, Offer Report and Transaction Counter pages (VERIFIED, bundle).

**Response.** `transactions[]` with the same fields as above (`processDate`, `expirationDate`, `teamActions`, `relatedTransactionId`, `memberId` appear only when relevant). VERIFIED (live).

**Gotchas (all VERIFIED, live).**
- The original `TRADE_PROPOSAL` record keeps `status: PENDING` and `isPending: true` after it is declined, canceled, accepted or processed. Resolve its real state from records whose `relatedTransactionId` points at it, or use `mPendingTransactions`.
- Proposals between two other teams are not returned; proposals sent by or to the caller's team are. Accepted, declined, vetoed and processed records of other teams are returned.
- In the 2027 preseason `?scoringPeriodId=` does not narrow the list (same 174 records for period 1 and 2). That is a preseason effect (VERIFIED live): on the completed 2026 season the view returns only the rows of the requested day and 0 rows without the parameter; plan for per-day requests in-season (UNVERIFIED for 2027 until opening night).
- A `PENDING` proposal row is not proof of an open offer (VERIFIED live): the "incoming proposal" visible on 2026-10-15 (team 10 to team 3, `status: PENDING`) had been withdrawn by its proposer one minute after creation (CANCEL record at 2026-10-14 03:43 UTC). No open proposal existed during these probes.
- An invalid `filterType` value returns 400 with the enum list; an unknown filter key is silently ignored and the full list is returned.

### 9.3 Recent Activity: `kona_league_communication`

**Request.** `GET {COMM}/communication/?view=kona_league_communication` with

```json
{"topics": {
  "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
  "filterDateRange": {"value": 1791849600000, "additionalValue": 1792108799999},
  "filterIncludeMessageTypeIds": {"value": [178, 180]},
  "filterExcludeMessageTypeIds": {"value": []},
  "filterMessageToAndFromIds": {"value": [3]},
  "limit": 25, "limitPerMessageSet": {"value": 25}, "offset": 0,
  "sortMessageDate": {"sortPriority": 1, "sortAsc": false},
  "sortFor": {"sortPriority": 2, "sortAsc": false}
}}
```

Filter keys are VERIFIED (bundle, Recent Activity page); the request with `filterType`, `limit`, `limitPerMessageSet`, `offset` and both sorts is VERIFIED (live, 19 topics). Topic types: `ACTIVITY_TRANSACTIONS`, `ACTIVITY_SETTINGS`, `ACTIVITY_STATUS`, `ACTIVITY_SCHEDULE`, `MSG_BOARD`, `MSG_BOARD_GROUP`, `MSG_BOARD_MATCHUP`, `NOTE`, `POLL`, `EMAIL` (VERIFIED, bundle). The total count comes back in header `x-fantasy-filter-communication-count` (VERIFIED, bundle).

**Response (VERIFIED, live).**

```json
{"topics": [{
  "id": "<topicId>", "type": "ACTIVITY_TRANSACTIONS",
  "author": "<SWID> or a processor name", "date": 1791989961430,
  "targetId": "<transactionId> or a scoring period number",
  "viewableBy": ["<SWID_A>", "<SWID_B>"],
  "creationInfo": {"platform": null, "source": "<SWID>", "clientAddress": null, "date": 1791989961430},
  "totalMessageCount": 2, "isDeleted": false, "isEdited": true,
  "messages": [{
    "id": "<msgId>", "topicId": "<topicId>", "messageTypeId": 230,
    "from": 3, "to": 1, "targetId": 5160992, "for": null,
    "author": "<SWID>", "date": 1791989961430, "isAlternateFormat": false
  }]
}]}
```

Field meaning by message type (VERIFIED, live):

| `messageTypeId` | Name | `from` | `to` | `for` | `targetId` |
|---|---|---|---|---|---|
| 188 | `TRANSACTION_ROSTER` | from slot | to slot | team | player |
| 180 / 181 | `TRANSACTION_WAIVER_ADD` / `_DROP` | 0 (pool) on add | team | waiver claim order (1) on add | player |
| 230 | `TRANSACTION_TRADE_PROPOSAL_TRADE` | giving team | receiving team | | player |
| 224 | `TRANSACTION_TRADE_ACCEPT_TRADE` | giving team | receiving team | | player |
| 244 | `TRANSACTION_TRADE_PROCESSED_TRADE` | giving team | receiving team | | player |

Trade proposal topics carry `viewableBy` with the two owners' SWIDs; other activity topics are league-wide. Authors include member SWIDs, `NightlyLeagueUpdateTaskProcessor`, `TradeTaskProcessor` and `CPU_USER_INITIATED`.

Complete communication message type ids (VERIFIED, bundle constants): 0 `CUSTOM`; 100 to 177 settings changes (for example 131 `ROSTER_SETTINGS_LINEUP_LOCKTIME_CHANGE`, 169 `TEAM_WAIVER_ORDER_CHANGE`, 177 `TRADE_SETTINGS_VOTES_REQ_CHANGE`); 178 `TRANSACTION_FREEAGENT_ADD`; 179 `TRANSACTION_FREEAGENT_DROP`; 180 `TRANSACTION_WAIVER_ADD`; 181 `TRANSACTION_WAIVER_DROP`; 182 `TRANSACTION_TRADE_ACCEPT`; 183 `TRANSACTION_TRADE_DECLINE`; 184 `TRANSACTION_TRADE_PROPOSAL`; 185 `TRANSACTION_TRADE_UPHOLD`; 186 `TRANSACTION_TRADE_VETO`; 187 `TRANSACTION_TRADE_PROCESSED`; 188 `TRANSACTION_ROSTER`; 189 `TRANSACTION_DRAFT`; 190 `TRANSACTION_DRAFT_TRADE`; 191 to 217 `TRANSACTION_FAILED_*` (191 POSITIONLIMIT, 192 TRADELOCK, 193 NOTCLEAREDWAIVERS, 194 ROSTERLOCK, 195 LINEUPLOCK, 196 TRADELIMIT, 197 ACQUISITIONLIMIT, 198 SLOTLIMIT, 199 INELIGIBLESLOT, 200 IRSLOT, 201 ROSTERLIMIT, 202 INVALIDPLAYERSOURCE, 203 TRANSVALIDATIONFAILED, 204 NOPERMISSION, 205 INVALIDROSTER, 206 CANCELTRANSACTION, 207 CANCELACCEPTEDTRADE, 208 UNDROPPABLEPLAYER, 209 BADUNIVERSE, 210 PLAYERALREADYDROPPED, 211 TRADEPLAYERTOIR, 212 DROPRESERVEDPLAYER, 213 MATCHUPACQUISITIONLIMIT, 214 AUCTIONBUDGETEXCEEDED, 215 PLAYERNOTONROSTER, 216 MINIMUMBID, 217 INVALID_FORMAT); 224 to 246 trade sub-messages (`_TRADE`, `_DROP`, `_DRAFT_TRADE` variants of accept 224 to 226, decline 227 to 229, proposal 230 to 232, uphold 233 to 235, veto 236 to 238, LM veto 240 to 243, processed 244 to 246); 239 `TRANSACTION_ROSTER_DROP`; 247 `SCHEDULE_MATCHUP_ADJUSTMENT_CHANGE`; 252 `TRANSACTION_LIKELY_TO_TRADE`; 284, 286, 290 FAAB trade accept, proposal, processed.

### 9.4 Chat unread counts

- `GET {COMM}/communication/?view=chat_conversations&platform=chat` without a filter returns every topic the user can see (40 live: `ACTIVITY_TRANSACTIONS`, `ACTIVITY_SETTINGS`, `ACTIVITY_STATUS`, `CHAT_ALL_MEMBERS`, `CHAT_DIRECT_MESSAGE`, legacy `CHAT`), each with `id`, `type`, `dateEdited`, `unreadMessageCount`, sometimes `viewableBy`, `subject`, `lastRead`, and no messages. Unread `ACTIVITY_TRANSACTIONS` topics showed `unreadMessageCount: 1`. VERIFIED (live).
- `GET https://lm-api-communication.fantasy.espn.com/apis/v3/communication/lastReadByMember?view=chat_unreads&platform=chat` returns `{"lastReadByGroup": {"<leagueId>.<gameId>.<seasonId>": {"lastMessageDate": ms, "unread": bool, "lastReadByTopic": {"<topicId>": {"unread": bool}}}}}`, one group per league season (for example `12345678.3.2027`). VERIFIED (live). Cheapest poll for "anything new in chat".

### 9.5 Recommended alert logic

1. Every few minutes: `GET mPendingTransactions`. New `TRADE_PROPOSAL` where `teamId != {me}` and an item has `toTeamId == {me}` or `fromTeamId == {me}` means "you received a trade offer"; show `expirationDate`. `TRADE_ACCEPT` with `status PENDING` means "accepted, in review until `processDate`". Track seen ids locally.
2. Optionally poll `chat_unreads`; when `unread` flips, read `chat_conversations` and the changed topics. A type 271 card in a DM is the same offer (`attributes.tId` = proposal id).
3. Use `mTransactions2` or `kona_league_communication` only for history and "what happened" summaries (declines, vetoes, processed trades, waiver results), resolving stale `PENDING` proposals through `relatedTransactionId`.

---

## 10. Chat and communication API (chat app `community-chat 1.0.67`)

### Resources

Status: VERIFIED (bundle).

All paths below are relative to `https://lm-api-communication.fantasy.espn.com`, with `{L}` = `/apis/v3/games/{gameAbbrev}/seasons/{seasonId}/segments/{segmentId}/leagues/{leagueId}/communication` and `gameAbbrev = fba`. The client appends `platform=chat` to every URL on a `fantasy.espn(qa).com` host and sends cookies (`withCredentials`).

| Resource | Method | Path | Body / filter |
|---|---|---|---|
| `conversations` | GET | `{L}/?view=chat_conversations` | `X-Fantasy-Filter: {"topics":{"filterType":{"value":["CHAT_ALL_MEMBERS","CHAT_DIRECT_MESSAGE"]}}}` |
| `conversation` | GET | `{L}/topics/{conversationId}?view=chat_conversation` | newest page: `{"limit":25,"offset":0,"sortDate":{"sortAsc":false,"sortPriority":1}}`; catch-up: `{"limit":10000000,"offset":N,"sortDate":{"sortAsc":true,"sortPriority":1}}` |
| `newConversation` | POST | `{L}/topics/?source={SWID}` | `{"messages":[{"author":"<SWID>","content":"text","messageTypeId":0}],"subject":"DM","type":"CHAT_DIRECT_MESSAGE","viewableBy":["<SWID_A>","<SWID_B>"]}` (subject is forced to `"DM"` for DMs) |
| `newMessage` | POST | `{L}/topics/{conversationId}/messages/?source={SWID}` | `{"author":"<SWID>","content":"text","messageTypeId":0}` plus payload fields for rich types; empty content becomes `null`; the response may be an array (client takes `[0]`) |
| `updateLastRead` | POST | `{L}/topics/{conversationId}/lastRead` | `{}` |
| `addReaction` / `removeReaction` | PUT / DELETE | `{L}/topics/{conversationId}/messages/{messageId}/reactions/{reactionId}` | none |
| `muteNotifications` / `unmuteNotifications` | PUT / DELETE | `{L}/topics/{conversationId}/mutedBy` | `["<SWID>"]` |
| `unreads` | GET | `/apis/v3/communication/lastReadByMember?view=chat_unreads` | none |
| `sendFeedback` | POST | `/apis/v3/feedback` | abuse report (HTML content) |

Other hosts used by the chat app (VERIFIED, bundle; not probed): `presence.fantasy.espn.com/apis/v1/heartbeat` and `/apis/v1/presence/?memberId=` (online status), `fan.api.espn.com/apis/v2/fans/{swid}` (the user's leagues), and `lm-api-reads` views `chat_league`, `chat_draftpicks`, `chat_players`. The fan API call (exact chat bundle path `/apis/v2/fans/{swid}?displayHiddenPrefs=true&context=fantasy&useCookieAuth=true&source=fantasyapp-ios&featureFlags=challengeEntries`) is documented with a live GET in 07, recipe (h). `lastReadByMember?view=chat_unreads` also answers on `lm-api-reads` (VERIFIED live).

### Topic types

Status: VERIFIED (bundle + live).

- `CHAT_ALL_MEMBERS`: the league chat shown in the web "Fantasy Chat" panel. Live: one topic, 172 messages, including bot cards. When it does not exist yet, the client uses a placeholder id `League|Chat`.
- `CHAT_DIRECT_MESSAGE`: one topic per member pair, `viewableBy` = both SWIDs, `subject` = `"DM"` when created by the chat app.
- `CHAT`: legacy type. Live: one topic with a single message from 2026-10-12. The chat app never requests or displays it.

### Message types

Status: VERIFIED (bundle; live where noted).

| Id | Meaning | Payload |
|---|---|---|
| 0 | Text (live) | `content` |
| 188, 239 | Lineup move / roster drop bot lines | `for`, `from`, `to`, `targetId` |
| 259 | Sticker | |
| 260 | GIF (live) | `targetId` = GIF id |
| 264, 265, 266 | Chat bot: player add, drop, add plus drop | `attributes` |
| 267, 268, 269 | Weekly recap: top players, best team, worst team | |
| 270 | System text | `content` |
| 271 | Trade proposal card (live) | `attributes` |
| 272 | Trade accepted card (live) | `attributes` |
| 273 | Waiver Wire Report card, "Offers Report" when bids exist (live) | `attributes` (`team1`, `wDate`, `numP`, `team1addP1`, `team1dropP1`, bids) |
| 278 | Shared text (`subject` plus `content`) | |
| 279 | Shared video | `content` (mp4 URL), `poster` |
| 280 | Rich text | `content` |
| 281 | League recap | |
| 283 | Shared image | `content` (URL), `attributes` |
| 294 | "Last words" message | |

Messages also carry `reactions`: `{"<reactionId>": ["<SWID>", ...]}` (VERIFIED, live).

### The type 271 trade card

Status: VERIFIED (bundle + live).

Posted by author `LM` into the DM topic between the two owners (and 272 into `CHAT_ALL_MEMBERS` on acceptance):

```json
{
  "messageTypeId": 271,
  "author": "LM",
  "attributes": {
    "tId": "<proposalTxId>",
    "team1": "1",
    "team2": "3",
    "team1addP1": "5160992",
    "team2addP1": "2595516"
  }
}
```

- Keys match the bundle regex `(team|t)(\d+)(add|drop)(D|P)` followed by an index, where the digit is the side (1 or 2, not a team id), `P` = player id, `D` = draft pick; FAAB uses `team{N}budgetAmt{i}`; `numP` (when present) switches to a summary layout. All values are strings.
- In all three live 271 cards, `team1` was the receiving team and `team2` the proposer. UNVERIFIED as a rule.
- The card links to the trade review page for `tId`. The proposal `comment` is not in the card and was not found in `mPendingTransactions` (earlier observation, UNVERIFIED); its delivery channel is an open question.

### Kona message board writes

Status: VERIFIED (bundle; legacy web).

The main web app (not the chat) posts to the WRITES host: `POST {WRITES}/communication/topics/?source={SWID}` (create topic), `POST {WRITES}/communication/topics/{id}?source={SWID}` (edit), `POST {WRITES}/communication/topics/{id}/messages?source={SWID}` with `{"author","content","isDeleted":false,"isEdited":false,"subject","topicId"}`, `POST .../topics/{id}/lastRead` `{}`, `POST .../topics/{id}/poll` (vote), `DELETE .../topics/{id}`, `POST .../topics` with `{"content","subject","type":"EMAIL","viewableBy"}` (email the league) and `POST .../topics?source={SWID}` with `{"type": ...}` (remind the LM). Reads use `view=kona_league_messageboard` and `kona_communication_topic`. Clients should use the chat API instead.

---

## 11. Client implementation checklist

How a non-browser client should match ESPN's web client. Rows marked VERIFIED (live record) are backed by writes that a non-browser client sent successfully before this document was written.

| Area | ESPN web client | Guidance |
|---|---|---|
| Body envelope | `isLeagueManager`, `teamId`, `type`, `memberId`, `scoringPeriodId`, `executionType`, `items` (section 2) | Send exactly these keys plus the type-specific ones. A non-browser client using this envelope succeeds. VERIFIED (bundle + live record) |
| Headers | Adds `X-Fantasy-Source: kona`, `X-Fantasy-Platform: espn-fantasy-web`, `?platformVersion=` | Not required. ESPN records `creationInfo.platform = null` for clients that omit them, versus `espn-fantasy-web` or `espn-fantasy-app-ios` for official clients (VERIFIED, live). Do not impersonate the web client. |
| Current period | `status.latestScoringPeriod` | The top-level `scoringPeriodId` of a read echoes the query parameter, so it equals "today" only when the read had none (VERIFIED, live). Use `status.latestScoringPeriod`. |
| Plain drop | `type: ROSTER` with `DROP` items (`dropPlayers`) | Do not send `FREEAGENT` with only a `DROP` item: the web never does, and the server behavior is UNVERIFIED. |
| Waiver claim | `bidAmount` key always present (`null` without FAAB) | Send `bidAmount: null` or the bid. |
| Free agent add | `FREEAGENT` with an `ADD` item, then optional `DROP` items | Same. |
| Lineup | `ROSTER` for today, `FUTURE_ROSTER` for later days (`movePlayers`) | Same rule; re-read and re-plan each day after the previous day's move is sent. |
| Trade proposal | `TRADE` items both ways, `comment` only if typed, `expirationDate` = now + N days (default 2) | If `expirationDate` is omitted the server defaults to 48 h (VERIFIED, live record); send an ISO 8601 UTC string to choose another window. |
| Trade lifecycle | Cancel, accept, decline (with dealbreakers), counter, vote | Bodies in section 7. |
| Pending claims | Cancel, edit bid, reorder | Bodies in section 6. |
| League chat | Uses `CHAT_ALL_MEMBERS` | The legacy `CHAT` topic is not the league chat (1 message live, versus 172 in `CHAT_ALL_MEMBERS`); reading or posting there misses the conversation. |
| Chat topic list | `chat_conversations` with `filterType [CHAT_ALL_MEMBERS, CHAT_DIRECT_MESSAGE]` | Without the filter, activity topics come back too. |
| Message labels | Renders 0, 188, 239, 259, 260, 264 to 273, 278 to 283, 294 | Label all of them (section 10), not only 0 and 271. |
| Response parsing | Checks HTTP `< 400` only; reads errors from `details[]` | The success body shape is UNVERIFIED: log it raw on first use, and show `details[].type` and `resolution` on errors. |

---

## 12. How the app should use all this

- Keep one `transactions.py` module that builds bodies exactly as in section 2 (same key set and conditional fields) and a dry-run mode that prints the JSON without sending. All writes stay behind an explicit confirmation flag.
- Always derive "today" from `status.latestScoringPeriod` and re-read before each write.
- Pre-validate locally to avoid round trips: lock flags, `positionLimits`, `droppable`, roster size, `acquisitionSettings`, `tradeSettings.deadlineDate`.
- Map `details[].type` to friendly messages and show `resolution` when present.
- Build alerts on `mPendingTransactions` plus `chat_unreads`, as in section 9.5.
- Treat `teamId`s as opaque (this league uses 1, 2, 3, 6, 10, 11, 13, 14, 15, 16).

---

## 13. Watch list: `POST {WRITES}/teams/{teamId}`

Status: VERIFIED (bundle, `watchPlayer`); the read side VERIFIED (live, 2026-10-16).

The watch list (the star next to a player in the ESPN app) is a field of your own team, not a transaction. The web client reads the current list, adds or removes one player id, and posts the whole new list:

```json
POST {WRITES}/teams/3
{"watchList": [4432166, 1111111]}
```

- **Read it** from `view=mTeam`: `teams[].watchList` is a list of player ids, present only on the caller's own team (an empty list when nothing is watched) and absent on the others. VERIFIED (live)
- **Send the whole list.** No envelope, no `type`, no `memberId`. Re-read the list right before writing, because the ESPN app may have changed it since (benchboss `Session.set_watched` does). The change is private to you and reversible.
- **Answer.** benchboss reads `watchList` from the response when it is there and otherwise keeps the list it sent; the exact response shape is UNVERIFIED.
- **Cap.** The web client refuses an add once the list holds `config.maxWatchListPlayers` players ("The Watch List is capped at {max} players. To add another player to your Watch List, please first remove..."). VERIFIED (bundle) The number lives in the web app's own config, not in the league settings (`mSettings` has no such key, VERIFIED live), and whether the server enforces it is UNVERIFIED. benchboss does not check it: an add past the cap gets whatever ESPN answers, shown as the write's result.
- benchboss: `benchboss watch add|remove "Player"` (asks first, `--dry-run` sends nothing) and the space key in the app's player finder (`client.update_team`).

---

## Open questions

1. Exact HTTP status codes for transaction errors (earlier client runs saw 409 for the position limit and for `ROSTER` on a non-current day); confirm with a real write and record the body.
2. Shape of a successful `POST /transactions/` response (does it return the transaction with `id` and `status`, or a wrapper?).
3. Does `type: FREEAGENT` with only a `DROP` item succeed, fail, or count as an acquisition? The web never sends it.
4. Where does the trade `comment` surface for the receiver (not in the 271 card attributes, reportedly not in `mPendingTransactions`)? Possibly a separate type 0 DM message or the trade review page only.
5. Does `mPendingTransactions` return other teams' pending offers or only those involving the caller? Observed data is consistent with "only ours" but there was no third-party pending offer to test.
6. Meaning of `matchupAcquisitionLimit: 1.0` with `matchupLimitPerScoringPeriod: true` (one add per day, or per matchup?). Partial answer (VERIFIED live record, 2026): neither; the league executed up to 5 adds per team per day and 9 per week. What it controls remains unknown.
7. Is `expirationDate` validated against a maximum (the UI offers 1 to 7 days) and does it accept epoch milliseconds as well as ISO strings?
8. Which parameter, if any, narrows `mTransactions2` by team? (`scoringPeriodId` narrows it by day on the completed 2026 season, but not in the 2027 preseason.)
9. Origin and purpose of the legacy `CHAT` topic, and whether the server still notifies members about messages posted there.
10. Whether `X-Fantasy-Platform` accepts arbitrary values (for example an app identifier) or only known clients.
11. The value of `maxWatchListPlayers` for basketball, and whether the server rejects a `watchList` longer than it (section 13).

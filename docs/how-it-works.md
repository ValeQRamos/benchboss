# How benchboss works

This page explains every number benchboss shows, so you can trust it or argue with it.

## The data

benchboss reads your league from ESPN's fantasy API with your session cookies, the same way
the ESPN website does. One call brings rosters, settings, standings and matchups; the NBA
schedule for the whole season is cached for a day. Player news comes from ESPN's public
fantasy news feed. The full map of what ESPN exposes is in [docs/api](api/README.md).

Vocabulary used below:

- **Scoring period**: one day. Period 1 is opening night of the NBA regular season.
- **Matchup week**: the days of one head-to-head matchup. The first runs from opening night to
  the first Sunday, then Monday to Sunday; the week of the All-Star break is merged with the
  next one, exactly like ESPN.
- **Projection**: ESPN's projected fantasy points per game for the season, already scored with
  your league's point values. When a player has none yet, his season average is used (last
  season's early in the year).

## Expected points for one player on one day

```
value(player, day) = 0                                  if his team has no game that day
                   = projection x availability          otherwise
```

| Status | Availability |
|---|---|
| Healthy, probable | 100% |
| Day-to-day, questionable | 75% |
| Doubtful | 25% |
| Out, suspended, injured reserve | 0% |

## Lineup optimizer

For each day, benchboss assigns players to your league's starting slots (PG, SG, SF, PF, C,
G, F, UT, ...) to maximize the total expected points. It does not guess: a dynamic program
walks the slots one by one and keeps the best total for every set of players already used, so
the answer is the true optimum for your slot rules. Ties favor keeping a player where he
already is, so a day that is already right produces no moves.

- **Today** is sent as a normal lineup change. Future days are sent as ESPN "future roster"
  moves, which carry forward to the following days.
- Before sending each day benchboss reads that day again, because a move on Monday carries
  into Tuesday: a day that looked fine in the preview can need moves after an earlier day
  changes, and the other way around. Days that need nothing are skipped.
- Players whose game has already tipped off are locked by ESPN, so they stay where they are
  and only the others are rearranged.
- Players on injured reserve are never moved.

## Projected final

```
projected final = points scored so far this week
                + sum over the remaining days of the best N expected values among players with a game
```

N is the number of starting slots. For today, only games that have not tipped off yet count:
the rest is already in the live score. Players projected at zero (out, suspended) do not count
as games left.

This is the same method for both teams, so the comparison is fair even when ESPN's own
numbers are not available (ESPN does not publish a matchup projection for basketball).

## Workload

For each rostered player: games in the matchup week, games left from today, and the opponent
for each day (`@` means away). In daily leagues a four-game week is worth a lot more than a
two-game week at the same average.

## Best trash (free agent value)

The question is not "who is the best free agent" but "who adds the most points to *my*
lineup before Sunday". For every free agent (the 60 most rostered) and every possible pickup
day:

1. For each remaining day from the pickup day, if he has a game, compare his expected points
   with the cutoff: the weakest of your players who would start that day. If you would have an
   empty slot, the cutoff is zero.
2. Add up the positive differences. That is his **gain** for that pickup day.
3. The **best day** is the pickup day with the highest gain minus drop cost (see 4 and 5).
   Picking up later can win when the player you drop still has games early in the week; ties
   go to the earlier day, because waiting risks losing the player. Today only counts if his
   game has not tipped off yet.
4. The **suggested drop** is the player whose absence costs you the fewest points over the
   same days (often someone with few games left). His lost points are the **drop cost**.
5. **Net** = gain minus drop cost. The list is sorted by net.

Players on waivers start counting only after the waiver period (24 hours in most leagues).

## Trade finder

1. **Positional profile**: for each team, the sum of projections at PG, SG, SF, PF and C. A
   player eligible at two positions counts half at each.
2. **Balance**: profile minus the league average. Positive is surplus, negative is need.
   `benchboss trades --needs` shows the whole table.
3. **Candidates**: you give a player whose main position is your surplus and their need; you
   get one whose main position is their surplus and your need (or the position you asked for
   with `--need`).
4. **Fairness**: `1 - |difference in projection| / higher projection`. Ideas below 85% are
   dropped (`--fairness` changes it).
5. **Limits**: deals that would break the league's position limits (for example a maximum of
   four centers) are removed.
6. **Ranking**: fairness first, then how much the deal fixes both sides, then a small bonus
   when you get the slightly better player. At most two ideas per team and two per player you
   give, so the list stays varied.

Each idea comes with a short note you can send with `benchboss trade ... --msg`.

## News

`benchboss news` asks ESPN's public fantasy feed for every player on your roster at once and
shows RotoWire's blurb plus its analysis (ESPN labels it "Spin"). With `--ai` and an
`ANTHROPIC_API_KEY`, Claude searches the web for the last few days and writes a short
fantasy briefing per player. In VS Code, the `player-news` skill does the same with Copilot.

## Alerts

From ESPN's pending transactions: trade offers sent to you, your own offers waiting for an
answer, accepted trades in their review period (with the time they process) and pending
claims. From the chat service: direct messages you have not read.

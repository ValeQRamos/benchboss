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
| Out, suspended, injured reserve, bereavement or paternity leave | 0% |

## Lineup optimizer

For each day, benchboss assigns players to your league's starting slots (PG, SG, SF, PF, C,
G, F, UT, ...) to maximize the total expected points. It does not guess: a dynamic program
walks the slots one by one and keeps the best total for every set of players already used, so
the answer is the true optimum for your slot rules. Ties favor keeping a player where he
already is, so a day that is already right produces no moves. A player who cannot score that
day (no game, out, suspended) is never moved into a starting slot, even an empty one: he is
only left where he already is.

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
the rest is already in the live score. A starter whose game has tipped off keeps his slot, so
today's later games share only the slots that are still open. Players projected at zero (out,
suspended) do not count as games left.

This is the same method for both teams, so the comparison is fair even when ESPN's own
numbers are not available (ESPN does not publish a matchup projection for basketball).

## Workload

For each rostered player: games in the matchup week, games left from today, and the opponent
for each day (`@` means away). In daily leagues a four-game week is worth a lot more than a
two-game week at the same average.

A game only scores when the player is in a starting slot that day, so Workload also reads
your lineup for every day of the week. That is one roster read per day (up to seven at a
time), kept until you refresh. For days already played it is the lineup you had. For today
and later days it is the lineup ESPN has saved, which includes moves you already sent for
those days (for example with `optimize week`).

- A game he spends on your bench is drawn dim in parentheses, `(LAC)`. On a narrow screen the
  cells turn into dots: `●` a game in your lineup, `○` a game on your bench.
- **G** is his games this week, **In** the ones in your lineup, **Left** the ones from today on.
- The footer counts how many of your players have a game each day, against your starting
  spots. `13/10` means 13 players play and only 10 can start, so at least 3 games go to the
  bench. IR players do not count, and neither do days before a player joined your roster.
- If the daily reads fail, the grid falls back to plain opponents and **In** shows `-`.
- A player you dropped or traded away during the week stays as a last row marked `gone`,
  with only the days he was yours, so the games he played for you still add up in **In**.

Rows come in lineup order (starters by slot, then the bench, then IR, then anyone gone). `v` in the app, or
`--view games`, sorts by most games instead.

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
   go to the earlier day, because waiting risks losing the player. **G** counts his games
   from that day on.
4. The **suggested drop** is the player whose absence costs you the fewest points over the
   same days (often someone with few games left), chosen only among players projected below
   the free agent and only where the league's position limits allow the swap (for example a
   fifth center). His lost points are the **drop cost**. If nobody on your roster qualifies,
   no drop is suggested, because you would have to release a better player for him. With an
   open roster spot (fewer players than starters plus bench, not counting IR) nobody has to
   go and there is no drop cost.
5. **Net** = gain minus drop cost, for this week only. The list is sorted by net.

When the first pickup day can be today:

- If your league locks rosters at the day's first tip-off (ESPN's `FIRSTGAME_SCORINGPERIOD`),
  an add made after that joins your roster tomorrow and a drop takes effect tomorrow too, so
  today stops counting for every free agent once the first game of the day has started.
- In leagues that lock each player at his own game, today only counts if his game has not
  tipped off yet.
- Players on waivers start counting only after the waiver period (24 hours in most
  leagues). Before the season starts they are ready for opening night.

## Trade finder

1. **Positional profile**: for each team, the sum of projections at PG, SG, SF, PF and C. A
   player eligible at two positions counts half at each.
2. **Balance**: profile minus the league average. Positive is surplus, negative is need.
   `benchboss trades --needs` shows the whole table.
3. **Candidates**: you give a player whose main position is your surplus and their need; you
   get one whose main position is their surplus and your need (or the position you asked for
   with `--need`). Players who are out, suspended or on injured reserve are left out on both
   sides, and so are swaps of two players eligible at exactly the same positions, because
   they change neither team's profile.
4. **Fairness**: `1 - |difference in projection| / higher projection`. Ideas below 85% are
   dropped (`--fairness` changes it).
5. **Limits**: deals that would break the league's position limits (for example a maximum of
   four centers) are removed.
6. **Ranking**: fairness first, then how much the deal fixes both sides, then a small bonus
   when you get the slightly better player. At most two ideas per team and two per player you
   give, so the list stays varied.

Each idea comes with a short note you can send with `benchboss trade ... --msg`. It only
calls the deal "close in value" from 85% fairness up.

## Stat splits (Roster and Player finder)

ESPN keeps several stat lines for every player. benchboss asks for six of them and calls
them splits:

| Split | Column | What it is |
|---|---|---|
| `season` | Avg | This season so far |
| `l7`, `l15`, `l30` | L7, L15, L30 | The last 7, 15 and 30 days |
| `proj` | Proj | ESPN's projection for the season |
| `last` | Prev | Last season, the only real numbers before opening night |

For each split ESPN sends fantasy points per game, already scored with your league's
settings, and a per-game box score. FG% and FT% are worked out from made and attempted shots,
so they match the box score. A split with no games (every split but Proj and Prev in the
preseason) is left out.

In the Player finder, L7, L15 and L30 turn green when they run at least 15% and 2 points
above the season average (or the projection before any game), and red when they run that
far below. The app fetches the top 150 players of a pool from ESPN. When you sort by a split
or by Rost% and the pool was cut at 150, it asks ESPN again for the top 150 by that column, so
sorting free agents by L7 brings in the best free agents of the last 7 days.

## Playoff race

`benchboss playoffs` and the `y` screen play the rest of the regular season 5,000 times
(the scenario builder in the app uses 2,000 per change, so it keeps up with your keys).

**Expected points.** Each team gets a points-per-day rate. Its real points per day so far
are blended with what its roster projects; the real results weigh `days / (days + 21)`, so
after three weeks of games they count half. The roster projection comes in two flavors:

- **This week and next**: the next 14 days of the NBA schedule. Each day the best players
  with a game fill the starting spots (positions ignored), with today's injuries applied
  (the same discount as the lineup optimizer).
- **Later weeks**: the healthy roster. Every player not on IR at his projection, playing
  about every other day, minus 8% for games that do not fit in the starting slots. A player
  who is out today is not out in February.

**One simulated season.** First every team gets a level for the whole season, drawn around
1.0 with a 5% spread, because trades, injuries and waiver luck make a team better or worse
for weeks at a time. Without it the best rosters look nearly locked in from opening night. Then each matchup score is drawn around rate x days in that week x level,
with a 12% spread (a typical week to week swing in fantasy points). A week in progress keeps
its live score and only simulates the days left. Results you pick with `--pick` or the arrow
keys are fixed in every run.

**Seeding** follows ESPN. The top `playoffTeamCount` teams get in. In a league with divisions
the division winners are seeded first, then everyone else by record. Ties go to the league's
tiebreaker setting (head-to-head record, points for, division record or points against), then
head-to-head, points for, division record, points against and a coin flip.

**What you see.** Playoff odds are the share of seasons a team gets in; seed and division
title odds the same way; the projected record is the average final record. "Clinched" and
"eliminated" are worked out from the games left, with no dice. Clinched means no mix of the
open results can keep the team out; eliminated means none can get it in. That math is
conservative, so a team can make it in every simulated season and still show as alive.
ESPN's own odds (`currentSimulationResults.playoffPct`) are shown next to ours for reference;
ESPN does not publish how it gets them.

## News

`benchboss news` asks ESPN's public fantasy feed for every player on your roster at once and
shows RotoWire's blurb plus its analysis (ESPN labels it "Spin"). `--watch` does the same for
your ESPN watch list, and the app's news screen shows both, in two sections. With `--ai` and
an `ANTHROPIC_API_KEY`, Claude searches the web for the last few days and writes a short
fantasy briefing per player. In VS Code, the `player-news` skill does the same with Copilot.

## Alerts

From ESPN's pending transactions: trade offers sent to you, your own offers waiting for an
answer, accepted trades in their review period (with the time they process) and pending
claims. From the chat service: direct messages you have not read.

### Watch-list news

Your ESPN watch list lives on your team in the league (the same list as the star in the ESPN
app). benchboss checks the news feed for those players over the last 3 days and keeps what
you have already seen in `seen-news.json` in the config folder: a list of news ids per
league, the newest 500.

- The app checks 20 seconds after it opens and then every 5 minutes. Each new item becomes a
  toast and is marked as seen right away. A burst shows the newest 4 and one line for the
  rest.
- `benchboss alerts` lists the unseen items after the trades, claims and DMs, and does not
  mark them. `benchboss alerts --mark-read` marks exactly the items it shows.
- The first time a league is checked, news older than 24 hours counts as seen, so a fresh
  install does not dump three days of news on you.
- If the news feed is down, the other alerts still show.

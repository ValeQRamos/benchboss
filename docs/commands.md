# Command reference

Generated from the CLI by `python tools/gen_commands_doc.py`. Every command also
accepts the global flags `--json`, `--demo`, `--theme dark|light` and `--yes`.

Running `benchboss` with no command opens the interactive app (it needs a terminal).
With `--json`, write commands print one JSON result as well; without `--yes` they
send nothing and exit with code 10.

## Look

### `benchboss dash`

The dashboard: matchup, roster, workload, trash, standings.

```text
benchboss dash [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                      [--watch [SECONDS]]
```

| Option | Meaning |
|---|---|
| `--watch` | Keep it open and refresh (default every 60 s) |

### `benchboss matchup`

This week's matchup: live score, projected final, games left.

```text
benchboss matchup [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

### `benchboss roster`

Your roster: every stat split (season, last 7/15/30, projection, last season) and the box score.

```text
benchboss roster [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                        [--view VIEW]
```

| Option | Meaning |
|---|---|
| `--view` | The split for the box score: season (default), l7, l15, l30, proj, last |

### `benchboss activity`

Games per player this matchup week, day by day, and the ones on your bench.

```text
benchboss activity [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                          [--view VIEW]
```

| Option | Meaning |
|---|---|
| `--view` | Row order: lineup (default), games |

### `benchboss standings`

League table: record, points for and against, streaks, playoff odds.

```text
benchboss standings [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                           [--view VIEW]
```

| Option | Meaning |
|---|---|
| `--view` | Which table: league (default), divisions, moves |

### `benchboss playoffs`

Playoff race: odds, who is in or out, what-if scenarios.

```text
benchboss playoffs [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                          [--pick WINNER>LOSER] [--sims SIMS] [--view VIEW]
```

| Option | Meaning |
|---|---|
| `--pick` | Fix a result, e.g. --pick "Monstars>Tune Squad" (add @WEEK for a given week; repeat for more) |
| `--sims` | Simulated seasons (default 5000) |
| `--view` | Odds (default) or games, the matchups left |

## Find

### `benchboss trash`

Most valuable free agents for this week (points added, best day to grab).

```text
benchboss trash [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                       [-n N]
                       [pos]
```

| Option | Meaning |
|---|---|
| `pos` | PG SG SF PF C G F |
| `-n` | How many (default 10) |

### `benchboss players`

Player finder: free agents, rostered players or your watch list with every stat split.

```text
benchboss players [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                         [--from {fa,rostered,all,watch}] [--pos POS]
                         [--sort {proj,season,l7,l15,l30,last,own,change}]
                         [--view VIEW] [-n N]
                         [query ...]
```

| Option | Meaning |
|---|---|
| `query` | The start of a player's first, last or full name |
| `--from` | Free agents (default), players on a team, everyone, or your watch list |
| `--pos` | PG SG SF PF C G F |
| `--sort` | Rank by this split (fantasy points per game), % rostered or its change (default: the --view split, else proj) |
| `--view` | Which split's box score to show: season l7 l15 l30 proj last |
| `-n` | How many (default 50) |

### `benchboss fa`

Free agents by % rostered.

```text
benchboss fa [-h] [--json] [--demo] [--theme {dark,light}] [-y] [-n N]
                    [pos]
```

| Option | Meaning |
|---|---|
| `pos` | PG SG SF PF C G F |
| `-n` | How many (default 25) |

### `benchboss trending`

Free agents being added the most.

```text
benchboss trending [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                          [-n N]
```

| Option | Meaning |
|---|---|
| `-n` | How many (default 15) |

### `benchboss news`

Recent news and spins on your players, your watch list (--watch) or the players you name.

```text
benchboss news [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                      [--watch] [--days DAYS] [--ai]
                      [players ...]
```

| Option | Meaning |
|---|---|
| `players` | Player names; default: your roster |
| `--watch` | Your watch-list players instead of your roster |
| `--days` | How many days back (default 5) |
| `--ai` | AI briefing with web search (needs ANTHROPIC_API_KEY) |

### `benchboss trades`

Trade finder: fair 1-for-1 deals that fix positional needs.

```text
benchboss trades [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                        [--need {PG,SG,SF,PF,C,pg,sg,sf,pf,c}] [--with TEAM]
                        [--fairness FAIRNESS] [--needs] [-n N]
```

| Option | Meaning |
|---|---|
| `--need` | Only deals that bring you this position |
| `--with` | Only this team or manager |
| `--fairness` | Minimum value match 0-1 (default 0.85) |
| `--needs` | Show every team's positional surplus and needs |
| `-n` | How many ideas (default 8) |

### `benchboss alerts`

Trade offers, accepted trades, pending claims, unread DMs and new news on your watch-list players.

```text
benchboss alerts [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                        [--mark-read]
```

| Option | Meaning |
|---|---|
| `--mark-read` | Mark the watch list news shown as read, so it does not show again |

## Act (writes to ESPN, always asks first)

### `benchboss optimize`

Set the best lineup: today, tomorrow, week, or a date.

```text
benchboss optimize [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                          [--dry-run] [-q]
                          [when]
```

| Option | Meaning |
|---|---|
| `when` | Today (default), tomorrow, week, 11-04, 2026-11-04 |
| `--dry-run` | Show the plan, send nothing |
| `-q, --quiet` | Only print the final result |

### `benchboss add`

Sign a free agent or put in a waiver claim.

```text
benchboss add [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                     [--dry-run] [--drop DROP] [--bid BID]
                     player
```

| Option | Meaning |
|---|---|
| `player` | The free agent or waiver player to add |
| `--dry-run` | Show the move, send nothing |
| `--drop` | Player to release in the same move |
| `--bid` | FAAB bid, if your league uses a budget |

### `benchboss drop`

Release a player.

```text
benchboss drop [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                      [--dry-run]
                      player
```

| Option | Meaning |
|---|---|
| `player` | The player on your roster to release |
| `--dry-run` | Show the move, send nothing |

### `benchboss trade`

Send a trade offer.

```text
benchboss trade [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                       --give PLAYER --get PLAYER [--msg MSG] [--dry-run]
```

| Option | Meaning |
|---|---|
| `--give` | Your player to send (repeat for more) |
| `--get` | Their player you want (repeat for more, all from one team) |
| `--msg` | Note the other manager will see |
| `--dry-run` | Show the offer, send nothing |

### `benchboss watch`

Your ESPN watch list: list it, or add / remove a player.

```text
benchboss watch [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                       [--dry-run]
                       [{list,add,remove}] [player ...]
```

| Option | Meaning |
|---|---|
| `action` | Default: list |
| `player` | The player to add or remove |
| `--dry-run` | Show the change, send nothing |

### `benchboss chat`

Read or post in the league chat, or a DM with --to.

```text
benchboss chat [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                      [--to TEAM_OR_NAME] [--dry-run] [-n N]
                      [text]
```

| Option | Meaning |
|---|---|
| `text` | Message to post; leave it out to read the chat |
| `--to` | Direct message instead of the league chat |
| `--dry-run` | Show the message, send nothing |
| `-n` | How many messages to show (default 15) |

## Account

### `benchboss setup`

First-run wizard: cookies, league, team, colors.

```text
benchboss setup [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

### `benchboss login`

Save your ESPN cookies (from Chrome on macOS, or pasted).

```text
benchboss login [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                       [--chrome] [--manual]
```

| Option | Meaning |
|---|---|
| `--chrome` | Import from Google Chrome (macOS) |
| `--manual` | Paste espn_s2 and SWID by hand |

### `benchboss logout`

Forget the saved cookies.

```text
benchboss logout [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

### `benchboss status`

Show config and check the connection to ESPN.

```text
benchboss status [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                        [--offline]
```

| Option | Meaning |
|---|---|
| `--offline` | Do not call ESPN |

### `benchboss app`

Open the interactive app (same as running benchboss with no command).

```text
benchboss app [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

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

Your roster with slots, injuries, averages and projections.

```text
benchboss roster [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

### `benchboss activity`

Games per player this matchup week, day by day.

```text
benchboss activity [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

### `benchboss standings`

League table.

```text
benchboss standings [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

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

Recent news and spins on your players (or on the players you name).

```text
benchboss news [-h] [--json] [--demo] [--theme {dark,light}] [-y]
                      [--days DAYS] [--ai]
                      [players ...]
```

| Option | Meaning |
|---|---|
| `players` | Player names; default: your roster |
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

Trade offers, accepted trades, pending claims, unread DMs.

```text
benchboss alerts [-h] [--json] [--demo] [--theme {dark,light}] [-y]
```

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

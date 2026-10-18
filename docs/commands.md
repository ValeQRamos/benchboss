# Command reference

Generated from the CLI by `python tools/gen_commands_doc.py`. Every command also
accepts the global flags `--json`, `--demo`, `--theme dark|light`,
`--layout auto|compact|full` and `--yes`.

Running `benchboss` with no command opens the interactive app (it needs a terminal).
With `--json`, write commands print one JSON result as well; without `--yes` they
send nothing and exit with code 10.

## Look

### `benchboss dash`

The dashboard: matchup, roster, workload, trash, standings.

```text
benchboss dash [-h] [--json] [--demo] [--theme {dark,light}]
                      [--layout {auto,compact,full}] [-y] [--watch [SECONDS]]
```

| Option | Meaning |
|---|---|
| `--watch` | Keep it open and refresh (default every 60 s) |

### `benchboss matchup`

This week's matchup: live score, projected final, games left.

```text
benchboss matchup [-h] [--json] [--demo] [--theme {dark,light}]
                         [--layout {auto,compact,full}] [-y]
```

### `benchboss roster`

Your roster: every stat split (season, last 7/15/30, projection, last season) and the box score.

```text
benchboss roster [-h] [--json] [--demo] [--theme {dark,light}]
                        [--layout {auto,compact,full}] [-y] [--view VIEW]
```

| Option | Meaning |
|---|---|
| `--view` | The split for the box score: season (default), l7, l15, l30, proj, last |

### `benchboss activity`

Games per player this matchup week, day by day, and the ones on your bench.

```text
benchboss activity [-h] [--json] [--demo] [--theme {dark,light}]
                          [--layout {auto,compact,full}] [-y] [--view VIEW]
```

| Option | Meaning |
|---|---|
| `--view` | Row order: games (default), lineup |

### `benchboss standings`

League table: record, points for and against, streaks, playoff odds.

```text
benchboss standings [-h] [--json] [--demo] [--theme {dark,light}]
                           [--layout {auto,compact,full}] [-y] [--view VIEW]
```

| Option | Meaning |
|---|---|
| `--view` | Which table: league (default), divisions, moves |

### `benchboss playoffs`

Playoff race: odds, who is in or out, what-if scenarios.

```text
benchboss playoffs [-h] [--json] [--demo] [--theme {dark,light}]
                          [--layout {auto,compact,full}] [-y]
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
benchboss trash [-h] [--json] [--demo] [--theme {dark,light}]
                       [--layout {auto,compact,full}] [-y] [-n N]
                       [pos]
```

| Option | Meaning |
|---|---|
| `pos` | PG SG SF PF C G F |
| `-n` | How many (default 10) |

### `benchboss players`

Player finder: free agents, rostered players or your watch list with every stat split.

```text
benchboss players [-h] [--json] [--demo] [--theme {dark,light}]
                         [--layout {auto,compact,full}] [-y]
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
benchboss fa [-h] [--json] [--demo] [--theme {dark,light}]
                    [--layout {auto,compact,full}] [-y] [-n N]
                    [pos]
```

| Option | Meaning |
|---|---|
| `pos` | PG SG SF PF C G F |
| `-n` | How many (default 25) |

### `benchboss trending`

Free agents being added the most.

```text
benchboss trending [-h] [--json] [--demo] [--theme {dark,light}]
                          [--layout {auto,compact,full}] [-y] [-n N]
```

| Option | Meaning |
|---|---|
| `-n` | How many (default 15) |

### `benchboss news`

Recent news and spins on your players or your watch list (--watch), or the latest news on any NBA player you name.

```text
benchboss news [-h] [--json] [--demo] [--theme {dark,light}]
                      [--layout {auto,compact,full}] [-y] [--watch]
                      [--days DAYS] [-n N] [--ai]
                      [players ...]
```

| Option | Meaning |
|---|---|
| `players` | Any NBA player (a close spelling works); default: your roster |
| `--watch` | Your watch-list players instead of your roster |
| `--days` | How many days back (default 5; a named player shows his latest news whatever the date unless you give --days) |
| `-n` | How many of a named player's latest items to show (default 10) |
| `--ai` | AI briefing with web search (needs ANTHROPIC_API_KEY) |

### `benchboss trades`

Trade finder: fair 1-for-1 deals that fix positional needs.

```text
benchboss trades [-h] [--json] [--demo] [--theme {dark,light}]
                        [--layout {auto,compact,full}] [-y]
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
benchboss alerts [-h] [--json] [--demo] [--theme {dark,light}]
                        [--layout {auto,compact,full}] [-y] [--mark-read]
```

| Option | Meaning |
|---|---|
| `--mark-read` | Mark the watch list news shown as read, so it does not show again |

## Act (writes to ESPN, always asks first)

### `benchboss optimize`

Set the best lineup: today, tomorrow, week, or a date.

```text
benchboss optimize [-h] [--json] [--demo] [--theme {dark,light}]
                          [--layout {auto,compact,full}] [-y] [--dry-run] [-q]
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
benchboss add [-h] [--json] [--demo] [--theme {dark,light}]
                     [--layout {auto,compact,full}] [-y] [--dry-run]
                     [--drop DROP] [--bid BID]
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
benchboss drop [-h] [--json] [--demo] [--theme {dark,light}]
                      [--layout {auto,compact,full}] [-y] [--dry-run]
                      player
```

| Option | Meaning |
|---|---|
| `player` | The player on your roster to release |
| `--dry-run` | Show the move, send nothing |

### `benchboss trade`

Send a trade offer.

```text
benchboss trade [-h] [--json] [--demo] [--theme {dark,light}]
                       [--layout {auto,compact,full}] [-y] --give PLAYER
                       --get PLAYER [--msg MSG] [--dry-run]
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
benchboss watch [-h] [--json] [--demo] [--theme {dark,light}]
                       [--layout {auto,compact,full}] [-y] [--dry-run]
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
benchboss chat [-h] [--json] [--demo] [--theme {dark,light}]
                      [--layout {auto,compact,full}] [-y] [--to TEAM_OR_NAME]
                      [--dry-run] [-n N]
                      [text]
```

| Option | Meaning |
|---|---|
| `text` | Message to post; leave it out to read the chat |
| `--to` | Direct message instead of the league chat |
| `--dry-run` | Show the message, send nothing |
| `-n` | How many messages to show (default 15) |

## Auto-swap (arming a player is your yes; the monitor makes the change)

### `benchboss autoswap`

Auto-swap: arm players who may turn healthy before their game, so benchboss starts them by itself.

```text
benchboss autoswap [-h] [--json] [--demo] [--theme {dark,light}]
                          [--layout {auto,compact,full}] [-y] [--today]
                          [--notify-only] [--dry-run] [-n N]
                          [{list,add,remove,clear,pause,resume,log}]
                          [player ...]
```

| Option | Meaning |
|---|---|
| `action` | Default: list |
| `player` | The player to add or remove |
| `--today` | Add: the mark ends tonight (default: the end of the matchup week) |
| `--notify-only` | Add: only tell me when he turns healthy, change nothing (no question) |
| `--dry-run` | Add: show what would happen, arm nothing |
| `-n` | Log: how many lines (default 20) |

### `benchboss monitor`

The background process: watches armed and watch-list players, makes the auto-swaps (trial mode unless --live) and sends the notifications.

```text
benchboss monitor [-h] [--json] [--demo] [--theme {dark,light}]
                         [--layout {auto,compact,full}] [-y] [--once]
                         [--dry-run] [--live] [--notify BACKENDS]
                         [--notify-test] [--simulate PLAYER=STATUS]
```

| Option | Meaning |
|---|---|
| `--once` | One read and one round, then exit |
| `--dry-run` | Print what it sees and would do: no notification, no state, no log |
| `--live` | Send the changes to ESPN (needs --yes or a yes at the prompt) |
| `--notify` | Mac, ntfy, cmd, log, comma separated (secrets come from the environment, never from here) |
| `--notify-test` | Send one test note through the backends and exit |
| `--simulate` | Pretend a status, e.g. --simulate "Dyson Daniels=ACTIVE" (trial, --dry-run or --demo only; repeat for more) |

## Account

### `benchboss setup`

First-run wizard: cookies, league, team, colors.

```text
benchboss setup [-h] [--json] [--demo] [--theme {dark,light}]
                       [--layout {auto,compact,full}] [-y]
```

### `benchboss login`

Save your ESPN cookies (from Chrome on macOS, or pasted), or send them to a server with --to.

```text
benchboss login [-h] [--json] [--demo] [--theme {dark,light}]
                       [--layout {auto,compact,full}] [-y] [--chrome]
                       [--manual] [--to [USER@]HOST] [--identity FILE]
                       [--ssh-port PORT] [--dry-run]
```

| Option | Meaning |
|---|---|
| `--chrome` | Import from Google Chrome (macOS) |
| `--manual` | Paste espn_s2 and SWID by hand |
| `--to` | Send the cookies over SSH to a server running benchboss, instead of saving them here |
| `--identity` | With --to: the SSH key file to use |
| `--ssh-port` | With --to: the SSH port |
| `--dry-run` | With --to: show what would be sent, send nothing |

### `benchboss logout`

Forget the saved cookies.

```text
benchboss logout [-h] [--json] [--demo] [--theme {dark,light}]
                        [--layout {auto,compact,full}] [-y]
```

### `benchboss status`

Show config and check the connection to ESPN.

```text
benchboss status [-h] [--json] [--demo] [--theme {dark,light}]
                        [--layout {auto,compact,full}] [-y] [--offline]
```

| Option | Meaning |
|---|---|
| `--offline` | Do not call ESPN |

### `benchboss app`

Open the interactive app (same as running benchboss with no command).

```text
benchboss app [-h] [--json] [--demo] [--theme {dark,light}]
                     [--layout {auto,compact,full}] [-y]
```

### `benchboss web`

Serve the app in a browser (needs the web extra); put a proxy with a login in front of it.

```text
benchboss web [-h] [--json] [--demo] [--theme {dark,light}]
                     [--layout {auto,compact,full}] [-y] [--host HOST]
                     [--port PORT] [--url URL] [--allow-remote]
                     [--password-file FILE] [--login-user NAME]
                     [--github-client-id ID] [--github-users LOGINS]
                     [--session-hours HOURS]
```

| Option | Meaning |
|---|---|
| `--host` | Address to listen on (default 127.0.0.1) |
| `--port` | Port to listen on (default 8000) |
| `--url` | The public address people type, for example https://bb.example.com (behind a proxy) |
| `--allow-remote` | Allow --host to be an address other computers can reach |
| `--password-file` | Turn on the sign in page with the password in this file (chmod 600, 12 characters or more) |
| `--login-user` | The user name for the password (default owner) |
| `--github-client-id` | Turn on Sign in with GitHub (also needs --github-users, --url and the BENCHBOSS_GITHUB_CLIENT_SECRET environment variable) |
| `--github-users` | GitHub logins (or numeric ids) allowed in, comma separated |
| `--session-hours` | How long a sign in lasts (default 12) |

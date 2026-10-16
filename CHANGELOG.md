# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.2] - 2026-10-16

### Added

- **Player finder** (`p` in the app, `benchboss players`): free agents, players on a team,
  your watch list or everyone in one table, with a position filter, every stat split, search,
  sorting and a detail card with the player's news.
- **ESPN watch list**: press space in the Player finder to star or unstar a player. This is
  the one change the app sends without an Apply step, on purpose: the watch list is private,
  the change is instant, and the same key undoes it, like the star in the ESPN app. From the
  CLI, `benchboss watch` lists it and `benchboss watch add|remove "Player"` changes it; like
  every other write, it asks first (`--yes` skips the question, `--dry-run` sends nothing).
- **Watch list news**: the app shows a notification for every new spin on a watch-list player
  (it checks every 5 minutes). `benchboss alerts` lists them, `alerts --mark-read` marks them
  as read, and `benchboss news --watch` shows the news on your watch list. The Player news
  screen has a section for your roster and one for your watch list.
- **Playoff race** (`y` in the app, `benchboss playoffs`): playoff odds from simulated seasons
  seeded like ESPN (division winners first, then the tiebreakers), the games left, and a
  scenario builder: pick the winners with the arrow keys and watch the odds move. In the CLI,
  `--pick "Winner>Loser"` (add `@WEEK` for a given week) fixes a result.
- **Stat splits**: every player carries season, last 7, 15 and 30 days, ESPN's projection and
  last season, each with the per-game box score. The Roster screen shows them side by side
  with the box score of one split.
- **Views**: `v` in the app and `--view` in the CLI switch a screen between its views (the
  roster's splits, the standings tables, the playoff odds or games left, the workload order).

### Changed

- **Standings**: points against, the difference, win percentage, games back, the streak,
  ESPN's playoff odds, clinch tags and a playoff line, plus division tables and every team's
  moves (waiver order, adds, drops and trades).
- **Workload** shows each player's positions, today's slot and the games he spends on your
  bench (from the lineup ESPN has saved for each day), and a footer that counts games against
  your starting spots.
- **Best trash** is redone to read at a glance, with a strip of games for each pick.
- **Dashboard**: a bigger news card with watch-list news starred, a pixel-art basketball in
  the header instead of the emoji, and your playoff odds.
- **Optimize week**: one block per day with its moves and lineup, and a line that explains
  the injury discount (day-to-day players count 75%).
- The demo league (`--demo`) has box scores, records, divisions and a watch list, frozen on
  Wednesday, November 4, 2026.

## [1.0.1] - 2026-10-15

### Fixed

#### Lineups and Optimize

- The app could send the week's lineup with no plan on screen: after a terminal resize or
  ctrl+t on the Optimize screen, the plan stayed armed behind hidden buttons and the next
  Enter sent it. A plan is now sent only from a visible Apply button.
- After Apply in the app, focus no longer lands on the hidden Cancel button. The arrow keys
  keep working, and the next Enter no longer says "Cancelled. Nothing was sent." after the
  moves were sent.
- The optimizer no longer moves players who have no game into empty slots or shuffles them
  around. A day with no games, or a lineup that is already right, now produces no moves and
  says so, and no extra changes are sent to ESPN.
- The projected final and games left no longer count too many of today's games once games
  tip off: starters whose game has started keep their slots.
- Players on bereavement or paternity leave now count as out instead of at full value, and
  their status is no longer shown cut off.
- `optimize week --yes`: when ESPN could not be read for a later day, the days already sent
  disappeared from the report. Every day now gets its own line, and the final message says
  how many days were not set and whether anything was sent at all (it used to say "the
  others were sent" even when nothing was).
- The week preview takes into account that a move on ESPN carries forward to the next days,
  so it no longer repeats a move on several days or promises more moves than Apply sends.
- "Your lineup is already optimal for day." and the other optimize messages now read as
  proper sentences.
- After Apply in the app, the Roster and Optimize today screens read the new lineup from
  ESPN instead of showing the old one and offering the same moves again.
- Pressing t in the app before the season starts explains when the season starts and how to
  set week 1, instead of showing command line date syntax as an error.

#### Best trash (free agents)

- In leagues that lock rosters at the day's first game, a pickup made after that tip-off now
  starts counting the next day. Before, picks could promise points from a game ESPN would
  not count for you.
- No drop is charged when you have an open roster spot, for example right after moving
  someone to IR.
- The suggested drop comes from the players who project lower for the season than the free
  agent, so a star who is out for a few days is no longer suggested as the drop. When nobody
  projects lower, the drop is your lowest projected player and the pick is marked `*` as a
  one-week stream instead of an upgrade.
- The games count (G) starts on the suggested pickup day, so it matches the points shown.
- Before the season, players on waivers no longer lose their opening night game.
- Late on the last day of a matchup week, the dashboard no longer lists free agents as
  "+0 pts · 0 games", and a negative net shows with the right sign.
- The Best trash table fits an 80-column terminal: the Net and G columns are no longer cut
  off or dropped.
- The app is readable in narrower terminals: Best trash, Workload and Roster are no longer
  clipped below about 112 columns.

#### Trades

- The trade finder no longer proposes getting or giving players who are out, suspended or on
  IR, and the ready-to-send note says "close in value" only when the values are close.
- Swaps between players with the same position eligibility are no longer pitched as fixing a
  positional need.
- When no trade fits, the advice is right: it says when you already have the most players
  allowed at a position, `--with` your own team says that it is your team, and a name that
  matches several teams says "teams" instead of "players".

#### ESPN connection and errors

- A dropped connection, or a cut-off or non-JSON reply from ESPN, no longer crashes
  `optimize`, `dash --watch` or the app's Apply with a Python traceback. You get a network
  error instead, and after a write it tells you to check ESPN before trying again.
- Connections to ESPN now trust your operating system's certificates and `SSL_CERT_FILE` as
  well as the bundled ones, so benchboss works behind company networks that inspect HTTPS.
- `add`, `drop`, `trade` and `chat` exit with code 4 when ESPN answers with a FAILED status
  (for example a roster lock or an undroppable player) instead of reporting success.
- On Windows, redirecting or piping the output (for example `benchboss roster > out.txt`) no
  longer crashes on characters the console cannot encode. Before, `optimize week -q --yes`
  could send every day and then fail on its last line.
- A non-numeric `BENCHBOSS_LEAGUE_ID`, `BENCHBOSS_TEAM_ID` or `BENCHBOSS_SEASON`, a
  `config.json` that is not a JSON object, and Ctrl-D at a prompt now give a short message
  instead of a traceback.
- A team id that is not in the league (for example the saved one after switching leagues
  with `BENCHBOSS_LEAGUE_ID`) now stops with a clear message instead of a traceback.
- `benchboss status --json` includes the reason when the connection to ESPN fails, so
  scripts can tell expired cookies from a network problem.

#### Command line

- `optimize --json` follows the same rules as the other writes: without `--yes` it exits with
  code 10 because nothing was applied, and with `--yes` it prints JSON instead of text.
- Before the season and after it ends, `roster`, `roster --json` and the app's Roster and
  Workload screens no longer mark opening night (or the last day) as today.
- `benchboss --demo chat` works instead of failing with "this league has no chat topic yet".
- A chat message made only of spaces is refused instead of posting a blank message to the
  league.
- `-n` must be 1 or more: `fa -n 0` no longer prints the whole player pool, and `trash -n -3`
  no longer shows almost everything.
- `news --days N` shows only the last N days (it showed up to a day more).
- Pending waiver claims, and waiver and drop cards in the chat, show player names instead of
  ESPN ids.
- `--demo` no longer touches your real account: `login`, `logout` and `setup` are off in demo
  mode, and `--demo status` describes the demo league instead of your real configuration.
- Running `benchboss` with no command (or with `--json`) where there is no terminal, for
  example from a script or an agent, exits with a hint instead of hanging.
- `dash --watch` in a short pane says that more cards are below instead of cutting them off
  without a word.
- The command line dashboard no longer says "n for more" next to the news, a key that only
  works in the app.
- Every option in `--help` and in docs/commands.md now has a description.

#### Setup and settings

- `setup` no longer crashes when you type something other than one of the numbers shown for
  the league or the team.
- On macOS, `setup` lets you paste the cookies when importing them from Chrome fails,
  instead of quitting.
- `setup` no longer saves the current season in `config.json`, so benchboss moves to the next
  season on its own.
- Pressing ctrl+t in the app saves only the theme. It used to also save one-off
  `BENCHBOSS_LEAGUE_ID`, `BENCHBOSS_TEAM_ID` and `BENCHBOSS_SEASON` values into
  `config.json` for good.
- In the app, resizing the terminal or pressing ctrl+t on a screen other than the dashboard
  no longer replaces it with an old dashboard, and ctrl+t redraws the current screen in the
  new colors.
- In the app, r reloads your cookies and settings, so "run `benchboss login`, then press r"
  works without restarting the app.

#### Install and packaging

- The install commands in the README no longer need git (they download a zip), and the
  Windows steps let you use uv in the same PowerShell window.
- `install.sh` stops with a clear message when uv cannot be downloaded, finds uv when
  `UV_INSTALL_DIR` or `XDG_BIN_HOME` is set, and uses a Python 3.10 or newer that you already
  have instead of always downloading 3.12.
- Building from source asks for the hatchling version it really needs (1.27 or newer).
- VS Code: the agent no longer runs `news --ai` (a paid call) or `dash --watch` (it never
  exits) without asking, `-y` always asks just like `--yes`, and chat reads and `--dry-run`
  previews no longer ask every time.
- The bug report template and CONTRIBUTING.md no longer ask you to paste `status` output in
  public, since it shows your league id, your league and team names and your home folder.

### Changed

- The version is now 1.0.1 and the package is marked Production/Stable. The first public
  release, shared as 1.0.0, reported itself as 0.1.0.
- If you ran `benchboss setup` with 1.0.0, your `config.json` has `"season": 2027`. Set it to
  `null`, or run `benchboss setup` again, so benchboss switches to the 2028 season by itself
  on August 1, 2027.
- With `--json`, the write commands print a JSON result instead of text.
- `trash --json` has new `needs_drop` and `drop_projects_higher` fields. The suggested drop
  is the cheapest player this week among those projected lower than the free agent; when
  nobody projects lower it is your lowest projected player and the pick is flagged as a
  one-week stream (marked `*` in the table). `drop` is null only when you have an open spot.

## [1.0.0] - 2026-10-15

### Added

- Interactive app with a menu and one-key screens: dashboard, optimize today, optimize week,
  workload, best trash, player news, trade finder, inbox, standings, roster. Dark and light
  themes.
- `benchboss dash --watch`: live dashboard that fits a narrow side terminal.
- Exact daily lineup optimizer for today, tomorrow, a date or the rest of the matchup week,
  with dry runs and a single confirmation.
- Trash scout: free agents ranked by points added this week, best pickup day, suggested drop.
- Trade finder: fair 1-for-1 ideas from positional surplus and needs, respecting position limits.
- Player news from ESPN's fantasy feed (RotoWire blurbs and spins), optional AI briefing.
- Alerts: trade offers, accepted trades in review, pending claims, unread DMs.
- League chat and DMs, add, drop and trade offers from the command line.
- `--json` on every read command, `--demo` mode with a fictional league, setup wizard with
  league discovery and Chrome cookie import on macOS.
- AGENTS.md, Copilot instructions, skills and a custom agent for AI-assisted use.
- ESPN Fantasy Basketball API reference in `docs/api/`.

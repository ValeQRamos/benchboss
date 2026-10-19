# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.5] - 2026-10-19

Setting up phone alerts no longer needs a text editor, and you choose which alerts you get.

### Added

- A Settings screen (`e` in the app) with an Alerts tab. It sets up [ntfy](https://ntfy.sh)
  pushes (topic, server and token; New makes a random topic, Copy puts it on the clipboard,
  Test sends a note, Off turns ntfy off) and writes the private `notify.env` and
  `notify.backends` in `config.json`. Nothing is saved or sent in the demo.
- Choose what `benchboss monitor` notifies you about, in every backend: lineup changes,
  watch-list players turning healthy, armed players turning healthy, and problems (cookies
  expired, ESPN unreachable, live mode refused). The boxes under "Notify me about" save at once
  to `notify.alerts` in `config.json`. Without it all four stay on, as before. The Inbox and
  the log still show everything. Restart the monitor to pick up a change.

### Fixed

- ntfy pushes failed with "certificate verify failed" on a python.org build of Python on
  macOS, which ships without root certificates. They now use the same certificates as the ESPN
  and news requests.

## [1.0.4] - 2026-10-18

Most of this release comes from the requests that showed up the night 1.0.3 went out: start a
player on his own when he turns healthy late, run benchboss from a phone, and read news on
any player. Auto-swap ships in trial mode. It tells you what it would have done and changes
nothing on ESPN until you turn live mode on.

### Added

- Auto-swap. Arm a player who is day-to-day or out (`u` in the app, or
  `benchboss autoswap add`). If he turns healthy at least 3 minutes before his game,
  benchboss starts him and benches the starter with the lowest projection that day whose game
  has not started. Nobody else in your lineup moves. Arming shows what would happen and asks
  first, and that yes covers that one player until Sunday (or until tonight with `--today`).
  `autoswap remove`, `clear` and `pause` take it back at any time.
  [docs/autoswap.md](docs/autoswap.md) has the details.
- `benchboss monitor`, the process that does the watching. It starts in trial mode: you get a
  note like "benchboss would have started Dyson Daniels at G and benched Scotty Pippen Jr."
  and nothing is sent. `--live --yes` makes the changes for real. Leave it off until a week of
  trial notes looks right to you, since nobody knows yet how often ESPN flips a status before
  tip-off rather than after. Only one monitor runs per league, it saves what it is about to
  send before sending it, and it reads your lineup again afterwards to check that ESPN took
  the change. `--once` runs a single round (for cron), and `--once --dry-run` prints what it
  sees and saves or sends nothing.
- Notifications from the monitor: the Mac's Notification Center, [ntfy](https://ntfy.sh)
  (free pushes to iPhone or Android) or a command of your own, for Telegram, Pushover or
  anything else. Secrets come from the environment or a private `notify.env`, never from the
  command line. `benchboss monitor --notify-test` sends a test note.
- A note when a player on your ESPN watch list turns healthy. The app's Inbox and
  `benchboss alerts` also show what the monitor found in the last 24 hours.
- A log of every lineup change (Apply in the app, `optimize`, the monitor) and every
  auto-swap decision, in `logs/lineup-YYYY-MM.jsonl`. `benchboss autoswap log` prints it.
- Player news has two tabs, `1` Roster and `2` Watch list, and `[` `]` change how far back it
  looks (1 to 30 days). `/` searches any NBA player, on a roster or not, and shows his 10
  latest items however old they are; `.` brings 10 more. From a terminal it's
  `benchboss news "Ben Simmons"` (`-n` for more items, `--days` for a window). A name that
  fits several players lists them and exits with code 2.
- A compact layout for phones and small windows. Under 80 columns or 30 rows the menu opens
  as a page of its own with `m`, a one-row key bar replaces the footer and always shows
  `m menu`, and tapping a key on the bar works like pressing it. A tap never sends anything to
  ESPN. `--layout compact` or `--layout full` (also `BENCHBOSS_LAYOUT` or `"layout"` in
  `config.json`) forces one or the other.
- Exit code 5: a safety check refused a lineup change and nothing was sent.
- `tools/responsive.py` runs the demo app at phone, landscape and laptop sizes and saves the
  text of every screen, so anyone changing the UI can check the small sizes.

### Changed

- Player finder on a phone. The columns that seemed to move around were the table scrolling
  itself sideways until the selected split was the last column, and it never scrolled back
  when you turned the phone. In the compact layout the split you pick sits right after the
  name, the table starts at the left edge again whenever the window changes size, and a
  column that does not fit whole is left out instead of showing as "Pro" or "3". With the
  keyboard up the filters fold into one line so the rows stay on screen.
- Optimize: a player whose game starts within 3 minutes keeps his slot, even while ESPN still
  shows him unlocked. On the bench his reason reads "locked, tipped 8:00 PM".
- Workload drops the bench section. Starters and bench share one list, since the cells
  already show who sat each day, and the default order is now most games first. `v` (or
  `--view lineup`) puts them in today's lineup order.
- Playoff race: more than 5 weeks out, the screen says the odds still move a lot and that
  picks matter most in the final 5 weeks (`e` jumps there). `,` and `.` change the week in
  the builder, for keyboards without Page Up and Page Down.
- The dashboard goes to two columns from 78 columns (it was 92), so a 120-column window with
  the menu open shows the cards side by side. The pixel ball only shows in windows with 34
  rows or more.
- Optimize, Roster and Best trash fit a phone: the day header, the injury math and the
  `add` command no longer break in the middle.
- Trade ideas put give, get and fairness on their own lines when a deal does not fit on one.
- The popup for watch-list news says where to read it: "press n, then 2".
- JSON that scripts may notice. Existing keys keep their meaning:
  - `optimize --json` rows add `frozen` (players who keep their slot, and why), `outcome`
    and `guards` (the safety checks that stopped a day).
  - `alerts --json` can have `healthy` and `autoswap` items from the monitor, with `player`
    and `at`.
  - `playoffs --json` adds `final_stretch_from`, the first week of the final 5.
  - New: `autoswap list --json`, `autoswap log --json` and `monitor --once --json`.

### Fixed

- Playoff race: the first view ran 5,000 seasons, but each pick in the builder ran 2,000
  against a separate 2,000-season base. A team could drop from 47% to 45% and the +/- column
  showed no change. Every view and every pick now plays the same 5,000 seasons, and +/- is
  measured against the odds the screen opened with. A pick still takes about half a second
  on the demo league.
- A division title only guarantees a playoff spot when the league has at least as many spots
  as divisions. With fewer, only the best division winners get in, the way ESPN seeds them.
- `add`, `drop` and `trade` printed "ESPN: UNKNOWN" and exited with 0 when ESPN's answer had
  no status. They now exit with 4 and tell you to check the league on ESPN before trying again.
- News over a long window showed at most the newest 200 items per batch of players, because
  ESPN counts video items toward that limit. benchboss now asks for the next page until the
  window is covered.

## [1.0.3] - 2026-10-16

A small patch on top of 1.0.2: a better ball and the loose ends the 1.0.2 audit left.

### Added

- `activity --json` rows have an `on_roster` key, false for a player who left your roster
  during the week (see Workload below).

### Changed

- New pixel ball on the dashboard and in the README. It's bigger (15 by 15 pixels), has a
  shine and a shaded side, and its seams curve the way they do on a real ball. It also gets
  more room next to the team name. The app's top bar shows a round dot in the ball's color,
  since one row of text is too short for a pixel ball.
- Workload: a player you dropped or traded away this week stays at the bottom, marked
  `gone`, with the games he played for you, so `In` and the daily counts add up.
- Standings shows ESPN's own clinch tags, combined ones included (`yz` is division and bye,
  `*z` top seed and bye).
- The demo league's days already played get the lineup a manager setting it every morning
  would have had, so Workload shows a few bench games instead of one lineup copied to every
  day.

### Fixed

- Budget waivers (FAAB) are detected the way ESPN's own app does it, from
  `isUsingAcquisitionBudget`. In a league with a budget, a claim on a player on waivers asks
  for `--bid` (at least the league minimum), and in a league without one `--bid` is refused
  instead of being sent.
- Player finder: the table ends on the last column that fits, so a column cut off at the
  right edge no longer shows a stray digit.

## [1.0.2] - 2026-10-16

Most of this release answers the feature request in
[issue #1](https://github.com/ValeQRamos/benchboss/issues/1): positions and the bench on
Workload, more stats than the projection, a way to find players, and the playoff race. The
rest is a pass over every screen so they read better, from 46 columns up, and the fixes from
an audit of all of it before shipping.

### Added

- Player finder (`p` in the app, `benchboss players`). Free agents, players on a team, your
  watch list or everyone in one table, with fantasy points per game for every split (season,
  last 7, 15 and 30 days, ESPN's projection, last season) and the box score of the split you
  pick. Filter by position, search by name (the start of a first or last name, like ESPN),
  sort by any column. Enter opens a card with every split and the player's latest news.
- Your ESPN watch list. Space in the finder stars a player. On the command line,
  `benchboss watch` lists it and `benchboss watch add|remove` changes it (asks first,
  `--dry-run` works, and a name that fits two players is an error, not a guess). ESPN caps
  the list at 50 players, and benchboss refuses the 51st without sending anything.
- News on watch-list players. The app pops up each new item once (it checks every 5
  minutes), `benchboss news --watch` lists them, and `benchboss alerts` keeps them until you
  run `benchboss alerts --mark-read`. A popup does not count as read. Starring a player does
  not dump his last 3 days of news on you. What you have seen is kept in `seen-news.json`,
  what already popped up in `toasted-news.json`, both in the config folder.
- Playoff race (`y`, `benchboss playoffs`). Playoff, seed and division title odds from 5,000
  simulated seasons, seeded the way ESPN does it (division winners first, then the league's
  tiebreaker), with clinched and eliminated tags and ESPN's own odds next to ours. In the app
  you pick winners of the games left with the arrow keys and the odds move. From a terminal:
  `benchboss playoffs --pick "Monstars>Tune Squad"` (add `@WEEK` for a given week; the same
  pair twice covers their next two games).
- `v` in the app switches a screen's view (roster split, workload order, standings table,
  playoff odds or games left). `--view` picks one from the command line on `roster`,
  `activity`, `standings`, `players` and `playoffs`.

### Changed

- Standings has PA, Diff, Pct, GB, streak, ESPN's playoff odds, clinch tags and a playoff
  line, plus two more views: divisions, and moves (waiver order, adds, drops, trades).
- Roster shows every split side by side, the box score of one split and today's opponent.
- Workload shows positions and today's slot, and reads the lineup ESPN has saved for each
  day of the week. A game a player spends on your bench shows in parentheses, `In` counts the
  games in your lineup, and the footer flags days with more games than starting spots. Days
  of a player who is OUT or suspended are dim and do not count. `v` goes back to the old
  order, most games first.
- Best trash has a strip of the days left for each pick (game, day off, grab day) and a
  caption half as long. A day he would sit on your bench shows as an open circle and is not
  counted in G.
- Optimize today and Optimize week draw each day as one block: the moves, the lineup they
  leave, and the bench with the reason each player sits. A hurt player gets the math
  ("DTD: 32.9 x 75% = 24.7"). Apply and Cancel stay docked under a long week.
- Dashboard: a small pixel basketball replaces the emoji (in the app's top bar too), the
  header has your place, streak and ESPN's playoff odds, and the news card shows up to 8
  items from the last 3 days, with the spin and a star on watch-list news.
- % rostered, shooting percentages and playoff odds look the same on every screen.
- The demo league has box scores, records, two divisions and a watch list, so every new
  screen works with `--demo`. The demo saves nothing to disk and refuses
  `watch add|remove` like every other write.
- The watch-list star in the app writes to ESPN as soon as you press space, without the
  Apply step, on purpose: the list is private to you, the change is instant and the same key
  undoes it. Every other write still shows the plan and waits.
- VS Code: Copilot can run the new reads (`players`, `watch`, `playoffs`, `news --watch`)
  without asking; `watch add|remove` and `alerts --mark-read` still ask.
- JSON that scripts may notice. Existing keys keep their meaning; everything below is new:
  - `activity --json` adds `positions`, `slot`, `games_in_lineup` and `days` (each with
    `date`, `opponent`, `slot`, `starting`). IR players are included, with slot `IR`.
  - `standings --json` adds `wins`, `losses`, `ties`, `win_pct`, `games_back`,
    `points_against`, `point_diff`, `streak`, `playoff_pct`, `clinch`, `division`,
    `division_record`, `waiver_rank`, `acquisitions`, `drops` and `trades`.
  - `roster --json` rows come in lineup order and add `opponent_today`, `last7`, `last30`,
    `started`, `on_team_id` and `stats` (each split with `fpts`, `total`, `gp`, `per_game`).
  - Picks in `trash --json` and `dash --json` add `game_days`, the dates he plays for you.
  - `news --json` items add `section` (`roster`, `watch` or `players`). `alerts --json` can
    have `spin` items with `player`, `headline`, `spin`, `published`, `source`, `link` and
    `news_id`.
  - `dash --json` adds `place`, `playoff_pct` and `watch_list` on each news item.
- The league read also asks ESPN for `mStandings` (playoff odds and clinch flags).

### Fixed

- The dashboard's auto refresh never ran in the app: a Textual attribute with the same name
  hid the method. It refreshes every minute again.
- After a terminal resize the app drew the screen at the old width, so a wide table could
  lose columns (Standings lost its Team column). It now waits for the new size.
- A bad `--view` value now exits with code 2 (bad usage) like the other argument errors.
- Tests no longer touch the real keychain, and the suite passes when run from the sdist.
- The demo league repeated one set of matchups from week 10 on. Weeks 4 to 20 are now a
  proper double round robin.

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

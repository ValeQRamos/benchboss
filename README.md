<div align="center">

<img src="docs/images/logo.png" alt="benchboss logo, a pixel basketball" width="88">

# benchboss

**Run your ESPN Fantasy Basketball team from the terminal.**

Live matchup dashboard · one-key lineup optimizer · auto-swap for game-time decisions · waiver scout that does the math · player finder · playoff odds · trade finder · player news

[![CI](https://github.com/ValeQRamos/benchboss/actions/workflows/ci.yml/badge.svg)](https://github.com/ValeQRamos/benchboss/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-3776ab)
![Platforms](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-555)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Built with Textual](https://img.shields.io/badge/built%20with-Textual-ee7d32)

<img src="docs/images/dashboard.png" alt="benchboss dashboard: matchup, roster, workload, news, best free agents and standings" width="900">

</div>

---

benchboss is a fast, keyboard-driven companion for **ESPN head-to-head points leagues** with
daily lineups. It reads your league with the same cookies your browser uses, shows everything
that matters this week on one screen, and turns the chores that decide close matchups into a
single key: set the best lineup for today or the whole week, find the free agent who adds the
most points before Sunday, and spot fair trades that fix a positional hole on both sides. It
also finds players by recent form, keeps your ESPN watch list, and plays out the rest of the
season to show your playoff odds. It can watch a player listed as day-to-day and start him if
he is cleared before his game (in trial mode for now, see [Auto-swap](docs/autoswap.md)), and
it fits on a phone over SSH.

Try it in ten seconds, no ESPN account needed (with [uv](https://docs.astral.sh/uv/) installed):

```bash
uvx --from "benchboss @ https://github.com/ValeQRamos/benchboss/archive/refs/heads/main.zip" benchboss --demo
```

## Contents

- [Features](#features)
- [Install](#install)
- [Quick start](#quick-start)
- [Using it from VS Code](#using-it-from-vs-code)
- [On a phone](#on-a-phone)
- [Commands](#commands)
- [How the numbers work](#how-the-numbers-work)
- [Configuration](#configuration)
- [Privacy and safety](#privacy-and-safety)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Contact](#contact)

## Features

| Feature | What it does |
|---|---|
| **Matchup dashboard** | Live score, a projected final for both sides, games left this week, your roster with who plays today, your place and ESPN's playoff odds, standings, alerts and the latest news. Works full screen or as a narrow side panel that refreshes itself. |
| **Optimize today / Optimize week** | One key sets the best lineup for today or for every day left in the matchup week. Benches players who rest, are OUT or project less; doubtful and day-to-day players are discounted. Each day shows the moves, the lineup they leave and why everyone on the bench sits, with the injury math written out. Waits for **Apply**, then tells you *"Your week is set"*. |
| **Auto-swap** | Arm a player who is day-to-day or out. If he turns healthy at least 3 minutes before his game, benchboss starts him and benches the starter with the lowest projection whose game has not started, and nobody else moves. `benchboss monitor` does the watching and sends notes to your Mac or phone (ntfy, or a command of your own). It ships in **trial mode**: it tells you what it would have done and changes nothing until you turn live mode on. [How it works](docs/autoswap.md). |
| **Workload this week** | Games per player this week with the opponent each day, his position and today's slot. Reads the lineup ESPN has saved for every day, so the games a player spends on your bench are marked, and the footer shows the days you have more games than starting spots. In daily leagues, volume wins. |
| **Best trash** | Ranks free agents ("trash") by the points they would actually add to *your* lineup from the day you grab them to Sunday, after subtracting what your weakest player would have scored. A strip shows the days each one plays. Knows about waivers. |
| **Player finder** | Free agents, players on a team, your watch list or everyone, in one table: fantasy points per game for the season, the last 7, 15 and 30 days, ESPN's projection and last season, plus the box score. Sort by any column, filter by position, search by name, and star players on your ESPN watch list. |
| **Playoff race** | Playoff, seed and division odds from 5,000 simulated seasons, seeded the way ESPN does it. Pick winners for the games left and watch the odds move. |
| **Roster and standings** | Your roster with every stat split side by side and the box score of one. Standings with PF, PA, Diff, streaks, games back, ESPN's playoff odds, clinch tags and the playoff line, plus a table per division and one with the waiver order and every team's adds, drops and trades. |
| **Trade finder** | Profiles every roster by position, finds where you are deep and they are thin (and the other way around), and proposes fair 1-for-1 deals that respect league position limits. Comes with a ready-to-send note. |
| **Player news** | The latest RotoWire blurbs and their "spin", with a tab for your roster and one for your watch list and a window from 1 to 30 days. Search any NBA player to read his latest news, however old. Plus an optional AI briefing that searches the web, and a popup when a watch-list player gets news. |
| **Works on a phone** | Under 80 columns or 30 rows the app goes compact: the menu opens as its own page, a one-row key bar keeps `m menu` in reach, and the Player finder keeps the name and the split you picked side by side. See [On a phone](#on-a-phone). |
| **Inbox** | Trade offers sent to you, accepted trades waiting to process, pending claims, unread DMs and watch-list news you have not seen. |
| **Agent ready** | Every read command speaks `--json`; every write has `--dry-run`. The repo ships instructions and skills so GitHub Copilot, Claude Code and other agents can drive it safely. |

<img src="docs/images/players.png" alt="Player finder: free agents with every stat split and the box score" width="100%"><br>
<sub><b>Player finder</b>: every split side by side, the box score of the one you pick, and a star for your ESPN watch list.</sub>

<table>
<tr>
<td width="50%"><img src="docs/images/optimize-week.png" alt="Optimize week: the plan for every remaining day"><br><sub><b>Optimize week</b>: the moves for every day, applied with one key.</sub></td>
<td width="50%"><img src="docs/images/trash.png" alt="Best trash: free agents ranked by points added this week"><br><sub><b>Best trash</b>: points added this week, the days he plays, who to drop.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/workload.png" alt="Workload: games per player, day by day, with the bench marked"><br><sub><b>Workload</b>: games per player this week, and the ones stuck on your bench.</sub></td>
<td width="50%"><img src="docs/images/roster.png" alt="Roster: every stat split and the box score"><br><sub><b>Roster</b>: season, last 7, 15 and 30 days, projection and last season.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/standings.png" alt="Standings with playoff odds and the playoff line"><br><sub><b>Standings</b>: PF, PA, Diff, streaks and ESPN's playoff odds.</sub></td>
<td width="50%"><img src="docs/images/playoffs.png" alt="Playoff race: odds and a scenario builder"><br><sub><b>Playoff race</b>: pick winners for the weeks left and see the odds move.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/news.png" alt="Player news for your roster and your watch list"><br><sub><b>Player news</b>: your roster, your watch list, or any player you search.</sub></td>
<td width="50%"><img src="docs/images/trades.png" alt="Trade finder: fair deals by positional need"><br><sub><b>Trade finder</b>: fair 1-for-1 deals that fix needs on both sides.</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/autoswap.png" alt="Auto-swap: armed players and what each would do if he turned healthy"><br><sub><b>Auto-swap</b>: who is armed and what happens if he is cleared.</sub></td>
<td width="50%"><img src="docs/images/dashboard-light.png" alt="The dashboard in the light theme"><br><sub><b>Light theme</b>: for light terminals, or <code>ctrl+t</code> any time.</sub></td>
</tr>
</table>

## Install

**macOS and Linux, one line** (installs [uv](https://docs.astral.sh/uv/) if you do not have it, then benchboss):

```bash
curl -LsSf https://raw.githubusercontent.com/ValeQRamos/benchboss/main/install.sh | sh
```

**Already have uv or pipx?**

```bash
uv tool install "benchboss @ https://github.com/ValeQRamos/benchboss/archive/refs/heads/main.zip"
# or
pipx install https://github.com/ValeQRamos/benchboss/archive/refs/heads/main.zip
```

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
$env:Path = "$HOME\.local\bin;$env:Path"   # lets this window find uv; new windows find it on their own
uv tool install "benchboss @ https://github.com/ValeQRamos/benchboss/archive/refs/heads/main.zip"
```

None of these need git: they download the source as a zip file.

**From a clone** (for hacking on it):

```bash
git clone https://github.com/ValeQRamos/benchboss && cd benchboss
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Upgrade any time with `uv tool upgrade benchboss` (or `pipx upgrade benchboss`). Requires Python 3.10 or newer; uv downloads one for you if needed.

## Quick start

```bash
benchboss setup     # 1. connect your ESPN account, pick your league and team
benchboss           # 2. open the app
```

`setup` reads your ESPN session cookies (on macOS it can import them from Chrome; anywhere
else you paste them once), finds your basketball leagues automatically, and asks whether your
terminal background is dark or light. That is all.

<details>
<summary><b>Where do I find my ESPN cookies?</b></summary>

1. Sign in at [espn.com](https://www.espn.com) and open your fantasy league.
2. Open your browser's developer tools and find the cookies stored for `espn.com`
   (Chrome and Edge: **Application** tab, Firefox and Safari: **Storage** tab).
3. Copy the values of **`espn_s2`** (a long string) and **`SWID`** (looks like `{XXXXXXXX-...}`).
4. Paste them when `benchboss setup` or `benchboss login --manual` asks. Input is hidden.

They are stored in your operating system keychain and never leave your computer except in
requests to ESPN. Run `benchboss logout` to forget them.
</details>

Inside the app every screen has a single key:

| Key | Screen | Key | Screen |
|---|---|---|---|
| `d` | Dashboard | `n` | Player news |
| `t` | Optimize today | `x` | Trade finder |
| `w` | Optimize week | `i` | Inbox |
| `a` | Workload | `s` | Standings |
| `f` | Best trash | `y` | Playoff race |
| `p` | Player finder | `o` | Roster |
| `u` | Auto-swap | `r` | Refresh |
| `v` | Next view of this screen (roster split, standings table, workload order) | `ctrl+t` | Light or dark |
| `m` | Show or hide the menu (it hides itself below 110 columns; on a phone it opens as a page) | `q` | Quit |
| `g` | AI news briefing (needs `ANTHROPIC_API_KEY`) | `e` | Settings (ntfy alerts) |

The Player finder has its own keys. Letters it does not use (`d`, `s`, `o`...) still jump
to the other screens, except while you type in the search box.

| Key | In the Player finder |
|---|---|
| `1` `2` `3` `4` | Free agents, players on a team, your watch list, everyone |
| `[` `]` | Previous or next position |
| `v` | Next stat split: Season, L7, L15, L30, Proj, Prev |
| `<` `>` | Sort by the column to the left or right (or click a header; click it again to flip the order) |
| `/` | Search by name, Enter to run it |
| `enter` | Open or close the player card: every split, ownership, news |
| `esc` | Leave the search box, close the card, or clear the search |
| `space` or `*` | Add the player to your ESPN watch list, or take him off. This one is sent right away, see [Privacy and safety](#privacy-and-safety) |

Player news has two tabs and a search:

| Key | In Player news |
|---|---|
| `1` `2` | Your roster, your watch list |
| `[` `]` | Fewer or more days back (1, 3, 5, 7, 14 or 30) |
| `/` | Search any NBA player by name (a close spelling works), Enter to run it |
| `.` | Ten older items for the player you searched (on a tab, the next window of days) |
| `esc` | Leave the search box, then the pick list, then the search |

On the Auto-swap screen (`u`), `enter` on a player shows what would happen if he turned
healthy, and a second `enter` arms him. `enter` or `backspace` on an armed player disarms
him, and `!` asks for an alert only, with no lineup change. The rest is in
[docs/autoswap.md](docs/autoswap.md).

The Playoff race screen is a scenario builder: the games left on one side, the odds on the
other. Every pick runs the season again and a +/- column shows what your picks changed.

| Key | In the Playoff race |
|---|---|
| `↑` `↓` (or `k` `j`) | Previous or next game |
| `Page Up` `Page Down` (or `,` `.`) | Previous or next week |
| `←` `→` (or `h` `l`) | The team on the left (home) or on the right (away) wins. The same key again clears it |
| `0` or `backspace` | Clear this game |
| `c` | Clear every pick |
| `e` | Jump to the final 5 weeks |
| `b` | Back to the next week |

## Using it from VS Code

benchboss was built to live in the VS Code integrated terminal.

- **Open the app:** in the terminal panel, run `benchboss`.
- **Side panel:** split the terminal and run `benchboss dash --watch` in the narrow half. It
  redraws every 60 seconds and adapts to the width.

  <img src="docs/images/side-panel.png" alt="Narrow side panel" width="300">

- **Tasks:** clone this repo and open the folder; `Tasks: Run Task` lists ready-made tasks
  (*benchboss: app*, *dashboard*, *optimize today*, *optimize week*, *best trash*, *news*).
- **GitHub Copilot (agent mode):** this repo ships [`AGENTS.md`](AGENTS.md),
  [`.github/copilot-instructions.md`](.github/copilot-instructions.md) and skills in
  [`.github/skills`](.github/skills). Open the folder, pick a model (Claude Sonnet works great)
  and ask in plain words: *"set my lineup for the rest of the week"*, *"who should I pick up?"*,
  *"news on my players from the last 5 days"*, *"find me a trade for a center"*, *"which free
  agent centers are hot over the last 7 days?"*, *"what are my playoff odds if I win this
  week?"*. The agent runs benchboss with `--json`, explains the result, and only writes to
  ESPN after you say yes.
- **Light theme?** Run `benchboss setup` again and choose light, or press `ctrl+t` in the app.

More in [docs/vscode.md](docs/vscode.md).

## On a phone

benchboss runs fine in an SSH app on a phone. Keep it on a computer that stays on (a Mac
mini, a home server, a small cloud machine), open a `tmux` session there so it keeps running
when the phone locks, and connect from the phone. To skip the SSH app, the server can serve
the app as a web page behind a login (see "On a server, and in a browser" below).

<table>
<tr>
<td width="50%"><img src="docs/images/phone-dashboard.png" alt="The dashboard on a 46-column phone screen"><br><sub><b>Dashboard</b> at 46 columns.</sub></td>
<td width="50%"><img src="docs/images/phone-players.png" alt="The Player finder on a 46-column phone screen"><br><sub><b>Player finder</b>: the name and the split you picked stay side by side.</sub></td>
</tr>
</table>

Under 80 columns or 30 rows the app switches to its compact layout on its own:

- `m` opens the menu as a page of its own; `m`, `esc` or `backspace` close it.
- A one-row key bar replaces the footer, with `m menu` always on it. Tapping a key on the bar
  works like pressing it, and a tap never sends anything to ESPN.
- `j` `k` scroll, and every action has a key that a phone keyboard has (letters, digits,
  `,` `.` `/` `!` and the like), so you never need arrows or Page Up.
- The Player finder puts the split you picked right after the name and folds its filters
  into one line when the keyboard is up.

`benchboss --layout compact` (or `full`) forces one or the other, and so do
`BENCHBOSS_LAYOUT` and `"layout"` in `config.json`.

## On a server, and in a browser

Run benchboss on a small always-on Linux server and open it over SSH from your Mac or your
phone, with `tmux` keeping the session alive, or serve it as a web page with
`benchboss web` behind a login. Setup, SSH keys, how users and cookies fit together and
troubleshooting are in [docs/server.md](docs/server.md). Deploying it, updating and rolling
back, adding people (one address for everyone, each with their own password and ESPN account)
and automatic deploys from GitHub are in [docs/deploy.md](docs/deploy.md).

## Commands

Run `benchboss --help` or `benchboss <command> --help` for every flag. Read commands accept
`--json`; write commands show what they will do and ask first (`--yes` skips the question).

| Command | What it does |
|---|---|
| `benchboss` | Interactive app (menu + screens) |
| `benchboss dash [--watch]` | Dashboard once, or live in a side terminal |
| `benchboss matchup` | Live score, projected final, games left |
| `benchboss roster [--view l7]` | Roster with every stat split, the box score of one (`season`, `l7`, `l15`, `l30`, `proj`, `last`), who plays today |
| `benchboss activity [--view lineup]` | Games per player this matchup week, day by day, with the bench marked (`games`: most games first, or today's `lineup` order) |
| `benchboss standings [--view divisions]` | League table with PA, Diff, streaks and playoff odds (`league`, `divisions`, `moves`) |
| `benchboss playoffs [--pick "Winner>Loser"] [--view games]` | Playoff odds. `--pick` fixes a result (add `@WEEK` for a given week, repeat for more); `--view games` lists the matchups left |
| `benchboss optimize [today\|tomorrow\|week\|11-04]` | Best lineup for a day or the rest of the week (`--dry-run` to only look) |
| `benchboss trash [POS] [-n N]` | Most valuable free agents for this week |
| `benchboss players [NAME] [--from fa\|rostered\|watch\|all] [--pos C] [--sort l7]` | Player finder: every split and the box score (`--view` picks the split for the box score) |
| `benchboss watch [list\|add\|remove] [PLAYER]` | Your ESPN watch list; `add` and `remove` ask first (`--dry-run` to only look) |
| `benchboss fa [POS]` · `benchboss trending` | Free agents by % rostered, or rising the fastest |
| `benchboss news [PLAYER ...] [--watch] [--days 5] [-n 10] [--ai]` | News and spins for your roster or your watch list, or the latest news on any NBA player you name |
| `benchboss trades [--need C] [--with TEAM] [--needs]` | Trade ideas, or every team's positional balance |
| `benchboss alerts [--mark-read]` | Trade offers, accepted trades, pending claims, unread DMs, new watch-list news (`--mark-read` stops showing the news you saw) |
| `benchboss autoswap [list\|add\|remove\|clear\|pause\|resume\|log] [PLAYER]` | Auto-swap: arm a player who might turn healthy before his game, so benchboss starts him by itself (`add` shows what would happen and asks; `--notify-only` for an alert alone) |
| `benchboss monitor [--once] [--live]` | The background process that makes the auto-swaps and sends the notifications. Trial mode (it only says what it would do) unless `--live` |
| `benchboss add PLAYER [--drop PLAYER]` · `drop` | Sign a free agent or put in a claim; release a player |
| `benchboss trade --give A --get B [--msg TEXT]` | Send a trade offer |
| `benchboss chat [TEXT] [--to TEAM]` | Read or post in the league chat or a DM |
| `benchboss setup` · `login` · `logout` · `status` | Account and configuration |

Full reference: [docs/commands.md](docs/commands.md).

## How the numbers work

- **Projections** come from ESPN (season projection per game, already scored with your
  league's settings). Before a player has a projection, his average is used. Day-to-day and
  questionable players count 75%, doubtful 25%, out and suspended 0.
- **Lineups** are solved exactly for each day: every possible assignment of players to your
  league's slots (positions, G, F, UT) is considered with a dynamic program, and ties keep
  players where they are so a day that is already right stays untouched. Future days are sent
  as ESPN "future roster" moves and re-checked right before sending.
- **Projected final** = points so far + for each remaining day, the best starters with a game.
- **Best trash**: for each free agent and each possible pickup day, his expected points count
  only on days he plays *and* beats the weakest starter you would otherwise use (or fills an
  open slot). Net value subtracts what the suggested drop would have scored over the same days.
  Waiver players start counting after their waiver period.
- **Trade finder** compares each team's projected points at PG, SG, SF, PF and C with the
  league average. A suggestion trades from your surplus into their need and back, at similar
  value (85% match by default), without breaking position limits.
- **Playoff race** plays the rest of the regular season 5,000 times. Each team's weekly score
  is drawn around what it is expected to score (results so far blended with its roster's
  projection, today's injuries only for this week and the next), with a 12% spread. Seeds
  follow ESPN's rules: division winners first, then the league's tiebreaker. ESPN's own odds
  sit next to ours for comparison.
- **Auto-swap** benches the starter with the lowest value that day (projection times
  availability) whose game has not started, and only when the change adds at least 1
  projected point. It never moves a player whose game starts within 3 minutes. Details in
  [docs/autoswap.md](docs/autoswap.md).
- **Workload** reads the lineup ESPN has saved for each day of the week. A game counts for you
  only when the player is in a starting slot that day, so the games he spends on your bench
  are marked and left out of the `In` count.

Details and the API behind them: [docs/how-it-works.md](docs/how-it-works.md) and the
[ESPN Fantasy Basketball API reference](docs/api/README.md) we wrote along the way.

## Configuration

| Setting | Where | Notes |
|---|---|---|
| League, team, season, theme | `~/.config/benchboss/config.json` (Windows: `%APPDATA%\benchboss`) | Written by `benchboss setup` |
| ESPN cookies | OS keychain (service `benchboss`) | Fallback: `credentials.json` with 0600 permissions |
| `BENCHBOSS_LEAGUE_ID`, `BENCHBOSS_TEAM_ID`, `BENCHBOSS_SEASON`, `BENCHBOSS_THEME` | Environment | Override the config file |
| `ESPN_S2`, `ESPN_SWID` | Environment | Cookies for CI or containers |
| Watch-list news you have seen | `seen-news.json` next to `config.json` | Written by `benchboss alerts --mark-read` |
| Auto-swap marks, the monitor's state, the lineup log | `leagues/<league id>/` and `logs/` next to `config.json` | See [docs/autoswap.md](docs/autoswap.md#files) |
| `BENCHBOSS_LAYOUT` | Environment | `auto` (compact on a phone or a small window), `compact` or `full` |
| `BENCHBOSS_NTFY_TOPIC`, `BENCHBOSS_NOTIFY_CMD` | Environment or `notify.env` | Where `benchboss monitor` sends its notes ([notifications](docs/autoswap.md#notifications)) |
| `ANTHROPIC_API_KEY` | Environment | Enables `benchboss news --ai` |
| `BENCHBOSS_HOME` | Environment | Use a different config folder |

More in [docs/configuration.md](docs/configuration.md).

## Privacy and safety

- Your cookies stay on your machine (keychain) and are only sent to ESPN. benchboss never
  prints them, logs them or puts them in `--json` output.
- Nothing changes in your league without a confirmation: every write shows the exact moves and
  asks first. `--dry-run` shows the plan and sends nothing. Demo mode sends nothing to ESPN and
  saves nothing on your computer.
- Two exceptions. In the app's Player finder, space adds a player to your ESPN watch list (or
  takes him off) right away, like the star in the ESPN app. Nobody else in the league sees your
  watch list and the same key undoes it. From the command line, `benchboss watch add|remove`
  asks first like every other write.
- The other one is auto-swap, and you opt in one player at a time. Arming a player shows what
  would happen and asks first; after that, `benchboss monitor --live` may make that one change
  without asking again. Without `--live` the monitor only tells you what it would have done.
  `benchboss autoswap pause` stops it, and disarming always wins over a change about to go out.
- What stays on your computer: your config, the cookies (in the keychain), two small files
  with the watch-list news you have already seen (`seen-news.json`) and the ones the app already
  popped up (`toasted-news.json`), and if you use auto-swap, your marks, the monitor's state and
  a log of every lineup change. Nothing in them leaves your machine.
- The monitor's notes carry player names and what happened, never your league id or cookies.
  On the public ntfy server anyone who knows your topic can read it, so pick a long random one.
- Player news comes from ESPN's public feed and needs no cookies. The optional AI briefing sends
  only your players' names, NBA teams and positions to the Anthropic API, and only when you ask for it.
- benchboss is not affiliated with, endorsed by or supported by ESPN. It uses the same
  undocumented endpoints as ESPN's website, which can change without notice.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## FAQ

<details><summary><b>Does it work for category (roto, H2H categories) leagues?</b></summary>
The dashboard, roster, news, standings and lineup tools work, but projections and the trash
and trade math are built for points leagues. Categories support is on the roadmap.
</details>

<details><summary><b>Can it use another sport?</b></summary>
Not today. The ESPN API is similar across sports, so football and hockey are possible later.
</details>

<details><summary><b>`benchboss` says my cookies expired.</b></summary>
ESPN sessions eventually expire, for example when you sign out of espn.com. Run `benchboss login` again.
</details>

<details><summary><b>The colors look washed out or the boxes are broken.</b></summary>
Use a terminal with true color (VS Code, iTerm2, Ghostty, WezTerm, Kitty, Windows Terminal).
macOS Terminal.app only has 256 colors. On a light background run `benchboss setup` and
choose light, or pass `--theme light`.
</details>

<details><summary><b>Why are the playoff odds different from ESPN's?</b></summary>
ESPN does not say how it simulates the season. benchboss runs its own simulation from the
results so far and every roster's projection, and shows ESPN's number next to it. Early in the
season the two can be far apart. The model is in [docs/how-it-works.md](docs/how-it-works.md#playoff-race).
</details>

<details><summary><b>Why "trash"?</b></summary>
In our league free agents are lovingly called trash. Some trash is gold.
</details>

## Roadmap

- [ ] Categories leagues (projections per category, punt strategies)
- [ ] Per-game projections from ESPN once the season starts (finer daily numbers)
- [ ] Notifications for trade offers and for starters ruled out before lock
- [ ] Accept, decline and counter trades from the app
- [ ] Waiver claim editing and FAAB suggestions
- [ ] PyPI and Homebrew releases

## Contributing

Bug reports, ideas and pull requests are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md):
it explains the layout, the demo dataset (so you can work without an ESPN league) and how to
run the tests.

## Contact

Suggestions, bug reports or just a good trade story: **[k1lldeer@proton.me](mailto:k1lldeer@proton.me)**

<sub>MIT licensed. Not affiliated with ESPN. NBA team and player names belong to their owners.</sub>

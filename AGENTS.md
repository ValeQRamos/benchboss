# AGENTS.md

Instructions for AI coding agents (GitHub Copilot, Claude Code, Codex, Cursor and others)
working in this repository. There are two kinds of tasks; figure out which one you have.

1. **Operating the user's fantasy team** ("set my lineup", "who should I pick up?",
   "news on my players"). Run the `benchboss` CLI. Do not edit source files.
2. **Developing benchboss** (fix a bug, add a feature). See "Developing" below.

## Operating the CLI

Check that it is installed and connected:

```bash
benchboss status --json        # league, team, season, whether cookies exist (never their values)
```

If it says no league or no cookies, ask the user to run `benchboss setup` themselves in a
terminal. Login is for humans only: never ask the user to paste cookies into the chat, never
print them, never pass them as command arguments.

### Always use `--json` when you need to read results

Every read command supports `--json` and prints stable keys, ISO dates and names.

| Intent | Command |
|---|---|
| Overview of the week | `benchboss dash --json` |
| Live score and projected final | `benchboss matchup --json` |
| Roster, injuries, who plays today, every stat split | `benchboss roster --json` |
| Games per player this week, and which are on the bench | `benchboss activity --json` |
| Best free agents for this week | `benchboss trash --json [-n 10] [POS]` |
| Find players by any split (free agents, rostered, watch list, all) | `benchboss players --json [--from fa\|rostered\|watch\|all] [--pos C] [--sort l7] [-n 20] [NAME]` |
| The user's ESPN watch list | `benchboss watch --json` |
| Free agents by ownership / rising | `benchboss fa --json [POS]`, `benchboss trending --json` |
| News and spins (last N days) | `benchboss news --json [--days 5] [PLAYER ...]` |
| News on watch-list players | `benchboss news --json --watch [--days 5]` |
| Trade ideas | `benchboss trades --json [--need C] [--with TEAM]` |
| Every team's positional balance | `benchboss trades --needs --json` |
| Trade offers, claims, unread DMs, unseen watch-list news | `benchboss alerts --json` |
| Standings, streaks, ESPN's playoff odds | `benchboss standings --json` |
| Playoff odds, and what-if results | `benchboss playoffs --json [--pick "Winner>Loser[@WEEK]" ...]` |
| League chat or a DM (read) | `benchboss chat --json [--to TEAM]` |

`--view` (on `roster`, `activity`, `standings`, `players` and `playoffs`) only changes the
text drawing; the JSON always has everything. On `players`, `--sort` picks which players ESPN
sends (`proj`, `season`, `l7`, `l15`, `l30`, `last`, `own`, `change`), and without it the
`--view` split is used.

Do not run `benchboss` with no command, `benchboss app`, `benchboss web` or
`benchboss dash --watch`: they are interactive and never exit. Run `benchboss news --ai` only
when the user asks for the AI briefing: it calls the Anthropic API with their key and costs
money.
Run `benchboss alerts --mark-read` only when the user asks (they say they read the news). It
writes nothing to ESPN, but the watch-list items it lists then never come back in `alerts` or
in the app's toasts.

### Writes need the user's explicit yes, every time

Write commands change the real league on ESPN. Protocol:

1. Show the plan first with `--dry-run` (nothing is sent), for example
   `benchboss optimize week --dry-run` or `benchboss add "Player" --drop "Player" --dry-run`.
   Never run a write without `--dry-run` or `--yes`: it waits for keyboard input and hangs
   an agent terminal.
2. Wait for the user to approve that specific action in chat.
3. Run the same command with `--yes`, then quote ESPN's answer (a line like `ESPN: EXECUTED`).

| Action | Command |
|---|---|
| Best lineup today / rest of week | `benchboss optimize today --yes`, `benchboss optimize week --yes` |
| Sign a free agent (optionally dropping someone) | `benchboss add "Player" --drop "Player" --yes` |
| Release a player | `benchboss drop "Player" --yes` |
| Send a trade offer | `benchboss trade --give "A" --get "B" --msg "text" --yes` |
| Post in the league chat or a DM | `benchboss chat "text" [--to TEAM] --yes` |
| Add a player to the ESPN watch list, or take him off | `benchboss watch add "Player" --yes`, `benchboss watch remove "Player" --yes` |
| Send the user's ESPN cookies to their server over SSH | `benchboss login --to user@host --yes`: the user runs this themselves, an agent never does |

Never chain several writes from one approval. Never retry a failed write without asking.

The watch list follows the same protocol from the command line; its answer reads
`ESPN: watch list has N players`. The one write that skips the protocol is the star in the
app's Player finder (space), on purpose, because the watch list is private, the change is
instant and the same key undoes it.

### Exit codes

`0` ok · `1` error · `2` bad usage · `3` cookies missing or expired (ask the user to run
`benchboss login`) · `4` ESPN rejected the request or part of a write (show the lines) · `10` a write was
prepared but not confirmed (rerun with `--yes` only after the user approves).

### Facts that prevent wrong answers

- A **scoring period is one day**; the first day of the NBA regular season is period 1.
- A **matchup week** runs Monday to Sunday (the first one runs from opening night to the first
  Sunday; the All-Star week is merged with the next one).
- Lineups are **per day**. Changing today does not change tomorrow; `optimize week` handles
  every remaining day.
- Use the system clock for "today"; never assume a date. When you mention a weekday with a
  date, compute it.
- Projections are ESPN's, in fantasy points per game for this league's scoring.
- Stat splits: `season`, `l7`, `l15`, `l30` are this season (all, last 7, 15, 30 days), `proj`
  is ESPN's projection, `last` is last season. Before opening night only `proj` and `last`
  have numbers. In JSON, `stats.<split>.fpts` is fantasy points per game.
- Two playoff odds exist. `standings --json` `playoff_pct` is ESPN's own number;
  `playoffs --json` `playoffs` is benchboss's simulation (5,000 seasons). Both are shares
  from 0 to 1, and neither is a promise; say which one you quote.
- "Trash" means free agents.

## Developing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                 # runs offline on the bundled demo league
ruff check src tests tools
benchboss --demo       # the app with fictional data, no ESPN account needed
```

Layout:

| Path | What lives there |
|---|---|
| `src/benchboss/espn/` | HTTP client, id tables (`constants.py`, incl. the stat splits), JSON to dataclasses (`models.py`) |
| `src/benchboss/core/` | Pure logic: calendar, lineup optimizer, projections, workload, trash scout, trade finder, playoff race |
| `src/benchboss/service.py` | `Session`: caches league data and exposes every feature (player pools, watch list, daily lineups) |
| `src/benchboss/actions.py`, `inbox.py`, `news.py` | Writes, chat and alerts (incl. watch-list news), news |
| `src/benchboss/ui/screens/` | One module per screen, shared by the app and the CLI; the protocol is in its `__init__.py` |
| `src/benchboss/ui/` | The dashboard, the Textual app (`app.py`: menu, keys), the older Rich views (`views.py`), shared drawing helpers, the logo |
| `src/benchboss/demo/` | Fictional league dataset and a client that refuses writes (the watch list changes in memory only) |
| `tools/` | Screenshots, `docs/commands.md`, the demo dataset and the logo PNG |
| `docs/api/` | Reverse-engineered ESPN Fantasy Basketball API reference |

New screens go in `src/benchboss/ui/screens/`. Each module has `TITLE`, `VIEWS` (cycled with
`v` in the app, `--view` in the CLI), `load(session)` (the only part that calls ESPN),
`draw(data, pal, width, view)` and `to_json(data)`, plus `widget(data, app)` when the screen
is interactive. Register it in `SCREENS` (`ui/screens/__init__.py`) and `MENU` (`ui/app.py`),
and give it a CLI command that calls `_screen`. Steps in
[CONTRIBUTING.md](CONTRIBUTING.md#adding-a-screen).

Rules:

- Keep `core/` free of I/O so it stays testable with the demo data.
- New ESPN calls go through `espn/client.py`; document new endpoints in `docs/api/`.
- Every new read command gets a `--json` output and a test in `tests/test_cli.py`.
- Every write must go through a confirmation (`Ctx.confirm` in the CLI, the Apply button in
  the app). The finder's watch-list star is the only exception; do not add another.
- Never commit cookies, league ids of private leagues, or real manager names. Tests use the demo league.
- Writing style for docs and UI text: plain English, no em dashes.

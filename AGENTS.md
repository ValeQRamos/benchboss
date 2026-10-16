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
| Roster, injuries, who plays today | `benchboss roster --json` |
| Games per player this week | `benchboss activity --json` |
| Best free agents for this week | `benchboss trash --json [-n 10] [POS]` |
| Free agents by ownership / rising | `benchboss fa --json [POS]`, `benchboss trending --json` |
| Find players with every stat split | `benchboss players --json [NAME] [--from all] [--pos C] [--sort l7] [-n 50]` |
| Your ESPN watch list | `benchboss watch --json` |
| News and spins (last N days) | `benchboss news --json [--days 5] [PLAYER ...]` |
| News on your watch-list players | `benchboss news --json --watch` |
| Trade ideas | `benchboss trades --json [--need C] [--with TEAM]` |
| Every team's positional balance | `benchboss trades --needs --json` |
| Trade offers, claims, unread DMs | `benchboss alerts --json` |
| Standings | `benchboss standings --json` |
| Playoff odds, who is in or out, what-if | `benchboss playoffs --json [--pick "Winner>Loser@WEEK"]` |
| League chat or a DM (read) | `benchboss chat --json [--to TEAM]` |

`players --from` takes `fa` (default), `rostered`, `all` or `watch`. A `NAME` search matches the
start of a first, last or full name ("Gilgeous", "Shai G"), as ESPN does, not any part of it.

Do not run `benchboss` with no command, `benchboss app` or `benchboss dash --watch`: they
are interactive and never exit. Run `benchboss news --ai` only when the user asks for the AI
briefing: it calls the Anthropic API with their key and costs money.

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
| Add a player to your ESPN watch list, or take him off | `benchboss watch add "Player" --yes`, `benchboss watch remove "Player" --yes` |

Never chain several writes from one approval. Never retry a failed write without asking.

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
- "Trash" means free agents.

## Developing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                 # runs offline on the bundled demo league
ruff check src tests
benchboss --demo       # the app with fictional data, no ESPN account needed
```

Layout:

| Path | What lives there |
|---|---|
| `src/benchboss/espn/` | HTTP client, id tables, JSON to dataclasses (`models.py`) |
| `src/benchboss/core/` | Pure logic: calendar, lineup optimizer, projections, workload, trash scout, trade finder |
| `src/benchboss/service.py` | `Session`: caches league data and exposes every feature |
| `src/benchboss/actions.py`, `inbox.py`, `news.py` | Writes, chat and alerts, news |
| `src/benchboss/ui/` | Rich views, the dashboard, the Textual app |
| `src/benchboss/demo/` | Fictional league dataset and a client that refuses writes |
| `docs/api/` | Reverse-engineered ESPN Fantasy Basketball API reference |

Rules:

- Keep `core/` free of I/O so it stays testable with the demo data.
- New ESPN calls go through `espn/client.py`; document new endpoints in `docs/api/`.
- Every new read command gets a `--json` output and a test in `tests/test_cli.py`.
- Every write must go through a confirmation (`Ctx.confirm` in the CLI, the Apply button in the app).
- Never commit cookies, league ids of private leagues, or real manager names. Tests use the demo league.
- Writing style for docs and UI text: plain English, no em dashes.

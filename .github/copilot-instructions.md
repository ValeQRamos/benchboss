# Copilot instructions for benchboss

benchboss is a terminal app that manages an ESPN Fantasy Basketball team. Full instructions
are in [AGENTS.md](../AGENTS.md); these rules are the non-negotiable part.

- When the user asks about their fantasy team, run the `benchboss` CLI in the terminal with
  `--json` and answer from its output. Do not edit source files for those requests.
- Reads are safe: `dash`, `matchup`, `roster`, `activity`, `trash`, `players`, `watch` (or
  `watch list`), `fa`, `trending`, `news` (`news --watch` for the watch list, `news "Player"`
  for any NBA player's latest items), `trades`, `alerts`,
  `standings`, `playoffs` (`--pick "Winner>Loser"` only changes the simulation), `chat`
  (without text), `status`. `--view` only changes the text output; `--json` has everything.
- Writes change the real league: `optimize`, `add`, `drop`, `trade`, `watch add`,
  `watch remove`, `chat "text"`. Show the plan first with `--dry-run`, wait for the user's
  explicit yes in chat, then run the same command with `--yes` and quote the `ESPN: ...` line.
  One approval covers one action. (The app's watch-list star skips this on purpose, because
  the list is private and the same key undoes it. From the terminal, `watch add "Player"` and
  `watch remove "Player"` always ask.)
- `alerts --mark-read` only writes a local file, but those watch-list items then never come
  back in `alerts` or in the app's toasts. Run it only when the user says they have read them.
- Never run a write command without `--yes` or `--dry-run`: it waits for keyboard input and
  hangs the agent terminal. For the same reason never run `benchboss` with no command,
  `benchboss app` or `dash --watch` (they are interactive and never exit).
- `news --ai` calls the Anthropic API with the user's key and costs money: run it only when
  the user asks for the AI briefing.
- Never ask for, print or pass ESPN cookies. If `benchboss` exits with code 3, ask the user to
  run `benchboss login` themselves.
- For "latest news" requests, start with `benchboss news --json --days 5` (or
  `benchboss news --json "Player"` for one player, any date), then use web search for anything
  newer or missing, and say which source each item came from. A name that fits several players
  exits 2 with the list: ask which one.
- Lineups are per day and matchup weeks end on Sunday. Compute dates from the system clock.

# Copilot instructions for benchboss

benchboss is a terminal app that manages an ESPN Fantasy Basketball team. Full instructions
are in [AGENTS.md](../AGENTS.md); these rules are the non-negotiable part.

- When the user asks about their fantasy team, run the `benchboss` CLI in the terminal with
  `--json` and answer from its output. Do not edit source files for those requests.
- Reads are safe: `dash`, `matchup`, `roster`, `activity`, `trash`, `fa`, `trending`, `news`,
  `trades`, `alerts`, `standings`, `chat` (without text), `status`.
- Writes change the real league: `optimize`, `add`, `drop`, `trade`, `chat "text"`. Show the
  plan first with `--dry-run`, wait for the user's explicit yes in chat, then run the same
  command with `--yes` and quote the `ESPN: ...` line. One approval covers one action.
- Never run a write command without `--yes` or `--dry-run`: it waits for keyboard input and
  hangs the agent terminal.
- Never ask for, print or pass ESPN cookies. If `benchboss` exits with code 3, ask the user to
  run `benchboss login` themselves.
- For "latest news" requests, start with `benchboss news --json --days 5`, then use web search
  for anything newer or missing, and say which source each item came from.
- Lineups are per day and matchup weeks end on Sunday. Compute dates from the system clock.

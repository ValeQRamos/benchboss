# Copilot instructions for benchboss

benchboss is a terminal app that manages an ESPN Fantasy Basketball team. Full instructions
are in [AGENTS.md](../AGENTS.md); these rules are the non-negotiable part.

- When the user asks about their fantasy team, run the `benchboss` CLI in the terminal with
  `--json` and answer from its output. Do not edit source files for those requests.
- Reads are safe: `dash`, `matchup`, `roster`, `activity`, `trash`, `players`, `fa`,
  `trending`, `news` (and `news --watch`), `trades`, `alerts`, `standings`, `playoffs`,
  `watch` (the list), `chat` (without text), `status`. `alerts --mark-read` only marks the
  watch-list news it shows as read, in a file on this computer.
- Writes change the real league: `optimize`, `add`, `drop`, `trade`, `chat "text"`,
  `watch add` and `watch remove`. Show the plan first with `--dry-run`, wait for the user's
  explicit yes in chat, then run the same command with `--yes` and quote the `ESPN: ...` line.
  One approval covers one action.
- Never run a write command without `--yes` or `--dry-run`: it waits for keyboard input and
  hangs the agent terminal. For the same reason never run `benchboss` with no command,
  `benchboss app` or `dash --watch` (they are interactive and never exit).
- `news --ai` calls the Anthropic API with the user's key and costs money: run it only when
  the user asks for the AI briefing.
- Never ask for, print or pass ESPN cookies. If `benchboss` exits with code 3, ask the user to
  run `benchboss login` themselves.
- For "latest news" requests, start with `benchboss news --json --days 5`, then use web search
  for anything newer or missing, and say which source each item came from.
- Lineups are per day and matchup weeks end on Sunday. Compute dates from the system clock.

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-15

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

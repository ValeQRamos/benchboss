# Configuration

benchboss keeps three things on your computer: which league and team to drive (a small JSON
file), your ESPN session cookies (your keychain), both written by `benchboss setup`, and which
news on your watch-list players you have already seen, so each spin alerts you once. It also
caches the NBA schedule for a day. Demo mode (`--demo`) writes none of these.

## Files

| What | macOS and Linux | Windows |
|---|---|---|
| Settings | `~/.config/benchboss/config.json` (or `$XDG_CONFIG_HOME/benchboss`) | `%APPDATA%\benchboss\config.json` |
| Cache (NBA schedule, 24 h) | `~/.config/benchboss/cache/` | `%APPDATA%\benchboss\cache\` |
| Cookies | OS keychain, service `benchboss`, accounts `espn_s2` and `SWID` | Windows Credential Locker, same names |
| Cookies fallback | `credentials.json` next to the settings, permissions 0600, only when no keychain is available | same |
| Watch list news you have seen | `seen-news.json` next to the settings: the ids of the newest 500 news items per league id, nothing else | same |

`config.json`:

```json
{
  "league_id": 12345678,
  "team_id": 4,
  "season": null,
  "theme": "dark",
  "league_name": "My League",
  "team_name": "My Team"
}
```

- `season` is the year the NBA season ends (October 2026 to April 2027 is `2027`). When it is
  `null` or left out, benchboss follows the calendar and moves to the next season every
  August 1. `benchboss setup` saves a year here only when you pick a league from another
  season. A saved year never changes on its own: if your file has one (setup in version 1.0.0
  always saved it), set it to `null` or run `benchboss setup` again when a new season starts.
- `team_id` is detected from your cookies during setup; set it only if you co-manage a team.
- `theme` is `dark` or `light`; it matches the palette to your terminal background.

## Environment variables

Environment variables override the file. They are handy for scripts, CI and AI agents.

| Variable | Meaning |
|---|---|
| `BENCHBOSS_LEAGUE_ID` | League id (the number after `leagueId=` in the ESPN URL) |
| `BENCHBOSS_TEAM_ID` | Your team id inside the league |
| `BENCHBOSS_SEASON` | Season year, for example `2027` |
| `BENCHBOSS_THEME` | `dark` or `light` |
| `BENCHBOSS_HOME` | Use another folder for settings, cache and fallback cookies |
| `ESPN_S2`, `ESPN_SWID` | Cookies from the environment instead of the keychain |
| `ANTHROPIC_API_KEY` | Enables the AI briefing in `benchboss news --ai` and the app's news screen |
| `BENCHBOSS_AI_MODEL` | Model for the AI briefing (default `claude-sonnet-5-5`) |
| `NO_COLOR` | Plain output without colors |

## Several leagues

Keep one settings folder per league and switch with `BENCHBOSS_HOME`, or override the league
and your team in it for one command. Set both variables: your team id is different in every
league, and the saved one belongs to your usual league.

```bash
BENCHBOSS_LEAGUE_ID=87654321 BENCHBOSS_TEAM_ID=2 benchboss dash
```

If the team id is not in that league, benchboss stops with a message instead of guessing.

## Resetting

```bash
benchboss logout                 # forget the cookies
rm -rf ~/.config/benchboss       # forget everything (Windows: %APPDATA%\benchboss)
```

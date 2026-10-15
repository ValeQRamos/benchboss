---
name: player-news
description: Gather the latest news, injuries and role changes for the user's fantasy basketball players (or named players) from the last few days, combining benchboss news with web search. Use when the user asks for news, updates, injuries or what is going on with their players.
argument-hint: optional player names and number of days (default 5)
---

# Player news

1. Start with ESPN's fantasy feed (RotoWire blurbs plus the "spin" analysis):

   ```bash
   benchboss news --json --days 5                 # whole roster
   benchboss news --json --days 5 "LaMelo Ball"   # specific players (rostered or free agents)
   ```

2. Use web search for anything newer than the feed or for players with no items: injury
   reports, beat writers, team announcements. Prefer sources from the last 5 days.
3. Write one short line per player with news, most important first: what happened and what it
   means for fantasy (start, sit, hold, sell, watch). Say where each item came from.
4. If something affects tonight (a late scratch, a questionable tag), offer to rerun the
   lineup: `benchboss optimize today --dry-run`.

If `ANTHROPIC_API_KEY` is set, `benchboss news --ai` produces a similar briefing on its own.

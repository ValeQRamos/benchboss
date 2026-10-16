---
name: player-news
description: Gather the latest news, injuries and role changes for the user's fantasy basketball players, their ESPN watch list or named players from the last few days, combining benchboss news with web search. Use when the user asks for news, updates, injuries or what is going on with their players or the players they are watching.
argument-hint: optional player names, "watch list", and number of days (default 5)
---

# Player news

1. Start with ESPN's fantasy feed (RotoWire blurbs plus the "spin" analysis):

   ```bash
   benchboss news --json --days 5                 # whole roster
   benchboss news --json --days 5 --watch         # the user's ESPN watch list
   benchboss news --json --days 5 "LaMelo Ball"   # specific players (rostered or free agents)
   ```

   Each item has `published`, `headline`, `spin`, `players` and `section` (`roster`, `watch`
   or `players`). `--watch` and player names do not mix; run two commands if you need both.

2. For "anything new?" questions, `benchboss alerts --json` lists watch-list news the user has
   not seen yet (`kind: "spin"`, with `player`, `headline`, `spin`, `published`). Do not run
   `benchboss alerts --mark-read` unless the user says they have read them: it stops those
   items from showing again in `alerts` and in the app.
3. Use web search for anything newer than the feed or for players with no items: injury
   reports, beat writers, team announcements. Prefer sources from the last 5 days.
4. Write one short line per player with news, most important first: what happened and what it
   means for fantasy (start, sit, hold, sell, watch, pick up). Keep roster and watch-list
   players apart. Say where each item came from.
5. If something affects tonight (a late scratch, a questionable tag), offer to rerun the
   lineup: `benchboss optimize today --dry-run`. If a watch-list player's role grew, offer the
   trash-scout skill to see what he would add this week.

If `ANTHROPIC_API_KEY` is set, `benchboss news --ai` (or `news --ai --watch`) produces a
similar briefing on its own. It is a paid call with the user's key, so run it only when the
user asks for it.

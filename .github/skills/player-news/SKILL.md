---
name: player-news
description: Gather the latest news, injuries and role changes for the user's fantasy basketball players, their ESPN watch list or any NBA player they name, combining benchboss news with web search. Use when the user asks for news, updates, injuries or what is going on with their players, the players they are watching, or a specific player.
argument-hint: optional player names, "watch list", and number of days (default 5)
---

# Player news

1. Start with ESPN's fantasy feed (RotoWire blurbs plus the "spin" analysis):

   ```bash
   benchboss news --json --days 5                 # whole roster, last 5 days
   benchboss news --json --days 5 --watch         # the user's ESPN watch list
   benchboss news --json "Ben Simmons"            # any NBA player: his latest 10 items, any date
   benchboss news --json "Ben Simmons" -n 20      # more of them
   benchboss news --json --days 3 "LaMelo Ball"   # a named player, last 3 days only
   ```

   Each item has `published`, `headline`, `spin`, `players`, `player_ids` and `section`
   (`roster`, `watch` or `players`). `--watch` and player names do not mix; run two commands
   if you need both. Check `published` before calling something "new": a named player's
   latest items can be weeks old.

2. Names are forgiving for news (never for writes). A close spelling picks the player and
   prints a note on stderr, such as `Showing Ben Simmons, the closest match to 'ben simons'.`:
   mention whom you looked up. A name that fits several players exits with code 2 and lists
   them with team, owner and % rostered (`'jalen' matches several players: ...`): ask the user
   which one, then run it again with the full name.
3. For "anything new?" questions, `benchboss alerts --json` lists watch-list news the user has
   not seen yet (`kind: "spin"`, with `player`, `headline`, `spin`, `published`). Do not run
   `benchboss alerts --mark-read` unless the user says they have read them: it stops those
   items from showing again in `alerts` and in the app.
4. Use web search for anything newer than the feed or for players with no items: injury
   reports, beat writers, team announcements. Prefer sources from the last 5 days.
5. Write one short line per player with news, most important first: what happened and what it
   means for fantasy (start, sit, hold, sell, watch, pick up). Keep roster and watch-list
   players apart. Say where each item came from.
6. If something affects tonight (a late scratch, a questionable tag), offer to rerun the
   lineup: `benchboss optimize today --dry-run`. If a watch-list player's role grew, offer the
   trash-scout skill to see what he would add this week.

If `ANTHROPIC_API_KEY` is set, `benchboss news --ai` (or `news --ai --watch`) produces a
similar briefing on its own. It is a paid call with the user's key, so run it only when the
user asks for it.

In the app, `n` opens Player news: `1` your roster, `2` your watch list, `[` `]` the window of
days, and `/` searches any player.

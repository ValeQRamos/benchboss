---
name: lineup-optimizer
description: Set the best ESPN fantasy basketball lineup for today, tomorrow, a date or the rest of the matchup week with the benchboss CLI. Use when the user asks to set, fix, optimize or check their lineup, or asks who should start or sit.
argument-hint: today | tomorrow | week | MM-DD
---

# Lineup optimizer

1. Pick the span from the request: `today` (default), `tomorrow`, `week` (every day left in
   the matchup week) or a date like `11-04`.
2. Preview without sending anything:

   ```bash
   benchboss optimize week --dry-run --json
   ```

   Each item has `date`, `moves` ("Player FROM -> TO") and `projected` points.
3. Summarize for the user: how many moves on how many days, the notable changes (who sits and
   why: no game, OUT, day-to-day discount, or simply a lower projection).
4. Ask for an explicit yes. Only then run:

   ```bash
   benchboss optimize week --yes
   ```

5. The command prints one `Wed Nov 4: ESPN: EXECUTED` line per day it changed and ends with
   `Your week is set: N moves across D days.` Report that last line and any day that did not
   say `EXECUTED`. Exit code 4 means ESPN refused at least one day; show those lines.

Notes: lineups are per day; future days are sent as future-roster moves and every day is
re-checked right before sending, so the final count can differ from the preview (moves carry
forward from one day to the next). Players whose game already started are locked and never
moved. If a day is already optimal nothing is sent for it.

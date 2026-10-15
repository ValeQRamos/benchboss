---
name: trash-scout
description: Find the most valuable free agents ("trash") for the current fantasy basketball matchup week with benchboss, including the best day to pick them up and who to drop. Use when the user asks who to pick up, stream, add, or which free agents are worth it.
argument-hint: optional position (PG SG SF PF C G F)
---

# Trash scout

1. Rank free agents by the points they would add this week:

   ```bash
   benchboss trash --json -n 10          # or: benchboss trash C --json
   ```

   Fields: `player` (name, team, positions, injury, proj, owned), `games_left`,
   `best_pickup_day`, `week_gain` (points over the weakest starter on the days he plays),
   `drop` and `drop_cost` (suggested release and what he would have scored), `net_gain`
   (points this week, not rest of season), `on_waivers`, `needs_drop`. The suggested drop
   always projects lower for the season than the free agent; `drop` is null when the roster
   has an open spot, or when `needs_drop` is true and nobody qualifies (say there is no clear
   drop).
2. Cross-check volume with `benchboss activity --json` if the user cares about games played.
3. Recommend at most three, each with one line of reasoning: net gain this week, games left,
   pickup day, injury flags. Mention waiver players cannot help until they clear.
4. If the user wants to act, preview with
   `benchboss add "Player" --drop "Player" --dry-run`, get an explicit yes, then run the same
   command with `--yes` and quote the `ESPN:` line.

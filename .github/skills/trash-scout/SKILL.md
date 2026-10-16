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
   `game_days` (the dates he would play for you, from the pickup day to Sunday),
   `best_pickup_day`, `week_gain` (points over the weakest starter on the days he plays),
   `drop` and `drop_cost` (suggested release and what he would have scored), `net_gain`
   (points this week, not rest of season), `on_waivers`, `needs_drop`,
   `drop_projects_higher`. The suggested drop is the cheapest player this week among those
   projected lower for the season than the free agent. When nobody projects lower it is the
   lowest projected player on the roster and `drop_projects_higher` is true: call that pick
   a one-week stream, not an upgrade. `drop` is null only when the roster has an open spot.
2. Cross-check volume with `benchboss activity --json` if the user cares about games played:
   `games`, `games_left`, and `games_in_lineup` (games in a starting slot, from the lineup
   ESPN has saved for each day). Each entry of `days` has `date`, `opponent`, `slot` and
   `starting`, and `on_roster` is false for a player who left the roster this week. To compare recent form, the player-finder skill
   (`benchboss players --json --sort l7`) has every stat split.
3. Recommend at most three, each with one line of reasoning: net gain this week, games left,
   pickup day, injury flags. Mention waiver players cannot help until they clear.
4. If the user wants to act, preview with
   `benchboss add "Player" --drop "Player" --dry-run`, get an explicit yes, then run the same
   command with `--yes` and quote the `ESPN:` line.

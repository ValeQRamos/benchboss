---
name: playoff-race
description: Report the fantasy basketball playoff race with benchboss (playoff, seed and division odds, clinched and eliminated teams, the games left) and answer what-if questions by fixing results. Use when the user asks about playoff chances, seeding, who is in or out, or what happens if they or another team win or lose a given week.
argument-hint: optional results to fix, like "Monstars>Tune Squad" or "Monstars>Tune Squad@11"
---

# Playoff race

Everything here is a read. Nothing is sent to ESPN.

1. Get the odds:

   ```bash
   benchboss playoffs --json
   ```

   Top level: `playoff_teams` (spots), `sims` (simulated seasons, 5,000 by default),
   `seeding_rule` (the league's tiebreaker), `weeks_left`, `picks`. Each row of `teams`, best
   projected seed first: `team`, `manager`, `division`, `record`, `points_for`,
   `projected_record` (average final record), `playoffs`, `division_title`, `seeds` (odds per
   seed, 1st first), `status` (`clinched`, `eliminated` or null), `espn_playoffs` (ESPN's own
   number) and `expected_weekly_points`. `games` lists every matchup left with `week`, `home`,
   `away`, `home_win` (share of simulations the home team won), `picked_winner` and `live`
   (being played this week).
2. What-if: fix one or more results and run it again.

   ```bash
   benchboss playoffs --json --pick "Monstars>Tune Squad"
   benchboss playoffs --json --pick "Monstars>Tune Squad@11" --pick "Brick City>Swish Kebab"
   ```

   Team or manager names work. Without `@WEEK` the pick is the next game between the two that
   is not decided yet. With picks, each team row adds `playoffs_without_picks`, so you can say
   what the result changes. An unknown team, a team playing itself or a pair with no game left
   stops with a message (exit code 1).
3. Answer in a few lines: the user's odds and likely seed, the teams around the playoff line,
   and the swing games left (their matchups in `games`, closest `home_win` to 0.5). For a
   what-if, give the odds before and after.

How to talk about the numbers:

- `playoffs` comes from benchboss's simulation; `espn_playoffs` (and `playoff_pct` in
  `benchboss standings --json`) is ESPN's. Say which one you quote. Early in the season they
  can differ a lot.
- Odds are shares from 0 to 1, not promises. Only `status` is certain: `clinched` means no mix
  of the open results keeps the team out, `eliminated` means none gets it in.
- Seeding follows ESPN: division winners first when the league has divisions, then the
  league's tiebreaker. The full model is in `docs/how-it-works.md` (Playoff race).
- For the current table (streaks, games back, clinch tags) use `benchboss standings --json`.

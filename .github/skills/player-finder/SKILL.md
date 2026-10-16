---
name: player-finder
description: Find fantasy basketball players by any stat split (season, last 7, 15 or 30 days, ESPN projection, last season) among free agents, rostered players, the user's ESPN watch list or everyone, and add or remove players on the watch list with benchboss. Use when the user asks who is hot, who is playing well lately, how a player has done over a stretch, or to watch or stop watching a player.
argument-hint: optional position (PG SG SF PF C G F), split (l7, l15, l30, season, proj, last) or a player name
---

# Player finder

1. Pick the pool, the position and the split from the request, then read:

   ```bash
   benchboss players --json --pos C --sort l7 -n 15          # free agent centers, best last 7 days
   benchboss players --json --from rostered --sort l15 -n 20 # players on a team in this league
   benchboss players --json --from all "jokic"               # anyone whose name starts like that
   benchboss watch --json                                    # the user's ESPN watch list
   ```

   `--from` is `fa` (free agents and waivers, the default), `rostered`, `watch` or `all`.
   `--sort` is a split (`proj`, `season`, `l7`, `l15`, `l30`, `last`), `own` (% rostered) or
   `change` (its weekly change). ESPN ranks the pool by it, so `--sort l7` really returns the
   best players of the last 7 days, not a re-sort of another list.

   Each player has `name`, `team`, `positions`, `injury`, `status` (`FREEAGENT`, `WAIVERS`,
   `ONTEAM`), `owner` (the fantasy team, or null), `owned`, `owned_change`, `started`,
   `watched`, and `stats` by split. In `stats.<split>`: `fpts` (fantasy points per game in
   this league's scoring), `gp`, `total`, and `per_game` (PTS, REB, AST, STL, BLK, 3PM, TO,
   FG%, FT% as a fraction, MIN, GP is the games count). A split with no games is missing;
   before opening night only `proj` and `last` exist.

2. Answer with the two or three players that fit, each with the numbers behind it: the split
   the user asked about, how it compares with `season` (or `proj`), minutes, games played,
   injury tag. The last 7 days hold three or four games at most, so say so when `gp` is low.
3. If the user wants to pick one up, hand off to the trash-scout skill (points added this
   week and who to drop) or preview `benchboss add "Player" --dry-run`.

## Watch list (a write to ESPN)

Adding or removing a player changes the user's ESPN watch list. It is private and easy to
undo, but it is still a write, so follow the protocol:

1. Preview: `benchboss watch add "Player" --dry-run` (or `watch remove`).
2. Wait for an explicit yes for that player.
3. Run `benchboss watch add "Player" --yes` and quote the `ESPN: watch list has N players`
   line. One approval covers one player.

If the player is already on the list (or not on it, for `remove`), the command says so and
sends nothing. With `--json` and no `--yes` it sends nothing and exits with code 10.

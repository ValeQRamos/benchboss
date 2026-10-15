---
name: trade-finder
description: Suggest fair fantasy basketball trades that fix positional needs (for example "I need a center") by analyzing every roster in the league with benchboss. Use when the user asks for trade ideas, who to trade with, or what a team needs.
argument-hint: optional position you need (PG SG SF PF C)
---

# Trade finder

1. See every team's positional balance (positive = surplus, negative = need):

   ```bash
   benchboss trades --needs --json
   ```

2. Get concrete ideas, filtered by what the user needs if they said so:

   ```bash
   benchboss trades --json --need C           # or --with "Team or manager"
   ```

   Each idea has `partner`, `owner`, `give`, `get`, `give_pos`, `get_pos`, `fairness`
   (1.0 = equal projected value) and a draft `message`.
3. Present the top two or three with the logic: what you give, what you get, why it helps both
   sides. Check injuries on both players with `benchboss news --json "Player"`.
4. Sending an offer is a write. Preview with
   `benchboss trade --give "A" --get "B" --msg "text" --dry-run`, get an explicit yes, then run
   it with `--yes` and quote the `ESPN:` line.

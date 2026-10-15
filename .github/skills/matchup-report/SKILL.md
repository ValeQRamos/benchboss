---
name: matchup-report
description: Report the current fantasy basketball matchup with benchboss: live score, projected final for both teams, games left, workload, alerts. Use when the user asks how they are doing, whether they will win this week, or for a weekly overview.
---

# Matchup report

1. Pull everything in one call:

   ```bash
   benchboss dash --json
   ```

   Keys: `matchup` (points, projected_final and games_left for `me` and `opponent`),
   `roster`, `activity`, `trash`, `alerts`, `news`, `standings`.
2. Answer in a few lines: score now, projected final, who has more games left, the biggest
   swing factors (injuries, players with many or few games), and anything urgent in `alerts`
   (a trade offer, unread DMs).
3. Offer the next useful action: optimize the week, look at trash, or check news.

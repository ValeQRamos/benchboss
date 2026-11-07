"""How long after a game does ESPN's fantasy stat split count it? Read-only: it changes nothing.

    python tools/probe_stat_lag.py "Player Name"            # pick a player whose game is on today
    python tools/probe_stat_lag.py "Player Name" --every 60

Start it before his game. Every ``--every`` seconds it asks three public or league reads and
prints a line when one of them changes: his team's game status, whether the public box score
has his line, and whether his season games played (the fantasy split) went up. At the end it
prints the lags from the moment the game went final. Needs a league from ``benchboss setup``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from benchboss import config as config_mod
from benchboss.errors import BenchbossError
from benchboss.espn.client import http
from benchboss.service import Session

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def stamp() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def find_game(team: str, days: int = 2) -> dict | None:
    """His team's newest game on today's or yesterday's scoreboard."""
    found = None
    for back in range(days):
        day = (dt.date.today() - dt.timedelta(days=back)).strftime("%Y%m%d")
        for ev in http(f"{SITE}/scoreboard", params={"dates": day}).get("events", []):
            teams = {c["team"]["abbreviation"] for c in ev["competitions"][0]["competitors"]}
            if team in teams and found is None:
                found = ev
    return found


def has_line(event_id: str, player_id: int) -> bool:
    """Whether the public box score already lists the player with minutes."""
    box = http(f"{SITE}/summary", params={"event": event_id}).get("boxscore", {})
    for team in box.get("players", []):
        for group in team.get("statistics", []):
            for a in group.get("athletes", []):
                if str(a["athlete"]["id"]) == str(player_id) and a.get("stats"):
                    return not a.get("didNotPlay", False)
    return False


def games_played(session: Session, name: str):
    pool = session.player_pool("all", None, 5, "season", name)
    pick = next((p for p in pool if p.name.lower() == name.lower()), pool[0] if pool else None)
    if pick is None:
        raise BenchbossError(f"no player matches '{name}'")
    line = pick.split("season")
    return pick, (line.gp if line else 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("player")
    ap.add_argument("--every", type=int, default=120, help="seconds between reads")
    args = ap.parse_args(argv)
    session = Session(config_mod.load())
    player, base = games_played(session, args.player)
    game = find_game(player.pro_team)
    if game is None:
        print(f"no game for {player.pro_team} on today's or yesterday's scoreboard")
        return 1
    print(f"{stamp()}  {player.name} ({player.id}) {player.pro_team}, game {game['id']}, "
          f"{base} games played in the fantasy season split")
    seen: dict[str, float] = {}
    last_status = ""
    while len(seen) < 3:
        status = http(f"{SITE}/summary", params={"event": game["id"]})["header"][
            "competitions"][0]["status"]["type"]["name"]
        if status != last_status:
            print(f"{stamp()}  game status: {status}")
            last_status = status
        if status == "STATUS_FINAL":
            seen.setdefault("final", time.time())
        if "box" not in seen and status != "STATUS_SCHEDULED" and has_line(game["id"], player.id):
            seen["box"] = time.time()
            print(f"{stamp()}  public box score has his line")
        _, gp = games_played(session, args.player)
        if gp > base and "fantasy" not in seen:
            seen["fantasy"] = time.time()
            print(f"{stamp()}  fantasy season split now counts the game ({base} to {gp})")
        if len(seen) < 3:
            time.sleep(args.every)
    final = seen["final"]
    print(f"\nbox score line: {(seen['box'] - final) / 60:+.1f} min from the final")
    print(f"fantasy split:  {(seen['fantasy'] - final) / 60:+.1f} min from the final")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BenchbossError, KeyboardInterrupt) as e:
        sys.exit(str(e) or 1)

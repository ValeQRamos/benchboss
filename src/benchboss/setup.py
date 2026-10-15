"""First-run wizard: cookies, league discovery, team, colors."""

from __future__ import annotations

import re
import sys
import urllib.parse

from benchboss import config as config_mod
from benchboss import credentials
from benchboss.errors import BenchbossError
from benchboss.espn.client import Client, http
from benchboss.espn.models import parse_league

FAN_API = "https://fan.api.espn.com/apis/v2/fans/"


def discover(cookies: tuple[str, str]) -> list[dict]:
    """Basketball leagues this ESPN account belongs to, from the account's fan profile.

    Each item: {league_id, league_name, team_id, season}.
    """
    swid = cookies[1]
    data = http(FAN_API + urllib.parse.quote(swid), cookies=cookies,
                params=[("displayHiddenPrefs", "true"), ("source", "espncom-fantasy-lm"),
                        ("lang", "en"), ("section", "espn"), ("region", "us")])
    out = []
    for pref in data.get("preferences") or []:
        entry = (pref.get("metaData") or {}).get("entry") or {}
        if (entry.get("abbrev") or "").upper() != "FBA":
            continue
        for g in entry.get("groups") or []:
            out.append({"league_id": g.get("groupId"), "league_name": g.get("groupName", ""),
                        "team_id": entry.get("entryId"), "season": entry.get("seasonId")})
    out.sort(key=lambda x: (-(x["season"] or 0), x["league_name"]))
    return out


def parse_league_id(text: str) -> int:
    m = re.search(r"leagueId=(\d+)", text) or re.fullmatch(r"\s*(\d{4,})\s*", text)
    if not m:
        raise BenchbossError("paste the league URL (it contains leagueId=...) or just the number")
    return int(m.group(1))


def _ask(c, prompt: str, default: str = "") -> str:
    if not sys.stdin.isatty():
        raise BenchbossError("setup needs an interactive terminal")
    suffix = f" [{default}]" if default else ""
    answer = c.out.input(f"[bold]{prompt}[/]{suffix} ").strip()
    return answer or default


def run(c) -> None:
    pal = c.pal
    out = c.out
    out.print(f"[bold {pal.accent}]benchboss setup[/]\n")

    # 1. cookies
    cookies = credentials.get()
    if cookies:
        out.print(f"[{pal.good}]✓[/] ESPN cookies found.")
    else:
        out.print("benchboss reads your league with the same two cookies your browser uses on "
                  "espn.com (espn_s2 and SWID). They stay on this computer, in your keychain.")
        how = "c" if sys.platform == "darwin" else "p"
        if sys.platform == "darwin":
            how = _ask(c, "Import them from Chrome (c) or paste them (p)?", "c").lower()[:1]
        if how == "c":
            source, s2, swid = credentials.from_chrome()
        else:
            import getpass

            out.print("In Chrome: espn.com > DevTools (Cmd/Ctrl+Option/Alt+I) > Application > "
                      "Cookies > https://www.espn.com, copy the values of espn_s2 and SWID.")
            s2, swid, source = getpass.getpass("espn_s2: "), getpass.getpass("SWID: "), "manual entry"
        where = credentials.store(s2, swid)
        out.print(f"[{pal.good}]✓[/] Cookies from {source} saved to {where}.")
        cookies = credentials.require()

    # 2. league
    season = config_mod.current_season()
    leagues = []
    try:
        leagues = [lg for lg in discover(cookies) if lg["season"] in (None, season)] or discover(cookies)
    except BenchbossError as e:
        out.print(f"[{pal.dim}]Could not list your leagues automatically ({e}).[/]")
    pick = None
    if len(leagues) == 1:
        pick = leagues[0]
        out.print(f"[{pal.good}]✓[/] Found your league: [bold]{pick['league_name']}[/] ({pick['season']}).")
    elif leagues:
        out.print("Your basketball leagues:")
        for i, lg in enumerate(leagues, 1):
            out.print(f"  {i}. {lg['league_name']}  [{pal.dim}]{lg['season']} · id {lg['league_id']}[/]")
        n = int(_ask(c, "Which one?", "1"))
        pick = leagues[max(1, min(n, len(leagues))) - 1]
    if pick:
        league_id, team_id, season = pick["league_id"], pick["team_id"], pick["season"] or season
    else:
        league_id = parse_league_id(_ask(c, "League URL or id (fantasy.espn.com/basketball/league?leagueId=...):"))
        team_id = None

    # 3. verify and find the team
    raw = Client(league_id, season, cookies).league("mTeam", "mSettings", "mStatus")
    lg = parse_league(raw, team_id, cookies[1], strict=False)
    if team_id is None and not any(cookies[1] in t.owner_ids for t in lg.teams.values()):
        out.print("Teams in this league:")
        teams = sorted(lg.teams.values(), key=lambda t: t.id)
        for t in teams:
            out.print(f"  {t.id}. {t.name}  [{pal.dim}]{t.owner_name}[/]")
        lg.my_team_id = int(_ask(c, "Which team is yours (number)?"))
    out.print(f"[{pal.good}]✓[/] {lg.name}: you are [bold]{lg.me.name}[/].")

    # 4. colors
    theme = _ask(c, "Terminal background: dark (d) or light (l)?", "d").lower()[:1]
    cfg = c.cfg
    cfg.league_id, cfg.team_id, cfg.season = league_id, lg.my_team_id, season
    cfg.league_name, cfg.team_name = lg.name, lg.me.name
    cfg.theme = "light" if theme == "l" else "dark"
    path = config_mod.save(cfg)
    out.print(f"[{pal.good}]✓[/] Saved to {path}\n")
    out.print("You are all set. Try:\n  [bold]benchboss[/]            the app\n"
              "  [bold]benchboss dash[/]       the dashboard\n  [bold]benchboss optimize week[/]")

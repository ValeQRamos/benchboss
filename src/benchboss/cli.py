"""Command line interface. Run ``benchboss`` with no arguments for the interactive app."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time

from rich.console import Console
from rich.text import Text

from benchboss import __version__, credentials
from benchboss import config as config_mod
from benchboss.errors import BenchbossError, NotConfirmed, WriteFailed
from benchboss.ui import views
from benchboss.ui.theme import palette

EPILOG = """\
examples:
  benchboss                      open the interactive app (menu, dashboard, one-key actions)
  benchboss dash --watch         live dashboard, refreshes every 60 s (great in a side terminal)
  benchboss optimize week        set the best lineup for every day left in the matchup week
  benchboss trash                most valuable free agents for this week
  benchboss news --days 5        latest news and spins on your players
  benchboss trades --need C      fair trades that get you a center
  benchboss roster --json        machine-readable output for scripts and AI agents

docs: https://github.com/ValeQRamos/benchboss   bugs and ideas: k1lldeer@proton.me
"""


class Ctx:
    def __init__(self, args):
        self.args = args
        self.cfg = config_mod.load()
        if getattr(args, "theme", None):
            self.cfg.theme = args.theme
        self.pal = palette(self.cfg.theme)
        self.out = Console(highlight=False)
        self.err = Console(stderr=True, highlight=False)
        self._session = None

    @property
    def session(self):
        if self._session is None:
            if self.args.demo:
                from benchboss.demo import demo_session

                self._session = demo_session(self.cfg)
            else:
                from benchboss.service import Session

                self._session = Session(self.cfg)
        return self._session

    def emit(self, renderable, data) -> None:
        if self.args.json:
            print(json.dumps(data, indent=2, default=str))
        else:
            self.out.print(renderable)

    def confirm(self, question: str = "Go ahead?") -> bool:
        if self.args.yes:
            return True
        if self.args.demo:
            self.out.print(f"[{self.pal.dim}]demo mode: nothing is sent to ESPN[/]")
            return False
        if not sys.stdin.isatty():
            raise NotConfirmed("NOT DONE: no terminal to confirm; repeat with --yes")
        answer = self.out.input(f"[bold]{question}[/] [y/N] ").strip().lower()
        if answer in ("y", "yes", "s", "si"):
            return True
        self.out.print("NOT DONE")
        return False


# --- account ------------------------------------------------------------------------------------

def cmd_login(c: Ctx):
    a = c.args
    if a.manual or (not a.chrome and sys.platform != "darwin"):
        c.out.print("Paste your ESPN cookies (they are hidden while you type).\n"
                    "Find them at espn.com: DevTools > Application > Cookies > espn.com")
        s2 = getpass.getpass("espn_s2: ")
        swid = getpass.getpass("SWID: ")
        source = "manual entry"
    else:
        source, s2, swid = credentials.from_chrome()
    where = credentials.store(s2, swid)
    c.out.print(f"[{c.pal.good}]✓[/] Cookies from {source} saved to {where}.")
    if not c.cfg.league_id:
        c.out.print("Next: [bold]benchboss setup[/] to pick your league and team.")


def cmd_logout(c: Ctx):
    credentials.clear()
    c.out.print("Cookies removed.")


def cmd_setup(c: Ctx):
    from benchboss import setup as setup_mod

    setup_mod.run(c)


def cmd_status(c: Ctx):
    cfg = c.cfg
    creds = credentials.get()
    data = {"version": __version__, "config": str(cfg.path), "league_id": cfg.league_id,
            "team_id": cfg.team_id, "season": cfg.effective_season, "theme": cfg.theme,
            "cookies": bool(creds)}
    lines = [f"benchboss {__version__}", f"config     {cfg.path}",
             f"league     {cfg.league_id or '-'} {cfg.league_name}",
             f"team       {cfg.team_id or 'auto'} {cfg.team_name}",
             f"season     {cfg.effective_season}", f"theme      {cfg.theme}",
             f"cookies    {'found' if creds else 'missing (run benchboss login)'}"]
    if creds and cfg.league_id and not c.args.offline:
        try:
            lg = c.session.league()
            data["connected"] = True
            lines.append(f"ESPN       connected: {lg.name}, team {lg.me.name}")
        except BenchbossError as e:
            data["connected"] = False
            lines.append(f"ESPN       {e}")
    c.emit("\n".join(lines), data)


# --- read -------------------------------------------------------------------------------------------

def cmd_dash(c: Ctx):
    from benchboss.ui import dashboard

    def once():
        d = dashboard.collect(c.session)
        return d

    if c.args.json:
        print(json.dumps(once().to_dict(), indent=2, default=str))
        return
    if not c.args.watch:
        c.out.print(dashboard.render(once(), c.pal, c.out.width))
        return
    from rich.live import Live

    with Live(console=c.out, screen=True, auto_refresh=False) as live:
        while True:
            try:
                live.update(dashboard.render(once(), c.pal, c.out.width), refresh=True)
            except BenchbossError as e:
                live.update(f"[{c.pal.bad}]{e}[/] (retrying)", refresh=True)
            time.sleep(max(15, c.args.watch))


def cmd_roster(c: Ctx):
    s = c.session
    lg = s.league()
    cal = s.calendar
    today = {sp.player.id for sp in lg.me.roster if cal.plays(sp.player.pro_team_id, s.today_period)}
    c.emit(views.roster(lg, c.pal, today),
           [{"slot": sp.slot, "plays_today": sp.player.id in today, **sp.player.to_dict()}
            for sp in lg.me.roster])


def cmd_standings(c: Ctx):
    lg = c.session.league()
    c.emit(views.standings(lg, c.pal),
           [{"rank": i + 1, "team": t.name, "manager": t.owner_name, "record": t.record,
             "points_for": t.points_for} for i, t in enumerate(lg.standings())])


def cmd_matchup(c: Ctx):
    from benchboss.ui import dashboard

    d = dashboard.collect(c.session, with_trash=False, with_alerts=False, with_trending=False)
    from rich.constrain import Constrain

    c.emit(Constrain(dashboard.matchup_card(d, c.pal), 60), d.outlook.to_dict() if d.outlook else None)


def cmd_activity(c: Ctx):
    s = c.session
    acts = s.activity()
    periods = s.matchup_periods()
    c.emit(views.activity(acts, s.calendar, periods, s.today_period, c.pal),
           [a.to_dict() for a in acts])


def cmd_fa(c: Ctx):
    s = c.session
    sort = "sortPercChanged" if c.args.cmd == "trending" else "sortPercOwned"
    players = s.free_agents(c.args.n, getattr(c.args, "pos", None), sort=sort)
    title = "Rising on waivers" if c.args.cmd == "trending" else "Free agents by % rostered"
    c.emit(views.free_agents(players, c.pal, title), [p.to_dict() for p in players])


def cmd_trash(c: Ctx):
    s = c.session
    picks = s.trash(n=c.args.n, position=c.args.pos, pool=max(60, c.args.n * 4))
    c.emit(views.trash(picks, s.calendar, c.pal, c.out.width),
           [p.to_dict(s.calendar) for p in picks])


def cmd_trades(c: Ctx):
    from benchboss.core import trades as trades_mod

    s = c.session
    lg = s.league()
    if c.args.needs:
        bal = trades_mod.describe_needs(lg)
        c.emit(views.needs(bal, lg.me.name, c.pal), bal)
        return
    ideas = trades_mod.find_trades(lg, need=c.args.need, limit=c.args.n,
                                   min_fairness=c.args.fairness,
                                   partner_id=_partner(s, c.args.partner))
    c.emit(views.trades(ideas, c.pal, c.args.need, lg), [t.to_dict() for t in ideas])


def _partner(s, q):
    if not q:
        return None
    from benchboss.text import match_one

    lg = s.league()
    return match_one(lg.teams.values(), q, lambda t: f"{t.name} {t.owner_name}", where="this league").id


def cmd_news(c: Ctx):
    from benchboss import news as news_mod

    s = c.session
    lg = s.league()
    roster = [sp.player for sp in lg.me.roster]
    if c.args.players:
        roster = [s.find_player(q) for q in c.args.players]
    names = {p.id: p.name for p in roster}
    if c.args.ai:
        with c.out.status("Asking Claude to search the web..."):
            text = news_mod.ai_digest(roster, c.args.days)
        c.emit(text, {"digest": text})
        return
    items = s.news([p.id for p in roster], c.args.days)
    c.emit(views.news(items, names, c.pal, c.args.days), [i.to_dict(names) for i in items])


def cmd_alerts(c: Ctx):
    from benchboss import inbox

    items = inbox.alerts(c.session)
    c.emit(views.alerts(items, c.pal), [a.to_dict() for a in items])


# --- write ------------------------------------------------------------------------------------------

def cmd_optimize(c: Ctx):
    from benchboss.service import periods_for

    s = c.session
    periods = [p for p in periods_for(s, c.args.when) if p >= s.league().scoring_period]
    if not periods:
        raise BenchbossError("those days are already over")
    plans = s.plan_days(periods)
    todo = [p for p in plans if p.changed]
    if c.args.json and (c.args.dry_run or not c.args.yes):
        print(json.dumps([{"date": s.calendar.date_of(p.period).isoformat(),
                           "moves": [str(m) for m in p.moves], "projected": round(p.projected, 1)}
                          for p in plans], indent=2))
        return
    if not c.args.quiet:
        c.out.print(views.plan(plans, s.calendar, c.pal))
    if not todo:
        c.out.print(Text(f"✓ Your lineup is already optimal for {_span(len(plans))}.",
                         style=c.pal.good))
        return
    if c.args.dry_run:
        c.out.print(Text("Dry run: nothing was sent. Moves on one day carry forward, so later "
                         "days are re-checked when you apply.", style=c.pal.dim))
        return
    if not c.confirm(f"Apply the lineup for {len(plans)} day{'s' * (len(plans) != 1)}?"):
        return
    results = s.apply_days([p.period for p in plans])
    moves, days, failed = 0, 0, []
    for r in results:
        day = s.calendar.date_of(r.plan.period)
        label = f"{day:%a %b} {day.day}"
        if r.error:
            failed.append(f"{label}: {r.error}")
        elif r.status != "ALREADY_OPTIMAL":
            moves += len(r.plan.moves)
            days += 1
            c.out.print(Text(f"{label}: ESPN: {r.status}", style=c.pal.dim))
    for f in failed:
        c.err.print(Text(f"✗ {f}", style=c.pal.bad))
    if failed:
        raise WriteFailed(f"{len(failed)} day(s) were not set; the others were sent")
    c.out.print(Text(f"✓ Your {_span(len(plans))} is set: {moves} move{'s' * (moves != 1)} "
                     f"across {days} day{'s' * (days != 1)}.", style=f"bold {c.pal.good}"))


def _span(n_days: int) -> str:
    return "day" if n_days == 1 else "week"


def _write(c: Ctx, pending):
    c.out.print(Text(pending.summary))
    if c.args.dry_run:
        c.out.print(Text("Dry run: nothing was sent.", style=c.pal.dim))
        return
    if c.confirm():
        c.out.print(f"ESPN: {pending.run(c.session)}")


def cmd_add(c: Ctx):
    from benchboss import actions

    _write(c, actions.prepare_add(c.session, c.args.player, c.args.drop, c.args.bid))


def cmd_drop(c: Ctx):
    from benchboss import actions

    _write(c, actions.prepare_drop(c.session, c.args.player))


def cmd_trade(c: Ctx):
    from benchboss import actions

    _write(c, actions.prepare_trade(c.session, c.args.give, c.args.get, c.args.msg or ""))


def cmd_chat(c: Ctx):
    from benchboss import inbox

    s = c.session
    to = inbox.resolve_member(s, c.args.to) if c.args.to else None
    if not c.args.text:
        tid, label = inbox.thread(s, to)
        msgs = inbox.messages(s, tid, c.args.n) if tid else []
        ppl = inbox.people(s)
        rows = [inbox.format_message(m, ppl, s) for m in msgs]
        if c.args.json:
            print(json.dumps([{"date": inbox.iso_date(m), "who": who, "text": t}
                              for m, (_, who, t) in zip(msgs, rows, strict=True)], indent=2))
            return
        c.out.print(Text(label, style=f"bold {c.pal.accent}"))
        for w, who, t in rows:
            c.out.print(Text.assemble((w, c.pal.dim), "  ", (who, "bold"), ": ", t))
        if not rows:
            c.out.print(Text("(no messages yet)", style=c.pal.dim))
        return
    _, label = inbox.thread(s, to)
    c.out.print(Text(f"Message to {label}: {c.args.text}"))
    if c.args.dry_run:
        c.out.print(Text("Dry run: nothing was sent.", style=c.pal.dim))
        return
    if c.confirm():
        c.out.print(f"ESPN: {inbox.send(s, c.args.text, to)}")


def cmd_app(c: Ctx):
    from benchboss.ui.app import run

    run(c.cfg, demo=c.args.demo)


# --- parser -------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    def global_options(suppress: bool) -> argparse.ArgumentParser:
        # the same flags work before or after the command; inside subcommands they default to
        # SUPPRESS so they never overwrite a value given before the command
        g = argparse.ArgumentParser(add_help=False)
        kw = {"default": argparse.SUPPRESS} if suppress else {}
        g.add_argument("--json", action="store_true", help="machine-readable JSON output", **kw)
        g.add_argument("--demo", action="store_true",
                       help="use built-in sample data, no ESPN account needed", **kw)
        g.add_argument("--theme", choices=config_mod.THEMES, help="color palette for this run", **kw)
        g.add_argument("-y", "--yes", action="store_true", help="skip the confirmation on writes", **kw)
        return g

    common = global_options(suppress=True)
    ap = argparse.ArgumentParser(
        prog="benchboss", parents=[global_options(suppress=False)],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Run your ESPN Fantasy Basketball team from the terminal.", epilog=EPILOG)
    ap.add_argument("-V", "--version", action="version", version=f"benchboss {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    def add(name, fn, help_, **kw):
        p = sub.add_parser(name, parents=[common], help=help_,
                           description=help_.replace("%%", "%"), **kw)
        p.set_defaults(fn=fn)
        return p

    add("app", cmd_app, "open the interactive app (same as running benchboss with no command)")
    p = add("dash", cmd_dash, "the dashboard: matchup, roster, workload, trash, standings")
    p.add_argument("--watch", nargs="?", type=int, const=60, metavar="SECONDS",
                   help="keep it open and refresh (default every 60 s)")
    add("setup", cmd_setup, "first-run wizard: cookies, league, team, colors")
    p = add("login", cmd_login, "save your ESPN cookies (from Chrome on macOS, or pasted)")
    p.add_argument("--chrome", action="store_true", help="import from Google Chrome (macOS)")
    p.add_argument("--manual", action="store_true", help="paste espn_s2 and SWID by hand")
    add("logout", cmd_logout, "forget the saved cookies")
    for name in ("status", "doctor"):
        p = add(name, cmd_status, "show config and check the connection to ESPN")
        p.add_argument("--offline", action="store_true", help="do not call ESPN")

    add("roster", cmd_roster, "your roster with slots, injuries, averages and projections")
    add("standings", cmd_standings, "league table")
    add("matchup", cmd_matchup, "this week's matchup: live score, projected final, games left")
    add("activity", cmd_activity, "games per player this matchup week, day by day")
    p = add("trash", cmd_trash, "most valuable free agents for this week (points added, best day to grab)")
    p.add_argument("pos", nargs="?", help="PG SG SF PF C G F")
    p.add_argument("-n", type=int, default=10, help="how many (default 10)")
    p = add("fa", cmd_fa, "free agents by %% rostered")
    p.add_argument("pos", nargs="?", help="PG SG SF PF C G F")
    p.add_argument("-n", type=int, default=25)
    p = add("trending", cmd_fa, "free agents being added the most")
    p.add_argument("-n", type=int, default=15)
    p = add("news", cmd_news, "recent news and spins on your players (or on the players you name)")
    p.add_argument("players", nargs="*", help="player names; default: your roster")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--ai", action="store_true", help="AI briefing with web search (needs ANTHROPIC_API_KEY)")
    p = add("trades", cmd_trades, "trade finder: fair 1-for-1 deals that fix positional needs")
    p.add_argument("--need", choices=["PG", "SG", "SF", "PF", "C", "pg", "sg", "sf", "pf", "c"],
                   help="only deals that bring you this position")
    p.add_argument("--with", dest="partner", metavar="TEAM", help="only this team or manager")
    p.add_argument("--fairness", type=float, default=0.85, help="minimum value match 0-1 (default 0.85)")
    p.add_argument("--needs", action="store_true", help="show every team's positional surplus and needs")
    p.add_argument("-n", type=int, default=8)
    add("alerts", cmd_alerts, "trade offers, accepted trades, pending claims, unread DMs")

    p = add("optimize", cmd_optimize, "set the best lineup: today, tomorrow, week, or a date")
    p.add_argument("when", nargs="?", default="today", help="today (default), tomorrow, week, 11-04, 2026-11-04")
    p.add_argument("--dry-run", action="store_true", help="show the plan, send nothing")
    p.add_argument("-q", "--quiet", action="store_true", help="only print the final result")
    p = add("add", cmd_add, "sign a free agent or put in a waiver claim")
    p.add_argument("player")
    p.add_argument("--dry-run", action="store_true", help="show the move, send nothing")
    p.add_argument("--drop", help="player to release in the same move")
    p.add_argument("--bid", type=int, help="FAAB bid, if your league uses a budget")
    p = add("drop", cmd_drop, "release a player")
    p.add_argument("player")
    p.add_argument("--dry-run", action="store_true", help="show the move, send nothing")
    p = add("trade", cmd_trade, "send a trade offer")
    p.add_argument("--give", action="append", required=True, metavar="PLAYER")
    p.add_argument("--get", action="append", required=True, metavar="PLAYER")
    p.add_argument("--msg", help="note the other manager will see")
    p.add_argument("--dry-run", action="store_true", help="show the offer, send nothing")
    p = add("chat", cmd_chat, "read or post in the league chat, or a DM with --to")
    p.add_argument("text", nargs="?")
    p.add_argument("--to", metavar="TEAM_OR_NAME", help="direct message instead of the league chat")
    p.add_argument("--dry-run", action="store_true", help="show the message, send nothing")
    p.add_argument("-n", type=int, default=15)
    return ap


def main(argv: list[str] | None = None) -> None:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        args.cmd, args.fn = "app", cmd_app
    try:
        c = Ctx(args)
        args.fn(c)
    except BenchbossError as e:
        Console(stderr=True, highlight=False).print(Text.assemble(("benchboss: ", "bold red"), str(e)))
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

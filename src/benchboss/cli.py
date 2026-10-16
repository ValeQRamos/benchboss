"""Command line interface. Run ``benchboss`` with no arguments for the interactive app."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import getpass
import json
import sys
import time

from rich.console import Console
from rich.text import Text

from benchboss import __version__, credentials
from benchboss import config as config_mod
from benchboss.errors import BenchbossError, ConfigError, NotConfirmed, WriteFailed
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
        try:
            self.cfg = config_mod.load()
        except ConfigError:
            if not args.demo:
                raise
            self.cfg = config_mod.Config()  # the demo league does not need the real config
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

    def usage(self, message: str):
        """Bad usage found after parsing: the command's usage line and ``message`` on stderr,
        exit 2, the same as argparse's own checks."""
        self.args.parser.error(message)

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

def _not_in_demo(c: Ctx) -> None:
    if c.args.demo:
        raise BenchbossError(f"`{c.args.cmd}` works on your real account, so it is off in demo mode; "
                             "run it without --demo")


def cmd_login(c: Ctx):
    _not_in_demo(c)
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
    _not_in_demo(c)
    credentials.clear()
    c.out.print("Cookies removed.")


def cmd_setup(c: Ctx):
    _not_in_demo(c)
    from benchboss import setup as setup_mod

    setup_mod.run(c)


def cmd_status(c: Ctx):
    if c.args.demo:
        _demo_status(c)
        return
    cfg = c.cfg
    creds = credentials.get()
    data = {"version": __version__, "demo": False, "config": str(cfg.path), "league_id": cfg.league_id,
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
            # keep the reason in the JSON too: exit code 3 means the cookies need a new login
            data.update(connected=False, error=str(e), error_code=e.exit_code)
            lines.append(f"ESPN       {e}")
    c.emit("\n".join(lines), data)


def _demo_status(c: Ctx):
    """Status of the built-in demo league; the real config and keychain are never read."""
    lg = c.session.league()
    data = {"version": __version__, "demo": True, "config": None, "league_id": lg.id,
            "team_id": lg.my_team_id, "season": lg.season, "theme": c.cfg.theme,
            "cookies": None, "connected": False}
    lines = [f"benchboss {__version__}",
             "mode       demo: built-in sample data, your config and cookies are not read",
             f"league     {lg.id} {lg.name}", f"team       {lg.my_team_id} {lg.me.name}",
             f"season     {lg.season}", f"theme      {c.cfg.theme}"]
    c.emit(Text("\n".join(lines)), data)


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
                board = dashboard.render(once(), c.pal, c.out.width)
                live.update(_fit_height(c.out, board, c.out.height, c.pal), refresh=True)
            except BenchbossError as e:
                live.update(f"[{c.pal.bad}]{e}[/] (retrying)", refresh=True)
            time.sleep(max(15, c.args.watch))


def _fit_height(console: Console, renderable, height: int, pal):
    """Cut a render that is taller than the screen and say so: a full-screen Live view
    would crop it without any hint."""
    lines = console.render_lines(renderable, console.options, pad=False)
    if len(lines) <= height:
        return renderable
    from rich.console import Group
    from rich.segment import SegmentLines

    return Group(SegmentLines(lines[:max(1, height - 1)], new_lines=True),
                 Text("more below: make the pane taller", style=pal.dim, no_wrap=True,
                      overflow="ellipsis"))


def _screen(c: Ctx, module, **options) -> None:
    """Print one of the app's screens (ui/screens) with its --view, or its JSON."""
    from benchboss.ui.screens import view_index

    view = view_index(module, getattr(c.args, "view", None))
    data = module.load(c.session, **options)
    if c.args.json:
        print(json.dumps(module.to_json(data), indent=2, default=str))
    else:
        c.out.print(module.draw(data, c.pal, c.out.width, view))


def cmd_roster(c: Ctx):
    from benchboss.ui.screens import roster

    _screen(c, roster)


def cmd_standings(c: Ctx):
    from benchboss.ui.screens import standings

    _screen(c, standings)


def cmd_players(c: Ctx):
    from benchboss.espn.constants import SPLITS
    from benchboss.ui.screens import finder

    a = c.args
    # the stats shown follow --sort unless --view says otherwise, and the other way round
    sort = a.sort or (a.view if a.view in SPLITS else "proj")
    a.view = a.view or (sort if sort in SPLITS else "proj")
    _screen(c, finder, source=a.source, position=a.pos, sort=sort,
            query=" ".join(a.query) or None, n=a.n)


def cmd_watch(c: Ctx):
    """benchboss watch: list the watch list; watch add/remove PLAYER changes it on ESPN."""
    from benchboss.ui.screens import finder

    a = c.args
    name = " ".join(a.player).strip()
    if not a.action or a.action == "list":
        if name:
            c.usage("`watch list` takes no player; use `watch add` or `watch remove`")
        a.view = "proj"  # benchboss watch has no --view: show the projections
        _screen(c, finder, source="watch")
        return
    if not name:
        c.usage(f"name the player: benchboss watch {a.action} \"Player\"")
    s = c.session
    on = a.action == "add"
    p = _watch_target(s, name, on)
    listed = p.id in s.watch_list()
    if on == listed:
        msg = f"{p.name} is {'already' if on else 'not'} on your watch list: nothing to do."
        c.emit(Text(msg, style=c.pal.dim), {"summary": msg, "dry_run": bool(a.dry_run),
                                            "sent": False, "status": None, "error": None})
        return
    summary = (f"Add {p.name} ({p.pro_team}) to your ESPN watch list" if on
               else f"Take {p.name} ({p.pro_team}) off your ESPN watch list")
    _write(c, summary, lambda: f"watch list has {len(s.set_watched(p.id, on))} players")


def _watch_target(s, name: str, on: bool):
    """The player `watch add/remove NAME` is about.

    remove looks at the watch list first, so "Allen" is the Allen you watch. Otherwise the
    players on every roster and ESPN's name search count together: a name that fits a
    rostered player and a free agent matches several players, it is not quietly the
    rostered one (Session.find_player looks at the rosters first).
    """
    from benchboss.text import match_one, norm

    if not on:
        watched = s.player_pool("watch")
        if any(norm(name) in norm(p.name) for p in watched):
            return match_one(watched, name, lambda p: p.name, where="your watch list")
    lg = s.league()
    found = {sp.player.id: sp.player for t in lg.teams.values() for sp in t.roster}
    for p in s.player_pool("all", n=10, sort="own", query=name):
        found.setdefault(p.id, p)
    return match_one(found.values(), name, lambda p: p.name, where="your league or free agency")


def cmd_playoffs(c: Ctx):
    from benchboss.ui.screens import playoffs

    _screen(c, playoffs, picks=_picks(c.session, c.args.pick), sims=c.args.sims)


def _picks(s, specs: list[str] | None) -> dict[int, int]:
    """--pick "Winner>Loser" (team or manager names) -> {matchup id: winning team id}.

    The matchup is the first undecided regular-season game between those two teams, or the
    one in the week given as "Winner>Loser@WEEK".
    """
    if not specs:
        return {}
    from benchboss.core import playoffs as playoffs_mod

    return playoffs_mod.parse_picks(s.league(), specs)


def cmd_matchup(c: Ctx):
    from benchboss.ui import dashboard

    d = dashboard.collect(c.session, with_trash=False, with_alerts=False, with_trending=False)
    from rich.constrain import Constrain

    c.emit(Constrain(dashboard.matchup_card(d, c.pal), 60), d.outlook.to_dict() if d.outlook else None)


def cmd_activity(c: Ctx):
    from benchboss.ui.screens import workload

    _screen(c, workload)


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
    from benchboss.text import match_one, norm

    def label(t):
        return f"{t.name} {t.owner_name}"

    lg = s.league()
    others = [t for t in lg.teams.values() if t.id != lg.my_team_id]
    if not any(norm(q) in norm(label(t)) for t in others) and norm(q) in norm(label(lg.me)):
        raise BenchbossError(f"'{q}' is your own team: name another team or manager")
    return match_one(others, q, label, where="the other teams of this league", kind="teams").id


def cmd_news(c: Ctx):
    """News on your roster, on your watch list (--watch) or on the players you name."""
    from benchboss import news as news_mod
    from benchboss.ui.screens import news as screen

    a = c.args
    s = c.session
    if a.watch and a.players:
        c.usage("name players or use --watch, not both")
    named = [s.find_player(q) for q in a.players] if a.players else None
    which = () if named else ("watch",) if a.watch else ("roster",)
    if a.ai:
        players = list({p.id: p for sec in screen.sections(s, which, named)
                        for p in sec.players}.values())
        if not players:
            raise BenchbossError(f"{screen.EMPTY_WATCH} {screen.WATCH_ADD}" if a.watch else
                                 "your roster is empty")
        with c.out.status("Asking Claude to search the web..."):
            text = news_mod.ai_digest(players, a.days)
        c.emit(text, {"digest": text})
        return
    data = screen.load(s, a.days, which, named)
    c.emit(screen.draw(data, c.pal, c.out.width), screen.to_json(data))


def cmd_alerts(c: Ctx):
    """Trade offers, claims and unread DMs, then unseen news on watch-list players;
    --mark-read marks the news shown as seen."""
    from rich.console import Group

    from benchboss import inbox

    s = c.session
    mark = c.args.mark_read
    items = inbox.alerts(s, include_spins=False)
    try:
        spins = inbox.spin_alerts(s, mark_seen=mark)  # one read, so what is marked is what shows
    except BenchbossError as e:
        if mark:
            raise
        spins = []
        c.err.print(Text(f"Watch list news is not available right now ({e}).", style=c.pal.dim))
    items += spins
    n = len(spins)
    if mark:  # with nothing at all to show, the "Nothing new" line says it already
        note = (f"Marked {n} watch list item{'s' * (n != 1)} as read." if n else
                "No new watch list news to mark as read." if items else "")
    else:
        note = "benchboss alerts --mark-read marks the watch list news as read." if n else ""
    c.emit(Group(views.alerts(items, c.pal), *([Text(f"\n{note}", style=c.pal.dim)] if note else [])),
           [x.to_dict() for x in items])


# --- write ------------------------------------------------------------------------------------------

def cmd_optimize(c: Ctx):
    from benchboss.service import periods_for

    s = c.session
    periods = [p for p in periods_for(s, c.args.when) if p >= s.league().scoring_period]
    if not periods:
        raise BenchbossError("those days are already over")
    plans = s.plan_days(periods)
    todo = [p for p in plans if p.changed]
    if c.args.json:
        _optimize_json(c, s, plans, todo)
        return
    when = _when(s, plans)
    if not c.args.quiet:
        c.out.print(views.plan(plans, s.calendar, c.pal))
    if not todo:
        c.out.print(Text(f"✓ Your lineup is already optimal for {when}.", style=c.pal.good))
        return
    if c.args.dry_run:
        c.out.print(Text("Dry run: nothing was sent. Moves on one day carry forward, so later "
                         "days are re-checked when you apply.", style=c.pal.dim))
        return
    if not c.confirm(f"Apply the lineup for {len(plans)} day{'s' * (len(plans) != 1)}?"):
        return
    results = s.apply_days([p.period for p in plans])
    for r in results:
        if not r.error and r.status != "ALREADY_OPTIMAL":
            c.out.print(Text(f"{_label(s.calendar.date_of(r.plan.period))}: ESPN: {r.status}",
                             style=c.pal.dim))
    moves, days = _check_results(c, s, results)
    done = f"{moves} move{'s' * (moves != 1)}"
    if len(plans) == 1:
        msg = f"✓ Your lineup for {when} is set: {done}."
    else:
        msg = f"✓ Your week is set: {done} across {days} day{'s' * (days != 1)}."
    c.out.print(Text(msg, style=f"bold {c.pal.good}"))


def _optimize_json(c: Ctx, s, plans, todo) -> None:
    """JSON mode: the plan (dry run or not confirmed) or what ESPN answered for each day.
    stdout stays valid JSON; errors go to stderr with the usual exit codes."""
    from benchboss.service import OptimizeResult

    def row(plan, result=None):
        out = {"date": s.calendar.date_of(plan.period).isoformat(),
               "moves": [str(m) for m in plan.moves], "projected": round(plan.projected, 1)}
        if result is not None:
            out.update(status=result.status or None, error=result.error or None)
        return out

    if c.args.dry_run or not c.args.yes:
        print(json.dumps([row(p) for p in plans], indent=2))
        if todo and not c.args.dry_run:
            raise NotConfirmed("NOT DONE: nothing was sent; repeat with --yes to apply the plan")
        return
    if todo:
        results = s.apply_days([p.period for p in plans])
    else:
        results = [OptimizeResult(p, status="ALREADY_OPTIMAL") for p in plans]
    print(json.dumps([row(r.plan, r) for r in results], indent=2))
    _check_results(c, s, results)


def _check_results(c: Ctx, s, results) -> tuple[int, int]:
    """Count what ESPN applied; raise WriteFailed (exit 4) when any day was not set."""
    moves, days, failed = 0, 0, []
    for r in results:
        if r.error:
            failed.append(f"{_label(s.calendar.date_of(r.plan.period))}: {r.error}")
        elif r.status != "ALREADY_OPTIMAL":
            moves += len(r.plan.moves)
            days += 1
    for f in failed:
        c.err.print(Text(f"✗ {f}", style=c.pal.bad))
    if failed:
        rest = "nothing was changed" if days == 0 else f"{days} other day(s) were set"
        raise WriteFailed(f"{len(failed)} day(s) were not set; {rest}")
    return moves, days


def _label(day: dt.date) -> str:
    return f"{day:%a %b} {day.day}"


def _when(s, plans) -> str:
    """'today', 'tomorrow' or the date for one day; 'the rest of the week' for several."""
    if len(plans) != 1:
        return "the rest of the week"
    day = s.calendar.date_of(plans[0].period)
    if day == s.today:
        return "today"
    if day == s.today + dt.timedelta(days=1):
        return "tomorrow"
    return _label(day)


def _write(c: Ctx, summary: str, send) -> None:
    """Show a write, ask, send it and print ESPN's answer.

    With --json, stdout gets one JSON object (summary, dry_run, sent, status, error) and
    nothing else. ESPN can answer HTTP 200 with a FAILED_* status (roster lock, undroppable
    player and so on): that exits 4 like any other refused write."""
    js = c.args.json
    result = {"summary": summary, "dry_run": bool(c.args.dry_run), "sent": False,
              "status": None, "error": None}
    if not js:
        c.out.print(Text(summary))
    if c.args.dry_run:
        if js:
            print(json.dumps(result, indent=2))
        else:
            c.out.print(Text("Dry run: nothing was sent.", style=c.pal.dim))
        return
    if js and not c.args.yes:
        # never prompt in JSON mode: the question would end up inside the JSON
        print(json.dumps(result, indent=2))
        raise NotConfirmed("NOT DONE: nothing was sent; repeat with --yes to send it")
    if not c.confirm():
        return
    try:
        status = send()
    except BenchbossError as e:
        if js:
            print(json.dumps({**result, "error": str(e)}, indent=2))
        raise
    failed = status.startswith("FAILED")
    if js:
        print(json.dumps({**result, "sent": True, "status": status,
                          "error": f"ESPN answered {status}" if failed else None}, indent=2))
    else:
        c.out.print(Text(f"ESPN: {status}"))
    if failed:
        raise WriteFailed(f"ESPN answered {status}")


def cmd_add(c: Ctx):
    from benchboss import actions

    p = actions.prepare_add(c.session, c.args.player, c.args.drop, c.args.bid)
    _write(c, p.summary, lambda: p.run(c.session))


def cmd_drop(c: Ctx):
    from benchboss import actions

    p = actions.prepare_drop(c.session, c.args.player)
    _write(c, p.summary, lambda: p.run(c.session))


def cmd_trade(c: Ctx):
    from benchboss import actions

    p = actions.prepare_trade(c.session, c.args.give, c.args.get, c.args.msg or "")
    _write(c, p.summary, lambda: p.run(c.session))


def cmd_chat(c: Ctx):
    from benchboss import inbox

    s = c.session
    text = (c.args.text or "").strip()
    if c.args.text is not None and not text:
        raise BenchbossError("the message is empty: nothing to send")
    to = inbox.resolve_member(s, c.args.to) if c.args.to else None
    if not text:
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
    _write(c, f"Message to {label}: {text}", lambda: inbox.send(s, text, to))


def cmd_app(c: Ctx):
    from benchboss.ui.app import run

    run(c.cfg, demo=c.args.demo)


# --- parser -------------------------------------------------------------------------------------------

def _count(value: str) -> int:
    """argparse type for -n and --days: a whole number, 1 or more."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a whole number") from None
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def _views(module) -> str:
    """ "season (default), l7, l15": a screen's --view choices for the help text."""
    keys = [k for k, _ in getattr(module, "VIEWS", ())]
    return ", ".join([f"{keys[0]} (default)", *keys[1:]]) if keys else "none"


def _view(module):
    """argparse type for --view: one of the screen's view keys, else bad usage (exit 2)."""
    from benchboss.ui.screens import view_index

    def check(key: str) -> str:
        try:
            view_index(module, key)
        except BenchbossError as e:
            raise argparse.ArgumentTypeError(str(e)) from None
        return key

    return check


def build_parser() -> argparse.ArgumentParser:
    from benchboss.ui.screens import finder, playoffs, roster, standings, workload

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
        p.set_defaults(fn=fn, parser=p)
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

    p = add("roster", cmd_roster, "your roster: every stat split (season, last 7/15/30, "
                                  "projection, last season) and the box score")
    p.add_argument("--view", metavar="VIEW", type=_view(roster),
                   help="the split for the box score: " + _views(roster))
    p = add("standings", cmd_standings, "league table: record, points for and against, streaks, "
                                        "playoff odds")
    p.add_argument("--view", metavar="VIEW", type=_view(standings),
                   help="which table: " + _views(standings))
    add("matchup", cmd_matchup, "this week's matchup: live score, projected final, games left")
    p = add("activity", cmd_activity, "games per player this matchup week, day by day, and the "
                                      "ones on your bench")
    p.add_argument("--view", metavar="VIEW", type=_view(workload), help="row order: " + _views(workload))
    p = add("players", cmd_players, "player finder: free agents, rostered players or your watch "
                                    "list with every stat split")
    p.add_argument("query", nargs="*", help="part of a player's name")
    p.add_argument("--from", dest="source", choices=["fa", "rostered", "all", "watch"], default="fa",
                   help="free agents (default), players on a team, everyone, or your watch list")
    p.add_argument("--pos", help="PG SG SF PF C G F")
    p.add_argument("--sort", choices=["proj", "season", "l7", "l15", "l30", "last", "own", "change"],
                   help="rank by this split (fantasy points per game), %% rostered or its change "
                        "(default: the --view split, else proj)")
    p.add_argument("--view", metavar="VIEW", type=_view(finder),
                   help="which split's box score to show: season l7 l15 l30 proj last")
    p.add_argument("-n", type=_count, default=50, help="how many (default 50)")
    p = add("watch", cmd_watch, "your ESPN watch list: list it, or add / remove a player")
    p.add_argument("action", nargs="?", choices=["list", "add", "remove"], help="default: list")
    p.add_argument("player", nargs="*", help="the player to add or remove")
    p.add_argument("--dry-run", action="store_true", help="show the change, send nothing")
    p = add("playoffs", cmd_playoffs, "playoff race: odds, who is in or out, what-if scenarios")
    p.add_argument("--pick", action="append", metavar="WINNER>LOSER",
                   help='fix a result, e.g. --pick "Monstars>Tune Squad" (add @WEEK for a '
                        "given week; repeat for more)")
    p.add_argument("--sims", type=_count, default=5000, help="simulated seasons (default 5000)")
    p.add_argument("--view", metavar="VIEW", type=_view(playoffs),
                   help="odds (default) or games, the matchups left")
    p = add("trash", cmd_trash, "most valuable free agents for this week (points added, best day to grab)")
    p.add_argument("pos", nargs="?", help="PG SG SF PF C G F")
    p.add_argument("-n", type=_count, default=10, help="how many (default 10)")
    p = add("fa", cmd_fa, "free agents by %% rostered")
    p.add_argument("pos", nargs="?", help="PG SG SF PF C G F")
    p.add_argument("-n", type=_count, default=25, help="how many (default 25)")
    p = add("trending", cmd_fa, "free agents being added the most")
    p.add_argument("-n", type=_count, default=15, help="how many (default 15)")
    p = add("news", cmd_news, "recent news and spins on your players, your watch list (--watch) "
                              "or the players you name")
    p.add_argument("players", nargs="*", help="player names; default: your roster")
    p.add_argument("--watch", action="store_true", help="your watch-list players instead of your roster")
    p.add_argument("--days", type=_count, default=5, help="how many days back (default 5)")
    p.add_argument("--ai", action="store_true", help="AI briefing with web search (needs ANTHROPIC_API_KEY)")
    p = add("trades", cmd_trades, "trade finder: fair 1-for-1 deals that fix positional needs")
    p.add_argument("--need", choices=["PG", "SG", "SF", "PF", "C", "pg", "sg", "sf", "pf", "c"],
                   help="only deals that bring you this position")
    p.add_argument("--with", dest="partner", metavar="TEAM", help="only this team or manager")
    p.add_argument("--fairness", type=float, default=0.85, help="minimum value match 0-1 (default 0.85)")
    p.add_argument("--needs", action="store_true", help="show every team's positional surplus and needs")
    p.add_argument("-n", type=_count, default=8, help="how many ideas (default 8)")
    p = add("alerts", cmd_alerts, "trade offers, accepted trades, pending claims, unread DMs and "
                                  "new news on your watch-list players")
    p.add_argument("--mark-read", action="store_true",
                   help="mark the watch list news shown as read, so it does not show again")

    p = add("optimize", cmd_optimize, "set the best lineup: today, tomorrow, week, or a date")
    p.add_argument("when", nargs="?", default="today", help="today (default), tomorrow, week, 11-04, 2026-11-04")
    p.add_argument("--dry-run", action="store_true", help="show the plan, send nothing")
    p.add_argument("-q", "--quiet", action="store_true", help="only print the final result")
    p = add("add", cmd_add, "sign a free agent or put in a waiver claim")
    p.add_argument("player", help="the free agent or waiver player to add")
    p.add_argument("--dry-run", action="store_true", help="show the move, send nothing")
    p.add_argument("--drop", help="player to release in the same move")
    p.add_argument("--bid", type=int, help="FAAB bid, if your league uses a budget")
    p = add("drop", cmd_drop, "release a player")
    p.add_argument("player", help="the player on your roster to release")
    p.add_argument("--dry-run", action="store_true", help="show the move, send nothing")
    p = add("trade", cmd_trade, "send a trade offer")
    p.add_argument("--give", action="append", required=True, metavar="PLAYER",
                   help="your player to send (repeat for more)")
    p.add_argument("--get", action="append", required=True, metavar="PLAYER",
                   help="their player you want (repeat for more, all from one team)")
    p.add_argument("--msg", help="note the other manager will see")
    p.add_argument("--dry-run", action="store_true", help="show the offer, send nothing")
    p = add("chat", cmd_chat, "read or post in the league chat, or a DM with --to")
    p.add_argument("text", nargs="?", help="message to post; leave it out to read the chat")
    p.add_argument("--to", metavar="TEAM_OR_NAME", help="direct message instead of the league chat")
    p.add_argument("--dry-run", action="store_true", help="show the message, send nothing")
    p.add_argument("-n", type=_count, default=15, help="how many messages to show (default 15)")
    return ap


def _isatty(stream) -> bool:
    try:
        return bool(stream and stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def main(argv: list[str] | None = None) -> None:
    # A console that cannot show a character (Windows pipes and redirects use the ANSI code
    # page) gets a "?" instead of a crash, which matters most after a write went through.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(errors="replace")
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd or args.cmd == "app":
        if args.json:
            ap.error("--json needs a command, for example `benchboss dash --json`")
        if not (_isatty(sys.stdin) and _isatty(sys.stdout)):
            ap.error("the interactive app needs a terminal; run a command instead, "
                     "for example `benchboss dash` (see `benchboss -h`)")
        args.cmd, args.fn = "app", cmd_app
    try:
        c = Ctx(args)
        args.fn(c)
    except BenchbossError as e:
        Console(stderr=True, highlight=False).print(Text.assemble(("benchboss: ", "bold red"), str(e)))
        sys.exit(e.exit_code)
    except EOFError:  # Ctrl-D or no input at a prompt
        print("\nbenchboss: cancelled, no input", file=sys.stderr)
        sys.exit(130)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

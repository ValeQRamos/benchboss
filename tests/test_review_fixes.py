"""Regression tests for issues found in review."""

import datetime as dt

import pytest

from benchboss import actions
from benchboss.core.lineup import plan_day
from benchboss.core.trades import find_trades
from benchboss.errors import BenchbossError, ConfigError
from benchboss.espn.models import parse_league
from benchboss.service import periods_for


def test_add_lookup_sends_a_sort_with_its_limit(session):
    # ESPN answers 400 when a filter has a limit but no sort; the demo client enforces it too
    pending = actions.prepare_add(session, "Egor Demin")
    assert pending.kind in ("FREEAGENT", "WAIVER")
    assert pending.extra == {"bidAmount": None}


def test_drop_uses_roster_transaction(session):
    assert actions.prepare_drop(session, "Scotty Pippen Jr.").kind == "ROSTER"


def test_locked_players_are_never_moved(session):
    lg = session.league()
    roster = lg.me.roster
    harris = next(s for s in roster if s.player.name == "Tobias Harris")
    harris.player.locked = True  # his game already tipped off
    try:
        plan = plan_day(roster, lg.slot_counts, session.today_period, session.calendar)
    finally:
        harris.player.locked = False
    assert all(m.player.id != harris.player.id for m in plan.moves)
    assert any(p.id == harris.player.id for p, _, _ in plan.starters)
    assert len(plan.starters) == lg.starter_slots


def test_trash_best_day_maximizes_net(session):
    for pick in session.trash(n=10):
        if pick.best_day is None:
            continue
        net = {d: g - (pick.drop_cost if d == pick.best_day else 0) for d, g in pick.gain_by_day.items()}
        assert pick.net >= net[pick.best_day] - 1e-9


def test_dash_json_trash_dates_are_iso(session):
    from benchboss.ui import dashboard

    data = dashboard.collect(session).to_dict()
    for t in data["trash"]:
        if t["best_pickup_day"]:
            dt.date.fromisoformat(t["best_pickup_day"])


def test_tomorrow_is_a_real_date(session):
    assert periods_for(session, "tomorrow") == [session.today_period + 1]


def test_today_before_the_season_is_refused(session):
    session._today = dt.date(2026, 10, 15)
    with pytest.raises(BenchbossError, match="before the season"):
        periods_for(session, "today")
    session._today = dt.date(2026, 10, 19)
    assert periods_for(session, "tomorrow") == [1]  # opening night


def test_espn_day_rolls_over_at_3am_eastern(session):
    eastern = dt.timezone(dt.timedelta(hours=-5))
    session._today = None
    session._now = dt.datetime(2026, 11, 5, 2, 30, tzinfo=eastern)
    assert session.today == dt.date(2026, 11, 4)
    session._now = dt.datetime(2026, 11, 5, 3, 30, tzinfo=eastern)
    assert session.today == dt.date(2026, 11, 5)


def test_unknown_team_is_not_guessed(session):
    raw = session.client.data["league"]
    with pytest.raises(ConfigError):
        parse_league(raw, None, "{NOT-A-MEMBER}")


def test_trade_pitch_only_claims_what_holds(session):
    for idea in find_trades(session.league(), limit=8):
        msg = idea.message()
        assert ("deep at" in msg) == idea.they_deep_get
        assert ("I need a" in msg) == idea.i_need_get


def test_demo_apply_is_refused(session):
    with pytest.raises(BenchbossError, match="demo"):
        actions.prepare_drop(session, "Scotty Pippen Jr.").run(session)


def test_news_finds_free_agents(session):
    p = session.find_player("Egor Demin")
    assert p.status in ("FREEAGENT", "WAIVERS")

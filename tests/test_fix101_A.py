"""Regression tests for the 1.0.1 core math fixes (trash scout, projection, optimizer, trades)."""

import dataclasses
import datetime as dt

from benchboss.core import trash
from benchboss.core.calendar import Game, SeasonCalendar
from benchboss.core.lineup import best_lineup, day_value, plan_day
from benchboss.core.projection import not_started, week_projection
from benchboss.core.trades import find_trades
from benchboss.espn.constants import BENCH, IR, POSITION_SLOTS, ROSTER_LOCK_FIRST_GAME, SLOT_ID
from benchboss.espn.models import Player, RosterSpot, Team

ET = dt.timezone(dt.timedelta(hours=-5))
UT = SLOT_ID["UT"]


def at(session, day: int, hour: int, minute: int = 0):
    """Move the demo session to a moment of matchup week 3 (November 2026, Eastern time)."""
    session._today = dt.date(2026, 11, day)
    session._now = dt.datetime(2026, 11, day, hour, minute, tzinfo=ET)
    return session


def pick_for(picks, name):
    return next(p for p in picks if p.player.name == name)


def roster_spot(session, name):
    return next(s for s in session.league().me.roster if s.player.name == name)


# --- F2: rosters lock at the day's first tip-off ------------------------------------------------

def test_demo_league_reads_the_roster_lock(session):
    assert session.league().roster_lock_type == ROSTER_LOCK_FIRST_GAME


def test_sunday_after_first_tip_nothing_counts_this_week(session):
    at(session, 8, 15, 45)  # first tip on Sun Nov 8 was 15:30
    assert session.now >= session.calendar.first_tip(session.today_period)
    for pick in session.trash(n=20):
        assert pick.best_day is None
        assert pick.gain == 0 and pick.games_left == 0


def test_saturday_after_first_tip_only_sunday_counts(session):
    at(session, 7, 17, 15)  # first tip on Sat Nov 7 was 17:00
    sunday = session.today_period + 1
    picks = session.trash(n=60)
    assert all(p.best_day in (None, sunday) for p in picks)
    demin = pick_for(picks, "Egor Demin")
    assert demin.best_day == sunday and demin.games_left == 1
    assert demin.gain < 31  # one Sunday game, not the 60 of two games


def test_before_first_tip_today_still_counts(session):
    at(session, 7, 16, 0)
    demin = pick_for(session.trash(n=60), "Egor Demin")
    assert demin.best_day == session.today_period and demin.games_left == 2


def test_individual_game_leagues_keep_the_per_player_rule(session):
    at(session, 7, 17, 15)
    session.league().roster_lock_type = "INDIVIDUAL_GAME"
    cal, today = session.calendar, session.today_period
    counted_today = 0
    for pick in session.trash(n=60):
        team = pick.player.pro_team_id
        plays_later = cal.plays(team, today) and not_started(cal, team, today, session.now)
        if pick.best_day == today and plays_later:
            counted_today += 1
            assert pick.games_left == cal.games_in(team, [today, today + 1])
        elif pick.best_day is not None:
            assert pick.games_left == cal.games_in(team, [today + 1])
    assert counted_today


# --- F1: started starters keep their slots tonight -----------------------------------------------

def test_projection_leaves_slots_to_starters_already_playing(session):
    at(session, 4, 19, 10)
    lg, cal, today = session.league(), session.calendar, session.today_period
    me = lg.teams[1]
    used = sum(1 for s in me.roster if s.is_starting and cal.plays(s.player.pro_team_id, today)
               and not not_started(cal, s.player.pro_team_id, today, session.now))
    assert used == 4
    points, games = week_projection(me, [today], cal, lg.starter_slots, today, session.now)
    assert games == lg.starter_slots - used == 6
    assert round(points, 1) == 239.7
    _, opp_games = week_projection(lg.teams[6], [today], cal, lg.starter_slots, today, session.now)
    assert opp_games == 5


def test_projection_before_tip_off_is_unchanged(session):
    lg, cal, today = session.league(), session.calendar, session.today_period
    with_now = week_projection(lg.me, [today], cal, lg.starter_slots, today, session.now)
    without = week_projection(lg.me, [today], cal, lg.starter_slots)
    assert with_now == without


# --- F4: an open roster spot needs no drop --------------------------------------------------------

def test_open_roster_spot_needs_no_drop(session):
    lg = session.league()
    lg.me.roster.remove(roster_spot(session, "Pascal Siakam"))  # 12 active of 13
    picks = session.trash(n=60)
    demin = pick_for(picks, "Egor Demin")
    assert demin.drop is None and demin.drop_cost == 0 and not demin.needs_drop
    assert demin.net == demin.gain > 63
    assert not pick_for(picks, "Jalen Suggs").needs_drop


def test_open_spot_still_respects_the_center_limit(session):
    session.league().me.roster.remove(roster_spot(session, "Pascal Siakam"))
    sharpe = pick_for(session.trash(n=60), "Day'Ron Sharpe")  # a fifth C needs a C to go
    assert sharpe.needs_drop
    assert sharpe.drop is None or sharpe.drop.position == "C"


def test_ir_players_do_not_count_against_the_roster(session):
    roster_spot(session, "Pascal Siakam").slot_id = IR
    assert trash.roster_has_room(session.league().me, session.league().slot_counts)


# --- F3, F73: never drop a better player for a streamer ----------------------------------------

def test_out_star_is_not_the_suggested_drop(session):
    roster_spot(session, "Anthony Edwards").player.injury_status = "OUT"
    for pick in session.trash(n=60):
        assert pick.drop is None or pick.drop.name != "Anthony Edwards"


def test_drop_always_projects_below_the_pickup(session):
    for when in [(4, 15, 30), (5, 12, 0), (6, 12, 0)]:
        for pick in at(session, *when).trash(n=60):
            if pick.drop:
                assert pick.drop.proj < pick.player.proj or pick.drop_projects_higher


def test_a_real_upgrade_still_gets_a_drop(session):
    george = pick_for(session.trash(n=60), "Kyshawn George")
    assert george.drop is not None and george.drop.name == "Tobias Harris"
    assert george.drop_cost > 0 and george.net == george.gain - george.drop_cost


def test_drop_respects_the_center_limit(session):
    # the roster already has four C: a C free agent can only replace another C
    robinson = pick_for(session.trash(n=60), "Mitchell Robinson")
    assert robinson.drop is None or robinson.drop.position == "C"


def test_no_clear_drop_is_flagged_in_json(session):
    # nobody on the roster projects below him: the drop is the lowest projected legal player
    # and the pick is flagged as a one-week stream
    data = pick_for(session.trash(n=60), "Egor Demin").to_dict(session.calendar)
    assert data["needs_drop"] is True and data["drop_projects_higher"] is True
    assert data["drop"] is not None and data["net_gain"] == round(data["week_gain"] - data["drop_cost"], 1)


# --- F6: games are counted from the grab day ------------------------------------------------------

def _tiny_league():
    """Two starters. K1 and K2 are core players, Y is the only player below the free agent X.
    X's day 1 game adds nothing (K2 is better), while Y starts on day 2, so the best grab day is
    3, after Y's games."""
    def game(sp):
        return Game(sp, dt.datetime(2026, 11, 1, 19, tzinfo=ET) + dt.timedelta(days=sp - 1), 1, 2)

    schedule = {1: [1, 2, 3], 2: [1], 3: [1, 2], 4: [1, 3]}  # pro team id -> periods
    cal = SeasonCalendar(dt.date(2026, 11, 1),
                         {t: {sp: game(sp) for sp in sps} for t, sps in schedule.items()}, 3)

    def player(pid, proj, team, name):
        return Player(id=pid, name=name, pro_team_id=team, proj=proj, position_id=1,
                      eligible_slots=(UT,))

    team = Team(1, "Mine", roster=[RosterSpot(player(1, 50, 1, "K1"), UT),
                                   RosterSpot(player(2, 40, 2, "K2"), UT),
                                   RosterSpot(player(3, 20, 3, "Y"), BENCH)])
    return cal, team, player(9, 25, 4, "X")


def test_games_left_counts_from_the_best_day():
    cal, team, fa = _tiny_league()
    (pick,) = trash.scout([fa], team, cal, [1, 2, 3], 1, starters=2)
    assert pick.drop.name == "Y"
    assert pick.best_day == 3
    assert pick.games_left == 1  # he also plays day 1, but that is before the grab day


def test_games_left_matches_best_day_on_demo(session):
    cal = session.calendar
    for when in [(4, 15, 30), (5, 12, 0), (7, 16, 0)]:
        for pick in at(session, *when).trash(n=60):
            if pick.best_day is not None:
                week = [sp for sp in session.matchup_periods() if sp >= pick.best_day]
                assert pick.games_left <= cal.games_in(pick.player.pro_team_id, week)


# --- F7: waivers before the season ----------------------------------------------------------------

def test_preseason_waiver_player_is_ready_for_opening_night(session, monkeypatch):
    session._today = dt.date(2026, 10, 15)
    session._now = dt.datetime(2026, 10, 15, 12, tzinfo=ET)
    lg, cal = session.league(), session.calendar
    week1 = cal.matchup_periods(1, lg.matchup_periods)
    fa = session.free_agents(60)[0]
    claim = dataclasses.replace(fa, status="WAIVERS")
    monkeypatch.setattr(session, "matchup_periods", lambda: week1)
    monkeypatch.setattr(session, "free_agents", lambda *a, **k: [fa, claim])
    free, waiver = sorted(session.trash(n=2), key=lambda p: p.on_waivers)
    assert waiver.on_waivers and waiver.best_day == free.best_day
    assert free.best_day in week1
    assert waiver.games_left == free.games_left
    assert round(waiver.net, 6) == round(free.net, 6)


def test_in_season_waiver_player_waits_a_day(session, monkeypatch):
    fa = session.free_agents(60)[0]
    claim = dataclasses.replace(fa, status="WAIVERS")
    monkeypatch.setattr(session, "free_agents", lambda *a, **k: [claim])
    (pick,) = session.trash(n=1)
    assert pick.best_day is None or pick.best_day >= session.today_period + 1


# --- F9, F69: no moves for players who cannot score -----------------------------------------------

def test_day_without_games_needs_no_moves(session):
    lg, cal = session.league(), session.calendar
    roster_spot(session, "Jalen Duren").slot_id = BENCH  # leaves the C slot empty
    no_games = next(sp for sp in session.matchup_periods() if cal.first_tip(sp) is None)
    plan = plan_day(lg.me.roster, lg.slot_counts, no_games, cal)
    assert plan.moves == []


def test_players_without_a_game_are_never_moved_into_a_slot(session):
    lg, cal = session.league(), session.calendar
    roster_spot(session, "Jalen Duren").slot_id = BENCH
    for sp in session.matchup_periods():
        plan = plan_day(lg.me.roster, lg.slot_counts, sp, cal)
        for m in plan.moves:
            if m.to_slot != BENCH:
                assert day_value(m.player, sp, cal) > 0, (sp, str(m))


def test_player_with_a_game_but_no_projection_still_fills_a_slot():
    pool = [RosterSpot(Player(id=1, name="P1", eligible_slots=(UT,)), BENCH),
            RosterSpot(Player(id=2, name="P2", eligible_slots=(UT,)), BENCH)]
    assert best_lineup(pool, {UT: 1, BENCH: 2}, [0.0, 0.0], [True, False]) == {0: UT}
    assert best_lineup(pool, {UT: 1, BENCH: 2}, [0.0, 0.0], [False, False]) == {}
    stays = [RosterSpot(Player(id=1, name="P1", eligible_slots=(UT,)), UT)]
    assert best_lineup(stays, {UT: 1}, [0.0], [False]) == {0: UT}  # left where he is


# --- F15: bereavement and paternity leave --------------------------------------------------------

def test_leave_statuses_count_as_out(session):
    spot = roster_spot(session, "Pascal Siakam")
    sp = next(p for p in session.matchup_periods() if session.calendar.plays(spot.player.pro_team_id, p))
    for status in ("BEREAVEMENT", "PATERNITY"):
        spot.player.injury_status = status
        assert spot.player.injury == "OUT"
        assert day_value(spot.player, sp, session.calendar) == 0
        plan = plan_day(session.league().me.roster, session.league().slot_counts, sp,
                        session.calendar)
        assert (spot.player, "OUT") in plan.bench


# --- F64, F8: trade finder -----------------------------------------------------------------------

def test_trades_skip_injured_players(session):
    lg = session.league()
    ideas = find_trades(lg, need="SF", min_fairness=0.5, limit=50)
    assert all(t.get.name != "Brandon Ingram" for t in ideas)  # OUT in the demo
    for t in find_trades(lg, min_fairness=0.5, limit=50):
        assert t.get.injury not in ("OUT", "SUSP", "IR")
        assert t.give.injury not in ("OUT", "SUSP", "IR")


def test_trades_never_offer_an_injured_player(session):
    lg = session.league()
    top = find_trades(lg, limit=8)[0]
    top.give.injury_status = "OUT"
    assert all(t.give.id != top.give.id for t in find_trades(lg, limit=50))


def test_close_in_value_only_when_it_is(session):
    ideas = find_trades(session.league(), min_fairness=0.5, limit=50)
    assert any(t.fairness < 0.85 for t in ideas)
    for t in ideas:
        assert ("close in value" in t.message()) == (t.fairness >= 0.85)


def test_trades_skip_swaps_with_the_same_eligibility(session):
    lg = session.league()
    top = find_trades(lg, limit=8)[0]
    assert top.give.position != top.get.position
    top.get.eligible_slots = top.give.eligible_slots  # same positions, different default
    for t in find_trades(lg, min_fairness=0.5, limit=50):
        assert ({s for s in t.give.eligible_slots if s in POSITION_SLOTS}
                != {s for s in t.get.eligible_slots if s in POSITION_SLOTS})
        assert not (t.give.id == top.give.id and t.get.id == top.get.id)

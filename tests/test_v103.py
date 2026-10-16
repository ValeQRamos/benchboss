"""1.0.3: budget waivers (FAAB) read the way ESPN's app reads them, and the demo's past lineups."""

import io

import pytest
from rich.console import Console

from benchboss import actions
from benchboss.demo import demo_session
from benchboss.errors import BenchbossError
from benchboss.espn.constants import BENCH
from benchboss.ui.screens import standings, view_index
from benchboss.ui.theme import DARK


@pytest.fixture
def session():
    return demo_session()


def text_of(renderable, width=140) -> str:
    console = Console(width=width, file=io.StringIO(), color_system=None)
    console.print(renderable)
    return console.file.getvalue()


def on_waivers(session, name: str) -> None:
    """Put a demo free agent on waivers, the way kona_player_info reports it."""
    for x in session.data["free_agents"]:
        if x["player"]["fullName"] == name:
            x["status"] = "WAIVERS"


def faab(session, on: bool = True, minimum: int = 1) -> None:
    acq = session.data["league"]["settings"]["acquisitionSettings"]
    acq["isUsingAcquisitionBudget"], acq["minimumBid"] = on, minimum
    session.league(refresh=True)


def test_the_budget_flag_is_what_counts(session):
    assert session.league().uses_faab is False
    faab(session)  # acquisitionType still says WAIVERS_TRADITIONAL, as ESPN leaves it
    lg = session.league()
    assert lg.uses_faab and lg.minimum_bid == 1 and lg.acquisition_type == "WAIVERS_TRADITIONAL"
    out = text_of(standings.draw(standings.load(session), DARK, 140,
                                 view_index(standings, "moves")))
    assert "budget waivers" in out and "traditional" not in out


def test_a_waiver_claim_in_a_budget_league_needs_a_bid(session):
    faab(session)
    on_waivers(session, "Egor Demin")
    with pytest.raises(BenchbossError, match="--bid N \\(at least 1\\)"):
        actions.prepare_add(session, "Egor Demin")
    with pytest.raises(BenchbossError, match="at least 1"):
        actions.prepare_add(session, "Egor Demin", bid=0)
    pending = actions.prepare_add(session, "Egor Demin", bid=7)
    assert pending.kind == "WAIVER" and pending.extra == {"bidAmount": 7}
    # a free agent (not on waivers) is signed right away, no bid needed
    assert actions.prepare_add(session, "Myles Turner").kind == "FREEAGENT"


def test_a_bid_in_a_league_without_a_budget_is_refused(session):
    with pytest.raises(BenchbossError, match="no waiver budget"):
        actions.prepare_add(session, "Egor Demin", bid=5)


def test_demo_past_days_have_their_own_lineup(session):
    today = session.today_period
    week = session.matchup_periods()
    past = [p for p in week if p < today]
    assert past, "the demo clock sits mid-week"
    now = {s.player.id: s.slot_id for s in session.roster_on(today)}
    for p in past:
        lineup = session.roster_on(p)
        assert len(lineup) == len(now)
        playing = [s for s in lineup if s.slot_id != BENCH
                   and session.calendar.plays(s.player.pro_team_id, p)]
        assert len(playing) <= session.league().starter_slots
    # somebody sits on a day already played who starts today, or the other way round
    assert any({s.player.id: s.slot_id for s in session.roster_on(p)} != now for p in past)
    assert session.roster_on(today + 1) == session.league().me.roster  # later days carry today's


@pytest.mark.parametrize("flag, tag", [("PLAYOFFS", "x"), ("DIVISION_BYE", "yz"),
                                       ("TOP_SEED_BYE", "*z"), ("ELIMINATED", "e"),
                                       ("UNKNOWN", ""), ("", "")])
def test_clinch_tags_are_espns_own(session, flag, tag):
    lg = session.league()
    team = next(t for t in lg.teams.values() if t.id != lg.my_team_id)
    team.clinch = "" if flag == "UNKNOWN" else flag  # the parser drops UNKNOWN and NONE
    out = text_of(standings.draw(lg, DARK, 140))
    row = next(line for line in out.splitlines() if team.name in line)
    if tag:
        assert f"{team.name} {tag} " in row
        for letter in tag:
            assert f"{letter} {standings.CLINCH[letter]}" in out
    else:
        assert "clinched" not in out and "eliminated" not in out


def test_the_clinch_flag_comes_from_the_simulation_results():
    from benchboss.espn.models import parse_team

    t = {"id": 1, "location": "A", "nickname": "B", "playoffClinchType": "UNKNOWN",
         "currentSimulationResults": {"playoffClinchType": "DIVISION"}}
    assert parse_team(t, 2027, {}).clinch == "DIVISION"


def test_the_menu_follows_the_window_width_and_m_sticks():
    import asyncio

    from textual.widgets import OptionList

    from benchboss.config import Config
    from benchboss.ui.app import NARROW, Benchboss

    app = Benchboss(Config(), demo=True)

    async def wait(pilot, ok, timeout=5.0):
        for _ in range(int(timeout / 0.05)):
            if ok():
                return True
            await pilot.pause(0.05)
        return ok()

    async def run():
        async with app.run_test(size=(NARROW + 20, 40)) as pilot:
            await pilot.app.workers.wait_for_complete()
            menu = app.query_one("#menu", OptionList)
            assert await wait(pilot, lambda: not menu.has_class("hidden"))
            await pilot.resize_terminal(NARROW - 10, 40)
            assert await wait(pilot, lambda: menu.has_class("hidden"))
            await pilot.press("m")
            assert await wait(pilot, lambda: not menu.has_class("hidden"))
            await pilot.resize_terminal(NARROW - 5, 40)  # still narrow: m keeps it open
            await pilot.pause(0.3)
            assert not menu.has_class("hidden")
            await pilot.resize_terminal(NARROW + 20, 40)
            assert await wait(pilot, lambda: not menu.has_class("hidden"))

    asyncio.run(run())


def test_a_player_dropped_midweek_keeps_the_games_he_played_for_you(session, monkeypatch):
    import json

    from benchboss.espn.models import RosterSpot
    from benchboss.ui.screens import workload

    gone = next(p for p in session.free_agents(40)
                if session.calendar.plays(p.pro_team_id, session.matchup_periods()[0]))
    real = type(session).roster_on
    first = session.matchup_periods()[0]

    def roster_on(self, period):  # he started on Monday and was dropped after it
        roster = real(self, period)
        if period == first:
            bench = next(s for s in roster if s.slot_id == BENCH)
            roster = [s for s in roster if s is not bench] + [RosterSpot(gone, 0)]
        return roster

    monkeypatch.setattr(type(session), "roster_on", roster_on)
    data = workload.load(session)
    row = next(a for a in data.acts if a.player.id == gone.id)
    assert row.gone and row.games == 1 and row.games_left == 0 and row.games_in_lineup == 1
    out = text_of(workload.draw(data, DARK, 150), 150)
    line = next(x for x in out.splitlines() if gone.name in x)
    assert "gone" in line and "gone no longer on your roster" in " ".join(out.split())
    assert out.splitlines().index(line) > max(i for i, x in enumerate(out.splitlines())
                                              if "Pippen" in x)  # after the bench
    # the footer counts his Monday game: In = every game played in a starting slot
    assert sum(a.games_in_lineup or 0 for a in data.acts) == sum(
        1 for a in data.acts for i, opp in enumerate(a.schedule) if opp and a.starting(i))
    rows = workload.to_json(data)
    assert [r["on_roster"] for r in rows].count(False) == 1
    json.dumps(rows)

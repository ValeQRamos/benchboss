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

from benchboss.core.lineup import best_lineup, plan_day
from benchboss.espn.constants import BENCH, SLOT_ID
from benchboss.espn.models import Player, RosterSpot


def spot(pid, slots, current=BENCH):
    return RosterSpot(Player(id=pid, name=f"P{pid}", eligible_slots=tuple(slots)), current)


def test_best_lineup_fills_positions_optimally():
    pg, c, ut = SLOT_ID["PG"], SLOT_ID["C"], SLOT_ID["UT"]
    pool = [spot(1, [pg, ut]), spot(2, [pg, ut]), spot(3, [c, ut]), spot(4, [c, ut])]
    values = [30.0, 20.0, 25.0, 10.0]
    assign = best_lineup(pool, {pg: 1, c: 1, ut: 1, BENCH: 1}, values)
    assert assign[0] in (pg, ut) and assign[2] in (c, ut)
    assert 3 not in assign  # the worst player sits
    assert sorted(values[i] for i in assign) == [20.0, 25.0, 30.0]


def test_ties_keep_players_in_place():
    ut = SLOT_ID["UT"]
    pool = [spot(1, [ut], current=ut), spot(2, [ut])]
    assign = best_lineup(pool, {ut: 1, BENCH: 1}, [10.0, 10.0])
    assert assign == {0: ut}


def test_demo_day_benches_injured_and_starts_best(session):
    lg = session.league()
    plan = plan_day(lg.me.roster, lg.slot_counts, session.today_period, session.calendar)
    starters = {p.name for p, _, _ in plan.starters}
    assert "Pascal Siakam" in starters  # healthy 41 pts projection should not sit
    assert len(plan.starters) == lg.starter_slots
    assert plan.changed
    for m in plan.moves:
        assert m.item()["type"] == "LINEUP"

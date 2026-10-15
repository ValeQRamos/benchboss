from benchboss.core import trades
from benchboss.core.activity import most_and_least


def test_outlook_projects_forward(session):
    o = session.outlook()
    assert o.matchup_id == 3
    assert o.opponent is not None
    assert o.me.projected >= o.me.points
    assert 0 < len(o.remaining) <= len(o.periods)


def test_activity_counts_games(session):
    acts = session.activity()
    assert acts and all(0 <= a.games_left <= a.games <= 7 for a in acts)
    assert acts == sorted(acts, key=lambda a: (-a.games, -a.games_left, -a.player.proj))
    most, least = most_and_least(acts, 3)
    assert most[0].games >= least[0].games


def test_trash_ranks_by_net_gain(session):
    picks = session.trash(n=8)
    assert picks
    nets = [p.net for p in picks]
    assert nets == sorted(nets, reverse=True)
    for p in picks:
        assert p.best_day is None or p.best_day >= session.today_period
        assert p.drop is not None


def test_trade_ideas_are_fair_and_varied(session):
    lg = session.league()
    ideas = trades.find_trades(lg, limit=8)
    assert ideas
    for t in ideas:
        assert t.fairness >= 0.85
        assert t.partner.id != lg.my_team_id
        assert t.give_pos != t.get_pos
    for t in ideas:
        assert sum(x.give.id == t.give.id for x in ideas) <= 2


def test_trade_need_filter(session):
    ideas = trades.find_trades(session.league(), need="PG", limit=5)
    assert all(t.get_pos == "PG" for t in ideas)


def test_alerts_show_trade_offer(session):
    from benchboss import inbox

    alerts = inbox.alerts(session)
    assert any(a.kind == "trade_offer" for a in alerts)

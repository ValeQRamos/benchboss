import datetime as dt


def test_day_one_and_round_trip(session):
    cal = session.calendar
    assert cal.day_one == dt.date(2026, 10, 20)
    assert cal.date_of(1) == cal.day_one
    assert cal.period_of(dt.date(2026, 11, 4)) == 16
    assert cal.date_of(cal.period_of(dt.date(2027, 1, 15))) == dt.date(2027, 1, 15)


def test_first_weeks(session):
    weeks = session.calendar.weeks()
    assert weeks[0] == (dt.date(2026, 10, 20), dt.date(2026, 10, 25))  # opening night to Sunday
    assert weeks[1] == (dt.date(2026, 10, 26), dt.date(2026, 11, 1))   # then Monday to Sunday
    assert weeks[2][0].weekday() == 0 and weeks[2][1].weekday() == 6


def test_all_star_week_is_merged(session):
    weeks = session.calendar.weeks()
    long = [(a, b) for a, b in weeks if (b - a).days > 7]
    assert len(long) == 1
    a, b = long[0]
    assert a.month == 2 and (b - a).days == 13


def test_matchup_periods_follow_league_mapping(session):
    lg = session.league()
    periods = session.calendar.matchup_periods(3, lg.matchup_periods)
    assert session.calendar.date_of(periods[0]) == dt.date(2026, 11, 2)
    assert len(periods) == 7
    assert session.today_period in periods

from benchboss import credentials
from benchboss.espn.models import parse_player


def test_projection_falls_back_to_last_season_average():
    entry = {"player": {"id": 1, "fullName": "Test Player", "stats": [
        {"id": "002026", "appliedAverage": 31.5, "appliedTotal": 2000}]}}
    p = parse_player(entry, 2027)
    assert p.avg == 31.5 and p.avg_is_last_season
    assert p.proj == 31.5


def test_preseason_zero_split_means_no_data():
    entry = {"player": {"id": 1, "fullName": "X", "stats": [
        {"id": "002027", "appliedAverage": 0.0, "appliedTotal": 0.0},
        {"id": "102027", "appliedAverage": 40.0, "appliedTotal": 3000}]}}
    p = parse_player(entry, 2027)
    assert p.avg is None and p.proj == 40.0


def test_swid_gets_braces():
    assert credentials.normalize_swid("ABC-123") == "{ABC-123}"
    assert credentials.normalize_swid("{ABC-123}") == "{ABC-123}"


def test_env_cookies_win(monkeypatch):
    monkeypatch.setenv("ESPN_S2", "s2value")
    monkeypatch.setenv("ESPN_SWID", "ABC")
    assert credentials.get() == ("s2value", "{ABC}")

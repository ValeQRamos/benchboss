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


def test_store_falls_back_to_a_private_file_without_keychain(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    import keyring.core

    keyring.core._keyring_backend = None  # pick up the env var
    where = credentials.store("s2value", "ABC")
    assert "credentials.json" in where
    assert credentials.get() == ("s2value", "{ABC}")
    import os
    import stat
    import sys

    f = credentials._file()
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    credentials.clear()
    assert credentials.get() is None
    keyring.core._keyring_backend = None

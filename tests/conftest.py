import pytest

from benchboss.demo import demo_session


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real config, cache or keychain during tests."""
    monkeypatch.setenv("BENCHBOSS_HOME", str(tmp_path / "home"))
    for var in ("ESPN_S2", "ESPN_SWID", "BENCHBOSS_LEAGUE_ID", "BENCHBOSS_TEAM_ID",
                "BENCHBOSS_SEASON", "BENCHBOSS_THEME", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def session():
    return demo_session()

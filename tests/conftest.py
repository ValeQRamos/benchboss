import pytest

from benchboss import credentials
from benchboss.demo import demo_session


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real config, cache or keychain during tests."""
    monkeypatch.setenv("BENCHBOSS_HOME", str(tmp_path / "home"))
    for var in ("ESPN_S2", "ESPN_SWID", "BENCHBOSS_LEAGUE_ID", "BENCHBOSS_TEAM_ID",
                "BENCHBOSS_SEASON", "BENCHBOSS_THEME", "BENCHBOSS_LAYOUT", "ANTHROPIC_API_KEY",
                "BENCHBOSS_NOTIFY_CMD", "BENCHBOSS_NTFY_TOPIC", "BENCHBOSS_NTFY_TOKEN",
                "BENCHBOSS_NTFY_SERVER"):
        monkeypatch.delenv(var, raising=False)
    # every keychain read and write goes through credentials._keyring: without a keychain the
    # cookies live in credentials.json under BENCHBOSS_HOME, which is the temporary folder above
    # (the real keychain can also block a test run on a macOS permission dialog)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)


@pytest.fixture
def session():
    return demo_session()

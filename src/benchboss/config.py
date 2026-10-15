"""User configuration: which league and team benchboss drives, and display preferences.

Stored as JSON in the platform config folder (see ``config_dir``). Every field can be
overridden with an environment variable, which is handy for CI and for AI agents:

    BENCHBOSS_LEAGUE_ID, BENCHBOSS_TEAM_ID, BENCHBOSS_SEASON, BENCHBOSS_THEME, BENCHBOSS_HOME
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from benchboss.errors import ConfigError

THEMES = ("dark", "light")


def config_dir() -> Path:
    """~/.config/benchboss on macOS and Linux, %APPDATA%\\benchboss on Windows."""
    if os.environ.get("BENCHBOSS_HOME"):
        return Path(os.environ["BENCHBOSS_HOME"]).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "benchboss"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "benchboss"


def cache_dir() -> Path:
    return config_dir() / "cache"


def current_season(today: dt.date | None = None) -> int:
    """ESPN names a season by the year it ends: Oct 2026 to Apr 2027 is season 2027."""
    today = today or dt.date.today()
    return today.year + 1 if today.month >= 8 else today.year


@dataclass
class Config:
    league_id: int | None = None
    team_id: int | None = None
    season: int | None = None
    theme: str = "dark"
    league_name: str = ""
    team_name: str = ""

    @property
    def path(self) -> Path:
        return config_dir() / "config.json"

    @property
    def effective_season(self) -> int:
        return self.season or current_season()

    def require_league(self) -> None:
        if not self.league_id:
            raise ConfigError("no league configured yet: run `benchboss setup`")


_ENV = {"league_id": "BENCHBOSS_LEAGUE_ID", "team_id": "BENCHBOSS_TEAM_ID",
        "season": "BENCHBOSS_SEASON", "theme": "BENCHBOSS_THEME"}


def load() -> Config:
    cfg = Config()
    path = cfg.path
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except ValueError as e:
            raise ConfigError(f"{path} is not valid JSON ({e}); fix it or run `benchboss setup`") from e
        known = {f.name for f in fields(Config)}
        cfg = Config(**{k: v for k, v in raw.items() if k in known})
    for name, var in _ENV.items():
        value = os.environ.get(var)
        if value:
            setattr(cfg, name, value if name == "theme" else int(value))
    if cfg.theme not in THEMES:
        cfg.theme = "dark"
    return cfg


def save(cfg: Config) -> Path:
    path = cfg.path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    tmp.replace(path)
    return path


def save_theme(theme: str) -> Path | None:
    """Store only the theme and leave every other saved setting as it is on disk.

    The app calls this instead of ``save`` so values that came from BENCHBOSS_* environment
    variables for one run never end up in config.json. A file that is not a JSON object is
    left alone (returns None) for the user or ``benchboss setup`` to fix.
    """
    path = config_dir() / "config.json"
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except ValueError:
            return None
        if not isinstance(raw, dict):
            return None
    raw["theme"] = theme
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n")
    tmp.replace(path)
    return path

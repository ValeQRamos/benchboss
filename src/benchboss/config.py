"""User configuration: which league and team benchboss drives, and display preferences.

Stored as JSON in the platform config folder (see ``config_dir``). Every field can be
overridden with an environment variable, which is handy for CI and for AI agents:

    BENCHBOSS_LEAGUE_ID, BENCHBOSS_TEAM_ID, BENCHBOSS_SEASON, BENCHBOSS_THEME,
    BENCHBOSS_LAYOUT, BENCHBOSS_HOME
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from benchboss.errors import ConfigError

THEMES = ("dark", "light")
LAYOUTS = ("auto", "compact", "full")  # ui/layout.py: compact on small windows, or forced


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
    layout: str = "auto"         # one of LAYOUTS
    # notifications from `benchboss monitor` (notify.py): {"backends": ["mac", "ntfy"],
    # "ntfy_server": "https://ntfy.sh"}. Never secrets: those come from the environment.
    notify: dict = field(default_factory=dict)

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
        "season": "BENCHBOSS_SEASON", "theme": "BENCHBOSS_THEME", "layout": "BENCHBOSS_LAYOUT"}
_TEXT = ("theme", "layout")  # the variables above that are words, not numbers


def load() -> Config:
    cfg = Config()
    path = cfg.path
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except ValueError as e:
            raise ConfigError(f"{path} is not valid JSON ({e}); fix it or run `benchboss setup`") from e
        if not isinstance(raw, dict):
            raise ConfigError(f"{path} must hold a JSON object; fix it or run `benchboss setup`")
        known = {f.name for f in fields(Config)}
        cfg = Config(**{k: v for k, v in raw.items() if k in known})
    for name, var in _ENV.items():
        value = os.environ.get(var)
        if not value:
            continue
        if name in _TEXT:
            setattr(cfg, name, value)
            continue
        try:
            setattr(cfg, name, int(value))
        except ValueError:
            raise ConfigError(f"{var} must be a whole number, got {value!r}") from None
    if cfg.theme not in THEMES:
        cfg.theme = "dark"
    if cfg.layout not in LAYOUTS:
        cfg.layout = "auto"
    if not isinstance(cfg.notify, dict):
        cfg.notify = {}
    return cfg


def _tmp(path: Path) -> Path:
    """A temp file next to ``path`` for this process only: the app, the CLI and the monitor
    can save at the same time without writing into each other's temp file."""
    return path.with_name(f"{path.name}.{os.getpid()}.tmp")


def save(cfg: Config) -> Path:
    path = cfg.path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    tmp.write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    tmp.replace(path)
    return path


def save_theme(theme: str) -> Path | None:
    """Store only the theme and leave every other saved setting as it is on disk.

    The app calls this instead of ``save`` so values that came from BENCHBOSS_* environment
    variables for one run never end up in config.json. A file that is not a JSON object is
    left alone (returns None) for the user or ``benchboss setup`` to fix.
    """
    return save_field("theme", theme)


def save_field(name: str, value) -> Path | None:
    """Store one field and leave every other saved setting as it is on disk (see save_theme)."""
    path = config_dir() / "config.json"
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except ValueError:
            return None
        if not isinstance(raw, dict):
            return None
    raw[name] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    tmp.write_text(json.dumps(raw, indent=2) + "\n")
    tmp.replace(path)
    return path

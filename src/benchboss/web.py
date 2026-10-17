"""Running the app in a browser (``benchboss web``): spotting a web session and the command
that ``textual serve`` starts for every visitor."""

from __future__ import annotations

import os
import shlex
import sys

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def in_web_session() -> bool:
    """True inside the process Textual's web server starts: it sets this driver itself."""
    return os.environ.get("TEXTUAL_DRIVER", "").endswith(":WebDriver")


def session_command(demo: bool = False, theme: str | None = None) -> str:
    """The shell command run once per browser session: the interactive app of this install."""
    argv = [sys.executable, "-m", "benchboss"]
    if demo:
        argv.append("--demo")
    if theme:
        argv += ["--theme", theme]
    return shlex.join(argv + ["app"])

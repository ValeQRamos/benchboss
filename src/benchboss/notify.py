"""Notifications on your computer or phone. Only the monitor sends them; the app shows toasts.

Backends (pick any number, by name, in config.json ``notify.backends`` or with
``benchboss monitor --notify mac,ntfy``):

    mac   macOS Notification Center through osascript, title and text passed as argv items
          (never pasted into the script, so a name cannot inject AppleScript)
    ntfy  a push to the ntfy app (iPhone, Android): JSON POST to the server root
          {topic, title, message, priority}, so accents travel in the body (an HTTP header
          cannot carry "Jokić"). The topic works like a password on the public server.
    cmd   your own command (Telegram, Pushover, anything): run without a shell, with the
          title and text in BENCHBOSS_TITLE and BENCHBOSS_TEXT and the text on stdin
    log   one line on stdout (tmux, launchd and systemd logs)

Secrets never go in config.json, on the command line or in a log. They come from the
environment, or from ``notify.env`` in the config folder (KEY=VALUE lines, used only when
the file is private, 0600):

    BENCHBOSS_NTFY_TOPIC   the ntfy topic (required for ntfy)
    BENCHBOSS_NTFY_TOKEN   an ntfy access token (optional)
    BENCHBOSS_NTFY_SERVER  another ntfy server (default NTFY_SERVER)
    BENCHBOSS_NOTIFY_CMD   the command for cmd, split like a shell would (shlex)

A note carries no league id and no cookies, and its text goes through store.redact. The
monitor dedupes by ``Note.key`` (once per key per day) and decides what to send; this
module only delivers.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from benchboss.errors import BenchbossError

BACKENDS = ("mac", "ntfy", "cmd", "log")
PRIORITIES = ("urgent", "normal", "info")
NTFY_SERVER = "https://ntfy.sh"
ENV_NTFY_TOPIC = "BENCHBOSS_NTFY_TOPIC"
ENV_NTFY_TOKEN = "BENCHBOSS_NTFY_TOKEN"
ENV_NTFY_SERVER = "BENCHBOSS_NTFY_SERVER"
ENV_CMD = "BENCHBOSS_NOTIFY_CMD"
TIMEOUT = 15  # seconds per backend


class NotifyError(BenchbossError):
    """A backend could not deliver; the message never contains a secret."""


@dataclass(frozen=True)
class Note:
    title: str
    body: str
    priority: str = "normal"  # one of PRIORITIES
    key: str = ""             # dedupe key: the monitor sends each key once per day


class Backend(Protocol):
    name: str

    def send(self, note: Note) -> str:
        """Deliver ``note``; return a short receipt ("ntfy: sent"); raise NotifyError."""
        ...


def default_backends() -> tuple[str, ...]:
    """Without a setting: Notification Center on a Mac, a log line elsewhere."""
    return ("mac",) if sys.platform == "darwin" else ("log",)


def secrets(env: dict[str, str] | None = None) -> dict[str, str]:
    """The notification settings from the environment (``env``, default os.environ), then
    notify.env when it is private. Implemented by the auto-swap package."""
    raise NotImplementedError


def backends(names: Iterable[str], env: dict[str, str] | None = None) -> list[Backend]:
    """Backends by name. An unknown name, or one whose secret is missing, raises NotifyError
    naming the environment variable to set. Implemented by the auto-swap package."""
    raise NotImplementedError


def send(note: Note, to: Iterable[Backend]) -> list[str]:
    """Deliver ``note`` through every backend; never raises. One receipt per backend:
    "mac: sent" or "ntfy: failed (reason)". Implemented by the auto-swap package."""
    raise NotImplementedError


__all__ = ["BACKENDS", "Backend", "NTFY_SERVER", "Note", "NotifyError", "PRIORITIES",
           "backends", "default_backends", "secrets", "send"]

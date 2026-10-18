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

On Windows, where files have no POSIX permissions, notify.env is read as it is.

A note carries no league id and no cookies, and its text goes through store.redact (the
monitor also removes the session's cookies). The monitor dedupes by ``Note.key`` (once per
key per day) and decides what to send; this module only delivers. Nothing is retried: a
push that timed out after the body went out may have arrived, and a second one would be a
duplicate.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TextIO

from benchboss import store
from benchboss.errors import BenchbossError

BACKENDS = ("mac", "ntfy", "cmd", "log")
PRIORITIES = ("urgent", "normal", "info")
NTFY_SERVER = "https://ntfy.sh"
NTFY_PRIORITY = {"urgent": 5, "normal": 3, "info": 2}
ENV_NTFY_TOPIC = "BENCHBOSS_NTFY_TOPIC"
ENV_NTFY_TOKEN = "BENCHBOSS_NTFY_TOKEN"
ENV_NTFY_SERVER = "BENCHBOSS_NTFY_SERVER"
ENV_CMD = "BENCHBOSS_NOTIFY_CMD"
SECRET_VARS = (ENV_NTFY_TOPIC, ENV_NTFY_TOKEN, ENV_NTFY_SERVER, ENV_CMD)
TIMEOUT = 15  # seconds per backend


class NotifyError(BenchbossError):
    """A backend could not deliver; the message never contains a secret."""


@dataclass(frozen=True)
class Note:
    title: str
    body: str
    priority: str = "normal"  # one of PRIORITIES
    key: str = ""             # dedupe key: the monitor sends each key once per day


class Backend:
    """One way to deliver a note. ``send`` returns a short receipt or raises NotifyError."""
    name = "?"
    hidden: tuple[str, ...] = ()  # values no receipt or error may show

    def send(self, note: Note) -> str:
        raise NotImplementedError

    def _clean(self, text: str) -> str:
        return store.redact(text, self.hidden)


def default_backends() -> tuple[str, ...]:
    """Without a setting: Notification Center on a Mac, a log line elsewhere."""
    return ("mac",) if sys.platform == "darwin" else ("log",)


def _private(path) -> bool:
    if sys.platform == "win32":
        return True  # no POSIX permissions to check
    try:
        return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    except OSError:
        return False


def _env_file() -> dict[str, str]:
    path = store.notify_env_path()
    if not path.exists() or not _private(path):
        return {}
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        key, value = ln.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in SECRET_VARS and value:
            out[key] = value
    return out


def secrets(env: dict[str, str] | None = None) -> dict[str, str]:
    """The notification settings from the environment (``env``, default os.environ), then
    notify.env when it is private (0600). The environment wins."""
    env = os.environ if env is None else env
    out = _env_file()
    out.update({k: env[k] for k in SECRET_VARS if env.get(k)})
    return out


def backends(names: Iterable[str], env: dict[str, str] | None = None) -> list[Backend]:
    """Backends by name. An unknown name, or one whose secret is missing, raises NotifyError
    naming the environment variable to set."""
    names = [n.strip().lower() for n in names if n and n.strip()]
    sec = secrets(env)
    out: list[Backend] = []
    for name in dict.fromkeys(names):
        if name == "mac":
            out.append(MacBackend())
        elif name == "ntfy":
            topic = sec.get(ENV_NTFY_TOPIC)
            if not topic:
                raise NotifyError(f"ntfy needs a topic: set {ENV_NTFY_TOPIC} (or put it in "
                                  f"{store.notify_env_path()}, readable only by you)")
            out.append(NtfyBackend(topic, sec.get(ENV_NTFY_TOKEN, ""),
                                   sec.get(ENV_NTFY_SERVER) or NTFY_SERVER))
        elif name == "cmd":
            cmd = sec.get(ENV_CMD)
            if not cmd:
                raise NotifyError(f"cmd needs a command: set {ENV_CMD} (or put it in "
                                  f"{store.notify_env_path()}, readable only by you)")
            out.append(CommandBackend(cmd))
        elif name == "log":
            out.append(LogBackend())
        else:
            raise NotifyError(f"unknown notification backend '{name}' ({', '.join(BACKENDS)})")
    return out


def send(note: Note, to: Iterable[Backend]) -> list[str]:
    """Deliver ``note`` through every backend; never raises. One receipt per backend:
    "mac: sent" or "ntfy: failed (reason)"."""
    hidden = tuple(s for b in to for s in b.hidden)
    clean = Note(store.redact(note.title, hidden), store.redact(note.body, hidden),
                 note.priority if note.priority in PRIORITIES else "normal", note.key)
    out = []
    for b in to:
        try:
            out.append(b.send(clean))
        except NotifyError as e:
            out.append(f"{b.name}: failed ({b._clean(str(e))})")
        except Exception as e:  # a backend must never stop the monitor
            out.append(f"{b.name}: failed ({b._clean(type(e).__name__ + ': ' + str(e))})")
    return out


# --- backends ------------------------------------------------------------------------------------

def _run(argv: list[str], *, text: str = "", env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=text.encode("utf-8"), capture_output=True,
                          timeout=TIMEOUT, env=env, check=False)


class MacBackend(Backend):
    """macOS Notification Center. The title and the text are argv items of the script."""
    name = "mac"
    SCRIPT = ("on run argv", "display notification (item 2 of argv) with title (item 1 of argv)",
              "end run")

    def send(self, note: Note) -> str:
        if sys.platform != "darwin":
            raise NotifyError("mac notifications need macOS")
        argv = ["osascript"]
        for line in self.SCRIPT:
            argv += ["-e", line]
        try:
            r = _run(argv + [note.title, note.body])
        except FileNotFoundError:
            raise NotifyError("osascript was not found") from None
        except subprocess.TimeoutExpired:
            raise NotifyError(f"osascript did not finish in {TIMEOUT} s") from None
        if r.returncode != 0:
            raise NotifyError(f"osascript exited with {r.returncode}")
        return "mac: sent"


class NtfyBackend(Backend):
    """A push to the ntfy app: JSON to the server root, so UTF-8 names travel in the body."""
    name = "ntfy"

    def __init__(self, topic: str, token: str = "", server: str = NTFY_SERVER):
        self.topic, self.token, self.server = topic, token, server.rstrip("/")
        self.hidden = tuple(s for s in (topic, token) if s)

    def payload(self, note: Note) -> dict:
        return {"topic": self.topic, "title": note.title, "message": note.body,
                "priority": NTFY_PRIORITY.get(note.priority, 3)}

    def send(self, note: Note) -> str:
        headers = {"Content-Type": "application/json; charset=utf-8",
                   "User-Agent": "benchboss notifications"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(self.payload(note), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.server + "/", data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            raise NotifyError(f"the ntfy server answered {e.code}") from None
        except urllib.error.URLError as e:
            raise NotifyError(f"could not reach the ntfy server ({e.reason})") from None
        except TimeoutError:
            raise NotifyError(f"the ntfy server did not answer in {TIMEOUT} s (it may still "
                              "have arrived; not sent again)") from None
        if not 200 <= status < 300:
            raise NotifyError(f"the ntfy server answered {status}")
        return "ntfy: sent"


class CommandBackend(Backend):
    """Your own command, run without a shell: title and text in BENCHBOSS_TITLE and
    BENCHBOSS_TEXT (and BENCHBOSS_PRIORITY), the text on stdin."""
    name = "cmd"

    def __init__(self, command: str):
        self.command = command
        self.hidden = (command,) + tuple(a for a in self._split(command) if len(a) >= 12)

    @staticmethod
    def _split(command: str) -> list[str]:
        try:
            return shlex.split(command, posix=sys.platform != "win32")
        except ValueError as e:
            raise NotifyError(f"{ENV_CMD} cannot be read as a command ({e})") from None

    def send(self, note: Note) -> str:
        argv = self._split(self.command)
        if not argv:
            raise NotifyError(f"{ENV_CMD} is empty")
        env = dict(os.environ, BENCHBOSS_TITLE=note.title, BENCHBOSS_TEXT=note.body,
                   BENCHBOSS_PRIORITY=note.priority)
        for var in SECRET_VARS:  # the command gets the note, not the other secrets
            if var != ENV_CMD:
                env.pop(var, None)
        try:
            r = _run(argv, text=note.body + "\n", env=env)
        except FileNotFoundError:
            raise NotifyError("the notification command was not found") from None
        except subprocess.TimeoutExpired:
            raise NotifyError(f"the notification command did not finish in {TIMEOUT} s") from None
        except OSError as e:
            raise NotifyError(f"the notification command could not run ({e.strerror})") from None
        if r.returncode != 0:
            raise NotifyError(f"the notification command exited with {r.returncode}")
        return "cmd: sent"


class LogBackend(Backend):
    """One line on stdout, for tmux, launchd and systemd logs."""
    name = "log"

    def __init__(self, stream: TextIO | None = None):
        self.stream = stream

    def send(self, note: Note) -> str:
        out = self.stream or sys.stdout
        print(f"[{note.priority}] {note.title}: {note.body}", file=out, flush=True)
        with contextlib.suppress(AttributeError, OSError, ValueError):
            out.flush()
        return "log: written"


__all__ = ["BACKENDS", "Backend", "CommandBackend", "LogBackend", "MacBackend", "NTFY_SERVER",
           "Note", "NotifyError", "NtfyBackend", "PRIORITIES", "backends", "default_backends",
           "secrets", "send"]

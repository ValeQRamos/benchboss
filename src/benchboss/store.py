"""The small local files benchboss keeps next to config.json, and how they are written.

Paths, all under ``config.config_dir()`` (which honors BENCHBOSS_HOME):

    leagues/<league id>/marks.json     auto-swap marks (marks.py)
    leagues/<league id>/monitor.json   the monitor's state and heartbeat (monitor.py)
    leagues/<league id>/monitor.lock   the monitor's lease: one monitor per league
    logs/lineup-YYYY-MM.jsonl          every lineup change and auto-swap decision (lineup_log.py)
    notify.env                         notification secrets (notify.py), read only when 0600

Folders are created private (0700) and files are written private (0600) where the system
has POSIX permissions. A JSON file is replaced atomically: a temp file named after the
process, then a rename, so a reader never sees half a file (a rename Windows blocks while
another process reads the file is tried again for a moment). A read-modify-write that two
processes can do at once (the app and the monitor) goes inside ``locked``.

A session that keeps its state in memory (``Session.local_state``, the demo) passes that
dict as ``memory``: nothing touches the disk and the paths are only keys.

Anything written here or sent in a notification goes through ``redact`` first.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import threading
import time
import urllib.parse
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from benchboss import config as config_mod
from benchboss.errors import BenchbossError

LOCK_WAIT = 2.0    # seconds ``locked`` waits for another process
LOCK_STALE = 30.0  # a lock file older than this was left by a process that died

_memory_lock = threading.RLock()


# --- paths ----------------------------------------------------------------------------------------

def league_dir(league_id: int) -> Path:
    return config_mod.config_dir() / "leagues" / str(league_id)


def marks_path(league_id: int) -> Path:
    return league_dir(league_id) / "marks.json"


def monitor_path(league_id: int) -> Path:
    return league_dir(league_id) / "monitor.json"


def lease_path(league_id: int) -> Path:
    return league_dir(league_id) / "monitor.lock"


def logs_dir() -> Path:
    return config_mod.config_dir() / "logs"


def notify_env_path() -> Path:
    return config_mod.config_dir() / "notify.env"


# --- files ----------------------------------------------------------------------------------------

def private_dir(path: Path) -> Path:
    """Create ``path`` (and its parents) if needed; the folder itself is made 0700."""
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(0o700)
    return path


def read_json(path: Path, default: Any = None, *, memory: dict | None = None) -> Any:
    """The JSON in ``path``, or ``default`` when there is no such file. A file that exists
    but cannot be read or parsed raises BenchbossError: callers decide what a damaged file
    means (the marks fail closed: no marks)."""
    if memory is not None:
        with _memory_lock:
            return copy.deepcopy(memory.get(str(path), default))
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as e:
        raise BenchbossError(f"could not read {path} ({e})") from e
    try:
        return json.loads(text)
    except ValueError as e:
        raise BenchbossError(f"{path} is damaged ({e})") from e


# On Windows a rename over a file fails while another process has it open (the app reading
# monitor.json while the monitor saves it): wait a moment and try again before giving up
REPLACE_WAITS = (0.02, 0.05, 0.1, 0.2, 0.4)
_sleep = time.sleep


def _replace(tmp: Path, path: Path) -> None:
    for wait in REPLACE_WAITS:
        try:
            tmp.replace(path)
            return
        except PermissionError:
            _sleep(wait)
    tmp.replace(path)


def write_json(path: Path, data: Any, *, memory: dict | None = None) -> None:
    """Replace ``path`` with ``data`` as JSON, atomically, readable only by you. A rename
    that another process blocks for a moment (Windows) is tried again (REPLACE_WAITS)."""
    if memory is not None:
        with _memory_lock:
            memory[str(path)] = copy.deepcopy(data)
        return
    private_dir(path.parent)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")
        _replace(tmp, path)
    except OSError as e:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise BenchbossError(f"could not save {path} ({e})") from e


def append_jsonl(path: Path, record: dict, *, memory: dict | None = None) -> None:
    """Add one JSON line to ``path`` (one write call, so lines from two processes never mix)."""
    line = json.dumps(record, ensure_ascii=False, default=str)
    if memory is not None:
        with _memory_lock:
            memory.setdefault(str(path), []).append(json.loads(line))
        return
    private_dir(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        raise BenchbossError(f"could not write to {path} ({e})") from e


def read_jsonl(path: Path, *, memory: dict | None = None) -> list[dict]:
    """Every JSON object line in ``path``, oldest first; broken lines are skipped."""
    if memory is not None:
        with _memory_lock:
            return copy.deepcopy(list(memory.get(str(path)) or []))
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        with contextlib.suppress(ValueError):
            obj = json.loads(ln)
            if isinstance(obj, dict):
                out.append(obj)
    return out


@contextlib.contextmanager
def locked(path: Path, *, wait: float = LOCK_WAIT, stale: float = LOCK_STALE,
           memory: dict | None = None) -> Iterator[None]:
    """Hold ``<path>.lock`` for a short read-modify-write of ``path``, across processes.

    The lock file is created with O_CREAT|O_EXCL. A lock older than ``stale`` seconds was
    left behind by a process that died and is taken over. Waiting longer than ``wait``
    raises BenchbossError. With ``memory`` it is a plain thread lock."""
    if memory is not None:
        with _memory_lock:
            yield
        return
    lock = path.with_name(path.name + ".lock")
    private_dir(lock.parent)
    deadline = time.monotonic() + wait
    while True:
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - lock.stat().st_mtime > stale:
                    lock.unlink()
                    continue
            if time.monotonic() > deadline:
                raise BenchbossError(f"{path.name} is busy (another benchboss is saving it); "
                                     "try again") from None
            time.sleep(0.05)
            continue
        except OSError as e:
            raise BenchbossError(f"could not lock {path} ({e})") from e
        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


# --- privacy --------------------------------------------------------------------------------------

_GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
HIDDEN = "[hidden]"


def redact(text: str, secrets: Iterable[str | None] = ()) -> str:
    """``text`` without secrets: every value in ``secrets`` (the session's espn_s2 and SWID,
    a notification token), raw or URL-encoded, and any {GUID} (ESPN member ids, the SWID)."""
    for s in secrets:
        if not s or len(s) < 6:
            continue
        for form in {s, urllib.parse.quote(s, safe=""), urllib.parse.unquote(s)}:
            if len(form) >= 6:
                text = text.replace(form, HIDDEN)
    return _GUID.sub(HIDDEN, text)


def session_secrets(session) -> tuple[str, ...]:
    """The cookie values of a session, for ``redact`` (empty without cookies)."""
    cookies = getattr(getattr(session, "client", None), "cookies", None) or ()
    return tuple(c for c in cookies if isinstance(c, str))


__all__ = ["append_jsonl", "league_dir", "lease_path", "locked", "logs_dir", "marks_path",
           "monitor_path", "notify_env_path", "private_dir", "read_json", "read_jsonl",
           "redact", "session_secrets", "write_json"]

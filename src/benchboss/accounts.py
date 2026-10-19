"""The people who can sign in to ``benchboss web --accounts``.

One SQLite file (``accounts.db``, private) holds each person's name, password hash and GitHub
name. Each person also gets a folder of their own under ``users/``: it is what ``BENCHBOSS_HOME``
points at for that person's app, so their ESPN cookies, settings and logs never mix with anyone
else's. Nothing here touches ESPN.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from benchboss.errors import BenchbossError

NAME = re.compile(r"^[a-z][a-z0-9]{1,15}$")
GITHUB = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}$")  # a login, or a numeric id
MIN_PASSWORD = 12
MAX_PASSWORD = 256
SCRYPT = (2**14, 8, 1)  # about 16 MB and 50 ms: fine on a small server
SKIP_ON_IMPORT = ("web-secret", "accounts.db", "cache", "users")


@dataclass(frozen=True)
class Account:
    name: str
    github: str | None
    created: float
    home: Path


def new_password() -> str:
    return secrets.token_urlsafe(18)


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    n, r, p = SCRYPT
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def _matches(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r),
                             p=int(p), dklen=32)
        return kind == "scrypt" and hmac.compare_digest(got, bytes.fromhex(digest))
    except ValueError:
        return False


class Accounts:
    def __init__(self, root: Path, now: Callable[[], float] = time.time) -> None:
        self.root = root
        self.path = root / "accounts.db"
        self.now = now
        self._dummy = ""

    # --- the file ------------------------------------------------------------------------------

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600))
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, pw TEXT NOT NULL, "
                       "github TEXT UNIQUE, created REAL NOT NULL, reset REAL NOT NULL DEFAULT 0)")
            with db:
                yield db
        finally:
            db.close()

    def home(self, name: str) -> Path:
        if not NAME.match(name):
            raise BenchbossError(f"'{name}' is not a valid name: 2 to 16 lowercase letters and "
                                 "digits, starting with a letter")
        return self.root / "users" / name

    # --- reading -------------------------------------------------------------------------------

    def everyone(self) -> list[Account]:
        with self._db() as db:
            rows = db.execute("SELECT name, github, created FROM users ORDER BY name").fetchall()
        return [Account(n, g, c, self.home(n)) for n, g, c in rows]

    def exists(self, name: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone() is not None

    def check(self, name: str, password: str) -> str | None:
        """The account's name when the password is right, else None. A wrong name costs the same
        time as a wrong password, so the answer does not say which one was wrong."""
        with self._db() as db:
            row = db.execute("SELECT pw FROM users WHERE name = ?", (name,)).fetchone()
        if row is None:
            self._dummy = self._dummy or _hash("not a real password")
            _matches(password, self._dummy)
            return None
        return name if _matches(password, row[0]) else None

    def by_github(self, login: str, uid: int) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT name FROM users WHERE github IN (?, ?)",
                             (login.lower(), str(uid))).fetchone()
        return row[0] if row else None

    def session_ok(self, name: str, issued: float) -> bool:
        """Is a sign in made at ``issued`` still good: the person exists and has not had their
        password or GitHub name changed since."""
        with self._db() as db:
            row = db.execute("SELECT reset FROM users WHERE name = ?", (name,)).fetchone()
        return row is not None and issued >= row[0]

    # --- changing ------------------------------------------------------------------------------

    def add(self, name: str, password: str, github: str | None = None) -> Account:
        home = self.home(name)
        self._strong(password)
        github = self._github(github)
        if self.exists(name):
            raise BenchbossError(f"{name} already exists (benchboss users list)")
        try:
            with self._db() as db:
                db.execute("INSERT INTO users (name, pw, github, created) VALUES (?, ?, ?, ?)",
                           (name, _hash(password), github, self.now()))
        except sqlite3.IntegrityError:
            raise BenchbossError(f"the GitHub name {github} already belongs to someone else") from None
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(home, 0o700)
        return Account(name, github, self.now(), home)

    def set_password(self, name: str, password: str) -> None:
        self._strong(password)
        self._update(name, "pw = ?, reset = ?", (_hash(password), self.now()))

    def set_github(self, name: str, github: str | None) -> None:
        github = self._github(github)
        try:
            self._update(name, "github = ?, reset = ?", (github, self.now()))
        except sqlite3.IntegrityError:
            raise BenchbossError(f"the GitHub name {github} already belongs to someone else") from None

    def remove(self, name: str, keep_data: bool = False) -> None:
        home = self.home(name)
        with self._db() as db:
            if db.execute("DELETE FROM users WHERE name = ?", (name,)).rowcount == 0:
                raise BenchbossError(f"no account named {name} (benchboss users list)")
        if not keep_data:
            shutil.rmtree(home, ignore_errors=True)

    def import_home(self, name: str, source: Path) -> None:
        """Copy an existing settings folder (cookies, league, logs) into the person's folder."""
        if not source.is_dir():
            raise BenchbossError(f"{source} is not a folder")
        home = self.home(name)
        shutil.copytree(source, home, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*SKIP_ON_IMPORT, "*.tmp"))
        os.chmod(home, 0o700)

    # --- checks --------------------------------------------------------------------------------

    def _update(self, name: str, assignment: str, values: tuple) -> None:
        self.home(name)  # checks the name
        with self._db() as db:
            if db.execute(f"UPDATE users SET {assignment} WHERE name = ?", (*values, name)).rowcount == 0:
                raise BenchbossError(f"no account named {name} (benchboss users list)")

    @staticmethod
    def _strong(password: str) -> None:
        if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
            raise BenchbossError(f"a password has {MIN_PASSWORD} to {MAX_PASSWORD} characters")

    @staticmethod
    def _github(value: str | None) -> str | None:
        value = (value or "").strip().lower()
        if not value:
            return None
        if not GITHUB.match(value):
            raise BenchbossError("a GitHub name is a login (letters, digits, hyphens) or a numeric id")
        return value

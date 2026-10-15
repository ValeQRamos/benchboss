"""ESPN session cookies (espn_s2 and SWID): where they live and how they get there.

Lookup order:
  1. Environment variables ESPN_S2 and ESPN_SWID (CI, containers, AI agents).
  2. The OS keychain through ``keyring`` (macOS Keychain, Windows Credential Locker,
     Secret Service on Linux).
  3. A fallback file ``credentials.json`` with 0600 permissions in the config folder, used
     only when no keychain backend is available.

The values are never printed, logged or written anywhere else.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import urllib.parse
from pathlib import Path

from benchboss.config import config_dir
from benchboss.errors import AuthError

SERVICE = "benchboss"
ACCOUNTS = ("espn_s2", "SWID")


def normalize_swid(swid: str) -> str:
    swid = swid.strip().strip('"')
    if swid and not swid.startswith("{"):
        swid = "{" + swid
    if swid and not swid.endswith("}"):
        swid += "}"
    return swid


def _file() -> Path:
    return config_dir() / "credentials.json"


def _keyring():
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def get() -> tuple[str, str] | None:
    env = os.environ.get("ESPN_S2"), os.environ.get("ESPN_SWID")
    if all(env):
        return env[0].strip(), normalize_swid(env[1])
    kr = _keyring()
    if kr:
        try:
            s2, swid = (kr.get_password(SERVICE, a) for a in ACCOUNTS)
            if s2 and swid:
                return s2, swid
        except Exception:
            pass
    f = _file()
    if f.exists():
        try:
            data = json.loads(f.read_text())
            if data.get("espn_s2") and data.get("SWID"):
                return data["espn_s2"], data["SWID"]
        except ValueError:
            pass
    return None


def require() -> tuple[str, str]:
    found = get()
    if not found:
        raise AuthError("no ESPN cookies found: run `benchboss login`")
    return found


def store(s2: str, swid: str) -> str:
    """Save the cookies; returns a human description of where they went."""
    s2, swid = s2.strip().strip('"'), normalize_swid(swid)
    if not s2 or not swid:
        raise AuthError("both espn_s2 and SWID are required")
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICE, "espn_s2", s2)
            kr.set_password(SERVICE, "SWID", swid)
            return "your system keychain"
        except Exception:
            pass
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump({"espn_s2": s2, "SWID": swid}, out)
    return f"{f} (permissions 0600)"


def clear() -> None:
    kr = _keyring()
    if kr:
        for a in ACCOUNTS:
            with contextlib.suppress(Exception):
                kr.delete_password(SERVICE, a)
    _file().unlink(missing_ok=True)


# --- import from Google Chrome (macOS) ----------------------------------------------------------

def from_chrome() -> tuple[str, str, str]:
    """Read espn_s2 and SWID from the newest Chrome profile that is signed in to ESPN.

    macOS only: Chrome encrypts cookies with a key kept in the login keychain, so macOS asks
    once for permission ("python wants to use Chrome Safe Storage"). Returns (profile, s2, swid).
    """
    if sys.platform != "darwin":
        raise AuthError("importing from Chrome works on macOS only; use `benchboss login --manual`")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as e:
        raise AuthError("the `cryptography` package is missing; use `benchboss login --manual`") from e
    r = subprocess.run(["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
                       capture_output=True, text=True)
    if r.returncode:
        raise AuthError("could not read 'Chrome Safe Storage' from the keychain; "
                        "use `benchboss login --manual`")
    key = hashlib.pbkdf2_hmac("sha1", r.stdout.strip().encode(), b"saltysalt", 1003, 16)
    base = Path.home() / "Library/Application Support/Google/Chrome"
    found = []
    try:
        dbs = sorted(base.glob("*/Cookies"))
    except PermissionError:
        dbs = []
    for db in dbs:
        uri = f"file:{urllib.parse.quote(str(db))}?mode=ro&immutable=1"
        con = sqlite3.connect(uri, uri=True)
        try:
            ver = int((con.execute("SELECT value FROM meta WHERE key='version'").fetchone() or [0])[0])
            rows = con.execute(
                "SELECT name, encrypted_value, value, last_access_utc FROM cookies "
                "WHERE host_key LIKE '%espn.com' AND name IN ('espn_s2', 'SWID')").fetchall()
        except sqlite3.Error:
            continue
        finally:
            con.close()
        got: dict[str, tuple[str, int]] = {}
        for name, enc, plain, last in rows:
            val = plain
            if enc and enc[:3] in (b"v10", b"v11"):
                dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
                raw = dec.update(enc[3:]) + dec.finalize()
                raw = raw[: -raw[-1]]
                if ver >= 24:  # newer Chrome prefixes the value with a 32 byte domain hash
                    raw = raw[32:]
                val = raw.decode(errors="replace")
            if val and (name not in got or last > got[name][1]):
                got[name] = (val, last)
        if "espn_s2" in got and "SWID" in got:
            found.append((max(got["espn_s2"][1], got["SWID"][1]), db.parent.name,
                          got["espn_s2"][0], got["SWID"][0]))
    if not found:
        raise AuthError("no ESPN session found in Chrome: sign in at espn.com in Chrome first, "
                        "or use `benchboss login --manual`")
    found.sort(reverse=True)
    _, profile, s2, swid = found[0]
    return f"Chrome ({profile})", s2, swid

"""Notifications (notify.py): Mac, ntfy, a user command, a log line. Never a shell, never a
secret in a receipt, accents intact."""

import io
import json
import os
import subprocess
import sys
import urllib.error

import pytest

from benchboss import notify, store

NOTE = notify.Note("Auto-swap", "Nikola Jokić is healthy (was OUT). Luka Dončić sits.", "urgent")


class Done:
    def __init__(self, code=0):
        self.returncode = code


def test_secrets_come_from_the_environment_then_a_private_file(monkeypatch):
    assert notify.secrets({}) == {}
    path = store.notify_env_path()
    store.private_dir(path.parent)
    path.write_text('# mine\nBENCHBOSS_NTFY_TOPIC="benchboss-abc123xyz"\n'
                    "export BENCHBOSS_NOTIFY_CMD=/usr/local/bin/tell-me\nOTHER=1\n",
                    encoding="utf-8")
    os.chmod(path, 0o600)
    got = notify.secrets({})
    assert got == {"BENCHBOSS_NTFY_TOPIC": "benchboss-abc123xyz",
                   "BENCHBOSS_NOTIFY_CMD": "/usr/local/bin/tell-me"}
    env = notify.secrets({"BENCHBOSS_NTFY_TOPIC": "from-env-topic"})
    assert env["BENCHBOSS_NTFY_TOPIC"] == "from-env-topic"  # the environment wins
    if sys.platform != "win32":
        os.chmod(path, 0o644)  # readable by others: ignored
        assert notify.secrets({}) == {}


def test_backends_by_name_and_what_is_missing():
    assert [b.name for b in notify.backends(["log", "mac"], env={})] == ["log", "mac"]
    with pytest.raises(notify.NotifyError, match="BENCHBOSS_NTFY_TOPIC"):
        notify.backends(["ntfy"], env={})
    with pytest.raises(notify.NotifyError, match="BENCHBOSS_NOTIFY_CMD"):
        notify.backends(["cmd"], env={})
    with pytest.raises(notify.NotifyError, match="telegram"):
        notify.backends(["telegram"], env={})
    assert notify.backends([" Log ", "log", ""], env={})[0].name == "log"  # once each


def test_ntfy_posts_json_so_accents_travel(monkeypatch):
    sent = []

    class Answer:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        sent.append((req, timeout))
        return Answer()

    monkeypatch.setattr(notify.urllib.request, "urlopen", urlopen)
    env = {"BENCHBOSS_NTFY_TOPIC": "benchboss-secret-topic", "BENCHBOSS_NTFY_TOKEN": "tk_123456"}
    (b,) = notify.backends(["ntfy"], env=env)
    assert notify.send(NOTE, [b]) == ["ntfy: sent"]
    req, timeout = sent[0]
    assert req.full_url == "https://ntfy.sh/" and req.get_method() == "POST"
    assert timeout == notify.TIMEOUT
    body = json.loads(req.data.decode("utf-8"))
    assert body == {"topic": "benchboss-secret-topic", "title": "Auto-swap",
                    "message": NOTE.body, "priority": 5}
    assert "Jokić" in req.data.decode("utf-8")
    assert req.get_header("Authorization") == "Bearer tk_123456"
    # no league id, no click url
    assert set(body) == {"topic", "title", "message", "priority"}


def test_ntfy_errors_never_show_the_topic_or_the_token(monkeypatch):
    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b""))

    monkeypatch.setattr(notify.urllib.request, "urlopen", refuse)
    env = {"BENCHBOSS_NTFY_TOPIC": "benchboss-secret-topic", "BENCHBOSS_NTFY_TOKEN": "tk_123456",
           "BENCHBOSS_NTFY_SERVER": "https://push.example.org/"}
    (b,) = notify.backends(["ntfy"], env=env)
    (receipt,) = notify.send(NOTE, [b])
    assert receipt == "ntfy: failed (the ntfy server answered 401)"

    def timeout(req, timeout):
        raise TimeoutError

    monkeypatch.setattr(notify.urllib.request, "urlopen", timeout)
    (receipt,) = notify.send(NOTE, [b])
    assert "not sent again" in receipt and "secret" not in receipt


def test_mac_passes_title_and_text_as_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.sys, "platform", "darwin")
    monkeypatch.setattr(notify.subprocess, "run", lambda argv, **kw: calls.append((argv, kw))
                        or Done())
    tricky = notify.Note('Shaquille O\'Neal "said"', 'end tell" & do shell script "rm -rf ~"')
    assert notify.send(tricky, notify.backends(["mac"], env={})) == ["mac: sent"]
    argv, kw = calls[0]
    assert argv[0] == "osascript" and argv[-2:] == [tricky.title, tricky.body]
    assert "shell" not in kw and all(tricky.body not in a for a in argv[:-1])
    monkeypatch.setattr(notify.subprocess, "run", lambda argv, **kw: Done(1))
    assert notify.send(NOTE, notify.backends(["mac"], env={})) == [
        "mac: failed (osascript exited with 1)"]


def test_mac_needs_macos(monkeypatch):
    monkeypatch.setattr(notify.sys, "platform", "linux")
    assert notify.send(NOTE, notify.backends(["mac"], env={})) == [
        "mac: failed (mac notifications need macOS)"]


def test_the_command_gets_the_note_in_its_environment_and_on_stdin(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.subprocess, "run", lambda argv, **kw: calls.append((argv, kw))
                        or Done())
    monkeypatch.setenv("BENCHBOSS_NTFY_TOKEN", "tk_hidden_from_the_command")
    env = {"BENCHBOSS_NOTIFY_CMD": "/opt/tell-me --chat 'my phone'"}
    assert notify.send(NOTE, notify.backends(["cmd"], env=env)) == ["cmd: sent"]
    argv, kw = calls[0]
    assert argv == ["/opt/tell-me", "--chat", "my phone"]
    assert "shell" not in kw and kw["timeout"] == notify.TIMEOUT
    assert kw["env"]["BENCHBOSS_TITLE"] == "Auto-swap"
    assert kw["env"]["BENCHBOSS_TEXT"] == NOTE.body
    assert kw["env"]["BENCHBOSS_PRIORITY"] == "urgent"
    assert "BENCHBOSS_NTFY_TOKEN" not in kw["env"]
    assert kw["input"].decode("utf-8") == NOTE.body + "\n"


def test_a_command_that_fails_or_hangs_is_a_receipt_not_a_crash(monkeypatch):
    env = {"BENCHBOSS_NOTIFY_CMD": "tell-me"}

    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 15)

    monkeypatch.setattr(notify.subprocess, "run", hang)
    assert notify.send(NOTE, notify.backends(["cmd"], env=env)) == [
        "cmd: failed (the notification command did not finish in 15 s)"]

    def missing(argv, **kw):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(notify.subprocess, "run", missing)
    assert "was not found" in notify.send(NOTE, notify.backends(["cmd"], env=env))[0]


def test_send_never_raises_and_keeps_going():
    class Broken(notify.Backend):
        name = "broken"

        def send(self, note):
            raise RuntimeError("boom")

    out = io.StringIO()
    receipts = notify.send(NOTE, [Broken(), notify.LogBackend(out)])
    assert receipts == ["broken: failed (RuntimeError: boom)", "log: written"]
    assert out.getvalue() == f"[urgent] Auto-swap: {NOTE.body}\n"


def test_notes_lose_member_ids():
    out = io.StringIO()
    notify.send(notify.Note("x", "member {00000000-0000-4000-8000-000000000001} said hi"),
                [notify.LogBackend(out)])
    assert "{00000000" not in out.getvalue() and store.HIDDEN in out.getvalue()

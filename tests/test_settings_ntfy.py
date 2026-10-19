"""The Settings screen (key e) and the ntfy settings it writes: notify.env stays private and
keeps its other lines, config.json keeps its other fields, the demo saves and sends nothing."""

import asyncio
import json
import os
import stat
import sys

import pytest
from textual.widgets import Button, Checkbox, Input, TabbedContent

from benchboss import config as config_mod
from benchboss import notify, store
from benchboss.config import Config
from benchboss.ui import layout
from benchboss.ui.app import MENU, Benchboss
from benchboss.ui.screens import settings as screen

TOPIC = "benchboss-abc123xyz"


async def settle(pilot):
    for _ in range(2):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


def drive(scenario, size=(140, 44)):
    app = Benchboss(Config(), demo=True)

    async def go():
        async with app.run_test(size=size) as pilot:
            await settle(pilot)
            await pilot.press("e")
            await settle(pilot)
            await scenario(pilot, app, app.query_one(screen.SettingsView))

    asyncio.run(go())
    assert app.return_code in (None, 0)
    return app


def test_e_is_the_menu_key_and_the_widget_binds_no_menu_letter():
    assert ("settings", "Settings", "e") in MENU
    keys = [k for _, _, k in MENU]
    assert len(keys) == len(set(keys))
    letters = set(keys) | set("gvmrq")
    for b in screen.SettingsView.BINDINGS:
        assert not set(b[0].split(",")) & letters


def test_save_ntfy_keeps_other_lines_and_the_file_private():
    path = store.notify_env_path()
    store.private_dir(path.parent)
    path.write_text("# mine\nBENCHBOSS_NOTIFY_CMD=/bin/tell-me\n"
                    "export BENCHBOSS_NTFY_TOPIC=old\nBENCHBOSS_NTFY_TOKEN=tk_old_token\n",
                    encoding="utf-8")
    notify.save_ntfy(f" {TOPIC} ", "", "https://push.example.org")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == ["# mine", "BENCHBOSS_NOTIFY_CMD=/bin/tell-me", f"BENCHBOSS_NTFY_TOPIC={TOPIC}",
                     "BENCHBOSS_NTFY_SERVER=https://push.example.org"]  # the empty token is gone
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert notify.secrets({})["BENCHBOSS_NTFY_TOPIC"] == TOPIC
    (b,) = notify.backends(["ntfy"], env={})
    assert b.topic == TOPIC and b.server == "https://push.example.org"


@pytest.mark.parametrize("topic,token,server", [
    ("", "", ""), ("has space", "", ""), ("a/b", "", ""), ("x" * 65, "", ""),
    (TOPIC, "two words", ""), (TOPIC, "a\nB=1", ""), (TOPIC, "", "ntfy.sh"),
    (TOPIC, "", "ftp://x.org"), (TOPIC, "", "https://x.org\nOTHER=1")])
def test_save_ntfy_refuses_what_ntfy_or_the_file_cannot_hold(topic, token, server):
    with pytest.raises(notify.NotifyError):
        notify.save_ntfy(topic, token, server)
    assert not store.notify_env_path().exists()


def test_new_topic_is_long_and_valid():
    a, b = notify.new_topic(), notify.new_topic()
    assert a != b and notify.TOPIC_RE.fullmatch(a) and len(a) >= 20


def test_set_backend_adds_and_removes_ntfy_and_keeps_the_rest():
    on = screen.set_backend({"ntfy_server": "x"}, True)
    assert on["backends"][-1] == "ntfy" and on["ntfy_server"] == "x"
    assert screen.set_backend(on, True)["backends"].count("ntfy") == 1
    off = screen.set_backend({"backends": ["log", "ntfy"]}, False)
    assert off == {"backends": ["log"]}


def test_save_field_leaves_the_other_fields():
    config_mod.save(Config(league_id=7, theme="light"))
    config_mod.save_field("notify", {"backends": ["ntfy"]})
    raw = json.loads(Config().path.read_text())
    assert raw["league_id"] == 7 and raw["theme"] == "light"
    assert raw["notify"] == {"backends": ["ntfy"]}


def test_the_demo_saves_and_sends_nothing(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the demo sent a notification")

    monkeypatch.setattr(notify, "send", refuse)

    async def scenario(pilot, app, view):
        assert view.data.demo and app.focused is view.query_one("#st-topic", Input)
        view.query_one("#st-topic", Input).value = TOPIC
        for button in ("#st-save", "#st-test", "#st-off"):
            view.query_one(button, Button).press()
            await settle(pilot)
            assert "Demo" in view.message[0]
        view.query_one("#st-new", Button).press()
        await settle(pilot)
        assert view.query_one("#st-topic", Input).value == TOPIC  # no new topic in the demo
        assert not store.notify_env_path().exists() and not Config().path.exists()

    drive(scenario)


def test_save_writes_the_file_and_turns_ntfy_on():
    async def scenario(pilot, app, view):
        view.data.demo = False
        view.query_one("#st-topic", Input).value = TOPIC
        await pilot.press("enter")
        await settle(pilot)
        assert view.message[1] == "good", view.message
        assert notify.secrets({})["BENCHBOSS_NTFY_TOPIC"] == TOPIC
        assert "ntfy" in json.loads(Config().path.read_text())["notify"]["backends"]
        assert app.cfg.notify == json.loads(Config().path.read_text())["notify"]
        assert view.data.enabled
        view.query_one("#st-off", Button).press()
        await settle(pilot)
        assert "ntfy" not in json.loads(Config().path.read_text())["notify"]["backends"]
        assert notify.secrets({})["BENCHBOSS_NTFY_TOPIC"] == TOPIC  # the topic stays
        view.query_one("#st-topic", Input).value = "not valid!"
        view.query_one("#st-save", Button).press()
        await settle(pilot)
        assert view.message[1] == "bad"
        assert notify.secrets({})["BENCHBOSS_NTFY_TOPIC"] == TOPIC

    drive(scenario)


def test_test_sends_one_note_with_the_boxes_and_shows_the_receipt(monkeypatch):
    sent = []

    def fake(note, to):
        sent.append((note, to))
        return ["ntfy: sent"]

    monkeypatch.setattr(notify, "send", fake)

    async def scenario(pilot, app, view):
        view.data.demo = False
        view.query_one("#st-topic", Input).value = TOPIC
        view.query_one("#st-token", Input).value = "tk_123456"
        view.query_one("#st-test", Button).press()
        await settle(pilot)
        assert len(sent) == 1
        (backend,) = sent[0][1]
        assert (backend.topic, backend.token, backend.server) == (TOPIC, "tk_123456",
                                                                  notify.NTFY_SERVER)
        assert view.message[1] == "good"
        assert not view.query_one("#st-test", Button).disabled
        assert not store.notify_env_path().exists()  # Test saves nothing

    drive(scenario)


def test_copy_puts_the_topic_on_the_clipboard(monkeypatch):
    monkeypatch.setattr(screen.subprocess, "run", lambda *a, **k: None)  # no real pbcopy

    async def scenario(pilot, app, view):
        view.query_one("#st-copy", Button).press()
        await settle(pilot)
        assert view.message[1] == "bad"  # nothing to copy yet
        view.query_one("#st-topic", Input).value = TOPIC
        view.query_one("#st-copy", Button).press()
        await settle(pilot)
        assert app.clipboard == TOPIC and view.message[1] == "good"

    drive(scenario)


def test_categories_default_to_all_and_ignore_what_is_unknown():
    everything = set(notify.CATEGORY_KEYS)
    assert notify.categories({}) == everything
    assert notify.categories({"alerts": "lineup"}) == everything  # not a list: ignored
    assert notify.categories({"alerts": []}) == set()
    assert notify.categories({"alerts": ["lineup", " Watchlist ", "bogus"]}) == {
        "lineup", "watchlist"}
    assert screen.set_alerts({"backends": ["log"]}, ["problems", "lineup", "x"]) == {
        "backends": ["log"], "alerts": ["lineup", "problems"]}


def test_alerts_is_a_tab_and_opening_it_saves_nothing():
    async def scenario(pilot, app, view):
        tabs = view.query_one(TabbedContent)
        assert tabs.active == "st-alerts"
        boxes = [view.query_one(f"#st-cat-{k}", Checkbox) for k in notify.CATEGORY_KEYS]
        assert all(b.value for b in boxes)
        assert not Config().path.exists()

    drive(scenario)


def test_a_category_box_saves_at_once_and_the_demo_only_remembers_it():
    async def scenario(pilot, app, view):
        box = view.query_one("#st-cat-watchlist", Checkbox)
        box.value = False
        await settle(pilot)
        assert view.data.alerts == ("lineup", "armed", "problems")
        assert "Demo" in view.message[0] and not Config().path.exists()
        view.data.demo = False
        box.value = True
        await settle(pilot)
        view.query_one("#st-cat-lineup", Checkbox).value = False
        await settle(pilot)
        saved = json.loads(Config().path.read_text())["notify"]
        assert saved == {"alerts": ["watchlist", "armed", "problems"]}
        assert app.cfg.notify == saved and view.message[1] == "good"
        assert notify.categories(saved) == {"watchlist", "armed", "problems"}
        for key in ("watchlist", "armed", "problems"):
            view.query_one(f"#st-cat-{key}", Checkbox).value = False
            await settle(pilot)
        assert json.loads(Config().path.read_text())["notify"]["alerts"] == []
        assert "sends nothing" in screen.status_line(view.data, screen.DARK).plain

    drive(scenario)


@pytest.mark.parametrize("size", [(140, 44), (46, 30)])
def test_the_tab_fits_a_laptop_and_a_phone(size):
    async def scenario(pilot, app, view):
        await pilot.pause(0.2)
        text = layout.screen_text(app)
        assert "Alerts" in text and "ntfy topic" in text, text
        for line in text.splitlines():
            assert len(line) <= size[0]

    drive(scenario, size=size)


def test_save_keeps_the_chosen_categories():
    async def scenario(pilot, app, view):
        view.data.demo = False
        view.query_one("#st-cat-armed", Checkbox).value = False
        await settle(pilot)
        view.query_one("#st-topic", Input).value = TOPIC
        view.query_one("#st-save", Button).press()
        await settle(pilot)
        saved = json.loads(Config().path.read_text())["notify"]
        assert saved["alerts"] == ["lineup", "watchlist", "problems"] and "ntfy" in saved["backends"]

    drive(scenario)


def test_the_status_says_when_the_environment_wins(monkeypatch):
    monkeypatch.setenv("BENCHBOSS_NTFY_TOPIC", "from-the-environment")
    data = screen.load(type("S", (), {"cfg": Config(), "demo": False})())
    assert data.topic == "from-the-environment" and data.env == ("BENCHBOSS_NTFY_TOPIC",)
    assert "wins" in screen.status_line(data, screen.DARK).plain
    assert os.environ["BENCHBOSS_NTFY_TOPIC"]

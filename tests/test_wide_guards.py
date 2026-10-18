"""The laptop look does not change: every guarded screen at the window sizes in
``layout.WIDE_GUARDS`` (120x40 and 150x54) must match its text snapshot in
tests/snapshots/wide/.

The phone work in 1.0.4 changes how the app reads under 80 columns or 30 rows. These
snapshots make sure it leaves the wide view alone. When a change to a wide screen is on
purpose, write the snapshots again and look at the diff before committing it:

    BENCHBOSS_UPDATE_GUARDS=1 pytest tests/test_wide_guards.py

The version number in the top bar is replaced by "X.Y.Z", so a release does not touch them.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from benchboss import __version__
from benchboss.config import Config
from benchboss.ui import layout
from benchboss.ui.app import Benchboss

SNAPSHOTS = Path(__file__).parent / "snapshots" / "wide"

# (name, keys pressed from the dashboard). The screens other 1.0.4 packages redraw on purpose
# (news, workload, playoffs, inbox) are left out; their own tests pin them.
GUARDED = (
    ("dash", ""),
    ("today", "t"),
    ("week", "w"),
    ("trash", "f"),
    ("players", "p"),
    ("players-card", "p enter"),
    ("trades", "x"),
    ("standings", "s"),
    ("roster", "o"),
)


async def _settle(pilot, wait: float = 0.3) -> None:
    for _ in range(2):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
    await pilot.pause(wait)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def _normal(text: str) -> str:
    return text.replace(__version__, "X.Y.Z")


async def _capture(size: tuple[int, int]) -> dict[str, str]:
    """Every guarded screen at ``size``, each from a fresh dashboard."""
    shots: dict[str, str] = {}
    app = Benchboss(Config(theme="dark"), demo=True)
    async with app.run_test(size=size) as pilot:
        await _settle(pilot)
        for name, keys in GUARDED:
            await pilot.press("d")
            await _settle(pilot)
            for key in keys.split():
                await pilot.press(key)
                await _settle(pilot)
            shots[name] = _normal(layout.screen_text(app))
    return shots


@pytest.mark.parametrize("size", layout.WIDE_GUARDS, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_wide_view_does_not_change(size):
    shots = asyncio.run(_capture(size))
    tag = f"{size[0]}x{size[1]}"
    if os.environ.get("BENCHBOSS_UPDATE_GUARDS"):
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        for name, text in shots.items():
            (SNAPSHOTS / f"{name}-{tag}.txt").write_text(text + "\n", encoding="utf-8")
    changed = []
    for name, text in shots.items():
        path = SNAPSHOTS / f"{name}-{tag}.txt"
        want = path.read_text(encoding="utf-8").rstrip("\n") if path.exists() else None
        if want != text:
            changed.append(name)
            if want is not None:
                for i, (a, b) in enumerate(zip(want.splitlines(), text.splitlines(), strict=False)):
                    if a != b:
                        print(f"{name} {tag} line {i + 1}\n  was: {a}\n  now: {b}")
                        break
    assert not changed, f"the wide view changed at {tag}: {changed}"

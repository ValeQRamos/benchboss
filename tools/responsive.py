"""Look at every screen of the demo app at phone, landscape and laptop sizes.

    python tools/responsive.py                       # every screen, every size, dark theme
    python tools/responsive.py --sizes 46x40,100x12 --screens dash,players
    python tools/responsive.py --theme light --svg   # also an SVG of each screen

Writes build/responsive/<W>x<H>/<screen>.txt (plain text of what the window shows) and, with
--svg, the matching .svg. It also turns a phone around on the Player finder (46x40, then
100x26, then 46x40) into build/responsive/rotate/. Nothing talks to ESPN: it runs the bundled
demo league. Run it and read the phone sizes before a release (CONTRIBUTING.md); the wide
sizes are pinned by tests/test_wide_guards.py.

At the end it prints one line per size with what to look at: a key bar without "m menu", a
screen whose title wrapped, a Player finder with no rows.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from benchboss.config import Config
from benchboss.ui import layout
from benchboss.ui.app import MENU, Benchboss

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "responsive"

# portrait phones (keyboard down and up), landscape phones, a short laptop pane, laptops
SIZES = ((40, 32), (40, 18), (46, 40), (46, 30), (46, 18), (60, 24), (80, 24), (90, 26),
         (100, 12), (110, 25), (120, 40), (150, 45), (150, 54))
EXTRA = {"players-card": "p enter", "players-search": "p slash", "menu": "m"}


def screens() -> dict[str, str]:
    """screen name -> the keys that open it from the dashboard (every menu entry)."""
    out = {sid: key for sid, _, key in MENU}
    out["dash"] = ""
    out.update(EXTRA)
    return out


def size_of(text: str) -> tuple[int, int]:
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


async def settle(pilot, wait: float = 0.4) -> None:
    for _ in range(2):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
    await pilot.pause(wait)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def checks(name: str, text: str) -> list[str]:
    """Things a person should look at, from the plain text alone."""
    lines = text.splitlines()
    notes = []
    bottom = lines[-1] if lines else ""
    # the menu page has "m close"; a laptop's footer shows only the search box's keys while it
    # has the focus
    if name not in ("menu", "players-search") and "m menu" not in bottom.lower():
        notes.append("no 'm menu' on the bottom row")
    rows = any(re.search(r"\s\d+\.\d\b", x) for x in lines[3:])
    if name.startswith("players") and name != "players-card" and not rows:
        notes.append("no player rows")
    return notes


async def shoot(size: tuple[int, int], names: list[str], theme: str, svg: bool) -> list[str]:
    folder = OUT / f"{size[0]}x{size[1]}"
    folder.mkdir(parents=True, exist_ok=True)
    keys = screens()
    report = []
    app = Benchboss(Config(theme=theme), demo=True)
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        for name in names:
            await pilot.press("escape")  # out of a search box, so d is a key and not a letter
            await pilot.press("d")
            await settle(pilot)
            for key in keys[name].split():
                await pilot.press(key)
                await settle(pilot)
            text = layout.screen_text(app)
            (folder / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
            if svg:
                app.save_screenshot(filename=f"{name}.svg", path=str(folder))
            report += [f"{size[0]}x{size[1]} {name}: {note}" for note in checks(name, text)]
            if name == "menu":
                await pilot.press("m")  # close it again
                await settle(pilot, 0.1)
    return report


async def rotate(theme: str, svg: bool) -> None:
    folder = OUT / "rotate"
    folder.mkdir(parents=True, exist_ok=True)
    app = Benchboss(Config(theme=theme), demo=True)
    async with app.run_test(size=(46, 40)) as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        for step, size in enumerate(((46, 40), (100, 26), (46, 40))):
            await pilot.resize_terminal(*size)
            await settle(pilot)
            name = f"{step + 1}-players-{size[0]}x{size[1]}"
            (folder / f"{name}.txt").write_text(layout.screen_text(app) + "\n", encoding="utf-8")
            if svg:
                app.save_screenshot(filename=f"{name}.svg", path=str(folder))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sizes", help="comma separated, like 46x40,100x12 (default: the phone, "
                                    "landscape and laptop matrix)")
    ap.add_argument("--screens", help=f"comma separated, from: {', '.join(screens())}")
    ap.add_argument("--theme", choices=("dark", "light"), default="dark")
    ap.add_argument("--svg", action="store_true", help="also write an SVG of every screen")
    args = ap.parse_args(argv)
    sizes = [size_of(s) for s in args.sizes.split(",")] if args.sizes else list(SIZES)
    names = args.screens.split(",") if args.screens else list(screens())
    unknown = [n for n in names if n not in screens()]
    if unknown:
        ap.error(f"unknown screen: {', '.join(unknown)}")
    report: list[str] = []
    for size in sizes:
        report += asyncio.run(shoot(size, names, args.theme, args.svg))
        print(f"{size[0]}x{size[1]}: {len(names)} screens", file=sys.stderr)
    if not args.sizes and not args.screens:
        asyncio.run(rotate(args.theme, args.svg))
    print(f"wrote {OUT.relative_to(ROOT)}/")
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

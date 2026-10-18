"""Regenerate the README screenshots from demo data.

    python tools/screenshots.py            # writes docs/images/*.svg (and *.png on macOS)

Most shots are a 150x54 laptop window. The phone-* shots are a 46x40 portrait phone, where the
app runs its compact layout (key bar, menu as a page).

PNGs are rendered with macOS QuickLook (qlmanage) and trimmed with ImageMagick when both are
available (the SVGs are then removed); otherwise the SVGs are kept.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console

from benchboss.config import Config
from benchboss.demo import demo_session
from benchboss.ui import dashboard
from benchboss.ui.app import Benchboss
from benchboss.ui.theme import palette

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


async def app_shots(theme: str, shots: list[tuple[str, str]], size=(150, 54)) -> None:
    app = Benchboss(Config(theme=theme), demo=True)
    async with app.run_test(size=size) as pilot:
        await pilot.pause(2.5)
        for key, name in shots:
            if key == "apply":
                await pilot.click("#apply")
                await pilot.pause(1.5)
            elif key == "arm":  # Auto-swap: enter shows what would happen, a second enter arms
                await pilot.press("enter")
                await pilot.pause(1.5)
                await pilot.press("enter")
                await pilot.pause(2.5)
            elif key:
                await pilot.press(key)
                await pilot.pause(2.5)
            if name:  # a step with no name only gets the screen ready for the next one
                app.save_screenshot(filename=f"{name}.svg", path=str(OUT))


def side_panel(width: int = 46) -> None:
    session = demo_session(Config(theme="dark"))
    d = dashboard.collect(session)
    console = Console(record=True, width=width, force_terminal=True, color_system="truecolor",
                      file=io.StringIO())
    console.print(dashboard.render(d, palette("dark"), width))
    console.save_svg(str(OUT / "side-panel.svg"), title="benchboss dash --watch")


def to_png(svg: Path, width: int = 1600) -> None:
    """Render, trim, shrink to ``width`` and keep 256 colors (a terminal has few, and the
    files come out about a third of the size with no visible change)."""
    if not (shutil.which("qlmanage") and shutil.which("magick")):
        return
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["qlmanage", "-t", "-s", "2400", "-o", tmp, str(svg)],
                       capture_output=True, check=False)
        rendered = Path(tmp) / (svg.name + ".png")
        if rendered.exists():
            subprocess.run(["magick", str(rendered), "-trim", "+repage", "-resize", f"{width}x>",
                            "+dither", "-colors", "256", "-strip",
                            f"PNG8:{svg.with_suffix('.png')}"], check=False)
    if svg.with_suffix(".png").exists():
        svg.unlink()  # the README uses the PNGs; keep the repo light


PHONE = (46, 40)  # a portrait phone over SSH: the app goes compact under 80 columns
PHONE_WIDTH = 640  # pixels; the README shows two of them side by side


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # every image the README shows, plus optimize-done and dashboard-light; the finder (p) and
    # the playoff builder (y) take the focus, and the next menu key still reaches the app
    asyncio.run(app_shots("dark", [("", "dashboard"), ("w", "optimize-week"), ("apply", "optimize-done"),
                                   ("f", "trash"), ("x", "trades"), ("a", "workload"), ("n", "news"),
                                   ("p", "players"), ("s", "standings"), ("o", "roster"),
                                   ("y", "playoffs"), ("u", ""), ("arm", "autoswap")]))
    asyncio.run(app_shots("light", [("", "dashboard-light")]))
    asyncio.run(app_shots("dark", [("", "phone-dashboard"), ("p", "phone-players")], size=PHONE))
    side_panel()
    for svg in OUT.glob("*.svg"):
        to_png(svg, PHONE_WIDTH if svg.stem.startswith("phone-") else 1600)
    print("\n".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    sys.exit(main())

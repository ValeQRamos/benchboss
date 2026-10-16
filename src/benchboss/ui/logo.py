"""The benchboss mark: a small pixel-art basketball.

Each terminal cell holds two pixels stacked: "▀" paints the top one, "▄" the bottom one and
"█" both. When the two pixels of a cell are different parts of the ball, "▀" gets the top
color as foreground and the bottom color as background. A pixel outside the ball gets no
color at all, so the terminal's own background shows through on dark and light themes.

Pixels: O ball (the palette accent), D shade (a darker orange, the lower right side),
S seam, . nothing. tools/make_logo.py turns BALL into docs/images/logo.png.
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

from benchboss.ui.theme import Palette

# 11 x 10 pixels, 5 rows of text: the side seams curve like "( | )" around the cross
BALL = (
    "...OOOOO...",
    "..OOOSOOO..",
    ".OSOOSOOSO.",
    "OSOOOSOOOSO",
    "OSSSSSSSSSD",
    "OSOOOSOOOSD",
    "OSOOOSOOOSD",
    ".OSOOSOOSD.",
    "..DDDSDDD..",
    "...DDDDD...",
)

# 4 x 2 pixels, one row of text, for the app's top bar. Two pixels of height cannot draw a
# circle, so shading does it: a lit top, a darker rim, and the two lower corners in E, an
# edge color halfway to the background that rounds the ball off like anti-aliasing. (A
# vertical seam at this size looked like a pause button.)
MARK = (
    "DOOD",
    "EDDE",
)


def _mix(color: str, factor: float) -> str:
    """``color`` (#rrggbb) with each channel scaled by ``factor``."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{min(255, round(c * factor)):02x}" for c in rgb)


def _toward_white(color: str, amount: float) -> str:
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * amount):02x}" for c in rgb)


def colors(pal: Palette) -> dict[str, str]:
    """Pixel letter -> color for this palette."""
    shade = _mix(pal.accent, 0.72)
    edge = _toward_white(shade, 0.5) if pal.name == "light" else _mix(pal.accent, 0.3)
    return {"O": pal.accent, "D": shade, "S": _mix(pal.accent, 0.22), "E": edge}


def draw(rows: tuple[str, ...], pal: Palette) -> Text:
    """Half-block text for a pixel design (an odd last row gets an empty half under it)."""
    rows = tuple(rows) + (("." * len(rows[0]),) if len(rows) % 2 else ())
    paint = colors(pal)
    out = Text(no_wrap=True, overflow="crop", end="")
    for r in range(0, len(rows), 2):
        if r:
            out.append("\n")
        for top, bottom in zip(rows[r], rows[r + 1], strict=True):
            t, b = paint.get(top), paint.get(bottom)
            if t is None and b is None:
                out.append(" ")
            elif t == b:
                out.append("█", Style(color=t))
            elif b is None:
                out.append("▀", Style(color=t))
            elif t is None:
                out.append("▄", Style(color=b))
            else:
                out.append("▀", Style(color=t, bgcolor=b))
    return out


def ball(pal: Palette) -> Text:
    """The dashboard logo: 11 cells wide, 5 rows tall."""
    return draw(BALL, pal)


def mark(pal: Palette) -> Text:
    """The top bar mark: 4 cells wide, 1 row tall."""
    return draw(MARK, pal)


BALL_WIDTH = len(BALL[0])
BALL_HEIGHT = (len(BALL) + 1) // 2

__all__ = ["BALL", "BALL_HEIGHT", "BALL_WIDTH", "MARK", "ball", "colors", "draw", "mark"]

"""The benchboss mark: a pixel-art basketball.

Each terminal cell holds two pixels stacked: "▀" paints the top one, "▄" the bottom one and
a colored background both (a block glyph leaves a hairline between rows in SVG screenshots).
When the two pixels of a cell are different parts of the ball, "▀" gets the top color as
foreground and the bottom color as background. A pixel outside the ball gets no
color at all, so the terminal's own background shows through on dark and light themes.

The ball is seen a little from above and turned to the right, lit from the top left, so the
seams curve the way they do on a real ball. Pixels: O ball (the palette accent), H the shine,
D the shaded side, S seam, . nothing. tools/make_logo.py turns BALL into docs/images/logo.png.
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

from benchboss.ui.theme import Palette

# 15 x 15 pixels, 8 rows of text (the last one half empty)
BALL = (
    ".....OOSOO.....",
    "...OOOOSOOOO...",
    "..SOHHHOSOOOS..",
    ".OOSHHHOSOOOSD.",
    ".OHSHHOOSOOOSD.",
    "OOHSOOOOSOOOSDD",
    "OOOOSOOOSOOOSDD",
    "OOOOSOOOSOOOSDD",
    "SOOOSOOOSOOOSDS",
    "OSSSSOOOSOSSSSD",
    ".OOOSSSSSSDDDD.",
    ".OOOSOOOSDDDSD.",
    "..DSDDDDSDDDS..",
    "...SDDDDSDDD...",
    ".....DDDSD.....",
)

# The app's top bar has one row: too little for pixels to make a round ball, so it gets a
# round glyph in the ball's color instead.
MARK = "●"


def _mix(color: str, factor: float) -> str:
    """``color`` (#rrggbb) with each channel scaled by ``factor``."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{min(255, round(c * factor)):02x}" for c in rgb)


def _toward_white(color: str, amount: float) -> str:
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * amount):02x}" for c in rgb)


def colors(pal: Palette) -> dict[str, str]:
    """Pixel letter -> color for this palette."""
    return {"O": pal.accent, "H": _toward_white(pal.accent, 0.3), "D": _mix(pal.accent, 0.74),
            "S": _mix(pal.accent, 0.22)}


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
            elif t == b:  # a background-colored space: no seam between rows in any renderer
                out.append(" ", Style(bgcolor=t))
            elif b is None:
                out.append("▀", Style(color=t))
            elif t is None:
                out.append("▄", Style(color=b))
            else:
                out.append("▀", Style(color=t, bgcolor=b))
    return out


def ball(pal: Palette) -> Text:
    """The dashboard logo: 15 cells wide, 8 rows tall."""
    return draw(BALL, pal)


def mark(pal: Palette) -> Text:
    """The top bar mark: one cell."""
    return Text(MARK, style=f"bold {pal.accent}", end="")


BALL_WIDTH = len(BALL[0])
BALL_HEIGHT = (len(BALL) + 1) // 2

__all__ = ["BALL", "BALL_HEIGHT", "BALL_WIDTH", "MARK", "ball", "colors", "draw", "mark"]

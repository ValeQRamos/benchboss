"""Layout rules every screen follows, from a phone over SSH (40 columns) to a wide laptop.

The app switches to the compact layout on small windows (``is_compact``), or always or
never with ``--layout``, BENCHBOSS_LAYOUT or ``layout`` in config.json (config.LAYOUTS).
Compact means: a one-row key bar instead of the footer and the status line, a smaller
gutter, the menu as a full page, the pixel ball only on tall windows.

What every screen does:

- ``draw(data, pal, width, view)`` stays width-only and fits every width in FIT_WIDTHS:
  no row wider than ``width``, nothing cut mid-word, a title on one line.
- An interactive widget reads ``app.compact`` and ``app.short`` (``getattr`` with a False
  default) for height choices, and exposes ``key_items() -> list[KeyItem]``: its own keys
  for the key bar. The app adds the global ones (m menu, d dashboard, r refresh, q quit).
- Every action has a key that a phone keyboard reaches: letters, digits, or the first
  symbols page (- / : ; ( ) . , ? ! ' "). Esc, arrows and PgUp/PgDn keep working too.
- A widget never binds a menu letter (d t w a f p n x i s y o u) or g v m r q.
- A tap (KeyItem.action) never sends anything to ESPN; at most it moves the focus to Apply.
- The wide layouts in WIDE_GUARDS do not change: the tests compare them before and after.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchboss.config import LAYOUTS

COMPACT_WIDTH = 80        # narrower than this: compact
COMPACT_HEIGHT = 30       # shorter than this: compact (and app.short)
COMPACT_HEIGHT_EXIT = 33  # once compact by height, stay until taller than this (the phone
                          # keyboard opening and closing must not flip the layout)
LOGO_MIN_HEIGHT = 34      # rows a window needs to show the pixel ball on the dashboard
DASH_TWO_COLUMNS = 78     # content columns from which the dashboard uses two columns
GUTTER = {False: 6, True: 3}  # columns of padding and scrollbar around the content
FIT_WIDTHS = (40, 46, 60, 80, 120, 150)   # widths every draw() is tested at
WIDE_GUARDS = ((120, 40), (150, 54))      # window sizes whose look must not change


@dataclass(frozen=True)
class KeyItem:
    """One key in the compact key bar."""
    key: str           # as shown: "m", "/", "1-2", "space", "⏎"
    label: str         # "menu", "search"
    action: str = ""   # Textual action run on a tap, e.g. "app.toggle_menu"; "" = none
    priority: int = 50  # lower shows first and drops last; the app's "m menu" is 0


def is_compact(width: int, height: int, layout: str = "auto", was: bool = False) -> bool:
    """Whether a ``width`` x ``height`` window uses the compact layout. ``was`` says the
    window is compact because it got short (the height hysteresis), not because it was
    narrow: a phone turned from portrait to landscape starts over."""
    if layout == "compact":
        return True
    if layout == "full":
        return False
    if width < COMPACT_WIDTH or height < COMPACT_HEIGHT:
        return True
    return was and height <= COMPACT_HEIGHT_EXIT


def screen_text(app) -> str:
    """What a running Textual app shows right now, as plain text: one line per row, trailing
    blanks removed. The same render ``App.export_screenshot`` turns into an SVG; the tests and
    ``tools/responsive.py`` compare it across window sizes."""
    import io

    from rich.console import Console

    width, height = app.size
    console = Console(width=width, height=height, file=io.StringIO(), record=True,
                      color_system=None, legacy_windows=False, safe_box=False)
    console.print(app.screen._compositor.render_update(full=True))
    return "\n".join(line.rstrip() for line in console.export_text().splitlines())


__all__ = ["COMPACT_HEIGHT", "COMPACT_HEIGHT_EXIT", "COMPACT_WIDTH", "DASH_TWO_COLUMNS",
           "FIT_WIDTHS", "GUTTER", "KeyItem", "LAYOUTS", "LOGO_MIN_HEIGHT", "WIDE_GUARDS",
           "is_compact", "screen_text"]

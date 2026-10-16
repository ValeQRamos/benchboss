"""Drawing helpers shared by the views, the screens and the dashboard.

The look, in short (every screen follows it, so the app reads as one thing):

- One title line per screen: the screen name in bold accent, then dim context after a
  middle dot ("Roster · Monstars 2-0 · Last 7 days"). See ``title``.
- Tables use ``table``: no outer box, a thin rule under a dim bold header, numbers right
  aligned, one decimal for fantasy points, percentages with no decimals unless they are
  small. Secondary columns are dim; the number the screen is about is bold.
- Color means something: accent = you and headings, good/bad = better or worse than the
  rest, warn = injuries and risk, dim = context. No color just for decoration.
- A player is "Name TEAM INJ" (``player_cell``): the name in text color, the NBA team dim,
  the injury tag in warn or bad.
- Legends and explanations go in one dim caption line under the table, kept short.
- No emoji. The glyphs in use: ● ○ ★ ☆ ▲ ▼ · ━ and the bar and spark blocks below.
- Every screen fits the width it is given: drop secondary columns before cutting names.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from rich import box
from rich.table import Table
from rich.text import Text

from benchboss.espn.models import Player
from benchboss.ui.theme import Palette

SPARK = "▁▂▃▄▅▆▇█"


def table(pal: Palette, title: str | None = None, caption: str | None = None) -> Table:
    return Table(title=title, caption=caption, box=box.SIMPLE_HEAD, header_style=f"bold {pal.dim}",
                 title_style=f"bold {pal.accent}", title_justify="left",
                 caption_style=pal.dim, caption_justify="left", border_style=pal.border,
                 pad_edge=False, expand=False)


def title(text: str, pal: Palette, *context: str) -> Text:
    """The screen's title line: "Roster · Monstars 2-0 · Last 7 days"."""
    out = Text()
    out.append(text, style=f"bold {pal.accent}")  # only the name is bold, not the context
    for part in context:
        if part:
            out.append("  ·  ", style=pal.border)
            out.append(part, style=pal.dim)
    return out


def day_label(d: dt.date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def num(v, fmt="{:.1f}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "-"


def pct(v: float | None, digits: int = 0) -> str:
    """A fraction as a percentage: 0.463 -> "46%" (or "46.3%" with digits=1)."""
    return "-" if v is None else f"{v * 100:.{digits}f}%"


def injury(p: Player, pal: Palette) -> Text:
    return Text(p.injury, style=pal.bad if p.injury in ("OUT", "SUSP", "IR") else pal.warn)


def player_cell(p: Player, pal: Palette, *, team: bool = True, inj: bool = True,
                style: str | None = None, short: bool = False) -> Text:
    """ "LaMelo Ball MIN DTD": the name, then the NBA team dim, then the injury tag."""
    out = Text(p.short_name if short else p.name, style=style or pal.text)
    if team:
        out.append(f" {p.pro_team}", style=pal.dim)
    if inj and p.injury:
        out.append(f" {p.injury}", style=pal.bad if p.injury in ("OUT", "SUSP", "IR") else pal.warn)
    return out


def scale(value: float | None, values: Iterable[float | None], pal: Palette,
          higher_is_better: bool = True) -> str:
    """good for the top quarter of ``values``, bad for the bottom quarter, text otherwise."""
    pool = sorted(v for v in values if v is not None)
    if value is None or len(pool) < 4:
        return pal.text
    lo, hi = pool[len(pool) // 4], pool[(3 * len(pool)) // 4]
    if value >= hi and hi > lo:
        return pal.good if higher_is_better else pal.bad
    if value <= lo and hi > lo:
        return pal.bad if higher_is_better else pal.good
    return pal.text


def spark(values: Iterable[float | None], pal: Palette, style: str | None = None) -> Text:
    """A one-line sparkline: ▂▅▇▃ (a gap for None)."""
    vals = list(values)
    nums = [v for v in vals if v is not None]
    if not nums:
        return Text("")
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    chars = "".join(" " if v is None else SPARK[min(7, int((v - lo) / span * 7.999))] for v in vals)
    return Text(chars, style=style or pal.info)


def meter(fraction: float | None, width: int, pal: Palette, color: str | None = None) -> Text:
    """A thin horizontal bar, ``width`` cells: ━━━━━━──── (fraction 0..1)."""
    if fraction is None:
        return Text("·" * width, style=pal.border)
    f = max(0.0, min(1.0, fraction))
    full = round(f * width)
    return Text.assemble(("━" * full, color or pal.accent), ("─" * (width - full), pal.border))


def legend(pal: Palette, *items: tuple[str, str]) -> Text:
    """ "G games · L left this week": one dim caption line from (key, meaning) pairs."""
    out = Text()
    for i, (key, meaning) in enumerate(items):
        if i:
            out.append("  ·  ", style=pal.border)
        out.append(key, style=f"bold {pal.dim}")
        out.append(f" {meaning}", style=pal.dim)
    return out

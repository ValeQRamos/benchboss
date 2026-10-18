"""The one-row key bar of the compact layout (phones and short windows).

It replaces Textual's footer and the status line when the app is compact: the keys first,
"m menu" always among them, then a little dim context on the right when there is room
("Projected", "demo"). Keys that do not fit are left out by priority, never cut. A tap on a
key runs its action when it has one; no action sends anything to ESPN.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.widget import Widget

from benchboss.ui.layout import KeyItem
from benchboss.ui.theme import Palette

GAP = "  "  # between two keys


def piece(item: KeyItem, pal: Palette) -> Text:
    """ "m menu": the key bold, the label dim."""
    return Text.assemble((item.key, f"bold {pal.text}"), (f" {item.label}", pal.dim))


def fit(items: list[KeyItem], width: int, pal: Palette,
        context: str = "") -> tuple[Text, list[tuple[int, int, int]]]:
    """The bar for ``width`` cells, and the cells each shown item covers as (start, end, index
    into ``items``). Items are tried from the lowest priority number up and kept when they
    fit; they show in the order given. The context goes on the right only when it fits too."""
    order = sorted(range(len(items)), key=lambda i: items[i].priority)
    keep: set[int] = set()

    def size(chosen: set[int]) -> int:
        parts = [cell_len(items[i].key) + 1 + cell_len(items[i].label) for i in sorted(chosen)]
        return sum(parts) + len(GAP) * max(0, len(parts) - 1)

    for i in order:
        if size(keep | {i}) <= width:
            keep.add(i)
    out, regions = Text(no_wrap=True, overflow="crop"), []
    for i in sorted(keep):
        if out.cell_len:
            out.append(GAP)
        start = out.cell_len
        out.append_text(piece(items[i], pal))
        regions.append((start, out.cell_len, i))
    room = width - out.cell_len - len(GAP)
    if context and cell_len(context) <= room:
        out.append(" " * (width - out.cell_len - cell_len(context)))
        out.append(context, style=pal.dim)
    return out, regions


class KeyBar(Widget):
    """Draws ``app.key_entries()`` (pairs of KeyItem and the node its action runs on) and
    ``app.status_short`` at its own width each time it refreshes."""

    DEFAULT_CSS = """
    KeyBar { height: 1; padding: 0 1; display: none; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.regions: list[tuple[int, int, int]] = []
        self._entries: list = []

    def on_mount(self) -> None:
        # Textual tells the footer when the focus moves or the bindings change; the bar
        # listens to the same signal so a widget's keys follow its state
        signal = getattr(self.screen, "bindings_updated_signal", None)
        if signal is not None:
            signal.subscribe(self, lambda _screen: self.refresh())

    def render(self) -> Text:
        app = self.app
        entries = list(getattr(app, "key_entries", list)())
        self._entries = entries
        pal = getattr(app, "pal", None)
        if pal is None:
            from benchboss.ui.theme import DARK

            pal = DARK
        width = max(1, self.content_region.width or self.size.width)
        out, self.regions = fit([item for item, _ in entries], width, pal,
                                getattr(app, "status_short", ""))
        return out

    async def on_click(self, event) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        hit = next((r for r in self.regions if r[0] <= offset.x < r[1]), None)
        if hit is None or hit[2] >= len(self._entries):
            return
        item, target = self._entries[hit[2]]
        if item.action:
            event.stop()
            await self.app.run_action(item.action, target)


__all__ = ["GAP", "KeyBar", "fit", "piece"]

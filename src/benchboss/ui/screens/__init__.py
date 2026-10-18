"""One module per screen. The app (ui/app.py) and the CLI (cli.py) both draw from them.

Every screen module exposes:

    TITLE: str                                   heading shown on the screen
    VIEWS: tuple[tuple[str, str], ...]           optional (key, label) alternate views; the app
                                                 cycles them with v, the CLI takes --view KEY
    load(session, **options) -> data             reads ESPN; runs in a worker thread in the app
    draw(data, pal, width, view=0) -> renderable a Rich renderable that fits ``width`` columns
    to_json(data) -> JSON-ready object           what ``--json`` prints

An interactive screen also exposes ``widget(data, app) -> textual.widget.Widget``. The app
mounts that widget in place of the static drawing (the CLI still uses ``draw``). The widget
gets the keyboard focus; keys it does not bind fall through to the app, so the one-key menu
(d t w a f p n x i s y o) keeps working unless an input box has the focus. A widget that
cycles VIEWS itself and skips some may define ``next_view() -> int`` (the index v goes to),
so the app's status line names the right one.

Rules for every screen: ``load`` may raise BenchbossError (the app shows the message);
``draw`` never calls ESPN, so a resize or ctrl+t redraws from the same data; both themes
(pal) must read well; nothing wider than ``width``.
"""

from __future__ import annotations

from benchboss.ui.screens import autoswap, finder, playoffs, roster, standings, trash, workload

# app screen id -> module (the dashboard, optimize, news, trades and inbox screens live in app.py)
SCREENS = {"roster": roster, "standings": standings, "activity": workload, "trash": trash,
           "players": finder, "playoffs": playoffs, "autoswap": autoswap}


def view_index(module, key: str | None) -> int:
    """The index of a view key in ``module.VIEWS`` (0 when ``key`` is None)."""
    views = getattr(module, "VIEWS", ())
    if not key:
        return 0
    keys = [k for k, _ in views]
    if key not in keys:
        from benchboss.errors import BenchbossError

        choices = ", ".join(keys) if keys else "none"
        raise BenchbossError(f"unknown view '{key}' (choices: {choices})")
    return keys.index(key)


__all__ = ["SCREENS", "view_index"]

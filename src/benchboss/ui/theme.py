"""Colors. Two palettes so the dashboard reads well on dark and light terminals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    text: str
    dim: str
    border: str
    accent: str   # basketball orange
    good: str
    bad: str
    warn: str
    info: str


DARK = Palette("dark", text="#e1e1e1", dim="#8a8a90", border="#4a4c53", accent="#ee7d32",
               good="#8ecc73", bad="#eb645a", warn="#fabd2f", info="#5c99fa")
LIGHT = Palette("light", text="#1f2328", dim="#6e7781", border="#c3c8cf", accent="#c4501a",
                good="#1a7f37", bad="#cf222e", warn="#9a6700", info="#0969da")


def palette(name: str | None) -> Palette:
    return LIGHT if (name or "").lower() == "light" else DARK

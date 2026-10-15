"""Name matching and small text helpers."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from typing import TypeVar

from benchboss.errors import BenchbossError

T = TypeVar("T")


def norm(s: str) -> str:
    """Lowercase, no accents, no punctuation: 'Nikola Jokić' -> 'nikola jokic'."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace(".", "").replace("'", "").replace("-", " ").split())


def match_one(items: Iterable[T], query: str, name: Callable[[T], str], where: str,
              kind: str = "players") -> T:
    """Exact (normalized) match wins; otherwise a unique substring match; otherwise an error.

    ``kind`` names the items in the error for several matches ("players", "teams")."""
    q = norm(query)
    items = list(items)
    hits = [x for x in items if q in norm(name(x))]
    exact = [x for x in hits if norm(name(x)) == q]
    if len(exact) == 1:
        return exact[0]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise BenchbossError(f"'{query}' is not in {where}")
    raise BenchbossError(f"'{query}' matches several {kind}: " + ", ".join(name(x) for x in hits))

"""Name matching and small text helpers."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from typing import TypeVar

from benchboss.errors import BenchbossError

T = TypeVar("T")

SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}


def surname(name: str) -> str:
    """ "Scotty Pippen Jr." -> "Pippen": the last name without a suffix, the way RotoWire
    headlines and narrow tables name a player."""
    parts = [p for p in name.split() if p.lower() not in SUFFIXES]
    return parts[-1] if parts else name


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


# --- ranking names for search (reading only) -----------------------------------------------------
#
# ``match_one`` above is what every write uses: exact, or one unique substring, or an error.
# ``rank`` is looser on purpose (typos, a first initial, one word of a name) and only ever
# picks a player to read about, never one to add, drop or trade.

EXACT, PREFIX, WORD_PREFIXES, WORD, WORD_START, INSIDE = 100, 90, 85, 80, 75, 70
FUZZY = 60          # times the similarity ratio, for names spelled a bit wrong
FUZZY_MIN = 0.75    # the least similarity that counts
LEAD = 10           # how far the best match must lead the next one to be picked alone
FUZZY_LEAD = 8      # the same when the best match is only a near spelling


def _score(q: str, words_q: list[str], full: str) -> float:
    """How well a normalized query matches one normalized name (0 = not at all)."""
    words = full.split()
    if not words:
        return 0.0
    if full == q:
        return EXACT
    if full.startswith(q):
        return PREFIX
    if len(words_q) > 1 and all(any(w.startswith(x) for w in words) for x in words_q):
        return WORD_PREFIXES
    if len(words_q) == 1 and q in words:
        return WORD
    if len(words_q) == 1 and any(w.startswith(q) for w in words):
        return WORD_START
    if q in full:
        return INSIDE
    from difflib import SequenceMatcher

    span = len(words_q)
    tries = {full, *words, *(" ".join(words[i:i + span]) for i in range(len(words)))}
    best = max(SequenceMatcher(None, q, t).ratio() for t in tries)
    return FUZZY * best if best >= FUZZY_MIN else 0.0


def rank(items: Iterable[T], query: str, name: Callable[[T], str],
         weight: Callable[[T], object] | None = None, n: int = 8) -> list[tuple[float, T]]:
    """The ``n`` items whose names match ``query`` best, as (score, item), best first.

    Scores: 100 the exact name, 90 the start of it ("ben sim"), 85 every word the start of a
    name word ("a edwards"), 80 one whole word ("simmons"), 75 the start of one word, 70
    inside the name ("okic"), and up to 60 for a near spelling ("ben simons"). Equal scores
    go to the higher ``weight`` (for players: % rostered)."""
    q = norm(query)
    if not q:
        return []
    words_q = q.split()
    scored = [(s, x) for x in items if (s := _score(q, words_q, norm(name(x))))]
    if weight is not None:
        scored.sort(key=lambda sx: weight(sx[1]), reverse=True)  # stable: the score sorts last
    scored.sort(key=lambda sx: sx[0], reverse=True)
    return scored[:n]


def confident(ranked: list[tuple[float, T]]) -> bool:
    """Whether the best of ``rank``'s matches is clearly the one meant: the only one, or
    ahead of the next by ``LEAD`` points (``FUZZY_LEAD`` for a near spelling)."""
    if not ranked:
        return False
    if len(ranked) == 1:
        return True
    top, second = ranked[0][0], ranked[1][0]
    return top - second >= (FUZZY_LEAD if top < INSIDE else LEAD)

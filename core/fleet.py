"""Known fleet list for idle-aircraft completion.

The dynamic list usually contains only aircraft with flight tasks.  Keep this
list explicit so missing tails can still be assigned as empty-task aircraft.
"""
from __future__ import annotations

KNOWN_FLEET_TAILS: tuple[str, ...] = (
    "305L",
    "306C",
    "300Z",
    "302Y",
    "303M",
    "30A2",
    "30AM",
    "30AN",
    "30EH",
    "321U",
    "322C",
    "325Q",
    "32Q6",
    "8432",
    "8983",
    "8285",
    "8318",
)

_FLEET_ORDER = {tail: idx for idx, tail in enumerate(KNOWN_FLEET_TAILS)}


def fleet_sort_key(tail: str) -> tuple[int, str]:
    """Stable tail ordering: known fleet order first, unknown tails afterward."""
    clean_tail = (tail or "").strip().upper()
    return (_FLEET_ORDER.get(clean_tail, len(_FLEET_ORDER)), clean_tail)

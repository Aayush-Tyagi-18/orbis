"""Check that a claimed quote really appears in the cited source.

This is the cheapest, most effective hallucination guard in the pipeline: if the model's
quote cannot be found in the document, the claim is not trusted.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .schema import Citation, Source

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _find_exact(q: list[str], hay: list[str]) -> bool:
    n = len(q)
    if n == 0 or n > len(hay):
        return False
    first = q[0]
    for i, w in enumerate(hay):
        if w == first and hay[i : i + n] == q:
            return True
    return False


def _find_fuzzy(q: list[str], hay: list[str], threshold: float = 0.9) -> bool:
    """Tolerate OCR noise and small model edits for longer quotes."""
    n = len(q)
    if n < 6 or n > len(hay):
        return False
    qs = " ".join(q)
    qset = set(q)
    for i in range(len(hay) - n + 1):
        if hay[i] not in qset:
            continue
        if SequenceMatcher(None, qs, " ".join(hay[i : i + n])).ratio() >= threshold:
            return True
    return False


def verify_citation(citation: Citation | None, source: Source) -> tuple[bool, int]:
    """Return (verified, page). Looks at the cited page first, then every other page."""
    if citation is None or not citation.quote.strip():
        return False, 1
    q = words(citation.quote)
    if not q:
        return False, citation.page
    order = [citation.page] + [p for p in range(1, len(source.pages) + 1) if p != citation.page]
    for page in order:
        if not 1 <= page <= len(source.pages):
            continue
        hay = words(source.pages[page - 1])
        if _find_exact(q, hay) or _find_fuzzy(q, hay):
            return True, page
    return False, citation.page

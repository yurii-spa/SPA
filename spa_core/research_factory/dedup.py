"""spa_core/research_factory/dedup.py — economic dedup (ADR-560 binding #3).

``no_duplicate_exposure`` fails on:
* a shared ``exposure_key`` with another known candidate (the SAME economic identity — this
  should be collapsed by ``registry.upsert`` already, but a defect elsewhere must still be
  caught, not silently admitted);
* a shared ``underlying_root`` with a candidate already in a PAPER state;
* a shared ``underlying_root`` with a holding already in the live books (``existing_book_roots``).

A shared ``economic_driver_key`` is a named correlation group shown to the CIO, NOT a block.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from typing import Iterable, Optional

from spa_core.research_factory import contract


def no_duplicate_exposure(candidate: dict, other_candidates: Iterable[dict],
                          existing_book_roots: Iterable[str]) -> tuple[str, str]:
    """``(verdict, reason)`` — verdict is ``contract.GATE_PASS`` or ``contract.GATE_FAIL``
    (never UNKNOWN: either a conflict is found or it is not)."""
    cid = candidate.get("candidate_id")
    exposure = candidate.get("exposure_key")
    root = candidate.get("underlying_root")

    roots_book = {r for r in existing_book_roots if r}
    if root and root in roots_book:
        return contract.GATE_FAIL, f"underlying_root {root!r} is already held in the live books"

    for other in other_candidates:
        if other.get("candidate_id") == cid:
            continue
        if exposure and other.get("exposure_key") == exposure:
            return contract.GATE_FAIL, f"shared exposure_key with candidate {other.get('candidate_id')!r}"
        if root and other.get("underlying_root") == root and other.get("admission_state") in contract.PAPER_STATES:
            return contract.GATE_FAIL, (f"shared underlying_root {root!r} with paper-state candidate "
                                       f"{other.get('candidate_id')!r}")
    return contract.GATE_PASS, "no shared exposure_key / underlying_root in a paper state / live book"


def correlation_groups(candidates: Iterable[dict]) -> dict:
    """``economic_driver_key`` -> [candidate_id, …] — shown to the CIO, never a block."""
    out: dict = {}
    for c in candidates:
        driver = c.get("economic_driver_key")
        if not driver:
            continue
        out.setdefault(driver, []).append(c.get("candidate_id"))
    return {k: v for k, v in out.items() if len(v) > 1}

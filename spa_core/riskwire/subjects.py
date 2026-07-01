"""
spa_core/riskwire/subjects.py — the RISKWIRE subject registry (WHAT RiskWire measures).

Enumerates the measurable subjects from the seeds' OWN universes — RISKWIRE invents no universe of its
own, it federates the seeds':
  • POOL subjects           ← DFB's pool universe (`spa_core.dfb.pool_universe.build_universe`).
  • RWA_COLLATERAL subjects  ← the RWA collateral registry (`rwa_backstop.collateral_registry`).
  • BOOK subjects            ← the underwriting book(s) (currently the single desk underwriting report;
                              extensible — add a book id here and the facade routes it).

Each subject gets a STABLE, deterministic `subject_id` = "<kind>::<native id>" so history/detail files
and cross-surface joins reproduce across runs. NO judgment here (mirrors pool_universe.py): no verdict,
no risk math — this only turns the seeds' registries into validated identity rows the facade grades.

stdlib-only · deterministic (sorted output) · READ-ONLY · fail-CLOSED (a malformed registry row is
skipped, never fabricated). Extensible: add a subject source and the facade dispatches on `kind`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import re
from typing import List, Optional

from spa_core.riskwire import Subject, SubjectKind


def _slug(s: str) -> str:
    """Lowercase, collapse any non-[a-z0-9] run to a single '-', strip edges (matches DFB `_slug`)."""
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "na"


def make_subject_id(kind: SubjectKind, native_id: str) -> str:
    """STABLE, DETERMINISTIC subject_id '<kind>::<native id slug>'. Same identity → same id across runs."""
    return f"{kind.value}::{_slug(native_id)}"


# ── the single default book subject (the desk underwriting report). Extensible list. ───────────────
# A "book" is an underwriting subject whose measurement anchor is the underwriting report's head_hash.
# Today there is one desk book; adding another is a one-line append (id + display name) — the facade
# routes every BOOK through underwriting.report.build_report (with an optional per-book path set later).
DEFAULT_BOOK_IDS = ("desk_underwriting",)


def pool_subjects(surface: Optional[dict] = None, *, include_breadth: Optional[bool] = None) -> List[Subject]:
    """The POOL subjects — DFB's followed-pool universe, each wrapped as a Subject carrying the raw Pool
    identity in `native_ref` (so the facade hands the exact Pool to `dfb.risk_overlay.overlay`). Sorted
    by subject_id. READ-ONLY."""
    from spa_core.dfb import pool_universe
    pools = pool_universe.build_universe(surface=surface, include_breadth=include_breadth)
    out: List[Subject] = []
    for pool in pools:
        sid = make_subject_id(SubjectKind.POOL, pool.pool_id)
        out.append(Subject(
            subject_id=sid,
            kind=SubjectKind.POOL,
            display_name=pool.pool_id,
            provenance=f"dfb.pool_universe/{pool.source}",
            native_ref={"pool": pool.to_dict()},   # the raw Pool dict — the facade rebuilds the Pool
        ))
    return sorted(out, key=lambda s: s.subject_id)


def rwa_subjects(assets=None) -> List[Subject]:
    """The RWA_COLLATERAL subjects — the tokenized-RWA collateral registry, each wrapped as a Subject
    carrying its symbol. Sorted by subject_id. READ-ONLY (pure config registry)."""
    from spa_core.strategy_lab.rwa_backstop import collateral_registry as reg
    asset_list = list(assets) if assets is not None else reg.registry()
    out: List[Subject] = []
    for a in asset_list:
        sid = make_subject_id(SubjectKind.RWA_COLLATERAL, a.symbol)
        out.append(Subject(
            subject_id=sid,
            kind=SubjectKind.RWA_COLLATERAL,
            display_name=a.symbol,
            provenance=f"rwa_backstop.collateral_registry/{a.issuer}",
            native_ref={"symbol": a.symbol},       # the facade measures this symbol via the safety board
        ))
    return sorted(out, key=lambda s: s.subject_id)


def book_subjects(book_ids=None) -> List[Subject]:
    """The BOOK subjects — the underwriting book(s). Each wraps a book id whose measurement anchor is the
    underwriting report's head_hash. Sorted by subject_id. Extensible (append a book id above)."""
    ids = list(book_ids) if book_ids is not None else list(DEFAULT_BOOK_IDS)
    out: List[Subject] = []
    for bid in ids:
        sid = make_subject_id(SubjectKind.BOOK, bid)
        out.append(Subject(
            subject_id=sid,
            kind=SubjectKind.BOOK,
            display_name=bid,
            provenance="strategy_lab.underwriting.report",
            native_ref={"book_id": bid},
        ))
    return sorted(out, key=lambda s: s.subject_id)


def build_registry(
    *,
    surface: Optional[dict] = None,
    include_breadth: Optional[bool] = None,
    assets=None,
    book_ids=None,
    kinds=None,
) -> List[Subject]:
    """The full RISKWIRE subject registry (pools + RWA collaterals + books), de-duplicated by
    subject_id and SORTED (deterministic — same inputs → byte-identical list). `kinds` optionally
    restricts to a subset of SubjectKind (tests / partial snapshots)."""
    want = set(kinds) if kinds is not None else set(SubjectKind)
    by_id = {}
    if SubjectKind.POOL in want:
        for s in pool_subjects(surface=surface, include_breadth=include_breadth):
            by_id.setdefault(s.subject_id, s)
    if SubjectKind.RWA_COLLATERAL in want:
        for s in rwa_subjects(assets=assets):
            by_id.setdefault(s.subject_id, s)
    if SubjectKind.BOOK in want:
        for s in book_subjects(book_ids=book_ids):
            by_id.setdefault(s.subject_id, s)
    return [by_id[k] for k in sorted(by_id.keys())]


def main() -> int:
    reg = build_registry()
    by_kind = {}
    for s in reg:
        by_kind.setdefault(s.kind.value, 0)
        by_kind[s.kind.value] += 1
    print(f"RISKWIRE subject registry — {len(reg)} subjects (deterministic, sorted)")
    for k in sorted(by_kind):
        print(f"  {k:16s} {by_kind[k]}")
    for s in reg:
        print(f"  {s.subject_id:44s} {s.provenance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Global Capacity Coordinator — aggregate exposure across the three independent
paper-trading books (SPA CIO oversight, phase A,
docs/ideas/2026-08-29-cio-oversight-layer.md).

The gap this closes: each book (Conservative/Balanced/Aggressive) checks only ITS
OWN proposed position against a pool's capacity limit before entering. If all three
independently decide to enter the same protocol, each passes on its own (its share
is small), but the three together could occupy an unsafe share of the pool's real
liquidity — nothing summed that before. Books remain fully independent: this module
does not blend risk, mandate, or capital between them, it only sums for the check.

Owner decisions (2026-08-30, both interactive):
  * warn-only, never blocks a book's trade — the sum is surfaced (CIO Brief), the
    decision stays with each book;
  * reuses the EXISTING capacity threshold (spa_core.risk.capacity_limits'
    MAX_CAPACITY_PCT / effective_max_pct) — no new number, no new ADR.

Read-only, pure reporting: this module never mutates a position and is never on
the money path. Fail-open by construction (matches
spa_core.paper_trading.cio_brief/spa_core.alerts.daily_report's contract): a bug
here must degrade to a safe, empty-but-honest result, never break the caller.

LLM forbidden. Pure stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

from spa_core.risk.capacity_limits import MAX_CAPACITY_PCT, build_tvl_map, check_all_capacities

log = logging.getLogger("spa.risk.capacity_coordinator")

# Each book's own position file — different schema per book (see the two readers
# below). Conservative writes a flat {protocol: usd} dict; Balanced/Aggressive
# write a list of per-leg dicts (a book can hold one protocol via more than one leg).
_BOOK_FILES = (
    ("conservative", "current_positions.json"),
    ("balanced", "hy_paper_trading.json"),
    ("aggressive", "lp_paper_trading.json"),
)
_TVL_FILENAME = "adapter_orchestrator_status.json"


def _canonical_protocol_key(name: str) -> str:
    """Collapses separator-style spelling variance ONLY (``aave_v3_arbitrum`` ==
    ``aave-v3-arbitrum`` == ``AAVE_V3_ARBITRUM``) — a formatting inconsistency
    confirmed live in ``data/apy_ranking.json`` (hyphen/underscore duplicates for
    the same protocol). Does NOT alias semantically distinct protocols: e.g.
    ``morpho_blue`` and ``morpho_steakhouse`` stay separate keys — different
    vaults with different risk, a real identity, not a spelling accident (the
    same distinction ``spa_core.analytics._apy_series`` already documents and
    deliberately does not merge). Getting this canonicalization wrong in the
    permissive direction would silently UNDER-count aggregate exposure — exactly
    the blind spot this coordinator exists to close — so it stays this narrow
    on purpose rather than growing into a guessed alias table.
    """
    return str(name).strip().lower().replace("-", "_")


def _positions_from_dict_file(doc: dict) -> Dict[str, float]:
    """Conservative shape: ``{"positions": {protocol: usd}}``."""
    positions = doc.get("positions") if isinstance(doc, dict) else None
    if not isinstance(positions, dict):
        return {}
    out: Dict[str, float] = {}
    for proto, usd in positions.items():
        try:
            amount = float(usd or 0.0)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            out[str(proto)] = amount
    return out


def _positions_from_list_file(doc: dict) -> Dict[str, float]:
    """Balanced/Aggressive shape: ``{"positions": [{"protocol": ..., "notional_usd":
    ...}, ...]}``. Multiple legs of the same protocol in one book are summed."""
    positions = doc.get("positions") if isinstance(doc, dict) else None
    if not isinstance(positions, list):
        return {}
    out: Dict[str, float] = {}
    for leg in positions:
        if not isinstance(leg, dict):
            continue
        proto = leg.get("protocol")
        if not proto:
            continue
        try:
            amount = float(leg.get("notional_usd") or 0.0)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            out[str(proto)] = out.get(str(proto), 0.0) + amount
    return out


def aggregate_book_positions(books: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    """Sums {protocol: usd} held across books. Pure — no I/O.

    ``books``: {book_name: {protocol: usd}}, already read/normalized per book
    (see the two readers above for how each book's raw file shape gets here).
    """
    total: Dict[str, float] = {}
    for book_positions in books.values():
        for proto, usd in (book_positions or {}).items():
            key = _canonical_protocol_key(proto)
            total[key] = total.get(key, 0.0) + float(usd or 0.0)
    return total


def check_aggregate_capacity(
    books: Dict[str, Dict[str, float]],
    tvl_map: Dict[str, float],
    max_pct: float = MAX_CAPACITY_PCT,
) -> dict:
    """Warn-only aggregate capacity check. Pure — no I/O.

    Reuses :func:`spa_core.risk.capacity_limits.check_all_capacities` unchanged —
    the only new work this module does is summing proposals across books BEFORE
    that existing, already-tested check runs on the total.
    """
    aggregated = aggregate_book_positions(books)
    canon_tvl = {_canonical_protocol_key(k): v for k, v in (tvl_map or {}).items()}
    result = check_all_capacities(aggregated, canon_tvl, max_pct)
    result["aggregated_positions"] = aggregated
    result["books_included"] = sorted(books.keys())
    return result


def read_books_capacity_check(data_dir: Path, max_pct: float = MAX_CAPACITY_PCT) -> dict:
    """The one public read-I/O entrypoint: reads all three books' position files +
    the shared TVL snapshot, and returns the aggregate warn-only check.

    Never raises — a coordinator bug must not break the caller. A missing or
    unreadable book file contributes nothing (not fabricated, not zero-filled);
    ``books_included`` names exactly which books were actually read.
    """
    try:
        books: Dict[str, Dict[str, float]] = {}
        readers = {
            "current_positions.json": _positions_from_dict_file,
            "hy_paper_trading.json": _positions_from_list_file,
            "lp_paper_trading.json": _positions_from_list_file,
        }
        for name, fname in _BOOK_FILES:
            p = Path(data_dir) / fname
            if not p.exists():
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.warning("capacity_coordinator: %s unreadable (%s)", fname, exc)
                continue
            positions = readers[fname](doc)
            if positions:
                books[name] = positions

        tvl_map: Dict[str, float] = {}
        orch_path = Path(data_dir) / _TVL_FILENAME
        if orch_path.exists():
            try:
                orch_doc = json.loads(orch_path.read_text(encoding="utf-8"))
                tvl_map = build_tvl_map(orch_doc)
            except (OSError, ValueError) as exc:
                log.warning("capacity_coordinator: %s unreadable (%s)", _TVL_FILENAME, exc)

        return check_aggregate_capacity(books, tvl_map, max_pct)
    except Exception as exc:  # noqa: BLE001 — reporting layer never breaks the caller
        log.warning("capacity_coordinator: read_books_capacity_check failed (%s)", exc)
        return {
            "ok": True, "violations": [], "warnings": ["coordinator_unavailable"],
            "results": {}, "aggregated_positions": {}, "books_included": [],
        }

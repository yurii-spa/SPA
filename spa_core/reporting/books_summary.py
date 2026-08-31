"""Three-book NAV summary for the owner's daily digest (CIO oversight, phase B→report).

The owner asked (2026-08-31): the daily Telegram report must show ALL THREE paper
books (Conservative/Balanced/Aggressive) and the combined picture — not just the
Conservative book it always reported.

Mirrors the per-book parsing the dashboard endpoint already does
(``spa_core/api/routers/live.py::live_books`` — ``_book_from_equity_curve`` /
``_book_from_seed_equity`` / ``_combine_books``). Deliberately a SEPARATE
stdlib-only copy rather than an import: the reporting path runs inside the daily
cycle, where the runtime is stdlib-only by invariant #4 — importing the FastAPI
router would drag fastapi into the cycle. The two copies are pinned to each
other by ``spa_core/tests/test_daily_report_books.py`` (same fixture, same
expected numbers), so drift between them fails a test instead of hiding.

Fail-closed per book: a missing/corrupt/zero-seed book reports
``available: False`` with a named reason — never a fabricated number, and never
silently dropped from the combined sum (``books_available`` says how partial
the total is).

LLM forbidden. Pure stdlib. Read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("spa.reporting.books_summary")


def _annualized_pct(return_pct: Optional[float], num_days: Optional[int]) -> Optional[float]:
    if not isinstance(return_pct, (int, float)) or not isinstance(num_days, int) or num_days <= 0:
        return None
    return round(float(return_pct) * 365.0 / num_days, 4)


def _book_from_equity_curve(label: str, doc: Any) -> dict:
    """Conservative shape: equity_curve_daily.json's own ``summary`` block."""
    summary = doc.get("summary") if isinstance(doc, dict) else None
    if not isinstance(summary, dict):
        return {"label": label, "available": False, "reason": "no_summary"}
    return_pct = summary.get("total_return_pct")
    return {
        "label": label,
        "available": True,
        "seed_equity": summary.get("start_equity"),
        "equity": summary.get("end_equity"),
        "return_pct": return_pct,
        "annualized_apy_pct": _annualized_pct(return_pct, summary.get("num_days")),
    }


def _book_from_seed_equity(label: str, doc: Any) -> dict:
    """Balanced/Aggressive shape: ``seed_equity`` + ``equity`` + ``start_date``."""
    if not isinstance(doc, dict):
        return {"label": label, "available": False, "reason": "bad_shape"}
    seed = doc.get("seed_equity")
    equity = doc.get("equity")
    return_pct = (
        round((equity / seed - 1.0) * 100.0, 4)
        if isinstance(seed, (int, float)) and seed and isinstance(equity, (int, float))
        else None
    )
    num_days = None
    start_date = doc.get("start_date")
    if isinstance(start_date, str):
        try:
            start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            num_days = max((datetime.now(timezone.utc) - start).days, 1)
        except ValueError:
            num_days = None
    return {
        "label": label,
        "available": True,
        "seed_equity": seed,
        "equity": equity,
        "return_pct": return_pct,
        "annualized_apy_pct": _annualized_pct(return_pct, num_days),
    }


def _combine_books(books: Dict[str, dict]) -> dict:
    """Dollar sum across books with numeric seed+equity. A missing/unreadable
    book is EXCLUDED, never treated as zero — ``books_available`` names how
    partial the total is."""
    usable = [
        b for b in books.values()
        if b.get("available")
        and isinstance(b.get("seed_equity"), (int, float)) and b.get("seed_equity")
        and isinstance(b.get("equity"), (int, float))
    ]
    total_seed = sum(b["seed_equity"] for b in usable)
    total_equity = sum(b["equity"] for b in usable)
    return {
        "total_seed_usd": round(total_seed, 2) if usable else None,
        "total_equity_usd": round(total_equity, 2) if usable else None,
        "combined_return_pct": (
            round((total_equity / total_seed - 1.0) * 100.0, 4) if total_seed else None
        ),
        "books_available": len(usable),
        "books_total": len(books),
    }


def collect_books_summary(data_dir: Path) -> dict:
    """{books: {conservative|balanced|aggressive}, combined: {...}} — never raises."""
    try:
        ddir = Path(data_dir)
        sources = [
            ("conservative", "Conservative", "equity_curve_daily.json", _book_from_equity_curve),
            ("balanced", "Balanced", "hy_paper_trading.json", _book_from_seed_equity),
            ("aggressive", "Aggressive", "lp_paper_trading.json", _book_from_seed_equity),
        ]
        books: Dict[str, dict] = {}
        for key, label, fname, parser in sources:
            p = ddir / fname
            if not p.exists():
                books[key] = {"label": label, "available": False, "reason": "file_missing"}
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                books[key] = {"label": label, "available": False, "reason": str(exc)}
                continue
            books[key] = parser(label, doc)
        return {"books": books, "combined": _combine_books(books)}
    except Exception as exc:  # noqa: BLE001 — reporting must never break the cycle
        log.warning("books_summary failed (%s) — degraded", exc)
        return {"books": {}, "combined": {"books_available": 0, "books_total": 0,
                                          "total_seed_usd": None, "total_equity_usd": None,
                                          "combined_return_pct": None}}

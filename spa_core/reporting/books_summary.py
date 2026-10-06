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

RM-TRUTH-01 W5 (ADR-580 C2) — the annualized-rate fix.
    RM-TRUTH-01's audit (``docs/rm_truth/A3_product.md`` §2, D1) found this module
    the LIVE, still-public source of the "higher-risk package shows a LOWER
    realized %" inversion: it annualised LINEARLY over the book's whole life,
    including the 39 ``sleeve-econ-v1`` days the cost-model defect distorted
    (ADR-530 P0-1 / ADR-531), with no maturity gate at all. The site itself
    stopped showing this shape on 2026-10-01 (ADR-531/1a2d79252); this module —
    feeding ``/api/live/books``, ``/admin/portfolio-summary`` and the Telegram
    daily "📚 Пакеты" block — did not. Fixed here by reusing the SAME v2-only /
    current-experiment / maturity-gated view the site already publishes
    (``spa_core.paper_trading.sleeve_track.sleeve_track_view``, ADR-531/533) for
    Balanced/Aggressive, and the SAME compound/evidenced-bars formula
    (``spa_core.reporting.compound_apy``) for Conservative. Below the 30-valid-day
    maturity gate (``spa_core.defi_engine.package_status.REPORTABLE_AFTER``) the
    rate is ``None`` and ``status`` reads ``accumulating`` — never an invented or
    short-window-distorted number (invariant #17). Each rate also carries a C2
    typed envelope (metric_type/window_days/annualisation/as_of/source/reportable).

LLM forbidden. Pure stdlib. Read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from spa_core.defi_engine.package_status import REPORTABLE_AFTER
from spa_core.paper_trading.sleeve_track import sleeve_track_view
from spa_core.reporting.compound_apy import compound_annualized_pct, evidenced_bars
from spa_core.reporting.typed_numbers import typed_pct

log = logging.getLogger("spa.reporting.books_summary")

#: Below this many valid (v2, current-experiment, positions>0) days the rate is not
#: a number yet — the SAME maturity line ``spa_core.defi_engine.package_status``
#: already draws for the site's package cards (ADR-533/537). Importing the constant
#: (not retyping ``30``) is the point: one maturity line, not two that can drift.
_MATURITY_DAYS = REPORTABLE_AFTER


def _typed_rate(
    value: Optional[float], *, window_days: Optional[int], as_of: Optional[str],
    source: str, reportable: bool,
) -> dict:
    """``typed_pct`` wrapper fixing the fields every book's rate shares."""
    return typed_pct(
        value, metric_type="REALIZED_PAPER", window_days=window_days,
        annualisation="compound", as_of=as_of, source=source,
        reportable=reportable, reportable_after=_MATURITY_DAYS,
    )


def _book_from_equity_curve(label: str, doc: Any) -> dict:
    """Conservative shape: equity_curve_daily.json's own bars, compound-annualised
    over EVIDENCED days only — the SAME method the public ``paper_apy_pct`` hero
    uses (``spa_core.reporting.compound_apy``), not the linear
    ``summary.total_return_pct / summary.num_days`` this used to read (that window
    can include pre-anchor warmup/backfill bars, not just evidenced ones).

    Conservative is the main go-live track, not a sleeve experiment — it carries
    no ``_MATURITY_DAYS`` (30-valid-day) gate of its own (that gate is
    ``package_status``'s rule for a sleeve's CURRENT experiment, ADR-533/537).
    The SAME ``len(evidenced) >= 2`` bar the public site snapshot already uses
    (``scripts/generate_track_snapshot.py::build_snapshot``) is the only gate —
    reusing a stricter one here would be a NEW, undiscussed rule, not a repair.
    """
    summary = doc.get("summary") if isinstance(doc, dict) else None
    if not isinstance(summary, dict):
        return {"label": label, "available": False, "reason": "no_summary"}
    ev = evidenced_bars(doc)
    real_days = len(ev) if ev else None
    apy = None
    as_of = None
    if ev and isinstance(real_days, int) and real_days >= 2:
        apy = compound_annualized_pct(ev[0].get("equity"), ev[-1].get("equity"), real_days)
        as_of = ev[-1].get("date")
    rate = _typed_rate(
        round(apy, 4) if apy is not None else None,
        window_days=real_days, as_of=as_of,
        source="data/equity_curve_daily.json (evidenced bars, compound)",
        reportable=apy is not None,
    )
    return_pct = summary.get("total_return_pct")
    return {
        "label": label,
        "available": True,
        "seed_equity": summary.get("start_equity"),
        "equity": summary.get("end_equity"),
        "return_pct": return_pct,
        "annualized_apy_pct": rate["value"],
        "annualized_apy_pct_rate": rate,
        "status": "paper_test_running" if real_days else "not_started",
    }


def _book_from_seed_equity(label: str, doc: Any) -> dict:
    """Balanced/Aggressive shape: ``seed_equity`` + ``equity`` + sleeve ``daily_history``.

    NAV/return come from the book's own top-level ``seed_equity``/``equity`` (real
    regardless of maturity — the book has a real NAV from day one). The ANNUALIZED
    RATE is the maturity-gated v2/current-experiment view
    (``spa_core.paper_trading.sleeve_track.sleeve_track_view``, ADR-531/533): below
    ``_MATURITY_DAYS`` valid days it is ``None`` and ``status`` reads
    ``accumulating`` — never the old linear/whole-life number this used to print.
    """
    if not isinstance(doc, dict):
        return {"label": label, "available": False, "reason": "bad_shape"}
    seed = doc.get("seed_equity")
    equity = doc.get("equity")
    return_pct = (
        round((equity / seed - 1.0) * 100.0, 4)
        if isinstance(seed, (int, float)) and seed and isinstance(equity, (int, float))
        else None
    )
    view = sleeve_track_view(doc, label.lower())
    n = view.get("days_with_positions") or 0
    mature = n >= _MATURITY_DAYS
    apy = view.get("apy_pct") if mature else None
    as_of = None
    history = doc.get("daily_history")
    if isinstance(history, list) and history and isinstance(history[-1], dict):
        as_of = history[-1].get("date")
    rate = _typed_rate(
        apy, window_days=n or None, as_of=as_of,
        source=f"sleeve_track_view({view.get('economics_model')}, experiment "
               f"{view.get('experiment_id')!r}, current only)",
        reportable=mature,
    )
    status = (view.get("status") if mature or view.get("status") != "paper_test_running"
              else "accumulating")
    return {
        "label": label,
        "available": True,
        "seed_equity": seed,
        "equity": equity,
        "return_pct": return_pct,
        "annualized_apy_pct": rate["value"],
        "annualized_apy_pct_rate": rate,
        "status": status,
        "days_with_positions": n,
        "maturity_days": _MATURITY_DAYS,
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


def collect_books_summary(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """{books: {conservative|balanced|aggressive}, combined: {...}} — never raises.

    ``now`` is accepted for signature parity with the old per-book clock dependency
    (deployment.md "time is an input") and is currently unused: maturity is counted
    in VALID DAYS (rows), not wall-clock age, exactly like the site's own package
    cards (``spa_core.defi_engine.package_status``)."""
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

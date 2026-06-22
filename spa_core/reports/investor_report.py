"""
Investor-grade report builder + decision audit-trail export (SPA-V393).

Assembles a single read-only "investor report" that an allocator/LP would want:

  (a) PnL attribution by protocol + portfolio roll-up
      (``spa_core.reports.pnl_attribution``).
  (b) A risk-grade table per protocol (slug, numeric score, A/B/C/D grade)
      from ``spa_core.risk.scoring_engine.RiskScoringEngine`` run **offline**
      (bootstrap data, no network). If the engine still fails for any reason we
      degrade to an empty grade table rather than raising.
  (c) The recent decision audit trail from
      ``spa_core.agents.decision_logger.DecisionLogger.get_recent(limit=...)``
      (an empty list when the log / DB is absent — get_recent is itself
      try/except guarded).

The report is written atomically (tmpfile + ``os.replace``) to
``data/investor_report.json``. A PDF is rendered *opportunistically*: only if
``reportlab`` is importable AND ``spa_core/reports/pdf_generator.py`` exposes
``generate_report(data, output_path)``. PDF is never required for success.

Safety:
  * Pure stdlib at the top level (json, os, logging, argparse, datetime,
    pathlib). ``reportlab`` is imported lazily and optionally; its absence is a
    no-op, never an error.
  * STRICTLY READ-ONLY. No execution / risk-policy / wallet / money code is
    touched. The scoring engine is invoked in offline bootstrap mode so the
    report never depends on the network.
  * Every stage is wrapped so a single broken source produces an empty section,
    not a crash.

CLI::

    python -m spa_core.reports.investor_report
    python -m spa_core.reports.investor_report --output data/investor_report.json \\
        --limit 50 --no-pdf
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.reports.pnl_attribution import compute_pnl_attribution
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.reports.investor_report")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "investor_report.json"
DEFAULT_AUDIT_LIMIT = 50

REPORT_SOURCE = "spa.reports.investor_report"


# ─── Risk-grade table (offline) ────────────────────────────────────────────────

def build_risk_grade_table(slugs: list[str] | None = None) -> list[dict]:
    """Per-protocol risk grades from the scoring engine, run offline/bootstrap.

    Returns ``[{slug, protocol, score, grade}, ...]``. On any import/runtime
    failure (or a scoring engine that tries to reach the network and dies)
    we degrade to an empty list — never raising.
    """
    try:
        from spa_core.risk.scoring_engine import (
            RiskScoringEngine,
            grade_for_score,
        )
    except Exception as exc:  # noqa: BLE001 — engine import is best-effort
        log.warning("scoring engine unavailable, empty grade table: %s", exc)
        return []

    try:
        # offline=True forces BOOTSTRAP_PROTOCOLS — no network access.
        engine = RiskScoringEngine(offline=True)
    except TypeError:
        # Older/newer signature without an ``offline`` kwarg — fall back to
        # the default constructor and rely on its own network guards.
        try:
            engine = RiskScoringEngine()
        except Exception as exc:  # noqa: BLE001
            log.warning("could not construct RiskScoringEngine: %s", exc)
            return []
    except Exception as exc:  # noqa: BLE001
        log.warning("could not construct RiskScoringEngine: %s", exc)
        return []

    table: list[dict] = []
    try:
        scores = engine.compute_all(slugs=slugs)
    except Exception as exc:  # noqa: BLE001 — never let scoring crash the report
        log.warning("scoring engine compute_all failed: %s", exc)
        return []

    for s in scores or []:
        try:
            d = s.to_dict()
        except Exception:  # noqa: BLE001
            continue
        score_val = d.get("score_numeric")
        # Prefer the engine's own grade; recompute via grade_for_score as a
        # cross-check / fallback when the grade field is missing.
        grade = d.get("grade")
        if grade is None and score_val is not None:
            try:
                grade = grade_for_score(float(score_val))
            except Exception:  # noqa: BLE001
                grade = None
        table.append({
            "slug":     d.get("slug"),
            "protocol": d.get("protocol"),
            "score":    score_val,
            "grade":    grade,
        })
    return table


# ─── Audit trail ───────────────────────────────────────────────────────────────

def build_audit_trail(limit: int = DEFAULT_AUDIT_LIMIT, db_path: str | Path | None = None) -> list[dict]:
    """Recent decision records via DecisionLogger.get_recent (empty if absent).

    ``DecisionLogger.get_recent`` is already try/except guarded and returns an
    empty list when the SQLite log is missing — we add one more guard here so an
    import-time failure (e.g. missing DB layer) also degrades to an empty trail.
    """
    try:
        from spa_core.agents.decision_logger import DecisionLogger
    except Exception as exc:  # noqa: BLE001
        log.warning("DecisionLogger unavailable, empty audit trail: %s", exc)
        return []
    try:
        logger = DecisionLogger(db_path=db_path) if db_path is not None else DecisionLogger()
        recent = logger.get_recent(limit=int(limit))
        return recent if isinstance(recent, list) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("get_recent failed, empty audit trail: %s", exc)
        return []


# ─── Report assembly ───────────────────────────────────────────────────────────

def build_investor_report(
    limit: int = DEFAULT_AUDIT_LIMIT,
    portfolio_path: str | Path | None = None,
    pnl_history_path: str | Path | None = None,
    equity_curve_path: str | Path | None = None,
    grade_slugs: list[str] | None = None,
    audit_db_path: str | Path | None = None,
) -> dict:
    """Assemble the full investor report dict (does not write anything).

    Each section is computed independently and guarded so a single broken source
    yields an empty section instead of a crash. The returned schema is stable.

    Returns a dict with::

        {generated_at, report_date, source,
         attribution: {protocols, roll_up},
         risk_grades: [...], audit_trail: [...],
         counts: {protocols, risk_grades, audit_records}}
    """
    now = datetime.now(timezone.utc)

    # (a) PnL attribution — pass through only the kwargs the caller overrode so
    # the module defaults (data/*.json) apply otherwise.
    attr_kwargs: dict[str, Any] = {}
    if portfolio_path is not None:
        attr_kwargs["portfolio_path"] = portfolio_path
    if pnl_history_path is not None:
        attr_kwargs["pnl_history_path"] = pnl_history_path
    if equity_curve_path is not None:
        attr_kwargs["equity_curve_path"] = equity_curve_path
    try:
        attribution = compute_pnl_attribution(**attr_kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("attribution failed, empty section: %s", exc)
        attribution = {"protocols": [], "roll_up": {}}

    # (b) Risk-grade table (offline).
    risk_grades = build_risk_grade_table(slugs=grade_slugs)

    # (c) Decision audit trail.
    audit_trail = build_audit_trail(limit=limit, db_path=audit_db_path)

    return {
        "generated_at": now.isoformat(),
        "report_date":  now.date().isoformat(),
        "source":       REPORT_SOURCE,
        "attribution":  attribution,
        "risk_grades":  risk_grades,
        "audit_trail":  audit_trail,
        "counts": {
            "protocols":     len(attribution.get("protocols", []) or []),
            "risk_grades":   len(risk_grades),
            "audit_records": len(audit_trail),
        },
    }


# ─── Atomic write ──────────────────────────────────────────────────────────────

def _atomic_write_json(data: dict, path: str | Path) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(data, str(path))
def _maybe_generate_pdf(report: dict, json_path: str | Path) -> str | None:
    """Render a PDF next to the JSON, only if reportlab + pdf_generator exist.

    Returns the PDF path on success, else ``None``. Never raises.
    """
    try:
        import importlib.util
        if importlib.util.find_spec("reportlab") is None:
            log.info("reportlab not installed — skipping PDF")
            return None
    except Exception:  # noqa: BLE001
        return None

    try:
        from spa_core.reports.pdf_generator import generate_report
    except Exception as exc:  # noqa: BLE001
        log.info("pdf_generator unavailable — skipping PDF: %s", exc)
        return None

    pdf_path = str(Path(json_path).with_suffix(".pdf"))
    try:
        generate_report(report, pdf_path)
        log.info("investor PDF written: %s", pdf_path)
        return pdf_path
    except Exception as exc:  # noqa: BLE001 — PDF is best-effort, never fatal
        log.warning("PDF generation failed (non-fatal): %s", exc)
        return None


# ─── Export ────────────────────────────────────────────────────────────────────

def export_report(
    path: str | Path = DEFAULT_OUTPUT_PATH,
    limit: int = DEFAULT_AUDIT_LIMIT,
    generate_pdf: bool = True,
    **build_kwargs: Any,
) -> dict:
    """Build the investor report, write it atomically, and optionally render PDF.

    Args:
        path: output JSON path (default ``data/investor_report.json``).
        limit: max audit-trail records.
        generate_pdf: attempt the optional PDF (skipped if deps missing).
        **build_kwargs: forwarded to :func:`build_investor_report`.

    Returns:
        The report dict (with a ``pdf_path`` key when a PDF was produced).
    """
    report = build_investor_report(limit=limit, **build_kwargs)
    try:
        _atomic_write_json(report, path)
        log.info(
            "investor report written: %s (%d protocols, %d grades, %d audit)",
            path, report["counts"]["protocols"],
            report["counts"]["risk_grades"], report["counts"]["audit_records"],
        )
    except OSError as exc:
        log.error("could not write investor report to %s: %s", path, exc)

    if generate_pdf:
        pdf_path = _maybe_generate_pdf(report, path)
        if pdf_path:
            report["pdf_path"] = pdf_path
    return report


# ─── CLI ───────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build the investor-grade report (PnL attribution + risk "
                    "grades + decision audit trail) and write it atomically.",
    )
    p.add_argument(
        "--output", default=str(DEFAULT_OUTPUT_PATH),
        help="output JSON path (default: data/investor_report.json)",
    )
    p.add_argument(
        "--limit", type=int, default=DEFAULT_AUDIT_LIMIT,
        help=f"max audit-trail records (default: {DEFAULT_AUDIT_LIMIT})",
    )
    p.add_argument(
        "--no-pdf", action="store_true",
        help="never attempt the optional PDF render",
    )
    return p


def _cli(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = export_report(
        path=args.output,
        limit=args.limit,
        generate_pdf=not args.no_pdf,
    )
    counts = report.get("counts", {})
    roll = report.get("attribution", {}).get("roll_up", {})
    print(json.dumps({
        "output":          args.output,
        "report_date":     report.get("report_date"),
        "protocols":       counts.get("protocols"),
        "risk_grades":     counts.get("risk_grades"),
        "audit_records":   counts.get("audit_records"),
        "total_capital_usd": roll.get("total_capital_usd"),
        "total_pnl_pct":   roll.get("total_pnl_pct"),
        "current_apy":     roll.get("current_apy"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

#!/usr/bin/env python3
"""Portfolio Analytics Roll-Up & Investor-DD Scorecard (SPA-V444 / MP-122) — read-only / advisory.

Consolidates the family of ~15 read-only/advisory analytics artifacts already
produced under ``data/`` (drawdown_analytics, concentration_analytics,
yield_attribution, risk_contribution, tail_risk, correlation_analytics,
turnover_analytics, exit_liquidity_status, capacity_analytics,
data_integrity_status, …) into ONE investor-grade due-diligence **scorecard**:
a single consolidated traffic-light (``overall_status``) plus the explicit list
of which sources are warning / failing / stale / demo, and how much of the
analytics surface is actually covered.

Where every individual module answers ONE question and writes ONE
``data/<name>.json`` (each with its own heterogeneous schema, but a shared
vocabulary of ``available`` / ``verdict`` ∈ {ok,warn,fail} / ``is_demo`` /
``meta.generated_at``), this module answers the cross-cutting investor question
*"taken together, what is the portfolio's analytics health, and what should a
diligent allocator look at first?"*.

ZERO duplicated mathematics
===========================
This module performs **no** portfolio math. It only READS the existing
artifacts and re-projects their already-computed ``verdict`` / ``available`` /
``is_demo`` / ``generated_at`` fields into a compact per-source summary plus
headline counts. The source-of-truth for each verdict remains the module that
produced it.

Source registry
===============
A fixed registry of ten DD-relevant sources (key, filename, human title,
category). :func:`extract_source_summary` is a pure, schema-tolerant projector:
it reads ``available`` / ``verdict`` / ``is_demo`` / ``generated_at`` from an
arbitrary loaded doc (which may be ``None``, a non-dict, an empty dict, or
garbage) and NEVER raises. Verdicts are normalised to one of
{``ok``, ``warn``, ``fail``, ``None``}; unknown verdict strings collapse to
``None`` with a note. A source whose ``generated_at`` is older than
:data:`STALE_HOURS` (48h) relative to ``now`` is flagged ``stale`` (an
unparsable timestamp → ``stale: None``, never an exception).

Roll-up logic (:func:`build_scorecard`)
=======================================
Per-source summaries are aggregated into headline ``counts`` (ok / warn / fail /
unknown_verdict / unavailable / total_sources) and the lists ``fails`` /
``warns`` / ``stale_sources`` / ``demo_sources``. ``coverage_pct`` is the share
of registry sources that are ``available``. The consolidated traffic-light:

* **fail**  — any source has ``verdict == "fail"``;
* **warn**  — else if any ``warn`` OR any stale OR any demo OR coverage < 60%;
* **ok**    — else if ≥1 available source carries a real verdict;
* **unknown** — nothing useful was read at all.

``overall_reason`` is a short human-readable justification mentioning the
fail / warn / stale counts.

Output / persistence
====================
:func:`build_scorecard` returns a stable-schema dict and NEVER raises (missing /
broken / empty / garbage inputs → that source is marked unavailable; a fully
empty ``data/`` → ``available: false`` + ``overall_status: "unknown"``).
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/analytics_scorecard.json`` with an in-file ``history`` of runs (rotation
≤ :data:`HISTORY_MAX`). Idempotency: the :func:`content_fingerprint` from
:mod:`spa_core.reporting.tear_sheet` is **reused by import** (single source of
truth — zero duplicated fingerprint logic) and excludes the volatile
``meta.generated_at`` / ``history``, so a repeated ``--run`` on unchanged inputs
is byte-identical and does not grow history.

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.analytics_scorecard --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.analytics_scorecard --run     # + atomic write
    python3 -m spa_core.paper_trading.analytics_scorecard --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/sys/math/datetime/argparse/tempfile/logging/pathlib/typing) — no
requests/web3/urllib/socket/http/LLM SDK/pandas/numpy/network. It only READS
sibling status artifacts and writes its OWN scorecard; it never moves capital
and never touches risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# REUSE BY IMPORT — single source of truth for the idempotency fingerprint
# (MP-501). We do NOT reimplement the content_fingerprint logic here.
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.analytics_scorecard")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "analytics_scorecard"
STATUS_FILENAME = "analytics_scorecard.json"
HISTORY_MAX = 500  # run-history rotation (pattern: tear_sheet / turnover_analytics)
STALE_HOURS = 48   # generated_at older than this → source flagged stale
COVERAGE_WARN_PCT = 60.0  # coverage below this contributes a warn

# Real (honest) track start — convention shared with index.html / portal_data.
REAL_TRACK_START = "2026-06-10"
DISCLAIMER = "NOT investment advice"

# Fixed registry of due-diligence-relevant analytics sources.
# (key, filename, human title, category)
SOURCE_REGISTRY: List[Tuple[str, str, str, str]] = [
    ("drawdown",       "drawdown_analytics.json",      "Drawdown & Underwater",       "risk"),
    ("concentration",  "concentration_analytics.json", "Capital Concentration (HHI)", "risk"),
    ("yield_attr",     "yield_attribution.json",       "Yield Attribution",           "return"),
    ("risk_contrib",   "risk_contribution.json",       "Risk Contribution",           "risk"),
    ("tail_risk",      "tail_risk.json",               "Tail Risk (VaR/CVaR)",        "risk"),
    ("correlation",    "correlation_analytics.json",   "Protocol Correlation",        "risk"),
    ("turnover",       "turnover_analytics.json",      "Turnover & Rebalancing",      "cost"),
    ("exit_liquidity", "exit_liquidity_status.json",   "Exit Liquidity Ladder",       "liquidity"),
    ("capacity",       "capacity_analytics.json",      "Capacity / Scalability",      "scalability"),
    ("data_integrity", "data_integrity_status.json",   "Data Integrity Sentinel",     "ops"),
]

_VALID_VERDICTS = ("ok", "warn", "fail")


# ─── Tolerant IO / coercion helpers (pattern: turnover_analytics / tear_sheet) ─


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _num(value: Any) -> Optional[float]:
    """Finite float or None (bool is not a number; NaN/inf are not data)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _round(value: Optional[float], ndigits: int = 2) -> Optional[float]:
    return None if value is None else round(value, ndigits)


def _parse_iso(value: Any) -> Optional[datetime]:
    """Tolerant ISO-8601 parse → aware datetime (UTC) or None. Never raises."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    # Tolerate a trailing 'Z' (UTC designator) that fromisoformat may reject.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        # Last resort: a bare date prefix.
        try:
            dt = datetime.fromisoformat(value[:10])
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ─── Per-source projection (pure, schema-tolerant) ───────────────────────────


def _doc_available(doc: Any) -> bool:
    """Resolve a source's ``available`` flag from an arbitrary doc.

    Explicit boolean ``doc["available"]`` wins; otherwise a non-empty dict with
    meaningful content (any key beyond a bare ``available``) is treated as
    available; anything else (None / non-dict / empty dict) is unavailable.
    """
    if not isinstance(doc, dict):
        return False
    avail = doc.get("available")
    if isinstance(avail, bool):
        return avail
    # No explicit flag: a non-empty dict carrying real content counts.
    meaningful = [k for k in doc.keys() if k != "available"]
    return bool(meaningful)


def _doc_verdict(doc: Any) -> Tuple[Optional[str], bool]:
    """Return (normalised_verdict, had_unknown_string).

    Looks at top-level ``doc["verdict"]``. Normalises to one of
    {ok, warn, fail}; any other (non-empty) string collapses to None with the
    ``had_unknown`` flag set. Missing / non-string → (None, False).
    """
    if not isinstance(doc, dict):
        return None, False
    raw = doc.get("verdict")
    if not isinstance(raw, str):
        return None, False
    norm = raw.strip().lower()
    if norm in _VALID_VERDICTS:
        return norm, False
    return None, True


def _doc_is_demo(doc: Any) -> Optional[bool]:
    """Resolve ``is_demo`` from ``meta.is_demo`` or top-level ``is_demo``."""
    if not isinstance(doc, dict):
        return None
    meta = doc.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("is_demo"), bool):
        return meta.get("is_demo")
    if isinstance(doc.get("is_demo"), bool):
        return doc.get("is_demo")
    return None


def _doc_generated_at(doc: Any) -> Optional[str]:
    """Resolve ``generated_at`` from ``meta.generated_at`` or top-level."""
    if not isinstance(doc, dict):
        return None
    meta = doc.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("generated_at"), str):
        return meta.get("generated_at")
    if isinstance(doc.get("generated_at"), str):
        return doc.get("generated_at")
    return None


def extract_source_summary(
    key: str,
    title: str,
    category: str,
    doc: Any,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Project an arbitrary loaded source ``doc`` into a compact summary.

    Pure and totally schema-tolerant: ``doc`` may be ``None`` (file missing),
    a non-dict, an empty dict, or garbage. NEVER raises. Returns a dict with
    ``key / title / category / available / verdict / is_demo / generated_at /
    stale`` and an optional ``note`` explaining anomalies (missing file,
    unknown verdict string).
    """
    now = now or datetime.now(timezone.utc)
    note: Optional[str] = None

    if doc is None:
        return {
            "key": key,
            "title": title,
            "category": category,
            "available": False,
            "verdict": None,
            "is_demo": None,
            "generated_at": None,
            "stale": None,
            "note": "missing",
        }

    available = _doc_available(doc)
    verdict, had_unknown = _doc_verdict(doc)
    if had_unknown:
        note = "unknown verdict string normalised to None"
    is_demo = _doc_is_demo(doc)
    generated_at = _doc_generated_at(doc)

    # Staleness: generated_at older than STALE_HOURS. Unparsable → None.
    stale: Optional[bool] = None
    if generated_at is not None:
        dt = _parse_iso(generated_at)
        if dt is None:
            stale = None
        else:
            age_hours = (now - dt).total_seconds() / 3600.0
            stale = age_hours > STALE_HOURS

    summary: Dict[str, Any] = {
        "key": key,
        "title": title,
        "category": category,
        "available": available,
        "verdict": verdict,
        "is_demo": is_demo,
        "generated_at": generated_at,
        "stale": stale,
    }
    if note is not None:
        summary["note"] = note
    return summary


# ─── Aggregate build ─────────────────────────────────────────────────────────


def build_scorecard(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the consolidated investor-DD scorecard. Stable schema, never raises."""
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now = now or datetime.now(timezone.utc)
    notes: List[str] = []

    summaries: List[Dict[str, Any]] = []
    for key, filename, title, category in SOURCE_REGISTRY:
        doc = _read_json(ddir / filename)
        summaries.append(
            extract_source_summary(key, title, category, doc, now=now)
        )

    total = len(summaries)
    n_ok = n_warn = n_fail = n_unknown_verdict = n_unavailable = n_available = 0
    fails: List[str] = []
    warns: List[str] = []
    stale_sources: List[str] = []
    demo_sources: List[str] = []
    any_demo_true = False
    any_demo_false = False
    any_real_verdict = False

    for s in summaries:
        if s["available"]:
            n_available += 1
        else:
            n_unavailable += 1
        verdict = s["verdict"]
        if verdict == "ok":
            n_ok += 1
            any_real_verdict = True
        elif verdict == "warn":
            n_warn += 1
            any_real_verdict = True
            warns.append(s["key"])
        elif verdict == "fail":
            n_fail += 1
            any_real_verdict = True
            fails.append(s["key"])
        else:
            # available source with no usable verdict counts as unknown_verdict
            if s["available"]:
                n_unknown_verdict += 1
        if s["stale"] is True:
            stale_sources.append(s["key"])
        if s["is_demo"] is True:
            demo_sources.append(s["key"])
            any_demo_true = True
        elif s["is_demo"] is False:
            any_demo_false = True

    coverage_pct = (n_available / total * 100.0) if total else 0.0

    counts = {
        "ok": n_ok,
        "warn": n_warn,
        "fail": n_fail,
        "unknown_verdict": n_unknown_verdict,
        "unavailable": n_unavailable,
        "total_sources": total,
    }

    # Consolidated traffic-light. If nothing useful was read at all (no
    # available source) the status is "unknown" — the low-coverage warn only
    # applies when there is at least some analytics surface to assess.
    if n_available == 0:
        overall = "unknown"
    elif n_fail > 0:
        overall = "fail"
    elif (
        n_warn > 0
        or stale_sources
        or any_demo_true
        or coverage_pct < COVERAGE_WARN_PCT
    ):
        overall = "warn"
    elif any_real_verdict:
        overall = "ok"
    else:
        overall = "unknown"

    overall_reason = _overall_reason(
        overall, counts, len(stale_sources), len(demo_sources), coverage_pct
    )

    # Top-level is_demo aggregation.
    if any_demo_true:
        is_demo: Optional[bool] = True
    elif any_demo_false:
        is_demo = False
    else:
        is_demo = None

    if n_available == 0:
        notes.append("no analytics source could be read — empty/missing data")

    meta = {
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "stale_hours": STALE_HOURS,
        "coverage_warn_pct": COVERAGE_WARN_PCT,
        "real_track_start": REAL_TRACK_START,
        "is_demo": is_demo,
        "notes": notes,
    }

    sources = sorted(summaries, key=lambda s: (s["category"], s["key"]))

    return {
        "meta": meta,
        "available": n_available > 0,
        "overall_status": overall,
        "overall_reason": overall_reason,
        "is_demo": is_demo,
        "counts": counts,
        "fails": fails,
        "warns": warns,
        "stale_sources": stale_sources,
        "demo_sources": demo_sources,
        "coverage_pct": _round(coverage_pct),
        "sources": sources,
    }


def _overall_reason(
    overall: str,
    counts: Dict[str, int],
    n_stale: int,
    n_demo: int,
    coverage_pct: float,
) -> str:
    """Short human-readable justification for the consolidated traffic-light."""
    cov = f"{coverage_pct:.0f}%"
    if overall == "fail":
        return (
            f"{counts['fail']} source(s) FAIL, {counts['warn']} warn, "
            f"{n_stale} stale — investor-DD scorecard fails until resolved"
        )
    if overall == "warn":
        bits: List[str] = []
        if counts["warn"]:
            bits.append(f"{counts['warn']} warn")
        if n_stale:
            bits.append(f"{n_stale} stale")
        if n_demo:
            bits.append(f"{n_demo} demo")
        if coverage_pct < COVERAGE_WARN_PCT:
            bits.append(f"coverage {cov} < {COVERAGE_WARN_PCT:.0f}%")
        detail = "; ".join(bits) if bits else "elevated"
        return f"no fails but caution warranted ({detail}); coverage {cov}"
    if overall == "ok":
        return (
            f"all {counts['ok']} verdict-bearing source(s) OK, no warn/fail/stale; "
            f"coverage {cov}"
        )
    return "no analytics source produced a usable verdict — status unknown"


# ─── Persist (idempotent, pattern: turnover_analytics / tear_sheet MP-501) ────
# content_fingerprint is REUSED BY IMPORT from tear_sheet (see module header):
# it excludes volatile meta.generated_at / history, so a repeated --run on
# unchanged inputs is byte-identical and does not grow history.


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record for analytics_scorecard.json."""
    meta = doc.get("meta") or {}
    counts = doc.get("counts") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "overall_status": doc.get("overall_status"),
        "ok": counts.get("ok"),
        "warn": counts.get("warn"),
        "fail": counts.get("fail"),
        "coverage_pct": doc.get("coverage_pct"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/analytics_scorecard.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` (reused from tear_sheet) is
    unchanged relative to the persisted status, the file is NOT rewritten (a
    repeated ``--run`` is byte-identical and history does not grow). On a
    content change a short record is appended to ``history`` (rotation ≤
    :data:`HISTORY_MAX`). A broken/absent existing status file is tolerated as
    fresh.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("analytics scorecard unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("analytics scorecard written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.analytics_scorecard",
        description=(
            "Portfolio Analytics Roll-Up & Investor-DD Scorecard "
            "(SPA-V444 / MP-122): read-only / advisory consolidation of the "
            "existing analytics artifacts into ONE traffic-light scorecard. "
            "Zero duplicated math. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON scorecard WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/analytics_scorecard.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: turnover_analytics.py).
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        doc = build_scorecard(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            counts = doc.get("counts") or {}
            state = "DATA_WRITTEN" if outcome["changed"] else "DATA_UNCHANGED"
            print(
                f"analytics_scorecard: available={doc.get('available')} "
                f"overall={doc.get('overall_status')} "
                f"fails={counts.get('fail')} "
                f"warns={counts.get('warn')} "
                f"coverage={doc.get('coverage_pct')}% — "
                f"{state} {outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"analytics_scorecard: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

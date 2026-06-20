#!/usr/bin/env python3
"""Portfolio Yield Attribution & Yield-Concentration Analyzer (SPA-V436 / MP-117) — read-only / advisory.

Complements the *capital-weight* concentration analyzer (MP-116, which measures
how concentrated the BOOK is via position-weight HHI) by answering the distinct
investor-DD question: **"where does the portfolio's yield actually come from,
and is the yield concentrated in one (possibly risky) source?"**. A book can be
weight-diversified yet have its *yield* dominated by a single high-APY (often
higher-risk) protocol — that is precisely what this module surfaces.

Per protocol it computes the **yield contribution** ``weight_frac * apy_pct``
(its contribution to the portfolio's APY, in percentage points), the share each
source represents of total positive yield, a **yield-source HHI** (concentration
of yield *sources*, not capital), the effective number of yield sources
(``1/HHI``), the top-1 / top-3 yield shares, the portfolio's weighted APY over
the full AUM (incl. cash drag) vs. over the deployed-known book, the visible
cash drag, and an unknown-yield bucket for protocols whose live APY is missing.

Single source of position weights (reuse-by-import)
==================================================
Position weights are NOT recomputed here. We import :func:`build_exposure` from
:mod:`spa_core.reporting.tear_sheet` (MP-501 — single source of truth for the
weight / cash math) and consume its ``by_protocol[p]["share_pct"]`` (a PERCENT,
0..100, of the FULL AUM incl. cash) and ``usd``. We only convert percent→fraction
(÷100) — zero duplicated weight arithmetic. If :func:`build_exposure` reports
``available: false`` or has no ``by_protocol`` we return an honest empty result
+ note.

Live APY source (nothing invented)
==================================
Per-protocol live APY is read from ``data/adapter_orchestrator_status.json``.
Each adapter record carries ``apy_pct`` (float), ``tier`` and ``tvl_usd``. A
protocol that holds weight but is **missing** from the adapters, or whose
``apy_pct`` is ``None`` / non-numeric, is marked ``known: false``, its
contribution is ``null``, and its weight is added to the ``unknown_yield``
bucket + a note — nothing is invented or extrapolated. (We tolerate both the
list-of-records shape actually emitted by the orchestrator *and* a dict keyed
by protocol slug, so the reader is robust to either layout.)

Yield contribution math
========================
For each KNOWN protocol::

    weight_frac          = share_pct / 100              # fraction of full AUM
    yield_contribution_pp = weight_frac * apy_pct       # pp of portfolio APY
    share_of_total_yield  = contribution / sum(positive contributions)

Portfolio-level::

    portfolio_apy_pp = sum(contribution over KNOWN)     # weighted APY of FULL
                                                        # AUM (cash drag incl.)
    deployed_apy_pct = sum(contribution) renormalised over the deployed-known
                       weight (cash drag REMOVED, so the gross deployed yield
                       is visible vs. the cash-diluted portfolio number)
    cash_drag_pp     = deployed_weighted - portfolio_apy_pp   (>= 0; honestly
                       None when not computable)

Yield-source HHI scale
======================
``yield_hhi`` is the concentration of yield SOURCES = ``sum(share_of_total_yield²)``,
reported both as a *fraction* in ``[0, 1]`` and on the standard 0–10000 *index*
scale (fraction × 10000, rounded). ``effective_num_yield_sources = 1/hhi_frac``
(None when the HHI is 0). The DOJ/FTC thresholds used for the yield-concentration
class are the SAME index thresholds as the capital concentration analyzer
(reused by import: :data:`HHI_MODERATE_FLOOR` 1500 / :data:`HHI_CONCENTRATED_FLOOR`
2500): ``< 1500`` diversified, ``1500..2500`` (inclusive) moderate, ``> 2500``
concentrated.

Verdict (advisory only — never blocks anything)
==============================================
* ``fail`` — a single source contributes ``> 60%`` of total yield, OR the yield
  is in the *concentrated* class;
* ``warn`` — *moderate* yield class, OR a significant unknown-yield share
  (``> 25%`` of weight has no live APY);
* ``ok`` — otherwise.

Output / persistence
====================
:func:`build_yield_attribution` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/yield_attribution.json`` with an in-file ``history`` of runs (rotation
≤ :data:`HISTORY_MAX`). Idempotency: a :func:`content_fingerprint` over the
whole doc EXCLUDING the volatile ``meta.generated_at`` / ``history`` means a
repeated ``--run`` on unchanged inputs is byte-identical and does not grow
history (``generated_at`` only changes when content changes).

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.yield_attribution --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.yield_attribution --run     # + atomic write
    python3 -m spa_core.paper_trading.yield_attribution --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/re/typing) — no
requests/web3/LLM SDK/sockets/network. It only READS ``current_positions.json``
and ``adapter_orchestrator_status.json`` (and, for honest ``is_demo``, glances
at ``equity_curve_daily.json``) and writes its OWN status artifact; it never
moves capital and never touches risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re  # noqa: F401  (kept for parity with sibling tolerant-IO modules)
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# REUSE BY IMPORT — single source of truth for the position weight / cash math
# (MP-501). We do NOT recompute weights from raw positions here; we consume
# build_exposure's share_pct (percent of full AUM) and usd directly.
from spa_core.reporting.tear_sheet import build_exposure

# REUSE BY IMPORT — same DOJ/FTC index thresholds as the capital concentration
# analyzer (MP-116), so the yield-concentration class is consistent with the
# weight-concentration class. (Imported, not re-defined.)
from spa_core.paper_trading.concentration_analytics import (
    HHI_CONCENTRATED_FLOOR,
    HHI_MODERATE_FLOOR,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.yield_attribution")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "yield_attribution"
STATUS_FILENAME = "yield_attribution.json"
POSITIONS_FILENAME = "current_positions.json"
ORCHESTRATOR_FILENAME = "adapter_orchestrator_status.json"
EQUITY_FILENAME = "equity_curve_daily.json"
HISTORY_MAX = 500  # run-history rotation (pattern: concentration_analytics / tear_sheet)

# A single yield source contributing strictly more than this FRACTION of total
# yield is a "fail" (one bet drives the whole book's return). Exactly 0.60 is OK.
MAX_SINGLE_YIELD_SHARE = 0.60

# A book with strictly more than this FRACTION of its weight in protocols whose
# live APY is unknown earns a "warn" — too much of the book's yield is unknown.
UNKNOWN_YIELD_WARN_SHARE = 0.25

DISCLAIMER = "NOT investment advice"

SOURCE_FILES = [POSITIONS_FILENAME, ORCHESTRATOR_FILENAME, EQUITY_FILENAME]


# ─── Tolerant IO helpers (pattern: concentration_analytics / tear_sheet) ──────


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


def _classify_yield(yield_hhi_index: Optional[int]) -> Optional[str]:
    """DOJ/FTC concentration class from the yield-source HHI index, or None.

    Uses the SAME thresholds as the capital concentration analyzer (reused by
    import): ``< 1500`` diversified, ``1500..2500`` moderate, ``> 2500``
    concentrated.
    """
    if yield_hhi_index is None:
        return None
    if yield_hhi_index < HHI_MODERATE_FLOOR:
        return "diversified"
    if yield_hhi_index <= HHI_CONCENTRATED_FLOOR:
        return "moderate"
    return "concentrated"


def _build_apy_map(orch_doc: Any) -> Dict[str, Optional[float]]:
    """Map protocol slug → live apy_pct (or None) from the orchestrator status.

    Tolerates BOTH layouts:
      * ``adapters`` is a LIST of records, each with a ``protocol`` slug (the
        shape actually emitted by the adapter orchestrator); and
      * ``adapters`` is a DICT keyed by protocol slug.
    A non-numeric / None ``apy_pct`` is preserved as ``None`` (honest unknown,
    never invented). Broken/missing input → empty map.
    """
    out: Dict[str, Optional[float]] = {}
    if not isinstance(orch_doc, dict):
        return out
    adapters = orch_doc.get("adapters")
    if isinstance(adapters, list):
        for ad in adapters:
            if not isinstance(ad, dict):
                continue
            proto = ad.get("protocol")
            if proto is None:
                continue
            out[str(proto)] = _num(ad.get("apy_pct"))
    elif isinstance(adapters, dict):
        for proto, ad in adapters.items():
            if isinstance(ad, dict):
                out[str(proto)] = _num(ad.get("apy_pct"))
            else:
                out[str(proto)] = None
    return out


def _orch_tvl(orch_doc: Any, proto: str) -> Optional[float]:
    """Live tvl_usd for ``proto`` from the orchestrator status, or None."""
    if not isinstance(orch_doc, dict):
        return None
    adapters = orch_doc.get("adapters")
    if isinstance(adapters, list):
        for ad in adapters:
            if isinstance(ad, dict) and str(ad.get("protocol")) == proto:
                return _num(ad.get("tvl_usd"))
    elif isinstance(adapters, dict):
        ad = adapters.get(proto)
        if isinstance(ad, dict):
            return _num(ad.get("tvl_usd"))
    return None


# ─── Pure computation ─────────────────────────────────────────────────────────


def _empty_result(
    notes: List[str],
    *,
    is_demo: Optional[bool] = None,
    available: bool = False,
) -> Dict[str, Any]:
    """A stable-schema, honest-empty yield-attribution result."""
    return {
        "available": available,
        "advisory_only": True,
        "execution_mode": "read_only",
        "is_demo": is_demo,
        "verdict": "warn",
        "aum_usd": 0.0,
        "deployed_usd": 0.0,
        "cash_share": 0.0,
        "portfolio_apy_pp": 0.0,
        "deployed_apy_pct": None,
        "cash_drag_pp": None,
        "yield_hhi": 0.0,
        "yield_hhi_index": 0,
        "effective_num_yield_sources": None,
        "top1_yield_protocol": None,
        "top1_yield_share": 0.0,
        "top3_yield_share": 0.0,
        "yield_concentration_class": None,
        "total_yield_pp": 0.0,
        "known_yield_weight": 0.0,
        "unknown_yield_share": 0.0,
        "num_yield_sources": 0,
        "num_known": 0,
        "num_unknown": 0,
        "max_single_yield_share": MAX_SINGLE_YIELD_SHARE,
        "unknown_yield_warn_share": UNKNOWN_YIELD_WARN_SHARE,
        "counts": {"sources": 0, "known": 0, "unknown": 0},
        "breakdown": [],
        "source_files": list(SOURCE_FILES),
        "disclaimer": DISCLAIMER,
        "notes": notes,
    }


def build_yield_attribution(
    data_dir: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """Build the portfolio yield-attribution dict. NEVER raises.

    Reads ``current_positions.json`` and ``adapter_orchestrator_status.json``
    from *data_dir* (both tolerant/optional). Calls :func:`build_exposure`
    (single source of weight / cash math) for the per-protocol weights, joins
    the orchestrator's live ``apy_pct`` onto them, and derives per-protocol
    yield contributions, the yield-source HHI, the effective number of yield
    sources, top1/top3 yield shares, the portfolio's full-AUM weighted APY vs.
    the deployed-known APY, the visible cash drag, and an unknown-yield bucket.
    Missing/broken input or an unavailable exposure → honest ``available:
    false`` empty result + note. Nothing is invented.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        positions_doc = _read_json(ddir / POSITIONS_FILENAME)
        orch_doc = _read_json(ddir / ORCHESTRATOR_FILENAME)
        equity_doc = _read_json(ddir / EQUITY_FILENAME)
        notes: List[str] = []

        # is_demo honestly from the source files (positions → equity → orch);
        # null + note if no source declares a bool.
        is_demo: Optional[bool] = None
        for doc in (positions_doc, equity_doc, orch_doc):
            if isinstance(doc, dict) and isinstance(doc.get("is_demo"), bool):
                is_demo = doc["is_demo"]
                break
        if is_demo is None:
            notes.append(
                "is_demo: no source file declares a bool — reported as null"
            )

        if positions_doc is None:
            notes.append(
                f"{POSITIONS_FILENAME}: missing/unreadable — no yield attribution"
            )
            return _empty_result(notes, is_demo=is_demo, available=False)
        if not isinstance(positions_doc, dict):
            notes.append(
                f"{POSITIONS_FILENAME}: unexpected top-level type — no analysis"
            )
            return _empty_result(notes, is_demo=is_demo, available=False)

        if orch_doc is None:
            notes.append(
                f"{ORCHESTRATOR_FILENAME}: missing/unreadable — all live APYs unknown"
            )

        # ── REUSE BY IMPORT: build_exposure is the single source of weights. ───
        exposure = build_exposure(positions_doc, orch_doc)
        if not isinstance(exposure, dict) or not exposure.get("available"):
            notes.append(
                "build_exposure unavailable — empty/broken positions, no analysis"
            )
            return _empty_result(notes, is_demo=is_demo, available=False)

        by_protocol = exposure.get("by_protocol") or {}
        if not isinstance(by_protocol, dict) or not by_protocol:
            notes.append("no deployed protocols in exposure — honest empty result")
            return _empty_result(notes, is_demo=is_demo, available=False)

        aum = _num(exposure.get("capital_usd")) or 0.0
        deployed = _num(exposure.get("deployed_usd")) or 0.0
        cash_pct = _num(exposure.get("cash_pct"))
        cash_share = (cash_pct / 100.0) if cash_pct is not None else 0.0

        apy_map = _build_apy_map(orch_doc)

        # ── Per-protocol join: weight (from build_exposure) × live APY. ────────
        rows: List[Dict[str, Any]] = []
        for proto, info in by_protocol.items():
            if not isinstance(info, dict):
                continue
            share_pct = _num(info.get("share_pct"))
            usd = _num(info.get("usd"))
            if share_pct is None or usd is None:
                notes.append(f"{proto}: missing share/usd in exposure — skipped")
                continue
            weight_frac = share_pct / 100.0  # ÷100 only — no duplicated weight math
            if proto in apy_map and apy_map[proto] is not None:
                apy_pct = apy_map[proto]
                known = True
                contribution = weight_frac * apy_pct
            else:
                apy_pct = None
                known = False
                contribution = None
                if proto not in apy_map:
                    notes.append(
                        f"{proto}: absent from adapters — live APY unknown, "
                        "added to unknown_yield bucket"
                    )
                else:
                    notes.append(
                        f"{proto}: apy_pct missing/non-numeric — live APY unknown, "
                        "added to unknown_yield bucket"
                    )
            rows.append({
                "protocol": str(proto),
                "usd": usd,
                "weight_frac": weight_frac,
                "apy_pct": apy_pct,
                "known": known,
                "tier": info.get("tier", "unknown"),
                "tvl_usd": _orch_tvl(orch_doc, str(proto)),
                "contribution": contribution,
            })

        if not rows:
            notes.append("no usable deployed positions — honest empty result")
            return _empty_result(notes, is_demo=is_demo, available=False)

        known_rows = [r for r in rows if r["known"]]
        unknown_rows = [r for r in rows if not r["known"]]

        # ── Portfolio APY over the FULL AUM (incl. cash drag). ─────────────────
        portfolio_apy_pp = sum(r["contribution"] for r in known_rows)

        # Deployed-known weight & renormalised deployed APY (cash drag removed).
        known_weight = sum(r["weight_frac"] for r in known_rows)
        if known_weight > 0:
            deployed_apy_pct = portfolio_apy_pp / known_weight
            # cash drag = gross deployed-known yield minus the AUM-diluted yield.
            cash_drag_pp = deployed_apy_pct - portfolio_apy_pp
        else:
            deployed_apy_pct = None
            cash_drag_pp = None

        # ── Shares of total POSITIVE yield + yield-source HHI. ─────────────────
        total_positive_yield = sum(
            r["contribution"] for r in known_rows if r["contribution"] > 0
        )
        for r in rows:
            if r["known"] and total_positive_yield > 0 and r["contribution"] > 0:
                r["share_of_total_yield"] = r["contribution"] / total_positive_yield
            else:
                # Zero/negative contribution or unknown → 0 share of total yield.
                r["share_of_total_yield"] = 0.0 if r["known"] else None

        yield_hhi = sum(
            r["share_of_total_yield"] ** 2
            for r in rows
            if r["known"] and r["share_of_total_yield"] is not None
        )
        yield_hhi_index = round(yield_hhi * 10000.0)
        if yield_hhi > 0:
            effective_num_yield_sources = 1.0 / yield_hhi
        else:
            effective_num_yield_sources = None

        # ── Top-1 / top-3 yield shares (over known, by share of total yield). ──
        contributing = sorted(
            (r for r in known_rows if r["share_of_total_yield"]),
            key=lambda r: r["share_of_total_yield"],
            reverse=True,
        )
        if contributing:
            top1_yield_protocol = contributing[0]["protocol"]
            top1_yield_share = contributing[0]["share_of_total_yield"]
            top3_yield_share = sum(
                r["share_of_total_yield"] for r in contributing[:3]
            )
        else:
            top1_yield_protocol = None
            top1_yield_share = 0.0
            top3_yield_share = 0.0

        unknown_yield_share = sum(r["weight_frac"] for r in unknown_rows)

        yield_concentration_class = _classify_yield(yield_hhi_index)

        # ── Verdict (advisory only). ───────────────────────────────────────────
        if (
            top1_yield_share > MAX_SINGLE_YIELD_SHARE
            or yield_concentration_class == "concentrated"
        ):
            verdict = "fail"
        elif (
            yield_concentration_class == "moderate"
            or unknown_yield_share > UNKNOWN_YIELD_WARN_SHARE
        ):
            verdict = "warn"
        else:
            verdict = "ok"

        if unknown_rows:
            notes.append(
                f"{len(unknown_rows)} protocol(s) with unknown live APY "
                f"({round(unknown_yield_share * 100.0, 4)}% of AUM weight) — "
                "yield contribution not computed for them"
            )

        # ── Per-protocol breakdown (sorted: known by contribution desc, then
        #    unknowns by weight desc). ───────────────────────────────────────────
        rows.sort(
            key=lambda r: (
                1 if r["known"] else 0,
                (r["contribution"] if r["known"] else r["weight_frac"]),
            ),
            reverse=True,
        )
        breakdown = [
            {
                "protocol": r["protocol"],
                "usd": round(r["usd"], 6),
                "weight_frac": round(r["weight_frac"], 9),
                "apy_pct": (None if r["apy_pct"] is None else round(r["apy_pct"], 6)),
                "known": r["known"],
                "yield_contribution_pp": (
                    None if r["contribution"] is None else round(r["contribution"], 9)
                ),
                "share_of_total_yield": (
                    None if r["share_of_total_yield"] is None
                    else round(r["share_of_total_yield"], 9)
                ),
                "tier": r["tier"],
                "tvl_usd": (None if r["tvl_usd"] is None else round(r["tvl_usd"], 2)),
            }
            for r in rows
        ]

        return {
            "available": True,
            "advisory_only": True,
            "execution_mode": "read_only",
            "is_demo": is_demo,
            "verdict": verdict,
            "aum_usd": round(aum, 6),
            "deployed_usd": round(deployed, 6),
            "cash_share": round(cash_share, 9),
            "portfolio_apy_pp": round(portfolio_apy_pp, 9),
            "deployed_apy_pct": (
                None if deployed_apy_pct is None else round(deployed_apy_pct, 9)
            ),
            "cash_drag_pp": (
                None if cash_drag_pp is None else round(cash_drag_pp, 9)
            ),
            "yield_hhi": round(yield_hhi, 9),
            "yield_hhi_index": int(yield_hhi_index),
            "effective_num_yield_sources": (
                None if effective_num_yield_sources is None
                else round(effective_num_yield_sources, 4)
            ),
            "top1_yield_protocol": top1_yield_protocol,
            "top1_yield_share": round(top1_yield_share, 9),
            "top3_yield_share": round(top3_yield_share, 9),
            "yield_concentration_class": yield_concentration_class,
            "total_yield_pp": round(total_positive_yield, 9),
            "known_yield_weight": round(known_weight, 9),
            "unknown_yield_share": round(unknown_yield_share, 9),
            "num_yield_sources": len(rows),
            "num_known": len(known_rows),
            "num_unknown": len(unknown_rows),
            "max_single_yield_share": MAX_SINGLE_YIELD_SHARE,
            "unknown_yield_warn_share": UNKNOWN_YIELD_WARN_SHARE,
            "counts": {
                "sources": len(rows),
                "known": len(known_rows),
                "unknown": len(unknown_rows),
            },
            "breakdown": breakdown,
            "source_files": list(SOURCE_FILES),
            "disclaimer": DISCLAIMER,
            "notes": notes,
        }
    except Exception as exc:  # last resort: even a junk data_dir never raises
        log.warning("build_yield_attribution degraded: %s", exc)
        return _empty_result(
            [f"internal error: {type(exc).__name__}: {exc} — honest empty result"],
        )


def build_status_doc(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Wrap :func:`build_yield_attribution` in a persistable status document.

    Adds a ``meta`` block ({generated_at, source_files}); ``history`` is added
    by :func:`write_status` on write.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    result = build_yield_attribution(data_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "meta": {
            "generated_at": now.isoformat(),
            "source_files": result.get("source_files", list(SOURCE_FILES)),
        },
        **result,
    }


# ─── Persist (idempotent, pattern: concentration_analytics / tear_sheet) ──────


def content_fingerprint(doc: Any) -> str:
    """Canonical fingerprint of the status CONTENT. Pure function.

    Volatile fields excluded: top-level ``history`` and ``meta.generated_at``
    (documented idempotency choice — ``generated_at`` only changes when content
    changes). Non-dict input → a fingerprint that never matches a valid doc.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k != "history"}
    meta = core.get("meta")
    if isinstance(meta, dict):
        core["meta"] = {k: v for k, v in meta.items() if k != "generated_at"}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record for yield_attribution.json."""
    meta = doc.get("meta") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "verdict": doc.get("verdict"),
        "portfolio_apy_pp": doc.get("portfolio_apy_pp"),
        "yield_hhi_index": doc.get("yield_hhi_index"),
        "top1_yield_share": doc.get("top1_yield_share"),
        "unknown_yield_share": doc.get("unknown_yield_share"),
        "counts": doc.get("counts"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/yield_attribution.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` is unchanged relative to the
    persisted status, the file is NOT rewritten (a repeated ``--run`` is
    byte-identical and history does not grow). On a content change a short
    record is appended to ``history`` (rotation ≤ :data:`HISTORY_MAX`). A
    broken/absent existing status file is tolerated as fresh. Returns
    {"path", "changed"}.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("yield attribution status unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("yield attribution status written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.yield_attribution",
        description=(
            "Portfolio Yield Attribution & Yield-Concentration Analyzer "
            "(SPA-V436 / MP-117): read-only / advisory per-protocol yield "
            "contribution, yield-source HHI, effective yield sources, top-N "
            "yield share, cash drag + unknown-yield bucket. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON analysis WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/yield_attribution.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: concentration_analytics.py).
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
        doc = build_status_doc(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            print(
                f"yield_attribution: verdict={doc['verdict']} "
                f"portfolio_apy_pp={doc.get('portfolio_apy_pp')} "
                f"yield_hhi_index={doc.get('yield_hhi_index')} "
                f"class={doc.get('yield_concentration_class')} "
                f"top1={doc.get('top1_yield_share')} — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"yield_attribution: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

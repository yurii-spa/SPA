#!/usr/bin/env python3
"""Portfolio Concentration & Diversification Analyzer (SPA-V435 / MP-116) — read-only / advisory.

Decomposes the *current* portfolio into concentration & diversification metrics
based on the **Herfindahl-Hirschman Index (HHI)**: how concentrated the book is
across protocols (both over the whole AUM and over the deployed book only),
across risk tiers, the effective number of positions (1/HHI), the largest and
top-3 position shares, a DOJ/FTC-style concentration class, and a single
max-single-position policy verdict. It answers the investor-DD question
*"how diversified is the book, and is any single bet too large?"*.

Single source of position weights (reuse-by-import)
==================================================
Position weights are NOT recomputed here. We import :func:`build_exposure` from
:mod:`spa_core.reporting.tear_sheet` (single source of truth for the weight /
tier / cash math) and consume its ``by_protocol[p]["share_pct"]`` (a PERCENT,
0..100, of the FULL AUM incl. cash) and ``by_tier`` (percent-of-AUM per tier).
We only convert percent→fraction (÷100) and aggregate into HHI — no duplicated
weight arithmetic. If :func:`build_exposure` reports ``available: false`` or no
``by_protocol`` we return an honest empty result + note.

Cash
====
``build_exposure`` shares are fractions of the FULL AUM (capital incl. cash), so
the deployed protocol shares sum to ``< 1.0`` whenever there is cash. We expose
both views: the **whole-AUM** HHI (cash dilutes concentration — cash is treated
as a synthetic non-concentrated bucket and is NOT squared into the protocol HHI)
AND the **deployed-only** HHI (each protocol's usd / deployed_sum), so a
cash-heavy book is not misleadingly reported as "diversified". The concentration
class and the effective-number-of-positions are derived from the DEPLOYED-only
HHI, which is the honest measure of how concentrated the *invested* book is.

HHI scales
==========
Each HHI is reported both as a *fraction* (sum of squared share fractions, in
``[0, 1]``) and on the standard 0–10000 *index* scale (fraction × 10000,
rounded). DOJ/FTC concentration thresholds are applied to the deployed-only
index: ``< 1500`` diversified, ``1500..2500`` (inclusive) moderate, ``> 2500``
concentrated (see :data:`HHI_MODERATE_FLOOR` / :data:`HHI_CONCENTRATED_FLOOR`).

Output / persistence
====================
:func:`build_concentration` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/concentration_analytics.json`` with an in-file ``history`` of runs
(rotation ≤ :data:`HISTORY_MAX`). Idempotency: a :func:`content_fingerprint`
over the whole doc EXCLUDING the volatile ``meta.generated_at`` / ``history``
means a repeated ``--run`` on unchanged inputs is byte-identical and does not
grow history (``generated_at`` only changes when content changes).

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.concentration_analytics --check    # compute+print, no write (default)
    python3 -m spa_core.paper_trading.concentration_analytics --run      # + atomic write
    python3 -m spa_core.paper_trading.concentration_analytics --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/re/typing) — no
requests/web3/LLM SDK/sockets/network. It only READS ``current_positions.json``
and ``adapter_orchestrator_status.json`` and writes its OWN status artifact; it
never moves capital and never touches risk/execution/allocator/cycle_runner.
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

# REUSE BY IMPORT — single source of truth for the position weight / tier / cash
# math (MP-501). We do NOT recompute weights from raw positions here; we consume
# build_exposure's share_pct (percent of full AUM) and by_tier directly.
from spa_core.reporting.tear_sheet import build_exposure
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.concentration_analytics")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "concentration_analytics"
STATUS_FILENAME = "concentration_analytics.json"
POSITIONS_FILENAME = "current_positions.json"
ORCHESTRATOR_FILENAME = "adapter_orchestrator_status.json"
HISTORY_MAX = 500  # run-history rotation (pattern: exit_liquidity / tear_sheet)

# DOJ/FTC standard HHI concentration thresholds, on the 0–10000 index scale.
# Applied to the DEPLOYED-only HHI index.
#   index < HHI_MODERATE_FLOOR (1500)                       → "diversified"
#   HHI_MODERATE_FLOOR <= index <= HHI_CONCENTRATED_FLOOR   → "moderate"
#   index > HHI_CONCENTRATED_FLOOR (2500)                   → "concentrated"
HHI_MODERATE_FLOOR = 1500
HHI_CONCENTRATED_FLOOR = 2500

# Max single-position policy: a single protocol may hold at most this FRACTION of
# the full AUM. Exactly 0.40 is OK (not a breach); strictly greater is a breach.
MAX_SINGLE_POSITION_SHARE = 0.40

DISCLAIMER = "NOT investment advice"

SOURCE_FILES = [POSITIONS_FILENAME, ORCHESTRATOR_FILENAME]


# ─── Tolerant IO helpers (pattern: exit_liquidity / data_integrity) ───────────


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


def _classify(hhi_index_deployed: Optional[int]) -> Optional[str]:
    """DOJ/FTC concentration class from the deployed-only HHI index, or None."""
    if hhi_index_deployed is None:
        return None
    if hhi_index_deployed < HHI_MODERATE_FLOOR:
        return "diversified"
    if hhi_index_deployed <= HHI_CONCENTRATED_FLOOR:
        return "moderate"
    return "concentrated"


# ─── Pure computation ─────────────────────────────────────────────────────────


def _empty_result(
    notes: List[str],
    *,
    is_demo: Optional[bool] = None,
    available: bool = False,
) -> Dict[str, Any]:
    """A stable-schema, honest-empty concentration result."""
    return {
        "available": available,
        "advisory_only": True,
        "execution_mode": "read_only",
        "is_demo": is_demo,
        "verdict": "warn",
        "aum_usd": 0.0,
        "deployed_usd": 0.0,
        "cash_usd": 0.0,
        "cash_share": 0.0,
        "hhi_protocol": 0.0,
        "hhi_protocol_index": 0,
        "hhi_protocol_deployed": 0.0,
        "hhi_protocol_deployed_index": 0,
        "effective_num_positions": None,
        "hhi_tier": 0.0,
        "hhi_tier_index": 0,
        "top1_share": 0.0,
        "top1_protocol": None,
        "top3_share": 0.0,
        "num_positions": 0,
        "concentration_class": None,
        "max_single_position_share": MAX_SINGLE_POSITION_SHARE,
        "policy_ok": True,
        "policy_breaches": [],
        "by_tier": {},
        "counts": {"positions": 0, "policy_breaches": 0},
        "breakdown": [],
        "source_files": list(SOURCE_FILES),
        "disclaimer": DISCLAIMER,
        "notes": notes,
    }


def build_concentration(
    data_dir: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """Build the portfolio concentration / diversification dict. NEVER raises.

    Reads ``current_positions.json`` and ``adapter_orchestrator_status.json``
    from *data_dir* (both tolerant/optional). Calls :func:`build_exposure`
    (single source of weight/tier/cash math) and aggregates its shares into
    HHI metrics — whole-AUM and deployed-only — the effective number of
    positions, top1/top3 shares, a DOJ/FTC concentration class, and a
    max-single-position policy verdict. Missing/broken input or an unavailable
    exposure → honest ``available: false`` empty result + note.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        positions_doc = _read_json(ddir / POSITIONS_FILENAME)
        orch_doc = _read_json(ddir / ORCHESTRATOR_FILENAME)
        notes: List[str] = []

        if positions_doc is None:
            return _empty_result(
                [f"{POSITIONS_FILENAME}: missing/unreadable — no concentration analysis"],
            )
        if not isinstance(positions_doc, dict):
            return _empty_result(
                [f"{POSITIONS_FILENAME}: unexpected top-level type — no analysis"],
            )

        # is_demo honestly from the positions file (null + note if absent/non-bool).
        is_demo: Optional[bool] = None
        if isinstance(positions_doc.get("is_demo"), bool):
            is_demo = positions_doc["is_demo"]
        else:
            notes.append(
                f"{POSITIONS_FILENAME}: is_demo missing/non-bool — reported as null"
            )

        if orch_doc is None:
            notes.append(
                f"{ORCHESTRATOR_FILENAME}: missing/unreadable — tiers reported as 'unknown'"
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
        cash_usd = round(aum * cash_share, 6) if aum > 0 else 0.0

        # ── Per-protocol fractions of the FULL AUM (from build_exposure). ──────
        # share_full = share_pct / 100; share_deployed renormalises to the
        # deployed book so a cash-heavy book is not misleadingly diversified.
        rows: List[Dict[str, Any]] = []
        deployed_sum = 0.0
        for proto, info in by_protocol.items():
            if not isinstance(info, dict):
                continue
            share_pct = _num(info.get("share_pct"))
            usd = _num(info.get("usd"))
            if share_pct is None or usd is None:
                notes.append(f"{proto}: missing share/usd in exposure — skipped")
                continue
            rows.append({
                "protocol": str(proto),
                "usd": usd,
                "share": share_pct / 100.0,
                "tier": info.get("tier", "unknown"),
            })
            deployed_sum += usd

        if not rows or deployed_sum <= 0:
            notes.append("no usable deployed positions — honest empty result")
            return _empty_result(notes, is_demo=is_demo, available=False)

        for row in rows:
            row["share_deployed"] = row["usd"] / deployed_sum

        rows.sort(key=lambda r: r["share"], reverse=True)

        # ── HHI over protocols. ────────────────────────────────────────────────
        # Whole-AUM HHI: cash is a synthetic non-concentrated bucket and is NOT
        # squared into the protocol HHI (documented), so the deployed shares
        # (summing < 1.0 when cash > 0) dilute the index.
        hhi_protocol = sum(r["share"] ** 2 for r in rows)
        hhi_protocol_index = round(hhi_protocol * 10000.0)
        # Deployed-only HHI: shares renormalised to the invested book.
        hhi_protocol_deployed = sum(r["share_deployed"] ** 2 for r in rows)
        hhi_protocol_deployed_index = round(hhi_protocol_deployed * 10000.0)

        # Effective number of positions from the DEPLOYED-only HHI (1/HHI).
        if hhi_protocol_deployed > 0:
            effective_num = 1.0 / hhi_protocol_deployed
        else:
            effective_num = None

        # ── HHI over tiers (by_tier is percent-of-AUM → ÷100). ─────────────────
        by_tier_raw = exposure.get("by_tier") or {}
        by_tier_echo: Dict[str, float] = {}
        hhi_tier = 0.0
        if isinstance(by_tier_raw, dict):
            for tier, pct in by_tier_raw.items():
                val = _num(pct)
                if val is None:
                    continue
                frac = val / 100.0
                by_tier_echo[str(tier)] = round(val, 9)
                hhi_tier += frac ** 2
        hhi_tier_index = round(hhi_tier * 10000.0)

        # ── Top-1 / top-3 shares (fractions of full AUM). ──────────────────────
        top1_share = rows[0]["share"]
        top1_protocol = rows[0]["protocol"]
        top3_share = sum(r["share"] for r in rows[:3])

        num_positions = len(rows)

        # ── Concentration class from the deployed-only HHI index. ──────────────
        concentration_class = _classify(hhi_protocol_deployed_index)

        # ── Max single-position policy (fraction of full AUM). ─────────────────
        breaches = [
            {"protocol": r["protocol"], "share": round(r["share"], 9)}
            for r in rows
            if r["share"] > MAX_SINGLE_POSITION_SHARE
        ]
        breaches.sort(key=lambda b: b["share"], reverse=True)
        policy_ok = not breaches

        # ── Verdict. ───────────────────────────────────────────────────────────
        has_unknown_tier = "unknown" in by_tier_echo
        if breaches or concentration_class == "concentrated":
            verdict = "fail"
        elif concentration_class == "moderate" or has_unknown_tier:
            verdict = "warn"
            if has_unknown_tier:
                notes.append(
                    "unknown-tier protocol(s) present in exposure (tier missing "
                    "from orchestrator)"
                )
        else:
            verdict = "ok"

        # ── Per-protocol breakdown (sorted by full-AUM share desc). ────────────
        breakdown = [
            {
                "protocol": r["protocol"],
                "usd": round(r["usd"], 6),
                "share": round(r["share"], 9),
                "share_deployed": round(r["share_deployed"], 9),
                "tier": r["tier"],
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
            "cash_usd": round(cash_usd, 6),
            "cash_share": round(cash_share, 9),
            "hhi_protocol": round(hhi_protocol, 9),
            "hhi_protocol_index": int(hhi_protocol_index),
            "hhi_protocol_deployed": round(hhi_protocol_deployed, 9),
            "hhi_protocol_deployed_index": int(hhi_protocol_deployed_index),
            "effective_num_positions": (
                None if effective_num is None else round(effective_num, 4)
            ),
            "hhi_tier": round(hhi_tier, 9),
            "hhi_tier_index": int(hhi_tier_index),
            "top1_share": round(top1_share, 9),
            "top1_protocol": top1_protocol,
            "top3_share": round(top3_share, 9),
            "num_positions": num_positions,
            "concentration_class": concentration_class,
            "max_single_position_share": MAX_SINGLE_POSITION_SHARE,
            "policy_ok": policy_ok,
            "policy_breaches": breaches,
            "by_tier": by_tier_echo,
            "counts": {
                "positions": num_positions,
                "policy_breaches": len(breaches),
            },
            "breakdown": breakdown,
            "source_files": list(SOURCE_FILES),
            "disclaimer": DISCLAIMER,
            "notes": notes,
        }
    except Exception as exc:  # last resort: even a junk data_dir never raises
        log.warning("build_concentration degraded: %s", exc)
        return _empty_result(
            [f"internal error: {type(exc).__name__}: {exc} — honest empty result"],
        )


def build_status_doc(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Wrap :func:`build_concentration` in a persistable status document.

    Adds a ``meta`` block ({generated_at, source_files}); ``history`` is added
    by :func:`write_status` on write.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    result = build_concentration(data_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "meta": {
            "generated_at": now.isoformat(),
            "source_files": result.get("source_files", list(SOURCE_FILES)),
        },
        **result,
    }


# ─── Persist (idempotent, pattern: exit_liquidity MP-114 / tear_sheet) ────────


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
    """Short run-history record for concentration_analytics.json."""
    meta = doc.get("meta") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "verdict": doc.get("verdict"),
        "hhi_protocol_index": doc.get("hhi_protocol_deployed_index"),
        "effective_num_positions": doc.get("effective_num_positions"),
        "top1_share": doc.get("top1_share"),
        "counts": doc.get("counts"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/concentration_analytics.json (tmp + os.replace).

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
        log.info("concentration analytics status unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("concentration analytics status written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.concentration_analytics",
        description=(
            "Portfolio Concentration & Diversification Analyzer (SPA-V435 / "
            "MP-116): read-only / advisory HHI decomposition of the current "
            "portfolio + max-single-position policy verdict. Offline."
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
        help="compute and atomically write data/concentration_analytics.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: exit_liquidity.py).
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
                f"concentration_analytics: verdict={doc['verdict']} "
                f"hhi_index={doc.get('hhi_protocol_deployed_index')} "
                f"class={doc.get('concentration_class')} "
                f"top1={doc.get('top1_share')} — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"concentration_analytics: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

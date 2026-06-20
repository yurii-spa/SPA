#!/usr/bin/env python3
"""Portfolio Exit-Liquidity Ladder (SPA-V431 / MP-114) — read-only / advisory.

Aggregates the *current* portfolio (``data/current_positions.json``) into a
portfolio-level **exit-liquidity ladder**: how the book's AUM is distributed
across exit-latency buckets (instant / liquid / illiquid / unknown), how much
capital can be returned within rolling time windows (≤24h, ≤72h, >72h), the
AUM-weighted mean exit latency, and a single liquidity-policy verdict
(does the book obey the ≤25%-illiquid policy?). It answers the investor-DD
question *"how fast can capital be returned, and is the book within policy?"*.

It builds directly on MP-113: the classification thresholds and the policy /
kill-switch logic are **reused by import** from
:mod:`spa_core.adapters.exit_latency_policy` (single source of truth for the
72h illiquid threshold and the 0.25 max-illiquid share — never duplicated here).

Per-protocol exit latency
=========================
The orchestrator status file does NOT surface exit latency, and instantiating
a live adapter to read it needs network (unavailable in this offline, read-only
scope). So we keep a small documented static map :data:`PROTOCOL_EXIT_LATENCY_HOURS`
that MIRRORS the adapters' ``EXIT_LATENCY_HOURS`` class constants. The adapters
remain the single source of truth — if an adapter's profile changes, update
this map. A protocol NOT present in the map resolves to latency ``None`` →
classifies ``"unknown"`` → counted as illiquid by the policy (it can never
silently pass). Protocol names are normalised defensively
("Aave V3" / "aave-v3" → "aave_v3") the same way the sibling modules do.

Cash
====
Portfolio weights are computed over ``capital_usd`` (the full AUM), and cash is
included as a synthetic ``__cash__`` position with latency 0.0 ("instant"), so
the reported ``illiquid_share`` is honestly measured over the *entire* book,
not just the deployed portion. If ``capital_usd`` is missing/0 we fall back to
the sum of positions (+cash) as the denominator (with a note); if that is still
0 the result is an honest empty ladder + note.

Output / persistence
====================
:func:`build_exit_liquidity` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/exit_liquidity_status.json`` with an in-file ``history`` of runs
(rotation ≤ :data:`HISTORY_MAX`). Idempotency: a :func:`content_fingerprint`
over the whole doc EXCLUDING the volatile ``meta.generated_at`` / ``history``
means a repeated ``--run`` on unchanged inputs is byte-identical and does not
grow history (``generated_at`` only changes when content changes).

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.exit_liquidity --check    # compute+print, no write (default)
    python3 -m spa_core.paper_trading.exit_liquidity --run      # + atomic write
    python3 -m spa_core.paper_trading.exit_liquidity --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/re) — no
requests/web3/LLM SDK/sockets/network. It only READS ``current_positions.json``
and writes its OWN status artifact; it never moves capital and never touches
risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# REUSE BY IMPORT — single source of truth for thresholds & policy/kill-switch
# logic (MP-113). We do NOT duplicate the 72h / 0.25 constants and do NOT
# reimplement the classification or the policy check here.
from spa_core.adapters.exit_latency_policy import (
    classify_exit_latency,
    check_exit_latency_policy,
    kill_switch_exit_order,
    ILLIQUID_THRESHOLD_HOURS,  # 72.0
    MAX_ILLIQUID_SHARE,        # 0.25
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.exit_liquidity")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "exit_liquidity"
STATUS_FILENAME = "exit_liquidity_status.json"
POSITIONS_FILENAME = "current_positions.json"
HISTORY_MAX = 500  # run-history rotation (pattern: data_integrity / tear_sheet)

# Synthetic cash position key (latency 0.0 — instant).
CASH_KEY = "__cash__"

# Convenience cumulative window boundary (in hours). A position with declared
# latency <= 24 is exitable within 24h; <= ILLIQUID_THRESHOLD_HOURS (72) within
# 72h; anything strictly above the 72h threshold (or unknown) is > 72h.
WINDOW_24H = 24.0

DISCLAIMER = "NOT investment advice"

# ─── Static per-protocol exit-latency map (MIRRORS the adapter constants) ─────
#
# Single source of truth = the adapters' ``EXIT_LATENCY_HOURS`` class constants.
# This map mirrors them so the aggregator stays offline (no live adapter
# instantiation / network). IF AN ADAPTER'S PROFILE CHANGES, UPDATE HERE.
# Verified against:
#   spa_core/adapters/aave_v3.py        EXIT_LATENCY_HOURS = 0.0
#   spa_core/adapters/compound_v3.py    EXIT_LATENCY_HOURS = 0.0
#   spa_core/adapters/euler_v2.py       EXIT_LATENCY_HOURS = 0.0
#   spa_core/adapters/morpho_blue.py    EXIT_LATENCY_HOURS = 0.0
#   spa_core/adapters/yearn_v3.py       EXIT_LATENCY_HOURS = 1.0
#   spa_core/adapters/maple.py          EXIT_LATENCY_HOURS = 336.0
#   spa_core/adapters/l2_adapters.py    EXIT_LATENCY_HOURS = 0.0 (all L2 lending)
# A protocol NOT in this map → latency None → "unknown" → counted illiquid.
PROTOCOL_EXIT_LATENCY_HOURS: Dict[str, Optional[float]] = {
    # Mainnet lending (T1) — instant, same-block withdrawals.
    "aave_v3": 0.0,
    "compound_v3": 0.0,
    "euler_v2": 0.0,
    "morpho_blue": 0.0,
    # Vault — short epoch / harvest settle.
    "yearn_v3": 1.0,
    # Epoch-based redemption queue (~14 days).
    "maple": 336.0,
    # L2 lending (T2) — instant, same-block withdrawals (l2_adapters.py).
    "aave_v3_arbitrum": 0.0,
    "aave_v3_base": 0.0,
    "compound_v3_base": 0.0,
    "morpho_blue_base": 0.0,
}


# ─── Tolerant IO / coercion helpers (pattern: data_integrity / tear_sheet) ────


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


def normalize_protocol(name: Any) -> str:
    """Normalise a protocol name to its canonical slug.

    "Aave V3" / "aave-v3" / "AAVE_V3" → "aave_v3". Lower-cases, collapses any
    run of non-alphanumeric characters to a single underscore, and trims
    leading/trailing underscores. Defensive — mirrors the convention used by
    the sibling read-only modules.
    """
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def latency_for_protocol(protocol: str) -> Optional[float]:
    """Static exit latency (hours) for a normalised protocol slug, or None.

    None (protocol not in :data:`PROTOCOL_EXIT_LATENCY_HOURS`) classifies as
    "unknown" and is counted illiquid by the policy — never silently passes.
    """
    return PROTOCOL_EXIT_LATENCY_HOURS.get(normalize_protocol(protocol))


# ─── Pure computation ─────────────────────────────────────────────────────────


def _empty_result(
    notes: List[str],
    *,
    is_demo: Optional[bool] = None,
    source_files: Optional[List[str]] = None,
    available: bool = False,
) -> Dict[str, Any]:
    """A stable-schema, honest-empty exit-liquidity result."""
    zero_bucket = {"usd": 0.0, "share": 0.0}
    return {
        "available": available,
        "advisory_only": True,
        "execution_mode": "read_only",
        "is_demo": is_demo,
        "verdict": "warn",
        "counts": {"ok": 0, "warn": 0, "fail": 0, "positions": 0},
        "aum_usd": 0.0,
        "cash_usd": 0.0,
        "cash_share": 0.0,
        "ladder": {
            "instant": dict(zero_bucket),
            "liquid": dict(zero_bucket),
            "illiquid": dict(zero_bucket),
            "unknown": dict(zero_bucket),
        },
        "exitable_within": {"24h": 0.0, "72h": 0.0, "gt_72h": 0.0},
        "weighted_mean_exit_latency_hours": None,
        "policy": {
            "ok": True,
            "illiquid_share": 0.0,
            "liquid_share": 0.0,
            "max_illiquid_share": MAX_ILLIQUID_SHARE,
            "threshold_hours": ILLIQUID_THRESHOLD_HOURS,
            "illiquid_positions": [],
        },
        "kill_switch_order": [],
        "breakdown": {},
        "source_files": source_files if source_files is not None else [POSITIONS_FILENAME],
        "disclaimer": DISCLAIMER,
        "notes": notes,
    }


def build_exit_liquidity(
    data_dir: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """Build the portfolio exit-liquidity ladder dict. NEVER raises.

    Reads ``current_positions.json`` from *data_dir*. Computes weights over the
    full AUM (``capital_usd``, with a documented fallback), buckets the book by
    exit-latency, derives cumulative exitable-within windows, the AUM-weighted
    mean exit latency, and a single policy verdict — reusing
    :func:`check_exit_latency_policy` and :func:`kill_switch_exit_order` from
    MP-113 (no logic duplicated). Missing/broken input → honest
    ``available: false`` empty result + note.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        positions_doc = _read_json(ddir / POSITIONS_FILENAME)
        notes: List[str] = []

        if positions_doc is None:
            return _empty_result(
                [f"{POSITIONS_FILENAME}: missing/unreadable — no exit-liquidity ladder"],
            )
        if not isinstance(positions_doc, dict):
            return _empty_result(
                [f"{POSITIONS_FILENAME}: unexpected top-level type — no ladder"],
            )

        # is_demo honestly from the file (null + note if absent/non-bool).
        is_demo: Optional[bool] = None
        if isinstance(positions_doc.get("is_demo"), bool):
            is_demo = positions_doc["is_demo"]
        else:
            notes.append(f"{POSITIONS_FILENAME}: is_demo missing/non-bool — reported as null")

        # ── Parse raw positions (USD), normalising protocol names. ──────────────
        raw = positions_doc.get("positions")
        usd_by_proto: Dict[str, float] = {}
        if isinstance(raw, dict):
            for proto, usd in raw.items():
                val = _num(usd)
                slug = normalize_protocol(proto)
                if not slug:
                    notes.append(f"skipped position with empty protocol name")
                    continue
                if val is None:
                    notes.append(f"{slug}: non-numeric position value — skipped")
                    continue
                if val < 0:
                    notes.append(f"{slug}: negative position value — skipped")
                    continue
                usd_by_proto[slug] = usd_by_proto.get(slug, 0.0) + val
        else:
            notes.append("'positions' is not a dict — no deployed positions parsed")

        cash = _num(positions_doc.get("cash_usd"))
        if cash is None:
            notes.append("cash_usd missing/non-numeric — treated as 0.0")
            cash = 0.0
        elif cash < 0:
            notes.append("cash_usd negative — treated as 0.0")
            cash = 0.0

        deployed_sum = sum(usd_by_proto.values())

        # ── Denominator: capital_usd (full AUM) with documented fallback. ──────
        capital = _num(positions_doc.get("capital_usd"))
        if capital is not None and capital > 0:
            aum = capital
        else:
            aum = deployed_sum + cash
            notes.append(
                "capital_usd missing/0 — using sum(positions)+cash as the AUM "
                "denominator (fallback)"
            )

        if aum <= 0:
            notes.append("AUM is 0 — empty portfolio, honest empty ladder")
            return _empty_result(notes, is_demo=is_demo, available=True)

        # ── Build the weighted positions mapping (incl. synthetic cash). ───────
        # Weights are fractions of the FULL AUM so illiquid_share is honest over
        # the whole book. Cash is a synthetic instant (0.0h) position.
        positions_map: Dict[str, Dict[str, Optional[float]]] = {}
        for slug, usd in usd_by_proto.items():
            positions_map[slug] = {
                "weight": usd / aum,
                "exit_latency_hours": latency_for_protocol(slug),
            }
        if cash > 0:
            positions_map[CASH_KEY] = {"weight": cash / aum, "exit_latency_hours": 0.0}

        # ── Reuse MP-113 policy + kill-switch (proves single source of truth). ──
        policy_report = check_exit_latency_policy(positions_map)
        kill_order = kill_switch_exit_order(positions_map)

        # ── Per-position breakdown + ladder buckets (USD + share). ─────────────
        ladder = {
            "instant": {"usd": 0.0, "share": 0.0},
            "liquid": {"usd": 0.0, "share": 0.0},
            "illiquid": {"usd": 0.0, "share": 0.0},
            "unknown": {"usd": 0.0, "share": 0.0},
        }
        exitable = {"24h": 0.0, "72h": 0.0, "gt_72h": 0.0}
        breakdown: Dict[str, Dict[str, Any]] = {}

        # USD per logical position (cash carries its own usd).
        usd_with_cash = dict(usd_by_proto)
        if cash > 0:
            usd_with_cash[CASH_KEY] = cash

        weighted_latency_sum = 0.0  # AUM-weighted sum over KNOWN-latency positions
        known_weight = 0.0
        for slug, usd in usd_with_cash.items():
            latency = positions_map[slug]["exit_latency_hours"]
            weight = usd / aum
            bucket = classify_exit_latency(latency)
            ladder[bucket]["usd"] += usd
            ladder[bucket]["share"] += weight

            # Cumulative exitable-within windows (deterministic boundaries):
            #   latency <= 24             → counts toward 24h AND 72h
            #   24 < latency <= 72        → counts toward 72h only
            #   latency > 72 OR unknown   → counts toward >72h
            if latency is None:
                exitable["gt_72h"] += weight
            elif latency <= WINDOW_24H:
                exitable["24h"] += weight
                exitable["72h"] += weight
                weighted_latency_sum += weight * latency
                known_weight += weight
            elif latency <= ILLIQUID_THRESHOLD_HOURS:
                exitable["72h"] += weight
                weighted_latency_sum += weight * latency
                known_weight += weight
            else:
                exitable["gt_72h"] += weight
                weighted_latency_sum += weight * latency
                known_weight += weight

            breakdown[slug] = {
                "usd": round(usd, 6),
                "weight": weight,
                "exit_latency_hours": latency,
                "bucket": bucket,
            }

        # AUM-weighted mean exit latency over positions with KNOWN latency.
        if known_weight > 0:
            weighted_mean = weighted_latency_sum / known_weight
        else:
            weighted_mean = None
            notes.append(
                "no positions with a known exit latency — weighted mean is null"
            )

        # ── Verdict. ───────────────────────────────────────────────────────────
        unknown_positions = [
            slug for slug, info in breakdown.items() if info["bucket"] == "unknown"
        ]
        cash_only = (deployed_sum <= 0)
        if not policy_report.get("ok", True):
            verdict = "fail"
        elif unknown_positions or cash_only:
            verdict = "warn"
            if unknown_positions:
                notes.append(
                    "unknown exit-latency protocol(s) present (counted illiquid): "
                    + ", ".join(sorted(unknown_positions))
                )
            if cash_only:
                notes.append("portfolio is cash-only / has no deployed positions")
        else:
            verdict = "ok"

        counts = {
            "ok": sum(1 for i in breakdown.values()
                      if i["bucket"] in ("instant", "liquid")),
            "warn": len(unknown_positions),
            "fail": sum(1 for i in breakdown.values() if i["bucket"] == "illiquid"),
            "positions": len(breakdown),
        }

        # Round ladder/exitable for stable output (after all summation).
        for b in ladder.values():
            b["usd"] = round(b["usd"], 6)
            b["share"] = round(b["share"], 9)
        for k in exitable:
            exitable[k] = round(exitable[k], 9)

        return {
            "available": True,
            "advisory_only": True,
            "execution_mode": "read_only",
            "is_demo": is_demo,
            "verdict": verdict,
            "counts": counts,
            "aum_usd": round(aum, 6),
            "cash_usd": round(cash, 6),
            "cash_share": round(cash / aum, 9),
            "ladder": ladder,
            "exitable_within": exitable,
            "weighted_mean_exit_latency_hours": (
                None if weighted_mean is None else round(weighted_mean, 6)
            ),
            "policy": {
                "ok": bool(policy_report.get("ok")),
                "illiquid_share": round(float(policy_report.get("illiquid_share", 0.0)), 9),
                "liquid_share": round(float(policy_report.get("liquid_share", 0.0)), 9),
                "max_illiquid_share": policy_report.get("max_illiquid_share", MAX_ILLIQUID_SHARE),
                "threshold_hours": policy_report.get("threshold_hours", ILLIQUID_THRESHOLD_HOURS),
                "illiquid_positions": list(policy_report.get("illiquid_positions", [])),
            },
            "kill_switch_order": list(kill_order),
            "breakdown": breakdown,
            "source_files": [POSITIONS_FILENAME],
            "disclaimer": DISCLAIMER,
            "notes": notes,
        }
    except Exception as exc:  # last resort: even a junk data_dir never raises
        log.warning("build_exit_liquidity degraded: %s", exc)
        return _empty_result(
            [f"internal error: {type(exc).__name__}: {exc} — honest empty ladder"],
        )


def build_status_doc(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Wrap :func:`build_exit_liquidity` in a persistable status document.

    Adds a ``meta`` block ({schema_version, source, generated_at}); ``history``
    is added by :func:`write_status` on write.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    result = build_exit_liquidity(data_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "meta": {
            "generated_at": now.isoformat(),
            "source_files": result.get("source_files", [POSITIONS_FILENAME]),
        },
        **result,
    }


# ─── Persist (idempotent, pattern: tear_sheet MP-501 / data_integrity) ───────


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
    """Short run-history record for exit_liquidity_status.json."""
    meta = doc.get("meta") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "verdict": doc.get("verdict"),
        "illiquid_share": (doc.get("policy") or {}).get("illiquid_share"),
        "aum_usd": doc.get("aum_usd"),
        "counts": doc.get("counts"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/exit_liquidity_status.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` is unchanged relative to the
    persisted status, the file is NOT rewritten (a repeated ``--run`` is
    byte-identical and history does not grow). On a content change a short
    record {generated_at, verdict, illiquid_share, aum_usd, counts} is appended
    to ``history`` (rotation ≤ :data:`HISTORY_MAX`). A broken/absent existing
    status file is tolerated as fresh. Returns {"path", "changed"}.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("exit liquidity status unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("exit liquidity status written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.exit_liquidity",
        description=(
            "Portfolio Exit-Liquidity Ladder (SPA-V431 / MP-114): read-only / "
            "advisory aggregation of the current portfolio into an "
            "exit-latency ladder + liquidity-policy verdict. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON ladder WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/exit_liquidity_status.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: data_integrity.py).
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
            policy = doc.get("policy") or {}
            print(
                f"exit_liquidity: verdict={doc['verdict']} "
                f"illiquid_share={policy.get('illiquid_share')} "
                f"aum=${doc.get('aum_usd')} — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(f"exit_liquidity: ERROR — {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

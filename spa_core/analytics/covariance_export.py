"""
Live APY Covariance Export (FEAT-007 / SPA-V336)
================================================

Emits ``data/covariance_summary.json`` — the single backend source of truth
for the live rolling-90d APY covariance / correlation / volatility used by
the dynamic-Kelly + Markowitz allocation path (FEAT-007 Phase 2, behind
``SPA_LIVE_COVARIANCE=1``).

This closes the last end-to-end gap in FEAT-007.  Phase 1 (v3.12) shipped
``CovarianceEstimator``; Phase 2 wired it into ``recommender.py`` and
``markowitz.py`` behind the env flag.  But the estimator reads its rolling
series from ``data/apy_history.json``, which is only written incrementally
by ``APYTracker`` during a live cycle — so in practice the live path always
fell back to the synthetic CV=10% proxy.  ``SPA-V336`` adds:

  1. an automatic bridge (``apy_history_bridge``) that materialises the
     tracker store from the existing ``data/historical_apy.json`` export
     when no live store exists, and
  2. this module, which builds the estimator over that store and writes a
     dashboard-ready JSON document with the full covariance matrix,
     correlation matrix, per-protocol volatilities, a tier map, and a
     ``source`` label that reports whether the numbers are LIVE (≥7
     real observations) or a SYNTHETIC fallback.

Schema (``data/covariance_summary.json``)::

    {
      "schema_version": 1,
      "generated_at": "<utc-iso>",
      "window_days": 90,
      "min_observations": 7,
      "source": "live" | "partial" | "synthetic_fallback",
      "history_store": "data/apy_history.json",
      "history_bridged": true,            # store was materialised by the bridge
      "protocols": {
        "<key>": {
          "tier": "T1"|"T2",
          "n_obs": int,
          "mean_apy": float,
          "volatility_pp": float,
          "fallback": bool                # synthetic proxy used for this key
        }, ...
      },
      "covariance_matrix": { "<key>": { "<key>": float, ... }, ... },
      "correlation_matrix": { "<key>": { "<key>": float, ... }, ... }
    }

Design constraints
------------------
* Pure stdlib — delegates all maths to ``CovarianceEstimator`` (which is
  itself numpy-free).  No network, no DB.
* Never raises on the happy path; a missing source yields a valid document
  with ``source="synthetic_fallback"`` and empty matrices.
* Deterministic for a fixed history store + window.

CLI
---
``python3 -m spa_core.analytics.covariance_export [--write] [--json]
        [--window N] [--source PATH] [--out PATH] [--no-bridge] [-v]``
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Resolve spa_core sub-packages whether invoked from spa_core/ or repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.covariance_estimator import (  # noqa: E402
    CovarianceEstimator,
    DEFAULT_WINDOW_DAYS,
    MIN_OBSERVATIONS,
)
from analytics import apy_history_bridge  # noqa: E402

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
COVARIANCE_SUMMARY_FILE = "data/covariance_summary.json"

# Canonical tier map for the current whitelist.  Used for the synthetic
# correlation fallback (same-tier 0.6 / cross-tier 0.2) and surfaced in the
# export so the dashboard can group rows.  Keys are matched by prefix so
# chain/asset-suffixed protocol keys (e.g. ``aave-v3-usdc-ethereum``) resolve.
_TIER_PREFIXES: list[tuple[str, str]] = [
    ("aave-v3", "T1"),
    ("compound-v3", "T1"),
    ("morpho", "T1"),
    ("sky-susds", "T1"),
    ("sky", "T1"),
    ("yearn-v3", "T2"),
    ("euler-v2", "T2"),
    ("maple", "T2"),
    ("pendle-pt", "T2"),
    ("pendle", "T2"),
]


def tier_for(protocol_key: str) -> str:
    """Resolve a protocol key to its risk tier via longest-prefix match."""
    key = (protocol_key or "").lower()
    best = ""
    best_tier = "T2"  # conservative default
    for prefix, tier in _TIER_PREFIXES:
        if key.startswith(prefix) and len(prefix) > len(best):
            best = prefix
            best_tier = tier
    return best_tier


def _classify_source(proto_rows: dict) -> str:
    """
    Aggregate per-protocol fallback flags into a single source label.

    * "synthetic_fallback" — no protocol produced a real estimate.
    * "live"               — every protocol has ≥ MIN_OBSERVATIONS points.
    * "partial"            — a mix (some live, some fell back).
    """
    if not proto_rows:
        return "synthetic_fallback"
    fallbacks = [r["fallback"] for r in proto_rows.values()]
    if all(fallbacks):
        return "synthetic_fallback"
    if any(fallbacks):
        return "partial"
    return "live"


def build_covariance_document(
    history_file: str = apy_history_bridge.APY_HISTORY_FILE,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    auto_bridge: bool = True,
    source_export: str = apy_history_bridge.HISTORICAL_APY_FILE,
) -> dict:
    """
    Build the covariance summary document.

    When ``auto_bridge`` is True and ``history_file`` does not yet exist,
    materialises it from ``source_export`` via ``apy_history_bridge`` so the
    estimator has real series to work with.  Never raises on the happy path.
    """
    bridged = False
    if auto_bridge:
        bridged = apy_history_bridge.ensure_apy_history(
            out_path=history_file, source=source_export
        )

    estimator = CovarianceEstimator(history_file=history_file)
    keys = estimator.protocols()

    # Per-protocol volatility / mean / n_obs (reuse the estimator's summary).
    summary = estimator.summary(window_days=window_days)
    summ_protos = summary.get("protocols", {})

    proto_rows: dict[str, dict] = {}
    tiers: dict[str, str] = {}
    synthetic_apys: dict[str, float] = {}
    for k in keys:
        s = summ_protos.get(k, {})
        tier = tier_for(k)
        tiers[k] = tier
        mean_apy = float(s.get("mean_apy", 0.0))
        synthetic_apys[k] = mean_apy
        proto_rows[k] = {
            "tier": tier,
            "n_obs": int(s.get("n_obs", 0)),
            "mean_apy": round(mean_apy, 4),
            "volatility_pp": round(float(s.get("volatility_pp", 0.0)), 4),
            "fallback": bool(s.get("fallback", True)),
        }

    cov = estimator.compute_covariance_matrix(
        window_days=window_days,
        protocols=keys,
        tiers=tiers,
        synthetic_apys=synthetic_apys,
    )
    corr = estimator.compute_correlation_matrix(
        window_days=window_days,
        protocols=keys,
        tiers=tiers,
    )

    # Round matrices for stable, diff-friendly output.
    cov = {i: {j: round(v, 8) for j, v in row.items()} for i, row in cov.items()}
    corr = {i: {j: round(v, 6) for j, v in row.items()} for i, row in corr.items()}

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "min_observations": MIN_OBSERVATIONS,
        "source": _classify_source(proto_rows),
        "history_store": history_file,
        "history_bridged": bridged,
        "protocols": proto_rows,
        "covariance_matrix": cov,
        "correlation_matrix": corr,
    }


def write_covariance_json(
    out_path: str = COVARIANCE_SUMMARY_FILE,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    history_file: str = apy_history_bridge.APY_HISTORY_FILE,
    auto_bridge: bool = True,
    source_export: str = apy_history_bridge.HISTORICAL_APY_FILE,
) -> dict:
    """Build the document and write it to ``out_path``; return the document."""
    doc = build_covariance_document(
        history_file=history_file,
        window_days=window_days,
        auto_bridge=auto_bridge,
        source_export=source_export,
    )
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))
    log.info(
        "covariance_export: wrote %s (source=%s, %d protocols)",
        out_path, doc["source"], len(doc["protocols"]),
    )
    return doc


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.analytics.covariance_export",
        description="Export live rolling-90d APY covariance summary JSON.",
    )
    ap.add_argument("--write", action="store_true",
                    help=f"write to --out (default: {COVARIANCE_SUMMARY_FILE})")
    ap.add_argument("--json", action="store_true",
                    help="print the document to stdout")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW_DAYS,
                    help=f"rolling window in days (default: {DEFAULT_WINDOW_DAYS})")
    ap.add_argument("--source", default=apy_history_bridge.HISTORICAL_APY_FILE,
                    help="source historical_apy.json for the auto-bridge")
    ap.add_argument("--history", default=apy_history_bridge.APY_HISTORY_FILE,
                    help="tracker history store the estimator reads")
    ap.add_argument("--out", default=COVARIANCE_SUMMARY_FILE,
                    help="output JSON path")
    ap.add_argument("--no-bridge", action="store_true",
                    help="do not materialise the history store from --source")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.write:
        doc = write_covariance_json(
            out_path=args.out,
            window_days=args.window,
            history_file=args.history,
            auto_bridge=not args.no_bridge,
            source_export=args.source,
        )
        print(f"wrote {args.out} — source={doc['source']}, "
              f"{len(doc['protocols'])} protocols")
    else:
        doc = build_covariance_document(
            history_file=args.history,
            window_days=args.window,
            auto_bridge=not args.no_bridge,
            source_export=args.source,
        )
        print(f"source={doc['source']}, {len(doc['protocols'])} protocols "
              f"(use --write to persist to {args.out})")
    if args.json:
        print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

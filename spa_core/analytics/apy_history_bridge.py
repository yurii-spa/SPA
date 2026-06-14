"""
APY History Bridge (FEAT-007 / SPA-V336)
========================================

Bridges the DeFiLlama 90-day APY export (``data/historical_apy.json``,
produced by ``data_pipeline``/``defillama`` loaders) into the rolling
history store that ``analytics.apy_tracker.APYTracker`` and
``analytics.covariance_estimator.CovarianceEstimator`` consume
(``data/apy_history.json``).

Why this module exists
----------------------
The live covariance / dynamic-Kelly pipeline (FEAT-007 Phase 2, wired in
``optimization/recommender.py`` and ``optimization/markowitz.py`` behind
``SPA_LIVE_COVARIANCE=1``) reads its rolling APY series from
``data/apy_history.json`` via ``CovarianceEstimator``.  But that file is
**only** written incrementally by ``APYTracker.record_snapshot`` during a
live 4h cycle — in a fresh checkout / sandbox it does not exist, so every
``SPA_LIVE_COVARIANCE=1`` run silently degrades to the synthetic CV=10%
proxy.  Meanwhile a real 90-day APY history already sits in
``data/historical_apy.json`` (the DeFiLlama / synthetic export consumed by
the backtester and dashboard charts) — just under a different schema.

This bridge converts that existing history into the tracker schema so the
covariance estimator finally has real per-protocol APY series to compute
rolling volatility and correlation from, instead of always falling back to
synthetic.

Schema mapping
--------------
Source (``historical_apy.json``)::

    {
      "generated_at": "<iso>",
      "data_source": "synthetic" | "defillama" | ...,
      "days": 90,
      "protocols": {
        "<protocol_key>": [
          {"date": "2026-02-21", "apy": 6.0511, "tvl_usd": 1.38e8},
          ...
        ],
        ...
      }
    }

Target (``apy_history.json`` — APYTracker schema)::

    {
      "protocol_history": {
        "<protocol_key>": [
          {"ts": "2026-02-21T00:00:00+00:00", "apy": 6.0511, "tvl_usd": 1.38e8},
          ...
        ],
        ...
      },
      "last_updated": "<iso>"
    }

The only structural change is the wrapper key (``protocols`` →
``protocol_history``) and the per-entry timestamp field: the source ``date``
(``YYYY-MM-DD``) is promoted to a timezone-aware ISO ``ts``
(``YYYY-MM-DDT00:00:00+00:00``) so it parses cleanly through the
estimator's ``_parse_iso`` and rolling-window filter.  ``apy`` is copied
verbatim; ``tvl_usd`` is preserved when present (the estimator ignores it,
but keeping it makes the bridged store a faithful superset).

Design constraints
------------------
* Pure stdlib (json / datetime / pathlib) — no numpy/scipy/web3.
* Never raises on the happy path; a missing / malformed source yields an
  empty-but-valid tracker document (``{"protocol_history": {}, ...}``) so
  downstream code degrades gracefully exactly as before.
* Deterministic: identical input → byte-identical output (entries kept in
  source order; ``protocol_history`` keys sorted for stable diffs).
* Read-only over the source; the only write target is
  ``data/apy_history.json`` (or an explicit ``out_path``).

CLI
---
``python3 -m spa_core.analytics.apy_history_bridge [--source PATH]
        [--out PATH] [--write] [--json] [-v]``
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Default file locations (relative to repo root / CWD, matching the rest of
# the codebase's ``data/...`` convention).
HISTORICAL_APY_FILE = "data/historical_apy.json"
APY_HISTORY_FILE = "data/apy_history.json"


# ──────────────────────────────────────────────────────────────────────────
# Timestamp normalisation
# ──────────────────────────────────────────────────────────────────────────

def _date_to_iso_ts(raw: str) -> Optional[str]:
    """
    Promote a source date/timestamp string to a timezone-aware ISO string.

    Accepts:
      * ``"YYYY-MM-DD"``                -> ``"YYYY-MM-DDT00:00:00+00:00"``
      * a full ISO timestamp           -> normalised to an aware ISO string
        (trailing ``Z`` accepted; naive timestamps assumed UTC).

    Returns ``None`` when the value cannot be parsed — the caller drops the
    entry rather than emitting an unparseable timestamp.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Date-only fast path.
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return d.isoformat()
        except ValueError:
            return None
    # Full ISO timestamp.
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ──────────────────────────────────────────────────────────────────────────
# Core conversion
# ──────────────────────────────────────────────────────────────────────────

def _empty_document() -> dict:
    """A valid-but-empty tracker document."""
    return {"protocol_history": {}, "last_updated": None}


def convert_history(historical: dict) -> dict:
    """
    Convert a parsed ``historical_apy.json`` dict to the APYTracker schema.

    Pure / side-effect free.  Never raises: malformed sub-structures are
    skipped entry-by-entry.  ``protocol_history`` keys are emitted sorted
    for deterministic, diff-friendly output.
    """
    if not isinstance(historical, dict):
        return _empty_document()

    protocols = historical.get("protocols")
    if not isinstance(protocols, dict):
        return _empty_document()

    out_history: dict[str, list] = {}
    for key in sorted(protocols.keys()):
        entries = protocols.get(key)
        if not isinstance(entries, list):
            continue
        converted: list[dict] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            ts = _date_to_iso_ts(e.get("date") or e.get("ts") or "")
            if ts is None:
                continue
            try:
                apy = float(e.get("apy", 0.0))
            except (TypeError, ValueError):
                continue
            rec = {"ts": ts, "apy": apy}
            if "tvl_usd" in e:
                try:
                    rec["tvl_usd"] = float(e["tvl_usd"])
                except (TypeError, ValueError):
                    pass
            converted.append(rec)
        # Keep only protocols that produced at least one usable point.
        if converted:
            out_history[key] = converted

    last_updated = historical.get("generated_at")
    if not isinstance(last_updated, str):
        last_updated = datetime.now(timezone.utc).isoformat()

    return {"protocol_history": out_history, "last_updated": last_updated}


def load_historical(source: str = HISTORICAL_APY_FILE) -> dict:
    """
    Read + parse the source ``historical_apy.json``.

    Returns ``{}`` (not the converted form) when the file is missing or
    unreadable — ``convert_history`` then yields an empty document.
    """
    p = Path(source)
    if not p.exists():
        log.warning("apy_history_bridge: source %s not found", source)
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("apy_history_bridge: failed to read %s — %s", source, exc)
        return {}


def build_tracker_document(source: str = HISTORICAL_APY_FILE) -> dict:
    """Read the source export and return the converted tracker document."""
    return convert_history(load_historical(source))


def write_tracker_history(
    source: str = HISTORICAL_APY_FILE,
    out_path: str = APY_HISTORY_FILE,
) -> dict:
    """
    Build the tracker document from ``source`` and write it to ``out_path``.

    Returns the written document.  Creates the parent directory if needed.
    """
    doc = build_tracker_document(source)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))
    log.info(
        "apy_history_bridge: wrote %s (%d protocols)",
        out_path,
        len(doc.get("protocol_history", {})),
    )
    return doc


def ensure_apy_history(
    out_path: str = APY_HISTORY_FILE,
    source: str = HISTORICAL_APY_FILE,
) -> bool:
    """
    Idempotent helper for the live-covariance path.

    If ``out_path`` already exists, leaves it untouched and returns False.
    Otherwise bridges from ``source`` (when available) and returns True if a
    non-empty store was written.  Never raises.
    """
    p = Path(out_path)
    if p.exists():
        return False
    try:
        doc = write_tracker_history(source=source, out_path=out_path)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("apy_history_bridge: ensure failed — %s", exc)
        return False
    return bool(doc.get("protocol_history"))


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.analytics.apy_history_bridge",
        description="Bridge historical_apy.json into the APYTracker store.",
    )
    ap.add_argument("--source", default=HISTORICAL_APY_FILE,
                    help=f"source export (default: {HISTORICAL_APY_FILE})")
    ap.add_argument("--out", default=APY_HISTORY_FILE,
                    help=f"output tracker store (default: {APY_HISTORY_FILE})")
    ap.add_argument("--write", action="store_true",
                    help="write the converted store to --out")
    ap.add_argument("--json", action="store_true",
                    help="print the converted document to stdout")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    doc = build_tracker_document(args.source)
    n_proto = len(doc.get("protocol_history", {}))
    n_points = sum(len(v) for v in doc.get("protocol_history", {}).values())
    if args.write:
        write_tracker_history(source=args.source, out_path=args.out)
        print(f"wrote {args.out} — {n_proto} protocols, {n_points} points")
    if args.json:
        print(json.dumps(doc, indent=2))
    if not args.write and not args.json:
        print(f"{n_proto} protocols, {n_points} points "
              f"(use --write to persist to {args.out})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

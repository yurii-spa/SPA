#!/usr/bin/env python3
"""Protocol Return Correlation Analyzer (SPA-V439 / MP-120) — read-only / advisory.

Computes pairwise Pearson correlations between protocol APY time series from
``data/apy_history.json``, building an N×N correlation matrix, identifying the
highest- and lowest-correlated pairs, clustering protocols with correlated
behaviour (threshold |r| > :data:`CLUSTER_THRESHOLD` = 0.8 → same cluster,
Union-Find), and producing an advisory verdict: if every active protocol belongs
to a single cluster the portfolio may lack risk-factor diversification.

Data source
===========
Primary: ``data/apy_history.json`` — ``{"protocol_history": {"slug": [{"ts":
"...", "apy": float, ...}, ...]}, "last_updated": "..."}``.

Each protocol series is aligned to the common date grid before computing
correlation. Only dates present in ALL selected protocols are used
(intersection alignment). If fewer than :data:`MIN_POINTS` = 7 aligned
observations remain, the result is ``available: false`` with
``reason: "insufficient_data"``.

Pearson correlation
===================
Implemented via pure stdlib (``math`` only) — no numpy/scipy. For series x, y::

    r = Σ(xi − x̄)(yi − ȳ) / sqrt(Σ(xi − x̄)² · Σ(yi − ȳ)²)

If either series has zero variance → r = null (not 0, not ±1 — the correlation
is undefined). A pair with null r is excluded from highest/lowest lists and
treated as uncorrelated for clustering purposes.

Clustering
==========
Union-Find over all protocol pairs where |r| > :data:`CLUSTER_THRESHOLD` (0.8).
If A↔B and B↔C both exceed threshold, A, B, C are placed in the same cluster
even if |r(A,C)| ≤ 0.8. Advisory verdict fires when ALL protocols with
sufficient data are in a single cluster.

Output / persistence
====================
:func:`build_correlation` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (tmp + ``os.replace``) writes
``data/correlation_analytics.json`` with an in-file ``history`` of runs
(rotation ≤ :data:`HISTORY_MAX`). Idempotency: a :func:`content_fingerprint`
over the whole doc EXCLUDING the volatile ``meta.generated_at`` / ``history``
means a repeated ``--run`` on unchanged inputs is byte-identical and does not
grow history.

CLI::

    python3 -m spa_core.paper_trading.correlation_analyzer --check    # compute+print, no write (default)
    python3 -m spa_core.paper_trading.correlation_analyzer --run      # + atomic write
    python3 -m spa_core.paper_trading.correlation_analyzer --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib/hashlib/itertools) —
no requests/web3/LLM SDK/sockets/network. It only READS ``apy_history.json``
and writes its OWN status artifact; it never moves capital and never touches
risk/execution/allocator/cycle_runner.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("spa.paper_trading.correlation_analyzer")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "correlation_analyzer"
STATUS_FILENAME: str = "correlation_analytics.json"
APY_HISTORY_FILENAME: str = "apy_history.json"

MIN_POINTS: int = 7           # minimum aligned observations for valid correlation
CLUSTER_THRESHOLD: float = 0.8  # |r| > this → same cluster
HISTORY_MAX: int = 500


# ──────────────────────────────────────────────────────────────────────────────
# Pearson correlation — pure stdlib
# ──────────────────────────────────────────────────────────────────────────────

def pearson(x: List[float], y: List[float]) -> Optional[float]:
    """Compute Pearson r for two equal-length float lists.

    Returns ``None`` if either series has zero variance (correlation undefined)
    or if ``len(x) < 2``.  Result is clamped to [-1, 1] to prevent
    floating-point overshoot on perfectly correlated integer series.
    """
    n = len(x)
    if n < 2 or n != len(y):
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    ss_x = sum((xi - mx) ** 2 for xi in x)
    ss_y = sum((yi - my) ** 2 for yi in y)
    if ss_x == 0.0 or ss_y == 0.0:
        return None
    r = num / math.sqrt(ss_x * ss_y)
    return max(-1.0, min(1.0, r))


# ──────────────────────────────────────────────────────────────────────────────
# Union-Find for threshold-based clustering
# ──────────────────────────────────────────────────────────────────────────────

class _UnionFind:
    """Simple Union-Find with path compression."""

    def __init__(self, items: List[str]) -> None:
        self._parent: Dict[str, str] = {x: x for x in items}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path halving
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def clusters(self) -> List[List[str]]:
        """Return list of clusters (each a sorted list of members)."""
        groups: Dict[str, List[str]] = {}
        for x in self._parent:
            r = self.find(x)
            groups.setdefault(r, []).append(x)
        return [sorted(v) for v in sorted(groups.values())]


# ──────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_apy_history(data_dir: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load and parse apy_history.json. Returns (data, error_note)."""
    p = data_dir / APY_HISTORY_FILENAME
    if not p.exists():
        return None, f"{APY_HISTORY_FILENAME} not found"
    try:
        raw = p.read_text(encoding="utf-8")
        d = json.loads(raw)
    except Exception as exc:
        return None, f"failed to parse {APY_HISTORY_FILENAME}: {exc}"
    if not isinstance(d, dict):
        return None, f"{APY_HISTORY_FILENAME} root is not a dict"
    ph = d.get("protocol_history")
    if not isinstance(ph, dict) or not ph:
        return None, "protocol_history missing or empty"
    return d, None


def _extract_series(
    protocol_history: Dict[str, Any],
) -> Dict[str, Dict[str, float]]:
    """For each protocol build {date_str: apy}.  Skips non-numeric APY values."""
    result: Dict[str, Dict[str, float]] = {}
    for slug, records in protocol_history.items():
        if not isinstance(records, list):
            continue
        series: Dict[str, float] = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            ts = rec.get("ts", "")
            apy = rec.get("apy")
            if not isinstance(ts, str) or not ts:
                continue
            date_str = ts[:10]  # YYYY-MM-DD
            if not isinstance(apy, (int, float)):
                continue
            if math.isnan(apy) or math.isinf(apy):
                continue
            series[date_str] = float(apy)
        if series:
            result[slug] = series
    return result


def _align_series(
    series_map: Dict[str, Dict[str, float]],
) -> Tuple[List[str], Dict[str, List[float]]]:
    """Align all series to the common date intersection.

    Returns ``(sorted_dates, {slug: [apy, ...]})``; empty on no overlap.
    """
    if not series_map:
        return [], {}
    common: Optional[set] = None
    for series in series_map.values():
        if common is None:
            common = set(series.keys())
        else:
            common &= set(series.keys())
    if not common:
        return [], {}
    sorted_dates = sorted(common)
    aligned: Dict[str, List[float]] = {
        slug: [series_map[slug][d] for d in sorted_dates]
        for slug in series_map
    }
    return sorted_dates, aligned


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────

def build_correlation(data_dir: Path = _DEFAULT_DATA_DIR) -> Dict[str, Any]:
    """Compute protocol APY correlation matrix and clustering. Never raises."""
    data_dir = Path(data_dir)
    notes: List[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        raw_data, err = _load_apy_history(data_dir)
        if err:
            return _unavailable(err, generated_at, notes)

        protocol_history: Dict[str, Any] = raw_data["protocol_history"]
        series_map = _extract_series(protocol_history)

        if not series_map:
            return _unavailable("no valid APY series found", generated_at, notes)

        if len(series_map) < 2:
            return _unavailable(
                f"only {len(series_map)} protocol(s) with data — need ≥ 2 for correlation",
                generated_at, notes,
            )

        sorted_dates, aligned = _align_series(series_map)
        n_obs = len(sorted_dates)

        if n_obs < MIN_POINTS:
            return {
                "available": False,
                "reason": "insufficient_data",
                "n_observations": n_obs,
                "min_required": MIN_POINTS,
                "protocols_found": sorted(series_map.keys()),
                "notes": [f"need ≥ {MIN_POINTS} aligned observations, got {n_obs}"],
                "meta": {
                    "generated_at": generated_at,
                    "schema_version": SCHEMA_VERSION,
                    "source": SOURCE_NAME,
                },
            }

        protocols = sorted(aligned.keys())

        # ── Correlation matrix (symmetric, diagonal = 1.0) ──────────────────
        corr: Dict[str, Dict[str, Optional[float]]] = {}
        for p in protocols:
            corr[p] = {}
        for p in protocols:
            corr[p][p] = 1.0
        for p, q in itertools.combinations(protocols, 2):
            r = pearson(aligned[p], aligned[q])
            corr[p][q] = r
            corr[q][p] = r

        # ── Pairwise list ────────────────────────────────────────────────────
        pairs: List[Dict[str, Any]] = []
        for p, q in itertools.combinations(protocols, 2):
            pairs.append({"protocol_a": p, "protocol_b": q, "r": corr[p][q]})

        valid_pairs = [pa for pa in pairs if pa["r"] is not None]
        sorted_desc = sorted(valid_pairs, key=lambda pa: pa["r"], reverse=True)

        highest_pairs = sorted_desc[:5]
        # lowest: most negative / smallest r first (most diversifying)
        sorted_asc = sorted(valid_pairs, key=lambda pa: pa["r"])
        lowest_pairs = sorted_asc[:5]

        # ── Clustering ───────────────────────────────────────────────────────
        uf = _UnionFind(protocols)
        high_corr_pairs: List[Dict[str, Any]] = []
        for pa in valid_pairs:
            if abs(pa["r"]) > CLUSTER_THRESHOLD:
                uf.union(pa["protocol_a"], pa["protocol_b"])
                high_corr_pairs.append(pa)

        clusters = uf.clusters()
        n_clusters = len(clusters)
        max_cluster_size = max(len(c) for c in clusters)
        dominant_cluster_share = max_cluster_size / len(protocols)

        # ── Advisory verdict ─────────────────────────────────────────────────
        all_in_one = n_clusters == 1 and len(protocols) >= 2
        if all_in_one:
            verdict = "fail"
            verdict_reason = (
                f"all {len(protocols)} protocols cluster together "
                f"(|r| > {CLUSTER_THRESHOLD}); "
                "portfolio may lack risk-factor diversification"
            )
        elif dominant_cluster_share >= 0.75 and len(protocols) >= 3:
            verdict = "warn"
            verdict_reason = (
                f"{max_cluster_size}/{len(protocols)} protocols in dominant cluster "
                f"({dominant_cluster_share:.0%}); limited diversification"
            )
        elif not valid_pairs:
            verdict = "warn"
            verdict_reason = (
                "no valid correlation pairs "
                "(all series have zero variance or < 2 observations)"
            )
        else:
            verdict = "ok"
            verdict_reason = (
                f"{n_clusters} independent cluster(s) across {len(protocols)} protocols"
            )

        # ── Correlation matrix as list-of-rows (stable JSON order) ──────────
        matrix_rows = [
            {"protocol": p, "correlations": {q: corr[p][q] for q in protocols}}
            for p in protocols
        ]

        return {
            "available": True,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "n_protocols": len(protocols),
            "n_observations": n_obs,
            "date_range": {"first": sorted_dates[0], "last": sorted_dates[-1]},
            "protocols": protocols,
            "correlation_matrix": matrix_rows,
            "highest_correlation_pairs": highest_pairs,
            "lowest_correlation_pairs": lowest_pairs,
            "cluster_threshold": CLUSTER_THRESHOLD,
            "n_clusters": n_clusters,
            "clusters": clusters,
            "high_correlation_pairs": high_corr_pairs,
            "dominant_cluster_share": round(dominant_cluster_share, 4),
            "notes": notes,
            "meta": {
                "generated_at": generated_at,
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE_NAME,
                "min_points_required": MIN_POINTS,
            },
        }

    except Exception as exc:
        log.exception("unexpected error in build_correlation")
        return _unavailable(f"unexpected error: {exc}", generated_at, notes)


def _unavailable(
    reason: str, generated_at: str, notes: List[str]
) -> Dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "notes": notes,
        "meta": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Fingerprint + atomic persistence
# ──────────────────────────────────────────────────────────────────────────────

def content_fingerprint(doc: Dict[str, Any]) -> str:
    """Stable MD5 hash of doc excluding volatile keys (generated_at, history)."""
    d = {k: v for k, v in doc.items() if k not in ("history", "_fingerprint")}
    if "meta" in d:
        d["meta"] = {k: v for k, v in d["meta"].items() if k != "generated_at"}
    return hashlib.md5(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_status(
    result: Dict[str, Any],
    data_dir: Path = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write correlation_analytics.json.

    Returns one of: ``"DATA_WRITTEN"`` | ``"DATA_UNCHANGED"``.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / STATUS_FILENAME

    current_fp = content_fingerprint(result)

    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    if existing.get("_fingerprint") == current_fp:
        return "DATA_UNCHANGED"

    # Rotate previous entry into history
    history: List[Dict[str, Any]] = existing.get("history", [])
    if existing and "_fingerprint" in existing:
        prev_entry = {k: v for k, v in existing.items() if k != "history"}
        history = [prev_entry] + history
        history = history[:HISTORY_MAX]

    doc = dict(result)
    doc["_fingerprint"] = current_fp
    doc["history"] = history

    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".tmp_corr_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return "DATA_WRITTEN"


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _print_result(result: Dict[str, Any]) -> None:
    if not result.get("available"):
        print(
            f"[correlation_analyzer] available=false "
            f"reason={result.get('reason', '?')}"
        )
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[correlation_analyzer] available=true")
    print(f"  verdict       : {result['verdict']} — {result['verdict_reason']}")
    print(
        f"  protocols     : {result['n_protocols']} "
        f"({', '.join(result['protocols'])})"
    )
    print(
        f"  observations  : {result['n_observations']} "
        f"({result['date_range']['first']} … {result['date_range']['last']})"
    )
    print(
        f"  clusters      : {result['n_clusters']} "
        f"(threshold |r|>{result['cluster_threshold']})"
    )
    for i, cl in enumerate(result["clusters"]):
        print(f"    cluster {i + 1}   : {cl}")
    print("  highest pairs :")
    for pa in result["highest_correlation_pairs"]:
        r_str = f"{pa['r']:.4f}" if pa["r"] is not None else "null"
        print(f"    {pa['protocol_a']} ↔ {pa['protocol_b']}  r={r_str}")
    print("  lowest pairs  :")
    for pa in result["lowest_correlation_pairs"]:
        r_str = f"{pa['r']:.4f}" if pa["r"] is not None else "null"
        print(f"    {pa['protocol_a']} ↔ {pa['protocol_b']}  r={r_str}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Protocol Return Correlation Analyzer (MP-120)",
        add_help=True,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="compute and print, no write (default)",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="compute, print, and atomically write to data/correlation_analytics.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="override data directory (default: <repo_root>/data)",
    )

    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"ERROR: invalid arguments: {unknown}", file=sys.stderr)
        sys.exit(0)

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    result = build_correlation(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[correlation_analyzer] write_status={status}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()

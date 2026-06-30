#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/dfb_perf_budget.py — PERF BUDGET gate for the DFB (DeFi Board, Lane 2) read paths.

WHAT IT MEASURES
================
The DFB screener is a PRECOMPUTED-SNAPSHOT product: the capture agent
(``spa_core.dfb.paper_dfb``) builds the per-pool risk overlay ONCE per day and writes the
atomic snapshot ``data/dfb/pools.json`` (+ ``pool/<id>.json`` details); the API router
(``spa_core/api/routers/dfb.py``) then SERVES that snapshot on each request with a single
``json.loads`` — it NEVER re-runs the risk-overlay engine per request. This harness proves
that O(1)-read property holds and gates its latency:

  * api:/api/dfb/pools           — the full screener list (verbatim snapshot read)
  * api:/api/dfb/summary         — universe stats (counts-only aggregation over the snapshot)
  * api:/api/dfb/pool/<id>       — one pool's detail (verbatim per-pool snapshot read)

Each surface is warmed then timed over N iterations; we report the MEDIAN and p95 and assert
**p95 < 300ms** (the charter's documented breadth budget) reading a realistic-breadth snapshot.

THE NO-RECOMPUTE PROPERTY (the load-bearing perf assertion)
-----------------------------------------------------------
The harness installs a tripwire on the overlay engine (``risk_overlay.overlay`` /
``build_overlays``) and asserts it is NEVER called while serving requests. If a router path
ever recomputed per-request, the tripwire fires and the gate FAILS — i.e. the gate proves the
snapshot is read, not rebuilt.

CONTRACT
--------
  * Hermetic: a SANDBOX tmp data dir seeded with a synthetic breadth snapshot — the live
    ``data/`` is NEVER read or written.
  * stdlib + pytest's TestClient (optional — skips with a clear note if fastapi is absent).
  * Deterministic inputs; wall-clock timing is the only non-determinism, absorbed by the
    p95-under-budget comparison with generous headroom.
  * Exit 0 iff every measured surface is under budget AND the no-recompute tripwire held.

CLI::
    python3 scripts/dfb_perf_budget.py             # run + print the budget table
    python3 scripts/dfb_perf_budget.py --json      # machine-readable verdict
    python3 scripts/dfb_perf_budget.py --pools 500 --iterations 30
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "spa_core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── DOCUMENTED BUDGET (ms, p95) — the charter's breadth ceiling (WS-3.2). ─────
# A snapshot READ is O(file-size); 300ms p95 is a generous regression ceiling for a
# few-hundred-pool snapshot served by a single json.loads. A p95 above this = a real
# slowdown (e.g. an accidental per-request recompute), not machine jitter.
P95_BUDGET_MS = 300.0

# Default synthetic-breadth snapshot size (pools). Real breadth grows behind SPA_DFB_BREADTH;
# the read path must stay flat in pool-count, so we time it at a realistic breadth.
DEFAULT_N_POOLS = 300


def _synthetic_overlay_row(i: int, prev_hash: str) -> dict:
    """One overlay row matching the shared contract (a presentation object — NO risk math).

    These are STATIC fixture rows (not engine output): the perf gate measures the SERVE path,
    not the build path, so a hand-rolled snapshot is exactly the right hermetic input."""
    rc = ("A", "B", "C", "D", "UNKNOWN")[i % 5]
    refuse = rc in ("C", "D")
    body = {
        "pool_id": f"perf-pool-{i:04d}",
        "protocol": f"protocol_{i % 12}",
        "chain": ("Ethereum", "Arbitrum", "Optimism", "Base", "Polygon")[i % 5],
        "asset": ("USDC", "USDT", "DAI", "weETH", "stETH")[i % 5],
        "tier": ("T1", "T2", "T3")[i % 3],
        "apy": {"total": 3.0 + (i % 20) * 0.1, "base": 2.0 + (i % 10) * 0.1,
                "reward": 1.0 + (i % 5) * 0.1},
        "tvl_usd": 5_000_000.0 + i * 100_000.0,
        "risk_class": rc,
        "risk_class_label": rc,
        "structural_haircut": round(0.01 * (i % 9), 8),
        "total_haircut": round(0.02 * (i % 9), 8),
        "exit_liquidity": [
            {"ticket_usd": t, "absorbable_usd": (None if (i % 7 == 0) else float(t) * 0.9),
             "dex_exit_frac": (None if (i % 7 == 0) else 0.9), "flagged": (i % 7 == 0)}
            for t in (1_000_000, 5_000_000, 10_000_000)
        ],
        "refusal": {"verdict": ("REFUSE" if refuse else "SAFE"),
                    "reason": ("TAIL_VETO" if rc == "D" else "OK"),
                    "tail_veto": rc == "D"},
        "as_of": "2026-06-30",
        "data_source": "live",
        "feed_coverage": "full" if (i % 7) else "partial",
        "flagged": (i % 7 == 0),
        "flag_reason": ("insufficient_contemporaneous_depth" if (i % 7 == 0) else None),
        "engine_proof_hash": f"{i:064x}",
        "prev_hash": prev_hash,
    }
    # A deterministic synthetic row_hash (the perf gate does not re-derive the chain; the
    # health domain + the no_fork/overlay tests own chain correctness).
    import hashlib
    rh = hashlib.sha256(
        json.dumps({"body": body, "prev_hash": prev_hash}, sort_keys=True,
                   separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    body["row_hash"] = rh
    return body


def _seed_snapshot(sbx: Path, n_pools: int) -> list:
    """Write a synthetic breadth snapshot into the sandbox (atomic-shaped): pools.json wrapper +
    one pool/<id>.json per row, exactly as the overlay writer would. Returns the row list."""
    dfb_dir = sbx / "dfb"
    pool_dir = dfb_dir / "pool"
    pool_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    prev = "0" * 64
    for i in range(n_pools):
        r = _synthetic_overlay_row(i, prev)
        rows.append(r)
        prev = r["row_hash"]
    import datetime
    wrapper = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "schema": "dfb_pool_overlay_v1",
        "n_pools": len(rows),
        "n_flagged": sum(1 for r in rows if r["flagged"]),
        "n_refused": sum(1 for r in rows if r["refusal"]["verdict"] == "REFUSE"),
        "n_unknown": sum(1 for r in rows if r["risk_class"] == "UNKNOWN"),
        "chain_valid": True,
        "pools": rows,
    }
    (dfb_dir / "pools.json").write_text(json.dumps(wrapper, separators=(",", ":")),
                                        encoding="utf-8")
    for r in rows:
        (pool_dir / f"{r['pool_id']}.json").write_text(json.dumps(r, separators=(",", ":")),
                                                       encoding="utf-8")
    return rows


def _time_calls(fn, iterations: int, warmup: int = 3) -> tuple[float, float]:
    """Return (median_ms, p95_ms) over ``iterations`` timed calls (after warmup)."""
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    median = statistics.median(samples)
    p95 = samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
    return round(median, 3), round(p95, 3)


class _RecomputeTripwire(Exception):
    """Raised iff a router request path calls the overlay ENGINE (a per-request recompute)."""


def run_budget(iterations: int = 20, n_pools: int = DEFAULT_N_POOLS) -> dict:
    logging.disable(logging.CRITICAL)
    try:
        try:
            from fastapi.testclient import TestClient
            import spa_core.api.server as server
        except Exception as exc:  # noqa: BLE001 — fastapi optional
            return {"module": "dfb_perf_budget", "version": "v1.0", "skipped": True,
                    "reason": f"fastapi/TestClient unavailable: {exc!r}",
                    "rows": [], "pass": True, "no_recompute": None}

        sbx = Path(tempfile.mkdtemp(prefix="spa_dfb_perf_"))
        rows = _seed_snapshot(sbx, n_pools)
        server._DATA_DIR = sbx  # redirect every DFB router read to the seeded sandbox

        # ── NO-RECOMPUTE TRIPWIRE — patch the overlay engine so any per-request call FAILS. ──
        from spa_core.dfb import risk_overlay as _ro

        recompute = {"hit": False}

        def _tripwire(*_a, **_k):
            recompute["hit"] = True
            raise _RecomputeTripwire("overlay engine called during a SERVE request — "
                                     "the snapshot path must NOT recompute per-request")

        _orig_overlay, _orig_build = _ro.overlay, _ro.build_overlays
        _ro.overlay = _tripwire
        _ro.build_overlays = _tripwire

        sample_pool_id = rows[len(rows) // 2]["pool_id"]
        measured: dict[str, tuple[float, float]] = {}
        try:
            with TestClient(server.app) as client:
                surfaces = {
                    "api:/api/dfb/pools": "/api/dfb/pools",
                    "api:/api/dfb/summary": "/api/dfb/summary",
                    f"api:/api/dfb/pool/{sample_pool_id}": f"/api/dfb/pool/{sample_pool_id}",
                }
                for label, ep in surfaces.items():
                    def _one(_ep=ep):
                        r = client.get(_ep)
                        assert r.status_code == 200, f"{_ep} -> {r.status_code}"
                    measured[label] = _time_calls(_one, iterations)
        finally:
            _ro.overlay, _ro.build_overlays = _orig_overlay, _orig_build
            import shutil
            shutil.rmtree(sbx, ignore_errors=True)
    finally:
        logging.disable(logging.NOTSET)

    rows_out = []
    all_ok = True
    for name, (median, p95) in measured.items():
        ok = p95 <= P95_BUDGET_MS
        all_ok = all_ok and ok
        rows_out.append({
            "surface": name, "median_ms": median, "p95_ms": p95,
            "budget_p95_ms": P95_BUDGET_MS,
            "headroom_pct": round(100.0 * (1 - p95 / P95_BUDGET_MS), 1),
            "ok": ok,
        })
    no_recompute = not recompute["hit"]
    all_ok = all_ok and no_recompute
    return {
        "module": "dfb_perf_budget", "version": "v1.0",
        "iterations": iterations, "n_pools": n_pools,
        "budget_p95_ms": P95_BUDGET_MS,
        "no_recompute": no_recompute,
        "rows": rows_out, "pass": all_ok,
        "over_budget": [r["surface"] for r in rows_out if not r["ok"]],
    }


def _print(report: dict) -> None:
    print("=" * 78)
    print("DFB PERF BUDGET (Lane-2 WS-3.2) — snapshot-read latency, gated (p95 < 300ms)")
    print("=" * 78)
    if report.get("skipped"):
        print(f" SKIPPED: {report['reason']}")
        print("=" * 78)
        return
    print(f" iterations: {report['iterations']}  n_pools: {report['n_pools']}  "
          f"budget p95: {report['budget_p95_ms']:.0f}ms")
    nr = report["no_recompute"]
    print(f" no-recompute tripwire: {'HELD (snapshot read, no per-request rebuild)' if nr else 'FIRED — PER-REQUEST RECOMPUTE!'}")
    print("-" * 78)
    print(f" {'surface':<38}{'median':>9}{'p95':>9}{'budget':>9}  status")
    for r in report["rows"]:
        mark = "OK" if r["ok"] else "OVER"
        print(f" {r['surface']:<38}{r['median_ms']:>8.1f}{r['p95_ms']:>9.1f}"
              f"{r['budget_p95_ms']:>9.0f}  [{mark}]")
    print("-" * 78)
    if report["over_budget"]:
        print(f" OVER BUDGET: {', '.join(report['over_budget'])}")
    print(f" GATE: {'PASS' if report['pass'] else 'FAIL'}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="DFB perf-budget gate (Lane-2 WS-3.2) — assert the snapshot-read paths "
                    "(/api/dfb/pools, /summary, /pool/<id>) stay under p95 300ms and never "
                    "recompute the overlay per-request (sandbox, hermetic).")
    p.add_argument("--iterations", type=int, default=20)
    p.add_argument("--pools", type=int, default=DEFAULT_N_POOLS, dest="n_pools")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    report = run_budget(iterations=args.iterations, n_pools=args.n_pools)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print(report)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

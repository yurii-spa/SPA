#!/usr/bin/env python3
# LLM_FORBIDDEN
"""scripts/perf_budget.py — PERF BUDGET gate for the money path (Cutover-Bulletproof WS-6.5).

WHAT IT MEASURES
================
A small, deterministic, hermetic latency harness over the load-bearing surfaces:

  * cycle              — one full ``cycle_runner.run_cycle`` against a SANDBOX tmp
                         data dir (network-free fakes). This is the daily money-path
                         loop; it must stay fast enough that the 08:00 UTC cron has
                         huge headroom.
  * allocator          — one ``StrategyAllocator.allocate`` over an in-memory
                         snapshot (the ranking/cap/remainder machinery).
  * reconcile          — one ``reconciliation.round_trip`` (plan→dry-run→reconcile).
  * api:<endpoint>     — each key read-only endpoint via an in-process TestClient
                         with the data dir redirected to a sandbox (no live data/).

Each surface is run a few warm-up times then timed over N iterations; we report the
MEDIAN and p95 and assert the median is under a DOCUMENTED budget. Budgets are
honest, sandbox-measured ceilings with generous headroom (a regression that, say,
doubles cycle latency trips the gate without flapping on normal machine jitter).

CONTRACT
--------
  * Hermetic: SANDBOX tmp data dir only — the live ``data/`` is NEVER read/written.
  * stdlib + pytest's TestClient (optional — api rows skip if fastapi absent).
  * Deterministic inputs; wall-clock timing is the only non-determinism, absorbed
    by comparing the MEDIAN against a budget with headroom.
  * Exit 0 iff every measured surface is under budget.

CLI::
    python3 scripts/perf_budget.py            # run + print the budget table
    python3 scripts/perf_budget.py --json     # machine-readable verdict
    python3 scripts/perf_budget.py --iterations 20
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "spa_core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── DOCUMENTED BUDGETS (ms, median) — honest sandbox ceilings with headroom. ──
# These are NOT the observed numbers (those run ~3-50x faster on a dev box); they
# are the regression ceilings. A median above the budget = a real slowdown to
# investigate, not machine jitter.
BUDGETS_MS: dict[str, float] = {
    "cycle": 1500.0,            # one full daily cycle (sandbox, fakes)
    "allocator": 250.0,         # one allocate() over an in-memory snapshot
    "reconcile": 150.0,         # one plan→dry-run→reconcile round_trip
    "api:/health": 100.0,
    "api:/api/execution/readiness": 150.0,
    "api:/api/redteam": 150.0,
    "api:/api/captured-book": 200.0,
    "api:/api/optimizer-ab": 150.0,
    "api:/api/v1/day30": 400.0,  # builds live artifact when file absent
}


# ── sandbox fixtures (network-free; never touch live data/) ──────────────────
_CLEAN_TARGET = {"aave_v3": 35_000.0, "compound_v3": 20_000.0}


def _clean_orch(_data_dir):
    adapters = [
        {"protocol": p, "apy_pct": 4.0, "tvl_usd": 1e7,
         "tier": "T1" if p == "aave_v3" else "T2", "status": "ok"}
        for p in _CLEAN_TARGET
    ]
    return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")


class _CleanAllocator:
    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(_CLEAN_TARGET),
            target_weights={p: v / 100_000 for p, v in _CLEAN_TARGET.items()},
            expected_apy_pct=4.0, model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _time_calls(fn, iterations: int, warmup: int = 2) -> tuple[float, float]:
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


def _bench_cycle(iterations: int) -> tuple[float, float]:
    from spa_core.paper_trading import cycle_runner as cr
    sbx = Path(tempfile.mkdtemp(prefix="spa_perf_cycle_"))
    counter = {"n": 11}

    def _one():
        # advance a day each call so we time the append path, not the idempotent
        # same-day short-circuit.
        n = counter["n"]
        counter["n"] += 1
        cr.run_cycle(
            data_dir=str(sbx),
            now=datetime(2026, 6, min(n, 28), 8, tzinfo=timezone.utc),
            orchestrator_fn=_clean_orch,
            allocator=_CleanAllocator(),
            risk_scorer_fn=lambda d: None,
            track_persister_fn=lambda d: None,
            write=True,
            allow_live_write=False,
        )

    try:
        return _time_calls(_one, iterations)
    finally:
        import shutil
        shutil.rmtree(sbx, ignore_errors=True)


def _bench_allocator(iterations: int) -> tuple[float, float]:
    from spa_core.allocator.allocator import StrategyAllocator
    adapters_snapshot = {
        "adapters": [
            {"protocol": f"p{i}", "status": "ok", "apy_pct": 3.0 + i,
             "tvl_usd": 5e7, "tier": "T1" if i % 2 else "T2"}
            for i in range(6)
        ]
    }
    sbx = Path(tempfile.mkdtemp(prefix="spa_perf_alloc_"))
    status_path = sbx / "adapter_orchestrator_status.json"
    status_path.write_text(json.dumps(adapters_snapshot), encoding="utf-8")

    def _make():
        return StrategyAllocator(
            status_path=status_path,
            risk_scores_path=sbx / "__none__.json",
            registry_path=sbx / "__none__.json",
            strategy_loop_enabled=False,
            live_apy_provider=False,
            allocation_model="best_apy",
        )

    def _one():
        _make().allocate()

    try:
        return _time_calls(_one, iterations)
    finally:
        import shutil
        shutil.rmtree(sbx, ignore_errors=True)


def _bench_reconcile(iterations: int) -> tuple[float, float]:
    from spa_core.execution import reconciliation as recon
    from spa_core.audit import hash_chain
    # redirect the best-effort audit append to a throwaway file (never live data/).
    sbx = Path(tempfile.mkdtemp(prefix="spa_perf_recon_"))
    hash_chain._CHAIN = sbx / "audit_chain.jsonl"  # noqa: SLF001
    current = {"aave_v3": 40_000.0, "compound_v3": 30_000.0, "cash": 30_000.0}
    target = {"aave_v3": 30_000.0, "compound_v3": 40_000.0, "cash": 30_000.0}

    def _one():
        recon.round_trip(current=current, target=target, write=False,
                         ts="2026-06-28T00:00:00+00:00")

    try:
        return _time_calls(_one, iterations)
    finally:
        import shutil
        shutil.rmtree(sbx, ignore_errors=True)


def _bench_api(iterations: int) -> dict[str, tuple[float, float]]:
    """Time each key read-only endpoint via an in-process TestClient (sandbox)."""
    try:
        from fastapi.testclient import TestClient
        import spa_core.api.server as server
    except Exception:  # noqa: BLE001 — fastapi optional
        return {}

    sbx = Path(tempfile.mkdtemp(prefix="spa_perf_api_"))
    server._DATA_DIR = sbx  # redirect every router read to the empty sandbox
    out: dict[str, tuple[float, float]] = {}
    with TestClient(server.app) as client:
        for ep in ("/health", "/api/execution/readiness", "/api/redteam",
                   "/api/captured-book", "/api/optimizer-ab", "/api/v1/day30"):
            def _one(_ep=ep):
                r = client.get(_ep)
                assert r.status_code in (200, 422), f"{_ep} -> {r.status_code}"
            out[f"api:{ep}"] = _time_calls(_one, iterations)
    import shutil
    shutil.rmtree(sbx, ignore_errors=True)
    return out


def run_budget(iterations: int = 12) -> dict:
    logging.disable(logging.CRITICAL)
    try:
        measured: dict[str, tuple[float, float]] = {}
        measured["cycle"] = _bench_cycle(iterations)
        measured["allocator"] = _bench_allocator(iterations)
        measured["reconcile"] = _bench_reconcile(iterations)
        measured.update(_bench_api(iterations))
    finally:
        logging.disable(logging.NOTSET)

    rows = []
    all_ok = True
    for name, (median, p95) in measured.items():
        budget = BUDGETS_MS.get(name)
        ok = budget is None or median <= budget
        all_ok = all_ok and ok
        rows.append({
            "surface": name, "median_ms": median, "p95_ms": p95,
            "budget_ms": budget,
            "headroom_pct": (round(100.0 * (1 - median / budget), 1)
                             if budget else None),
            "ok": ok,
        })
    return {
        "module": "perf_budget", "version": "v1.0",
        "iterations": iterations, "rows": rows, "pass": all_ok,
        "over_budget": [r["surface"] for r in rows if not r["ok"]],
    }


def _print(report: dict) -> None:
    print("=" * 74)
    print("SPA PERF BUDGET (WS-6.5) — money-path + key-endpoint latency, gated")
    print("=" * 74)
    print(f" iterations: {report['iterations']}  (median timed after warmup)")
    print("-" * 74)
    print(f" {'surface':<34}{'median':>9}{'p95':>9}{'budget':>9}  status")
    for r in report["rows"]:
        b = f"{r['budget_ms']:.0f}" if r["budget_ms"] is not None else "  -"
        mark = "OK" if r["ok"] else "OVER"
        print(f" {r['surface']:<34}{r['median_ms']:>8.1f}{r['p95_ms']:>9.1f}"
              f"{b:>9}  [{mark}]")
    print("-" * 74)
    if report["over_budget"]:
        print(f" OVER BUDGET: {', '.join(report['over_budget'])}")
    print(f" GATE: {'PASS' if report['pass'] else 'FAIL'}")
    print("=" * 74)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="SPA perf-budget gate (WS-6.5) — assert money-path + key "
                    "endpoint latency stays under documented budgets (sandbox).")
    p.add_argument("--iterations", type=int, default=12)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    report = run_budget(iterations=args.iterations)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print(report)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

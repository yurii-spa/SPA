"""
spa_core/dfb/paper_dfb.py — WS-1.5: the DFB daily capture AGENT entrypoint (one tick).

One run: (1) build the pool universe, (2) overlay every pool through the SPA engine (proof-chained),
(3) write the shared-contract artifacts (data/dfb/pools.json + data/dfb/pool/<id>.json), and
(4) append ONE idempotent, proof-chained history record per pool for today's UTC day. Re-running the
same UTC day is a NO-OP on the history (idempotent), so a KeepAlive / retried agent never double-
appends.

Advisory: capital is NEVER moved; the go-live track (equity_curve_daily / golive_status / trades) is
NEVER touched; writes are confined to data/dfb/. stdlib only · deterministic · fail-CLOSED · atomic.

Run (the launchd agent calls this via the bash wrapper):
    python3 -m spa_core.dfb.paper_dfb
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime

from spa_core.dfb import PoolOverlay, RiskClass
from spa_core.dfb import history as dfb_history
from spa_core.dfb import risk_overlay


def run_tick(capture_date=None) -> dict:
    """One capture tick. Returns a small summary dict. Idempotent per UTC day on the history chain."""
    if capture_date is None:
        capture_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()

    # (1)+(2)+(3) — build + overlay + write the shared-contract artifacts (atomic, data/dfb/ only).
    result = risk_overlay.build_and_write(write=True)

    # rebuild the overlay objects for the history append (deterministic — same inputs).
    from spa_core.dfb import pool_universe
    pools = pool_universe.build_universe()
    overlays = risk_overlay.build_overlays(pools)

    # (4) — append one idempotent, proof-chained record per pool for today.
    cap = dfb_history.capture_all(overlays, capture_date=capture_date)

    return {
        "capture_date": capture_date,
        "n_pools": result["n_pools"],
        "n_flagged": result["n_flagged"],
        "n_refused": result["n_refused"],
        "chain_valid": result["chain_valid"],
        "history_appended": cap["n_appended"],
        "history_skipped": cap["n_skipped"],
    }


def main() -> int:
    summary = run_tick()
    print("DFB capture tick (advisory; read-only; writes only data/dfb/)")
    for k, v in summary.items():
        print(f"  {k:>18s}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

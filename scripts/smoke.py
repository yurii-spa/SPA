#!/usr/bin/env python3
"""
scripts/smoke.py — the FAST (<60s) "is the desk alive & honest" end-to-end check.

The SINGLE command the owner (or CI) runs to confirm health in under a minute. Unlike the heavier
smoke_test_flagship.py (which runs the live engine + an npm build), this is a lean, READ-ONLY,
no-network, no-mutation smoke that exercises the load-bearing surfaces and the standing red-team:

  STEP 1  RED-TEAM      — run the rotating red-team scenarios against SANDBOX copies (every surface
                          red-teams itself). Live data/ is snapshotted before/after; a single byte
                          changed FAILS. Each seeded forgery MUST be caught.
  STEP 2  PROOF         — re-derive the published decision-chain head with the zero-dependency
                          verify_spa.py over the LIVE public files (read-only) → the chain reproduces.
  STEP 3  API           — hit /api/redteam + /api/rates-desk/proof + /api/live/ping via the FastAPI
                          TestClient (no network): 200s, fail-closed shapes, no 500s.
  STEP 4  DASHBOARD     — the dashboard data-integrity contract: the published mirror verifies as ONE
                          chain (the same verdict the integrity badge reads), and a tampered copy
                          (sandbox) flips it to broken (the badge would read INTEGRITY BROKEN).
  STEP 5  KILL-SWITCH   — the deterministic drawdown ladder classifies a healthy curve NONE and a
                          >10% crash HARD_KILL (the safety floor cannot be talked out of a kill).

Exit 0 = the desk is alive & honest; 1 = any check failed. One-screen summary.

Deterministic, idempotent, safe to re-run. READ-ONLY against live data/ (the red-team writes only
sandbox tmp dirs; verify_spa + the contract checks only READ live files). stdlib + repo deps only.
LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_VERIFY_SPA = _ROOT / "scripts" / "verify_spa.py"
_LIVE_RD = _ROOT / "data" / "rates_desk"

FAILS: List[str] = []
NOTES: List[str] = []


def _fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"  ✗ FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _note(msg: str) -> None:
    NOTES.append(msg)
    print(f"  · {msg}")


def _load_verify_spa():
    spec = importlib.util.spec_from_file_location("_smoke_verify_spa", str(_VERIFY_SPA))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ════════════════════════════════════════════════════════════════════════════════════════════════
# STEP 1 — RED-TEAM (the standing adversarial harness, sandbox-only, live data untouched)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def step1_redteam() -> None:
    print("\n[1/5] Red-team — every surface red-teams itself (sandbox; live data untouched)")
    try:
        from spa_core.redteam.runner import run_all
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not import the red-team runner: {exc}")
        return
    verdict = run_all(check_live_untouched=True)
    if not verdict["live_data_untouched"]:
        _fail(f"red-team MUTATED live data/: {verdict['live_data_mutated_files']}")
    else:
        _ok("live data/ untouched by the red-team (read-only guard held)")
    if verdict["ok"]:
        _ok(f"all {verdict['n']} seeded forgeries CAUGHT ({verdict['n_caught']}/{verdict['n']})")
    else:
        _fail(f"red-team verdict FAIL — {verdict['n_failed']} scenario(s) did not catch their forgery")
        for f in verdict["findings"]:
            if not f["ok"]:
                why = f["error"] or ("control-failed: " + f["evidence"] if not f["control_ok"]
                                     else "UNCAUGHT: " + f["evidence"])
                _fail(f"  {f['surface']}/{f['scenario']}: {why}")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# STEP 2 — PROOF (verify_spa re-derives the live published chain head, read-only)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def step2_proof() -> None:
    print("\n[2/5] Proof — zero-dependency verify_spa.py re-derives the LIVE chain head (read-only)")
    if not _LIVE_RD.exists():
        _note("no live data/rates_desk/ — skipping (fresh checkout)")
        return
    V = _load_verify_spa()
    report = V.run([str(_LIVE_RD)])
    dc = report.get("decision_chain") or {}
    if dc.get("valid"):
        _ok(f"decision chain reproduces: length={dc.get('length')}, "
            f"head={str(dc.get('head_hash'))[:16]}…")
    elif dc.get("length") in (0, None):
        _note("live decision chain empty (no decisions yet) — vacuously valid")
    else:
        _fail(f"live decision chain does NOT reproduce: broken_at={dc.get('broken_at')} "
              f"(errors={report.get('errors')})")
    # the whole rates-desk subtree must be internally consistent (no coverage/proof failure).
    if not report.get("ok"):
        # an empty/absent chain reports ok via the no-files path; only flag real reproduction errors.
        errs = [e for e in report.get("errors", []) if "no recognizable public files" not in e]
        if errs:
            _fail(f"verify_spa over live data/rates_desk/ reported errors: {errs}")
        else:
            _ok("verify_spa: no reproduction errors over live rates-desk surfaces")
    else:
        _ok("verify_spa: live rates-desk surfaces all reproduce (ok=True)")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# STEP 3 — API (TestClient, no network): fail-closed shapes, no 500s
# ════════════════════════════════════════════════════════════════════════════════════════════════
def step3_api() -> None:
    print("\n[3/5] API — TestClient (no network): /api/redteam, /api/rates-desk/proof, /api/live/ping")
    try:
        from fastapi.testclient import TestClient
        from spa_core.api.server import app
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not import FastAPI app / TestClient: {exc}")
        return
    client = TestClient(app)

    # /api/redteam — fail-closed envelope (available true/false, never a 500, never a fabricated pass)
    r = client.get("/api/redteam")
    if r.status_code != 200:
        _fail(f"GET /api/redteam → {r.status_code} (expected 200)")
    else:
        j = r.json()
        if "available" not in j:
            _fail(f"/api/redteam missing 'available' (have {sorted(j.keys())})")
        elif j.get("available") and j.get("ok") is False:
            _fail("/api/redteam reports a published FAIL verdict — the desk has an unaddressed hole")
        else:
            state = ("published ok=%s" % j.get("ok")) if j.get("available") else "no run published yet"
            _ok(f"GET /api/redteam → 200, fail-closed envelope ({state})")

    # /api/rates-desk/proof — verified shape (graceful when no chain yet)
    r = client.get("/api/rates-desk/proof")
    if r.status_code != 200:
        _fail(f"GET /api/rates-desk/proof → {r.status_code} (expected 200)")
    else:
        j = r.json()
        if "verified" not in j:
            _fail(f"/api/rates-desk/proof missing 'verified' (have {sorted(j.keys())})")
        elif j.get("verified") is False and j.get("chain_length"):
            _fail(f"/api/rates-desk/proof verified=False on a non-empty chain "
                  f"(broken_at={j.get('broken_at')})")
        else:
            _ok(f"GET /api/rates-desk/proof → 200, verified={j.get('verified')}, "
                f"chain_length={j.get('chain_length')}")

    # /api/live/ping — liveness
    r = client.get("/api/live/ping")
    if r.status_code != 200:
        _fail(f"GET /api/live/ping → {r.status_code} (expected 200)")
    else:
        _ok("GET /api/live/ping → 200 (API alive)")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# STEP 4 — DASHBOARD data-integrity contract (the badge verdict + tamper flips it, sandbox)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def step4_dashboard_contract() -> None:
    print("\n[4/5] Dashboard — data-integrity contract (badge verdict + tamper flips it)")
    try:
        from spa_core.strategy_lab.rates_desk import proof_chain as PC
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not import proof_chain: {exc}")
        return

    # The contract the integrity badge reads: a healthy mirror verifies as ONE chain.
    bodies = [
        {"kind": "ENTRY", "approved": True, "underlying": "susde", "as_of": "2026-06-28"},
        {"kind": "REFUSAL", "approved": False, "underlying": "ezeth", "as_of": "2026-06-28"},
    ]
    rows = PC._rebase_rows([{"ts": "2026-06-28T00:00:00+00:00", **b} for b in bodies])
    healthy = PC.verify_mirror(rows)
    if healthy.get("valid"):
        _ok("integrity contract: a healthy mirror verifies as ONE chain (badge → green)")
    else:
        _fail(f"integrity contract: a HEALTHY mirror reported broken (false red badge): {healthy}")

    # A tampered copy must flip verified → False (the badge would read INTEGRITY BROKEN).
    tampered = [dict(r) for r in rows]
    tampered[1] = dict(tampered[1], approved=True, underlying="ezeth_flipped")
    bad = PC.verify_mirror(tampered)
    if (not bad.get("valid")) and bad.get("broken_at") == 1:
        _ok("integrity contract: a tampered mirror flips verified→False (badge → INTEGRITY BROKEN)")
    else:
        _fail(f"integrity contract: a TAMPERED mirror was NOT caught: {bad}")


# ════════════════════════════════════════════════════════════════════════════════════════════════
# STEP 5 — KILL-SWITCH ladder (deterministic safety floor)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def step5_kill_switch() -> None:
    print("\n[5/5] Kill-switch — deterministic drawdown ladder (NONE healthy, HARD_KILL on crash)")
    try:
        from spa_core.governance import kill_switch as KS
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not import kill_switch: {exc}")
        return

    def _bar(day: int, close: float) -> dict:
        return {"date": f"2026-06-{day:02d}", "close_equity": close, "open_equity": close,
                "source": "live", "evidenced": True}

    healthy = [_bar(10 + i, 100_000.0 + i * 50.0) for i in range(12)]
    tier_h, _ = KS.drawdown_tier(healthy)
    if tier_h == KS.TIER_NONE:
        _ok("healthy evidenced curve → TIER_NONE (no false kill)")
    else:
        _fail(f"healthy curve mis-classified {tier_h} (false kill)")

    crash = [_bar(10 + i, 100_000.0 + i * 100.0) for i in range(6)]
    crash.append(_bar(16, 88_000.0))  # ≈ −12.4% from the ≈100,500 peak
    tier_c, reason = KS.drawdown_tier(crash)
    if tier_c == KS.TIER_HARD_KILL:
        _ok(f"≈−12.4% evidenced crash → TIER_HARD_KILL ({reason})")
    else:
        _fail(f"a >{KS.DRAWDOWN_THRESHOLD_PCT}% crash did NOT escalate to HARD_KILL (got {tier_c})")


# ════════════════════════════════════════════════════════════════════════════════════════════════
def main() -> int:
    t0 = time.time()
    print("SPA SMOKE — is the desk alive & honest? (fast, read-only, no-network)")
    print(f"repo: {_ROOT}")
    print(f"python: {sys.executable}")

    step1_redteam()
    step2_proof()
    step3_api()
    step4_dashboard_contract()
    step5_kill_switch()

    elapsed = time.time() - t0
    print("\n" + "=" * 84)
    if NOTES:
        print(f"notes: {len(NOTES)} (non-fatal)")
    print(f"elapsed: {elapsed:.1f}s  (budget < 60s)")
    if elapsed > 60:
        print("  ⚠ smoke exceeded the 60s budget — investigate slow path")
    print(f"DESK ALIVE & HONEST: {'YES' if not FAILS else 'NO'}")
    print(f"SMOKE: {'PASS' if not FAILS else 'FAIL'}"
          + ("" if not FAILS else f"  ({len(FAILS)} failure(s))"))
    if FAILS:
        print("\nFAILURES:")
        for i, f in enumerate(FAILS, 1):
            print(f"  {i}. {f}")
    print("=" * 84)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())

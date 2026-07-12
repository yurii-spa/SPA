"""Tier-1 router — verifiable NAV / packages / validation surfaces.

Behavior-preserving extraction from server.py. Every handler is a graceful
read_state passthrough (missing/corrupt file → the same default payload as before),
with the additive honesty `meta` on /nav and /packages kept byte-identical.
"""

from __future__ import annotations

from fastapi import APIRouter

from spa_core.api._shared import backtest_meta, now, read_state

router = APIRouter(tags=["tier1"])


@router.get("/api/tier1/nav")
def get_tier1_nav():
    """Verifiable NAV / proof-of-reserves snapshot — anyone can recompute from components."""
    nav = read_state("tier1_nav_proof.json", {
        "generated_at": now(), "computed_nav_usd": None, "reconciliation_ok": None,
    })
    if isinstance(nav, dict):
        nav.setdefault("meta", {
            "track_basis": "paper, advisory",
            "is_realized": False,
            "evidence_note": "see /track-record for which days are live-cycle-evidenced "
                             "vs backfill",
        })
    return nav


@router.get("/api/tier1/packages")
def get_tier1_packages():
    """Tier-1 risk-tier packages (Conservative/Balanced/Aggressive) — data/tier1_packages.json."""
    _pkg_meta = backtest_meta(
        basis="real-data backtest, net-of-cost, out-of-sample + capacity-validated; "
              "risk-tier packages, NOT realized capital",
        period="tier-1 backtest validation window",
    )
    pkgs = read_state("tier1_packages.json", {
        "generated_at": now(), "model": "tier1_packages", "packages": {},
        "note": "Tier-1 packages not yet generated (run the backtest pipeline).",
    })
    if isinstance(pkgs, dict):
        pkgs.setdefault("meta", _pkg_meta)
    return pkgs


@router.get("/api/tier1/verdict")
def get_tier1_verdict():
    """Full Tier-1 verdict over the tournament — data/tier1_verdict.json."""
    return read_state("tier1_verdict.json", {
        "generated_at": now(), "model": "tier1_parallel", "leaderboard_tier1": [],
    })


@router.get("/api/tier1/gate")
def get_tier1_gate():
    """Backtest→paper eligibility gate + live-vs-backtest divergence — data/tier1_gate.json."""
    return read_state("tier1_gate.json", {
        "generated_at": now(), "gate": "tier1_backtest_to_paper",
        "eligible_for_paper": [], "blocked": {},
    })


@router.get("/api/tier1/status")
def get_tier1_status():
    """One-glance Tier-1 rollup (regime, eligible, packages, integrity, divergence)."""
    return read_state("tier1_status.json", {
        "generated_at": now(), "model": "tier1_status", "health": "unknown", "packages": {},
    })


@router.get("/api/tier1/reverse-stress")
def get_tier1_reverse_stress():
    """Inverse stress test — minimal shock that breaches loss tolerance — data/tier1_reverse_stress.json."""
    return read_state("tier1_reverse_stress.json", {
        "generated_at": now(), "model": "tier1_reverse_stress", "strategies": {},
    })


@router.get("/api/tier1/walk-forward")
def get_tier1_walk_forward():
    """Walk-forward out-of-sample validation (consistency, robustness, capacity) — data/tier1_walk_forward.json."""
    return read_state("tier1_walk_forward.json", {
        "generated_at": now(), "model": "tier1_walk_forward", "strategies": {},
    })


@router.get("/api/tier1/correlation")
def get_tier1_correlation():
    """Cross-strategy / package correlation matrix — data/tier1_correlation.json."""
    return read_state("tier1_correlation.json", {
        "generated_at": now(), "model": "tier1_correlation", "packages": {},
    })


@router.get("/api/tier1/monte-carlo")
def get_tier1_monte_carlo():
    """Block-bootstrap Monte-Carlo path simulation — data/tier1_monte_carlo.json."""
    return read_state("tier1_monte_carlo.json", {
        "generated_at": now(), "model": "tier1_monte_carlo", "strategies": {},
    })


@router.get("/api/tier1/var")
def get_tier1_var():
    """Value-at-Risk / CVaR (yield + principal) per validated strategy — data/tier1_var.json."""
    return read_state("tier1_var.json", {
        "generated_at": now(), "model": "tier1_var", "strategies": [],
    })


@router.get("/api/tier1/limits")
def get_tier1_limits():
    """Risk-limit gate (HHI, concentration, tier aggregates, cash floor) — data/tier1_limits.json."""
    return read_state("tier1_limits.json", {
        "generated_at": now(), "model": "tier1_limits", "limits": {}, "current_portfolio": {},
    })


@router.get("/api/tier1/attribution")
def get_tier1_attribution():
    """In-sample vs out-of-sample return attribution — data/tier1_attribution.json."""
    return read_state("tier1_attribution.json", {
        "generated_at": now(), "model": "tier1_attribution", "strategies": {},
    })


@router.get("/api/tier1/benchmark")
def get_tier1_benchmark():
    """Strategy returns vs Aave / risk-free benchmark — data/tier1_benchmark.json."""
    return read_state("tier1_benchmark.json", {
        "generated_at": now(), "model": "tier1_benchmark", "results": {},
    })


@router.get("/api/tier1/regime")
def get_tier1_regime():
    """Market regime classification + per-regime yield — data/tier1_regime.json."""
    return read_state("tier1_regime.json", {
        "generated_at": now(), "model": "tier1_regime", "current": None, "labels": [],
    })


@router.get("/api/tier1/proof")
def get_tier1_proof():
    """THE Tier-1 proof panel — the one-stop "why you can trust the conservative tier" surface.

    Aggregates (verbatim, fail-closed — a missing artifact is reported missing, never invented):
      • evidenced track state (go-live gate pass count + evidenced days, from golive_status.json)
      • track continuity (gap_monitor.json)
      • the swarm's SHADOW guardian on the LIVE conservative track (signal-only, zero authority)
      • the S2 lead-time evidence ledger INCLUDING false alarms (the cost side, same weight)
      • how to verify all of it INDEPENDENTLY (scripts/verify_spa.py, zero-dependency)

    This is the Tier-1 differentiator surface: not a yield claim, a VERIFIABILITY claim.
    Numbers themselves stay owner-gated on /packages; this panel only exposes proof states.
    """
    golive = read_state("golive_status.json", {}) or {}
    gap = read_state("gap_monitor.json", {}) or {}
    guardian = read_state("swarm/guardian_forward.json", {}) or {}
    leadtime = read_state("swarm/leadtime_evidence.json", {}) or {}

    shadow_lt = ((guardian.get("shadow") or {}).get("live_track") or {})
    checks = golive.get("checks") or golive.get("criteria") or {}
    passed = golive.get("passed") or golive.get("n_passed")
    total = golive.get("total") or golive.get("n_total")
    if passed is None and isinstance(checks, dict) and checks:
        vals = list(checks.values())
        passed = sum(1 for v in vals
                     if (isinstance(v, dict) and v.get("pass")) or v is True)
        total = len(vals)

    return {
        "generated_at": now(),
        "model": "tier1_proof_panel",
        "is_advisory": True,
        "claim": ("verifiability, not yield: every number below is backed by a hash-chained "
                  "artifact you can re-derive yourself with the standalone verifier"),
        "golive_gate": {
            "available": bool(golive),
            "passed": passed, "total": total,
            "ready": golive.get("ready", golive.get("go_live_ready")),
        },
        "track_continuity": {
            "available": bool(gap),
            "status": gap.get("status"),
            "gap_detected": gap.get("gap_detected"),
            "days_count": gap.get("days_count"),
            "last_entry_date": gap.get("last_entry_date"),
        },
        "shadow_guardian_live_track": {
            "available": bool(shadow_lt),
            "state": shadow_lt.get("state"),
            "vol_ratio": (shadow_lt.get("signal") or {}).get("ratio"),
            "days_watched": shadow_lt.get("days"),
            "authority": "NONE — signal-only; RiskPolicy v1.0 is the sole gate (see charter)",
        },
        "leadtime_ledger": {
            "available": bool(leadtime),
            "state": leadtime.get("state"),
            "score": leadtime.get("score"),
            "false_alarms": leadtime.get("false_alarms"),
            "honesty": "false alarms are published with the same weight as saves — "
                       "an alarm-heavy ledger argues AGAINST the signal, and we will say so",
        },
        "verify_yourself": {
            "tool": "scripts/verify_spa.py (standalone, zero-dependency, no spa_core import)",
            "command": "python3 verify_spa.py <data-dir> --expect-surfaces A,D,I",
            "covers": "decision chain (A) · evidenced equity track (D) · swarm decision chains (I) "
                      "— any forged/edited/dropped historical row diverges the recompute",
        },
    }

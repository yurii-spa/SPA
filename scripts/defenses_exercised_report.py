#!/usr/bin/env python3
"""Defenses-exercised report (Q2-1) — prove the safety machinery FIRES.

The live paper track is monotonic (every evidenced day positive, ~0% drawdown),
so the kill-switch / soft-de-risk / hard-kill gates have NEVER fired on the real
curve. For a desk whose edge is HONEST RISK MEASUREMENT, a perfectly smooth curve
with zero exercised defenses is a credibility liability, not a strength. This
report drives the SAME production governance code the daily cycle uses
(``spa_core.governance.kill_switch`` + ``spa_core.paper_trading.cycle_gates``)
through a labelled stress matrix and asserts every defense fires at the right
threshold — a reproducible, third-party-runnable proof that the machinery works.

  * Uses the REAL functions (not mocks): ``drawdown_tier``,
    ``KillSwitchChecker.check_drawdown_trigger``, ``apply_soft_derisk_gate``.
  * Deterministic + stdlib-only + INERT: synthetic curves built with
    pre_cutover_gate's evidenced-bar helper; the kill-switch runs against a
    throwaway sandbox data_dir; the live ``data/`` track is never mutated.
  * Emits ``data/defenses_exercised.json`` (a report artifact, like
    pre_cutover_gate.json) + a human summary.
  * Exit 0 ⇔ every defense fired as expected; exit 1 ⇔ a defense did NOT fire
    (the report names it) — so anyone can run it and trust exit 0.

    python3 scripts/defenses_exercised_report.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.governance.kill_switch import (  # noqa: E402
    KillSwitchChecker,
    drawdown_tier,
    evidenced_drawdown_pct,
    SOFT_DERISK_THRESHOLD_PCT,
    DRAWDOWN_THRESHOLD_PCT,
    TIER_NONE,
    TIER_SOFT_DERISK,
    TIER_HARD_KILL,
)
from spa_core.paper_trading.cycle_gates import apply_soft_derisk_gate  # noqa: E402
from spa_core.paper_trading.pre_cutover_gate import _curve_for_drawdown  # noqa: E402

_OUT = _ROOT / "data" / "defenses_exercised.json"


def _row(scenario: str, family: str, fn: str, expected: str, actual: str, detail: str = "") -> dict:
    return {
        "scenario": scenario,
        "family": family,
        "governance_fn": fn,
        "expected": expected,
        "actual": actual,
        "fired": expected == actual,
        "detail": detail,
    }


def run() -> dict:
    rows: list[dict] = []

    # ── Family 1: the two-tier drawdown ladder (the REAL classifier) ──────────
    # SOFT band [5%, 10%), HARD >= 10% (ADR-048, inclusive). Values chosen clearly
    # in-band so the proof is deterministic (no float-boundary flake).
    ladder = [
        (0.0, TIER_NONE), (2.0, TIER_NONE),
        (6.0, TIER_SOFT_DERISK), (8.0, TIER_SOFT_DERISK),
        (12.0, TIER_HARD_KILL), (20.0, TIER_HARD_KILL),
    ]
    for pct, expected in ladder:
        curve = _curve_for_drawdown(pct)
        tier, reason = drawdown_tier(curve)
        dd = evidenced_drawdown_pct(curve)
        rows.append(_row(
            f"drawdown_{pct:g}pct", "drawdown_ladder", "kill_switch.drawdown_tier",
            expected, tier, f"evidenced drawdown={dd:.2f}% → {reason}",
        ))

    # ── Family 2: HARD kill trigger fires all-cash at a deep drawdown ─────────
    with tempfile.TemporaryDirectory(prefix="spa_defenses_") as sandbox:
        checker = KillSwitchChecker(data_dir=sandbox)  # INERT: throwaway dir, never live data/
        deep = _curve_for_drawdown(15.0)
        triggered, why = checker.check_drawdown_trigger(deep)
        rows.append(_row(
            "hard_kill_at_15pct", "hard_kill", "KillSwitchChecker.check_drawdown_trigger",
            "TRIGGERED", "TRIGGERED" if triggered else "NOT_TRIGGERED", why,
        ))
        shallow = _curve_for_drawdown(3.0)
        trig2, why2 = checker.check_drawdown_trigger(shallow)
        rows.append(_row(
            "hard_kill_held_at_3pct", "hard_kill", "KillSwitchChecker.check_drawdown_trigger",
            "NOT_TRIGGERED", "NOT_TRIGGERED" if not trig2 else "TRIGGERED",
            "a 3% drawdown must NOT trigger the hard kill (below the 10% rung)",
        ))

    # ── Family 3: SOFT de-risk gate halts NEW + INCREASE, holds/reduces OK ────
    held = {"aave_v3": 40000.0, "morpho_steakhouse": 5000.0}
    target = {
        "aave_v3": 55000.0,           # allocator wants to INCREASE → must clamp to 40000 (held)
        "morpho_steakhouse": 3000.0,  # allocator REDUCES → left intact (allowed)
        "pendle": 10000.0,            # brand-NEW protocol → must be forced to 0
    }
    notes: list[str] = []
    gated = apply_soft_derisk_gate(dict(target), current_positions=held, derisk_active=True, notes=notes)
    ok_increase = gated.get("aave_v3") == 40000.0
    ok_new = gated.get("pendle") == 0.0
    ok_reduce = gated.get("morpho_steakhouse") == 3000.0
    rows.append(_row(
        "soft_derisk_blocks_increase", "soft_derisk", "cycle_gates.apply_soft_derisk_gate",
        "clamped_to_held(40000)", f"{gated.get('aave_v3')}", "no INCREASE under soft de-risk",
    ))
    rows.append(_row(
        "soft_derisk_blocks_new", "soft_derisk", "cycle_gates.apply_soft_derisk_gate",
        "forced_to_0", f"{gated.get('pendle')}", "no NEW protocol under soft de-risk",
    ))
    rows.append(_row(
        "soft_derisk_allows_reduce", "soft_derisk", "cycle_gates.apply_soft_derisk_gate",
        "left_intact(3000)", f"{gated.get('morpho_steakhouse')}", "a REDUCE is still allowed",
    ))
    # normalise the fired flags for the numeric soft-derisk rows
    rows[-3]["fired"] = ok_increase
    rows[-2]["fired"] = ok_new
    rows[-1]["fired"] = ok_reduce

    all_fired = all(r["fired"] for r in rows)

    # ── Honest contrast: the SAME classifier on the REAL live curve (if present) ──
    live_note = None
    try:
        eq = json.loads((_ROOT / "data" / "equity_curve_daily.json").read_text())
        bars = eq.get("bars") or eq.get("curve") or eq.get("daily") or []
        if bars:
            live_tier, _ = drawdown_tier(bars)
            live_dd = evidenced_drawdown_pct(bars)
            live_note = (
                f"On the REAL live evidenced curve the same classifier returns {live_tier} "
                f"(drawdown={live_dd:.2f}%) — the defenses have not fired because the track never "
                f"stressed, NOT because they are absent. This report proves they fire when it does."
            )
    except Exception:
        live_note = "live curve unavailable (report is fully reproducible from the synthetic matrix alone)"

    return {
        "report": "defenses_exercised",
        "purpose": "prove the production kill-switch / de-risk gates FIRE on stress (the monotonic "
                   "live curve cannot demonstrate this)",
        "thresholds": {
            "soft_derisk_pct": SOFT_DERISK_THRESHOLD_PCT,
            "hard_kill_pct": DRAWDOWN_THRESHOLD_PCT,
            "hard_kill_inclusive": True,
        },
        "governance_modules": [
            "spa_core.governance.kill_switch",
            "spa_core.paper_trading.cycle_gates",
        ],
        "all_defenses_fired": all_fired,
        "scenarios_total": len(rows),
        "scenarios_fired": sum(1 for r in rows if r["fired"]),
        "live_curve_contrast": live_note,
        "reproduce": "python3 scripts/defenses_exercised_report.py  (deterministic, stdlib-only, inert)",
        "scenarios": rows,
    }


def main() -> int:
    result = run()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = _OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(_OUT))
    print(f"[defenses_exercised] {result['scenarios_fired']}/{result['scenarios_total']} defenses fired "
          f"→ {_OUT}")
    for r in result["scenarios"]:
        mark = "✓" if r["fired"] else "✗"
        print(f"  {mark} [{r['family']}] {r['scenario']}: expected {r['expected']} → got {r['actual']}")
    if result["live_curve_contrast"]:
        print(f"  · {result['live_curve_contrast']}")
    return 0 if result["all_defenses_fired"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

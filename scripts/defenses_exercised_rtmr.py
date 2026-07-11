#!/usr/bin/env python3
"""Q2-13 — RTMR defenses-exercised report: prove the LIVE-MONITORING brakes FIRE.

`defenses_exercised_report.py` (Q2-1) proves the daily-cycle kill-switch / de-risk ladder fires. This
companion extends that "the brakes provably work" story to the REAL-TIME monitoring plane (RTMR): it
drives the SAME production reaction engine (`spa_core.monitoring.reaction.evaluate`) through a labelled
signal matrix and ASSERTS the right DE-RISK action fires for each sensor + severity — and that the whole
engine only ever de-risks (never raises exposure). A monotonic paper curve can't show the RTMR reactions
fire; this does, deterministically, without touching any live position.

Reaction ladder under test (reaction.py §5.2, all de-risk-only):
  • peg / tvl / liquidity  critical → FULL_EXIT ; warn → REDUCE
  • oracle                 critical → FREEZE    ; warn → TIGHTEN
  • ANY stale/blind sensor          → FREEZE (fail-closed, regardless of value)
  • N distinct hot scopes  (systemic)          → MARKET_EXIT (portfolio-wide)

Deterministic, stdlib-only, LLM-forbidden, fail-CLOSED. Writes data/defenses_exercised_rtmr.json atomic.
Advisory / read-only — drives the engine on synthetic signals, moves no capital.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.monitoring import signal as S  # noqa: E402
from spa_core.monitoring import reaction as R  # noqa: E402

_OUT = _ROOT / "data" / "defenses_exercised_rtmr.json"
_TS = 1_700_000_000  # fixed timestamp — determinism


def _sig(source: str, scope: str, severity: str, *, staleness_ok: bool = True):
    return S.make_signal(ts=_TS, source=source, scope=scope, metric=f"{source}_metric",
                         value=1.0, severity=severity, threshold_crossed=True, staleness_ok=staleness_ok)


def _action_for(signals) -> dict:
    """evaluate the signals and return {scope: action_kind} for assertion."""
    acts = R.evaluate(signals, {})
    # de-risk-only invariant must hold for EVERY produced action
    for a in acts:
        assert a.is_de_risk_only(), f"NON-DE-RISK action leaked: {a}"
    return {a.scope: a.kind for a in acts}


def _row(scenario: str, expected: str, actual: str, detail: str = "") -> dict:
    return {"scenario": scenario, "family": "rtmr_reaction", "expected": expected,
            "actual": actual, "fired": expected == actual, "detail": detail}


def run() -> dict:
    rows: list[dict] = []

    # single-sensor scenarios: (source, severity, scope, expected action)
    matrix = [
        ("peg", S.CRITICAL, "ethena:USDe", R.FULL_EXIT),
        ("peg", S.WARN, "ethena:USDe", R.REDUCE),
        ("tvl", S.CRITICAL, "aave_v3:USDC", R.FULL_EXIT),
        ("tvl", S.WARN, "aave_v3:USDC", R.REDUCE),
        ("liquidity", S.CRITICAL, "pendle:PT", R.FULL_EXIT),
        ("liquidity", S.WARN, "pendle:PT", R.REDUCE),
        ("oracle", S.CRITICAL, "chainlink:ETH", R.FREEZE),
        ("oracle", S.WARN, "chainlink:ETH", R.TIGHTEN),
    ]
    for source, sev, scope, expected in matrix:
        got = _action_for([_sig(source, scope, sev)]).get(scope, "NONE")
        rows.append(_row(f"{source} {sev} → de-risk", expected, got))

    # fail-closed: a STALE/blind sensor de-risks by FREEZE regardless of the (forced-critical) value
    got = _action_for([_sig("peg", "ethena:USDe", S.WARN, staleness_ok=False)]).get("ethena:USDe", "NONE")
    rows.append(_row("stale/blind sensor → FREEZE (fail-closed)", R.FREEZE, got))

    # INFO (fresh) is non-actionable → NO action (the engine must not over-react on noise)
    got = _action_for([_sig("peg", "ethena:USDe", S.INFO)])
    rows.append(_row("info fresh → no action (no over-reaction)", "NONE",
                     "NONE" if not got else next(iter(got.values()))))

    # systemic: 3 distinct hot scopes → portfolio-wide MARKET_EXIT
    systemic = [_sig("peg", "a:1", S.WARN), _sig("tvl", "b:2", S.WARN), _sig("liquidity", "c:3", S.WARN)]
    acts = _action_for(systemic)
    rows.append(_row("systemic (3 hot scopes) → MARKET_EXIT", R.MARKET_EXIT,
                     R.MARKET_EXIT if R.PORTFOLIO in acts else "NONE"))

    # rate-limit honesty: many STALE scopes (our own data outage) must NOT cascade to systemic MARKET_EXIT
    stale_many = [_sig("peg", f"x:{i}", S.WARN, staleness_ok=False) for i in range(3)]
    acts = _action_for(stale_many)
    rows.append(_row("3 STALE scopes → NO systemic exit (data-outage not cascaded)", "no_market_exit",
                     "no_market_exit" if R.PORTFOLIO not in acts else R.MARKET_EXIT))

    n_fired = sum(1 for r in rows if r["fired"])
    report = {
        "model": "defenses_exercised_rtmr",
        "is_advisory": True,
        "deterministic": True,
        "llm_forbidden": True,
        "purpose": ("prove the RTMR real-time de-risk reaction ladder FIRES (peg/tvl/oracle/liquidity + "
                    "stale + systemic) through the SAME production engine — de-risk-only, fail-closed. "
                    "Complements defenses_exercised.json (the daily-cycle kill ladder)."),
        "scenarios_total": len(rows),
        "scenarios_fired": n_fired,
        "all_fired": n_fired == len(rows),
        "de_risk_only_invariant": "enforced (every produced action asserted de-risk-only)",
        "scenarios": rows,
    }
    atomic_save(report, str(_OUT))
    return report


def main() -> int:
    r = run()
    print(f"[defenses_exercised_rtmr] {r['scenarios_fired']}/{r['scenarios_total']} RTMR reactions fired "
          f"({'ALL FIRE' if r['all_fired'] else 'MISMATCH'})")
    for row in r["scenarios"]:
        print(f"  {'✅' if row['fired'] else '❌'} {row['scenario']}: expected {row['expected']} → got {row['actual']}")
    return 0 if r["all_fired"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

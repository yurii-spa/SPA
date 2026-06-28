#!/usr/bin/env python3
"""
scripts/regenerate_rates_decision_log.py — regenerate the PUBLIC rates-desk decision log through the
CORRECTED structural-toxicity gate (red-team FAIL #1 fix).

The published data/rates_desk/decision_log.jsonl was written before the structural-veto fix, so it
could contain an APPROVED toxic LRT (the proven case: seq=63 ezETH, approved at $4,062 by sizing down
its liquidity haircut until the TOTAL haircut dipped under the cap, while its size-INDEPENDENT
structural tail sat at ~0.097 — toxicity sized around). The fix moved the toxicity verdict onto the
size-independent structural_haircut so it can't be sized around. This script re-applies that corrected
verdict to EVERY logged row PURELY from each row's own stored decomposition (no live feed, deterministic)
and re-bases the file into one coherent, independently-verifiable chain (docs/PROOF_CHAIN_SPEC.md §5).

A formerly-approved-but-structurally-toxic row is flipped to a structural TAIL_VETO refusal; every clean
row is preserved verbatim. Atomic write. Deterministic. stdlib-only, LLM-FORBIDDEN.

Run:
    python3 scripts/regenerate_rates_decision_log.py
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.strategy_lab.rates_desk import proof_chain  # noqa: E402


def main() -> int:
    summary = proof_chain.rewrite_log()
    print("Rates-Desk decision-log regeneration (structural-veto fix)")
    print(f"  rows                       : {summary['n_rows']}")
    print(f"  flipped to REFUSAL (toxic) : {summary['n_flipped']}")
    print(f"  toxic approvals remaining  : {summary['toxic_approvals_remaining']}")
    print(f"  chain verifies as one chain: {summary['valid']}")
    if summary["toxic_approvals_remaining"] != 0 or not summary["valid"]:
        print("  !! FAILED — toxic approvals remain or chain invalid")
        return 1
    print(f"  wrote {proof_chain._LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

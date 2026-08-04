"""
MP-1216: DeFiProtocolVaultPerformanceFeeGrossOfExitSlippageBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Thin wrapper: the gross-of-exit-slippage performance-fee base-gap engine lives in
``spa_core.analytics._fee_gap_core`` (one shared implementation for the whole
gross-of-<KIND> base-gap family; the 15-line formula was previously duplicated
per module). This module supplies the exit-slippage-specific vocabulary (input/output
key names, classification / recommendation / flag labels, the HIGH-rate
threshold and the ring-buffer log path) and re-exports the family-standard
public names unchanged. Behavior, dict shapes, rounding, sentinels and the
atomic ring-buffer log are identical to the pre-refactor module; the unit test
``spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_exit_slippage_base_gap_analyzer.py`` is unmodified and remains the equivalence
proof.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json  # noqa: F401  (used by the __main__ CLI block)
import os
from typing import List

from spa_core.analytics._fee_gap_core import (  # noqa: F401
    CLEAN_FRACTION,
    EPS,
    LOG_CAP,
    MILD_FRACTION,
    MODERATE_FRACTION,
    _clamp,
    _coerce_count,
    _coerce_num,
    _coerce_signed,
    _f,
    _grade_from_score,
    _mean,
    _safe_div,
    build_module_api,
)

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_performance_fee_gross_of_exit_slippage_base_gap_log.json"
)

# High-exit-slippage flag threshold on exit_slippage_rate_pct.
HIGH_EXIT_SLIPPAGE_PCT = 5.0

_api = build_module_api(
    class_name="DeFiProtocolVaultPerformanceFeeGrossOfExitSlippageBaseGapAnalyzer",
    log_path=LOG_PATH,
    high_threshold=HIGH_EXIT_SLIPPAGE_PCT,
    keys={
        "gross": "gross_yield_pct",
        "net": "net_of_exit_slippage_yield_pct",
        "consumed": "slippage_consumed_yield_pct",
        "gap": "fee_on_slippage_gap_pct",
        "fraction": "fee_on_slippage_fraction",
        "rate": "exit_slippage_rate_pct",
    },
    labels={
        "clean": "CLEAN_NET_OF_SLIPPAGE_BASE",
        "mild": "MILD_FEE_ON_SLIPPAGE_GAP",
        "moderate": "MODERATE_FEE_ON_SLIPPAGE_GAP",
        "severe": "SEVERE_FEE_ON_SLIPPAGE_GAP",
        "trust": "TRUST_FEE_STRUCTURE",
        "minor": "MINOR_FEE_ON_SLIPPAGE",
        "demand": "DEMAND_NET_OF_SLIPPAGE_BASE",
        "avoid": "AVOID_FEE_ON_SLIPPAGE",
        "high_flag": "HIGH_EXIT_SLIPPAGE",
        "fee_on_flag": "FEE_ON_EXIT_SLIPPAGE",
        "full_fee_on_flag": "FULL_FEE_ON_SLIPPAGE",
        "agg_worst": "worst_slippage_gap_vault",
    },
)

DeFiProtocolVaultPerformanceFeeGrossOfExitSlippageBaseGapAnalyzer = _api["analyzer_cls"]
_build_default_cfg = _api["_build_default_cfg"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_SLIPPAGE_BASE: net_of_exit_slip ≈ gross → exit slippage
            # consumed nothing, the performance fee was charged on the right base.
            "vault": "USDC-Vault-CleanNetBase",
            "gross_yield_pct": 18.0,
            "net_of_exit_slippage_yield_pct": 18.0,
            "performance_fee_pct": 20.0,
            "exit_slippage_rate_pct": 0.0,
        },
        {
            # MODERATE_FEE_ON_SLIPPAGE_GAP: gross 16, net 8 → ~half the fee was
            # charged on the slippage slice (fraction ~ 0.5).
            "vault": "stETH-Vault-ModerateSlippage",
            "gross_yield_pct": 16.0,
            "net_of_exit_slippage_yield_pct": 8.0,
            "performance_fee_pct": 20.0,
            "exit_slippage_rate_pct": 6.0,
        },
        {
            # SEVERE_FEE_ON_SLIPPAGE_GAP (net negative): exit slippage drove the
            # net-of-exit-slippage yield negative, yet the performance fee is
            # still charged on the gross yield → fair net return is negative.
            "vault": "GOV-Vault-SevereSlippage",
            "gross_yield_pct": 12.0,
            "net_of_exit_slippage_yield_pct": -3.0,
            "performance_fee_pct": 50.0,
            "exit_slippage_rate_pct": 12.0,
        },
        {
            # Override path: a fee-on-slippage gap supplied directly with the fee
            # charged → fraction = 5/12 ≈ 0.4167 → MODERATE.
            "vault": "LST-Vault-OverrideGap",
            "gross_yield_pct": 24.0,
            "fee_on_slippage_gap_pct": 5.0,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_exit_slippage_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1216 Vault Performance-Fee Gross-Of-Exit-Slippage-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfExitSlippageBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

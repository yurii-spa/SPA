"""
MP-1229: DeFiProtocolVaultPerformanceFeeGrossOfDepositFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Thin wrapper: the gross-of-deposit-fee performance-fee base-gap engine lives in
``spa_core.analytics._fee_gap_core`` (one shared implementation for the whole
gross-of-<KIND> base-gap family; the 15-line formula was previously duplicated
per module). This module supplies the deposit-fee-specific vocabulary (input/output
key names, classification / recommendation / flag labels, the HIGH-rate
threshold and the ring-buffer log path) and re-exports the family-standard
public names unchanged. Behavior, dict shapes, rounding, sentinels and the
atomic ring-buffer log are identical to the pre-refactor module; the unit test
``spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_deposit_fee_base_gap_analyzer.py`` is unmodified and remains the equivalence
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
    "data", "vault_performance_fee_gross_of_deposit_fee_base_gap_log.json"
)

# High-deposit-fee flag threshold on deposit_fee_rate_pct.
HIGH_DEPOSIT_FEE_PCT = 1.0

_api = build_module_api(
    class_name="DeFiProtocolVaultPerformanceFeeGrossOfDepositFeeBaseGapAnalyzer",
    log_path=LOG_PATH,
    high_threshold=HIGH_DEPOSIT_FEE_PCT,
    keys={
        "gross": "gross_yield_pct",
        "net": "net_of_deposit_fee_yield_pct",
        "consumed": "deposit_fee_consumed_yield_pct",
        "gap": "fee_on_deposit_fee_gap_pct",
        "fraction": "fee_on_deposit_fee_fraction",
        "rate": "deposit_fee_rate_pct",
    },
    labels={
        "clean": "CLEAN_NET_OF_DEPOSIT_FEE_BASE",
        "mild": "MILD_FEE_ON_DEPOSIT_FEE_GAP",
        "moderate": "MODERATE_FEE_ON_DEPOSIT_FEE_GAP",
        "severe": "SEVERE_FEE_ON_DEPOSIT_FEE_GAP",
        "trust": "TRUST_FEE_STRUCTURE",
        "minor": "MINOR_FEE_ON_DEPOSIT_FEE",
        "demand": "DEMAND_NET_OF_DEPOSIT_FEE_BASE",
        "avoid": "AVOID_FEE_ON_DEPOSIT_FEE",
        "high_flag": "HIGH_DEPOSIT_FEE",
        "fee_on_flag": "FEE_ON_DEPOSIT_FEE",
        "full_fee_on_flag": "FULL_FEE_ON_DEPOSIT_FEE",
        "agg_worst": "worst_deposit_fee_gap_vault",
    },
)

DeFiProtocolVaultPerformanceFeeGrossOfDepositFeeBaseGapAnalyzer = _api["analyzer_cls"]
_build_default_cfg = _api["_build_default_cfg"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_DEPOSIT_FEE_BASE: net_of_deposit_fee ≈ gross → the
            # deposit fee consumed nothing (e.g., the underlying charges a
            # 0.01% entry fee), the performance fee was on the right base.
            "vault": "USDC-Vault-CleanNetBase",
            "gross_yield_pct": 15.0,
            "net_of_deposit_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "deposit_fee_rate_pct": 0.01,
        },
        {
            # MODERATE_FEE_ON_DEPOSIT_FEE_GAP: gross 14, net 7 → ~half the fee
            # was charged on the deposit-fee slice (fraction ~ 0.5).
            "vault": "CRV-Vault-ModerateDepositFee",
            "gross_yield_pct": 14.0,
            "net_of_deposit_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "deposit_fee_rate_pct": 1.5,
        },
        {
            # SEVERE_FEE_ON_DEPOSIT_FEE_GAP (net negative): the deposit fees on
            # re-depositing the compounded yield drove the net yield negative,
            # yet the performance fee is still charged on the gross yield.
            "vault": "BAL-Vault-SevereDepositFee",
            "gross_yield_pct": 10.0,
            "net_of_deposit_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "deposit_fee_rate_pct": 3.0,
        },
        {
            # Override path: fee-on-deposit-fee gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-Vault-OverrideGap",
            "gross_yield_pct": 20.0,
            "fee_on_deposit_fee_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_deposit_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1229 Vault Performance-Fee Gross-Of-Deposit-Fee-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPerformanceFeeGrossOfDepositFeeBaseGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

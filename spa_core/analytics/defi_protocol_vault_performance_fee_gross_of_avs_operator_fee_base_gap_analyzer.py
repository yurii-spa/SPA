"""
MP-1245: DeFiProtocolVaultPerformanceFeeGrossOfAvsOperatorFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Thin wrapper: the gross-of-avs-operator-fee performance-fee base-gap engine lives in
``spa_core.analytics._fee_gap_core`` (one shared implementation for the whole
gross-of-<KIND> base-gap family; the 15-line formula was previously duplicated
per module). This module supplies the avs-operator-fee-specific vocabulary (input/output
key names, classification / recommendation / flag labels, the HIGH-rate
threshold and the ring-buffer log path) and re-exports the family-standard
public names unchanged. Behavior, dict shapes, rounding, sentinels and the
atomic ring-buffer log are identical to the pre-refactor module; the unit test
``spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_avs_operator_fee_base_gap_analyzer.py`` is unmodified and remains the equivalence
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
    "data", "vault_performance_fee_gross_of_avs_operator_fee_base_gap_log.json"
)

# High-avs-operator-fee flag threshold on avs_operator_fee_rate_pct.
HIGH_AVS_OPERATOR_FEE_PCT = 0.3

_api = build_module_api(
    class_name="DeFiProtocolVaultPerformanceFeeGrossOfAvsOperatorFeeBaseGapAnalyzer",
    log_path=LOG_PATH,
    high_threshold=HIGH_AVS_OPERATOR_FEE_PCT,
    keys={
        "gross": "gross_yield_pct",
        "net": "net_of_avs_operator_fee_yield_pct",
        "consumed": "avs_operator_fee_consumed_yield_pct",
        "gap": "fee_on_avs_operator_fee_gap_pct",
        "fraction": "fee_on_avs_operator_fee_fraction",
        "rate": "avs_operator_fee_rate_pct",
    },
    labels={
        "clean": "CLEAN_NET_OF_AVS_OPERATOR_FEE_BASE",
        "mild": "MILD_FEE_ON_AVS_OPERATOR_FEE_GAP",
        "moderate": "MODERATE_FEE_ON_AVS_OPERATOR_FEE_GAP",
        "severe": "SEVERE_FEE_ON_AVS_OPERATOR_FEE_GAP",
        "trust": "TRUST_FEE_STRUCTURE",
        "minor": "MINOR_FEE_ON_AVS_OPERATOR_FEE",
        "demand": "DEMAND_NET_OF_AVS_OPERATOR_FEE_BASE",
        "avoid": "AVOID_FEE_ON_AVS_OPERATOR_FEE",
        "high_flag": "HIGH_AVS_OPERATOR_FEE",
        "fee_on_flag": "FEE_ON_AVS_OPERATOR_FEE",
        "full_fee_on_flag": "FULL_FEE_ON_AVS_OPERATOR_FEE",
        "agg_worst": "worst_avs_operator_fee_gap_vault",
    },
)

DeFiProtocolVaultPerformanceFeeGrossOfAvsOperatorFeeBaseGapAnalyzer = _api["analyzer_cls"]
_build_default_cfg = _api["_build_default_cfg"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_AVS_OPERATOR_FEE_BASE: net ≈ gross → a vault delegated
            # to a low-commission operator whose AVS operator fee took essentially
            # nothing out of a 15% annual restaking yield, so the performance fee
            # was on the right base.
            "vault": "USDC-AVS-Vault-CleanAvsOperatorFee",
            "gross_yield_pct": 15.0,
            "net_of_avs_operator_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "avs_operator_fee_rate_pct": 0.05,
        },
        {
            # MODERATE_FEE_ON_AVS_OPERATOR_FEE_GAP: gross 14, net 7 → ~half the
            # performance fee was charged on the avs-operator-fee slice
            # (fraction ≈ 0.5).
            "vault": "CRV-AVS-Vault-ModerateAvsOperatorFee",
            "gross_yield_pct": 14.0,
            "net_of_avs_operator_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "avs_operator_fee_rate_pct": 0.2,
        },
        {
            # SEVERE_FEE_ON_AVS_OPERATOR_FEE_GAP (net negative): the vault is
            # delegated to high-commission operators running AVS-heavy strategies;
            # the cumulative AVS operator fee withheld from the earned AVS rewards
            # pushed net yield negative — yet the performance fee is still charged
            # on gross yield.
            "vault": "BAL-AVS-Vault-SevereAvsOperatorFee",
            "gross_yield_pct": 10.0,
            "net_of_avs_operator_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "avs_operator_fee_rate_pct": 0.6,
        },
        {
            # Override path: fee-on-avs-operator-fee gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-AVS-Vault-OverrideAvsOperatorFeeGap",
            "gross_yield_pct": 20.0,
            "fee_on_avs_operator_fee_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_avs_operator_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1245 Vault Performance-Fee Gross-Of-Avs-Operator-Fee-Base Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfAvsOperatorFeeBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

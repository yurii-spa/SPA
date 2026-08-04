"""
MP-1220: DeFiProtocolVaultPerformanceFeeGrossOfFundingCostBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Thin wrapper: the gross-of-funding-cost performance-fee base-gap engine lives in
``spa_core.analytics._fee_gap_core`` (one shared implementation for the whole
gross-of-<KIND> base-gap family; the 15-line formula was previously duplicated
per module). This module supplies the funding-cost-specific vocabulary (input/output
key names, classification / recommendation / flag labels, the HIGH-rate
threshold and the ring-buffer log path) and re-exports the family-standard
public names unchanged. Behavior, dict shapes, rounding, sentinels and the
atomic ring-buffer log are identical to the pre-refactor module; the unit test
``spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_funding_cost_base_gap_analyzer.py`` is unmodified and remains the equivalence
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
    "data", "vault_performance_fee_gross_of_funding_cost_base_gap_log.json"
)

# High-funding-cost flag threshold on funding_cost_pct.
HIGH_FUNDING_COST_PCT = 10.0

_api = build_module_api(
    class_name="DeFiProtocolVaultPerformanceFeeGrossOfFundingCostBaseGapAnalyzer",
    log_path=LOG_PATH,
    high_threshold=HIGH_FUNDING_COST_PCT,
    keys={
        "gross": "gross_yield_pct",
        "net": "net_of_funding_cost_yield_pct",
        "consumed": "funding_cost_consumed_yield_pct",
        "gap": "fee_on_funding_cost_gap_pct",
        "fraction": "fee_on_funding_cost_fraction",
        "rate": "funding_cost_pct",
    },
    labels={
        "clean": "CLEAN_NET_OF_FUNDING_COST_BASE",
        "mild": "MILD_FEE_ON_FUNDING_COST_GAP",
        "moderate": "MODERATE_FEE_ON_FUNDING_COST_GAP",
        "severe": "SEVERE_FEE_ON_FUNDING_COST_GAP",
        "trust": "TRUST_FEE_STRUCTURE",
        "minor": "MINOR_FEE_ON_FUNDING_COST",
        "demand": "DEMAND_NET_OF_FUNDING_COST_BASE",
        "avoid": "AVOID_FEE_ON_FUNDING_COST",
        "high_flag": "HIGH_FUNDING_COST",
        "fee_on_flag": "FEE_ON_FUNDING_COST",
        "full_fee_on_flag": "FULL_FEE_ON_FUNDING_COST",
        "agg_worst": "worst_funding_cost_gap_vault",
    },
)

DeFiProtocolVaultPerformanceFeeGrossOfFundingCostBaseGapAnalyzer = _api["analyzer_cls"]
_build_default_cfg = _api["_build_default_cfg"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_FUNDING_COST_BASE: net_of_funding_cost ≈ gross →
            # the funding consumed nothing, the performance fee was charged on
            # the right base.
            "vault": "USDC-Vault-CleanNetBase",
            "gross_yield_pct": 18.0,
            "net_of_funding_cost_yield_pct": 18.0,
            "performance_fee_pct": 20.0,
            "funding_cost_pct": 0.0,
        },
        {
            # MODERATE_FEE_ON_FUNDING_COST_GAP: gross 16, net 8 → ~half the
            # fee was charged on the funding-cost slice (fraction ~ 0.5).
            "vault": "AAVE-Vault-ModerateFundingCost",
            "gross_yield_pct": 16.0,
            "net_of_funding_cost_yield_pct": 8.0,
            "performance_fee_pct": 20.0,
            "funding_cost_pct": 12.0,
        },
        {
            # SEVERE_FEE_ON_FUNDING_COST_GAP (net negative): the funding cost
            # drove the net-of-funding-cost yield negative, yet the
            # performance fee is still charged on the gross yield → fair net
            # return is negative.
            "vault": "CRV-Vault-SevereFundingCost",
            "gross_yield_pct": 12.0,
            "net_of_funding_cost_yield_pct": -3.0,
            "performance_fee_pct": 50.0,
            "funding_cost_pct": 15.0,
        },
        {
            # Override path: a fee-on-funding-cost gap supplied directly with
            # the fee charged → fraction = 5/12 ≈ 0.4167 → MODERATE.
            "vault": "LST-Vault-OverrideGap",
            "gross_yield_pct": 24.0,
            "fee_on_funding_cost_gap_pct": 5.0,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_funding_cost_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1220 Vault Performance-Fee Gross-Of-Funding-Cost-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfFundingCostBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

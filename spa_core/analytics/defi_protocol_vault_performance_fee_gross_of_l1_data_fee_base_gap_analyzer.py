"""
MP-1233: DeFiProtocolVaultPerformanceFeeGrossOfL1DataFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Thin wrapper: the gross-of-l1-data-fee performance-fee base-gap engine lives in
``spa_core.analytics._fee_gap_core`` (one shared implementation for the whole
gross-of-<KIND> base-gap family; the 15-line formula was previously duplicated
per module). This module supplies the l1-data-fee-specific vocabulary (input/output
key names, classification / recommendation / flag labels, the HIGH-rate
threshold and the ring-buffer log path) and re-exports the family-standard
public names unchanged. Behavior, dict shapes, rounding, sentinels and the
atomic ring-buffer log are identical to the pre-refactor module; the unit test
``spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_l1_data_fee_base_gap_analyzer.py`` is unmodified and remains the equivalence
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

# Публичная поверхность модуля. Имена из _fee_gap_core здесь —
# НАМЕРЕННЫЙ ре-экспорт: их берёт ИЗ ЭТОЙ обёртки её собственный
# тест-эквивалентности, поэтому удалить их нельзя. __all__ —
# конвенция, по которой ре-экспорт считается использованием
# (dead_code_scanner._collect_exported_names, так же и pyflakes).
__all__ = [
    "CLEAN_FRACTION",
    "DeFiProtocolVaultPerformanceFeeGrossOfL1DataFeeBaseGapAnalyzer",
    "EPS",
    "HIGH_L1_DATA_FEE_PCT",
    "LOG_CAP",
    "LOG_PATH",
    "MILD_FRACTION",
    "MODERATE_FRACTION",
    "_build_default_cfg",
    "_clamp",
    "_coerce_count",
    "_coerce_num",
    "_coerce_signed",
    "_demo_positions",
    "_f",
    "_grade_from_score",
    "_mean",
    "_safe_div",
]

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_performance_fee_gross_of_l1_data_fee_base_gap_log.json"
)

# High-l1-data-fee flag threshold on l1_data_fee_rate_pct.
HIGH_L1_DATA_FEE_PCT = 0.5

_api = build_module_api(
    class_name="DeFiProtocolVaultPerformanceFeeGrossOfL1DataFeeBaseGapAnalyzer",
    log_path=LOG_PATH,
    high_threshold=HIGH_L1_DATA_FEE_PCT,
    keys={
        "gross": "gross_yield_pct",
        "net": "net_of_l1_data_fee_yield_pct",
        "consumed": "l1_data_fee_consumed_yield_pct",
        "gap": "fee_on_l1_data_fee_gap_pct",
        "fraction": "fee_on_l1_data_fee_fraction",
        "rate": "l1_data_fee_rate_pct",
    },
    labels={
        "clean": "CLEAN_NET_OF_L1_DATA_FEE_BASE",
        "mild": "MILD_FEE_ON_L1_DATA_FEE_GAP",
        "moderate": "MODERATE_FEE_ON_L1_DATA_FEE_GAP",
        "severe": "SEVERE_FEE_ON_L1_DATA_FEE_GAP",
        "trust": "TRUST_FEE_STRUCTURE",
        "minor": "MINOR_FEE_ON_L1_DATA_FEE",
        "demand": "DEMAND_NET_OF_L1_DATA_FEE_BASE",
        "avoid": "AVOID_FEE_ON_L1_DATA_FEE",
        "high_flag": "HIGH_L1_DATA_FEE",
        "fee_on_flag": "FEE_ON_L1_DATA_FEE",
        "full_fee_on_flag": "FULL_FEE_ON_L1_DATA_FEE",
        "agg_worst": "worst_l1_data_fee_gap_vault",
    },
)

DeFiProtocolVaultPerformanceFeeGrossOfL1DataFeeBaseGapAnalyzer = _api["analyzer_cls"]
_build_default_cfg = _api["_build_default_cfg"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_L1_DATA_FEE_BASE: net_of_l1_data_fee ≈ gross →
            # the L1 data fee consumed nothing (e.g., a tiny per-tx calldata
            # posting cost on a 15% annual yield is trivial, net ≈ gross),
            # the performance fee was on the right base.
            "vault": "USDC-Base-Vault-CleanNetBase",
            "gross_yield_pct": 15.0,
            "net_of_l1_data_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "l1_data_fee_rate_pct": 0.09,
        },
        {
            # MODERATE_FEE_ON_L1_DATA_FEE_GAP: gross 14, net 7 → ~half the
            # performance fee was charged on the l1-data-fee slice
            # (fraction ≈ 0.5).
            "vault": "CRV-Optimism-Vault-ModerateL1DataFee",
            "gross_yield_pct": 14.0,
            "net_of_l1_data_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "l1_data_fee_rate_pct": 0.3,
        },
        {
            # SEVERE_FEE_ON_L1_DATA_FEE_GAP (net negative): an L1 basefee spike
            # drove the L1 data posting fee high enough to push net yield
            # negative, yet the performance fee is still charged on gross yield.
            "vault": "BAL-Arbitrum-Vault-SevereL1DataFee",
            "gross_yield_pct": 10.0,
            "net_of_l1_data_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "l1_data_fee_rate_pct": 0.8,
        },
        {
            # Override path: fee-on-l1-data-fee gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-Vault-OverrideGap",
            "gross_yield_pct": 20.0,
            "fee_on_l1_data_fee_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-L2-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_l1_data_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1233 Vault Performance-Fee Gross-Of-L1-Data-Fee-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPerformanceFeeGrossOfL1DataFeeBaseGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

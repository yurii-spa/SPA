"""
MP-1241: DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Thin wrapper: the gross-of-liquidation-penalty performance-fee base-gap engine lives in
``spa_core.analytics._fee_gap_core`` (one shared implementation for the whole
gross-of-<KIND> base-gap family; the 15-line formula was previously duplicated
per module). This module supplies the liquidation-penalty-specific vocabulary (input/output
key names, classification / recommendation / flag labels, the HIGH-rate
threshold and the ring-buffer log path) and re-exports the family-standard
public names unchanged. Behavior, dict shapes, rounding, sentinels and the
atomic ring-buffer log are identical to the pre-refactor module; the unit test
``spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_liquidation_penalty_base_gap_analyzer.py`` is unmodified and remains the equivalence
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
    "DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer",
    "EPS",
    "HIGH_LIQUIDATION_PENALTY_PCT",
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
    "data", "vault_performance_fee_gross_of_liquidation_penalty_base_gap_log.json"
)

# High-liquidation-penalty flag threshold on liquidation_penalty_rate_pct.
HIGH_LIQUIDATION_PENALTY_PCT = 0.3

_api = build_module_api(
    class_name="DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer",
    log_path=LOG_PATH,
    high_threshold=HIGH_LIQUIDATION_PENALTY_PCT,
    keys={
        "gross": "gross_yield_pct",
        "net": "net_of_liquidation_penalty_yield_pct",
        "consumed": "liquidation_penalty_consumed_yield_pct",
        "gap": "fee_on_liquidation_penalty_gap_pct",
        "fraction": "fee_on_liquidation_penalty_fraction",
        "rate": "liquidation_penalty_rate_pct",
    },
    labels={
        "clean": "CLEAN_NET_OF_LIQUIDATION_PENALTY_BASE",
        "mild": "MILD_FEE_ON_LIQUIDATION_PENALTY_GAP",
        "moderate": "MODERATE_FEE_ON_LIQUIDATION_PENALTY_GAP",
        "severe": "SEVERE_FEE_ON_LIQUIDATION_PENALTY_GAP",
        "trust": "TRUST_FEE_STRUCTURE",
        "minor": "MINOR_FEE_ON_LIQUIDATION_PENALTY",
        "demand": "DEMAND_NET_OF_LIQUIDATION_PENALTY_BASE",
        "avoid": "AVOID_FEE_ON_LIQUIDATION_PENALTY",
        "high_flag": "HIGH_LIQUIDATION_PENALTY",
        "fee_on_flag": "FEE_ON_LIQUIDATION_PENALTY",
        "full_fee_on_flag": "FULL_FEE_ON_LIQUIDATION_PENALTY",
        "agg_worst": "worst_liquidation_penalty_gap_vault",
    },
)

DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer = _api["analyzer_cls"]
_build_default_cfg = _api["_build_default_cfg"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_LIQUIDATION_PENALTY_BASE: net ≈ gross → a prudently
            # managed low-LTV leveraged vault took essentially no liquidation
            # penalty over a 15% annual yield, the performance fee was on the
            # right base.
            "vault": "USDC-LIQ-Vault-CleanLiquidationPenalty",
            "gross_yield_pct": 15.0,
            "net_of_liquidation_penalty_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "liquidation_penalty_rate_pct": 0.05,
        },
        {
            # MODERATE_FEE_ON_LIQUIDATION_PENALTY_GAP: gross 14, net 7 → ~half the
            # performance fee was charged on the liquidation-penalty slice
            # (fraction ≈ 0.5).
            "vault": "CRV-LIQ-Vault-ModerateLiquidationPenalty",
            "gross_yield_pct": 14.0,
            "net_of_liquidation_penalty_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "liquidation_penalty_rate_pct": 0.2,
        },
        {
            # SEVERE_FEE_ON_LIQUIDATION_PENALTY_GAP (net negative): the vault runs
            # a high-LTV leverage loop that is repeatedly liquidated in a volatile
            # window; the cumulative liquidator bonus + protocol liquidation fee
            # bled from collateral pushed net yield negative — yet the performance
            # fee is still charged on gross yield.
            "vault": "BAL-LIQ-Vault-SevereLiquidationPenalty",
            "gross_yield_pct": 10.0,
            "net_of_liquidation_penalty_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "liquidation_penalty_rate_pct": 0.6,
        },
        {
            # Override path: fee-on-liquidation-penalty gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-LIQ-Vault-OverrideLiquidationPenaltyGap",
            "gross_yield_pct": 20.0,
            "fee_on_liquidation_penalty_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_liquidation_penalty_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1241 Vault Performance-Fee Gross-Of-Liquidation-Penalty-Base Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

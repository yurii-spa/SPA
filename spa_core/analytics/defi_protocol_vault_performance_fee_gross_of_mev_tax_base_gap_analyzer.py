"""
MP-1239: DeFiProtocolVaultPerformanceFeeGrossOfMevTaxBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Thin wrapper: the gross-of-mev-tax performance-fee base-gap engine lives in
``spa_core.analytics._fee_gap_core`` (one shared implementation for the whole
gross-of-<KIND> base-gap family; the 15-line formula was previously duplicated
per module). This module supplies the mev-tax-specific vocabulary (input/output
key names, classification / recommendation / flag labels, the HIGH-rate
threshold and the ring-buffer log path) and re-exports the family-standard
public names unchanged. Behavior, dict shapes, rounding, sentinels and the
atomic ring-buffer log are identical to the pre-refactor module; the unit test
``spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_mev_tax_base_gap_analyzer.py`` is unmodified and remains the equivalence
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
    "DeFiProtocolVaultPerformanceFeeGrossOfMevTaxBaseGapAnalyzer",
    "EPS",
    "HIGH_MEV_TAX_PCT",
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
    "data", "vault_performance_fee_gross_of_mev_tax_base_gap_log.json"
)

# High-mev-tax flag threshold on mev_tax_rate_pct.
HIGH_MEV_TAX_PCT = 0.3

_api = build_module_api(
    class_name="DeFiProtocolVaultPerformanceFeeGrossOfMevTaxBaseGapAnalyzer",
    log_path=LOG_PATH,
    high_threshold=HIGH_MEV_TAX_PCT,
    keys={
        "gross": "gross_yield_pct",
        "net": "net_of_mev_tax_yield_pct",
        "consumed": "mev_tax_consumed_yield_pct",
        "gap": "fee_on_mev_tax_gap_pct",
        "fraction": "fee_on_mev_tax_fraction",
        "rate": "mev_tax_rate_pct",
    },
    labels={
        "clean": "CLEAN_NET_OF_MEV_TAX_BASE",
        "mild": "MILD_FEE_ON_MEV_TAX_GAP",
        "moderate": "MODERATE_FEE_ON_MEV_TAX_GAP",
        "severe": "SEVERE_FEE_ON_MEV_TAX_GAP",
        "trust": "TRUST_FEE_STRUCTURE",
        "minor": "MINOR_FEE_ON_MEV_TAX",
        "demand": "DEMAND_NET_OF_MEV_TAX_BASE",
        "avoid": "AVOID_FEE_ON_MEV_TAX",
        "high_flag": "HIGH_MEV_TAX",
        "fee_on_flag": "FEE_ON_MEV_TAX",
        "full_fee_on_flag": "FULL_FEE_ON_MEV_TAX",
        "agg_worst": "worst_mev_tax_gap_vault",
    },
)

DeFiProtocolVaultPerformanceFeeGrossOfMevTaxBaseGapAnalyzer = _api["analyzer_cls"]
_build_default_cfg = _api["_build_default_cfg"]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # CLEAN_NET_OF_MEV_TAX_BASE: net ≈ gross → the MEV tax (a
            # well-protected swap via private orderflow / MEV-share) consumed
            # nothing on a 15% annual yield, the performance fee was on the
            # right base.
            "vault": "USDC-MEV-Vault-CleanMevTax",
            "gross_yield_pct": 15.0,
            "net_of_mev_tax_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "mev_tax_rate_pct": 0.05,
        },
        {
            # MODERATE_FEE_ON_MEV_TAX_GAP: gross 14, net 7 → ~half the
            # performance fee was charged on the mev-tax slice (fraction ≈ 0.5).
            "vault": "CRV-MEV-Vault-ModerateMevTax",
            "gross_yield_pct": 14.0,
            "net_of_mev_tax_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "mev_tax_rate_pct": 0.2,
        },
        {
            # SEVERE_FEE_ON_MEV_TAX_GAP (net negative): the vault routes large
            # unprotected harvest/rebalance swaps into thin pools through the
            # public mempool; searchers sandwich every one, and the cumulative
            # MEV tax pushed net yield negative — yet the performance fee is
            # still charged on gross yield.
            "vault": "BAL-MEV-Vault-SevereMevTax",
            "gross_yield_pct": 10.0,
            "net_of_mev_tax_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "mev_tax_rate_pct": 0.6,
        },
        {
            # Override path: fee-on-mev-tax gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-MEV-Vault-OverrideMevTaxGap",
            "gross_yield_pct": 20.0,
            "fee_on_mev_tax_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_mev_tax_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1239 Vault Performance-Fee Gross-Of-Mev-Tax-Base Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfMevTaxBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

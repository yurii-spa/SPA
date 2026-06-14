"""
SPA Risk Policy — Frozen Snapshot: v1.0 "Passive Stable Lending Core"
=======================================================================

DO NOT IMPORT THIS AS THE ACTIVE POLICY.
This file is an immutable historical record of the v1.0 RiskConfig,
created for audit trail, rollback capability, and paper test baseline.

Snapshot taken: 2026-05-20
Status at snapshot: ACTIVE (paper testing, started 2026-05-20)
Approved by: Yurii (Owner)
ADR reference: docs/adr/ADR_001_initial_risk_policy.md

ROLLBACK INSTRUCTIONS:
  If you need to revert the active policy to v1.0, copy the default values
  from V1_0_PASSIVE_CONFIG below back into spa_core/risk/policy.py RiskConfig.
  Then create an ADR documenting the rollback decision.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class _V1_0_RiskConfig:
    """
    Frozen (immutable) snapshot of RiskConfig v1.0.
    Values here must NEVER be changed — they are a historical record.
    """

    # ── Version metadata ──────────────────────────────────────────────────────
    version: str = "v1.0"
    version_date: str = "2026-05-20"
    changelog: str = (
        "Initial policy: T1/T2 concentration limits, 5% drawdown kill switch, 5% cash buffer"
    )

    # ── Concentration limits — max % of portfolio in a single protocol ────────
    max_concentration_t1: float = 0.40   # T1: max 40%
    max_concentration_t2: float = 0.20   # T2: max 20%
    max_single_protocol:  float = 0.40   # absolute max for any single protocol

    # ── Category limits ───────────────────────────────────────────────────────
    max_total_t2_allocation: float = 0.35  # T2 aggregate ≤ 35%

    # ── Circuit breakers — auto-stop ──────────────────────────────────────────
    max_apy_for_new_position: float = 30.0   # % — skip if APY > 30% (too risky)
    min_apy_for_new_position: float = 1.0    # % — skip if APY < 1% (not attractive)
    min_tvl_usd: float = 5_000_000           # $5M minimum TVL to enter
    max_drawdown_stop: float = 0.05          # 5% — kill switch for entire portfolio
    max_single_position_drawdown: float = 0.03  # 3% — close individual position

    # ── VaR parameters (historical, 95% confidence, 7-day horizon) ────────────
    var_confidence: float = 0.95
    var_horizon_days: int = 7
    max_var_pct: float = 0.05               # VaR ≤ 5% of portfolio

    # ── Minimum cash buffer ────────────────────────────────────────────────────
    min_cash_pct: float = 0.05              # 5% always kept in cash


# Singleton instance — import this if you need the frozen v1.0 reference values
V1_0_PASSIVE_CONFIG = _V1_0_RiskConfig()


# ── Metadata for tooling / audit scripts ──────────────────────────────────────
VERSION_INFO = {
    "version": "v1.0",
    "codename": "passive",
    "snapshot_date": "2026-05-20",
    "approved_by": "Yurii (Owner)",
    "adr": "docs/adr/ADR_001_initial_risk_policy.md",
    "paper_test_start": "2026-05-20",
    "paper_test_end_target": "2026-07-15",
    "status": "active_paper_testing",
    "strategy": "Stable Lending Core — T1/T2 stablecoin lending protocols only",
    "capital": "$100,000 paper (virtual)",
}

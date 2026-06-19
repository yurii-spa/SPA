"""
spa_core/analytics/regime_adjusted_allocator.py

Adjusts RS-001 / RS-002 allocation based on current market regime.

Allocation rules:
  BULL regime:
    RS-001: 40% (full capacity, aggressive)
    RS-002: 30% (enabled, BTC LP attractive)
    Cash:   30% (reserve for opportunities)

  NEUTRAL regime:
    RS-001: 50% (primary)
    RS-002: 20% (limited, IL manageable)
    Cash:   30% (neutral reserve)

  BEAR regime:
    RS-001: 30% (reduced, anti-crisis mode)
    RS-002:  0% (SUSPENDED — IL too high)
    Cash:   70% (maximum protection)

Target APY per strategy per regime (from adaptive_apy_target.py + RS-002 research):
  RS-001: bear=8.0%, neutral=18.2%, bull=22.0%
  RS-002: bear=0.0% (SUSPENDED), neutral=15.0%, bull=20.0%

expected_apy formula:
  RS-001 contribution: alloc_pct × RS001_APY[regime]
  RS-002 contribution: alloc_pct × RS002_APY[regime]  (0 if suspended)
  Cash contribution:   0%

RESEARCH_ONLY — does NOT affect allocator / risk / execution.
Pure stdlib. No external dependencies. LLM FORBIDDEN.
Atomic writes: mkstemp + os.replace.

Sprint v9.78 — MP-1362
Date: 2026-06-19
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

# ── Regime constants ────────────────────────────────────────────────────────────

VALID_REGIMES = ("bull", "neutral", "bear")

# Target APY per strategy per regime (%)
RS001_APY: Dict[str, float] = {
    "bull":    22.0,
    "neutral": 18.2,
    "bear":     8.0,
}

RS002_APY: Dict[str, float] = {
    "bull":    20.0,
    "neutral": 15.0,
    "bear":     0.0,   # SUSPENDED in bear
}

REGIME_ALLOCATIONS: Dict[str, Dict[str, float]] = {
    "bull": {
        "rs001": 0.40,
        "rs002": 0.30,
        "cash":  0.30,
    },
    "neutral": {
        "rs001": 0.50,
        "rs002": 0.20,
        "cash":  0.30,
    },
    "bear": {
        "rs001": 0.30,
        "rs002": 0.00,   # SUSPENDED
        "cash":  0.70,
    },
}

# Mapping from data/market_regime.json "regime" field → internal regime key
_REGIME_MAP: Dict[str, str] = {
    "bull":    "bull",
    "bear":    "bear",
    "neutral": "neutral",
    "stable":  "neutral",   # DeFiLlama "STABLE" → neutral
}

_DATA_REGIME_FILE = "data/market_regime.json"


# ── Result dataclass (stdlib-compatible) ────────────────────────────────────────

class AllocationResult:
    """Allocation decision for one market regime."""

    __slots__ = [
        "regime",
        "rs001_pct",
        "rs002_pct",
        "cash_pct",
        "rs001_capital_usd",
        "rs002_capital_usd",
        "cash_capital_usd",
        "expected_portfolio_apy",
        "rs002_suspended",
    ]

    def __init__(
        self,
        regime: str,
        rs001_pct: float,
        rs002_pct: float,
        cash_pct: float,
        rs001_capital_usd: float,
        rs002_capital_usd: float,
        cash_capital_usd: float,
        expected_portfolio_apy: float,
        rs002_suspended: bool,
    ) -> None:
        self.regime: str = regime
        self.rs001_pct: float = rs001_pct
        self.rs002_pct: float = rs002_pct
        self.cash_pct: float = cash_pct
        self.rs001_capital_usd: float = rs001_capital_usd
        self.rs002_capital_usd: float = rs002_capital_usd
        self.cash_capital_usd: float = cash_capital_usd
        self.expected_portfolio_apy: float = expected_portfolio_apy
        self.rs002_suspended: bool = rs002_suspended

    def to_dict(self) -> dict:
        return {
            "regime":                  self.regime,
            "rs001_pct":               self.rs001_pct,
            "rs002_pct":               self.rs002_pct,
            "cash_pct":                self.cash_pct,
            "rs001_capital_usd":       self.rs001_capital_usd,
            "rs002_capital_usd":       self.rs002_capital_usd,
            "cash_capital_usd":        self.cash_capital_usd,
            "expected_portfolio_apy":  self.expected_portfolio_apy,
            "rs002_suspended":         self.rs002_suspended,
        }

    def __repr__(self) -> str:
        return (
            f"AllocationResult(regime={self.regime!r}, "
            f"rs001={self.rs001_pct:.0%}, "
            f"rs002={self.rs002_pct:.0%}, "
            f"cash={self.cash_pct:.0%}, "
            f"expected_apy={self.expected_portfolio_apy:.2f}%)"
        )


# ── Allocator ───────────────────────────────────────────────────────────────────

class RegimeAdjustedAllocator:
    """
    Adjusts RS-001 / RS-002 portfolio allocation based on current market regime.

    Usage:
        alloc = RegimeAdjustedAllocator(total_capital=100_000.0)
        result = alloc.allocate("bull")
        print(alloc.to_markdown())
        alloc.save()
    """

    def __init__(
        self,
        total_capital: float = 100_000.0,
        base_dir: str = ".",
    ) -> None:
        """
        Args:
            total_capital: total portfolio capital in USD (default $100,000)
            base_dir: repository root for resolving data/ paths
        """
        self.total_capital: float = total_capital
        self.base_dir: Path = Path(base_dir)

    # ── Regime detection ────────────────────────────────────────────────────────

    def current_regime(self) -> str:
        """
        Read current market regime from data/market_regime.json.

        Maps raw "regime" field (case-insensitive) to one of "bull" / "neutral" / "bear".
        Falls back to "neutral" if the file is missing, unreadable, or has an unknown value.

        Returns:
            str: "bull", "neutral", or "bear"
        """
        regime_path = self.base_dir / _DATA_REGIME_FILE
        try:
            with open(regime_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            raw = str(data.get("regime", "")).lower().strip()
            return _REGIME_MAP.get(raw, "neutral")
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return "neutral"

    # ── Allocation ──────────────────────────────────────────────────────────────

    def allocate(self, regime: Optional[str] = None) -> AllocationResult:
        """
        Return allocation for the given regime.

        Args:
            regime: "bull", "neutral", or "bear".
                    If None, uses current_regime().

        Returns:
            AllocationResult
        """
        if regime is None:
            regime = self.current_regime()

        regime = regime.lower().strip()
        if regime not in VALID_REGIMES:
            raise ValueError(
                f"Unknown regime {regime!r}. Valid: {VALID_REGIMES}"
            )

        alloc = REGIME_ALLOCATIONS[regime]
        rs001_pct = alloc["rs001"]
        rs002_pct = alloc["rs002"]
        cash_pct  = alloc["cash"]

        rs001_capital = self.total_capital * rs001_pct
        rs002_capital = self.total_capital * rs002_pct
        cash_capital  = self.total_capital * cash_pct

        exp_apy = self._compute_expected_apy(regime, rs001_pct, rs002_pct)
        suspended = rs002_pct == 0.0 and regime == "bear"

        return AllocationResult(
            regime=regime,
            rs001_pct=rs001_pct,
            rs002_pct=rs002_pct,
            cash_pct=cash_pct,
            rs001_capital_usd=round(rs001_capital, 2),
            rs002_capital_usd=round(rs002_capital, 2),
            cash_capital_usd=round(cash_capital, 2),
            expected_portfolio_apy=round(exp_apy, 4),
            rs002_suspended=suspended,
        )

    def allocate_all_regimes(self) -> Dict[str, AllocationResult]:
        """
        Return AllocationResult for all 3 regimes.

        Returns:
            dict mapping "bull" / "neutral" / "bear" → AllocationResult
        """
        return {regime: self.allocate(regime) for regime in VALID_REGIMES}

    # ── APY helpers ─────────────────────────────────────────────────────────────

    def expected_apy(self, regime: str) -> float:
        """
        Expected blended portfolio APY for the given regime.

        Formula:
          RS-001 contribution = rs001_pct × RS001_APY[regime]
          RS-002 contribution = rs002_pct × RS002_APY[regime]  (0 if SUSPENDED)
          Cash contribution   = 0%

        Args:
            regime: "bull", "neutral", or "bear"

        Returns:
            float: expected portfolio APY (%)
        """
        regime = regime.lower().strip()
        if regime not in VALID_REGIMES:
            raise ValueError(f"Unknown regime {regime!r}. Valid: {VALID_REGIMES}")
        alloc = REGIME_ALLOCATIONS[regime]
        return self._compute_expected_apy(regime, alloc["rs001"], alloc["rs002"])

    # ── Persistence ─────────────────────────────────────────────────────────────

    def save(self, regime: Optional[str] = None) -> str:
        """
        Atomically save current allocation to data/current_allocation.json.

        Args:
            regime: if None, uses current_regime()

        Returns:
            str: path to written file
        """
        result = self.allocate(regime)
        all_regimes = self.allocate_all_regimes()

        payload = {
            "generated_at":    datetime.now(timezone.utc).isoformat(),
            "module":          "spa_core/analytics/regime_adjusted_allocator.py",
            "total_capital":   self.total_capital,
            "current_regime":  result.regime,
            "current":         result.to_dict(),
            "all_regimes": {
                r: ar.to_dict() for r, ar in all_regimes.items()
            },
        }

        out_dir = self.base_dir / "data"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "current_allocation.json"

        from spa_core.utils.atomic import atomic_save
        atomic_save(payload, str(out_path))

        return str(out_path)

    # ── Markdown report ─────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """
        Markdown table comparing allocations across all 3 regimes.

        Columns: Regime | RS-001 % | RS-002 % | Cash % | Expected APY | RS-002 Status
        """
        all_regimes = self.allocate_all_regimes()
        lines = [
            "## Regime-Adjusted Portfolio Allocation\n",
            f"Total capital: ${self.total_capital:,.0f}\n",
            "| Regime | RS-001 % | RS-002 % | Cash % | Expected APY | RS-002 Status |",
            "|---|---|---|---|---|---|",
        ]
        for regime in VALID_REGIMES:
            r = all_regimes[regime]
            status = "SUSPENDED" if r.rs002_suspended else "active"
            lines.append(
                f"| {regime} "
                f"| {r.rs001_pct:.0%} "
                f"| {r.rs002_pct:.0%} "
                f"| {r.cash_pct:.0%} "
                f"| {r.expected_portfolio_apy:.2f}% "
                f"| {status} |"
            )
        return "\n".join(lines) + "\n"

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _compute_expected_apy(
        self,
        regime: str,
        rs001_pct: float,
        rs002_pct: float,
    ) -> float:
        """Compute blended expected APY for a regime."""
        rs001_contrib = rs001_pct * RS001_APY[regime]
        rs002_contrib = rs002_pct * RS002_APY[regime]   # 0 if suspended (RS002_APY["bear"]=0)
        return rs001_contrib + rs002_contrib

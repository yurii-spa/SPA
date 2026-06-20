"""
spa_core/strategies/s20_curve_convex.py — MP-1511 S20_CRV Curve/Convex Optimizer

Strategy S20_CRV — Curve/Convex Yield Optimizer.
=====================================================
Optimizes across Curve stablecoin pools with Convex-boosted CRV+CVX emissions.
Target APY: 8–12% via CRV + CVX emission boosting.
Tier: T2 (requires DeFiLlama pool verification).
Chain: Ethereum mainnet.

Pool selection logic:
  - Queries DeFiLlama feed (via apy_data dict) for live pool APYs.
  - Selects best-risk-adjusted pool exceeding per-pool min_apy floor.
  - 80% deployed to winning pool, 20% held as cash buffer.
  - Falls back to 100% cash if no pool meets criteria.

Backtest stats (synthetic baseline — replace with real PIT data):
  Sharpe: 1.4 | Max DD: -3% | Annual return: 9% | Win rate: 72%

Constraints:
  - TIER = "T2": per-protocol cap 20%, T2 total cap 50% (ADR-019)
  - APY bounds for new positions: 1%–30% (RiskPolicy v1.0)
  - No Convex on-chain adapter yet — pool APYs come from DeFiLlama feed
  - LLM FORBIDDEN in this module
  - Stdlib only, no external dependencies

ADR: ADR-019 (T2 total cap 50%), ADR-023 (promotion policy)
Date: 2026-06-20 (MP-1511, Sprint v11.27)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ─── Module-level constants ────────────────────────────────────────────────────

STRATEGY_ID: str = "S20_CRV"
STRATEGY_NAME: str = "Curve/Convex Yield Optimizer"
DESCRIPTION: str = "Curve/Convex yield optimizer with emission boosting"
TARGET_APY: float = 0.10        # 10% nominal target (fraction)
TARGET_APY_PCT: float = 10.0    # same in percent
TIER: str = "T2"
CHAIN: str = "ethereum"
RISK_TIER: str = "T2"

# APY bounds mirror RiskPolicy v1.0
APY_MIN_PCT: float = 1.0    # % — min for new position
APY_MAX_PCT: float = 30.0   # % — max (anything higher → filter out as anomalous)

# Allocation fractions
POOL_ALLOCATION: float = 0.80   # 80% to best pool
CASH_BUFFER: float = 0.20       # 20% cash reserve

# Per-pool configuration: name → {tokens, min_apy_pct}
CURVE_POOLS: Dict[str, dict] = {
    "3pool": {
        "tokens": ["USDC", "USDT", "DAI"],
        "min_apy": 0.04,       # 4% min (fraction)
        "description": "Curve 3pool: USDC/USDT/DAI — deepest stablecoin liquidity",
    },
    "frax_usdc": {
        "tokens": ["FRAX", "USDC"],
        "min_apy": 0.06,       # 6% min — boosted by Convex
        "description": "Curve FRAX/USDC — Convex-boosted CRV+CVX emissions",
    },
    "susd": {
        "tokens": ["sUSD", "USDC", "USDT", "DAI"],
        "min_apy": 0.05,       # 5% min — SNX rewards layer
        "description": "Curve sUSD pool: sUSD/3CRV — SNX + CRV dual rewards",
    },
}

# Backtest baseline stats (synthetic — no real PIT data yet)
_BACKTEST_STATS: dict = {
    "sharpe": 1.4,
    "max_dd": -0.03,
    "annual_return": 0.09,
    "win_rate": 0.72,
    "calmar": 3.0,
    "note": "Synthetic baseline; replace with real DeFiLlama PIT data.",
}

# Target APY range for registry
TARGET_APY_MIN: float = 8.0
TARGET_APY_MAX: float = 12.0
MAX_DRAWDOWN_PCT: float = 5.0


# ─── S20CurveConvex ───────────────────────────────────────────────────────────

class S20CurveConvex:
    """
    S20_CRV — Curve/Convex Yield Optimizer Strategy.

    Public API:
        select_pool(apy_data)           → pool_name | None
        get_allocation(portfolio_value, apy_data)  → {slot: usd_amount}
        blended_apy(apy_data)           → float (% APY)
        backtest_stats()                → dict
        risk_check(apy_data)            → (ok: bool, reason: str)
        to_dict(portfolio_value, apy_data) → full snapshot for dashboard
    """

    STRATEGY_ID = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    DESCRIPTION = DESCRIPTION
    TARGET_APY = TARGET_APY
    TIER = TIER
    CHAIN = CHAIN

    # ── Pool selection ─────────────────────────────────────────────────────────

    def select_pool(self, apy_data: dict) -> Optional[str]:
        """
        Selects best Curve pool by risk-adjusted APY.

        Reads APY from apy_data under key f"curve_{pool_name}" (fractional).
        Only pools with apy >= pool's min_apy AND within global APY bounds
        are eligible. Returns pool_name of the best, or None if none qualify.

        Args:
            apy_data: dict mapping protocol keys → APY fraction (e.g. 0.09 = 9%)

        Returns:
            Best eligible pool name, or None.
        """
        best_pool: Optional[str] = None
        best_apy: float = 0.0

        for pool_name, config in CURVE_POOLS.items():
            key = f"curve_{pool_name}"
            raw = apy_data.get(key)
            if raw is None:
                continue
            try:
                pool_apy = float(raw)
            except (TypeError, ValueError):
                continue

            # Bounds check (APY must be in [1%, 30%] band as fraction)
            apy_pct = pool_apy * 100.0
            if not (APY_MIN_PCT <= apy_pct <= APY_MAX_PCT):
                continue

            # Pool's own floor
            if pool_apy < config["min_apy"]:
                continue

            if pool_apy > best_apy:
                best_pool = pool_name
                best_apy = pool_apy

        return best_pool

    def get_allocation(self, portfolio_value: float, apy_data: dict) -> dict:
        """
        Returns USD allocation recommendation across pool + cash.

        80% to best qualifying Curve pool (or 0 if none qualify).
        20% cash buffer always maintained.

        Args:
            portfolio_value: Total portfolio USD value (≥ 0).
            apy_data:        Live APY dict {key: fraction}.

        Returns:
            dict with slot → USD amount. Keys: best pool or "cash" only.
        """
        safe_val = max(0.0, portfolio_value)
        pool = self.select_pool(apy_data)

        if pool:
            return {
                f"curve_{pool}": safe_val * POOL_ALLOCATION,
                "cash": safe_val * CASH_BUFFER,
            }
        # Fallback: 100% cash
        return {"cash": safe_val}

    def blended_apy(self, apy_data: dict) -> float:
        """
        Computes blended portfolio APY (%).

        Weights: POOL_ALLOCATION × pool_apy + CASH_BUFFER × 0.
        Returns 0.0 if no pool qualifies.

        Args:
            apy_data: Live APY dict {key: fraction}.

        Returns:
            Blended APY in percent (float ≥ 0.0).
        """
        pool = self.select_pool(apy_data)
        if not pool:
            return 0.0
        key = f"curve_{pool}"
        raw_apy = apy_data.get(key, 0.0)
        try:
            pool_apy_pct = float(raw_apy) * 100.0
        except (TypeError, ValueError):
            pool_apy_pct = 0.0
        return round(POOL_ALLOCATION * pool_apy_pct, 4)

    def backtest_stats(self) -> dict:
        """
        Returns synthetic backtest stats.

        Replace with real PIT DeFiLlama data before promotion.

        Returns:
            dict with: sharpe, max_dd, annual_return, win_rate, calmar, note.
        """
        return dict(_BACKTEST_STATS)

    def risk_check(self, apy_data: dict) -> Tuple[bool, str]:
        """
        Lightweight risk pre-check before allocation.

        Returns (True, "ok") if a qualifying pool exists.
        Returns (False, reason) otherwise.

        Args:
            apy_data: Live APY dict.

        Returns:
            (ok: bool, reason: str)
        """
        pool = self.select_pool(apy_data)
        if pool is None:
            return False, "No Curve pool meets APY floor or RiskPolicy bounds"
        key = f"curve_{pool}"
        apy = apy_data.get(key, 0.0)
        apy_pct = float(apy) * 100.0
        if apy_pct > APY_MAX_PCT:
            return False, f"APY anomaly: {apy_pct:.1f}% exceeds {APY_MAX_PCT}% cap"
        return True, "ok"

    def available_pools(self) -> List[str]:
        """Returns list of configured pool names."""
        return list(CURVE_POOLS.keys())

    def pool_config(self, pool_name: str) -> Optional[dict]:
        """Returns config for a specific pool, or None if not found."""
        return CURVE_POOLS.get(pool_name)

    def to_dict(
        self,
        portfolio_value: float = 0.0,
        apy_data: Optional[dict] = None,
    ) -> dict:
        """Full strategy snapshot for dashboard and reports."""
        apy_data = apy_data or {}
        pool = self.select_pool(apy_data)
        allocation = self.get_allocation(portfolio_value, apy_data)
        ok, reason = self.risk_check(apy_data)

        return {
            "strategy_id": STRATEGY_ID,
            "strategy_name": STRATEGY_NAME,
            "description": DESCRIPTION,
            "tier": TIER,
            "chain": CHAIN,
            "target_apy_pct": TARGET_APY_PCT,
            "target_apy_range": [TARGET_APY_MIN, TARGET_APY_MAX],
            "selected_pool": pool,
            "allocation": allocation,
            "blended_apy_pct": self.blended_apy(apy_data),
            "backtest_stats": self.backtest_stats(),
            "risk_check": {"ok": ok, "reason": reason},
            "curve_pools": {k: v["description"] for k, v in CURVE_POOLS.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S20_CRV in the global REGISTRY. Failure does not block import."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta  # type: ignore
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lp",
            risk_tier=RISK_TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "S20_CRV Curve/Convex optimizer: 80% to best-APY Curve stablecoin pool "
                "(3pool / frax_usdc / susd) + Convex CRV+CVX emission boost. "
                "20% cash buffer. Target APY 8–12%, Tier T2, Ethereum."
            ),
            module="spa_core.strategies.s20_curve_convex",
            handler_class="S20CurveConvex",
            tags=["curve", "convex", "crv", "cvx", "stablecoin", "lp", "t2", "s20_crv"],
        ))
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S20CurveConvex auto-registration failed: %s", exc
        )


_register()

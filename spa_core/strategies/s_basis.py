"""
S_BASIS: Delta-neutral basis trade strategy for SPA tournament.

Reads perp_funding_rates.json + adapter_status.json → feeds BasisTradeAnalyzer →
returns allocation signal for USDC lending + basis yield.

Advisory/read-only — never imports execution/. Pure stdlib.
PAPER SIMULATION ONLY until promoted by tournament confidence >= 0.75 for 7+ days.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("spa.strategies.s_basis")

# ---------------------------------------------------------------------------
# Module-level constants (exported for cycle_runner import pattern)
# ---------------------------------------------------------------------------

STRATEGY_ID: str = "S_BASIS"
STRATEGY_NAME: str = "Live Basis Trade (Funding Harvest)"
TIER: str = "T2"
TARGET_APY_MIN: float = 0.0
TARGET_APY_MAX: float = 24.0

ALLOCATION: Dict[str, float] = {
    "usdc_lend_leg": 0.50,
    "perp_short_leg": 0.50,
}

# ---------------------------------------------------------------------------
# Strategy parameters
# ---------------------------------------------------------------------------

DEFAULT_EXEC_COST_BPS: float = 20.0
MIN_NET_SPREAD_BPS_ENTER: float = 50.0
MIN_OPEN_INTEREST_USD: float = 50_000_000.0
MAX_BTS_WEIGHT: float = 0.20
TRACKED_ASSETS: tuple = ("ETH", "BTC")

# USDC lending protocol keys to look up in adapter_status
_USDC_LEND_KEYS: list = [
    "aave_v3", "aave_usdc", "compound_v3", "morpho_steakhouse",
    "morpho_blue", "spark_susds",
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class BasisSignal:
    """Signal from S_BASIS strategy evaluation."""

    asset: str
    structure: str
    net_spread_bps: float
    edge_quality: str
    recommended_action: str
    target_weight: float
    annual_pnl_usd: float

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "structure": self.structure,
            "net_spread_bps": self.net_spread_bps,
            "edge_quality": self.edge_quality,
            "recommended_action": self.recommended_action,
            "target_weight": self.target_weight,
            "annual_pnl_usd": self.annual_pnl_usd,
        }


# ---------------------------------------------------------------------------
# SBasisStrategy
# ---------------------------------------------------------------------------


class SBasisStrategy:
    """Live basis-trade strategy for the SPA tournament.

    Reads perp_funding_rates.json + adapter_status.json, computes delta-neutral
    net spread per asset via BasisTradeAnalyzer, and returns an allocation signal.
    PAPER SIMULATION ONLY. Never imports execution/.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        capital: float = 100_000.0,
        exec_cost_bps: float = DEFAULT_EXEC_COST_BPS,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else Path("data")
        self.capital = capital
        self.exec_cost_bps = exec_cost_bps

    def _load_json(self, filename: str) -> dict:
        """Load JSON file from data_dir, {} on any error."""
        try:
            path = self.data_dir / filename
            if not path.exists():
                return {}
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _get_funding_data(self) -> dict:
        """Load perp_funding_rates.json."""
        return self._load_json("perp_funding_rates.json")

    def _get_adapter_status(self) -> dict:
        """Load adapter_status.json."""
        return self._load_json("adapter_status.json")

    def _get_funding_annual(self, asset: str) -> Optional[float]:
        """Get annualized funding rate for an asset from cached data."""
        try:
            from spa_core.feeds.perp_funding_feed import get_funding_annual
            return get_funding_annual(asset, data_dir=self.data_dir)
        except ImportError:
            pass
        data = self._get_funding_data()
        if not data or data.get("stale", True):
            return None
        assets = data.get("assets", {})
        info = assets.get(asset, {})
        if isinstance(info, dict):
            return info.get("funding_rate_annual")
        return None

    def _get_open_interest(self, asset: str) -> float:
        """Get open interest USD for an asset from cached data."""
        data = self._get_funding_data()
        if not data:
            return 0.0
        assets = data.get("assets", {})
        info = assets.get(asset, {})
        if isinstance(info, dict):
            return float(info.get("open_interest_usd", 0.0))
        return 0.0

    def _spot_yield_for(self, asset: str, adapter_status: dict) -> float:
        """Cash-carry leg yield (decimal).

        Returns the best live T1 stablecoin USDC lending APY from adapter_status.
        Falls back to 0.03 (3% conservative estimate) if no data.
        """
        best_apy = 0.0
        for key in _USDC_LEND_KEYS:
            info = adapter_status.get(key, {})
            if not isinstance(info, dict):
                continue
            apy = info.get("apy")
            if apy is None:
                apy = info.get("current_apy")
            if apy is None:
                continue
            try:
                apy_val = float(apy)
                if apy_val > 1.0:
                    apy_val = apy_val / 100.0
                if apy_val > best_apy:
                    best_apy = apy_val
            except (ValueError, TypeError):
                continue
        return best_apy if best_apy > 0.0 else 0.03

    def evaluate(self) -> List[BasisSignal]:
        """Build BasisTradeInput per tracked asset → analyze → rank.

        Returns [] if funding data stale or no asset clears floors.
        """
        try:
            from spa_core.analytics.basis_trade_analyzer import (
                BasisTradeAnalyzer,
                BasisTradeInput,
            )
        except ImportError:
            logger.error("BasisTradeAnalyzer not available")
            return []

        funding_data = self._get_funding_data()
        if not funding_data or funding_data.get("stale", True):
            logger.info("Funding data stale or missing — no signals")
            return []

        adapter_status = self._get_adapter_status()
        analyzer = BasisTradeAnalyzer()
        signals = []

        sleeve_capital = self.capital * MAX_BTS_WEIGHT

        for asset in TRACKED_ASSETS:
            try:
                funding_annual = self._get_funding_annual(asset)
                if funding_annual is None:
                    continue

                oi_usd = self._get_open_interest(asset)
                if oi_usd < MIN_OPEN_INTEREST_USD:
                    logger.info(
                        "%s OI $%.0f < floor $%.0f — skipping",
                        asset, oi_usd, MIN_OPEN_INTEREST_USD,
                    )
                    continue

                spot_yield = self._spot_yield_for(asset, adapter_status)

                inp = BasisTradeInput(
                    asset=asset,
                    spot_yield_annual=spot_yield,
                    perp_funding_annual=funding_annual,
                    execution_cost_bps=self.exec_cost_bps,
                    capital_usd=sleeve_capital / max(len(TRACKED_ASSETS), 1),
                )

                result = analyzer.analyze(inp)

                if result.recommended_action == "ENTER":
                    weight = min(
                        result.net_spread_bps / 200.0,
                        1.0,
                    )
                    target_weight = weight * MAX_BTS_WEIGHT
                else:
                    target_weight = 0.0

                signals.append(BasisSignal(
                    asset=asset,
                    structure="explicit_long_usdc_short_perp",
                    net_spread_bps=result.net_spread_bps,
                    edge_quality=result.edge_quality,
                    recommended_action=result.recommended_action,
                    target_weight=target_weight,
                    annual_pnl_usd=result.annual_pnl_usd,
                ))
            except Exception as exc:
                logger.warning("Failed to evaluate %s: %s", asset, exc)
                continue

        signals.sort(key=lambda s: s.net_spread_bps, reverse=True)
        return signals

    def allocate(self, sleeve_capital_usd: float = 0.0) -> Dict[str, float]:
        """Convert signals to {leg_key: usd}.

        Returns {} when no ENTER signal → sleeve goes to T1 safe harbor.
        Capped at MAX_BTS_WEIGHT (20%) of total capital.
        """
        try:
            signals = self.evaluate()
        except Exception as exc:
            logger.error("evaluate() failed: %s", exc)
            return {}

        enter_signals = [s for s in signals if s.recommended_action == "ENTER"]
        if not enter_signals:
            return {}

        max_capital = self.capital * MAX_BTS_WEIGHT
        if sleeve_capital_usd > 0:
            max_capital = min(sleeve_capital_usd, max_capital)

        total_weight = sum(s.target_weight for s in enter_signals)
        if total_weight <= 0:
            return {}

        allocations = {}
        for sig in enter_signals:
            frac = sig.target_weight / total_weight
            usd = round(max_capital * frac, 2)
            allocations[f"basis_{sig.asset.lower()}_lend"] = round(usd * 0.5, 2)
            allocations[f"basis_{sig.asset.lower()}_short"] = round(usd * 0.5, 2)

        return allocations

    def get_summary(self) -> dict:
        """Return a summary dict for tournament/dashboard consumption."""
        try:
            signals = self.evaluate()
            enter_count = sum(1 for s in signals if s.recommended_action == "ENTER")
            best = signals[0] if signals else None
            return {
                "strategy_id": STRATEGY_ID,
                "strategy_name": STRATEGY_NAME,
                "signals_count": len(signals),
                "enter_count": enter_count,
                "best_asset": best.asset if best else None,
                "best_net_spread_bps": best.net_spread_bps if best else 0.0,
                "best_edge_quality": best.edge_quality if best else None,
                "allocations": self.allocate(),
            }
        except Exception as exc:
            logger.error("get_summary failed: %s", exc)
            return {"strategy_id": STRATEGY_ID, "error": str(exc)}


# ---------------------------------------------------------------------------
# Self-registration in strategy domain registry
# ---------------------------------------------------------------------------


def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="basis_trade",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=0.05,
            description=(
                "Delta-neutral basis trade: long USDC lending + short ETH/BTC perp. "
                "Harvests positive funding. ENTER when net spread >= 50bps. Max 20%."
            ),
            module="spa_core.strategies.s_basis",
            handler_class="SBasisStrategy",
            tags=["basis_trade", "funding", "delta_neutral", "hyperliquid"],
        ))
    except Exception:
        pass


_register()

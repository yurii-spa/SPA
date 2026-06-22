"""Slippage Simulator — MP-629.

Models price impact for position sizing decisions.  Pure advisory;
never touches allocator / risk / execution domains.

Design constraints
------------------
* Stdlib only (no numpy, requests, web3, pandas, …).
* Pure advisory — read-only; no side-effects on position state.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* All writes are atomic (tmp + os.replace) where applicable.

Usage (CLI)::

    python3 -m spa_core.analytics.slippage_simulator --check
    python3 -m spa_core.analytics.slippage_simulator --run
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class SlippageEstimate:
    """Result of a single slippage estimate for one adapter/trade pair."""

    adapter_id: str
    trade_size_usd: float
    pool_tvl_usd: float
    slippage_bps: float
    price_impact_pct: float
    is_acceptable: bool
    max_safe_trade_usd: float


# ---------------------------------------------------------------------------
# Slippage model constants
# ---------------------------------------------------------------------------


SLIPPAGE_MODEL: Dict[str, dict] = {
    "low_liquidity":    {"tvl_threshold": 1_000_000,       "base_bps": 50},
    "medium_liquidity": {"tvl_threshold": 10_000_000,      "base_bps": 20},
    "high_liquidity":   {"tvl_threshold": 100_000_000,     "base_bps": 5},
    "deep_liquidity":   {"tvl_threshold": float("inf"),    "base_bps": 1},
}

ACCEPTABLE_SLIPPAGE_BPS: float = 30.0  # max acceptable slippage (bps)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _base_bps_for_tvl(pool_tvl_usd: float) -> float:
    """Return the base_bps bucket for a given pool TVL."""
    # Buckets are ordered from lowest to highest threshold; we pick the
    # LAST bucket whose tvl_threshold is strictly greater than the TVL
    # (i.e. the cheapest liquidity tier that can accommodate this TVL).
    buckets = sorted(
        SLIPPAGE_MODEL.values(),
        key=lambda b: b["tvl_threshold"],
    )
    chosen_bps = buckets[-1]["base_bps"]  # default: deep_liquidity
    for bucket in buckets:
        if pool_tvl_usd < bucket["tvl_threshold"]:
            chosen_bps = bucket["base_bps"]
            break
    return float(chosen_bps)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class SlippageSimulator:
    """Estimate price impact and slippage for DeFi position sizing.

    All estimates are *advisory* — they are not used to gate any trade.
    """

    # Re-expose constants as class attributes for easy access in tests.
    SLIPPAGE_MODEL = SLIPPAGE_MODEL
    ACCEPTABLE_SLIPPAGE_BPS = ACCEPTABLE_SLIPPAGE_BPS

    # ------------------------------------------------------------------
    # Core estimate
    # ------------------------------------------------------------------

    def estimate_slippage(
        self,
        adapter_id: str,
        trade_size_usd: float,
        pool_tvl_usd: float,
    ) -> SlippageEstimate:
        """Estimate slippage for a single trade.

        Formula::

            slippage_bps = base_bps * (trade_size_usd / pool_tvl_usd) * 10_000

        A guard prevents division-by-zero: TVL < 1 USD is treated as 1 USD.

        Parameters
        ----------
        adapter_id:
            Identifier for the protocol / adapter.
        trade_size_usd:
            Notional size of the trade in USD.
        pool_tvl_usd:
            Total value locked in the pool, in USD.

        Returns
        -------
        SlippageEstimate
        """
        safe_tvl = max(pool_tvl_usd, 1.0)
        safe_trade = max(trade_size_usd, 0.0)

        base_bps = _base_bps_for_tvl(safe_tvl)

        slippage_bps = base_bps * (safe_trade / safe_tvl) * 10_000
        price_impact_pct = slippage_bps / 100.0
        is_acceptable = slippage_bps <= ACCEPTABLE_SLIPPAGE_BPS

        # Solve for max safe trade at ACCEPTABLE_SLIPPAGE_BPS limit:
        #   30 = base_bps * (x / tvl) * 10_000
        #   x  = 30 * tvl / (base_bps * 10_000)
        max_safe_trade_usd = (ACCEPTABLE_SLIPPAGE_BPS / 10_000.0) * safe_tvl / (base_bps / 10_000.0)

        return SlippageEstimate(
            adapter_id=adapter_id,
            trade_size_usd=safe_trade,
            pool_tvl_usd=safe_tvl,
            slippage_bps=round(slippage_bps, 6),
            price_impact_pct=round(price_impact_pct, 6),
            is_acceptable=is_acceptable,
            max_safe_trade_usd=round(max_safe_trade_usd, 2),
        )

    # ------------------------------------------------------------------
    # Portfolio estimate
    # ------------------------------------------------------------------

    def estimate_portfolio_slippage(
        self,
        trades: Dict[str, float],
        tvl_map: Dict[str, float],
    ) -> List[SlippageEstimate]:
        """Estimate slippage for every adapter in a portfolio.

        Parameters
        ----------
        trades:
            Mapping of ``adapter_id → trade_size_usd``.
        tvl_map:
            Mapping of ``adapter_id → pool_tvl_usd``.

        Returns
        -------
        list of SlippageEstimate — one per adapter in *trades*.
        Missing TVL defaults to 0 (treated as 1 USD after guard).
        """
        results: List[SlippageEstimate] = []
        for adapter_id, trade_size in trades.items():
            tvl = tvl_map.get(adapter_id, 0.0)
            results.append(self.estimate_slippage(adapter_id, trade_size, tvl))
        return results

    # ------------------------------------------------------------------
    # Effective APY
    # ------------------------------------------------------------------

    @staticmethod
    def compute_effective_apy(
        gross_apy: float,
        slippage_bps: float,
        rebalance_frequency_days: int = 30,
    ) -> float:
        """Deduct annualised slippage cost from gross APY.

        Formula::

            annual_slippage_cost = (slippage_bps / 10_000)
                                    * (365 / rebalance_frequency_days)
            effective_apy = gross_apy - annual_slippage_cost

        Parameters
        ----------
        gross_apy:
            Gross annual percentage yield (e.g. 0.065 for 6.5 %).
        slippage_bps:
            One-way slippage in basis points per rebalance event.
        rebalance_frequency_days:
            How often a rebalance occurs (default 30 days).

        Returns
        -------
        float — effective APY (may be negative if slippage dominates).
        """
        freq = max(rebalance_frequency_days, 1)
        annual_slippage_cost = (slippage_bps / 10_000.0) * (365.0 / freq)
        return gross_apy - annual_slippage_cost

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def generate_report(
        self,
        trades: Dict[str, float],
        tvl_map: Dict[str, float],
    ) -> dict:
        """Generate a full slippage report for a set of trades.

        Parameters
        ----------
        trades:
            Mapping of ``adapter_id → trade_size_usd``.
        tvl_map:
            Mapping of ``adapter_id → pool_tvl_usd``.

        Returns
        -------
        dict with keys:

        * ``estimates`` — list of SlippageEstimate (as dicts)
        * ``total_slippage_bps`` — sum of all slippage_bps
        * ``worst_adapter`` — adapter_id with the highest slippage_bps
        * ``best_adapter`` — adapter_id with the lowest slippage_bps
        * ``advisory`` — human-readable advisory string
        """
        estimates = self.estimate_portfolio_slippage(trades, tvl_map)

        if not estimates:
            return {
                "estimates": [],
                "total_slippage_bps": 0.0,
                "worst_adapter": None,
                "best_adapter": None,
                "advisory": "No trades provided.",
            }

        total_bps = sum(e.slippage_bps for e in estimates)
        worst = max(estimates, key=lambda e: e.slippage_bps)
        best = min(estimates, key=lambda e: e.slippage_bps)

        unacceptable = [e for e in estimates if not e.is_acceptable]
        if unacceptable:
            advisory = (
                f"{len(unacceptable)} of {len(estimates)} trades exceed "
                f"{ACCEPTABLE_SLIPPAGE_BPS} bps slippage limit. "
                "Consider splitting large trades or choosing higher-TVL pools."
            )
        else:
            advisory = (
                f"All {len(estimates)} trades within {ACCEPTABLE_SLIPPAGE_BPS} bps "
                "slippage limit. Estimates are advisory only."
            )

        def _est_to_dict(e: SlippageEstimate) -> dict:
            return {
                "adapter_id": e.adapter_id,
                "trade_size_usd": e.trade_size_usd,
                "pool_tvl_usd": e.pool_tvl_usd,
                "slippage_bps": e.slippage_bps,
                "price_impact_pct": e.price_impact_pct,
                "is_acceptable": e.is_acceptable,
                "max_safe_trade_usd": e.max_safe_trade_usd,
            }

        return {
            "estimates": [_est_to_dict(e) for e in estimates],
            "total_slippage_bps": round(total_bps, 6),
            "worst_adapter": worst.adapter_id,
            "best_adapter": best.adapter_id,
            "advisory": advisory,
        }


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _demo_run() -> None:
    """Run a demo estimate and print the report."""
    sim = SlippageSimulator()
    trades = {
        "aave_v3": 50_000.0,
        "compound_v3": 30_000.0,
        "morpho_steakhouse": 20_000.0,
    }
    tvl_map = {
        "aave_v3": 2_000_000_000.0,
        "compound_v3": 500_000_000.0,
        "morpho_steakhouse": 80_000_000.0,
    }
    import json
    report = sim.generate_report(trades, tvl_map)
    print(json.dumps(report, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: --check (print only) or --run (same for now — no disk write)."""
    args = argv if argv is not None else sys.argv[1:]
    _demo_run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

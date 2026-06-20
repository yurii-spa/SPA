"""
MP-984: DeFiYieldSourceDiversificationScorer
Evaluates diversification of yield sources across a DeFi portfolio.
Pure stdlib — no external dependencies.
"""

import json
import os
import math
import time
from datetime import datetime, timezone
from typing import Any
from spa_core.utils.atomic import atomic_save

VALID_YIELD_SOURCES = {
    "trading_fees",
    "lending_interest",
    "staking_rewards",
    "liquidity_mining",
    "real_yield",
    "points",
    "basis_trade",
}

DIVERSITY_LABELS = [
    (80.0, "HIGHLY_DIVERSIFIED"),
    (60.0, "DIVERSIFIED"),
    (40.0, "MODERATE"),
    (20.0, "CONCENTRATED"),
    (0.0,  "SINGLE_SOURCE"),
]

LOG_CAP = 100
DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "yield_diversification_log.json",
)


def _hhi(shares_pct: list[float]) -> float:
    """HHI as sum of squared fractional shares (0–1 scale).
    Perfect concentration → 1.0; perfect equal split among n → 1/n.
    """
    total = sum(shares_pct)
    if total <= 0:
        return 1.0
    return sum((s / total) ** 2 for s in shares_pct)


def _group_shares(items: list[dict], key: str, value_key: str = "capital_usd") -> dict[str, float]:
    """Group capital by a categorical key and return {category: total_capital}."""
    groups: dict[str, float] = {}
    for item in items:
        cat = str(item.get(key, "unknown"))
        val = float(item.get(value_key, 0.0))
        groups[cat] = groups.get(cat, 0.0) + val
    return groups


def _diversity_label(score: float) -> str:
    for threshold, label in DIVERSITY_LABELS:
        if score >= threshold:
            return label
    return "SINGLE_SOURCE"


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
class DeFiYieldSourceDiversificationScorer:
    """
    Scores yield-source diversification across a DeFi portfolio.

    Input schema per position:
        asset_name            str   — position label
        yield_source_type     str   — one of VALID_YIELD_SOURCES
        protocol              str   — protocol name
        chain                 str   — blockchain name
        yield_pct             float — annualised yield percentage (e.g. 5.0 = 5%)
        capital_usd           float — USD capital in this position
        correlated_with_market bool  — True if yield degrades in bear markets

    Config keys (all optional):
        log_path              str   — path to ring-buffer log file
        disable_log           bool  — skip log write (default False)
        real_yield_heavy_threshold   float  (default 40.0)
        points_heavy_threshold       float  (default 30.0)
        bear_market_exposed_threshold float (default 60.0)
        protocol_concentrated_threshold float (default 50.0)
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, portfolio: list[dict], config: dict | None = None) -> dict:
        config = config or {}

        log_path = config.get("log_path", DEFAULT_LOG_PATH)
        disable_log = bool(config.get("disable_log", False))

        real_yield_threshold = float(config.get("real_yield_heavy_threshold", 40.0))
        points_threshold = float(config.get("points_heavy_threshold", 30.0))
        bear_threshold = float(config.get("bear_market_exposed_threshold", 60.0))
        proto_conc_threshold = float(config.get("protocol_concentrated_threshold", 50.0))

        if not portfolio:
            result = self._empty_result()
            if not disable_log:
                self._append_log(result, log_path)
            return result

        # ---- normalise & validate -------------------------------------------
        positions = []
        for pos in portfolio:
            positions.append({
                "asset_name":           str(pos.get("asset_name", "unknown")),
                "yield_source_type":    str(pos.get("yield_source_type", "unknown")),
                "protocol":             str(pos.get("protocol", "unknown")),
                "chain":                str(pos.get("chain", "unknown")),
                "yield_pct":            float(pos.get("yield_pct", 0.0)),
                "capital_usd":          float(pos.get("capital_usd", 0.0)),
                "correlated_with_market": bool(pos.get("correlated_with_market", False)),
            })

        total_capital = sum(p["capital_usd"] for p in positions)
        if total_capital <= 0:
            result = self._empty_result("zero_capital")
            if not disable_log:
                self._append_log(result, log_path)
            return result

        # ---- per-type breakdown ----------------------------------------------
        type_capital: dict[str, float] = {}
        type_yield_weighted: dict[str, float] = {}
        for p in positions:
            t = p["yield_source_type"]
            type_capital[t] = type_capital.get(t, 0.0) + p["capital_usd"]
            type_yield_weighted[t] = (
                type_yield_weighted.get(t, 0.0) + p["capital_usd"] * p["yield_pct"]
            )

        per_type_allocation: dict[str, float] = {}
        per_type_yield_contribution: dict[str, float] = {}
        total_yield_weighted = sum(type_yield_weighted.values())

        for t in type_capital:
            per_type_allocation[t] = round(type_capital[t] / total_capital * 100, 4)
            if total_yield_weighted > 0:
                per_type_yield_contribution[t] = round(
                    type_yield_weighted[t] / total_yield_weighted * 100, 4
                )
            else:
                per_type_yield_contribution[t] = 0.0

        # ---- protocol & chain breakdown --------------------------------------
        proto_capital = _group_shares(positions, "protocol", "capital_usd")
        chain_capital = _group_shares(positions, "chain", "capital_usd")

        # ---- HHI computations ------------------------------------------------
        source_hhi = _hhi(list(type_capital.values()))
        protocol_hhi = _hhi(list(proto_capital.values()))
        chain_hhi = _hhi(list(chain_capital.values()))

        source_score = (1.0 - source_hhi) * 100.0
        protocol_score = (1.0 - protocol_hhi) * 100.0
        chain_score = (1.0 - chain_hhi) * 100.0

        diversification_score = round(
            0.40 * source_score + 0.35 * protocol_score + 0.25 * chain_score, 4
        )

        # ---- bear-market exposure --------------------------------------------
        bear_capital = sum(
            p["capital_usd"] for p in positions if p["correlated_with_market"]
        )
        bear_market_exposure_pct = round(bear_capital / total_capital * 100, 4)

        # ---- weighted avg yield ----------------------------------------------
        weighted_avg_yield_pct = round(
            sum(p["capital_usd"] * p["yield_pct"] for p in positions) / total_capital, 6
        )

        # ---- dominant values -------------------------------------------------
        dominant_source_type = max(type_capital, key=type_capital.get)
        dominant_protocol = max(proto_capital, key=proto_capital.get)
        dominant_chain = max(chain_capital, key=chain_capital.get)

        # ---- flags -----------------------------------------------------------
        flags: list[str] = []

        if len(chain_capital) == 1:
            flags.append("SINGLE_CHAIN")

        dominant_proto_pct = proto_capital[dominant_protocol] / total_capital * 100
        if dominant_proto_pct > proto_conc_threshold:
            flags.append("PROTOCOL_CONCENTRATED")

        real_yield_pct = per_type_allocation.get("real_yield", 0.0)
        if real_yield_pct > real_yield_threshold:
            flags.append("REAL_YIELD_HEAVY")

        points_pct = per_type_allocation.get("points", 0.0)
        if points_pct > points_threshold:
            flags.append("POINTS_HEAVY")

        if bear_market_exposure_pct > bear_threshold:
            flags.append("BEAR_MARKET_EXPOSED")

        # ---- diversity label -------------------------------------------------
        diversity_label = _diversity_label(diversification_score)

        # ---- protocol-level detail ------------------------------------------
        protocol_allocation: dict[str, float] = {
            p: round(v / total_capital * 100, 4) for p, v in proto_capital.items()
        }
        chain_allocation: dict[str, float] = {
            c: round(v / total_capital * 100, 4) for c, v in chain_capital.items()
        }

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "position_count": len(positions),
            "total_capital_usd": round(total_capital, 4),
            "weighted_avg_yield_pct": weighted_avg_yield_pct,
            "bear_market_exposure_pct": bear_market_exposure_pct,
            # HHI values (0–1 scale)
            "source_hhi": round(source_hhi, 6),
            "protocol_hhi": round(protocol_hhi, 6),
            "chain_hhi": round(chain_hhi, 6),
            # Component scores
            "source_diversity_score": round(source_score, 4),
            "protocol_diversity_score": round(protocol_score, 4),
            "chain_diversity_score": round(chain_score, 4),
            # Final score
            "diversification_score": diversification_score,
            "diversity_label": diversity_label,
            # Flags
            "flags": flags,
            # Breakdowns
            "per_type_allocation_pct": per_type_allocation,
            "per_type_yield_contribution_pct": per_type_yield_contribution,
            "protocol_allocation_pct": protocol_allocation,
            "chain_allocation_pct": chain_allocation,
            # Dominants
            "dominant_source_type": dominant_source_type,
            "dominant_protocol": dominant_protocol,
            "dominant_chain": dominant_chain,
            # Portfolio-level
            "total_portfolio_yield_pct": weighted_avg_yield_pct,
        }

        if not disable_log:
            self._append_log(result, log_path)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_result(self, reason: str = "empty_portfolio") -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "position_count": 0,
            "total_capital_usd": 0.0,
            "weighted_avg_yield_pct": 0.0,
            "bear_market_exposure_pct": 0.0,
            "source_hhi": 1.0,
            "protocol_hhi": 1.0,
            "chain_hhi": 1.0,
            "source_diversity_score": 0.0,
            "protocol_diversity_score": 0.0,
            "chain_diversity_score": 0.0,
            "diversification_score": 0.0,
            "diversity_label": "SINGLE_SOURCE",
            "flags": [],
            "per_type_allocation_pct": {},
            "per_type_yield_contribution_pct": {},
            "protocol_allocation_pct": {},
            "chain_allocation_pct": {},
            "dominant_source_type": None,
            "dominant_protocol": None,
            "dominant_chain": None,
            "total_portfolio_yield_pct": 0.0,
            "error": reason,
        }

    def _append_log(self, entry: dict, log_path: str) -> None:
        """Append entry to ring-buffer log (cap=100), atomic write."""
        try:
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    log = json.load(f)
                if not isinstance(log, list):
                    log = []
            else:
                log = []
            log.append(entry)
            if len(log) > LOG_CAP:
                log = log[-LOG_CAP:]
            _atomic_write(log_path, log)
        except Exception:
            pass  # log failures must never break the main flow


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sample_portfolio = [
        {
            "asset_name": "Aave USDC",
            "yield_source_type": "lending_interest",
            "protocol": "Aave",
            "chain": "Ethereum",
            "yield_pct": 3.5,
            "capital_usd": 30000.0,
            "correlated_with_market": False,
        },
        {
            "asset_name": "Uniswap ETH/USDC LP",
            "yield_source_type": "trading_fees",
            "protocol": "Uniswap",
            "chain": "Ethereum",
            "yield_pct": 8.0,
            "capital_usd": 20000.0,
            "correlated_with_market": True,
        },
        {
            "asset_name": "Lido stETH",
            "yield_source_type": "staking_rewards",
            "protocol": "Lido",
            "chain": "Ethereum",
            "yield_pct": 4.0,
            "capital_usd": 25000.0,
            "correlated_with_market": True,
        },
        {
            "asset_name": "Curve CRV rewards",
            "yield_source_type": "liquidity_mining",
            "protocol": "Curve",
            "chain": "Arbitrum",
            "yield_pct": 12.0,
            "capital_usd": 15000.0,
            "correlated_with_market": True,
        },
        {
            "asset_name": "GMX Real Yield",
            "yield_source_type": "real_yield",
            "protocol": "GMX",
            "chain": "Arbitrum",
            "yield_pct": 15.0,
            "capital_usd": 10000.0,
            "correlated_with_market": False,
        },
    ]

    scorer = DeFiYieldSourceDiversificationScorer()
    result = scorer.score(sample_portfolio, {"disable_log": True})
    print(json.dumps(result, indent=2))

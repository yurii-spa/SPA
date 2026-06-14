"""
MP-780: CrossChainYieldComparator
Compares yield opportunities across chains, accounting for bridge costs.
Outputs ranked_opportunities (by net_apy), cross_chain_arbitrage_score (0-100),
recommended_chain. Ring buffer log, capped 100 entries, atomic write.
stdlib only. LLM_FORBIDDEN.
"""

import json
import os
import time
import tempfile
from typing import List, Dict, Optional, Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_FILE = os.path.join(DATA_DIR, "cross_chain_yield_log.json")
LOG_CAP = 100
DAYS_PER_YEAR = 365.0


# ---------------------------------------------------------------------------
# Opportunity dataclass-like helpers
# ---------------------------------------------------------------------------

def _validate_opportunity(opp: Dict[str, Any]) -> None:
    """Raise ValueError if a required field is missing or out of range."""
    required = [
        "chain", "protocol", "apy",
        "bridge_cost_usd", "bridge_time_hours", "chain_gas_cost_daily_usd",
    ]
    for field in required:
        if field not in opp:
            raise ValueError(f"Missing field '{field}' in opportunity: {opp}")
    if opp["apy"] < 0:
        raise ValueError(f"apy must be non-negative, got {opp['apy']}")
    if opp["bridge_cost_usd"] < 0:
        raise ValueError(f"bridge_cost_usd must be non-negative")
    if opp["bridge_time_hours"] < 0:
        raise ValueError(f"bridge_time_hours must be non-negative")
    if opp["chain_gas_cost_daily_usd"] < 0:
        raise ValueError(f"chain_gas_cost_daily_usd must be non-negative")


def _compute_net_apy(opp: Dict[str, Any], capital_usd: float) -> float:
    """
    net_apy = apy - (bridge_cost + chain_gas_cost_daily * 365) / capital_usd * 100
    Returns a float (percentage points).
    """
    if capital_usd <= 0:
        raise ValueError("capital_usd must be positive")
    annual_cost_usd = opp["bridge_cost_usd"] + opp["chain_gas_cost_daily_usd"] * DAYS_PER_YEAR
    cost_pct = (annual_cost_usd / capital_usd) * 100.0
    return opp["apy"] - cost_pct


def _compute_chain_premium(net_apy: float, eth_baseline_apy: float) -> float:
    """chain_premium_vs_eth = net_apy - eth_baseline_apy (both in %, as stored)."""
    # eth_baseline_apy supplied as fraction (e.g. 0.04 = 4%) → convert to pct
    return net_apy - (eth_baseline_apy * 100.0)


def _compute_arbitrage_score(opportunities: List[Dict[str, Any]]) -> float:
    """
    cross_chain_arbitrage_score (0-100).

    Logic:
    - spread = max_net_apy - min_net_apy across ranked opportunities
    - Score scales with spread:  score = min(100, spread * 10)
    - If only one opportunity → score 0 (no arbitrage possible)
    """
    if len(opportunities) < 2:
        return 0.0
    net_apys = [o["net_apy"] for o in opportunities]
    spread = max(net_apys) - min(net_apys)
    score = min(100.0, spread * 10.0)
    return round(score, 2)


def _best_chain_per_category(opportunities: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Returns {category: chain} where category is the protocol name (no sub-category
    schema in the spec, so we use protocol as category key).
    """
    best: Dict[str, Dict] = {}
    for opp in opportunities:
        proto = opp["protocol"]
        if proto not in best or opp["net_apy"] > best[proto]["net_apy"]:
            best[proto] = opp
    return {proto: info["chain"] for proto, info in best.items()}


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_log(path: str) -> List[Any]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(path: str, entry: Any, cap: int = LOG_CAP) -> None:
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write_json(path, log)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CrossChainYieldComparator:
    """
    MP-780: Compare yield opportunities across chains net of bridge and gas costs.

    Usage:
        cmp = CrossChainYieldComparator()
        result = cmp.compare(opportunities, capital_usd=100_000)
        best = cmp.get_best_opportunity()
        ranking = cmp.get_chain_ranking()
    """

    def __init__(self, data_dir: Optional[str] = None, log_cap: int = LOG_CAP):
        self._data_dir = data_dir or DATA_DIR
        self._log_file = os.path.join(self._data_dir, "cross_chain_yield_log.json")
        self._log_cap = log_cap
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(
        self,
        opportunities: List[Dict[str, Any]],
        capital_usd: float,
        eth_baseline_apy: float = 0.04,
        write_log: bool = False,
    ) -> Dict[str, Any]:
        """
        Compare cross-chain yield opportunities.

        Parameters
        ----------
        opportunities : list of dicts with keys:
            chain, protocol, apy (%), bridge_cost_usd, bridge_time_hours,
            chain_gas_cost_daily_usd
        capital_usd : float — deployed capital used to amortise fixed costs
        eth_baseline_apy : float — Ethereum baseline APY as fraction (default 0.04 = 4%)
        write_log : bool — persist result to ring-buffer log

        Returns
        -------
        dict with:
            ranked_opportunities, cross_chain_arbitrage_score,
            recommended_chain, best_chain_per_protocol,
            timestamp_utc, capital_usd, eth_baseline_apy_pct
        """
        if capital_usd <= 0:
            raise ValueError("capital_usd must be positive")
        if not opportunities:
            result = self._empty_result(capital_usd, eth_baseline_apy)
            self._last_result = result
            if write_log:
                self._persist(result)
            return result

        enriched: List[Dict[str, Any]] = []
        for opp in opportunities:
            _validate_opportunity(opp)
            net_apy = _compute_net_apy(opp, capital_usd)
            chain_premium = _compute_chain_premium(net_apy, eth_baseline_apy)
            entry = dict(opp)
            entry["net_apy"] = round(net_apy, 6)
            entry["chain_premium_vs_eth"] = round(chain_premium, 6)
            entry["annual_cost_usd"] = round(
                opp["bridge_cost_usd"] + opp["chain_gas_cost_daily_usd"] * DAYS_PER_YEAR, 4
            )
            enriched.append(entry)

        ranked = sorted(enriched, key=lambda x: x["net_apy"], reverse=True)
        arb_score = _compute_arbitrage_score(ranked)
        recommended = ranked[0]["chain"] if ranked else None
        best_per_proto = _best_chain_per_category(ranked)

        result = {
            "ranked_opportunities": ranked,
            "cross_chain_arbitrage_score": arb_score,
            "recommended_chain": recommended,
            "best_chain_per_protocol": best_per_proto,
            "capital_usd": capital_usd,
            "eth_baseline_apy_pct": round(eth_baseline_apy * 100.0, 4),
            "timestamp_utc": time.time(),
            "opportunity_count": len(ranked),
        }
        self._last_result = result
        if write_log:
            self._persist(result)
        return result

    def get_best_opportunity(self) -> Optional[Dict[str, Any]]:
        """
        Return the top-ranked opportunity from the last compare() call.
        Returns None if compare() has not been called yet or had no opportunities.
        """
        if self._last_result is None:
            return None
        ranked = self._last_result.get("ranked_opportunities", [])
        return ranked[0] if ranked else None

    def get_chain_ranking(self) -> List[Dict[str, Any]]:
        """
        Return a list of {chain, avg_net_apy, max_net_apy, opportunity_count}
        sorted by avg_net_apy descending, derived from the last compare() call.
        """
        if self._last_result is None:
            return []
        ranked = self._last_result.get("ranked_opportunities", [])
        if not ranked:
            return []

        chain_data: Dict[str, List[float]] = {}
        for opp in ranked:
            chain = opp["chain"]
            chain_data.setdefault(chain, [])
            chain_data[chain].append(opp["net_apy"])

        chain_ranking = []
        for chain, apys in chain_data.items():
            chain_ranking.append({
                "chain": chain,
                "avg_net_apy": round(sum(apys) / len(apys), 6),
                "max_net_apy": round(max(apys), 6),
                "min_net_apy": round(min(apys), 6),
                "opportunity_count": len(apys),
            })
        chain_ranking.sort(key=lambda x: x["avg_net_apy"], reverse=True)
        return chain_ranking

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _persist(self, result: Dict[str, Any]) -> None:
        """Append summary entry to ring-buffer log."""
        summary = {
            "timestamp_utc": result["timestamp_utc"],
            "capital_usd": result["capital_usd"],
            "eth_baseline_apy_pct": result["eth_baseline_apy_pct"],
            "recommended_chain": result["recommended_chain"],
            "cross_chain_arbitrage_score": result["cross_chain_arbitrage_score"],
            "opportunity_count": result["opportunity_count"],
            "top_net_apy": (
                result["ranked_opportunities"][0]["net_apy"]
                if result["ranked_opportunities"]
                else None
            ),
        }
        _append_log(self._log_file, summary, self._log_cap)

    @staticmethod
    def _empty_result(capital_usd: float, eth_baseline_apy: float) -> Dict[str, Any]:
        return {
            "ranked_opportunities": [],
            "cross_chain_arbitrage_score": 0.0,
            "recommended_chain": None,
            "best_chain_per_protocol": {},
            "capital_usd": capital_usd,
            "eth_baseline_apy_pct": round(eth_baseline_apy * 100.0, 4),
            "timestamp_utc": time.time(),
            "opportunity_count": 0,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    """Quick smoke-test with sample data."""
    opps = [
        {
            "chain": "ethereum",
            "protocol": "aave_v3",
            "apy": 4.5,
            "bridge_cost_usd": 0.0,
            "bridge_time_hours": 0.0,
            "chain_gas_cost_daily_usd": 2.0,
        },
        {
            "chain": "arbitrum",
            "protocol": "aave_v3",
            "apy": 5.8,
            "bridge_cost_usd": 15.0,
            "bridge_time_hours": 0.1,
            "chain_gas_cost_daily_usd": 0.10,
        },
        {
            "chain": "base",
            "protocol": "compound_v3",
            "apy": 6.2,
            "bridge_cost_usd": 10.0,
            "bridge_time_hours": 0.05,
            "chain_gas_cost_daily_usd": 0.05,
        },
    ]
    cmp = CrossChainYieldComparator()
    result = cmp.compare(opps, capital_usd=100_000, eth_baseline_apy=0.04)
    print(json.dumps(result, indent=2))
    print("Best opportunity:", json.dumps(cmp.get_best_opportunity(), indent=2))
    print("Chain ranking:", json.dumps(cmp.get_chain_ranking(), indent=2))


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        _demo()
    else:
        print("Usage: python3 -m spa_core.analytics.cross_chain_yield_comparator --demo")

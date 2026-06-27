"""
MP-1056 | DeFiProtocolCrossChainYieldComparator
Read-only / advisory analytics. No trades. Pure stdlib.
Log: data/cross_chain_yield_comparator_log.json (ring-buffer 100)

Ranks DeFi positions across chains by effective (net) APY after accounting
for bridge fees, annualised gas costs, and entry slippage.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from spa_core.utils import clock

_LOG_CAP = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "cross_chain_yield_comparator_log.json"
)

_REC_TOP_PICK = "TOP_PICK"
_REC_STRONG   = "STRONG"
_REC_NEUTRAL  = "NEUTRAL"
_REC_WEAK     = "WEAK"
_REC_AVOID    = "AVOID"


# ---------------------------------------------------------------------------
# I/O helpers (pure stdlib, atomic writes)
# ---------------------------------------------------------------------------

def _atomic_write_json(path: str, data: Any) -> None:
    """Write JSON atomically: write to .tmp then os.replace."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    finally:
        # Clean up orphan tmp on any failure path
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass


def _append_ring_log(path: str, entry: dict, cap: int = _LOG_CAP) -> None:
    """Append *entry* to a ring-buffer JSON list capped at *cap* entries."""
    try:
        with open(path, encoding="utf-8") as fh:
            log: List[dict] = json.load(fh)
        if not isinstance(log, list):
            log = []
    except Exception:
        log = []
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write_json(path, log)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolCrossChainYieldComparator:
    """
    Advisory-only cross-chain DeFi yield comparator.

    Computes, for each candidate position:
    - migration_cost_usd   : total one-time + recurring entry cost
    - net_apy_pct          : gross APY minus annualised migration drag
    - break_even_days      : days until gross yield recoups migration cost
    - yield_advantage_pct  : net_apy delta vs the weakest position
    - recommendation       : TOP_PICK | STRONG | NEUTRAL | WEAK | AVOID

    Sorted output: ranked_positions (highest net_apy first).
    No trades, no allocator/risk/execution writes.
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = os.path.normpath(log_path or _DEFAULT_LOG_PATH)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parameters
        ----------
        data : dict
            positions            : list[dict]
                chain               : str
                protocol            : str
                apy_pct             : float
                tvl_usd             : float
                bridge_cost_usd     : float
                gas_cost_usd_per_year: float
                slippage_pct        : float
                days_locked         : int
            capital_usd          : float   – capital being deployed
            holding_period_days  : float   – intended holding period (> 0)

        Returns
        -------
        dict
            ranked_positions : list[dict]  sorted by net_apy_pct desc;
                each entry copies all input fields and adds:
                migration_cost_usd, net_apy_pct, break_even_days,
                yield_advantage_pct, recommendation
        """
        raw_positions: List[dict] = list(data.get("positions") or [])
        capital_usd = float(data.get("capital_usd") or 0)
        holding_period_days = float(data.get("holding_period_days") or 1)
        if holding_period_days <= 0:
            holding_period_days = 1.0

        enriched = [
            self._enrich_position(p, capital_usd, holding_period_days)
            for p in raw_positions
        ]

        # Primary sort: net_apy_pct descending
        enriched.sort(key=lambda x: x["net_apy_pct"], reverse=True)

        # yield_advantage_pct = distance from worst option
        if enriched:
            worst_net = enriched[-1]["net_apy_pct"]
            best_net  = enriched[0]["net_apy_pct"]
            for pos in enriched:
                pos["yield_advantage_pct"] = round(pos["net_apy_pct"] - worst_net, 6)
        else:
            best_net = 0.0

        # Assign labels
        for rank, pos in enumerate(enriched):
            pos["recommendation"] = self._recommend(
                net_apy=pos["net_apy_pct"],
                rank=rank,
                best_net_apy=best_net,
            )

        self._log(capital_usd, holding_period_days, enriched)
        return {"ranked_positions": enriched}

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _migration_cost(
        self, pos: dict, capital_usd: float, holding_period_days: float
    ) -> float:
        """
        Total cost to enter and maintain a position for *holding_period_days*:
            bridge_cost_usd (one-time)
          + gas_cost_usd_per_year prorated to holding period
          + slippage on capital
        """
        bridge   = float(pos.get("bridge_cost_usd") or 0)
        gas      = float(pos.get("gas_cost_usd_per_year") or 0) * (holding_period_days / 365.0)
        slippage = capital_usd * float(pos.get("slippage_pct") or 0) / 100.0
        return bridge + gas + slippage

    def _net_apy(
        self,
        apy_pct: float,
        migration_cost: float,
        capital_usd: float,
        holding_period_days: float,
    ) -> float:
        """Net annualised return (%) after deducting migration cost."""
        if capital_usd <= 0:
            return 0.0
        gross_yield = capital_usd * apy_pct / 100.0 * (holding_period_days / 365.0)
        net_yield   = gross_yield - migration_cost
        return round((net_yield / capital_usd) * (365.0 / holding_period_days) * 100.0, 6)

    def _break_even_days(
        self, apy_pct: float, migration_cost: float, capital_usd: float
    ) -> float:
        """Days for gross yield to recoup migration cost (inf if impossible)."""
        if migration_cost <= 0:
            return 0.0
        if capital_usd <= 0 or apy_pct <= 0:
            return float("inf")
        daily_yield = capital_usd * apy_pct / 100.0 / 365.0
        if daily_yield <= 0:
            return float("inf")
        return round(migration_cost / daily_yield, 4)

    def _enrich_position(
        self, pos: dict, capital_usd: float, holding_period_days: float
    ) -> dict:
        result = dict(pos)
        apy_pct = float(pos.get("apy_pct") or 0)
        mc  = self._migration_cost(pos, capital_usd, holding_period_days)
        net = self._net_apy(apy_pct, mc, capital_usd, holding_period_days)
        be  = self._break_even_days(apy_pct, mc, capital_usd)
        result["migration_cost_usd"]  = round(mc, 6)
        result["net_apy_pct"]         = net
        result["break_even_days"]     = be
        result["yield_advantage_pct"] = 0.0  # filled after sort
        result["recommendation"]      = ""   # filled after sort
        return result

    def _recommend(self, net_apy: float, rank: int, best_net_apy: float) -> str:
        """
        Recommendation rules:
        - rank 0 (highest net_apy)          → TOP_PICK  (always the best option)
        - net_apy < 0                        → AVOID     (losing money net of costs)
        - best_net_apy <= 0 (all <= 0)       → NEUTRAL   (all break-even or negative)
        - ratio = net_apy / best_net_apy:
            >= 0.90                          → STRONG
            >= 0.70                          → NEUTRAL
            >= 0.50                          → WEAK
            < 0.50                           → AVOID
        """
        if rank == 0:
            return _REC_TOP_PICK
        if net_apy < 0:
            return _REC_AVOID
        if best_net_apy <= 0:
            return _REC_NEUTRAL
        ratio = net_apy / best_net_apy
        if ratio >= 0.90:
            return _REC_STRONG
        if ratio >= 0.70:
            return _REC_NEUTRAL
        if ratio >= 0.50:
            return _REC_WEAK
        return _REC_AVOID

    def _log(
        self, capital_usd: float, holding_period_days: float, enriched: List[dict]
    ) -> None:
        try:
            top = enriched[0] if enriched else {}
            entry = {
                "ts":                  clock.utcnow().isoformat() + "Z",
                "capital_usd":         capital_usd,
                "holding_period_days": holding_period_days,
                "n_positions":         len(enriched),
                "top_pick_protocol":   top.get("protocol"),
                "top_pick_net_apy":    top.get("net_apy_pct"),
            }
            _append_ring_log(self._log_path, entry)
        except Exception:
            pass  # advisory — never propagate logging failures

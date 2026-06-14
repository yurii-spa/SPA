"""
MP-1111: DeFiProtocolCrossChainYieldBasisRiskAnalyzer
Analyzes basis risk arising when the same underlying asset generates different
yields across DeFi protocols or chains. Quantifies spread, convergence risk,
bridge/migration costs, and optimal rebalancing decisions.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "cross_chain_basis_risk_log.json"
)
LOG_CAP = 100

# Basis spread thresholds (percentage points)
SPREAD_WIDE       = 3.0    # spread >3pp → basis risk flag
SPREAD_VERY_WIDE  = 7.0    # spread >7pp → arbitrage anomaly
SPREAD_NARROW     = 0.5    # spread <0.5pp → well-converged

# Convergence speed categories (half-life in days)
CONVERGENCE_FAST  = 7.0    # <1 week
CONVERGENCE_SLOW  = 30.0   # >1 month

# Bridge cost thresholds (USD)
BRIDGE_COST_HIGH  = 50.0   # >$50 bridge cost → not economical for small positions

# Minimum APY differential needed to justify migration (net of bridge + gas)
MIN_MIGRATION_BENEFIT_PP = 0.5   # 0.5pp net improvement


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _spread(apy_a: float, apy_b: float) -> float:
    """Absolute spread between two APYs in percentage points."""
    return abs(apy_a - apy_b)


def _zscore(value: float, mean: float, std: float) -> float:
    """Standard z-score; returns 0 when std=0."""
    if std <= 0:
        return 0.0
    return (value - mean) / std


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _breakeven_days(
    position_usd: float,
    apy_diff_pct: float,
    bridge_cost_usd: float,
    gas_cost_usd: float,
) -> Optional[float]:
    """
    Days to break even on migrating to a higher-yield protocol.
    daily_gain = position * apy_diff / 100 / 365
    """
    total_cost = bridge_cost_usd + gas_cost_usd
    if apy_diff_pct <= 0 or position_usd <= 0:
        return None
    daily_gain = position_usd * apy_diff_pct / 100.0 / 365.25
    if daily_gain <= 0:
        return None
    return total_cost / daily_gain


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolCrossChainYieldBasisRiskAnalyzer:
    """
    Analyzes yield basis risk across DeFi protocols/chains for the same
    underlying asset (e.g. USDC on Aave-Ethereum vs Aave-Arbitrum vs Compound).

    Input `asset_groups`: list of asset group dicts, each containing:
        asset               : str   (e.g. "USDC", "ETH")
        legs                : list[dict] — each leg:
            protocol        : str
            chain           : str
            apy_pct         : float
            tvl_usd         : float
            bridge_cost_usd : float  (cost to move position to this leg)
            gas_cost_usd    : float  (harvest/entry/exit gas)
            apy_history_7d  : list[float]  (optional, for volatility)
        position_usd        : float (how much the user has to deploy/already has)
        current_leg         : str   (protocol:chain currently deployed, optional)
    """

    def analyze(
        self,
        asset_groups: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_group(g) for g in asset_groups]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"asset_groups": results, "aggregate": agg}

    # ── per-group ─────────────────────────────────────────────────────────────

    def _analyze_group(self, g: dict) -> dict:
        asset    = g.get("asset", "UNKNOWN")
        legs     = g.get("legs", [])
        pos_usd  = float(g.get("position_usd", 0.0))
        cur_leg  = g.get("current_leg", None)

        if not legs:
            return {
                "asset": asset,
                "legs": [],
                "basis_spread_pp": 0.0,
                "best_leg": None,
                "worst_leg": None,
                "spread_label": "NO_DATA",
                "migration_recommendation": None,
                "flags": ["NO_LEGS"],
            }

        # APY stats
        apys   = [float(l.get("apy_pct", 0.0)) for l in legs]
        apy_mean = _mean(apys)
        apy_std  = _std(apys)
        max_apy  = max(apys)
        min_apy  = min(apys)
        basis_spread = _spread(max_apy, min_apy)

        # Rank legs
        ranked = sorted(
            legs,
            key=lambda l: float(l.get("apy_pct", 0.0)),
            reverse=True
        )
        best_leg  = ranked[0]
        worst_leg = ranked[-1]

        # Per-leg details
        leg_details = [
            self._score_leg(l, apy_mean, apy_std, pos_usd, best_leg)
            for l in legs
        ]

        # Migration recommendation
        migration = self._migration_rec(
            cur_leg, best_leg, leg_details, pos_usd, basis_spread
        )

        spread_label = self._spread_label(basis_spread)
        flags = self._flags(basis_spread, apy_std, legs, migration)

        return {
            "asset":            asset,
            "legs":             leg_details,
            "basis_spread_pp":  round(basis_spread, 4),
            "spread_label":     spread_label,
            "apy_mean_pct":     round(apy_mean, 4),
            "apy_std_pct":      round(apy_std, 4),
            "best_leg":         f"{best_leg.get('protocol')}:{best_leg.get('chain')}",
            "worst_leg":        f"{worst_leg.get('protocol')}:{worst_leg.get('chain')}",
            "migration_recommendation": migration,
            "flags":            flags,
        }

    def _score_leg(
        self,
        leg: dict,
        apy_mean: float,
        apy_std: float,
        pos_usd: float,
        best_leg: dict,
    ) -> dict:
        protocol = leg.get("protocol", "unknown")
        chain    = leg.get("chain", "unknown")
        apy      = float(leg.get("apy_pct", 0.0))
        tvl      = float(leg.get("tvl_usd", 0.0))
        bridge   = float(leg.get("bridge_cost_usd", 0.0))
        gas      = float(leg.get("gas_cost_usd", 5.0))
        history  = [float(x) for x in leg.get("apy_history_7d", [])]

        apy_z     = _zscore(apy, apy_mean, apy_std)
        apy_vol   = _std(history) if history else 0.0

        # Spread vs best
        best_apy = float(best_leg.get("apy_pct", 0.0))
        vs_best  = apy - best_apy   # always ≤ 0 except for best leg

        # Break-even days to migrate to best leg from this leg
        be_days = _breakeven_days(pos_usd, max(0.0, best_apy - apy), bridge, gas)

        return {
            "leg_id":           f"{protocol}:{chain}",
            "protocol":         protocol,
            "chain":            chain,
            "apy_pct":          round(apy, 4),
            "apy_z_score":      round(apy_z, 4),
            "apy_7d_vol_pp":    round(apy_vol, 4),
            "tvl_usd":          round(tvl, 2),
            "bridge_cost_usd":  round(bridge, 2),
            "apy_vs_best_pp":   round(vs_best, 4),
            "breakeven_days_to_best": round(be_days, 1) if be_days is not None else None,
        }

    # ── migration recommendation ──────────────────────────────────────────────

    def _migration_rec(
        self,
        cur_leg: Optional[str],
        best_leg: dict,
        leg_details: List[dict],
        pos_usd: float,
        spread: float,
    ) -> Optional[dict]:
        best_id = f"{best_leg.get('protocol')}:{best_leg.get('chain')}"
        best_apy = float(best_leg.get("apy_pct", 0.0))

        if cur_leg is None or cur_leg == best_id:
            return None   # already optimal or unknown

        # Find current leg details
        cur_detail = next((l for l in leg_details if l["leg_id"] == cur_leg), None)
        if cur_detail is None:
            return None

        cur_apy   = cur_detail["apy_pct"]
        bridge    = float(best_leg.get("bridge_cost_usd", 0.0))
        gas       = float(best_leg.get("gas_cost_usd", 5.0))
        net_diff  = best_apy - cur_apy - (bridge + gas) / pos_usd * 100.0 if pos_usd > 0 else 0.0
        be_days   = _breakeven_days(pos_usd, max(0.0, best_apy - cur_apy), bridge, gas)

        recommend = net_diff >= MIN_MIGRATION_BENEFIT_PP and (be_days is None or be_days < 90)

        return {
            "from_leg":           cur_leg,
            "to_leg":             best_id,
            "apy_gain_pp":        round(best_apy - cur_apy, 4),
            "net_gain_pp_annual": round(net_diff, 4),
            "breakeven_days":     round(be_days, 1) if be_days is not None else None,
            "recommend_migrate":  recommend,
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _spread_label(self, spread: float) -> str:
        if spread >= SPREAD_VERY_WIDE:
            return "VERY_WIDE"
        if spread >= SPREAD_WIDE:
            return "WIDE"
        if spread >= SPREAD_NARROW:
            return "MODERATE"
        return "NARROW"

    # ── flags ─────────────────────────────────────────────────────────────────

    def _flags(
        self,
        spread: float,
        apy_std: float,
        legs: List[dict],
        migration: Optional[dict],
    ) -> List[str]:
        flags: List[str] = []

        if spread >= SPREAD_VERY_WIDE:
            flags.append("VERY_WIDE_BASIS_SPREAD")
        elif spread >= SPREAD_WIDE:
            flags.append("WIDE_BASIS_SPREAD")

        if apy_std >= 2.0:
            flags.append("HIGH_APY_DISPERSION")

        # Any bridge costs very high
        if any(float(l.get("bridge_cost_usd", 0)) >= BRIDGE_COST_HIGH for l in legs):
            flags.append("HIGH_BRIDGE_COST")

        # Any leg TVL < $5M → liquidity risk
        if any(float(l.get("tvl_usd", 0)) < 5_000_000 for l in legs):
            flags.append("LOW_TVL_LEG")

        if migration and migration.get("recommend_migrate"):
            flags.append("MIGRATION_RECOMMENDED")

        if len(legs) == 1:
            flags.append("SINGLE_LEG_NO_DIVERSIFICATION")

        return flags

    # ── aggregates ────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        if not results:
            return {
                "widest_spread_asset": None,
                "avg_basis_spread_pp": 0.0,
                "wide_spread_count":   0,
                "migration_opportunities": 0,
            }

        by_spread = sorted(
            results, key=lambda r: r.get("basis_spread_pp", 0.0), reverse=True
        )
        avg_spread = _mean([r.get("basis_spread_pp", 0.0) for r in results])
        wide_count = sum(
            1 for r in results if r.get("basis_spread_pp", 0.0) >= SPREAD_WIDE
        )
        mig_count = sum(
            1 for r in results
            if r.get("migration_recommendation") and r["migration_recommendation"].get("recommend_migrate")
        )

        return {
            "widest_spread_asset":    by_spread[0]["asset"] if by_spread else None,
            "avg_basis_spread_pp":    round(avg_spread, 4),
            "wide_spread_count":      wide_count,
            "migration_opportunities": mig_count,
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap      = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts":          datetime.now(timezone.utc).isoformat(),
            "group_count": len(results),
            "aggregates":  agg,
            "snapshots": [
                {
                    "asset":          r["asset"],
                    "basis_spread_pp": r["basis_spread_pp"],
                    "spread_label":   r["spread_label"],
                    "best_leg":       r["best_leg"],
                    "flags":          r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_groups() -> List[dict]:
    return [
        {
            "asset": "USDC",
            "position_usd": 100_000.0,
            "current_leg": "Aave:ethereum",
            "legs": [
                {
                    "protocol": "Aave",
                    "chain": "ethereum",
                    "apy_pct": 3.5,
                    "tvl_usd": 5_000_000_000,
                    "bridge_cost_usd": 0.0,
                    "gas_cost_usd": 15.0,
                    "apy_history_7d": [3.4, 3.5, 3.6, 3.5, 3.4, 3.5, 3.5],
                },
                {
                    "protocol": "Aave",
                    "chain": "arbitrum",
                    "apy_pct": 6.2,
                    "tvl_usd": 800_000_000,
                    "bridge_cost_usd": 10.0,
                    "gas_cost_usd": 2.0,
                    "apy_history_7d": [6.0, 6.3, 6.5, 6.1, 6.2, 6.4, 6.2],
                },
                {
                    "protocol": "Compound",
                    "chain": "ethereum",
                    "apy_pct": 4.8,
                    "tvl_usd": 2_000_000_000,
                    "bridge_cost_usd": 0.0,
                    "gas_cost_usd": 12.0,
                    "apy_history_7d": [4.7, 4.9, 4.8, 4.7, 4.9, 4.8, 4.8],
                },
            ],
        }
    ]


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="MP-1111 Cross-Chain Yield Basis Risk Analyzer")
    parser.add_argument("--run",   action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolCrossChainYieldBasisRiskAnalyzer()
    result = analyzer.analyze(_demo_groups(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

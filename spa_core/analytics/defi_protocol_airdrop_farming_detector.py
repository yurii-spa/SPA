"""
MP-996: DeFiProtocolAirdropFarmingDetector
Detects degree of airdrop farming (mercenary capital attracted by airdrop expectations).
Stdlib only. Atomic ring-buffer log (cap 100) → data/airdrop_farming_log.json.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save


_LOG_CAP = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "airdrop_farming_log.json"
)


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    atomic_save(data, str(abs_path))
def _load_log(path: str) -> list:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


class DeFiProtocolAirdropFarmingDetector:
    """
    Detects airdrop farming intensity for DeFi protocols.

    Protocol dict fields:
        name (str)
        announced_airdrop (bool)
        airdrop_date_days_until (int|None)
        tvl_usd (float)
        tvl_change_30d_pct (float)
        unique_wallets_30d (int)
        wallet_growth_30d_pct (float)
        avg_transaction_size_usd (float)
        dust_wallet_pct (float)           # % wallets < $100
        repeat_interaction_rate_pct (float) # % users >3 txns
        tvl_per_wallet_usd (float)
        has_points_system (bool)
        points_to_token_ratio_announced (bool)
    """

    def __init__(self, log_path: str | None = None):
        self._log_path = log_path or _DEFAULT_LOG_PATH

    # ------------------------------------------------------------------
    # Core scoring helpers
    # ------------------------------------------------------------------

    def _farming_intensity_score(self, p: dict) -> float:
        """
        farming_intensity_score = dust_wallet_pct×0.30
                                 + tvl_wallet_imbalance×0.25
                                 + wallet_growth_vs_tvl_divergence×0.25
                                 + announced_factor×0.20
        All sub-scores normalised 0–100.
        """
        dust = float(p.get("dust_wallet_pct", 0))
        dust_component = min(dust, 100.0)

        # TVL-wallet imbalance: low tvl_per_wallet signals sybil fragmentation
        tvl_per_wallet = float(p.get("tvl_per_wallet_usd", 10_000))
        if tvl_per_wallet <= 0:
            tvl_per_wallet = 1.0
        # Score 100 if tvl_per_wallet ≤ $50 (dust), 0 if ≥ $50k
        imbalance = max(0.0, min(100.0, (1 - math.log10(max(tvl_per_wallet, 1)) / math.log10(50_000)) * 100))

        # Wallet growth vs TVL divergence
        wallet_growth = float(p.get("wallet_growth_30d_pct", 0))
        tvl_change = float(p.get("tvl_change_30d_pct", 0))
        divergence_raw = wallet_growth - tvl_change
        # High wallet growth relative to TVL = farming signal
        divergence = max(0.0, min(100.0, divergence_raw))

        # Announced factor
        has_announced = bool(p.get("announced_airdrop", False))
        has_points = bool(p.get("has_points_system", False))
        ratio_announced = bool(p.get("points_to_token_ratio_announced", False))
        announced_factor = 0.0
        if has_announced:
            announced_factor += 60.0
        if has_points:
            announced_factor += 25.0
        if ratio_announced:
            announced_factor += 15.0
        announced_factor = min(100.0, announced_factor)

        score = (
            dust_component * 0.30
            + imbalance * 0.25
            + divergence * 0.25
            + announced_factor * 0.20
        )
        return round(min(100.0, max(0.0, score)), 2)

    def _organic_user_pct(self, p: dict) -> float:
        """100 - dust_wallet_pct weighted by repeat_interaction."""
        dust = float(p.get("dust_wallet_pct", 0))
        repeat = float(p.get("repeat_interaction_rate_pct", 0))
        # organic = non-dust users plus a bonus for repeat interactions
        base = 100.0 - dust
        organic = base * (0.5 + 0.5 * repeat / 100.0)
        return round(max(0.0, min(100.0, organic)), 2)

    def _sybil_risk_score(self, p: dict) -> float:
        """
        sybil_risk_score = wallet_count_anomaly + transaction_size_clustering
        wallet_count_anomaly: high wallet growth + low avg tx size
        tx_size_clustering: very small avg tx → likely sybil bots
        """
        wallet_growth = float(p.get("wallet_growth_30d_pct", 0))
        avg_tx = float(p.get("avg_transaction_size_usd", 1_000))
        dust_pct = float(p.get("dust_wallet_pct", 0))

        # Wallet count anomaly: growth > 50% with low TVL per wallet
        # wallet_growth=100 → 50, 200 → 100 (capped)
        wallet_anomaly = min(100.0, wallet_growth * 0.5)

        # Transaction size clustering: avg_tx < $100 = high sybil, >$10k = low
        if avg_tx <= 0:
            avg_tx = 1.0
        tx_cluster = max(0.0, min(100.0, (1 - math.log10(avg_tx) / math.log10(10_000)) * 100))

        score = wallet_anomaly * 0.55 + tx_cluster * 0.25 + dust_pct * 0.20
        return round(min(100.0, max(0.0, score)), 2)

    def _capital_stickiness(self, p: dict) -> float:
        """
        capital_stickiness = repeat_interaction×0.4 + avg_size_normalized×0.3
                            + no_airdrop_announced×0.3
        """
        repeat = float(p.get("repeat_interaction_rate_pct", 0))
        avg_tx = float(p.get("avg_transaction_size_usd", 1_000))

        # Normalise avg_tx: $10k+ → 100, $10 → ~25
        if avg_tx <= 0:
            avg_tx = 1.0
        avg_norm = min(100.0, math.log10(max(avg_tx, 10)) / math.log10(100_000) * 100)

        announced = bool(p.get("announced_airdrop", False))
        no_airdrop_factor = 0.0 if announced else 100.0

        score = repeat * 0.40 + avg_norm * 0.30 + no_airdrop_factor * 0.30
        return round(min(100.0, max(0.0, score)), 2)

    # ------------------------------------------------------------------
    # Label & flags
    # ------------------------------------------------------------------

    def _label(self, farming_score: float, organic_pct: float,
               sybil_score: float, announced: bool) -> str:
        if sybil_score > 80:
            return "SYBIL_FARM"
        if farming_score > 60:
            return "FARMING_DOMINANT"
        if farming_score < 20 and organic_pct > 80:
            return "ORGANIC_GROWTH"
        if farming_score < 40:
            return "MIXED_ORGANIC"
        if farming_score < 60 and announced:
            return "AIRDROP_INFLATED"
        return "FARMING_DOMINANT"

    def _flags(self, p: dict, sybil_score: float,
               stickiness: float) -> list[str]:
        flags: list[str] = []
        if p.get("announced_airdrop"):
            flags.append("ANNOUNCED_AIRDROP_CATALYST")
        if p.get("has_points_system"):
            flags.append("POINTS_FARMING_ACTIVE")
        if sybil_score > 70:
            flags.append("HIGH_SYBIL_RISK")
        if stickiness < 30:
            flags.append("CAPITAL_FLIGHT_RISK")
        if float(p.get("dust_wallet_pct", 0)) > 40:
            flags.append("DUST_WALLET_CONCENTRATION")
        if float(p.get("repeat_interaction_rate_pct", 0)) > 50:
            flags.append("ORGANIC_RETENTION_SIGNAL")
        return flags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, protocols: list[dict], config: dict) -> dict:
        """
        Main entry point.

        Returns:
            {
                "results": [...],
                "aggregates": {...},
                "timestamp": float,
            }
        """
        results = []
        for p in protocols:
            name = p.get("name", "unknown")
            farming_score = self._farming_intensity_score(p)
            organic_pct = self._organic_user_pct(p)
            sybil_score = self._sybil_risk_score(p)
            stickiness = self._capital_stickiness(p)
            announced = bool(p.get("announced_airdrop", False))
            label = self._label(farming_score, organic_pct, sybil_score, announced)
            flags = self._flags(p, sybil_score, stickiness)

            results.append({
                "protocol": name,
                "farming_intensity_score": farming_score,
                "organic_user_pct": organic_pct,
                "sybil_risk_score": sybil_score,
                "capital_stickiness_prediction": stickiness,
                "label": label,
                "flags": flags,
            })

        # Aggregates
        if results:
            most_organic = min(results, key=lambda r: r["farming_intensity_score"])["protocol"]
            most_farmed = max(results, key=lambda r: r["farming_intensity_score"])["protocol"]
            avg_farming = round(
                sum(r["farming_intensity_score"] for r in results) / len(results), 2
            )
            sybil_farm_count = sum(1 for r in results if r["label"] == "SYBIL_FARM")
            organic_count = sum(1 for r in results if r["label"] == "ORGANIC_GROWTH")
        else:
            most_organic = None
            most_farmed = None
            avg_farming = 0.0
            sybil_farm_count = 0
            organic_count = 0

        output = {
            "results": results,
            "aggregates": {
                "most_organic": most_organic,
                "most_farmed": most_farmed,
                "avg_farming_score": avg_farming,
                "sybil_farm_count": sybil_farm_count,
                "organic_count": organic_count,
                "total_protocols": len(results),
            },
            "timestamp": time.time(),
            "config": config,
        }

        # Write ring-buffer log
        write_log = config.get("write_log", True)
        if write_log:
            self._append_log(output)

        return output

    def _append_log(self, entry: dict) -> None:
        log_path = self._log_path
        log = _load_log(log_path)
        log.append(entry)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]
        _atomic_write(log_path, log)

"""
MP-905: DeFiStablecoinDepegRiskMonitor

Monitors stablecoin peg health: calculates depeg probability, resilience score,
and collateral quality based on mechanism type, collateral ratio, mint/burn
activity, TVL, historical depeg data, and on-chain audit coverage.

Advisory/read-only. Pure stdlib. Atomic writes (tmp + os.replace).
Ring-buffer capped at 100 entries in data/stablecoin_depeg_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/stablecoin_depeg_log.json")
MAX_ENTRIES = 100

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

PEG_TYPE_BASE_RISK = {
    "algo":           0.35,
    "crypto_backed":  0.15,
    "collateralized": 0.08,
    "fiat_backed":    0.03,
}

PEG_TYPE_RESILIENCE_BASE = {
    "fiat_backed":    82,
    "collateralized": 68,
    "crypto_backed":  52,
    "algo":           25,
}

PEG_TYPE_COLLATERAL_BASE = {
    "fiat_backed":    90,
    "collateralized": 72,
    "crypto_backed":  55,
    "algo":           18,
}


# ─────────────────────────────────────────────────────────────────
# Internal computation helpers (exposed for unit tests)
# ─────────────────────────────────────────────────────────────────

def _compute_depeg_probability(
    peg_type: str,
    current_price: float,
    collateral_ratio: float,
    historical_max_depeg_pct: float,
    mint_burn_24h_usd: float,
    tvl_usd: float,
) -> float:
    """Return depeg probability in [0.0, 1.0]."""
    base = PEG_TYPE_BASE_RISK.get(peg_type.lower(), 0.20)

    # Current price deviation from 1.0
    dev = abs(current_price - 1.0)
    base += dev * 4.0            # e.g. 5% depeg → +0.20

    # Historical worst depeg
    if historical_max_depeg_pct > 10.0:
        base += 0.18
    elif historical_max_depeg_pct > 5.0:
        base += 0.10
    elif historical_max_depeg_pct > 2.0:
        base += 0.05
    elif historical_max_depeg_pct > 0.5:
        base += 0.02

    # Collateral ratio effect
    # fiat_backed: 1.0 is fully backed by design — no penalty at 1.0
    if collateral_ratio < 1.0:
        base += 0.20
    elif collateral_ratio < 1.10 and peg_type.lower() != "fiat_backed":
        base += 0.12
    elif collateral_ratio < 1.30 and peg_type.lower() not in ("fiat_backed",):
        base += 0.04
    elif collateral_ratio >= 2.0:
        base -= 0.05

    # Large mint/burn pressure
    if tvl_usd > 0 and (mint_burn_24h_usd / tvl_usd) > 0.10:
        base += 0.08

    return max(0.0, min(1.0, base))


def _compute_resilience_score(
    peg_type: str,
    collateral_ratio: float,
    historical_max_depeg_pct: float,
    tvl_usd: float,
    audit_count: int,
    mint_burn_24h_usd: float,
) -> int:
    """Return resilience score in [0, 100]."""
    score = PEG_TYPE_RESILIENCE_BASE.get(peg_type.lower(), 40)

    # Collateral ratio adjustments
    # fiat_backed: 1.0 is standard fully-backed — no penalty; only penalise if truly short
    if collateral_ratio >= 2.0:
        score += 12
    elif collateral_ratio >= 1.5:
        score += 7
    elif collateral_ratio >= 1.30:
        score += 3
    elif collateral_ratio < 1.10 and peg_type.lower() != "fiat_backed":
        score -= 20

    # Historical depeg penalty
    if historical_max_depeg_pct > 10.0:
        score -= 25
    elif historical_max_depeg_pct > 5.0:
        score -= 15
    elif historical_max_depeg_pct > 2.0:
        score -= 8

    # TVL bonus/penalty
    if tvl_usd >= 1_000_000_000:
        score += 12
    elif tvl_usd >= 100_000_000:
        score += 6
    elif tvl_usd < 1_000_000:
        score -= 10

    # Audit bonus (capped at 15)
    score += min(int(audit_count) * 4, 15)

    # Large mint/burn penalty
    if tvl_usd > 0 and (mint_burn_24h_usd / tvl_usd) > 0.10:
        score -= 8

    return max(0, min(100, score))


def _compute_collateral_quality(
    peg_type: str,
    collateral_ratio: float,
    audit_count: int,
) -> int:
    """Return collateral quality in [0, 100]."""
    base = PEG_TYPE_COLLATERAL_BASE.get(peg_type.lower(), 40)

    if collateral_ratio >= 2.0:
        base += 8
    elif collateral_ratio >= 1.5:
        base += 4
    elif collateral_ratio >= 1.2:
        base += 1
    elif collateral_ratio < 1.0:
        base -= 30
    elif collateral_ratio < 1.10 and peg_type.lower() != "fiat_backed":
        base -= 15

    # Audit bonus (capped at 10)
    base += min(int(audit_count) * 3, 10)

    return max(0, min(100, base))


def _risk_label(
    current_price: float,
    depeg_probability: float,
    resilience_score: int,
) -> str:
    """Map metrics to a risk label string."""
    if current_price < 0.97 or current_price > 1.03:
        return "DEPEGGED"
    if depeg_probability > 0.55 or resilience_score < 20:
        return "DANGER"
    if depeg_probability > 0.35 or resilience_score < 38:
        return "WARNING"
    if depeg_probability > 0.18 or resilience_score < 55:
        return "WATCH"
    if depeg_probability > 0.08 or resilience_score < 72:
        return "STABLE"
    return "VERY_STABLE"


def _compute_flags(
    peg_type: str,
    collateral_ratio: float,
    mint_burn_24h_usd: float,
    tvl_usd: float,
    historical_max_depeg_pct: float,
) -> list:
    """Return list of active flag strings."""
    flags = []
    if peg_type.lower() == "algo":
        flags.append("ALGO_RISK")
    if collateral_ratio < 1.10:
        flags.append("UNDERCOLLATERALIZED")
    if tvl_usd > 0 and (mint_burn_24h_usd / tvl_usd) > 0.10:
        flags.append("LARGE_MINT_BURN")
    if historical_max_depeg_pct > 2.0:
        flags.append("HISTORICAL_DEPEG")
    if tvl_usd < 1_000_000:
        flags.append("LOW_TVL")
    return flags


# ─────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────

class DeFiStablecoinDepegRiskMonitor:
    """
    Advisory monitor for stablecoin depeg risk.

    Pure stdlib, read-only/advisory. Ring-buffer log to
    data/stablecoin_depeg_log.json (cap 100, atomic writes).
    """

    def monitor(self, stablecoins: list, config: dict = None) -> dict:
        """
        Analyse depeg risk for each stablecoin.

        Parameters
        ----------
        stablecoins : list[dict]
            Each entry must have:
              name, peg_type (algo/collateralized/fiat_backed/crypto_backed),
              current_price, collateral_ratio, mint_burn_24h_usd, tvl_usd,
              historical_max_depeg_pct, chain, audit_count, mint_mechanism
        config : dict, optional
            Reserved for future tuneable thresholds.

        Returns
        -------
        dict
            {
              "stablecoins": [...per-coin result dicts...],
              "most_stable": str | None,
              "highest_risk": str | None,
              "depegged_count": int,
              "danger_count": int,
              "average_resilience": float,
              "timestamp": float,
            }
        """
        cfg = config or {}
        _ = cfg  # reserved for future use

        results = []

        for coin in stablecoins:
            name = str(coin.get("name", "UNKNOWN"))
            peg_type = str(coin.get("peg_type", "fiat_backed")).lower()
            current_price = float(coin.get("current_price", 1.0))
            collateral_ratio = float(coin.get("collateral_ratio", 1.0))
            mint_burn_24h_usd = float(coin.get("mint_burn_24h_usd", 0.0))
            tvl_usd = float(coin.get("tvl_usd", 0.0))
            historical_max_depeg_pct = float(coin.get("historical_max_depeg_pct", 0.0))
            chain = str(coin.get("chain", "ethereum"))
            audit_count = int(coin.get("audit_count", 0))
            mint_mechanism = str(coin.get("mint_mechanism", ""))

            depeg_prob = _compute_depeg_probability(
                peg_type, current_price, collateral_ratio,
                historical_max_depeg_pct, mint_burn_24h_usd, tvl_usd,
            )
            resilience = _compute_resilience_score(
                peg_type, collateral_ratio, historical_max_depeg_pct,
                tvl_usd, audit_count, mint_burn_24h_usd,
            )
            cq = _compute_collateral_quality(peg_type, collateral_ratio, audit_count)
            label = _risk_label(current_price, depeg_prob, resilience)
            flags = _compute_flags(
                peg_type, collateral_ratio, mint_burn_24h_usd,
                tvl_usd, historical_max_depeg_pct,
            )

            results.append({
                "name": name,
                "peg_type": peg_type,
                "current_price": current_price,
                "collateral_ratio": collateral_ratio,
                "tvl_usd": tvl_usd,
                "chain": chain,
                "mint_mechanism": mint_mechanism,
                "depeg_probability": round(depeg_prob, 4),
                "resilience_score": resilience,
                "collateral_quality": cq,
                "risk_label": label,
                "flags": flags,
            })

        # ── Aggregates ─────────────────────────────────────────
        most_stable: str | None = None
        highest_risk: str | None = None
        depegged_count = 0
        danger_count = 0
        average_resilience = 0.0

        if results:
            by_resilience = sorted(results, key=lambda r: r["resilience_score"])
            highest_risk = by_resilience[0]["name"]
            most_stable = by_resilience[-1]["name"]

            depegged_count = sum(1 for r in results if r["risk_label"] == "DEPEGGED")
            danger_count = sum(
                1 for r in results if r["risk_label"] in ("DANGER", "DEPEGGED")
            )
            average_resilience = (
                sum(r["resilience_score"] for r in results) / len(results)
            )

        output = {
            "stablecoins": results,
            "most_stable": most_stable,
            "highest_risk": highest_risk,
            "depegged_count": depegged_count,
            "danger_count": danger_count,
            "average_resilience": round(average_resilience, 2),
            "timestamp": time.time(),
        }

        _append_log(output)
        return output


# ─────────────────────────────────────────────────────────────────
# Ring-buffer log
# ─────────────────────────────────────────────────────────────────

def _append_log(entry: dict) -> None:
    """Atomically append *entry* to DATA_FILE, capped at MAX_ENTRIES."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing: list = []
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, DATA_FILE)


# ─────────────────────────────────────────────────────────────────
# CLI demo
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo = [
        {
            "name": "USDC",
            "peg_type": "fiat_backed",
            "current_price": 1.0002,
            "collateral_ratio": 1.0,
            "mint_burn_24h_usd": 500_000_000,
            "tvl_usd": 30_000_000_000,
            "historical_max_depeg_pct": 0.05,
            "chain": "ethereum",
            "audit_count": 5,
            "mint_mechanism": "fiat_reserve",
        },
        {
            "name": "USTC",
            "peg_type": "algo",
            "current_price": 0.012,
            "collateral_ratio": 0.0,
            "mint_burn_24h_usd": 10_000_000,
            "tvl_usd": 50_000_000,
            "historical_max_depeg_pct": 99.0,
            "chain": "terra",
            "audit_count": 1,
            "mint_mechanism": "algorithmic_burn",
        },
    ]
    monitor = DeFiStablecoinDepegRiskMonitor()
    result = monitor.monitor(demo)
    print(json.dumps(result, indent=2))

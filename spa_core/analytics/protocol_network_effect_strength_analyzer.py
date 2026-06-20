"""
MP-985: ProtocolNetworkEffectStrengthAnalyzer
Measures the strength of network effects in DeFi protocols using Metcalfe's Law.
Pure stdlib — no external dependencies.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Any
from spa_core.utils.atomic import atomic_save

NETWORK_LABELS = [
    # (min_score, high_switching_required, label)
    (80.0, True,  "DOMINANT_NETWORK"),
    (60.0, False, "STRONG_NETWORK"),
    (40.0, False, "EMERGING_NETWORK"),
    (20.0, False, "WEAK_NETWORK"),
    (0.0,  False, "NO_MOAT"),
]

LOG_CAP = 100
DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "network_effect_log.json",
)

# Normalisation constants (soft caps)
_METCALFE_SOFT_CAP = 1e15   # users² × avg_tx_value
_GROWTH_SOFT_CAP = 100.0    # 100% growth → score = 100
_INT_DENSITY_SOFT_CAP = 10.0  # integration density → 100% at 10+


def _pct_change(new: float, old: float) -> float:
    """Percentage change; returns 0 if old is 0."""
    if old <= 0:
        return 0.0
    return (new - old) / old * 100.0


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
class ProtocolNetworkEffectStrengthAnalyzer:
    """
    Measures network effect strength for a list of DeFi protocols.

    Input schema per protocol:
        name                        str   — protocol identifier
        category                    str   — e.g. "lending", "dex", "derivatives"
        monthly_active_users        int   — current MAU
        monthly_active_users_3m_ago int   — MAU 3 months ago
        total_integrations          int   — current # of integrating protocols
        total_integrations_3m_ago   int   — (optional) integrations 3 months ago
        total_tvl_usd               float — current TVL in USD
        tvl_3m_ago_usd              float — TVL 3 months ago
        transaction_count_30d       int   — transactions in last 30 days
        avg_transaction_value_usd   float — average USD value per transaction
        switching_cost_score        float — 0–100 (higher = harder to leave)
        data_network_effect         bool  — True if value grows with user data

    Config keys (all optional):
        log_path                  str   — override ring-buffer log path
        disable_log               bool  — skip log write (default False)
        dominant_score_threshold  float — min score to be DOMINANT (default 80)
        high_switching_threshold  float — min switching cost for DOMINANT (default 60)
        integration_hub_threshold int   — min integrations for INTEGRATION_HUB (default 50)
        metcalfe_scaling_growth   float — growth % threshold for METCALFE_SCALING (default 20)
        stalling_growth_threshold float — max growth % for USER_GROWTH_STALLING (default 5)
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, protocols: list[dict], config: dict | None = None) -> dict:
        config = config or {}

        log_path = config.get("log_path", DEFAULT_LOG_PATH)
        disable_log = bool(config.get("disable_log", False))

        dominant_threshold = float(config.get("dominant_score_threshold", 80.0))
        high_switching_threshold = float(config.get("high_switching_threshold", 60.0))
        integration_hub_threshold = int(config.get("integration_hub_threshold", 50))
        metcalfe_scaling_growth = float(config.get("metcalfe_scaling_growth", 20.0))
        stalling_growth_threshold = float(config.get("stalling_growth_threshold", 5.0))

        if not protocols:
            result = self._empty_result()
            if not disable_log:
                self._append_log(result, log_path)
            return result

        # ---- count protocols per category (for integration_density) ---------
        category_counts: dict[str, int] = {}
        for p in protocols:
            cat = str(p.get("category", "unknown"))
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # ---- per-protocol metrics -------------------------------------------
        metcalfe_values: list[float] = []
        analyzed: list[dict] = []

        for proto in protocols:
            name = str(proto.get("name", "unknown"))
            category = str(proto.get("category", "unknown"))

            mau = max(0, int(proto.get("monthly_active_users", 0)))
            mau_3m = max(0, int(proto.get("monthly_active_users_3m_ago", 0)))
            integrations = max(0, int(proto.get("total_integrations", 0)))
            integrations_3m = int(proto.get("total_integrations_3m_ago", integrations))
            tvl = max(0.0, float(proto.get("total_tvl_usd", 0.0)))
            tvl_3m = max(0.0, float(proto.get("tvl_3m_ago_usd", 0.0)))
            tx_count = max(0, int(proto.get("transaction_count_30d", 0)))
            avg_tx_val = max(0.0, float(proto.get("avg_transaction_value_usd", 0.0)))
            switching_cost = _clamp(float(proto.get("switching_cost_score", 0.0)))
            data_ne = bool(proto.get("data_network_effect", False))

            # Derived metrics
            metcalfe_value = float(mau ** 2) * avg_tx_val
            metcalfe_values.append(metcalfe_value)

            user_growth_pct_3m = _pct_change(mau, mau_3m)
            tvl_growth_pct_3m = _pct_change(tvl, tvl_3m)

            n_in_cat = max(1, category_counts.get(category, 1))
            integration_density = integrations / math.sqrt(n_in_cat)

            analyzed.append({
                "name": name,
                "category": category,
                "metcalfe_value": metcalfe_value,
                "user_growth_pct_3m": round(user_growth_pct_3m, 4),
                "tvl_growth_pct_3m": round(tvl_growth_pct_3m, 4),
                "integration_density": round(integration_density, 6),
                "integrations": integrations,
                "integrations_3m": integrations_3m,
                "switching_cost_score": switching_cost,
                "data_network_effect": data_ne,
                "monthly_active_users": mau,
                "tvl_usd": tvl,
                "tx_count_30d": tx_count,
            })

        # ---- normalise metcalfe across batch --------------------------------
        max_metcalfe = max(metcalfe_values) if metcalfe_values else 0.0

        # ---- score & label each protocol ------------------------------------
        protocol_results: list[dict] = []

        for item, proto in zip(analyzed, protocols):
            mv = item["metcalfe_value"]
            metcalfe_score = (mv / max_metcalfe * 100.0) if max_metcalfe > 0 else 0.0
            metcalfe_score = _clamp(metcalfe_score)

            # Growth score: average of user+tvl growth, capped at 100
            combined_growth = (item["user_growth_pct_3m"] + item["tvl_growth_pct_3m"]) / 2.0
            growth_score = _clamp(combined_growth, 0.0, 100.0)

            # Integration density score (soft cap)
            intd = item["integration_density"]
            integration_score = _clamp(intd / _INT_DENSITY_SOFT_CAP * 100.0)

            # Switching cost is already 0-100
            switching_score = _clamp(item["switching_cost_score"])

            network_strength_score = (
                growth_score * 0.30
                + switching_score * 0.25
                + integration_score * 0.25
                + metcalfe_score * 0.20
            )
            network_strength_score = round(_clamp(network_strength_score), 4)

            # ---- label -------------------------------------------------------
            network_label = self._network_label(
                network_strength_score,
                item["switching_cost_score"],
                dominant_threshold,
                high_switching_threshold,
            )

            # ---- flags -------------------------------------------------------
            flags: list[str] = []

            if (
                item["user_growth_pct_3m"] > metcalfe_scaling_growth
                and item["tvl_growth_pct_3m"] > metcalfe_scaling_growth
            ):
                flags.append("METCALFE_SCALING")

            if item["switching_cost_score"] > 70.0:
                flags.append("HIGH_SWITCHING_COST")

            if item["integrations"] > integration_hub_threshold:
                flags.append("INTEGRATION_HUB")

            if item["user_growth_pct_3m"] < stalling_growth_threshold:
                flags.append("USER_GROWTH_STALLING")

            if item["integrations"] < item["integrations_3m"]:
                flags.append("LOSING_INTEGRATIONS")

            protocol_results.append({
                "name": item["name"],
                "category": item["category"],
                "network_strength_score": network_strength_score,
                "network_label": network_label,
                "metcalfe_value": round(mv, 2),
                "metcalfe_score": round(metcalfe_score, 4),
                "user_growth_pct_3m": item["user_growth_pct_3m"],
                "tvl_growth_pct_3m": item["tvl_growth_pct_3m"],
                "integration_density": item["integration_density"],
                "growth_score": round(growth_score, 4),
                "integration_score": round(integration_score, 4),
                "switching_cost_score": item["switching_cost_score"],
                "data_network_effect": item["data_network_effect"],
                "flags": flags,
            })

        # ---- aggregates ------------------------------------------------------
        scores = [r["network_strength_score"] for r in protocol_results]
        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

        strongest = max(protocol_results, key=lambda x: x["network_strength_score"])
        weakest = min(protocol_results, key=lambda x: x["network_strength_score"])

        dominant_count = sum(1 for r in protocol_results if r["network_label"] == "DOMINANT_NETWORK")
        no_moat_count = sum(1 for r in protocol_results if r["network_label"] == "NO_MOAT")

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(protocol_results),
            "protocols": protocol_results,
            "average_network_score": avg_score,
            "strongest_network": strongest["name"],
            "weakest_network": weakest["name"],
            "dominant_count": dominant_count,
            "no_moat_count": no_moat_count,
        }

        if not disable_log:
            self._append_log(result, log_path)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _network_label(
        self,
        score: float,
        switching_cost: float,
        dominant_threshold: float,
        high_switching_threshold: float,
    ) -> str:
        if score >= dominant_threshold and switching_cost >= high_switching_threshold:
            return "DOMINANT_NETWORK"
        if score >= 60.0:
            return "STRONG_NETWORK"
        if score >= 40.0:
            return "EMERGING_NETWORK"
        if score >= 20.0:
            return "WEAK_NETWORK"
        return "NO_MOAT"

    def _empty_result(self) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol_count": 0,
            "protocols": [],
            "average_network_score": 0.0,
            "strongest_network": None,
            "weakest_network": None,
            "dominant_count": 0,
            "no_moat_count": 0,
            "error": "empty_protocols",
        }

    def _append_log(self, entry: dict, log_path: str) -> None:
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
            pass


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json

    sample_protocols = [
        {
            "name": "Aave",
            "category": "lending",
            "monthly_active_users": 120_000,
            "monthly_active_users_3m_ago": 95_000,
            "total_integrations": 80,
            "total_integrations_3m_ago": 75,
            "total_tvl_usd": 12_000_000_000,
            "tvl_3m_ago_usd": 9_000_000_000,
            "transaction_count_30d": 500_000,
            "avg_transaction_value_usd": 5000.0,
            "switching_cost_score": 75.0,
            "data_network_effect": True,
        },
        {
            "name": "Uniswap",
            "category": "dex",
            "monthly_active_users": 300_000,
            "monthly_active_users_3m_ago": 280_000,
            "total_integrations": 200,
            "total_integrations_3m_ago": 190,
            "total_tvl_usd": 5_000_000_000,
            "tvl_3m_ago_usd": 4_800_000_000,
            "transaction_count_30d": 5_000_000,
            "avg_transaction_value_usd": 800.0,
            "switching_cost_score": 40.0,
            "data_network_effect": False,
        },
    ]

    analyzer = ProtocolNetworkEffectStrengthAnalyzer()
    result = analyzer.analyze(sample_protocols, {"disable_log": True})
    print(_json.dumps(result, indent=2))

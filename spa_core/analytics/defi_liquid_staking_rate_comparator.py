"""
MP-938: DeFiLiquidStakingRateComparator
Compares liquid staking protocols by yield and risk metrics.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""
import json
import math
import os
from datetime import datetime, timezone
from spa_core.utils.atomic import atomic_save

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "liquid_staking_comparison_log.json"
)
LOG_CAP = 100

QUALITY_LABELS = ["PREMIUM", "GOOD", "STANDARD", "BELOW_AVERAGE", "AVOID"]

_QUALITY_THRESHOLDS = [
    (80, "PREMIUM"),
    (65, "GOOD"),
    (50, "STANDARD"),
    (35, "BELOW_AVERAGE"),
    (0,  "AVOID"),
]


class DeFiLiquidStakingRateComparator:
    """Compare liquid staking protocols by effective APY, risk, and decentralisation."""

    # ---------- public API ----------

    def compare(self, lst_protocols: list, config: dict) -> dict:
        """
        Parameters
        ----------
        lst_protocols : list[dict]
            Each dict must contain the fields described in the spec.
        config : dict
            Optional tuning keys (see defaults below).

        Returns
        -------
        dict with keys:
            protocols, aggregates, timestamp, config_used
        """
        if not isinstance(lst_protocols, list):
            raise TypeError("lst_protocols must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        cfg = self._resolve_config(config)
        results = [self._score_protocol(p, cfg) for p in lst_protocols]

        aggregates = self._compute_aggregates(results)
        output = {
            "protocols": results,
            "aggregates": aggregates,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config_used": cfg,
        }
        self._append_log(output)
        return output

    # ---------- config ----------

    def _resolve_config(self, config: dict) -> dict:
        return {
            "high_commission_threshold_pct": float(config.get("high_commission_threshold_pct", 15.0)),
            "peg_discount_threshold_pct": float(config.get("peg_discount_threshold_pct", 0.5)),
            "min_validators_centralised": int(config.get("min_validators_centralised", 10)),
            "min_client_diversity_centralised": int(config.get("min_client_diversity_centralised", 30)),
            "withdrawal_delay_threshold_days": float(config.get("withdrawal_delay_threshold_days", 7.0)),
            "max_slash_incidents_clean": int(config.get("max_slash_incidents_clean", 0)),
            "slash_risk_weight": float(config.get("slash_risk_weight", 0.4)),
            "commission_weight": float(config.get("commission_weight", 0.2)),
            "decentralization_weight": float(config.get("decentralization_weight", 0.25)),
            "peg_weight": float(config.get("peg_weight", 0.15)),
        }

    # ---------- per-protocol scoring ----------

    def _score_protocol(self, p: dict, cfg: dict) -> dict:
        name = str(p.get("name", ""))
        token = str(p.get("token", ""))
        base_apy = float(p.get("base_staking_apy_pct", 0.0))
        defi_boost = float(p.get("defi_boost_apy_pct", 0.0))
        commission = float(p.get("commission_pct", 0.0))
        slash_count = int(p.get("slash_incidents_count", 0))
        validator_count = int(p.get("validator_count", 1))
        client_diversity = float(p.get("client_diversity_score", 0.0))
        tvl_usd = float(p.get("tvl_usd", 0.0))
        withdrawal_days = float(p.get("withdrawal_delay_days", 0.0))
        is_liquid = bool(p.get("is_liquid", True))
        peg_discount = float(p.get("peg_discount_pct", 0.0))

        # -- effective APY (commission reduces base only, boost is already net) --
        commission_drag = base_apy * (commission / 100.0)
        total_effective_apy = base_apy + defi_boost - commission_drag

        # -- slash risk score (0-100, higher = riskier) --
        slash_risk = self._slash_risk_score(slash_count)

        # -- decentralization score (0-100, higher = more decentralised) --
        decentralization = self._decentralization_score(validator_count, client_diversity)

        # -- composite quality score (0-100, higher = better) --
        # weights in config sum to 1.0 (slash 0.4 + commission 0.2 + decentralization 0.25 + peg 0.15)
        peg_health = max(0.0, 100.0 - peg_discount * 20.0)  # each 1% discount → -20 pts
        commission_score = max(0.0, 100.0 - commission * 3.0)

        composite = (
            cfg["slash_risk_weight"] * (100.0 - slash_risk)
            + cfg["commission_weight"] * commission_score
            + cfg["decentralization_weight"] * decentralization
            + cfg["peg_weight"] * peg_health
        )
        composite = max(0.0, min(100.0, composite))

        quality_label = self._quality_label(composite)
        flags = self._compute_flags(p, cfg, commission, slash_count, peg_discount, validator_count, client_diversity, withdrawal_days)

        return {
            "name": name,
            "token": token,
            "base_staking_apy_pct": base_apy,
            "defi_boost_apy_pct": defi_boost,
            "commission_pct": commission,
            "total_effective_apy_pct": round(total_effective_apy, 6),
            "net_slash_risk_score": round(slash_risk, 2),
            "decentralization_score": round(decentralization, 2),
            "composite_quality_score": round(composite, 2),
            "quality_label": quality_label,
            "flags": flags,
            "tvl_usd": tvl_usd,
            "withdrawal_delay_days": withdrawal_days,
            "is_liquid": is_liquid,
            "peg_discount_pct": peg_discount,
            "slash_incidents_count": slash_count,
            "validator_count": validator_count,
            "client_diversity_score": client_diversity,
        }

    # ---------- sub-scores ----------

    def _slash_risk_score(self, slash_count: int) -> float:
        """0=no risk, 100=very high risk."""
        if slash_count <= 0:
            return 0.0
        return min(100.0, slash_count * 20.0)

    def _decentralization_score(self, validator_count: int, client_diversity: float) -> float:
        """0=centralised, 100=fully decentralised."""
        # validator score: log scale capped at 1000 → maps to 50 pts
        val_score = min(50.0, math.log1p(validator_count) / math.log1p(1000) * 50.0)
        # client diversity is already 0-100 → maps to 50 pts
        cd_score = float(client_diversity) / 100.0 * 50.0
        return round(val_score + cd_score, 2)

    def _quality_label(self, score: float) -> str:
        for threshold, label in _QUALITY_THRESHOLDS:
            if score >= threshold:
                return label
        return "AVOID"

    # ---------- flags ----------

    def _compute_flags(self, p: dict, cfg: dict, commission: float,
                       slash_count: int, peg_discount: float,
                       validator_count: int, client_diversity: float,
                       withdrawal_days: float) -> list:
        flags = []
        if slash_count > cfg["max_slash_incidents_clean"]:
            flags.append("SLASHING_HISTORY")
        if commission > cfg["high_commission_threshold_pct"]:
            flags.append("HIGH_COMMISSION")
        if peg_discount > cfg["peg_discount_threshold_pct"]:
            flags.append("TRADING_AT_DISCOUNT")
        if (validator_count < cfg["min_validators_centralised"]
                or client_diversity < cfg["min_client_diversity_centralised"]):
            flags.append("CENTRALIZED")
        if withdrawal_days > cfg["withdrawal_delay_threshold_days"]:
            flags.append("WITHDRAWAL_DELAY")
        return flags

    # ---------- aggregates ----------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_lst": None,
                "worst_lst": None,
                "highest_total_apy": None,
                "average_composite_quality": None,
                "premium_count": 0,
                "protocol_count": 0,
            }

        sorted_quality = sorted(results, key=lambda x: x["composite_quality_score"], reverse=True)
        sorted_apy = sorted(results, key=lambda x: x["total_effective_apy_pct"], reverse=True)

        avg_quality = sum(r["composite_quality_score"] for r in results) / len(results)
        premium_count = sum(1 for r in results if r["quality_label"] == "PREMIUM")

        return {
            "best_lst": sorted_quality[0]["name"] if sorted_quality else None,
            "worst_lst": sorted_quality[-1]["name"] if sorted_quality else None,
            "highest_total_apy": sorted_apy[0]["total_effective_apy_pct"] if sorted_apy else None,
            "highest_total_apy_protocol": sorted_apy[0]["name"] if sorted_apy else None,
            "average_composite_quality": round(avg_quality, 2),
            "premium_count": premium_count,
            "protocol_count": len(results),
        }

    # ---------- ring-buffer log ----------

    def _append_log(self, entry: dict) -> None:
        log_entry = {
            "ts": entry["timestamp"],
            "protocol_count": entry["aggregates"].get("protocol_count", 0),
            "best_lst": entry["aggregates"].get("best_lst"),
            "avg_composite": entry["aggregates"].get("average_composite_quality"),
            "premium_count": entry["aggregates"].get("premium_count", 0),
        }
        try:
            log_path = LOG_PATH
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    buf = json.load(f)
                if not isinstance(buf, list):
                    buf = []
            else:
                buf = []
            buf.append(log_entry)
            if len(buf) > LOG_CAP:
                buf = buf[-LOG_CAP:]
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            atomic_save(buf, str(log_path))
        except Exception:
            pass  # log failure must never break the caller


# ---------- CLI ----------

if __name__ == "__main__":
    sample_protocols = [
        {
            "name": "Lido",
            "token": "stETH",
            "base_staking_apy_pct": 3.8,
            "defi_boost_apy_pct": 1.2,
            "commission_pct": 10.0,
            "slash_incidents_count": 0,
            "validator_count": 300000,
            "client_diversity_score": 75,
            "tvl_usd": 30_000_000_000,
            "withdrawal_delay_days": 0,
            "is_liquid": True,
            "peg_discount_pct": 0.02,
        },
        {
            "name": "RocketPool",
            "token": "rETH",
            "base_staking_apy_pct": 3.6,
            "defi_boost_apy_pct": 0.9,
            "commission_pct": 14.0,
            "slash_incidents_count": 0,
            "validator_count": 5000,
            "client_diversity_score": 85,
            "tvl_usd": 3_000_000_000,
            "withdrawal_delay_days": 2,
            "is_liquid": True,
            "peg_discount_pct": 0.01,
        },
    ]
    comparator = DeFiLiquidStakingRateComparator()
    result = comparator.compare(sample_protocols, {})
    print(json.dumps(result, indent=2))

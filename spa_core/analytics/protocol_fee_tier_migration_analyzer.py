"""
MP-943: ProtocolFeeTierMigrationAnalyzer
Analyzes liquidity migrations between DEX fee tiers (Uniswap v3-style).
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import os
import time
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "fee_tier_migration_log.json")
LOG_CAP = 100

LABEL_HIGHLY_SUCCESSFUL = "HIGHLY_SUCCESSFUL"
LABEL_SUCCESSFUL = "SUCCESSFUL"
LABEL_NEUTRAL = "NEUTRAL"
LABEL_UNSUCCESSFUL = "UNSUCCESSFUL"
LABEL_COUNTERPRODUCTIVE = "COUNTERPRODUCTIVE"

FLAG_VOLUME_CAPTURE_IMPROVED = "VOLUME_CAPTURE_IMPROVED"
FLAG_FEE_REVENUE_INCREASED = "FEE_REVENUE_INCREASED"
FLAG_IL_REDUCED = "IL_REDUCED"
FLAG_REVERSE_MIGRATION_CANDIDATE = "REVERSE_MIGRATION_CANDIDATE"
FLAG_INCENTIVE_DRIVEN = "INCENTIVE_DRIVEN"

DEFAULT_CONFIG = {
    "volume_capture_improvement_threshold_pct": 20.0,   # >20% improvement → VOLUME_CAPTURE_IMPROVED
    "reverse_migration_threshold": 20.0,                 # net_benefit < 20 → REVERSE_MIGRATION_CANDIDATE
    "highly_successful_threshold": 75.0,                 # net_benefit >= 75 → HIGHLY_SUCCESSFUL
    "successful_threshold": 55.0,                        # net_benefit >= 55 → SUCCESSFUL
    "neutral_threshold": 35.0,                           # net_benefit >= 35 → NEUTRAL
    "unsuccessful_threshold": 15.0,                      # net_benefit >= 15 → UNSUCCESSFUL
    # below unsuccessful_threshold → COUNTERPRODUCTIVE
}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _compute_fee_revenue_change_pct(migration: dict) -> float:
    """
    fee_revenue_change_pct: (to_tier * volume_after) / (from_tier * volume_before) - 1
    Both expressed as ratios (pct / 100 internally).
    """
    from_tier = max(1e-9, float(migration.get("from_tier_pct", 0.3)))
    to_tier = max(1e-9, float(migration.get("to_tier_pct", 0.05)))
    vol_before = max(1e-9, float(migration.get("volume_captured_before_pct", 1.0)))
    vol_after = max(0.0, float(migration.get("volume_captured_after_pct", 1.0)))

    revenue_before = from_tier * vol_before
    revenue_after = to_tier * vol_after

    fee_change = (revenue_after / revenue_before - 1.0) * 100.0
    return round(fee_change, 4)


def _compute_volume_efficiency_gain(migration: dict) -> float:
    """
    volume_efficiency_gain = (volume_after / volume_before) - 1 expressed as pct.
    """
    vol_before = max(1e-9, float(migration.get("volume_captured_before_pct", 1.0)))
    vol_after = max(0.0, float(migration.get("volume_captured_after_pct", 1.0)))
    gain = (vol_after / vol_before - 1.0) * 100.0
    return round(gain, 4)


def _compute_migration_success_score(migration: dict, fee_rev_change: float, vol_eff_gain: float) -> float:
    """
    migration_success_score 0-100: composite of volume improvement + fee revenue + IL improvement.
    """
    il_change = float(migration.get("il_change_pct", 0.0))

    # Volume component (0-40 points): normalized improvement
    # vol_eff_gain > 50% → 40 pts; vol < 0 → 0 pts
    vol_score = _clamp(vol_eff_gain / 50.0 * 40.0, -40.0, 40.0)

    # Fee revenue component (0-40 points)
    fee_score = _clamp(fee_rev_change / 50.0 * 40.0, -40.0, 40.0)

    # IL component (0-20 points): negative il_change (reduced IL) is good
    # il_change < 0 means IL decreased
    il_score = _clamp(-il_change / 5.0 * 20.0, -20.0, 20.0)

    raw = vol_score + fee_score + il_score
    # Normalize to 0-100: raw ranges from -100 to 100 → map to 0-100
    normalized = (raw + 100.0) / 2.0
    return round(_clamp(normalized, 0.0, 100.0), 4)


def _compute_net_benefit_score(
    fee_rev_change: float,
    vol_eff_gain: float,
    il_change: float,
    migration: dict,
) -> float:
    """
    net_benefit_score 0-100: broader view including TVL migrated and time context.
    """
    # Base from migration success but weighted differently
    vol_weight = 0.35
    fee_weight = 0.35
    il_weight = 0.20
    recency_weight = 0.10

    # Vol component
    vol_component = _clamp((vol_eff_gain + 100.0) / 2.0, 0.0, 100.0) * vol_weight

    # Fee component
    fee_component = _clamp((fee_rev_change + 100.0) / 2.0, 0.0, 100.0) * fee_weight

    # IL component: il_change < 0 = good
    il_raw = _clamp(-il_change / 10.0 * 100.0, -100.0, 100.0)
    il_component = _clamp((il_raw + 100.0) / 2.0, 0.0, 100.0) * il_weight

    # Recency component: more recent migration scores higher (date_days_ago)
    date_days_ago = max(0.0, float(migration.get("date_days_ago", 30)))
    recency_raw = _clamp(100.0 - date_days_ago / 365.0 * 100.0, 0.0, 100.0)
    recency_component = recency_raw * recency_weight

    net = vol_component + fee_component + il_component + recency_component
    return round(_clamp(net, 0.0, 100.0), 4)


def _get_flags(migration: dict, fee_rev_change: float, vol_eff_gain: float, net_benefit: float, config: dict) -> list:
    flags = []
    il_change = float(migration.get("il_change_pct", 0.0))
    reason = migration.get("reason", "")

    vol_threshold = float(config.get("volume_capture_improvement_threshold_pct", 20.0))
    reverse_threshold = float(config.get("reverse_migration_threshold", 20.0))

    if vol_eff_gain > vol_threshold:
        flags.append(FLAG_VOLUME_CAPTURE_IMPROVED)
    if fee_rev_change > 0:
        flags.append(FLAG_FEE_REVENUE_INCREASED)
    if il_change < 0:
        flags.append(FLAG_IL_REDUCED)
    if net_benefit < reverse_threshold:
        flags.append(FLAG_REVERSE_MIGRATION_CANDIDATE)
    if reason == "incentives":
        flags.append(FLAG_INCENTIVE_DRIVEN)

    return flags


def _get_label(net_benefit: float, config: dict) -> str:
    if net_benefit >= float(config.get("highly_successful_threshold", 75.0)):
        return LABEL_HIGHLY_SUCCESSFUL
    if net_benefit >= float(config.get("successful_threshold", 55.0)):
        return LABEL_SUCCESSFUL
    if net_benefit >= float(config.get("neutral_threshold", 35.0)):
        return LABEL_NEUTRAL
    if net_benefit >= float(config.get("unsuccessful_threshold", 15.0)):
        return LABEL_UNSUCCESSFUL
    return LABEL_COUNTERPRODUCTIVE


def _analyze_single(migration: dict, config: dict) -> dict:
    fee_rev_change = _compute_fee_revenue_change_pct(migration)
    vol_eff_gain = _compute_volume_efficiency_gain(migration)
    il_change = float(migration.get("il_change_pct", 0.0))
    migration_success_score = _compute_migration_success_score(migration, fee_rev_change, vol_eff_gain)
    net_benefit_score = _compute_net_benefit_score(fee_rev_change, vol_eff_gain, il_change, migration)
    flags = _get_flags(migration, fee_rev_change, vol_eff_gain, net_benefit_score, config)
    label = _get_label(net_benefit_score, config)

    return {
        "pair": migration.get("pair", ""),
        "from_tier_pct": float(migration.get("from_tier_pct", 0.0)),
        "to_tier_pct": float(migration.get("to_tier_pct", 0.0)),
        "tvl_migrated_usd": float(migration.get("tvl_migrated_usd", 0.0)),
        "fee_revenue_change_pct": fee_rev_change,
        "volume_efficiency_gain": vol_eff_gain,
        "migration_success_score": migration_success_score,
        "net_benefit_score": net_benefit_score,
        "migration_label": label,
        "flags": flags,
        "reason": migration.get("reason", ""),
        "il_change_pct": il_change,
    }


def _atomic_log_write(entry: dict, log_path: str, cap: int) -> None:
    log_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    existing = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    if len(existing) > cap:
        existing = existing[-cap:]

    tmp_path = log_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp_path, log_path)


class ProtocolFeeTierMigrationAnalyzer:
    """
    Analyzes liquidity migrations between DEX fee tiers.
    Computes fee revenue change, volume efficiency gain, migration success score,
    net benefit score, and migration quality label per migration.
    """

    def __init__(self, log_path: Optional[str] = None, log_cap: int = LOG_CAP):
        self._log_path = log_path or LOG_PATH
        self._log_cap = log_cap

    def analyze(self, migrations: list, config: Optional[dict] = None) -> dict:
        """
        Analyzes a list of fee tier migrations.

        Args:
            migrations: List of migration dicts with keys:
                pair, from_tier_pct, to_tier_pct, tvl_migrated_usd,
                volume_captured_before_pct, volume_captured_after_pct,
                date_days_ago, reason (high_volatility/low_volatility/
                competition/incentives/other), il_change_pct
            config: Optional config overrides.

        Returns:
            dict with per-migration analysis and aggregates.
        """
        if config is None:
            config = {}
        cfg = {**DEFAULT_CONFIG, **config}

        if not migrations:
            return {
                "migrations": [],
                "aggregates": {
                    "most_successful_migration": None,
                    "least_successful_migration": None,
                    "average_net_benefit": 0.0,
                    "successful_count": 0,
                    "total_tvl_migrated_usd": 0.0,
                    "migration_count": 0,
                },
                "timestamp": time.time(),
            }

        results = []
        for m in migrations:
            r = _analyze_single(m, cfg)
            results.append(r)

        # Aggregates
        total_tvl = sum(r["tvl_migrated_usd"] for r in results)
        avg_net_benefit = sum(r["net_benefit_score"] for r in results) / len(results)
        successful_count = sum(
            1 for r in results
            if r["migration_label"] in (LABEL_HIGHLY_SUCCESSFUL, LABEL_SUCCESSFUL)
        )

        most_successful = max(results, key=lambda r: r["net_benefit_score"])
        least_successful = min(results, key=lambda r: r["net_benefit_score"])

        output = {
            "migrations": results,
            "aggregates": {
                "most_successful_migration": {
                    "pair": most_successful["pair"],
                    "label": most_successful["migration_label"],
                    "net_benefit_score": most_successful["net_benefit_score"],
                },
                "least_successful_migration": {
                    "pair": least_successful["pair"],
                    "label": least_successful["migration_label"],
                    "net_benefit_score": least_successful["net_benefit_score"],
                },
                "average_net_benefit": round(avg_net_benefit, 4),
                "successful_count": successful_count,
                "total_tvl_migrated_usd": round(total_tvl, 2),
                "migration_count": len(results),
            },
            "timestamp": time.time(),
        }

        # Ring-buffer log (atomic write)
        try:
            _atomic_log_write(
                {
                    "timestamp": output["timestamp"],
                    "migration_count": len(results),
                    "total_tvl_migrated_usd": output["aggregates"]["total_tvl_migrated_usd"],
                    "average_net_benefit": output["aggregates"]["average_net_benefit"],
                    "successful_count": successful_count,
                },
                self._log_path,
                self._log_cap,
            )
        except OSError:
            pass

        return output

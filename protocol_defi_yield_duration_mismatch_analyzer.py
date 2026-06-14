"""
MP-1025: ProtocolDeFiYieldDurationMismatchAnalyzer
Измеряет несоответствие дюрации/ликвидности активов и обязательств
yield-протокола (run-risk при стресс-выводе).
Только stdlib Python, atomic writes, read-only/advisory домен.
"""

import json
import os
import time
import tempfile
from typing import Any

# Default data directory (relative to repo root)
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

_EPS = 1e-9


def _atomic_write(path: str, data: Any) -> None:
    """Atomic write: tmp file + os.replace."""
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name or ".", prefix=".tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_ring_buffer(path: str, cap: int) -> list:
    """Load existing ring-buffer log or return empty list."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data[-cap:]
        return []
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return []


class ProtocolDeFiYieldDurationMismatchAnalyzer:
    """
    Analyzes yield-protocol asset/liability duration & liquidity mismatch.

    analyze(protocols, config) -> dict with per-protocol details
    and aggregate statistics.
    """

    LOG_FILE = "yield_duration_mismatch_log.json"
    LOG_CAP = 100

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Core metric helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _duration_gap_days(proto: dict) -> float:
        """asset_avg_maturity_days - liability_avg_redemption_days."""
        asset = float(proto.get("asset_avg_maturity_days", 0))
        liability = float(proto.get("liability_avg_redemption_days", 0))
        return asset - liability

    @staticmethod
    def _liquidity_coverage_ratio(proto: dict) -> float:
        """liquid_reserve_pct / max(stress_redemption_pct, eps)."""
        liquid = float(proto.get("liquid_reserve_pct", 0))
        stress = float(proto.get("stress_redemption_pct", 0))
        return liquid / max(stress, _EPS)

    @staticmethod
    def _redemption_stress_shortfall_pct(proto: dict) -> float:
        """max(0, stress_redemption_pct - liquid_reserve_pct)."""
        stress = float(proto.get("stress_redemption_pct", 0))
        liquid = float(proto.get("liquid_reserve_pct", 0))
        return max(0.0, stress - liquid)

    @staticmethod
    def _net_interest_margin_pct(proto: dict) -> float:
        """asset_yield_apy_pct - funding_cost_apy_pct."""
        asset_yield = float(proto.get("asset_yield_apy_pct", 0))
        funding = float(proto.get("funding_cost_apy_pct", 0))
        return asset_yield - funding

    @staticmethod
    def _rate_reset_exposed(proto: dict) -> bool:
        """fixed_rate_assets and floating_rate_liabilities."""
        return bool(proto.get("fixed_rate_assets", False)) and bool(
            proto.get("floating_rate_liabilities", False))

    def _duration_mismatch_score(self, proto: dict) -> float:
        """
        0-100 (higher=worse). Grows with duration_gap_days,
        redemption_stress_shortfall_pct, illiquid_asset_pct; reduced by
        high liquidity_coverage_ratio.
        """
        gap = self._duration_gap_days(proto)
        shortfall = self._redemption_stress_shortfall_pct(proto)
        illiquid = float(proto.get("illiquid_asset_pct", 0))
        coverage = self._liquidity_coverage_ratio(proto)

        # Gap component: only positive gaps add risk, saturating at 365d.
        gap_component = min(max(gap, 0.0) / 365.0, 1.0) * 40.0
        # Shortfall component: saturates at 50pp shortfall.
        shortfall_component = min(max(shortfall, 0.0) / 50.0, 1.0) * 35.0
        # Illiquidity component: 0-100% -> 0-25 pts.
        illiquid_component = min(max(illiquid, 0.0) / 100.0, 1.0) * 25.0

        raw = gap_component + shortfall_component + illiquid_component

        # Coverage relief: strong coverage reduces score (up to ~40%).
        relief = min(max(coverage, 0.0) / 3.0, 1.0) * 0.4
        score = raw * (1.0 - relief)
        return min(max(score, 0.0), 100.0)

    @staticmethod
    def _classification(score: float) -> str:
        """
        MATCHED / MINOR_MISMATCH / MODERATE_MISMATCH / SEVERE_MISMATCH / RUN_RISK
        """
        if score >= 80:
            return "RUN_RISK"
        if score >= 60:
            return "SEVERE_MISMATCH"
        if score >= 40:
            return "MODERATE_MISMATCH"
        if score >= 20:
            return "MINOR_MISMATCH"
        return "MATCHED"

    @staticmethod
    def _grade(score: float) -> str:
        """A-F grade from duration_mismatch_score (higher -> worse)."""
        if score < 20:
            return "A"
        if score < 40:
            return "B"
        if score < 60:
            return "C"
        if score < 80:
            return "D"
        return "F"

    @staticmethod
    def _has_key_fields(proto: dict) -> bool:
        """True if minimal key fields for analysis are present."""
        key_fields = (
            "asset_avg_maturity_days",
            "liability_avg_redemption_days",
            "liquid_reserve_pct",
            "stress_redemption_pct",
        )
        return any(k in proto for k in key_fields)

    def _compute_flags(self, proto: dict) -> list:
        """Compute applicable flags for a protocol."""
        flags = []
        gap = self._duration_gap_days(proto)
        coverage = self._liquidity_coverage_ratio(proto)
        shortfall = self._redemption_stress_shortfall_pct(proto)
        nim = self._net_interest_margin_pct(proto)
        illiquid = float(proto.get("illiquid_asset_pct", 0))

        if gap < 0:
            flags.append("NEGATIVE_DURATION_GAP")
        if gap > 180:
            flags.append("LARGE_DURATION_GAP")
        if coverage < 1:
            flags.append("INSUFFICIENT_LIQUID_RESERVE")
        if shortfall > 10 and coverage < 1:
            flags.append("RUN_RISK")
        if self._rate_reset_exposed(proto):
            flags.append("RATE_RESET_EXPOSED")
        if bool(proto.get("fixed_rate_assets", False)) != bool(
                proto.get("floating_rate_liabilities", False)):
            flags.append("FIXED_FLOATING_MISMATCH")
        if illiquid > 70:
            flags.append("HIGH_ILLIQUID_ASSETS")
        if coverage >= 2 and gap <= 30:
            flags.append("WELL_MATCHED")
        if coverage >= 3:
            flags.append("STRONG_LIQUIDITY_COVERAGE")
        if nim < 0:
            flags.append("NEGATIVE_NIM")

        if not self._has_key_fields(proto):
            flags.append("INSUFFICIENT_DATA")

        return flags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, protocols: list, config: dict | None = None) -> dict:
        """
        Analyze a list of yield protocols for duration / liquidity mismatch.

        Args:
            protocols: list of protocol dicts
            config: optional config dict (data_dir, etc.)

        Returns:
            dict with analyzed_protocols, aggregates, metadata
        """
        if config is None:
            config = {}

        data_dir = config.get("data_dir", self.data_dir)
        log_path = os.path.join(data_dir, self.LOG_FILE)

        analyzed = []
        for proto in protocols:
            gap = self._duration_gap_days(proto)
            coverage = self._liquidity_coverage_ratio(proto)
            shortfall = self._redemption_stress_shortfall_pct(proto)
            nim = self._net_interest_margin_pct(proto)
            rate_reset = self._rate_reset_exposed(proto)
            score = self._duration_mismatch_score(proto)
            classification = self._classification(score)
            grade = self._grade(score)
            flags = self._compute_flags(proto)

            analyzed.append({
                "name": proto.get("name", ""),
                "protocol": proto.get("protocol", ""),
                "asset_avg_maturity_days": float(
                    proto.get("asset_avg_maturity_days", 0)),
                "liability_avg_redemption_days": float(
                    proto.get("liability_avg_redemption_days", 0)),
                "liquid_reserve_pct": float(proto.get("liquid_reserve_pct", 0)),
                "stress_redemption_pct": float(
                    proto.get("stress_redemption_pct", 0)),
                "illiquid_asset_pct": float(proto.get("illiquid_asset_pct", 0)),
                "duration_gap_days": round(gap, 2),
                "liquidity_coverage_ratio": round(coverage, 4),
                "redemption_stress_shortfall_pct": round(shortfall, 2),
                "net_interest_margin_pct": round(nim, 2),
                "rate_reset_exposed": bool(rate_reset),
                "duration_mismatch_score": round(score, 2),
                "classification": classification,
                "grade": grade,
                "flags": flags,
            })

        # Aggregates
        if analyzed:
            scores = [a["duration_mismatch_score"] for a in analyzed]
            avg_score = sum(scores) / len(scores)
            worst = max(analyzed, key=lambda a: a["duration_mismatch_score"])
            best = min(analyzed, key=lambda a: a["duration_mismatch_score"])
            run_risk_count = sum(
                1 for a in analyzed if a["classification"] == "RUN_RISK")
            matched_count = sum(
                1 for a in analyzed if a["classification"] == "MATCHED")
        else:
            avg_score = 0.0
            worst = {}
            best = {}
            run_risk_count = 0
            matched_count = 0

        aggregates = {
            "best_matched": best.get("name", "") if best else "",
            "worst_mismatch": worst.get("name", "") if worst else "",
            "avg_duration_mismatch_score": round(avg_score, 2),
            "run_risk_count": run_risk_count,
            "matched_count": matched_count,
        }

        result = {
            "analyzed_protocols": analyzed,
            "aggregates": aggregates,
            "metadata": {
                "module": "ProtocolDeFiYieldDurationMismatchAnalyzer",
                "mp": "MP-1025",
                "protocol_count": len(protocols),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

        # Ring-buffer log (cap 100), atomic write
        log_entry = {
            "timestamp": result["metadata"]["timestamp"],
            "protocol_count": len(protocols),
            "avg_duration_mismatch_score": aggregates["avg_duration_mismatch_score"],
            "run_risk_count": aggregates["run_risk_count"],
            "matched_count": aggregates["matched_count"],
        }
        buf = _load_ring_buffer(log_path, self.LOG_CAP)
        buf.append(log_entry)
        buf = buf[-self.LOG_CAP:]
        _atomic_write(log_path, buf)

        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    demo_protocols = [
        {
            "name": "Stable Money Market",
            "protocol": "MarketCo",
            "asset_avg_maturity_days": 20,
            "liability_avg_redemption_days": 1,
            "liquid_reserve_pct": 60,
            "redeemable_on_demand_pct": 80,
            "stress_redemption_pct": 30,
            "illiquid_asset_pct": 20,
            "asset_yield_apy_pct": 8.0,
            "funding_cost_apy_pct": 4.0,
            "fixed_rate_assets": False,
            "floating_rate_liabilities": False,
        },
        {
            "name": "RWA Yield Vault",
            "protocol": "VaultCo",
            "asset_avg_maturity_days": 365,
            "liability_avg_redemption_days": 1,
            "liquid_reserve_pct": 5,
            "redeemable_on_demand_pct": 100,
            "stress_redemption_pct": 40,
            "illiquid_asset_pct": 90,
            "asset_yield_apy_pct": 6.0,
            "funding_cost_apy_pct": 9.0,
            "fixed_rate_assets": True,
            "floating_rate_liabilities": True,
        },
    ]

    analyzer = ProtocolDeFiYieldDurationMismatchAnalyzer()
    result = analyzer.analyze(demo_protocols, {})
    print(json.dumps(result, indent=2))

"""
MP-1024: DeFiProtocolSequencerDowntimeRiskAnalyzer
Оценивает риск для L2 DeFi позиций от простоя/цензуры sequencer'а
(несправедливые/задержанные ликвидации, bad debt).
Только stdlib Python, atomic writes, read-only/advisory домен.
"""

import json
import os
import time
import tempfile
from typing import Any

# Default data directory (relative to repo root)
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


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


class DeFiProtocolSequencerDowntimeRiskAnalyzer:
    """
    Analyzes L2 DeFi positions for sequencer-downtime / censorship risk.

    analyze(positions, config) -> dict with per-position details
    and aggregate statistics.
    """

    LOG_FILE = "sequencer_downtime_risk_log.json"
    LOG_CAP = 100

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Core scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _downtime_frequency_score(pos: dict) -> float:
        """
        0-100 (higher=worse) from historical_downtime_minutes_30d.
        Monotonic, saturates to 100 at >= 720 minutes.
        """
        downtime = float(pos.get("historical_downtime_minutes_30d", 0))
        if downtime <= 0:
            return 0.0
        # Linear ramp, saturating at 720 min (12h) over 30d window.
        score = (downtime / 720.0) * 100.0
        return min(max(score, 0.0), 100.0)

    @staticmethod
    def _liquidation_exposure_score(pos: dict) -> float:
        """
        0-100 (higher=worse). Higher as health_factor approaches 1.0.
        Amplified when single-sequencer and no grace period.
        """
        hf_raw = pos.get("health_factor", None)
        if hf_raw is None:
            # No HF data -> assume moderate baseline exposure.
            base = 50.0
        else:
            hf = float(hf_raw)
            if hf <= 0:
                # Already underwater / invalid -> maximal exposure.
                base = 100.0
            elif hf >= 3.0:
                base = 0.0
            else:
                # hf=1.0 -> 100, hf=3.0 -> 0, linear in between.
                base = max(0.0, min(100.0, (3.0 - hf) / 2.0 * 100.0))

        multiplier = 1.0
        if pos.get("is_single_sequencer", False):
            multiplier += 0.25
        if not pos.get("has_grace_period", False):
            multiplier += 0.25
        score = base * multiplier
        return min(max(score, 0.0), 100.0)

    @staticmethod
    def _escape_hatch_score(pos: dict) -> float:
        """
        0-100 PROTECTION score (higher=better):
        force_inclusion(50) + uptime_feed(30) + decentralization_roadmap(20).
        Long force_inclusion_delay_hours reduces the force_inclusion contribution.
        """
        score = 0.0
        if pos.get("has_force_inclusion", False):
            delay = float(pos.get("force_inclusion_delay_hours", 0))
            # Decay contribution as delay grows; 24h delay halves it.
            decay = 24.0 / (24.0 + max(delay, 0.0))
            score += 50.0 * decay
        if pos.get("uptime_feed_integrated", False):
            score += 30.0
        if pos.get("decentralized_sequencer_roadmap", False):
            score += 20.0
        return min(max(score, 0.0), 100.0)

    @staticmethod
    def _centralization_score(pos: dict) -> float:
        """
        0-100 (higher=worse):
        is_single_sequencer(60) + (not decentralized_roadmap)(40).
        """
        score = 0.0
        if pos.get("is_single_sequencer", False):
            score += 60.0
        if not pos.get("decentralized_sequencer_roadmap", False):
            score += 40.0
        return min(max(score, 0.0), 100.0)

    def _net_downtime_risk_score(self, pos: dict) -> float:
        """
        Weighted combination of (downtime_frequency, liquidation_exposure,
        centralization) minus escape_hatch_score, clipped 0..100.
        """
        downtime = self._downtime_frequency_score(pos)
        liq = self._liquidation_exposure_score(pos)
        central = self._centralization_score(pos)
        escape = self._escape_hatch_score(pos)

        raw = downtime * 0.35 + liq * 0.40 + central * 0.25
        net = raw - escape * 0.5
        return min(max(net, 0.0), 100.0)

    @staticmethod
    def _classification(net_risk: float) -> str:
        """
        RESILIENT / LOW_RISK / MODERATE_RISK / HIGH_RISK / CRITICAL_EXPOSURE
        """
        if net_risk >= 80:
            return "CRITICAL_EXPOSURE"
        if net_risk >= 60:
            return "HIGH_RISK"
        if net_risk >= 40:
            return "MODERATE_RISK"
        if net_risk >= 20:
            return "LOW_RISK"
        return "RESILIENT"

    @staticmethod
    def _grade(net_risk: float) -> str:
        """A-F grade from net_downtime_risk_score (higher risk -> worse grade)."""
        if net_risk < 20:
            return "A"
        if net_risk < 40:
            return "B"
        if net_risk < 60:
            return "C"
        if net_risk < 80:
            return "D"
        return "F"

    @staticmethod
    def _has_key_fields(pos: dict) -> bool:
        """True if minimal key fields for analysis are present."""
        key_fields = (
            "health_factor",
            "historical_downtime_minutes_30d",
            "is_single_sequencer",
        )
        return any(k in pos for k in key_fields)

    def _compute_flags(self, pos: dict) -> list:
        """Compute applicable flags for a position."""
        flags = []
        if pos.get("is_single_sequencer", False):
            flags.append("SINGLE_SEQUENCER")
        if not pos.get("has_grace_period", False):
            flags.append("NO_GRACE_PERIOD")

        hf_raw = pos.get("health_factor", None)
        if hf_raw is not None:
            hf = float(hf_raw)
            if 0 < hf < 1.1:
                flags.append("NEAR_LIQUIDATION")

        escape = self._escape_hatch_score(pos)
        if escape <= 0:
            flags.append("NO_ESCAPE_HATCH")

        downtime = float(pos.get("historical_downtime_minutes_30d", 0))
        if downtime > 60:
            flags.append("FREQUENT_DOWNTIME")

        max_outage = float(pos.get("max_single_outage_minutes", 0))
        if max_outage > 120:
            flags.append("LONG_MAX_OUTAGE")

        if pos.get("uptime_feed_integrated", False):
            flags.append("UPTIME_FEED_PROTECTED")
        if pos.get("has_force_inclusion", False):
            flags.append("FORCE_INCLUSION_AVAILABLE")
        if pos.get("decentralized_sequencer_roadmap", False):
            flags.append("DECENTRALIZATION_PLANNED")

        if not self._has_key_fields(pos):
            flags.append("INSUFFICIENT_DATA")

        return flags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, positions: list, config: dict | None = None) -> dict:
        """
        Analyze a list of L2 DeFi positions for sequencer-downtime risk.

        Args:
            positions: list of position dicts
            config: optional config dict (data_dir, etc.)

        Returns:
            dict with analyzed_positions, aggregates, metadata
        """
        if config is None:
            config = {}

        data_dir = config.get("data_dir", self.data_dir)
        log_path = os.path.join(data_dir, self.LOG_FILE)

        analyzed = []
        for pos in positions:
            downtime_freq = self._downtime_frequency_score(pos)
            liq_exposure = self._liquidation_exposure_score(pos)
            escape = self._escape_hatch_score(pos)
            central = self._centralization_score(pos)
            net_risk = self._net_downtime_risk_score(pos)
            classification = self._classification(net_risk)
            grade = self._grade(net_risk)
            flags = self._compute_flags(pos)

            analyzed.append({
                "name": pos.get("name", ""),
                "protocol": pos.get("protocol", ""),
                "chain": pos.get("chain", ""),
                "is_single_sequencer": bool(pos.get("is_single_sequencer", False)),
                "has_grace_period": bool(pos.get("has_grace_period", False)),
                "health_factor": float(pos.get("health_factor", 0)),
                "historical_downtime_minutes_30d": float(
                    pos.get("historical_downtime_minutes_30d", 0)),
                "max_single_outage_minutes": float(
                    pos.get("max_single_outage_minutes", 0)),
                "downtime_frequency_score": round(downtime_freq, 2),
                "liquidation_exposure_score": round(liq_exposure, 2),
                "escape_hatch_score": round(escape, 2),
                "centralization_score": round(central, 2),
                "net_downtime_risk_score": round(net_risk, 2),
                "classification": classification,
                "grade": grade,
                "flags": flags,
            })

        # Aggregates
        if analyzed:
            risks = [a["net_downtime_risk_score"] for a in analyzed]
            avg_risk = sum(risks) / len(risks)
            riskiest = max(analyzed, key=lambda a: a["net_downtime_risk_score"])
            safest = min(analyzed, key=lambda a: a["net_downtime_risk_score"])
            critical_count = sum(
                1 for a in analyzed if a["classification"] == "CRITICAL_EXPOSURE")
            resilient_count = sum(
                1 for a in analyzed if a["classification"] == "RESILIENT")
        else:
            avg_risk = 0.0
            riskiest = {}
            safest = {}
            critical_count = 0
            resilient_count = 0

        aggregates = {
            "safest_position": safest.get("name", "") if safest else "",
            "riskiest_position": riskiest.get("name", "") if riskiest else "",
            "avg_net_downtime_risk": round(avg_risk, 2),
            "critical_count": critical_count,
            "resilient_count": resilient_count,
        }

        result = {
            "analyzed_positions": analyzed,
            "aggregates": aggregates,
            "metadata": {
                "module": "DeFiProtocolSequencerDowntimeRiskAnalyzer",
                "mp": "MP-1024",
                "position_count": len(positions),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

        # Ring-buffer log (cap 100), atomic write
        log_entry = {
            "timestamp": result["metadata"]["timestamp"],
            "position_count": len(positions),
            "avg_net_downtime_risk": aggregates["avg_net_downtime_risk"],
            "critical_count": aggregates["critical_count"],
            "resilient_count": aggregates["resilient_count"],
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

    demo_positions = [
        {
            "name": "ETH Leveraged Long",
            "protocol": "Aave V3",
            "chain": "Arbitrum",
            "is_single_sequencer": True,
            "has_grace_period": True,
            "grace_period_minutes": 30,
            "historical_downtime_minutes_30d": 45,
            "max_single_outage_minutes": 90,
            "health_factor": 1.15,
            "has_force_inclusion": True,
            "force_inclusion_delay_hours": 24,
            "uptime_feed_integrated": True,
            "decentralized_sequencer_roadmap": True,
        },
        {
            "name": "Risky Borrow",
            "protocol": "Lending Co",
            "chain": "MegaL2",
            "is_single_sequencer": True,
            "has_grace_period": False,
            "grace_period_minutes": 0,
            "historical_downtime_minutes_30d": 800,
            "max_single_outage_minutes": 300,
            "health_factor": 1.02,
            "has_force_inclusion": False,
            "force_inclusion_delay_hours": 0,
            "uptime_feed_integrated": False,
            "decentralized_sequencer_roadmap": False,
        },
    ]

    analyzer = DeFiProtocolSequencerDowntimeRiskAnalyzer()
    result = analyzer.analyze(demo_positions, {})
    print(json.dumps(result, indent=2))

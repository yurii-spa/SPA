"""
MP-765: ProtocolHealthChecker
Multi-factor protocol health scoring.

Factors considered:
  - TVL trend (1-week and 4-week)
  - Governance activity (0–1 float)
  - Code audit score (0–100)
  - Team activity score (0–1 float)
  - Bug bounty size (USD)

Outputs:
  - health_score (0–100 composite)
  - health_status: HEALTHY / WATCH / CAUTION / CRITICAL
  - flagged flag (True when score < FLAG_THRESHOLD)

Pure stdlib, read-only advisory module.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json
import math
import time
import os
from pathlib import Path

DATA_FILE = Path("data/protocol_health_log.json")
MAX_ENTRIES = 100

# health_status thresholds (score boundaries, inclusive lower bound)
HEALTHY_THRESHOLD = 75.0
WATCH_THRESHOLD = 50.0
CAUTION_THRESHOLD = 25.0
# score < CAUTION_THRESHOLD → CRITICAL

# Protocols are flagged for attention when score is below this
FLAG_THRESHOLD = 50.0


@dataclass
class HealthResult:
    """Health evaluation result for a single protocol."""
    protocol: str
    timestamp: float
    health_score: float    # 0–100 composite
    health_status: str     # HEALTHY / WATCH / CAUTION / CRITICAL
    flagged: bool          # True if health_score < FLAG_THRESHOLD
    components: Dict[str, float]   # individual component scores (0–25 each)

    def get_health_score(self) -> float:
        """Return the composite health score."""
        return self.health_score


class ProtocolHealthChecker:
    """
    Evaluates multi-factor protocol health and flags protocols needing attention.

    Usage::

        checker = ProtocolHealthChecker()
        result = checker.check_health({
            "protocol": "Aave V3",
            "tvl_trend_1w": 0.05,
            "tvl_trend_4w": 0.10,
            "governance_activity": 0.8,
            "code_audit_score": 90.0,
            "team_activity_score": 0.9,
            "bug_bounty_size_usd": 1_000_000,
        })
        print(result.health_status)          # HEALTHY
        print(checker.get_health_score())    # composite score
        flagged = checker.get_flagged_protocols()
    """

    def __init__(self, data_file: Path = DATA_FILE) -> None:
        self.data_file = data_file
        self._results: List[HealthResult] = []
        self._last_result: Optional[HealthResult] = None

    # ------------------------------------------------------------------ #
    # Core evaluation                                                      #
    # ------------------------------------------------------------------ #

    def check_health(self, protocol_data: dict) -> HealthResult:
        """
        Evaluate health for a single protocol dict and store the result.

        Args:
            protocol_data: dict with keys (all optional except ``protocol``):
                - ``protocol``            (str)   – protocol name
                - ``tvl_trend_1w``        (float) – fractional TVL change over 1 week
                                                    (e.g. 0.05 = +5 %, -0.10 = -10 %)
                - ``tvl_trend_4w``        (float) – fractional TVL change over 4 weeks
                - ``governance_activity`` (float) – 0.0–1.0 score of recent governance
                - ``code_audit_score``    (float) – 0–100 from external audit
                - ``team_activity_score`` (float) – 0.0–1.0 developer/team activity
                - ``bug_bounty_size_usd`` (float) – USD size of active bug bounty

        Returns:
            HealthResult with composite score, status, and component breakdown.
        """
        result = self._evaluate(protocol_data)
        self._results.append(result)
        self._last_result = result
        return result

    def check_all(self, protocols: List[dict]) -> List[HealthResult]:
        """
        Evaluate health for multiple protocols, replacing the internal batch.

        Returns the full list of HealthResult objects.
        """
        self._results = []
        results = [self._evaluate(p) for p in protocols]
        self._results = results
        if results:
            self._last_result = results[-1]
        return results

    # ------------------------------------------------------------------ #
    # Accessor methods                                                     #
    # ------------------------------------------------------------------ #

    def get_health_score(self) -> float:
        """Return health score of the most recently checked protocol (0.0 if none)."""
        if self._last_result is None:
            return 0.0
        return self._last_result.health_score

    def get_flagged_protocols(self) -> List[HealthResult]:
        """Return all stored results where health_score < FLAG_THRESHOLD."""
        return [r for r in self._results if r.flagged]

    def clear_results(self) -> None:
        """Clear all stored results and reset last result."""
        self._results = []
        self._last_result = None

    # ------------------------------------------------------------------ #
    # Internal scoring                                                     #
    # ------------------------------------------------------------------ #

    def _evaluate(self, protocol_data: dict) -> HealthResult:
        """Compute HealthResult from a protocol_data dict."""
        protocol = str(protocol_data.get("protocol", "unknown"))

        tvl_1w = float(protocol_data.get("tvl_trend_1w", 0.0))
        tvl_4w = float(protocol_data.get("tvl_trend_4w", 0.0))
        gov_act = float(protocol_data.get("governance_activity", 0.0))
        audit_score = float(protocol_data.get("code_audit_score", 0.0))
        team_act = float(protocol_data.get("team_activity_score", 0.0))
        bounty_usd = float(protocol_data.get("bug_bounty_size_usd", 0.0))

        # Component 1: TVL health (0–25)
        #   1w sub-score (0–12.5): full credit at +10 %, zero at -10 %
        #   4w sub-score (0–12.5): full credit at +20 %, zero at -20 %
        tvl_1w_score = 12.5 * self._clamp((tvl_1w + 0.10) / 0.20, 0.0, 1.0)
        tvl_4w_score = 12.5 * self._clamp((tvl_4w + 0.20) / 0.40, 0.0, 1.0)
        tvl_score = round(tvl_1w_score + tvl_4w_score, 6)

        # Component 2: governance activity (0–25)
        gov_score = round(25.0 * self._clamp(gov_act, 0.0, 1.0), 6)

        # Component 3: code audit security (0–25)
        audit_component = round(25.0 * self._clamp(audit_score / 100.0, 0.0, 1.0), 6)

        # Component 4: team activity + bug bounty (0–25)
        #   team sub-score  (0–15): scales with team_activity_score
        #   bounty sub-score (0–10): log-scale; $10M → 10 pts, $0 → 0 pts
        team_sub = 15.0 * self._clamp(team_act, 0.0, 1.0)
        bounty_sub = 10.0 * min(
            1.0,
            math.log10(max(1.0, bounty_usd)) / 7.0,   # log10(10M) = 7
        )
        team_bounty_score = round(team_sub + bounty_sub, 6)

        health_score = round(
            tvl_score + gov_score + audit_component + team_bounty_score,
            4,
        )
        # Clamp to [0, 100] in case of floating-point drift
        health_score = max(0.0, min(100.0, health_score))

        health_status = self._classify_status(health_score)
        flagged = health_score < FLAG_THRESHOLD

        components = {
            "tvl_health": tvl_score,
            "governance": gov_score,
            "code_audit": audit_component,
            "team_bounty": team_bounty_score,
        }

        return HealthResult(
            protocol=protocol,
            timestamp=time.time(),
            health_score=health_score,
            health_status=health_status,
            flagged=flagged,
            components=components,
        )

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _classify_status(score: float) -> str:
        """Map a composite score to a human-readable health_status string."""
        if score >= HEALTHY_THRESHOLD:
            return "HEALTHY"
        if score >= WATCH_THRESHOLD:
            return "WATCH"
        if score >= CAUTION_THRESHOLD:
            return "CAUTION"
        return "CRITICAL"

    # ------------------------------------------------------------------ #
    # Persistence (ring-buffer, atomic write)                              #
    # ------------------------------------------------------------------ #

    def save_results(self, results: Optional[List[HealthResult]] = None) -> None:
        """
        Atomically append health results to the ring-buffer JSON log.
        Saves ``self._results`` by default; pass ``results`` to override.
        The log is capped at MAX_ENTRIES (100) most-recent entries.
        """
        to_save = results if results is not None else self._results
        if not to_save:
            return

        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        for r in to_save:
            existing.append(
                {
                    "timestamp": r.timestamp,
                    "protocol": r.protocol,
                    "health_score": r.health_score,
                    "health_status": r.health_status,
                    "flagged": r.flagged,
                    "components": r.components,
                }
            )

        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Load saved health log from disk; returns [] if file missing/invalid."""
        try:
            data = json.loads(self.data_file.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            return []


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _demo_protocols() -> List[dict]:
    return [
        {
            "protocol": "Aave V3",
            "tvl_trend_1w": 0.04,
            "tvl_trend_4w": 0.08,
            "governance_activity": 0.80,
            "code_audit_score": 92.0,
            "team_activity_score": 0.85,
            "bug_bounty_size_usd": 2_000_000,
        },
        {
            "protocol": "Compound V3",
            "tvl_trend_1w": 0.01,
            "tvl_trend_4w": -0.05,
            "governance_activity": 0.60,
            "code_audit_score": 85.0,
            "team_activity_score": 0.70,
            "bug_bounty_size_usd": 500_000,
        },
        {
            "protocol": "HighRisk Protocol",
            "tvl_trend_1w": -0.15,
            "tvl_trend_4w": -0.30,
            "governance_activity": 0.10,
            "code_audit_score": 30.0,
            "team_activity_score": 0.20,
            "bug_bounty_size_usd": 10_000,
        },
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-765 ProtocolHealthChecker")
    parser.add_argument("--run", action="store_true", help="Compute + save to data file")
    parser.add_argument("--check", action="store_true", help="Compute + print, no save (default)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_file = DATA_FILE
    if args.data_dir:
        data_file = Path(args.data_dir) / "protocol_health_log.json"

    checker = ProtocolHealthChecker(data_file=data_file)
    results = checker.check_all(_demo_protocols())

    for r in results:
        flag = " ⚠️ FLAGGED" if r.flagged else ""
        print(f"{r.protocol:<25} [{r.health_status:<8}] score={r.health_score:.1f}{flag}")
        for comp, val in r.components.items():
            print(f"  {comp:<18}: {val:.2f}/25")

    flagged = checker.get_flagged_protocols()
    if flagged:
        print(f"\n⚠️  {len(flagged)} protocol(s) flagged for attention.")

    if args.run:
        checker.save_results()
        print(f"\nSaved → {data_file}")

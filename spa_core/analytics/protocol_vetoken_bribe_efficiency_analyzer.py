"""
MP-932 ProtocolVeTokenBribeEfficiencyAnalyzer
=============================================
Evaluates vote-escrow (ve-token) **bribe markets** / gauge-voting economics in
ve(3,3)-style ecosystems (Curve/Convex, Balancer/Aura, Aerodrome, Velodrome…).

In these systems gauges receive token emissions in proportion to the veToken
votes they attract, and "bribe markets" let protocols pay voters to direct
those emissions toward their own gauge. This module answers two questions:

  * Briber side  — "Is paying this bribe an efficient way to buy emissions?"
  * Voter side   — "Which gauge pays voters the best APR for their lock?"

For each gauge it computes:
  bribe_per_vote            bribe_usd / votes        (voter income per vote)
  emission_value_per_vote   emissions_usd / votes
  briber_efficiency_ratio   emissions_usd / bribe_usd  (>1 = cheap emissions)
  voter_apr_pct             annualised return for a voter locking veToken here

Gauge classification (from briber efficiency):
  HIGHLY_EFFICIENT | EFFICIENT | BREAK_EVEN | INEFFICIENT | WASTEFUL

Flags:
  NO_VOTES           votes <= 0
  NO_BRIBE           bribe_usd <= 0
  OVERBRIBED         bribe_usd > emissions_usd  (briber overpays vs emissions)
  UNDERBRIBED        bribe_usd < 10 % of emissions_usd (voters underpaid)
  HIGH_VOTER_APR     voter_apr_pct > 50 %
  MERCENARY_RISK     voter_apr_pct > 100 % (unsustainable, mercenary capital)

Input gauge keys:
  name                 str
  votes                float   veToken vote units on this gauge
  bribe_usd            float   total bribes offered this epoch
  emissions_usd        float   USD value of emissions the gauge will direct
  vote_value_usd       float   USD value of one vote unit (default 1.0)
  epochs_per_year      float   default 52 (weekly epochs)

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "vetoken_bribe_efficiency_log.json"
)
_LOG_CAP = 100

_DEFAULT_EPOCHS_PER_YEAR = 52.0
_DEFAULT_VOTE_VALUE_USD = 1.0

# Briber efficiency ratio thresholds → classification / grade
_HIGHLY_EFFICIENT_RATIO = 2.0
_EFFICIENT_RATIO = 1.3
_BREAK_EVEN_RATIO = 0.9
_INEFFICIENT_RATIO = 0.5

# Flag thresholds
_UNDERBRIBED_RATIO = 0.10          # bribe < 10 % of emissions value
_HIGH_VOTER_APR_PCT = 50.0
_MERCENARY_VOTER_APR_PCT = 100.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float, denominator: float) -> float:
    """Division guarded against zero/negative denominators → 0.0."""
    if denominator is None or denominator <= 0.0:
        return 0.0
    return numerator / denominator


def _grade_from_efficiency(ratio: float) -> str:
    """Map briber efficiency ratio to an A–F letter grade."""
    if ratio >= _HIGHLY_EFFICIENT_RATIO:
        return "A"
    if ratio >= _EFFICIENT_RATIO:
        return "B"
    if ratio >= _BREAK_EVEN_RATIO:
        return "C"
    if ratio >= _INEFFICIENT_RATIO:
        return "D"
    return "F"


def _classification_from_efficiency(ratio: float) -> str:
    """Map briber efficiency ratio to a human-readable classification."""
    if ratio >= _HIGHLY_EFFICIENT_RATIO:
        return "HIGHLY_EFFICIENT"
    if ratio >= _EFFICIENT_RATIO:
        return "EFFICIENT"
    if ratio >= _BREAK_EVEN_RATIO:
        return "BREAK_EVEN"
    if ratio >= _INEFFICIENT_RATIO:
        return "INEFFICIENT"
    return "WASTEFUL"


def _atomic_log(log_path: str, entry: dict) -> None:
    """Append entry to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolVeTokenBribeEfficiencyAnalyzer:
    """
    Analyses ve-token bribe markets / gauge-voting efficiency.

    Usage::

        analyzer = ProtocolVeTokenBribeEfficiencyAnalyzer()
        result = analyzer.analyze(gauges, config)

    config keys (all optional):
        log_path         str    override default log file location
        write_log        bool   default True; set False to skip disk write
        epochs_per_year  float  global default for epochs per year (52)
    """

    # ------------------------------------------------------------------
    # Per-gauge calculations
    # ------------------------------------------------------------------

    def _bribe_per_vote(self, gauge: dict) -> float:
        votes = float(gauge.get("votes", 0.0))
        bribe = float(gauge.get("bribe_usd", 0.0))
        return round(_safe_div(bribe, votes), 8)

    def _emission_value_per_vote(self, gauge: dict) -> float:
        votes = float(gauge.get("votes", 0.0))
        emissions = float(gauge.get("emissions_usd", 0.0))
        return round(_safe_div(emissions, votes), 8)

    def _briber_efficiency_ratio(self, gauge: dict) -> float:
        """USD of emissions attracted per USD of bribe spent."""
        bribe = float(gauge.get("bribe_usd", 0.0))
        emissions = float(gauge.get("emissions_usd", 0.0))
        return round(_safe_div(emissions, bribe), 6)

    def _voter_apr_pct(self, gauge: dict, default_epochs: float) -> float:
        """
        Annualised voter return: (bribe_per_vote / vote_value) per epoch,
        scaled by epochs_per_year.
        """
        bribe_per_vote = self._bribe_per_vote(gauge)
        vote_value = float(gauge.get("vote_value_usd", _DEFAULT_VOTE_VALUE_USD))
        epochs = float(gauge.get("epochs_per_year", default_epochs))
        per_epoch_return = _safe_div(bribe_per_vote, vote_value)
        return round(per_epoch_return * epochs * 100.0, 6)

    def _compute_flags(
        self,
        gauge: dict,
        efficiency_ratio: float,
        voter_apr: float,
    ) -> list:
        """Return list of applicable flag strings."""
        flags: list[str] = []

        votes = float(gauge.get("votes", 0.0))
        bribe = float(gauge.get("bribe_usd", 0.0))
        emissions = float(gauge.get("emissions_usd", 0.0))

        if votes <= 0.0:
            flags.append("NO_VOTES")

        if bribe <= 0.0:
            flags.append("NO_BRIBE")

        if emissions > 0.0 and bribe > emissions:
            flags.append("OVERBRIBED")

        if (
            emissions > 0.0
            and bribe > 0.0
            and bribe < emissions * _UNDERBRIBED_RATIO
        ):
            flags.append("UNDERBRIBED")

        if voter_apr > _MERCENARY_VOTER_APR_PCT:
            flags.append("MERCENARY_RISK")
        elif voter_apr > _HIGH_VOTER_APR_PCT:
            flags.append("HIGH_VOTER_APR")

        return flags

    # ------------------------------------------------------------------
    # Single-gauge analysis
    # ------------------------------------------------------------------

    def _analyze_gauge(self, gauge: dict, default_epochs: float) -> dict:
        """Analyse one gauge and return result dict."""
        bribe_per_vote = self._bribe_per_vote(gauge)
        emission_value_per_vote = self._emission_value_per_vote(gauge)
        efficiency_ratio = self._briber_efficiency_ratio(gauge)
        voter_apr = self._voter_apr_pct(gauge, default_epochs)
        classification = _classification_from_efficiency(efficiency_ratio)
        grade = _grade_from_efficiency(efficiency_ratio)
        flags = self._compute_flags(gauge, efficiency_ratio, voter_apr)

        return {
            "name": gauge.get("name", "unknown"),
            "votes": float(gauge.get("votes", 0.0)),
            "bribe_usd": float(gauge.get("bribe_usd", 0.0)),
            "emissions_usd": float(gauge.get("emissions_usd", 0.0)),
            "bribe_per_vote": bribe_per_vote,
            "emission_value_per_vote": emission_value_per_vote,
            "briber_efficiency_ratio": efficiency_ratio,
            "voter_apr_pct": voter_apr,
            "classification": classification,
            "grade": grade,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, gauges: list, config: dict | None = None) -> dict:
        """
        Analyse a list of ve-token gauges / bribe markets.

        Parameters
        ----------
        gauges : list[dict]
            Each dict describes one gauge (see module docstring).
        config : dict, optional
            Optional overrides:
                log_path         str    custom log file path
                write_log        bool   set False to skip log write (default True)
                epochs_per_year  float  default epochs per year (52)

        Returns
        -------
        dict with keys:
            results     list[dict]  per-gauge analysis
            aggregates  dict        portfolio-level summary
            timestamp   float       unix timestamp
        """
        if config is None:
            config = {}
        if not isinstance(gauges, list):
            raise TypeError("gauges must be a list")

        default_epochs = float(
            config.get("epochs_per_year", _DEFAULT_EPOCHS_PER_YEAR)
        )

        results = [self._analyze_gauge(g, default_epochs) for g in gauges]

        # ── Aggregates ───────────────────────────────────────────────
        if results:
            efficiencies = [r["briber_efficiency_ratio"] for r in results]
            voter_aprs = [r["voter_apr_pct"] for r in results]

            best_eff_idx = efficiencies.index(max(efficiencies))
            best_apr_idx = voter_aprs.index(max(voter_aprs))

            most_efficient_gauge = results[best_eff_idx]["name"]
            best_voter_apr_gauge = results[best_apr_idx]["name"]
            avg_efficiency = sum(efficiencies) / len(efficiencies)
            total_bribe = sum(r["bribe_usd"] for r in results)
            total_emissions = sum(r["emissions_usd"] for r in results)
            overbribed_count = sum(
                1 for r in results if "OVERBRIBED" in r["flags"]
            )
            efficient_count = sum(
                1
                for r in results
                if r["classification"] in ("HIGHLY_EFFICIENT", "EFFICIENT")
            )
        else:
            most_efficient_gauge = None
            best_voter_apr_gauge = None
            avg_efficiency = 0.0
            total_bribe = 0.0
            total_emissions = 0.0
            overbribed_count = 0
            efficient_count = 0

        aggregates = {
            "most_efficient_gauge": most_efficient_gauge,
            "best_voter_apr_gauge": best_voter_apr_gauge,
            "average_briber_efficiency": round(avg_efficiency, 6),
            "total_bribe_usd": round(total_bribe, 6),
            "total_emissions_usd": round(total_emissions, 6),
            "overall_efficiency_ratio": round(
                _safe_div(total_emissions, total_bribe), 6
            ),
            "overbribed_count": overbribed_count,
            "efficient_count": efficient_count,
        }

        ts = time.time()
        output: dict[str, Any] = {
            "results": results,
            "aggregates": aggregates,
            "timestamp": ts,
        }

        # ── Ring-buffer log ──────────────────────────────────────────
        write_log = config.get("write_log", True)
        if write_log:
            log_path = config.get("log_path", _LOG_PATH)
            try:
                _atomic_log(
                    log_path,
                    {
                        "timestamp": ts,
                        "gauge_count": len(results),
                        "aggregates": aggregates,
                    },
                )
            except Exception:
                pass  # advisory: never block caller

        return output

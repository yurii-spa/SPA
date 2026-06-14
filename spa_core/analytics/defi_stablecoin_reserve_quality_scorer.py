"""
MP-966: DeFiStablecoinReserveQualityScorer

Scores the *fundamental backing / reserve quality* of a stablecoin — distinct from
StablecoinDepegMonitor (which watches market price) and StablecoinRiskAssessor.
Answers: "how robust is the collateral behind this peg?" by composing
collateralization buffer, reserve composition quality, attestation freshness,
redemption mechanism strength, custodian diversification and regulatory status
into a single 0-100 backing_quality_score with an A-F grade.

No prior reserve/backing-quality module existed (gap confirmed v7.21).

Pure stdlib, read-only/advisory, all divisions guarded, atomic tempfile+os.replace
writes, ring-buffer 100 (`data/stablecoin_reserve_quality_log.json`).
"""

import json
import os
import time


class DeFiStablecoinReserveQualityScorer:
    """
    Per-stablecoin reserve/backing quality scoring.

    Input fields (per stablecoin dict):
      name, issuer,
      collateralization_ratio_pct      (total reserves / outstanding supply * 100)
      cash_pct, tbills_pct, crypto_pct, algo_pct, other_pct  (reserve composition, ~sum 100)
      attestation_age_days             (days since last attestation/audit)
      attestation_frequency_days       (cadence; lower = better)
      redemption_available (bool), redemption_fee_pct, redemption_time_days
      largest_custodian_pct            (share held by single largest custodian)
      regulated (bool)

    Composite backing_quality_score weights:
      composition 0.30, collateral buffer 0.25, attestation 0.15,
      redemption 0.15, custodian diversification 0.10, regulation 0.05
    """

    LOG_CAP = 100

    # Quality weight per reserve component (0-1, higher = safer backing)
    COMPONENT_QUALITY = {
        "tbills": 1.00,   # short-dated T-bills — highest quality
        "cash": 0.90,     # bank cash / deposits
        "other": 0.55,    # commercial paper / repo / misc
        "crypto": 0.45,   # overcollateralized crypto (volatile)
        "algo": 0.10,     # algorithmic / endogenous — lowest quality
    }

    WEIGHTS = {
        "composition": 0.30,
        "buffer": 0.25,
        "attestation": 0.15,
        "redemption": 0.15,
        "custodian": 0.10,
        "regulation": 0.05,
    }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(self, stablecoins: list, config: dict = None) -> dict:
        if config is None:
            config = {}

        results = [self._score_one(s) for s in stablecoins]
        aggregates = self._compute_aggregates(results)

        output = {
            "stablecoins": results,
            "aggregates": aggregates,
            "stablecoin_count": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if config.get("write_log", False):
            self._write_log(output, config.get("data_dir", "data"))

        return output

    # ------------------------------------------------------------------ #
    # Per-stablecoin scoring
    # ------------------------------------------------------------------ #

    def _score_one(self, s: dict) -> dict:
        name = s.get("name", "unknown")
        issuer = s.get("issuer", "unknown")

        collat = float(s.get("collateralization_ratio_pct", 0.0))
        cash = max(0.0, float(s.get("cash_pct", 0.0)))
        tbills = max(0.0, float(s.get("tbills_pct", 0.0)))
        crypto = max(0.0, float(s.get("crypto_pct", 0.0)))
        algo = max(0.0, float(s.get("algo_pct", 0.0)))
        other = max(0.0, float(s.get("other_pct", 0.0)))

        attest_age = float(s.get("attestation_age_days", 9999.0))
        attest_freq = float(s.get("attestation_frequency_days", 90.0))

        redemption_available = bool(s.get("redemption_available", False))
        redemption_fee = float(s.get("redemption_fee_pct", 0.0))
        redemption_time = float(s.get("redemption_time_days", 0.0))

        largest_custodian = float(s.get("largest_custodian_pct", 100.0))
        regulated = bool(s.get("regulated", False))

        comp_total = cash + tbills + crypto + algo + other

        # ── Composition quality (0-100): weighted average of component qualities ──
        if comp_total > 0:
            composition_score = 100.0 * (
                tbills * self.COMPONENT_QUALITY["tbills"]
                + cash * self.COMPONENT_QUALITY["cash"]
                + other * self.COMPONENT_QUALITY["other"]
                + crypto * self.COMPONENT_QUALITY["crypto"]
                + algo * self.COMPONENT_QUALITY["algo"]
            ) / comp_total
        else:
            composition_score = 0.0

        # ── Collateral buffer (0-100): how far above 100% backing ──
        collateral_buffer_pct = collat - 100.0
        # 100% -> 60, each +1pp buffer adds 4 up to 100; below 100% drops fast
        if collat <= 0:
            buffer_score = 0.0
        elif collat >= 100.0:
            buffer_score = min(100.0, 60.0 + collateral_buffer_pct * 4.0)
        else:
            # undercollateralized: 100% -> 60, 90% -> 12, 0% -> ~ -ve clamped 0
            buffer_score = max(0.0, 60.0 - (100.0 - collat) * 5.0)

        # ── Attestation freshness (0-100) ──
        attestation_score = self._attestation_score(attest_age, attest_freq)

        # ── Redemption strength (0-100) ──
        redemption_score = self._redemption_score(
            redemption_available, redemption_fee, redemption_time
        )

        # ── Custodian diversification (0-100): inverse of single-custodian share ──
        custodian_score = max(0.0, min(100.0, (100.0 - largest_custodian) * (100.0 / 70.0)))

        # ── Regulation (0-100) ──
        regulation_score = 100.0 if regulated else 40.0

        # ── Composite ──
        w = self.WEIGHTS
        backing_quality_score = (
            composition_score * w["composition"]
            + buffer_score * w["buffer"]
            + attestation_score * w["attestation"]
            + redemption_score * w["redemption"]
            + custodian_score * w["custodian"]
            + regulation_score * w["regulation"]
        )
        backing_quality_score = max(0.0, min(100.0, backing_quality_score))

        grade = self._grade(backing_quality_score)
        classification = self._classify(collat, backing_quality_score, algo, comp_total)
        flags = self._flags(
            collat, algo, crypto, comp_total, attest_age, attest_freq,
            redemption_available, redemption_fee, largest_custodian, regulated,
        )

        return {
            "name": name,
            "issuer": issuer,
            "collateralization_ratio_pct": round(collat, 4),
            "collateral_buffer_pct": round(collateral_buffer_pct, 4),
            "composition_score": round(composition_score, 4),
            "buffer_score": round(buffer_score, 4),
            "attestation_score": round(attestation_score, 4),
            "redemption_score": round(redemption_score, 4),
            "custodian_score": round(custodian_score, 4),
            "regulation_score": round(regulation_score, 4),
            "backing_quality_score": round(backing_quality_score, 4),
            "grade": grade,
            "classification": classification,
            "flags": flags,
        }

    # ------------------------------------------------------------------ #
    # Sub-scores
    # ------------------------------------------------------------------ #

    def _attestation_score(self, age_days: float, freq_days: float) -> float:
        """Fresh, frequent attestations score high; stale ones decay toward 0."""
        if age_days < 0:
            age_days = 0.0
        # Freshness: full marks if age <= freq, linear decay to 0 at 4x freq.
        ref = max(freq_days, 1.0)
        if age_days <= ref:
            freshness = 100.0
        else:
            freshness = max(0.0, 100.0 * (1.0 - (age_days - ref) / (3.0 * ref)))
        # Cadence bonus/penalty: monthly (<=30d) cadence is ideal.
        if freq_days <= 30.0:
            cadence = 100.0
        elif freq_days <= 90.0:
            cadence = 80.0
        elif freq_days <= 180.0:
            cadence = 55.0
        else:
            cadence = 30.0
        return 0.7 * freshness + 0.3 * cadence

    def _redemption_score(self, available: bool, fee_pct: float, time_days: float) -> float:
        if not available:
            return 0.0
        score = 100.0
        # Fee penalty: each 0.1% fee removes ~10 points.
        score -= max(0.0, fee_pct) * 100.0
        # Time penalty: instant = no penalty, longer settlement penalised.
        if time_days > 1.0:
            score -= min(40.0, (time_days - 1.0) * 8.0)
        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------ #
    # Grade / classification / flags
    # ------------------------------------------------------------------ #

    def _grade(self, score: float) -> str:
        if score >= 90.0:
            return "A"
        if score >= 75.0:
            return "B"
        if score >= 60.0:
            return "C"
        if score >= 45.0:
            return "D"
        return "F"

    def _classify(self, collat: float, score: float, algo: float, comp_total: float) -> str:
        if comp_total <= 0 and collat <= 0:
            return "INSUFFICIENT_DATA"
        if collat < 100.0:
            return "UNDERCOLLATERALIZED"
        if comp_total > 0 and (algo / comp_total) * 100.0 >= 50.0:
            return "WEAK"
        if score >= 85.0:
            return "FULLY_BACKED"
        if score >= 70.0:
            return "WELL_BACKED"
        if score >= 55.0:
            return "ADEQUATE"
        return "WEAK"

    def _flags(
        self, collat, algo, crypto, comp_total, attest_age, attest_freq,
        redemption_available, redemption_fee, largest_custodian, regulated,
    ) -> list:
        flags = []
        if comp_total <= 0:
            flags.append("INSUFFICIENT_DATA")
        if collat < 100.0:
            flags.append("UNDERCOLLATERALIZED")
        if comp_total > 0 and (algo / comp_total) * 100.0 >= 25.0:
            flags.append("ALGO_DEPENDENT")
        if comp_total > 0 and (crypto / comp_total) * 100.0 >= 60.0:
            flags.append("CRYPTO_HEAVY")
        if attest_age > 3.0 * max(attest_freq, 1.0):
            flags.append("STALE_ATTESTATION")
        if not redemption_available:
            flags.append("NO_REDEMPTION")
        if redemption_fee >= 0.5:
            flags.append("HIGH_REDEMPTION_FEE")
        if largest_custodian >= 60.0:
            flags.append("CUSTODIAN_CONCENTRATION")
        if not regulated:
            flags.append("UNREGULATED")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_backed": None,
                "worst_backed": None,
                "average_backing_quality_score": None,
                "undercollateralized_count": 0,
                "algo_dependent_count": 0,
            }

        best = max(results, key=lambda r: r["backing_quality_score"])
        worst = min(results, key=lambda r: r["backing_quality_score"])
        avg = sum(r["backing_quality_score"] for r in results) / len(results)
        under = sum(1 for r in results if "UNDERCOLLATERALIZED" in r["flags"])
        algo = sum(1 for r in results if "ALGO_DEPENDENT" in r["flags"])

        return {
            "best_backed": {
                "name": best["name"],
                "backing_quality_score": best["backing_quality_score"],
                "grade": best["grade"],
            },
            "worst_backed": {
                "name": worst["name"],
                "backing_quality_score": worst["backing_quality_score"],
                "grade": worst["grade"],
            },
            "average_backing_quality_score": round(avg, 4),
            "undercollateralized_count": under,
            "algo_dependent_count": algo,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "stablecoin_reserve_quality_log.json")

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        agg = result.get("aggregates", {})
        log.append({
            "timestamp": result.get("timestamp", ""),
            "stablecoin_count": result.get("stablecoin_count", 0),
            "average_backing_quality_score": agg.get("average_backing_quality_score"),
            "undercollateralized_count": agg.get("undercollateralized_count", 0),
            "algo_dependent_count": agg.get("algo_dependent_count", 0),
        })

        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)

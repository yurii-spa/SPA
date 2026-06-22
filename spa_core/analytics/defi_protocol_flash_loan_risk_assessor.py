"""
MP-1008: DeFiProtocolFlashLoanRiskAssessor
Evaluates flash loan attack risk for DeFi protocols.
Pure stdlib, read-only analytics, atomic ring-buffer log.
"""

from __future__ import annotations

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "flash_loan_risk_log.json")
LOG_CAP = 100

RISK_LABELS = {
    "FLASH_LOAN_SAFE": "Flash Loan Safe",
    "LOW_RISK": "Low Risk",
    "MODERATE_RISK": "Moderate Risk",
    "HIGH_RISK": "High Risk",
    "CRITICAL": "Critical",
}

FLAGS = {
    "SPOT_ORACLE_EXPOSED": "Spot oracle without TWAP – price manipulation window",
    "GOVERNANCE_ATTACK_VECTOR": "Governance vote executable in single block",
    "FLASH_LOAN_PROVIDER": "Protocol provides flash loans – double risk exposure",
    "REENTRANCY_PROTECTED": "Reentrancy guard in place",
    "HISTORICAL_EXPLOIT": "Protocol suffered at least one flash-loan exploit",
    "HIGH_REVENUE_DEPENDENCY": "Flash loan fees exceed 30 % of total protocol fees",
}


class DeFiProtocolFlashLoanRiskAssessor:
    """Assess flash-loan attack risk across a portfolio of DeFi protocols."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self, protocols: list[dict], config: dict) -> dict:
        """
        Parameters
        ----------
        protocols:
            List of protocol dicts.  Required keys per protocol:
              name, category, flash_loan_available, flash_loan_fee_bps,
              total_flash_loan_volume_30d_usd, historical_flash_loan_attacks,
              amount_lost_to_flash_loans_usd, oracle_type, twap_period_minutes,
              single_block_price_manipulation_possible, reentrancy_guard,
              governance_attack_via_flash_loan_possible,
              max_single_flash_loan_as_pct_tvl, tvl_usd,
              total_protocol_fees_30d_usd (optional, 0 if omitted)
        config:
            Optional overrides, e.g. risk_free_rate_pct, high_revenue_threshold_pct.

        Returns
        -------
        dict  with keys: protocols (list of assessed results), aggregates
        """
        if not isinstance(protocols, list):
            raise TypeError("protocols must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        risk_free_rate = float(config.get("risk_free_rate_pct", 4.0))
        high_rev_threshold = float(config.get("high_revenue_threshold_pct", 30.0))
        write_log = bool(config.get("write_log", False))

        assessed: list[dict] = []
        for p in protocols:
            assessed.append(self._assess_protocol(p, risk_free_rate, high_rev_threshold))

        aggregates = self._aggregate(assessed)
        result = {"protocols": assessed, "aggregates": aggregates}

        if write_log:
            self._write_log(result)

        return result

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------

    def _assess_protocol(self, p: dict, risk_free_rate: float, high_rev_threshold: float) -> dict:
        name = str(p.get("name", "unknown"))
        category = str(p.get("category", "lending"))
        fl_available = bool(p.get("flash_loan_available", False))
        fl_fee_bps = float(p.get("flash_loan_fee_bps", 0))
        fl_volume = float(p.get("total_flash_loan_volume_30d_usd", 0))
        hist_attacks = int(p.get("historical_flash_loan_attacks", 0))
        amount_lost = float(p.get("amount_lost_to_flash_loans_usd", 0))
        oracle_type = str(p.get("oracle_type", "chainlink_twap"))
        twap_min = float(p.get("twap_period_minutes", 0))
        single_block_manip = bool(p.get("single_block_price_manipulation_possible", False))
        reentrancy = bool(p.get("reentrancy_guard", True))
        gov_attack = bool(p.get("governance_attack_via_flash_loan_possible", False))
        max_loan_pct = float(p.get("max_single_flash_loan_as_pct_tvl", 0))
        tvl = float(p.get("tvl_usd", 1))  # avoid division by zero
        total_fees = float(p.get("total_protocol_fees_30d_usd", 0))

        # ---- derived booleans -------------------------------------------
        is_spot_oracle = oracle_type in ("uniswap_spot", "manual") or (
            oracle_type not in ("chainlink_twap", "pyth", "band") and twap_min == 0
        )
        # If oracle is TWAP-based but TWAP period is very short (<5 min), treat as spot
        if oracle_type == "chainlink_twap" and 0 < twap_min < 5:
            is_spot_oracle = True

        # ---- component scores -------------------------------------------
        # attack_surface_score 0-100
        spot_component = 40 if (is_spot_oracle or single_block_manip) else 0
        gov_component = 30 if gov_attack else 0
        reent_component = 20 if not reentrancy else 0
        high_loan_component = 10 if max_loan_pct > 50 else (5 if max_loan_pct > 25 else 0)
        attack_surface_score = float(min(100.0, spot_component + gov_component + reent_component + high_loan_component))

        # historical_loss_ratio  (lost / tvl * 100), capped 0-100
        if tvl > 0:
            historical_loss_ratio = min(100.0, (amount_lost / tvl) * 100.0)
        else:
            historical_loss_ratio = 0.0

        # fee_deterrent_score  0-100
        if fl_fee_bps >= 50:
            fee_deterrent_score = 60.0
        elif fl_fee_bps >= 20:
            fee_deterrent_score = 30.0
        elif fl_fee_bps >= 5:
            fee_deterrent_score = 10.0
        else:
            fee_deterrent_score = 0.0

        # flash_loan_revenue_pct  (proportion of protocol fees from flash loan fees)
        fl_fee_revenue = fl_volume * (fl_fee_bps / 10_000.0) if fl_available else 0.0
        if total_fees > 0:
            flash_loan_revenue_pct = min(100.0, (fl_fee_revenue / total_fees) * 100.0)
        else:
            flash_loan_revenue_pct = 0.0

        # composite_risk_score
        hist_component = min(100.0, historical_loss_ratio)
        composite_risk_score = (
            attack_surface_score * 0.6
            - fee_deterrent_score * 0.2
            + hist_component * 0.2
        )
        composite_risk_score = max(0.0, min(100.0, composite_risk_score))

        # ---- risk label -------------------------------------------------
        label = self._compute_label(
            is_spot_oracle=is_spot_oracle,
            reentrancy=reentrancy,
            gov_attack=gov_attack,
            attack_surface_score=attack_surface_score,
            hist_attacks=hist_attacks,
            composite_risk_score=composite_risk_score,
        )

        # ---- flags -------------------------------------------------------
        flags: list[str] = []
        if is_spot_oracle or single_block_manip:
            flags.append("SPOT_ORACLE_EXPOSED")
        if gov_attack:
            flags.append("GOVERNANCE_ATTACK_VECTOR")
        if fl_available:
            flags.append("FLASH_LOAN_PROVIDER")
        if reentrancy:
            flags.append("REENTRANCY_PROTECTED")
        if hist_attacks > 0:
            flags.append("HISTORICAL_EXPLOIT")
        if flash_loan_revenue_pct > high_rev_threshold:
            flags.append("HIGH_REVENUE_DEPENDENCY")

        return {
            "name": name,
            "category": category,
            "attack_surface_score": round(attack_surface_score, 2),
            "historical_loss_ratio": round(historical_loss_ratio, 4),
            "fee_deterrent_score": round(fee_deterrent_score, 2),
            "flash_loan_revenue_pct": round(flash_loan_revenue_pct, 4),
            "composite_risk_score": round(composite_risk_score, 4),
            "risk_label": label,
            "flags": flags,
            # pass-through
            "fl_available": fl_available,
            "hist_attacks": hist_attacks,
            "amount_lost_usd": amount_lost,
            "tvl_usd": tvl,
        }

    @staticmethod
    def _compute_label(
        is_spot_oracle: bool,
        reentrancy: bool,
        gov_attack: bool,
        attack_surface_score: float,
        hist_attacks: int,
        composite_risk_score: float,
    ) -> str:
        # CRITICAL: historical attack AND spot oracle AND governance vuln
        if hist_attacks > 0 and is_spot_oracle and gov_attack:
            return "CRITICAL"

        # HIGH_RISK: attack_surface > 60 OR more than 1 historical attack
        if attack_surface_score > 60 or hist_attacks > 1:
            return "HIGH_RISK"

        # FLASH_LOAN_SAFE: no spot oracle AND reentrancy protected AND no gov vuln
        if (not is_spot_oracle) and reentrancy and (not gov_attack):
            return "FLASH_LOAN_SAFE"

        # Composite score bucketing
        if composite_risk_score <= 10:
            return "FLASH_LOAN_SAFE"
        elif composite_risk_score <= 25:
            return "LOW_RISK"
        elif composite_risk_score <= 50:
            return "MODERATE_RISK"
        else:
            return "HIGH_RISK"

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(assessed: list[dict]) -> dict:
        if not assessed:
            return {
                "safest": None,
                "riskiest": None,
                "total_historical_losses_usd": 0.0,
                "critical_count": 0,
                "safe_count": 0,
                "total_protocols": 0,
            }

        safest = min(assessed, key=lambda x: x["composite_risk_score"])
        riskiest = max(assessed, key=lambda x: x["composite_risk_score"])

        total_losses = sum(p["amount_lost_usd"] for p in assessed)
        critical_count = sum(1 for p in assessed if p["risk_label"] == "CRITICAL")
        safe_count = sum(1 for p in assessed if p["risk_label"] == "FLASH_LOAN_SAFE")

        return {
            "safest": safest["name"],
            "riskiest": riskiest["name"],
            "total_historical_losses_usd": round(total_losses, 2),
            "critical_count": critical_count,
            "safe_count": safe_count,
            "total_protocols": len(assessed),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _write_log(self, result: dict) -> None:
        log_path = os.path.abspath(LOG_FILE)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        # Load existing
        entries: list[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                entries = []

        # Append new entry
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "total_protocols": result["aggregates"]["total_protocols"],
            "critical_count": result["aggregates"]["critical_count"],
            "safe_count": result["aggregates"]["safe_count"],
            "total_historical_losses_usd": result["aggregates"]["total_historical_losses_usd"],
            "riskiest": result["aggregates"]["riskiest"],
        }
        entries.append(entry)

        # Trim to cap
        if len(entries) > LOG_CAP:
            entries = entries[-LOG_CAP:]

        # Atomic write
        dir_path = os.path.dirname(log_path)
        atomic_save(entries, str(log_path))

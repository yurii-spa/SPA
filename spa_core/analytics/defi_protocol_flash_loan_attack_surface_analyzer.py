"""
MP-1060: DeFiProtocolFlashLoanAttackSurfaceAnalyzer
Evaluates the economic attack surface and oracle vulnerability that enables
flash-loan-based exploits on DeFi protocols.

Pure stdlib, read-only / advisory, atomic ring-buffer log (cap 100).
LLM_FORBIDDEN: no AI calls in this module.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_THIS_DIR, "..", "..")
LOG_FILE = os.path.normpath(
    os.path.join(_REPO_ROOT, "data", "flash_loan_attack_surface_log.json")
)
LOG_CAP = 100

# Oracle type base vulnerability scores (0–100)
_ORACLE_BASE: Dict[str, float] = {
    "spot":      90.0,   # trivially manipulable in one block
    "internal":  72.0,   # protocol-internal price, no external check
    "twap_1h":   28.0,   # 1-hour TWAP requires sustained manipulation
    "chainlink": 12.0,   # decentralised aggregator, hardest to manipulate
}
_ORACLE_DEFAULT = 55.0   # unknown oracle type


# Risk label thresholds (applied to flash_loan_risk_score)
_LABEL_THRESHOLDS = [
    (80.0, "CRITICAL_EXPOSURE"),
    (62.0, "HIGH_RISK"),
    (42.0, "MODERATE_RISK"),
    (22.0, "LOW_RISK"),
    (0.0,  "FLASH_LOAN_RESISTANT"),
]

# Composite score weights
_W_PROFIT    = 0.25   # attack profitability
_W_ORACLE    = 0.30   # oracle vulnerability
_W_REENTRY   = 0.20   # reentrancy exposure
_W_AUDIT     = 0.15   # audit deficit
_W_HISTORY   = 0.10   # historical exploit record


class DeFiProtocolFlashLoanAttackSurfaceAnalyzer:
    """
    Analyse the flash-loan attack surface of a single DeFi protocol.

    Usage
    -----
    analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()
    result   = analyzer.analyze(protocol_data)

    ``protocol_data`` keys
    ----------------------
    protocol_name               str
    tvl_usd                     float  – total value locked in USD
    single_block_borrowable_usd float  – max borrowable in one block (flash loan)
    price_oracle_type           str    – "spot" | "twap_1h" | "chainlink" | "internal"
    reentrancy_guards           bool   – protocol has reentrancy protection
    has_price_manipulation_check bool  – on-chain price sanity checks present
    audit_count                 int    – number of completed security audits
    days_since_last_audit       float  – calendar days since most recent audit
    historical_flash_loan_attacks int  – number of past flash-loan exploits
    total_value_lost_usd        float  – cumulative USD lost to flash-loan attacks

    Result keys
    -----------
    protocol_name               str
    attack_profitability_score  float  0–100 (higher = more profitable to attack)
    oracle_vulnerability_score  float  0–100
    flash_loan_risk_score       float  0–100 (composite)
    risk_label                  str    one of the five label constants above
    _breakdown                  dict   sub-scores for transparency
    timestamp                   float  unix epoch
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, data: Dict[str, Any], *, write_log: bool = False) -> Dict[str, Any]:
        """
        Compute all scores for a single protocol snapshot.

        Parameters
        ----------
        data       : protocol snapshot dict (required keys listed in class docstring)
        write_log  : if True, append result to ring-buffer log atomically

        Returns
        -------
        dict with keys: protocol_name, attack_profitability_score,
            oracle_vulnerability_score, flash_loan_risk_score, risk_label,
            _breakdown, timestamp
        """
        self._validate(data)

        name      = str(data["protocol_name"])
        tvl       = float(data["tvl_usd"])
        borrowable = float(data["single_block_borrowable_usd"])
        oracle    = str(data["price_oracle_type"]).lower()
        reentry   = bool(data["reentrancy_guards"])
        manip_chk = bool(data["has_price_manipulation_check"])
        audits    = int(data["audit_count"])
        days_aud  = float(data["days_since_last_audit"])
        attacks   = int(data["historical_flash_loan_attacks"])
        lost      = float(data["total_value_lost_usd"])

        profit_score  = self._attack_profitability_score(tvl, borrowable)
        oracle_score  = self._oracle_vulnerability_score(oracle, manip_chk)
        reentry_score = self._reentrancy_score(reentry)
        audit_score   = self._audit_deficit_score(audits, days_aud)
        hist_score    = self._historical_score(attacks, lost)

        composite = (
            profit_score  * _W_PROFIT
            + oracle_score  * _W_ORACLE
            + reentry_score * _W_REENTRY
            + audit_score   * _W_AUDIT
            + hist_score    * _W_HISTORY
        )
        composite = _clamp(composite, 0.0, 100.0)

        label = self._label(composite)

        result: Dict[str, Any] = {
            "protocol_name":               name,
            "attack_profitability_score":  round(profit_score,  2),
            "oracle_vulnerability_score":  round(oracle_score,  2),
            "flash_loan_risk_score":       round(composite,     2),
            "risk_label":                  label,
            "_breakdown": {
                "profit_score":  round(profit_score,  2),
                "oracle_score":  round(oracle_score,  2),
                "reentry_score": round(reentry_score, 2),
                "audit_score":   round(audit_score,   2),
                "hist_score":    round(hist_score,    2),
            },
            "timestamp": time.time(),
        }

        if write_log:
            _append_log(LOG_FILE, result, LOG_CAP)

        return result

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _attack_profitability_score(self, tvl: float, borrowable: float) -> float:
        """
        Economic profitability of staging a flash-loan attack.

        Factors
        -------
        - Borrow ratio: what fraction of TVL can be borrowed in one block.
          High ratio → higher leverage → more profitable.
        - TVL scale: larger pools have more absolute value at risk.
        """
        if tvl <= 0:
            borrow_ratio = 1.0
        else:
            borrow_ratio = _clamp(borrowable / tvl, 0.0, 1.0)

        # Sigmoid-like scale: $10M → 30 pts, $100M → 50, $1B → 65, $10B → 75
        if tvl <= 0:
            tvl_pts = 0.0
        else:
            tvl_pts = _clamp(15.0 * math.log10(max(tvl, 1.0) / 1_000_000.0 + 1.0), 0.0, 40.0)

        borrow_pts = borrow_ratio * 60.0
        score = borrow_pts * 0.65 + tvl_pts * 0.35 + borrow_ratio * tvl_pts * 0.10
        return _clamp(score, 0.0, 100.0)

    def _oracle_vulnerability_score(self, oracle: str, manip_chk: bool) -> float:
        """
        How vulnerable is the price oracle to flash-loan manipulation?
        """
        base = _ORACLE_BASE.get(oracle, _ORACLE_DEFAULT)
        # On-chain price manipulation check reduces vulnerability
        if manip_chk:
            base -= 18.0
        else:
            base += 12.0
        return _clamp(base, 0.0, 100.0)

    def _reentrancy_score(self, guards: bool) -> float:
        """Missing reentrancy guards = full exposure."""
        return 0.0 if guards else 100.0

    def _audit_deficit_score(self, count: int, days: float) -> float:
        """
        Higher = more audit deficit.

        Zero audits → 100.  Each audit reduces score; staleness adds back risk.
        """
        if count <= 0:
            base = 100.0
        else:
            base = _clamp(100.0 - count * 20.0, 0.0, 100.0)

        # Staleness penalty
        if days > 365:
            base = _clamp(base + 35.0, 0.0, 100.0)
        elif days > 180:
            base = _clamp(base + 18.0, 0.0, 100.0)
        elif days > 90:
            base = _clamp(base + 8.0, 0.0, 100.0)

        return _clamp(base, 0.0, 100.0)

    def _historical_score(self, attacks: int, lost_usd: float) -> float:
        """
        Track record of past flash-loan exploits.
        """
        if attacks <= 0 and lost_usd <= 0:
            return 0.0

        attack_pts = _clamp(attacks * 25.0, 0.0, 75.0)

        # Large losses add risk signal
        if lost_usd >= 50_000_000:
            loss_pts = 25.0
        elif lost_usd >= 10_000_000:
            loss_pts = 18.0
        elif lost_usd >= 1_000_000:
            loss_pts = 10.0
        else:
            loss_pts = 5.0 if lost_usd > 0 else 0.0

        return _clamp(attack_pts + loss_pts, 0.0, 100.0)

    def _label(self, score: float) -> str:
        for threshold, label in _LABEL_THRESHOLDS:
            if score >= threshold:
                return label
        return "FLASH_LOAN_RESISTANT"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, data: Dict[str, Any]) -> None:
        required = [
            "protocol_name", "tvl_usd", "single_block_borrowable_usd",
            "price_oracle_type", "reentrancy_guards", "has_price_manipulation_check",
            "audit_count", "days_since_last_audit",
            "historical_flash_loan_attacks", "total_value_lost_usd",
        ]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing required keys: {missing}")
        if float(data["tvl_usd"]) < 0:
            raise ValueError("tvl_usd must be non-negative")
        if float(data["single_block_borrowable_usd"]) < 0:
            raise ValueError("single_block_borrowable_usd must be non-negative")
        if int(data["audit_count"]) < 0:
            raise ValueError("audit_count must be non-negative")
        if float(data["days_since_last_audit"]) < 0:
            raise ValueError("days_since_last_audit must be non-negative")
        if int(data["historical_flash_loan_attacks"]) < 0:
            raise ValueError("historical_flash_loan_attacks must be non-negative")
        if float(data["total_value_lost_usd"]) < 0:
            raise ValueError("total_value_lost_usd must be non-negative")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _append_log(path: str, entry: Dict[str, Any], cap: int) -> None:
    """Atomically append entry to ring-buffer JSON log."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            log: list = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]

    dir_ = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(log, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# CLI entry-point (informational only)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sample = {
        "protocol_name":               "ExampleProtocol",
        "tvl_usd":                     50_000_000.0,
        "single_block_borrowable_usd": 40_000_000.0,
        "price_oracle_type":           "spot",
        "reentrancy_guards":           False,
        "has_price_manipulation_check": False,
        "audit_count":                 1,
        "days_since_last_audit":       200.0,
        "historical_flash_loan_attacks": 1,
        "total_value_lost_usd":        5_000_000.0,
    }

    analyzer = DeFiProtocolFlashLoanAttackSurfaceAnalyzer()
    result = analyzer.analyze(sample)
    print(json.dumps(result, indent=2))
    sys.exit(0)

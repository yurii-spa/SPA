#!/usr/bin/env python3
"""DeFi Protocol Smart Contract Upgrade Risk Analyzer (SPA-V784 / MP-1093).

Evaluates the governance and technical risk of a protocol's smart contract
upgrade mechanism. Proxy patterns without timelock = high risk; immutable
contracts = no upgrade risk but no bug-fix path.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/smart_contract_upgrade_risk_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Upgrade risk label logic
------------------------
  1. not upgradeable                                          -> IMMUTABLE_SAFE
  2. upgradeable AND timelock >= 72h AND multisig AND audits >= 2
                                                             -> WELL_GOVERNED
  3. upgradeable AND timelock >= 24h AND (multisig OR audits >= 1)
                                                             -> MODERATE_RISK
  4. upgradeable AND timelock > 0                            -> HIGH_RISK
  5. upgradeable AND timelock == 0                           -> CRITICAL_UPGRADE_RISK

Timelock adequacy (based on timelock_hours):
  0        -> NONE
  1-23     -> WEAK
  24-71    -> ADEQUATE
  >= 72    -> STRONG

Governance decentralisation score (0-100, 100 = most decentralised):
  If not upgradeable: 100.
  Otherwise (sum, clamped to 100):
    - Multisig component (max 40):
        * required:                                    +20
        * required AND threshold >= 2:                 +10
        * required AND threshold/signers >= 0.5:       +10
    - Timelock component (max 30):
        * >= 72h:  +30
        * >= 24h:  +20
        * >  0h:   +10
    - Audit component (max 25):
        * min(audit_count * 8, 25)
    - Stability bonus (max 5):
        * +5 if upgrade_history_count > 0 AND days_since_last_upgrade > 180

Upgrade risk score (0-100, 0 = safe, 100 = critical):
  If not upgradeable: 0.
  Start at 100:
    - Timelock reduction (max -30):
        * >= 72h: -30
        * >= 24h: -20
        * >  0h:  -10
    - Multisig reduction (max -30):
        * required:                                    -15
        * required AND threshold >= 2:                  -8
        * required AND threshold/signers >= 0.5:        -7
    - Audit reduction (max -20):
        * -min(audit_count * 8, 20)
    - Frequency penalty: upgrade_history_count > 5:    +10
    - Recency penalty: 0 < days_since_last_upgrade < 30: +5
    Clamped [0, 100].

CLI
---
  python3 -m spa_core.analytics.protocol_defi_smart_contract_upgrade_risk_analyzer --check
  python3 -m spa_core.analytics.protocol_defi_smart_contract_upgrade_risk_analyzer --run
  python3 -m spa_core.analytics.protocol_defi_smart_contract_upgrade_risk_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "smart_contract_upgrade_risk_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "protocol_defi_smart_contract_upgrade_risk_analyzer"
MP_TAG = "MP-1093"

# Timelock adequacy thresholds (hours)
TIMELOCK_STRONG_H: int = 72
TIMELOCK_ADEQUATE_H: int = 24

# Governance score component maximums
GOV_MULTISIG_BASE: int = 20
GOV_MULTISIG_THRESHOLD_BONUS: int = 10
GOV_MULTISIG_RATIO_BONUS: int = 10
GOV_MULTISIG_MAX: int = GOV_MULTISIG_BASE + GOV_MULTISIG_THRESHOLD_BONUS + GOV_MULTISIG_RATIO_BONUS  # 40
GOV_TIMELOCK_MAX: int = 30
GOV_AUDIT_PER_UNIT: int = 8
GOV_AUDIT_MAX: int = 25
GOV_STABILITY_BONUS: int = 5
GOV_STABILITY_MIN_DAYS: int = 180

# Upgrade risk score reductions
RISK_TIMELOCK_STRONG_REDUCTION: int = 30
RISK_TIMELOCK_ADEQUATE_REDUCTION: int = 20
RISK_TIMELOCK_WEAK_REDUCTION: int = 10
RISK_MULTISIG_BASE_REDUCTION: int = 15
RISK_MULTISIG_THRESHOLD_REDUCTION: int = 8
RISK_MULTISIG_RATIO_REDUCTION: int = 7
RISK_AUDIT_PER_UNIT: int = 8
RISK_AUDIT_MAX_REDUCTION: int = 20
RISK_FREQUENCY_PENALTY: int = 10
RISK_FREQUENCY_THRESHOLD: int = 5        # upgrade_history_count > this
RISK_RECENCY_PENALTY: int = 5
RISK_RECENCY_MAX_DAYS: int = 30          # days_since_last_upgrade < this (and > 0)

# Multisig governance threshold ratio (threshold/signers >= this => bonus)
MULTISIG_RATIO_MIN: float = 0.5

log = logging.getLogger("spa.analytics.protocol_defi_smart_contract_upgrade_risk_analyzer")


# ---------------------------------------------------------------------------
# Core computation helpers (public for unit testing)
# ---------------------------------------------------------------------------


def timelock_adequacy(timelock_hours: int) -> str:
    """Classify timelock quality.

    Rules:
      timelock_hours == 0        -> NONE
      0 < timelock_hours < 24   -> WEAK
      24 <= timelock_hours < 72 -> ADEQUATE
      >= 72                     -> STRONG
    """
    if timelock_hours <= 0:
        return "NONE"
    if timelock_hours < TIMELOCK_ADEQUATE_H:
        return "WEAK"
    if timelock_hours < TIMELOCK_STRONG_H:
        return "ADEQUATE"
    return "STRONG"


def upgrade_risk_label(
    is_upgradeable: bool,
    timelock_hours: int,
    multisig_required: bool,
    audit_count: int,
) -> str:
    """Determine upgrade risk label using priority-ordered rules.

    Rules (evaluated in order):
      1. not upgradeable                                        -> IMMUTABLE_SAFE
      2. upgradeable AND timelock >= 72h AND multisig AND audits >= 2
                                                               -> WELL_GOVERNED
      3. upgradeable AND timelock >= 24h AND (multisig OR audits >= 1)
                                                               -> MODERATE_RISK
      4. upgradeable AND timelock > 0                          -> HIGH_RISK
      5. upgradeable AND timelock == 0                         -> CRITICAL_UPGRADE_RISK
    """
    if not is_upgradeable:
        return "IMMUTABLE_SAFE"
    if (
        timelock_hours >= TIMELOCK_STRONG_H
        and multisig_required
        and audit_count >= 2
    ):
        return "WELL_GOVERNED"
    if timelock_hours >= TIMELOCK_ADEQUATE_H and (multisig_required or audit_count >= 1):
        return "MODERATE_RISK"
    if timelock_hours > 0:
        return "HIGH_RISK"
    return "CRITICAL_UPGRADE_RISK"


def governance_decentralization_score(
    is_upgradeable: bool,
    has_timelock: bool,
    timelock_hours: int,
    multisig_required: bool,
    multisig_signers: int,
    multisig_threshold: int,
    audit_count: int,
    days_since_last_upgrade: int,
    upgrade_history_count: int,
) -> int:
    """Compute governance decentralisation score 0-100 (100 = most decentralised).

    If the contract is not upgradeable, returns 100 (no governance needed
    because the code cannot change).

    For upgradeable contracts, score is built from four components:
      1. Multisig (max 40)
      2. Timelock (max 30)
      3. Audits (max 25)
      4. Stability bonus (max 5)
    """
    if not is_upgradeable:
        return 100

    score = 0

    # Component 1: Multisig (max 40)
    if multisig_required:
        score += GOV_MULTISIG_BASE
        if multisig_threshold >= 2:
            score += GOV_MULTISIG_THRESHOLD_BONUS
        if multisig_signers > 0 and (multisig_threshold / multisig_signers) >= MULTISIG_RATIO_MIN:
            score += GOV_MULTISIG_RATIO_BONUS

    # Component 2: Timelock (max 30)
    if timelock_hours >= TIMELOCK_STRONG_H:
        score += GOV_TIMELOCK_MAX
    elif timelock_hours >= TIMELOCK_ADEQUATE_H:
        score += 20
    elif timelock_hours > 0:
        score += 10

    # Component 3: Audits (max 25)
    score += min(audit_count * GOV_AUDIT_PER_UNIT, GOV_AUDIT_MAX)

    # Component 4: Stability bonus (max 5)
    if upgrade_history_count > 0 and days_since_last_upgrade > GOV_STABILITY_MIN_DAYS:
        score += GOV_STABILITY_BONUS

    return min(100, score)


def upgrade_risk_score(
    is_upgradeable: bool,
    has_timelock: bool,
    timelock_hours: int,
    multisig_required: bool,
    multisig_signers: int,
    multisig_threshold: int,
    audit_count: int,
    days_since_last_upgrade: int,
    upgrade_history_count: int,
) -> int:
    """Compute upgrade risk score 0-100 (0 = safe, 100 = critical).

    If the contract is not upgradeable, returns 0 (no upgrade risk).

    For upgradeable contracts, starts at 100 and subtracts for good governance,
    then adds penalties for risky behaviour.
    """
    if not is_upgradeable:
        return 0

    score = 100

    # Timelock reductions (max -30)
    if timelock_hours >= TIMELOCK_STRONG_H:
        score -= RISK_TIMELOCK_STRONG_REDUCTION
    elif timelock_hours >= TIMELOCK_ADEQUATE_H:
        score -= RISK_TIMELOCK_ADEQUATE_REDUCTION
    elif timelock_hours > 0:
        score -= RISK_TIMELOCK_WEAK_REDUCTION

    # Multisig reductions (max -30)
    if multisig_required:
        score -= RISK_MULTISIG_BASE_REDUCTION
        if multisig_threshold >= 2:
            score -= RISK_MULTISIG_THRESHOLD_REDUCTION
        if multisig_signers > 0 and (multisig_threshold / multisig_signers) >= MULTISIG_RATIO_MIN:
            score -= RISK_MULTISIG_RATIO_REDUCTION

    # Audit reductions (max -20)
    score -= min(audit_count * RISK_AUDIT_PER_UNIT, RISK_AUDIT_MAX_REDUCTION)

    # Frequency penalty: many upgrades = more risk
    if upgrade_history_count > RISK_FREQUENCY_THRESHOLD:
        score += RISK_FREQUENCY_PENALTY

    # Recency penalty: very recent upgrade = less time to detect issues
    # days_since_last_upgrade == 0 means "never upgraded" — no penalty
    if 0 < days_since_last_upgrade < RISK_RECENCY_MAX_DAYS:
        score += RISK_RECENCY_PENALTY

    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# Main analysis function (module-level)
# ---------------------------------------------------------------------------


def analyze(
    is_upgradeable: bool,
    has_timelock: bool,
    timelock_hours: int,
    multisig_required: bool,
    multisig_signers: int,
    multisig_threshold: int,
    audit_count: int,
    days_since_last_upgrade: int,
    upgrade_history_count: int,
    protocol_name: str,
) -> Dict[str, Any]:
    """Evaluate smart contract upgrade risk for a single protocol.

    Parameters
    ----------
    is_upgradeable:
        Whether the protocol's contracts can be upgraded (proxy pattern).
    has_timelock:
        Whether a timelock contract exists (may differ from timelock_hours > 0).
    timelock_hours:
        Timelock delay in hours (0 if no timelock).
    multisig_required:
        Whether a multisig wallet is required to authorize upgrades.
    multisig_signers:
        Total number of multisig keys (N in M-of-N).
    multisig_threshold:
        Required signatures for upgrade approval (M in M-of-N).
    audit_count:
        Number of public third-party security audits conducted.
    days_since_last_upgrade:
        Days elapsed since the last contract upgrade (0 if never upgraded).
    upgrade_history_count:
        Total number of upgrades ever executed.
    protocol_name:
        Name of the protocol (e.g. "Aave", "Compound", "MakerDAO").

    Returns
    -------
    Dict with all computed outputs plus raw inputs and metadata.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    timelock_adeq = timelock_adequacy(timelock_hours)
    risk_label = upgrade_risk_label(
        is_upgradeable, timelock_hours, multisig_required, audit_count
    )
    gov_score = governance_decentralization_score(
        is_upgradeable, has_timelock, timelock_hours,
        multisig_required, multisig_signers, multisig_threshold,
        audit_count, days_since_last_upgrade, upgrade_history_count,
    )
    risk_score = upgrade_risk_score(
        is_upgradeable, has_timelock, timelock_hours,
        multisig_required, multisig_signers, multisig_threshold,
        audit_count, days_since_last_upgrade, upgrade_history_count,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "mp_tag": MP_TAG,
        "timestamp": timestamp,
        "protocol_name": str(protocol_name),
        # Raw inputs echoed
        "is_upgradeable": bool(is_upgradeable),
        "has_timelock": bool(has_timelock),
        "timelock_hours": int(timelock_hours),
        "multisig_required": bool(multisig_required),
        "multisig_signers": int(multisig_signers),
        "multisig_threshold": int(multisig_threshold),
        "audit_count": int(audit_count),
        "days_since_last_upgrade": int(days_since_last_upgrade),
        "upgrade_history_count": int(upgrade_history_count),
        # Computed outputs
        "governance_decentralization_score": gov_score,
        "upgrade_risk_score": risk_score,
        "timelock_adequacy": timelock_adeq,
        "upgrade_risk_label": risk_label,
    }


# ---------------------------------------------------------------------------
# Stateful class
# ---------------------------------------------------------------------------


class ProtocolDeFiSmartContractUpgradeRiskAnalyzer(BaseAnalytics):
    """Stateful analyzer that accumulates results into a ring-buffer log.

    Usage
    -----
    ::

        analyzer = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(data_dir="/path/to/data")
        result   = analyzer.analyze(
            is_upgradeable=True,
            has_timelock=True,
            timelock_hours=48,
            multisig_required=True,
            multisig_signers=5,
            multisig_threshold=3,
            audit_count=2,
            days_since_last_upgrade=180,
            upgrade_history_count=3,
            protocol_name="Aave",
        )
        label = result["upgrade_risk_label"]
        score = result["upgrade_risk_score"]
        analyzer.save()  # atomic ring-buffer append
    """

    OUTPUT_PATH = "data/smart_contract_upgrade_risk_log.json"

    def __init__(
        self,
        data_dir: Optional["Path | str"] = None,
        ring_cap: int = RING_BUFFER_CAP,
    ) -> None:
        super().__init__()
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._ring_cap = ring_cap
        self._last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """Returns last smart contract upgrade risk result as JSON-serializable dict."""
        return dict(self._last_result) if self._last_result else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        is_upgradeable: bool,
        has_timelock: bool,
        timelock_hours: int,
        multisig_required: bool,
        multisig_signers: int,
        multisig_threshold: int,
        audit_count: int,
        days_since_last_upgrade: int,
        upgrade_history_count: int,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Run upgrade risk analysis and cache the result for save()."""
        result = analyze(
            is_upgradeable=is_upgradeable,
            has_timelock=has_timelock,
            timelock_hours=timelock_hours,
            multisig_required=multisig_required,
            multisig_signers=multisig_signers,
            multisig_threshold=multisig_threshold,
            audit_count=audit_count,
            days_since_last_upgrade=days_since_last_upgrade,
            upgrade_history_count=upgrade_history_count,
            protocol_name=protocol_name,
        )
        self._last_result = result
        return result

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Return the result from the last analyze() call, or None."""
        return self._last_result

    def save(self) -> bool:
        """Atomically append last result to the ring-buffer log file.

        Returns True on success, False on any error (never raises).
        """
        if self._last_result is None:
            log.warning("save() called before analyze() — nothing to write")
            return False
        try:
            log_path = self._data_dir / LOG_FILENAME
            existing: List[Dict[str, Any]] = _load_json_list(log_path)
            existing.append(self._last_result)
            if len(existing) > self._ring_cap:
                existing = existing[-self._ring_cap:]
            _atomic_write(log_path, existing)
            log.info(
                "smart_contract_upgrade_risk_log written (%d entries)", len(existing)
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("save() failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path) -> List[Any]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="protocol_defi_smart_contract_upgrade_risk_analyzer",
        description="MP-1093 DeFi Protocol Smart Contract Upgrade Risk Analyzer",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print; do NOT write to disk (default)",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute, print, and atomically write last result to log file",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override default data/ directory path",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry-point — exit 0 always (pure advisory)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    write_mode: bool = args.run

    # Demo cases covering all risk label categories
    demo_cases = [
        {
            "protocol_name": "Uniswap V3",
            "is_upgradeable": False,
            "has_timelock": False,
            "timelock_hours": 0,
            "multisig_required": False,
            "multisig_signers": 0,
            "multisig_threshold": 0,
            "audit_count": 5,
            "days_since_last_upgrade": 0,
            "upgrade_history_count": 0,
        },
        {
            "protocol_name": "Aave V3",
            "is_upgradeable": True,
            "has_timelock": True,
            "timelock_hours": 168,     # 7 days
            "multisig_required": True,
            "multisig_signers": 6,
            "multisig_threshold": 4,
            "audit_count": 4,
            "days_since_last_upgrade": 200,
            "upgrade_history_count": 2,
        },
        {
            "protocol_name": "NewDeFi",
            "is_upgradeable": True,
            "has_timelock": False,
            "timelock_hours": 0,
            "multisig_required": False,
            "multisig_signers": 0,
            "multisig_threshold": 0,
            "audit_count": 0,
            "days_since_last_upgrade": 0,
            "upgrade_history_count": 0,
        },
        {
            "protocol_name": "MidTier",
            "is_upgradeable": True,
            "has_timelock": True,
            "timelock_hours": 48,
            "multisig_required": True,
            "multisig_signers": 5,
            "multisig_threshold": 3,
            "audit_count": 1,
            "days_since_last_upgrade": 90,
            "upgrade_history_count": 1,
        },
    ]

    analyzer = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(data_dir=data_dir)
    results = []
    for case in demo_cases:
        r = analyzer.analyze(**case)
        results.append(r)

    print(json.dumps(results, indent=2, ensure_ascii=False))

    if write_mode:
        ok = analyzer.save()
        status_str = "OK" if ok else "FAILED"
        print(f"[{SOURCE_NAME}] save: {status_str}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()

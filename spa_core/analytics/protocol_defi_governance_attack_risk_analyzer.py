#!/usr/bin/env python3
"""
MP-1059: ProtocolDeFiGovernanceAttackRiskAnalyzer — read-only / advisory.

Analyzes governance attack risk for DeFi protocols by computing:
  - attack_cost_vs_tvl_ratio  (attacker's acquisition cost relative to TVL)
  - governance_capture_score  (0–100; higher = more captured / at risk)
  - decentralization_score    (0–100; higher = more decentralized / safer)
  - attack_risk_label         (one of five labels)

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/governance_attack_risk_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Scoring formulas
----------------

attack_cost_vs_tvl_ratio
  Estimated cost to acquire a controlling governance stake (51% of circulating
  supply at market price) divided by TVL.

  attack_cost_usd      = governance_token_market_cap_usd * 0.51
  attack_cost_vs_tvl   = attack_cost_usd / tvl_usd   (0.0 if tvl_usd <= 0)

governance_capture_score  (0–100, higher = worse)
  Weighted sum of capture-risk factors:

  concentration_factor = token_concentration_top10_pct / 100          (0–1)
  timelock_factor      = max(0, 1 - timelock_hours / 168)             (0–1; 168h=1 week → safe)
  quorum_factor        = max(0, 1 - quorum_pct / 50)                  (0–1; 50%+ quorum → safe)
  participation_factor = max(0, 1 - voter_participation_pct / 50)     (0–1)
  guardian_factor      = 0 if has_guardian else 1                     (0 or 1)

  score = (
      concentration_factor * 35
    + timelock_factor       * 20
    + quorum_factor         * 15
    + participation_factor  * 15
    + guardian_factor       * 15
  )
  Clamped to [0, 100].

decentralization_score  (0–100, higher = better)
  Based on attack_cost_vs_tvl, multisig threshold ratio, and timelock adequacy.

  cost_ratio_score     = min(attack_cost_vs_tvl / 1.0, 1.0) * 40     (max 40 pts; ratio≥1.0 = safe)
  multisig_ratio_score = (m / n) * 30  for multisig "m/n", else 0    (max 30 pts)
  timelock_score       = min(timelock_hours / 168.0, 1.0) * 20       (max 20 pts)
  recency_score        = min(days_since_last_proposal / 30.0, 1.0) * 10  (max 10 pts; stale=safer)

  total = cost_ratio_score + multisig_ratio_score + timelock_score + recency_score
  Clamped to [0, 100].

attack_risk_label
  Based on governance_capture_score:
    < 20   → GOVERNANCE_FORTRESS
    < 40   → WELL_PROTECTED
    < 60   → MODERATE_RISK
    < 80   → HIGH_CAPTURE_RISK
    >= 80  → CRITICAL_VULNERABILITY

CLI
---
  python3 -m spa_core.analytics.protocol_defi_governance_attack_risk_analyzer --check
  python3 -m spa_core.analytics.protocol_defi_governance_attack_risk_analyzer --run
  python3 -m spa_core.analytics.protocol_defi_governance_attack_risk_analyzer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "governance_attack_risk_log.json"
RING_BUFFER_CAP = 100
SCHEMA_VERSION = 1
SOURCE_NAME = "protocol_defi_governance_attack_risk_analyzer"
MP_TAG = "MP-1059"

# Capture-score label thresholds (ascending capture_score)
_RISK_LABEL_THRESHOLDS = [
    (20.0, "GOVERNANCE_FORTRESS"),
    (40.0, "WELL_PROTECTED"),
    (60.0, "MODERATE_RISK"),
    (80.0, "HIGH_CAPTURE_RISK"),
]

log = logging.getLogger("spa.analytics.protocol_defi_governance_attack_risk_analyzer")

# ---------------------------------------------------------------------------
# Pure computation helpers (exported for tests)
# ---------------------------------------------------------------------------


def compute_attack_cost_vs_tvl(
    governance_token_market_cap_usd: float, tvl_usd: float
) -> float:
    """Ratio of 51%-acquisition cost to TVL.  Returns 0.0 if tvl_usd <= 0."""
    if tvl_usd <= 0:
        return 0.0
    attack_cost = governance_token_market_cap_usd * 0.51
    return attack_cost / tvl_usd


def parse_multisig_threshold(multisig_threshold: str) -> Tuple[int, int]:
    """Parse "m/n" → (m, n).  Returns (0, 1) on parse failure."""
    try:
        parts = str(multisig_threshold).strip().split("/")
        if len(parts) == 2:
            m, n = int(parts[0].strip()), int(parts[1].strip())
            if n > 0:
                return m, n
    except (ValueError, AttributeError):
        pass
    return 0, 1


def compute_governance_capture_score(
    token_concentration_top10_pct: float,
    timelock_hours: float,
    quorum_pct: float,
    voter_participation_pct: float,
    has_guardian: bool,
) -> float:
    """Return governance capture score in [0, 100].  Higher = more at risk."""
    concentration_factor = min(max(token_concentration_top10_pct / 100.0, 0.0), 1.0)
    timelock_factor = max(0.0, 1.0 - timelock_hours / 168.0)
    quorum_factor = max(0.0, 1.0 - quorum_pct / 50.0)
    participation_factor = max(0.0, 1.0 - voter_participation_pct / 50.0)
    guardian_factor = 0.0 if has_guardian else 1.0

    score = (
        concentration_factor * 35.0
        + timelock_factor * 20.0
        + quorum_factor * 15.0
        + participation_factor * 15.0
        + guardian_factor * 15.0
    )
    return max(0.0, min(score, 100.0))


def compute_decentralization_score(
    attack_cost_vs_tvl: float,
    multisig_threshold: str,
    timelock_hours: float,
    days_since_last_proposal: float,
) -> float:
    """Return decentralization score in [0, 100].  Higher = more decentralized."""
    cost_ratio_score = min(attack_cost_vs_tvl / 1.0, 1.0) * 40.0

    m, n = parse_multisig_threshold(multisig_threshold)
    multisig_ratio = (m / n) if n > 0 else 0.0
    multisig_score = min(max(multisig_ratio, 0.0), 1.0) * 30.0

    timelock_score = min(timelock_hours / 168.0, 1.0) * 20.0

    recency_score = min(days_since_last_proposal / 30.0, 1.0) * 10.0

    total = cost_ratio_score + multisig_score + timelock_score + recency_score
    return max(0.0, min(total, 100.0))


def attack_risk_label(governance_capture_score: float) -> str:
    """Map governance_capture_score to a risk label."""
    for threshold, label in _RISK_LABEL_THRESHOLDS:
        if governance_capture_score < threshold:
            return label
    return "CRITICAL_VULNERABILITY"


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------


class ProtocolDeFiGovernanceAttackRiskAnalyzer:
    """Read-only analytics: assesses governance attack risk for a DeFi protocol.

    Parameters (input dict)
    -----------------------
    protocol_name                     : str   — protocol identifier
    governance_token_market_cap_usd   : float — market cap of gov token (USD)
    tvl_usd                           : float — total value locked (USD)
    token_concentration_top10_pct     : float — % of tokens held by top-10 wallets
    timelock_hours                    : float — governance timelock in hours
    quorum_pct                        : float — required quorum % for passing proposals
    voter_participation_pct           : float — typical voter participation %
    has_guardian                      : bool  — whether a guardian/veto exists
    multisig_threshold                : str   — e.g. "3/5" (m-of-n multisig)
    days_since_last_proposal          : float — days since last governance proposal

    Outputs (dict)
    --------------
    attack_cost_vs_tvl_ratio    : float — attack cost / TVL
    governance_capture_score    : float — 0–100 (higher = more at risk)
    decentralization_score      : float — 0–100 (higher = more decentralized)
    attack_risk_label           : str   — one of five risk labels
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._log_path = self._data_dir / LOG_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze governance attack risk and return result dict."""
        self._validate(params)

        protocol_name = str(params["protocol_name"])
        gov_market_cap = float(params["governance_token_market_cap_usd"])
        tvl_usd = float(params["tvl_usd"])
        concentration = float(params["token_concentration_top10_pct"])
        timelock_hours = float(params["timelock_hours"])
        quorum_pct = float(params["quorum_pct"])
        participation_pct = float(params["voter_participation_pct"])
        has_guardian = bool(params["has_guardian"])
        multisig = str(params["multisig_threshold"])
        days_since_proposal = float(params["days_since_last_proposal"])

        attack_ratio = compute_attack_cost_vs_tvl(gov_market_cap, tvl_usd)
        capture_score = compute_governance_capture_score(
            concentration, timelock_hours, quorum_pct, participation_pct, has_guardian
        )
        decent_score = compute_decentralization_score(
            attack_ratio, multisig, timelock_hours, days_since_proposal
        )
        label = attack_risk_label(capture_score)

        return {
            "schema_version": SCHEMA_VERSION,
            "mp_tag": MP_TAG,
            "source": SOURCE_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol_name": protocol_name,
            "governance_token_market_cap_usd": gov_market_cap,
            "tvl_usd": tvl_usd,
            "token_concentration_top10_pct": concentration,
            "timelock_hours": timelock_hours,
            "quorum_pct": quorum_pct,
            "voter_participation_pct": participation_pct,
            "has_guardian": has_guardian,
            "multisig_threshold": multisig,
            "days_since_last_proposal": days_since_proposal,
            # --- outputs ---
            "attack_cost_vs_tvl_ratio": round(attack_ratio, 8),
            "governance_capture_score": round(capture_score, 4),
            "decentralization_score": round(decent_score, 4),
            "attack_risk_label": label,
        }

    def analyze_and_save(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze and atomically append result to ring-buffer log."""
        result = self.analyze(params)
        self._append_to_log(result)
        result["saved_to"] = str(self._log_path)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate(self, params: Dict[str, Any]) -> None:
        required = [
            "protocol_name", "governance_token_market_cap_usd", "tvl_usd",
            "token_concentration_top10_pct", "timelock_hours", "quorum_pct",
            "voter_participation_pct", "has_guardian", "multisig_threshold",
            "days_since_last_proposal",
        ]
        missing = [k for k in required if k not in params]
        if missing:
            raise ValueError(f"Missing required params: {missing}")

    def _append_to_log(self, entry: Dict[str, Any]) -> None:
        """Load existing log, append entry, cap at RING_BUFFER_CAP, atomic save."""
        existing: List[Dict[str, Any]] = _load_json_list(self._log_path)
        existing.append(entry)
        if len(existing) > RING_BUFFER_CAP:
            existing = existing[-RING_BUFFER_CAP:]
        _atomic_write_json(self._log_path, existing)


# ---------------------------------------------------------------------------
# JSON I/O helpers
# ---------------------------------------------------------------------------


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    """Load a JSON list from *path*; return [] on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _atomic_write_json(path: Path, data: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(data, str(path))
def _build_sample_params() -> Dict[str, Any]:
    return {
        "protocol_name": "Compound",
        "governance_token_market_cap_usd": 500_000_000.0,
        "tvl_usd": 2_000_000_000.0,
        "token_concentration_top10_pct": 45.0,
        "timelock_hours": 48.0,
        "quorum_pct": 4.0,
        "voter_participation_pct": 8.0,
        "has_guardian": False,
        "multisig_threshold": "4/7",
        "days_since_last_proposal": 14.0,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=f"{MP_TAG}: Governance Attack Risk Analyzer")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", default=True,
                      help="Compute and print (no write). Default.")
    mode.add_argument("--run", action="store_true",
                      help="Compute, print, and save to log.")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory path.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    analyzer = ProtocolDeFiGovernanceAttackRiskAnalyzer(data_dir=data_dir)
    params = _build_sample_params()

    if args.run:
        result = analyzer.analyze_and_save(params)
        print(json.dumps(result, indent=2))
        log.info("Saved to %s", result.get("saved_to"))
    else:
        result = analyzer.analyze(params)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

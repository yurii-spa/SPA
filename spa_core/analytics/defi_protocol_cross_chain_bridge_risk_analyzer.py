"""
MP-1126 — DeFiProtocolCrossChainBridgeRiskAnalyzer
Analyzes the risk of yield strategies that depend on cross-chain bridges.
Bridge hacks: Ronin $625M, Wormhole $320M, Nomad $190M.
Scores the compounded bridge risk for multi-chain yield strategies.

Pure stdlib. No external deps. Atomic JSON writes.
"""

import json
import os
import time
from typing import Dict, Any, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIDGE_BASE_SCORES: Dict[str, int] = {
    "native_rollup": 0,
    "layerzero":     8,
    "stargate":     12,
    "wormhole":     20,
    "multichain":   35,
    "nomad":        40,
    "synapse":      10,
    "hop":          10,
    "custom":       30,
}

BRIDGE_LABELS = [
    (10,  "BATTLE_TESTED_BRIDGE"),
    (25,  "ESTABLISHED_BRIDGE"),
    (45,  "MODERATE_BRIDGE_RISK"),
    (70,  "HIGH_BRIDGE_RISK"),
    (101, "AVOID_BRIDGE"),
]

LOG_FILE = "data/cross_chain_bridge_risk_log.json"
LOG_RING_BUFFER = 100


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class DeFiProtocolCrossChainBridgeRiskAnalyzer:
    """
    Scores the bridge risk of a cross-chain yield position.

    All arithmetic is deterministic integers/floats (no LLM, no network).
    """

    def __init__(self, data_dir: str = "data"):
        self._data_dir = data_dir
        self._log_path = os.path.join(data_dir, "cross_chain_bridge_risk_log.json")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        bridge_name: str,
        bridge_tvl_usd: float,
        bridge_audit_count: int,
        bridge_age_days: int,
        prior_hack_usd: float,
        position_bridge_exposure_usd: float,
        is_canonical_bridge: bool,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Run analysis and return result dict.

        Parameters
        ----------
        bridge_name : str
            One of native_rollup / layerzero / stargate / wormhole /
            multichain / nomad / synapse / hop / custom
        bridge_tvl_usd : float
            Total value secured by the bridge in USD.
        bridge_audit_count : int
            Number of completed security audits.
        bridge_age_days : int
            Days since bridge launched.
        prior_hack_usd : float
            Total value lost in prior hacks (0 if never hacked).
        position_bridge_exposure_usd : float
            Our position value crossing this bridge in USD.
        is_canonical_bridge : bool
            True if this is the native L2 bridge (Arbitrum/Optimism official).
        protocol_name : str
            Human-readable protocol label (advisory, not used in scoring).

        Returns
        -------
        dict with all computed fields plus inputs echoed back.
        """
        self._validate_inputs(
            bridge_name, bridge_tvl_usd, bridge_audit_count,
            bridge_age_days, prior_hack_usd, position_bridge_exposure_usd,
        )

        bridge_base_risk_score = self._base_score(bridge_name)
        hack_history_penalty   = self._hack_penalty(prior_hack_usd)
        maturity_bonus         = self._maturity_bonus(bridge_age_days)
        audit_bonus            = self._audit_bonus(bridge_audit_count)
        canonical_bonus        = 20 if is_canonical_bridge else 0

        raw = (bridge_base_risk_score + hack_history_penalty
               - maturity_bonus - audit_bonus - canonical_bonus)
        bridge_risk_score = max(0, min(100, raw))

        expected_loss_usd = position_bridge_exposure_usd * (bridge_risk_score / 100) * 0.1
        bridge_label      = self._label(bridge_risk_score)

        result: Dict[str, Any] = {
            # Inputs (echoed)
            "protocol_name":                 protocol_name,
            "bridge_name":                   bridge_name,
            "bridge_tvl_usd":                bridge_tvl_usd,
            "bridge_audit_count":            bridge_audit_count,
            "bridge_age_days":               bridge_age_days,
            "prior_hack_usd":                prior_hack_usd,
            "position_bridge_exposure_usd":  position_bridge_exposure_usd,
            "is_canonical_bridge":           is_canonical_bridge,
            # Outputs
            "bridge_base_risk_score":        bridge_base_risk_score,
            "hack_history_penalty":          hack_history_penalty,
            "maturity_bonus":                maturity_bonus,
            "audit_bonus":                   audit_bonus,
            "canonical_bonus":               canonical_bonus,
            "bridge_risk_score":             bridge_risk_score,
            "expected_loss_usd":             round(expected_loss_usd, 6),
            "bridge_label":                  bridge_label,
            "timestamp":                     int(time.time()),
        }
        return result

    def analyze_and_log(
        self,
        bridge_name: str,
        bridge_tvl_usd: float,
        bridge_audit_count: int,
        bridge_age_days: int,
        prior_hack_usd: float,
        position_bridge_exposure_usd: float,
        is_canonical_bridge: bool,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Run analyze() and append result to ring-buffer log."""
        result = self.analyze(
            bridge_name, bridge_tvl_usd, bridge_audit_count,
            bridge_age_days, prior_hack_usd,
            position_bridge_exposure_usd, is_canonical_bridge,
            protocol_name,
        )
        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _base_score(bridge_name: str) -> int:
        name = bridge_name.lower().strip()
        return BRIDGE_BASE_SCORES.get(name, BRIDGE_BASE_SCORES["custom"])

    @staticmethod
    def _hack_penalty(prior_hack_usd: float) -> int:
        if prior_hack_usd <= 0:
            return 0
        return min(40, int(prior_hack_usd / 1e7))

    @staticmethod
    def _maturity_bonus(bridge_age_days: int) -> int:
        return min(15, bridge_age_days // 60)

    @staticmethod
    def _audit_bonus(bridge_audit_count: int) -> int:
        return min(10, bridge_audit_count * 3)

    @staticmethod
    def _label(score: int) -> str:
        for threshold, label in BRIDGE_LABELS:
            if score <= threshold:
                return label
        return "AVOID_BRIDGE"  # pragma: no cover

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(
        bridge_name: str,
        bridge_tvl_usd: float,
        bridge_audit_count: int,
        bridge_age_days: int,
        prior_hack_usd: float,
        position_bridge_exposure_usd: float,
    ) -> None:
        valid_names = set(BRIDGE_BASE_SCORES.keys())
        name = bridge_name.lower().strip()
        if name not in valid_names:
            raise ValueError(
                f"Unknown bridge_name '{bridge_name}'. "
                f"Valid: {sorted(valid_names)}"
            )
        if bridge_tvl_usd < 0:
            raise ValueError("bridge_tvl_usd must be >= 0")
        if bridge_audit_count < 0:
            raise ValueError("bridge_audit_count must be >= 0")
        if bridge_age_days < 0:
            raise ValueError("bridge_age_days must be >= 0")
        if prior_hack_usd < 0:
            raise ValueError("prior_hack_usd must be >= 0")
        if position_bridge_exposure_usd < 0:
            raise ValueError("position_bridge_exposure_usd must be >= 0")

    # ------------------------------------------------------------------
    # Atomic log append (ring-buffer capped at LOG_RING_BUFFER)
    # ------------------------------------------------------------------

    def _append_log(self, entry: Dict[str, Any]) -> None:
        os.makedirs(self._data_dir, exist_ok=True)
        existing: List[Dict[str, Any]] = []
        if os.path.exists(self._log_path):
            try:
                with open(self._log_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(entry)
        if len(existing) > LOG_RING_BUFFER:
            existing = existing[-LOG_RING_BUFFER:]

        atomic_save(existing, str(self))
    # ------------------------------------------------------------------
    # Convenience class-method for one-shot use
    # ------------------------------------------------------------------

    @classmethod
    def score(
        cls,
        bridge_name: str,
        bridge_tvl_usd: float,
        bridge_audit_count: int,
        bridge_age_days: int,
        prior_hack_usd: float,
        position_bridge_exposure_usd: float,
        is_canonical_bridge: bool,
        protocol_name: str = "",
        data_dir: str = "data",
    ) -> Dict[str, Any]:
        """One-shot class-method wrapper (no log write)."""
        return cls(data_dir=data_dir).analyze(
            bridge_name, bridge_tvl_usd, bridge_audit_count,
            bridge_age_days, prior_hack_usd,
            position_bridge_exposure_usd, is_canonical_bridge,
            protocol_name,
        )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="DeFiProtocolCrossChainBridgeRiskAnalyzer CLI"
    )
    parser.add_argument("--bridge-name",       required=True)
    parser.add_argument("--bridge-tvl-usd",    type=float, required=True)
    parser.add_argument("--bridge-audit-count", type=int,  required=True)
    parser.add_argument("--bridge-age-days",   type=int,   required=True)
    parser.add_argument("--prior-hack-usd",    type=float, default=0.0)
    parser.add_argument("--position-exposure", type=float, required=True)
    parser.add_argument("--is-canonical",      action="store_true")
    parser.add_argument("--protocol-name",     default="")
    parser.add_argument("--data-dir",          default="data")
    parser.add_argument("--log",               action="store_true",
                        help="Write result to log file")
    args = parser.parse_args()

    analyzer = DeFiProtocolCrossChainBridgeRiskAnalyzer(data_dir=args.data_dir)
    fn = analyzer.analyze_and_log if args.log else analyzer.analyze
    result = fn(
        bridge_name=args.bridge_name,
        bridge_tvl_usd=args.bridge_tvl_usd,
        bridge_audit_count=args.bridge_audit_count,
        bridge_age_days=args.bridge_age_days,
        prior_hack_usd=args.prior_hack_usd,
        position_bridge_exposure_usd=args.position_exposure,
        is_canonical_bridge=args.is_canonical,
        protocol_name=args.protocol_name,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()

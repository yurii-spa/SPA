"""
MP-1127 — ProtocolDeFiTokenUnlockPressureAnalyzer
Analyzes upcoming token unlock events and their potential sell pressure on
protocol governance/reward tokens.

Large unlocks to early investors/team members often cause token price drops,
reducing emission-based yields.

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

RECIPIENT_TYPE_WEIGHTS: Dict[str, int] = {
    "team":       25,
    "investors":  20,
    "mixed":      10,
    "foundation":  5,
    "community":   0,
}

PRESSURE_LABELS = [
    (15,  "MINIMAL_UNLOCK_PRESSURE"),
    (35,  "LOW_UNLOCK_PRESSURE"),
    (55,  "MODERATE_UNLOCK_PRESSURE"),
    (75,  "HIGH_UNLOCK_PRESSURE"),
    (101, "SEVERE_UNLOCK_PRESSURE"),
]

LOG_RING_BUFFER = 100


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class ProtocolDeFiTokenUnlockPressureAnalyzer:
    """
    Analyzes upcoming token unlock events and scores sell pressure risk.

    All arithmetic is deterministic (no LLM, no network calls).
    """

    def __init__(self, data_dir: str = "data"):
        self._data_dir = data_dir
        self._log_path = os.path.join(data_dir, "token_unlock_pressure_log.json")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        current_circulating_supply: float,
        tokens_unlocking_in_30d: float,
        tokens_unlocking_in_90d: float,
        unlock_recipient_type: str,
        current_token_price_usd: float,
        avg_daily_volume_usd: float,
        protocol_tvl_usd: float,
        our_emission_based_yield_usd_monthly: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Run analysis and return result dict.

        Parameters
        ----------
        current_circulating_supply : float
            Tokens currently in circulation.
        tokens_unlocking_in_30d : float
            Tokens to unlock in the next 30 days.
        tokens_unlocking_in_90d : float
            Tokens to unlock in the next 90 days.
        unlock_recipient_type : str
            One of team / investors / community / foundation / mixed.
        current_token_price_usd : float
            Current token price in USD.
        avg_daily_volume_usd : float
            24-hour trading volume of the token in USD.
        protocol_tvl_usd : float
            Protocol total value locked in USD.
        our_emission_based_yield_usd_monthly : float
            How much we earn in this token per month (USD).
        protocol_name : str
            Human-readable protocol label (advisory).

        Returns
        -------
        dict with all computed fields plus inputs echoed back.
        """
        self._validate_inputs(
            current_circulating_supply, tokens_unlocking_in_30d,
            tokens_unlocking_in_90d, unlock_recipient_type,
            current_token_price_usd, avg_daily_volume_usd,
            protocol_tvl_usd, our_emission_based_yield_usd_monthly,
        )

        unlock_pct_30d = self._unlock_pct(
            tokens_unlocking_in_30d, current_circulating_supply
        )
        unlock_pct_90d = self._unlock_pct(
            tokens_unlocking_in_90d, current_circulating_supply
        )
        unlock_value_30d_usd = tokens_unlocking_in_30d * current_token_price_usd
        unlock_value_90d_usd = tokens_unlocking_in_90d * current_token_price_usd

        days_of_volume_to_absorb = self._days_to_absorb(
            unlock_value_30d_usd, avg_daily_volume_usd
        )

        sell_pressure_score = self._pressure_score(
            unlock_pct_30d, unlock_recipient_type, days_of_volume_to_absorb
        )

        our_yield_at_risk_usd = our_emission_based_yield_usd_monthly * 0.30
        pressure_label = self._label(sell_pressure_score)

        result: Dict[str, Any] = {
            # Inputs echoed
            "protocol_name":                        protocol_name,
            "current_circulating_supply":           current_circulating_supply,
            "tokens_unlocking_in_30d":              tokens_unlocking_in_30d,
            "tokens_unlocking_in_90d":              tokens_unlocking_in_90d,
            "unlock_recipient_type":                unlock_recipient_type,
            "current_token_price_usd":              current_token_price_usd,
            "avg_daily_volume_usd":                 avg_daily_volume_usd,
            "protocol_tvl_usd":                     protocol_tvl_usd,
            "our_emission_based_yield_usd_monthly": our_emission_based_yield_usd_monthly,
            # Outputs
            "unlock_pct_30d":                       round(unlock_pct_30d, 6),
            "unlock_pct_90d":                       round(unlock_pct_90d, 6),
            "unlock_value_30d_usd":                 round(unlock_value_30d_usd, 6),
            "unlock_value_90d_usd":                 round(unlock_value_90d_usd, 6),
            "days_of_volume_to_absorb":             round(days_of_volume_to_absorb, 6),
            "sell_pressure_score":                  sell_pressure_score,
            "our_yield_at_risk_usd":                round(our_yield_at_risk_usd, 6),
            "pressure_label":                       pressure_label,
            "timestamp":                            int(time.time()),
        }
        return result

    def analyze_and_log(
        self,
        current_circulating_supply: float,
        tokens_unlocking_in_30d: float,
        tokens_unlocking_in_90d: float,
        unlock_recipient_type: str,
        current_token_price_usd: float,
        avg_daily_volume_usd: float,
        protocol_tvl_usd: float,
        our_emission_based_yield_usd_monthly: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """Run analyze() and append result to ring-buffer log."""
        result = self.analyze(
            current_circulating_supply, tokens_unlocking_in_30d,
            tokens_unlocking_in_90d, unlock_recipient_type,
            current_token_price_usd, avg_daily_volume_usd,
            protocol_tvl_usd, our_emission_based_yield_usd_monthly,
            protocol_name,
        )
        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unlock_pct(tokens: float, circulating: float) -> float:
        if circulating <= 0:
            return 0.0
        return (tokens / circulating) * 100.0

    @staticmethod
    def _days_to_absorb(unlock_value_30d: float, avg_daily_volume: float) -> float:
        if avg_daily_volume <= 0:
            # Infinite absorption time; cap at a large number for score purposes
            return 1_000_000.0
        return unlock_value_30d / avg_daily_volume

    @classmethod
    def _pressure_score(
        cls,
        unlock_pct_30d: float,
        recipient_type: str,
        days_of_volume_to_absorb: float,
    ) -> int:
        base             = min(50, unlock_pct_30d * 5)
        recipient_weight = RECIPIENT_TYPE_WEIGHTS.get(
            recipient_type.lower().strip(), 0
        )
        volume_penalty   = min(25, days_of_volume_to_absorb * 2)
        raw              = base + recipient_weight + volume_penalty
        return max(0, min(100, int(raw)))

    @staticmethod
    def _label(score: int) -> str:
        for threshold, label in PRESSURE_LABELS:
            if score <= threshold:
                return label
        return "SEVERE_UNLOCK_PRESSURE"  # pragma: no cover

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(
        current_circulating_supply: float,
        tokens_unlocking_in_30d: float,
        tokens_unlocking_in_90d: float,
        unlock_recipient_type: str,
        current_token_price_usd: float,
        avg_daily_volume_usd: float,
        protocol_tvl_usd: float,
        our_emission_based_yield_usd_monthly: float,
    ) -> None:
        valid_types = set(RECIPIENT_TYPE_WEIGHTS.keys())
        rtype = unlock_recipient_type.lower().strip()
        if rtype not in valid_types:
            raise ValueError(
                f"Unknown unlock_recipient_type '{unlock_recipient_type}'. "
                f"Valid: {sorted(valid_types)}"
            )
        if current_circulating_supply < 0:
            raise ValueError("current_circulating_supply must be >= 0")
        if tokens_unlocking_in_30d < 0:
            raise ValueError("tokens_unlocking_in_30d must be >= 0")
        if tokens_unlocking_in_90d < 0:
            raise ValueError("tokens_unlocking_in_90d must be >= 0")
        if current_token_price_usd < 0:
            raise ValueError("current_token_price_usd must be >= 0")
        if avg_daily_volume_usd < 0:
            raise ValueError("avg_daily_volume_usd must be >= 0")
        if protocol_tvl_usd < 0:
            raise ValueError("protocol_tvl_usd must be >= 0")
        if our_emission_based_yield_usd_monthly < 0:
            raise ValueError("our_emission_based_yield_usd_monthly must be >= 0")

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

        atomic_save(existing, str(self._log_path))
    # ------------------------------------------------------------------
    # Convenience class-method
    # ------------------------------------------------------------------

    @classmethod
    def score(
        cls,
        current_circulating_supply: float,
        tokens_unlocking_in_30d: float,
        tokens_unlocking_in_90d: float,
        unlock_recipient_type: str,
        current_token_price_usd: float,
        avg_daily_volume_usd: float,
        protocol_tvl_usd: float,
        our_emission_based_yield_usd_monthly: float,
        protocol_name: str = "",
        data_dir: str = "data",
    ) -> Dict[str, Any]:
        """One-shot class-method wrapper (no log write)."""
        return cls(data_dir=data_dir).analyze(
            current_circulating_supply, tokens_unlocking_in_30d,
            tokens_unlocking_in_90d, unlock_recipient_type,
            current_token_price_usd, avg_daily_volume_usd,
            protocol_tvl_usd, our_emission_based_yield_usd_monthly,
            protocol_name,
        )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="ProtocolDeFiTokenUnlockPressureAnalyzer CLI"
    )
    parser.add_argument("--circulating-supply",   type=float, required=True)
    parser.add_argument("--unlock-30d",           type=float, required=True)
    parser.add_argument("--unlock-90d",           type=float, required=True)
    parser.add_argument("--recipient-type",       required=True)
    parser.add_argument("--token-price",          type=float, required=True)
    parser.add_argument("--daily-volume",         type=float, required=True)
    parser.add_argument("--protocol-tvl",         type=float, required=True)
    parser.add_argument("--our-monthly-yield",    type=float, required=True)
    parser.add_argument("--protocol-name",        default="")
    parser.add_argument("--data-dir",             default="data")
    parser.add_argument("--log",                  action="store_true",
                        help="Write result to log file")
    args = parser.parse_args()

    analyzer = ProtocolDeFiTokenUnlockPressureAnalyzer(data_dir=args.data_dir)
    fn = analyzer.analyze_and_log if args.log else analyzer.analyze
    result = fn(
        current_circulating_supply=args.circulating_supply,
        tokens_unlocking_in_30d=args.unlock_30d,
        tokens_unlocking_in_90d=args.unlock_90d,
        unlock_recipient_type=args.recipient_type,
        current_token_price_usd=args.token_price,
        avg_daily_volume_usd=args.daily_volume,
        protocol_tvl_usd=args.protocol_tvl,
        our_emission_based_yield_usd_monthly=args.our_monthly_yield,
        protocol_name=args.protocol_name,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()

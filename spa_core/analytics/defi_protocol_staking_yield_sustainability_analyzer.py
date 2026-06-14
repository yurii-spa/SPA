"""
MP-1040: DeFiProtocolStakingYieldSustainabilityAnalyzer
========================================================
Advisory-only analytics module.
Analyzes whether staking yields (ETH staking, liquid staking, restaking) are
sustainable by decomposing the yield into real economic sources (consensus +
MEV) vs. inflation-driven dilution.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/staking_yield_sustainability_log.json.
Atomic writes: tmp + os.replace.

Labels
------
PURE_CONSENSUS_YIELD  : ≥90% of yield from consensus+MEV, restaking_boost < 2%
SUSTAINABLE_BOOST     : ≥60% real yield AND restaking_boost meaningful
INFLATION_SUPPORTED   : 30-70% of yield is inflation-driven
DILUTION_RISK         : >70% of yield is inflation-driven, real purchasing power eroded
PONZI_YIELD           : inflation-adjusted yield < -2% (yield is net-negative in real terms)

Outputs
-------
sustainable_yield_pct        : consensus + mev + restaking_boost - slashing_risk
inflation_adjusted_yield_pct : staking_apy - token_inflation
real_yield_score             : 0-100 composite sustainability score
sustainability_grade         : A (≥80) / B (≥60) / C (≥40) / D (≥20) / F (<20)
label                        : see Labels above

CLI
---
python3 -m spa_core.analytics.defi_protocol_staking_yield_sustainability_analyzer --check
python3 -m spa_core.analytics.defi_protocol_staking_yield_sustainability_analyzer --run
python3 -m spa_core.analytics.defi_protocol_staking_yield_sustainability_analyzer --run --data-dir PATH
"""

import argparse
import json
import os
import sys
import tempfile
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")

LOG_FILENAME = "staking_yield_sustainability_log.json"
LOG_MAX_ENTRIES = 100

# Grade thresholds
GRADE_A_THRESHOLD = 80.0
GRADE_B_THRESHOLD = 60.0
GRADE_C_THRESHOLD = 40.0
GRADE_D_THRESHOLD = 20.0

# Label thresholds
PONZI_INFLATION_ADJ_THRESHOLD = -2.0   # inflation_adjusted_yield < this → PONZI_YIELD
DILUTION_INFLATION_FRACTION = 0.70     # inflation_fraction > this → DILUTION_RISK
INFLATION_SUPPORTED_FRACTION = 0.30    # inflation_fraction > this → INFLATION_SUPPORTED
PURE_CONSENSUS_REAL_FRACTION = 0.90    # real_fraction >= this (and low restaking) → PURE_CONSENSUS
PURE_CONSENSUS_MAX_RESTAKING = 2.0     # restaking_boost < this for PURE_CONSENSUS_YIELD
SUSTAINABLE_BOOST_REAL_FRACTION = 0.60 # real_fraction >= this → SUSTAINABLE_BOOST

# Score weights
SCORE_MAX_REAL_RATIO_POINTS = 70.0
SCORE_MAX_PARTICIPATION_POINTS = 10.0
SCORE_MAX_INFLATION_PENALTY = 30.0
SCORE_MAX_SLASHING_PENALTY = 20.0
SCORE_SLASHING_MULTIPLIER = 4.0
SCORE_RESTAKING_THRESHOLD = 3.0        # restaking > this adds complexity penalty
SCORE_RESTAKING_PENALTY_RATE = 2.0
SCORE_MAX_RESTAKING_PENALTY = 10.0


# ---------------------------------------------------------------------------
# Helper computations
# ---------------------------------------------------------------------------

def _compute_sustainable_yield(
    consensus_yield_pct: float,
    mev_yield_pct: float,
    restaking_boost_pct: float,
    slashing_risk_pct: float,
) -> float:
    """Real economic yield from the protocol (consensus + MEV + restaking - slashing)."""
    return consensus_yield_pct + mev_yield_pct + restaking_boost_pct - slashing_risk_pct


def _compute_inflation_adjusted_yield(
    staking_apy_pct: float,
    token_inflation_pct: float,
) -> float:
    """Purchasing-power yield: what stakers actually earn after token dilution."""
    return staking_apy_pct - token_inflation_pct


def _compute_real_yield_score(
    staking_apy_pct: float,
    consensus_yield_pct: float,
    mev_yield_pct: float,
    token_inflation_pct: float,
    restaking_boost_pct: float,
    slashing_risk_pct: float,
    network_participation_rate_pct: float,
) -> float:
    """
    Composite sustainability score (0-100).

    Scoring components
    ------------------
    +70  weighted by real-yield fraction (consensus + mev) / staking_apy
    +10  network participation health (proportional)
    -30  inflation penalty (proportional to inflation fraction of staking_apy)
    -20  slashing risk penalty (slashing_risk * 4, capped at 20)
    -10  restaking complexity penalty (only when restaking_boost > 3%)
    """
    if staking_apy_pct <= 0.0:
        return 0.0

    # Real economic sources
    real_yield = max(0.0, consensus_yield_pct + mev_yield_pct)
    real_ratio = min(1.0, real_yield / staking_apy_pct)
    real_points = real_ratio * SCORE_MAX_REAL_RATIO_POINTS

    # Network participation bonus
    participation = max(0.0, min(100.0, network_participation_rate_pct))
    participation_points = (participation / 100.0) * SCORE_MAX_PARTICIPATION_POINTS

    # Inflation penalty
    inflation_ratio = min(1.0, max(0.0, token_inflation_pct / staking_apy_pct))
    inflation_penalty = inflation_ratio * SCORE_MAX_INFLATION_PENALTY

    # Slashing risk penalty
    slashing_penalty = min(
        SCORE_MAX_SLASHING_PENALTY,
        max(0.0, slashing_risk_pct * SCORE_SLASHING_MULTIPLIER),
    )

    # Restaking complexity penalty
    restaking_penalty = 0.0
    if restaking_boost_pct > SCORE_RESTAKING_THRESHOLD:
        excess = restaking_boost_pct - SCORE_RESTAKING_THRESHOLD
        restaking_penalty = min(
            SCORE_MAX_RESTAKING_PENALTY, excess * SCORE_RESTAKING_PENALTY_RATE
        )

    score = (
        real_points
        + participation_points
        - inflation_penalty
        - slashing_penalty
        - restaking_penalty
    )
    return max(0.0, min(100.0, score))


def _compute_sustainability_grade(score: float) -> str:
    """Map 0-100 score to A-F grade."""
    if score >= GRADE_A_THRESHOLD:
        return "A"
    elif score >= GRADE_B_THRESHOLD:
        return "B"
    elif score >= GRADE_C_THRESHOLD:
        return "C"
    elif score >= GRADE_D_THRESHOLD:
        return "D"
    else:
        return "F"


def _compute_label(
    staking_apy_pct: float,
    consensus_yield_pct: float,
    mev_yield_pct: float,
    token_inflation_pct: float,
    restaking_boost_pct: float,
) -> str:
    """
    Classify yield sustainability into one of five labels.

    Priority (highest to lowest):
    1. PONZI_YIELD          — inflation_adjusted < -2%
    2. DILUTION_RISK        — >70% of staking_apy is inflation
    3. INFLATION_SUPPORTED  — 30-70% of staking_apy is inflation
    4. PURE_CONSENSUS_YIELD — ≥90% real, restaking_boost < 2%
    5. SUSTAINABLE_BOOST    — default when real ≥ 60%
    """
    if staking_apy_pct <= 0.0:
        return "PONZI_YIELD"

    inflation_adjusted = _compute_inflation_adjusted_yield(staking_apy_pct, token_inflation_pct)
    if inflation_adjusted < PONZI_INFLATION_ADJ_THRESHOLD:
        return "PONZI_YIELD"

    inflation_fraction = max(0.0, token_inflation_pct) / staking_apy_pct

    if inflation_fraction > DILUTION_INFLATION_FRACTION:
        return "DILUTION_RISK"

    if inflation_fraction > INFLATION_SUPPORTED_FRACTION:
        return "INFLATION_SUPPORTED"

    real_yield = max(0.0, consensus_yield_pct + mev_yield_pct)
    real_fraction = real_yield / staking_apy_pct

    if real_fraction >= PURE_CONSENSUS_REAL_FRACTION and restaking_boost_pct < PURE_CONSENSUS_MAX_RESTAKING:
        return "PURE_CONSENSUS_YIELD"

    return "SUSTAINABLE_BOOST"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolStakingYieldSustainabilityAnalyzer:
    """
    Analyzes whether a DeFi staking protocol's advertised APY is economically
    sustainable (backed by real consensus + MEV revenue) or inflation-driven.

    Parameters
    ----------
    data_dir : str | None
        Directory for log output. Defaults to <repo_root>/data.
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR
        self.log_path = os.path.join(self.data_dir, LOG_FILENAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        protocol_name: str,
        staking_apy_pct: float,
        consensus_yield_pct: float,
        mev_yield_pct: float,
        token_inflation_pct: float,
        restaking_boost_pct: float,
        slashing_risk_pct: float,
        network_participation_rate_pct: float,
        save: bool = False,
    ) -> dict:
        """
        Analyze staking yield sustainability for a single protocol.

        Parameters
        ----------
        protocol_name               : str   e.g. "Lido stETH", "EtherFi eETH"
        staking_apy_pct             : float total advertised APY (%)
        consensus_yield_pct         : float share from PoS consensus rewards (%)
        mev_yield_pct               : float share from MEV tips (%)
        token_inflation_pct         : float annualized token supply inflation (%)
        restaking_boost_pct         : float additional yield from restaking (%)
        slashing_risk_pct           : float expected annualized slashing loss (%)
        network_participation_rate_pct : float % of eligible stake participating
        save                        : bool  if True, atomically append to log

        Returns
        -------
        dict with keys:
            protocol_name, staking_apy_pct, consensus_yield_pct, mev_yield_pct,
            token_inflation_pct, restaking_boost_pct, slashing_risk_pct,
            network_participation_rate_pct,
            sustainable_yield_pct, inflation_adjusted_yield_pct,
            real_yield_score, sustainability_grade, label, timestamp
        """
        # Validate / clamp inputs
        staking_apy_pct = float(staking_apy_pct)
        consensus_yield_pct = float(consensus_yield_pct)
        mev_yield_pct = float(mev_yield_pct)
        token_inflation_pct = float(token_inflation_pct)
        restaking_boost_pct = float(restaking_boost_pct)
        slashing_risk_pct = float(slashing_risk_pct)
        network_participation_rate_pct = float(network_participation_rate_pct)

        sustainable_yield = _compute_sustainable_yield(
            consensus_yield_pct, mev_yield_pct, restaking_boost_pct, slashing_risk_pct
        )
        inflation_adjusted_yield = _compute_inflation_adjusted_yield(
            staking_apy_pct, token_inflation_pct
        )
        score = _compute_real_yield_score(
            staking_apy_pct,
            consensus_yield_pct,
            mev_yield_pct,
            token_inflation_pct,
            restaking_boost_pct,
            slashing_risk_pct,
            network_participation_rate_pct,
        )
        grade = _compute_sustainability_grade(score)
        label = _compute_label(
            staking_apy_pct,
            consensus_yield_pct,
            mev_yield_pct,
            token_inflation_pct,
            restaking_boost_pct,
        )

        result = {
            "protocol_name": protocol_name,
            "staking_apy_pct": round(staking_apy_pct, 6),
            "consensus_yield_pct": round(consensus_yield_pct, 6),
            "mev_yield_pct": round(mev_yield_pct, 6),
            "token_inflation_pct": round(token_inflation_pct, 6),
            "restaking_boost_pct": round(restaking_boost_pct, 6),
            "slashing_risk_pct": round(slashing_risk_pct, 6),
            "network_participation_rate_pct": round(network_participation_rate_pct, 6),
            "sustainable_yield_pct": round(sustainable_yield, 6),
            "inflation_adjusted_yield_pct": round(inflation_adjusted_yield, 6),
            "real_yield_score": round(score, 4),
            "sustainability_grade": grade,
            "label": label,
            "timestamp": time.time(),
        }

        if save:
            self._append_log(result)

        return result

    # ------------------------------------------------------------------
    # Log management
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        """Atomically append entry to ring-buffer log (capped at LOG_MAX_ENTRIES)."""
        os.makedirs(self.data_dir, exist_ok=True)
        existing = self._read_log()
        existing.append(entry)
        existing = existing[-LOG_MAX_ENTRIES:]
        self._atomic_write(existing)

    def _read_log(self) -> list:
        if not os.path.exists(self.log_path):
            return []
        try:
            with open(self.log_path, "r") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _atomic_write(self, data: list) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.data_dir, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, self.log_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def init_log(self) -> None:
        """Initialize log file as empty list if it does not exist."""
        if not os.path.exists(self.log_path):
            self._atomic_write([])


# ---------------------------------------------------------------------------
# Module-level convenience API (mirrors class for easy import in tests)
# ---------------------------------------------------------------------------

def analyze(
    protocol_name: str,
    staking_apy_pct: float,
    consensus_yield_pct: float,
    mev_yield_pct: float,
    token_inflation_pct: float,
    restaking_boost_pct: float,
    slashing_risk_pct: float,
    network_participation_rate_pct: float,
    data_dir: Optional[str] = None,
    save: bool = False,
) -> dict:
    """Module-level shortcut: create analyzer and call analyze()."""
    analyzer = DeFiProtocolStakingYieldSustainabilityAnalyzer(data_dir=data_dir)
    return analyzer.analyze(
        protocol_name=protocol_name,
        staking_apy_pct=staking_apy_pct,
        consensus_yield_pct=consensus_yield_pct,
        mev_yield_pct=mev_yield_pct,
        token_inflation_pct=token_inflation_pct,
        restaking_boost_pct=restaking_boost_pct,
        slashing_risk_pct=slashing_risk_pct,
        network_participation_rate_pct=network_participation_rate_pct,
        save=save,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MP-1040 DeFiProtocolStakingYieldSustainabilityAnalyzer"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print results without writing to log",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute, print, and atomically save to log",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory (default: <repo_root>/data)",
    )
    return parser


def _demo_samples() -> list:
    return [
        {
            "protocol_name": "Lido stETH",
            "staking_apy_pct": 3.8,
            "consensus_yield_pct": 3.0,
            "mev_yield_pct": 0.5,
            "token_inflation_pct": 0.5,
            "restaking_boost_pct": 0.3,
            "slashing_risk_pct": 0.01,
            "network_participation_rate_pct": 65.0,
        },
        {
            "protocol_name": "EtherFi eETH (restaking)",
            "staking_apy_pct": 5.5,
            "consensus_yield_pct": 3.0,
            "mev_yield_pct": 0.5,
            "token_inflation_pct": 1.0,
            "restaking_boost_pct": 2.0,
            "slashing_risk_pct": 0.05,
            "network_participation_rate_pct": 60.0,
        },
        {
            "protocol_name": "HighInflationToken Stake",
            "staking_apy_pct": 20.0,
            "consensus_yield_pct": 2.0,
            "mev_yield_pct": 0.5,
            "token_inflation_pct": 18.0,
            "restaking_boost_pct": 0.0,
            "slashing_risk_pct": 0.1,
            "network_participation_rate_pct": 30.0,
        },
    ]


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    if not args.check and not args.run:
        parser.print_help()
        sys.exit(0)

    save_flag = args.run
    samples = _demo_samples()

    for s in samples:
        result = analyze(
            protocol_name=s["protocol_name"],
            staking_apy_pct=s["staking_apy_pct"],
            consensus_yield_pct=s["consensus_yield_pct"],
            mev_yield_pct=s["mev_yield_pct"],
            token_inflation_pct=s["token_inflation_pct"],
            restaking_boost_pct=s["restaking_boost_pct"],
            slashing_risk_pct=s["slashing_risk_pct"],
            network_participation_rate_pct=s["network_participation_rate_pct"],
            data_dir=args.data_dir,
            save=save_flag,
        )
        print(json.dumps(result, indent=2))

    sys.exit(0)

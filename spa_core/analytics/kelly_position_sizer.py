"""
MP-719: KellyPositionSizer
Compute the optimal fraction of capital to allocate using the Kelly criterion,
plus its risk-managed fractional variants (half- and quarter-Kelly). Two entry
points are supported: a continuous **mean-variance** Kelly derived from a return
series, and the classic **discrete-odds** Kelly derived from a win probability and
a win/loss payoff ratio. Raw Kelly can exceed 1.0 (implied leverage) or go negative
(no edge); this module always reports the raw value, a capped value, and a
conservative fractional recommendation, then classifies the aggressiveness tier and
emits advisory guidance about ruin risk. Pure stdlib only. Advisory/read-only.
Atomic writes.

Note: this is distinct from ``position_sizing_engine.py`` (MP-626), which performs
risk-parity / tier-cap portfolio construction. This module is purely about the
Kelly criterion and fractional-Kelly risk management for a single bet/strategy.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/kelly_position_log.json")
MAX_ENTRIES = 100

# Default per-period risk-free rate (fraction) subtracted from the mean return.
DEFAULT_RISK_FREE_PER_PERIOD = 0.0
# Default cap on the allocatable fraction (1.0 = full capital, no leverage).
DEFAULT_CAP = 1.0

# Threshold below which the return variance is treated as exactly zero
# (Kelly is undefined for a zero-variance series).
_ZERO_VAR_EPS = 1e-12

# Aggressiveness tiers keyed on the *raw* (uncapped) Kelly fraction.
KELLY_CONSERVATIVE_MAX = 0.25
KELLY_MODERATE_MAX = 0.50
KELLY_AGGRESSIVE_MAX = 1.0
# < 0 => NEGATIVE ; > 1.0 => EXTREME


@dataclass
class KellyReport:
    method: str                      # "RETURNS" / "ODDS" / "UNKNOWN"
    num_samples: int                 # number of return samples (0 for ODDS)
    win_prob: Optional[float]        # ODDS only (None for RETURNS)
    win_loss_ratio: Optional[float]  # ODDS only (None for RETURNS)
    kelly_fraction: float            # raw; may be < 0 or > 1
    capped_fraction: float           # clamped to [0, cap]
    half_kelly: float                # capped_fraction / 2
    quarter_kelly: float             # capped_fraction / 4
    recommended_fraction: float      # = half_kelly, clamped to [0, cap]
    aggressiveness_tier: str         # NEGATIVE/CONSERVATIVE/MODERATE/AGGRESSIVE/EXTREME/UNKNOWN
    cap: float
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


class KellyPositionSizer:
    """
    Computes Kelly-criterion position sizing (mean-variance and discrete-odds)
    with conservative fractional-Kelly recommendations.
    Advisory only — never modifies allocator, risk, or execution domains.
    """

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mean(xs: List[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    @staticmethod
    def _sample_variance(xs: List[float], mean: float) -> float:
        """Sample (n-1) variance. 0.0 for fewer than 2 points."""
        if len(xs) < 2:
            return 0.0
        return sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)

    @staticmethod
    def _classify(kelly_fraction: float) -> str:
        if kelly_fraction < 0.0:
            return "NEGATIVE"
        if kelly_fraction <= KELLY_CONSERVATIVE_MAX:
            return "CONSERVATIVE"
        if kelly_fraction <= KELLY_MODERATE_MAX:
            return "MODERATE"
        if kelly_fraction <= KELLY_AGGRESSIVE_MAX:
            return "AGGRESSIVE"
        return "EXTREME"

    @staticmethod
    def _build_advisory(tier: str, kelly_fraction: float, cap: float) -> List[str]:
        out: List[str] = []
        if tier == "NEGATIVE":
            out.append("No edge detected — do not allocate (raw Kelly is negative)")
        elif tier == "CONSERVATIVE":
            out.append("Small positive edge — conservative Kelly sizing")
        elif tier == "MODERATE":
            out.append("Moderate edge — Kelly sizing is reasonable")
        elif tier == "AGGRESSIVE":
            out.append("Strong edge — full Kelly is aggressive; fractional Kelly advised")
        elif tier == "EXTREME":
            out.append(
                f"Raw Kelly {kelly_fraction:.3f} implies leverage; capped at {cap:.2f} — "
                "use fractional Kelly to limit drawdown risk"
            )
        # Universal fractional-Kelly guidance to reduce risk of ruin.
        out.append(
            "Recommend fractional (half / quarter) Kelly to reduce risk of ruin from "
            "estimation error"
        )
        return out

    def _finalize(
        self,
        method: str,
        kelly_fraction: float,
        cap: float,
        num_samples: int = 0,
        win_prob: Optional[float] = None,
        win_loss_ratio: Optional[float] = None,
        extra_advisory: Optional[List[str]] = None,
    ) -> KellyReport:
        """Shared post-processing: clamping, fractional Kelly, tiering, advisory."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        safe_cap = cap if cap and cap > 0 else DEFAULT_CAP

        capped_fraction = min(max(kelly_fraction, 0.0), safe_cap)
        half_kelly = capped_fraction / 2.0
        quarter_kelly = capped_fraction / 4.0
        recommended_fraction = min(max(half_kelly, 0.0), safe_cap)

        tier = self._classify(kelly_fraction)
        advisory = list(extra_advisory or [])
        advisory.extend(self._build_advisory(tier, kelly_fraction, safe_cap))

        return KellyReport(
            method=method,
            num_samples=num_samples,
            win_prob=win_prob,
            win_loss_ratio=win_loss_ratio,
            kelly_fraction=round(kelly_fraction, 6),
            capped_fraction=round(capped_fraction, 6),
            half_kelly=round(half_kelly, 6),
            quarter_kelly=round(quarter_kelly, 6),
            recommended_fraction=round(recommended_fraction, 6),
            aggressiveness_tier=tier,
            cap=round(safe_cap, 6),
            advisory=advisory,
            generated_at=generated_at,
        )

    def _unknown(
        self,
        method: str,
        cap: float,
        advisory: List[str],
        num_samples: int = 0,
        win_prob: Optional[float] = None,
        win_loss_ratio: Optional[float] = None,
    ) -> KellyReport:
        """Build an UNKNOWN report when inputs are insufficient/invalid."""
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        safe_cap = cap if cap and cap > 0 else DEFAULT_CAP
        return KellyReport(
            method="UNKNOWN",
            num_samples=num_samples,
            win_prob=win_prob,
            win_loss_ratio=win_loss_ratio,
            kelly_fraction=0.0,
            capped_fraction=0.0,
            half_kelly=0.0,
            quarter_kelly=0.0,
            recommended_fraction=0.0,
            aggressiveness_tier="UNKNOWN",
            cap=round(safe_cap, 6),
            advisory=advisory,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def kelly_from_returns(
        self,
        returns: List[float],
        risk_free_per_period: float = DEFAULT_RISK_FREE_PER_PERIOD,
        cap: float = DEFAULT_CAP,
    ) -> KellyReport:
        """
        Mean-variance (continuous) Kelly from a series of per-period returns.

        ``kelly_fraction = (mean - risk_free_per_period) / variance``

        Requires at least 2 samples; otherwise returns an UNKNOWN report. A
        near-zero variance makes Kelly undefined, so the fraction is reported as
        0.0 with an advisory note.
        """
        n = len(returns)
        if n < 2:
            return self._unknown(
                "RETURNS",
                cap,
                ["Need at least 2 return samples to compute Kelly fraction"],
                num_samples=n,
            )

        mean = self._mean(returns)
        var = self._sample_variance(returns, mean)
        if var < _ZERO_VAR_EPS:
            return self._finalize(
                "RETURNS",
                0.0,
                cap,
                num_samples=n,
                extra_advisory=["Zero variance — Kelly undefined"],
            )

        excess = mean - risk_free_per_period
        kelly_fraction = excess / var
        return self._finalize(
            "RETURNS",
            kelly_fraction,
            cap,
            num_samples=n,
        )

    def kelly_from_odds(
        self,
        win_prob: float,
        win_loss_ratio: float,
        cap: float = DEFAULT_CAP,
    ) -> KellyReport:
        """
        Discrete-odds Kelly from a win probability and a win/loss payoff ratio.

        ``b = win_loss_ratio`` is the net amount won per unit staked on a win.
        ``kelly_fraction = (win_prob * b - (1 - win_prob)) / b``

        Guards: ``win_prob`` must be in [0, 1] and ``b`` must be > 0; otherwise an
        UNKNOWN report is returned with an advisory.
        """
        if not (0.0 <= win_prob <= 1.0):
            return self._unknown(
                "ODDS",
                cap,
                ["win_prob must be in [0, 1] — cannot compute Kelly fraction"],
                win_prob=win_prob,
                win_loss_ratio=win_loss_ratio,
            )
        if win_loss_ratio <= 0:
            return self._unknown(
                "ODDS",
                cap,
                ["win_loss_ratio must be positive — cannot compute Kelly fraction"],
                win_prob=win_prob,
                win_loss_ratio=win_loss_ratio,
            )

        b = win_loss_ratio
        kelly_fraction = (win_prob * b - (1.0 - win_prob)) / b
        return self._finalize(
            "ODDS",
            kelly_fraction,
            cap,
            num_samples=0,
            win_prob=win_prob,
            win_loss_ratio=win_loss_ratio,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: KellyReport, data_file: Path = DATA_FILE) -> None:
        """Append a report to a ring-buffer JSON (max MAX_ENTRIES). Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": report.method,
            "num_samples": report.num_samples,
            "win_prob": report.win_prob,
            "win_loss_ratio": report.win_loss_ratio,
            "kelly_fraction": report.kelly_fraction,
            "capped_fraction": report.capped_fraction,
            "half_kelly": report.half_kelly,
            "quarter_kelly": report.quarter_kelly,
            "recommended_fraction": report.recommended_fraction,
            "aggressiveness_tier": report.aggressiveness_tier,
            "cap": report.cap,
            "advisory": report.advisory,
        }

        combined = (existing + [entry])[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load history from ring-buffer JSON. Returns [] if missing or corrupt."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    sizer = KellyPositionSizer()

    # Mean-variance Kelly from a per-period return series.
    returns = [0.012, 0.008, -0.004, 0.015, 0.006, 0.010, -0.002, 0.009]
    r1 = sizer.kelly_from_returns(returns, risk_free_per_period=0.003)
    print("=== kelly_from_returns ===")
    print(f"Method:               {r1.method}")
    print(f"Samples:              {r1.num_samples}")
    print(f"Raw Kelly:            {r1.kelly_fraction:.6f}")
    print(f"Capped fraction:      {r1.capped_fraction:.6f}")
    print(f"Half Kelly:           {r1.half_kelly:.6f}")
    print(f"Quarter Kelly:        {r1.quarter_kelly:.6f}")
    print(f"Recommended:          {r1.recommended_fraction:.6f}")
    print(f"Aggressiveness tier:  {r1.aggressiveness_tier}")
    for line in r1.advisory:
        print(f"  - {line}")

    # Discrete-odds Kelly from win probability and payoff ratio.
    r2 = sizer.kelly_from_odds(win_prob=0.55, win_loss_ratio=1.2)
    print("=== kelly_from_odds ===")
    print(f"Method:               {r2.method}")
    print(f"Win prob:             {r2.win_prob}")
    print(f"Win/loss ratio:       {r2.win_loss_ratio}")
    print(f"Raw Kelly:            {r2.kelly_fraction:.6f}")
    print(f"Capped fraction:      {r2.capped_fraction:.6f}")
    print(f"Half Kelly:           {r2.half_kelly:.6f}")
    print(f"Quarter Kelly:        {r2.quarter_kelly:.6f}")
    print(f"Recommended:          {r2.recommended_fraction:.6f}")
    print(f"Aggressiveness tier:  {r2.aggressiveness_tier}")
    for line in r2.advisory:
        print(f"  - {line}")


if __name__ == "__main__":
    _demo()

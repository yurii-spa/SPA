"""
MP-1124: DeFiProtocolBorrowRateModeOptimizer

For Aave-style lending markets that offer BOTH a stable and a variable
borrow-rate mode, decide which mode minimizes expected borrow cost for a
leveraged / looping yield farmer, given current rates and a forward
variable-rate volatility / drift forecast.

Borrowers who loop (recursive deposit/borrow) are sensitive to the borrow
leg: a variable rate that drifts up can flip a position from positive to
negative carry, while a "stable" rate carries protocol re-pricing risk.
This module is purely advisory — it never changes a position.

Cost model (all in APR percentage points):
  1. expected_variable_apr_pct   = variable_borrow_apr_pct + variable_rate_drift_pct
       (time-weighted simple mean over the horizon; mid-point approximation)
  2. variable_apr_p95_pct        = expected_variable_apr_pct + 1.645 * variable_rate_volatility_pct
  3. expected_cost_stable_pct    = stable_borrow_apr_pct
       NOTE: the headline stable cost is NOT inflated by rebalance risk.
       Aave's "stable" rate is the rate the borrower pays; the protocol can
       re-price ("rebalance") it against the borrower under certain liquidity
       conditions, but that uncertainty is captured separately in
       `stable_certainty_score` rather than folded into the cost number.
       (The formula stable_borrow_apr_pct * (1 + risk/100 * 0.0) reduces to
       stable_borrow_apr_pct by design — the 0.0 multiplier documents intent.)
  4. expected_cost_variable_pct  = expected_variable_apr_pct
  5. cost_advantage_variable_pct = expected_cost_stable_pct - expected_cost_variable_pct
       (positive  => variable is cheaper in expectation)
  6. worst_case_cost_variable_pct = variable_apr_p95_pct
  7. breakeven_variable_apr_pct  = stable_borrow_apr_pct
       (the variable APR at which the two modes cost the same)
  8. headroom_to_breakeven_pct   = breakeven_variable_apr_pct - expected_variable_apr_pct
  9. net_carry_stable_pct        = farm_apr_pct - expected_cost_stable_pct
 10. net_carry_variable_pct      = farm_apr_pct - expected_cost_variable_pct
 11. net_carry_variable_p95_pct  = farm_apr_pct - worst_case_cost_variable_pct
 12. stable_certainty_score 0-100 = 100 - penalty(stable_rate_rebalance_risk_pct)
 13. mode_recommendation_score 0-100 (higher => prefer VARIABLE)

cost_regime (by cost_advantage_variable_pct):
  >= +3.0            => VARIABLE_STRONGLY_CHEAPER
  +1.0 .. +3.0       => VARIABLE_CHEAPER
  -1.0 .. +1.0       => NEAR_PARITY      (|adv| < 1.0)
  -3.0 .. -1.0       => STABLE_CHEAPER
  <= -3.0            => STABLE_STRONGLY_CHEAPER

recommended_mode: STABLE / VARIABLE / INDIFFERENT
  INDIFFERENT when |cost_advantage_variable_pct| <= 0.10 (epsilon).

grade A-F: derived from mode_recommendation_score clarity AND carry quality
  (a position with strong negative p95 carry is penalised regardless of which
  mode is cheaper).

Pure stdlib only.  Advisory / read-only — never modifies allocator, risk,
execution, or monitoring domains.  Atomic writes (tmp + os.replace).
Log file: data/borrow_rate_mode_optimizer_log.json  (ring-buffer, cap 100).
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/borrow_rate_mode_optimizer_log.json")
MAX_ENTRIES: int = 100

# p95 one-sided z-score
_Z95 = 1.645

# Epsilon for INDIFFERENT recommendation
_INDIFFERENT_EPS = 0.10

# cost_advantage_variable_pct thresholds for cost_regime
_REGIME_STRONG = 3.0
_REGIME_MILD = 1.0
_REGIME_PARITY = 0.10  # boundary inside NEAR_PARITY for NEAR_BREAKEVEN flag

# Recommended modes
_MODE_STABLE = "STABLE"
_MODE_VARIABLE = "VARIABLE"
_MODE_INDIFFERENT = "INDIFFERENT"

# Cost regimes
_REGIME_VAR_STRONG = "VARIABLE_STRONGLY_CHEAPER"
_REGIME_VAR = "VARIABLE_CHEAPER"
_REGIME_NEAR = "NEAR_PARITY"
_REGIME_STABLE = "STABLE_CHEAPER"
_REGIME_STABLE_STRONG = "STABLE_STRONGLY_CHEAPER"

# Volatility threshold (percentage points) for HIGH_RATE_VOLATILITY flag
_HIGH_VOL_PCT = 3.0
# Stable rebalance-risk threshold (percent) for STABLE_REBALANCE_RISK flag
_HIGH_REBALANCE_RISK_PCT = 40.0
# Headroom threshold (pct points) for NEAR_BREAKEVEN flag
_NEAR_BREAKEVEN_HEADROOM = 0.5
# Drift thresholds (pct points) for rising / falling flags
_RATE_MOVE_EPS = 0.05

# Grades
_GRADE_A = "A"
_GRADE_B = "B"
_GRADE_C = "C"
_GRADE_D = "D"
_GRADE_F = "F"

# Flags
_FLAG_VARIABLE_CHEAPER_NOW = "VARIABLE_CHEAPER_NOW"
_FLAG_STABLE_SAFER_TAIL = "STABLE_SAFER_TAIL"
_FLAG_NEGATIVE_CARRY_AT_P95 = "NEGATIVE_CARRY_AT_P95"
_FLAG_HIGH_RATE_VOLATILITY = "HIGH_RATE_VOLATILITY"
_FLAG_STABLE_REBALANCE_RISK = "STABLE_REBALANCE_RISK"
_FLAG_NEAR_BREAKEVEN = "NEAR_BREAKEVEN"
_FLAG_RISING_VARIABLE_RATE = "RISING_VARIABLE_RATE"
_FLAG_FALLING_VARIABLE_RATE = "FALLING_VARIABLE_RATE"
_FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class BorrowRateModeReport:
    protocol_name: str
    stable_borrow_apr_pct: float
    variable_borrow_apr_pct: float
    variable_rate_drift_pct: float
    variable_rate_volatility_pct: float
    horizon_days: int
    farm_apr_pct: float
    borrow_amount_usd: float
    stable_rate_rebalance_risk_pct: float

    # Computed outputs
    expected_variable_apr_pct: float
    variable_apr_p95_pct: float
    expected_cost_stable_pct: float
    expected_cost_variable_pct: float
    cost_advantage_variable_pct: float
    worst_case_cost_variable_pct: float
    breakeven_variable_apr_pct: float
    headroom_to_breakeven_pct: float
    net_carry_stable_pct: float
    net_carry_variable_pct: float
    net_carry_variable_p95_pct: float
    stable_certainty_score: float
    mode_recommendation_score: float
    recommended_mode: str
    cost_regime: str
    grade: str

    flags: List[str] = field(default_factory=list)
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class DeFiProtocolBorrowRateModeOptimizer:
    """
    Recommends STABLE vs VARIABLE borrow-rate mode for an Aave-style market,
    minimising expected borrow cost while accounting for variable-rate
    volatility and stable-rate rebalance risk.

    Advisory only — never modifies allocator, risk, execution, or monitoring
    domains.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_regime(cost_advantage_variable_pct: float) -> str:
        """Map cost_advantage_variable_pct -> cost_regime string."""
        adv = cost_advantage_variable_pct
        if adv >= _REGIME_STRONG:
            return _REGIME_VAR_STRONG
        if adv >= _REGIME_MILD:
            return _REGIME_VAR
        if adv <= -_REGIME_STRONG:
            return _REGIME_STABLE_STRONG
        if adv <= -_REGIME_MILD:
            return _REGIME_STABLE
        return _REGIME_NEAR

    @staticmethod
    def _classify_mode(cost_advantage_variable_pct: float,
                       mode_recommendation_score: float) -> str:
        """Map outputs -> recommended_mode string."""
        if abs(cost_advantage_variable_pct) <= _INDIFFERENT_EPS:
            return _MODE_INDIFFERENT
        if mode_recommendation_score >= 50.0:
            return _MODE_VARIABLE
        return _MODE_STABLE

    @staticmethod
    def _stable_certainty(stable_rate_rebalance_risk_pct: float) -> float:
        """
        100 minus a penalty scaled by rebalance risk.  The penalty is the
        rebalance-risk probability itself (clamped 0-100), so a 30% rebalance
        risk -> certainty 70.
        """
        risk = stable_rate_rebalance_risk_pct
        if risk < 0.0:
            risk = 0.0
        if risk > 100.0:
            risk = 100.0
        return 100.0 - risk

    @staticmethod
    def _recommendation_score(
        cost_advantage_variable_pct: float,
        net_carry_variable_p95_pct: float,
        stable_certainty_score: float,
    ) -> float:
        """
        Blend (higher => prefer VARIABLE), clamped 0-100.

        Components:
          - cost advantage: 50 + 8 * cost_advantage (variable cheaper pushes up)
          - tail protection: if p95 carry goes negative, push DOWN toward STABLE
          - stable certainty: low stable certainty pushes UP toward VARIABLE
        """
        score = 50.0 + 8.0 * cost_advantage_variable_pct

        # Tail: negative p95 carry favours STABLE (the locked rate caps the
        # downside), so subtract a penalty proportional to the shortfall.
        if net_carry_variable_p95_pct < 0.0:
            score -= min(40.0, abs(net_carry_variable_p95_pct) * 4.0)

        # Stable certainty: when the stable rate is unreliable (low certainty),
        # variable becomes relatively more attractive.
        certainty_gap = 100.0 - stable_certainty_score  # 0 = perfectly certain
        score += certainty_gap * 0.15

        if score < 0.0:
            score = 0.0
        if score > 100.0:
            score = 100.0
        return score

    @staticmethod
    def _classify_grade(
        mode_recommendation_score: float,
        net_carry_variable_pct: float,
        net_carry_stable_pct: float,
        net_carry_variable_p95_pct: float,
    ) -> str:
        """
        Grade A-F from decision clarity + carry quality.

        Clarity: how far the recommendation score is from the 50 midpoint.
        Carry quality: best achievable carry across modes; penalise if even
        the best mode is unprofitable, and penalise tail risk.
        """
        clarity = abs(mode_recommendation_score - 50.0)  # 0..50
        best_carry = max(net_carry_variable_pct, net_carry_stable_pct)

        if best_carry <= 0.0:
            # Even the cheaper mode loses money -> at best a D, F if deeply so.
            if best_carry <= -2.0:
                return _GRADE_F
            return _GRADE_D

        # Profitable: blend clarity and a tail-protection bonus.
        score = clarity  # 0..50
        if net_carry_variable_p95_pct >= 0.0:
            score += 15.0  # tail is safe even in variable mode
        if best_carry >= 3.0:
            score += 10.0

        if score >= 55.0:
            return _GRADE_A
        if score >= 40.0:
            return _GRADE_B
        if score >= 25.0:
            return _GRADE_C
        if score >= 12.0:
            return _GRADE_D
        return _GRADE_F

    @staticmethod
    def _build_flags(
        cost_advantage_variable_pct: float,
        net_carry_variable_p95_pct: float,
        variable_rate_volatility_pct: float,
        stable_rate_rebalance_risk_pct: float,
        headroom_to_breakeven_pct: float,
        variable_rate_drift_pct: float,
        insufficient: bool,
    ) -> List[str]:
        flags: List[str] = []
        if insufficient:
            flags.append(_FLAG_INSUFFICIENT_DATA)
            return flags

        if cost_advantage_variable_pct > _INDIFFERENT_EPS:
            flags.append(_FLAG_VARIABLE_CHEAPER_NOW)
        if net_carry_variable_p95_pct < 0.0:
            flags.append(_FLAG_NEGATIVE_CARRY_AT_P95)
            # The locked stable rate protects the tail.
            flags.append(_FLAG_STABLE_SAFER_TAIL)
        if variable_rate_volatility_pct >= _HIGH_VOL_PCT:
            flags.append(_FLAG_HIGH_RATE_VOLATILITY)
        if stable_rate_rebalance_risk_pct >= _HIGH_REBALANCE_RISK_PCT:
            flags.append(_FLAG_STABLE_REBALANCE_RISK)
        if abs(headroom_to_breakeven_pct) <= _NEAR_BREAKEVEN_HEADROOM:
            flags.append(_FLAG_NEAR_BREAKEVEN)
        if variable_rate_drift_pct > _RATE_MOVE_EPS:
            flags.append(_FLAG_RISING_VARIABLE_RATE)
        elif variable_rate_drift_pct < -_RATE_MOVE_EPS:
            flags.append(_FLAG_FALLING_VARIABLE_RATE)
        return flags

    @staticmethod
    def _build_advisory(
        protocol_name: str,
        recommended_mode: str,
        cost_regime: str,
        cost_advantage_variable_pct: float,
        net_carry_variable_p95_pct: float,
        stable_certainty_score: float,
        flags: List[str],
        insufficient: bool,
    ) -> List[str]:
        msgs: List[str] = []
        if insufficient:
            msgs.append(
                f"{protocol_name}: insufficient data to choose a borrow-rate "
                f"mode (missing or invalid rate inputs)"
            )
            return msgs

        if recommended_mode == _MODE_VARIABLE:
            msgs.append(
                f"{protocol_name}: recommend VARIABLE mode — variable is "
                f"{cost_advantage_variable_pct:.2f}pp cheaper in expectation "
                f"({cost_regime})"
            )
        elif recommended_mode == _MODE_STABLE:
            msgs.append(
                f"{protocol_name}: recommend STABLE mode — locks the borrow "
                f"cost ({cost_regime}); advantage to variable is "
                f"{cost_advantage_variable_pct:.2f}pp"
            )
        else:
            msgs.append(
                f"{protocol_name}: modes are near parity "
                f"({cost_advantage_variable_pct:.2f}pp) — INDIFFERENT; pick on "
                f"non-cost factors"
            )

        if _FLAG_NEGATIVE_CARRY_AT_P95 in flags:
            msgs.append(
                f"{protocol_name}: variable-mode carry turns NEGATIVE in the "
                f"p95 stress ({net_carry_variable_p95_pct:.2f}pp) — the stable "
                f"rate caps this tail risk"
            )
        if _FLAG_STABLE_REBALANCE_RISK in flags:
            msgs.append(
                f"{protocol_name}: stable-rate certainty is low "
                f"({stable_certainty_score:.0f}/100) — the protocol may "
                f"re-price the stable rate against you"
            )
        if _FLAG_HIGH_RATE_VOLATILITY in flags:
            msgs.append(
                f"{protocol_name}: forward variable-rate volatility is high — "
                f"the variable cost is uncertain"
            )
        if _FLAG_NEAR_BREAKEVEN in flags:
            msgs.append(
                f"{protocol_name}: the expected variable rate sits very close "
                f"to the stable breakeven — the decision is marginal"
            )
        return msgs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        stable_borrow_apr_pct: float,
        variable_borrow_apr_pct: float,
        variable_rate_drift_pct: float,
        variable_rate_volatility_pct: float,
        horizon_days: int,
        farm_apr_pct: float,
        borrow_amount_usd: float,
        stable_rate_rebalance_risk_pct: float,
        protocol_name: str,
    ) -> BorrowRateModeReport:
        """
        Decide STABLE vs VARIABLE borrow mode and return a BorrowRateModeReport.

        Parameters
        ----------
        stable_borrow_apr_pct          : locked stable borrow rate offered now (%)
        variable_borrow_apr_pct        : current variable borrow rate (%)
        variable_rate_drift_pct        : expected change in variable APR over
                                         the horizon, +/- (percentage points)
        variable_rate_volatility_pct   : forward stdev of variable APR (pp)
        horizon_days                   : holding horizon in days (>= 1)
        farm_apr_pct                   : gross yield on the borrowed capital (%)
        borrow_amount_usd              : USD size of the borrow
        stable_rate_rebalance_risk_pct : 0-100 probability the protocol
                                         re-prices the stable rate against the
                                         borrower (haircuts stable certainty)
        protocol_name                  : human-readable market label
        """
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # ---- Coerce / clamp inputs ----
        stable = float(stable_borrow_apr_pct)
        var = float(variable_borrow_apr_pct)
        drift = float(variable_rate_drift_pct)
        vol = float(variable_rate_volatility_pct)
        if vol < 0.0:
            vol = 0.0  # stdev cannot be negative
        hz = max(1, int(horizon_days))
        farm = float(farm_apr_pct)
        amount = float(borrow_amount_usd)
        rebalance_risk = float(stable_rate_rebalance_risk_pct)

        # ---- INSUFFICIENT_DATA path ----
        # Need at least one usable rate; non-finite inputs are unusable.
        insufficient = False
        for v in (stable, var, drift, vol, farm):
            if not math.isfinite(v):
                insufficient = True
                break
        if (stable == 0.0 and var == 0.0):
            insufficient = True

        if insufficient:
            flags = self._build_flags(
                0.0, 0.0, 0.0, 0.0, 0.0, 0.0, insufficient=True
            )
            advisory = self._build_advisory(
                protocol_name, _MODE_INDIFFERENT, _REGIME_NEAR,
                0.0, 0.0, 0.0, flags, insufficient=True
            )
            return BorrowRateModeReport(
                protocol_name=protocol_name,
                stable_borrow_apr_pct=round(stable, 8),
                variable_borrow_apr_pct=round(var, 8),
                variable_rate_drift_pct=round(drift, 8),
                variable_rate_volatility_pct=round(vol, 8),
                horizon_days=hz,
                farm_apr_pct=round(farm, 8),
                borrow_amount_usd=amount,
                stable_rate_rebalance_risk_pct=round(rebalance_risk, 8),
                expected_variable_apr_pct=0.0,
                variable_apr_p95_pct=0.0,
                expected_cost_stable_pct=0.0,
                expected_cost_variable_pct=0.0,
                cost_advantage_variable_pct=0.0,
                worst_case_cost_variable_pct=0.0,
                breakeven_variable_apr_pct=0.0,
                headroom_to_breakeven_pct=0.0,
                net_carry_stable_pct=0.0,
                net_carry_variable_pct=0.0,
                net_carry_variable_p95_pct=0.0,
                stable_certainty_score=0.0,
                mode_recommendation_score=0.0,
                recommended_mode=_MODE_INDIFFERENT,
                cost_regime=_REGIME_NEAR,
                grade=_GRADE_F,
                flags=flags,
                advisory=advisory,
                generated_at=generated_at,
            )

        # ---- Core computation ----
        expected_variable = var + drift
        variable_p95 = expected_variable + _Z95 * vol

        # Headline stable cost is NOT inflated by rebalance risk (documented in
        # the module docstring); the rebalance risk feeds stable_certainty.
        expected_cost_stable = stable * (1.0 + rebalance_risk / 100.0 * 0.0)
        expected_cost_variable = expected_variable

        cost_advantage_variable = expected_cost_stable - expected_cost_variable
        worst_case_cost_variable = variable_p95
        breakeven_variable = stable
        headroom_to_breakeven = breakeven_variable - expected_variable

        net_carry_stable = farm - expected_cost_stable
        net_carry_variable = farm - expected_cost_variable
        net_carry_variable_p95 = farm - worst_case_cost_variable

        stable_certainty = self._stable_certainty(rebalance_risk)
        recommendation_score = self._recommendation_score(
            cost_advantage_variable, net_carry_variable_p95, stable_certainty
        )
        recommended_mode = self._classify_mode(
            cost_advantage_variable, recommendation_score
        )
        cost_regime = self._classify_regime(cost_advantage_variable)
        grade = self._classify_grade(
            recommendation_score, net_carry_variable, net_carry_stable,
            net_carry_variable_p95,
        )

        flags = self._build_flags(
            cost_advantage_variable, net_carry_variable_p95, vol,
            rebalance_risk, headroom_to_breakeven, drift, insufficient=False,
        )
        advisory = self._build_advisory(
            protocol_name, recommended_mode, cost_regime,
            cost_advantage_variable, net_carry_variable_p95, stable_certainty,
            flags, insufficient=False,
        )

        return BorrowRateModeReport(
            protocol_name=protocol_name,
            stable_borrow_apr_pct=round(stable, 8),
            variable_borrow_apr_pct=round(var, 8),
            variable_rate_drift_pct=round(drift, 8),
            variable_rate_volatility_pct=round(vol, 8),
            horizon_days=hz,
            farm_apr_pct=round(farm, 8),
            borrow_amount_usd=amount,
            stable_rate_rebalance_risk_pct=round(rebalance_risk, 8),
            expected_variable_apr_pct=round(expected_variable, 8),
            variable_apr_p95_pct=round(variable_p95, 8),
            expected_cost_stable_pct=round(expected_cost_stable, 8),
            expected_cost_variable_pct=round(expected_cost_variable, 8),
            cost_advantage_variable_pct=round(cost_advantage_variable, 8),
            worst_case_cost_variable_pct=round(worst_case_cost_variable, 8),
            breakeven_variable_apr_pct=round(breakeven_variable, 8),
            headroom_to_breakeven_pct=round(headroom_to_breakeven, 8),
            net_carry_stable_pct=round(net_carry_stable, 8),
            net_carry_variable_pct=round(net_carry_variable, 8),
            net_carry_variable_p95_pct=round(net_carry_variable_p95, 8),
            stable_certainty_score=round(stable_certainty, 8),
            mode_recommendation_score=round(recommendation_score, 8),
            recommended_mode=recommended_mode,
            cost_regime=cost_regime,
            grade=grade,
            flags=flags,
            advisory=advisory,
            generated_at=generated_at,
        )

    def analyze_portfolio(self, positions: List[dict]) -> dict:
        """
        Summarise a list of position dicts (each forwarded as kwargs to
        ``analyze``).  Returns cheapest / most-expensive market summary,
        average recommendation score, recommended-mode counts, and a
        negative-carry count.
        """
        if not positions:
            return {
                "count": 0,
                "cheapest_variable_market": None,
                "most_expensive_variable_market": None,
                "avg_mode_recommendation_score": 0.0,
                "recommend_stable_count": 0,
                "recommend_variable_count": 0,
                "recommend_indifferent_count": 0,
                "negative_carry_count": 0,
            }

        reports: List[BorrowRateModeReport] = []
        for pos in positions:
            reports.append(self.analyze(**pos))

        usable = [r for r in reports
                  if _FLAG_INSUFFICIENT_DATA not in r.flags]

        if usable:
            cheapest = min(usable, key=lambda r: r.expected_cost_variable_pct)
            dearest = max(usable, key=lambda r: r.expected_cost_variable_pct)
            cheapest_name = cheapest.protocol_name
            dearest_name = dearest.protocol_name
        else:
            cheapest_name = None
            dearest_name = None

        total_score = sum(r.mode_recommendation_score for r in reports)
        avg_score = total_score / len(reports) if reports else 0.0

        stable_count = sum(
            1 for r in reports if r.recommended_mode == _MODE_STABLE
        )
        variable_count = sum(
            1 for r in reports if r.recommended_mode == _MODE_VARIABLE
        )
        indifferent_count = sum(
            1 for r in reports if r.recommended_mode == _MODE_INDIFFERENT
        )
        negative_carry_count = sum(
            1 for r in reports
            if max(r.net_carry_stable_pct, r.net_carry_variable_pct) <= 0.0
            and _FLAG_INSUFFICIENT_DATA not in r.flags
        )

        return {
            "count": len(reports),
            "cheapest_variable_market": cheapest_name,
            "most_expensive_variable_market": dearest_name,
            "avg_mode_recommendation_score": round(avg_score, 8),
            "recommend_stable_count": stable_count,
            "recommend_variable_count": variable_count,
            "recommend_indifferent_count": indifferent_count,
            "negative_carry_count": negative_carry_count,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self,
        report: BorrowRateModeReport,
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append report to ring-buffer JSON (cap MAX_ENTRIES).  Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "protocol_name": report.protocol_name,
            "stable_borrow_apr_pct": report.stable_borrow_apr_pct,
            "variable_borrow_apr_pct": report.variable_borrow_apr_pct,
            "expected_variable_apr_pct": report.expected_variable_apr_pct,
            "variable_apr_p95_pct": report.variable_apr_p95_pct,
            "cost_advantage_variable_pct": report.cost_advantage_variable_pct,
            "net_carry_stable_pct": report.net_carry_stable_pct,
            "net_carry_variable_pct": report.net_carry_variable_pct,
            "net_carry_variable_p95_pct": report.net_carry_variable_p95_pct,
            "stable_certainty_score": report.stable_certainty_score,
            "mode_recommendation_score": report.mode_recommendation_score,
            "recommended_mode": report.recommended_mode,
            "cost_regime": report.cost_regime,
            "grade": report.grade,
            "horizon_days": report.horizon_days,
            "borrow_amount_usd": report.borrow_amount_usd,
            "flags": report.flags,
            "advisory": report.advisory,
        }

        combined = (existing + [entry])[-MAX_ENTRIES:]

        data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = data_file.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(combined, fh, indent=2)
        os.replace(tmp, data_file)

    def load_history(self, data_file: Path = DATA_FILE) -> list:
        """Load ring-buffer JSON.  Returns [] on missing / corrupt file."""
        data_file = Path(data_file)
        if not data_file.exists():
            return []
        try:
            with open(data_file, "r") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo() -> None:
    ana = DeFiProtocolBorrowRateModeOptimizer()
    report = ana.analyze(
        stable_borrow_apr_pct=6.5,
        variable_borrow_apr_pct=4.8,
        variable_rate_drift_pct=0.8,
        variable_rate_volatility_pct=1.5,
        horizon_days=30,
        farm_apr_pct=9.0,
        borrow_amount_usd=100_000.0,
        stable_rate_rebalance_risk_pct=25.0,
        protocol_name="Aave V3 USDC",
    )
    print(f"Protocol:                  {report.protocol_name}")
    print(f"Stable borrow APR:         {report.stable_borrow_apr_pct:.4f}%")
    print(f"Variable borrow APR:       {report.variable_borrow_apr_pct:.4f}%")
    print(f"Expected variable APR:     {report.expected_variable_apr_pct:.4f}%")
    print(f"Variable p95 APR:          {report.variable_apr_p95_pct:.4f}%")
    print(f"Cost advantage (variable): {report.cost_advantage_variable_pct:.4f}pp")
    print(f"Headroom to breakeven:     {report.headroom_to_breakeven_pct:.4f}pp")
    print(f"Net carry (stable):        {report.net_carry_stable_pct:.4f}pp")
    print(f"Net carry (variable):      {report.net_carry_variable_pct:.4f}pp")
    print(f"Net carry (variable p95):  {report.net_carry_variable_p95_pct:.4f}pp")
    print(f"Stable certainty score:    {report.stable_certainty_score:.1f}/100")
    print(f"Mode recommendation score: {report.mode_recommendation_score:.1f}/100")
    print(f"Recommended mode:          {report.recommended_mode}")
    print(f"Cost regime:               {report.cost_regime}")
    print(f"Grade:                     {report.grade}")
    print(f"Flags:                     {', '.join(report.flags) or '(none)'}")
    for msg in report.advisory:
        print(f"  • {msg}")

    print()
    print("Portfolio summary:")
    summary = ana.analyze_portfolio([
        {
            "stable_borrow_apr_pct": 6.5, "variable_borrow_apr_pct": 4.8,
            "variable_rate_drift_pct": 0.8, "variable_rate_volatility_pct": 1.5,
            "horizon_days": 30, "farm_apr_pct": 9.0,
            "borrow_amount_usd": 100_000.0,
            "stable_rate_rebalance_risk_pct": 25.0,
            "protocol_name": "Aave V3 USDC",
        },
        {
            "stable_borrow_apr_pct": 5.0, "variable_borrow_apr_pct": 7.2,
            "variable_rate_drift_pct": 1.2, "variable_rate_volatility_pct": 4.0,
            "horizon_days": 60, "farm_apr_pct": 6.0,
            "borrow_amount_usd": 50_000.0,
            "stable_rate_rebalance_risk_pct": 10.0,
            "protocol_name": "Aave V3 DAI",
        },
    ])
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    _demo()

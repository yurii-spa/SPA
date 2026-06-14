"""
MP-1125: DeFiProtocolSupplyCapProximityAnalyzer

Deposit-SIDE analysis for Aave-V3-style markets that enforce a ``supplyCap``.
Quantifies how much headroom remains to deposit before the cap is hit, whether
the farmer's intended deposit even fits, and the yield / crowding risk that a
near-full cap implies.

A near-full supply cap is a leading signal of a crowded market: the closer
total supply sits to the cap, the more competition there is for the same
borrow demand, so the supply APR tends to compress.  A full cap also BLOCKS
future top-ups / compounding.  This is DISTINCT from the borrow-side debt
ceiling analyzer — here we look only at the deposit / supply cap.

Computation:
  1. utilization_of_cap_pct      = current_total_supply_usd / supply_cap_usd * 100   (guarded)
  2. remaining_headroom_usd      = max(0, supply_cap_usd - current_total_supply_usd)
  3. headroom_pct                = remaining_headroom_usd / supply_cap_usd * 100      (guarded)
  4. deposit_fits (bool)         = intended_deposit_usd <= remaining_headroom_usd
  5. fillable_pct_of_deposit     = min(100, remaining_headroom_usd / intended_deposit_usd * 100)  (guarded)
  6. days_until_cap_reached      = remaining_headroom_usd / recent_supply_growth_usd_per_day
       Only meaningful when growth > 0.  When growth <= 0 the cap will NOT be
       reached by growth, so we return the sentinel DAYS_SENTINEL_NEVER
       (a large finite number, see constant) and raise no CAP_REACHED_SOON flag.
  7. post_deposit_utilization_pct = (current_total_supply_usd
                                     + min(intended_deposit_usd, remaining_headroom_usd))
                                     / supply_cap_usd * 100                            (guarded)
  8. yield_compression_risk_pct 0-100 — rises with utilization_of_cap_pct
  9. cap_proximity_score 0-100 (higher = SAFER / more headroom)

classification (proximity_label, by utilization_of_cap_pct):
  < 60     => AMPLE_HEADROOM
  60 .. 85 => COMFORTABLE
  85 .. 95 => APPROACHING_CAP
  95 ..100 => NEAR_CAP
  >= 100   => AT_CAP
  supply_cap_usd <= 0 => UNCAPPED   (treated as no cap; INSUFFICIENT-ish path)

grade A-F: A = lots of headroom + deposit fits + slow fill; F = at cap /
deposit blocked.

flags: AT_CAP, NEAR_CAP, DEPOSIT_DOES_NOT_FIT, FAST_FILLING,
CAP_REACHED_SOON, AMPLE_HEADROOM, UNCAPPED_MARKET,
HIGH_YIELD_COMPRESSION_RISK, SHRINKING_SUPPLY, INSUFFICIENT_DATA.

Pure stdlib only.  Advisory / read-only — never modifies allocator, risk,
execution, or monitoring domains.  Atomic writes (tmp + os.replace).
Log file: data/supply_cap_proximity_log.json  (ring-buffer, cap 100).
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/supply_cap_proximity_log.json")
MAX_ENTRIES: int = 100

# Sentinel for "cap will never be reached by current growth" (growth <= 0).
# A large finite number so it serialises cleanly to JSON (no inf / NaN).
DAYS_SENTINEL_NEVER: float = 1.0e9

# utilization_of_cap_pct thresholds for proximity_label
_UTIL_AMPLE_MAX = 60.0
_UTIL_COMFORTABLE_MAX = 85.0
_UTIL_APPROACHING_MAX = 95.0
_UTIL_NEAR_MAX = 100.0

# Flag thresholds
_AMPLE_HEADROOM_UTIL_MAX = 60.0     # below this -> AMPLE_HEADROOM flag
_NEAR_CAP_UTIL_MIN = 95.0           # at/above -> NEAR_CAP flag
_FAST_FILLING_DAYS = 7.0            # days_until_cap < this -> FAST_FILLING
_CAP_REACHED_SOON_DAYS = 14.0       # days_until_cap < this -> CAP_REACHED_SOON
_HIGH_COMPRESSION_RISK_PCT = 70.0   # at/above -> HIGH_YIELD_COMPRESSION_RISK

# Proximity labels
_LABEL_AMPLE = "AMPLE_HEADROOM"
_LABEL_COMFORTABLE = "COMFORTABLE"
_LABEL_APPROACHING = "APPROACHING_CAP"
_LABEL_NEAR = "NEAR_CAP"
_LABEL_AT_CAP = "AT_CAP"
_LABEL_UNCAPPED = "UNCAPPED"

# Grades
_GRADE_A = "A"
_GRADE_B = "B"
_GRADE_C = "C"
_GRADE_D = "D"
_GRADE_F = "F"

# Flags
_FLAG_AT_CAP = "AT_CAP"
_FLAG_NEAR_CAP = "NEAR_CAP"
_FLAG_DEPOSIT_DOES_NOT_FIT = "DEPOSIT_DOES_NOT_FIT"
_FLAG_FAST_FILLING = "FAST_FILLING"
_FLAG_CAP_REACHED_SOON = "CAP_REACHED_SOON"
_FLAG_AMPLE_HEADROOM = "AMPLE_HEADROOM"
_FLAG_UNCAPPED_MARKET = "UNCAPPED_MARKET"
_FLAG_HIGH_YIELD_COMPRESSION_RISK = "HIGH_YIELD_COMPRESSION_RISK"
_FLAG_SHRINKING_SUPPLY = "SHRINKING_SUPPLY"
_FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class SupplyCapProximityReport:
    protocol_name: str
    current_total_supply_usd: float
    supply_cap_usd: float
    intended_deposit_usd: float
    current_supply_apr_pct: float
    recent_supply_growth_usd_per_day: float

    # Computed outputs
    utilization_of_cap_pct: float
    remaining_headroom_usd: float
    headroom_pct: float
    deposit_fits: bool
    fillable_pct_of_deposit: float
    days_until_cap_reached: float
    post_deposit_utilization_pct: float
    yield_compression_risk_pct: float
    cap_proximity_score: float
    proximity_label: str
    grade: str

    flags: List[str] = field(default_factory=list)
    advisory: List[str] = field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class DeFiProtocolSupplyCapProximityAnalyzer:
    """
    Quantifies deposit-side supply-cap headroom for Aave-V3-style markets:
    whether an intended deposit fits, how fast the cap is filling, and the
    yield-compression / crowding risk a near-full cap implies.

    Advisory only — never modifies allocator, risk, execution, or monitoring
    domains.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_label(utilization_of_cap_pct: float, uncapped: bool) -> str:
        """Map utilization_of_cap_pct -> proximity_label string."""
        if uncapped:
            return _LABEL_UNCAPPED
        u = utilization_of_cap_pct
        if u >= _UTIL_NEAR_MAX:
            return _LABEL_AT_CAP
        if u >= _UTIL_APPROACHING_MAX:
            return _LABEL_NEAR
        if u >= _UTIL_COMFORTABLE_MAX:
            return _LABEL_APPROACHING
        if u >= _UTIL_AMPLE_MAX:
            return _LABEL_COMFORTABLE
        return _LABEL_AMPLE

    @staticmethod
    def _yield_compression_risk(utilization_of_cap_pct: float,
                                uncapped: bool) -> float:
        """
        0-100, rising with utilization.  A crowded (near-full) supply cap
        means more deposits chasing the same borrow demand, so APR tends to
        fall.  Uncapped markets have no cap-driven crowding signal -> 0.
        """
        if uncapped:
            return 0.0
        u = utilization_of_cap_pct
        if u < 0.0:
            u = 0.0
        if u > 100.0:
            u = 100.0
        # Convex: low utilization barely matters, high utilization bites.
        risk = (u / 100.0) ** 2 * 100.0
        return risk

    @staticmethod
    def _cap_proximity_score(
        headroom_pct: float,
        deposit_fits: bool,
        days_until_cap_reached: float,
        uncapped: bool,
    ) -> float:
        """
        0-100, higher = SAFER / more headroom.  Blends headroom_pct,
        deposit_fits, and days_until_cap_reached.  Uncapped markets score
        very high (no cap constraint at all).
        """
        if uncapped:
            return 100.0

        h = headroom_pct
        if h < 0.0:
            h = 0.0
        if h > 100.0:
            h = 100.0

        # Headroom is the dominant component (0..70).
        score = h * 0.70

        # Deposit fits adds confidence (0 or 20).
        if deposit_fits:
            score += 20.0

        # Fill speed: lots of runway -> bonus; imminent fill -> nothing.
        if days_until_cap_reached >= DAYS_SENTINEL_NEVER:
            score += 10.0  # never filling by growth
        elif days_until_cap_reached >= 30.0:
            score += 10.0
        elif days_until_cap_reached >= 14.0:
            score += 5.0
        # else (< 14 days) no bonus

        if score < 0.0:
            score = 0.0
        if score > 100.0:
            score = 100.0
        return score

    @staticmethod
    def _classify_grade(
        cap_proximity_score: float,
        deposit_fits: bool,
        uncapped: bool,
    ) -> str:
        """Grade A-F from proximity score and whether the deposit fits."""
        if uncapped:
            return _GRADE_A
        if not deposit_fits:
            # A blocked deposit is at best a D regardless of score.
            if cap_proximity_score >= 30.0:
                return _GRADE_D
            return _GRADE_F

        s = cap_proximity_score
        if s >= 80.0:
            return _GRADE_A
        if s >= 65.0:
            return _GRADE_B
        if s >= 45.0:
            return _GRADE_C
        if s >= 25.0:
            return _GRADE_D
        return _GRADE_F

    @staticmethod
    def _build_flags(
        utilization_of_cap_pct: float,
        deposit_fits: bool,
        days_until_cap_reached: float,
        yield_compression_risk_pct: float,
        recent_supply_growth_usd_per_day: float,
        uncapped: bool,
        insufficient: bool,
    ) -> List[str]:
        flags: List[str] = []
        if insufficient:
            flags.append(_FLAG_INSUFFICIENT_DATA)
            return flags
        if uncapped:
            flags.append(_FLAG_UNCAPPED_MARKET)
            return flags

        u = utilization_of_cap_pct
        if u >= _UTIL_NEAR_MAX:
            flags.append(_FLAG_AT_CAP)
        elif u >= _NEAR_CAP_UTIL_MIN:
            flags.append(_FLAG_NEAR_CAP)

        if u < _AMPLE_HEADROOM_UTIL_MAX:
            flags.append(_FLAG_AMPLE_HEADROOM)

        if not deposit_fits:
            flags.append(_FLAG_DEPOSIT_DOES_NOT_FIT)

        # Fill-speed flags only meaningful when growing toward the cap.
        if days_until_cap_reached < DAYS_SENTINEL_NEVER:
            if days_until_cap_reached < _FAST_FILLING_DAYS:
                flags.append(_FLAG_FAST_FILLING)
            if days_until_cap_reached < _CAP_REACHED_SOON_DAYS:
                flags.append(_FLAG_CAP_REACHED_SOON)

        if yield_compression_risk_pct >= _HIGH_COMPRESSION_RISK_PCT:
            flags.append(_FLAG_HIGH_YIELD_COMPRESSION_RISK)

        if recent_supply_growth_usd_per_day < 0.0:
            flags.append(_FLAG_SHRINKING_SUPPLY)

        return flags

    @staticmethod
    def _build_advisory(
        protocol_name: str,
        proximity_label: str,
        utilization_of_cap_pct: float,
        deposit_fits: bool,
        fillable_pct_of_deposit: float,
        days_until_cap_reached: float,
        flags: List[str],
        uncapped: bool,
        insufficient: bool,
    ) -> List[str]:
        msgs: List[str] = []
        if insufficient:
            msgs.append(
                f"{protocol_name}: insufficient data to assess supply-cap "
                f"proximity (invalid supply / cap inputs)"
            )
            return msgs
        if uncapped:
            msgs.append(
                f"{protocol_name}: market is UNCAPPED — no supply-cap "
                f"constraint on deposits"
            )
            return msgs

        msgs.append(
            f"{protocol_name}: {proximity_label} — supply cap is "
            f"{utilization_of_cap_pct:.1f}% utilized"
        )

        if _FLAG_AT_CAP in flags:
            msgs.append(
                f"{protocol_name}: cap is FULL — new deposits are blocked "
                f"until supply or the cap changes"
            )
        elif not deposit_fits:
            msgs.append(
                f"{protocol_name}: intended deposit does NOT fit — only "
                f"{fillable_pct_of_deposit:.1f}% of it can be supplied"
            )

        if _FLAG_CAP_REACHED_SOON in flags:
            msgs.append(
                f"{protocol_name}: at the current fill rate the cap is reached "
                f"in ~{days_until_cap_reached:.1f} days — top up soon or expect "
                f"to be locked out"
            )
        if _FLAG_HIGH_YIELD_COMPRESSION_RISK in flags:
            msgs.append(
                f"{protocol_name}: crowded near the cap — supply APR is at "
                f"elevated risk of compression"
            )
        if _FLAG_SHRINKING_SUPPLY in flags:
            msgs.append(
                f"{protocol_name}: supply is shrinking — headroom is opening "
                f"up, cap pressure is easing"
            )
        if _FLAG_AMPLE_HEADROOM in flags:
            msgs.append(
                f"{protocol_name}: ample headroom remains — deposits fit "
                f"comfortably"
            )
        return msgs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        current_total_supply_usd: float,
        supply_cap_usd: float,
        intended_deposit_usd: float,
        current_supply_apr_pct: float,
        recent_supply_growth_usd_per_day: float,
        protocol_name: str,
    ) -> SupplyCapProximityReport:
        """
        Assess supply-cap proximity and return a SupplyCapProximityReport.

        Parameters
        ----------
        current_total_supply_usd          : USD currently supplied to the market
        supply_cap_usd                    : the supplyCap in USD; <= 0 => UNCAPPED
        intended_deposit_usd              : USD the farmer intends to deposit
        current_supply_apr_pct            : current supply-side APR (%)
        recent_supply_growth_usd_per_day  : recent net daily supply growth (USD);
                                            can be negative (shrinking)
        protocol_name                     : human-readable market label
        """
        generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # ---- Coerce inputs ----
        supply = float(current_total_supply_usd)
        cap = float(supply_cap_usd)
        deposit = float(intended_deposit_usd)
        apr = float(current_supply_apr_pct)
        growth = float(recent_supply_growth_usd_per_day)

        # Clamp nonsensical negatives.
        if supply < 0.0:
            supply = 0.0
        if deposit < 0.0:
            deposit = 0.0

        # ---- INSUFFICIENT_DATA path (non-finite inputs) ----
        insufficient = False
        for v in (supply, cap, deposit, apr, growth):
            if not math.isfinite(v):
                insufficient = True
                break

        if insufficient:
            flags = self._build_flags(
                0.0, False, DAYS_SENTINEL_NEVER, 0.0, 0.0,
                uncapped=False, insufficient=True,
            )
            advisory = self._build_advisory(
                protocol_name, _LABEL_AMPLE, 0.0, False, 0.0,
                DAYS_SENTINEL_NEVER, flags, uncapped=False, insufficient=True,
            )
            return SupplyCapProximityReport(
                protocol_name=protocol_name,
                current_total_supply_usd=supply if math.isfinite(supply) else 0.0,
                supply_cap_usd=cap if math.isfinite(cap) else 0.0,
                intended_deposit_usd=deposit if math.isfinite(deposit) else 0.0,
                current_supply_apr_pct=apr if math.isfinite(apr) else 0.0,
                recent_supply_growth_usd_per_day=(
                    growth if math.isfinite(growth) else 0.0
                ),
                utilization_of_cap_pct=0.0,
                remaining_headroom_usd=0.0,
                headroom_pct=0.0,
                deposit_fits=False,
                fillable_pct_of_deposit=0.0,
                days_until_cap_reached=DAYS_SENTINEL_NEVER,
                post_deposit_utilization_pct=0.0,
                yield_compression_risk_pct=0.0,
                cap_proximity_score=0.0,
                proximity_label=_LABEL_AMPLE,
                grade=_GRADE_F,
                flags=flags,
                advisory=advisory,
                generated_at=generated_at,
            )

        # ---- UNCAPPED path (cap <= 0) ----
        uncapped = cap <= 0.0
        if uncapped:
            flags = self._build_flags(
                0.0, True, DAYS_SENTINEL_NEVER, 0.0, growth,
                uncapped=True, insufficient=False,
            )
            advisory = self._build_advisory(
                protocol_name, _LABEL_UNCAPPED, 0.0, True, 100.0,
                DAYS_SENTINEL_NEVER, flags, uncapped=True, insufficient=False,
            )
            return SupplyCapProximityReport(
                protocol_name=protocol_name,
                current_total_supply_usd=round(supply, 8),
                supply_cap_usd=round(cap, 8),
                intended_deposit_usd=round(deposit, 8),
                current_supply_apr_pct=round(apr, 8),
                recent_supply_growth_usd_per_day=round(growth, 8),
                utilization_of_cap_pct=0.0,
                remaining_headroom_usd=0.0,
                headroom_pct=0.0,
                deposit_fits=True,
                fillable_pct_of_deposit=100.0,
                days_until_cap_reached=DAYS_SENTINEL_NEVER,
                post_deposit_utilization_pct=0.0,
                yield_compression_risk_pct=0.0,
                cap_proximity_score=100.0,
                proximity_label=_LABEL_UNCAPPED,
                grade=_GRADE_A,
                flags=flags,
                advisory=advisory,
                generated_at=generated_at,
            )

        # ---- Core computation (cap > 0) ----
        utilization = supply / cap * 100.0  # cap > 0 guaranteed here

        remaining_headroom = cap - supply
        if remaining_headroom < 0.0:
            remaining_headroom = 0.0

        headroom_pct = remaining_headroom / cap * 100.0

        deposit_fits = deposit <= remaining_headroom

        if deposit <= 0.0:
            # Nothing to deposit -> trivially fully fillable.
            fillable_pct_of_deposit = 100.0
        else:
            fillable_pct_of_deposit = min(
                100.0, remaining_headroom / deposit * 100.0
            )

        # days_until_cap_reached: only meaningful for positive growth.
        if growth > 0.0:
            if remaining_headroom <= 0.0:
                days_until_cap_reached = 0.0
            else:
                days_until_cap_reached = remaining_headroom / growth
        else:
            days_until_cap_reached = DAYS_SENTINEL_NEVER

        effective_deposit = min(deposit, remaining_headroom)
        post_deposit_utilization = (supply + effective_deposit) / cap * 100.0

        yield_compression_risk = self._yield_compression_risk(
            utilization, uncapped=False
        )
        cap_proximity_score = self._cap_proximity_score(
            headroom_pct, deposit_fits, days_until_cap_reached, uncapped=False
        )
        proximity_label = self._classify_label(utilization, uncapped=False)
        grade = self._classify_grade(
            cap_proximity_score, deposit_fits, uncapped=False
        )

        flags = self._build_flags(
            utilization, deposit_fits, days_until_cap_reached,
            yield_compression_risk, growth, uncapped=False, insufficient=False,
        )
        advisory = self._build_advisory(
            protocol_name, proximity_label, utilization, deposit_fits,
            fillable_pct_of_deposit, days_until_cap_reached, flags,
            uncapped=False, insufficient=False,
        )

        return SupplyCapProximityReport(
            protocol_name=protocol_name,
            current_total_supply_usd=round(supply, 8),
            supply_cap_usd=round(cap, 8),
            intended_deposit_usd=round(deposit, 8),
            current_supply_apr_pct=round(apr, 8),
            recent_supply_growth_usd_per_day=round(growth, 8),
            utilization_of_cap_pct=round(utilization, 8),
            remaining_headroom_usd=round(remaining_headroom, 8),
            headroom_pct=round(headroom_pct, 8),
            deposit_fits=deposit_fits,
            fillable_pct_of_deposit=round(fillable_pct_of_deposit, 8),
            days_until_cap_reached=round(days_until_cap_reached, 8),
            post_deposit_utilization_pct=round(post_deposit_utilization, 8),
            yield_compression_risk_pct=round(yield_compression_risk, 8),
            cap_proximity_score=round(cap_proximity_score, 8),
            proximity_label=proximity_label,
            grade=grade,
            flags=flags,
            advisory=advisory,
            generated_at=generated_at,
        )

    def analyze_portfolio(self, markets: List[dict]) -> dict:
        """
        Summarise a list of market dicts (each forwarded as kwargs to
        ``analyze``).  Returns most / least constrained market, average
        cap_proximity_score, at-cap count, and deposits-that-don't-fit count.
        """
        if not markets:
            return {
                "count": 0,
                "most_constrained_market": None,
                "least_constrained_market": None,
                "avg_cap_proximity_score": 0.0,
                "at_cap_count": 0,
                "deposits_that_dont_fit_count": 0,
            }

        reports: List[SupplyCapProximityReport] = []
        for mkt in markets:
            reports.append(self.analyze(**mkt))

        usable = [r for r in reports
                  if _FLAG_INSUFFICIENT_DATA not in r.flags]

        if usable:
            # Most constrained = lowest proximity score (least safe).
            most = min(usable, key=lambda r: r.cap_proximity_score)
            least = max(usable, key=lambda r: r.cap_proximity_score)
            most_name = most.protocol_name
            least_name = least.protocol_name
        else:
            most_name = None
            least_name = None

        total_score = sum(r.cap_proximity_score for r in reports)
        avg_score = total_score / len(reports) if reports else 0.0

        at_cap_count = sum(1 for r in reports if _FLAG_AT_CAP in r.flags)
        dont_fit_count = sum(
            1 for r in reports if _FLAG_DEPOSIT_DOES_NOT_FIT in r.flags
        )

        return {
            "count": len(reports),
            "most_constrained_market": most_name,
            "least_constrained_market": least_name,
            "avg_cap_proximity_score": round(avg_score, 8),
            "at_cap_count": at_cap_count,
            "deposits_that_dont_fit_count": dont_fit_count,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self,
        report: SupplyCapProximityReport,
        data_file: Path = DATA_FILE,
    ) -> None:
        """Append report to ring-buffer JSON (cap MAX_ENTRIES).  Atomic write."""
        data_file = Path(data_file)
        existing = self.load_history(data_file)

        entry = {
            "timestamp": report.generated_at
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "protocol_name": report.protocol_name,
            "current_total_supply_usd": report.current_total_supply_usd,
            "supply_cap_usd": report.supply_cap_usd,
            "intended_deposit_usd": report.intended_deposit_usd,
            "utilization_of_cap_pct": report.utilization_of_cap_pct,
            "remaining_headroom_usd": report.remaining_headroom_usd,
            "headroom_pct": report.headroom_pct,
            "deposit_fits": report.deposit_fits,
            "fillable_pct_of_deposit": report.fillable_pct_of_deposit,
            "days_until_cap_reached": report.days_until_cap_reached,
            "post_deposit_utilization_pct": report.post_deposit_utilization_pct,
            "yield_compression_risk_pct": report.yield_compression_risk_pct,
            "cap_proximity_score": report.cap_proximity_score,
            "proximity_label": report.proximity_label,
            "grade": report.grade,
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
    ana = DeFiProtocolSupplyCapProximityAnalyzer()
    report = ana.analyze(
        current_total_supply_usd=88_000_000.0,
        supply_cap_usd=100_000_000.0,
        intended_deposit_usd=5_000_000.0,
        current_supply_apr_pct=4.2,
        recent_supply_growth_usd_per_day=1_500_000.0,
        protocol_name="Aave V3 wstETH",
    )
    print(f"Protocol:                  {report.protocol_name}")
    print(f"Utilization of cap:        {report.utilization_of_cap_pct:.2f}%")
    print(f"Remaining headroom:        ${report.remaining_headroom_usd:,.0f}")
    print(f"Headroom pct:              {report.headroom_pct:.2f}%")
    print(f"Deposit fits:              {report.deposit_fits}")
    print(f"Fillable pct of deposit:   {report.fillable_pct_of_deposit:.2f}%")
    print(f"Days until cap reached:    {report.days_until_cap_reached:.2f}")
    print(f"Post-deposit utilization:  {report.post_deposit_utilization_pct:.2f}%")
    print(f"Yield compression risk:    {report.yield_compression_risk_pct:.2f}%")
    print(f"Cap proximity score:       {report.cap_proximity_score:.1f}/100")
    print(f"Proximity label:           {report.proximity_label}")
    print(f"Grade:                     {report.grade}")
    print(f"Flags:                     {', '.join(report.flags) or '(none)'}")
    for msg in report.advisory:
        print(f"  • {msg}")

    print()
    print("Portfolio summary:")
    summary = ana.analyze_portfolio([
        {
            "current_total_supply_usd": 88_000_000.0,
            "supply_cap_usd": 100_000_000.0,
            "intended_deposit_usd": 5_000_000.0,
            "current_supply_apr_pct": 4.2,
            "recent_supply_growth_usd_per_day": 1_500_000.0,
            "protocol_name": "Aave V3 wstETH",
        },
        {
            "current_total_supply_usd": 10_000_000.0,
            "supply_cap_usd": 50_000_000.0,
            "intended_deposit_usd": 2_000_000.0,
            "current_supply_apr_pct": 6.0,
            "recent_supply_growth_usd_per_day": -200_000.0,
            "protocol_name": "Aave V3 USDC",
        },
        {
            "current_total_supply_usd": 5_000_000.0,
            "supply_cap_usd": 0.0,
            "intended_deposit_usd": 1_000_000.0,
            "current_supply_apr_pct": 3.0,
            "recent_supply_growth_usd_per_day": 50_000.0,
            "protocol_name": "Aave V3 WETH (uncapped)",
        },
    ])
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    _demo()

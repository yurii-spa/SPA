"""
MP-1152: DeFiProtocolPerformanceFeeHighWaterMarkAnalyzer
========================================================
Advisory/read-only analytics module.

Models the HIGH-WATER MARK (HWM) mechanics of a performance-fee vault. After a
drawdown, the performance fee is NOT charged again until the vault's NAV climbs
back above its previous HWM — but the management fee keeps accruing during this
"underwater" period. This computes the true net-APY after mgmt + perf fees,
quantifies the perf-fee drag WITH the HWM protection versus WITHOUT it, measures
the underwater distance to the HWM, and estimates the recovery needed.

Angle: "the vault advertises gross X%, but after mgmt + perf fees and accounting
for the HWM my real net is lower; and if I enter above the current NAV while it
sits below an old HWM, I pay perf fee only later."

This isolates the *performance-fee / high-water-mark drag* question — how much of
the headline yield is eaten by fees given the HWM state, and how much the HWM
mechanism actually shields the investor in an underwater vault.

Distinct from:
  * performance_fee_crystallization_frequency_analyzer → it models how OFTEN the
    perf fee is crystallized (compounding loss), not the HWM level itself.
  * yield_harvesting_frequency_optimizer → it picks compounding CADENCE.
  * vault_share_price / apy_realization monitors → they track realized vs
    theoretical yield, not the fee schedule / HWM accounting.
This module answers only the HWM-aware net-of-fee / perf-fee-drag question.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "performance_fee_high_water_mark_log.json"
)
LOG_CAP = 100

RATIO_SENTINEL_INF = 1e9       # gross ~ 0 → net/gross ratio undefined

DEFAULT_HOLDING_DAYS = 365.0
DEFAULT_MGMT_FEE_PCT = 2.0
DEFAULT_PERF_FEE_PCT = 20.0
DEFAULT_HURDLE_PCT = 0.0

# Fee-level thresholds for flags.
HIGH_MGMT_FEE_PCT = 3.0        # management fee >= 3% → expensive
HIGH_PERF_FEE_PCT = 25.0       # performance fee >= 25% → aggressive

# Total fee-drag classification thresholds (mgmt + perf drag, % of capital
# over the holding horizon, annualized-equivalent comparison vs gross).
LOW_FEE_DRAG_PCT = 1.5         # total annualized fee drag < 1.5% → low
MODERATE_FEE_DRAG_PCT = 4.0    # < 4% → moderate
HIGH_FEE_DRAG_PCT = 8.0        # < 8% → high; >= 8% → excessive

# Underwater threshold for the AT_HIGH_WATER_MARK flag (NAV ~ HWM).
AT_HWM_TOLERANCE_PCT = 0.05    # within 0.05% of HWM → treated as at-peak


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel: float) -> float:
    if den <= 0:
        return sentinel
    return num / den


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolPerformanceFeeHighWaterMarkAnalyzer:
    """
    Analyzes performance-fee / high-water-mark mechanics for yield vaults.

    Per-position input dict fields:
        vault / token              : str
        gross_apr_pct              : float  (headline gross yield)
        management_fee_pct         : float  (annual, default 2.0)
        performance_fee_pct        : float  (default 20.0)
        current_nav                : float  (current NAV / share price)
        high_water_mark            : float  (prior HWM; 0/None → = current_nav)
        holding_period_days        : float  (default 365)
        hurdle_rate_pct            : float  (perf fee only above hurdle, default 0)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))
        gross_apr = _f(p.get("gross_apr_pct"))
        mgmt_fee = max(0.0, _f(p.get("management_fee_pct"), DEFAULT_MGMT_FEE_PCT))
        perf_fee = max(0.0, _f(p.get("performance_fee_pct"), DEFAULT_PERF_FEE_PCT))
        current_nav = _f(p.get("current_nav"))
        hwm_raw = _f(p.get("high_water_mark"))
        days = _f(p.get("holding_period_days"), DEFAULT_HOLDING_DAYS)
        if days <= 0:
            days = DEFAULT_HOLDING_DAYS
        hurdle = max(0.0, _f(p.get("hurdle_rate_pct"), DEFAULT_HURDLE_PCT))

        # Insufficient data: no/negative gross yield, or no NAV to anchor HWM.
        if gross_apr <= 0 or current_nav <= 0:
            return self._insufficient(token)

        # HWM defaults to current NAV (vault is at peak) when not provided.
        hwm = hwm_raw if hwm_raw > 0 else current_nav

        horizon_frac = days / 365.0

        # Underwater state: how far NAV is below the HWM.
        underwater_pct = _clamp((hwm - current_nav) / hwm * 100.0, 0.0, 100.0) \
            if current_nav < hwm else 0.0
        is_underwater = current_nav < hwm
        at_hwm = abs(current_nav - hwm) / hwm * 100.0 <= AT_HWM_TOLERANCE_PCT

        # Gross yield over the horizon, as a % of current capital.
        gross_yield_pct = gross_apr * horizon_frac

        # Recovery needed to climb from current NAV back to the HWM (% of NAV).
        recovery_to_hwm_pct = _clamp((hwm - current_nav) / current_nav * 100.0,
                                     0.0, 1e6) if current_nav < hwm else 0.0

        # Portion of the horizon gross-growth that lands ABOVE the HWM and is
        # therefore exposed to the perf fee. Underwater gap must close first.
        gross_above_hwm_pct = max(0.0, gross_yield_pct - recovery_to_hwm_pct)

        # Hurdle: perf fee only applies to growth above the hurdle rate (over
        # the same horizon). The fee-able base is reduced by the hurdle band.
        hurdle_over_horizon = hurdle * horizon_frac
        hurdle_applied = hurdle > 0.0

        # Management fee accrues regardless of HWM / underwater state.
        mgmt_fee_drag_pct = mgmt_fee * horizon_frac

        # Perf-fee base WITH HWM protection: only the gross above HWM, then
        # only the part of that above the hurdle band.
        perf_base_with_hwm = max(0.0, gross_above_hwm_pct - hurdle_over_horizon)
        perf_fee_drag_with_hwm_pct = perf_base_with_hwm * perf_fee / 100.0

        # Perf-fee base WITHOUT HWM protection: the whole horizon gross above
        # the hurdle, even the part merely recovering the drawdown.
        perf_base_no_hwm = max(0.0, gross_yield_pct - hurdle_over_horizon)
        perf_fee_drag_no_hwm_pct = perf_base_no_hwm * perf_fee / 100.0

        # Investor saving from the HWM mechanism (only > 0 when underwater).
        hwm_savings_pct = max(0.0,
                              perf_fee_drag_no_hwm_pct - perf_fee_drag_with_hwm_pct)

        total_fee_drag_pct = mgmt_fee_drag_pct + perf_fee_drag_with_hwm_pct

        # Annualized net APY = gross - mgmt - perf(with HWM), all annualized.
        # Drags above are over-horizon; annualize back by dividing horizon_frac.
        if horizon_frac > 0:
            mgmt_annual = mgmt_fee_drag_pct / horizon_frac
            perf_annual_with_hwm = perf_fee_drag_with_hwm_pct / horizon_frac
        else:
            mgmt_annual = 0.0
            perf_annual_with_hwm = 0.0
        net_apy_pct = gross_apr - mgmt_annual - perf_annual_with_hwm

        # Annualized total fee drag for classification.
        total_fee_drag_annual_pct = mgmt_annual + perf_annual_with_hwm

        net_over_gross_ratio = _safe_div(net_apy_pct, gross_apr, RATIO_SENTINEL_INF)
        if net_over_gross_ratio >= RATIO_SENTINEL_INF:
            net_over_gross_ratio = RATIO_SENTINEL_INF

        score = self._efficiency_score(
            total_fee_drag_annual_pct, net_apy_pct, gross_apr,
            hwm_savings_pct, is_underwater,
        )
        classification = self._classify(total_fee_drag_annual_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, net_apy_pct)
        flags = self._flags(
            is_underwater, at_hwm, hwm_savings_pct, mgmt_fee, perf_fee,
            net_apy_pct, hurdle_applied, total_fee_drag_annual_pct,
        )

        return {
            "token": token,
            "gross_apr_pct": round(gross_apr, 4),
            "underwater_pct": round(underwater_pct, 4),
            "is_underwater": is_underwater,
            "gross_yield_over_horizon_pct": round(gross_yield_pct, 4),
            "recovery_to_hwm_pct": round(recovery_to_hwm_pct, 4),
            "gross_above_hwm_pct": round(gross_above_hwm_pct, 4),
            "mgmt_fee_drag_pct": round(mgmt_fee_drag_pct, 4),
            "perf_fee_drag_with_hwm_pct": round(perf_fee_drag_with_hwm_pct, 4),
            "perf_fee_drag_no_hwm_pct": round(perf_fee_drag_no_hwm_pct, 4),
            "hwm_savings_pct": round(hwm_savings_pct, 4),
            "total_fee_drag_annual_pct": round(total_fee_drag_annual_pct, 4),
            "net_apy_pct": round(net_apy_pct, 4),
            "net_over_gross_ratio": (
                None if net_over_gross_ratio >= RATIO_SENTINEL_INF
                else round(net_over_gross_ratio, 4)
            ),
            "fee_efficiency_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _efficiency_score(
        self,
        total_fee_drag_annual_pct: float,
        net_apy_pct: float,
        gross_apr: float,
        hwm_savings_pct: float,
        is_underwater: bool,
    ) -> float:
        """
        0–100, higher = better (fee-efficient). Weighted:
          low total fee drag (≈45) + high net/gross ratio (≈30)
          + HWM protection value (≈15) + positive-net bonus (≈10).
        """
        # Fee-drag component — 0% drag → full, HIGH_FEE_DRAG_PCT+ → 0.
        drag = 45.0 * _clamp(
            1.0 - total_fee_drag_annual_pct / HIGH_FEE_DRAG_PCT, 0.0, 1.0)

        # Net/gross-ratio component.
        if gross_apr <= 0:
            ratio = 0.0
        else:
            ratio = _clamp(net_apy_pct / gross_apr, 0.0, 1.0)
        retention = 30.0 * ratio

        # HWM-protection component — only meaningful when underwater; reward
        # the magnitude of fee shielded, saturating at ~5% of capital.
        if is_underwater and hwm_savings_pct > 0:
            protection = 15.0 * _clamp(hwm_savings_pct / 5.0, 0.0, 1.0)
        else:
            # Not underwater → no protection to give, but no penalty: half.
            protection = 7.5

        # Positive-net bonus.
        bonus = 10.0 if net_apy_pct > 0 else 0.0

        return _clamp(drag + retention + protection + bonus, 0.0, 100.0)

    def _classify(self, total_fee_drag_annual_pct: float) -> str:
        if total_fee_drag_annual_pct < LOW_FEE_DRAG_PCT:
            return "LOW_FEE_DRAG"
        if total_fee_drag_annual_pct < MODERATE_FEE_DRAG_PCT:
            return "MODERATE_FEE_DRAG"
        if total_fee_drag_annual_pct < HIGH_FEE_DRAG_PCT:
            return "HIGH_FEE_DRAG"
        return "EXCESSIVE_FEE_DRAG"

    def _recommend(self, classification: str, net_apy_pct: float) -> str:
        if net_apy_pct <= 0:
            return "AVOID"
        if classification in ("LOW_FEE_DRAG", "MODERATE_FEE_DRAG"):
            return "DEPLOY"
        if classification == "HIGH_FEE_DRAG":
            return "NEGOTIATE_TERMS"
        return "AVOID"

    def _flags(
        self,
        is_underwater: bool,
        at_hwm: bool,
        hwm_savings_pct: float,
        mgmt_fee: float,
        perf_fee: float,
        net_apy_pct: float,
        hurdle_applied: bool,
        total_fee_drag_annual_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if is_underwater:
            flags.append("UNDERWATER")
            if hwm_savings_pct > 0:
                flags.append("HWM_PROTECTION_ACTIVE")
            else:
                flags.append("NO_HWM_PROTECTION")
        else:
            flags.append("NO_HWM_PROTECTION")
            if at_hwm:
                flags.append("AT_HIGH_WATER_MARK")

        if mgmt_fee >= HIGH_MGMT_FEE_PCT:
            flags.append("HIGH_MGMT_FEE")
        if perf_fee >= HIGH_PERF_FEE_PCT:
            flags.append("HIGH_PERF_FEE")
        if net_apy_pct < 0:
            flags.append("NEGATIVE_NET_APY")
        if hurdle_applied:
            flags.append("HURDLE_APPLIED")
        if total_fee_drag_annual_pct >= HIGH_FEE_DRAG_PCT:
            flags.append("EXCESSIVE_TOTAL_FEE_DRAG")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_apr_pct": 0.0,
            "underwater_pct": 0.0,
            "is_underwater": False,
            "gross_yield_over_horizon_pct": 0.0,
            "recovery_to_hwm_pct": 0.0,
            "gross_above_hwm_pct": 0.0,
            "mgmt_fee_drag_pct": 0.0,
            "perf_fee_drag_with_hwm_pct": 0.0,
            "perf_fee_drag_no_hwm_pct": 0.0,
            "hwm_savings_pct": 0.0,
            "total_fee_drag_annual_pct": 0.0,
            "net_apy_pct": 0.0,
            "net_over_gross_ratio": None,
            "fee_efficiency_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_fee_efficient_vault": None,
                "least_fee_efficient_vault": None,
                "avg_fee_efficiency_score": 0.0,
                "high_fee_drag_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["fee_efficiency_score"])
        avg = _mean([r["fee_efficiency_score"] for r in scored])
        high_drag = sum(
            1 for r in results
            if r["classification"] in ("HIGH_FEE_DRAG", "EXCESSIVE_FEE_DRAG")
        )
        return {
            "most_fee_efficient_vault": by_score[-1]["token"],
            "least_fee_efficient_vault": by_score[0]["token"],
            "avg_fee_efficiency_score": round(avg, 2),
            "high_fee_drag_count": high_drag,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "fee_efficiency_score": r["fee_efficiency_score"],
                    "recommendation": r["recommendation"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            "vault": "StableYield-2/20",
            "gross_apr_pct": 12.0,
            "management_fee_pct": 2.0,
            "performance_fee_pct": 20.0,
            "current_nav": 1.05,
            "high_water_mark": 1.05,
            "holding_period_days": 365.0,
        },
        {
            "vault": "Underwater-Vault",
            "gross_apr_pct": 15.0,
            "management_fee_pct": 2.0,
            "performance_fee_pct": 20.0,
            "current_nav": 0.90,
            "high_water_mark": 1.00,
            "holding_period_days": 365.0,
        },
        {
            "vault": "Expensive-4/30",
            "gross_apr_pct": 10.0,
            "management_fee_pct": 4.0,
            "performance_fee_pct": 30.0,
            "current_nav": 1.20,
            "high_water_mark": 1.20,
            "holding_period_days": 365.0,
            "hurdle_rate_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1152 Performance-Fee High-Water-Mark Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolPerformanceFeeHighWaterMarkAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

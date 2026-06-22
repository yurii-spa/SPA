"""
MP-1153: DeFiProtocolPerformanceFeeCrystallizationFrequencyAnalyzer
===================================================================
Advisory/read-only analytics module.

Models how OFTEN a performance fee "crystallizes" (is locked in and skimmed) on
a vault, and the extra drag that frequency causes through lost compounding.
Frequent crystallization (every block / daily) removes profit before it would
have compounded; infrequent crystallization (annual) is gentler on the investor.
It also captures the "pay-for-volatility" risk: with frequent crystallization
and no high-water mark, an investor can pay fee on transient peaks that later
evaporate.

Angle: "two vaults with the same 20% perf fee but one crystallizes daily and the
other once a year — the real fee-drag and lost compounding are very different."

This isolates the *crystallization-frequency / compounding-loss* question — the
cadence at which the perf fee is realized, not the HWM level it is measured
against.

Distinct from:
  * performance_fee_high_water_mark_analyzer → it models the HWM level and the
    underwater perf-fee shielding, not the crystallization cadence.
  * yield_harvesting_frequency_optimizer → it picks compounding CADENCE for the
    investor's own claims, not the vault's fee-skim schedule.
This module answers only the fee-crystallization-frequency drag question.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "performance_fee_crystallization_frequency_log.json"
)
LOG_CAP = 100

RATIO_SENTINEL_INF = 1e9       # gross ~ 0 → net/gross ratio undefined

DEFAULT_HOLDING_DAYS = 365.0
DEFAULT_PERF_FEE_PCT = 20.0
DEFAULT_VOLATILITY_PCT = 0.0

# Crystallization-frequency labels (events per year).
CONTINUOUS_FREQ = 365.0        # >= 365/yr → effectively continuous / per-block
DAILY_FREQ = 365.0
WEEKLY_FREQ = 52.0
MONTHLY_FREQ = 12.0
QUARTERLY_FREQ = 4.0
ANNUAL_FREQ = 1.0

HIGH_PERF_FEE_PCT = 25.0       # perf fee >= 25% → aggressive

# Compounding-loss thresholds (extra drag % of capital, annualized).
HIGH_COMPOUNDING_LOSS_PCT = 0.5    # >= 0.5% annual lost-compounding → high

# Frequency considered "high" for pay-for-volatility risk.
HIGH_FREQUENCY_THRESHOLD = 52.0    # >= weekly counts as high-frequency

# Pay-for-volatility risk threshold for the flag.
PAY_FOR_VOL_RISK_PCT = 0.5         # >= 0.5% annual risk → flag

# Friendliness classification thresholds (frequency_efficiency_score bands).
PREDATORY_SCORE = 40.0
UNFRIENDLY_SCORE = 55.0
NEUTRAL_SCORE = 70.0


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

class DeFiProtocolPerformanceFeeCrystallizationFrequencyAnalyzer:
    """
    Analyzes performance-fee crystallization frequency / compounding-loss drag.

    Per-position input dict fields:
        vault / token                       : str
        gross_apr_pct                       : float  (headline gross yield)
        performance_fee_pct                 : float  (default 20.0)
        crystallization_frequency_per_year  : float  (365 daily, 12 monthly, ...)
        holding_period_days                 : float  (default 365)
        has_high_water_mark                 : bool   (default True)
        volatility_pct                      : float  (annual, default 0.0)
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
        perf_fee = max(0.0, _f(p.get("performance_fee_pct"), DEFAULT_PERF_FEE_PCT))
        freq = _f(p.get("crystallization_frequency_per_year"))
        days = _f(p.get("holding_period_days"), DEFAULT_HOLDING_DAYS)
        if days <= 0:
            days = DEFAULT_HOLDING_DAYS
        has_hwm = bool(p.get("has_high_water_mark", True))
        volatility = max(0.0, _f(p.get("volatility_pct"), DEFAULT_VOLATILITY_PCT))

        # Insufficient data: no/negative gross yield, or no crystallization rate.
        if gross_apr <= 0 or freq <= 0:
            return self._insufficient(token)

        horizon_frac = days / 365.0

        crystallization_label = self._frequency_label(freq)
        crystallizations_over_horizon = freq * horizon_frac

        # Gross over the horizon, % of capital.
        gross_yield_pct = gross_apr * horizon_frac

        # Nominal perf-fee drag: fee on the horizon gross, as if a single
        # crystallization at the end (the textbook drag).
        nominal_perf_fee_drag_pct = gross_yield_pct * perf_fee / 100.0

        # Compounding loss: when the fee is skimmed N times across the horizon,
        # the skimmed capital can no longer compound. Model the net-of-fee
        # growth under N discrete skims vs a single final skim and take the
        # difference. Both grow at the per-period gross rate; the frequent case
        # removes a fee fraction each period that then misses compounding.
        compounding_loss_pct = self._compounding_loss(
            gross_apr, perf_fee, freq, horizon_frac)

        effective_perf_fee_drag_pct = (
            nominal_perf_fee_drag_pct + compounding_loss_pct)

        # Pay-for-volatility risk: no HWM + volatility + high frequency → the
        # vault may skim fee on transient peaks that later reverse. Scale with
        # volatility, fee size and frequency, saturating.
        pay_for_volatility_risk_pct = self._pay_for_volatility(
            has_hwm, volatility, perf_fee, freq, horizon_frac)

        # Annualize the effective drag back to APY terms.
        if horizon_frac > 0:
            effective_drag_annual = effective_perf_fee_drag_pct / horizon_frac
            compounding_loss_annual = compounding_loss_pct / horizon_frac
        else:
            effective_drag_annual = 0.0
            compounding_loss_annual = 0.0

        net_apy_pct = gross_apr - effective_drag_annual

        net_over_gross_ratio = _safe_div(net_apy_pct, gross_apr, RATIO_SENTINEL_INF)
        if net_over_gross_ratio >= RATIO_SENTINEL_INF:
            net_over_gross_ratio = RATIO_SENTINEL_INF

        score = self._efficiency_score(
            freq, compounding_loss_annual, has_hwm,
            pay_for_volatility_risk_pct, net_apy_pct,
        )
        classification = self._classify(score)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, net_apy_pct)
        flags = self._flags(
            freq, has_hwm, compounding_loss_annual,
            pay_for_volatility_risk_pct, perf_fee, net_apy_pct,
        )

        return {
            "token": token,
            "gross_apr_pct": round(gross_apr, 4),
            "crystallization_label": crystallization_label,
            "crystallizations_over_horizon": round(crystallizations_over_horizon, 4),
            "nominal_perf_fee_drag_pct": round(nominal_perf_fee_drag_pct, 4),
            "compounding_loss_pct": round(compounding_loss_pct, 4),
            "compounding_loss_annual_pct": round(compounding_loss_annual, 4),
            "effective_perf_fee_drag_pct": round(effective_perf_fee_drag_pct, 4),
            "pay_for_volatility_risk_pct": round(pay_for_volatility_risk_pct, 4),
            "net_apy_pct": round(net_apy_pct, 4),
            "net_over_gross_ratio": (
                None if net_over_gross_ratio >= RATIO_SENTINEL_INF
                else round(net_over_gross_ratio, 4)
            ),
            "frequency_efficiency_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── sub-models ───────────────────────────────────────────────────────────

    def _frequency_label(self, freq: float) -> str:
        if freq >= CONTINUOUS_FREQ:
            return "CONTINUOUS" if freq > CONTINUOUS_FREQ else "DAILY"
        if freq >= WEEKLY_FREQ:
            return "WEEKLY"
        if freq >= MONTHLY_FREQ:
            return "MONTHLY"
        if freq >= QUARTERLY_FREQ:
            return "QUARTERLY"
        if freq >= ANNUAL_FREQ:
            return "ANNUAL"
        return "INFREQUENT"

    def _compounding_loss(
        self,
        gross_apr: float,
        perf_fee: float,
        freq: float,
        horizon_frac: float,
    ) -> float:
        """
        Extra drag (% of capital, over horizon) from skimming the perf fee N
        times instead of once at the end. Compare net growth under N discrete
        crystallizations vs a single terminal one. Saturates with freq and gross.
        """
        if gross_apr <= 0 or perf_fee <= 0 or freq <= 0 or horizon_frac <= 0:
            return 0.0

        g = gross_apr / 100.0          # annual gross rate
        f = perf_fee / 100.0           # fee fraction

        # Number of crystallization periods over the horizon (>= 1).
        n = max(1.0, freq * horizon_frac)
        periods = int(min(n, 4000.0))  # cap iterations for very high freq
        if periods < 1:
            periods = 1

        per_period_gross = g * horizon_frac / periods

        # Frequent case: each period grow on the *net* (post-fee) NAV, then skim
        # fee on that period's gain. Skimmed capital leaves and never compounds.
        nav_freq = 1.0
        for _ in range(periods):
            gain = nav_freq * per_period_gross
            nav_freq = nav_freq + gain - gain * f

        # Single terminal case: let the FULL gross compound across every period
        # (nothing is skimmed mid-stream), then crystallize the fee once at the
        # end on the total gross gain. This is the investor-friendly benchmark.
        nav_gross = 1.0
        for _ in range(periods):
            nav_gross = nav_gross * (1.0 + per_period_gross)
        total_gross_gain = nav_gross - 1.0
        nav_terminal = 1.0 + total_gross_gain - total_gross_gain * f

        # Loss = how much LESS the frequent case ends up with (as % of capital).
        loss = (nav_terminal - nav_freq) * 100.0
        return max(0.0, loss)

    def _pay_for_volatility(
        self,
        has_hwm: bool,
        volatility: float,
        perf_fee: float,
        freq: float,
        horizon_frac: float,
    ) -> float:
        """
        Risk (% of capital, over horizon) of paying perf fee on transient peaks
        that later reverse. Only material without a HWM and with high frequency.
        """
        if has_hwm or volatility <= 0 or perf_fee <= 0 or freq <= 0:
            return 0.0
        if freq < HIGH_FREQUENCY_THRESHOLD:
            # Infrequent crystallization gives peaks time to wash out → low risk.
            freq_factor = _clamp(freq / HIGH_FREQUENCY_THRESHOLD, 0.0, 1.0) * 0.3
        else:
            freq_factor = _clamp(0.3 + 0.7 * (freq / CONTINUOUS_FREQ), 0.0, 1.0)
        vol_factor = _clamp(volatility / 100.0, 0.0, 1.0)
        f = perf_fee / 100.0
        # Transient peaks scale with volatility; fee skimmed on the upside swings.
        risk = volatility * vol_factor * f * freq_factor * horizon_frac
        return max(0.0, risk)

    # ── scoring ────────────────────────────────────────────────────────────────

    def _efficiency_score(
        self,
        freq: float,
        compounding_loss_annual: float,
        has_hwm: bool,
        pay_for_volatility_risk_pct: float,
        net_apy_pct: float,
    ) -> float:
        """
        0–100, higher = better (investor-friendly). Weighted:
          low frequency / low compounding loss (≈40) + has HWM (≈25)
          + low pay-for-vol risk (≈20) + positive-net bonus (≈15).
        """
        # Frequency / compounding-loss component — split between the raw cadence
        # and the realized compounding loss.
        freq_comp = 20.0 * _clamp(
            1.0 - math.log10(max(1.0, freq)) / math.log10(CONTINUOUS_FREQ),
            0.0, 1.0)
        loss_comp = 20.0 * _clamp(
            1.0 - compounding_loss_annual / HIGH_COMPOUNDING_LOSS_PCT, 0.0, 1.0)

        # HWM presence.
        hwm = 25.0 if has_hwm else 0.0

        # Low pay-for-volatility risk.
        vol = 20.0 * _clamp(
            1.0 - pay_for_volatility_risk_pct / PAY_FOR_VOL_RISK_PCT, 0.0, 1.0)

        # Positive-net bonus.
        bonus = 15.0 if net_apy_pct > 0 else 0.0

        return _clamp(freq_comp + loss_comp + hwm + vol + bonus, 0.0, 100.0)

    def _classify(self, score: float) -> str:
        if score >= NEUTRAL_SCORE:
            return "INVESTOR_FRIENDLY"
        if score >= UNFRIENDLY_SCORE:
            return "NEUTRAL"
        if score >= PREDATORY_SCORE:
            return "INVESTOR_UNFRIENDLY"
        return "PREDATORY"

    def _recommend(self, classification: str, net_apy_pct: float) -> str:
        if net_apy_pct <= 0:
            return "AVOID"
        if classification == "INVESTOR_FRIENDLY":
            return "DEPLOY"
        if classification in ("NEUTRAL", "INVESTOR_UNFRIENDLY"):
            return "PREFER_LESS_FREQUENT"
        return "AVOID"

    def _flags(
        self,
        freq: float,
        has_hwm: bool,
        compounding_loss_annual: float,
        pay_for_volatility_risk_pct: float,
        perf_fee: float,
        net_apy_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if freq >= CONTINUOUS_FREQ:
            flags.append("CONTINUOUS_CRYSTALLIZATION")
        if freq < ANNUAL_FREQ:
            flags.append("INFREQUENT_CRYSTALLIZATION")

        if has_hwm:
            flags.append("HAS_HWM")
        else:
            flags.append("NO_HWM")

        if compounding_loss_annual >= HIGH_COMPOUNDING_LOSS_PCT:
            flags.append("HIGH_COMPOUNDING_LOSS")
        if pay_for_volatility_risk_pct >= PAY_FOR_VOL_RISK_PCT:
            flags.append("PAY_FOR_VOLATILITY_RISK")
        if perf_fee >= HIGH_PERF_FEE_PCT:
            flags.append("HIGH_PERF_FEE")
        if net_apy_pct < 0:
            flags.append("NEGATIVE_NET_APY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_apr_pct": 0.0,
            "crystallization_label": "INSUFFICIENT_DATA",
            "crystallizations_over_horizon": 0.0,
            "nominal_perf_fee_drag_pct": 0.0,
            "compounding_loss_pct": 0.0,
            "compounding_loss_annual_pct": 0.0,
            "effective_perf_fee_drag_pct": 0.0,
            "pay_for_volatility_risk_pct": 0.0,
            "net_apy_pct": 0.0,
            "net_over_gross_ratio": None,
            "frequency_efficiency_score": 0.0,
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
                "most_frequency_efficient_vault": None,
                "least_frequency_efficient_vault": None,
                "avg_frequency_efficiency_score": 0.0,
                "unfriendly_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["frequency_efficiency_score"])
        avg = _mean([r["frequency_efficiency_score"] for r in scored])
        unfriendly = sum(
            1 for r in results
            if r["classification"] in ("INVESTOR_UNFRIENDLY", "PREDATORY")
        )
        return {
            "most_frequency_efficient_vault": by_score[-1]["token"],
            "least_frequency_efficient_vault": by_score[0]["token"],
            "avg_frequency_efficiency_score": round(avg, 2),
            "unfriendly_count": unfriendly,
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
                    "frequency_efficiency_score": r["frequency_efficiency_score"],
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
            "vault": "Annual-Friendly",
            "gross_apr_pct": 20.0,
            "performance_fee_pct": 20.0,
            "crystallization_frequency_per_year": 1.0,
            "holding_period_days": 365.0,
            "has_high_water_mark": True,
            "volatility_pct": 30.0,
        },
        {
            "vault": "Daily-Skim",
            "gross_apr_pct": 20.0,
            "performance_fee_pct": 20.0,
            "crystallization_frequency_per_year": 365.0,
            "holding_period_days": 365.0,
            "has_high_water_mark": True,
            "volatility_pct": 30.0,
        },
        {
            "vault": "Predatory-NoHWM",
            "gross_apr_pct": 25.0,
            "performance_fee_pct": 30.0,
            "crystallization_frequency_per_year": 365.0,
            "holding_period_days": 365.0,
            "has_high_water_mark": False,
            "volatility_pct": 80.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1153 Performance-Fee Crystallization Frequency Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolPerformanceFeeCrystallizationFrequencyAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

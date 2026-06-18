"""
MP-1203: DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer
=============================================================
Advisory/read-only analytics module.

A vault that charges a PERFORMANCE FEE (perf_fee_pct, typically 10–20%) on profit
almost always applies it with a HIGH-WATER MARK (HWM): the fee is only crystallised
on NEW NAV highs, on the increment ABOVE the prior HWM. This makes the performance
fee ASYMMETRIC — it is taken on up-moves above the HWM but is NEVER refunded on the
drawdowns in between. As a consequence a VOLATILE gross-return path realises a LOWER
net-of-perf-fee return than a SMOOTH path with the SAME gross APR. This is the
"volatility tax" / "fee asymmetry drag" of a high-water-mark performance fee.

The headline net APR a vault advertises usually assumes a SMOOTH path — the fee is
taken once on the gross APR. The realised net APR is lower because the volatility of
the path interacts with the asymmetric over-HWM fee:

    gross_apr_pct      = ((1 + geom_mean_period(gross r_i))^ppy - 1) * 100
    smooth_net_apr_pct = gross_apr_pct * (1 - perf_fee_pct/100)   if gross > 0
                       = gross_apr_pct                            otherwise

    realised_net_apr_pct: simulate a net-NAV path period by period. Apply the gross
      per-period return r_i to NAV; if the new NAV exceeds the HWM, crystallise
      perf_fee_pct% of the increment ABOVE the HWM (deduct it from NAV) and raise the
      HWM to the post-fee NAV; otherwise no fee. From the resulting net-NAV path take
      the geometric mean per-period NET return and annualise it.

    volatility_tax_pct = smooth_net_apr_pct - realised_net_apr_pct   (>0 = realised
      net BELOW the smooth/headline net → fee asymmetry is eating the path)
    fee_drag_total_pct = gross_apr_pct - realised_net_apr_pct        (total perf-fee
      drag from gross to realised net)
    realisation_ratio  = clamp(realised_net_apr_pct / smooth_net_apr_pct, 0, 1) when
      smooth > 0 (fraction of the smooth/headline net that actually reaches the LP)
    gross_return_vol_pct = pstdev(per-period gross returns) (source of the asymmetry)
    crystallization_count = number of up-periods where a fee was crystallised (new HWM)

When perf_fee_pct == 0 the fee branch never fires → realised net == gross == smooth
and volatility_tax_pct == 0. When every per-period gross return is identical (a
smooth monotone path) the over-HWM fee is taken on a single smooth ascent and the
realised net coincides with the smooth net → volatility_tax_pct ≈ 0. A choppy path
of equal gross APR pays fees on each up-leg above the HWM but recoups nothing on the
down-legs → realised net < smooth net → volatility_tax_pct > 0.

Override path (when valid per-period samples < MIN_SAMPLES = 2): accept direct
position fields (gross_apr_pct, perf_fee_pct, gross_return_vol_pct) and APPROXIMATE
the volatility tax with a closed-form heuristic. The asymmetric over-HWM fee is paid
on roughly half of the path's variance swings (the up-legs), so:

    perf_fee_frac      = perf_fee_pct / 100
    var_proxy          = (gross_return_vol_pct / 100)^2   (per-period gross variance)
    volatility_tax_pct ≈ perf_fee_frac * 0.5 * var_proxy * ppy * 100
                         = perf_fee_frac * 0.5 * gross_return_vol_pct^2/100 * ppy/100*100

    smooth_net_apr_pct = gross_apr_pct * (1 - perf_fee_frac)   if gross > 0
    realised_net_apr_pct = smooth_net_apr_pct - volatility_tax_pct  (sentinel-safe)

(The 0.5 factor encodes that only up-legs above the HWM are taxed; the proxy is kept
deliberately conservative and bounded so no inf/NaN can leak into the output.)

HIGHER score = realised_net ≈ smooth_net (low path volatility and/or neutral fee
asymmetry → the LP receives the headline net). LOWER score = a large volatility_tax
(high path volatility × high perf fee → realised net far below the headline net).

Distinct from:
  * defi_protocol_performance_fee_high_water_mark_analyzer — that scores a SNAPSHOT of
    the current state relative to the HWM (NAV above/below the mark, the unrecovered
    drawdown a depositor must climb back before fees resume). HERE it is a PATH-
    DEPENDENT volatility tax: the gap between gross and realised net over the WHOLE
    return path created by the fee's asymmetry, not a single above/below-HWM snapshot.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that concerns
    the FREQUENCY / timing cadence of fee crystallisation events (how often the fee is
    booked). HERE it is the MAGNITUDE of the asymmetric net drag the path volatility
    causes, not how often the fee crystallises.
  * defi_protocol_vault_yield_variance_drag_realization_analyzer — that converts the
    DISPERSION of a return series into a geometric-vs-arithmetic compounding penalty on
    a SINGLE GROSS capital base with NO fee. HERE the penalty is specifically the one
    introduced by the ASYMMETRIC over-HWM PERFORMANCE FEE (it vanishes when perf_fee=0,
    whereas the variance/compounding drag does not).
  * defi_protocol_vault_management_fee_accrual_analyzer — that concerns a LINEAR
    management fee accrued on AUM regardless of profit (symmetric, path-independent).
    HERE it is the NON-LINEAR performance fee with a high-water mark whose asymmetry
    is the entire source of the measured tax.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_performance_fee_volatility_tax_log.json"
)
LOG_CAP = 100

# Minimum valid per-period gross-return samples required to use the sample path.
MIN_SAMPLES = 2

# Default annualisation factor (sub-periods per year).
DEFAULT_PERIODS_PER_YEAR = 365.0

# Starting NAV for the simulated net path (unit base; results are scale-free).
DEFAULT_INITIAL_NAV = 1.0

# Default performance fee fraction sentinel when omitted on the sample path.
DEFAULT_PERF_FEE_PCT = 0.0

# Classification thresholds on the scale-free tax_fraction in [0, 1]
# (= volatility_tax_pct / smooth_net_apr_pct).
NEUTRAL_FRACTION = 0.05      # at/below → neutral (realised ≈ smooth/headline)
MILD_FRACTION = 0.20         # at/below → mild volatility tax
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe tax

# Flag thresholds.
HIGH_PERF_FEE_PCT = 20.0          # perf fee at/above this → HIGH_PERF_FEE
HIGH_GROSS_VOL_PCT = 3.0          # per-period gross stdev at/above → HIGH_GROSS_VOL
HIGH_VOL_TAX_FRACTION = MILD_FRACTION  # tax_fraction above this → HIGH_VOLATILITY_TAX

# Heuristic factor: only up-legs above the HWM are taxed (≈ half the variance swings).
ASYMMETRY_FACTOR = 0.5

# Small epsilon to keep normalisers finite.
EPS = 1e-12


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


def _safe_div(num: float, den: float, sentinel):
    if den <= 0:
        return sentinel
    return num / den


def _coerce_num(val) -> Optional[float]:
    """
    Coerce a single sample to a finite float, or None if it is not interpretable
    (skipped). Accepts int/float/numeric-string; rejects bool, None, NaN, inf,
    and non-numeric values.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        try:
            fv = float(val)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            fv = float(s)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    return None


def _coerce_returns(raw) -> List[float]:
    """
    Coerce a list of per-sub-period GROSS RETURN (% per sub-period) samples to finite
    floats. NEGATIVE returns are VALID (a period can lose), so only non-finite /
    non-numeric / bool entries are skipped. Order is preserved (newest LAST).
    """
    out: List[float] = []
    if not raw:
        return out
    for v in list(raw):
        cv = _coerce_num(v)
        if cv is None:
            continue
        out.append(cv)
    return out


def _coerce_perf_fee_pct(raw) -> Optional[float]:
    """
    Coerce a performance fee percent. A negative fee is meaningless; clamp to
    [0, 100]. Returns None if uninterpretable.
    """
    cv = _coerce_num(raw)
    if cv is None:
        return None
    return _clamp(cv, 0.0, 100.0)


def _pstdev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    try:
        sd = statistics.pstdev(values)
    except statistics.StatisticsError:
        return 0.0
    return sd if math.isfinite(sd) else 0.0


def _geom_mean_period(returns_pct: List[float]) -> Optional[float]:
    """
    Geometric mean per-period return (as a FRACTION) of a list of per-period %
    returns: (prod (1 + r_i/100))^(1/n) - 1. Returns None if any growth factor is
    non-positive (a period that loses >= 100% breaks the geometric link) or the
    result is non-finite.
    """
    if not returns_pct:
        return None
    log_sum = 0.0
    for r in returns_pct:
        factor = 1.0 + r / 100.0
        if factor <= 0.0:
            return None
        log_sum += math.log(factor)
    gm = math.exp(log_sum / len(returns_pct)) - 1.0
    return gm if math.isfinite(gm) else None


def _annualise_geom(period_frac: float, ppy: float) -> Optional[float]:
    """
    Annualise a geometric per-period fractional return to an APR % by compounding:
    ((1 + period_frac)^ppy - 1) * 100. Returns None if non-finite or the base is
    non-positive.
    """
    base = 1.0 + period_frac
    if base <= 0.0:
        return None
    try:
        apr = (math.exp(ppy * math.log(base)) - 1.0) * 100.0
    except (ValueError, OverflowError):
        return None
    return apr if math.isfinite(apr) else None


def _simulate_net_path(
    returns_pct: List[float],
    perf_fee_pct: float,
    initial_nav: float,
) -> Tuple[List[float], int]:
    """
    Simulate the NET-of-performance-fee NAV path under a HIGH-WATER MARK. NAV starts
    at `initial_nav` and HWM starts at `initial_nav`. For period i (oldest→newest):
    apply the gross return r_i to NAV (nav *= 1 + r_i/100). If the new NAV exceeds the
    current HWM, crystallise perf_fee_pct% of the increment (nav - hwm) ABOVE the HWM,
    deduct that fee from NAV, and raise the HWM to the post-fee NAV. Otherwise no fee
    is taken and the HWM is unchanged.

    Returns (net_period_factors, crystallization_count), where net_period_factors[i]
    is the NET growth factor of period i (post-fee NAV_i / NAV_{i-1}) and
    crystallization_count is the number of periods a fee was crystallised. The factors
    are clamped to be strictly positive so the downstream geometric link is defined.
    """
    fee_frac = _clamp(perf_fee_pct, 0.0, 100.0) / 100.0
    nav = initial_nav
    hwm = initial_nav
    factors: List[float] = []
    crystallizations = 0
    for r in returns_pct:
        prev_nav = nav
        nav = nav * (1.0 + r / 100.0)
        if fee_frac > 0.0 and nav > hwm:
            fee = (nav - hwm) * fee_frac
            nav = nav - fee
            hwm = nav
            crystallizations += 1
        if prev_nav <= 0.0:
            factor = 0.0
        else:
            factor = nav / prev_nav
        factors.append(factor)
    return factors, crystallizations


def _net_geom_period(factors: List[float]) -> Optional[float]:
    """
    Geometric mean per-period NET return (FRACTION) from a list of net growth factors:
    (prod factor_i)^(1/n) - 1. Returns None if any factor is non-positive or the
    result is non-finite.
    """
    if not factors:
        return None
    log_sum = 0.0
    for fac in factors:
        if fac <= 0.0:
            return None
        log_sum += math.log(fac)
    gm = math.exp(log_sum / len(factors)) - 1.0
    return gm if math.isfinite(gm) else None


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

class DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer:
    """
    Measures the "volatility tax" a HIGH-WATER-MARK PERFORMANCE FEE imposes on a
    vault depositor: the gap between the SMOOTH/headline net APR (the gross APR taxed
    once, as a brochure implies) and the REALISED net APR once the asymmetric over-HWM
    fee is applied period by period across the actual gross-return PATH.

        gross_apr_pct      = ((1 + geom_mean_period(gross r_i))^ppy - 1) * 100
        smooth_net_apr_pct = gross_apr_pct * (1 - perf_fee_pct/100)   (gross > 0)
        realised_net_apr_pct = annualise( geom_mean( net-of-fee per-period factors ) )
        volatility_tax_pct = smooth_net_apr_pct - realised_net_apr_pct
        fee_drag_total_pct = gross_apr_pct - realised_net_apr_pct
        realisation_ratio  = clamp(realised_net_apr_pct / smooth_net_apr_pct, 0, 1)
        tax_fraction       = clamp(volatility_tax_pct / smooth_net_apr_pct, 0, 1)

    The over-HWM fee is taken on up-legs but never refunded on drawdowns, so a choppy
    path realises LESS net than a smooth path of identical gross APR. With perf_fee=0
    the fee never fires (tax 0 → NEUTRAL). With a perfectly smooth equal-return path
    the fee is taken on one ascent and the realised net coincides with the smooth net
    (tax ≈ 0 → NEUTRAL).

    HIGHER score = realised_net ≈ smooth_net (LP receives the headline net). LOWER
    score = large volatility tax (high vol × high perf fee → realised net far below
    the headline net).

    Per-position input dict fields:
        vault / token       : str
        period_returns      : list — per-sub-period GROSS % returns (e.g. 2.0 = +2%),
                              newest LAST. Negative returns are VALID; non-finite /
                              non-numeric / bool entries are skipped. MIN_SAMPLES = 2.
        perf_fee_pct        : float — performance fee percent on profit above HWM
                              (clamped to [0, 100]; default 0 on the sample path).
        periods_per_year    : float — annualisation factor (default 365).
        gross_apr_pct       : float — OPTIONAL direct override of the gross APR.
        gross_return_vol_pct : float — OPTIONAL per-period gross stdev for the override
                              heuristic. Override path REQUIRES gross_apr_pct AND
                              perf_fee_pct (else INSUFFICIENT_DATA); gross_return_vol_pct
                              defaults to 0 (→ zero approximated volatility tax).

    MIN_SAMPLES = 2 valid gross-return samples are required to use the sample path.
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

        ppy = _f(p.get("periods_per_year"), default=DEFAULT_PERIODS_PER_YEAR)
        if not math.isfinite(ppy) or ppy <= 0:
            ppy = DEFAULT_PERIODS_PER_YEAR

        returns = _coerce_returns(p.get("period_returns"))
        n = len(returns)
        used_samples = n >= MIN_SAMPLES

        if used_samples:
            return self._analyze_samples(token, p, returns, n, ppy)
        return self._analyze_override(token, p, n, ppy)

    # ── sample path ─────────────────────────────────────────────────────────────

    def _analyze_samples(
        self, token: str, p: dict, returns: List[float], n: int, ppy: float
    ) -> dict:
        perf_fee_pct = _coerce_perf_fee_pct(p.get("perf_fee_pct"))
        if perf_fee_pct is None:
            perf_fee_pct = DEFAULT_PERF_FEE_PCT

        # Gross APR from the geometric mean of the per-period gross returns.
        gross_period = _geom_mean_period(returns)
        if gross_period is None:
            return self._insufficient(token)
        gross_apr_pct = _annualise_geom(gross_period, ppy)
        if gross_apr_pct is None or not math.isfinite(gross_apr_pct):
            return self._insufficient(token)

        # Realised net APR: simulate the net-of-perf-fee NAV path under the HWM.
        net_factors, crystallizations = _simulate_net_path(
            returns, perf_fee_pct, DEFAULT_INITIAL_NAV)
        net_period = _net_geom_period(net_factors)
        if net_period is None:
            return self._insufficient(token)
        realised_net_apr_pct = _annualise_geom(net_period, ppy)
        if realised_net_apr_pct is None or not math.isfinite(realised_net_apr_pct):
            return self._insufficient(token)

        gross_return_vol_pct = _pstdev(returns)

        return self._finish(
            token=token,
            gross_apr_pct=gross_apr_pct,
            realised_net_apr_pct=realised_net_apr_pct,
            perf_fee_pct=perf_fee_pct,
            gross_return_vol_pct=gross_return_vol_pct,
            crystallization_count=crystallizations,
            ppy=ppy,
            n=n,
            used_samples=True,
            used_override=False,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(self, token: str, p: dict, n: int, ppy: float) -> dict:
        gross_o_raw = p.get("gross_apr_pct")
        fee_o_raw = p.get("perf_fee_pct")
        # Both gross APR and perf fee are required on the override path.
        if gross_o_raw is None or fee_o_raw is None:
            return self._insufficient(token)
        gross_o = _coerce_num(gross_o_raw)
        fee_o = _coerce_perf_fee_pct(fee_o_raw)
        if gross_o is None or fee_o is None or not math.isfinite(gross_o):
            return self._insufficient(token)

        vol_o = _coerce_num(p.get("gross_return_vol_pct"))
        if vol_o is None or vol_o < 0.0 or not math.isfinite(vol_o):
            vol_o = 0.0

        # Heuristic volatility tax: the asymmetric over-HWM fee is paid on ≈ half the
        # variance swings (the up-legs above the HWM). var_proxy is per-period gross
        # variance as a fraction^2; scale by ppy to APR space, by the fee fraction, and
        # by ASYMMETRY_FACTOR. Bounded + finite so no inf/NaN can leak out.
        perf_fee_frac = _clamp(fee_o, 0.0, 100.0) / 100.0
        var_proxy = (vol_o / 100.0) ** 2
        approx_tax = perf_fee_frac * ASYMMETRY_FACTOR * var_proxy * ppy * 100.0
        if not math.isfinite(approx_tax) or approx_tax < 0.0:
            approx_tax = 0.0

        smooth_net = gross_o * (1.0 - perf_fee_frac) if gross_o > 0.0 else gross_o
        # The approximated tax cannot exceed the smooth net (a fully-eaten net), and a
        # non-positive smooth net has no headline net to tax.
        if smooth_net > 0.0:
            approx_tax = _clamp(approx_tax, 0.0, smooth_net)
        else:
            approx_tax = 0.0
        realised_net = smooth_net - approx_tax
        if not math.isfinite(realised_net):
            return self._insufficient(token)

        return self._finish(
            token=token,
            gross_apr_pct=gross_o,
            realised_net_apr_pct=realised_net,
            perf_fee_pct=fee_o,
            gross_return_vol_pct=vol_o,
            crystallization_count=None,
            ppy=ppy,
            n=n,
            used_samples=False,
            used_override=True,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_apr_pct: float,
        realised_net_apr_pct: float,
        perf_fee_pct: float,
        gross_return_vol_pct: float,
        crystallization_count: Optional[int],
        ppy: float,
        n: int,
        used_samples: bool,
        used_override: bool,
    ) -> dict:
        perf_fee_frac = _clamp(perf_fee_pct, 0.0, 100.0) / 100.0

        # Smooth/headline net APR: gross taxed once (only on a positive gross).
        if gross_apr_pct > 0.0:
            smooth_net_apr_pct = gross_apr_pct * (1.0 - perf_fee_frac)
        else:
            smooth_net_apr_pct = gross_apr_pct

        volatility_tax_pct = smooth_net_apr_pct - realised_net_apr_pct
        fee_drag_total_pct = gross_apr_pct - realised_net_apr_pct

        # Scale-free realisation_ratio / tax_fraction against the smooth net headline.
        if smooth_net_apr_pct > EPS:
            realisation_ratio = _clamp(
                realised_net_apr_pct / smooth_net_apr_pct, 0.0, 1.0)
            tax_fraction = _clamp(
                volatility_tax_pct / smooth_net_apr_pct, 0.0, 1.0)
        else:
            # Non-positive smooth net: a tax is not meaningfully scale-free. Treat a
            # near-equal / non-positive headline as fully realised (no headline net to
            # erode); divergence is surfaced through the negative-gross flag instead.
            realisation_ratio = 1.0
            tax_fraction = 0.0

        negative_gross = gross_apr_pct < 0.0

        classification = self._classify(
            tax_fraction, negative_gross, smooth_net_apr_pct)
        score = self._score(
            realisation_ratio, volatility_tax_pct, smooth_net_apr_pct, used_override)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            negative_gross,
            perf_fee_pct,
            gross_return_vol_pct,
            tax_fraction,
            used_override,
        )

        return {
            "token": token,
            "gross_apr_pct": round(gross_apr_pct, 4),
            "smooth_net_apr_pct": round(smooth_net_apr_pct, 4),
            "realised_net_apr_pct": round(realised_net_apr_pct, 4),
            "volatility_tax_pct": round(volatility_tax_pct, 4),
            "fee_drag_total_pct": round(fee_drag_total_pct, 4),
            "realisation_ratio": round(realisation_ratio, 4),
            "tax_fraction": round(tax_fraction, 4),
            "perf_fee_pct": round(perf_fee_pct, 4),
            "gross_return_vol_pct": round(gross_return_vol_pct, 4),
            "crystallization_count": crystallization_count,
            "periods_per_year": round(ppy, 4),
            "sample_count": n,
            "used_samples": used_samples,
            "used_override": used_override,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        realisation_ratio: float,
        volatility_tax_pct: float,
        smooth_net_apr_pct: float,
        used_override: bool,
    ) -> float:
        """
        0–100, HIGHER = the realised net APR is close to the smooth/headline net (low
        path volatility / neutral fee asymmetry → the LP receives the headline net).
        Two components:
          * realisation = clamp(realisation_ratio, 0, 1) — the fraction of the smooth
            net the LP actually keeps (1 → realised ≈ smooth, 0 → realised ≤ 0),
          * tax penalty = clamp(1 − normalised_tax, 0, 1), where
                normalised_tax = volatility_tax_pct
                                 / (|smooth_net_apr_pct| + volatility_tax_pct + eps)
            penalises a large ABSOLUTE volatility tax relative to the headline net.
        Weighted 70/30 toward realisation (it directly maps to the net a depositor
        keeps); the absolute-tax penalty corroborates how exposed the position is. On
        the override path (heuristic tax only) the penalty component is still applied
        from the approximated tax.
        """
        realisation = _clamp(realisation_ratio, 0.0, 1.0)
        denom = abs(smooth_net_apr_pct) + max(volatility_tax_pct, 0.0) + EPS
        normalised_tax = _clamp(max(volatility_tax_pct, 0.0) / denom, 0.0, 1.0)
        tax_penalty = _clamp(1.0 - normalised_tax, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * tax_penalty, 0.0, 100.0)

    def _classify(
        self,
        tax_fraction: float,
        negative_gross: bool,
        smooth_net_apr_pct: float,
    ) -> str:
        if negative_gross:
            # A losing gross path has no positive net for the fee to erode; surface it
            # as the worst case (no headline net the LP can realise).
            return "SEVERE_TAX"
        if smooth_net_apr_pct <= EPS:
            # Non-positive headline net: no meaningful positive volatility tax.
            return "NEUTRAL"
        if tax_fraction <= NEUTRAL_FRACTION:
            return "NEUTRAL"
        if tax_fraction <= MILD_FRACTION:
            return "MILD_TAX"
        if tax_fraction <= MODERATE_FRACTION:
            return "MODERATE_TAX"
        return "SEVERE_TAX"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "NEUTRAL":
            return "TRUST_HEADLINE_NET"
        if classification == "MILD_TAX":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_TAX":
            return "DISCOUNT_HEADLINE"
        # SEVERE_TAX
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        negative_gross: bool,
        perf_fee_pct: float,
        gross_return_vol_pct: float,
        tax_fraction: float,
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag (NEUTRAL → NEUTRAL_TAX for the good case).
        if classification == "NEUTRAL":
            flags.append("NEUTRAL_TAX")
        else:
            flags.append(classification)

        if tax_fraction > HIGH_VOL_TAX_FRACTION and not negative_gross:
            flags.append("HIGH_VOLATILITY_TAX")
        if perf_fee_pct >= HIGH_PERF_FEE_PCT:
            flags.append("HIGH_PERF_FEE")
        if gross_return_vol_pct >= HIGH_GROSS_VOL_PCT:
            flags.append("HIGH_GROSS_VOL")
        if negative_gross:
            flags.append("NEGATIVE_GROSS")
        if used_override:
            flags.append("TAX_FROM_OVERRIDE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_apr_pct": None,
            "smooth_net_apr_pct": None,
            "realised_net_apr_pct": None,
            "volatility_tax_pct": None,
            "fee_drag_total_pct": None,
            "realisation_ratio": None,
            "tax_fraction": None,
            "perf_fee_pct": None,
            "gross_return_vol_pct": None,
            "crystallization_count": None,
            "periods_per_year": None,
            "sample_count": 0,
            "used_samples": False,
            "used_override": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "lowest_tax_vault": None,
                "highest_tax_vault": None,
                "avg_score": 0.0,
                "negative_gross_count": 0,
                "position_count": len(results),
            }
        # Higher score = realised net ≈ smooth net → highest score is lowest tax.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        negative = sum(
            1 for r in results
            if "NEGATIVE_GROSS" in r.get("flags", []))
        return {
            "lowest_tax_vault": by_score[-1]["token"],
            "highest_tax_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "negative_gross_count": negative,
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
                    "score": r["score"],
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
            # NEUTRAL: zero performance fee → the over-HWM fee never fires, realised
            # net == gross == smooth, no volatility tax regardless of the path.
            "vault": "USDC-Vault-NoPerfFee",
            "period_returns": [3.0, -1.0, 4.0, -2.0, 3.5, -1.5],
            "perf_fee_pct": 0.0,
            "periods_per_year": 12.0,
        },
        {
            # NEUTRAL-ish: a SMOOTH equal-return path with a perf fee — the fee is
            # taken on one steady ascent, realised net ≈ smooth net (tax ≈ 0).
            "vault": "stETH-Vault-SmoothPath",
            "period_returns": [1.5, 1.5, 1.5, 1.5, 1.5, 1.5],
            "perf_fee_pct": 20.0,
            "periods_per_year": 12.0,
        },
        {
            # SEVERE_TAX: a choppy high-vol path with a high perf fee — fees crystallise
            # on every up-leg above the HWM but nothing is recouped on the down-legs,
            # so realised net falls well below the smooth/headline net.
            "vault": "GOV-Vault-ChoppyHighFee",
            "period_returns": [12.0, -8.0, 12.0, -8.0, 12.0, -8.0],
            "perf_fee_pct": 20.0,
            "periods_per_year": 12.0,
        },
        {
            # Override path: gross APR + perf fee (+ gross vol) supplied directly →
            # heuristic volatility tax.
            "vault": "LST-Vault-OverrideTax",
            "gross_apr_pct": 30.0,
            "perf_fee_pct": 20.0,
            "gross_return_vol_pct": 8.0,
        },
        {
            # INSUFFICIENT_DATA: a single return sample and no full override.
            "vault": "MYSTERY-Vault-NoData",
            "period_returns": [2.0],
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1203 Vault Performance-Fee Volatility-Tax Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

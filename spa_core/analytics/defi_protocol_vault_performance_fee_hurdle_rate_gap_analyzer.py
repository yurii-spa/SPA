"""
MP-1207: DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer
=============================================================
Advisory/read-only analytics module.

A vault charges a PERFORMANCE fee on its GROSS appreciation WITHOUT a hurdle rate
(or with a hurdle set BELOW the risk-free / benchmark basis). That means the
depositor pays a performance fee on BETA — the return they could have earned
passively at the benchmark / risk-free rate — as though it were ALPHA. The
headline "net APR" overstates the real value the manager added, because part of
the fee is charged on SUB-HURDLE (benchmark-level) returns that required no skill.

A fair hurdle is the benchmark / risk-free rate: the depositor should only pay a
performance fee on the EXCESS over what they could have earned by doing nothing.
If the vault's applied hurdle is below the benchmark, the fee leaks onto beta:

    fee_frac              = clamp(performance_fee_pct / 100, 0, 1)
    fee_charged_apr_pct   = fee_frac * max(0, gross - hurdle_apr_pct)
    fair_fee_apr_pct      = fee_frac * max(0, gross - benchmark_apr_pct)
    hurdle_gap_apr_pct    = benchmark_apr_pct - hurdle_apr_pct
    excess_fee_apr_pct    = max(0, fee_charged_apr - fair_fee_apr)
                          (= fee_frac * (benchmark - hurdle) when gross >= benchmark
                             >= hurdle)
    net_apr_charged_pct   = gross - fee_charged_apr
    net_apr_fair_pct      = gross - fair_fee_apr
    gross_alpha_apr_pct   = max(0, gross - benchmark_apr_pct)
    net_alpha_apr_pct     = gross_alpha_apr - fee_charged_apr
    alpha_realization_ratio = clamp(net_alpha / gross_alpha, 0, 1)
    fee_on_beta_fraction  = clamp(excess_fee_apr / fee_charged_apr, 0, 1)

The headline says "the manager beat the market and we only skim the upside", but
the fee was taken on the whole gross over a near-zero hurdle, so a chunk of it was
charged on the benchmark-level return (beta) that any passive holder would have
captured. The scale-free fee_on_beta_fraction is the share of the charged fee that
leaked onto beta; it is the basis of the classification. When the vault's hurdle
coincides with the benchmark the fee falls almost entirely on alpha (the depositor
pays for skill, not for beta → HIGHER score). When there is no hurdle and the
benchmark is high the fee is dominated by beta tax (LOWER score), and if the fee
eats more than the whole gross alpha the net alpha goes negative.

HIGHER score = the hurdle is approximately the benchmark, so the fee falls almost
entirely on alpha (the depositor pays for skill, not for beta). LOWER score = a
large share of the fee is charged on sub-hurdle (benchmark-level) beta, or the fee
exceeds the gross alpha and the net alpha goes negative.

Override path (when excess_fee_apr_pct is supplied directly, finite, AND a valid
POSITIVE gross_apr_pct and POSITIVE fee_charged_apr_pct are present): take the
excess verbatim (negative → magnitude) and skip the hurdle / benchmark geometry —
fee_on_beta_fraction and the metrics are computed the same way:

    fee_on_beta_fraction = clamp(excess_fee_apr / fee_charged_apr, 0, 1)

(On the override path the hurdle / benchmark / hurdle_gap geometry is not known →
they are reported as None, and the geometry-only flags NO_HURDLE_APPLIED /
FEE_EXCEEDS_ALPHA are NOT raised.)

Distinguished from:
  * defi_protocol_performance_fee_high_water_mark_analyzer — that prices the
    mechanics of the HWM RESET: whether the fee waits for the prior peak to be
    recovered before crystallising. HERE it is the gap between the applied HURDLE
    and the benchmark — an ORTHOGONAL axis: a vault can have a HWM yet have NO
    hurdle, so it charges its perf fee on benchmark-level beta above the last peak.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a high-water-mark performance fee over a VOLATILE gross path
    (the fee is taken on up-legs but not refunded on down-legs). HERE it is a
    SINGLE-PERIOD, FIRST-MOMENT benchmark-hurdle gap — no path, no volatility.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that prices
    how OFTEN the fee crystallises (more frequent crystallisation taxes mean
    reversion). HERE it is on what BASIS the fee is applied: hurdle vs no-hurdle,
    not how often it is taken.
  * defi_protocol_risk_adjusted_yield_hurdle_analyzer — that asks whether the
    RETURN clears a risk-premium hurdle that compensates for tail loss. HERE it is
    whether the FEE respects a benchmark hurdle: fee FAIRNESS, not the
    risk-adequacy of the return itself.
  * defi_protocol_vault_headline_yield_honesty_composite_analyzer — that is a
    bottom-up roll-up of headline-yield drags; THIS module is one of the
    mechanisms that feeds it.

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
    "data", "vault_performance_fee_hurdle_rate_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_beta_fraction in [0, 1]
# (= excess_fee_apr_pct / fee_charged_apr_pct).
CLEAN_FRACTION = 0.05        # at/below → clean hurdle (fee falls on alpha)
MILD_FRACTION = 0.20         # at/below → mild beta tax
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe beta tax

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
    Coerce a single value to a finite float, or None if it is not interpretable.
    Accepts int/float/numeric-string; rejects bool, None, NaN, inf, and
    non-numeric values.
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


def _coerce_nonneg(val) -> float:
    """
    Coerce a value to a finite NON-NEGATIVE magnitude. A signed negative value is
    taken as its magnitude; non-finite / non-numeric / bool / None → 0.0.
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return 0.0
    return abs(cv)


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

class DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer:
    """
    Measures the gap between the HURDLE rate a vault actually applies before taking
    its performance fee and the FAIR hurdle (the benchmark / risk-free rate the
    depositor could have earned passively), and the share of the charged fee that
    therefore leaks onto BETA rather than ALPHA.

        fee_frac                = clamp(performance_fee_pct / 100, 0, 1)
        fee_charged_apr_pct     = fee_frac * max(0, gross - hurdle_apr_pct)
        fair_fee_apr_pct        = fee_frac * max(0, gross - benchmark_apr_pct)
        hurdle_gap_apr_pct      = benchmark_apr_pct - hurdle_apr_pct
        excess_fee_apr_pct      = max(0, fee_charged_apr - fair_fee_apr)
        net_apr_charged_pct     = gross - fee_charged_apr
        net_apr_fair_pct        = gross - fair_fee_apr
        gross_alpha_apr_pct     = max(0, gross - benchmark_apr_pct)
        net_alpha_apr_pct       = gross_alpha_apr - fee_charged_apr
        alpha_realization_ratio = clamp(net_alpha / gross_alpha, 0, 1)
        fee_on_beta_fraction    = clamp(excess_fee_apr / fee_charged_apr, 0, 1)

    The fee is charged on gross over the applied hurdle; the fair fee would be
    charged only on gross over the benchmark. When the applied hurdle equals (or
    exceeds) the benchmark, the fee falls entirely on alpha (CLEAN_HURDLE). When
    there is no hurdle and the benchmark is high, a large share of the fee is
    charged on benchmark-level beta (MODERATE / SEVERE beta tax), and if the fee
    exceeds the gross alpha the net alpha goes negative.

    HIGHER score = hurdle ≈ benchmark, fee falls on alpha (the depositor pays for
    skill). LOWER score = a large share of the fee is charged on beta, or the fee
    eats more than the whole gross alpha (net alpha negative).

    Per-position input dict fields:
        vault / token        : str
        gross_apr_pct        : float — gross vault APR before the perf fee.
                               REQUIRED, must be a finite POSITIVE number (else
                               INSUFFICIENT_DATA).
        performance_fee_pct  : float — performance-fee rate % (REQUIRED finite,
                               clamped into 0..100; non-finite → INSUFFICIENT_DATA
                               on the main path).
        hurdle_apr_pct       : float — hurdle the vault actually applies before
                               taking the fee (finite >= 0; default 0.0 = "no
                               hurdle").
        benchmark_apr_pct    : float — the FAIR hurdle (risk-free / benchmark rate
                               the depositor could earn passively; finite >= 0;
                               the economically correct hurdle).
        excess_fee_apr_pct   : float — OPTIONAL direct override of the
                               benchmark-relative excess fee (the fee leaked onto
                               beta). When supplied (finite; negative → magnitude)
                               AND a valid POSITIVE gross_apr_pct and POSITIVE
                               fee_charged_apr_pct are present, take this excess
                               directly and skip the hurdle / benchmark geometry
                               (override path; geometry → None).
        fee_charged_apr_pct  : float — OPTIONAL, only used on the override path as
                               the denominator for fee_on_beta_fraction (finite
                               > 0 required to take the override path).
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

        # The gross APR is required and must be finite & positive.
        gross = _coerce_num(p.get("gross_apr_pct"))
        if gross is None or not math.isfinite(gross) or gross <= 0.0:
            return self._insufficient(token)

        # Override path: a direct excess fee + a positive fee_charged supplied.
        excess_o = _coerce_num(p.get("excess_fee_apr_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_apr_pct"))
        if (excess_o is not None and math.isfinite(excess_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross, abs(excess_o), fee_charged_o)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, gross, fee_pct)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross: float, fee_pct: float,
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        hurdle_apr_pct = _coerce_nonneg(p.get("hurdle_apr_pct"))
        benchmark_apr_pct = _coerce_nonneg(p.get("benchmark_apr_pct"))

        fee_charged_apr_pct = fee_frac * max(0.0, gross - hurdle_apr_pct)
        fair_fee_apr_pct = fee_frac * max(0.0, gross - benchmark_apr_pct)
        hurdle_gap_apr_pct = benchmark_apr_pct - hurdle_apr_pct
        excess_fee_apr_pct = max(0.0, fee_charged_apr_pct - fair_fee_apr_pct)
        gross_alpha_apr_pct = max(0.0, gross - benchmark_apr_pct)

        return self._finish(
            token=token,
            gross_apr_pct=gross,
            fee_frac=fee_frac,
            hurdle_apr_pct=hurdle_apr_pct,
            benchmark_apr_pct=benchmark_apr_pct,
            hurdle_gap_apr_pct=hurdle_gap_apr_pct,
            fee_charged_apr_pct=fee_charged_apr_pct,
            fair_fee_apr_pct=fair_fee_apr_pct,
            excess_fee_apr_pct=excess_fee_apr_pct,
            gross_alpha_apr_pct=gross_alpha_apr_pct,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross: float, excess: float, fee_charged: float,
    ) -> dict:
        # Excess can not exceed the charged fee (it is a SHARE of it).
        excess = min(excess, fee_charged)
        # gross alpha / hurdle / benchmark geometry is unknown on the override
        # path → report None; net alpha can not be derived without gross_alpha, so
        # net-alpha flags / ratio fall back to the fee-on-beta share alone.
        return self._finish(
            token=token,
            gross_apr_pct=gross,
            fee_frac=None,
            hurdle_apr_pct=None,
            benchmark_apr_pct=None,
            hurdle_gap_apr_pct=None,
            fee_charged_apr_pct=fee_charged,
            fair_fee_apr_pct=max(0.0, fee_charged - excess),
            excess_fee_apr_pct=excess,
            gross_alpha_apr_pct=None,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_apr_pct: float,
        fee_frac: Optional[float],
        hurdle_apr_pct: Optional[float],
        benchmark_apr_pct: Optional[float],
        hurdle_gap_apr_pct: Optional[float],
        fee_charged_apr_pct: float,
        fair_fee_apr_pct: float,
        excess_fee_apr_pct: float,
        gross_alpha_apr_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        net_apr_charged_pct = gross_apr_pct - fee_charged_apr_pct
        net_apr_fair_pct = gross_apr_pct - fair_fee_apr_pct
        # overstatement = the excess fee leaked onto beta (kept for family
        # consistency with the headline-honesty family).
        overstatement_pct = excess_fee_apr_pct

        # Net alpha: only computable when the gross alpha geometry is known.
        if gross_alpha_apr_pct is not None:
            net_alpha_apr_pct = gross_alpha_apr_pct - fee_charged_apr_pct
            net_alpha_is_negative = net_alpha_apr_pct < 0.0
            if gross_alpha_apr_pct > EPS:
                alpha_realization_ratio = _clamp(
                    net_alpha_apr_pct / gross_alpha_apr_pct, 0.0, 1.0)
            else:
                # No gross alpha: ratio is 1.0 if no fee charged, else 0.0.
                alpha_realization_ratio = (
                    1.0 if fee_charged_apr_pct <= 0.0 else 0.0)
        else:
            # Override path: gross alpha unknown. Treat net alpha via the
            # fee-on-beta share as the realisation proxy below; flag as not known.
            net_alpha_apr_pct = None
            net_alpha_is_negative = False
            alpha_realization_ratio = None

        # Scale-free fee-on-beta fraction — the share of the charged fee on beta.
        if fee_charged_apr_pct > EPS:
            fee_on_beta_fraction = _clamp(
                excess_fee_apr_pct / fee_charged_apr_pct, 0.0, 1.0)
        else:
            fee_on_beta_fraction = 0.0

        # On the override path, with no gross alpha geometry, anchor the alpha
        # realisation on (1 - fee_on_beta_fraction): the share of the fee that
        # fell on alpha is the share the depositor "kept paying for skill".
        if alpha_realization_ratio is None:
            alpha_realization_ratio = _clamp(
                1.0 - fee_on_beta_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_beta_fraction, net_alpha_is_negative)
        score = self._score(
            alpha_realization_ratio, fee_on_beta_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_alpha_is_negative,
            hurdle_apr_pct,
            benchmark_apr_pct,
            fee_charged_apr_pct,
            gross_alpha_apr_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_apr_pct": round(gross_apr_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "hurdle_apr_pct": (
                round(hurdle_apr_pct, 4)
                if hurdle_apr_pct is not None else None),
            "benchmark_apr_pct": (
                round(benchmark_apr_pct, 4)
                if benchmark_apr_pct is not None else None),
            "hurdle_gap_apr_pct": (
                round(hurdle_gap_apr_pct, 4)
                if hurdle_gap_apr_pct is not None else None),
            "fee_charged_apr_pct": round(fee_charged_apr_pct, 4),
            "fair_fee_apr_pct": round(fair_fee_apr_pct, 4),
            "excess_fee_apr_pct": round(excess_fee_apr_pct, 4),
            "net_apr_charged_pct": round(net_apr_charged_pct, 4),
            "net_apr_fair_pct": round(net_apr_fair_pct, 4),
            "overstatement_pct": round(overstatement_pct, 4),
            "gross_alpha_apr_pct": (
                round(gross_alpha_apr_pct, 4)
                if gross_alpha_apr_pct is not None else None),
            "net_alpha_apr_pct": (
                round(net_alpha_apr_pct, 4)
                if net_alpha_apr_pct is not None else None),
            "alpha_realization_ratio": round(alpha_realization_ratio, 4),
            "fee_on_beta_fraction": round(fee_on_beta_fraction, 4),
            "net_alpha_is_negative": net_alpha_is_negative,
            "sample_count": 0,
            "used_override": used_override,
            "used_main": used_main,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        alpha_realization_ratio: float,
        fee_on_beta_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the fee respects a benchmark hurdle: it falls on alpha and
        the depositor keeps the alpha the manager actually produced. Two
        components:
          * alpha realisation = clamp(alpha_realization_ratio, 0, 1) — the fraction
            of the gross alpha that survives the charged fee,
          * fee-base penalty = clamp(1 − fee_on_beta_fraction, 0, 1) — penalises a
            large share of the fee being charged on benchmark-level beta.
        Weighted 70/30 toward alpha realisation (it directly maps to the net alpha
        the depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(alpha_realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_beta_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_beta_fraction: float, net_alpha_is_negative: bool,
    ) -> str:
        if net_alpha_is_negative:
            # The fee has eaten the whole gross alpha (or more).
            return "SEVERE_BETA_TAX"
        if fee_on_beta_fraction <= CLEAN_FRACTION:
            return "CLEAN_HURDLE"
        if fee_on_beta_fraction <= MILD_FRACTION:
            return "MILD_BETA_TAX"
        if fee_on_beta_fraction <= MODERATE_FRACTION:
            return "MODERATE_BETA_TAX"
        return "SEVERE_BETA_TAX"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_NO_HURDLE_FEE"
        if classification == "CLEAN_HURDLE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_BETA_TAX":
            return "MINOR_HURDLE_GAP"
        if classification == "MODERATE_BETA_TAX":
            return "NEGOTIATE_HURDLE"
        # SEVERE_BETA_TAX
        return "AVOID_NO_HURDLE_FEE"

    def _flags(
        self,
        classification: str,
        net_alpha_is_negative: bool,
        hurdle_apr_pct: Optional[float],
        benchmark_apr_pct: Optional[float],
        fee_charged_apr_pct: float,
        gross_alpha_apr_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_HURDLE":
            flags.append("CLEAN_HURDLE_CONFIRMED")

        if net_alpha_is_negative:
            flags.append("NET_ALPHA_NEGATIVE_AFTER_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (hurdle_apr_pct is not None and hurdle_apr_pct == 0.0
                    and benchmark_apr_pct is not None
                    and benchmark_apr_pct > 0.0):
                flags.append("NO_HURDLE_APPLIED")
            if (gross_alpha_apr_pct is not None
                    and gross_alpha_apr_pct >= 0.0
                    and fee_charged_apr_pct > gross_alpha_apr_pct):
                flags.append("FEE_EXCEEDS_ALPHA")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_apr_pct": None,
            "performance_fee_pct": None,
            "hurdle_apr_pct": None,
            "benchmark_apr_pct": None,
            "hurdle_gap_apr_pct": None,
            "fee_charged_apr_pct": None,
            "fair_fee_apr_pct": None,
            "excess_fee_apr_pct": None,
            "net_apr_charged_pct": None,
            "net_apr_fair_pct": None,
            "overstatement_pct": None,
            "gross_alpha_apr_pct": None,
            "net_alpha_apr_pct": None,
            "alpha_realization_ratio": None,
            "fee_on_beta_fraction": None,
            "net_alpha_is_negative": False,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_NO_HURDLE_FEE",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_hurdle_vault": None,
                "worst_beta_tax_vault": None,
                "avg_score": 0.0,
                "net_alpha_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = hurdle ≈ benchmark → highest score is the cleanest hurdle.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_alpha_negative = sum(
            1 for r in results
            if "NET_ALPHA_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_hurdle_vault": by_score[-1]["token"],
            "worst_beta_tax_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_alpha_negative_count": net_alpha_negative,
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
            # CLEAN_HURDLE: the applied hurdle equals the benchmark → the fee
            # falls entirely on alpha, no beta tax.
            "vault": "USDC-Vault-CleanHurdle",
            "gross_apr_pct": 20.0,
            "performance_fee_pct": 20.0,
            "hurdle_apr_pct": 5.0,
            "benchmark_apr_pct": 5.0,
        },
        {
            # MODERATE_BETA_TAX: no hurdle, a high benchmark → a large share of the
            # fee is charged on benchmark-level beta (fee_on_beta ~ 0.5).
            "vault": "stETH-Vault-ModerateBetaTax",
            "gross_apr_pct": 16.0,
            "performance_fee_pct": 20.0,
            "hurdle_apr_pct": 0.0,
            "benchmark_apr_pct": 8.0,
        },
        {
            # SEVERE_BETA_TAX (net alpha negative): a thin alpha over the benchmark
            # with a no-hurdle fee on the whole gross → fee eats all the alpha.
            "vault": "GOV-Vault-SevereBetaTax",
            "gross_apr_pct": 12.0,
            "performance_fee_pct": 50.0,
            "hurdle_apr_pct": 0.0,
            "benchmark_apr_pct": 10.0,
        },
        {
            # Override path: a benchmark-relative excess fee supplied directly with
            # the charged fee → fee_on_beta = 5/12 ≈ 0.4167 → MODERATE_BETA_TAX.
            "vault": "LST-Vault-OverrideGap",
            "gross_apr_pct": 24.0,
            "excess_fee_apr_pct": 5.0,
            "fee_charged_apr_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross APR supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "hurdle_apr_pct": 0.0,
            "benchmark_apr_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1207 Vault Performance-Fee Hurdle-Rate Gap Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)

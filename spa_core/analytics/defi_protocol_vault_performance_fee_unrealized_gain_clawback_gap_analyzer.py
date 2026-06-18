"""
MP-1208: DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer
========================================================================
Advisory/read-only analytics module.

A vault crystallizes a PERFORMANCE fee on UNREALIZED (mark-to-market / paper)
PEAK gains, but provides NO CLAWBACK when those paper gains later reverse. The
depositor paid a fee on profit that subsequently evaporated, so the net realized
return is OVERSTATED by the fee that was charged on the un-recovered (reverted)
portion of the gain. The fee was levied on a mark that did not persist; without a
clawback provision, that fee is never refunded:

    fee_frac              = clamp(performance_fee_pct / 100, 0, 1)
    reverted_gain_pct     = max(0, peak_unrealized_gain_pct - realized_gain_pct)
    fee_paid_on_peak_pct  = fee_frac * max(0, peak_unrealized_gain_pct)
    fair_fee_pct          = fee_frac * max(0, realized_gain_pct)
    clawback_gap_pct      = max(0, fee_paid_on_peak_pct - fair_fee_pct)
                          (= fee charged on the vanished gains, never clawed back)
    net_realized_pct      = realized_gain_pct - fee_paid_on_peak_pct
    net_realized_fair_pct = realized_gain_pct - fair_fee_pct
    overstatement_pct     = clawback_gap_pct
    fee_on_reverted_fraction = clamp(clawback_gap_pct / fee_paid_on_peak_pct, 0, 1)
    realization_ratio     = clamp(net_realized_pct / net_realized_fair_pct, 0, 1)

The headline says "the manager earned this gain and we only skim the upside", but
the fee was crystallized on a PEAK mark that later reversed, so a chunk of it was
charged on paper profit that the depositor never actually realized. The scale-free
fee_on_reverted_fraction is the share of the charged fee that landed on vanished
gains; it is the basis of the classification. When the realized gain ≈ the peak
mark, the fee was effectively fair and no clawback is needed (HIGHER score). When
the gain fully reverses (or the net realized return goes negative after the fee),
the fee was charged almost entirely on gains that evaporated (LOWER score).

HIGHER score = gains persisted (realized ≈ peak), the fee was effectively fair, no
clawback needed. LOWER score = a large share of the fee was charged on reverted
paper gains, or the net realized return goes negative after the fee.

Override path (when clawback_gap_pct is supplied directly, finite, AND a valid
POSITIVE peak_unrealized_gain_pct and POSITIVE fee_paid_on_peak_pct are present):
take the gap verbatim (negative → magnitude) and skip the realized/reverted
geometry — fee_on_reverted_fraction and the metrics are computed the same way:

    fee_on_reverted_fraction = clamp(clawback_gap_pct / fee_paid_on_peak_pct, 0, 1)

(On the override path the realized / reverted / fair geometry is not known → those
fields are reported as None, and the geometry-only flags FEE_ON_VANISHED_GAINS /
FULL_REVERSAL / NET_NEGATIVE_AFTER_FEE are NOT raised; realization_ratio is
anchored to (1 - fee_on_reverted_fraction).)

Distinct from:
  * defi_protocol_performance_fee_high_water_mark_analyzer — that prices the
    mechanics of the HWM RESET: whether the fee waits for the prior peak to be
    recovered before crystallising. HERE it is a fee already crystallised on an
    UNREALIZED peak mark that then REVERSED, with NO clawback — an ORTHOGONAL axis.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a high-water-mark performance fee over a VOLATILE gross path
    (fee taken on up-legs, not refunded on down-legs). HERE it is a SINGLE
    first-moment peak-vs-realized gap: fee on the un-recovered portion of one
    crystallised mark, no path / no volatility series.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that prices
    how OFTEN the fee crystallises. HERE it is what HAPPENED to the gain the fee
    was crystallised on: it reverted and was never clawed back, regardless of
    frequency.
  * defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer — that prices the
    fee charged on BETA (benchmark-level beta over a too-low hurdle) vs ALPHA.
    HERE it is the fee charged on a PEAK paper gain that REVERSED, independent of
    any hurdle / benchmark.
  * protocol_real_yield_vs_paper_yield_analyzer — that compares REAL fee/interest
    yield against token-PRICE paper yield. HERE the novel axis is a performance
    FEE charged on UNREALIZED peak gains that later REVERSED, with NO clawback —
    NOT a comparison of real vs paper yield sources.

The novel axis here: fee charged on UNREALIZED peak gains that later REVERSED,
with NO clawback.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_performance_fee_unrealized_gain_clawback_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_reverted_fraction in [0, 1]
# (= clawback_gap_pct / fee_paid_on_peak_pct).
CLEAN_FRACTION = 0.05        # at/below → clean persistent gain (no clawback need)
MILD_FRACTION = 0.20         # at/below → mild clawback gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe clawback gap

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


def _coerce_signed(val) -> Optional[float]:
    """
    Coerce a value to a finite SIGNED float (may be negative), or None if it is
    not interpretable. Identical to _coerce_num; kept as a named alias for the
    realized-gain field, which may legitimately be negative.
    """
    return _coerce_num(val)


def _coerce_count(val) -> Optional[int]:
    """
    Coerce a value to a non-negative integer count, or None if not interpretable.
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return None
    iv = int(cv)
    return iv if iv >= 0 else None


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

class DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer:
    """
    Measures the gap between the performance fee a vault crystallized on an
    UNREALIZED PEAK gain and the FAIR fee it would have charged on the gain that
    actually persisted/realized, and the share of the charged fee that therefore
    landed on REVERTED (vanished) paper gains with NO clawback.

        fee_frac                 = clamp(performance_fee_pct / 100, 0, 1)
        reverted_gain_pct        = max(0, peak_unrealized_gain - realized_gain)
        fee_paid_on_peak_pct     = fee_frac * max(0, peak_unrealized_gain)
        fair_fee_pct             = fee_frac * max(0, realized_gain)
        clawback_gap_pct         = max(0, fee_paid_on_peak - fair_fee)
        net_realized_pct         = realized_gain - fee_paid_on_peak
        net_realized_fair_pct    = realized_gain - fair_fee
        overstatement_pct        = clawback_gap_pct
        fee_on_reverted_fraction = clamp(clawback_gap / fee_paid_on_peak, 0, 1)
        realization_ratio        = clamp(net_realized / net_realized_fair, 0, 1)

    The fee is charged on the peak unrealized mark; the fair fee would be charged
    only on the gain that persisted. When the realized gain equals (or exceeds) the
    peak, the fee falls entirely on persistent gain (CLEAN_PERSISTENT_GAIN). When
    the gain reverts and there is no clawback, a large share of the fee was charged
    on vanished gains (MODERATE / SEVERE clawback gap), and if the fee exceeds the
    realized gain the net realized return goes negative.

    HIGHER score = gains persisted (realized ≈ peak), the fee was effectively fair,
    no clawback needed. LOWER score = a large share of the fee was charged on
    reverted paper gains, or the net realized return goes negative after the fee.

    Per-position input dict fields:
        vault / token            : str
        peak_unrealized_gain_pct : float — the mark-to-market peak gain on which
                                   the fee was crystallized. REQUIRED, must be a
                                   finite POSITIVE number (else INSUFFICIENT_DATA).
        realized_gain_pct        : float — the gain that actually persisted /
                                   realized (finite; may be < peak; may be
                                   negative; default 0.0 = full reversal).
        performance_fee_pct      : float — performance-fee rate % (REQUIRED finite,
                                   clamped into 0..100; non-finite →
                                   INSUFFICIENT_DATA on the main path).
        crystallizations         : int — OPTIONAL informational count of fee
                                   crystallisations.
        clawback_gap_pct         : float — OPTIONAL direct override of the
                                   benchmark-relative clawback gap (the fee charged
                                   on vanished gains). When supplied (finite;
                                   negative → magnitude) AND a valid POSITIVE
                                   peak_unrealized_gain_pct and POSITIVE
                                   fee_paid_on_peak_pct are present, take this gap
                                   directly and skip the realized / reverted
                                   geometry (override path; geometry → None).
        fee_paid_on_peak_pct     : float — OPTIONAL, only used on the override path
                                   as the denominator for fee_on_reverted_fraction
                                   (finite > 0 required to take the override path).
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

        # The peak unrealized gain is required and must be finite & positive.
        peak = _coerce_num(p.get("peak_unrealized_gain_pct"))
        if peak is None or not math.isfinite(peak) or peak <= 0.0:
            return self._insufficient(token)

        crystallizations = _coerce_count(p.get("crystallizations"))

        # Override path: a direct clawback gap + a positive fee_paid_on_peak.
        gap_o = _coerce_num(p.get("clawback_gap_pct"))
        fee_paid_o = _coerce_num(p.get("fee_paid_on_peak_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_paid_o is not None and math.isfinite(fee_paid_o)
                and fee_paid_o > 0.0):
            return self._analyze_override(
                token, peak, abs(gap_o), fee_paid_o, crystallizations)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, p, peak, fee_pct, crystallizations)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, peak: float, fee_pct: float,
        crystallizations: Optional[int],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # realized gain may legitimately be negative (full reversal / loss).
        realized = _coerce_signed(p.get("realized_gain_pct"))
        if realized is None or not math.isfinite(realized):
            realized = 0.0

        reverted_gain_pct = max(0.0, peak - realized)
        fee_paid_on_peak_pct = fee_frac * max(0.0, peak)
        fair_fee_pct = fee_frac * max(0.0, realized)
        clawback_gap_pct = max(0.0, fee_paid_on_peak_pct - fair_fee_pct)

        return self._finish(
            token=token,
            peak_unrealized_gain_pct=peak,
            fee_frac=fee_frac,
            realized_gain_pct=realized,
            reverted_gain_pct=reverted_gain_pct,
            fee_paid_on_peak_pct=fee_paid_on_peak_pct,
            fair_fee_pct=fair_fee_pct,
            clawback_gap_pct=clawback_gap_pct,
            crystallizations=crystallizations,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, peak: float, gap: float, fee_paid: float,
        crystallizations: Optional[int],
    ) -> dict:
        # The gap can not exceed the fee paid (it is a SHARE of it).
        gap = min(gap, fee_paid)
        # realized / reverted / fair geometry is unknown on the override path →
        # report None; net realized can not be derived without realized_gain, so
        # net-negative / reversal flags / ratio fall back to the gap share alone.
        return self._finish(
            token=token,
            peak_unrealized_gain_pct=peak,
            fee_frac=None,
            realized_gain_pct=None,
            reverted_gain_pct=None,
            fee_paid_on_peak_pct=fee_paid,
            fair_fee_pct=max(0.0, fee_paid - gap),
            clawback_gap_pct=gap,
            crystallizations=crystallizations,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        peak_unrealized_gain_pct: float,
        fee_frac: Optional[float],
        realized_gain_pct: Optional[float],
        reverted_gain_pct: Optional[float],
        fee_paid_on_peak_pct: float,
        fair_fee_pct: float,
        clawback_gap_pct: float,
        crystallizations: Optional[int],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the fee charged on vanished gains (kept for family
        # consistency with the headline-honesty family).
        overstatement_pct = clawback_gap_pct

        # Net realized: only computable when realized geometry is known.
        if realized_gain_pct is not None:
            net_realized_pct = realized_gain_pct - fee_paid_on_peak_pct
            net_realized_fair_pct = realized_gain_pct - fair_fee_pct
            net_is_negative = net_realized_pct < 0.0
            if net_realized_fair_pct > EPS:
                realization_ratio = _clamp(
                    net_realized_pct / net_realized_fair_pct, 0.0, 1.0)
            else:
                # Mirror the hurdle template's gross_alpha==0 edge: when the fair
                # net is non-positive, the ratio is 1.0 only if the charged net
                # still clears the fair net and is itself non-negative, else 0.0.
                realization_ratio = (
                    1.0 if (net_realized_pct >= net_realized_fair_pct
                            and net_realized_pct >= 0.0) else 0.0)
        else:
            # Override path: realized geometry unknown. Treat realization via the
            # fee-on-reverted share as the proxy below; flag as not known.
            net_realized_pct = None
            net_realized_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-reverted fraction — the share of the charged fee that
        # landed on vanished gains.
        if fee_paid_on_peak_pct > EPS:
            fee_on_reverted_fraction = _clamp(
                clawback_gap_pct / fee_paid_on_peak_pct, 0.0, 1.0)
        else:
            fee_on_reverted_fraction = 0.0

        # On the override path, with no realized geometry, anchor the realisation
        # on (1 - fee_on_reverted_fraction): the share of the fee that fell on the
        # persistent gain is the share the depositor "paid fairly".
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_reverted_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_reverted_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_reverted_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            realized_gain_pct,
            reverted_gain_pct,
            peak_unrealized_gain_pct,
            crystallizations,
            used_override,
        )

        return {
            "token": token,
            "peak_unrealized_gain_pct": round(peak_unrealized_gain_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "realized_gain_pct": (
                round(realized_gain_pct, 4)
                if realized_gain_pct is not None else None),
            "reverted_gain_pct": (
                round(reverted_gain_pct, 4)
                if reverted_gain_pct is not None else None),
            "fee_paid_on_peak_pct": round(fee_paid_on_peak_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "clawback_gap_pct": round(clawback_gap_pct, 4),
            "net_realized_pct": (
                round(net_realized_pct, 4)
                if net_realized_pct is not None else None),
            "net_realized_fair_pct": (
                round(net_realized_fair_pct, 4)
                if net_realized_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_reverted_fraction": round(fee_on_reverted_fraction, 4),
            "net_is_negative": net_is_negative,
            "crystallizations": crystallizations,
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
        realization_ratio: float,
        fee_on_reverted_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the fee was charged on gains that persisted: the depositor
        keeps the net realized return the gain actually produced. Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the fair
            net realized return that survives the peak-mark fee,
          * fee-base penalty = clamp(1 − fee_on_reverted_fraction, 0, 1) —
            penalises a large share of the fee being charged on reverted gains.
        Weighted 70/30 toward realisation (it directly maps to the net realized
        return the depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_reverted_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_reverted_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole realized gain (or more).
            return "SEVERE_CLAWBACK_GAP"
        if fee_on_reverted_fraction <= CLEAN_FRACTION:
            return "CLEAN_PERSISTENT_GAIN"
        if fee_on_reverted_fraction <= MILD_FRACTION:
            return "MILD_CLAWBACK_GAP"
        if fee_on_reverted_fraction <= MODERATE_FRACTION:
            return "MODERATE_CLAWBACK_GAP"
        return "SEVERE_CLAWBACK_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_NO_CLAWBACK"
        if classification == "CLEAN_PERSISTENT_GAIN":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_CLAWBACK_GAP":
            return "MINOR_CLAWBACK_GAP"
        if classification == "MODERATE_CLAWBACK_GAP":
            return "DEMAND_CLAWBACK_PROVISION"
        # SEVERE_CLAWBACK_GAP
        return "AVOID_NO_CLAWBACK"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        realized_gain_pct: Optional[float],
        reverted_gain_pct: Optional[float],
        peak_unrealized_gain_pct: float,
        crystallizations: Optional[int],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_PERSISTENT_GAIN":
            flags.append("CLEAN_NO_REVERSAL")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if crystallizations is not None and crystallizations >= 2:
            flags.append("MULTIPLE_CRYSTALLIZATIONS")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if reverted_gain_pct is not None and reverted_gain_pct > 0.0:
                flags.append("FEE_ON_VANISHED_GAINS")
            if (realized_gain_pct is not None
                    and realized_gain_pct <= 0.0
                    and peak_unrealized_gain_pct > 0.0):
                flags.append("FULL_REVERSAL")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "peak_unrealized_gain_pct": None,
            "performance_fee_pct": None,
            "realized_gain_pct": None,
            "reverted_gain_pct": None,
            "fee_paid_on_peak_pct": None,
            "fair_fee_pct": None,
            "clawback_gap_pct": None,
            "net_realized_pct": None,
            "net_realized_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_reverted_fraction": None,
            "net_is_negative": False,
            "crystallizations": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_NO_CLAWBACK",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_vault": None,
                "worst_clawback_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = gains persisted → highest score is the cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_clawback_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_negative_count": net_negative,
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
            # CLEAN_PERSISTENT_GAIN: realized ≈ peak → fee was effectively fair,
            # no clawback needed.
            "vault": "USDC-Vault-CleanPersistent",
            "peak_unrealized_gain_pct": 20.0,
            "realized_gain_pct": 20.0,
            "performance_fee_pct": 20.0,
            "crystallizations": 1,
        },
        {
            # MODERATE_CLAWBACK_GAP: gain reverted from 16 to 8 → ~half the fee was
            # charged on vanished gains (fee_on_reverted ~ 0.5).
            "vault": "stETH-Vault-ModerateClawback",
            "peak_unrealized_gain_pct": 16.0,
            "realized_gain_pct": 8.0,
            "performance_fee_pct": 20.0,
            "crystallizations": 2,
        },
        {
            # SEVERE_CLAWBACK_GAP (net negative): a big fee on a peak that fully
            # reverses → the fee eats more than the realized gain.
            "vault": "GOV-Vault-SevereClawback",
            "peak_unrealized_gain_pct": 12.0,
            "realized_gain_pct": 1.0,
            "performance_fee_pct": 50.0,
            "crystallizations": 3,
        },
        {
            # Override path: a clawback gap supplied directly with the fee paid on
            # peak → fee_on_reverted = 5/12 ≈ 0.4167 → MODERATE_CLAWBACK_GAP.
            "vault": "LST-Vault-OverrideGap",
            "peak_unrealized_gain_pct": 24.0,
            "clawback_gap_pct": 5.0,
            "fee_paid_on_peak_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no peak unrealized gain supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "realized_gain_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1208 Vault Performance-Fee Unrealized-Gain "
            "Clawback-Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
